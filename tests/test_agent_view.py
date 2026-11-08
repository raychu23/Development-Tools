#!/usr/bin/env python3
"""Deterministic interface/protocol checks in temporary roots, no native trials."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import agent_view

HERE = Path(__file__).resolve().parents[1] / 'systems'


class BoardTests(unittest.TestCase):
    def test_empty_snapshot_has_semantic_navigation_and_deferred_boundary(self):
        text = agent_view.render_data({}, '/workspace')
        self.assertIn('aria-label="Board views"', text)
        self.assertIn('<main id="main">', text)
        self.assertIn('No tasks records', text)
        self.assertIn('live trials remain deferred', text)
        self.assertIn(':focus-visible', text)
        self.assertNotIn('<script', text)
        self.assertNotIn('https://', text)

    def test_untrusted_content_and_paths_do_not_become_executable(self):
        data = {'tasks': [{'task_id': 't', 'goal': '<script>alert(1)</script>', 'path': '../../outside', 'owner': '" onmouseover="bad'}], 'sources': [{'source_id': '<img>', 'path': 'javascript:alert(1)'}]}
        text = agent_view.render_data(data, '/workspace')
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', text)
        self.assertNotIn('<script>', text)
        self.assertNotIn('href="javascript:', text)
        self.assertNotIn('href="file:///outside', text)
        self.assertIn('&quot; onmouseover=&quot;bad', text)

    def test_revision_queue_delivery_ack_and_load_receipt_remain_distinct(self):
        task = {'task_id': 'task-a', 'path': 'Project/demo/T1-task', 'requirement_rev': 3, 'state': 'submitted', 'runs': [{'run_id': 'r1', 'requirement_rev': 2, 'receipt': {'requirement_rev': 1}, 'lease_until': 'expired'}], 'messages': [{'message_id': 'm1', 'status': 'queued', 'body': 'correction ready', 'requirement_rev': 3}], 'evidence': [{'report_id': 'e1', 'criterion_id': 'a1', 'requirement_rev': 2, 'stale': True, 'observed': 'passed', 'path': 'Project/demo/proof.txt'}]}
        text = agent_view.render_data({'tasks': [task]}, '/workspace')
        self.assertIn('requirement revision 3', text)
        self.assertIn('Loaded revision', text)
        self.assertIn('no delivery receipt', text)
        self.assertIn('no acknowledgement', text)
        self.assertIn('correction ready', text)
        self.assertIn('file:///workspace/Project/demo/proof.txt', text)
        self.assertIn('<td>True</td>', text)
        self.assertNotIn('session launched', text)

    def test_recovery_conflict_fields_are_visible(self):
        text = agent_view.render_data({'recovery': [{'operation_id': 'op-fixture', 'phase': 'conflict', 'conflicts': ['important.txt']}]}, '/tmp')
        self.assertIn('<td>conflict</td>', text)
        self.assertIn('important.txt', text)

    def test_load_error_is_visible_and_not_a_success_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'board.html'
            fake = types.SimpleNamespace(Store=lambda *a, **k: (_ for _ in ()).throw(ValueError('bad <contract>')))
            with patch.dict(sys.modules, {'agent_core': fake}):
                result = agent_view.render(root, output)
            self.assertFalse(result['ok'])
            text = output.read_text()
            self.assertIn('role="alert"', text)
            self.assertIn('bad &lt;contract&gt;', text)
            self.assertIn('does not represent a successful fresh read', text)

    def test_renderer_calls_engine_with_requested_scope(self):
        calls = []
        class FakeStore:
            def __init__(self, root, commit):
                calls.append((root, commit))
            def board(self, scope):
                calls.append(scope)
                return {'tasks': []}
            def locked(self):
                return contextlib.nullcontext()
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(sys.modules, {'agent_core': types.SimpleNamespace(Store=FakeStore), 'agent_services': types.SimpleNamespace(view_records=lambda *a, **k: {})}):
                result = agent_view.render(root, Path(root) / 'board.html', 'Project')
            self.assertEqual(calls, [(root, False), 'Project'])
            self.assertTrue(result['ok'])

    def test_real_engine_service_projection_renders_current_revision_without_mutations(self):
        from agent_core import Store
        with tempfile.TemporaryDirectory() as root:
            task = Path(root) / 'Project/demo/T1-task'
            task.mkdir(parents=True)
            (task / '0 start.md').write_text('```notes\n    task\n        goal    fixture only\n```\n')
            store = Store(root, commit=False)
            contract = store.enroll(str(task), 'owner-a', 'fixture only', ['visible revision'])
            before = (task / 'systems/task.json').read_bytes()
            result = agent_view.render(root, Path(root) / 'board.html')
            self.assertTrue(result['ok'], result['error'])
            text = (Path(root) / 'board.html').read_text()
            self.assertIn(contract['task_id'], text)
            self.assertIn('requirement revision 1', text)
            self.assertIn('native_trials', text)
            self.assertEqual((task / 'systems/task.json').read_bytes(), before)


class HookProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.task = Path(self.root) / 'Context/demo/T1-task'
        self.task.mkdir(parents=True)
        (self.task / '0 start.md').write_text('```notes\n    task\n        goal    actual work\n```\n')
        loader = importlib.machinery.SourceFileLoader('ctx_hook_protocol', str(HERE / 'ctx-hook'))
        spec = importlib.util.spec_from_loader('ctx_hook_protocol', loader)
        self.hook = importlib.util.module_from_spec(spec)
        loader.exec_module(self.hook)

    def tearDown(self):
        self.temp.cleanup()

    def run_hook(self, event, managed=False, boot=None):
        if managed:
            (self.task / 'systems').mkdir(exist_ok=True)
            (self.task / 'systems/task.json').write_text('{}')
        out = io.StringIO()
        env = {'CTX_ROOT': self.root, 'CTX_TASK': str(self.task)}
        core = types.SimpleNamespace(make_boot=lambda *a, **k: boot or {'text': 'full prioritized mandatory context', 'manifest': {'blocked': False, 'requirement_rev': 3, 'included': ['current constraints'], 'required_reads': []}})
        with patch.dict(os.environ, env), patch.dict(sys.modules, {'agent_core': core}), patch.object(sys, 'stdin', io.StringIO(json.dumps({'cwd': self.root, 'session_id': 'session-one'}))), contextlib.redirect_stdout(out):
            result = self.hook.main(['ctx-hook', event])
        self.assertEqual(result, 0)
        return json.loads(out.getvalue()) if out.getvalue() else {}

    def test_managed_boot_emission_does_not_claim_revision_ack(self):
        result = self.run_hook('session-start', managed=True)
        self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'SessionStart')
        self.assertIn('full prioritized mandatory context', result['hookSpecificOutput']['additionalContext'])
        beat = json.loads((Path(self.root) / 'systems/state/beats.json').read_text())['Context/demo/T1-task']
        self.assertEqual(beat['boot_emitted_revision'], 3)
        self.assertNotIn('loaded_revision', beat)
        self.assertNotIn('acknowledged_revision', beat)

    def test_managed_overflow_is_visible_and_never_sliced_again(self):
        boot = {'text': 'REQUIRED FILE MUST BE READ ENTIRELY', 'manifest': {'blocked': True, 'requirement_rev': 3, 'included': [], 'required_reads': ['0 start.md']}}
        result = self.run_hook('session-start', managed=True, boot=boot)
        self.assertIn('CTX BOOT BLOCKED', result['hookSpecificOutput']['additionalContext'])
        self.assertIn(boot['text'], result['hookSpecificOutput']['additionalContext'])

    def test_precompact_requests_checkpoint_without_fabricating_status(self):
        result = self.run_hook('pre-compact', managed=True)
        self.assertIn('CTX CHECKPOINT NEEDED', result['systemMessage'])
        self.assertIn('does not rewrite', result['systemMessage'])
        self.assertEqual((self.task / '0 start.md').read_text(), '```notes\n    task\n        goal    actual work\n```\n')

    def test_failure_protocol_visible_and_json_escaped(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.hook.visible_failure('session-start', ValueError('<bad task>'))
        result = json.loads(out.getvalue())
        self.assertIn('CTX TASK LOAD FAILED', result['hookSpecificOutput']['additionalContext'])


if __name__ == '__main__':
    unittest.main()
