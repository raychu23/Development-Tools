---
name: find-context
description: Find raymond's past decisions, corrections, rules and task state in CS Code — "what did we decide", "why did I reject", "where does task X stand", "last time", "earlier". One fast local search over the curated level files (rules.md + rules/, AGENTS, every 0 start / 1 takeaways / 2 insights / 3 workflow, context mgmt/me). Use before reading chat logs, grepping the tree, or asking raymond again.
metadata:
  source: own
  takeaway: "Run ctx_search before reading logs or asking Raymond again; on a miss, grep its words"
---

```notes
find-context
    use when                a question depends on earlier work: what was decided, why, what raymond corrected, where a task stands, which file owns something
                            before opening 4 log, codex/full transcripts or other big files      before asking raymond something the files may already say
    run                     python3 "$WORKSPACE/skills/all/system/find-context/ctx_search.py" "<the question in plain words>"
        options             -k 3 (fewer hits)      --json (machine output)      --all (also the codex/dense chat archive)
        output              path:lines + the cue it sits under + 6 lines of text      ~150 tokens per hit
    then                    open only the cited path:lines slice if more is needed      cite path:line in the answer
                            0 hits or wrong hits → rephrase with the words the files would use (cue names, task ids like T3, file names) → then grep → then 4 log
    why                     T5/T7 eval, 21 questions: 16/21 in top 5 at ~780 tokens/q (held-out half 7/10)      grep slices 17/21 at ~4.6K, different misses      hindsight 15/21 at ~2.2K, 7 s      ai-memory 0-12/21
    miss → grep             find-context and grep miss different questions (together 19/21)      a miss here → grep the cited words before giving up
                            stdlib only (sqlite fts5), no model, no server, ~0.1 s      files stay the only truth
    not for                 code search (use rg)      live state of running systems (ask the tool)      handoffs between agents (ai-memory)
    source                  Context/context-and-skills/T7-memory-llm-trial/2 insights.md
```
