"""Single-host task coordination over canonical files and exact-path Git commits.

Actor identity comes from issued credentials: an owner token returned once by enroll, and
run tokens returned once by claim (review runs included). Typed actor labels must match the
credential presented. Credentials coordinate a trusted local operator; they are not an OS
security boundary. Raymond's explicit decisions are recorded as human authority.
Provider launch and live trials are outside this module: unsupported adapters leave
durable messages queued.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import datetime as dt
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid

VERSION = 1
_TASK_INDEX = {}  # root -> (stamp, tasks, corrupt tasks, record paths): per-process enrolled-task index
KINDS = {"assignment", "question", "correction", "submission", "finding", "handoff", "status"}


class AgentError(RuntimeError):
    """An inspectable rejected operation, rather than a partial success."""


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def ident(prefix):
    return prefix + "-" + uuid.uuid4().hex


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def file_hash(path):
    return digest(path.read_bytes()) if path.is_file() else None


class HumanUnavailable(AgentError):
    """No way to reach a present human (no GUI dialog): refuse, never accept typed text."""


OSASCRIPT = "/usr/bin/osascript"
# Fixed locations, not TMPDIR: an agent must not be able to make a real workspace look temporary.
_TEST_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")


def _test_hook(root):
    hook = os.getenv("CTX_HUMAN_CONFIRM_HOOK")
    if not hook or not os.getenv("CTX_TEST_HUMAN_CONFIRM") or root is None:
        return None
    real = os.path.realpath(str(root))
    return hook if any(real == base or real.startswith(base + "/") for base in _TEST_ROOTS) else None


def human_authority(statement, action="decision", task="", root=None):
    """Raymond's explicit decision, confirmed by a person in a native dialog, recorded verbatim.

    Typed text alone never grants: the dialog shows the exact action, task and reason and only
    "Approve" grants. A test stub replaces the dialog only when CTX_TEST_HUMAN_CONFIRM is set and
    the workspace is a temporary fixture.
    """
    text = " ".join(str(statement or "").split())
    if not re.match(r"(?i)^raymond:\s*\S", text):
        raise AgentError('human authority must read "raymond: <reason>"')
    if os.getenv("CTX_RUN_TOKEN"):
        raise AgentError("human authority cannot be asserted from inside a leased run environment")
    prompt = f"ctx system {action}\ntask: {task}\nreason: {text}\n\nApprove only if you, Raymond, asked for this."
    hook = _test_hook(root)
    if hook:
        method, result = "test-hook", subprocess.run([hook, action, str(task), text], capture_output=True, text=True)
        approved = result.returncode == 0 and result.stdout.strip() == "Approve"
    else:
        if sys.platform != "darwin" or not os.path.isfile(OSASCRIPT):
            raise HumanUnavailable("human approval needs the macOS confirmation dialog, which is unavailable here; "
                                   "typed --human is never enough")
        script = ['on run argv', 'display dialog (item 1 of argv) with title "ctx: human approval" '
                  'buttons {"Deny", "Approve"} default button "Deny" giving up after 120', 'end run']
        try:
            result = subprocess.run([OSASCRIPT] + [a for line in script for a in ("-e", line)] + [prompt],
                                    capture_output=True, text=True, timeout=150)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HumanUnavailable("macOS confirmation dialog could not be shown: " + str(exc)) from exc
        if result.returncode:
            raise HumanUnavailable("macOS confirmation dialog could not be shown: " + result.stderr.strip())
        method = "macos-dialog"
        approved = "button returned:Approve" in result.stdout and "gave up:true" not in result.stdout
    if not approved:
        raise AgentError("human approval not given in the confirmation dialog; nothing changed")
    return {"kind": "human", "statement": text, "method": method, "action": action, "confirmed_at": utc()}


TASK_FIELDS = {"schema_version", "task_id", "owner", "goal", "criteria", "allowed_paths", "dependencies",
               "state", "requirement_rev", "sequence", "budget"}


def journal_problem(record):
    """None when a core operation journal has the shape recovery needs, else the reason."""
    if not isinstance(record, dict):
        return "not a JSON object"
    if not isinstance(record.get("operation_id"), str) or not isinstance(record.get("phase"), str):
        return "missing operation_id or phase"
    if record["phase"] in ("committed", "abandoned"):
        return None
    files = record.get("files")
    if not isinstance(files, dict) or not files:
        return "missing files"
    for rel, item in files.items():
        if not isinstance(item, dict) or not {"before_hash", "before", "after_hash", "after", "mode"} <= set(item):
            return "malformed file entry: " + str(rel)
    if not isinstance(record.get("payload_hash"), str) or not isinstance(record.get("applied", []), list):
        return "missing payload_hash or applied list"
    return None


def legacy_problem(record):
    """None when a legacy ctx journal has the shape recover_legacy needs, else the reason."""
    if not isinstance(record, dict) or not isinstance(record.get("operation_id"), str):
        return "not a legacy journal object"
    if not isinstance(record.get("writes", []), list) or not isinstance(record.get("moves", []), list):
        return "malformed writes or moves"
    if any(not isinstance(w, dict) or not isinstance(w.get("path"), str) or not {"before", "after"} <= set(w)
           for w in record.get("writes", [])):
        return "malformed write entry"
    if any(not isinstance(m, dict) or not {"source", "target", "hashes"} <= set(m) for m in record.get("moves", [])):
        return "malformed move entry"
    return None


def task_problem(record):
    if not isinstance(record, dict):
        return "not a JSON object"
    missing = TASK_FIELDS - set(record)
    return "missing fields: " + ", ".join(sorted(missing)) if missing else None


def atomic(path, data, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".ctx-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(name, mode)
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)  # only this operation's disposable staging file


def case_insensitive(directory):
    """Detect, never assume, whether this filesystem folds name case (macOS APFS default)."""
    directory = Path(directory)
    name = directory.name
    if name != name.swapcase():
        try:
            return os.path.samefile(directory, directory.with_name(name.swapcase()))
        except OSError:
            return False
    try:
        fd, probe = tempfile.mkstemp(prefix=".ctx-case-probe-", dir=directory)
    except OSError:
        return False
    os.close(fd)
    try:
        other = os.path.join(os.path.dirname(probe), os.path.basename(probe).swapcase())
        return os.path.exists(other) and os.path.samefile(probe, other)
    finally:
        os.unlink(probe)  # only this call's disposable probe


class Store:
    def __init__(self, root, commit=True):
        self.root = Path(root).resolve()
        self.commit = commit
        self.case_insensitive = case_insensitive(self.root)
        self.corrupt_tasks = []
        self.state = self.root / "systems/agent-state"
        self._local = threading.local()
        common = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--git-common-dir"],
                                capture_output=True, text=True)
        if common.returncode == 0:
            directory = Path(common.stdout.strip())
            directory = directory if directory.is_absolute() else self.root / directory
            self.lock_path = directory.resolve() / "ctx.lock"
        else:
            self.lock_path = self.root / "systems/state/ctx.lock"
        self.check_lock_path = self.lock_path.with_name("ctx-check.lock")

    def path(self, relative):
        candidate = Path(relative)
        candidate = candidate if candidate.is_absolute() else self.root / candidate
        candidate = candidate.resolve()
        try:
            part = candidate.relative_to(self.root)
        except ValueError:
            raise AgentError("path escapes workspace")
        if self.case_insensitive:
            part = self._spelling(part)
            candidate = self.root.joinpath(*part.parts)
        if not part.parts or ".git" in {p.casefold() for p in part.parts}:
            raise AgentError("workspace root and git internals are not mutation targets")
        return candidate

    def _spelling(self, part):
        """The on-disk spelling of each existing component; a missing tail keeps its spelling."""
        current, names = self.root, []
        for i, name in enumerate(part.parts):
            try:
                entries = os.listdir(current)
            except OSError:
                return Path(*names, *part.parts[i:])
            if name not in entries:
                matches = [e for e in entries if e.casefold() == name.casefold()]
                if len(matches) != 1:
                    return Path(*names, *part.parts[i:])
                name = matches[0]
            names.append(name)
            current = current / name
        return Path(*names)

    def relative(self, path):
        return str(self.path(path).relative_to(self.root))

    def read(self, relative, default=None):
        path = self.path(relative)
        if not path.exists():
            return copy.deepcopy(default)
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise AgentError(f"invalid canonical JSON at {path}: {exc}") from exc

    @contextlib.contextmanager
    def locked(self, shared=False):
        """Exclusive for writers; shared holds let readers (boot) in while every writer waits."""
        depth = getattr(self._local, "depth", 0)
        if depth:
            if not shared and getattr(self._local, "shared", False):
                raise AgentError("exclusive coordinator lock requested inside a shared hold")
            self._local.depth += 1
            try:
                yield
            finally:
                self._local.depth -= 1
            return
        self.state.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            self._local.depth, self._local.shared = 1, shared
            try:
                yield
            finally:
                self._local.depth, self._local.shared = 0, False
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _git(self, *args, env=None, check=True):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                text=True, env=env)
        if check and result.returncode:
            raise AgentError("git operation failed: " + result.stderr.strip())
        return result

    def _commit(self, paths, action, operation_id, contents=None):
        if not self.commit:
            return None
        base = self._git("rev-parse", "HEAD").stdout.strip()
        # update-ref may have succeeded before the final journal fsync. Locate the
        # operation's original commit even when unrelated commits followed the crash.
        prior = self._git("log", "-1", "--format=%H", "--extended-regexp", "--grep",
                          "^Operation: " + operation_id + "$").stdout.strip()
        if prior:
            for path in paths:
                blob = subprocess.run(["git", "-C", str(self.root), "show", prior + ":" + path],
                                      capture_output=True)
                if blob.returncode or digest(blob.stdout) != file_hash(self.path(path)):
                    raise AgentError("operation commit receipt does not match recovered artifact: " + path)
            self._git("reset", "-q", "HEAD", "--", *[":(literal)" + p for p in paths])
            return prior
        fd, index = tempfile.mkstemp(prefix="ctx-index-")
        os.close(fd)
        os.unlink(index)
        env = dict(os.environ, GIT_INDEX_FILE=index, GIT_AUTHOR_NAME="Raymond Chu",
                   GIT_AUTHOR_EMAIL="", GIT_COMMITTER_NAME="Raymond Chu", GIT_COMMITTER_EMAIL="")
        try:
            self._git("read-tree", base, env=env)
            literal = [":(literal)" + p for p in paths]
            if contents is None:
                self._git("add", "--", *literal, env=env)
            else:
                # Commit journaled bytes, never an unrelated edit that raced git add.
                for path, item in contents.items():
                    blob = subprocess.run(["git", "-C", str(self.root), "hash-object", "-w", "--stdin"],
                                          input=base64.b64decode(item["after"]), capture_output=True, env=env)
                    if blob.returncode:
                        raise AgentError("git object write failed: " + blob.stderr.decode(errors="replace"))
                    mode = "100755" if item["mode"] & 0o111 else "100644"
                    self._git("update-index", "--add", "--cacheinfo", mode,
                              blob.stdout.decode().strip(), path, env=env)
            tree = self._git("write-tree", env=env).stdout.strip()
            oldtree = self._git("rev-parse", base + "^{tree}").stdout.strip()
            if tree == oldtree:
                self._git("reset", "-q", base, "--", *literal)
                return base
            message = f"ctx {action}\n\nOperation: {operation_id}\n"
            result = subprocess.run(["git", "-C", str(self.root), "commit-tree", tree, "-p", base],
                                    input=message, capture_output=True, text=True, env=env)
            if result.returncode:
                raise AgentError("git commit failed: " + result.stderr.strip())
            commit = result.stdout.strip()
            self._git("update-ref", "HEAD", commit, base)
            # Reset only paths in this transaction, preserving all unrelated staging.
            self._git("reset", "-q", commit, "--", *literal)
            return commit
        finally:
            for item in (index, index + ".lock"):
                if os.path.exists(item):
                    os.unlink(item)

    def transaction(self, action, writes, expected=None, operation_id=None):
        """Journal and roll forward a bounded operation; never overwrite a later edit.

        expected maps root-relative paths to SHA256 or None for absent files. Reusing an
        operation id with identical payload is idempotent; a different payload is rejected.
        """
        if not writes:
            raise AgentError("transaction must own at least one file")
        operation_id = operation_id or ident("op")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", operation_id):
            raise AgentError("invalid operation id")
        normalized = {self.relative(p): encoded(v) for p, v in writes.items()}
        if len(normalized) != len(writes):
            raise AgentError("duplicate canonical target")
        wanted = {self.relative(p): v for p, v in (expected or {}).items()}
        payload = digest(encoded({"action": action, "writes": {p: digest(b) for p, b in normalized.items()},
                                  "expected": wanted}))
        journal_path = self.state / "operations" / (operation_id + ".json")
        with self.locked():
            prior = self.read(journal_path)
            if prior:
                if journal_problem(prior):
                    raise AgentError("operation journal is corrupt (" + journal_problem(prior) +
                                     "): ctx system recover --quarantine " + self.relative(journal_path))
                if prior.get("payload_hash") != payload:
                    raise AgentError("operation id already names a different payload")
                if prior["phase"] in ("committed", "abandoned"):
                    return prior
            reports = self._recover_locked() + self._legacy_recovery()
            blocking = [r for r in reports if r["phase"] in ("conflict", "corrupt")]
            unknown = [r for r in blocking if "*" in r.get("paths", r.get("conflicts", []))]
            if unknown:
                raise AgentError("corrupt recovery record with unknown paths blocks all writes; inspect it, then "
                                 "the way out is: " + "; ".join(r.get("repair") or "ctx system recover --quarantine " +
                                                                r.get("record", r["operation_id"]) for r in unknown))
            conflicts = {p for report in blocking for p in report.get("paths", report.get("conflicts", []))}
            if any(self.path(p) == self.path(c) or self.path(c) in self.path(p).parents or
                   self.path(p) in self.path(c).parents for p in normalized for c in conflicts):
                raise AgentError("unresolved recovery conflict on requested target")
            if prior:
                return self.read(journal_path)
            for p, h in wanted.items():
                if file_hash(self.path(p)) != h:
                    raise AgentError("stale base hash for " + p)
            files = {}
            for p, data in normalized.items():
                target = self.path(p)
                if target.exists() and not target.is_file():
                    raise AgentError("target must be a regular file")
                before = target.read_bytes() if target.exists() else None
                files[p] = {"before_hash": digest(before) if before is not None else None,
                            "before": base64.b64encode(before).decode() if before is not None else None,
                            "after_hash": digest(data), "after": base64.b64encode(data).decode(),
                            "mode": target.stat().st_mode & 0o777 if target.exists() else 0o644}
            record = {"schema_version": VERSION, "operation_id": operation_id, "action": action,
                      "created_at": utc(), "phase": "prepared", "payload_hash": payload,
                      "actor": os.getenv("CTX_ACTOR", "local"), "files": files, "applied": [],
                      "commit_enabled": self.commit}
            atomic(journal_path, encoded(record))
            # Leave an incomplete journal on any error, ready for restart reconciliation.
            try:
                return self._finish(record, journal_path)
            finally:
                if any(Path(p).name == "task.json" for p in normalized):
                    self._bump_index()

    def _finish(self, record, path):
        for rel, item in record["files"].items():
            target = self.path(rel)
            observed = file_hash(target)
            if observed not in (item["before_hash"], item["after_hash"]):
                record.update(phase="conflict", conflicts=[rel], updated_at=utc())
                atomic(path, encoded(record))
                raise AgentError("recovery would overwrite a later edit: " + rel)
        for rel, item in record["files"].items():
            # Recheck immediately before every replacement: another non-cooperating editor
            # may change the next target while an earlier replacement is being persisted.
            if file_hash(self.path(rel)) not in (item["before_hash"], item["after_hash"]):
                record.update(phase="conflict", conflicts=[rel], updated_at=utc())
                atomic(path, encoded(record))
                raise AgentError("recovery would overwrite a later edit: " + rel)
            atomic(self.path(rel), base64.b64decode(item["after"]), item["mode"])
            if rel not in record["applied"]:
                record["applied"].append(rel)
            record["phase"] = "applying"
            atomic(path, encoded(record))
        record["phase"] = "applied"
        atomic(path, encoded(record))
        bad = [rel for rel, item in record["files"].items() if file_hash(self.path(rel)) != item["after_hash"]]
        if bad:
            record.update(phase="conflict", conflicts=bad, updated_at=utc())
            atomic(path, encoded(record))
            raise AgentError("later edit before commit preserved: " + ", ".join(bad))
        original = self.commit
        try:
            self.commit = record.get("commit_enabled", original)
            record["commit"] = self._commit(list(record["files"]), record["action"], record["operation_id"], record["files"])
        finally:
            self.commit = original
        bad = [rel for rel, item in record["files"].items() if file_hash(self.path(rel)) != item["after_hash"]]
        if bad:
            record.update(phase="conflict", conflicts=bad, updated_at=utc())
            atomic(path, encoded(record))
            raise AgentError("later edit during commit preserved: " + ", ".join(bad))
        record.update(phase="committed", finished_at=utc())
        atomic(path, encoded(record))
        return record

    def _corrupt(self, path, record, reason):
        """A named recovery conflict for an unusable record, scoped to the paths it names if any."""
        files = record.get("files") if isinstance(record, dict) else None
        paths = sorted(files) if isinstance(files, dict) and files else ["*"]
        try:
            paths = paths if paths == ["*"] else [self.relative(p) for p in paths]
        except (AgentError, OSError, ValueError, TypeError):
            paths = ["*"]
        try:
            shown = str(path.relative_to(self.root))
        except ValueError:
            shown = str(path)
        return {"operation_id": path.stem, "phase": "corrupt", "record": shown, "reason": reason,
                "paths": paths, "repair": "ctx system recover --quarantine " + shown}

    def _receipt(self, record):
        """The operation's own commit when update-ref landed before the journal said so."""
        if not record.get("commit_enabled"):
            return None
        found = self._git("log", "-1", "--format=%H", "--extended-regexp", "--grep",
                          "^Operation: " + record["operation_id"] + "$", check=False).stdout.strip()
        if not found:
            return None
        for rel, item in record["files"].items():
            blob = subprocess.run(["git", "-C", str(self.root), "show", found + ":" + rel], capture_output=True)
            if blob.returncode or digest(blob.stdout) != item["after_hash"]:
                return None
            # Repair only a stale pre-commit index entry left by the crash, never newer staging.
            staged = subprocess.run(["git", "-C", str(self.root), "show", ":" + rel], capture_output=True)
            if staged.returncode == 0 and digest(staged.stdout) == item["before_hash"] != item["after_hash"]:
                self._git("reset", "-q", found, "--", ":(literal)" + rel, check=False)
        return found

    def _recover_locked(self):
        reports = []
        folder = self.state / "operations"
        for path in sorted(folder.glob("*.json")):
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                reports.append(self._corrupt(path, None, "unreadable JSON: " + str(exc)))
                continue
            problem = journal_problem(record)
            if problem:
                reports.append(self._corrupt(path, record, problem))
                continue
            if record["phase"] in ("committed", "abandoned"):
                continue
            receipt = self._receipt(record)
            if receipt:
                # Committed before the crash: a later human edit is not this operation's conflict.
                later = [p for p, item in record["files"].items() if file_hash(self.path(p)) != item["after_hash"]]
                record.update(phase="committed", commit=receipt, finished_at=utc(), recovered_from_receipt=True,
                              later_edits_preserved=later)
                record.pop("conflicts", None)
                atomic(path, encoded(record))
                reports.append({"operation_id": record["operation_id"], "phase": "committed",
                                "paths": list(record["files"]), "conflicts": [], "commit": receipt,
                                "later_edits_preserved": later})
                continue
            bad = [p for p, item in record["files"].items()
                   if file_hash(self.path(p)) not in (item["before_hash"], item["after_hash"])]
            if bad:
                record.update(phase="conflict", conflicts=bad, updated_at=utc())
                atomic(path, encoded(record))
            else:
                record = self._finish(record, path)
            reports.append({"operation_id": record["operation_id"], "phase": record["phase"],
                            "paths": list(record["files"]), "conflicts": record.get("conflicts", [])})
        return reports

    def _legacy_recovery(self):
        for name in ("ctx", "__main__", "_ctx_agent_recovery"):
            module = sys.modules.get(name)
            legacy = getattr(module, "recover_legacy", None) if module else None
            if legacy:
                return legacy(str(self.root))
        source = Path(__file__).with_name("ctx")
        if not source.is_file():
            return []
        loader = importlib.machinery.SourceFileLoader("_ctx_agent_recovery", str(source))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        sys.modules[loader.name] = module
        helper = getattr(module, "recover_legacy", None)
        return helper(str(self.root)) if helper else []

    def recover(self):
        with self.locked():
            return self._recover_locked() + self._legacy_recovery()

    def _legacy_dir(self):
        found = self._git("rev-parse", "--git-dir", check=False).stdout.strip()
        if not found:
            return self.root / "systems/state/ctx-operations"
        found = Path(found)
        return (found if found.is_absolute() else self.root / found).resolve() / "ctx-operations"

    def _located_record(self, record):
        """(path, kind) for a recovery-relevant record: core journal, legacy journal or systems record."""
        raw = Path(record)
        raw = raw if raw.is_absolute() else self.root / raw
        absolute = Path(os.path.abspath(raw))
        if absolute.is_symlink() or not absolute.is_file():
            raise AgentError("quarantine takes an existing regular record file")
        legacy = self._legacy_dir()
        if absolute.parent.resolve() == legacy and absolute.suffix == ".json":
            return absolute.resolve(), "legacy"
        path = self.path(absolute)
        if path.parent == self.state / "operations" and path.suffix == ".json":
            return path, "journal"
        if path.suffix == ".json" and "systems" in path.relative_to(self.root).parts:
            return path, "task" if path.name == "task.json" else "record"
        raise AgentError("quarantine takes a core journal, legacy journal or systems/*.json record")

    def quarantine(self, record):
        """Move an unusable record's exact bytes to a corrupt/ sibling. Nothing is deleted."""
        with self.locked():
            path, kind = self._located_record(record)
            data = path.read_bytes()
            try:
                value = json.loads(data.decode("utf-8"))
                problem = {"journal": journal_problem, "legacy": legacy_problem, "task": task_problem,
                           "record": lambda v: None if isinstance(v, dict) else "not a JSON object"}[kind](value)
            except ValueError as exc:
                problem = "unreadable JSON: " + str(exc)
            if not problem:
                raise AgentError("record is readable; quarantine refused so a valid record is never hidden")
            target_dir = path.parent / "corrupt"
            target = target_dir / path.name
            if target.exists():
                target = target_dir / (path.stem + "-" + uuid.uuid4().hex[:8] + path.suffix)
            tracked = kind != "legacy" and self._git("ls-files", "--error-unmatch", "--",
                                                     ":(literal)" + self.relative(path), check=False).returncode == 0
            target_dir.mkdir(exist_ok=True)
            os.rename(path, target)  # same directory tree: the exact bytes move, nothing is rewritten
            if kind == "task":
                self._bump_index()
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            commit = None
            if tracked and self.commit:
                commit = self._commit([str(path.relative_to(self.root)), str(target.relative_to(self.root))],
                                      "quarantine", ident("op"))
            return {"quarantined": str(path), "to": str(target), "kind": kind, "reason": problem,
                    "sha256": digest(data), "bytes": len(data), "tracked": tracked, "commit": commit,
                    "deleted": False}

    def abandon(self, operation_id, human):
        """Raymond retires a conflicted operation; current files, including his later edit, stay."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", str(operation_id)):
            raise AgentError("invalid operation id")
        # Confirm outside the writer lock: the dialog may wait up to two minutes.
        authority = human_authority(human, "recover --abandon " + operation_id, "", self.root)
        with self.locked():
            candidates = [self.state / "operations" / (operation_id + ".json"),
                          self._legacy_dir() / (operation_id + ".json")]
            path = next((p for p in candidates if p.is_file()), None)
            if not path:
                raise AgentError("operation journal not found: " + operation_id)
            try:
                record = json.loads(path.read_text())
            except ValueError as exc:
                raise AgentError("operation journal unreadable; use recover --quarantine instead") from exc
            if not isinstance(record, dict) or record.get("phase") != "conflict":
                raise AgentError("only a conflicted operation can be abandoned; run recover first")
            record.update(phase="abandoned", abandoned=dict(authority, at=utc()),
                          kept="current files as found, including later human edits")
            atomic(path, encoded(record))
            return {"operation_id": operation_id, "phase": "abandoned", "record": str(path),
                    "authority": authority, "conflicts": record.get("conflicts", [])}

    def task_path(self, task):
        raw = Path(str(task))
        candidate = self.root / raw if not raw.is_absolute() else raw
        if candidate.exists():
            candidate = self.path(candidate)
            if not candidate.is_dir():
                raise AgentError("task must be a directory")
            return candidate
        for record in self.tasks():
            if record["task_id"] == str(task):
                return self.path(record["path"])
        raise AgentError("task not found: " + str(task))

    def contract(self, task):
        location = self.task_path(task) / "systems/task.json"
        try:
            value = self.read(location)
        except AgentError as exc:
            raise AgentError(f"task record corrupt, only this task is blocked; repair it or ctx system recover "
                             f"--quarantine {self.relative(location)} ({exc})") from exc
        if not value:
            raise AgentError("task is not enrolled")
        if isinstance(value, dict) and value.get("schema_version") != VERSION:
            raise AgentError("unsupported task schema version; preserve and migrate explicitly")
        if task_problem(value):
            raise AgentError(f"task record corrupt ({task_problem(value)}), only this task is blocked: "
                             f"{self.relative(location)}")
        return value

    def _index_stamp(self, records):
        """Cheap validity key for the cached index: generation bump plus each known record's stat."""
        try:
            generation = self._generation.read_text()
        except OSError:
            generation = None
        stats = []
        for rel in records:
            try:
                st = os.stat(self.root / rel)
            except OSError:
                return None  # a known task moved or vanished: walk again
            stats.append((rel, st.st_mtime_ns, st.st_size, st.st_ino))
        return generation, tuple(stats)

    @property
    def _generation(self):
        return self.lock_path.parent / "ctx-task-index.generation"

    def _bump_index(self):
        """Every Store process sees a new or rewritten task record on its next tasks() call."""
        _TASK_INDEX.pop(str(self.root), None)
        try:
            atomic(self._generation, uuid.uuid4().hex.encode())
        except OSError:
            pass  # the per-record stat check still catches rewrites and moves of known records

    def tasks(self):
        """Readable enrolled tasks. Unreadable task records are listed in self.corrupt_tasks.

        The workspace walk is cached per process and reused while the generation file and
        every known task record are unchanged; enroll/claim/correct/accept bump the generation.
        """
        cached = _TASK_INDEX.get(str(self.root))
        if cached and cached[0] is not None and self._index_stamp(cached[3]) == cached[0]:
            self.corrupt_tasks = copy.deepcopy(cached[2])
            return copy.deepcopy(cached[1])
        try:
            generation = self._generation.read_text()
        except OSError:
            generation = None
        result, self.corrupt_tasks, records, stats = [], [], [], []
        for base, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".venv", "__pycache__", "full"}
                       and not (Path(base) / d).is_symlink()]
            if Path(base).name == "systems" and "task.json" in files:
                folder = str(Path(base).parent.relative_to(self.root))
                records.append(folder + "/systems/task.json")
                try:
                    # Stat before reading: a rewrite after this point changes the stamp, never hides.
                    st = os.stat(Path(base) / "task.json")
                    stats.append((records[-1], st.st_mtime_ns, st.st_size, st.st_ino))
                    record = json.loads((Path(base) / "task.json").read_text())
                    problem = task_problem(record)
                except (OSError, ValueError) as exc:
                    record, problem = None, "unreadable JSON: " + str(exc)
                if problem:
                    self.corrupt_tasks.append({"path": folder, "record": folder + "/systems/task.json",
                                               "reason": problem})
                    continue
                record["path"] = folder
                result.append(record)
        identities = [r["task_id"] for r in result]
        if len(set(identities)) != len(identities):
            raise AgentError("duplicate task identity: inspect copied task metadata")
        result = sorted(result, key=lambda r: r["path"])
        if len(stats) == len(records):
            _TASK_INDEX[str(self.root)] = ((generation, tuple(stats)), copy.deepcopy(result),
                                           copy.deepcopy(self.corrupt_tasks), records)
        return result

    def _record(self, task, group, record_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", str(record_id)):
            raise AgentError("invalid record id")
        return self.task_path(task) / "systems" / group / (str(record_id) + ".json")

    def _list(self, task, group):
        return [self.read(p) for p in sorted((self.task_path(task) / "systems" / group).glob("*.json"))]

    def _owner(self, task, actor=None, owner_token=None):
        """Owner authority is the credential enrollment issued once, never a typed label."""
        contract = self.contract(task)
        if not owner_token:
            raise AgentError("task owner credential required (--owner-token or CTX_OWNER_TOKEN)")
        expected = contract.get("owner_token_hash")
        if not expected or not secrets.compare_digest(expected, digest(owner_token.encode())):
            raise AgentError("invalid owner credential")
        if actor is not None and actor != contract["owner"]:
            raise AgentError("owner credential was issued to a different actor")
        return contract

    def _bearer(self, task, run_id, token, actor=None, action=None):
        """Actor identity comes from the issued run receipt; a typed actor must match it."""
        record = self.read(self._record(task, "runs", run_id)) if run_id else None
        if not record:
            raise AgentError("run credential required (--run/--token or CTX_RUN/CTX_RUN_TOKEN)")
        return self._run(task, run_id, record["actor"] if actor is None else actor, token, action, acknowledged=False)

    def reissue_owner(self, task, human):
        """Raymond replaces a lost or leaked owner credential; the old one stops working."""
        authority = human_authority(human, "owner-token (revokes the current owner credential)",
                                    self.relative(self.task_path(task)), self.root)
        with self.locked():
            contract = self.contract(task)
            token = secrets.token_urlsafe(32)
            contract.update(owner_token_hash=digest(token.encode()), owner_token_issued=dict(authority, at=utc()))
            self.transaction("owner-token", {str(self.task_path(task) / "systems/task.json"): contract})
            return {"task_id": contract["task_id"], "owner": contract["owner"], "owner_token": token,
                    "authority": authority}

    def enroll(self, task, owner, goal, criteria, allowed_paths=None, dependencies=None, operation_id=None):
        if not owner or not goal or not criteria:
            raise AgentError("owner, goal and observable criteria are required")
        path = self.task_path(task)
        if not (path / "0 start.md").is_file():
            raise AgentError("enrollment requires an existing task packet")
        parsed = []
        for i, value in enumerate(criteria, 1):
            value = {"id": "A" + str(i), "text": value} if isinstance(value, str) else dict(value)
            if not value.get("id") or not value.get("text"):
                raise AgentError("criterion id and text are required")
            parsed.append(value)
        if len({p["id"] for p in parsed}) != len(parsed):
            raise AgentError("criterion ids must be unique")
        scopes = [self.relative(p) for p in (allowed_paths or [path])]
        deps = dependencies or []
        for dep in deps:
            self.contract(dep)
        with self.locked():
            previous = self.read(path / "systems/task.json")
            if previous:
                if previous["owner"] == owner and previous["goal"] == goal and previous["criteria"] == parsed:
                    return previous
                raise AgentError("already enrolled: use scoped correction, never replace identity")
            owner_token = secrets.token_urlsafe(32)
            record = {"schema_version": VERSION, "task_id": ident("task"), "requirement_rev": 1,
                      "owner": owner, "goal": goal, "criteria": parsed, "allowed_paths": scopes,
                      "dependencies": [self.contract(d)["task_id"] for d in deps], "state": "planned",
                      "created_at": utc(), "sequence": 0, "review_required": True, "location": self.relative(path),
                      "budget": {"max_active_runs": 4, "max_attempts": 12, "max_review_rounds": 2},
                      "owner_token_hash": digest(owner_token.encode())}
            self.transaction("enroll", {str(path / "systems/task.json"): record}, operation_id=operation_id)
            # Returned once, like a run token: retain the receipt, never commit the token.
            return dict(record, owner_token=owner_token)

    def reconcile_location(self, task, actor=None, owner_token=None):
        """Repair an explicitly moved task's internal readers, never broaden its scopes.

        External readers are not rewritten under another owner's authority. The receipt
        names old/new locations so the move coordinator can repair those declared readers.
        """
        with self.locked():
            contract = self._owner(task, actor, owner_token)
            path = self.task_path(task)
            current = self.relative(path)
            old = contract.get("location", current)
            if old == current:
                return {"task_id": contract["task_id"], "old": old, "new": current, "changed": False}
            original = self.root / old
            if (original / "systems/task.json").exists():
                raise AgentError("old location still contains task metadata; reconcile duplicate explicitly")
            def relocated(value):
                if value == old:
                    return current
                if value.startswith(old + "/"):
                    return current + value[len(old):]
                return value
            contract["allowed_paths"] = [relocated(v) for v in contract["allowed_paths"]]
            contract["location"] = current
            writes = {str(path / "systems/task.json"): contract}
            for group in ("runs", "submissions", "evidence", "acceptances", "challenges", "reviews"):
                for record in self._list(task, group):
                    if "allowed_paths" in record:
                        record["allowed_paths"] = [relocated(v) for v in record["allowed_paths"]]
                        record["acknowledged_rev"] = None
                    if "artifacts" in record:
                        mapped = {relocated(p): h for p, h in record["artifacts"].items()}
                        if any(file_hash(self.path(p)) != h for p, h in mapped.items()):
                            raise AgentError("moved artifact differs from recorded bytes; submission must be redone")
                        record["artifacts"] = mapped
                    key = "evidence_id" if group == "evidence" else group[:-1] + "_id"
                    writes[str(self._record(task, group, record[key]))] = record
            for file in path.rglob("*.md"):
                if "4 log" in file.relative_to(path).parts or "history" in file.relative_to(path).parts:
                    continue
                text = file.read_text()
                updated = text.replace(str(original) + "/", str(path) + "/").replace(old + "/", current + "/")
                if updated != text:
                    writes[str(file)] = updated
            self.transaction("reconcile-location", writes)
            return {"task_id": contract["task_id"], "old": old, "new": current, "changed": True,
                    "external_reader_repair": "move coordinator must repair declared external readers"}

    def _scope(self, path, scopes):
        # Case-insensitive filesystems: a missing tail can differ only in case, so fold too.
        fold = (lambda p: Path(str(p).casefold())) if self.case_insensitive else (lambda p: p)
        target = fold(path)
        return any(target == fold(self.path(s)) or fold(self.path(s)) in target.parents for s in scopes)

    def _dependencies(self, contract):
        snapshots = {}
        for dep in contract["dependencies"]:
            upstream = self.contract(dep)
            candidates = [a for a in self._list(dep, "acceptances") if not a.get("stale") and
                          a["requirement_rev"] == upstream["requirement_rev"] and
                          all(file_hash(self.path(p)) == h for p, h in a["artifacts"].items())]
            if upstream["state"] != "complete" or not candidates:
                raise AgentError("dependency lacks current accepted artifact: " + dep)
            selected = max(candidates, key=lambda a: a["created_at"])
            snapshots[dep] = {"requirement_rev": upstream["requirement_rev"], "artifacts": selected["artifacts"]}
        return snapshots

    def claim(self, task, actor, harness="local", allowed_paths=None, lease_seconds=900, run_id=None,
              operation_id=None, coordinator=None, actions=None, owner_token=None, reissue=False):
        """The owner credential grants a run to actor; review-only runs hold no write scope.

        A retried grant returns no token; reissue=True replaces the token of the same active
        run for the same actor, revoking the previous one.
        """
        if not actor or not 1 <= lease_seconds <= 86400:
            raise AgentError("actor required and lease must be 1–86400 seconds")
        with self.locked():
            contract = self._owner(task, coordinator, owner_token)
            run_id = run_id or ("run-" + digest(operation_id.encode())[:32] if operation_id else ident("run"))
            location = self._record(task, "runs", run_id)
            existing = self.read(location)
            if existing:
                if existing["actor"] != actor or existing["harness"] != harness or (allowed_paths is not None and
                    [self.relative(p) for p in allowed_paths] != existing["allowed_paths"]) or (actions is not None and actions != existing["actions"]):
                    raise AgentError("run id already belongs to a different dispatch")
                if not reissue:
                    return dict(existing, token=None, dispatch_reused=True,
                                note="already granted: use the original receipt, or claim again with --reissue "
                                     "to revoke it and issue a new token to the same actor")
                if existing["status"] != "active" or existing["expires_at"] <= time.time():
                    raise AgentError("run is no longer active; claim a new run instead of reissuing")
                token = secrets.token_urlsafe(32)
                existing.update(token_hash=digest(token.encode()), reissued_at=utc(),
                                reissue_count=existing.get("reissue_count", 0) + 1)
                self.transaction("claim-reissue", {str(location): existing})
                return dict(existing, token=token, dispatch_reused=True, reissued=True)
            if reissue:
                raise AgentError("nothing to reissue: no run with this id or operation id")
            if actions is not None and (not actions or set(actions) - {"write", "submit", "review"} or
                                        ("review" in actions and set(actions) != {"review"})):
                raise AgentError("run actions must be write/submit, or review alone")
            reviewing = actions is not None and set(actions) == {"review"}
            scopes = [self.relative(p) for p in (allowed_paths or contract["allowed_paths"])]
            for scope in scopes:
                if not self._scope(self.path(scope), contract["allowed_paths"]):
                    raise AgentError("run scope exceeds task contract")
            active = [r for r in self._list(task, "runs") if r["status"] == "active" and r["expires_at"] > time.time()]
            if len(active) >= contract["budget"]["max_active_runs"]:
                raise AgentError("task concurrency budget exhausted")
            if len(self._list(task, "runs")) >= contract["budget"]["max_attempts"]:
                raise AgentError("task attempt budget exhausted")
            # Check all enrolled tasks, including overlapping scopes in another task.
            for other in ([] if reviewing else self.tasks()):
                for run in self._list(other["task_id"], "runs"):
                    if run["status"] != "active" or run["expires_at"] <= time.time() or run["actions"] == ["review"]:
                        continue
                    if any(self._scope(self.path(s), run["allowed_paths"]) or
                           self._scope(self.path(r), scopes) for s in scopes for r in run["allowed_paths"]):
                        raise AgentError("active writer lease overlaps requested scope")
            for bad in ([] if reviewing else self.corrupt_tasks):
                # Its leases are unreadable: only its own folder is withheld, never the workspace.
                if any(self._scope(self.path(s), [bad["path"]]) or self._scope(self.path(bad["path"]), [s]) for s in scopes):
                    raise AgentError("requested scope overlaps a task whose record is corrupt: " + bad["record"])
            dependency_snapshot = self._dependencies(contract)
            token = secrets.token_urlsafe(32)
            record = {"schema_version": VERSION, "run_id": run_id, "task_id": contract["task_id"],
                      "actor": actor, "harness": harness, "requirement_rev": contract["requirement_rev"],
                      "allowed_paths": scopes, "actions": actions or ["write", "submit"], "status": "active",
                      "expires_at": time.time() + lease_seconds, "created_at": utc(),
                      "token_hash": digest(token.encode()), "acknowledged_rev": None,
                      "session_receipt": None, "dependencies": dependency_snapshot,
                      "granted_by": {"kind": "owner-credential", "owner": contract["owner"]}}
            if not reviewing:
                contract["state"] = "active"
            self.transaction("claim", {str(location): record,
                             str(self.task_path(task) / "systems/task.json"): contract}, operation_id=operation_id)
            return dict(record, token=token)

    def _run(self, task, run_id, actor, token, action=None, acknowledged=True):
        record = self.read(self._record(task, "runs", run_id))
        contract = self.contract(task)
        if not record or record["actor"] != actor or not token or not secrets.compare_digest(
                record["token_hash"], digest(token.encode())):
            raise AgentError("invalid run capability")
        if record["status"] != "active" or record["expires_at"] <= time.time():
            raise AgentError("writer lease expired or inactive")
        if action and action not in record["actions"]:
            raise AgentError("run action is outside lease")
        if record["requirement_rev"] != contract["requirement_rev"]:
            raise AgentError("run is stale after requirement correction")
        if record.get("dependencies", {}) != self._dependencies(contract):
            raise AgentError("consumed upstream artifact changed; new attempt required")
        if acknowledged and record.get("acknowledged_rev") != contract["requirement_rev"]:
            raise AgentError("boot acknowledgement required")
        return record

    def acknowledge(self, task, run_id, actor, token, manifest, session_receipt=None):
        with self.locked():
            record = self.read(self._record(task, "runs", run_id))
            contract = self.contract(task)
            if not record or record["actor"] != actor or not token or not secrets.compare_digest(
                    record["token_hash"], digest(token.encode())):
                raise AgentError("invalid run capability")
            if record["status"] != "active" or record["expires_at"] <= time.time():
                raise AgentError("writer lease expired or inactive")
            if manifest.get("blocked") or manifest.get("requirement_rev") != contract["requirement_rev"]:
                raise AgentError("cannot acknowledge blocked or stale boot")
            current = _make_boot_locked(self, task, max_chars=manifest.get("budget", 9500))["manifest"]
            if manifest.get("manifest_hash") != current["manifest_hash"]:
                raise AgentError("boot sources changed before acknowledgement")
            record.update(acknowledged_rev=contract["requirement_rev"], requirement_rev=contract["requirement_rev"],
                          boot_manifest_hash=manifest["manifest_hash"], session_receipt=session_receipt,
                          acknowledged_at=utc())
            self.transaction("acknowledge", {str(self._record(task, "runs", run_id)): record})
            return record

    def renew(self, task, run_id, actor, token, lease_seconds=900):
        if not 1 <= lease_seconds <= 86400:
            raise AgentError("invalid lease duration")
        with self.locked():
            record = self._run(task, run_id, actor, token)
            record["expires_at"] = time.time() + lease_seconds
            self.transaction("renew", {str(self._record(task, "runs", run_id)): record})
            return record

    def release(self, task, run_id, actor, token, reason="finished"):
        with self.locked():
            record = self.read(self._record(task, "runs", run_id))
            if not record or record["actor"] != actor or not token or not secrets.compare_digest(
                    record["token_hash"], digest(token.encode())):
                raise AgentError("invalid run capability")
            if record["status"] == "released":
                return record
            record.update(status="released", released_at=utc(), reason=reason)
            self.transaction("release", {str(self._record(task, "runs", run_id)): record})
            return record

    def correct(self, task, actor, old, replacement, source, affected=None, criteria=None, supersedes=None,
                owner_token=None):
        if not old or not replacement or not source:
            raise AgentError("old, replacement and exact human source are required")
        with self.locked():
            original = self._owner(task, actor, owner_token)
            actor = original["owner"]
            prior_ids = {c["correction_id"] for c in self._list(task, "corrections")}
            if set(supersedes or []) - prior_ids:
                raise AgentError("supersession must name an existing scoped correction")
            tasks = self.tasks()
            ids = {original["task_id"]} | set(affected or [])
            # Fanout is restricted to explicitly declared dependencies, never prose similarity.
            while True:
                added = {t["task_id"] for t in tasks if set(t["dependencies"]).intersection(ids)}
                if added.issubset(ids):
                    break
                ids.update(added)
            if ids - {t["task_id"] for t in tasks}:
                raise AgentError("unknown affected task id")
            correction_id = ident("correction")
            writes = {}
            for current in tasks:
                if current["task_id"] not in ids:
                    continue
                current.pop("path")
                previous = current["requirement_rev"]
                current["requirement_rev"] += 1
                current["state"] = "active"
                if current["task_id"] == original["task_id"] and criteria is not None:
                    if not criteria or any(not c.get("id") or not c.get("text") for c in criteria):
                        raise AgentError("corrected criteria require id and text")
                    if len({c["id"] for c in criteria}) != len(criteria):
                        raise AgentError("criterion ids must be unique")
                    current["criteria"] = criteria
                path = self.task_path(current["task_id"])
                event = {"schema_version": VERSION, "correction_id": correction_id,
                         "task_id": current["task_id"], "old": old, "replacement": replacement,
                         "source": source, "source_kind": "user", "created_at": utc(),
                         "old_rev": previous, "requirement_rev": current["requirement_rev"],
                         "affected": sorted(ids), "supersedes": list(supersedes or [])}
                writes[str(path / "systems/task.json")] = current
                writes[str(self._record(current["task_id"], "corrections", correction_id))] = event
                for group in ("evidence", "submissions", "acceptances"):
                    for record in self._list(current["task_id"], group):
                        record.update(stale=True, stale_reason=correction_id)
                        key = record[group[:-1] + "_id"] if group != "evidence" else record["evidence_id"]
                        writes[str(self._record(current["task_id"], group, key))] = record
                message = self._message(current, "correction", actor, replacement,
                                        source=source, correlation=correction_id)
                current["sequence"] = message["sequence"]
                writes[str(self._record(current["task_id"], "messages", message["message_id"]))] = message
                takeaways = path / "1 takeaways.md"
                text = takeaways.read_text() if takeaways.exists() else ""
                text += "\n```notes\n    correction " + correction_id + "\n"
                for key, value in (("old", old), ("replacement", replacement), ("scope", current["task_id"]),
                                   ("source", source), ("requirement revision", str(current["requirement_rev"]))):
                    text += "        " + key.ljust(24) + " ".join(str(value).splitlines()).replace("```", "'") + "\n"
                writes[str(takeaways)] = text + "```\n"
                packet = path / "0 start.md"
                text = packet.read_text()
                notice = "    requirement revision    " + str(current["requirement_rev"]) + "\n"
                notice += "    latest correction       " + " ".join(replacement.splitlines()).replace("```", "'") + "\n"
                # Keep packet bounded: replace existing correction rows rather than append history.
                text = re.sub(r"^    (?:requirement revision|latest correction)\s+.*\n", "", text, flags=re.M)
                if "```notes\n" in text:
                    text = text.replace("```notes\n", "```notes\n" + notice, 1)
                else:
                    text = "```notes\n" + notice + "```\n" + text
                if len(text.splitlines()) > 40:
                    raise AgentError("correction would overflow current packet; trim owned packet first")
                writes[str(packet)] = text
            self.transaction("correct", writes)
            return {"correction_id": correction_id, "affected": sorted(ids)}

    def _message(self, contract, kind, sender, body, **fields):
        if kind not in KINDS or not body or not sender:
            raise AgentError("known message type, sender and body required")
        reserved = {"schema_version", "message_id", "task_id", "requirement_rev", "sequence", "kind", "sender", "body", "created_at", "delivery", "adapter", "acknowledged", "authority"}
        if reserved.intersection(fields):
            raise AgentError("message extension cannot replace protocol fields")
        return {"schema_version": VERSION, "message_id": ident("message"), "task_id": contract["task_id"],
                "requirement_rev": contract["requirement_rev"], "sequence": contract["sequence"] + 1,
                "kind": kind, "sender": sender, "body": body, "created_at": utc(),
                "delivery": "queued", "adapter": "unsupported", "acknowledged": False,
                "authority": "informational; not human permission", **fields}

    def send(self, task, kind, sender, body, dedupe_key=None, **fields):
        with self.locked():
            contract = self.contract(task)
            if dedupe_key:
                for item in self._list(task, "messages"):
                    if item.get("dedupe_key") == dedupe_key:
                        if item["body"] != body or item["kind"] != kind or item["sender"] != sender:
                            raise AgentError("message dedupe key used for different content")
                        return item
            record = self._message(contract, kind, sender, body, dedupe_key=dedupe_key, **fields)
            contract["sequence"] = record["sequence"]
            self.transaction("send", {str(self._record(task, "messages", record["message_id"])): record,
                                      str(self.task_path(task) / "systems/task.json"): contract})
            return record

    def receipt(self, task, message_id, actor, note="loaded", run_id=None, token=None, owner_token=None):
        with self.locked():
            if run_id:
                actor = self._bearer(task, run_id, token, actor)["actor"]
            else:
                actor = self._owner(task, actor, owner_token)["owner"]
            record = self.read(self._record(task, "messages", message_id))
            if not record:
                raise AgentError("message not found")
            record.update(acknowledged=True, acknowledged_at=utc(), receipt_actor=actor, receipt_note=note)
            self.transaction("receipt", {str(self._record(task, "messages", message_id)): record})
            return record

    def submit(self, task, run_id, actor, token, artifacts, criteria=None):
        with self.locked():
            run = self._run(task, run_id, actor, token, "submit")
            contract = self.contract(task)
            hashes = {}
            for item in artifacts:
                path = self.path(item)
                if not self._scope(path, run["allowed_paths"]) or not path.is_file():
                    raise AgentError("submission artifact missing or outside writer scope")
                hashes[self.relative(path)] = file_hash(path)
            if not hashes:
                raise AgentError("submission requires concrete artifacts")
            criterion_ids = criteria or [c["id"] for c in contract["criteria"]]
            if set(criterion_ids) != {c["id"] for c in contract["criteria"]}:
                raise AgentError("submission must address every current criterion")
            record = {"schema_version": VERSION, "submission_id": ident("submission"),
                      "task_id": contract["task_id"], "run_id": run_id, "actor": actor,
                      "requirement_rev": contract["requirement_rev"], "artifacts": hashes,
                      "criteria": criterion_ids, "created_at": utc(), "stale": False, "dependencies": run.get("dependencies", {}),
                      "base_commit": self._git("rev-parse", "HEAD", check=False).stdout.strip() or None}
            contract["state"] = "submitted"
            self.transaction("submit", {str(self._record(task, "submissions", record["submission_id"])): record,
                                        str(self.task_path(task) / "systems/task.json"): contract})
            return record

    def _submission(self, task, submission_id):
        record = self.read(self._record(task, "submissions", submission_id))
        contract = self.contract(task)
        if not record or record.get("stale") or record["requirement_rev"] != contract["requirement_rev"]:
            raise AgentError("submission absent or based on stale requirements")
        if record.get("dependencies", {}) != self._dependencies(contract):
            raise AgentError("submission consumed stale upstream artifacts")
        for rel, h in record["artifacts"].items():
            if file_hash(self.path(rel)) != h:
                raise AgentError("combined artifact changed after submission: " + rel)
        return record

    def _content_files(self, path):
        """Content files under a folder, skipping coordination records, git and bytecode."""
        for base, dirs, files in os.walk(path):
            # Coordination records (task systems/ folders, agent-state) change as review proceeds.
            dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__", ".pytest_cache", "agent-state"}
                             and not (Path(base) / d).is_symlink() and not (Path(base) / d / "task.json").is_file())
            for name in sorted(files):
                item = Path(base) / name
                if item.is_file() and not item.is_symlink() and not name.endswith(".pyc") and name != ".DS_Store":
                    yield item

    def _input_hash(self, rel):
        path = self.path(rel)
        if path.is_file():
            return file_hash(path)
        if not path.is_dir():
            return None
        return digest("\n".join(str(item.relative_to(path)) + "\0" + file_hash(item)
                                for item in self._content_files(path)).encode())

    def _combined_tree(self, roots):
        """File-level content hashes under roots: what any check could have read from another task."""
        tree = {}
        for rel in sorted(set(roots)):
            path = self.path(rel)
            if path.is_file():
                tree[self.relative(path)] = file_hash(path)
            elif path.is_dir():
                for item in self._content_files(path):
                    tree[str(item.relative_to(self.root))] = file_hash(item)
        return tree

    def _combined_roots(self, extra=()):
        """Every enrolled task's scopes and submitted artifacts, plus this check's declared inputs."""
        roots = set(extra)
        for task in self.tasks():
            roots.update(task["allowed_paths"])
            for record in self._list(task["task_id"], "submissions"):
                if not record.get("stale"):
                    roots.update(record.get("artifacts", {}))
        return sorted(roots)

    def _check_inputs(self, command, artifacts, declared=None):
        """Bind a check to the combined revision it read: artifacts, declared inputs, argv paths."""
        paths = set(artifacts) | {self.relative(p) for p in declared or []}
        for arg in command[1:]:
            if arg.startswith("-") or "\n" in arg or len(arg) > 1024:
                continue
            try:
                candidate = self.path(arg)
                if candidate.exists():
                    paths.add(self.relative(candidate))
            except (AgentError, OSError, ValueError):
                continue
        return {p: self._input_hash(p) for p in sorted(paths)}

    def check(self, task, submission_id, actor, criterion, command, timeout=60, run_id=None, token=None,
              owner_token=None, inputs=None):
        """Execute argv without a shell against the current combined artifact.

        The evidence actor is the holder of the presented run or owner credential. Evidence
        records HEAD and the hash of every artifact, declared input and argv path the check
        read; acceptance refuses if any of them moved after the check.
        """
        args = (task, submission_id, actor, criterion, command, timeout, run_id, token, owner_token, inputs)
        if getattr(self._local, "depth", 0):
            return self._check(*args)  # a held coordinator lock already serializes everything
        # Checks stay one at a time, as before: only readers such as boot overlap a running command,
        # so another check's command can never change what this check read before it is recorded.
        self.check_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.check_lock_path, "a+b") as serial:
            fcntl.flock(serial, fcntl.LOCK_EX)
            try:
                return self._check(*args)
            finally:
                fcntl.flock(serial, fcntl.LOCK_UN)

    def _check(self, task, submission_id, actor, criterion, command, timeout, run_id, token, owner_token, inputs):
        def authenticate():
            if run_id:
                return self._bearer(task, run_id, token, actor)["actor"]
            if owner_token:
                return self._owner(task, actor, owner_token)["owner"]
            raise AgentError("check requires a run credential (--run/--token) or the owner credential")
        # The command runs under a shared hold: readers such as a fresh boot proceed while every
        # managed writer waits, so nothing the check reads moves through the engine meanwhile.
        with self.locked(shared=True):
            actor = authenticate()
            submission = self._submission(task, submission_id)
            if criterion not in submission["criteria"] or not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command) or not 0 < timeout <= 600:
                raise AgentError("known criterion and explicit argv command required")
            consumed = [p for dep in submission.get("dependencies", {}).values() for p in dep.get("artifacts", {})]
            observed_inputs = self._check_inputs(command, list(submission["artifacts"]) + consumed, inputs)
            head = self._git("rev-parse", "HEAD", "HEAD^{tree}", check=False).stdout.split() or [None, None]
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                try:
                    result = subprocess.run(command, cwd=self.root, stdout=stdout, stderr=stderr, timeout=timeout)
                    passed, code = result.returncode == 0, result.returncode
                    failure = ""
                except subprocess.TimeoutExpired:
                    passed, code, failure = False, None, "timeout"
                except OSError as exc:
                    passed, code, failure = False, None, str(exc)
                def tail(stream):
                    stream.seek(0, os.SEEK_END)
                    stream.seek(max(0, stream.tell() - 20000))
                    return stream.read().decode("utf-8", errors="replace")
                out, err = tail(stdout), tail(stderr)
                if failure:
                    err += "\n" + failure
            self._submission(task, submission_id)  # a mutating check invalidates its own result
            after = {p: self._input_hash(p) for p in observed_inputs}
            moved = [p for p, h in observed_inputs.items() if after[p] != h and self.path(p).is_file()]
            if moved:
                raise AgentError("check changed its own input; result discarded: " + ", ".join(moved))
            observed_inputs = after  # directory inputs bind to the state the check left behind
            # Conservative A13 default: bind to every enrolled scope too, so an undeclared read
            # (python -c, imports) of another task's file is still covered at acceptance.
            roots = self._combined_roots(observed_inputs)
            tree = self._combined_tree(roots)
        # Recording needs the writer lock; anything that moved while no lock was held discards the result.
        with self.locked():
            authenticate()
            self._submission(task, submission_id)
            if ({p: self._input_hash(p) for p in observed_inputs} != observed_inputs or
                    self._combined_roots(observed_inputs) != roots or self._combined_tree(roots) != tree):
                raise AgentError("combined revision changed before the check was recorded; result discarded, re-run")
            record = {"schema_version": VERSION, "evidence_id": ident("evidence"), "kind": "deterministic",
                      "inputs": observed_inputs, "head": head[0], "head_tree": head[-1],
                      "combined_roots": roots, "combined_tree": tree,
                      "task_id": submission["task_id"], "submission_id": submission_id, "actor": actor,
                      "run_id": run_id, "credential": "run" if run_id else "owner-credential",
                      "criterion": criterion, "requirement_rev": submission["requirement_rev"],
                      "artifacts": submission["artifacts"], "command": command, "returncode": code,
                      "passed": passed, "stdout": out[-20000:], "stderr": err[-20000:],
                      "created_at": utc(), "stale": False}
            self.transaction("check", {str(self._record(task, "evidence", record["evidence_id"])): record})
            return record

    def challenge(self, task, submission_id, actor, criterion, expected, observed, source, severity="material",
                  run_id=None, token=None):
        with self.locked():
            submission = self._submission(task, submission_id)
            actor = self._bearer(task, run_id, token, actor, "review")["actor"]
            if actor == submission["actor"] or run_id == submission["run_id"]:
                raise AgentError("fresh challenger must differ from builder")
            if criterion not in submission["criteria"] or not expected or not observed or not source:
                raise AgentError("challenge requires criterion, expected, observed and evidence source")
            rounds = [c for c in self._list(task, "challenges") if c["submission_id"] == submission_id and c["criterion"] == criterion]
            if len(rounds) + sum(r["submission_id"] == submission_id and criterion in r["criteria"] for r in self._list(task, "reviews")) >= self.contract(task)["budget"]["max_review_rounds"]:
                raise AgentError("review round cap reached; explicit human decision required")
            record = {"schema_version": VERSION, "challenge_id": ident("challenge"), "task_id": submission["task_id"],
                      "submission_id": submission_id, "actor": actor, "run_id": run_id, "criterion": criterion,
                      "requirement_rev": submission["requirement_rev"], "artifacts": submission["artifacts"],
                      "expected": expected, "observed": observed, "source": source, "severity": severity,
                      "status": "open", "created_at": utc()}
            self.transaction("challenge", {str(self._record(task, "challenges", record["challenge_id"])): record})
            return record

    def resolve(self, task, challenge_id, actor, response, evidence_ids, outcome="resolved", owner_token=None):
        with self.locked():
            actor = self._owner(task, actor, owner_token)["owner"]
            record = self.read(self._record(task, "challenges", challenge_id))
            if not record or outcome not in {"resolved", "accepted-risk", "unresolved"} or not response:
                raise AgentError("challenge, adjudication outcome and response required")
            submission = self._submission(task, record["submission_id"])
            evidence = [self.read(self._record(task, "evidence", item)) for item in evidence_ids]
            if outcome != "unresolved" and (not evidence or any(not e or not e["passed"] or e.get("stale") or
                e["submission_id"] != submission["submission_id"] or e["criterion"] != record["criterion"] for e in evidence)):
                raise AgentError("resolution requires passing current evidence for challenged criterion")
            record.update(status=outcome, response=response, evidence_ids=evidence_ids,
                          adjudicator=actor, resolved_at=utc())
            self.transaction("resolve", {str(self._record(task, "challenges", challenge_id)): record})
            return record

    def review(self, task, submission_id, actor, source, evidence_ids, criteria=None, run_id=None, token=None):
        """An independent criterion review may legitimately find no violation.

        The reviewer is the holder of an issued review run, never the submitting run or actor.
        """
        with self.locked():
            submission = self._submission(task, submission_id)
            actor = self._bearer(task, run_id, token, actor, "review")["actor"]
            if actor == submission["actor"] or run_id == submission["run_id"] or not source:
                raise AgentError("fresh reviewer and source required")
            selected = criteria or submission["criteria"]
            if not selected or not set(selected).issubset(submission["criteria"]):
                raise AgentError("review requires known criterion coverage")
            evidence = [self.read(self._record(task, "evidence", item)) for item in evidence_ids]
            if not evidence or any(not e or not e["passed"] or e.get("stale") or e.get("run_id") != run_id or
                                   e["submission_id"] != submission_id for e in evidence):
                raise AgentError("review requires reviewer-observed passing current evidence")
            if not set(selected).issubset({e["criterion"] for e in evidence}):
                raise AgentError("review evidence does not cover criteria")
            prior = self._list(task, "reviews")
            cap = self.contract(task)["budget"]["max_review_rounds"]
            if any(sum(c in r["criteria"] and r["submission_id"] == submission_id for r in prior) +
                   sum(ch["criterion"] == c and ch["submission_id"] == submission_id for ch in self._list(task, "challenges")) >= cap for c in selected):
                raise AgentError("review round cap reached; explicit human decision required")
            record = {"schema_version": VERSION, "review_id": ident("review"), "task_id": submission["task_id"],
                      "submission_id": submission_id, "actor": actor, "run_id": run_id, "criteria": selected,
                      "source": source, "evidence_ids": evidence_ids, "findings": [],
                      "requirement_rev": submission["requirement_rev"], "artifacts": submission["artifacts"],
                      "created_at": utc()}
            self.transaction("review", {str(self._record(task, "reviews", record["review_id"])): record})
            return record

    def accept(self, task, submission_id, actor=None, owner_token=None, human=None):
        """Owner credential, or Raymond's dialog-confirmed human authority recorded verbatim."""
        if human:  # confirm outside the writer lock: the dialog may wait up to two minutes
            human_grant = human_authority(human, "accept " + str(submission_id),
                                          self.relative(self.task_path(task)), self.root)
        with self.locked():
            if human:
                authority = human_grant
                contract = self.contract(task)
                actor = "raymond"
            else:
                contract = self._owner(task, actor, owner_token)
                actor = contract["owner"]
                authority = {"kind": "owner-credential", "owner": actor}
            submission = self._submission(task, submission_id)
            observed = [e for e in self._list(task, "evidence") if e["submission_id"] == submission_id and
                        e["requirement_rev"] == contract["requirement_rev"] and not e.get("stale")]
            latest = {}
            for item in sorted(observed, key=lambda e: e["created_at"]):
                latest[(item["criterion"], tuple(item["command"]))] = item
            if any(not item["passed"] for item in latest.values()):
                raise AgentError("a current required deterministic check is failing")
            evidence = list(latest.values())
            if {e["criterion"] for e in evidence} != set(submission["criteria"]):
                raise AgentError("passing current deterministic evidence missing for a criterion")
            # A13: another task's later change to anything a check read invalidates that check.
            moved = {p for e in evidence for p, h in e.get("inputs", {}).items() if self._input_hash(p) != h}
            for e in evidence:
                if "combined_tree" in e:
                    current, recorded = self._combined_tree(e["combined_roots"]), e["combined_tree"]
                    moved.update(p for p in set(current) | set(recorded) if current.get(p) != recorded.get(p))
            moved = sorted(moved)
            if moved:
                raise AgentError("combined revision changed after check; re-run against current inputs: " + ", ".join(moved))
            challenges = [c for c in self._list(task, "challenges") if c["submission_id"] == submission_id]
            reviews = [r for r in self._list(task, "reviews") if r["submission_id"] == submission_id and
                       r["requirement_rev"] == contract["requirement_rev"]]
            covered = {c["criterion"] for c in challenges} | {c for r in reviews for c in r["criteria"]}
            if contract.get("review_required") and covered != set(submission["criteria"]):
                raise AgentError("fresh independent review required for every criterion")
            if any(c["status"] not in {"resolved", "accepted-risk"} for c in challenges):
                raise AgentError("unresolved consequential finding prevents acceptance")
            for dep in contract["dependencies"]:
                upstream = self.contract(dep)
                if upstream["state"] != "complete":
                    raise AgentError("upstream dependency is not accepted")
                accepted = self._list(dep, "acceptances")
                if not any(not a.get("stale") and a["requirement_rev"] == upstream["requirement_rev"] and
                           all(file_hash(self.path(p)) == h for p, h in a["artifacts"].items()) for a in accepted):
                    raise AgentError("upstream accepted artifact is stale")
            record = {"schema_version": VERSION, "acceptance_id": ident("acceptance"),
                      "task_id": contract["task_id"], "submission_id": submission_id, "actor": actor,
                      "authority": authority,
                      "requirement_rev": contract["requirement_rev"], "artifacts": submission["artifacts"],
                      "evidence_ids": [e["evidence_id"] for e in evidence],
                      "challenge_ids": [c["challenge_id"] for c in challenges],
                      "review_ids": [r["review_id"] for r in reviews], "created_at": utc(), "stale": False}
            contract["state"] = "complete"
            self.transaction("accept", {str(self._record(task, "acceptances", record["acceptance_id"])): record,
                                        str(self.task_path(task) / "systems/task.json"): contract})
            return record

    def boot(self, task, max_chars=9500, persist=False):
        """Consistent boot snapshot, reentrant when a service holds this Store's lock.

        A read-only boot takes a shared hold, so a running check's subprocess can still boot."""
        with self.locked(shared=not persist):
            return _make_boot_locked(self, task, max_chars, persist)

    def board(self, scope="."):
        scope_path = self.root if scope == "." else self.path(scope)
        rows = []
        for task in self.tasks():
            candidate = self.path(task["path"])
            if candidate != scope_path and scope_path not in candidate.parents:
                continue
            runs = self._list(task["task_id"], "runs")
            messages = self._list(task["task_id"], "messages")
            evidence = self._list(task["task_id"], "evidence")
            corrections = self._list(task["task_id"], "corrections")
            public = {k: v for k, v in task.items() if k != "owner_token_hash"}
            rows.append(dict(public, messages=messages, evidence=evidence, corrections=corrections,
                             needs_you=sum(m["kind"] == "question" and not m.get("acknowledged") for m in messages),
                             health={"stale_runs": [r["run_id"] for r in runs if r["status"] == "active" and r["requirement_rev"] != task["requirement_rev"]],
                                     "expired_runs": [r["run_id"] for r in runs if r["status"] == "active" and r["expires_at"] <= time.time()],
                                     "adapter": "unsupported", "native_verified": False},
                             runs=[{k: v for k, v in r.items() if k != "token_hash"} for r in runs],
                             queued_messages=sum(not m.get("acknowledged") for m in self._list(task["task_id"], "messages")),
                             lease_health="active" if any(r["status"] == "active" and r["expires_at"] > time.time() for r in runs) else "idle"))
        return rows


def make_boot(root, task, max_chars=9500, persist=False):
    store = Store(root, commit=False)
    return store.boot(task, max_chars, persist)


def _make_boot_locked(store, task, max_chars=9500, persist=False):
    if max_chars < 1:
        raise AgentError("boot character budget must be positive")
    path = store.task_path(task)
    contract = store.read(path / "systems/task.json")
    included, required, pieces = [], [], []
    if contract:
        mandatory = {k: contract[k] for k in ("task_id", "requirement_rev", "owner", "goal", "criteria", "allowed_paths",
                                              "state")}  # boot shows core state, never a legacy status
        pieces.append("CURRENT AUTHORITY AND REQUIREMENTS\n" + encoded(mandatory).decode())
        included.append({"id": contract["task_id"], "path": store.relative(path / "systems/task.json"),
                         "hash": file_hash(path / "systems/task.json"), "tier": 0})
        corrections = store._list(task, "corrections")
        superseded = {key for item in corrections for key in item.get("supersedes", [])}
        for item in sorted(corrections, key=lambda c: c["requirement_rev"], reverse=True):
            if item["correction_id"] not in superseded:
                loc = store._record(task, "corrections", item["correction_id"])
                pieces.append("LATEST HUMAN CORRECTION\n" + encoded(item).decode())
                included.append({"id": item["correction_id"], "path": store.relative(loc), "hash": file_hash(loc), "tier": 0})
        for finding in store._list(task, "challenges"):
            if finding["status"] not in {"open", "unresolved"} or finding["requirement_rev"] != contract["requirement_rev"]:
                continue
            loc = store._record(task, "challenges", finding["challenge_id"])
            pieces.append("KNOWN UNRESOLVED FINDING\n" + encoded(finding).decode())
            included.append({"id": finding["challenge_id"], "path": store.relative(loc), "hash": file_hash(loc), "tier": 0})
    # Corrections, unresolved findings and scope precede optional narrative. Never truncate a source.
    packet = path / "0 start.md"
    if not packet.is_file():
        raise AgentError("current packet unavailable")
    candidates = [(packet, "current", 1)]
    for p in sorted(path.rglob("*.md")):
        if p == packet or any(s in {"4 log", "systems", "history"} for s in p.relative_to(path).parts):
            continue
        if re.search(r"(?m)^carry:\s*pin\s*$", p.read_text()):
            candidates.append((p, "pin", 1))
    mandatory_size = len("\n".join(pieces))
    blocked = mandatory_size > max_chars
    if blocked:
        required = [item["path"] for item in included]
        included = []
        pieces = ["BOOT BLOCKED: mandatory authority exceeds budget; read every required source before consequential writes"]
    for p, label, tier in candidates:
        body = f"\n{label.upper()}: {store.relative(p)}\n{p.read_text()}"
        if not blocked and len("\n".join(pieces)) + len(body) <= max_chars:
            pieces.append(body)
            included.append({"id": store.relative(p), "path": store.relative(p), "hash": file_hash(p), "tier": tier})
        else:
            required.append(store.relative(p))
            # The current task packet and active pins are required before writing.
            blocked = True
    if contract and not blocked:
        for message in store._list(task, "messages"):
            if message.get("acknowledged"):
                continue
            location = store._record(task, "messages", message["message_id"])
            body = "\nQUEUED MESSAGE (not permission)\n" + encoded(message).decode()
            if len("\n".join(pieces)) + len(body) <= max_chars:
                pieces.append(body)
                included.append({"id": message["message_id"], "path": store.relative(location), "hash": file_hash(location), "tier": 1})
            else:
                required.append(store.relative(location))
                if message["kind"] in {"correction", "assignment", "question", "handoff"}:
                    blocked = True
    manifest = {"schema_version": VERSION, "task_id": contract["task_id"] if contract else None,
                "requirement_rev": contract["requirement_rev"] if contract else None, "blocked": blocked,
                "included": included, "required_reads": required, "budget": max_chars,
                "estimate_kind": "characters, not exact tokens", "mandatory_chars": mandatory_size}
    manifest["manifest_hash"] = digest(encoded(manifest))
    result = {"text": "\n".join(pieces)[:max_chars] if blocked else "\n".join(pieces), "manifest": manifest}
    if persist:
        store.transaction("boot-manifest", {str(path / "systems/boot/latest.json"): manifest})
    return result


def guard_path(root, path):
    """Legacy writes use the actual run's contract, including explicitly shared scopes."""
    store = Store(root, commit=False)
    target = store.path(path)
    current = target if target.is_dir() else target.parent
    protected = False
    while current != store.root:
        if (current / "systems/task.json").is_file():
            protected = True
            break
        current = current.parent
    tasks = store.tasks()
    for bad in store.corrupt_tasks:
        if store._scope(target, [bad["path"]]):
            raise AgentError("task record corrupt, writes inside this task wait for repair or "
                             "ctx system recover --quarantine " + bad["record"])
    protected = protected or any(store._scope(target, t["allowed_paths"]) for t in tasks)
    if not protected:
        return target
    run_id, actor, token = (os.getenv(k) for k in ("CTX_RUN", "CTX_ACTOR", "CTX_RUN_TOKEN"))
    if not run_id or not actor or not token:
        raise AgentError("enrolled task writes require CTX_ACTOR, CTX_RUN and CTX_RUN_TOKEN")
    candidates = [task for task in tasks if store.read(store._record(task["task_id"], "runs", run_id))]
    for task in candidates:
        record = store.read(store._record(task["task_id"], "runs", run_id))
        if record["actor"] != actor or not secrets.compare_digest(record["token_hash"], digest(token.encode())):
            continue
        run = store._run(task["task_id"], run_id, actor, token, "write")
        if not store._scope(target, run["allowed_paths"]):
            raise AgentError("write exceeds leased path scope")
        return target
    raise AgentError("invalid run capability")


def owner_option(p):
    p.add_argument("--owner-token", default=os.getenv("CTX_OWNER_TOKEN"),
                   help="owner credential returned once by enroll (or CTX_OWNER_TOKEN)")


def run_options(p):
    p.add_argument("--run", default=os.getenv("CTX_RUN")); p.add_argument("--token", default=os.getenv("CTX_RUN_TOKEN"))


def main(argv=None, root=None, commit=True):
    parser = argparse.ArgumentParser(prog="ctx system")
    parser.add_argument("--root", default=str(root or Path(__file__).resolve().parent.parent))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("enroll")
    p.add_argument("task"); p.add_argument("--owner", required=True); p.add_argument("--goal", required=True)
    p.add_argument("--criterion", action="append", required=True); p.add_argument("--scope", action="append")
    p.add_argument("--dependency", action="append")
    for name in ("claim", "renew", "release", "acknowledge", "submit"):
        p = sub.add_parser(name); p.add_argument("task"); p.add_argument("--actor", default=os.getenv("CTX_ACTOR"))
        if name != "claim":
            p.add_argument("--run", default=os.getenv("CTX_RUN")); p.add_argument("--token", default=os.getenv("CTX_RUN_TOKEN"))
        if name in ("claim", "renew"):
            p.add_argument("--lease", type=int, default=900)
        if name == "claim":
            p.add_argument("--harness", default="local"); p.add_argument("--scope", action="append")
            p.add_argument("--coordinator"); p.add_argument("--run-id")
            p.add_argument("--action", action="append", choices=["write", "submit", "review"])
            p.add_argument("--operation-id", help="stable dispatch id: a retry returns the same run")
            p.add_argument("--reissue", action="store_true",
                           help="new token for the same active run and actor; the previous token stops working")
            owner_option(p)
        if name == "acknowledge":
            p.add_argument("--manifest", required=True); p.add_argument("--session-receipt")
        if name == "submit":
            p.add_argument("--artifact", action="append", required=True)
    p = sub.add_parser("correct"); p.add_argument("task"); p.add_argument("--actor"); owner_option(p)
    for key in ("old", "replacement", "source"):
        p.add_argument("--" + key, required=True)
    p.add_argument("--affected", action="append"); p.add_argument("--supersedes", action="append")
    p = sub.add_parser("owner-token"); p.add_argument("task"); p.add_argument("--human", required=True)
    p = sub.add_parser("boot"); p.add_argument("task"); p.add_argument("--budget", "--max-chars", type=int, default=9500)
    p.add_argument("--persist", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("send"); p.add_argument("task"); p.add_argument("--kind", choices=sorted(KINDS), required=True)
    p.add_argument("--sender", required=True); p.add_argument("--body", required=True); p.add_argument("--dedupe-key")
    # --actor below is optional: identity comes from the presented credential and must match it.
    p = sub.add_parser("receipt"); p.add_argument("task"); p.add_argument("message_id"); p.add_argument("--actor")
    p.add_argument("--note", default="loaded"); run_options(p); owner_option(p)
    p = sub.add_parser("check"); p.add_argument("task"); p.add_argument("submission_id"); p.add_argument("--actor")
    p.add_argument("--criterion", required=True); p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--command-json"); run_options(p); owner_option(p)
    p.add_argument("--input", action="append", help="file or folder the check reads beyond its argv paths")
    p = sub.add_parser("challenge"); p.add_argument("task"); p.add_argument("submission_id"); p.add_argument("--actor")
    for key in ("criterion", "expected", "observed", "source"):
        p.add_argument("--" + key, required=True)
    run_options(p)
    p = sub.add_parser("resolve"); p.add_argument("task"); p.add_argument("challenge_id"); p.add_argument("--actor")
    p.add_argument("--response", required=True); p.add_argument("--evidence", action="append", required=True)
    p.add_argument("--outcome", choices=["resolved", "accepted-risk", "unresolved"], default="resolved"); owner_option(p)
    p = sub.add_parser("accept"); p.add_argument("task"); p.add_argument("submission_id"); p.add_argument("--actor")
    owner_option(p); p.add_argument("--human", help='Raymond\'s explicit decision: "raymond: <reason>"')
    p = sub.add_parser("relocate-records"); p.add_argument("task"); p.add_argument("--actor"); owner_option(p)
    p = sub.add_parser("review"); p.add_argument("task"); p.add_argument("submission_id"); p.add_argument("--actor")
    run_options(p)
    p.add_argument("--source", required=True); p.add_argument("--evidence", action="append", required=True)
    p.add_argument("--criterion", action="append")
    p = sub.add_parser("view"); p.add_argument("--scope", default="."); p.add_argument("--output", required=True)
    p = sub.add_parser("board"); p.add_argument("--scope", default="."); p.add_argument("--json", action="store_true")
    p = sub.add_parser("recover")
    p.add_argument("--quarantine", metavar="RECORD", help="move an unusable record's exact bytes to a corrupt/ sibling")
    p.add_argument("--abandon", metavar="OPERATION_ID", help="retire a conflicted operation, keeping current files")
    p.add_argument("--human", help='required with --abandon: "raymond: <reason>"')
    try:
        import agent_services
    except ImportError:
        agent_services = None
    if agent_services and hasattr(agent_services, "add_commands"):
        agent_services.add_commands(sub)
    supplied = list(sys.argv[1:] if argv is None else argv)
    executable_argv = None
    if "--" in supplied and "check" in supplied[:supplied.index("--")]:
        separator = supplied.index("--")
        executable_argv, supplied = supplied[separator + 1:], supplied[:separator]
    args = parser.parse_args(supplied)
    store = Store(args.root, commit=commit)
    try:
        name = args.command
        if name == "enroll":
            result = store.enroll(args.task, args.owner, args.goal, args.criterion, args.scope, args.dependency)
        elif name == "claim":
            result = store.claim(args.task, args.actor, args.harness, args.scope, args.lease, args.run_id,
                                 operation_id=args.operation_id, coordinator=args.coordinator, actions=args.action,
                                 owner_token=args.owner_token, reissue=args.reissue)
        elif name == "renew":
            result = store.renew(args.task, args.run, args.actor, args.token, args.lease)
        elif name == "release":
            result = store.release(args.task, args.run, args.actor, args.token)
        elif name == "acknowledge":
            result = store.acknowledge(args.task, args.run, args.actor, args.token,
                                       store.read(args.manifest), args.session_receipt)
        elif name == "correct":
            result = store.correct(args.task, args.actor, args.old, args.replacement, args.source, args.affected,
                                   supersedes=args.supersedes, owner_token=args.owner_token)
        elif name == "owner-token":
            result = store.reissue_owner(args.task, args.human)
        elif name == "boot":
            result = make_boot(args.root, args.task, args.budget, args.persist)
        elif name == "send":
            result = store.send(args.task, args.kind, args.sender, args.body, args.dedupe_key)
        elif name == "receipt":
            result = store.receipt(args.task, args.message_id, args.actor, args.note, args.run, args.token,
                                   owner_token=args.owner_token)
        elif name == "submit":
            result = store.submit(args.task, args.run, args.actor, args.token, args.artifact)
        elif name == "check":
            result = store.check(args.task, args.submission_id, args.actor, args.criterion,
                                 executable_argv if executable_argv is not None else json.loads(args.command_json or "[]"), args.timeout,
                                 run_id=args.run, token=args.token, owner_token=args.owner_token, inputs=args.input)
        elif name == "challenge":
            result = store.challenge(args.task, args.submission_id, args.actor, args.criterion,
                                     args.expected, args.observed, args.source, run_id=args.run, token=args.token)
        elif name == "resolve":
            result = store.resolve(args.task, args.challenge_id, args.actor, args.response, args.evidence, args.outcome,
                                   owner_token=args.owner_token)
        elif name == "relocate-records":
            result = store.reconcile_location(args.task, args.actor, args.owner_token)
        elif name == "review":
            result = store.review(args.task, args.submission_id, args.actor, args.source, args.evidence, args.criterion,
                                  run_id=args.run, token=args.token)
        elif name == "accept":
            result = store.accept(args.task, args.submission_id, args.actor, args.owner_token, args.human)
        elif name == "view":
            import agent_view
            result = agent_view.render(args.root, args.output, args.scope)
        elif name == "board":
            result = store.board(args.scope)
        elif name == "recover":
            if args.quarantine and args.abandon:
                raise AgentError("choose one of --quarantine or --abandon")
            result = (store.quarantine(args.quarantine) if args.quarantine else
                      store.abandon(args.abandon, args.human) if args.abandon else store.recover())
        else:
            result = agent_services.dispatch(args, store)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except HumanUnavailable as exc:
        print("ctx system: " + str(exc), file=sys.stderr)
        return 3
    except (AgentError, OSError, ValueError) as exc:
        print("ctx system: " + str(exc), file=sys.stderr)
        return 1
    except (KeyError, TypeError, AttributeError) as exc:
        # A canonical record had an unexpected shape: name it instead of printing a traceback.
        print("ctx system: malformed canonical record (" + type(exc).__name__ + ": " + str(exc) +
              "); run ctx system recover to list named conflicts", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
