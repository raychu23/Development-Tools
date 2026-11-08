"""provenance (own / ext <repo>) · skills-map · merge-skill · dora · commit-msg hook"""
import importlib.machinery, importlib.util, os, subprocess, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / 'systems'


def load(name):
    l = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(HERE / name))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(l.name, l)); l.exec_module(m)
    return m


pv, sm, ms, dora = load('provenance'), load('skills-map'), load('merge-skill'), load('dora')
G = ['-c', 'user.email=t@t', '-c', 'user.name=t']


def sh(cwd, *a):
    return subprocess.run(['git', '-C', str(cwd), *G, *a], capture_output=True, text=True)


class Map(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        r = Path(t.name) / 'cs'; (r / 'skills/systems').mkdir(parents=True); sh(r.parent, 'init', '-q', str(r))
        up = Path(t.name) / 'up'; (up / 'a').mkdir(parents=True)
        (up / 'a/SKILL.md').write_text('---\nname: ext-a\ndescription: Does A. Use when A.\n---\nb\n')
        sh(up.parent, 'init', '-q', str(up)); sh(up, 'add', '.'); sh(up, 'commit', '-qm', 'up')
        subprocess.run(['git', 'clone', '-q', str(up), str(r / 'skills/all/tools/3-up')], check=True)
        (r / 'skills/.gitignore').write_text('all/tools/3-up/\n')
        (r / 'skills/systems/load.txt').write_text('# x\nall/tools/3-up/a      # → project/sdlc/1-plan · fills a gap\n')
        own = r / 'skills/all/system/mine'; own.mkdir(parents=True)
        (own / 'SKILL.md').write_text('---\nname: mine\ndescription: "Mine. Use when."\n---\nbody\n')
        cp = r / 'skills/project/sdlc/5-pr/cr'; cp.mkdir(parents=True)
        (cp / 'SKILL.md').write_text('---\nname: cr\ndescription: d\nmetadata:\n  source: ext coderabbit github.com/coderabbitai/skills\n---\nb\n')
        sh(r, 'add', '.'); sh(r, 'commit', '-qm', 'i')
        self.r = r
        for m in (sm, pv):
            m.ROOT = r
        sm.SK, sm.START = r / 'skills', r / 'skills/0 start.md'
        self._m = pv._map; pv._map = lambda: sm; self.addCleanup(setattr, pv, '_map', self._m)

    def test_map_and_check(self):
        rows, cl = sm.skills()
        by = {x['name']: x for x in rows}
        self.assertEqual(by['ext-a']['frm'], 'ext up'); self.assertEqual(by['ext-a']['cat'], 'project/sdlc/1-plan')
        self.assertEqual(by['ext-a']['take'], 'fills a gap'); self.assertEqual(by['mine']['frm'], 'own')
        (self.r / 'skills/0 start.md').write_text('hand notes\n')
        sm.main(); sm.main()
        t = (self.r / 'skills/0 start.md').read_text()
        self.assertEqual(t.count('# skills map'), 1); self.assertTrue(t.rstrip().endswith('hand notes'))
        self.assertIn('| [ext-a](all/tools/3-up/a/SKILL.md) | ext up |', t)
        self.assertIn('| coderabbit | [github.com/coderabbitai/skills]', t); self.assertIn('| [cr](', t)
        self.assertIn('| ext coderabbit |', t)
        self.assertEqual(len(pv.check()), 1)  # mine has no source
        f = self.r / 'skills/all/system/mine/SKILL.md'
        pv.stamp([f]); pv.stamp([f])
        self.assertEqual(f.read_text().count('source: own'), 1); self.assertEqual(pv.check(), [])

    def test_comprehensive_tree_preserves_detail_and_aligns_columns(self):
        folder = self.r / 'skills/interview-class/writing/3-experiments/deeper/specific'
        folder.mkdir(parents=True)
        name = 'a-skill-name-that-is-longer-than-the-old-fixed-name-column'
        desc = 'Use when comparing experiments. ' + 'keep relevant detail ' * 16 + 'final caveat'
        take = 'important rule ' * 12 + 'last condition'
        (folder / 'SKILL.md').write_text(
            f'---\nname: {name}\ndescription: {desc}\nmetadata:\n  source: own\n  takeaway: {take}\n---\nbody\n')
        sh(self.r, 'add', '.'); sh(self.r, 'commit', '-qm', 'deep skill')
        lines = sm.tree()
        text = '\n'.join(lines)
        self.assertIn('                deeper\n', text)
        self.assertIn(desc, text)
        self.assertIn(take, text)
        header = next(l for l in lines if l.startswith('skills '))
        own_rows = [l for l in lines if 'own' in l.split()]
        self.assertTrue(own_rows)
        self.assertTrue(all(l.index('own') == header.index('from') for l in own_rows))
        self.assertIn('1 skills linked (listed under their stage)', text)
        library = self.r / 'skills/all/tools/3-up/nested/unlinked'
        library.mkdir(parents=True)
        (library / 'SKILL.md').write_text('---\nname: available-only\ndescription: Full library detail.\n---\n')
        full = '\n'.join(sm.tree())
        self.assertIn('available-only', full)
        self.assertIn('ext up · not linked', full)
        self.assertIn('Full library detail.', full)

    def test_stamp_nested_metadata_and_tag(self):
        f = self.r / 'x.md'; f.write_text('---\nname: x\nmetadata:\n    hermes:\n        tags: [a]\n---\nb1\nb2\n')
        pv.stamp([f])
        import yaml
        d = yaml.safe_load(f.read_text().split('---')[1])
        self.assertEqual(d['metadata']['source'], 'own'); self.assertEqual(d['metadata']['hermes']['tags'], ['a'])
        with self.assertRaises(SystemExit):
            pv.tag(f, 2, 2, 'up')
        n = f.read_text().split('\n').index('b1') + 1
        pv.tag(f, n, n + 1, 'up')
        self.assertIn('<!-- ext up -->\nb1\nb2\n<!-- /ext up -->', f.read_text())

    def test_hook(self):
        hook, msg = HERE / 'commit-msg-hook', self.r / 'MSG'
        clean = {k: v for k, v in os.environ.items() if not k.startswith(('HERMES_', 'CLAUDE', 'CODEX_'))}
        msg.write_text('s\n'); subprocess.run(['sh', str(hook), str(msg)], env=clean, cwd=self.r)
        self.assertEqual(msg.read_text(), 's\n')
        for _ in range(2):
            subprocess.run(['sh', str(hook), str(msg)], env=dict(clean, HERMES_SESSION_ID='s1'), cwd=self.r)
        self.assertEqual(msg.read_text().count('Assisted-by: hermes'), 1)
        w = self.r / 'w'; w.write_text('#!/bin/sh\nH="/nope"\n[ -f "$H" ] && sh "$H" "$@"\nexit 0\n')
        self.assertEqual(subprocess.run(['sh', str(w), 'x']).returncode, 0)


class Merge(unittest.TestCase):
    def test_merge(self):
        d = Path(tempfile.mkdtemp())
        (d / 'o').write_text('a\nB\nc\nd\n'); (d / 't').write_text('a\nb\nc\nD\n')
        self.assertEqual(ms.merge(d / 'o', d / 't', 'a\nb\nc\nd\n', d / 'out'), 0)
        self.assertEqual((d / 'out').read_text(), 'a\nB\nc\nD\n')
        (d / 't').write_text('a\nX\nc\nd\n')
        self.assertEqual(ms.merge(d / 'o', d / 't', 'a\nb\nc\nd\n', d / 'out'), 1)


class Dora(unittest.TestCase):
    def test_rework(self):
        t = 1_700_000_000
        rows = [{'hash': '1', 'ts': t, 'subject': 'add', 'files': ['skills/a.md']},
                {'hash': '2', 'ts': t + 60, 'subject': 'fix again', 'files': ['skills/a.md']},
                {'hash': '3', 'ts': t + 120, 'subject': 'add fix-ci skill', 'files': ['skills/a.md']},
                {'hash': '4', 'ts': t + 99 * 86400, 'subject': 'revert broken hook', 'files': ['systems/h']}]
        m = dora.measure(rows)
        self.assertEqual((m['changes'], m['rework'], m['fail']), (4, 1, 1))


if __name__ == '__main__':
    unittest.main()
