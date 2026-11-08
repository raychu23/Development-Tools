"""hermes-hook: hermes gets the same §1 boot + complaint log as claude code / codex (T18 T1-core-layer)"""
# [source: Context/context-and-skills/T18-skills-home/T1-core-layer; added: 2026-10-15]
import importlib.machinery
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / 'systems'
sys.path.insert(0, str(HERE))
_loader = importlib.machinery.SourceFileLoader('hermes_hook', str(HERE / 'hermes-hook'))
_spec = importlib.util.spec_from_loader('hermes_hook', _loader)
hh = importlib.util.module_from_spec(_spec)
_loader.exec_module(hh)
from agent_core import Store  # noqa: E402
from native_activation import NativeRegistry  # noqa: E402
import ground_truth as gt  # noqa: E402

CORE = ('```notes\n1 core      said most\n    1  short + clear      answer what was asked      ×11\n    11 docs over chat      all to files      ×6\n```\n'
        '```notes\n3 inbox      x\n    d      "q"      s      → §1 #11 again\n    d      "q2"      s      → §1 #11 #1\n```\n')


class HermesHook(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'repo'; (self.root / 'Context').mkdir(parents=True)
        (self.root / gt.TAKEAWAYS).write_text(CORE)
        self.task = 'Project/demo/T1-active'; folder = self.root / self.task; folder.mkdir(parents=True)
        (folder / '0 start.md').write_text('```notes\n    goal                    demo goal\n    next                    step x\n```\n')
        store = Store(self.root, commit=False)
        contract = store.enroll(self.task, 'owner', 'demo goal', ['works'])
        self.registry = NativeRegistry(self.root, base / 'private')
        self.registry.register(self.task, contract['owner_token'])
        self.home = base / 'hermes'; self.home.mkdir()
        con = sqlite3.connect(self.home / 'state.db')
        con.execute('create table sessions (id text, cwd text)')
        con.execute('insert into sessions values (?, ?)', ('s-root', str(self.root)))
        con.execute('insert into sessions values (?, ?)', ('s-task', str(folder)))
        con.execute('insert into sessions values (?, ?)', ('s-out', str(base)))
        con.commit(); con.close()
        self.env = patch.dict(os.environ, {'HERMES_HOME': str(self.home)}, clear=False); self.env.start(); self.addCleanup(self.env.stop)

    def run_hook(self, sid, msg, first, event='pre_llm_call'):
        payload = {'hook_event_name': event, 'session_id': sid, 'cwd': str(Path.home()),
                   'extra': {'user_message': msg, 'is_first_turn': first, 'conversation_history': []}}
        return hh.context_text(str(self.root), payload, self.registry)

    def inbox(self):
        p = self.root / gt.INBOX
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def test_first_turn_in_cs_code_gets_core_and_routing(self):
        out = self.run_hook('s-root', 'hello', True)
        self.assertIn('1  short + clear', out)
        self.assertIn('no task binding', out)

    def test_cwd_comes_from_state_db_not_gateway(self):
        # payload cwd = home (desktop gateway); state.db says task folder → task boot
        out = self.run_hook('s-task', 'hello', True)
        self.assertIn('CTX native task: ' + self.task, out)
        self.assertIn('demo goal', out)

    def test_complaint_logged_with_harness_hermes(self):
        out = self.run_hook('s-root', 'why do you keep forgetting my rules again, i told you', False)
        self.assertIn('auto-logged', out)
        rows = self.inbox()
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['harness'], 'hermes'); self.assertEqual(rows[0]['session'], 's-root')

    def test_later_turn_no_complaint_is_silent(self):
        self.run_hook('s-root', 'hello', True)
        self.assertEqual(self.run_hook('s-root', 'list the files please', False), '')

    def test_outside_cs_code_gets_nothing_and_logs_nothing(self):
        self.assertEqual(self.run_hook('s-out', 'why do you keep forgetting, i told you', True), '')
        self.assertEqual(self.run_hook('s-out', 'why do you keep forgetting, i told you', False), '')
        self.assertEqual(self.inbox(), [])

    def test_subagent_handback_never_logged(self):
        msg = '<agent-message from="a1">\n[Subagent hand-back] why do you keep forgetting, i told you ' + 'x' * 9000
        self.assertEqual(self.run_hook('s-root', msg, False), '')
        self.assertEqual(self.inbox(), [])

    def test_subagent_brief_never_logged(self):
        payload = {'hook_event_name': 'pre_llm_call', 'session_id': 's-task', 'cwd': str(Path.home()),
                   'extra': {'user_message': 'CONTEXT: make sure every test passes before you report', 'is_first_turn': True, 'platform': 'subagent'}}
        self.assertEqual(hh.context_text(str(self.root), payload, self.registry), '')
        self.assertEqual(self.inbox(), [])

    def test_reminder_only_from_turn_10(self):
        outs = [self.run_hook('s-root', 'next step please', i == 0) for i in range(10)]
        self.assertNotIn('reminder', outs[8])
        self.assertIn('Turn 10 reminder', outs[9]); self.assertIn('§1 #11 docs over chat', outs[9])
        self.assertLess(len(outs[9].split('Turn 10 reminder')[1]), 600)

    def hist(self, calls):
        tc = [{'function': {'name': n, 'arguments': json.dumps(a)}} for n, a in calls]
        return [{'role': 'user', 'content': 'do it'}, {'role': 'assistant', 'content': '', 'tool_calls': tc},
                {'role': 'tool', 'content': 'ok'}, {'role': 'assistant', 'content': 'done'}, {'role': 'user', 'content': 'next'}]

    def map_folder(self, sid, folder):
        p = self.root / hh.FOLDERS; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({sid: str(folder)}))

    def test_sensor(self):
        task = self.root / self.task
        code = str(self.root / 'systems/x.py')
        self.assertIn('no task folder', hh.save_nudge(str(self.root), 's-root', self.hist([('write_file', {'path': code})])))
        self.map_folder('s-root', task)
        self.assertIn('wrote nothing to the task folder', hh.save_nudge(str(self.root), 's-root', self.hist([('write_file', {'path': code})])))
        self.assertEqual(hh.save_nudge(str(self.root), 's-root', self.hist([('write_file', {'path': code}), ('patch', {'path': str(task / '0 start.md')})])), '')
        self.assertEqual(hh.save_nudge(str(self.root), 's-root', self.hist([('terminal', {'command': f'git commit -- "{self.task}/0 start.md"'})])), '')
        self.assertEqual(hh.save_nudge(str(self.root), 's-root', self.hist([('read_file', {'path': code})])), '')
        self.assertEqual(hh.save_nudge(str(self.root), 's-root', [{'role': 'user', 'content': 'hi'}]), '')

    def test_doc_style_idempotent(self):
        import subprocess as sp
        sys.path.insert(0, str(HERE.parent / 'skills/all/system/docs-over-chat/scripts')); import doc_style
        d = self.root / 'docs'; d.mkdir(); f = d / 'doc.html'; f.write_text('<nav>n</nav><main>m</main>')
        sp.run(['git', 'init', '-q', str(self.root)]); sp.run(['git', '-C', str(self.root), 'add', '.'])
        sp.run(['git', '-C', str(self.root), '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'first'])
        self.assertTrue(doc_style.apply(f)); self.assertFalse(doc_style.apply(f))
        self.assertEqual(f.read_text().count('data-doc-recent>'), 1)
        for page in ('<nav>n</nav>\n<main>m</main>\n', '<head><style>x</style></head>\n<main class="a">m</main>\n', '<nav>n</nav>\n\n<section>s</section>'):
            f.write_text(page)
            runs = [doc_style.apply(f) for _ in range(3)]
            self.assertEqual(runs[1:], [False, False], page)

    def test_sensor_folder_prefix(self):
        self.map_folder('s-root', self.root / 'Project/demo/T1')
        self.assertIn('wrote nothing', hh.save_nudge(str(self.root), 's-root', self.hist([('write_file', {'path': str(self.root / 'Project/demo/T18/x.md')})])))

    def test_sensor_owner_task_not_chat_folder(self):
        """work in task X is saved by X's level file even when the chat is mapped to another task"""
        self.map_folder('s-root', self.root / 'Project/demo/T18-chat')
        other = self.root / 'Project/demo/T16-other'
        h = lambda *c: self.hist(list(c))
        self.assertEqual(hh.save_nudge(str(self.root), 's-root', h(('write_file', {'path': str(other / 'x.py')}), ('patch', {'path': str(other / '1 takeaways.md')}))), '')
        out = hh.save_nudge(str(self.root), 's-root', h(('write_file', {'path': str(other / 'x.py')}), ('patch', {'path': str(self.root / 'Project/demo/T18-chat/0 start.md')})))
        self.assertIn('Project/demo/T16-other', out)   # T18 got the save, T16 (owner of the code) did not
        self.assertEqual(hh.save_nudge(str(self.root), 's-root', h(('write_file', {'path': str(other / '0 start.md')}))), '')

    def test_list_content_message(self):
        out = self.run_hook('s-root', [{'type': 'text', 'text': 'i told you already, stop doing that'}], False)
        self.assertIn('auto-logged', out)

    def test_finalize_releases_and_prints_nothing(self):
        self.run_hook('s-task', 'hello', True)
        self.assertEqual(self.run_hook('s-task', '', False, event='on_session_finalize'), '')

    def test_script_never_breaks_on_garbage(self):
        r = subprocess.run([sys.executable, str(HERE / 'hermes-hook'), '--root', str(self.root)], input='not json',
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0); self.assertEqual(r.stdout, '')


if __name__ == '__main__':
    unittest.main()
