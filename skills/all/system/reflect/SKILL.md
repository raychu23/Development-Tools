---
name: reflect
description: End-of-chat sweep (/reflect). Use when a chat is ending, handing off, about to compact, or Raymond says reflect / wrap up / save what matters. Route facts into task files, verify the changed files, and commit only own work when safe and unblocked. Never asks Raymond to do it by hand.
metadata:
  source: own
  takeaway: "Before a chat ends, move every fact only in chat into task files, then grep to confirm"
---

```notes
reflect      (/reflect      raymond 0B L10-16: "turn this reflection process into skill … so I never have to manually do this again")
    when                    chat ends · hand-off · before compaction · raymond says reflect / wrap up / save what matters
    needs                   docs-over-chat (task folder + routing rules)      notes-style for every line written
    1 reread                this chat's asks, decisions, corrections, results, findings, to-dos      tool output too
    1b my notes             tag this chat's new msgs (cat · key · to) in my words cats.json → my_words.py --insights (docs-over-chat row)      then overview.py → Context/overview.md
    2 route                 each one still only in chat → its file (docs-over-chat §3)      same task folder as this chat
        raymond's words     1 takeaways (task)      complaint / correction / pref → also Context/1 takeaways.md §3 inbox, verbatim + date + source
        own diagnosis       2 insights      label INFERENCE
        how the chat went   3 workflow      misreads, loops, what worked
        state               0 start      status · next · decisions needed      ≤40 lines
        cross-session fact  memory only if true every session (who raymond is, env)      else a skill or task file
    3 skill candidates      flag, dont build      list in 2 insights "skill candidates"
        new skill           same procedure done ≥2× (this chat or earlier) · a workflow that took trial and error
        patch skill         a skill was loaded and was wrong / missing a step / needed a pitfall → patch it now (that one IS done now)
        each row            name · trigger · steps seen · evidence (file / chat id)
    3b check, not text      poteto /correct (skills/all/system/poteto): every correction this chat → could a check enforce it?
        seen ≥2×            fix at highest level: architecture → hook / lint / test whose error names the fix → rule text last
        rule table          Context/1 takeaways §1 rule → its enforcer (hook · test · reviewer · none)      "none" + repeat = build the check
        prune               §1 / skill rules whose mistake can no longer happen → propose removing
    4 fold inbox            locate the active repo's fold-inbox utility and confirm its CLI before running `propose`
                            if missing, leave inbox/proposal untouched and report the blocker; never guess the path or apply
                            approve only with raymond's ok (he sets approve or says "fold all")      then apply
    5 check                 grep this chat's key numbers, paths, ids in the task files      any missing → add      chat holds nothing the files lack
    6 commit                check staged overlap + HEAD.lock first; commit only own paths when unblocked; never remove a lock; msg = reflect: <task> + what landed
    7 say                   ≤5 lines: files changed (full paths) · skill candidates · inbox count
    never                   invent a decision raymond didnt make · rewrite his notes · mark a gap fixed without proof
```
