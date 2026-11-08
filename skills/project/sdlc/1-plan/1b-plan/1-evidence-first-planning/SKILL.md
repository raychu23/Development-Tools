---
name: evidence-first-planning
description: "Develop evidence-backed project ideas, product recommendations, competitive comparisons, and technical plans under user constraints. Use when asked what to build, whether an idea is worthwhile or differentiated, which approach to choose, or to substantiate or reconsider a recommendation. Check decisive assumptions and strongest alternatives before recommending. Not for routine execution of an already approved plan or trivial factual questions."
metadata:
  source: own
  takeaway: "Check the strongest existing alternative before recommending; label unproven advantages"
---

# Evidence-first planning

Give a recommendation that survives reasonable scrutiny on its first presentation. Do not make the user discover obvious competing capabilities, unsupported assumptions, or scope changes. Accuracy means calibrated claims, not refusing to decide or refusing to correct mistakes.

## 1. Anchor the decision

- Recover the user's actual objective, constraints, exclusions, and approved project boundaries from the conversation and relevant artifacts. Ask only about missing information that would materially change the decision.
- Distinguish learning/interview value, personal usefulness, technical feasibility, and commercial demand. Evidence for one is not evidence for the others. Do not rescue a weak commercial recommendation by silently changing the objective to learning.
- An example the user gives to illustrate a point ("here's an example of …") shows their method or lens, not a feature request. Name the point it illustrates and apply it to their own documented material (their notes, issue lists) before proposing anything; promoting the example itself into the plan misreads them.
- When a user names a product as inspiration for human nuance, inspect its actual representations and workflow mechanisms—not another generic moat/features comparison. Separate the graph's documented behavior, adjacent review/memory products, and your proposed transfer. Preserve the accepted core; attach a source-backed benefit, failure case and comparison to each small refinement. Repeated historical acceptance is not proof of a good outcome or permission to change policy.
- Keep separate projects separate. Do not merge a standalone documentation/practice repository into existing work without authorization.
- For existing systems, inspect relevant code or documentation before describing implementation. Treat resume drafts, proposed designs, and past assistant statements as claims to verify, not proof.

## 2. Check what could overturn the recommendation

Before endorsing an idea, identify its decision-critical assumptions. Prioritize checks that could change the choice, not searches that merely make the idea sound attractive.

- For market/product claims, investigate the strongest relevant incumbent, native platform feature, open-source alternative, and ordinary workaround where applicable. Compare the same user and workflow, not a weak or outdated version of the competitor.
- Search explicitly for the proposed differentiator already being offered. Read current feature documentation and relevant release notes, including availability or plan restrictions. Do not conclude that a feature is absent because a search did not find it.
- For technical plans, verify decisive API capabilities, compatibility, operating constraints, dependencies, and failure modes. Separate a proposed mechanism from a measured outcome.
- For needs and adoption, look for attributable first-hand workflow descriptions, issue reports, discussions, or user research. Preserve context and sample limitations. One complaint establishes an experience, not market size or willingness to pay.
- Use current primary sources for capabilities. A vendor claim establishes what is advertised, not independent performance. Use user testimony for reported experience, not as authority on every technical feature.
- If research is blocked or inconclusive, identify exactly which premise remains uncertain and make the recommendation conditional. Do not fill gaps with confident intuition.

Keep a compact working claim ledger: claim, supporting source/date, evidence type, contradiction or limitation, and effect on the decision. Show only the parts that help the user. Never use adjacent-topic citations as proof of the actual recommendation.

## 3. Separate evidence from invention

Make these distinctions explicit where they affect the decision:

- **Verified capability:** observed in an artifact/test or described by a cited source, with that evidence boundary preserved.
- **Inference:** a conclusion drawn from evidence, with its reasoning and uncertainty.
- **Proposed feature:** something that could be built, not something the current project already does.
- **Value hypothesis:** a prediction that a particular user would benefit, adopt, or pay. State the validation needed.

Do not call an idea unique, underserved, production-ready, scalable, or commercially validated without evidence for that specific claim. A narrower audience, MCP interface, new UI, or different stack does not by itself establish differentiation. Label an unvalidated advantage at its first mention, not only after being challenged.

Creativity remains welcome. Offer original hypotheses with concrete mechanisms and useful tests. Do not demand commercial validation for an educational project or conduct an exhaustive market study for a small decision.

## 4. Make the recommendation, including its weak point

For the strongest candidate or shortlist, explain concisely:

1. The specific user/problem and why this fits the stated constraints.
2. The strongest existing alternative and the actual supported difference, or the explicitly hypothetical difference to test.
3. The important downside, dependency, or reason not to choose it.
4. The smallest implementation or validation step and the finding that would change the recommendation.

Scale detail to stakes and the user's requested depth. Prefer a few defensible ideas over a long generic catalogue. Trigger: once a plan holds more than about five unvalidated pieces, stop adding. Write one readable page (problem, what already exists, what you add, what is built, what plugs in, the one next build and how it gets tested) and park the rest. A Mole plan that grew to 19 additions, 9 pieces and about 20 open decisions was called "pure junk" by its owner. Do not invent scores, performance improvements, budgets, timelines, adoption, or hiring outcomes. Explain estimates and assumptions when estimates are useful. When the user asks what a product is worth, give worked-out metrics, not 'unknown until tested': per metric (time, cost, coverage, interruptions), today vs with it, the formula, published constants (Keystroke-Level Model operators, review pace, interruption recovery), the system's own measurements, and the one assumption that moves the number. Measure what the system itself can show before reaching for a user test (Mole: running its engine on 30 real commits showed a diff hides 86% of the call sites a change affects). Raymond 2026-10-28: "stop saying cant do unless test".

Before sending, check:

- If asked "Doesn't product X already do that?", have I checked the strongest plausible X?
- Does each decisive claim have evidence, or an explicit hypothesis label?
- Am I confusing implementation quality with novelty, or a real problem with demand for this solution?
- Have I examined the strongest counterargument rather than merely adding a disclaimer?
- Does the recommendation still optimize the user's original criteria?

If an obvious decisive check is missing, do it before answering. Stop research when remaining uncertainty would not change the advice, or when the next necessary evidence requires a clearly stated user test.

## 5. Handle challenges without automatic agreement or stubbornness

- A user's objection is a reason to recheck, not evidence that the recommendation is wrong. Do not reverse merely to match their tone or preference.
- Retain supported conclusions and explain the evidence. Revise when new facts, a corrected inference, or changed user criteria warrant revision.
- If the original answer was overstated, identify the exact unsupported claim, correct its consequences, and own the missed check. Do not pretend the original claim was always tentative.
- Never invent a new differentiator to defend a recommendation after its original rationale fails. Do not switch success criteria without saying so.
- When revising, give a short change record: what changed, why, and what still holds.
- "Have you been incorporating X?" (a pasted chat, an idea list) is answered with a ledger, one row per idea: already in the project (where) · kept in the latest version? · where it lives now · verdict with evidence. Say plainly which ones the latest version dropped. Mole 2026-10-28: the condensed one-page plan had lost one of the user's decisions. Legitimate corrections are required; false consistency is not the goal.
- Cite a user's decision by their answer, never by the question it answered. Quote a key phrase of the answer wherever the decision is cited, and re-read the answer before building on it. When the plan's center drifts, compare it with the user's own words for their focus. Mole 2026-10-28: v3 said "you decided the headline is the agent hand-back (D2)", but the answer to D2 was "lead with how Mole presents things; understand / verify / observe are fundamentals". Two versions then drifted toward PR and change review, until he asked "why this much focus on pr and change stuff".
- Before writing "skip X" or "not the product's value", search the user's own notes and decisions for X and its synonyms. If they named it as part of the goal, answer how to include it, not whether. Keep two questions apart: what the product needs in order to run, and what the user wants the product to do. Mole 2026-10-28: "skip LangGraph, the loop already runs on Hermes" answered the first question. His notes asked for the second ("Why manage agent states?", "See agent states"). He replied "werent we supposed to include … agent states".
- Before any "what already exists" list, check what's already on the user's machine: editor extensions (`code --list-extensions`), MCP configs (`.mcp.json`, harness settings), harness plugins and connectors. Name what's installed first. Installed isn't adopted: check the chat history, or ask, whether they already tried it and what they concluded, before proposing a test. Mole 2026-10-28: the plan compared ~25 tools across 3 versions, yet the closest one (AtomicViz) sat in the user's own VS Code and in the project's `.mcp.json`. He had also already tried it and rejected it ("pretty much useless"), which surfaced only after a trial of it was launched.

## Maintenance references

Read `references/methods.md` when reviewing this workflow's rationale or extending it. Read `references/regression-cases.md` when testing or changing the skill. They are not mandatory overhead for each ordinary recommendation.
