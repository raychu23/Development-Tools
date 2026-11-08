---
name: docs-over-chat
description: "Keep all work info in files, never only in chat, for every topic, project and task in any harness. Facts that get reused or checked live as structured data (JSON/JSONL with a schema); the level files carry the prose; one generated doc.html per task is the readable page any browser or Hermes opens. No Claude Docs. Chat only for corrections and back-and-forth. Also sets up the task folder and its level files (0 start, 1 takeaways, 2 insights, 3 workflow, 4 log) and c/o/d subideas: at chat start, on a topic switch, and when Raymond gives a fix, correction or preference (task-files merged in, 2026-10-15). Always on in every harness. Use every turn that produces an ask, decision, result, finding, correction or to-do."
metadata:
  source: own
  takeaway: "All work info lives in files; chat is only for corrections and back-and-forth"
---

```notes
docs-over-chat      (every topic · project · task · any harness      builds on notes-style      task-files merged in as §0, 2026-10-15)
    rule                    chat = corrections + back-and-forth only      all work info lives in files      nothing worthwhile only in chat
    why                     raymond reads + revises files      chats get compacted + lost      next session boots from files, never old chat
    no claude docs          raymond 2026-10-14: "no more claude artifacts, use system thats available universally"
                            existing claude docs are frozen      their exact exports live in the task's docs/      never create new ones

    0 task folder first      (was task-files skill, rules.md §3)      do this before the first real reply of any chat
        find                    the task this chat serves: cwd · chat → folder map · find-context skill      none fits → new task
        new task                sh systems/new-task.sh "<parent dir>" "<name>"      makes <name>/0 start.md from template
        new subidea             sh systems/subidea.sh "<task dir>" "<name>"      topic switch inside a chat: c → o for current, makes c <name>/0 start.md, fixes links, git mv
        list limit              ≤7 main tasks per project (T1-T7)      new work → agent T<n>-a<n>-<job> inside the closest main task      never an 8th T      Context/1 takeaways §0
        my notes                every msg raymond types = his notes, never thrown away      route it to its task same turn (Context/1 takeaways §0 #2)
                                tag it in <task>/systems/my words cats.json: cat (belief · note · pref · ask · decision · check) · key (few words) · to (where it landed)
                                python3 Context/context-and-skills/T16-notes-foundation-org/systems/my_words.py <transcript.jsonl> "<task>/4 log/my words.md" --cats "<task>/systems/my words cats.json" --insights "<task>/2 insights.md"
                                → key table on top of 2 insights.md · full verbatim in 4 log/my words.md + plain 4 log/my words.txt (oldest first)
                                hermes chat: pass /dev/null as transcript + --hermes <session id> · run it every few big turns, not only at chat end (raymond 10-29: "shouldve also been klept in like a txt doc")
                                pasted chats he attaches (~/.hermes/attachments/pasted_content_*) → copy to 4 log/pasted/
        overview                python3 "Context/context-and-skills/T16-notes-foundation-org/o overview/systems/overview.py"      → Context/overview.md (every task, 1 table per project)      run at chat end
        which file
            0 start.md          current state only      ≤40 lines      goal · done-when · status · next · links · harness
            1 takeaways.md      raymond's own words: fix / complaint / pref → fix · proof · applies-to · gap · status
                correction      old → replacement → scope → source → affected work
            2 insights.md       agent diagnosis, eval findings, dependency watch, next-step candidates      label INFERENCE
                                lead section "0 continuous": topics that are never "done", only refined — raymond saying "deep research" / "research X" / "find external tools" on a topic is the signal it belongs here, not as a one-shot finding (Context/1 takeaways §0 belief 6)      row = topic · why continuous · last touched · what's still open/unsatisfied · pointer to the deep-dive section      update in place, never delete, never mark done
            3 workflow.md       patterns of the back-and-forth (misreads, loops, handoffs that worked)
            4 log               pointer to raw transcript      never preloaded
        create only             files with real content      0 start always, the rest when something lands in them
        chat ends / hands off   run the reflect skill (what to keep · skill candidates · fold-inbox)
    1 three layers, same facts      (learning M10: Project/sdlc/9-guidance/7 learnings.md)
        a data              <task>/systems/*.json or *.jsonl      results · decisions · asks · status      the record agents reuse + check
                            agree the schema before the work starts      a script validates it (required keys, types, paths exist)
                            numbers, paths, run ids, dates go here first, never only in prose
        b level files       0 start · 1 takeaways · 2 insights · 3 workflow · 4 log      §0      notes style      canonical prose      git
        c readable page     <task>/doc.html made by <task>/systems/render_docs.py      build rules, look, hermes Docs pane: references/doc-page.md
            colors          status pills + greys come ONLY from assets/doc-style.css (.s / .tag state classes)      never set a pill background or text color in a page's own CSS (pastel bg + light page text = unreadable, raymond 2026-11-03)      details: references/doc-page.md §4
            summary on top  EVERY doc / page / long section he'll read opens with "## Summary" written like the chat reply:
                            plain words · what it is + the answer/state + what's open · ≤8 lines · jargon defined      dense notes below it
                            raymond 2026-11-02: "the summary you often provide in chat very clear usually i prefer that … any doc … at top"
                            refresh it on every edit (stale summary = wrong doc)
        d sync              every write lands in a + b in the same turn, then re-render c      commit data + files + page together
        e conflict          raymond edits a file → keep it, fold into data      other agent edits → build on it, never revert
        f hermes            map chat → task folder in Context/context-and-skills/systems/hermes session folders.json      details: references/doc-page.md
    2 issues (raymond 2026-11-03/04)      a project's directions that never end (e.g. "load socials")      numbered topic.project.issue.item (3.1.3.D2)      1 Build + 2 Fix in every project      tasks and agents serve an issue
        data            <project>/systems/issues.json · notes.jsonl · timeline.jsonl      tool: python3 systems/active/active.py (README: systems/active/README.md)      project must be a row in systems/active/projects.json
        every turn      his message → active.py note 3.1.3 <kind> "<key>"      what changed → active.py log 3.1.3 <agent> <task> "..."      state changed → issues.json or active.py set 3.1.3.D2 answered      then render + commit own paths
        his words       notes.jsonl is append-only, never edit or remove (the check fails)      his notes + chat prompts are gold      route each to an issue the same turn
        pages           Context/active.html (topics → projects, no global notes/timeline) · <project>/active.html      D decision = blocked on him · P proposal = my idea, nothing blocked      be proactive: add proposals with the evidence in 'why'
        fresh agent     reads <project>/systems/briefs/<ref>.md (generated, ≤40 lines) instead of the old chat
    2b page kit (raymond 2026-11-04 "back the core block + folding into the docs generation")      scripts/doc_style.py + assets/doc-style.css
        core(lines)         ≤7-line core block, first line "core ..." with counts linking to sections (data-go / data-open)
        fold(summary, body) folding section, nest freely      fold_list(rows, label) cuts any list into folds of 7      fold_bar() expand / collapse all
        script              added automatically by doc_style.apply when a page uses the kit      old pages are untouched      doc_style.py --audit lists pages without a core block or with tables/lists over 14
        rule                every multi-section page = core block + folds, ≤7 things per list (Context/principles.md)
    3 every turn (sdlc order)
        1 sort new info     ask · decision · correction · result · finding · blocker · idea · to-do
        2 route
            ask             data asks + 1 takeaways if it is a pref or fix
            decision        data decisions (with why) + 0 start
            correction      1 takeaways (old → new → scope → source → affected work)      fix data + files in place, no new version
            result/finding  data results (numbers, paths, run ids) + 0 start status
            to-do           0 start next (agent) or decisions-needed checklist (raymond)
            own diagnosis   2 insights (label INFERENCE)
        3 validate          run the task's schema check      a failing check blocks the commit
        4 render            systems/render_docs.py → doc.html      open it once to confirm it shows the new facts
        5 commit            git add only own paths      msg = what + why
        6 audit             reread this turn's chat + tool output: any fact, number, path or finding missing → add now
        7 reply             ≤8 lines: what changed + where (full paths)      questions → checklist, 1 line in chat
            deliverables    a link must open in the Hermes app. Its Files panel only lists the open project, so a markdown link to a file outside it errors ("outside the open project"). For anything Raymond has to open: write a readable HTML page in the task folder (thumbnails for images, one link per file), open it with `open`, and link that page. Keep the markdown list too.
            pre-send check  count the lines · no …/ shortened paths · every question already in <task>/systems/decisions.jsonl + doc.html checklist · doc.html re-rendered this turn
                            routing facts into files = steps 1-2 only, not the whole skill      (raymond 2026-10-16 "why arent you following docs-over-chat")

    more                    page layout · style · checks · hermes Docs details → references/doc-page.md (read when building a page)
```
