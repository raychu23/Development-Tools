# 0001 · Plain files + git over a database

Status: accepted

## Context

Agents in 3 different harnesses and I all need to read and change the same state: task status, decisions, corrections. A database would need a server, a schema migration story, and a separate viewer for me.

## Decision

All state is markdown and JSON/JSONL in one git repo. Tools write through `ctx`, which makes each change one commit and waits on `index.lock` instead of failing.

## Consequences

History, diff, blame and rollback come free. Any agent can boot cold from files. The cost: no queries across tasks without a scan, and concurrent writers need explicit locking (see 0003).
