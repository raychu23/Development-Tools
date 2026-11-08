# 0003 · Advisory locks + leases for concurrent agents

Status: accepted

## Context

Several agents can run at once against the same repo. Two of them editing one task folder corrupts it, and a crashed agent must not hold a task forever.

## Decision

`agent_core` takes `fcntl` advisory locks around every store write and hands out writer leases (default 900 s, max 1 day) scoped to paths. Overlapping scopes are refused. Expired leases free themselves.

## Consequences

Race behaviour is tested with real processes, not mocks (`tests/test_agent_core.py`). Locks are advisory: a tool that skips `agent_core` can still write, so hooks route writes through it.
