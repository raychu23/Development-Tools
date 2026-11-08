"""tests for systems/runs      run: python3 -m unittest test_runs"""
import datetime
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'systems')
RUNS = os.path.join(HERE, 'runs')

SESSIONS = '''create table sessions (id text primary key, source text not null, parent_session_id text, started_at real not null,
    ended_at real, end_reason text, message_count integer default 0, tool_call_count integer default 0,
    estimated_cost_usd real, actual_cost_usd real, title text, last_activity_at real, model text, cwd text, model_config text)'''
EXECS = '''create table executions (id text primary key, job_id text not null, source text not null, process_id text not null,
    pid integer not null, status text not null, claimed_at text not null, started_at text, finished_at text, error text,
    delivery_outcome text, scheduled_instant text, progress_at text)'''


def iso(t):
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat()


class RunsTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.now = time.time()
        self.db = os.path.join(self.home, 'state.db')

    def tearDown(self):
        shutil.rmtree(self.home)

    def run_cli(self, *args):
        r = subprocess.run([sys.executable, RUNS, '--hermes-home', self.home, *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('Traceback', r.stderr)
        return r.stdout

    def j(self, *args):
        return json.loads(self.run_cli('--json', *args))

    def fixture(self):
        h = 3600
        n = self.now
        con = sqlite3.connect(self.db)
        con.execute(SESSIONS)
        rows = [
            # id, source, parent, started, ended, end_reason, tools, est cost, title, last_activity, model_config
            ('P1', 'desktop', None, n - 5 * h, None, None, 40, 2.5, 'live parent', n - 60, None),
            ('C1', 'desktop', 'P1', n - 4 * h, n - 3 * h, 'agent_close', 9, 0.4, 'Subagent: done child', n - 3 * h, None),
            ('C2', 'desktop', 'P1', n - 1 * h, None, None, 3, None, 'Subagent: busy child', n - 120, None),
            ('G1', 'desktop', 'C2', n - 0.5 * h, None, None, 1, None, 'Subagent: grandchild', n - 60, None),
            ('C3', 'desktop', 'P1', n - 20 * h, None, None, 2, None, 'Subagent: stuck child', n - 19 * h, None),
            ('P2', 'desktop', None, n - 6 * h, n - 2 * h, 'cli_close', 10, None, 'ended parent', n - 2 * h, None),
            ('C4', 'desktop', 'P2', n - 5 * h, None, None, 4, None, 'Subagent: orphan child', n - 2.5 * h, None),
            ('B1', 'desktop', 'P2', n - 3 * h, None, None, 4, None, 'a branch', n - 60, '{"_branched_from": "P2"}'),
            ('cron_job1_20261015_050000', 'cron', None, n - 1 * h, n - 0.9 * h, 'agent_close', 5, 0.1, 'cron run', None, None),
            ('OLD', 'desktop', None, n - 30 * 24 * h, n - 29 * 24 * h, 'cli_close', 1, None, 'old one', None, None),
        ]
        con.executemany('insert into sessions (id, source, parent_session_id, started_at, ended_at, end_reason, tool_call_count,'
                        ' estimated_cost_usd, title, last_activity_at, model_config) values (?,?,?,?,?,?,?,?,?,?,?)', rows)
        con.commit()
        con.close()
        os.makedirs(os.path.join(self.home, 'cron'))
        ex = sqlite3.connect(os.path.join(self.home, 'cron', 'executions.db'))
        ex.execute(EXECS)
        ex.executemany('insert into executions (id, job_id, source, process_id, pid, status, claimed_at, started_at, finished_at,'
                       ' progress_at) values (?,?,?,?,?,?,?,?,?,?)', [
                           ('e1', 'job1', 'tick', 'p', 1, 'completed', iso(n - h - 5), iso(n - h - 3), iso(n - 0.9 * h), None),
                           ('e2', 'script2', 'tick', 'p', 1, 'failed', iso(n - 2 * h), iso(n - 2 * h), iso(n - 2 * h + 5), None),
                           ('e3', 'script3', 'tick', 'p', 1, 'running', iso(n - 10 * h), iso(n - 10 * h), None, iso(n - 9 * h)),
                       ])
        ex.commit()
        ex.close()

    def test_tree_status_and_json_shape(self):
        self.fixture()
        v = self.j()
        for k in ('db', 'missing', 'since_days', 'errors', 'parents', 'cron', 'cron_executions', 'orphans', 'counts'):
            self.assertIn(k, v)
        parents = {p['id']: p for p in v['parents']}
        self.assertEqual(set(parents), {'P1', 'P2'})  # OLD is outside 7 days, the cron session is under cron
        p1 = parents['P1']
        self.assertEqual(p1['status'], 'running')
        self.assertEqual(p1['cost_usd'], 2.5)
        kids = {c['id']: c for c in p1['children']}
        self.assertEqual(set(kids), {'C1', 'C2', 'C3'})
        self.assertEqual(kids['C1']['status'], 'ended')
        self.assertEqual(kids['C1']['end_reason'], 'agent_close')
        self.assertEqual(kids['C1']['tool_calls'], 9)
        self.assertEqual(kids['C2']['status'], 'running')
        self.assertEqual([g['id'] for g in kids['C2']['children']], ['G1'])
        self.assertEqual(kids['C3']['status'], 'orphaned')  # open, no activity for 19 h > 6 h
        self.assertIn('no activity', kids['C3']['why'])
        p2kids = {c['id']: c for c in parents['P2']['children']}
        self.assertEqual(p2kids['C4']['status'], 'orphaned')  # parent ended, child still open
        self.assertIn('parent ended', p2kids['C4']['why'])
        self.assertEqual(p2kids['B1']['kind'], 'branch')
        self.assertEqual(p2kids['B1']['status'], 'running')  # branches outlive their parent by design
        orphans = {o['id'] for o in v['orphans']}
        self.assertEqual(orphans, {'C3', 'C4', 'e3'})
        self.assertEqual(v['counts']['orphaned'], 3)
        self.assertEqual(v['counts']['subagents'], 5)

    def test_cron_sessions_and_executions(self):
        self.fixture()
        v = self.j()
        self.assertEqual([c['id'] for c in v['cron']], ['cron_job1_20261015_050000'])
        self.assertEqual(v['cron'][0]['execution']['status'], 'completed')
        ex = {x['id']: x for x in v['cron_executions']}
        self.assertEqual(ex['e1']['session'], 'cron_job1_20261015_050000')  # agent fire bound to its session
        self.assertIsNone(ex['e2']['session'])  # script-only fire: execution row is its only record
        self.assertEqual(ex['e2']['status'], 'ended')
        self.assertEqual(ex['e3']['status'], 'orphaned')  # running, no progress for 9 h
        text = self.run_cli()
        self.assertIn('    cron', text)
        self.assertIn('job script2', text)

    def test_orphans_only_and_session_filter(self):
        self.fixture()
        v = self.j('--orphans')
        ids = {p['id']: [c['id'] for c in p['children']] for p in v['parents']}
        self.assertEqual(ids, {'P1': ['C3'], 'P2': ['C4']})
        self.assertEqual([x['id'] for x in v['cron_executions']], ['e3'])
        one = self.j('--session', 'G1')  # any id in the tree resolves to its root
        self.assertEqual([p['id'] for p in one['parents']], ['P1'])
        self.assertEqual(self.j('--session', 'nope')['errors'], ['no session nope'])
        self.assertEqual({p['id'] for p in self.j('--since', '40')['parents']}, {'OLD', 'P1', 'P2'})

    def test_text_is_notes_style(self):
        self.fixture()
        out = self.run_cli()
        self.assertTrue(out.startswith('```notes\nruns      last 7 days'))
        self.assertTrue(out.rstrip().endswith('```'))
        self.assertIn('orphaned  C4', out)
        self.assertNotIn(';', out)

    def test_readonly(self):
        self.fixture()
        def state():
            with open(self.db, 'rb') as f:
                return os.path.getmtime(self.db), f.read(), sorted(os.listdir(self.home))
        before = state()
        os.chmod(self.db, 0o444)
        self.run_cli()
        self.assertEqual(state(), before)  # no write, no -wal / -journal left behind

    def test_locked_db_still_reads(self):
        self.fixture()
        con = sqlite3.connect(self.db)
        con.execute('begin exclusive')
        try:
            v = self.j()
        finally:
            con.rollback()
            con.close()
        self.assertEqual(v['errors'], [])
        self.assertEqual(len(v['parents']), 2)

    def test_empty_db(self):
        con = sqlite3.connect(self.db)
        con.execute(SESSIONS)
        con.close()
        v = self.j()
        self.assertFalse(v['missing'])
        self.assertEqual((v['parents'], v['cron'], v['orphans'], v['errors']), ([], [], [], []))
        self.assertIn('no parent sessions', self.run_cli())

    def test_db_without_sessions_table(self):
        sqlite3.connect(self.db).close()
        self.assertEqual(self.j()['parents'], [])

    def test_missing_db(self):
        v = self.j()
        self.assertTrue(v['missing'])
        self.assertEqual(v['parents'], [])
        self.assertIn('no hermes state db at', self.run_cli())
        self.assertFalse(os.path.exists(self.db))  # never created

    def add_sessions(self, rows):
        con = sqlite3.connect(self.db)
        con.executemany('insert into sessions (id, source, parent_session_id, started_at, ended_at, last_activity_at, title)'
                        ' values (?,?,?,?,?,?,?)', rows)
        con.commit()
        con.close()

    # prevents a logged mistake [source: Project/sdlc/T8-agent-setups-research/systems/code tasks/T4-runs-and-memory-snapshot; added: 2026-10-15]
    def test_iso_string_timestamps_on_open_children(self):
        # review round 1: ISO last_activity_at / started_at on an open child crashed the stale check (float(iso))
        self.fixture()
        n, h = self.now, 3600
        self.add_sessions([
            ('P3', 'desktop', None, n - 3 * h, None, n - 60, 'iso parent'),
            ('I1', 'desktop', 'P3', iso(n - 2 * h), None, iso(n - 60), 'Subagent: iso busy'),
            ('I2', 'desktop', 'P3', iso(n - 20 * h), None, None, 'Subagent: iso stuck'),
            ('cron_job4_20261015_060000', 'cron', None, iso(n - 0.5 * h), None, None, 'iso cron'),
        ])
        ex = sqlite3.connect(os.path.join(self.home, 'cron', 'executions.db'))
        ex.execute("insert into executions (id, job_id, source, process_id, pid, status, claimed_at, started_at) "
                   "values ('e4', 'job4', 'tick', 'p', 1, 'running', ?, ?)", (iso(n - 0.5 * h - 5), iso(n - 0.5 * h)))
        ex.commit()
        ex.close()
        v = self.j()  # mixed real + ISO started_at must also sort and bind without a crash
        kids = {c['id']: c for p in v['parents'] if p['id'] == 'P3' for c in p['children']}
        self.assertEqual(kids['I1']['status'], 'running')
        self.assertEqual(kids['I1']['why'], '')
        self.assertEqual(kids['I2']['status'], 'orphaned')
        self.assertIn('no activity for 20.0 h', kids['I2']['why'])
        self.assertEqual(kids['I1']['started'][:4], iso(n)[:4])  # shown as local time, not the raw string
        cron = {c['id']: c for c in v['cron']}
        self.assertEqual(cron['cron_job4_20261015_060000']['status'], 'running')
        self.assertEqual({x['id']: x['session'] for x in v['cron_executions']}['e4'], 'cron_job4_20261015_060000')
        self.assertIn('orphaned  I2', self.run_cli())

    def test_garbage_timestamps_skip_stale_check_with_note(self):
        self.fixture()
        n = self.now
        self.add_sessions([
            ('P4', 'desktop', None, n - 3600, None, n - 60, 'garbage parent'),
            ('X1', 'desktop', 'P4', n - 20 * 3600, None, 'not-a-time', 'Subagent: bad activity'),
            ('X2', 'desktop', 'P4', 'yesterday-ish', None, None, 'Subagent: bad start'),
            ('X3', 'desktop', 'P4', n - 600, None, '', 'Subagent: blank activity'),
        ])
        ex = sqlite3.connect(os.path.join(self.home, 'cron', 'executions.db'))
        ex.execute("insert into executions (id, job_id, source, process_id, pid, status, claimed_at, progress_at) "
                   "values ('e5', 'script5', 'tick', 'p', 1, 'running', 'garbage', '??')")
        ex.commit()
        ex.close()
        v = self.j('--since', '40')
        kids = {c['id']: c for p in v['parents'] if p['id'] == 'P4' for c in p['children']}
        for sid, field in (('X1', 'last_activity_at'), ('X2', 'started_at')):
            self.assertEqual(kids[sid]['status'], 'running', sid)  # never flagged orphaned on unreadable data
            self.assertIn(f'stale check skipped: unreadable {field}', kids[sid]['why'])
        self.assertEqual(kids['X2']['started'], 'yesterday-ish')  # unparseable stamp shown as-is
        self.assertEqual((kids['X3']['status'], kids['X3']['why']), ('running', ''))  # blank falls back to started_at
        e5 = {x['id']: x for x in v['cron_executions']}['e5']
        self.assertEqual(e5['status'], 'running')
        self.assertIn('stale check skipped: unreadable progress_at', e5['why'])
        self.assertNotIn('X1', {o['id'] for o in v['orphans']})
        out = self.run_cli('--since', '40')
        self.assertIn('stale check skipped', out)
        self.assertNotIn(';', out)

    def test_bad_flags(self):
        r = subprocess.run([sys.executable, RUNS, '--hermes-home', self.home, '--since', '0'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == '__main__':
    unittest.main()
