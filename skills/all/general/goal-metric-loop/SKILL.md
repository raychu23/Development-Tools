---
name: goal-metric-loop
description: "Use when a task is hard, uncertain or long-running. Freeze goal + metrics first, checkpoint and readjust, prove it."
metadata:
  source: own
  takeaway: "Write the goal and how you'll measure it before code; measure at every checkpoint; change the plan when the numbers say so; one real-path check before 'done'"
---

# Goal → metric → checkpoint loop

Default loop for any task that is challenging (likely to fail the first try), long-running (>~30 min, many steps), or aimed at something you can't read directly (a live app, a UI, a service). Skip it for trivial edits. Raymond asked for it by name on 2026-10-29 ("follow the whole loop with initial goal and how to measure achieve goal, plus checks throughout... strategic readjustments").

Lighter than `metric-gated-build-loop` (many ledger tasks, builder chats). Use `fix-loop-metric-gate` when a fix already failed twice. Both build on this shape.

## The loop

1. **Goal + done-when, in a file, before code.** One sentence of what must be true, then numbered metrics M1..Mn: what is measured, the target, and the **oracle** (a different method than the code under test: brute-force count, the real file, the live source). Save as `<task>/systems/<goal>-goal.json` with `asked` (his words verbatim), `metrics`, `checkpoints`, `never`. Frozen: a metric changes only with a dated line saying why.
2. **Name the layers each metric proves** (pure logic / DOM / real OS input / his eyes). Keep the requested user-visible outcome as the completion gate; a handler pass, process timestamp, or success toast is supporting evidence, not a substitute. Add safety invariants for existing user data and working integrations before running tests. Follow `stateful-integration-verification` before starting stateful test processes: prove effective storage paths and block live writes before startup, rather than trusting environment overrides or after-the-fact hashes. A genuinely unsafe or inaccessible layer remains OPEN with its exact blocker; use available safe automation rather than automatically handing the click back to Raymond.
3. **Baseline on the current state** with the same checks, written to `<goal>-runs.jsonl`. If it can't run, write how the baseline was derived instead.
4. **Probe before you patch.** Anything that decides the design (event order, API semantics, which code owns an element) gets a one-shot probe whose raw output you read. One failed theory → probe, not a second theory. (Cmd+F task: core's key handler runs before plugins; Electron's `findNext` flag is inverted. Both were facts, not guesses, only after a probe.)
5. **Build the smallest slice, then run ONE command that measures everything** and appends a row `{run, time, plugin/code sha, harness sha, metrics, note}`. Same shas as the last row = no new evidence; say so.
6. **Checkpoint after each slice (C1..Cn)**, one line in the file: what moved, what didn't, next change or *changed plan*. This is the strategic readjust. Triggers: a metric didn't move after 2 changes (premise wrong, stop patching, probe); 2+ failures came from the environment (fix the harness: fixtures, pinned state, not the code); a constraint appeared that the goal didn't assume (re-plan in the file). Probes and goal-file setup are prerequisites, not completion: after them, keep iterating through implemented slices until every reachable goal metric passes; each code slice must change the artifact or behavior and then produce fresh measurement evidence.
7. **Triage every failure into one class** before touching anything: code bug / harness bug / oracle bug / environment interference. Fixing the wrong class is where most loops waste turns. Stop the loop immediately if a safety invariant fails or fixture state disappears unexpectedly; disable the unsafe runner and prioritize restoration of the user's working system. Do not continue feature iterations while a test may be damaging live state.
8. **Independent check before "done"**: one run through the real path (his real app, real input, the real page), plus a visual check for any UI (screenshot, read it). For stateful UI integrations, verify the state owner changed—not only the request or registration payload: a mock that sees `ctx.register` can pass while the existing layout tree remains untouched. Test an already-present pane whose target changes, assert its post-operation group and active selection, then do the live screenshot check when safe. If the real path can't be run safely, say exactly what is unverified and the one step he does.
9. **Hygiene**: remove temporary harness pieces (eval backdoors, probes), keep the reusable harness and runner in the repo, confirm no leaks (listeners, timers, duplicate DOM) with a number.
10. **Report**: answer “fixed and live-verified” or “not fixed yet” first, then only the decisive evidence and remaining blocker. Keep the detailed metric table and checkpoint history in task files instead of replaying the process in chat. A blocked activation is not completion; identify the specific intervention needed instead of repeatedly using the active chat as an indefinite reason to defer. Route the facts to task files the same turn (docs-over-chat).

## Rules that kept this honest
- Metrics are computed by code; a model only rewords them. Green only by fixing the thing, never by loosening a check.
- Don't test by typing into the user's live window while he's working (osascript keystrokes into Hermes hit his composer). Drive synthetic events from the right origin, and ask for his one real press.
- A shared stateful surface (a pane something else keeps re-pointing) makes flaky tests: build a fixture with the same attributes and keep one smoke on the real thing.
- Cap: 3 changes that don't move the same metric → dispatch a fresh debugger with live evidence (`inspecting-hermes-desktop-dom` pattern).

## Example
Cmd+F in Hermes Browser + Docs panes: `Context/context-and-skills/T13-hermes-desktop-setup/systems/find-goal.json` (metrics M1-M7, checkpoints C0-C3), `find-runs.jsonl` (rows incl. baseline), runner `~/.hermes/desktop-plugins/.test-harness/run-find.py`.

See also: `fix-loop-metric-gate` and its worked example (`references/worked-example-path-links.md`) -- what a slow 21-round fix looked like, and the preflight that makes it first-try.
