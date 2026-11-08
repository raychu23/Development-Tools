# 0005 · One task = one folder with fixed level files

Status: accepted

## Context

Chats get compacted or end, and a new agent has to pick up the work without the old transcript.

## Decision

Every task is a folder with fixed files: `0 start` (current state, ≤40 lines), `1 takeaways` (the owner's corrections, verbatim), `2 insights` (agent analysis, labeled as inference), `3 workflow`, `4 log`. A session-start hook binds the chat to its task and injects `0 start` + takeaways as the boot packet (capped at 9,500 chars).

## Consequences

Any agent can resume from files. Writing state down becomes part of the work, which takes discipline that hooks nudge but can't fully force.
