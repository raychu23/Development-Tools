"""T10 ground truth hooks: core injection at session start, complaint capture on prompt (rules.md §5)"""
import json
import os
import sys
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ground_truth as gt
from agent_core import Store
from native_activation import NativeRegistry, handle_hook

CORE = ('# 1 takeaways\n\n```notes\nheader      ignored\n```\n\n```notes\n1 core      said most\n'
        '    1  short + clear      ×11\n    2  keep my text      ×10\n```\n\n```notes\n2 open gaps\n    x\n```\n')


class Detect(unittest.TestCase):
    def test_hits_in_raymonds_phrasing(self):
        for text in ['why do you keep forgetting the links', 'i told you already, notes style',
                     'nonono. stop genirifying', 'Ive told you i want the ai-memory repo',
                     'what the hell. clickable paths', 'no thats wrong, use the official mask',
                     'i dont get what you did here, way too much text', 'didnt i tell you to keep my structure',
                     'from now on always give me full paths and make sure you link them']:
            self.assertTrue(gt.detect(text)[0], text)

    def test_misses_plain_requests_and_empty(self):
        for text in ['', '   ', 'ok', 'run the tests for lab3', 'can you summarize this paper section',
                     'fix the import error in train.py', 'no problem, go ahead', '{"type":"tool_result"}', '/compact',
                     'wait for the build to finish then run tests', 'stop the dev server and restart it on 3001',
                     'why does it return None here', 'no rush, do it tomorrow', 'still need to run the tests',
                     'never mind, run the eval', 'huh interesting, explain more', 'i meant to ask: what is a monad']:
            self.assertFalse(gt.detect(text)[0], text)

    def test_wrappers_are_ignored(self):
        wrapped = '<in-app-browser-context source="ambient">why do you keep this</in-app-browser-context>\nrun the tests'
        self.assertFalse(gt.detect(wrapped)[0])
        codex = '# Files mentioned by the user:\n## a.png: /tmp/a.png\n## My request for Codex:\nno thats wrong'
        self.assertEqual(gt.human_text(codex), 'no thats wrong')
        self.assertTrue(gt.detect(codex)[0])

    def test_user_tags_are_kept(self):
        self.assertTrue(gt.detect('<b>why do you</b> keep doing this')[0])
        self.assertTrue(gt.detect('<note>i told you already</note>')[0])

    def test_long_adversarial_prompts_are_fast(self):
        for text in ['<a ' * 70000, 'List<Integer> x;\n' * 25000, '<in-app-browser-context x>' * 20000,
                     '# Files mentioned by the user:\n' + '## f.png: /x\n' * 20000 + '## My request for Codex:\nwhy do you keep doing this']:
            t = time.time(); gt.detect(text); self.assertLess(time.time() - t, 1.0, text[:30])

    def test_redact_common_pastes(self):
        for secret in ['AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY', 'GITHUB_TOKEN=github_pat_11ABCDEFGHIJKLMNOPQRSTUV',
                       '{"token": "abcd1234efgh5678"}', 'stripe sk_live_51Habcdefghijklmnopqr', 'postgres://ray:S3cretPassw0rd@db:5432',
                       'google AIzaSyA1234567890abcdefghijklmnopqrstuv', 'hf_AbCdEfGhIjKlMnOpQrStUvWxYz1234567',
                       'my password is Tr0ub4dor&3xyz', 'Bearer abcdefghijklmnop.qrst']:
            self.assertIn('[redacted]', gt.redact(secret), secret)
        for clean in ['risk-assessment-for-the-api', 'token limit is 200k', 'the secret sauce is notes style']:
            self.assertEqual(gt.redact(clean), clean)

    def test_redact(self):
        out = gt.redact('key AKIAABCDEFGHIJKLMNOP and sk-abcdefghijklmnopqrstuv and password=hunter2hunter2 ok')
        self.assertNotIn('AKIA', out); self.assertNotIn('sk-abc', out); self.assertNotIn('hunter2', out); self.assertIn('ok', out)

    def test_never_raises(self):
        self.assertEqual(gt.detect(None), (False, []))
        self.assertEqual(gt.detect(12345), (False, []))


class Core(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, text):
        p = self.root / gt.TAKEAWAYS; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)

    def test_changes_notice_only_when_piled(self):
        self.write('```notes\n1 core      x\n    1  short\n```\n')
        st = self.root / 'Context/systems/changes state.json'; st.parent.mkdir(parents=True, exist_ok=True)
        st.write_text('{"pending": 3, "piled": false}'); self.assertNotIn('waiting for', gt.core_block(self.root))
        st.write_text('{"pending": 20, "piled": true}'); self.assertIn('20 system changes are waiting', gt.core_block(self.root))
        st.write_text('garbage'); self.assertIn('1  short', gt.core_block(self.root))

    def test_turn_reminder(self):
        self.write('```notes\n1 core      x\n    1  short + clear      no filler      ×11\n    16 where it is      full path      ×5\n```\n```notes\n3 inbox      x\n    d      "a"      s      → §1 #16\n```\n')
        r = [gt.turn_reminder(self.root, 'sess') for _ in range(10)]
        self.assertEqual(r[2], ''); self.assertIn('§1 #16 where it is', r[9]); self.assertNotIn('#1 short', r[9])
        self.assertEqual(gt.turn_reminder(self.root, ''), '')

    def test_core_block_only(self):
        self.write(CORE)
        out = gt.core_block(self.root)
        self.assertIn('1  short + clear', out); self.assertNotIn('open gaps', out); self.assertNotIn('header', out)
        self.assertTrue(out.startswith("Raymond's ground truth"))

    def test_missing_or_garbled(self):
        self.assertEqual(gt.core_block(self.root), '')
        self.write('no fences at all'); self.assertEqual(gt.core_block(self.root), '')
        self.write('```notes\n1 core\n   unclosed'); self.assertEqual(gt.core_block(self.root), '')
        (self.root / gt.TAKEAWAYS).write_bytes(b'\xff\xfe\x00bad'); self.assertEqual(gt.core_block(self.root), '')

    def test_cap(self):
        self.write('```notes\n1 core\n' + ''.join(f'    {i}  rule {"x"*60}\n' for i in range(200)) + '```\n')
        out = gt.core_block(self.root, cap=1000)
        self.assertLess(len(out), 1000 + len(gt.HEAD) + 80); self.assertIn('… cut', out)

    def test_log_appends_verbatim(self):
        r1 = gt.log(self.root, 'why do you keep — “quotes” ok', ['why-you'], 'codex', 's1', '/x')
        gt.log(self.root, 'second', ['again'])
        rows = [json.loads(l) for l in (self.root / gt.INBOX).read_text().splitlines()]
        self.assertEqual(len(rows), 2); self.assertEqual(rows[0]['prompt'], 'why do you keep — “quotes” ok')
        self.assertFalse(rows[0]['folded']); self.assertEqual(r1['harness'], 'codex')
        self.assertEqual(oct((self.root / gt.INBOX).stat().st_mode & 0o777), '0o600')

    def test_log_never_raises(self):
        (self.root / 'Context').mkdir(); (self.root / 'Context' / 'systems').write_text('a file, not a dir')
        self.assertIsNone(gt.log(self.root, 'x', []))
        self.assertIn('auto-logged', gt.on_prompt(self.root, {'prompt': 'why do you keep doing this'}))


class Hooks(unittest.TestCase):
    """the real native hook path: bound task, unbound CS Code session, out-of-scope cwd"""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'; self.root.mkdir()
        p = self.root / gt.TAKEAWAYS; p.parent.mkdir(parents=True); p.write_text(CORE)
        self.task = 'Project/demo/T1-active'; self.folder = self.root / self.task; self.folder.mkdir(parents=True)
        (self.folder / '0 start.md').write_text('```notes\n    goal                    g\n    status                  active\n    next                    n\n```\n')
        store = Store(self.root, commit=False)
        contract = store.enroll(self.task, 'owner', 'g', ['done'])
        self.reg = NativeRegistry(self.root, Path(self.tmp.name) / 'private')
        self.reg.register(self.task, contract['owner_token'])
        self.env = patch.dict(os.environ, {}, clear=True); self.env.start(); self.addCleanup(self.env.stop)
        self.outside = Path(self.tmp.name) / 'elsewhere'; self.outside.mkdir()

    def ctx(self, out):
        return (out or {}).get('hookSpecificOutput', {}).get('additionalContext', '')

    def test_session_start_bound_unbound_compact(self):
        for cwd, source in [(self.folder, 'startup'), (self.root, 'startup'), (self.root, 'compact'), (self.folder, 'resume')]:
            for harness in ['codex', 'claude-code']:
                text = self.ctx(handle_hook(self.reg, harness, 'session-start', {'session_id': f'{harness}-{cwd.name}-{source}', 'cwd': str(cwd), 'source': source}))
                self.assertIn('1  short + clear', text, (cwd, source, harness))
                self.assertLessEqual(len(text), 9500, (cwd, source, harness))
        bound = self.ctx(handle_hook(self.reg, 'codex', 'session-start', {'session_id': 'b2', 'cwd': str(self.folder)}))
        self.assertIn('CTX native task', bound)
        unbound = self.ctx(handle_hook(self.reg, 'codex', 'session-start', {'session_id': 'u2', 'cwd': str(self.root)}))
        self.assertIn('CTX native routing', unbound)

    def test_out_of_scope_untouched(self):
        self.assertIsNone(handle_hook(self.reg, 'codex', 'session-start', {'session_id': 'o', 'cwd': str(self.outside)}))
        self.assertIsNone(handle_hook(self.reg, 'codex', 'prompt', {'session_id': 'o', 'cwd': str(self.outside), 'prompt': 'why do you keep forgetting'}))
        self.assertFalse((self.root / gt.INBOX).exists())

    def test_prompt_hit_logs_and_reminds_miss_is_silent(self):
        d = {'session_id': 'p1', 'cwd': str(self.root)}
        handle_hook(self.reg, 'claude-code', 'session-start', d)
        self.assertNotIn('auto-logged', self.ctx(handle_hook(self.reg, 'claude-code', 'prompt', dict(d, prompt='run the tests'))))
        self.assertFalse((self.root / gt.INBOX).exists())
        self.assertNotIn('auto-logged', self.ctx(handle_hook(self.reg, 'claude-code', 'prompt', dict(d, prompt='')))) # unbound sessions get the routing board on every prompt (pre-existing)
        out = self.ctx(handle_hook(self.reg, 'claude-code', 'prompt', dict(d, prompt='i told you already, links every time')))
        self.assertIn('auto-logged', out)
        rows = [json.loads(l) for l in (self.root / gt.INBOX).read_text().splitlines()]
        self.assertEqual(rows[-1]['prompt'], 'i told you already, links every time'); self.assertEqual(rows[-1]['harness'], 'claude-code')

    def test_bound_boot_not_resent_on_first_prompt(self):
        d = {'session_id': 'rs', 'cwd': str(self.folder)}
        self.assertIn('CTX native task', self.ctx(handle_hook(self.reg, 'codex', 'session-start', d)))
        self.assertNotIn('CTX native task', self.ctx(handle_hook(self.reg, 'codex', 'prompt', dict(d, prompt='run the tests'))))

    def test_big_packet_keeps_priority(self):
        (self.folder / '0 start.md').write_text('```notes\n    goal                    g\n    status                  active\n    next                    n\n'
                                                + ''.join(f'    row{i:03d}                  {"y"*50}\n' for i in range(75)) + '```\n')
        text = self.ctx(handle_hook(self.reg, 'codex', 'session-start', {'session_id': 'big', 'cwd': str(self.folder)}))
        self.assertIn('row070', text); self.assertLessEqual(len(text), 9500)

    def test_home_cwd_is_in_scope_and_redacted(self):
        # decision: home-dir sessions are raymond's too (existing boot scope) → captured, secrets redacted (T10 2 insights)
        with patch('pathlib.Path.home', return_value=self.outside):
            out = self.ctx(handle_hook(self.reg, 'codex', 'prompt', {'session_id': 'h', 'cwd': str(self.outside),
                                                                   'prompt': 'why do you keep pasting AKIAABCDEFGHIJKLMNOP'}))
        self.assertIn('auto-logged', out)
        row = json.loads((self.root / gt.INBOX).read_text().splitlines()[-1])
        self.assertNotIn('AKIA', row['prompt'])

    def test_broken_module_never_breaks_hooks(self):
        with patch.dict(sys.modules, {'ground_truth': None}):
            text = self.ctx(handle_hook(self.reg, 'codex', 'session-start', {'session_id': 'bm', 'cwd': str(self.folder)}))
        self.assertIn('CTX native task', text); self.assertNotIn("Raymond's ground truth", text)

    def test_garbled_takeaways_still_boots(self):
        (self.root / gt.TAKEAWAYS).write_text('garbled')
        text = self.ctx(handle_hook(self.reg, 'codex', 'session-start', {'session_id': 'g', 'cwd': str(self.folder)}))
        self.assertIn('CTX native task', text); self.assertNotIn("Raymond's ground truth", text)


if __name__ == '__main__':
    unittest.main()
