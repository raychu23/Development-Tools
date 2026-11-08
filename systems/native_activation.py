"""Native Codex/Claude wiring; local capabilities stay in a private operator registry.

Hook delivery is evidence of emission, never evidence of model reading. A model
must run ack after reading its emitted packet. This is coordination on one trusted
host, not an OS sandbox: shell write detection deliberately reports its limits.
"""
from __future__ import annotations
import argparse
import contextlib
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
sys.dont_write_bytecode = True  # read-only receipt helpers must not create import caches
from agent_core import Store, AgentError, utc, guard_path

DEFAULT_STATE = Path.home() / 'Library/Application Support/ctx-native'
EVENTS = {'session-start':'SessionStart', 'prompt':'UserPromptSubmit', 'pre-tool':'PreToolUse',
          'post-tool':'PostToolUse', 'pre-compact':'PreCompact', 'stop':'Stop', 'session-end':'SessionEnd'}


def private_json(path, data):
    path = Path(path)
    if path.is_symlink():
        raise AgentError('refusing symlink private file')
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.ctx-')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class NativeRegistry:
    def __init__(self, root, directory=None):
        self.root = Path(root).resolve()
        self.directory = Path(directory or os.environ.get('CTX_NATIVE_STATE') or DEFAULT_STATE)
        if self.directory.is_symlink():
            raise AgentError('refusing symlink private directory')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / 'registry.json'
        self.store = Store(self.root, commit=False)

    @contextlib.contextmanager
    def locked(self):
        lock = self.directory / 'registry.lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'r+') as f:
            os.chmod(lock, 0o600)
            fcntl.flock(f, fcntl.LOCK_EX)
            if self.path.is_symlink():
                raise AgentError('refusing symlink private registry')
            try:
                data = json.loads(self.path.read_text()) if self.path.exists() else {'version':1,'projects':{}}
            except (OSError, ValueError) as e:
                raise AgentError('private native registry unreadable; repair before managed work') from e
            if data.get('version') != 1 or not isinstance(data.get('projects'), dict):
                raise AgentError('unsupported private registry schema')
            project = data['projects'].setdefault(str(self.root), {'tasks':{},'sessions':{},'aliases':[]})
            yield project
            private_json(self.path, data)

    def register(self, task, owner_token, auto=True):
        task = self.store.relative(self.store.task_path(task))
        contract = self.store._owner(task, owner_token=owner_token)
        with self.locked() as p:
            p['tasks'][task] = {'owner_token':owner_token,'auto':bool(auto),'task_id':contract['task_id']}
        return {'task':task,'auto':bool(auto),'owner':contract['owner'],'credentials':'private'}

    def bind(self, harness, session, task, actor=None):
        if harness not in {'codex','claude-code'} or not session:
            raise AgentError('native harness and session required')
        task = self.store.relative(self.store.task_path(task))
        contract = self.store.contract(task)
        if os.environ.get('CTX_TASK') and self.store.relative(self.store.task_path(os.environ['CTX_TASK'])) != task:
            raise AgentError('native session binding conflicts with CTX_TASK')
        key = harness + ':' + session
        with self.locked() as p:
            previous = p['sessions'].get(key)
            if previous and previous['task'] != task:
                raise AgentError('session already bound to another task; release before rebinding')
            p['sessions'][key] = previous or {'task':task,'actor':actor or harness + ':' + session,
                                           'bound_at':utc(),'task_id':contract['task_id']}
            state=p['sessions'][key]
            record={'schema_version':1,'kind':'native-session-binding','root':str(self.root),
                    'task':task,'task_id':contract['task_id'],'harness':harness,'session_hash':session_hash(harness,session),
                    'actor':state['actor'],'bound_at':state['bound_at']}
            record['binding_id']=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
            self.store.transaction('native-session-bind',{
                str(self.root/'systems/agent-state/native bindings'/(session_hash(harness,session)+'.json')):record,
                str(self.store.task_path(task)/'systems/native bind'/(session_hash(harness,session)+'.json')):record})
        return {'task':task,'session':session,'harness':harness}

    def alias(self, path):
        path = str(Path(path).resolve())
        # Require the same Git common directory; aliases cannot route another project.
        def common(where):
            r = subprocess.run(['git','-C',str(where),'rev-parse','--path-format=absolute','--git-common-dir'],
                               capture_output=True,text=True)
            if r.returncode:
                raise AgentError('worktree alias requires a Git checkout')
            return Path(r.stdout.strip()).resolve()
        if common(path) != common(self.root):
            raise AgentError('worktree alias belongs to another repository')
        with self.locked() as p:
            p['aliases'] = sorted(set(p['aliases'] + [path]))
        return {'alias':path,'root':str(self.root)}

    def _select(self, p, harness, session, data):
        explicit = os.environ.get('CTX_TASK')
        key = harness + ':' + session if session else None
        bound = p['sessions'].get(key) if key else None
        if explicit:
            task = self.store.relative(self.store.task_path(explicit))
            if bound and bound['task'] != task:
                raise AgentError('CTX_TASK conflicts with native session binding')
            return task, key
        if bound:
            return bound['task'], key
        cwd = Path(data.get('cwd') or os.getcwd()).resolve()
        for base in sorted([str(self.root)] + p['aliases'], key=len, reverse=True):
            try:
                relative = cwd.relative_to(Path(base))
            except ValueError:
                continue
            if not relative.parts:
                return None, key
            target = self.root / relative
            matches = [t for t, g in p['tasks'].items() if g['auto'] and
                       (target == self.root/t or self.root/t in target.parents)]
            if matches:
                return max(matches, key=len), key
        return None, key

    def route(self, harness, data):
        sid = str(data.get('session_id') or '')
        with self.locked() as p:
            task, key = self._select(p, harness, sid, data)
            if task and key and key not in p['sessions']:
                p['sessions'][key] = {'task':task,'actor':harness + ':' + sid,'bound_at':utc(),
                                     'task_id':self.store.contract(task)['task_id']}
            return task, key

    def boot(self, harness, data, cap=9500):
        sid = str(data.get('session_id') or '')
        with self.locked() as p:
            task, key = self._select(p, harness, sid, data)
            if not task:
                cwd = Path(data.get('cwd') or os.getcwd()).resolve()
                scoped = cwd == Path.home().resolve() or any(cwd == Path(b) or Path(b) in cwd.parents
                          for b in [str(self.root)] + p['aliases'])
                if not scoped:
                    return {'text':'','ignored':True,'changed':False}
                return {'text':self.routing_board(harness, sid, registered=p['tasks']),'unbound':True,'changed':True}
            state = p['sessions'].setdefault(key, {'task':task,'actor':harness+':'+sid,
                        'bound_at':utc(),'task_id':self.store.contract(task)['task_id']}) if key else None
            warning = ''
            contract = self.store.contract(task)
            grant = p['tasks'].get(task)
            if contract['state'] == 'complete':
                warning = '\nTask already accepted complete: this boot is read-only; a new task or explicit requirement correction is required.'
                if state and state.get('token'):
                    self.store.release(task,state['run'],state['actor'],state['token'],reason='task accepted complete')
                    state.pop('token',None)
                    state.pop('run',None)
            if state and state.get('token'):
                record = self.store.read(self.store._record(task,'runs',state['run']))
                if record and (record['status'] != 'active' or record['expires_at'] <= time.time()):
                    state.pop('token',None)
                    state.pop('run',None)
            if state and not state.get('token') and grant and grant['auto'] and contract['state'] != 'complete':
                try:
                    run = self.store.claim(task, state['actor'], harness=harness, owner_token=grant['owner_token'])
                    state.update(run=run['run_id'], token=run['token'])
                except AgentError as e:
                    warning = '\nWriter grant unavailable: ' + str(e)
            pack = self.store.boot(task, max_chars=max(1, cap-1700))
            changed = not state or state.get('manifest',{}).get('manifest_hash') != pack['manifest']['manifest_hash']
            if state:
                state.update(manifest=pack['manifest'], emitted_at=utc(), delivery='emitted; model reading unverified')
            if not state or not state.get('token'):
                warning += '\nThis session has no writer grant; managed work remains read-only until an owner grants this active task.'
            command = shlex.join(ack_argv(self.root,harness,sid,task))
            wrapper = shlex.join([sys.executable, str(Path(__file__).resolve()), '--root', str(self.root),
                                 'run','--harness',harness,'--session',sid,'--'])
            head = ('CTX native task: ' + task + '\nRead this current boot before acting. Delivery is not acknowledgement. '
                    'After reading, explicitly run: ' + command + '\nUse this capability wrapper for managed ctx/ledger commands: '
                    + wrapper + ' <command>\nKnown file writes are checked by native hooks. Arbitrary shell/MCP writes are not a complete enforcement boundary.'
                    + warning + '\n')
            return {'text':head+pack['text'],'manifest':pack['manifest'],'changed':changed,'task':task}

    def routing_board(self, harness='codex', session='<native-session-id>', registered=None):
        rows = self.store.board()
        if registered is not None:
            rows=[r for r in rows if r['path'] in registered]
        lines = ['CTX native routing: this session has no task binding. No task was claimed.',
                 'Choose the relevant current packet before managed work; task-folder cwd routes automatically only for registered active tasks.',
                 'After reading the matching current packet, run its exact bind_command below. The trusted native hook records the route and injects the current boot. Read that boot before acknowledgement.',
                 'Current registered tasks:']
        rows.sort(key=lambda r:(not (registered or {}).get(r['path'],{}).get('auto',False),r.get('state')=='complete',r.get('path','')))
        for row in rows[:20]:
            brief={k:row.get(k) for k in ['path','owner','state','lease_health','queued_messages','needs_you']}
            brief['current_packet']=str(self.root/row['path']/'0 start.md')
            if session:
                brief['bind_command']=shlex.join(bind_argv(self.root,harness,session,row['path']))
            line=json.dumps(brief,sort_keys=True)
            if len('\n'.join(lines))+len(line)+1 > 4900:
                lines.append('Additional registered tasks omitted from this bounded board; use the relevant current packet to choose your task')
                break
            lines.append(line)
        return '\n'.join(lines)

    def acknowledge(self, harness, session, task=None):
        with self.locked() as p:
            state = p['sessions'].get(harness+':'+session)
            if not state or not state.get('token') or not state.get('manifest'):
                raise AgentError('no emitted packet and writer grant for this session')
            if task is not None and state['task'] != task:
                raise AgentError('native acknowledgement task conflicts with session binding')
            record = self.store.acknowledge(state['task'], state['run'], state['actor'], state['token'], state['manifest'],
                                           session_receipt='native:'+harness+':'+session+':explicit-read-ack')
            receipt={'schema_version':1,'task':state['task'],'task_id':record['task_id'],'run_id':state['run'],
                     'actor':state['actor'],'harness':harness,'session_hash':session_hash(harness,session),
                     'session_receipt':record['session_receipt'],'requirement_rev':record['requirement_rev'],
                     'acknowledged_rev':record['acknowledged_rev'],'boot_manifest_hash':record['boot_manifest_hash'],
                     'acknowledged_at':record['acknowledged_at'],'kind':'explicit agent read acknowledgement'}
            path=self.store.task_path(state['task'])/'systems/native ack'/ (session_hash(harness,session)+'.json')
            self.store.transaction('native-read-receipt',{str(path):receipt})
            state.update(acknowledged_at=utc(), acknowledged_manifest=state['manifest']['manifest_hash'])
            return {'task':state['task'],'run':state['run'],'acknowledged_rev':record['acknowledged_rev'],
                    'public_receipt':str(path),'receipt':'explicit agent read acknowledgement; not independent cognition proof'}

    def credentials(self, harness, session, renew=False):
        with self.locked() as p:
            state = p['sessions'].get(harness+':'+session)
            if not state or not state.get('token'):
                raise AgentError('native session has no writer grant')
            if self.store.contract(state['task'])['state'] == 'complete':
                raise AgentError('task already accepted complete; native work is read-only')
            if renew:
                self.store.renew(state['task'],state['run'],state['actor'],state['token'])
            else:
                self.store._run(state['task'],state['run'],state['actor'],state['token'],'write')
            return {'CTX_TASK':state['task'],'CTX_ACTOR':state['actor'],'CTX_RUN':state['run'],
                    'CTX_RUN_TOKEN':state['token']}

    def release(self, harness, session):
        with self.locked() as p:
            state = p['sessions'].get(harness+':'+session)
            if state and state.get('token'):
                self.store.release(state['task'],state['run'],state['actor'],state['token'],reason='native session ended')
                state.pop('token',None)
                state.pop('run',None)
                state.update(ended_at=utc())
        return {'session':session,'released':True}

    def status(self):
        with self.locked() as p:
            return {'root':str(self.root),'tasks':{k:{'auto':v['auto'],'task_id':v['task_id']} for k,v in p['tasks'].items()},
                    'sessions':{k:{n:v[n] for n in ['task','actor','run','emitted_at','delivery','acknowledged_at','ended_at'] if n in v}
                                for k,v in p['sessions'].items()},'aliases':p['aliases'],'last_pretool':p.get('last_pretool')}


def session_hash(harness, session):
    return hashlib.sha256((harness+':'+session).encode()).hexdigest()


def ack_argv(root,harness,session,task):
    return [sys.executable,str(Path(root).resolve()/'systems/native_activation.py'),'--root',str(Path(root).resolve()),
            'ack','--harness',harness,'--session',session,'--task',task]


def bind_argv(root,harness,session,task):
    return [sys.executable,str(Path(root).resolve()/'systems/native_activation.py'),'--root',str(Path(root).resolve()),
            'bind','--harness',harness,'--session',session,'--task',task]


def public_bind(root,task,harness,session,actor=None):
    """Verify tokenless canonical routing records with no private or lock access."""
    root=Path(root).resolve()
    relative=Path(task)
    if relative.is_absolute() or not relative.parts or any(p in {'.','..','.git'} for p in relative.parts):
        raise AgentError('public binding task must be a canonical relative task path')
    def read(part):
        path=root/part
        if any(p.is_symlink() for p in [path,*path.parents] if root in [p,*p.parents]):
            raise AgentError('symlink public binding source refused')
        if root not in path.resolve().parents:
            raise AgentError('public binding source escapes workspace')
        if not path.exists():return None
        if path.stat().st_size>65536:raise AgentError('public binding source exceeds bound')
        try:return json.loads(path.read_text())
        except (OSError,ValueError) as e:raise AgentError('public binding source unreadable') from e
    name=session_hash(harness,session)+'.json'
    receipt=read(relative/'systems/native bind'/name)
    if receipt is None:return None
    route=read(Path('systems/agent-state/native bindings')/name)
    contract=read(relative/'systems/task.json')
    fields={'schema_version','kind','root','task','task_id','harness','session_hash','actor','bound_at','binding_id'}
    if (not isinstance(receipt,dict) or set(receipt)!=fields or receipt!=route or not isinstance(contract,dict)
        or receipt.get('schema_version')!=1 or contract.get('schema_version')!=1
        or receipt.get('kind')!='native-session-binding' or receipt.get('root')!=str(root)
        or receipt.get('task')!=str(relative) or contract.get('location')!=str(relative)
        or not isinstance(contract.get('task_id'),str) or not re.fullmatch(r'task-[a-f0-9]{32}',contract['task_id'])
        or receipt.get('task_id')!=contract.get('task_id') or receipt.get('harness')!=harness
        or receipt.get('session_hash')!=session_hash(harness,session)
        or not isinstance(receipt.get('actor'),str) or not receipt.get('actor')
        or actor is not None and actor!=receipt.get('actor')
        or not isinstance(receipt.get('bound_at'),str) or not receipt.get('bound_at')):
        raise AgentError('public binding receipt does not match canonical native route')
    material={k:v for k,v in receipt.items() if k!='binding_id'}
    if receipt['binding_id']!=hashlib.sha256(json.dumps(material,sort_keys=True).encode()).hexdigest():
        raise AgentError('public binding receipt identity is invalid')
    return {'task':str(relative),'harness':harness,'session':session,
            'receipt':'verified public native routing record; boot emission is not read acknowledgement and no capability granted'}


def public_ack(root,task,harness,session):
    """Read-only verification: a public receipt never issues or carries a capability.

    Do not instantiate Store here: its filesystem detection/lock machinery can
    mutate protected locations even before an actual engine operation is requested.
    """
    root=Path(root).resolve()
    task_path=Path(task)
    if task_path.is_absolute() or not task_path.parts or any(p in {'.','..','.git'} for p in task_path.parts):
        raise AgentError('public acknowledgement task must be a canonical relative task path')
    folder=root/task_path
    def read(relative):
        path=folder/relative
        if any(p.is_symlink() for p in [path,*path.parents] if p != root.parent and root in [p,*p.parents]):
            raise AgentError('symlink public acknowledgement source refused')
        if root not in path.resolve().parents:
            raise AgentError('public acknowledgement source escapes workspace')
        if not path.exists():return None
        if path.stat().st_size > 65536:raise AgentError('public acknowledgement source exceeds bound')
        try:return json.loads(path.read_text())
        except (OSError,ValueError) as e:raise AgentError('public acknowledgement source unreadable') from e
    receipt=read(Path('systems/native ack')/(session_hash(harness,session)+'.json'))
    if receipt is None:return None
    if not isinstance(receipt,dict):raise AgentError('public acknowledgement receipt must be an object')
    run_id=receipt.get('run_id','')
    if not isinstance(run_id,str) or not re.fullmatch(r'run-[a-f0-9]{32}',run_id):
        raise AgentError('invalid public acknowledgement run id')
    contract=read(Path('systems/task.json'));run=read(Path('systems/runs')/(run_id+'.json'))
    expected='native:'+harness+':'+session+':explicit-read-ack'
    revision=contract.get('requirement_rev') if isinstance(contract,dict) else None
    expiry=run.get('expires_at') if isinstance(run,dict) else None
    if (not isinstance(run,dict) or not isinstance(contract,dict) or contract.get('state')=='complete'
        or receipt.get('schema_version')!=1 or contract.get('schema_version')!=1 or run.get('schema_version')!=1
        or not isinstance(revision,int) or isinstance(revision,bool) or revision < 1
        or not isinstance(expiry,(int,float)) or isinstance(expiry,bool) or not math.isfinite(expiry) or expiry <= time.time()
        or run.get('status')!='active' or run.get('run_id')!=run_id
        or run.get('task_id')!=contract.get('task_id') or receipt.get('task_id')!=contract.get('task_id')
        or receipt.get('task')!=str(task_path) or contract.get('location')!=str(task_path)
        or receipt.get('harness')!=harness or receipt.get('session_hash')!=session_hash(harness,session)
        or receipt.get('session_receipt')!=expected or run.get('session_receipt')!=expected
        or receipt.get('requirement_rev')!=revision or run.get('requirement_rev')!=revision
        or receipt.get('acknowledged_rev')!=revision or run.get('acknowledged_rev')!=revision
        or receipt.get('actor')!=run.get('actor') or receipt.get('acknowledged_at')!=run.get('acknowledged_at')
        or not isinstance(receipt.get('boot_manifest_hash'),str)
        or not re.fullmatch(r'[a-f0-9]{64}',receipt['boot_manifest_hash'])
        or receipt['boot_manifest_hash']!=run.get('boot_manifest_hash')):
        raise AgentError('public acknowledgement is stale or does not match active canonical run')
    return {'task':str(task_path),'run':run_id,'acknowledged_rev':revision,
            'receipt':'verified public record of explicit native read acknowledgement; no capability granted'}


def native_request(registry,harness,data):
    """Recognize exactly the emitted helper argv; never execute user shell text."""
    args=data.get('tool_input')
    if data.get('tool_name')!='Bash' or not isinstance(args,dict) or not isinstance(args.get('command'),str):
        return None
    command=args['command']
    if 'native_activation.py' not in command or not re.search(r'\b(?:ack|bind)\b',command):return None
    try:
        lexer=shlex.shlex(command,posix=True,punctuation_chars=';&|()<>')
        lexer.whitespace_split=True;lexer.commenters=''
        argv=list(lexer)
    except ValueError as e:
        raise AgentError('native helper command cannot be parsed safely') from e
    # A source search, echo or git command mentioning the helper is not an invocation.
    # Recognize actual helper invocations in shell segments, then reject every compound form.
    segments=[[]]
    for token in argv:
        if token and all(c in ';&|()<>' for c in token):segments.append([])
        else:segments[-1].append(token)
    candidate=False
    for segment in segments:
        words=list(segment)
        while words and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=',words[0]):words.pop(0)
        if words[:1]==['env']:words.pop(0)
        script=None
        if words and Path(words[0]).name=='native_activation.py':script=0
        elif len(words)>1 and re.fullmatch(r'python(?:[0-9]+(?:\.[0-9]+)*)?',Path(words[0]).name) and Path(words[1]).name=='native_activation.py':script=1
        if script is not None and any(w in {'ack','bind'} for w in words[script+1:]):candidate=True
    if not candidate:return None
    if len(command)>4096 or '\n' in command or '\r' in command or '`' in command or '$' in command:
        raise AgentError('native helper requires the exact single emitted command')
    if any(t and all(c in ';&|()<>' for c in t) for t in argv):
        raise AgentError('compound native acknowledgement command refused')
    session=str(data.get('session_id') or '')
    if not session:raise AgentError('native acknowledgement event has no session identity')
    if len(argv)==11 and argv[4]=='bind':
        task=argv[10]
        if argv!=bind_argv(registry.root,harness,session,task):
            raise AgentError('native binding must match event session, harness, root and configured helper')
        with registry.locked() as p:
            if task not in p['tasks'] or p['tasks'][task]['task_id'] != registry.store.contract(task)['task_id']:
                raise AgentError('native binding target is not a registered workspace task')
        registry.bind(harness,session,task)
        pack=registry.boot(harness,data)
        return {'operation':'bind','text':'CTX native session binding recorded by trusted hook. This boot is emitted, not acknowledged.\n'+pack['text']}
    task,_=registry.route(harness,data)
    if not task or argv!=ack_argv(registry.root,harness,session,task):
        raise AgentError('native acknowledgement must match current session, harness, root, task and configured helper')
    return registry.acknowledge(harness,session)


def record_pretool_shape(registry,harness,data):
    """Bounded field metadata only, never command text, argument values or tokens."""
    cwd=Path(data.get('cwd') or os.getcwd()).resolve()
    with registry.locked() as p:
        bound=p['sessions'].get(harness+':'+str(data.get('session_id') or ''))
        if not bound and cwd!=registry.root and registry.root not in cwd.parents:
            return
        args=data.get('tool_input')
        allowed={'command','cmd','code','input','input_string','description','args','cwd','workdir','yield_time_ms','timeout_ms',
                 'file_path','path','patch','edits'}
        tool=str(data.get('tool_name') or '')
        p['last_pretool']={'at':utc(),'harness':harness,'session_hash':session_hash(harness,str(data.get('session_id') or '')),
            'tool_name':re.sub(r'[^A-Za-z0-9_.-]','?',tool)[:80],
            'tool_input_type':type(args).__name__,'tool_input_keys':sorted(k for k in args if k in allowed)[:20] if isinstance(args,dict) else [],
            'tool_input_key_count':len(args) if isinstance(args,dict) else 0}


def known_write_paths(data):
    """Only exact native file targets; no claim of arbitrary shell interpretation."""
    tool = str(data.get('tool_name') or '')
    args = data.get('tool_input') or {}
    if not isinstance(args, dict):
        args = {'command':args} if isinstance(args,str) else {}
    if tool in {'Write','Edit','MultiEdit','write_file','edit_file'}:
        return [args.get('file_path') or args.get('path')] if args.get('file_path') or args.get('path') else []
    if tool in {'apply_patch','functions.apply_patch'}:
        patch = args.get('command') or args.get('input') or args.get('patch') or ''
        paths = re.findall(r'^\*\*\* (?:Add|Update|Delete) File: (.+)$',patch,re.M)
        paths += re.findall(r'^\*\*\* Move to: (.+)$',patch,re.M)
        return paths
    return []


def _ground_truth():
    """T10 module, imported lazily so a broken ground_truth.py can never take the native hooks down"""
    try:
        import ground_truth
        return ground_truth
    except Exception:
        return None


def hook_output(event, text=None, deny=None):
    out = {'hookEventName':EVENTS[event]}
    if text:
        out['additionalContext'] = text
    if deny:
        out.update(permissionDecision='deny',permissionDecisionReason=deny)
    return {'hookSpecificOutput':out}


def handle_hook(registry, harness, event, data):
    if event in {'session-start','prompt'}:
        # T10: raymond's ground truth rides on the same scope check as the boot pack (CS Code cwd or home, never elsewhere)
        # the boot pack keeps its own budget (same cap both events → manifest hash stable) and priority; the core fills what is left
        pack = registry.boot(harness,data)
        if pack.get('ignored'):
            return None
        gt = _ground_truth()
        if event=='session-start':
            core = gt.core_block(registry.root, cap=9500-len(pack['text'])-2) if gt else ''
            parts = [core, pack['text']]
        else:
            parts = [pack['text'] if pack['changed'] else '', gt.on_prompt(registry.root,data,harness) if gt else '',
                     gt.turn_reminder(registry.root,str(data.get('session_id') or '')) if gt else '']
        text = '\n\n'.join(p for p in parts if p)
        return hook_output(event,text) if text else None
    if event == 'session-end':
        registry.release(harness,str(data.get('session_id') or ''))
        return None
    if event == 'pre-compact':
        task, _ = registry.route(harness,data)
        return {'systemMessage':'CTX checkpoint needed: flush observed progress and unfinished work to '+task+'/0 start.md before compaction; no progress was invented.'} if task else None
    if event == 'pre-tool':
        record_pretool_shape(registry,harness,data)
        try:
            receipt=native_request(registry,harness,data)
        except AgentError as e:
            return hook_output(event,deny='CTX native helper refused: '+str(e))
        if receipt and receipt.get('operation')=='bind':
            return hook_output(event,text=receipt['text'])
        if receipt:
            return hook_output(event,text='CTX explicit read acknowledgement recorded by trusted native hook. The helper may read its tokenless public receipt. No command was executed by the hook.')
        paths = known_write_paths(data)
        if not paths:
            return None
        cwd = Path(data.get('cwd') or os.getcwd()).resolve()
        # Resolve any worktree alias to the corresponding canonical coordinate.
        with registry.locked() as p:
            bases = sorted([str(registry.root)] + p['aliases'],key=len,reverse=True)
        targets = []
        for path in paths:
            target = (cwd/path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
            for base in bases:
                try:
                    target = registry.root / target.relative_to(base)
                    break
                except ValueError:
                    pass
            if registry.root == target or registry.root in target.parents:
                targets.append(target)
        if not targets:
            return None
        tasks = registry.store.tasks()
        managed = [t for t in targets if any(registry.store._scope(t,c['allowed_paths']) for c in tasks)]
        if not managed:
            return None
        try:
            creds = registry.credentials(harness,str(data.get('session_id') or ''),renew=True)
            old = {k:os.environ.get(k) for k in creds}
            try:
                os.environ.update(creds)
                for path in managed:
                    guard_path(registry.root,path)
            finally:
                for k,v in old.items():
                    if v is None: os.environ.pop(k,None)
                    else: os.environ[k]=v
        except AgentError as e:
            return hook_output(event, deny='CTX managed write denied: '+str(e)+'. Read current boot then run the explicit native ack command; do not bypass the task scope.')
    if event in {'post-tool','stop'}:
        task, _ = registry.route(harness,data)
        if task:
            try:
                registry.credentials(harness,str(data.get('session_id') or ''),renew=True)
            except AgentError:
                pass  # acknowledgement and fresh packet remain required; reads stay available
    return None


def git_coordinate(root, path):
    """Canonical coordinate for a verified same-Git worktree, without the registry."""
    root, path = Path(root).resolve(), Path(path).resolve()
    if path == root or root in path.parents:
        return path
    existing = path if path.is_dir() else path.parent
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    def query(where, flag):
        result = subprocess.run(['git','-C',str(where),'rev-parse',flag],capture_output=True,text=True,timeout=3)
        return Path(result.stdout.strip()).resolve() if result.returncode == 0 and result.stdout.strip() else None
    try:
        # Request absolute common dirs because Git usually returns a relative path.
        def absolute_common(where):
            result = subprocess.run(['git','-C',str(where),'rev-parse','--path-format=absolute','--git-common-dir'],
                                    capture_output=True,text=True,timeout=3)
            return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None
        root_common=absolute_common(root)
        if not root_common or root_common != absolute_common(existing):
            return None
        top = query(existing,'--show-toplevel')
        return root / path.relative_to(top) if top else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def failure_scope(root, data):
    """A corrupt private registry must still protect known managed alias writes."""
    cwd = Path(data.get('cwd') or os.getcwd()).resolve()
    relevant = cwd == Path.home().resolve() or git_coordinate(root,cwd) is not None
    writes = []
    for target in known_write_paths(data):
        path = Path(target)
        mapped = git_coordinate(root,(cwd/path).resolve() if not path.is_absolute() else path)
        if mapped is not None:
            writes.append(mapped)
    managed = False
    if writes:
        try:
            store=Store(root,commit=False)
            tasks=store.tasks()
            managed=any(store._scope(t,c['allowed_paths']) for t in writes for c in tasks)
            managed=managed or any(store._scope(t,[c['path']]) for t in writes for c in store.corrupt_tasks)
        except Exception:
            managed=True  # known writes in this same repository cannot inspect authority
    return relevant, managed


def hook_main(argv):
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--harness',choices=['codex','claude-code'],required=True)
    parser.add_argument('event',choices=list(EVENTS))
    args=parser.parse_args(argv)
    try:
        data=json.loads(sys.stdin.read() or '{}')
        if not isinstance(data,dict): raise AgentError('native hook input must be an object')
        result=handle_hook(NativeRegistry(args.root),args.harness,args.event,data)
        if result: print(json.dumps(result))
        return 0
    except Exception as e:
        # Do not echo raw input or credentials in diagnostics.
        message='CTX native hook unavailable: '+type(e).__name__+'; inspect private runtime and current task before managed writes'
        relevant, managed = failure_scope(args.root,data) if isinstance(locals().get('data'),dict) else (False,False)
        if relevant or managed: print(message,file=sys.stderr)
        if args.event=='pre-tool' and managed:
            print(json.dumps(hook_output(args.event,deny=message)))
        elif args.event in {'session-start','prompt'} and relevant:
            print(json.dumps(hook_output(args.event,message)))
        return 0


def merged_hooks(config, root, harness, ai_memory=None, archive=None):
    result=copy.deepcopy(config)
    hooks=result.setdefault('hooks',{})
    if not isinstance(hooks,dict): raise AgentError('native hooks config must be an object')
    for event,name in EVENTS.items():
        groups=hooks.setdefault(name,[])
        if not isinstance(groups,list): raise AgentError('native hook groups must be arrays')
        command=shlex.join([sys.executable,str(Path(root)/'systems/ctx-hook'),'--native','--root',str(root),'--harness',harness,event])
        # Remove only our previously named handler, keeping every other hook/group.
        for group in groups:
            group['hooks']=[h for h in group.get('hooks',[]) if not
                            (h.get('type')=='command' and 'systems/ctx-hook' in h.get('command','') and '--native' in h.get('command','')
                             and ('--harness '+harness) in h.get('command',''))]
        handler={'type':'command','command':command,'timeout':3 if event=='session-end' else 15}
        if harness=='codex' and event not in {'pre-compact','stop','session-end'}:
            handler['additionalContextLimit']=9500
        groups.append({'hooks':[handler]})
        hooks[name]=[g for g in groups if g.get('hooks')]
        extras=[]
        if ai_memory:
            extras.append(shlex.join([str(ai_memory),'--data-dir',str(Path.home()/'Library/Application Support/ai-memory'),
                                     'hook','--event',{'prompt':'user-prompt-submit','pre-tool':'pre-tool-use','post-tool':'post-tool-use'}.get(event,event),'--agent',harness,'--server-url','http://127.0.0.1:49374']))
        if archive and event in {'pre-compact','stop','session-end'}:
            extras.append(shlex.join([str(archive[0]),str(archive[1]),'hook']))
        existing={h.get('command') for g in hooks[name] for h in g.get('hooks',[])}
        for extra in extras:
            if extra not in existing:
                hooks[name].append({'hooks':[{'type':'command','command':extra,'timeout':3 if event=='session-end' else 15}]})
    return result


def install(path,root,harness,ai_memory=None,archive=None):
    path=Path(path)
    if path.is_symlink(): raise AgentError('refusing symlink native settings')
    try: current=json.loads(path.read_text()) if path.exists() else {}
    except ValueError as e: raise AgentError('native settings malformed; preserved unchanged') from e
    updated=merged_hooks(current,root,harness,ai_memory,archive)
    path.parent.mkdir(parents=True,exist_ok=True)
    changed=current!=updated
    if changed: private_json(path,updated)
    return {'path':str(path),'changed':changed,'harness':harness,
            'trust':'Codex requires review of new hook definitions in /hooks; installer never forges trust' if harness=='codex' else 'Native settings load on next session; verify actual events'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default=str(Path(__file__).resolve().parent.parent))
    p.add_argument('--state-dir')
    sub=p.add_subparsers(dest='command',required=True)
    x=sub.add_parser('register');x.add_argument('--task',required=True);x.add_argument('--no-auto',action='store_true')
    for name in ['bind','ack','run','release']:
        x=sub.add_parser(name);x.add_argument('--harness',required=True,choices=['codex','claude-code']);x.add_argument('--session',required=True)
        if name=='bind':x.add_argument('--task',required=True);x.add_argument('--actor')
        if name=='ack':x.add_argument('--task')
        if name=='run':x.add_argument('argv',nargs=argparse.REMAINDER)
    x=sub.add_parser('alias');x.add_argument('--path',required=True)
    sub.add_parser('status')
    x=sub.add_parser('install');x.add_argument('--harness',required=True,choices=['codex','claude-code']);x.add_argument('--path',required=True)
    x.add_argument('--ai-memory');x.add_argument('--archive-python');x.add_argument('--archive-script')
    a=p.parse_args(argv)
    try:
        if a.command=='install':
            result=install(a.path,a.root,a.harness,a.ai_memory,[a.archive_python,a.archive_script] if a.archive_python and a.archive_script else None)
        elif a.command=='bind':
            result=public_bind(a.root,a.task,a.harness,a.session,actor=a.actor)
            if result is None:
                result=NativeRegistry(a.root,a.state_dir).bind(a.harness,a.session,a.task,a.actor)
        elif a.command=='ack':
            result=public_ack(a.root,a.task,a.harness,a.session) if a.task else None
            if result is None:
                result=NativeRegistry(a.root,a.state_dir).acknowledge(a.harness,a.session,task=a.task)
        else:
            r=NativeRegistry(a.root,a.state_dir)
            if a.command=='register':result=r.register(a.task,sys.stdin.read().strip(),not a.no_auto)
            elif a.command=='alias':result=r.alias(a.path)
            elif a.command=='release':result=r.release(a.harness,a.session)
            elif a.command=='status':result=r.status()
            elif a.command=='run':
                command=a.argv[1:] if a.argv[:1]==['--'] else a.argv
                if not command:raise AgentError('run requires a command after --')
                env=dict(os.environ,**r.credentials(a.harness,a.session,renew=True))
                return subprocess.run(command,env=env).returncode
        print(json.dumps(result,indent=2))
        return 0
    except AgentError as e:
        print('ctx native: '+str(e),file=sys.stderr)
        return 2

if __name__=='__main__':sys.exit(main())
