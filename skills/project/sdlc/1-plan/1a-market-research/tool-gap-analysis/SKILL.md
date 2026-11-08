---
name: tool-gap-analysis
description: Use when comparing other tools to the user's own, or planning it. Covers shared articles/threads, gap ranking, product build-out plans.
metadata:
  source: own
  takeaway: "Grep the user's own tool for a feature before calling it a gap; many exist but sit unused"
  hermes:
    related_skills: [evidence-first-planning, docs-over-chat, github]
---

# Tool gap analysis

Trigger: "they do X I don't see in mine", screenshots of competitor tools/harnesses/apps, "should I copy/adopt X", or a shared article/thread ("read this, find similar, what should we build"). Output is a ranked gap table + build list the user can pick from, not a feature tour. Reasoning standards (claim ledger, strongest alternative, verified vs inference) come from `evidence-first-planning`; files/page layout from `docs-over-chat`. This skill is the procedure; when the user says "build it", follow `references/build-phase.md`. When the user owns the vision and asks to "build out the idea" / "a detailed plan to review" after the research, follow `references/product-plan.md` — the research becomes background and the plan is the deliverable. Shared X posts (thread, replies, media): `references/x-sources.md`.

## Procedure

1. **Task home first.** Make the task folder (CS Code: `sh systems/new-task.sh "<parent>" "<name>"`), log the user's ask verbatim in `1 takeaways.md`. `new-task.sh` creates `0 start.md`, so read it before overwriting (write_file refuses unread files).
   - When the folder lives outside the task tree (e.g. a product's private `context/reference/<topic>/`, where new-task.sh doesn't apply), build the full docs-over-chat skeleton by hand in the same turn: `0 start` (decisions checklist + change log) · `1 takeaways` · `2 insights` · `3 workflow` · `4 log` (chat id from `~/.hermes/state.db` sessions + subagent transcript paths) · `systems/decisions.jsonl` (id · date · status USER/ASSISTANT/OPEN · decision · why · superseded_by · source) rendered on the history tab · the chat→folder link in `hermes session folders.json` · symlinks for other-owned files you edit. Writing only 0 start + data json leaves gaps the user has to point out.
   - Link the chat to the folder's REAL path, not a symlinked alias (private context folders get moved between symlink ends mid-session). If git then says "beyond a symbolic link" or the folder is gitignored by the user's decision, don't force a commit; say the files are saved but unversioned.
   - A new deliverable in the same chat (research → product plan) gets its own task folder: symlink the research folder in as `research/` and re-point the chat link to the new folder.
2. **Read the user's evidence.** Transcribe each screenshot into `systems/screenshots.json` (tool · file · observed; nothing inferred). macOS screenshot names contain U+202F before AM/PM, which some image tools fail to open: copy to scratch with plain names first — `sips -Z 1800 "$f" --out <scratch>/<tool>-<n>.png`.
   - Article/thread input: save the full text to `systems/research/0-source-article.md` (+ raw json) before anything else. X posts and X Articles: `curl -s https://api.fxtwitter.com/<handle>/status/<id>` (article text = `tweet.article.content.blocks[].text`; see `xurl` skill). The baseline (step 3) then scores the user's setup against the article's rules/patterns.
   - Shared X posts: the user counts the **linked articles/repos and the replies** as evidence equal to the main post — a post that ends in ":" is a thread, and replies hold the sharpest critiques (staleness, "pin to commit", "bind status to tests"). Fetch post + self-thread + replies + media per `references/x-sources.md`, curate the useful replies (who · likes · text · url) into `systems/research/x-posts.json`, and give every linked repo/article to a research child.
   - Articles that aggregate company numbers are secondhand: add one research child that checks each decisive claim against its cited primary post (confirmed · partially · not-found · unreadable) and each "start here" repo (`gh api repos/<o>/<r>`). Cited URLs are often wrong or moved; the child should search for the real post before marking it unreadable.
3. **Baseline the incumbent in its source before calling anything a gap.** Grep the user's own tool (code, docs, i18n strings, config) for every feature the screenshots show; record `feature · status (have / have, off / have, have, unused / have, thin / partial / missing) · how · source path:line` in `systems/<tool>-baseline.json`. Many "missing" features exist but are hidden, off by default, or thin — saying "mine lacks X" without this check is the classic error.
   - Search by **workflow step**, not only by screenshot feature: list the whole feature-docs dir (Hermes: `website/docs/user-guide/features/` + `user-guide/*.md`) and read the section headings for review, gates/done-checks, task boards, hooks, rollback, scheduled/loop runs, profiles, sandbox backends. Grepping only the UI code for the screenshot's terms (e.g. desktop git code) misses whole subsystems (`/review`, `/goal gate`, kanban review loop, shell hooks) and produces false gaps.
   - Read the user's live config (`~/.hermes/config.yaml`: model, terminal.backend, delegation, auxiliary, hooks, checkpoints, profiles) so each row says whether *they* have it on, not just whether it exists.
   - **Proposal-stage product (no code yet, e.g. Mole):** the incumbent is the product's startup packet, not source. Restate it first in two lists, **accepted by the user** vs **assistant proposal (not accepted)** plus what is still OPEN. The user asks for this clarification before any comparison, and mixing the two lists makes a proposal look decided.
4. **Fan out research in parallel** (delegate_task, one child per tool + one per practice topic). Give each child: the screenshot transcription, the user's research rules (how it works · claimed benefit + proof · real testimony with date + sentiment · stars/pricing), an exact JSON output path + schema where every item has `source` url, `evidence` (primary-doc · vendor-claim · testimony · observed-screenshot · inference), `user_experience` (what the end user sees/does, step by step), `end_problem_solved`, and `relevance` to the user's tool (adopt-idea · use-as-component · run-alongside · competitor · background — the user wants to know whether to borrow, embed, or pair with each tool, not just whether it competes), and "verify, don't assume" for isolation/security claims. Ask them to read the user's local app-support data when the app is installed — it shows what the user actually configured. Tell them the fallbacks up front: curl, raw GitHub files, `llms-full.txt`/changelog markdown, HN API; snippet-only testimony marked UNVERIFIED. While they run, do the baseline (step 3) and end the turn with a one-line status.
5. **Spot-check decisive child facts yourself** (`gh api repos/<o>/<r>` for stars, `df` for disk, `--version`) — child summaries are self-reports. Validate required keys only; tolerate extra keys.
   - IDE-extension traction, same day, no scraping: POST `https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery?api-version=7.2-preview.1` with `{"filters":[{"criteria":[{"filterType":7,"value":"<publisher.name>"},…]}],"flags":914}` (installs + last update; filterType 10 = search text, plus filterType 8 `Microsoft.VisualStudio.Code`) and `https://open-vsx.org/api/<ns>/<name>` (downloadCount = Cursor / Windsurf reach). Save the json with an `itemName=` url per row so the render's citation check can match it.
   - Before writing "not found among N reviewed" for a combo, search the exact moment + mechanism once more ('review agent changes against design decisions', 'ADR check on PR', 'spec → tests'). In Mole's offering pass this second search surfaced GitHub's gh-aw Design Decision Gate, Kiro's executable specs and CodeRabbit's in-IDE review, all missed by the first sweep.
   - Listings tell what numbers don't: a pivoted tagline (Swimm → legacy apps, CodeStream → telemetry) or no update for a year marks a stalled category; show folded/stalled vs spreading tools side by side.
6. **Synthesize `systems/gaps.json`:** `id · verdict · value (what the user gains, 1 line) · feature · each tool's approach · incumbent now · gap (cost to the user) · build (PROPOSED) · where (file paths in the incumbent) · effort · rank`. Rank in tiers: 0 = config/habit only (existing feature, just unused) → skills/prompts (no core patch) → patches to the incumbent's source (local core patches must be rechecked after every upstream update). Always fill `value` — the user will ask "what's the value added" next.
6a. **Proposal-stage product → `systems/compare.json` instead of gaps.json:**
   - `groups[]`: cluster the sources by **customer → end problem** (e.g. agent paying tokens · system owner · docs writer · PR reviewer), not by source. Per group: `customer · end_problem · experience (what the user sees/does) · vs_<product> · relation · take[] (ideas worth borrowing) · limits/threat`. Different customers explain why look-alike tools are not the same product.
   - **The compare is a feature/integration inventory, not a verdict on the user's selling point.** The user owns the vision: competitors are sources of features to take, components to embed, or tools to pair with, and overlap does not shrink the USP. Never headline "X can't be your selling point" or narrow the USP to whatever no one else does — that framing gets rejected outright and the user restates the vision from scratch.
   - `features[]` (was `usp[]`): each capability with `status` from `common · in a fork/paid tier · not found among N reviewed (≠ absent)` + the tools that have it + `take` (borrow · embed · pair). Write "not found among N reviewed", never "unique"; a not-found item that matches the user's stated vision is support for it, say so.
   - Checking an outside critique or a new idea follows the same rule: report 'already ships' as borrow / integrate rows and answer 'can it work?' with how it fails + how the clear version avoids it. Verdicts like 'its survivors are wrong, can't win on checks' or 'won't stand out' made Raymond restate his vision (2026-10-28: 'it's ok if other tools exist … as long as they're not universal systs … like git'). Only universal systems (git-scale) count as can't-compete.
   - Integrations need a job: state the product's edge rules first (Mole: facts you can click · on the picture beside the code · your files, any tool), then name the one job each plugged-in tool does inside them. A tool with no job is the comparison to try first, not a plug-in: listing DeepWiki as a plug-in without one drew "i dont see pt of linking all that stuff if it's not clear the edge directions and whats the point" (2026-10-28).
   - `baseline`: the free alternative the product must beat (plain frontier-model prompt + top open-source tool) — a build risk to note, not a reason to doubt the vision.
   - The reply leads with the user's vision restated, then a short compare/contrast table (group · customer→problem · experience · relation/take), the comments' best advice, weak points as build risks, and open questions. Record no decision; the product's startup file gets only a pointer line to the research.
   - When the user answers with their own vision, record it as a USER decision that supersedes the assistant framing (startup files + `systems/decisions.jsonl`), mark the compare's verdict sections superseded in `2 insights.md`, and write the vision where they point (e.g. README: core problems → views with pros/cons → staged vision → still open).
6b. **Use-now map (`systems/use-now.json`):** for every existing-but-unused feature from the baseline: `step (workflow step it serves) · tool · does · use_it (exact command / config key) · your_setup (from their config) · value · source path:line`. Render it ABOVE the gap table — "use what you already have" comes before "build more".
7. **Call out features that only looked real** (e.g. a per-workspace "VM" that is only a worktree, or only on a paid tier) with the doc quote.
8. **Practice/workflow synthesis** goes in its own data file with per-step `source` + `evidence_type`; label the stitched end-to-end pipeline INFERENCE even when each step is cited.
9. **Cross-check citations:** every url in a synthesis table must appear in the raw research files; replace any that don't. Put this check inside `render_docs.py`'s validation (regex the urls out of builds/takeaways json, require each in `systems/research/*`) so a bad citation fails the render instead of relying on a manual pass.
10. Render + commit per `docs-over-chat`; user decisions go in the 0 start decisions-needed checklist with a recommended option. Reply ≤ 8 lines: verdict, top gaps, the surprise, decisions needed, paths — the full compare table lives in doc.html, not chat, unless the user asked to see the compare in chat (then a ≤6-row table + pointer).
11. **Follow-up "teach me / full guidebook / list all tools / UI ideas":** this user learns by stage and wants tools to surface when needed, not be memorized.
   - `systems/<tool>-tools.json` = exact inventory from the incumbent's live registries (Hermes: see `hermes-agent` Scope & Verification) with the user's on/off status — never a hand-typed list.
   - `systems/guidebook.json` = one row per SDLC stage (0 setup → understand → scope → design → isolate → implement → debug → verify → review → PR → CI → merge/clean → learn): `goal · ui (where to look/click + shortcut) · commands · agent_tools · skills (the user's own) · gate · watch_out · signals (what tells the app you're in this stage)`. Build `systems/skills-index.json` (name → description → path from each SKILL.md) and make the render FAIL if a guidebook skill isn't in it.
   - `systems/ui-ideas.json` = ideas (`inspired_by · you_see · pops_up_when · data_from · build (plugin vs core) · effort · value · rank`) + a `triggers` table (signal → stage → suggest). Rank a zero-code option first (Hermes: stage skill bundles), then one plugin.
   - Mockups are generated from REAL state snapshotted into json (`git worktree list --porcelain`, `git diff --shortstat main...<branch>`, `ledger board --json`), clickable (embedded json + tiny JS), labelled MOCK with which signals are not wired. Emit a `.widget.html` twin for `::preview`.
   - Pages: `guidebook.html` (tabs guidebook · ui ideas · all tools · commands · surfaces) + `ui-mockup.html`, written by a `render_guidebook.py` module that `render_docs.py` imports and calls, so one command renders everything.

## Comparing the user's product with trusted offerings (Raymond's format)

Raymond named ai-memory's README and `docs/comparison.md` as the model ("i like the way they describe problem analyze other gofferings, coming from other tool, and their unique contributions", 10-29). Write it in this order:

1. Why: the limits of what the reader already has, each with testimony.
2. How it works, as one line.
3. Camps (approach · who · strength · trade-off).
4. Coming from another tool: similar · gain · give up.
5. What the field independently agrees on.
6. What we take, and where.
7. Where we're behind.

Say which choices are now common and no longer the pitch. Write "not found among N", never "unique".

Research children's quotes are self-reports: 10 of 79 in Mole's pass weren't on any saved page (LinkedIn posts, Reddit or Gartner seen only in search caches). The renderer must find every quote on a saved page, splitting on ellipses, and drop what it can't.

## Reporting a tool trial (Raymond's format)

Raymond asked a trial chat for this, and accepted the answer (Mole `systems/tool-trials/metrics explained.md`): "waht were the metrics exactly how did you get them in first palce what is it measuring core do those tools themsleves advwerrtise those epsecialy in recent blogs lets say. and then whats the ucrrent result can you like use tables or something. also what do the results indicate exactly both themselves and larger implciations". For each metric, write:

- what it is exactly, and where its bar came from;
- what it measures at its core;
- whether the tools advertise it (a dated quote, preferably from a recent blog post, changelog or README);
- the current result, in a table;
- what the result says about the tool;
- what it means for the user's project: borrow, integrate, build or skip, and which task or idea it changes.

Score tools on the same frozen keys as the project's own tasks, so the numbers compare.

## Render pitfalls

- A page the user names or structures explicitly (e.g. "new page called Sequence, one big table, start to finish") is built exactly that way — the 4-section layout below applies only to the default doc.html.
- Page = exactly the 4 docs-over-chat sections: main (0 start: answer + decisions checklist + change log) · results (use-now table, then `gaps.json` with `verdict` first + value column, then workflow + per-tool comparison as h2s) · history and decisions · background (2 insights + all research detail). Never one tab per research topic or tool — research detail is background. Add a `4 log` pointer (session id + subagent log paths) at task creation.

- Starting `render_docs.py` by copying a sibling task's script inherits whatever page look it had; drop its inline css/nav and apply the current shared style from `docs-over-chat` (`doc_style.apply`) so the page matches every other doc.
- The shared `doc-style.css` hides every `<section>` without class `on`: a fresh render script must put `class='on'` on the main section and emit a few lines of JS that toggle `.on` on nav click and from `location.hash`, or the page renders blank below the tab bar.
- Comparison the user wants to "see" in chat (e.g. two boards side by side): have `render_docs.py` also write `systems/<name>.widget.html` from the same json and show it with `::preview{file=...}`; use `var(--border)`/`var(--card)` fallbacks so it themes in the chat frame. Snapshot live state (`ledger board --json`, `hermes kanban boards list`) into the json first — never hand-type board contents.
- "Make the fixes" for tier-0 items: apply with `hermes config set` (never hand-edit config.yaml), test each one live (see the guard-hook recipe in the `hermes-agent` skill's git-worktrees-and-prs reference), flip the gap's `verdict` to done + update `use-now.your_setup`, and put any habit-only fix (no config key) into the skill that governs that workflow step (e.g. the ledger skill) so it actually gets used.
- No browser tool? Confirm the page with headless Chrome, then look at the png: `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --window-size=1500,1000 --screenshot=<scratch>/doc.png "file://<doc.html>#<tab>"`.
- Parsing SKILL.md frontmatter for an index: strip quotes from `name:` (`name: "playwright"` is common) and skip `node_modules/`, or real skills silently go missing and package-bundled ones take their place.
