"""Apply the one design source (../assets/doc-style.css) to CS Code doc.html files.

  python3 doc_style.py                 every doc.html under CS Code (skips skill assets, worktrees, node_modules)
  python3 doc_style.py <file.html> …   only those

From a render script, after writing doc.html:
  sys.path.insert(0, "$WORKSPACE/skills/all/system/docs-over-chat/scripts"); import doc_style; doc_style.apply(path)

Idempotent: replaces the <style data-doc-style> block if present, else inserts it last in <head>
(before </head>, or right after the page's last </style>), so the shared rules win.
"""
import html
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
CSS = HERE.parent / "assets" / "doc-style.css"
CS = pathlib.Path(os.environ.get("WORKSPACE") or pathlib.Path(__file__).resolve().parents[5])
SKIP = ("/.git/", "/.worktrees/", "/node_modules/", "/skills/", "-worktrees/")
BLOCK = re.compile(r"<style data-doc-style>.*?</style>", re.S)
RECENT = re.compile(r"<div data-doc-recent>.*?</div>", re.S)      # inserted with no extra whitespace → removing it restores the page exactly
RECENT_N = 5


def recent(folder) -> str:
    """'latest' strip: uncommitted files + last commits touching this doc's folder      raymond 2026-10-17: unclear what was added recently"""
    try:
        run = lambda *a: subprocess.run(["git", "-C", str(folder), *a], capture_output=True, text=True, timeout=10).stdout
        dirty = [l[3:].strip('"') for l in run("status", "--porcelain", "--", ".").splitlines() if l[3:].strip('"').split("/")[-1] != "doc.html"]
        rows = []
        if dirty:
            rows.append(f"<li><b>now</b> unsaved: {html.escape(', '.join(pathlib.Path(d).name for d in dirty[:4]))}{' …' if len(dirty) > 4 else ''}</li>")
        log = run("log", "-20", "--format=%cd%x1f%s", "--date=format:%m-%d %H:%M", "--", ".").splitlines()
        for line in [l for l in log if "\x1fledger " not in l][:RECENT_N]:  # ledger state moves = noise here
            d, _, subj = line.partition("\x1f")
            rows.append(f"<li><b>{html.escape(d)}</b> {html.escape(subj[:140])}</li>")
        if not rows:
            return ""
        return "<div data-doc-recent><span>latest</span><ul>" + "".join(rows) + "</ul></div>"
    except Exception:
        return ""


FOLD_JS = """<script data-doc-fold>
document.querySelectorAll('[data-go]').forEach(a=>a.onclick=ev=>{ev.preventDefault();const b=document.querySelector('nav [data-tab="'+a.dataset.go+'"]');if(b)b.click()});
document.querySelectorAll('[data-open]').forEach(a=>a.onclick=ev=>{ev.preventDefault();const t=document.getElementById(a.dataset.open);if(!t)return;for(let d=t;d;d=d.parentElement){if(d.tagName==='DETAILS')d.open=true}t.scrollIntoView()});
document.querySelectorAll('[data-fold]').forEach(b=>b.onclick=()=>document.querySelectorAll(b.dataset.scope||'details.fold').forEach(d=>d.open=b.dataset.fold==='open'));
document.querySelectorAll('input[data-filter]').forEach(i=>i.oninput=()=>{const sec=i.closest('section')||document;const q=i.value.toLowerCase();sec.querySelectorAll('[data-q]').forEach(r=>r.hidden=!!q&&!r.dataset.q.includes(q));sec.querySelectorAll('details.fold').forEach(d=>{const any=d.querySelector('[data-q]:not([hidden])');if(d.querySelector('[data-q]')){d.hidden=!!q&&!any;if(q&&any)d.open=true}})});
</script>"""
USES_FOLD = re.compile(r'data-fold|data-open|data-go|class="fold|data-filter')
FOLD = re.compile(r"<script data-doc-fold>.*?</script>", re.S)
LIMIT = 7        # principle: a human cannot hold 7+ things in their head -> never a list or table longer than this without folds


def core(lines) -> str:
    """The core block: <=7 lines (html allowed: caller escapes), first line starts with 'core'. Counts should link to sections (data-go / data-open)."""
    lines = list(lines)
    assert 1 <= len(lines) <= LIMIT, f"core block has {len(lines)} lines, limit {LIMIT}"
    return '<pre class="core">' + "\n".join(lines) + "</pre>"


def fold(summary, body, open=False, id=None, cls="") -> str:
    """One folding section. summary/body are html. Nest folds freely; keep each body <=7 items (fold_list)."""
    head = f'<details class="fold {cls}"'.replace(' "', '"') if not cls else f'<details class="fold {cls}"'
    return (head + (f' id="{id}"' if id else "") + (" open" if open else "") + ">"
            f'<summary>{summary}</summary><div class="fold-body">{body}</div></details>')


def fold_list(rows, label, size=LIMIT, open_first=False) -> str:
    """rows = html strings. <=size rows are shown as is; more are cut into folds of `size` (the 7-things rule)."""
    rows = list(rows)
    if len(rows) <= size:
        return "".join(rows)
    out = []
    for n in range(0, len(rows), size):
        part = rows[n:n + size]
        out.append(fold(f"{label} {n + 1}-{n + len(part)} <span class='sub'>of {len(rows)}</span>", "".join(part), open=open_first and n == 0, cls="chunk"))
    return "".join(out)


def fold_bar(scope="details.fold") -> str:
    return f'<p class="fold-bar"><button data-fold="open" data-scope="{scope}">Expand all</button><button data-fold="close" data-scope="{scope}">Collapse all</button></p>'


def audit(path) -> dict:
    """How well does a page follow the structure rules? core block, folds, longest table / list."""
    t = pathlib.Path(path).read_text(errors="replace")
    rows = [len(re.findall(r"<tr[\s>]", x)) - 1 for x in re.findall(r"<table.*?</table>", t, re.S)]
    items = [len(re.findall(r"<li[\s>]", x)) for x in re.findall(r"<(?:ul|ol)[\s>].*?</(?:ul|ol)>", t, re.S)]
    return {"core": 'class="core"' in t or "<pre>core" in t.replace(" ", "") or bool(re.search(r"core\s{2,}", t[:6000])),
            "folds": len(re.findall(r'<details class="fold', t)), "max_table_rows": max(rows, default=0), "max_list_items": max(items, default=0)}


def block() -> str:
    return "<style data-doc-style>\n" + CSS.read_text() + "</style>"


def apply(path) -> bool:
    p = pathlib.Path(path)
    s = p.read_text()
    new = block()
    if BLOCK.search(s):
        out = BLOCK.sub(lambda _: new, s, count=1)
    elif "</head>" in s:
        out = s.replace("</head>", new + "</head>", 1)
    elif "</style>" in s:
        i = s.rfind("</style>") + len("</style>")
        out = s[:i] + new + s[i:]
    else:
        out = new + s
    if USES_FOLD.search(BLOCK.sub("", out)):
        if FOLD.search(out):
            out = FOLD.sub(lambda _: FOLD_JS, out, count=1)
        elif "</html>" in out:
            out = out.replace("</html>", FOLD_JS + "</html>", 1)
        else:
            out += FOLD_JS
    strip = recent(p.parent)
    out = RECENT.sub("", out)
    if strip:
        if "</nav>" in out:
            out = out.replace("</nav>", "</nav>" + strip, 1)
        elif re.search(r"<main[\s>]", out.split("</style>")[-1]):
            i = out.rindex("</style>") + 8 if "</style>" in out else 0
            i = out.index(re.search(r"<main[\s>]", out[i:]).group(0), i)
            out = out[:i] + strip + out[i:]
    if out != s:
        p.write_text(out)
        return True
    return False


def all_docs():
    for p in CS.rglob("doc.html"):
        if not any(x in str(p) for x in SKIP):
            yield p


if __name__ == "__main__":
    if sys.argv[1:2] == ["--audit"]:
        bad = 0
        for f in sorted(all_docs()):
            a = audit(f)
            ok = a["core"] and a["max_table_rows"] <= LIMIT * 2 and a["max_list_items"] <= LIMIT * 2
            bad += not ok
            print(("ok     " if ok else "NEEDS  ") + f"core={'y' if a['core'] else 'n'} folds={a['folds']:<3} longest table={a['max_table_rows']:<4} longest list={a['max_list_items']:<4} {f.relative_to(CS)}")
        print(f"{bad} pages need the core block / folds")
        sys.exit(0)
    files = [pathlib.Path(a) for a in sys.argv[1:]] or list(all_docs())
    for f in files:
        print(("updated  " if apply(f) else "same     ") + str(f))
