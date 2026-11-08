"""Public seam and legacy recovery checks, exclusively in disposable fixtures."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_core import Store, make_boot

HERE = Path(__file__).resolve().parents[1] / 'systems'


def load(name):
    loader = importlib.machinery.SourceFileLoader('integration_' + name, str(HERE / name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


ctx = load('ctx')
ledger = load('ledger')


class Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = self.root / 'Project/demo/T1-work'
        self.task.mkdir(parents=True)
        (self.task / '0 start.md').write_text('```notes\n    task\n        goal                preserve corrections\n        done-when           current output matches intent\n        status              active\n        next                write output\n        pinned              keep original\n        came from           fixture\n        links               1 takeaways.md\n        harness             fixture\n```\n')
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        self.git('add','.')
        self.git('-c','user.name=t','-c','user.email=t@t','commit','-qm','fixture')

    def git(self, *args):
        return subprocess.run(['git','-C',str(self.root),*args],capture_output=True,text=True,check=True).stdout

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = ctx.main(['--root',str(self.root),*args])
        return result, out.getvalue(), err.getvalue()

    def enroll(self):
        store = Store(self.root, commit=False)
        record = store.enroll(str(self.task), 'owner', 'preserve corrections', ['current output matches intent'])
        self.owner = {'owner_token': record['owner_token']} if record.get('owner_token') else {}
        run = store.claim(str(self.task), 'owner', **self.owner)
        store.acknowledge(str(self.task), run['run_id'], 'owner', run['token'], make_boot(self.root,str(self.task))['manifest'])
        return store, run

    def test_t4_6_legacy_done_status_refused_until_core_complete(self):
        store, run = self.enroll()
        with patch.dict(os.environ,{'CTX_ACTOR':'owner','CTX_RUN':run['run_id'],'CTX_RUN_TOKEN':run['token']}):
            set_code, _, set_err = self.call('--no-commit','set',str(self.task),'status=done')
            beat_code, _, beat_err = self.call('--no-commit','beat',str(self.task),'--status','verified and complete')
            ok_code, _, ok_err = self.call('--no-commit','set',str(self.task),'next=build the parser')
        packet = (self.task/'0 start.md').read_text()
        self.assertEqual(store.contract(str(self.task))['state'], 'active')
        self.assertEqual(ok_code, 0, ok_err)
        self.assertEqual(ctx.fm_get(packet, 'next'), 'build the parser')
        self.assertEqual(set_code, 2, 'legacy done claimed while core state is active')
        self.assertEqual(beat_code, 2, 'legacy beat claimed done while core state is active')
        self.assertIn('core state', set_err + beat_err)

    def test_t4_3_tokenless_case_variant_pin_cannot_write_leased_file(self):
        shared = self.root / 'Project/shared'
        shared.mkdir(parents=True)
        (shared / '0 start.md').write_text('```notes\n    shared notes folder\n```\n')
        note = shared / 'note.md'
        note.write_text('---\ncarry: auto\n---\n```notes\n    leased note\n```\n')
        if not (self.root / 'project/SHARED/note.md').exists():
            self.skipTest('case-sensitive filesystem: spellings are distinct paths')
        store = Store(self.root, commit=False)
        record = store.enroll(str(self.task), 'owner', 'shared scope', ['scope respected'],
                              [str(self.task), 'Project/shared'])
        owner = {'owner_token': record['owner_token']} if record.get('owner_token') else {}
        store.claim(str(self.task), 'owner', allowed_paths=['Project/shared'], **owner)
        before = note.read_text()
        code, out, err = self.call('--no-commit', 'pin', str(self.root / 'project/SHARED/note.md'))
        self.assertEqual(note.read_text(), before, 'tokenless case-variant pin wrote into a leased file')
        self.assertEqual(code, 2)

    def test_t4_4_truncated_legacy_journal_is_named_and_quarantinable(self):
        journals = Path(ctx.legacy_journal_dir(str(self.root)))
        journals.mkdir(parents=True, exist_ok=True)
        broken = journals / 'broken-op.json'
        broken.write_bytes(b'{"schema_version": 1, "kind": "legacy_ctx", "operation_id": "bro')
        store = Store(self.root, commit=False)
        reports = store.recover()
        self.assertEqual([(r['operation_id'], r['phase']) for r in reports], [('broken-op', 'corrupt')])
        with self.assertRaisesRegex(RuntimeError, 'quarantine'):
            store.transaction('blocked', {'Project/demo/T1-work/x.md': 'x'})
        code, out, err = self.call('--no-commit', 'set', str(self.task), 'next=after recovery')
        self.assertEqual(code, 2)
        self.assertIn('broken-op', err)
        self.assertNotIn('Traceback', err)
        code, out, err = self.call('system', 'recover', '--quarantine', str(broken))
        self.assertEqual(code, 0, err)
        self.assertEqual((journals / 'corrupt/broken-op.json').read_bytes()[:20], b'{"schema_version": 1')
        code, out, err = self.call('--no-commit', 'set', str(self.task), 'next=after recovery')
        self.assertEqual(code, 0, err)
        store.transaction('allowed', {'Project/demo/T1-work/x.md': 'x'})

    def test_t4_7_relegate_checks_owner_first_and_repairs_external_links(self):
        sub = self.task / 'c idea'
        sub.mkdir()
        (sub / '0 start.md').write_text('```notes\n    idea\n        goal                try it\n```\n')
        other = self.root / 'Project/other'
        other.mkdir(parents=True)
        notes = other / 'notes.md'
        notes.write_text('see [idea](../demo/T1-work/c%20idea/0%20start.md)\nplan Project/demo/T1-work/c idea/plan.md\n')
        personal = self.root / 'Notes/mine.md'
        personal.parent.mkdir()
        personal.write_text('Project/demo/T1-work/c idea/0 start.md\n')
        locked = self.root / 'Work/proj/T5-locked'
        locked.mkdir(parents=True)
        (locked / '0 start.md').write_text('```notes\n    locked\n```\n')
        (locked / 'refs.md').write_text('Project/demo/T1-work/c idea/0 start.md\n')
        self.git('add', '.')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'links fixture')
        store = Store(self.root, commit=False)
        record = store.enroll(str(sub), 'owner', 'idea', ['decided'])
        Store(self.root, commit=False).enroll(str(locked), 'other-owner', 'locked', ['kept'])
        owner = {'owner_token': record['owner_token']} if record.get('owner_token') else {}
        run = store.claim(str(sub), 'owner', **owner)
        store.acknowledge(str(sub), run['run_id'], 'owner', run['token'], make_boot(self.root, str(sub))['manifest'])
        env = {'CTX_ACTOR': 'owner', 'CTX_RUN': run['run_id'], 'CTX_RUN_TOKEN': run['token']}
        with patch.dict(os.environ, dict(env, CTX_OWNER_TOKEN='not-the-owner')):
            code, out, err = self.call('relegate', str(sub), '--no-merge')
        self.assertEqual(code, 2)
        self.assertTrue(sub.is_dir(), 'non-owner relegate moved the folder before the record check')
        self.assertEqual(store.contract(str(sub))['location'], 'Project/demo/T1-work/c idea')
        with patch.dict(os.environ, dict(env, CTX_OWNER_TOKEN=record.get('owner_token', ''))):
            code, out, err = self.call('relegate', str(sub), '--no-merge')
        self.assertEqual(code, 0, err)
        moved = self.task / 'o idea'
        self.assertEqual(Store(self.root, commit=False).contract(str(moved))['location'], 'Project/demo/T1-work/o idea')
        self.assertEqual(notes.read_text(), 'see [idea](../demo/T1-work/o%20idea/0%20start.md)\nplan Project/demo/T1-work/o idea/plan.md\n')
        self.assertEqual(personal.read_text(), 'Project/demo/T1-work/c idea/0 start.md\n')
        self.assertIn('Work/proj/T5-locked/refs.md', out)
        self.assertEqual((locked / 'refs.md').read_text(), 'Project/demo/T1-work/c idea/0 start.md\n')

    def test_t4_r3_legacy_status_on_enrolled_task_is_display_only(self):
        store, run = self.enroll()
        with patch.dict(os.environ,{'CTX_ACTOR':'owner','CTX_RUN':run['run_id'],'CTX_RUN_TOKEN':run['token']}):
            shipped, _, shipped_err = self.call('--no-commit','set',str(self.task),'status=shipped')
            beat, _, beat_err = self.call('--no-commit','beat',str(self.task),'--status','all good')
            nxt, _, nxt_err = self.call('--no-commit','set',str(self.task),'next=write the parser')
        self.assertEqual(nxt, 0, nxt_err)
        self.assertIsNone(ctx.fm_get((self.task/'0 start.md').read_text(), 'status'))
        self.assertEqual((shipped, beat), (2, 2), 'legacy status written on an enrolled task')
        self.assertIn('core state', shipped_err + beat_err)
        code, out, err = self.call('tree', str(self.task), '--json')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)[0]['status'], 'core state: active')

    def test_t4_r4_relegate_repairs_relative_links_and_reports_each(self):
        sub = self.task / 'c work'
        sub.mkdir()
        (sub / '0 start.md').write_text('```notes\n    work\n        goal                try it\n```\n')
        other = self.root / 'Project/other'
        other.mkdir(parents=True)
        notes = other / 'notes.md'
        notes.write_text('plain [w](../demo/T1-work/c work/0 start.md)\nbare ../demo/T1-work/c work/plan.md\n')
        personal = self.root / 'Notes/mine.md'
        personal.parent.mkdir()
        personal.write_text('[mine](../Project/demo/T1-work/c work/0 start.md)\n')
        self.git('add', '.')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'relative links fixture')
        code, out, err = self.call('relegate', str(sub), '--no-merge')
        self.assertEqual(code, 0, err)
        self.assertEqual(notes.read_text(), 'plain [w](../demo/T1-work/o work/0 start.md)\nbare ../demo/T1-work/o work/plan.md\n')
        self.assertEqual(personal.read_text(), '[mine](../Project/demo/T1-work/c work/0 start.md)\n')
        self.assertIn('external link fixed: Project/other/notes.md: ../demo/T1-work/c work/0 start.md → ../demo/T1-work/o work/0 start.md', out)
        self.assertIn('external link not fixed: Notes/mine.md: ../Project/demo/T1-work/c work/0 start.md (personal folder Notes/, never edited)', out)

    def test_namespace_help_and_services_available(self):
        with self.assertRaises(SystemExit) as result, contextlib.redirect_stdout(io.StringIO()) as out:
            ctx.main(['--root',str(self.root),'system','--help'])
        self.assertEqual(result.exception.code, 0)
        self.assertIn('sources',out.getvalue())
        self.assertIn('recover',out.getvalue())

    def test_managed_pin_requires_lease_and_accepts_acknowledged_owner(self):
        store, run = self.enroll()
        code, out, err = self.call('--no-commit','pin',str(self.task),'--text','new decision')
        self.assertEqual(code, 2)
        self.assertIn('require',err)
        with patch.dict(os.environ,{'CTX_ACTOR':'owner','CTX_RUN':run['run_id'],'CTX_RUN_TOKEN':run['token']}):
            code, out, err = self.call('--no-commit','pin',str(self.task),'--text','new decision')
        self.assertEqual(code,0,err)
        self.assertIn('new decision',(self.task/'0 start.md').read_text())

    def test_managed_move_requires_destination_in_lease(self):
        store=Store(self.root,commit=False)
        record=store.enroll(str(self.task),'owner','scope test',['preserve scope'])
        source,target=self.task/'c idea',self.task/'o idea'
        source.mkdir();(source/'0 start.md').write_text('```notes\n    idea\n```\n')
        run=store.claim(str(self.task),'owner',allowed_paths=[str(source)],owner_token=record['owner_token'])
        store.acknowledge(str(self.task),run['run_id'],'owner',run['token'],make_boot(self.root,str(self.task))['manifest'])
        with patch.dict(os.environ,{'CTX_ACTOR':'owner','CTX_RUN':run['run_id'],'CTX_RUN_TOKEN':run['token']}):
            with self.assertRaises(ctx.CtxError):
                ctx.Ctx(str(self.root),commit=False).move(str(source),str(target))
        self.assertTrue(source.exists());self.assertFalse(target.exists())

    def test_managed_boot_default_budget_and_reserved_fields(self):
        store, run = self.enroll()
        code, out, err = self.call('boot',str(self.task))
        self.assertEqual(code,0,err)
        self.assertIn('preserve corrections',out)
        with patch.dict(os.environ,{'CTX_ACTOR':'owner','CTX_RUN':run['run_id'],'CTX_RUN_TOKEN':run['token']}):
            code, out, err = self.call('--no-commit','set',str(self.task),'state=done')
        self.assertEqual(code,2)
        self.assertIn('managed contract fields',err)
        self.assertEqual(store.contract(str(self.task))['state'],'active')

    def test_legacy_send_uses_durable_managed_inbox(self):
        self.enroll()
        original = (self.task/'0 start.md').read_bytes()
        code, out, err = self.call('--no-commit','send',str(self.task),'question from another run','--from','peer')
        self.assertEqual(code,0,err)
        self.assertIn('message_id',out)
        messages=list((self.task/'systems/messages').glob('*.json'))
        self.assertEqual(len(messages),1)
        self.assertEqual(original,(self.task/'0 start.md').read_bytes())
        self.assertFalse(json.loads(messages[0].read_text()).get('acknowledged'))

    def test_interrupted_legacy_multi_file_action_restores_before_state(self):
        a,b=self.task/'a.md',self.task/'b.md'
        a.write_text('original a');b.write_text('original b')
        action=ctx.Ctx(str(self.root),commit=False)
        action.edit(str(a),'partial a')
        action.edit(str(b),'partial b')
        reports=ctx.recover_legacy(str(self.root))
        self.assertEqual(reports[0]['phase'],'rolled_back')
        self.assertEqual(a.read_text(),'original a');self.assertEqual(b.read_text(),'original b')

    def test_legacy_recovery_preserves_later_manual_edit(self):
        a=self.task/'a.md';a.write_text('original')
        action=ctx.Ctx(str(self.root),commit=False)
        action.edit(str(a),'partial')
        a.write_text('human later edit')
        reports=ctx.recover_legacy(str(self.root))
        self.assertEqual(reports[0]['phase'],'conflict')
        self.assertEqual(a.read_text(),'human later edit')

    def test_edit_arriving_between_legacy_recovery_replacements_is_preserved(self):
        a,b=self.task/'a.md',self.task/'b.md'
        a.write_text('old a');b.write_text('old b')
        action=ctx.Ctx(str(self.root),commit=False)
        action.edit(str(a),'partial a');action.edit(str(b),'partial b')
        original_write=ctx.write
        def concurrent_write(path,text):
            original_write(path,text)
            if str(path)==str(a) and text=='old a':
                b.write_text('later human edit')
        with patch.object(ctx,'write',concurrent_write):
            report=ctx.recover_legacy(str(self.root))
        self.assertEqual(report[0]['phase'],'conflict')
        self.assertEqual(b.read_text(),'later human edit')

    def test_legacy_commit_is_recognized_after_receipt_crash(self):
        a=self.task/'a.md';a.write_text('original')
        action=ctx.Ctx(str(self.root),commit=True)
        action.edit(str(a),'finished')
        receipt=action.commit('completed legacy operation')
        journal=Path(action.journal)
        record=json.loads(journal.read_text());record['phase']='committing'
        journal.write_text(json.dumps(record))
        reports=ctx.recover_legacy(str(self.root))
        self.assertEqual(reports[0]['phase'],'committed')
        self.assertEqual(a.read_text(),'finished')
        self.assertTrue(receipt)

    def test_managed_ledger_cannot_verify_without_acceptance(self):
        self.enroll()
        packet=self.task/'0 start.md'
        packet.write_text(ctx.fm_set(packet.read_text(),state='submitted',owner='owner'))
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=ledger.main(['--root',str(self.root),'--no-commit','--no-orca','move',str(self.task),'verified',
                              '--reviewer','fresh','--findings','none','--checks-result','passed'])
        self.assertEqual(code,2)
        self.assertIn('current criterion acceptance',err.getvalue())


if __name__=='__main__':
    unittest.main()
