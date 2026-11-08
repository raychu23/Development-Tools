"""tests for systems/ledger      run: python3 systems/test_ledger.py"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'systems')
BRIEF = ('--non-goals', 'no ui', '--proof', 'unit test', '--stop', '2 rounds')  # the 3 rows ready needs besides done-when · boundary · checks


def sh(*args, cwd=None, env=None, check=True):
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=env)
    if check and r.returncode:
        raise AssertionError(f'{args}: {r.returncode}\n{r.stdout}\n{r.stderr}')
    return r


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, 'CS Code')
        os.makedirs(os.path.join(self.root, 'systems'))
        for f in ('ctx', 'ledger'):
            shutil.copy(os.path.join(HERE, f), os.path.join(self.root, 'systems', f))
        os.makedirs(os.path.join(self.root, 'Project', 'demo'))
        open(os.path.join(self.root, 'Project', 'demo', 'README.md'), 'w').write('demo\n')
        sh('git', 'init', '-q', '-b', 'main', cwd=self.root)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'add', '-A', cwd=self.root)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qm', 'init', cwd=self.root)
        # a code repo for --git-worktree
        self.repo = os.path.join(self.tmp, 'app')
        os.makedirs(self.repo)
        open(os.path.join(self.repo, 'a.txt'), 'w').write('x\n')
        sh('git', 'init', '-q', '-b', 'main', cwd=self.repo)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'add', '-A', cwd=self.repo)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qm', 'init', cwd=self.repo)
        # fake orca: logs its args, answers json with a path
        self.bin = os.path.join(self.tmp, 'bin')
        os.makedirs(self.bin)
        self.orcalog = os.path.join(self.tmp, 'orca.log')
        wt = os.path.join(self.tmp, 'orca-wt')
        os.makedirs(wt)
        with open(os.path.join(self.bin, 'orca'), 'w') as f:
            f.write(f'#!/bin/sh\necho "$@" >> "{self.orcalog}"\necho \'{{"worktree": {{"id": "w1", "path": "{wt}"}}}}\'\n')
        os.chmod(os.path.join(self.bin, 'orca'), 0o755)
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ['PATH'])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def L(self, *args, ok=True, orca=False):
        env = self.env if orca else dict(os.environ, LEDGER_ORCA='0')
        r = sh(sys.executable, os.path.join(self.root, 'systems', 'ledger'), '--root', self.root, *args, env=env, check=False)
        if ok and r.returncode:
            raise AssertionError(f'ledger {args} failed\n{r.stdout}\n{r.stderr}')
        if not ok:
            self.assertNotEqual(r.returncode, 0, f'expected failure: {args}\n{r.stdout}')
        return r

    def fm(self, task):
        t = open(os.path.join(self.root, task, '0 start.md')).read()
        return dict(l.split(':', 1) for l in t.split('---\n')[1].strip().split('\n') if ':' in l)

    def log(self, task):
        return open(os.path.join(self.root, task, '4 log', 'ledger.md')).read()

    def commits(self):
        return int(sh('git', 'rev-list', '--count', 'HEAD', cwd=self.root).stdout)

    def test_full_flow_git_worktree(self):
        self.L('new', 'Project/demo', 'Add CSV export', '--goal', 'export rows as csv',
               '--done-when', 'csv with header, empty table gives header only', '--repo', self.repo)
        t = 'Project/demo/T1-add-csv-export'
        self.assertEqual(self.fm(t)['state'].strip(), 'proposed')
        self.L('move', t, 'ready', ok=False)  # no owner, boundary, checks yet
        p = os.path.join(self.root, t, '0 start.md')
        txt = open(p).read().replace('    boundary', '    boundary                src/export/').replace('    checks', '    checks                  test -f a.txt')
        open(p, 'w').write(txt)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qam', 'fill', cwd=self.root)
        self.L('move', t, 'running', ok=False)  # proposed → running skips ready
        self.L('move', t, 'ready', '--owner', 'codex-a', ok=False)  # non-goals · proof · stop still empty
        self.L('move', t, 'ready', '--owner', 'codex-a', *BRIEF)
        self.L('move', t, 'running', ok=False)  # no workspace given
        self.L('move', t, 'running', '--git-worktree')
        fm = self.fm(t)
        self.assertTrue(os.path.isdir(fm['worktree'].strip()))
        self.assertEqual(fm['branch'].strip(), 'ledger/t1-add-csv-export')
        self.assertTrue(fm['base'].strip())
        self.L('move', t, 'submitted', '--report', 'export.py + test', '--checks-result', 'pytest → 4 passed')
        self.L('move', t, 'verified', '--reviewer', 'codex-a', '--findings', 'none', '--checks-result', 'ok', ok=False)  # owner ≠ reviewer
        self.L('move', t, 'running', '--findings', 'empty table writes nothing')  # changes requested
        self.L('move', t, 'submitted', '--report', 'header for empty table', '--checks-result', 'pytest → 5 passed')
        self.L('move', t, 'verified', '--reviewer', 'hermes-reviewer', '--findings', 'none', '--checks-result', 'pytest → 5 passed')
        self.L('move', t, 'integrated', '--merge', 'main@abc123', '--checks-result', 'combined pytest → 5 passed')
        self.L('move', t, 'done', '--outcome', 'app/src/export.py on main', '--resources', 'archive', '--prevents', 'a.txt:1 header check')
        self.L('move', t, 'ready', ok=False)  # done is final
        lg = self.log(t)
        for s in ('new → proposed', 'proposed → ready', 'ready → running', 'running → submitted', 'submitted → running',
                  'submitted → verified', 'verified → integrated', 'integrated → done'):
            self.assertIn(s, lg)
        self.assertEqual(self.fm(t)['state'].strip(), 'done')
        self.assertIn('done', open(p).read().split('```notes')[1])
        self.assertEqual(self.commits(), 11)  # init + new + fill + 8 moves
        self.assertNotIn(';', open(p).read().split('```notes')[1])

    def test_orca_claim_and_cards(self):
        self.L('new', 'Project/demo', 'fix login', '--goal', 'g', '--done-when', 'd', '--owner', 'o',
               '--boundary', 'src/', '--checks', 'npm test', *BRIEF)
        t = 'Project/demo/T1-fix-login'
        self.L('move', t, 'ready', orca=True)
        self.L('move', t, 'running', '--orca', orca=True, ok=False)  # needs a repo selector
        r = self.L('move', t, 'running', '--orca', '--orca-repo', 'id:r9', orca=True)
        self.assertIn('orca:', r.stdout)
        log = open(self.orcalog).read()
        self.assertIn('worktree create --repo id:r9 --name T1-fix-login --json', log)
        self.assertIn('--workspace-status in-progress', log)
        self.assertTrue(self.fm(t)['worktree'].strip().endswith('orca-wt'))

    def test_blocked_and_board(self):
        self.L('new', 'Project/demo', 'a', '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', 'b', '--checks', 'c', *BRIEF)
        self.L('new', 'Project/demo', 'b', '--goal', 'g', '--done-when', 'd')
        t = 'Project/demo/T1-a'
        self.L('move', t, 'ready')
        self.L('move', t, 'running', '--worktree', self.repo)
        self.L('move', t, 'blocked', '--cause', 'api key missing', ok=False)
        self.L('move', t, 'blocked', '--cause', 'api key missing', '--decision-owner', 'raymond')
        r = self.L('board')
        self.assertIn('T1-a', r.stdout)
        self.assertIn('blocked', r.stdout)
        self.assertIn('T2-b', r.stdout)
        self.assertIn('no ledger tasks in state ready', self.L('ready').stdout)
        self.L('move', t, 'ready', '--note', 'key added')
        self.assertIn('T1-a', self.L('ready').stdout)

    def test_no_orca_prints_command(self):
        self.L('new', 'Project/demo', 'c', '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', 'b', '--checks', 'c', *BRIEF)
        env = dict(os.environ, PATH='/usr/bin:/bin')
        t = 'Project/demo/T1-c'
        sh(sys.executable, os.path.join(self.root, 'systems', 'ledger'), '--root', self.root, 'move', t, 'ready', env=env)
        r = sh(sys.executable, os.path.join(self.root, 'systems', 'ledger'), '--root', self.root, 'move', t, 'running',
               '--worktree', self.repo, env=env)
        self.assertIn('run on the mac: orca worktree set', r.stdout)

    def test_check_task_passes(self):
        cs = os.path.join(HERE, 'check-task.sh')
        if not os.path.exists(cs):
            self.skipTest('check-task.sh not next to ledger')
        shutil.copy(cs, os.path.join(self.root, 'systems', 'check-task.sh'))
        self.L('new', 'Project/demo', 'd', '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', 'b', '--checks', 'c', *BRIEF)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'add', '-A', cwd=self.root)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qm', 'cs', cwd=self.root, check=False)
        r = sh('sh', os.path.join(self.root, 'systems', 'check-task.sh'), os.path.join(self.root, 'Project/demo/T1-d'), check=False)
        self.assertIn('RESULT PASS', r.stdout, r.stdout)


    def test_rollback_and_retry(self):
        self.L('new', 'Project/demo', 'r', '--goal', 'g', '--done-when', 'd', '--repo', self.repo)
        t = 'Project/demo/T1-r'
        self.L('move', t, 'ready', '--owner', 'o', '--boundary', 'src/', '--checks', 'make test', *BRIEF)  # fills rows here
        p = os.path.join(self.root, t, '0 start.md')
        with open(p, 'a') as f:
            f.write('hand edit\n')  # uncommitted → the move must fail and undo the worktree + branch
        self.L('move', t, 'running', '--git-worktree', ok=False)
        self.assertEqual(sh('git', 'branch', '--list', 'ledger/t1-r', cwd=self.repo).stdout.strip(), '')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'app-worktrees', 'T1-r')))
        self.L('--include-dirty', 'move', t, 'running', '--git-worktree')
        self.L('move', t, 'failed', '--cause', 'flaky', '--decision-owner', 'raymond')
        self.L('move', t, 'ready', '--note', 'retry')
        r = self.L('move', t, 'running', '--git-worktree')  # retry reuses the worktree
        self.assertIn('reusing worktree', r.stdout)

    def test_new_does_not_double_task_prefix(self):
        self.L('new', 'Project/demo', 'T7-csv export', '--goal', 'g', '--done-when', 'd')
        self.assertTrue(os.path.isdir(os.path.join(self.root, 'Project/demo/T1-csv-export')))
        self.assertFalse(os.path.exists(os.path.join(self.root, 'Project/demo/T1-t7-csv-export')))

    def test_checks_command_gates_submit_verify_integrate(self):
        self.L('new', 'Project/demo', 'gate', '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', 'b',
               '--checks', 'sh -c "echo failing check >&2; exit 3"', *BRIEF, '--repo', self.repo)
        t = 'Project/demo/T1-gate'
        self.L('move', t, 'ready')
        self.L('move', t, 'running', '--git-worktree')
        r = self.L('move', t, 'submitted', '--report', 'r', ok=False)
        self.assertIn('exit 3', r.stderr)
        self.assertIn('failing check', r.stderr)
        self.assertEqual(self.fm(t)['state'].strip(), 'running')
        p = os.path.join(self.root, t, '0 start.md')
        txt = open(p).read().replace('sh -c "echo failing check >&2; exit 3"', 'test -f a.txt')
        open(p, 'w').write(txt)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qam', 'fix checks', cwd=self.root)
        self.L('move', t, 'submitted', '--report', 'r')  # the ledger runs the check itself, no typed result needed
        self.assertRegex(self.log(t), r'checks ran: test -f a.txt in .*T1-gate → exit 0')
        os.remove(os.path.join(self.fm(t)['worktree'].strip(), 'a.txt'))
        self.L('move', t, 'verified', '--reviewer', 'fresh', '--findings', 'none', ok=False)  # worktree check now fails
        self.L('move', t, 'running', '--findings', 'restore a.txt')
        sh('git', 'checkout', '--', 'a.txt', cwd=self.fm(t)['worktree'].strip())
        self.L('move', t, 'submitted', '--report', 'r2')
        self.L('move', t, 'verified', '--reviewer', 'fresh', '--findings', 'none')
        self.L('move', t, 'integrated', '--merge', 'main@x')
        self.assertRegex(self.log(t), r'combined checks ran: test -f a.txt in .*app → exit 0')

    def test_empty_checks_row_cannot_submit(self):
        self.L('new', 'Project/demo', 'none', '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', 'b', '--checks', 'x', *BRIEF)
        t = 'Project/demo/T1-none'
        self.L('move', t, 'ready')
        self.L('move', t, 'running', '--worktree', self.repo)
        p = os.path.join(self.root, t, '0 start.md')
        txt = open(p).read().replace('    checks                  x', '    checks                  tbd')
        open(p, 'w').write(txt)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qam', 'blank', cwd=self.root)
        r = self.L('move', t, 'submitted', '--report', 'r', '--checks-result', 'trust me', ok=False)
        self.assertIn('checks', r.stderr)

    def test_board_flags_stalled_and_overlapping_claims(self):
        for name, boundary in (('a', 'systems, Project/demo/T1-a'), ('b', 'systems/ledger'), ('c', 'docs/')):
            self.L('new', 'Project/demo', name, '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', boundary, '--checks', 'true', *BRIEF)
        for t in ('Project/demo/T1-a', 'Project/demo/T2-b', 'Project/demo/T3-c'):
            self.L('move', t, 'ready')
            self.L('move', t, 'running', '--worktree', self.repo)
        p = os.path.join(self.root, 'Project/demo/T3-c', '0 start.md')
        txt = re.sub(r'(?m)^updated: .*$', 'updated: 2020-01-01 00:00', open(p).read())
        open(p, 'w').write(txt)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qam', 'old', cwd=self.root)
        rows = {r['task']: r['flags'] for r in json.loads(self.L('board', '--json').stdout)}
        self.assertIn('overlap Project/demo/T2-b', rows['Project/demo/T1-a'])
        self.assertIn('overlap Project/demo/T1-a', rows['Project/demo/T2-b'])
        self.assertEqual(rows['Project/demo/T3-c'], ['stalled'])
        self.assertIn('overlap', self.L('board').stdout)
        self.L('move', 'Project/demo/T2-b', 'blocked', '--cause', 'x', '--decision-owner', 'raymond')
        rows = {r['task']: r['flags'] for r in json.loads(self.L('board', '--json').stdout)}
        self.assertEqual(rows['Project/demo/T1-a'], [])  # a blocked task holds no live claim

    def gate_task(self, name, checks, boundary='b'):
        self.L('new', 'Project/demo', name, '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', boundary,
               '--checks', checks, *BRIEF, '--repo', self.repo)
        t = f'Project/demo/T1-{name}'
        self.L('move', t, 'ready')
        self.L('move', t, 'running', '--git-worktree')
        return t

    def test_review_fixes_checks_run_only_where_and_when_they_should(self):
        marker = os.path.join(self.tmp, 'ran')
        t = self.gate_task('w', f'touch {marker}      notes after the gap are not shell words')
        r = self.L('move', t, 'verified', '--reviewer', 'x', '--findings', 'f', ok=False)  # running → verified is illegal
        self.assertFalse(os.path.exists(marker))
        self.L('move', t, 'submitted', ok=False)  # missing --report refuses before running checks
        self.assertFalse(os.path.exists(marker))
        wt = self.fm(t)['worktree'].strip()
        sh('git', 'worktree', 'remove', '--force', wt, cwd=self.repo)
        r = self.L('move', t, 'submitted', '--report', 'r', ok=False)
        self.assertIn('worktree missing', r.stderr)
        self.assertFalse(os.path.exists(marker))
        sh('git', 'worktree', 'add', wt, 'ledger/t1-w', cwd=self.repo)
        self.L('move', t, 'submitted', '--report', 'REPORT-KEPT')
        self.assertTrue(os.path.exists(marker))
        self.assertNotIn('notes after the gap', self.log(t).split('checks ran:')[1].split(' in ')[0])

    def test_long_command_keeps_exit_code_and_report_in_log(self):
        t = self.gate_task('long', 'test -f a.txt && echo ' + 'x' * 200)
        self.L('move', t, 'submitted', '--report', 'REPORT-KEPT')
        lines = [l for l in self.log(t).splitlines() if 'running → submitted' in l]
        self.assertIn('REPORT-KEPT', lines[0])
        self.assertIn('checks exit 0', lines[0])
        self.assertTrue(any('checks ran:' in l and l.endswith('→ exit 0 (' + 'x' * 100 + ')') or ('checks ran:' in l and '→ exit 0' in l)
                            for l in self.log(t).splitlines()))

    def test_placeholder_checks_refused(self):
        t = self.gate_task('ph', 'cd <worktree>/systems && true')
        r = self.L('move', t, 'submitted', '--report', 'r', ok=False)
        self.assertIn('placeholder', r.stderr)

    def test_board_survives_malformed_packet_and_reads_boundary_like_ctx(self):
        bad = os.path.join(self.root, 'Project/demo/T9-bad')
        os.makedirs(bad)
        open(os.path.join(bad, '0 start.md'), 'w').write('---\nstate: proposed\n---\nno notes block\n')
        for name, boundary in (('a', 'systems/ledger      tests only'), ('b', '`./systems/ledger/**`'), ('c', 'systems/ledgerx')):
            self.L('new', 'Project/demo', name, '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', boundary, '--checks', 'true', *BRIEF)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'add', '-A', cwd=self.root)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qm', 'bad', cwd=self.root)
        for t in ('Project/demo/T10-a', 'Project/demo/T11-b', 'Project/demo/T12-c'):
            self.L('move', t, 'ready')
            self.L('move', t, 'running', '--worktree', self.repo)
        rows = {r['task']: r['flags'] for r in json.loads(self.L('board', '--json').stdout)}
        self.assertIn('Project/demo/T9-bad', rows)
        self.assertEqual(rows['Project/demo/T10-a'], ['overlap Project/demo/T11-b'])
        self.assertEqual(rows['Project/demo/T12-c'], [])

    def test_shell_redirect_is_not_a_placeholder_and_race_refuses_cleanly(self):
        t = self.gate_task('redir', 'sort <a.txt >sorted.txt')
        self.L('move', t, 'submitted', '--report', 'r')
        self.assertTrue(any(l.startswith('    ') and 'checks ran:' in l for l in self.log(t).splitlines()))
        sys.path.insert(0, os.path.join(self.root, 'systems'))
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader('ledger_mod', os.path.join(self.root, 'systems', 'ledger'))
        spec = importlib.util.spec_from_loader('ledger_mod', loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        mod.run_checks = lambda root, a: None  # another ledger call moved the task while checks ran
        rc = mod.main(['--root', self.root, 'move', t, 'verified', '--reviewer', 'fresh', '--findings', 'none'])
        self.assertEqual(rc, 2)
        self.assertEqual(self.fm(t)['state'].strip(), 'submitted')

    def test_prefix_strip_keeps_real_names(self):
        self.L('new', 'Project/demo', 'T5 small finetune', '--goal', 'g', '--done-when', 'd')
        self.L('new', 'Project/demo', 't2-micro instance setup', '--goal', 'g', '--done-when', 'd')
        names = sorted(os.listdir(os.path.join(self.root, 'Project/demo')))
        self.assertIn('T1-t5-small-finetune', names)
        self.assertIn('T2-t2-micro-instance-setup', names)

    def test_bad_env_numbers_refuse_cleanly(self):
        t = self.gate_task('env', 'true')
        r = sh(sys.executable, os.path.join(self.root, 'systems', 'ledger'), '--root', self.root, 'move', t, 'submitted',
               '--report', 'r', env=dict(os.environ, LEDGER_ORCA='0', LEDGER_CHECKS_TIMEOUT='10m'), check=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn('LEDGER_CHECKS_TIMEOUT', r.stderr)
        self.assertNotIn('Traceback', r.stderr)

    def test_relative_repo_and_quoting(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            self.L('new', 'Project/demo', 'q', '--goal', 'g', '--done-when', 'd', '--repo', 'app', '--owner', 'o',
                   '--boundary', 'b', '--checks', 'true', *BRIEF)
        finally:
            os.chdir(cwd)
        t = 'Project/demo/T1-q'
        self.assertEqual(os.path.realpath(self.fm(t)['repo'].strip()), os.path.realpath(self.repo))
        self.L('move', t, 'ready')
        env = dict(os.environ, PATH='/usr/bin:/bin')
        sh(sys.executable, os.path.join(self.root, 'systems', 'ledger'), '--root', self.root, 'move', t, 'running', '--git-worktree', env=env)
        r = sh(sys.executable, os.path.join(self.root, 'systems', 'ledger'), '--root', self.root, 'move', t, 'submitted',
               '--report', 'ok $(touch /tmp/PWNED_LEDGER)', '--checks-result', '`id`', env=env)
        line = [l for l in r.stdout.splitlines() if 'run on the mac' in l][0]
        cmd = line.split('run on the mac: ', 1)[1]
        sh('sh', '-c', 'echo ' + cmd.split(' ', 1)[1])  # pasting the printed args into a shell runs nothing
        self.assertFalse(os.path.exists('/tmp/PWNED_LEDGER'))

    def to_integrated(self, name, detour=()):
        """a task at integrated      detour = extra moves taken while running (a logged mistake)"""
        t = self.gate_task(name, 'true')
        for mv in detour:
            self.L('move', t, *mv)
        self.L('move', t, 'submitted', '--report', 'r')
        self.L('move', t, 'verified', '--reviewer', 'fresh', '--findings', 'none')
        self.L('move', t, 'integrated', '--merge', 'main@x')
        return t

    def test_ready_needs_non_goals_proof_and_stop(self):
        self.L('new', 'Project/demo', 'brief', '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', 'b', '--checks', 'true')
        t = 'Project/demo/T1-brief'
        r = self.L('move', t, 'ready', ok=False)
        self.assertIn('non-goals · proof · stop', r.stderr)
        flags = dict(zip(BRIEF[::2], BRIEF[1::2]))
        for missing in flags:  # each of the 3 rows alone blocks ready
            given = [x for k, v in flags.items() if k != missing for x in (k, v)]
            r = self.L('move', t, 'ready', *given, ok=False)
            self.assertIn('not ready', r.stderr)
            self.assertIn(missing[2:], r.stderr)
            self.assertEqual(self.fm(t)['state'].strip(), 'proposed')
        self.L('move', t, 'ready', *BRIEF)
        rows = open(os.path.join(self.root, t, '0 start.md')).read()
        for line in ('    non-goals               no ui', '    proof                   unit test', '    stop                    2 rounds'):
            self.assertIn(line, rows)

    def test_new_writes_brief_rows_and_blocked_task_returns_to_ready_without_them(self):
        self.L('new', 'Project/demo', 'n', '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', 'b', '--checks', 'true', *BRIEF)
        t = 'Project/demo/T1-n'
        self.L('move', t, 'ready')  # rows came from new
        self.L('move', t, 'running', '--worktree', self.repo)
        self.L('move', t, 'blocked', '--cause', 'c', '--decision-owner', 'raymond')
        p = os.path.join(self.root, t, '0 start.md')  # an old task: packet from before the 3 rows existed
        txt = re.sub(r'(?m)^    (non-goals|proof|stop) .*\n', '', open(p).read())
        open(p, 'w').write(txt)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qam', 'old packet', cwd=self.root)
        self.L('move', t, 'ready', '--note', 'unblocked')  # blocked → ready never strands it
        self.assertEqual(self.fm(t)['state'].strip(), 'ready')

    def test_done_needs_prevents_and_none_only_on_a_clean_log(self):
        t = self.to_integrated('clean')
        r = self.L('move', t, 'done', '--outcome', 'o', '--resources', 'retain', ok=False)
        self.assertIn('--prevents', r.stderr)
        self.L('move', t, 'done', '--outcome', 'o', '--resources', 'retain', '--prevents', 'none:', ok=False)  # needs a reason
        self.L('move', t, 'done', '--outcome', 'o', '--resources', 'retain', '--prevents', 'none: first try, nothing went wrong')
        lg = self.log(t)
        self.assertRegex(lg, r'prevents: none: first try, nothing went wrong \[source: Project/demo/T1-clean; added: \d{4}-\d\d-\d\d\]')
        self.assertIn('    prevents                none: first try', open(os.path.join(self.root, t, '0 start.md')).read())

    def test_none_refused_after_changes_requested_and_artifact_must_exist(self):
        t = self.to_integrated('cr', detour=[('submitted', '--report', 'r0'), ('running', '--findings', 'missed empty case')])
        done = ('move', t, 'done', '--outcome', 'o', '--resources', 'retain', '--prevents')
        r = self.L(*done, 'none: nothing', ok=False)
        self.assertIn('submitted → running', r.stderr)
        r = self.L(*done, 'skills/nope.md:3 pitfall', ok=False)
        self.assertIn('no existing artifact', r.stderr)
        r = self.L(*done, 'a.txt:9', ok=False)  # a.txt has 1 line
        self.assertIn('line 9', r.stderr)
        r = self.L(*done, 'systems/ledger:2 empty-case reviewer check')  # ledger root path, label after it
        self.assertIn('stamp the artifact with: [source: Project/demo/T1-cr; added: ', r.stdout)
        self.assertIn('prevents: systems/ledger:2 empty-case reviewer check [source: Project/demo/T1-cr; added: ', self.log(t))

    def test_none_refused_after_blocked(self):
        t = self.to_integrated('bl', detour=[('blocked', '--cause', 'c', '--decision-owner', 'raymond'), ('ready', '--note', 'n'),
                                             ('running', '--git-worktree')])
        r = self.L('move', t, 'done', '--outcome', 'o', '--resources', 'retain', '--prevents', 'none: fine', ok=False)
        self.assertIn('running → blocked', r.stderr)
        self.L('move', t, 'done', '--outcome', 'o', '--resources', 'retain', '--prevents', 'a.txt')  # repo path

    def test_old_done_packet_without_prevents_still_lists(self):
        old = os.path.join(self.root, 'Project/demo/T5-old')
        os.makedirs(os.path.join(old, '4 log'))
        open(os.path.join(old, '0 start.md'), 'w').write(
            '---\nstate: done\nowner: o\nupdated: 2026-10-01 10:00\nnext: —\n---\n```notes\nT5-old      ledger task\n'
            '    goal                    g\n    done-when               d\n    boundary                b\n    checks                  true\n```\n')
        open(os.path.join(old, '4 log', 'ledger.md'), 'w').write('```notes\n    2026-10-01 09:00      integrated → done      outcome: x\n```\n')
        rows = {r['task']: r for r in json.loads(self.L('board', '--json').stdout)}
        self.assertEqual(rows['Project/demo/T5-old']['state'], 'done')
        self.assertIn('T5-old', self.L('board').stdout)
        self.assertIn('integrated → done', self.L('show', 'Project/demo/T5-old').stdout)
        self.L('move', 'Project/demo/T5-old', 'ready', ok=False)  # done stays final


if __name__ == '__main__':
    unittest.main(verbosity=2)
