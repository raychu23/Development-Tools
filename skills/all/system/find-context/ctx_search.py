#!/usr/bin/env python3
"""ctx-search: find raymond's decisions, rules and task state in the curated CS Code files.

usage   python3 ctx_search.py "why is T3 blocked?"            top 5 sections, path:lines + text
        python3 ctx_search.py -k 3 --json "ledger states"     machine-readable
        python3 ctx_search.py --all "cifar accuracy"          also search the chat archive (codex/dense)
how     sqlite FTS5 (stdlib, no model, no server), porter stemming, bm25 weights path 2 · heading 3 · body 1
        6-line overlapping sections, long prose lines split into sentences, a hit overlapping a better one is dropped
eval    T5/T7 21 questions: 16/21 in top 5 at ~780 tokens/q, 7 ms      grep slices 17/21 at ~4.6K (different misses, union 19/21)
corpus  rules.md · AGENTS.md · CLAUDE.md · every 0 start / 1 takeaways / 2 insights / 3 workflow · context mgmt/me
        rebuilt in memory on every call (~0.5 MB, well under a second)      files on disk stay the only truth
"""
import argparse
import json
import os
import re
import sqlite3
import sys

ROOT = os.environ.get('CS_CODE_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
LEVEL = ('0 start.md', '1 takeaways.md', '2 insights.md', '3 workflow.md', '0-start.md', '1-takeaways.md')
TOP = ['rules.md', 'AGENTS.md', 'CLAUDE.md']
EXTRA = ['Context/context mgmt/me', 'rules']      # rules/ = on-demand parts of rules.md (T11 split)
ARCHIVE = ['Context/context mgmt/codex/dense']
SKIP = {'.git', 'Deleted', '.worktrees', 'node_modules', '__pycache__', 'full', '2-full', 'sources', 'assets',
        'code', 'worktrees', 'code-worktrees'}
STOP = set('a an the and or of to in on at for by with from is are was were be been do does did what which who why '
           'when where how my i me we our you your this that it its into about should can could would will one two '
           'than then there their they them not no'.split())
WINDOW, STEP = 6, 3      # lines per section, overlap 3: small enough to land on the answer line
MAX_DEPTH = 6            # level files sit ≤6 folders deep      stops the walk from crawling data trees (Work/transportation)


def corpus(root=ROOT, archive=False):
    files = [f for f in TOP if os.path.isfile(os.path.join(root, f))]
    extra = EXTRA + (ARCHIVE if archive else [])
    for d, ds, fs in os.walk(root):
        rel = os.path.relpath(d, root)
        depth = 0 if rel == '.' else rel.count(os.sep) + 1
        ds[:] = [x for x in ds if x not in SKIP and not x.startswith('.')] if depth < MAX_DEPTH else []
        for f in fs:
            p = os.path.normpath(os.path.join(rel, f))
            if (f in LEVEL or any(p.startswith(e + '/') for e in extra)) and p not in files:
                if f.endswith(('.md', '.txt')) and os.path.getsize(os.path.join(root, p)) <= 2_000_000:
                    files.append(p)
    return files


def heading_of(lines, n):
    """nearest line above n with less indentation (the cue this line belongs to), or a markdown heading"""
    indent = len(lines[n]) - len(lines[n].lstrip())
    for m in range(n - 1, -1, -1):
        s = lines[m]
        if s.lstrip().startswith('#'):
            return s.strip('# ').strip()
        if s.strip() and not s.strip().startswith(('```', '---')) and len(s) - len(s.lstrip()) < indent:
            return s.strip()
    return ''


def split_long(lines, limit=240):
    """long prose lines (AGENTS.md bullets) → sentence pieces, each keeping its original line number"""
    out = []
    for n, line in enumerate(lines, 1):
        if len(line) <= limit:
            out.append((n, line))
            continue
        indent = line[:len(line) - len(line.lstrip())]
        for piece in re.split(r'(?<=[.;:])\s+(?=[A-Z`(\-])', line.strip()):
            out.append((n, indent + piece))
    return out


def sections(text, window=None, step=None):
    window, step = window or WINDOW, step or STEP
    raw = text.splitlines()
    lines = split_long(raw)
    plain = [l for _, l in lines]
    for a in range(0, max(1, len(lines)), step):
        chunk = lines[a:a + window]
        body = '\n'.join(l for _, l in chunk).strip()
        if chunk and body.strip('`\n notes'):
            first = next((a + i for i, (_, l) in enumerate(chunk) if l.strip() and not l.strip().startswith('```')), a)
            top = plain[first].strip().strip('# ')
            head = heading_of(plain, first) or ('' if top == '---' else top)      # a top-level cue names itself
            yield chunk[0][0], chunk[-1][0], head, body


def build(files, root=ROOT, window=None, step=None):
    db = sqlite3.connect(':memory:')
    db.execute("create virtual table s using fts5(path, heading, body, file unindexed, start unindexed, "
               "stop unindexed, tokenize='porter unicode61')")
    rows = []
    for p in files:
        try:
            with open(os.path.join(root, p), encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            continue
        words = p.replace('/', ' ').replace('-', ' ')
        for a, b, h, body in sections(text, window, step):
            rows.append((words, h, body, p, a, b))
    db.executemany('insert into s values (?,?,?,?,?,?)', rows)
    return db


def terms(question):
    words = re.findall(r'[a-z0-9][a-z0-9.\-]*[a-z0-9]|[a-z0-9]', question.lower())
    return [w for w in dict.fromkeys(words) if w not in STOP and (len(w) > 2 or re.search(r'\d', w))]      # keep ids like t3, q4


def fts(ts):
    return ' OR '.join('"' + t.replace('"', '') + '"' for t in ts)


def search(question, k=5, archive=False, root=ROOT, db=None, weights=(2.0, 3.0, 1.0)):
    ts = terms(question)
    if not ts:
        return []
    db = db or build(corpus(root, archive), root)
    q = f'select file, start, stop, heading, body, bm25(s, {weights[0]}, {weights[1]}, {weights[2]}, 0, 0, 0) as r ' \
        f'from s where s match ? order by r limit ?'
    out, seen = [], set()
    for path, a, b, h, body, r in db.execute(q, (fts(ts), k * 4)):
        if any(p == path and a <= e and b >= st for p, st, e in seen):      # overlaps a section already returned
            continue
        seen.add((path, a, b))
        out.append({'path': path, 'lines': f'{a}-{b}', 'heading': h, 'text': body, 'score': round(-r, 3)})
        if len(out) >= k:
            break
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('question')
    ap.add_argument('-k', type=int, default=5)
    ap.add_argument('--all', action='store_true', help='also search the codex chat archive (dense)')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    hits = search(a.question, a.k, a.all)
    if a.json:
        print(json.dumps(hits, indent=1))
        return 0
    for h in hits:
        print(f"{h['path']}:{h['lines']}      {h['heading'][:80]}")
        for line in h['text'].splitlines():
            print('    ' + line)
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
