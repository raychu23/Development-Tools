"""Isolated behavior, contention, Git and restart tests; no live harness trials."""
import contextlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'systems'))
from agent_core import AgentError, Store, file_hash, guard_path, main, make_boot


def competing_claim(root, result, owner_token):
    try:
        value = Store(root, commit=False).claim("Context/project/T1-test", "owner", owner_token=owner_token)
        result.put(("ok", value["run_id"]))
    except AgentError as exc:
        result.put(("rejected", str(exc)))


def check_after_flag(root, task, submission_id, run_id, token, command, flag, result):
    """A second check started while the first check's command is still running."""
    deadline = time.time() + 10
    while not os.path.exists(flag) and time.time() < deadline:
        time.sleep(.02)
    try:
        record = Store(root, commit=False).check(task, submission_id, None, "A1", command, run_id=run_id, token=token)
        result.put(("ok", record["passed"]))
    except AgentError as exc:
        result.put(("refused", str(exc)))


def interrupt_operation(root):
    # Abrupt process death after the first atomic replacement, not a caught exception.
    store = Store(root, commit=False)
    original = __import__("agent_core").atomic
    def interrupted(path, data, mode=None):
        original(path, data, mode)
        if str(path).endswith("one.txt"):
            os._exit(37)
    with patch("agent_core.atomic", interrupted):
        store.transaction("crash-fixture", {"one.txt": "after-one", "two.txt": "after-two"}, operation_id="crash")


def interrupt_commit_receipt(root):
    store = Store(root, commit=True)
    original = __import__("agent_core").atomic
    def interrupted(path, data, mode=None):
        if str(path).endswith("receipt-gap.json"):
            value = json.loads(data)
            if value.get("phase") == "committed":
                os._exit(39)
        original(path, data, mode)
    with patch("agent_core.atomic", interrupted):
        store.transaction("receipt-gap", {"one.txt": "after-receipt"}, operation_id="receipt-gap")


class CoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.task = "Context/project/T1-test"
        self.other = "Work/project/T2-other"
        for rel in (self.task, self.other, "Context/project/T3-dependent"):
            p = self.root / rel
            p.mkdir(parents=True)
            (p / "0 start.md").write_text("```notes\n    current\n        goal                produce a useful artifact\n        done-when           actual output verified\n```\n")
        (self.root / "one.txt").write_text("before-one")
        (self.root / "two.txt").write_text("before-two")
        (self.root / "unrelated.txt").write_text("initial")
        self.git("init", "-q", "-b", "main")
        self.git("add", ".")
        self.git("-c", "user.name=fixture", "-c", "user.email=t@t", "commit", "-qm", "fixture")
        self.store = Store(self.root, commit=False)
        self.environment = dict(os.environ)
        for key in ("CTX_ACTOR", "CTX_RUN", "CTX_RUN_TOKEN", "CTX_OWNER_TOKEN", "CTX_TEST_HUMAN_CONFIRM",
                    "CTX_HUMAN_CONFIRM_HOOK"):
            os.environ.pop(key, None)
        # Never show a real approval dialog from the suite.
        no_dialog = patch("agent_core.OSASCRIPT", "/nonexistent/osascript")
        no_dialog.start()
        self.addCleanup(no_dialog.stop)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.environment)
        self.tmp.cleanup()

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def enroll(self, task=None, **extra):
        record = self.store.enroll(task or self.task, "owner", "produce correct output", ["output equals reference"], **extra)
        if record.get("owner_token"):
            tokens = self.__dict__.setdefault("owner_tokens", {})
            tokens[task or self.task] = tokens[record["task_id"]] = record["owner_token"]
        return record

    def own(self, task=None):
        """Owner credential kwargs returned once by enrollment (empty before credentials existed)."""
        token = self.__dict__.get("owner_tokens", {}).get(task or self.task)
        return {"owner_token": token} if token else {}

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--root", str(self.root), *args], commit=False)
        return code, out.getvalue(), err.getvalue()

    def test_t4_1_self_approval_with_only_run_token_is_refused(self):
        self.enroll()
        run = self.store.claim(self.task, "worker", coordinator="owner", **self.own())
        self.store.acknowledge(self.task, run["run_id"], "worker", run["token"], make_boot(self.root, self.task)["manifest"])
        artifact = self.root / self.task / "output.txt"
        artifact.write_text("reference")
        sid = self.store.submit(self.task, run["run_id"], "worker", run["token"], [str(artifact)])["submission_id"]
        # The worker holds only its own run receipt and types other actors' names.
        os.environ.update(CTX_ACTOR="worker", CTX_RUN=run["run_id"], CTX_RUN_TOKEN=run["token"])
        code_check, out, _ = self.cli("check", self.task, sid, "--actor", "reviewer", "--criterion", "A1",
                                      "--", sys.executable, "-c", "pass")
        evidence = json.loads(out)["evidence_id"] if code_check == 0 else "evidence-none"
        code_review, _, _ = self.cli("review", self.task, sid, "--actor", "reviewer", "--source", "forged",
                                     "--evidence", evidence)
        code_accept, _, _ = self.cli("accept", self.task, sid, "--actor", "owner")
        self.assertNotEqual(self.store.contract(self.task)["state"], "complete")
        self.assertNotEqual(code_check, 0, "copied run token presented as another actor")
        self.assertNotEqual(code_review, 0, "review without an issued reviewer credential")
        self.assertNotEqual(code_accept, 0, "accept without owner credential or human authority")

    def test_t4_1_review_and_accept_need_distinct_issued_credentials(self):
        submission = self.submitted()
        sid = submission["submission_id"]
        passing = [sys.executable, "-c", "pass"]
        with self.assertRaisesRegex(AgentError, "owner credential"):
            self.store.accept(self.task, sid, "owner")
        with self.assertRaisesRegex(AgentError, "owner credential"):
            self.store.claim(self.task, "reviewer", actions=["review"])
        reviewer = self.store.claim(self.task, "reviewer", actions=["review"], **self.own())
        cred = {"run_id": reviewer["run_id"], "token": reviewer["token"]}
        with self.assertRaisesRegex(AgentError, "invalid run capability"):
            self.store.check(self.task, sid, "intruder", "A1", passing, **cred)
        evidence = self.store.check(self.task, sid, None, "A1", passing, **cred)
        self.assertEqual((evidence["actor"], evidence["run_id"]), ("reviewer", reviewer["run_id"]))
        builder = self.store.claim(self.task, "owner", actions=["review"], **self.own())
        own_check = self.store.check(self.task, sid, None, "A1", passing, run_id=builder["run_id"], token=builder["token"])
        with self.assertRaisesRegex(AgentError, "fresh reviewer"):
            self.store.review(self.task, sid, None, "self", [own_check["evidence_id"]],
                              run_id=builder["run_id"], token=builder["token"])
        writer = self.store._list(self.task, "runs")[0]
        with self.assertRaisesRegex(AgentError, "fresh reviewer|outside lease|invalid run"):
            self.store.review(self.task, sid, None, "self", [own_check["evidence_id"]], run_id=writer["run_id"], token="guess")
        review = self.store.review(self.task, sid, None, "independent inspection", [evidence["evidence_id"]], **cred)
        self.assertEqual(review["actor"], "reviewer")
        with self.assertRaisesRegex(AgentError, "invalid owner credential"):
            self.store.accept(self.task, sid, "owner", owner_token=reviewer["token"])
        with self.assertRaisesRegex(AgentError, "raymond"):
            self.store.accept(self.task, sid, human="looks fine")
        os.environ["CTX_RUN_TOKEN"] = reviewer["token"]
        with self.assertRaisesRegex(AgentError, "leased run"):
            self.store.accept(self.task, sid, human="raymond: approve")
        os.environ.pop("CTX_RUN_TOKEN")
        self.human("Approve")
        accepted = self.store.accept(self.task, sid, human="raymond: inspected the output myself")
        self.assertEqual({k: accepted["authority"][k] for k in ("kind", "statement", "method")},
                         {"kind": "human", "statement": "raymond: inspected the output myself", "method": "test-hook"})
        self.assertEqual(self.store.contract(self.task)["state"], "complete")

    def test_t4_2_independently_valid_patches_conflict_in_combination(self):
        (self.root / "check_sum.py").write_text(
            "import sys\nvalues = [int(open(p).read() or 0) for p in sys.argv[1:]]\n"
            "raise SystemExit(0 if sum(values) <= 3 else 1)\n")
        a_file, b_file = self.root / self.task / "a.txt", self.root / self.other / "b.txt"
        a_file.write_text("0"); b_file.write_text("0")
        self.enroll(self.task); self.enroll(self.other)
        a_run, b_run = self.lease(self.task), self.lease(self.other)
        shared_check = [sys.executable, "check_sum.py", self.task + "/a.txt", self.other + "/b.txt"]
        b_file.write_text("2")  # B alone: 0 + 2 <= 3
        b_sub = self.store.submit(self.other, b_run["run_id"], "owner", b_run["token"], [str(b_file)])
        b_check = self.store.check(self.other, b_sub["submission_id"], None, "A1", shared_check, **self.reviewer(self.other))
        self.assertTrue(b_check["passed"])
        self.store.review(self.other, b_sub["submission_id"], None, "combined sum inspected", [b_check["evidence_id"]],
                          **self.reviewer(self.other))
        a_file.write_text("2")  # A alone: 2 + 0 <= 3, but combined 2 + 2 > 3
        a_sub = self.store.submit(self.task, a_run["run_id"], "owner", a_run["token"], [str(a_file)])
        a_check = self.store.check(self.task, a_sub["submission_id"], None, "A1", shared_check, **self.reviewer(self.task))
        self.assertFalse(a_check["passed"])
        with self.assertRaisesRegex(AgentError, "combined revision"):
            self.store.accept(self.other, b_sub["submission_id"], **self.own(self.other))
        self.assertNotEqual(self.store.contract(self.other)["state"], "complete")

    def test_t4_3_case_variant_scope_is_the_same_path(self):
        shared = self.root / "Project/shared"
        shared.mkdir(parents=True)
        (shared / "notes.md").write_text("A's leased notes")
        if not (self.root / "project/SHARED").exists():
            self.skipTest("case-sensitive filesystem: spellings are distinct paths")
        self.enroll(allowed_paths=[self.task, "Project/shared"])
        self.enroll(self.other, allowed_paths=[self.other, "project/SHARED"])
        self.assertEqual(self.store.contract(self.other)["allowed_paths"][1], "Project/shared")
        self.assertEqual(self.store.relative("project/SHARED/notes.md"), "Project/shared/notes.md")
        self.lease(allowed_paths=["Project/shared"])
        with self.assertRaisesRegex(AgentError, "overlaps"):
            self.store.claim(self.other, "owner", allowed_paths=["project/SHARED"], **self.own(self.other))
        with self.assertRaisesRegex(AgentError, "require CTX_ACTOR"):
            guard_path(self.root, self.root / "project/SHARED/notes.md")
        with self.assertRaisesRegex(AgentError, "require CTX_ACTOR"):
            guard_path(self.root, self.root / "PROJECT/Shared/new-note.md")

    def test_t4_4_corrupt_operation_records_are_named_scoped_and_quarantinable(self):
        ops = self.root / "systems/agent-state/operations"
        ops.mkdir(parents=True)
        truncated = b'{"operation_id": "truncated", "phase": "prep'
        (ops / "truncated.json").write_bytes(truncated)
        (ops / "nofiles.json").write_text(json.dumps({"schema_version": 1, "operation_id": "nofiles", "phase": "prepared"}))
        (ops / "scoped.json").write_text(json.dumps({"schema_version": 1, "operation_id": "scoped", "phase": "prepared",
                                                     "files": {"two.txt": {"before_hash": None}}}))
        code, out, err = self.cli("recover")
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        reports = {r["operation_id"]: r for r in json.loads(out)}
        self.assertEqual({k: r["phase"] for k, r in reports.items()},
                         {"truncated": "corrupt", "nofiles": "corrupt", "scoped": "corrupt"})
        self.assertEqual(reports["scoped"]["paths"], ["two.txt"])
        with self.assertRaisesRegex(AgentError, "recover --quarantine systems/agent-state/operations/truncated.json"):
            self.store.transaction("unrelated", {"unrelated.txt": "blocked by unknown-path record"})
        (ops / "valid.json").write_text(json.dumps({"schema_version": 1, "operation_id": "valid", "phase": "committed",
                                                    "payload_hash": "0" * 64, "files": {}}))
        with self.assertRaisesRegex(AgentError, "readable"):
            self.store.quarantine("systems/agent-state/operations/valid.json")
        for name in ("truncated", "nofiles"):
            code, out, err = self.cli("recover", "--quarantine", "systems/agent-state/operations/" + name + ".json")
            self.assertEqual(code, 0, err)
        self.assertEqual((ops / "corrupt/truncated.json").read_bytes(), truncated)
        self.assertFalse((ops / "truncated.json").exists())
        self.store.transaction("unrelated", {"unrelated.txt": "allowed after quarantine"})
        with self.assertRaisesRegex(AgentError, "conflict"):
            self.store.transaction("scoped-target", {"two.txt": "still scoped-blocked"})

    def test_t4_4_corrupt_task_record_blocks_only_that_task(self):
        self.enroll(allowed_paths=[self.task, self.other])
        self.enroll(self.other)
        record = self.root / self.other / "systems/task.json"
        record.write_bytes(record.read_bytes()[:40])
        run = self.lease(allowed_paths=[self.task])
        self.assertTrue(run["token"])
        self.assertEqual(guard_path(self.root, self.root / "unrelated.txt"), self.root / "unrelated.txt")
        with self.assertRaisesRegex(AgentError, "corrupt"):
            guard_path(self.root, self.root / self.other / "notes.md")
        with self.assertRaisesRegex(AgentError, "corrupt"):
            self.store.claim(self.task, "owner", **self.own(), allowed_paths=[self.other], run_id="run-overlap")
        code, _, err = self.cli("claim", self.other, "--actor", "owner")
        self.assertEqual(code, 1)
        self.assertIn("corrupt", err)
        self.assertNotIn("Traceback", err)
        # A tracked corrupt record moves with its exact bytes and the move is committed.
        corrupt_bytes = record.read_bytes()
        self.git("add", "--", self.other + "/systems/task.json")
        self.git("-c", "user.name=fixture", "-c", "user.email=t@t", "commit", "-qm", "tracked corrupt record")
        receipt = Store(self.root, commit=True).quarantine(self.other + "/systems/task.json")
        self.assertTrue(receipt["tracked"] and receipt["commit"])
        moved = self.root / self.other / "systems/corrupt/task.json"
        self.assertEqual(moved.read_bytes(), corrupt_bytes)
        self.assertEqual(self.git("show", "HEAD:" + self.other + "/systems/corrupt/task.json").encode(), corrupt_bytes.strip())
        self.assertEqual(self.git("ls-files", "--", self.other + "/systems/task.json"), "")

    def test_t4_5_committed_operation_is_not_a_permanent_conflict(self):
        context = multiprocessing.get_context("fork")
        child = context.Process(target=interrupt_commit_receipt, args=(str(self.root),))
        child.start(); child.join(10)
        self.assertEqual(child.exitcode, 39)
        receipt = self.git("rev-parse", "HEAD")
        (self.root / "one.txt").write_text("human edit committed after the crash")
        self.git("add", "one.txt")
        self.git("-c", "user.name=fixture", "-c", "user.email=t@t", "commit", "-qm", "human edit")
        store = Store(self.root, commit=True)
        reports = store.recover()
        self.assertEqual([r["phase"] for r in reports], ["committed"])
        self.assertEqual(self.store.read("systems/agent-state/operations/receipt-gap.json")["commit"], receipt)
        self.assertEqual((self.root / "one.txt").read_text(), "human edit committed after the crash")
        store.transaction("later", {"one.txt": "later owned write"})
        self.assertEqual(store.recover(), [])

    def test_t4_5_conflicted_operation_can_be_abandoned_keeping_human_edit(self):
        context = multiprocessing.get_context("fork")
        child = context.Process(target=interrupt_operation, args=(str(self.root),))
        child.start(); child.join(10)
        (self.root / "one.txt").write_text("human edit to keep")
        self.assertEqual(self.store.recover()[0]["phase"], "conflict")
        with self.assertRaisesRegex(AgentError, "raymond"):
            self.store.abandon("crash", human="agent says fine")
        self.human("Approve")
        receipt = self.store.abandon("crash", human="raymond: keep my edit, drop the interrupted write")
        self.assertEqual(receipt["phase"], "abandoned")
        self.assertEqual((self.root / "one.txt").read_text(), "human edit to keep")
        self.assertEqual(self.store.recover(), [])
        self.store.transaction("after-abandon", {"one.txt": "new owned write"})

    def test_t4_8_retried_claim_can_reissue_a_usable_credential(self):
        self.enroll()
        first = self.store.claim(self.task, "owner", operation_id="dispatch-x", **self.own())
        retry = self.store.claim(self.task, "owner", operation_id="dispatch-x", **self.own())
        self.assertIsNone(retry["token"])
        self.assertIn("original receipt", retry["note"])
        again = self.store.claim(self.task, "owner", operation_id="dispatch-x", reissue=True, **self.own())
        self.assertEqual(again["run_id"], first["run_id"])
        self.assertTrue(again["token"])
        self.assertNotEqual(again["token"], first["token"])
        self.store.acknowledge(self.task, again["run_id"], "owner", again["token"], make_boot(self.root, self.task)["manifest"])
        with self.assertRaisesRegex(AgentError, "invalid run capability"):
            self.store.renew(self.task, first["run_id"], "owner", first["token"])
        with self.assertRaisesRegex(AgentError, "different dispatch"):
            self.store.claim(self.task, "intruder", operation_id="dispatch-x", reissue=True, **self.own())
        self.assertEqual(len(self.store._list(self.task, "runs")), 1)

    def test_t4_9_task_index_cached_per_process_and_invalidated_on_change(self):
        self.enroll()
        Store(self.root, commit=False).tasks()
        real_walk = os.walk
        walks = []
        def counting_walk(top, *args, **kwargs):
            walks.append(str(top))
            return real_walk(top, *args, **kwargs)
        target = self.root / "unrelated.txt"
        with patch("agent_core.os.walk", counting_walk):
            for _ in range(3):
                self.assertEqual(guard_path(self.root, target), target)
            self.assertEqual(walks, [], "guard_path re-walked the workspace for every edited file")
            Store(self.root, commit=False).enroll(self.other, "owner", "second", ["listed"])
            self.assertEqual(len(Store(self.root, commit=False).tasks()), 2)
            self.assertEqual(len(walks), 1, "enrollment must invalidate the cached index")
            moved = self.root / "Context/project/T9-moved"
            (self.root / self.task).rename(moved)
            paths = [t["path"] for t in Store(self.root, commit=False).tasks()]
            self.assertIn("Context/project/T9-moved", paths)
            self.assertEqual(len(walks), 2, "a moved task record must invalidate the cached index")
            record = moved / "systems/task.json"
            record.write_bytes(record.read_bytes()[:30])
            store = Store(self.root, commit=False)
            self.assertEqual(len(store.tasks()), 1)
            self.assertEqual(len(store.corrupt_tasks), 1)

    def human(self, answer):
        """Point the human-presence gate at a non-interactive stub (honored only for temp roots)."""
        if "stub_dir" not in self.__dict__:
            self.stub_dir = tempfile.mkdtemp(prefix="ctx-confirm-")
            self.addCleanup(__import__("shutil").rmtree, self.stub_dir, True)
        stubs = Path(self.stub_dir)
        stub = stubs / ("confirm-" + answer)
        stub.write_text("#!/bin/sh\necho " + answer + "\n")
        stub.chmod(0o755)
        os.environ.update(CTX_TEST_HUMAN_CONFIRM="1", CTX_HUMAN_CONFIRM_HOOK=str(stub))

    def test_t4_r1_typed_human_needs_dialog_approval(self):
        submission = self.submitted()
        sid = submission["submission_id"]
        passing = [sys.executable, "-c", "pass"]
        evidence = self.store.check(self.task, sid, None, "A1", passing, **self.reviewer())
        self.store.review(self.task, sid, None, "inspected", [evidence["evidence_id"]], **self.reviewer())
        child = multiprocessing.get_context("fork").Process(target=interrupt_operation, args=(str(self.root),))
        child.start(); child.join(10)
        (self.root / "one.txt").write_text("human edit")
        self.assertEqual(self.store.recover()[0]["phase"], "conflict")
        self.human("Deny")  # the dialog was shown and not approved
        code_token, _, _ = self.cli("owner-token", self.task, "--human", "raymond: lost my token")
        code_accept, _, _ = self.cli("accept", self.task, sid, "--human", "raymond: fine")
        code_abandon, _, _ = self.cli("recover", "--abandon", "crash", "--human", "raymond: drop it")
        self.assertNotEqual(code_token, 0, "typed --human minted a new owner token")
        self.assertNotEqual(code_accept, 0, "typed --human accepted without approval")
        self.assertNotEqual(code_abandon, 0, "typed --human abandoned without approval")
        self.assertNotEqual(self.store.contract(self.task)["state"], "complete")
        self.assertEqual(self.store.recover()[0]["phase"], "conflict")
        import agent_core
        os.environ.pop("CTX_TEST_HUMAN_CONFIRM")  # hook alone is ignored; no dialog available -> exit 3
        with patch.object(agent_core, "OSASCRIPT", "/nonexistent/osascript"):
            code, _, err = self.cli("accept", self.task, sid, "--human", "raymond: fine")
            self.assertEqual(code, 3, err)
            self.human("Approve")
            with self.assertRaises(agent_core.HumanUnavailable):  # hook never honored outside temp roots
                agent_core.human_authority("raymond: fine", "accept", self.task, "/Users/someone/CS Code")
        accepted = self.store.accept(self.task, sid, human="raymond: inspected it myself")
        self.assertEqual((accepted["authority"]["method"], accepted["authority"]["kind"]), ("test-hook", "human"))
        self.assertIn("confirmed_at", accepted["authority"])
        self.assertTrue(self.store.claim(self.task, "reviewer-2", actions=["review"], **self.own())["token"],
                        "the real owner token must still work")

    def test_t4_r2_undeclared_python_c_inputs_still_bind_combined_tree(self):
        a_file, b_file = self.root / self.task / "a.txt", self.root / self.other / "b.txt"
        a_file.write_text("0"); b_file.write_text("0")
        self.enroll(self.task); self.enroll(self.other)
        a_run, b_run = self.lease(self.task), self.lease(self.other)
        code = ("import sys; a = int(open(%r).read()); b = int(open(%r).read()); sys.exit(0 if a + b <= 3 else 1)"
                % (self.task + "/a.txt", self.other + "/b.txt"))
        shared_check = [sys.executable, "-c", code]
        b_file.write_text("2")
        b_sub = self.store.submit(self.other, b_run["run_id"], "owner", b_run["token"], [str(b_file)])
        b_check = self.store.check(self.other, b_sub["submission_id"], None, "A1", shared_check, **self.reviewer(self.other))
        self.assertTrue(b_check["passed"])
        self.store.review(self.other, b_sub["submission_id"], None, "sum inspected", [b_check["evidence_id"]],
                          **self.reviewer(self.other))
        a_file.write_text("2")
        a_sub = self.store.submit(self.task, a_run["run_id"], "owner", a_run["token"], [str(a_file)])
        self.assertFalse(self.store.check(self.task, a_sub["submission_id"], None, "A1", shared_check,
                                          **self.reviewer(self.task))["passed"])
        with self.assertRaisesRegex(AgentError, "combined revision.*" + self.task + "/a.txt"):
            self.store.accept(self.other, b_sub["submission_id"], **self.own(self.other))
        self.assertNotEqual(self.store.contract(self.other)["state"], "complete")

    def run(self, *args, **kwargs):
        # unittest's run() is not a fixture helper
        return super().run(*args, **kwargs)

    def lease(self, task=None, **extra):
        task = task or self.task
        value = self.store.claim(task, "owner", **self.own(task), **extra)
        self.store.acknowledge(task, value["run_id"], "owner", value["token"], make_boot(self.root, task)["manifest"])
        return value

    def submitted(self):
        self.enroll()
        run = self.lease()
        artifact = self.root / self.task / "output.txt"
        artifact.write_text("reference")
        return self.store.submit(self.task, run["run_id"], "owner", run["token"], [str(artifact)])

    def evidence(self, submission, pass_=True):
        return self.store.check(self.task, submission["submission_id"], None, "A1",
                                [sys.executable, "-c", "raise SystemExit(" + ("0" if pass_ else "1") + ")"],
                                **self.reviewer())

    def reviewer(self, task=None):
        """An issued review-only run for the independent reviewer of task."""
        task = task or self.task
        cache = self.__dict__.setdefault("reviewers", {})
        if task not in cache:
            run = self.store.claim(task, "reviewer", actions=["review"], **self.own(task))
            cache[task] = {"run_id": run["run_id"], "token": run["token"]}
        return cache[task]

    def test_A01_enroll_requires_criteria_and_preserves_identity_after_rename(self):
        with self.assertRaises(AgentError):
            self.store.enroll(self.task, "owner", "goal", [])
        record = self.enroll()
        moved = self.root / "Context/project/T9-renamed"
        (self.root / self.task).rename(moved)
        self.assertEqual(self.store.contract(record["task_id"])["task_id"], record["task_id"])
        self.assertEqual(self.store.tasks()[0]["path"], "Context/project/T9-renamed")
        self.assertFalse((self.root / self.other / "systems/task.json").exists())
        receipt = self.store.reconcile_location(record["task_id"], "owner", **self.own(record["task_id"]))
        self.assertTrue(receipt["changed"])
        run = self.lease(record["task_id"])
        artifact = moved / "output.txt"
        artifact.write_text("reference")
        submitted = self.store.submit(record["task_id"], run["run_id"], "owner", run["token"], [str(artifact)])
        self.assertIn("Context/project/T9-renamed/output.txt", submitted["artifacts"])

    def test_A02_scope_and_symlink_escape_rejected(self):
        self.enroll()
        with self.assertRaises(AgentError):
            self.store.claim(self.task, "owner", **self.own(), allowed_paths=[self.other])
        with self.assertRaises(AgentError):
            self.store.transaction("escape", {"../outside": "no"})
        (self.root / "escape").symlink_to("/tmp")
        with self.assertRaises(AgentError):
            self.store.path("escape/not-owned")

    def test_A03_atomic_claim_contention_and_idempotent_dispatch(self):
        self.enroll()
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        children = [context.Process(target=competing_claim, args=(str(self.root), queue, self.own()["owner_token"])) for _ in range(2)]
        for child in children:
            child.start()
        for child in children:
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        responses = [queue.get(timeout=2) for _ in children]
        self.assertEqual(sorted(r[0] for r in responses), ["ok", "rejected"])
        run = self.store._list(self.task, "runs")[0]
        reused = self.store.claim(self.task, "owner", **self.own(), run_id=run["run_id"])
        self.assertTrue(reused["dispatch_reused"])
        self.assertIsNone(reused["token"])
        self.assertEqual(len(self.store._list(self.task, "runs")), 1)

    def test_dispatch_operation_id_retry_and_conflicting_scope(self):
        self.enroll()
        first = self.store.claim(self.task, "owner", **self.own(), operation_id="dispatch-1")
        retry = self.store.claim(self.task, "owner", **self.own(), operation_id="dispatch-1")
        self.assertEqual(first["run_id"], retry["run_id"])
        self.assertTrue(retry["dispatch_reused"])
        with self.assertRaises(AgentError):
            self.store.claim(self.task, "owner", **self.own(), run_id=first["run_id"], allowed_paths=[self.task + "/narrow"])
        self.assertEqual(len(self.store._list(self.task, "runs")), 1)

    def test_A04_expired_and_wrong_capability_guard(self):
        self.enroll()
        run = self.lease()
        os.environ.update(CTX_ACTOR="owner", CTX_RUN=run["run_id"], CTX_RUN_TOKEN=run["token"])
        target = self.root / self.task / "output.txt"
        self.assertEqual(guard_path(self.root, target), target)
        os.environ["CTX_RUN_TOKEN"] = "wrong"
        with self.assertRaises(AgentError):
            guard_path(self.root, target)
        os.environ["CTX_RUN_TOKEN"] = run["token"]
        location = self.store._record(self.task, "runs", run["run_id"])
        value = self.store.read(location)
        value["expires_at"] = 0
        self.store.transaction("expire-fixture", {str(location): value})
        with self.assertRaises(AgentError):
            guard_path(self.root, target)
        self.assertEqual(guard_path(self.root, self.root / "unrelated.txt"), self.root / "unrelated.txt")

    def test_A05_boot_mandatory_overflow_blocks_instead_of_truncating_correction(self):
        self.enroll()
        self.store.correct(self.task, "owner", "old", "necessary " * 2000, "human message 1", **self.own())
        boot = make_boot(self.root, self.task, max_chars=800)
        self.assertTrue(boot["manifest"]["blocked"])
        self.assertLessEqual(len(boot["text"]), 800)
        self.assertTrue(any("corrections" in p for p in boot["manifest"]["required_reads"]))
        large = make_boot(self.root, self.task, max_chars=100000)
        self.assertIn("necessary " * 20, large["text"])
        self.assertFalse(large["manifest"]["blocked"])

    def test_A06_ack_current_pack_required_and_stale_source_rejected(self):
        self.enroll()
        run = self.store.claim(self.task, "owner", **self.own())
        artifact = self.root / self.task / "output.txt"
        artifact.write_text("reference")
        with self.assertRaises(AgentError):
            self.store.submit(self.task, run["run_id"], "owner", run["token"], [str(artifact)])
        manifest = make_boot(self.root, self.task)["manifest"]
        (self.root / self.task / "0 start.md").write_text("changed after pack")
        with self.assertRaises(AgentError):
            self.store.acknowledge(self.task, run["run_id"], "owner", run["token"], manifest)
        self.store.acknowledge(self.task, run["run_id"], "owner", run["token"], make_boot(self.root, self.task)["manifest"])
        self.assertEqual(self.store.submit(self.task, run["run_id"], "owner", run["token"], [str(artifact)])["requirement_rev"], 1)

    def test_A07_correction_fanout_exact_dependencies_and_stale_results(self):
        submission = self.submitted()
        evidence = self.evidence(submission)
        main_task = self.store.contract(self.task)
        dep = self.enroll("Context/project/T3-dependent", dependencies=[main_task["task_id"]])
        unrelated = self.enroll(self.other)
        correction = self.store.correct(self.task, "owner", "old", "new requirement", "human record 42", **self.own())
        self.assertEqual(set(correction["affected"]), {main_task["task_id"], dep["task_id"]})
        self.assertEqual(self.store.contract(self.other)["requirement_rev"], 1)
        self.assertEqual(self.store.contract(dep["task_id"])["requirement_rev"], 2)
        self.assertTrue(self.store.read(self.store._record(self.task, "evidence", evidence["evidence_id"]))["stale"])
        self.assertTrue(self.store.read(self.store._record(self.task, "submissions", submission["submission_id"]))["stale"])
        self.assertIn("new requirement", (self.root / self.task / "0 start.md").read_text())
        with self.assertRaises(AgentError):
            self.store.accept(self.task, submission["submission_id"], "owner", **self.own())

    def test_A08_durable_message_dedupe_and_receipt_are_not_delivery_or_authority(self):
        self.enroll()
        first = self.store.send(self.task, "question", "worker", "which artifact", "question-1")
        retry = self.store.send(self.task, "question", "worker", "which artifact", "question-1")
        self.assertEqual(first["message_id"], retry["message_id"])
        self.assertEqual(first["delivery"], "queued")
        self.assertIn("not human permission", first["authority"])
        with self.assertRaises(AgentError):
            self.store.send(self.task, "question", "worker", "different", "question-1")
        self.store.receipt(self.task, first["message_id"], "owner", **self.own())
        self.assertEqual(self.store.board()[0]["queued_messages"], 0)

    def test_A09_recovery_after_process_death_rolls_forward_exact_operation(self):
        context = multiprocessing.get_context("fork")
        child = context.Process(target=interrupt_operation, args=(str(self.root),))
        child.start(); child.join(10)
        self.assertEqual(child.exitcode, 37)
        self.assertEqual((self.root / "one.txt").read_text(), "after-one")
        self.assertEqual((self.root / "two.txt").read_text(), "before-two")
        reports = Store(self.root, commit=False).recover()
        self.assertEqual(reports[0]["phase"], "committed")
        self.assertEqual((self.root / "two.txt").read_text(), "after-two")
        self.assertEqual(self.store.recover(), [])

    def test_A10_recovery_preserves_later_edit_and_reports_conflict(self):
        context = multiprocessing.get_context("fork")
        child = context.Process(target=interrupt_operation, args=(str(self.root),))
        child.start(); child.join(10)
        (self.root / "one.txt").write_text("human later edit")
        (self.root / "unrelated.txt").write_text("other edit")
        reports = self.store.recover()
        self.assertEqual(reports[0]["phase"], "conflict")
        self.assertEqual((self.root / "one.txt").read_text(), "human later edit")
        self.assertEqual((self.root / "two.txt").read_text(), "before-two")
        self.assertEqual((self.root / "unrelated.txt").read_text(), "other edit")
        with self.assertRaises(AgentError):
            self.store.transaction("conflicting", {"one.txt": "erase"})
        self.store.transaction("unrelated-safe", {"safe.txt": "allowed"})

    def test_A11_git_commit_exact_owned_paths_preserves_unrelated_staged_blob(self):
        (self.root / "unrelated.txt").write_text("staged human edit")
        self.git("add", "unrelated.txt")
        before = self.git("show", ":unrelated.txt")
        (self.root / "unrelated.txt").write_text("unstaged later human edit")
        store = Store(self.root, commit=True)
        receipt = store.transaction("owned", {"one.txt": "only owned change"})
        self.assertTrue(receipt["commit"])
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"), "one.txt")
        self.assertEqual(self.git("show", ":unrelated.txt"), before)
        self.assertEqual((self.root / "unrelated.txt").read_text(), "unstaged later human edit")
        self.assertEqual(self.git("show", "HEAD:unrelated.txt"), "initial")

    def test_A12_transaction_cas_and_retry_payload_mismatch(self):
        h = file_hash(self.root / "one.txt")
        record = self.store.transaction("cas", {"one.txt": "after"}, expected={"one.txt": h}, operation_id="stable")
        retry = self.store.transaction("cas", {"one.txt": "after"}, expected={"one.txt": h}, operation_id="stable")
        self.assertEqual(record["operation_id"], retry["operation_id"])
        with self.assertRaises(AgentError):
            self.store.transaction("cas", {"one.txt": "different"}, operation_id="stable")
        with self.assertRaises(AgentError):
            self.store.transaction("stale", {"one.txt": "bad"}, expected={"one.txt": h})
        with self.store.locked():
            self.store.transaction("nested", {"nested.txt": "reentrant"})

    def test_A13_acceptance_requires_current_checks_fresh_challenge_and_resolution(self):
        submission = self.submitted()
        with self.assertRaises(AgentError):
            self.store.accept(self.task, submission["submission_id"], "owner", **self.own())
        evidence = self.evidence(submission)
        with self.assertRaises(AgentError):
            self.store.accept(self.task, submission["submission_id"], "owner", **self.own())
        with self.assertRaises(AgentError):
            self.store.challenge(self.task, submission["submission_id"], "owner", "A1", "reference", "reference", "artifact")
        challenge = self.store.challenge(self.task, submission["submission_id"], "reviewer", "A1", "reference", "reference", "artifact inspection", **self.reviewer())
        with self.assertRaises(AgentError):
            self.store.accept(self.task, submission["submission_id"], "owner", **self.own())
        self.store.resolve(self.task, challenge["challenge_id"], "owner", "current reference comparison passes", [evidence["evidence_id"]], **self.own())
        accepted = self.store.accept(self.task, submission["submission_id"], "owner", **self.own())
        self.assertEqual(accepted["artifacts"], submission["artifacts"])
        self.assertEqual(self.store.contract(self.task)["state"], "complete")

    def test_A14_combined_artifact_change_rejects_old_evidence_and_failed_check(self):
        submission = self.submitted()
        self.evidence(submission)
        (self.root / self.task / "output.txt").write_text("new combined revision")
        with self.assertRaises(AgentError):
            self.store.check(self.task, submission["submission_id"], None, "A1", [sys.executable, "-c", "pass"], **self.reviewer(self.task))
        with self.assertRaises(AgentError):
            self.store.accept(self.task, submission["submission_id"], "owner", **self.own())

    def test_no_finding_review_accepts_without_invented_challenge(self):
        submission = self.submitted()
        evidence = self.store.check(self.task, submission["submission_id"], "reviewer", "A1", [sys.executable, "-c", "pass"], **self.reviewer(self.task))
        review = self.store.review(self.task, submission["submission_id"], "reviewer", "reference inspection", [evidence["evidence_id"]], **self.reviewer(self.task))
        self.assertEqual(review["findings"], [])
        accepted = self.store.accept(self.task, submission["submission_id"], "owner", **self.own())
        self.assertEqual(accepted["review_ids"], [review["review_id"]])
        self.assertEqual(accepted["challenge_ids"], [])

    def test_bounded_reviews_and_failed_independence(self):
        submission = self.submitted()
        evidence = self.store.check(self.task, submission["submission_id"], "reviewer", "A1", [sys.executable, "-c", "pass"], **self.reviewer(self.task))
        with self.assertRaises(AgentError):
            self.store.review(self.task, submission["submission_id"], "owner", "self", [evidence["evidence_id"]])
        for _ in range(2):
            self.store.review(self.task, submission["submission_id"], "reviewer", "inspection", [evidence["evidence_id"]], **self.reviewer(self.task))
        with self.assertRaises(AgentError):
            self.store.review(self.task, submission["submission_id"], "reviewer", "third", [evidence["evidence_id"]], **self.reviewer(self.task))

    def test_failed_check_cannot_be_hidden_by_different_passing_command(self):
        submission = self.submitted()
        failed = self.evidence(submission, False)
        self.assertFalse(failed["passed"])
        passed = self.store.check(self.task, submission["submission_id"], "reviewer", "A1", [sys.executable, "-c", "pass"], **self.reviewer(self.task))
        self.store.review(self.task, submission["submission_id"], "reviewer", "reference", [passed["evidence_id"]], **self.reviewer(self.task))
        with self.assertRaisesRegex(AgentError, "failing"):
            self.store.accept(self.task, submission["submission_id"], "owner", **self.own())

    def test_check_handles_missing_command_timeout_and_bounded_output(self):
        submission = self.submitted()
        missing = self.store.check(self.task, submission["submission_id"], None, "A1", ["/missing/executable"], **self.reviewer(self.task))
        self.assertFalse(missing["passed"])
        timeout = self.store.check(self.task, submission["submission_id"], None, "A1", [sys.executable, "-c", "import time; time.sleep(2)"], timeout=.03, **self.reviewer(self.task))
        self.assertFalse(timeout["passed"])
        self.assertIn("timeout", timeout["stderr"])
        large = self.store.check(self.task, submission["submission_id"], None, "A1", [sys.executable, "-c", "print('x'*1000000)"], **self.reviewer(self.task))
        self.assertTrue(large["passed"])
        self.assertLessEqual(len(large["stdout"]), 20000)

    def test_dependency_artifact_revision_captured_and_rechecked(self):
        upstream = self.enroll(self.other)
        up_run = self.lease(self.other)
        up_file = self.root / self.other / "output.txt"
        up_file.write_text("version one")
        def finish_upstream():
            submitted = self.store.submit(self.other, up_run["run_id"], "owner", up_run["token"], [str(up_file)])
            checked = self.store.check(self.other, submitted["submission_id"], "reviewer", "A1", [sys.executable, "-c", "pass"], **self.reviewer(self.other))
            self.store.review(self.other, submitted["submission_id"], "reviewer", "observed reference", [checked["evidence_id"]], **self.reviewer(self.other))
            self.store.accept(self.other, submitted["submission_id"], "owner", **self.own(self.other))
        finish_upstream()
        self.enroll(dependencies=[upstream["task_id"]])
        run = self.lease()
        artifact = self.root / self.task / "output.txt"
        artifact.write_text("consumes version one")
        down = self.store.submit(self.task, run["run_id"], "owner", run["token"], [str(artifact)])
        self.assertIn(upstream["task_id"], down["dependencies"])
        up_file.write_text("version two")
        finish_upstream()
        with self.assertRaisesRegex(AgentError, "upstream"):
            self.store.submit(self.task, run["run_id"], "owner", run["token"], [str(artifact)])
        with self.assertRaisesRegex(AgentError, "upstream"):
            self.store.check(self.task, down["submission_id"], None, "A1", [sys.executable, "-c", "pass"], **self.reviewer(self.task))

    def test_midway_later_edit_preserved(self):
        original = __import__("agent_core").atomic
        def edits_next_file(path, data, mode=None):
            original(path, data, mode)
            if str(path).endswith("one.txt"):
                (self.root / "two.txt").write_text("human concurrent edit")
        with patch("agent_core.atomic", edits_next_file):
            with self.assertRaisesRegex(AgentError, "later edit"):
                self.store.transaction("two-files", {"one.txt": "ours", "two.txt": "must not overwrite"})
        self.assertEqual((self.root / "two.txt").read_text(), "human concurrent edit")
        self.assertEqual(self.store.recover()[0]["phase"], "conflict")

    def test_cli_check_options_after_task_and_submission(self):
        submission = self.submitted()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--root", str(self.root), "check", self.task, submission["submission_id"], "--actor", "reviewer", "--criterion", "A1", "--run", self.reviewer()["run_id"], "--token", self.reviewer()["token"], "--", sys.executable, "-c", "pass"], commit=False)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["passed"])

    def test_shared_scope_uses_actual_run_contract_not_first_enrollment(self):
        shared = self.root / "shared.txt"
        shared.write_text("shared")
        self.enroll(allowed_paths=[self.task, "shared.txt"])
        self.enroll(self.other, allowed_paths=[self.other, "shared.txt"])
        run = self.lease(self.other, allowed_paths=["shared.txt"])
        os.environ.update(CTX_ACTOR="owner", CTX_RUN=run["run_id"], CTX_RUN_TOKEN=run["token"])
        self.assertEqual(guard_path(self.root, shared), shared)
        with self.assertRaises(AgentError):
            self.store.claim(self.task, "owner", **self.own(), allowed_paths=["shared.txt"])

    def test_all_independent_corrections_remain_mandatory_after_message_ack(self):
        self.enroll()
        first = self.store.correct(self.task, "owner", "can delete original", "preserve all originals", "human message 1", **self.own())
        message = self.store._list(self.task, "messages")[0]
        self.store.receipt(self.task, message["message_id"], "owner", **self.own())
        second = self.store.correct(self.task, "owner", "no attribution", "retain source attribution", "human message 2", **self.own())
        boot = make_boot(self.root, self.task)
        ids = {x["id"] for x in boot["manifest"]["included"]}
        self.assertIn(first["correction_id"], ids)
        self.assertIn(second["correction_id"], ids)
        self.assertIn("preserve all originals", boot["text"])
        self.assertFalse(boot["manifest"]["blocked"])
        self.store.correct(self.task, "owner", "old attribution rule", "source links required", "human message 3", supersedes=[second["correction_id"]], **self.own())
        ids = {x["id"] for x in make_boot(self.root, self.task)["manifest"]["included"]}
        self.assertIn(first["correction_id"], ids)
        self.assertNotIn(second["correction_id"], ids)

    def test_recovery_receipt_is_original_commit_after_later_unrelated_commit(self):
        context = multiprocessing.get_context("fork")
        child = context.Process(target=interrupt_commit_receipt, args=(str(self.root),))
        child.start(); child.join(10)
        self.assertEqual(child.exitcode, 39)
        original_commit = self.git("rev-parse", "HEAD")
        (self.root / "unrelated.txt").write_text("later human commit")
        self.git("add", "unrelated.txt")
        self.git("-c", "user.name=fixture", "-c", "user.email=t@t", "commit", "-qm", "unrelated")
        later_commit = self.git("rev-parse", "HEAD")
        self.assertNotEqual(original_commit, later_commit)
        reports = Store(self.root, commit=True).recover()
        self.assertEqual(reports[0]["phase"], "committed")
        journal = self.store.read("systems/agent-state/operations/receipt-gap.json")
        self.assertEqual(journal["commit"], original_commit)
        self.assertEqual(self.git("rev-parse", "HEAD"), later_commit)
        self.assertEqual((self.root / "unrelated.txt").read_text(), "later human commit")
        self.assertEqual((self.root / "one.txt").read_text(), "after-receipt")

    def test_edit_after_final_replace_before_commit_reports_conflict(self):
        store = Store(self.root, commit=True)
        old_head = self.git("rev-parse", "HEAD")
        original = __import__("agent_core").atomic
        def later_edit(path, data, mode=None):
            original(path, data, mode)
            if str(path).endswith("one.txt"):
                (self.root / "one.txt").write_text("human after replace")
        with patch("agent_core.atomic", later_edit):
            with self.assertRaisesRegex(AgentError, "before commit"):
                store.transaction("late-before-commit", {"one.txt": "our intended bytes"})
        self.assertEqual((self.root / "one.txt").read_text(), "human after replace")
        self.assertEqual(self.git("rev-parse", "HEAD"), old_head)

    def test_edit_during_git_commit_is_preserved_not_captured_in_commit(self):
        store = Store(self.root, commit=True)
        original = store._commit
        def later_edit(*args, **kwargs):
            (self.root / "one.txt").write_text("human racing git")
            return original(*args, **kwargs)
        with patch.object(store, "_commit", later_edit):
            with self.assertRaisesRegex(AgentError, "during commit"):
                store.transaction("race-git", {"one.txt": "our intended bytes"})
        self.assertEqual((self.root / "one.txt").read_text(), "human racing git")
        self.assertEqual(self.git("show", "HEAD:one.txt"), "our intended bytes")
        # T4 finding 5: the commit receipt exists, so the operation is committed; the racing
        # human bytes stay in the working tree and are reported, not turned into a permanent block.
        report = store.recover()[0]
        self.assertEqual((report["phase"], report["later_edits_preserved"]), ("committed", ["one.txt"]))
        self.assertEqual((self.root / "one.txt").read_text(), "human racing git")

    def test_store_boot_reentrant_for_service_snapshot(self):
        self.enroll()
        with self.store.locked():
            packet = self.store.boot(self.task, persist=True)
        self.assertFalse(packet["manifest"]["blocked"])
        self.assertEqual(self.store.read(self.task + "/systems/boot/latest.json")["manifest_hash"], packet["manifest"]["manifest_hash"])

    def test_open_finding_is_mandatory_until_adjudicated(self):
        submission = self.submitted()
        finding = self.store.challenge(self.task, submission["submission_id"], "reviewer", "A1", "reference output", "known wrong output", "inspection", **self.reviewer())
        packet = self.store.boot(self.task)
        self.assertIn("known wrong output", packet["text"])
        self.assertIn(finding["challenge_id"], {p["id"] for p in packet["manifest"]["included"]})
        small = self.store.boot(self.task, max_chars=400)
        self.assertTrue(small["manifest"]["blocked"])
        self.assertTrue(any("challenges" in p for p in small["manifest"]["required_reads"]))
        evidence = self.evidence(submission)
        self.store.resolve(self.task, finding["challenge_id"], "owner", "current reference passes", [evidence["evidence_id"]], **self.own())
        self.assertNotIn(finding["challenge_id"], {p["id"] for p in self.store.boot(self.task)["manifest"]["included"]})

    def test_commit_receipt_ids_match_whole_trailer(self):
        store=Store(self.root,commit=True)
        first=store.transaction('prefix',{'one.txt':'first'},operation_id='attempt-long')
        second=store.transaction('prefix',{'one.txt':'second'},operation_id='attempt')
        self.assertNotEqual(first['commit'],second['commit'])
        self.assertEqual(self.git('show',second['commit']+':one.txt'),'second')

    def test_cli_core_and_board_health_shape(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--root", str(self.root), "enroll", self.task, "--owner", "owner", "--goal", "reference", "--criterion", "equal"], commit=False)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["requirement_rev"], 1)
        board = self.store.board()[0]
        for key in ("messages", "evidence", "corrections", "health", "needs_you", "runs", "path"):
            self.assertIn(key, board)

    def test_check_subprocess_reads_boot_while_managed_writers_wait(self):
        submission = self.submitted()
        probe = ("import fcntl, sys\nsys.path.insert(0, %r)\nfrom agent_core import Store, make_boot\n"
                 "assert not make_boot(%r, %r)['manifest']['blocked']\n"
                 "with open(Store(%r, commit=False).lock_path, 'a+b') as lock:\n"
                 "    try:\n        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                 "    except BlockingIOError:\n        raise SystemExit(0)\n"
                 "raise SystemExit('a managed writer could act during the check')\n"
                 ) % (str(Path(__file__).resolve().parents[1] / 'systems'), str(self.root), self.task, str(self.root))
        evidence = self.store.check(self.task, submission["submission_id"], None, "A1", [sys.executable, "-c", probe],
                                    timeout=10, **self.reviewer())
        self.assertTrue(evidence["passed"], evidence["stderr"])

    def test_checks_stay_serialized_so_evidence_binds_to_what_was_read(self):
        submission = self.submitted()
        self.enroll(self.other)
        notes, flag = self.root / self.other / "notes.txt", self.root / "first-check-running.flag"
        notes.write_text("good")
        good = file_hash(notes)
        reviewer = self.reviewer()
        read = [sys.executable, "-c", "import pathlib, time\nx = pathlib.Path(%r).read_text()\npathlib.Path(%r).write_text('1')\n"
                "time.sleep(1.5)\nraise SystemExit(0 if x == 'good' else 1)" % (str(notes), str(flag))]
        write = [sys.executable, "-c", "import pathlib; pathlib.Path(%r).write_text('bad')" % str(notes)]
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        child = context.Process(target=check_after_flag, args=(str(self.root), self.task, submission["submission_id"],
                                reviewer["run_id"], reviewer["token"], write, str(flag), queue))
        child.start()
        first = self.store.check(self.task, submission["submission_id"], None, "A1", read, timeout=20, **reviewer)
        child.join(30)
        self.assertEqual(queue.get(timeout=5), ("ok", True))
        self.assertTrue(first["passed"])
        # the first check read "good", so its evidence must bind to "good" and acceptance must see the later change
        self.assertEqual(first["combined_tree"][self.other + "/notes.txt"], good)
        self.assertEqual(notes.read_text(), "bad")

    def racing_check(self, submission, race):
        """Run a check with race() acting between its shared run and its exclusive record step."""
        reviewer, original, state = self.reviewer(), self.store.locked, {}
        def locked(shared=False):
            if not shared and not getattr(self.store._local, "depth", 0) and state.pop("ran", False):
                race()
            if shared:
                state["ran"] = True
            return original(shared)
        with patch.object(self.store, "locked", locked):
            return self.store.check(self.task, submission["submission_id"], None, "A1", [sys.executable, "-c", "pass"], **reviewer)

    def test_check_discards_result_when_combined_revision_moves_before_recording(self):
        submission = self.submitted()
        self.enroll(self.other)
        other = self.root / self.other / "notes.txt"
        other.write_text("before")
        with self.assertRaisesRegex(AgentError, "changed"):
            self.racing_check(submission, lambda: other.write_text("racing writer"))
        own = self.root / self.task / "output.txt"
        with self.assertRaisesRegex(AgentError, "changed"):
            self.racing_check(submission, lambda: own.write_text("racing artifact"))
        self.assertEqual(self.store._list(self.task, "evidence"), [])

    def test_check_refuses_stale_submission_corrected_before_recording(self):
        submission = self.submitted()
        correct = lambda: self.store.correct(self.task, "owner", "output equals reference", "output equals new reference",
                                             "Raymond fixture source", **self.own())
        with self.assertRaisesRegex(AgentError, "stale"):
            self.racing_check(submission, correct)
        self.assertEqual(self.store._list(self.task, "evidence"), [])


if __name__ == "__main__":
    unittest.main()
