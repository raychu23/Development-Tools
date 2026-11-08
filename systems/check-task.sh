#!/bin/sh
# usage: sh systems/check-task.sh "<task dir>" [...]   → PASS/FAIL per rules.md §2 §3 §7 §10 standard      exit 1 on any FAIL
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 - "$ROOT" "$@" <<'PY'
import os, re, subprocess, sys
root, dirs = sys.argv[1], sys.argv[2:]
MAC = '$WORKSPACE'
need = ['goal', 'done-when', 'status', 'next', 'pinned', 'came from', 'links', 'harness']
okname = re.compile(r'^([0-3] (start|takeaways|insights|workflow)\.md|4 log.*|T\d+-a\d+-[a-z0-9-]+|[cod] [a-z0-9 -]+|systems)$')
bad = 0
def res(ok, what):
    global bad
    bad += (not ok)
    print(('PASS  ' if ok else 'FAIL  ') + what)
def blocks(text):
    return re.findall(r'```notes\n(.*?)```', text, re.S)
for d in dirs:
    d = os.path.abspath(d); rel = os.path.relpath(d, root)
    print(f'== {rel}')
    f0 = os.path.join(d, '0 start.md')
    res(os.path.isfile(f0), '0 start.md exists')
    if os.path.isfile(f0):
        b = blocks(open(f0, encoding='utf-8').read())
        pk = b[0].splitlines() if b else []
        res(0 < len(pk) <= 40, f'0 start packet ≤40 lines ({len(pk)})')
        cues = {l.strip().split('  ')[0].strip() for l in pk if l.startswith('    ') and not l.startswith('     ')}
        miss = [n for n in need if n not in cues]
        res(not miss, 'packet rows ' + ('all present' if not miss else 'missing: ' + ', '.join(miss)))
    for cur, subs, files in os.walk(d):
        subs[:] = [s for s in subs if not s.startswith('.')]
        for n in subs + [f for f in files if f != '.DS_Store']:
            if cur == d or os.path.basename(cur).startswith(('T', 'c ', 'o ', 'd ')):
                res(bool(okname.match(n)), f'name ok: {os.path.relpath(os.path.join(cur, n), d)}')
        for f in files:
            if not f.endswith('.md'): continue
            p = os.path.join(cur, f); t = open(p, encoding='utf-8').read(); r = os.path.relpath(p, d)
            res(t.count('```') % 2 == 0, f'fences balanced: {r}')
            nb = blocks(t); lines = [l for b in nb for l in b.splitlines()]
            res(bool(nb), f'notes style blocks: {r}')
            ind = [l for l in lines if (len(l) - len(l.lstrip(' '))) % 4 and l.strip()]
            res(not ind, f'indent multiple of 4: {r}' + (f' ({len(ind)} off)' if ind else ''))
            semi = [l for l in lines if ';' in re.sub(r'https?://\S+', '', l)]
            res(not semi, f'no semicolons: {r}' + (f' ({len(semi)})' if semi else ''))
            dead = []
            for m in re.finditer(r'$WORKSPACE/(?:[^\s)>]| (?! ))*?(?:\.(?:md|txt|py|sh)|/)(?=\s|$|[)>])', t):
                path = m.group(0).rstrip()
                if not os.path.exists(path.replace(MAC, root)): dead.append(path)
            res(not dead, f'links resolve: {r}' + (' → ' + ' | '.join(dead) if dead else ''))
    st = subprocess.run(['git', '-C', root, 'status', '--porcelain', '--untracked-files=all', '--', rel], capture_output=True, text=True).stdout.strip()
    res(not st, 'git: all files committed' + ('' if not st else ' → ' + st.replace('\n', ' | ')))
print('RESULT', 'PASS' if not bad else f'FAIL ({bad})')
sys.exit(1 if bad else 0)
PY
