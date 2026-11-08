---
name: intuitive-technical-explanations
description: Explain technical projects, experiments, designs, and failures so a reader can see the whole system, current stage, causal reason, and next decision. Use for requests to explain better, give the big picture, or make progress intelligible; do not use for terse fact lookups.
metadata:
  source: own
  takeaway: "Give every number a reference point and explain the cause, not just the sequence of runs"
---

# Intuitive Technical Explanations

Make the reader able to answer four questions after the first screen: What are we trying to finish? Where are we now? What does the evidence mean? What changes next?

## Build the mental model first

- Start with the conclusion in plain language, then give the technical detail. This follows the conclusion-first structure used in GitHub Docs.
- For a staged system, draw the smallest useful progression and mark the active boundary. Explain what is still conventional, what is already replaced, and what the final state must contain.
- Translate names into roles on first use. For example, “teacher” means the already-strong reference model; “student TB layer” means the replacement being taught to reproduce the teacher’s internal signal.
- Show a coined name for a product part ("the card") on one real case before using it a second time. Go line by line and mark which parts already exist elsewhere, naming the tool. If most parts exist, say so, and lead with the part that doesn't. Raymond, Mole 2026-10-28: "i dont get this card thinng you keep talking whats even pt of that isnt that just basic stuff". It had been used on 3 pages with only made-up numbers, and 3 of its 5 lines turned out to exist in other tools.
- Give numbers a reference point: baseline, prior stage, goal, or matched comparison. A value with no comparison is not an explanation.
- When a reader has already seen a prior update, start from that exact checkpoint. Do not rewind to a broad project introduction unless a new fact actually changes the project premise.

## Explain cause, not just sequence

Use this order when it fits:

1. **Outcome:** the one-sentence answer.
2. **Model:** a small flow, analogy, or concrete before/after that shows the system.
3. **Evidence:** the smallest set of results that supports the interpretation.
4. **Mechanism:** why the result plausibly happened, marking hypothesis versus demonstrated fact.
5. **Decision:** the next action and why it is the most informative one.

Do not replace the mechanism with a list of attempted settings. Use lists only for genuinely independent choices.

For experiment progress, use an evidence chain when possible:

```text
prior gate → intended change → observed result → interpretation → next gate
```

For example, distinguish a *routing endpoint* from the fraction of batches that actually used that route during a gradual ramp. This prevents a simple percentage from creating the wrong mental picture.

## Match the reader's need

- **Manager update:** whole-project map, decision-relevant evidence, constraint, and next gate. Avoid code-level details unless they change priority or risk.
- **Personal understanding:** slow down at the boundary that changed. Trace one example through the system before generalizing.
- **Implementation handoff:** explain the contract, the affected boundary, exact artifacts, and verification separately.
- **Troubleshooting:** distinguish product evidence from environment evidence. A disk-full or service error explains an interrupted measurement, not the quality of the underlying approach.

This separates understanding-oriented explanation from task-oriented instruction, consistent with Diataxis. Keep the update self-contained: readers should not need earlier messages to understand its claim.

## Style checks

- Prefer one concrete causal example over many generic examples.
- Use an analogy only if it preserves the important constraint; immediately map it back to the real system.
- State uncertainty plainly: “we know X,” “Y is the leading explanation,” “Z has not yet been measured.”
- Do not use motivational filler, fake certainty, unexplained acronyms, or a “last time/current/next” chronology when the project map communicates more.
- When supplying copy-ready Markdown, use one fence level at most. Put small flows in indented plain text if they must live inside a larger copy block.
