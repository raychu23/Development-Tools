"""unit tests for systems/ctx      run: python3 -m unittest systems/test_ctx.py   (or python3 systems/test_ctx.py)"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True  # no __pycache__ beside the scripts
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'systems')
_loader = importlib.machinery.SourceFileLoader('ctx', os.path.join(HERE, 'ctx'))
_spec = importlib.util.spec_from_loader('ctx', _loader)
ctx = importlib.util.module_from_spec(_spec)
_loader.exec_module(ctx)

TASK = '''```notes
T9-demo      demo task
    goal                    make the demo work
    done-when               tests pass
    status                  2026-10-11      building
    next                    1 write tests      2 run them
    pinned                  nothing ever deleted
    came from               test fixture
    links                   c idea-one/0 start.md      ../../rules.md
    harness                 test
```

```notes
questions
    q1 order                a first?
        a
```
'''

SUB = '''```notes
c idea-one      subidea of T9
    goal                    try idea one
    done-when               decided
    status                  explored, keep the parser part
    next                    —
    pinned                  —
    came from               T9-demo
    links                   ../0 start.md
    harness                 test
```
'''

AGENT = '''---
owner: T9-a1-build
status: building
---
```notes
T9-a1-build      agent run 1 of T9
    goal                    build it
    done-when               merged
    status                  started
    next                    write ctx
    pinned                  own branch
    came from               T9
    links                   ../0 start.md
    harness                 test
```
'''

NOTE = '''---
carry: auto
---
```notes
note x
    idea                    a loose idea note, only loaded when pinned
```
'''


def run(*args, cwd=None):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=True).stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.task = os.path.join(self.root, 'Context', 'proj', 'T9-demo')
        files = {
            'Context/0 start.md': '```notes\nContext\n    status                  topic\n```\n',
            'Context/proj/T9-demo/0 start.md': TASK,
            'Context/proj/T9-demo/c idea-one/0 start.md': SUB,
            'Context/proj/T9-demo/T9-a1-build/0 start.md': AGENT,
            'Context/proj/T9-demo/note-x.md': NOTE,
            'Context/proj/T9-demo/2 insights.md': '```notes\ninsights\n    see c idea-one/0 start.md\n```\n',
            'other/untouched.md': 'keep me\n',
        }
        for p, t in files.items():
            full = os.path.join(self.root, p)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w', encoding='utf-8') as f:
                f.write(t)
        run('git', 'init', '-q', '-b', 'main', cwd=self.root)
        run('git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '-A', cwd=self.root)
        run('git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'fixture', cwd=self.root)
        self.env = dict(os.environ)
        os.environ.pop('CTX_TRAILERS', None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def ctx(self, *args, ok=True):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ctx.main(['--root', self.root] + list(args))
        if ok:
            self.assertEqual(code, 0, err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def read(self, p):
        with open(os.path.join(self.root, p), encoding='utf-8') as f:
            return f.read()

    def git(self, *a):
        return run('git', *a, cwd=self.root)

    def commits(self):
        return int(self.git('rev-list', '--count', 'HEAD').strip())

    def no_deletes(self):
        """nothing ever deleted: no D in history (renames count as R), working tree clean"""
        self.assertEqual(self.git('log', '-M', '--diff-filter=D', '--name-only', '--format=').strip(), '')


T = 'Context/proj/T9-demo'


class TestTree(Base):
    def test_tree_kinds_and_depth(self):
        _, out, _ = self.ctx('tree', 'Context', '--json')
        rows = {r['name']: r for r in json.loads(out)}
        self.assertEqual(rows['T9-demo']['kind'], 'task')
        self.assertEqual(rows['c idea-one']['kind'], 'current')
        self.assertEqual(rows['T9-a1-build']['kind'], 'agent')
        self.assertEqual(rows['note-x']['kind'], 'note')
        self.assertEqual(rows['c idea-one']['depth'], rows['T9-demo']['depth'] + 1)
        self.assertEqual(rows['T9-demo']['status'], '2026-10-11 building')  # a leading date takes the next segment along
        self.assertEqual(rows['T9-a1-build']['status'], 'building')  # frontmatter wins
        self.assertEqual(rows['T9-demo']['needs_you'], 1)

    def test_scope_resolves_against_root_when_cwd_outside(self):
        other = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(other.name, 'Context', 'T1-decoy'))
        with open(os.path.join(other.name, 'Context', 'T1-decoy', '0 start.md'), 'w') as f:
            f.write('```notes\nT1-decoy\n```\n')
        here = os.getcwd()
        try:
            os.chdir(other.name)
            _, out, _ = self.ctx('tree', 'Context', '--json')
        finally:
            os.chdir(here)
            other.cleanup()
        names = [r['name'] for r in json.loads(out)]
        self.assertIn('T9-demo', names)
        self.assertNotIn('T1-decoy', names)

    def test_tree_text(self):
        _, out, _ = self.ctx('tree', T)
        self.assertIn('T9-demo', out)
        self.assertIn('    c idea-one', out)

    def test_board_lists_agents_only(self):
        _, out, _ = self.ctx('board', 'Context', '--json')
        names = [r['name'] for r in json.loads(out)]
        self.assertEqual(names, ['T9-a1-build'])


class TestCarry(Base):
    def test_pin_note_sets_frontmatter_and_commits(self):
        n = self.commits()
        self.ctx('pin', f'{T}/c idea-one')
        t = self.read(f'{T}/c idea-one/0 start.md')
        self.assertTrue(t.startswith('---\ncarry: pin\n---\n```notes'))
        self.assertEqual(self.commits(), n + 1)
        self.assertEqual(self.git('log', '-1', '--format=%an|%ae').strip(), 'Raymond Chu|')
        self.assertIn('ctx pin', self.git('log', '-1', '--format=%s'))
        self.assertEqual(self.git('status', '--porcelain').strip(), '')

    def test_pin_text_adds_aligned_continuation(self):
        self.ctx('pin', T, '--text', 'keep parser idea')
        lines = self.read(f'{T}/0 start.md').split('\n')
        i = next(k for k, l in enumerate(lines) if l.startswith('    pinned'))
        self.assertEqual(lines[i + 1], ' ' * 28 + 'keep parser idea')
        self.assertTrue(lines[i + 2].startswith('    came from'))

    def test_drop_text_moves_line_to_log(self):
        self.ctx('pin', T, '--text', 'temp idea zz')
        self.ctx('drop', T, '--text', 'temp idea zz')
        self.assertNotIn('temp idea zz', self.read(f'{T}/0 start.md'))
        log = self.read(f'{T}/4 log/dropped.md')
        self.assertIn('pinned      temp idea zz', log)
        self.assertTrue(log.startswith('```notes\ndropped'))
        self.no_deletes()

    def test_drop_segment_keeps_cue(self):
        self.ctx('drop', T, '--text', '2 run them')
        t = self.read(f'{T}/0 start.md')
        self.assertIn('    next                    1 write tests\n', t)
        self.assertIn('2 run them', self.read(f'{T}/4 log/dropped.md'))

    def test_drop_ambiguous_refused(self):
        code, _, err = self.ctx('drop', T, '--text', 'e', ok=False)
        self.assertEqual(code, 2)
        self.assertIn('more specific', err)

    def test_drop_and_auto_note(self):
        self.ctx('drop', f'{T}/note-x.md')
        self.assertIn('carry: drop', self.read(f'{T}/note-x.md'))
        self.ctx('auto', f'{T}/note-x.md')
        self.assertIn('carry: auto', self.read(f'{T}/note-x.md'))
        self.assertNotIn('carry: drop', self.read(f'{T}/note-x.md'))

    def test_commit_only_touches_its_paths(self):
        with open(os.path.join(self.root, 'other/untouched.md'), 'a') as f:
            f.write('raymond typing\n')
        self.ctx('pin', f'{T}/c idea-one')
        self.assertIn('other/untouched.md', self.git('status', '--porcelain'))
        self.assertNotIn('other/untouched.md', self.git('show', '--name-only', '--format=', 'HEAD'))

    def test_trailers(self):
        os.environ['CTX_TRAILERS'] = 'Co-Authored-By: Claude <noreply@anthropic.com>\nClaude-Session: https://x'
        self.ctx('pin', f'{T}/c idea-one', )
        body = self.git('log', '-1', '--format=%B')
        self.assertIn('Co-Authored-By: Claude <noreply@anthropic.com>', body)
        self.assertIn('Claude-Session: https://x', body)

    def test_no_commit_flag(self):
        n = self.commits()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ctx.main(['--root', self.root, '--no-commit', 'pin', f'{T}/c idea-one'])
        self.assertEqual(code, 0)
        self.assertIn('carry: pin', self.read(f'{T}/c idea-one/0 start.md'))
        self.assertEqual(self.commits(), n)


class TestTree2(Base):
    def test_merge_up(self):
        self.ctx('merge-up', f'{T}/c idea-one')
        t = self.read(f'{T}/0 start.md')
        lines = t.split('\n')
        i = next(k for k, l in enumerate(lines) if l.startswith('    merged up'))
        self.assertIn('c idea-one      try idea one · explored, keep the parser part', lines[i])
        self.assertTrue(lines[i + 1].startswith('    came from'))

    def test_merge_up_custom_text_appends(self):
        self.ctx('merge-up', f'{T}/c idea-one', '--text', 'first')
        self.ctx('merge-up', f'{T}/c idea-one', '--text', 'second')
        t = self.read(f'{T}/0 start.md')
        self.assertIn('c idea-one      first\n' + ' ' * 28, t)
        self.assertIn('c idea-one      second', t)

    def test_relegate(self):
        before = sorted(self.git('ls-files').split('\n'))
        self.ctx('relegate', f'{T}/c idea-one')
        self.assertFalse(os.path.exists(os.path.join(self.root, T, 'c idea-one')))
        self.assertTrue(os.path.isfile(os.path.join(self.root, T, 'o idea-one', '0 start.md')))
        t = self.read(f'{T}/0 start.md')
        self.assertIn('o idea-one      try idea one', t)  # merged up, then link-fixed
        self.assertIn('o idea-one/0 start.md', t)
        self.assertIn('o idea-one/0 start.md', self.read(f'{T}/2 insights.md'))
        self.assertEqual(self.read(f'{T}/o idea-one/0 start.md'), SUB)  # moved as-is
        self.assertEqual(len(self.git('ls-files').split('\n')), len(before))
        self.assertEqual(self.git('status', '--porcelain').strip(), '')
        self.assertIn('R', self.git('show', '-M', '--name-status', '--format=', 'HEAD'))
        self.no_deletes()
        self.assertIn('try idea one', self.git('log', '--follow', '-p', '--', f'{T}/o idea-one/0 start.md'))

    def test_relegate_dead(self):
        self.ctx('relegate', f'{T}/c idea-one', '--dead')
        self.assertTrue(os.path.isdir(os.path.join(self.root, T, 'd idea-one')))
        _, out, _ = self.ctx('boot', T)
        self.assertIn('dropped (not loaded): ' + T + '/d idea-one', out)

    def test_relegate_refuses(self):
        code, _, err = self.ctx('relegate', f'{T}/T9-a1-build', ok=False)
        self.assertEqual(code, 2)
        os.makedirs(os.path.join(self.root, T, 'o idea-one'))
        code, _, err = self.ctx('relegate', f'{T}/c idea-one', ok=False)
        self.assertIn('already exists', err)
        self.assertTrue(os.path.isdir(os.path.join(self.root, T, 'c idea-one')))

    def test_relegate_skips_merge_when_already_merged(self):
        self.ctx('merge-up', f'{T}/c idea-one', '--text', 'by hand')
        self.ctx('relegate', f'{T}/c idea-one')
        self.assertEqual(self.read(f'{T}/0 start.md').count('o idea-one      '), 1)


class TestBot(Base):
    def test_rotate(self):
        self.ctx('set', T, 'session=cse_old')
        _, out, _ = self.ctx('rotate', T)
        log = self.read(f'{T}/4 log/sessions.md')
        self.assertIn('old session cse_old', log)
        t = self.read(f'{T}/0 start.md')
        self.assertIn('session:\n', t)
        self.assertIn('rotated: ', t)
        self.assertIn('# boot pack', out)
        self.no_deletes()

    def test_send_inbox(self):
        self.ctx('send', T, 'please review ctx', '--from', 'T1')
        self.ctx('send', T, 'second msg', '--from', 'T3')
        t = self.read(f'{T}/0 start.md')
        self.assertEqual(t.count('```notes\ninbox'), 1)
        self.assertIn('from T1 → T9-demo      please review ctx\n        a\n', t)
        self.assertLess(t.index('please review ctx'), t.index('second msg'))
        _, out, _ = self.ctx('tree', T, '--json')
        self.assertEqual(json.loads(out)[0]['needs_you'], 3)

    def test_boot_pack(self):
        self.ctx('pin', f'{T}/note-x.md')
        self.ctx('drop', f'{T}/c idea-one')
        self.ctx('send', T, 'hello', '--from', 'T1')
        _, out, _ = self.ctx('boot', T)
        self.assertIn(f'## {T}/0 start.md', out)
        self.assertIn('a loose idea note', out)  # pinned note in full
        self.assertNotIn('try idea one', out)  # dropped
        self.assertIn('dropped (not loaded)', out)
        self.assertIn('hello', out)  # inbox
        _, short, _ = self.ctx('boot', T, '--max-chars', '200')
        self.assertIn('boot pack cut at 200', short)

    def test_boot_from_inside_task(self):
        _, out, _ = self.ctx('boot', f'{T}/note-x.md')
        self.assertIn(f'## {T}/0 start.md', out)

    def test_beat_no_commit_and_board(self):
        n = self.commits()
        self.ctx('beat', f'{T}/T9-a1-build', '--session', 's1', '--harness', 'cowork')
        self.assertEqual(self.commits(), n)
        self.assertEqual(self.git('status', '--porcelain').strip(), '')  # state is git-ignored
        b = json.loads(self.read('systems/state/beats.json'))
        self.assertEqual(b[f'{T}/T9-a1-build']['session'], 's1')
        _, out, _ = self.ctx('board', 'Context', '--json')
        self.assertTrue(json.loads(out)[0]['heartbeat'])
        _, txt, _ = self.ctx('board', 'Context')
        self.assertIn('0m', txt)

    def test_beat_status_commits(self):
        n = self.commits()
        self.ctx('beat', f'{T}/T9-a1-build', '--status', 'tests green')
        self.assertEqual(self.commits(), n + 1)
        self.assertIn('status: tests green', self.read(f'{T}/T9-a1-build/0 start.md'))

    def test_set_and_packet_untouched(self):
        self.ctx('set', T, 'owner=T9', 'next=ship')
        t = self.read(f'{T}/0 start.md')
        self.assertTrue(t.startswith('---\nowner: T9\nnext: ship\n---\n'))
        self.assertTrue(t.endswith(TASK))

    def test_full_sequence_nothing_deleted(self):
        files_before = len(self.git('ls-files').split('\n'))
        for args in (('pin', f'{T}/note-x.md'), ('pin', T, '--text', 'x1'), ('drop', T, '--text', 'x1'),
                     ('merge-up', f'{T}/c idea-one'), ('relegate', f'{T}/c idea-one'), ('rotate', T),
                     ('send', T, 'hi'), ('auto', f'{T}/note-x.md')):
            self.ctx(*args)
        self.no_deletes()
        self.assertGreaterEqual(len(self.git('ls-files').split('\n')), files_before)
        self.assertEqual(self.git('status', '--porcelain').strip(), '')


def notes_check(test, root, task):
    """the parts of systems/check-task.sh that ctx output can break: fences, notes blocks, 4-space grid, no semicolons, packet ≤40"""
    import re as _re
    for cur, subs, files in os.walk(os.path.join(root, task)):
        for fn in files:
            if not fn.endswith('.md'):
                continue
            t = ctx.read(os.path.join(cur, fn))
            body = t.split('\n---\n', 1)[1] if t.startswith('---\n') else t
            test.assertEqual(body.count('```') % 2, 0, fn)
            blocks = _re.findall(r'```notes\n(.*?)```', body, _re.S)
            test.assertTrue(blocks, fn)
            for line in (l for b in blocks for l in b.splitlines()):
                test.assertEqual((len(line) - len(line.lstrip(' '))) % 4 if line.strip() else 0, 0, f'{fn}: {line!r}')
                test.assertNotIn(';', line, fn)
            if fn == '0 start.md':
                test.assertLessEqual(len(blocks[0].splitlines()), 40, fn)


class TestReview(Base):
    """findings of the fresh review (T2-a2 2 insights.md), each as a regression test"""

    def test_parallel_sends_all_land(self):
        procs = [subprocess.Popen(['python3', os.path.join(HERE, 'ctx'), '--root', self.root, 'send', T, f'msg {i}'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(8)]
        res = [p.communicate() for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * 8, [r[1] for r in res])
        t = self.read(f'{T}/0 start.md')
        for i in range(8):
            self.assertIn(f'msg {i}\n', t)
        self.assertEqual(self.git('status', '--porcelain').strip(), '')

    def test_parallel_beats_all_land(self):
        for i in range(6):
            os.makedirs(os.path.join(self.root, 'Context', f'T{i + 20}-a1-x'), exist_ok=True)
            with open(os.path.join(self.root, 'Context', f'T{i + 20}-a1-x', '0 start.md'), 'w') as f:
                f.write('```notes\nx\n```\n')
        procs = [subprocess.Popen(['python3', os.path.join(HERE, 'ctx'), '--root', self.root, 'beat', f'Context/T{i + 20}-a1-x'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(6)]
        [p.communicate() for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * 6)
        self.assertEqual(len(json.loads(self.read('systems/state/beats.json'))), 6)

    def test_free_text_cannot_break_notes(self):
        self.ctx('pin', T, '--text', 'line one\nline two; x')
        self.ctx('send', T, 'see ```x``` here; ok')
        self.ctx('send', T, 'second')
        self.ctx('merge-up', f'{T}/c idea-one', '--text', 'a;b\nc')
        notes_check(self, self.root, T)
        t = self.read(f'{T}/0 start.md')
        self.assertIn('line one line two, x', t)
        _, out, _ = self.ctx('tree', T, '--json')
        self.assertEqual(json.loads(out)[0]['needs_you'], 3)

    def test_drop_title_refused(self):
        code, _, err = self.ctx('drop', T, '--text', 'demo task', ok=False)
        self.assertEqual(code, 2)
        self.assertIn('title', err)
        self.assertIn('T9-demo      demo task', self.read(f'{T}/0 start.md'))

    def test_relegate_whole_name_only(self):
        os.makedirs(os.path.join(self.root, T, 'c idea-one-v2'))
        with open(os.path.join(self.root, T, 'c idea-one-v2', '0 start.md'), 'w') as f:
            f.write(SUB.replace('c idea-one', 'c idea-one-v2'))
        with open(os.path.join(self.root, T, '2 insights.md'), 'a') as f:
            f.write('```notes\nmore\n    see c idea-one-v2/0 start.md\n```\n')
        os.makedirs(os.path.join(self.root, T, '4 log'))
        with open(os.path.join(self.root, T, '4 log', 'dropped.md'), 'w') as f:
            f.write('```notes\nold\n    c idea-one was here\n```\n')
        self.git('add', '-A')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'v2')
        self.ctx('relegate', f'{T}/c idea-one')
        ins = self.read(f'{T}/2 insights.md')
        self.assertIn('o idea-one/0 start.md', ins)
        self.assertIn('c idea-one-v2/0 start.md', ins)
        self.assertIn('c idea-one-v2', self.read(f'{T}/c idea-one-v2/0 start.md'))
        self.assertIn('c idea-one was here', self.read(f'{T}/4 log/dropped.md'))  # log is history
        self.assertNotIn('c idea-one-v2', self.git('show', '--name-only', '--format=', 'HEAD'))

    def test_relegate_small_file_is_a_rename(self):
        with open(os.path.join(self.root, T, 'c idea-one', '0 start.md'), 'w') as f:
            f.write('```notes\nc idea-one\n    goal                    x\n```\n')
        self.git('add', '-A')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'small')
        self.ctx('relegate', f'{T}/c idea-one')
        self.no_deletes()
        self.assertIn('R100', self.git('show', '-M', '--name-status', '--format=', 'HEAD'))

    def test_failed_relegate_rolls_back(self):
        os.makedirs(os.path.join(self.root, T, 'o idea-one'))
        before = self.read(f'{T}/0 start.md')
        self.ctx('relegate', f'{T}/c idea-one', ok=False)
        self.assertEqual(self.read(f'{T}/0 start.md'), before)  # merge-up not left behind
        self.assertEqual(self.git('status', '--porcelain', '--untracked-files=no').strip(), '')

    def test_undecodable_file_skipped(self):
        with open(os.path.join(self.root, T, 'bin.txt'), 'wb') as f:
            f.write(b'\xff\xfe c idea-one \x80')
        self.git('add', '-A')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'bin')
        self.ctx('relegate', f'{T}/c idea-one')
        self.assertTrue(os.path.isdir(os.path.join(self.root, T, 'o idea-one')))
        self.assertEqual(self.git('status', '--porcelain').strip(), '')

    def test_rollback_after_git_mv(self):
        # the link-fix step fails after the folder already moved: everything goes back
        real = ctx.Ctx.edit

        def failing(self_, p, text):
            if p.endswith('2 insights.md'):
                raise ctx.CtxError('disk full (simulated)')
            return real(self_, p, text)

        ctx.Ctx.edit = failing
        try:
            code, _, err = self.ctx('relegate', f'{T}/c idea-one', ok=False)
        finally:
            ctx.Ctx.edit = real
        self.assertEqual(code, 2)
        self.assertIn('simulated', err)
        self.assertTrue(os.path.isdir(os.path.join(self.root, T, 'c idea-one')))
        self.assertFalse(os.path.exists(os.path.join(self.root, T, 'o idea-one')))
        self.assertEqual(self.git('status', '--porcelain').strip(), '')

    def test_glob_chars_are_literal(self):
        for n in ('c v1', 'c v[12]'):
            os.makedirs(os.path.join(self.root, T, n))
            with open(os.path.join(self.root, T, n, '0 start.md'), 'w') as f:
                f.write(SUB)
        self.git('add', '-A')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'globs')
        with open(os.path.join(self.root, T, 'c v1', '0 start.md'), 'a') as f:
            f.write('raymond typing\n')
        self.ctx('pin', f'{T}/c v[12]')
        self.assertNotIn('c v1/', self.git('show', '--name-only', '--format=', 'HEAD'))
        self.assertIn('c v1', self.git('status', '--porcelain'))

    def test_dirty_file_refused_unless_include_dirty(self):
        with open(os.path.join(self.root, T, '0 start.md'), 'a') as f:
            f.write('\nraymond typing\n')
        n = self.commits()
        code, _, err = self.ctx('pin', T, '--text', 'x', ok=False)
        self.assertIn('uncommitted edits', err)
        self.assertEqual(self.commits(), n)
        self.assertTrue(self.read(f'{T}/0 start.md').endswith('raymond typing\n'))
        self.ctx('--include-dirty', 'pin', T, '--text', 'x')
        self.assertIn('included edits already uncommitted', self.git('log', '-1', '--format=%B'))

    def test_full_packet_merges_into_log(self):
        t = self.read(f'{T}/0 start.md')
        filler = ''.join(f'                            filler {i}\n' for i in range(31))
        t = t.replace('    pinned                  nothing ever deleted\n', '    pinned                  nothing ever deleted\n' + filler)
        with open(os.path.join(self.root, T, '0 start.md'), 'w') as f:
            f.write(t)
        self.git('add', '-A')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'full')
        self.assertEqual(ctx.packet_len(self.read(f'{T}/0 start.md')), 40)
        _, out, _ = self.ctx('merge-up', f'{T}/c idea-one')
        self.assertIn('packet full', out)
        self.assertIn('c idea-one', self.read(f'{T}/4 log/merged.md'))
        code, _, err = self.ctx('pin', T, '--text', 'one more', ok=False)
        self.assertIn('max 40', err)
        notes_check(self, self.root, T)

    def test_outside_root_refused(self):
        other = tempfile.TemporaryDirectory()
        with open(os.path.join(other.name, 'x.md'), 'w') as f:
            f.write('hi\n')
        code, _, err = self.ctx('pin', os.path.join(other.name, 'x.md'), ok=False)
        self.assertIn('outside the root', err)
        other.cleanup()

    def test_boot_pack_own_task_only(self):
        os.makedirs(os.path.join(self.root, T, 'T9-a1-build', 'c inner'))
        with open(os.path.join(self.root, T, 'T9-a1-build', 'c inner', '0 start.md'), 'w') as f:
            f.write('---\ncarry: pin\n---\n```notes\nc inner\n    goal                    other bots idea\n```\n')
        _, out, _ = self.ctx('boot', T)
        self.assertNotIn('other bots idea', out)
        _, out, _ = self.ctx('boot', f'{T}/T9-a1-build')
        self.assertIn('other bots idea', out)

    def test_symlink_loop_safe(self):
        os.symlink(os.path.join(self.root, 'Context'), os.path.join(self.root, T, 'loop'))
        self.ctx('tree', 'Context', '--json')

    def test_every_action_keeps_notes_valid(self):
        for args in (('pin', T, '--text', 'p1'), ('send', T, 'hi'), ('merge-up', f'{T}/c idea-one'),
                     ('relegate', f'{T}/c idea-one'), ('rotate', T), ('drop', T, '--text', 'p1'), ('set', T, 'owner=T9')):
            self.ctx(*args)
            notes_check(self, self.root, T)

    def test_relegate_name_then_space_word_untouched(self):
        for n in ('c idea', 'c idea two'):
            os.makedirs(os.path.join(self.root, T, n))
            with open(os.path.join(self.root, T, n, '0 start.md'), 'w') as f:
                f.write(SUB.replace('c idea-one', n))
        with open(os.path.join(self.root, T, '2 insights.md'), 'a') as f:
            f.write('```notes\nlinks\n    c idea/0 start.md      c idea two/0 start.md\n```\n')
        self.git('add', '-A')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'two')
        self.ctx('relegate', f'{T}/c idea')
        ins = self.read(f'{T}/2 insights.md')
        self.assertIn('o idea/0 start.md      c idea two/0 start.md', ins)

    def test_failed_commit_rolls_back_index_too(self):
        hook = os.path.join(self.root, '.git', 'hooks', 'pre-commit')
        with open(hook, 'w') as f:
            f.write('#!/bin/sh\necho no >&2\nexit 1\n')
        os.chmod(hook, 0o755)
        before = self.read(f'{T}/0 start.md')
        code, out, err = self.ctx('pin', T, '--text', 'zz9', ok=False)
        self.assertEqual(code, 2)
        self.assertNotIn('pinned in', out)  # nothing claimed before the commit landed
        self.assertEqual(self.read(f'{T}/0 start.md'), before)
        self.assertEqual(self.git('status', '--porcelain').strip(), '')
        self.ctx('relegate', f'{T}/c idea-one', ok=False)
        self.assertTrue(os.path.isdir(os.path.join(self.root, T, 'c idea-one')))
        self.assertEqual(self.git('status', '--porcelain').strip(), '')

    def test_frontmatter_closing_at_eof(self):
        self.assertEqual(ctx.fm_set('---\na: 1\n---', a='2'), '---\na: 2\n---\n')


class TestHook(Base):
    def hook(self, ev, data, **env):
        e = dict(os.environ, CTX_ROOT=self.root, **env)
        r = subprocess.run(['python3', os.path.join(HERE, 'ctx-hook'), ev], input=json.dumps(data),
                           capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, '')
        return r.stdout

    def transcript(self, used, model='claude-opus'):
        p = os.path.join(self.root, 't.jsonl')
        with open(p, 'w') as f:
            f.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'hi'}}) + '\n')
            f.write(json.dumps({'type': 'assistant', 'message': {'model': model, 'usage': {
                'input_tokens': 10, 'cache_read_input_tokens': used - 10, 'cache_creation_input_tokens': 0, 'output_tokens': 0}}}) + '\n')
        return p

    def test_no_task_is_silent(self):
        self.assertEqual(self.hook('session-start', {'cwd': self.root, 'session_id': 's'}), '')

    def test_session_start_injects_boot_pack(self):
        out = self.hook('session-start', {'cwd': self.root, 'session_id': 's1', 'source': 'startup'}, CTX_TASK=T)
        o = json.loads(out)['hookSpecificOutput']
        self.assertEqual(o['hookEventName'], 'SessionStart')
        self.assertIn('# boot pack', o['additionalContext'])
        self.assertIn('make the demo work', o['additionalContext'])
        b = json.loads(self.read('systems/state/beats.json'))[T]
        self.assertEqual((b['session'], b['harness'], b['event']), ('s1', 'claude-code', 'start:startup'))

    def test_session_start_from_cwd_and_compact(self):
        out = self.hook('session-start', {'cwd': os.path.join(self.root, T, 'c idea-one'), 'source': 'compact'})
        ctxt = json.loads(out)['hookSpecificOutput']['additionalContext']
        self.assertIn('just compacted', ctxt)
        self.assertIn('c idea-one', ctxt.split('\n')[0])

    def test_codex_cap(self):
        out = self.hook('session-start', {'cwd': self.root, 'transcript_path': '/u/.codex/sessions/x.jsonl'},
                        CTX_TASK=T, CTX_BOOT_MAX='300')
        self.assertIn('cut at 300', json.loads(out)['hookSpecificOutput']['additionalContext'])

    def test_gauge_nudges_once_per_level(self):
        d = {'session_id': 'g', 'transcript_path': self.transcript(50_000)}
        self.assertEqual(self.hook('prompt', d, CTX_TASK=T), '')
        d['transcript_path'] = self.transcript(115_000)
        out = json.loads(self.hook('prompt', d, CTX_TASK=T))['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'UserPromptSubmit')
        self.assertIn('57% full: refresh', out['additionalContext'])
        self.assertEqual(self.hook('prompt', d, CTX_TASK=T), '')  # same level → quiet
        d['transcript_path'] = self.transcript(150_000)
        self.assertIn('75% full: rotate', self.hook('prompt', d, CTX_TASK=T))
        d['session_id'] = 'new'
        self.assertIn('rotate', self.hook('prompt', d, CTX_TASK=T))  # new session starts over

    def test_gauge_1m_window_and_codex(self):
        d = {'session_id': 'g', 'model': 'claude-opus-5[1m]', 'transcript_path': self.transcript(150_000)}
        self.assertEqual(self.hook('prompt', d, CTX_TASK=T), '')
        p = os.path.join(self.root, 'c.jsonl')
        with open(p, 'w') as f:
            f.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
                'last_token_usage': {'input_tokens': 200_000, 'output_tokens': 1000}, 'model_context_window': 272_000}}}) + '\n')
        self.assertIn('73% full', self.hook('prompt', {'session_id': 'c', 'transcript_path': p}, CTX_TASK=T))

    def test_stop_and_precompact_beat(self):
        self.hook('stop', {'session_id': 's'}, CTX_TASK=T)
        self.assertEqual(json.loads(self.read('systems/state/beats.json'))[T]['event'], 'stop')
        self.hook('pre-compact', {'session_id': 's'}, CTX_TASK=T)
        self.assertEqual(json.loads(self.read('systems/state/beats.json'))[T]['event'], 'precompact')
        self.assertEqual(self.git('status', '--porcelain').strip(), '')

    def test_project_folder_is_not_a_bot(self):
        with open(os.path.join(self.root, 'Context', 'proj', '0 start.md'), 'w') as f:
            f.write('```notes\nproj\n```\n')
        self.assertEqual(self.hook('session-start', {'cwd': os.path.join(self.root, 'Context', 'proj')}), '')

    def test_gauge_reads_past_huge_lines(self):
        p = self.transcript(150_000)
        with open(p, 'a') as f:
            f.write(json.dumps({'type': 'user', 'message': {'content': 'x' * 3_000_000}}) + '\n')
        self.assertIn('75% full', self.hook('prompt', {'session_id': 'big', 'transcript_path': p}, CTX_TASK=T))

    def test_compact_resets_gauge(self):
        d = {'session_id': 'k', 'transcript_path': self.transcript(150_000)}
        self.assertIn('rotate', self.hook('prompt', d, CTX_TASK=T))
        self.assertEqual(self.hook('prompt', d, CTX_TASK=T), '')
        self.hook('session-start', {'session_id': 'k', 'source': 'compact'}, CTX_TASK=T)
        self.assertIn('rotate', self.hook('prompt', d, CTX_TASK=T))

    def test_boot_pack_fits_claude_code_limit(self):
        with open(os.path.join(self.root, T, 'note-x.md'), 'w') as f:
            f.write('---\ncarry: pin\n---\n```notes\nbig\n' + ''.join(f'    line {i} ' + 'y' * 80 + '\n' for i in range(300)) + '```\n')
        out = json.loads(self.hook('session-start', {'session_id': 's'}, CTX_TASK=T))['hookSpecificOutput']['additionalContext']
        self.assertLessEqual(len(out), 10_000)
        self.assertIn('boot pack cut at', out)

    def test_missing_ctx_never_fails(self):
        d = tempfile.TemporaryDirectory()
        import shutil
        shutil.copy(os.path.join(HERE, 'ctx-hook'), os.path.join(d.name, 'ctx-hook'))
        r = subprocess.run(['python3', os.path.join(d.name, 'ctx-hook'), 'session-start'], input='{}', capture_output=True, text=True)
        d.cleanup()
        self.assertEqual(r.returncode, 0)
        self.assertIn('cannot load systems/ctx', r.stderr)

    def test_gauge_ignores_usage_before_compaction(self):
        p = self.transcript(150_000)
        with open(p, 'a') as f:
            f.write(json.dumps({'type': 'system', 'subtype': 'compact_boundary'}) + '\n')
            f.write(json.dumps({'type': 'user', 'message': {'content': 'summary'}}) + '\n')
        self.assertEqual(self.hook('prompt', {'session_id': 'cb', 'transcript_path': p}, CTX_TASK=T), '')

    def test_bad_input_never_fails(self):
        r = subprocess.run(['python3', os.path.join(HERE, 'ctx-hook'), 'session-start'], input='not json',
                           capture_output=True, text=True, env=dict(os.environ, CTX_ROOT=self.root, CTX_TASK='nope/x'))
        self.assertEqual(r.returncode, 0)


class TestParsing(unittest.TestCase):
    def test_frontmatter_roundtrip(self):
        t = '---\na: 1\nb: x: y\n---\nbody\n'
        self.assertEqual(ctx.fm_items(t), {'a': '1', 'b': 'x: y'})
        self.assertEqual(ctx.fm_set(t, a='2'), '---\na: 2\nb: x: y\n---\nbody\n')
        self.assertEqual(ctx.fm_set('body\n', c='z'), '---\nc: z\n---\nbody\n')

    def test_frontmatter_keeps_lists_comments_and_empty(self):
        t = '---\ntags:\n  - idea\n  - ctx\n# a comment\nnested:\n  k: v\n---\nbody\n'
        n = ctx.fm_set(t, carry='pin')
        self.assertEqual(n, '---\ntags:\n  - idea\n  - ctx\n# a comment\nnested:\n  k: v\ncarry: pin\n---\nbody\n')
        self.assertEqual(ctx.fm_set('---\n---\nbody\n', carry='pin'), '---\ncarry: pin\n---\nbody\n')

    def test_clean(self):
        self.assertEqual(ctx.clean('a\nb; c ```x```'), "a b, c '''x'''")

    def test_value_col_on_grid(self):
        self.assertEqual(ctx.value_col('    merged up      x', 'merged up'), 20)

    def test_empty_row_gets_value_on_cue_line(self):
        t = '```notes\nx\n    pinned\n    came from               y\n```\n'
        self.assertIn('    pinned                  hi\n', ctx.add_to_row(t, 'pinned', 'hi'))

    def test_open_q_count(self):
        t = '    q1 a?\n        a\n    q2 b?\n        a yes\n'
        self.assertEqual(ctx.count_open_q(t), 1)


if __name__ == '__main__':
    unittest.main()
