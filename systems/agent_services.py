#!/usr/bin/env python3
"""Source, recovery, maintenance and provider services for the existing ctx engine.

Canonical service records are JSON files written by Agent Store transactions.
The SQLite query view is derived and disposable. No command calls a model,
launches a native app, signs in, schedules work, or deletes a registered resource.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
import uuid
from urllib.parse import quote

from agent_core import AgentError

STATE = "systems/agent-state"
MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif", ".mp4", ".mov",
         ".pdf", ".txt", ".md"}
SCHEMA = 1


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def identifier(value, label="identifier"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise AgentError(f"invalid {label}")
    return value


def safe_relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise AgentError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"..", "."} for part in path.parts):
        raise AgentError("path must be relative without traversal")
    if str(path) != value:
        raise AgentError("path must be normalized")
    return value


def relative(store, value):
    path = Path(value)
    root = Path(store.root).absolute()
    if path.is_absolute():
        try:
            value = str(path.relative_to(root))
        except ValueError as exc:
            raise AgentError("source must be inside the explicit repository root") from exc
    return safe_relative(str(value))


def guarded(store, value):
    """Guard paths even when a caller supplies a test Store with a looser path API."""
    rel = relative(store, value)
    path = Path(store.path(rel))
    root = Path(store.root).absolute()
    candidate = root / rel
    for part in [candidate, *candidate.parents]:
        if part == root.parent:
            break
        if part.is_symlink():
            raise AgentError(f"symlink is not an allowed service input: {rel}")
        if part == root:
            break
    return path


def read(store, rel, default=None):
    value = store.read(rel, default=default)
    if value is None:
        raise AgentError(f"missing record: {rel}")
    return value


def expect(store, paths):
    return {path: file_hash(guarded(store, path)) if guarded(store, path).is_file() else None
            for path in paths}


def write(store, action, writes, expected=None, operation_id=None):
    return store.transaction(action, writes, expected=expected, operation_id=operation_id)


def locked(store):
    # Real Store supplies the same reentrant lock used by transaction/recovery.
    if not hasattr(store, "locked"):
        raise AgentError("consistent service operations require Store.locked()")
    return store.locked()


def source_base(store, project):
    rel = relative(store, project)
    if not guarded(store, rel).is_dir():
        raise AgentError(f"project root missing: {rel}")
    return f"{rel}/systems/sources"


def source_card(store, project, source_id):
    if not re.fullmatch(r"[0-9a-f]{64}", source_id):
        raise AgentError("source id must be a full sha256")
    return read(store, f"{source_base(store, project)}/{source_id}.json")


def cached_extraction(store, cache, sha, suffix, raw):
    result = {"kind": "machine-extraction", "status": "unreviewed", "text": "",
              "engine": None, "error": None, "cache": None, "review": None}
    if suffix in {".mp4", ".mov"}:
        return dict(result, status="not-extracted", error="video content has not been reviewed")
    if suffix in {".txt", ".md"}:
        try:
            return dict(result, text=raw.decode("utf-8"), engine="utf8-original-text")
        except UnicodeError:
            return dict(result, status="failed", error="original is not UTF-8 text")
    if cache:
        cached = guarded(store, f"{relative(store, cache)}/{sha}.json")
        if cached.is_file():
            try:
                record = json.loads(cached.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                return dict(result, status="failed", error="invalid cached extraction")
            if not isinstance(record, dict):
                return dict(result, status="failed", error="cached extraction is not an object")
            if record.get("sha256") != sha:
                return dict(result, status="failed", error="cached extraction hash mismatch")
            text = record.get("text")
            if text is None:
                lines = record.get("lines", [])
                if not isinstance(lines, list) or not all(isinstance(row, dict) for row in lines):
                    return dict(result, status="failed", error="cached extraction lines malformed")
                text = "\n".join(str(row.get("text", "")) for row in lines)
            return dict(result, text=str(text), engine=record.get("engine", "cached-unknown-version"),
                        status="failed" if record.get("error") else "unreviewed",
                        error=record.get("error"), cache=str(cached))
    return dict(result, status="not-extracted", error="no configured cached extraction")


def source_refresh(store, project, roots, cache=None, extensions=None, *, allow_missing_registered_roots=False):
    """Reconcile explicit roots, preserving all old locations and byte identities."""
    if not roots:
        raise AgentError("at least one explicit source root is required")
    base = source_base(store, project)
    roots = sorted(set(relative(store, root) for root in roots))
    allowed = {s.lower() if s.startswith(".") else "." + s.lower()
               for s in (extensions or MEDIA)}
    with locked(store):
        original = read(store, f"{base}/manifest.json", {"items": [], "locations": {}})
        missing_roots = []
        for root in roots:
            path = guarded(store, root)
            if not path.is_dir():
                if allow_missing_registered_roots and root in original.get("roots", []) and not path.exists():
                    missing_roots.append(root)
                else:
                    raise AgentError(f"source root missing, refresh aborted: {root}")
        if cache and not guarded(store, cache).is_dir():
            raise AgentError("configured OCR cache is missing")
        locations = dict(original.get("locations", {}))
        cards = {}
        paths = {}
        for root in roots:
            if root in missing_roots:
                continue
            for candidate in sorted(guarded(store, root).rglob("*")):
                if candidate.is_symlink():
                    raise AgentError(f"symlink inside source root: {candidate}")
                if candidate.is_file() and candidate.suffix.lower() in allowed:
                    rel = relative(store, str(candidate))
                    raw = candidate.read_bytes()
                    sha = digest(raw)
                    paths[rel] = sha
                    card = cards.get(sha)
                    if card is None:
                        card = read(store, f"{base}/{sha}.json", {})
                        if not card:
                            card = {"schema": SCHEMA, "id": sha, "sha256": sha,
                                    "kind": "original", "bytes": len(raw), "first_seen": now(),
                                    "locations": [], "links": [], "meaning": [],
                                    "extraction": cached_extraction(store, cache, sha, candidate.suffix.lower(), raw)}
                        elif cache or candidate.suffix.lower() in {".md", ".txt"}:
                            new_extraction = cached_extraction(store, cache, sha, candidate.suffix.lower(), raw)
                            previous = card.get("extraction", {})
                            if new_extraction["status"] == "unreviewed" and any(new_extraction.get(key) != previous.get(key) for key in ("engine", "text")):
                                card.setdefault("extraction_history", []).append(previous)
                                if previous.get("review"):
                                    new_extraction["review"] = previous["review"]
                                    new_extraction["status"] = "reviewed"
                                card["extraction"] = new_extraction
                            elif previous.get("status") in {"failed", "not-extracted"}:
                                card["extraction"] = new_extraction
                        cards[sha] = card
                    card["last_seen"] = now()
        # Cards outside refreshed roots retain their current scope and locations.
        for item in original.get("items", []):
            sha = item if isinstance(item, str) else item["id"]
            if sha not in cards:
                cards[sha] = read(store, f"{base}/{sha}.json", {})
        changes = []
        for rel, sha in sorted(paths.items()):
            old = locations.get(rel)
            if old and old.get("sha256") != sha:
                changes.append({"path": rel, "kind": "changed-bytes", "old": old["sha256"], "new": sha})
            elif not old:
                prior = [p for p, value in locations.items() if value.get("sha256") == sha]
                changes.append({"path": rel, "kind": "new-location", "sha256": sha,
                                "previous_locations": prior})
            locations[rel] = {"sha256": sha, "available": True, "last_seen": now()}
        for rel, value in locations.items():
            selected = any(rel == root or rel.startswith(root + "/") for root in roots)
            if selected and rel not in paths:
                value["available"] = False
                changes.append({"path": rel, "kind": "unavailable", "sha256": value["sha256"]})
        for sha, card in cards.items():
            if not card:
                raise AgentError(f"manifest references a missing source card: {sha}")
            history = {v["path"]: v for v in card.get("locations", [])}
            for rel, value in locations.items():
                if value["sha256"] == sha:
                    history[rel] = {"path": rel, "original_absolute_path": str(Path(store.root) / rel),
                                    "available": value["available"], "last_seen": value["last_seen"]}
                elif rel in history:
                    history[rel]["available"] = False
                    history[rel]["changed_bytes"] = True
            card["locations"] = list(history.values())
        # External editors need not obey the engine lock, so verify before attribution.
        for rel, sha in paths.items():
            if file_hash(guarded(store, rel)) != sha:
                raise AgentError(f"source changed during extraction, refresh aborted: {rel}")
        summary = {"paths_in_scan": len(paths), "unique_in_scan": len(set(paths.values())),
                   "exact_duplicate_copies": len(paths) - len(set(paths.values())),
                   "historical_cards": len(cards), "unavailable_locations": sum(not x["available"] for x in locations.values()),
                   "unreviewed": sum(c["extraction"]["status"] == "unreviewed" for c in cards.values()),
                   "failed_or_unextracted": sum(c["extraction"]["status"] in {"failed", "not-extracted"} for c in cards.values())}
        if missing_roots:
            summary["missing_registered_roots"] = missing_roots
            summary["registration_boundary"] = "Missing roots retain source history with unavailable locations; a moved folder outside registered roots requires explicit registration"
        manifest = {"schema": SCHEMA, "project": relative(store, project), "generated_at": now(),
                    "roots": sorted(set(original.get("roots", []) + roots)), "scan_roots": roots,
                    "items": sorted(cards), "locations": locations,
                    "summary": summary, "changes": changes, "originals_modified": False}
        writes = {f"{base}/{sha}.json": card for sha, card in cards.items()}
        writes[f"{base}/manifest.json"] = manifest
        receipt = write(store, "source-refresh", writes, expect(store, writes))
        index_rebuild(store, project)
        return {"manifest": manifest, "operation": receipt}


def index_revision(store, project):
    base = source_base(store, project)
    manifest = read(store, f"{base}/manifest.json")
    hashes = [file_hash(guarded(store, f"{base}/manifest.json"))]
    for sha in manifest["items"]:
        path = guarded(store, f"{base}/{identifier(sha)}.json")
        if not path.is_file():
            raise AgentError("source index cannot hide a missing canonical card")
        hashes.append(file_hash(path))
    return digest("\n".join(hashes).encode())


def index_rebuild(store, project):
    """Build a derived SQLite view, never a new authority or a Git input."""
    base = source_base(store, project)
    manifest = read(store, f"{base}/manifest.json")
    target = guarded(store, f"{base}/search.sqlite")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".search-", dir=target.parent)
    os.close(handle)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.execute("CREATE VIRTUAL TABLE sources USING fts5(id UNINDEXED, paths, text, meaning, links)")
            for sha in manifest["items"]:
                card = source_card(store, project, sha)
                extraction = card["extraction"]
                text = extraction.get("review", {}).get("text", extraction.get("text", "")) if extraction.get("review") else extraction.get("text", "")
                db.execute("INSERT INTO sources VALUES (?,?,?,?,?)", (sha,
                           "\n".join(x["path"] for x in card["locations"]), text,
                           json.dumps(card.get("meaning", [])), json.dumps(card.get("links", []))))
            db.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO metadata VALUES (?,?)", ("source_revision", index_revision(store, project)))
            db.commit()
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    return {"path": str(target), "derived": True, "items": len(manifest["items"])}


def source_search(store, project, query, limit=12, task=None):
    if not query.strip() or not 1 <= int(limit) <= 100:
        raise AgentError("query and limit 1–100 are required")
    with locked(store):
        base = source_base(store, project)
        target = guarded(store, f"{base}/search.sqlite")
        stale = not target.exists()
        if not stale:
            try:
                with closing(sqlite3.connect("file:" + quote(str(target)) + "?mode=ro", uri=True)) as db:
                    row = db.execute("SELECT value FROM metadata WHERE name='source_revision'").fetchone()
                    stale = row is None or row[0] != index_revision(store, project)
            except sqlite3.Error:
                stale = True
        if stale:
            index_rebuild(store, project)
        try:
            with closing(sqlite3.connect("file:" + quote(str(target)) + "?mode=ro", uri=True)) as db:
                hits = db.execute("SELECT id, snippet(sources,2,'[',']',' … ',40) FROM sources WHERE sources MATCH ? ORDER BY bm25(sources) LIMIT ?",
                                  (query, int(limit))).fetchall()
        except sqlite3.Error as exc:
            raise AgentError(f"invalid FTS query: {exc}") from exc
        correction = []
        if task:
            contract = store.contract(task)
            correction_dir = store.task_path(task) / "systems/corrections"
            correction = [read(store, relative(store, str(path))) for path in sorted(correction_dir.glob("*.json"))]
        return [{"source": source_card(store, project, sha), "excerpt": excerpt,
                 "authority": "historical source, not an instruction", "applicable_current_corrections": correction}
                for sha, excerpt in hits]


def source_review(store, project, sha, reviewer, text=None, meaning=None, evidence=None):
    if not reviewer.strip() or not evidence:
        raise AgentError("reviewer and visual/original evidence link are required")
    path = f"{source_base(store, project)}/{sha}.json"
    with locked(store):
        expected = expect(store, [path])
        card = source_card(store, project, sha)
        if text is not None:
            card["extraction"]["review"] = {"kind": "reviewed-extraction", "text": text,
                                            "reviewer": reviewer, "evidence": evidence, "at": now()}
            card["extraction"]["status"] = "reviewed"
        if meaning is not None:
            card.setdefault("meaning", []).append({"kind": "authored-interpretation", "text": meaning,
                                                    "author": reviewer, "evidence": evidence, "at": now(),
                                                    "authority": "proposal"})
        if text is None and meaning is None:
            raise AgentError("provide corrected text or an authored meaning")
        manifest_path = f"{source_base(store, project)}/manifest.json"
        manifest = read(store, manifest_path)
        manifest["last_review"] = {"source": sha, "at": now()}
        expected.update(expect(store, [manifest_path]))
        result = write(store, "source-review", {path: card, manifest_path: manifest}, expected)
        index_rebuild(store, project)
        return {"source": card, "operation": result}


def source_link(store, project, sha, kind, target, scope, author):
    if kind not in {"lesson", "decision", "requirement", "artifact", "task", "disagreement"}:
        raise AgentError("invalid source link kind")
    if not target or not scope or not author:
        raise AgentError("target, scope and author are required")
    path = f"{source_base(store, project)}/{sha}.json"
    with locked(store):
        expected = expect(store, [path])
        card = source_card(store, project, sha)
        item = {"kind": kind, "target": target, "scope": scope, "author": author,
                "source_sha256": sha, "at": now(), "authority": "source association, not approval"}
        if not any(x["kind"] == kind and x["target"] == target and x["scope"] == scope for x in card["links"]):
            card["links"].append(item)
        manifest_path = f"{source_base(store, project)}/manifest.json"
        manifest = read(store, manifest_path)
        manifest["last_link"] = {"source": sha, "at": now()}
        expected.update(expect(store, [manifest_path]))
        result = write(store, "source-link", {path: card, manifest_path: manifest}, expected)
        index_rebuild(store, project)
        return {"source": card, "operation": result}


def dependencies_add(store, project, source, target, relation, evidence, reviewed=False):
    """Edges pin exact bytes. A path rename is stale until deliberately repaired."""
    base = relative(store, project)
    guarded(store, base)
    source = relative(store, source)
    target = relative(store, target)
    if not guarded(store, source).is_file() or not guarded(store, target).is_file():
        raise AgentError("dependency endpoints must be existing files")
    if not relation.strip() or not evidence:
        raise AgentError("relationship and evidence are required")
    path = f"{base}/systems/dependencies.json"
    with locked(store):
        expected = expect(store, [path])
        graph = read(store, path, {"schema": SCHEMA, "project": base, "edges": []})
        key = digest(f"{source}\0{target}\0{relation}".encode())[:24]
        edge = {"id": key, "source": source, "target": target, "relation": relation,
                "source_sha256": file_hash(guarded(store, source)), "target_sha256": file_hash(guarded(store, target)),
                "evidence": evidence, "reviewed": bool(reviewed), "status": "current", "at": now()}
        graph["edges"] = [e for e in graph["edges"] if e["id"] != key] + [edge]
        graph["updated_at"] = now()
        result = write(store, "dependency-add", {path: graph}, expected)
        return {"edge": edge, "operation": result}


def dependencies_scan(store, project, discover=False):
    path = f"{relative(store, project)}/systems/dependencies.json"
    with locked(store):
        expected = expect(store, [path])
        graph = read(store, path, {"schema": SCHEMA, "project": relative(store, project), "edges": []})
        for edge in graph["edges"]:
            issues = []
            for field in ("source", "target"):
                endpoint = guarded(store, edge[field])
                if not endpoint.is_file():
                    issues.append({"endpoint": field, "reason": "missing-or-renamed", "path": edge[field]})
                elif file_hash(endpoint) != edge[field + "_sha256"]:
                    issues.append({"endpoint": field, "reason": "changed-bytes", "path": edge[field]})
            edge["status"] = "stale" if issues else "current"
            edge["stale_reasons"] = issues
        graph["proposals"] = []
        if discover:
            # Conservative Python import discovery, never treated as confirmed architecture.
            project_path = guarded(store, project)
            modules = {str(p.relative_to(project_path).with_suffix("")).replace(os.sep, "."): p
                       for p in project_path.rglob("*.py") if not p.is_symlink()}
            for module, source in modules.items():
                try:
                    tree = ast.parse(source.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeError):
                    continue
                for node in ast.walk(tree):
                    names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
                    for name in names:
                        if name in modules and modules[name] != source:
                            graph["proposals"].append({"source": relative(store, str(source)), "target": relative(store, str(modules[name])),
                                                       "relation": "python-import", "evidence": f"{relative(store, str(source))}:{node.lineno}",
                                                       "status": "proposal", "reviewed": False})
        graph["checked_at"] = now()
        result = write(store, "dependency-scan", {path: graph}, expected)
        return {"graph": graph, "operation": result}


def external_destination(value):
    path = Path(value).absolute()
    if not Path(value).is_absolute():
        raise AgentError("destination must be an explicit absolute path")
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise AgentError("destination cannot contain a symlink")
    return path


def credential_name(path):
    parts = [part.lower() for part in Path(path).parts]
    return any(part in {".git", ".env", "credentials", "credentials.json", "auth.json", "secrets.json"}
               or part.startswith(".env.") or part.endswith((".pem", ".key", ".p12", ".pfx")) for part in parts)


def backup_create(store, includes, destination, exclusions=(), backup_id=None):
    """Snapshot an explicit allowlist under the writer lock, using SQLite backup API."""
    if not includes:
        raise AgentError("backup needs an explicit path allowlist")
    backup_id = identifier(backup_id or "backup-" + uuid.uuid4().hex)
    destination = external_destination(destination)
    target = destination / backup_id
    if target.exists():
        raise AgentError("backup set already exists, refusing replacement")
    includes = sorted(set(relative(store, value) for value in includes))
    exclusions = sorted(set(relative(store, value) for value in exclusions))
    selected = {}
    excluded = []
    stage = None
    with locked(store):
        for allow in includes:
            source = guarded(store, allow)
            if not source.exists():
                raise AgentError(f"allowlisted backup source missing: {allow}")
            # Destination inside an included directory would recursively capture itself.
            if source.is_dir() and (destination == source or source in destination.parents):
                raise AgentError("backup destination cannot be inside an included source")
            candidates = [source] if source.is_file() else sorted(source.rglob("*"))
            for candidate in candidates:
                if candidate.is_symlink():
                    raise AgentError(f"backup symlink refused: {candidate}")
                if not candidate.is_file():
                    continue
                rel = relative(store, str(candidate))
                denied = credential_name(rel) or any(rel == value or rel.startswith(value + "/") for value in exclusions)
                if denied:
                    excluded.append({"path": rel, "reason": "credential-name-exclusion" if credential_name(rel) else "configured-exclusion"})
                else:
                    selected[rel] = candidate
        # A suffix does not identify a SQLite sidecar. Only omit it when the
        # corresponding selected database will actually receive an online snapshot.
        sqlite_selected = set()
        for rel, candidate in selected.items():
            with candidate.open("rb") as stream:
                if stream.read(16) == b"SQLite format 3\x00":
                    sqlite_selected.add(rel)
        for rel, candidate in list(selected.items()):
            if candidate.name.endswith(("-wal", "-shm", "-journal")):
                database_rel = rel.rsplit("-", 1)[0]
                if database_rel in sqlite_selected:
                    excluded.append({"path": rel, "reason": "sqlite-sidecar-covered-by-online-backup",
                                     "database": database_rel})
                    del selected[rel]
        if not selected:
            raise AgentError("backup allowlist contains no permitted files")
        destination.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".backup-", dir=destination))
        manifest = {"schema": SCHEMA, "id": backup_id, "created_at": now(),
                    "source_root": str(Path(store.root).absolute()), "allowlist": includes,
                    "configured_exclusions": exclusions, "exclusions": excluded, "files": [],
                    "destination": str(target), "encryption": "not-configured",
                    "off_device": "not-established", "status": "snapshot"}
        try:
            for rel, source in sorted(selected.items()):
                copied = stage / "files" / rel
                copied.parent.mkdir(parents=True, exist_ok=True)
                original_hash = file_hash(source)
                with source.open("rb") as stream:
                    header = stream.read(16)
                is_sqlite = header == b"SQLite format 3\x00"
                if is_sqlite != (rel in sqlite_selected):
                    raise AgentError(f"backup source type changed during snapshot: {rel}")
                if is_sqlite:
                    # Snapshot into a private scratch database, convert it to a rollback journal and
                    # close it, then copy that one self-contained file: no -wal/-shm sidecar can reach
                    # the bundle (older SQLite left the snapshot's -shm beside it).
                    scratch = Path(tempfile.mkdtemp(prefix=".sqlite-snapshot-", dir=destination))
                    try:
                        scratch_db = scratch / "snapshot.sqlite"
                        # URI read-only is important: backup must not create a missing source DB.
                        with closing(sqlite3.connect("file:" + quote(str(source)) + "?mode=ro", uri=True)) as original_db:
                            with closing(sqlite3.connect(scratch_db)) as snapshot_db:
                                original_db.backup(snapshot_db)
                                mode = snapshot_db.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                                check = snapshot_db.execute("PRAGMA integrity_check").fetchone()[0]
                                if str(mode).lower() != "delete" or check != "ok":
                                    raise AgentError(f"SQLite snapshot not self-contained or not intact: {rel}")
                        shutil.copyfile(scratch_db, copied)
                    finally:
                        shutil.rmtree(scratch)  # this call's own scratch directory only
                    with copied.open("rb") as stream:
                        if stream.read(20)[18:20] != b"\x01\x01":
                            raise AgentError(f"SQLite snapshot still requires a WAL sidecar: {rel}")
                else:
                    shutil.copyfile(source, copied)
                    if original_hash != file_hash(copied) or original_hash != file_hash(source):
                        raise AgentError(f"backup source changed during snapshot: {rel}")
                manifest["files"].append({"path": rel, "original_path": str(source),
                                          "sha256": file_hash(copied), "source_file_sha256": original_hash,
                                          "bytes": copied.stat().st_size,
                                          "snapshot_method": "sqlite-online-backup" if is_sqlite else "writer-locked-copy"})
            # Recheck all non-DB originals before establishing the consistent boundary.
            for record in manifest["files"]:
                if record["snapshot_method"] != "sqlite-online-backup" and file_hash(selected[record["path"]]) != record["source_file_sha256"]:
                    raise AgentError(f"backup changed source at boundary: {record['path']}")
            manifest_path = stage / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            verified = backup_verify(stage)
            if not verified["valid"]:
                raise AgentError("backup read-back failed")
            # No replacement of an existing set, including concurrent/external creation.
            if target.exists():
                raise AgentError("backup set appeared during snapshot")
            stage.rename(target)
            stage = None
            receipt = {"schema": SCHEMA, "id": backup_id, "destination": str(target),
                       "manifest_sha256": file_hash(target / "manifest.json"), "created_at": now(),
                       "files": len(manifest["files"]), "read_back_verified": True,
                       "isolated_restore_verified": False, "off_device": "not-established"}
            operation = write(store, "backup-create", {f"{STATE}/backups/{backup_id}.json": receipt})
            return {"backup": receipt, "manifest": manifest, "operation": operation}
        finally:
            if stage is not None:
                # This command owns only its newly-created temporary staging tree.
                shutil.rmtree(stage)


def backup_verify(bundle, expected_manifest_sha256=None):
    bundle = external_destination(bundle)
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise AgentError("backup manifest missing or symlinked")
    if expected_manifest_sha256 and file_hash(manifest_path) != expected_manifest_sha256:
        raise AgentError("backup manifest changed since canonical receipt")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise AgentError("backup manifest corrupt") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or not isinstance(manifest.get("files"), list) or not manifest["files"]:
        raise AgentError("unsupported or empty backup manifest")
    identifier(manifest.get("id"), "backup id")
    observed = set()
    failures = []
    for record in manifest["files"]:
        if not isinstance(record, dict):
            raise AgentError("malformed backup file record")
        rel = safe_relative(record.get("path"))
        if rel in observed:
            raise AgentError("duplicate path in backup manifest")
        observed.add(rel)
        path = bundle / "files" / rel
        for parent in [path, *path.parents]:
            if parent.is_symlink():
                raise AgentError("symlink in backup bundle")
            if parent == bundle:
                break
        if not path.is_file():
            failures.append({"path": rel, "reason": "missing"})
        elif not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))) or file_hash(path) != record["sha256"]:
            failures.append({"path": rel, "reason": "hash-mismatch"})
        elif path.stat().st_size != record.get("bytes"):
            failures.append({"path": rel, "reason": "size-mismatch"})
    actual = set()
    files_root = bundle / "files"
    if files_root.is_symlink():
        raise AgentError("symlinked backup files root")
    for path in files_root.rglob("*"):
        if path.is_symlink():
            raise AgentError("symlink in backup bundle")
        if path.is_file():
            actual.add(str(path.relative_to(files_root)))
    for extra in actual - observed:
        failures.append({"path": extra, "reason": "unmanifested-file"})
    return {"valid": not failures, "files": len(observed), "failures": failures,
            "manifest": manifest, "manifest_sha256": file_hash(manifest_path)}


def backup_restore(bundle, destination, store=None):
    bundle = external_destination(bundle)
    destination = external_destination(destination)
    if destination.exists():
        raise AgentError("restore requires a new isolated directory, refusing existing destination")
    checked = backup_verify(bundle)
    if not checked["valid"]:
        raise AgentError("backup verification failed, restore aborted")
    if store is not None:
        known_receipt = store.read(f"{STATE}/backups/{checked['manifest']['id']}.json")
        if known_receipt and known_receipt.get("manifest_sha256") != checked["manifest_sha256"]:
            raise AgentError("backup manifest changed since canonical receipt")
    if destination == bundle or bundle in destination.parents:
        raise AgentError("restore destination cannot be inside backup bundle")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".restore-", dir=destination.parent))
    try:
        for record in checked["manifest"]["files"]:
            rel = safe_relative(record["path"])
            target = stage / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bundle / "files" / rel, target)
            if file_hash(target) != record["sha256"]:
                raise AgentError("restore read-back hash mismatch")
        if destination.exists():
            raise AgentError("restore destination appeared during copy")
        stage.rename(destination)
        stage = None
        result = {"backup_id": checked["manifest"]["id"], "destination": str(destination),
                  "files": checked["files"], "isolated_restore_verified": True,
                  "original_relative_paths_preserved": True, "restored_at": now(),
                  "exclusions": checked["manifest"].get("exclusions", [])}
        if store is not None:
            receipt_path = f"{STATE}/backups/{result['backup_id']}.json"
            with locked(store):
                expected = expect(store, [receipt_path])
                receipt = read(store, receipt_path, {})
                receipt.update({key: value for key, value in result.items() if key != "destination"})
                receipt["restore_destination"] = str(destination)
                receipt["manifest_sha256"] = checked["manifest_sha256"]
                result["operation"] = write(store, "backup-restore-receipt", {receipt_path: receipt}, expected)
        return result
    finally:
        if stage is not None:
            shutil.rmtree(stage)


def resource_register(store, task, resource_id, owner, kind, location, references=(), unfinished=(), recovery=None):
    resource_id = identifier(resource_id, "resource id")
    contract = store.contract(task)
    if not owner or not kind or not location:
        raise AgentError("owner, kind and location are required")
    # References are validated at registration rather than becoming phantom consumers.
    references = [store.contract(ref)["task_id"] for ref in references]
    task_path = relative(store, str(store.task_path(task)))
    path = f"{task_path}/systems/resources/{resource_id}.json"
    with locked(store):
        if guarded(store, path).exists():
            raise AgentError("resource already registered")
        record = {"schema": SCHEMA, "id": resource_id, "task_id": contract["task_id"],
                  "owner": owner, "kind": kind, "location": location, "references": sorted(set(references)),
                  "unfinished": list(unfinished), "recovery": recovery, "status": "active", "history": [], "at": now()}
        result = write(store, "resource-register", {path: record}, {path: None})
        return {"resource": record, "operation": result}


def resource_list(store, task=None):
    tasks = [store.contract(task)] if task else store.tasks()
    records = []
    for contract in tasks:
        resource_dir = store.task_path(contract["task_id"]) / "systems/resources"
        if resource_dir.is_symlink():
            raise AgentError("symlinked resource registry")
        if resource_dir.is_dir():
            for path in sorted(resource_dir.glob("*.json")):
                records.append(read(store, relative(store, str(path))))
    return records


def resource_update(store, task, resource_id, owner, evidence, references=None, unfinished=None, recovery=None):
    """Owner records completed work or changed consumers without erasing history."""
    if not evidence:
        raise AgentError("resource update needs evidence")
    path = f"{relative(store, str(store.task_path(task)))}/systems/resources/{identifier(resource_id)}.json"
    with locked(store):
        expected = expect(store, [path])
        record = read(store, path)
        if record["owner"] != owner or record["status"] != "active":
            raise AgentError("only the active resource owner can update it")
        before = {k: record[k] for k in ("references", "unfinished", "recovery")}
        if references is not None:
            record["references"] = sorted(set(store.contract(ref)["task_id"] for ref in references))
        if unfinished is not None:
            record["unfinished"] = list(unfinished)
        if recovery is not None:
            record["recovery"] = recovery
        record["history"].append({"kind": "update", "before": before, "evidence": evidence, "owner": owner, "at": now()})
        return {"resource": record, "operation": write(store, "resource-update", {path: record}, expected)}


def resource_retire(store, task, resource_id, owner, reason, released=False):
    resource_id = identifier(resource_id)
    path = f"{relative(store, str(store.task_path(task)))}/systems/resources/{resource_id}.json"
    with locked(store):
        expected = expect(store, [path])
        record = read(store, path)
        if owner != record["owner"]:
            raise AgentError("resource retirement requires the registered owner")
        if not reason:
            raise AgentError("resource retirement needs a reason")
        unfinished = list(record["unfinished"])
        for ref in record["references"]:
            consumer = store.contract(ref)
            if consumer.get("state") not in {"done", "complete"}:
                unfinished.append(f"consumer {ref} is {consumer.get('state', 'unfinished')}")
        owning = store.contract(task)
        if owning.get("state") not in {"done", "complete"} and not released:
            unfinished.append("owning task unfinished and owner has not explicitly released it")
        if unfinished:
            raise AgentError("retirement blocked: " + "; ".join(unfinished))
        if not record.get("recovery"):
            raise AgentError("retirement requires a recovery pointer")
        record["history"].append({"status": record["status"], "at": now(), "reason": reason, "owner": owner})
        record["status"] = "retired"
        record["retired_at"] = now()
        record["destructive_action"] = False
        result = write(store, "resource-retire", {path: record}, expected)
        return {"resource": record, "operation": result}


CAPABILITIES = {"boot", "usage", "launch", "wake", "interrupt", "artifact", "export"}
CAPABILITY_STATUS = {"observed", "documented", "manual", "unsupported"}
ADAPTERS_PATH = f"{STATE}/adapters.json"


def adapter_defaults():
    result = {}
    for name in ("codex", "claude", "hermes", "grok", "jev", "cheap-provider"):
        result[name] = {"schema": SCHEMA, "id": name,
                        "role": "baseline" if name in {"codex", "claude"} else "optional",
                        "transport": "manual-file-contract", "capabilities": {
                            "boot": {"status": "documented", "evidence": "local canonical boot packet protocol"},
                            "artifact": {"status": "manual", "evidence": "local artifact receipt protocol"},
                            **{cap: {"status": "unsupported", "evidence": "no native integration observed"}
                               for cap in CAPABILITIES - {"boot", "artifact"}}},
                        "native_activation": "not-observed", "cost": {"status": "unknown"},
                        "config": {}, "authority": "current task contract"}
    return {"schema": SCHEMA, "adapters": result}


def adapter_list(store):
    return read(store, ADAPTERS_PATH, adapter_defaults())


def adapter_register(store, adapter_id, capabilities, config=None, role="optional", evidence=None):
    adapter_id = identifier(adapter_id, "adapter id")
    if role not in {"baseline", "optional"}:
        raise AgentError("invalid adapter role")
    if not isinstance(capabilities, dict) or set(capabilities) - CAPABILITIES:
        raise AgentError("unknown adapter capability")
    values = {}
    for name in CAPABILITIES:
        value = capabilities.get(name, {"status": "unsupported", "evidence": "not configured"})
        if isinstance(value, str):
            value = {"status": value, "evidence": evidence}
        if value.get("status") not in CAPABILITY_STATUS or not value.get("evidence"):
            raise AgentError("capabilities require a valid status and evidence")
        values[name] = value
    # Config is a template/data record only. No subprocess or network execution seam.
    config = config or {}
    if not isinstance(config, dict):
        raise AgentError("adapter config must be an object")
    if any(re.search(r"secret|password|api.?key|token", key, re.I) for key in config):
        raise AgentError("adapter config stores credential references, never credentials")
    with locked(store):
        expected = expect(store, [ADAPTERS_PATH])
        registry = adapter_list(store)
        old = registry["adapters"].get(adapter_id)
        record = {"schema": SCHEMA, "id": adapter_id, "role": role, "transport": "manual-file-contract",
                  "capabilities": values, "config": config, "cost": {"status": "unknown"},
                  "native_activation": "observed" if evidence and any(v["status"] == "observed" for v in values.values()) else "not-observed",
                  "authority": "current task contract", "updated_at": now(),
                  "history": (old or {}).get("history", []) + ([{k: v for k, v in old.items() if k != "history"}] if old else [])}
        # A documented/observed native launch does not make this implementation a launcher.
        record["engine_launch"] = "unsupported, use manual contract export and receipt"
        registry["adapters"][adapter_id] = record
        result = write(store, "adapter-register", {ADAPTERS_PATH: registry}, expected)
        return {"adapter": record, "operation": result}


def adapter_dispatch(store, task, adapter_id, actor, requirement_rev, key, payload, run_id=None):
    """Export a stable assignment, retaining idempotence across retry/reconnect."""
    adapter_id = identifier(adapter_id)
    if not key or not isinstance(payload, dict):
        raise AgentError("idempotence key and object payload are required")
    with locked(store):
        contract = store.contract(task)
        if actor != contract["owner"]:
            raise AgentError("dispatch requires the task owner")
        if int(requirement_rev) != contract["requirement_rev"]:
            raise AgentError("dispatch requirement revision is stale")
        registry = adapter_list(store)
        if adapter_id not in registry["adapters"]:
            raise AgentError("adapter not registered")
        scopes = payload.get("allowed_paths", contract["allowed_paths"])
        for scope in scopes:
            rel = relative(store, scope)
            if not any(rel == allowed or rel.startswith(allowed + "/") for allowed in contract["allowed_paths"]):
                raise AgentError("adapter payload exceeds task path scope")
        assignment_id = "dispatch-" + digest((contract["task_id"] + "\0" + key).encode())[:32]
        path = f"{STATE}/dispatches/{assignment_id}.json"
        signature = digest(json.dumps({"adapter": adapter_id, "payload": payload, "run_id": run_id,
                                       "actor": actor, "rev": int(requirement_rev)}, sort_keys=True).encode())
        existing = store.read(path)
        if existing:
            if existing["signature"] != signature:
                raise AgentError("idempotence key already used for a different assignment")
            return dict(existing, duplicate=True)
        if run_id:
            run = read(store, f"{relative(store, str(store.task_path(task)))}/systems/runs/{identifier(run_id)}.json")
            if run.get("task_id") != contract["task_id"] or run.get("requirement_rev") != contract["requirement_rev"]:
                raise AgentError("adapter run does not match task requirement")
        boot = store.boot(task, max_chars=9500, persist=False)
        record = {"schema": SCHEMA, "id": assignment_id, "task_id": contract["task_id"],
                  "requirement_rev": contract["requirement_rev"], "actor": actor, "adapter": adapter_id,
                  "run_id": run_id, "idempotence_key": key, "signature": signature, "payload": payload,
                  "allowed_paths": scopes, "criteria": contract["criteria"], "boot": boot,
                  "status": "blocked-context" if boot["manifest"].get("blocked") else "queued-manual",
                  "launch": "unsupported by this engine", "capability": registry["adapters"][adapter_id],
                  "events": [{"type": "queued", "at": now()}], "receipts": [], "created_at": now()}
        operation = write(store, "adapter-dispatch", {path: record}, {path: None}, operation_id=assignment_id)
        return dict(record, operation=operation, duplicate=False)


def adapter_receipt(store, assignment_id, receipt_id, adapter_id, requirement_rev, status, evidence,
                    artifacts=None, usage=None):
    assignment_id = identifier(assignment_id)
    receipt_id = identifier(receipt_id)
    if status not in {"received", "manual-start-observed", "partial", "submitted", "failed", "unsupported"}:
        raise AgentError("invalid adapter receipt status")
    if not evidence:
        raise AgentError("receipt requires observable evidence")
    path = f"{STATE}/dispatches/{assignment_id}.json"
    with locked(store):
        expected = expect(store, [path])
        record = read(store, path)
        contract = store.contract(record["task_id"])
        if record["adapter"] != adapter_id:
            raise AgentError("adapter does not own this assignment")
        if int(requirement_rev) != record["requirement_rev"]:
            raise AgentError("receipt does not match assignment requirement")
        artifacts = artifacts or []
        for rel in artifacts:
            rel = relative(store, rel)
            if not any(rel == allowed or rel.startswith(allowed + "/") for allowed in record["allowed_paths"]):
                raise AgentError("receipt artifact exceeds assigned scope")
            if not guarded(store, rel).is_file():
                raise AgentError("receipt artifact missing")
        stale = record["requirement_rev"] != contract["requirement_rev"]
        receipt = {"id": receipt_id, "adapter": adapter_id, "status": status, "evidence": evidence,
                   "requirement_rev": int(requirement_rev), "stale": stale,
                   "artifacts": {relative(store, p): file_hash(guarded(store, p)) for p in artifacts},
                   "usage": usage, "at": now(), "acceptance": "not established by provider receipt"}
        previous = next((r for r in record["receipts"] if r["id"] == receipt_id), None)
        if previous:
            if {k: v for k, v in previous.items() if k not in {"at", "stale"}} != {k: v for k, v in receipt.items() if k not in {"at", "stale"}}:
                raise AgentError("receipt id was reused with changed evidence")
            return dict(record, duplicate=True)
        record["receipts"].append(receipt)
        record["events"].append({"type": "receipt", "id": receipt_id, "at": now()})
        record["status"] = "stale-receipt" if stale else status
        operation = write(store, "adapter-receipt", {path: record}, expected)
        return dict(record, operation=operation, duplicate=False)


def current_acceptance(store, task, acceptance_id):
    acceptance_id = identifier(acceptance_id)
    contract = store.contract(task)
    record = read(store, f"{relative(store, str(store.task_path(task)))}/systems/acceptances/{acceptance_id}.json")
    if record.get("task_id") != contract["task_id"] or record.get("stale") or record.get("requirement_rev") != contract["requirement_rev"]:
        raise AgentError("acceptance evidence is stale or belongs to another task")
    for rel, sha in record.get("artifacts", {}).items():
        if not guarded(store, rel).is_file() or file_hash(guarded(store, rel)) != sha:
            raise AgentError("accepted artifact changed after evidence")
    return record


def maintenance_propose(store, method=None, task_evidence=(), scope="workspace"):
    """Produce inspectable drift/skill proposals, never modify a rule or scheduler."""
    with locked(store):
        tasks = store.tasks()
        drift = []
        for contract in tasks:
            task_path = store.task_path(contract["task_id"])
            for group in ("acceptances", "evidence", "submissions"):
                for path in sorted((task_path / "systems" / group).glob("*.json")):
                    record = read(store, relative(store, str(path)))
                    if record.get("stale") or record.get("requirement_rev") != contract["requirement_rev"]:
                        drift.append({"kind": "stale-evidence", "task_id": contract["task_id"], "path": relative(store, str(path))})
        evidence = []
        for task, acceptance_id in task_evidence:
            acceptance = current_acceptance(store, task, acceptance_id)
            evidence.append({"task_id": store.contract(task)["task_id"], "acceptance_id": acceptance_id,
                             "requirement_rev": acceptance["requirement_rev"],
                             "path": f"{relative(store, str(store.task_path(task)))}/systems/acceptances/{acceptance_id}.json"})
        distinct = {item["task_id"] for item in evidence}
        promotion = None
        if method:
            promotion = {"method": method, "scope": scope, "evidence": evidence,
                         "status": "eligible-for-human-review" if len(distinct) >= 2 else "insufficient-task-evidence",
                         "required_distinct_tasks": 2, "observed_distinct_tasks": len(distinct),
                         "proposed_change": "review and draft a scoped skill", "authority": "proposal",
                         "automatic_rule_edit": False, "semantic_method_equivalence": "requires reviewer"}
        stable_id = "proposal-" + digest(json.dumps({"method": method, "scope": scope, "evidence": evidence, "drift": drift}, sort_keys=True).encode())[:24]
        path = f"{STATE}/maintenance/{stable_id}.json"
        record = {"schema": SCHEMA, "id": stable_id, "at": now(), "drift": drift, "promotion": promotion,
                  "rules_modified": False, "scheduler_created": False, "status": "proposal"}
        operation = write(store, "maintenance-propose", {path: record}, expect(store, [path]))
        return {"proposal": record, "operation": operation}


def nonnegative(value, label):
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise AgentError(f"{label} must be a finite nonnegative number")
    return value


def cost_record(store, task, provider, attempt_id, evidence, usage_cost=None, rework_minutes=None,
                human_hourly_rate=None, currency="USD", acceptance_id=None):
    attempt_id = identifier(attempt_id)
    provider = identifier(provider)
    if not evidence or not re.fullmatch(r"[A-Z]{3}", currency):
        raise AgentError("measured usage evidence and currency are required")
    usage_cost = nonnegative(usage_cost, "usage cost")
    rework_minutes = nonnegative(rework_minutes, "human rework")
    human_hourly_rate = nonnegative(human_hourly_rate, "human hourly rate")
    with locked(store):
        contract = store.contract(task)
        if acceptance_id:
            current_acceptance(store, task, acceptance_id)
        record = {"schema": SCHEMA, "id": attempt_id, "task_id": contract["task_id"],
                  "requirement_rev": contract["requirement_rev"], "provider": provider,
                  "usage_cost": usage_cost, "human_rework_minutes": rework_minutes,
                  "human_hourly_rate": human_hourly_rate, "currency": currency, "evidence": evidence,
                  "acceptance_id": acceptance_id, "quality": "accepted" if acceptance_id else "unverified",
                  "total_cost": usage_cost + rework_minutes / 60 * human_hourly_rate if None not in (usage_cost, rework_minutes, human_hourly_rate) else None,
                  "at": now(), "measurement": "caller-supplied actual observation, not estimated model score"}
        path = f"{STATE}/costs/{attempt_id}.json"
        existing = store.read(path)
        if existing:
            if {k: v for k, v in existing.items() if k != "at"} != {k: v for k, v in record.items() if k != "at"}:
                raise AgentError("cost attempt id already records different evidence")
            return dict(existing, duplicate=True)
        operation = write(store, "cost-record", {path: record}, {path: None})
        return dict(record, operation=operation, duplicate=False)


def cost_compare(store, providers, tasks=None):
    if len(set(providers)) < 2:
        raise AgentError("comparison requires at least two providers")
    providers = sorted(set(identifier(p) for p in providers))
    with locked(store):
        records = [read(store, relative(store, str(path))) for path in sorted(guarded(store, f"{STATE}/costs").glob("*.json"))]
        requested = {store.contract(task)["task_id"] for task in tasks} if tasks else None
        by_key = {}
        for record in records:
            if record["provider"] not in providers or (requested is not None and record["task_id"] not in requested):
                continue
            contract = store.contract(record["task_id"])
            if record["requirement_rev"] != contract["requirement_rev"]:
                continue
            by_key.setdefault((record["task_id"], record["requirement_rev"]), {}).setdefault(record["provider"], []).append(record)
        comparable = {key: value for key, value in by_key.items() if set(value) == set(providers)}
        rows = []
        for (task_id, rev), group in sorted(comparable.items()):
            for provider, attempts in group.items():
                accepted = False
                for attempt in attempts:
                    if attempt.get("acceptance_id"):
                        try:
                            current_acceptance(store, task_id, attempt["acceptance_id"])
                            accepted = True
                        except AgentError:
                            pass
                currencies = {a["currency"] for a in attempts}
                complete = len(currencies) == 1 and all(a["total_cost"] is not None for a in attempts)
                rows.append({"task_id": task_id, "requirement_rev": rev, "provider": provider,
                             "attempts": len(attempts), "accepted_output": accepted,
                             "currency": next(iter(currencies)) if len(currencies) == 1 else None,
                             "measured_total_cost": sum(a["total_cost"] for a in attempts) if complete else None,
                             "usage_cost": sum(a["usage_cost"] for a in attempts) if all(a["usage_cost"] is not None for a in attempts) else None,
                             "human_rework_minutes": sum(a["human_rework_minutes"] for a in attempts) if all(a["human_rework_minutes"] is not None for a in attempts) else None,
                             "evidence": [a["evidence"] for a in attempts], "measurement_complete": complete})
        eligible = bool(rows) and all(r["measurement_complete"] and r["accepted_output"] for r in rows) and len({r["currency"] for r in rows}) == 1
        totals = {provider: sum(r["measured_total_cost"] for r in rows if r["provider"] == provider) for provider in providers} if eligible else None
        return {"same_task_revision_count": len(comparable), "rows": rows, "totals": totals,
                "comparison_supported": eligible, "decision": "review measured totals and acceptance" if eligible else "insufficient comparable evidence",
                "unmatched_task_revisions": [{"task_id": key[0], "requirement_rev": key[1], "providers": sorted(value)}
                                             for key, value in by_key.items() if key not in comparable],
                "automatic_provider_change": False}


def view_records(store, scope="."):
    """Read-only presentation projection. A page cannot create an index or decision."""
    root = Path(store.root) if scope == "." else guarded(store, scope)
    if not root.is_dir():
        raise AgentError("view scope missing")
    result = {"sources": [], "dependencies": [], "resources": [], "recovery": [],
              "adapters": [], "dispatches": [], "health": {"observations": [], "native_trials": "deferred"}}
    with locked(store):
        for base, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".venv", "__pycache__", "full", "ocr"}
                       and not (Path(base) / d).is_symlink()]
            folder = Path(base)
            if folder.name == "sources" and folder.parent.name == "systems":
                for name in files:
                    if re.fullmatch(r"[0-9a-f]{64}\.json", name):
                        value = read(store, relative(store, str(folder / name)))
                        value["record_path"] = relative(store, str(folder / name))
                        result["sources"].append(value)
            if folder.name == "systems" and "dependencies.json" in files:
                graph = read(store, relative(store, str(folder / "dependencies.json")))
                result["dependencies"].extend(graph.get("edges", []))
            if folder.name == "resources" and folder.parent.name == "systems":
                for name in files:
                    if name.endswith(".json"):
                        value = read(store, relative(store, str(folder / name)))
                        result["resources"].append(value)
                        result["recovery"].append(dict(value, record_kind="resource"))
        for group, target in (("operations", "recovery"), ("backups", "recovery"), ("dispatches", "dispatches")):
            for path in sorted(guarded(store, f"{STATE}/{group}").glob("*.json")):
                value = read(store, relative(store, str(path)))
                result[target].append(dict(value, record_kind=group.rstrip("s")))
        result["adapters"] = list(adapter_list(store)["adapters"].values())
        result["health"].update({"source_cards": len(result["sources"]),
            "unavailable_source_locations": sum(not location.get("available", False) for card in result["sources"] for location in card.get("locations", [])),
            "unreviewed_sources": sum(card.get("extraction", {}).get("status") != "reviewed" for card in result["sources"]),
            "stale_dependencies": sum(edge.get("status") == "stale" for edge in result["dependencies"]),
            "active_resources": sum(resource.get("status") == "active" for resource in result["resources"]),
            "queued_adapters": sum(d.get("status") in {"queued-manual", "blocked-context"} for d in result["dispatches"]),
            "authority": "canonical files, read-only projection"})
    return result


def json_file(value):
    try:
        return json.loads(Path(value).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise AgentError(f"invalid JSON input file: {value}") from exc


def add_commands(subparsers):
    def group(name, actions):
        parser = subparsers.add_parser(name)
        sub = parser.add_subparsers(dest="service_action", required=True)
        return {action: sub.add_parser(action) for action in actions}

    def project(parser):
        parser.add_argument("--project", required=True, help="explicit project root inside the workspace")

    p = group("sources", ("refresh", "search", "review", "link"))
    for parser in p.values():
        project(parser)
    p["refresh"].add_argument("--root", action="append", required=True, dest="roots")
    p["refresh"].add_argument("--cache", help="existing hash-keyed extraction cache, read only")
    p["refresh"].add_argument("--extension", action="append", dest="extensions")
    p["search"].add_argument("query")
    p["search"].add_argument("--limit", type=int, default=12)
    p["search"].add_argument("--task")
    for action in ("review", "link"):
        p[action].add_argument("--source", required=True)
    p["review"].add_argument("--reviewer", required=True)
    p["review"].add_argument("--text-file")
    p["review"].add_argument("--meaning")
    p["review"].add_argument("--evidence", required=True)
    p["link"].add_argument("--kind", required=True)
    p["link"].add_argument("--target", required=True)
    p["link"].add_argument("--scope", required=True)
    p["link"].add_argument("--author", required=True)

    p = group("dependencies", ("add", "scan"))
    for parser in p.values():
        project(parser)
    p["add"].add_argument("--source", required=True)
    p["add"].add_argument("--target", required=True)
    p["add"].add_argument("--relation", required=True)
    p["add"].add_argument("--evidence", required=True)
    p["add"].add_argument("--reviewed", action="store_true")
    p["scan"].add_argument("--discover", action="store_true")

    p = group("backup", ("create", "verify", "restore"))
    p["create"].add_argument("--include", action="append", required=True, dest="includes")
    p["create"].add_argument("--exclude", action="append", default=[], dest="exclusions")
    p["create"].add_argument("--destination", required=True)
    p["create"].add_argument("--id", dest="backup_id")
    for action in ("verify", "restore"):
        p[action].add_argument("--bundle", required=True)
    p["restore"].add_argument("--destination", required=True)

    p = group("resources", ("register", "update", "retire", "list"))
    for action in ("register", "update", "retire"):
        p[action].add_argument("--task", required=True)
        p[action].add_argument("--id", required=True, dest="resource_id")
        p[action].add_argument("--owner", required=True)
    p["register"].add_argument("--kind", required=True)
    p["register"].add_argument("--location", required=True)
    p["register"].add_argument("--reference", action="append", default=[], dest="references")
    p["register"].add_argument("--unfinished", action="append", default=[])
    p["register"].add_argument("--recovery")
    p["update"].add_argument("--evidence", required=True)
    p["update"].add_argument("--reference", action="append", dest="references")
    p["update"].add_argument("--unfinished", action="append")
    p["update"].add_argument("--clear-references", action="store_true")
    p["update"].add_argument("--clear-unfinished", action="store_true")
    p["update"].add_argument("--recovery")
    p["retire"].add_argument("--reason", required=True)
    p["retire"].add_argument("--released", action="store_true", help="owner explicitly releases the unfinished owning task resource")
    p["list"].add_argument("--task")

    p = group("maintenance", ("propose",))
    p["propose"].add_argument("--method")
    p["propose"].add_argument("--scope", default="workspace")
    p["propose"].add_argument("--task-evidence", action="append", default=[], help="task-id:acceptance-id")

    p = group("adapters", ("register", "dispatch", "receipt", "list"))
    p["register"].add_argument("--id", required=True, dest="adapter_id")
    p["register"].add_argument("--capabilities", required=True, help="JSON file of capability status and evidence")
    p["register"].add_argument("--config", help="JSON templates only, no credentials")
    p["register"].add_argument("--role", default="optional", choices=("baseline", "optional"))
    p["register"].add_argument("--evidence")
    p["dispatch"].add_argument("--task", required=True)
    p["dispatch"].add_argument("--adapter", required=True, dest="adapter_id")
    p["dispatch"].add_argument("--actor", required=True)
    p["dispatch"].add_argument("--revision", required=True, type=int, dest="requirement_rev")
    p["dispatch"].add_argument("--key", required=True)
    p["dispatch"].add_argument("--payload", required=True, help="JSON assignment payload")
    p["dispatch"].add_argument("--run", dest="run_id")
    p["receipt"].add_argument("--assignment", required=True, dest="assignment_id")
    p["receipt"].add_argument("--id", required=True, dest="receipt_id")
    p["receipt"].add_argument("--adapter", required=True, dest="adapter_id")
    p["receipt"].add_argument("--revision", required=True, type=int, dest="requirement_rev")
    p["receipt"].add_argument("--status", required=True)
    p["receipt"].add_argument("--evidence", required=True)
    p["receipt"].add_argument("--artifact", action="append", default=[], dest="artifacts")
    p["receipt"].add_argument("--usage", help="JSON actual usage receipt")

    p = group("costs", ("record", "compare"))
    p["record"].add_argument("--task", required=True)
    p["record"].add_argument("--provider", required=True)
    p["record"].add_argument("--attempt", required=True, dest="attempt_id")
    p["record"].add_argument("--evidence", required=True)
    p["record"].add_argument("--usage-cost", type=float)
    p["record"].add_argument("--rework-minutes", type=float)
    p["record"].add_argument("--human-hourly-rate", type=float)
    p["record"].add_argument("--currency", default="USD")
    p["record"].add_argument("--acceptance", dest="acceptance_id")
    p["compare"].add_argument("--provider", action="append", required=True, dest="providers")
    p["compare"].add_argument("--task", action="append", dest="tasks")


def dispatch(args, store):
    # Core CLI uses command as its top-level destination; tolerate existing ctx's cmd.
    command = getattr(args, "command", None) or getattr(args, "cmd", None) or getattr(args, "action", None)
    action = args.service_action
    if command == "sources":
        if action == "refresh":
            return source_refresh(store, args.project, args.roots, args.cache, args.extensions)
        if action == "search":
            return source_search(store, args.project, args.query, args.limit, args.task)
        if action == "review":
            text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else None
            return source_review(store, args.project, args.source, args.reviewer, text, args.meaning, args.evidence)
        return source_link(store, args.project, args.source, args.kind, args.target, args.scope, args.author)
    if command == "dependencies":
        if action == "add":
            return dependencies_add(store, args.project, args.source, args.target, args.relation, args.evidence, args.reviewed)
        return dependencies_scan(store, args.project, args.discover)
    if command == "backup":
        if action == "create":
            return backup_create(store, args.includes, args.destination, args.exclusions, args.backup_id)
        if action == "verify":
            verified = backup_verify(args.bundle)
            receipt = store.read(f"{STATE}/backups/{verified['manifest']['id']}.json")
            if receipt and receipt.get("manifest_sha256") != verified["manifest_sha256"]:
                raise AgentError("backup manifest changed since canonical receipt")
            return verified
        return backup_restore(args.bundle, args.destination, store)
    if command == "resources":
        if action == "register":
            return resource_register(store, args.task, args.resource_id, args.owner, args.kind, args.location,
                                     args.references, args.unfinished, args.recovery)
        if action == "retire":
            return resource_retire(store, args.task, args.resource_id, args.owner, args.reason, args.released)
        if action == "update":
            return resource_update(store, args.task, args.resource_id, args.owner, args.evidence,
                                   [] if args.clear_references else args.references,
                                   [] if args.clear_unfinished else args.unfinished, args.recovery)
        return resource_list(store, args.task)
    if command == "maintenance":
        pairs = []
        for value in args.task_evidence:
            if ":" not in value:
                raise AgentError("task evidence needs task-id:acceptance-id")
            pairs.append(tuple(value.split(":", 1)))
        return maintenance_propose(store, args.method, pairs, args.scope)
    if command == "adapters":
        if action == "register":
            return adapter_register(store, args.adapter_id, json_file(args.capabilities), json_file(args.config) if args.config else None, args.role, args.evidence)
        if action == "dispatch":
            return adapter_dispatch(store, args.task, args.adapter_id, args.actor, args.requirement_rev, args.key, json_file(args.payload), args.run_id)
        if action == "receipt":
            return adapter_receipt(store, args.assignment_id, args.receipt_id, args.adapter_id, args.requirement_rev, args.status,
                                   args.evidence, args.artifacts, json_file(args.usage) if args.usage else None)
        return adapter_list(store)
    if command == "costs":
        if action == "record":
            return cost_record(store, args.task, args.provider, args.attempt_id, args.evidence, args.usage_cost,
                               args.rework_minutes, args.human_hourly_rate, args.currency, args.acceptance_id)
        return cost_compare(store, args.providers, args.tasks)
    raise AgentError("unknown service command")



