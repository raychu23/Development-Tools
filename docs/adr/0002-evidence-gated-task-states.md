# 0002 · Evidence-gated task states

Status: accepted

## Context

Agents report "done" with failing tests, review their own work, or forget what they changed. A free-text status field can't stop any of that.

## Decision

`ledger` keeps an explicit transition table (9 states). Each move needs typed evidence flags. The ledger runs the task's checks itself in the task's worktree and refuses the move on failure. `verified` needs a reviewer who isn't the owner. `done` needs `--prevents path:line`, a pointer to the check that now blocks the mistake.

## Consequences

"Done" means proven, and the audit log (`4 log/ledger.md`, append-only) shows who proved it. Moves are slower and more verbose. A failed move undoes its own edits, worktree and branch so partial state never lands.
