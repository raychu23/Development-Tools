---
name: code-walkthroughs
description: Explain an existing programming lab or code flow for learning by connecting assignment parts or functions to a concrete trace, short source excerpts, and why each step matters. Use for code comprehension, not as a substitute for implementation or correctness review.
metadata:
  source: own
  takeaway: "Trace one real input through the code so the reader can predict what each part does"
---

# Code Walkthroughs

## 0. Aim

Help the reader predict what the code does on a concrete input and reconstruct how its parts connect. Keep the main explanation compact; expand only the part the reader asks about. Prefer the actual assignment, board diagram, starter, and current implementation over generic language tutorials.

## 1. Establish the map

- Read the relevant prompt and code before explaining their relationship. Separate what the assignment requires, what the code implements, and what has been tested.
- Start with one small flow using a real input and the names from the prompt or code: `malloc(27) → choose 32 → take a slot → free it → reuse it`. If a board diagram is supplied, keep its physical layout and pointer arrows recognizable.
- Name the object, units, and role of each value at first use. Distinguish requested bytes, class size, page size, list index, offset within a page, and absolute address. Show a short numerical conversion when one becomes another.

## 2. Walk the parts in the reader's order

For each assignment part or function, use this compact pattern when it helps:

1. `### Part B — Get a slot from that row`: one action-oriented heading.
2. A short `c` code excerpt containing the active lines that perform that action. Preserve real variable names and statement order. Label omitted guards or loops; never make an excerpt with `...` look like complete code.
3. Two to four sentences: **what changed** on the running example, **why** those lines are needed, and how they connect to the previous/next part. Link the exact source function or line when available.

Use a tiny before/after diagram when pointers or state change. Show both the physical slots and the logical freelist if confusing them would change the answer. For `node->next = head; head = node`, show the old head becoming second; do not say merely that a node was “added.” Explain casts and arithmetic as address operations, not movement of memory.

Keep snippets short for an overview. Mark stale comments, dead code, or redundant branches so the learner knows what actually runs. Preserve relevant edge cases such as `NULL`, allocation failure, boundaries, and assignment-specific exceptions; do not add a general-purpose edge-case inventory.

## 3. Match the requested depth

- **Overview:** one flow plus a small excerpt and worked result for each part. Avoid repeating full functions.
- **Specific confusion:** answer the questioned operation first, then draw one state transition or calculation; do not replay the whole lab.
- **Line-by-line:** cover every active statement and necessary setup in the requested range. Skip boilerplate only with an explicit scope note.
- **Full code:** provide complete functions and required declarations, with no placeholder `...`. Distinguish verbatim code from a cleaned teaching version, identify any omitted dead branch, and include the assignment's relevant edge cases.

If the user asks whether code works, verify with the appropriate build/tests when possible. Report source inspection and runtime evidence separately; neither a plausible trace nor a structural skill check proves correctness.
