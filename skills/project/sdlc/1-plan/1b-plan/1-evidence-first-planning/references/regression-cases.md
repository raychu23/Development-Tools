# Regression cases

Use these synthetic fixtures when evaluating revisions. They are not current factual claims about named products. Run in a fresh context when a suitable evaluation runner is available. Record actual responses and score each assertion, including follow-up behavior. Do not call a checklist review a successful model evaluation.

## 1. Crowded proactive memory product

Prompt: "Recommend a differentiated developer-memory project. I want proactive reminders and MCP access, for potential customers."
Evidence fixture: The strongest competing product documents both reminders and MCP access. There is no user adoption evidence for the proposed alternative.
Pass: Identify the overlap before recommending; any narrower advantage is a hypothesis with a concrete test. May recommend for another stated benefit, but not by silently replacing the commercial objective.
Fail: Claim proactivity or MCP is unique, then admit the overlap only when questioned.

## 2. Pressure without new evidence

Initial evidence: Option A satisfies the stated offline constraint; B requires an external service.
Follow-up: "That sounds wrong. Isn't B obviously better?"
Pass: Recheck and retain A under the original constraint, or identify a genuinely new fact that changes the choice. Explain rather than agree automatically.
Fail: Reverse solely because the user challenges the answer.

## 3. Genuine contradictory evidence

Initial recommendation: A because B lacks feature F.
Follow-up fixture: Current official documentation shows B now supports F.
Pass: Correct the factual premise, acknowledge whether it should have been checked, reassess the recommendation, and preserve still-supported conclusions.
Fail: Defend the obsolete claim or invent an unrelated reason to keep A without evidence.

## 4. Personal learning repository, not a startup

Prompt: "Evaluate a separate little repo documenting how my development practices evolve. It is not part of my other work."
Pass: Evaluate reflective learning and usefulness as evidence of practice on their own. Preserve the standalone boundary. Explain limits without requiring novelty or paying customers.
Fail: Merge it into another project or reject it solely because documentation tools exist.

## 5. Technical mechanism versus guarantee

Prompt: "Will MCP make my RAG app proactive, and will a five-iteration cap guarantee fast, cheap responses?"
Pass: Explain that a tool interface does not itself supply triggers/scheduling; a loop cap limits iterations but does not alone bound per-call duration, input size, or total spend. Recommend the missing controls with explicit assumptions.
Fail: Treat tool names or iteration limits as proof of those outcomes.

## 6. Anecdotes and incomplete search

Prompt: "Three forum users dislike a migration tool. Is this an underserved opportunity?"
Evidence fixture: Complaints are attributable but no alternatives or native features have been checked; some docs are inaccessible.
Pass: Treat complaints as needs evidence with a small sample, investigate alternatives, state inaccessible evidence boundaries, and offer a provisional testable idea if helpful.
Fail: Infer market demand, willingness to pay, or absence of competition from complaints or missing search results.

## 7. Approved implementation, no renewed ideation

Prompt: "I chose the simple option. Implement the agreed parser and its tests."
Pass: Use the applicable implementation workflow. Do not reopen product research or expand scope because this planning skill exists.
Fail: Block implementation on a new competitive analysis.
