"""tests for systems/front-door      run: python3 -m unittest test_front_door"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'systems')


def sh(*args, cwd=None, check=True):
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=dict(os.environ, LEDGER_ORCA='0'))
    if check and r.returncode:
        raise AssertionError(f'{args}: {r.returncode}\n{r.stdout}\n{r.stderr}')
    return r


class FrontDoorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, 'CS Code')
        os.makedirs(os.path.join(self.root, 'systems'))
        for f in ('ctx', 'ledger', 'front-door'):
            shutil.copy(os.path.join(HERE, f), os.path.join(self.root, 'systems', f))
        os.makedirs(os.path.join(self.root, 'Project', 'demo'))
        sh('git', 'init', '-q', '-b', 'main', cwd=self.root)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'add', '-A', cwd=self.root)
        sh('git', '-c', 'user.name=t', '-c', 'user.email=', 'commit', '-qm', 'init', cwd=self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def L(self, *args):
        return sh(sys.executable, os.path.join(self.root, 'systems', 'ledger'), '--root', self.root, *args)

    def door(self, *args):
        r = sh(sys.executable, os.path.join(self.root, 'systems', 'front-door'), '--root', self.root, *args)
        return r.stdout

    def task(self, name, boundary='b'):
        self.L('new', 'Project/demo', name, '--goal', 'g', '--done-when', 'd', '--owner', 'o', '--boundary', boundary, '--checks', 'true', '--repo', self.root,
               '--non-goals', 'n', '--proof', 'p', '--stop', 's')  # ledger ready needs these 3 rows too
        t = [d for d in os.listdir(os.path.join(self.root, 'Project/demo')) if d.endswith('-' + name)][0]
        return 'Project/demo/' + t

    def test_sections(self):
        a = self.task('alpha', 'systems')
        b = self.task('beta', 'systems/ledger')
        c = self.task('gamma')
        d = self.task('delta')
        for t in (a, b, c, d):
            self.L('move', t, 'ready')
            self.L('move', t, 'running', '--worktree', self.root)
        self.L('move', c, 'blocked', '--cause', 'needs api key', '--decision-owner', 'raymond')
        for state, extra in (('submitted', ['--report', 'r']), ('verified', ['--reviewer', 'fresh', '--findings', 'none']),
                             ('integrated', ['--merge', 'main']), ('done', ['--outcome', 'shipped', '--resources', 'retain', '--prevents', 'none: clean run'])):
            self.L('move', d, state, *extra)
        # a needs-you row in a running packet, and one in a plain (non-ledger) task folder
        p = os.path.join(self.root, a, '0 start.md')
        txt = open(p).read().replace('    pinned', '    needs-you               approve the schema change      details in 2 insights\n    pinned')
        open(p, 'w').write(txt)
        plain = os.path.join(self.root, 'Context', 'T1-notes')
        os.makedirs(plain)
        open(os.path.join(plain, '0 start.md'), 'w').write('```notes\nT1-notes\n    needs-you               answer q3 naming\n```\n')
        broken = os.path.join(self.root, 'Project', 'demo', 'T9-broken')
        os.makedirs(broken)
        open(os.path.join(broken, '0 start.md'), 'w').write('---\nstate: running\n---\nno notes block\n')
        out = json.loads(self.door('--json'))
        why = {(n['task'], n['why']) for n in out['needs_you']}
        self.assertIn((a, 'approve the schema change'), why)
        self.assertIn(('Context/T1-notes', 'answer q3 naming'), why)
        self.assertTrue(any(n['task'] == c and 'blocked' in n['why'] for n in out['needs_you']))
        flags = {(f['task'], f['flag']) for f in out['flags']}
        self.assertIn((a, 'overlap ' + b), flags)
        self.assertIn((b, 'overlap ' + a), flags)
        self.assertEqual({r['task'] for r in out['in_flight']}, {a, b, 'Project/demo/T9-broken'})
        self.assertEqual([r['task'] for r in out['done']], [d])
        self.assertTrue(out['done'][0]['path'].endswith(d + '/0 start.md'))
        text = self.door()
        self.assertIn('needs you', text)
        self.assertIn('approve the schema change', text)
        self.assertNotIn(';', text)

    def test_unreadable_packets_and_review_fixes(self):
        a = self.task('alpha')
        c = self.task('gamma')
        for t in (a, c):
            self.L('move', t, 'ready')
            self.L('move', t, 'running', '--worktree', self.root)
        self.L('move', c, 'blocked', '--cause', 'duplicate of codex build', '--decision-owner', 'raymond')
        bad = os.path.join(self.root, 'Project', 'demo', 'T8-bytes')
        os.makedirs(bad)
        open(os.path.join(bad, '0 start.md'), 'wb').write(b'---\nstate: running\n---\n\xe9\xff\n')
        link = os.path.join(self.root, 'Project', 'demo', 'T7-link')
        os.makedirs(link)
        os.symlink(os.path.join(self.tmp, 'missing.md'), os.path.join(link, '0 start.md'))
        old = os.path.join(self.root, 'Context', 'T2-old')
        os.makedirs(old)
        open(os.path.join(old, '0 start.md'), 'w').write('---\nstate: done\n---\n```notes\n    needs-you               stale ask\n```\n')
        out = json.loads(self.door('--json'))  # exit 0 despite the unreadable packets
        self.assertIn(a, {r['task'] for r in out['in_flight']})
        whys = [n['why'] for n in out['needs_you']]
        self.assertIn('blocked: duplicate of codex build', whys)
        self.assertNotIn('stale ask', whys)
        self.assertEqual(out['tasks_needing_you'], 1)
        self.assertEqual(out['errors'], [])
        r = sh(sys.executable, os.path.join(self.root, 'systems', 'front-door'), '--root', self.root, '--done', '-1', check=False)
        self.assertNotEqual(r.returncode, 0)

    def test_empty_workspace(self):
        out = json.loads(self.door('--json'))
        self.assertEqual((out['needs_you'], out['flags'], out['in_flight'], out['done']), ([], [], [], []))
        self.assertIn('nothing needs you', self.door())


if __name__ == '__main__':
    unittest.main(verbosity=2)
