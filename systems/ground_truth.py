"""ground_truth: raymond's ground truth in every CS Code session (T10, rules.md §5 complaint routing)

    core_block(root)        §1 core of Context/1 takeaways.md, capped, '' when missing or garbled
    detect(prompt)          (hit, cues) — complaint / correction / standing pref in raymond's own phrasing
    log(root, ...)          append 1 verbatim row to Context/systems/complaint inbox.jsonl (gitignored, folded nightly)

tuned on T8 harvest: 3,356 real codex prompts, 496 that held a complaint / correction / pref (T10 2 insights)
nothing here may raise into a hook: every public function swallows its own errors
"""
import json
import os
import re
import time
from pathlib import Path

TAKEAWAYS = 'Context/1 takeaways.md'
INBOX = 'Context/systems/complaint inbox.jsonl'
CORE_CAP = 3500
PROMPT_CAP = 8000

HEAD = ('Raymond\'s ground truth (CS Code/Context/1 takeaways.md §1, his own words rolled up from every past chat). '
        'Apply every line without being reminded. When he complains, corrects or states a preference: '
        'log it verbatim in that file\'s §3 inbox, fix it, say so in 1 line.\n'
        'Always-on core skill: docs-over-chat (CS Code/skills/all/system/docs-over-chat/SKILL.md): load it before your first reply '
        '(task folder + 0-4 files + routing every turn). Before a chat ends or hands off: run the reflect skill.\n')
REMINDER = ('This message may be a complaint, correction or standing preference from Raymond (matched: {cues}); '
            'it was auto-logged to CS Code/Context/systems/complaint inbox.jsonl. If it is one: fix it, add it to '
            'Context/1 takeaways.md §3 inbox if new, and say in 1 line what changed. If it is not, ignore this note.')

# cue → pattern      raymond writes lowercase, fast, with typos: keep patterns loose, anchor on intent words
CUES = [
    ('told-you',   r"\bi (?:already |just |literally )?(?:told|said|asked|mentioned)\b|\bi (?:ve|'ve|have) (?:told|said|asked)\b|\bas i said\b|\blike i said\b|\bive (?:told|said|asked)\b|\bi repeat\b"),
    ('again',      r"\b(?:again|still|keeps?|keep on|every time|evry time|alw(?:ays)?s?)\b.{0,60}\b(?:not|dont|don't|didnt|didn't|wrong|missing|forget|forgot|miss|ignor)"),
    ('why-you',    r"\bwhy (?:do|did|are|cant|can't|dont|don't|didnt|didn't|would|wont|won't|r) (?:you|u|they|codex|claude|the agents?)\b|\bwhy (?:does|is|did|didnt|didn't|cant|can't) (?:codex|claude|the agents?)\b"),
    ('frustration',r"\b(?:what the (?:hell|fuck|heck)|wtf|i hate|so annoying|annoy\w*|frustrat\w*|ridiculous|stupid|useless|fucking|fuck|bruh|ugh+)\b"),
    ('wrong',      r"\b(?:that'?s|thats|this is|its|it's|you(?:'re| are)?|ur) (?:wrong|not right|incorrect|not what i (?:asked|wanted|meant|said))\b|\bnot what i (?:asked|wanted|meant|said)\b|\bi meant\b(?! to ask)"),
    ('no-lead',    r"^\s*(?:no|nope|nah)[,.!:;\s]+(?!problem|worries|need|idea\b|rush|thanks|thank|worry)\S"),
    ('stop-dont',  r"^\s*(?:stop|quit) (?:being|just|throwing|doing|adding|changing|making|giving|using|writing|asking|it|that|this|with|the (?:lists?|fluff|filler))\b|^\s*(?:dont|don't|do not|never)\b(?!\s*mind)|\b(?:stop|quit) (?:being|just|throwing|doing|adding|changing|making|giving|using|writing|asking)\b"),
    ('standing',   r"\b(?:always|never|every (?:time|chat|agent|task|project))\b"),
    ('from-now',   r"\b(?:from now on|going forward|in (?:the )?future|make sure (?:you|u|to|all|every|each|that|theyre|they're|they)|remember (?:to|that)|remember:|each time (?:you|any)|every time (?:you|any))\b"),
    ('forgot',     r"\b(?:you|u) (?:forgot|missed|ignored|skipped|didnt|didn't|did not|never)\b|\bforgot to\b|\bnot follow\w*\b"),
    ('lost-me',    r"\bi (?:dont|don't|do not|still dont|still don't) (?:get|understand|see|follow)\b|\bconfus\w*|\boverwhelm\w*|\btoo (?:much|long|many|fancy|complicated|wordy)\b|\bway too\b|\ba mess\b|\bmessy\b|\bhard to (?:read|follow|see|scroll)\b|\bi (?:cant|can't|cannot) (?:read|see|find|tell|follow)\b"),
    ('thought-we', r"\bi thought (?:we|you|it)\b|\bdid(?:nt|n't| not) i (?:tell|say|ask)\b|\bdon'?t you see\b|\bnot (?:truly |really )?getting me\b|\b(?:you|u)(?:'re| are|re)? not (?:adding|following|listening|getting|doing|reading|using)\b|\bwe (?:already|just) (?:did|talked|discussed|defined|agreed)\b"),
    ('interrupt',  r"^\s*(?:no(?:no)+\w*|huh[?!]|hold on\b|wait(?:[,.!]| wait| what| no)|uh+\b(?!-)|well no\b|still[:!]|still (?:not|wrong|broken|the same)\b|nope\b)"),
    ('dislike',    r"\bi (?:dont|don't|do not|really dont|really don't) like\b|\bnot good\b|\bunacceptable\b|\bcome on\b|\bmake (?:shit|stuff|things) up\b|\bwhere (?:did|di) (?:you|u) (?:move|put|get)\b|\byou (?:cant|can't|cannot) (?:just|jsut)\b|\b(?:kinda |so |really )?tired of\b|\b(?:syst\w*|system|this|that) (?:is |was )?bad\b|\bare(?:nt|n't) (?:being|really|actually)\b|\b(?:u|you) sure\b|\bwhat exactly happened\b|\b(?:and|so|but) (?:now|bow) what\b"),
    ('broken',     r"\b(?:not working|doesnt work|doesn't work|didnt work|didn't work|still (?:broken|failing|cant|can't))\b"),
    ('pref',       r"\bi (?:want|prefer|need|like|dont want|don't want|do not want|dont like|don't like|hate)\b.{0,80}\b(?:you|u|it|agent|agents|docs?|files?|format|style|chat|notes|links?|paths?)\b"),
]
CUE_RE = [(name, re.compile(p, re.I | re.M)) for name, p in CUES]
NOT_FOR_HUMAN = re.compile(r'^\s*(?:\{|\[|```|/[a-z-]+\s*$)', re.I)
HARNESS_TAGS = ('in-app-browser-context', 'environment_context', 'recommended_plugins', 'user_instructions', 'INSTRUCTIONS',
                'skill', 'image', 'subagent_notification', 'turn_aborted', 'system-reminder', 'command-name', 'command-message',
                'command-args', 'local-command-stdout', 'local-command-stderr', 'task-notification', 'user-prompt-submit-hook',
                'artifact-view-context', 'agent-message')
# only known harness wrappers, each with a fixed name (linear scan per tag, no backreference)      text is capped before this runs
WRAPPERS = [re.compile(r'<' + re.escape(t) + r'\b[^>]{0,400}>.*?</' + re.escape(t) + r'>', re.S | re.I) for t in HARNESS_TAGS]
CODEX_REQUEST = re.compile(r'^## My request[^\n]{0,80}:[ \t]*\n?', re.M)
FILES_HEADER = re.compile(r'^# Files mentioned by the user:', re.M)
SECRETS = [re.compile(p) for p in (
    r'\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}', r'\bAKIA[0-9A-Z]{16}\b', r'\bgh[pousr]_[A-Za-z0-9]{20,}', r'\bxox[abposr]-[A-Za-z0-9-]{10,}',
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)',
    r'(?i)(?<![A-Za-z0-9])[A-Z0-9_]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[A-Z0-9_]*["\']?\s*[:=]\s*["\']?[^\s"\']{6,}',
    r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}', r'(?i)\bpassword is\s+\S{6,}',
    r'\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}', r'\bgithub_pat_[A-Za-z0-9_]{20,}', r'\bAIza[0-9A-Za-z_-]{35}', r'\bhf_[A-Za-z0-9]{30,}',
    r'\beyJ[\w-]+\.[\w-]+\.[\w-]+', r'(?<=://)[^/\s:@]+:[^@\s]+(?=@)',
)]


def redact(text):
    for rx in SECRETS:
        text = rx.sub('[redacted]', text)
    return text


def human_text(prompt):
    """strip harness wrappers so only what raymond typed is matched"""
    text = str(prompt or '')
    if text.lstrip().startswith('<agent-message'):   # subagent hand-back: never raymond, often too long to see its closing tag
        return ''
    m = None
    for m in CODEX_REQUEST.finditer(text):
        pass
    if m is not None:                       # codex attachment wrapper: only the typed request after the last header counts
        text = text[m.end():]
    elif FILES_HEADER.match(text):
        return ''
    text = text[:PROMPT_CAP]
    for rx in WRAPPERS:
        text = rx.sub('\n', text)
    return text.strip()


def detect(prompt):
    """(hit, cues) for one user prompt      empty / tool-ish / generated payloads → (False, [])"""
    try:
        text = human_text(prompt)
        if len(text) < 6 or NOT_FOR_HUMAN.match(text):
            return False, []
        cues = [name for name, rx in CUE_RE if rx.search(text)]
        strong = {'told-you', 'again', 'why-you', 'frustration', 'wrong', 'no-lead', 'forgot', 'lost-me', 'thought-we', 'stop-dont', 'interrupt', 'dislike', 'from-now'}
        hit = bool(strong & set(cues)) or len(cues) >= 2
        return hit, cues
    except Exception:
        return False, []


def changes_notice(root):
    """1 line when system changes piled up (systems/change-report)      '' otherwise      never raises"""
    try:
        st = json.loads((Path(root) / 'Context/systems/changes state.json').read_text())
        if st.get('piled'):
            return (f"\n{st['pending']} system changes are waiting for Raymond's review: CS Code/Context/changes to review.md "
                    '(mention it once in your first reply).')
    except Exception:
        pass
    return ''


def core_block(root, cap=CORE_CAP):
    """the ```notes block whose first line starts with '1 core'      '' if absent"""
    try:
        if cap < 400:
            return ''
        text = (Path(root) / TAKEAWAYS).read_text(encoding='utf-8')
        for block in re.findall(r'```notes\n(.*?)```', text, re.S):
            if block.lstrip().startswith('1 core'):
                block = block.rstrip()
                room = cap - len(HEAD) - 60
                if room < 200:
                    return ''
                if len(block) > room:
                    block = block[:room].rsplit('\n', 1)[0] + '\n    … cut, full list in Context/1 takeaways.md §1'
                return HEAD + block + changes_notice(root)
        return ''
    except Exception:
        return ''


def log(root, prompt, cues, harness='', session='', cwd=''):
    """append 1 jsonl row      returns the row or None      never raises"""
    try:
        path = Path(root) / INBOX
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'harness': harness, 'session': str(session or ''),
               'cwd': str(cwd or ''), 'cues': cues, 'prompt': redact(str(prompt)[:PROMPT_CAP]), 'folded': False}
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return row
    except Exception:
        return None


TURNS = 'Context/systems/turns.json'
REMIND_FROM, REMIND_CAP, REMIND_TOP = 10, 600, 4
REMIND_TAIL = '\nAlso: save this turn\'s facts to the task files before replying.'


def top_rules(root, n=REMIND_TOP):
    """§1 rules cited most in §3 inbox (raymond's repeat complaints)      [(num, text)]"""
    try:
        text = (Path(root) / TAKEAWAYS).read_text(encoding='utf-8')
        core, inbox = {}, ''
        for block in re.findall(r'```notes\n(.*?)```', text, re.S):
            if block.lstrip().startswith('1 core'):
                for line in block.splitlines()[1:]:
                    m = re.match(r'\s+(\d+)\s+(.*)', line)
                    if m:
                        core[int(m.group(1))] = re.split(r'\s{6}×', m.group(2))[0].strip()
            elif block.lstrip().startswith('3 inbox'):
                inbox = block
        hits = {}
        for grp in re.findall(r'§1 ((?:#\d+(?:[ ,+]|and|&)*)+)', inbox):
            for k in re.findall(r'#(\d+)', grp):
                hits[int(k)] = hits.get(int(k), 0) + 1
        ranked = sorted((k for k in hits if k in core), key=lambda k: -hits[k])[:n]
        return [(k, core[k]) for k in ranked]
    except Exception:
        return []


def turn_reminder(root, session):
    """count this session's turns      from turn 10 on: ≤600-char reminder of the most-complained rules      never raises
    why: rules in the 1st message fade as the chat grows (§0 belief 4, T18 research-rule-decay)"""
    try:
        if not session:
            return ''
        p = Path(root) / TURNS
        try:
            counts = json.loads(p.read_text())
        except (OSError, ValueError):
            counts = {}
        counts[session] = n = int(counts.get(session, 0)) + 1
        if len(counts) > 400:  # keep the file small: newest 200 sessions
            counts = dict(list(counts.items())[-200:])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix('.tmp%d' % os.getpid()); tmp.write_text(json.dumps(counts)); os.replace(tmp, p)
        if n < REMIND_FROM:
            return ''
        rules = top_rules(root)
        if not rules:
            return ''
        out = f'Turn {n} reminder (rules fade in long chats), Raymond\'s most-repeated complaints:'
        for k, t in rules:
            line = f'\n- §1 #{k} {t}'
            if len(out) + len(line) + len(REMIND_TAIL) > REMIND_CAP:
                break
            out += line
        return out + REMIND_TAIL
    except Exception:
        return ''


def on_prompt(root, data, harness=''):
    """hook helper: detect + log      returns reminder text or ''"""
    try:
        prompt = data.get('prompt') or data.get('user_prompt') or data.get('message') or ''
        hit, cues = detect(prompt)
        if not hit:
            return ''
        log(root, prompt, cues, harness, data.get('session_id'), data.get('cwd'))
        return REMINDER.format(cues=', '.join(cues))
    except Exception:
        return ''
