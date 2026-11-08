"""Native routing, privacy, acknowledgement and hook-preservation contract fixtures."""
import copy
import contextlib
import io
import subprocess
import shlex
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent_core import Store, AgentError
from native_activation import NativeRegistry, handle_hook, merged_hooks, install, known_write_paths, hook_main, ack_argv, public_ack, bind_argv, public_bind, main

class NativeActivation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'repo';self.root.mkdir()
        self.task='Project/demo/T1-active';self.folder=self.root/self.task;self.folder.mkdir(parents=True)
        (self.folder/'0 start.md').write_text('```notes\n    goal                    preserve source\n    status                  active\n    next                    implement parser\n```\n')
        self.store=Store(self.root,commit=False)
        self.contract=self.store.enroll(self.task,'owner','preserve source',['current source matches intent'])
        self.registry=NativeRegistry(self.root,Path(self.temp.name)/'private')
        self.registry.register(self.task,self.contract['owner_token'])
        self.data={'session_id':'native-session','cwd':str(self.folder)}
        self.environment=patch.dict(os.environ,{},clear=True);self.environment.start();self.addCleanup(self.environment.stop)

    def output(self,event,data=None):return handle_hook(self.registry,'codex',event,data or self.data)

    def test_root_and_external_sessions_never_claim_unrelated_task(self):
        result=self.output('session-start',dict(self.data,cwd=str(self.root)))
        self.assertIn('no task binding',result['hookSpecificOutput']['additionalContext'])
        self.assertIsNone(self.output('session-start',dict(self.data,cwd=str(Path(self.temp.name)))))
        self.assertEqual(self.registry.status()['sessions'],{})
        self.assertEqual(self.store._list(self.task,'runs'),[])

    def test_boot_requires_explicit_read_ack_and_keeps_credentials_private(self):
        result=self.output('session-start')
        context=result['hookSpecificOutput']['additionalContext']
        state=json.loads(self.registry.path.read_text())['projects'][str(self.root.resolve())]['sessions']['codex:native-session']
        self.assertIn('Delivery is not acknowledgement',context)
        self.assertNotIn(state['token'],context)
        self.assertNotIn(self.contract['owner_token'],context)
        self.assertNotIn('acknowledged_at',state)
        self.assertNotIn(state['token'],json.dumps(self.registry.status()))
        self.assertEqual(self.registry.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.registry.directory.stat().st_mode & 0o777,0o700)
        with self.assertRaisesRegex(AgentError,'acknowledgement'):
            self.registry.credentials('codex','native-session')
        ack=self.registry.acknowledge('codex','native-session')
        self.assertEqual(ack['acknowledged_rev'],1)
        self.assertIn('CTX_RUN_TOKEN',self.registry.credentials('codex','native-session',renew=True))

    def test_known_write_denied_until_ack_and_scope_checked(self):
        self.output('session-start')
        data=dict(self.data,tool_name='Write',tool_input={'file_path':str(self.folder/'out.md')})
        self.assertEqual(self.output('pre-tool',data)['hookSpecificOutput']['permissionDecision'],'deny')
        self.registry.acknowledge('codex','native-session')
        self.assertIsNone(self.output('pre-tool',data))
        other='Project/demo/T2-other';(self.root/other).mkdir();(self.root/other/'0 start.md').write_text('other')
        self.store.enroll(other,'other','other goal',['other result'])
        bad=dict(data,tool_input={'file_path':str(self.root/other/'out.md')})
        self.assertEqual(self.output('pre-tool',bad)['hookSpecificOutput']['permissionDecision'],'deny')
        external=dict(data,tool_input={'file_path':str(Path(self.temp.name)/'outside.md')})
        self.assertIsNone(self.output('pre-tool',external))

    def test_stale_packet_cannot_ack_and_prompt_emits_updated_packet(self):
        self.output('session-start')
        (self.folder/'0 start.md').write_text('corrected current packet')
        with self.assertRaisesRegex(AgentError,'sources changed'):
            self.registry.acknowledge('codex','native-session')
        result=self.output('prompt')
        self.assertIn('corrected current packet',result['hookSpecificOutput']['additionalContext'])
        self.registry.acknowledge('codex','native-session')
        self.assertIsNone(self.output('prompt'))

    def test_historical_registration_routes_only_when_explicit_and_does_not_claim(self):
        self.registry.register(self.task,self.contract['owner_token'],auto=False)
        self.assertIn('no task binding',self.output('session-start')['hookSpecificOutput']['additionalContext'])
        self.registry.bind('codex','native-session',self.task)
        self.output('session-start')
        self.assertEqual(self.store._list(self.task,'runs'),[])

    def test_session_binding_is_harness_specific_and_conflicting_env_refused(self):
        self.registry.bind('codex','native-session',self.task)
        result=handle_hook(self.registry,'claude-code','session-start',dict(self.data,cwd=str(self.root)))
        self.assertIn('no task binding',result['hookSpecificOutput']['additionalContext'])
        second='Project/demo/T2-other';(self.root/second).mkdir();(self.root/second/'0 start.md').write_text('other')
        self.store.enroll(second,'other','other goal',['other result'])
        with patch.dict(os.environ,{'CTX_TASK':second}):
            with self.assertRaisesRegex(AgentError,'conflicts'):
                self.output('session-start')

    def test_session_end_releases_lease(self):
        self.output('session-start');self.registry.acknowledge('codex','native-session')
        self.output('session-end')
        runs=self.store._list(self.task,'runs')
        self.assertEqual(runs[0]['status'],'released')
        with self.assertRaisesRegex(AgentError,'no writer'):
            self.registry.credentials('codex','native-session')

    def test_complete_task_boot_does_not_reopen_or_hold_writer(self):
        self.output('session-start');self.registry.acknowledge('codex','native-session')
        location=self.folder/'systems/task.json'
        contract=self.store.read(location);contract['state']='complete'
        self.store.transaction('fixture-complete',{str(location):contract})
        result=self.output('session-start')
        self.assertIn('read-only',result['hookSpecificOutput']['additionalContext'])
        self.assertEqual(self.store.contract(self.task)['state'],'complete')
        self.assertEqual(self.store._list(self.task,'runs')[0]['status'],'released')
        with self.assertRaisesRegex(AgentError,'no writer'):
            self.registry.credentials('codex','native-session')

    def test_expired_session_resume_gets_fresh_grant_with_fresh_ack_required(self):
        self.output('session-start');self.registry.acknowledge('codex','native-session')
        before=self.registry.status()['sessions']['codex:native-session']['run']
        location=self.store._record(self.task,'runs',before)
        record=self.store.read(location);record['expires_at']=0
        self.store.transaction('fixture-expire',{str(location):record})
        self.output('session-start')
        self.assertNotEqual(self.registry.status()['sessions']['codex:native-session']['run'],before)
        with self.assertRaisesRegex(AgentError,'acknowledgement'):
            self.registry.credentials('codex','native-session')

    def test_overlapping_native_sessions_receive_visible_grant_failure(self):
        self.output('session-start')
        result=self.output('session-start',dict(self.data,session_id='different'))
        self.assertIn('Writer grant unavailable',result['hookSpecificOutput']['additionalContext'])
        self.assertEqual(len(self.store._list(self.task,'runs')),1)

    def test_corrupt_private_registry_is_visible_and_not_replaced(self):
        self.registry.path.write_text('{broken')
        with self.assertRaisesRegex(AgentError,'unreadable'):
            self.registry.status()
        self.assertEqual(self.registry.path.read_text(),'{broken')

    def test_wrong_owner_token_and_symlink_private_registry_refused(self):
        with self.assertRaisesRegex(AgentError,'credential'):
            self.registry.register(self.task,'wrong')
        self.registry.path.unlink();self.registry.path.symlink_to(self.folder/'0 start.md')
        with self.assertRaisesRegex(AgentError,'symlink'):
            self.registry.status()

    def test_installer_preserves_all_existing_settings_and_hooks_idempotently(self):
        original={'permissions':{'allow':['Read']},'model':'existing-model','hooks':{
            'SessionStart':[{'matcher':'resume','hooks':[{'type':'command','command':'existing ai-memory hook'}]}],
            'Stop':[{'hooks':[{'type':'command','command':'existing archive hook'}]}]}}
        path=Path(self.temp.name)/'settings.json';path.write_text(json.dumps(original))
        result=install(path,self.root,'claude-code')
        self.assertTrue(result['changed'])
        updated=json.loads(path.read_text())
        self.assertEqual(updated['permissions'],original['permissions'])
        self.assertEqual(updated['model'],original['model'])
        self.assertIn(original['hooks']['SessionStart'][0],updated['hooks']['SessionStart'])
        self.assertIn(original['hooks']['Stop'][0],updated['hooks']['Stop'])
        self.assertFalse(install(path,self.root,'claude-code')['changed'])
        self.assertEqual(json.loads(path.read_text()),updated)

    def test_installer_malformed_config_untouched_and_trust_not_forged(self):
        path=Path(self.temp.name)/'hooks.json';path.write_text('{broken')
        with self.assertRaisesRegex(AgentError,'malformed'):
            install(path,self.root,'codex')
        self.assertEqual(path.read_text(),'{broken')
        path.write_text('{}');result=install(path,self.root,'codex')
        self.assertIn('never forges trust',result['trust'])
        self.assertNotIn('trusted_hash',path.read_text())

    def test_corrupt_registry_visible_and_denies_managed_write_in_same_git_alias(self):
        def git(*args):
            subprocess.run(['git','-C',str(self.root),*args],check=True,capture_output=True)
        git('init','-q');git('add',self.task+'/0 start.md')
        git('-c','user.name=fixture','-c','user.email=fixture@example.test','commit','-qm','fixture')
        alias=Path(self.temp.name)/'alias'
        git('worktree','add','-q','--detach',str(alias))
        self.registry.alias(alias)
        self.registry.path.write_text('{broken')
        def invoke(event,cwd,tool=None):
            data=dict(self.data,cwd=str(cwd))
            if tool:data.update(tool_name='Write',tool_input={'file_path':str(tool)})
            out,err=io.StringIO(),io.StringIO()
            with patch.dict(os.environ,{'CTX_NATIVE_STATE':str(self.registry.directory)}), patch('sys.stdin',io.StringIO(json.dumps(data))), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code=hook_main(['--root',str(self.root),'--harness','codex',event])
            self.assertEqual(code,0)
            return out.getvalue(),err.getvalue()
        out,err=invoke('session-start',alias)
        self.assertIn('unavailable',json.loads(out)['hookSpecificOutput']['additionalContext'])
        out,err=invoke('pre-tool',alias,alias/self.task/'out.md')
        self.assertEqual(json.loads(out)['hookSpecificOutput']['permissionDecision'],'deny')
        other=Path(self.temp.name)/'other';other.mkdir()
        subprocess.run(['git','init','-q',str(other)],check=True,capture_output=True)
        self.assertEqual(invoke('session-start',other),('',''))
        self.assertEqual(invoke('pre-tool',other,other/'out.md'),('',''))
        # Same repository alone does not make an unmanaged exact-file write managed.
        self.assertEqual(invoke('pre-tool',alias,alias/'unmanaged.md')[0],'')

    def ack_data(self):
        return dict(self.data,tool_name='Bash',tool_input={'command':shlex.join(ack_argv(self.root,'codex','native-session',self.task))})

    def test_exact_native_ack_handoff_and_cli_receipt_are_read_only(self):
        self.output('session-start')
        result=self.output('pre-tool',self.ack_data())
        self.assertIn('trusted native hook',result['hookSpecificOutput']['additionalContext'])
        receipt=self.folder/'systems/native ack'
        public=json.loads(next(receipt.glob('*.json')).read_text())
        self.assertNotIn('token',json.dumps(public))
        out,err=io.StringIO(),io.StringIO()
        # The read-only seam must not even construct these mutation-capable objects.
        with patch('native_activation.Store',side_effect=AssertionError('Store constructed')), patch('native_activation.NativeRegistry',side_effect=AssertionError('registry constructed')), contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=main(['--root',str(self.root),'ack','--harness','codex','--session','native-session','--task',self.task])
        self.assertEqual(code,0,err.getvalue())
        self.assertEqual(json.loads(out.getvalue())['acknowledged_rev'],1)
        self.assertIn('no capability granted',out.getvalue())

    def test_native_ack_rejects_spoofed_harness_session_root_script_and_compound(self):
        self.output('session-start')
        good=ack_argv(self.root,'codex','native-session',self.task)
        variants=[]
        for find,replacement in [('codex','claude-code'),('native-session','other-session'),(str(self.root.resolve()),str(self.root.parent/'other')),(str(self.root.resolve()/'systems/native_activation.py'),str(self.root.parent/'native_activation.py')),(self.task,'Project/demo/T2-other')]:
            modified=list(good);modified[modified.index(find)]=replacement;variants.append(shlex.join(modified))
        variants.extend([shlex.join(good)+'; echo bad',shlex.join(good)+' && true',shlex.join(good)+' > output',shlex.join(good)+'\ntrue','X=1 '+shlex.join(good)])
        for command in variants:
            data=dict(self.data,tool_name='Bash',tool_input={'command':command})
            result=self.output('pre-tool',data)
            self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny',command)
        self.assertFalse((self.folder/'systems/native ack').exists())
        self.assertIsNone(self.store._list(self.task,'runs')[0]['acknowledged_rev'])

    def test_public_receipt_cannot_ack_expired_stale_or_other_session_run(self):
        self.output('session-start');self.output('pre-tool',self.ack_data())
        self.assertIsNone(public_ack(self.root,self.task,'codex','other-session'))
        run=self.store._list(self.task,'runs')[0]
        path=self.store._record(self.task,'runs',run['run_id'])
        cases=[{'expires_at':0},{'status':'released'},{'acknowledged_rev':None},{'session_receipt':'native:codex:wrong:explicit-read-ack'},
               {'boot_manifest_hash':'a'*64},{'task_id':'task-wrong'}]
        for fields in cases:
            self.store.transaction('fixture-run-corruption',{str(path):dict(run,**fields)})
            with self.assertRaisesRegex(AgentError,'stale'):
                public_ack(self.root,self.task,'codex','native-session')
        self.store.transaction('fixture-run-restore',{str(path):run})
        location=self.folder/'systems/task.json'
        contract=self.store.read(location);contract['requirement_rev']+=1
        self.store.transaction('fixture-correction',{str(location):contract})
        with self.assertRaisesRegex(AgentError,'stale'):
            public_ack(self.root,self.task,'codex','native-session')

    def test_fake_receipt_does_not_create_ack_and_symlink_sources_refused(self):
        self.output('session-start');self.output('pre-tool',self.ack_data())
        receipt=next((self.folder/'systems/native ack').glob('*.json'))
        before=self.store._list(self.task,'runs')[0]
        record=json.loads(receipt.read_text());record['run_id']='../../escape'
        receipt.write_text(json.dumps(record))
        with self.assertRaisesRegex(AgentError,'run id'):
            public_ack(self.root,self.task,'codex','native-session')
        self.assertEqual(self.store._list(self.task,'runs')[0],before)
        receipt.unlink();receipt.symlink_to(self.folder/'systems/task.json')
        with self.assertRaisesRegex(AgentError,'symlink'):
            public_ack(self.root,self.task,'codex','native-session')

    def test_native_input_diagnostics_store_only_bounded_field_metadata(self):
        self.output('session-start')
        secret='SECRET_VALUE_DO_NOT_STORE'
        self.output('pre-tool',dict(self.data,tool_name='Bash',tool_input={'command':'echo '+secret,'description':secret,'unexpected':secret}))
        meta=self.registry.status()['last_pretool']
        self.assertEqual(meta['tool_name'],'Bash')
        self.assertEqual(meta['tool_input_keys'],['command','description'])
        self.assertNotIn(secret,self.registry.path.read_text())

    def test_unbound_root_bind_handoff_emits_boot_and_cli_only_reads_receipt(self):
        data=dict(self.data,cwd=str(self.root))
        initial=self.output('session-start',data)
        command=shlex.join(bind_argv(self.root,'codex','native-session',self.task))
        board=initial['hookSpecificOutput']['additionalContext']
        self.assertIn(json.dumps(command)[1:-1],board)
        self.assertEqual(self.store._list(self.task,'runs'),[])
        data.update(tool_name='Bash',tool_input={'command':command})
        result=self.output('pre-tool',data)
        context=result['hookSpecificOutput']['additionalContext']
        self.assertIn('CURRENT AUTHORITY AND REQUIREMENTS',context)
        self.assertIn('emitted, not acknowledged',context)
        self.assertIsNone(self.store._list(self.task,'runs')[0]['acknowledged_rev'])
        out,err=io.StringIO(),io.StringIO()
        with patch('native_activation.Store',side_effect=AssertionError('Store constructed')),patch('native_activation.NativeRegistry',side_effect=AssertionError('registry constructed')),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=main(['--root',str(self.root),'bind','--harness','codex','--session','native-session','--task',self.task])
        self.assertEqual(code,0,err.getvalue())
        self.assertEqual(json.loads(out.getvalue())['task'],self.task)
        self.assertIn('no capability granted',out.getvalue())
        ack=dict(data,tool_input={'command':shlex.join(ack_argv(self.root,'codex','native-session',self.task))})
        self.output('pre-tool',ack)
        self.assertEqual(public_ack(self.root,self.task,'codex','native-session')['acknowledged_rev'],1)

    def test_native_bind_rejects_cross_session_root_harness_helper_task_and_compound(self):
        data=dict(self.data,cwd=str(self.root));self.output('session-start',data)
        good=bind_argv(self.root,'codex','native-session',self.task)
        variants=[]
        other='Project/demo/T2-unregistered';(self.root/other).mkdir();(self.root/other/'0 start.md').write_text('other')
        self.store.enroll(other,'other','other',['other result'])
        for find,value in [('codex','claude-code'),('native-session','other-session'),(str(self.root.resolve()),str(self.root.parent/'otherrepo')),(str(self.root.resolve()/'systems/native_activation.py'),str(self.root.parent/'native_activation.py')),(self.task,other),(self.task,'../outside')]:
            command=list(good);command[command.index(find)]=value;variants.append(shlex.join(command))
        variants.extend([shlex.join(good)+'; true',shlex.join(good)+' && true',shlex.join(good)+' > out',shlex.join(good)+'\ntrue'])
        for command in variants:
            result=self.output('pre-tool',dict(data,tool_name='Bash',tool_input={'command':command}))
            self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny',command)
        self.assertEqual(self.registry.status()['sessions'],{})
        self.assertEqual(self.store._list(self.task,'runs'),[])

    def test_native_bind_preserves_existing_binding_and_explicit_task_conflicts(self):
        second='Project/demo/T2-registered';(self.root/second).mkdir();(self.root/second/'0 start.md').write_text('other')
        contract=self.store.enroll(second,'other','other',['other result'])
        self.registry.register(second,contract['owner_token'])
        self.registry.bind('codex','native-session',self.task)
        data=dict(self.data,cwd=str(self.root),tool_name='Bash',tool_input={'command':shlex.join(bind_argv(self.root,'codex','native-session',second))})
        self.assertEqual(self.output('pre-tool',data)['hookSpecificOutput']['permissionDecision'],'deny')
        self.assertEqual(self.registry.status()['sessions']['codex:native-session']['task'],self.task)
        with patch.dict(os.environ,{'CTX_TASK':second}):
            same=dict(data,tool_input={'command':shlex.join(bind_argv(self.root,'codex','native-session',self.task))})
            self.assertEqual(self.output('pre-tool',same)['hookSpecificOutput']['permissionDecision'],'deny')

    def test_public_bind_rejects_different_canonical_route_and_symlink(self):
        self.registry.bind('codex','native-session',self.task)
        record=next((self.root/'systems/agent-state/native bindings').glob('*.json'))
        original=record.read_text();data=json.loads(original);data['task_id']='task-wrong'
        record.write_text(json.dumps(data))
        with self.assertRaisesRegex(AgentError,'canonical'):
            public_bind(self.root,self.task,'codex','native-session')
        record.write_text(original)
        receipt=next((self.folder/'systems/native bind').glob('*.json'))
        receipt.unlink();receipt.symlink_to(record)
        with self.assertRaisesRegex(AgentError,'symlink'):
            public_bind(self.root,self.task,'codex','native-session')

    def test_source_search_and_git_mentions_are_not_native_helper_requests(self):
        self.output('session-start')
        for command in ['rg bind systems/native_activation.py', 'git add systems/native_activation.py; git commit -m bind', 'echo '+shlex.join(bind_argv(self.root,'codex','native-session',self.task))]:
            self.assertIsNone(self.output('pre-tool',dict(self.data,tool_name='Bash',tool_input={'command':command})))
        self.assertIsNone(self.store._list(self.task,'runs')[0]['acknowledged_rev'])

    def test_native_hook_never_executes_generic_run_wrapper(self):
        self.output('session-start')
        command=shlex.join([str(self.root/'systems/native_activation.py'),'--root',str(self.root),'run','--harness','codex','--session','native-session','--','echo','hello'])
        with patch('subprocess.run',side_effect=AssertionError('generic command executed')):
            self.assertIsNone(self.output('pre-tool',dict(self.data,tool_name='Bash',tool_input={'command':command})))

    def test_patch_targets_include_rename_and_ignore_arbitrary_reads(self):
        self.assertEqual(known_write_paths({'tool_name':'apply_patch','tool_input':{
            'command':'*** Update File: a.md\n*** Move to: b.md\n*** Delete File: c.md'}}),['a.md','c.md','b.md'])
        self.assertEqual(known_write_paths({'tool_name':'Bash','tool_input':{'command':'cat file'}}),[])
        self.assertEqual(known_write_paths({'tool_name':'Read','tool_input':{'file_path':'file'}}),[])

if __name__=='__main__':unittest.main()
