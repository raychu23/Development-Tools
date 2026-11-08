"""Isolated implementation checks, not trials on Raymond's real reference library."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from agent_core import AgentError, Store, main
import agent_services as s


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-services-fixture-")
        self.root = Path(self.temp.name).resolve() / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        self.store = Store(self.root, commit=False)
        (self.root / "Project/demo/pictures").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value if isinstance(value, bytes) else value.encode())
        return target

    def task(self, name="T1-fixture"):
        self.put(f"Project/demo/{name}/0 start.md", "```notes\n    goal    fixture\n    next    deterministic verification\n```\n")
        return self.store.enroll(f"Project/demo/{name}", "owner", "fixture outcome", ["observable fixture"], ["Project/demo"])

    def accepted(self, task, acceptance_id="acceptance-fixture"):
        # Construct a service's read-side prerequisite; core acceptance guards have their own tests.
        artifact = self.put(f"Project/demo/{task['task_id']}.txt", "accepted bytes")
        path = self.store.task_path(task["task_id"]) / "systems/acceptances" / (acceptance_id + ".json")
        value = {"task_id": task["task_id"], "requirement_rev": task["requirement_rev"], "stale": False,
                 "acceptance_id": acceptance_id, "artifacts": {str(artifact.relative_to(self.root)): s.file_hash(artifact)}}
        self.store.transaction("fixture", {str(path): value})
        return acceptance_id

    def refresh(self):
        return s.source_refresh(self.store, "Project/demo", ["Project/demo/pictures"], "Project/demo/cache" if (self.root / "Project/demo/cache").exists() else None)

    def test_a15_full_inventory_duplicates_and_explicit_video_boundary(self):
        # 124 image paths, 115 unique image bytes and one unread video, matching inventory contract.
        for n in range(115):
            raw = f"distinct image {n}".encode()
            self.put(f"Project/demo/pictures/image-{n}.png", raw)
            self.put(f"Project/demo/cache/{s.digest(raw)}.json", json.dumps({"sha256": s.digest(raw),
                "engine": "Apple Vision accurate en-US; language correction off", "lines": [{"text": f"memory lesson {n}"}]}))
        for n in range(9):
            self.put(f"Project/demo/pictures/duplicate-{n}.png", f"distinct image {n}")
        self.put("Project/demo/pictures/unread.mp4", "video fixture")
        result = self.refresh()["manifest"]
        self.assertEqual(result["summary"]["paths_in_scan"], 125)
        self.assertEqual(result["summary"]["unique_in_scan"], 116)
        self.assertEqual(result["summary"]["exact_duplicate_copies"], 9)
        self.assertEqual(result["summary"]["unreviewed"], 115)
        card = s.source_card(self.store, "Project/demo", s.digest(b"video fixture"))
        self.assertEqual(card["extraction"]["status"], "not-extracted")
        self.assertIn("not been reviewed", card["extraction"]["error"])
        self.assertFalse(result["originals_modified"])

    def test_missing_root_aborts_without_shrinking_manifest(self):
        self.put("Project/demo/pictures/a.png", "a")
        self.refresh()
        manifest = self.root / "Project/demo/systems/sources/manifest.json"
        before = s.file_hash(manifest)
        with self.assertRaises(AgentError):
            s.source_refresh(self.store, "Project/demo", ["Project/demo/pictures", "Project/demo/absent"])
        self.assertEqual(s.file_hash(manifest), before)

    def test_a02_rename_preserves_identity_history_and_links(self):
        source = self.put("Project/demo/pictures/a.png", "source bytes")
        sha = s.file_hash(source)
        self.refresh()
        s.source_link(self.store, "Project/demo", sha, "lesson", "F1", "demo", "owner")
        source.rename(source.with_name("renamed.png"))
        self.refresh()
        card = s.source_card(self.store, "Project/demo", sha)
        self.assertEqual(card["links"][0]["target"], "F1")
        locations = {x["path"]: x for x in card["locations"]}
        self.assertFalse(locations["Project/demo/pictures/a.png"]["available"])
        self.assertTrue(locations["Project/demo/pictures/renamed.png"]["available"])
        self.assertEqual(len(card["locations"]), 2)

    def test_changed_bytes_do_not_reuse_old_meaning(self):
        source = self.put("Project/demo/pictures/a.png", "old")
        old_hash = s.file_hash(source)
        self.refresh()
        s.source_review(self.store, "Project/demo", old_hash, "owner", meaning="selected old lesson", evidence="visual fixture")
        source.write_text("new")
        new_hash = s.file_hash(source)
        manifest = self.refresh()["manifest"]
        self.assertIn("changed-bytes", {change["kind"] for change in manifest["changes"]})
        self.assertEqual(s.source_card(self.store, "Project/demo", new_hash)["meaning"], [])
        old = s.source_card(self.store, "Project/demo", old_hash)
        self.assertEqual(old["meaning"][0]["text"], "selected old lesson")
        self.assertFalse(old["locations"][0]["available"])

    def test_a16_review_keeps_original_and_machine_text_and_near_duplicates_separate(self):
        original = self.put("Project/demo/pictures/a.png", "nearly identical first")
        self.put("Project/demo/pictures/b.png", "nearly identical second")
        sha = s.file_hash(original)
        self.put(f"Project/demo/cache/{sha}.json", json.dumps({"sha256": sha, "engine": "Apple OCR fixture v1",
                                                            "lines": [{"text": "mem0ry"}]}))
        before = original.read_bytes()
        self.refresh()
        s.source_review(self.store, "Project/demo", sha, "owner", "memory", "keep original provenance", "viewed original fixture")
        card = s.source_card(self.store, "Project/demo", sha)
        self.assertEqual(card["extraction"]["text"], "mem0ry")
        self.assertEqual(card["extraction"]["review"]["text"], "memory")
        self.assertEqual(card["meaning"][0]["kind"], "authored-interpretation")
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(len(s.source_search(self.store, "Project/demo", "memory")), 1)
        self.assertEqual(len(s.read(self.store, "Project/demo/systems/sources/manifest.json")["items"]), 2)

    def test_failed_cached_ocr_does_not_become_reviewed(self):
        source = self.put("Project/demo/pictures/a.png", "broken extract")
        sha = s.file_hash(source)
        self.put(f"Project/demo/cache/{sha}.json", json.dumps({"sha256": sha, "error": "no text", "lines": []}))
        self.refresh()
        self.assertEqual(s.source_card(self.store, "Project/demo", sha)["extraction"]["status"], "failed")

    def test_extractor_version_updates_retain_human_review_and_old_machine_text(self):
        source = self.put("Project/demo/pictures/a.png", "original")
        sha = s.file_hash(source)
        self.put(f"Project/demo/cache/{sha}.json", json.dumps({"sha256": sha, "engine": "v1", "text": "incorrect"}))
        self.refresh()
        s.source_review(self.store, "Project/demo", sha, "owner", "correct", evidence="original inspected")
        self.put(f"Project/demo/cache/{sha}.json", json.dumps({"sha256": sha, "engine": "v2", "text": "new extraction"}))
        self.refresh()
        card = s.source_card(self.store, "Project/demo", sha)
        self.assertEqual(card["extraction"]["engine"], "v2")
        self.assertEqual(card["extraction"]["review"]["text"], "correct")
        self.assertEqual(card["extraction_history"][0]["engine"], "v1")

    def test_index_rebuilds_after_out_of_band_canonical_card_change(self):
        self.put("Project/demo/pictures/a.md", "old phrase")
        self.refresh()
        sha = s.digest(b"old phrase")
        path = f"Project/demo/systems/sources/{sha}.json"
        card = s.read(self.store, path)
        card["meaning"] = [{"kind": "authored-interpretation", "text": "distinctive new lookup"}]
        self.store.transaction("fixture edit", {path: card})
        self.assertEqual(len(s.source_search(self.store, "Project/demo", "distinctive")), 1)

    def test_source_symlink_is_refused(self):
        outside = self.root.parent / "outside.png"
        outside.write_text("outside")
        (self.root / "Project/demo/pictures/link.png").symlink_to(outside)
        with self.assertRaises(AgentError):
            self.refresh()

    def test_a17_dependency_rename_and_changed_bytes_flagged(self):
        source = self.put("Project/demo/code.py", "import module\n")
        self.put("Project/demo/module.py", "VALUE = 1\n")
        s.dependencies_add(self.store, "Project/demo", "Project/demo/code.py", "Project/demo/module.py", "imports", "code.py:1", True)
        source.rename(source.with_name("renamed.py"))
        graph = s.dependencies_scan(self.store, "Project/demo", True)["graph"]
        self.assertEqual(graph["edges"][0]["status"], "stale")
        self.assertEqual(graph["edges"][0]["stale_reasons"][0]["reason"], "missing-or-renamed")
        self.assertEqual(graph["proposals"][0]["status"], "proposal")
        repaired = s.dependencies_add(self.store, "Project/demo", "Project/demo/renamed.py", "Project/demo/module.py", "imports", "renamed.py:1", True)
        self.assertEqual(repaired["edge"]["status"], "current")

    def test_a20_scoped_snapshot_sqlite_wal_and_isolated_restore(self):
        self.put("Project/demo/decision.md", "human decision fixture")
        self.put("Project/demo/.env", "SECRET fixture deliberately excluded")
        dbpath = self.root / "Project/demo/live.sqlite"
        db = sqlite3.connect(dbpath)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE example (value TEXT)")
            db.execute("INSERT INTO example VALUES ('committed in WAL')")
            db.commit()
            backup = s.backup_create(self.store, ["Project/demo"], str(self.root.parent / "bundles"), backup_id="backup-fixture")
            self.assertFalse(backup["backup"]["isolated_restore_verified"])
            self.assertIn("Project/demo/.env", {x["path"] for x in backup["manifest"]["exclusions"]})
            self.assertEqual(backup["backup"]["off_device"], "not-established")
            destination = self.root.parent / "restore"
            restored = s.backup_restore(backup["backup"]["destination"], str(destination), self.store)
            self.assertTrue(restored["isolated_restore_verified"])
            self.assertEqual((destination / "Project/demo/decision.md").read_text(), "human decision fixture")
            with sqlite3.connect(destination / "Project/demo/live.sqlite") as snapshot:
                self.assertEqual(snapshot.execute("SELECT value FROM example").fetchone()[0], "committed in WAL")
            with self.assertRaises(AgentError):
                s.backup_restore(backup["backup"]["destination"], str(destination))
        finally:
            db.close()

    def test_t4_10_sqlite_snapshot_bundle_is_self_contained(self):
        from contextlib import closing
        from urllib.parse import quote
        dbpath = self.root / "Project/demo/wal.sqlite"
        dbpath.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(dbpath)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE example (value TEXT)")
            db.execute("INSERT INTO example VALUES ('only in the WAL so far')")
            db.commit()
            receipt = s.backup_create(self.store, ["Project/demo/wal.sqlite"], str(self.root.parent / "t4-bundles"),
                                      backup_id="t4-wal")
        finally:
            db.close()
        files_root = Path(receipt["backup"]["destination"]) / "files"
        names = sorted(str(p.relative_to(files_root)) for p in files_root.rglob("*") if p.is_file())
        self.assertEqual(names, ["Project/demo/wal.sqlite"], "sidecar or extra file in the bundle")
        snapshot = files_root / "Project/demo/wal.sqlite"
        self.assertEqual(snapshot.read_bytes()[18:20], b"\x01\x01", "snapshot still in WAL mode needs a sidecar")
        with closing(sqlite3.connect("file:" + quote(str(snapshot)) + "?mode=ro&immutable=1", uri=True)) as copy:
            self.assertEqual(copy.execute("SELECT value FROM example").fetchone()[0], "only in the WAL so far")
        self.assertTrue(s.backup_verify(receipt["backup"]["destination"])["valid"])

    def test_backup_suffix_siblings_are_not_silently_excluded(self):
        self.put("Project/demo/report", "ordinary text")
        self.put("Project/demo/report-journal", "human decision journal")
        self.put("Project/demo/report-wal", "ordinary evidence named wal")
        self.put("Project/demo/report-shm", "ordinary evidence named shm")
        result = s.backup_create(self.store, ["Project/demo"], str(self.root.parent / "bundles"))
        self.assertEqual({record["path"] for record in result["manifest"]["files"]},
                         {"Project/demo/report", "Project/demo/report-journal", "Project/demo/report-wal", "Project/demo/report-shm"})
        self.assertEqual(result["manifest"]["exclusions"], [])
        restored = self.root.parent / "restore"
        s.backup_restore(result["backup"]["destination"], str(restored), self.store)
        self.assertEqual((restored / "Project/demo/report-journal").read_text(), "human decision journal")

    def test_sqlite_sidecar_without_selected_database_keeps_explicit_coverage(self):
        path = self.root / "Project/demo/live.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE example (value TEXT)")
        self.put("Project/demo/live.sqlite-wal", "standalone sidecar fixture")
        # The actual SQLite sibling is deliberately outside this allowlist.
        result = s.backup_create(self.store, ["Project/demo/live.sqlite-wal"], str(self.root.parent / "bundles"))
        self.assertEqual([record["path"] for record in result["manifest"]["files"]], ["Project/demo/live.sqlite-wal"])
        self.assertEqual(result["manifest"]["files"][0]["snapshot_method"], "writer-locked-copy")
        self.assertEqual(result["manifest"]["exclusions"], [])

    def test_corruption_and_traversal_restore_abort_before_destination(self):
        self.put("Project/demo/decision.md", "correct")
        result = s.backup_create(self.store, ["Project/demo/decision.md"], str(self.root.parent / "bundles"))
        bundle = Path(result["backup"]["destination"])
        (bundle / "files/Project/demo/decision.md").write_text("corrupt")
        destination = self.root.parent / "restore"
        self.assertFalse(s.backup_verify(bundle)["valid"])
        with self.assertRaises(AgentError):
            s.backup_restore(bundle, str(destination))
        self.assertFalse(destination.exists())
        manifest = json.loads((bundle / "manifest.json").read_text())
        manifest["files"][0]["path"] = "../escape"
        (bundle / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(AgentError):
            s.backup_restore(bundle, str(destination))
        self.assertFalse(destination.exists())

    def test_manifest_anchor_rejects_self_consistent_tampering(self):
        self.put("Project/demo/decision.md", "correct")
        result = s.backup_create(self.store, ["Project/demo/decision.md"], str(self.root.parent / "bundles"))
        bundle = Path(result["backup"]["destination"])
        copied = bundle / "files/Project/demo/decision.md"
        copied.write_text("changed")
        manifest = json.loads((bundle / "manifest.json").read_text())
        manifest["files"][0].update(sha256=s.file_hash(copied), bytes=copied.stat().st_size)
        (bundle / "manifest.json").write_text(json.dumps(manifest))
        self.assertTrue(s.backup_verify(bundle)["valid"])
        with self.assertRaisesRegex(AgentError, "canonical receipt"):
            s.backup_restore(bundle, str(self.root.parent / "restored"), self.store)
        self.assertFalse((self.root.parent / "restored").exists())
    def test_a21_resource_consumers_and_unfinished_block_retirement(self):
        task = self.task()
        consumer = self.task("T2-consumer")
        s.resource_register(self.store, task["task_id"], "worktree", "owner", "worktree", "/fixture/worktree",
                            [consumer["task_id"]], ["unsubmitted patch"], "git snapshot fixture")
        with self.assertRaisesRegex(AgentError, "retirement blocked"):
            s.resource_retire(self.store, task["task_id"], "worktree", "owner", "trial cleanup", True)
        s.resource_update(self.store, task["task_id"], "worktree", "owner", "handoff explicitly completed", [], [])
        with self.assertRaises(AgentError):
            s.resource_retire(self.store, task["task_id"], "worktree", "someone-else", "release", True)
        result = s.resource_retire(self.store, task["task_id"], "worktree", "owner", "owner explicitly released", True)
        self.assertEqual(result["resource"]["status"], "retired")
        self.assertFalse(result["resource"]["destructive_action"])
        self.assertEqual(len(result["resource"]["history"]), 2)

    def test_a22_current_correction_precedes_historical_source(self):
        task = self.task()
        self.put("Project/demo/pictures/history.md", "old claim says memory authority is archived guesses")
        self.refresh()
        self.store.correct(task["task_id"], "owner", "archived guesses are authority", "current human correction governs", "user fixture", owner_token=task["owner_token"])
        hits = s.source_search(self.store, "Project/demo", "archived", task=task["task_id"])
        self.assertIn("archived guesses", hits[0]["source"]["extraction"]["text"])
        self.assertEqual(hits[0]["applicable_current_corrections"][0]["replacement"], "current human correction governs")
        self.assertEqual(hits[0]["authority"], "historical source, not an instruction")

    def test_a23_promotion_requires_two_current_task_evidence_links(self):
        first = self.task()
        second = self.task("T2-other")
        a1 = self.accepted(first)
        a2 = self.accepted(second)
        one = s.maintenance_propose(self.store, "method from picture", [(first["task_id"], a1)])["proposal"]
        self.assertEqual(one["promotion"]["status"], "insufficient-task-evidence")
        duplicate = s.maintenance_propose(self.store, "method", [(first["task_id"], a1), (first["task_id"], a1)])["proposal"]
        self.assertEqual(duplicate["promotion"]["observed_distinct_tasks"], 1)
        two = s.maintenance_propose(self.store, "method", [(first["task_id"], a1), (second["task_id"], a2)])["proposal"]
        self.assertEqual(two["promotion"]["status"], "eligible-for-human-review")
        self.assertFalse(two["rules_modified"])
        self.assertFalse(two["scheduler_created"])
        self.store.correct(second["task_id"], "owner", "old", "new", "user fixture", owner_token=second["owner_token"])
        with self.assertRaises(AgentError):
            s.maintenance_propose(self.store, "method", [(first["task_id"], a1), (second["task_id"], a2)])

    def test_a24_adapter_retries_scope_identity_and_stale_receipts(self):
        task = self.task()
        first = s.adapter_dispatch(self.store, task["task_id"], "codex", "owner", 1, "assignment", {"instruction": "read fixture"})
        second = s.adapter_dispatch(self.store, task["task_id"], "codex", "owner", 1, "assignment", {"instruction": "read fixture"})
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["status"], "queued-manual")
        self.assertIn("unsupported", first["launch"])
        with self.assertRaises(AgentError):
            s.adapter_dispatch(self.store, task["task_id"], "codex", "owner", 1, "assignment", {"instruction": "different work"})
        with self.assertRaises(AgentError):
            s.adapter_dispatch(self.store, task["task_id"], "codex", "owner", 1, "outside", {"allowed_paths": ["Other/project"]})
        self.store.correct(task["task_id"], "owner", "old", "new", "user correction fixture", owner_token=task["owner_token"])
        receipt = s.adapter_receipt(self.store, first["id"], "receipt-fixture", "codex", 1, "partial", "manual observed partial")
        self.assertEqual(receipt["status"], "stale-receipt")
        self.assertTrue(receipt["receipts"][0]["stale"])
        self.assertIn("not established", receipt["receipts"][0]["acceptance"])

    def test_optional_adapter_has_real_contract_without_activation(self):
        task = self.task()
        registered = s.adapter_register(self.store, "local-open-model", {"boot": {"status": "manual", "evidence": "exported JSON contract"}}, {"model": "candidate"})
        self.assertEqual(registered["adapter"]["native_activation"], "not-observed")
        self.assertEqual(registered["adapter"]["cost"]["status"], "unknown")
        dispatch = s.adapter_dispatch(self.store, task["task_id"], "local-open-model", "owner", 1, "open-model-fixture", {"instruction": "bounded extraction"})
        self.assertEqual(dispatch["task_id"], task["task_id"])
        self.assertEqual(dispatch["criteria"], task["criteria"])
        self.assertEqual(dispatch["requirement_rev"], 1)

    def test_a25_same_task_cost_includes_all_attempts_and_human_rework(self):
        task = self.task()
        acceptance = self.accepted(task)
        s.cost_record(self.store, task["task_id"], "baseline", "attempt-base", "measured invoice", 2, 10, 60, acceptance_id=acceptance)
        s.cost_record(self.store, task["task_id"], "cheap", "attempt-retry", "measured first failure", 0.5, 20, 60)
        s.cost_record(self.store, task["task_id"], "cheap", "attempt-success", "measured retry", 0.5, 5, 60, acceptance_id=acceptance)
        result = s.cost_compare(self.store, ["baseline", "cheap"])
        self.assertTrue(result["comparison_supported"])
        self.assertEqual(result["totals"], {"baseline": 12, "cheap": 26})
        self.assertFalse(result["automatic_provider_change"])

    def test_unknown_cost_and_unmatched_tasks_do_not_produce_scores(self):
        task = self.task()
        other = self.task("T2-unmatched")
        s.cost_record(self.store, task["task_id"], "baseline", "base", "observation", 1, 0, None)
        s.cost_record(self.store, task["task_id"], "cheap", "cheap", "observation", 0.1, None, None)
        s.cost_record(self.store, other["task_id"], "cheap", "other", "observation", 0.1, 0, 60)
        result = s.cost_compare(self.store, ["baseline", "cheap"])
        self.assertFalse(result["comparison_supported"])
        self.assertIsNone(result["totals"])
        self.assertEqual(len(result["unmatched_task_revisions"]), 1)

    def test_view_is_read_only_and_cli_routes_services(self):
        self.put("Project/demo/pictures/a.md", "reference")
        self.refresh()
        before = {str(p.relative_to(self.root)): s.file_hash(p) for p in self.root.rglob("*.json")}
        view = s.view_records(self.store)
        after = {str(p.relative_to(self.root)): s.file_hash(p) for p in self.root.rglob("*.json")}
        self.assertEqual(before, after)
        self.assertEqual(view["health"]["source_cards"], 1)
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = main(["adapters", "list"], root=self.root, commit=False)
        self.assertEqual(code, 0)
        self.assertIn("codex", json.loads(output.getvalue())["adapters"])


if __name__ == "__main__":
    unittest.main()
