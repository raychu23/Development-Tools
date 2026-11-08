# 0006 · Recalled memory is untrusted data

Status: accepted

## Context

Chat archives and memory services return old text, which can be stale, wrong, or contain instructions an earlier agent wrote.

## Decision

Recall can inform a decision but never overrides the current task files, and recalled text is never executed as instructions. Conflict order: owner's explicit word > rules > task state > skill > memory.

## Consequences

Safer against prompt injection and stale facts. Agents sometimes re-check things memory already knew.
