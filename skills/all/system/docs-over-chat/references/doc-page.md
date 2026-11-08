```notes
doc page + hermes details      moved out of docs-over-chat SKILL.md 2026-10-17 (shrink, raymond ok) · text unchanged · read when building / fixing a doc.html
    1 c / f (from §1)
        c readable page     <task>/doc.html      generated from a + b by <task>/systems/render_docs.py      any browser, hermes Docs page
                            tabs = TOP tab bar inside the one file, never a left sidebar (raymond 2026-10-15: too much left-right scrolling)      sections: main · results · history and decisions · background
                            look = 1 source for every doc: assets/doc-style.css (this skill)      never restyle a doc by hand
                                new doc / render script      write plain <nav> (a or button tabs, .on = active) · <main> · <section class="on"> for the initially active section, then doc_style.apply(path)
                                visibility contract         shared CSS hides sections without .on      tab handlers toggle .on on sections AND buttons, hidden=false alone is insufficient
                                verify preview              browser-check computed display, nonzero geometry and text on initial load + every tab      parsing HTML or finding source text does not prove visible content
                                                            headless chrome passing ≠ hermes Docs pane showing it: check the pane too (computer_use capture of the Hermes window)
                                change the look            edit assets/doc-style.css → python3 scripts/doc_style.py (re-stamps every doc.html in CS Code)
                                wide comparison tables     <main class='wide'> lifts the 1100px cap (opt-in, page-level)      extra pages = <name>.html beside doc.html, same render script
                                                            wrap each wide table in <div class='tw'> (.tw{overflow-x:auto}) + min-width by column count (≥8 cols 900px · 7 780 · 6 720 · 5 620): a narrow Docs pane then scrolls the table, not the page, and no column turns into a 1-word sliver
                                many pages                 > 2 pages in one task → hub '0 Start here.html' (sorts first in Docs ▾): pages in reading order · every OPEN decision in 1 list by theme · decided · timeline · files      rendered from systems/hub/pages.json + decisions.jsonl; render fails if a page or an OPEN decision is unlisted; every page links back to it
                                                            raymond 2026-10-28: "help me navigate all the planning files … where cna i see all the info proeprly review them"      example: Mole product-plan/systems/hub
                                                            a list of every page is not enough (raymond 10-29, 3rd time): first tab = the ≤5 main reads with what each is for + when · his own problem → solution words (quoted by line) mapped to the page that answers each + its build state · who's building · a 'words + ids' tab explains every id family and label, and where a letter means 2 things, where each meaning applies · render fails on a misquoted line, unknown task / decision id, unlisted page
                                                            his own ideas = dense notes in his file format, not big tables (raymond 10-29 'this big ass table reallty not heliing anyone'): prob left · solutn right · per bullet idea / state / next / read (1-line source summaries) + a newest-first list · number the main reads 1-N in their file names
                                one readable page first    any product / plan write-up starts as 1 text page: problem → what exists → what we add → built → plug in → 1 next build → test · tabs + tables only behind it      raymond 2026-10-28: "very confusing … be clear about the full seuweence pronb solutison etc in a new file"      example: Mole product-plan/Mole start to finish.md
                                carry every USER decision  a page that condenses others keeps every USER / ANSWERED / DECIDED decision + accepted feature from them · render check: each such decision id appears in the page's own prose (generated tables don't count)      raymond 2026-10-28: Mole one page v1/v2 lost D2 and he caught it ('have you been incoproraig these core ideas') · then v3 cited D2 for the opposite of his answer → each such decision also needs a key phrase from his ANSWER on the page (render check), not just its id
                                plan page                  proposals pile up across pages → one current plan page: what's built (verified) · build order · every earlier milestone + addition placed exactly once (render-checked) · my replaced proposals marked replaced, not stacked
                                                            raymond 2026-10-28: "is there new r updated product plan"      example: Mole product-plan/What to build.html
                                quoting his lines          pages that cite a live notes file by line number: the re-pin shifts every page's refs, and a validator checks the quoted words sit on the cited line
                                text-first layout check    no eyes? inject a load-time probe script into a scratch copy, run Chrome --headless=new --user-data-dir=<scratch profile> --window-size=<w>,2000 --virtual-time-budget=3000 --dump-dom (no own profile → it can hang when Chrome is open), read its JSON back
                                                            probe per tab: page scrollWidth > clientWidth · td < 70px holding > 14 chars · .tw boxes that scroll · elements whose scrollWidth > clientWidth      run at 1440 / 900 / 700 px      example: Mole product-plan/systems/offering (10-27)
                                                            a page with no <section> tabs needs a page-level probe: a per-section probe returns {} on it and looks like a pass · long URLs in a Sources list don't wrap and overflow the page at phone width (Mole 10-29: 4 pages, 36-150 px at 560) → main p, main li {overflow-wrap:anywhere}; pre {max-width:100%; overflow-x:auto}
                            optional docs/*.md copies for git diffs      never hand-edit html, edit data or level files then re-render
        f hermes desktop    reader = <task folder>/doc.html      an explicitly requested doc.md / existing format wins
                            1 folder per chat: the task folder      files owned by other tasks → symlink in, never copy
                            link chat → folder: add "<chat id>": "<folder>" to Context/context-and-skills/systems/hermes session folders.json      chat id = sessions row in ~/.hermes/state.db
                            raymond picks docs from title bar "Docs ▾" (plugins docs-button + docs-page) → 1 Docs tab in the browser/file preview strip      .html listed first      folder = only what THIS chat made
                            dont open docs with desktop_preview (new tab each)      dont tell him to pin

    2 page layout (from §2)
        0 summary           top of every page AND every long section: chat-style summary (plain, ≤8 lines: what this is · answer/state · open)
                            raymond 2026-11-02 prefers it over dense notes for a first read      refresh on every edit
        a main              current answer / plan      most relevant top      decisions-needed checklist      change log bottom
        b results           table rendered from systems/results.json(l)      verdict first
        c history           every ask in order · decisions + why · mistakes owned      from systems/decisions.jsonl + 1 takeaways
        d background        explanations worth keeping      from 2 insights

    4 style
        files               notes-style      page: tables for comparisons (verdict first), plain words
        order               plan → build → test → review → ship      (or academic / bug-fix cycle)
        pills + colors      status pill = <span class="s done|active|blocked|todo"> or class="tag ok|open|wait"      colors come ONLY from assets/doc-style.css (dark tint bg + light colored text, always paired)
                            never write a pill background, or any color, in a page's own CSS      pastel bg + the dark page's light text = unreadable (raymond 2026-11-03, Context/active.html)
                            new state → add a class to doc-style.css, run doc_style.py      grey text uses var(--ds-mut), never #666

    5 checks
        a end of turn       chat holds nothing the files lack      data + 0 start + doc.html agree on status + next
        b new session       boots from 0 start.md (+ data)      if it needs the old chat, step 6 missed something → fix
        d readable         open the page once: every pill + small text readable on the dark bg      (computed color vs background, not assumed)
        c spot check        ask a fresh session "where is <fact>"      answer must be a file path or data key
```
