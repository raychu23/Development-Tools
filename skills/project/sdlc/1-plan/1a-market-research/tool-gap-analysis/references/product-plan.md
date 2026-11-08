# From research to a reviewable product plan

Use when the user has stated their own product vision (accepted as USER decisions) and asks to build it out. Do not re-judge the vision by competitor overlap: research is background, competitors are features to borrow, components to embed or tools to pair with.

## Procedure

1. **New task folder** (`product-plan/`), full docs-over-chat skeleton in the first turn, `research/` symlink to the compare folder, chat link re-pointed. Log the ask verbatim.
2. **Structure by the user's own stages** (e.g. editor surface → agent plugins/MCP/hooks → infrastructure), not by research groups. Name customers with job + pain, primary first.
3. **One shared core model** that every surface reads (layers · source · where stored · statuses), then per stage the components.
4. **Every component = `backend` + `benefit` + `evidence`.** Backend is the concrete mechanism (API events, storage path, what runs where, what is deterministic vs LLM). Benefit is the customer gain or tangible saving in plain words — the user requires each decision to pay off concretely; cut a component that has none. Evidence = doc URL or research file path.
5. **Verify decisive platform capabilities in current primary docs** before planning on them: editor API events, agent hook events + payload fields (e.g. whether subagent tool events carry an agent id), plugin bundle contents, protocol features (MCP resource subscriptions). Many doc sites serve raw markdown at `<page>.md`; curl and grep headings. VS Code: grep raw `src/vscode-dts/vscode.d.ts`.
6. **Decisions** for the user: `question · options · recommend · benefit · status OPEN`, recommendation first. **Milestones**: each with a pass/fail acceptance and what it proves; put measurement (token savings, learning benefit) here, never as a claim.
7. **Weak points** (latency path, mapping accuracy, dependency risk, scope) in `2 insights.md` as INFERENCE.
8. **Adversarial gate:** dispatch a fresh challenger with the user's accepted criteria listed, asking for a concrete failure case per finding (or no finding), missing backend pieces, and benefit claims without mechanism; output `systems/review.json` (`verdict · findings[id, target, severity, failure_case, evidence, fix] · no_finding[] · missing[]`). While it runs, end the turn with the draft summary.
   - Fold every finding into plan.json: each touched component/backend piece/milestone gets `review: [F<n>]`, missing backend pieces become a `core_backend[]` section (`id · name · backend · benefit · review`), and `review: {verdict, by, adjudication}` records what was accepted or disputed (with evidence). Make the validator fail when a finding is cited by nothing or a cited id doesn't exist — traceability is what lets the user trust "all findings folded in".
   - Spot-check the challenger's decisive doc claims yourself (curl the `.md` doc page, grep) before accepting them.
   - A fix that changes a design the user stated (e.g. three side-by-side panes → one layered canvas) keeps the user's intent and becomes a new OPEN decision with the recommendation, never a silent rewrite.
9. Update the product's startup file `next` line to point at the plan; reply ≤8 lines (core idea per stage, what was verified, decisions with recommendations, path). Version the plan in `0 start` change log (v1 draft → v2 after review → v3 after the user's decisions).
10. **User decision round:** the user often accepts recommendations in bulk ("go with rec overall") and adds a criterion. Flip those decisions to `status USER` with an `accepted` note in plan.json, the product catalog and both startup files (verbatim in takeaways). If they name a tool for a role it doesn't fill (e.g. an agent-orchestration framework as the code-graph engine), record their underlying criterion (popular, industry-standard, job-relevant), say plainly what the named tool is for, propose tools that fit both role and criterion with `gh api` traction/license, keep that decision PROPOSED until the measuring milestone, and give the named tool the role it does fit. A new surface they ask for ("a sidebar for agents too") becomes a component with backend + benefit, not a chat-only answer.
11. **Offerings page (customer → problem → offering → proof).** When the user asks for a page that grounds every feature in a problem, build it from `systems/offerings.json` as ONE page in the user's order, named exactly what they call it (e.g. `Sequence.html`), no tabs:
    1. customers + their day-to-day workflow as numbered steps · 2. issues with evidence + source (published studies/surveys, research files) · 3. per issue: existing options, best combination today, gap left · 4. what the product contains, layer by layer (in it? · which projects need it · what it contributes · tools that do it today) · 5. **ONE big table**: a bold stage row then its feature rows, identical columns (`# build order · stage/feature · solves issue / builds on · how · benefit · diff from competitors · integrates with existing tools/workflow · tools needed + how to build · time · milestone · metric · verdict · why it earns its place`), go/no-go gate rows inline · 6. build sequence start → finish (# · milestone · step) · 7. integrations with today's popular tools (agent harnesses, LangGraph via MCP adapter, diagram-as-code, CI/PR, trackers) · 8. claims: metric · today's baseline · mechanism · projected gain · type (hypothesis/target/guarantee) · basis (closest published number, often another tool) · measured at milestone · 9. considerations (juniors, seniors, PRs, large teams/monorepos, agent-heavy work, each SDLC stage, licensing).
    - Validator refuses to render when a feature has no issue and no `builds_on`, a non-core feature has no `fight` (case for inclusion), an issue has no options row, or build order has gaps — this is what makes each feature "fight" for its place.
    - Don't split the big table into per-stage tables or put stages in a separate table; don't invent a page name or tabbed layout — the user asked for one table and one sequence and will reject the reorganised version.
    - Effort = rough solo-FTE weeks, labelled ESTIMATE; projections are hypotheses until the milestone measures them.
    - When the user asks "does it include X? does every project need it?", answer with the layer table: a layer the plan lacks gets added as a `maybe` feature with its case, and state the rule that layers appear only where they exist for the open file, so projects never pay for layers they don't have.

## plan.json

```json
{"status": "PROPOSED ... built on USER decisions <ids>",
 "customers": [{"id": "C1", "who": "", "primary": true, "job": "", "pain": ""}],
 "core_model": {"idea": "", "layers": [{"layer": "", "what": "", "source": "", "store": ""}], "statuses": []},
 "stages": [{"stage": 1, "name": "", "goal": "", "components": [{"id": "S1.1", "name": "", "backend": "", "benefit": "", "evidence": ""}]}],
 "decisions": [{"id": "P1", "question": "", "options": [], "recommend": "", "benefit": "", "status": "OPEN"}],
 "milestones": [{"id": "M0", "name": "", "acceptance": "", "proves": ""}]}
```

Validator in `render_docs.py`: stages in the user's order; every component has non-empty backend/benefit/evidence; unique ids; decisions have options + recommend + benefit + allowed status; milestones have acceptance; relative evidence paths resolve (write them relative to the plan folder, through the `research/` symlink). Page results tab: decisions table first, then customers, core model, one table per stage with the benefit column before backend, milestones.

## Recurring design rules for developer tools

- Nothing slow or paid on the interactive path (file switch, cursor move): local deterministic queries only; LLM work on demand, cached by content hash, labelled inferred.
- Generated artifacts gitignored; human-intended models committed and reviewed in PRs.
- Agent edits to intended design go to a human review queue; code changes stay proposed tasks unless the user approves automatic edits.
- Adopt an existing engine behind your own schema with a pinned version, picked by a measured spike that measures recall against the language's own compiler/language service, not only hand-checked edges (tree-sitter alone misses callers through re-exports and path aliases).
- Put these in the FIRST draft — a challenger reliably finds them missing otherwise:
  - one local daemon per repo as the single writer; editor extension, MCP server, hooks and CLI are thin clients (else double indexing + SQLite lock errors)
  - anchor identity that survives renames/moves (qualified name + path + kind + signature hash, git rename detection) and a cold-start bootstrap for repos with no existing diagrams
  - an exact drift/violation rule (what satisfies an edge; tests, type-only imports and planned edges excluded)
  - surface width: an editor sidebar is ~300 px — one layered canvas plus a full-view panel, not several side-by-side diagrams
  - agent activity via hooks misses shell (Bash) reads/edits: add git-diff snapshots at subagent start/stop, coverage levels, and "touched" not "checked" against an explicit scope
  - numeric latency budgets (interactive path, each hook) with fail-open, and injected agent context counted as a token cost
  - privacy: code to an LLM only with per-repo consent; agent activity stores ids/paths by default
  - an early go/no-go milestone with real target users and the cost test, before building the editing/propagation layers
- Agent-facing visual surfaces: build one renderer and host it in every shell (editor panel, desktop-app plugin pane, MCP Apps `ui://` resource, localhost page for terminal agents) rather than one UI per harness; don't rely on MCP resource subscriptions reaching the agent mid-session — push via hook `additionalContext`.
