---
name: product-prototypes
description: "Use when prototyping a planned product from plan docs."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  source: own
  takeaway: "Run the real core on real data, simulate only what can't run yet, label it REAL or MOCK"
  hermes:
    tags: [prototype, product, plan, mockup, verification, headless]
    related_skills: [claude-design, spike, verify-pyramid, docs-over-chat]
---

# Product prototypes (from a plan, before the real build)

## When to Use

Asks like "build me a prototype of <product> in its different settings and how it's used", after a planning session left structured plan data. The deliverable is a clickable local app that shows each setting/host the plan names, grounded in real data wherever the plan's core can already run. Not a spike (that answers one feasibility question) and not a design board (see `claude-design` for taste/composition rules, which still apply to the visuals).

## Procedure

1. **Read the plan data, not the rendered page.** Load the plan's structured files (e.g. `systems/plan.json`, `offerings.json`) plus the project's startup packet. Note component ids (S1.x, F2.x) so every view can cite them.
   - A sibling chat may still be editing the plan. Re-check plan files' mtimes before reporting; fold in rules added mid-build (renamed pages, new layer rules) instead of shipping against a stale copy.
2. **Map settings → views.** One top tab per setting/host the plan names (editor sidebar, agent terminal, agent panel per host, PR/CI, settings) plus a first "How it's used" tab: a settings table (setting · stage · who · what you see · plan ids) and one walkthrough per customer whose steps deep-link into the exact view state (`go({tab, file, step, host})`).
3. **Ground the core in real data.** Run the piece the plan already chose on a real, mid-size repo that is already on disk (e.g. TS Compiler API over a local TS project). Reuse an existing `node_modules` via an env override (`MOLE_TS=/path/to/typescript`) instead of installing; disk is tight.
4. **One shared core module** (UMD: sets `window.X` in the browser, `module.exports` in Node) used by the app, a small CLI, and the tests, so the agent-facing text and the UI can never disagree.
5. **Simulate only what cannot run yet** (agent sessions, PRs, host chrome, LLM text) as a scripted event list with step/back/run-to-end replay. Route simulated effects through the real core (e.g. an agent edit adds an overlay edge, then the real drift rule flags it) so downstream views compute real consequences.
6. **Label honestly on every view**: a strip with REAL / SAMPLE / MOCK tags, plus a real-vs-simulated table on the start tab. Cost/speed numbers from simulation are marked `proxy`, never presented as measured savings; point to the plan milestone that will measure them.
7. **One state across tabs.** Settings change the other tabs live (persona presets + every config key, rendered as the proposed config file). Expose `window.__app = { S, go }` for tests.
8. **Verify bottom-up** (see `references/verification.md`):
   - `node --check` every JS file.
   - Deterministic core checks against the real source: sampled file:line lands on the claimed statement, caps respected, budgets (bytes/chars) met, determinism of generated blocks.
   - Headless browser smoke that drives every tab and key interaction, fails on any console/page error, saves screenshots.
   - Look at the screenshots (vision) and fix layout problems before handing over.
9. **Repo hygiene.** Generated data that embeds third-party source goes in a gitignored `data/` with the rebuild command in the prototype README. Don't commit unless asked.
10. **Report**: path to open, one table of tabs (stage · what you can do), real vs simulated in 2 lines, bugs found while building, what's not shown, the one open question for the user.

## Pitfalls

- **A check that fails on real data is usually a core bug, not a flaky test.** Print the offending lines before loosening the threshold (see `references/ts-code-graph.md`).
- **Pin must-show items in capped/ranked lists.** If a badge says "drift here", the drift partner must be in the neighbourhood even at a small node cap, or the picture contradicts the badge.
- **Badge only exact anchors.** A folder-level anchor badged on every file inside it turns the explorer into noise; badge the folder row instead.
- **Layers/badges appear only where they exist** for the current item; disable the toggle with a tooltip rather than showing an empty layer.
- **Box-and-arrow SVGs**: route same-column, non-adjacent edges around the outside and draw violation edges after the boxes, otherwise the important line hides behind a box.
- **Debounce file-switch renders** and show render time + skipped renders in the footer, so "instant, zero tokens" claims are visible, not asserted.

## References

- `references/verification.md`: headless smoke harness pattern, browser launch fix, screenshot review checklist
- `references/ts-code-graph.md`: building a file/symbol/import/call graph with the TypeScript Compiler API and its traps
