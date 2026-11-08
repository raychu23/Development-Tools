---
name: verify-pyramid
description: Check work bottom-up before calling it done - deterministic checks first, a separate fresh reviewer last. Use before marking any code, doc or skill change done, and for PR review.
metadata:
  source: own
  takeaway: "Check bottom-up, stop at the first fail; the model judge goes last and isn't the builder"
---

```notes
verify pyramid
    why                     self-review skews positive (anthropic harness post)      llm judges drift to long answers + first-read bias (lavaee)
    order (stop at 1st fail)
        1 types             tsc / mypy / compiler
        2 lint + static     eslint / ruff / validate scripts (systems/validate.sh for skills + names)
        3 unit tests
        4 integration       against real services or real files
        5 end to end        running app / real artifact opened and used
        6 model judge       only for what code cant check: does it match the spec, does the message make sense
    model judge rules
        separate            reviewer ≠ builder      fresh context, reads acceptance criteria before the build report
        checklist           1 item per row      score 1 = broken … 20 = proven with evidence
        fresh per item      1 verifier per checklist item so strong items cant lift weak ones
        fail fast           average scores, but any "definitely broken" fails the whole thing
        repeat              rerun flaky checks      1 good run proves little (pass^k)
    intent                  raymond writes the done-when first      agent-written intent only confirms itself
    record                  results + evidence links → task 2 insights.md      raymond-facing summary → 0 start.md status
```
