# 0004 · Hooks over prompts

Status: accepted

## Context

Rules written into prompts fade in long chats and get skipped. The same correction kept coming back.

## Decision

The 2nd time a mistake shows up, it becomes code: a hook, lint or test (for example `test-guard` on every write, `provenance` on every commit). Rule text is the last resort. Hook configs for each harness live in `hooks/` and call the same Python entry points.

## Consequences

Enforcement doesn't depend on the model remembering. Every hook must fail open (exit 0 on its own errors) so a bug never blocks a session.
