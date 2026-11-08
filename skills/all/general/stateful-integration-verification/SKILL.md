---
name: stateful-integration-verification
description: "Verify a fix against a live DB or queue end to end."
metadata:
  source: own
  takeaway: "A reused live service carries state from earlier runs that masquerades as a bug in the code under test; start fresh per verification pass"
---

# Stateful integration verification

Covers the step after unit tests pass, where you actually run the system against a real database, queue, or broker to prove a fix works end to end — not a replacement for a project's own verification workflow, a narrow addition to it.

## When to use

- You are about to verify a fix or feature by running it against a real, stateful service (Postgres, MySQL, a job queue, a message broker) rather than a mock.
- A benchmark or timing number you measured is about to be written into a document that outlives this session (a report, a resume line, a spec).
- A terminal `cd` or relative-path command fails against a directory you are confident exists.

## Use a fresh instance per verification pass

A long-lived or reused instance of a stateful service (Postgres, a job queue like pg-boss, a broker) accumulates state from earlier debugging sessions or other test files: failed jobs sitting in retry/backoff, stale rows, orphaned queue entries. When you then run a fresh verification against that same instance, the leftover state collides with the current pass — a FIFO job queue, for example, serializes behind an old failing retry and its backoff delay, making a correct fix look slow, stuck, or broken. The failure is about leftover state, not the code under test, and chasing it as a code bug wastes the verification.

Stand up a fresh instance (new data directory, fresh database/schema) for the one verification run, but prove its isolation before startup and mutation:

1. Enumerate every store the launcher and children can reach: credentials, profile roots, singleton fallbacks, migrations, and startup cleanup. A temporary `HOME` or service-home environment variable is a configuration request, not an isolation boundary.
2. Use fabricated records from the documented schema; do not read or copy live access/refresh tokens to construct fixtures. For a handler-level mapping test, inject the pool and persistence boundary before auth initialization rather than booting a full production gateway.
3. Resolve effective storage paths inside each child before the first write, and enforce denial of live-store access with a filesystem sandbox or an injected persistence boundary. If that denial cannot be established, use the bounded seam and mark full-process verification unverified. A dead proxy does not prevent disk writes; comparing a live-file hash afterward detects damage too late to protect it.
4. For an explicitly authorized live mutation, establish a protected rollback copy and its restoration scope before writing. Keep credentials out of Git, task documents, transcripts, and model-visible output. Never restore an entire shared credential store over unrelated concurrent changes.
5. Stop immediately if fixture rows disappear, paths resolve outside the sandbox, or live credentials change. Terminate owned test processes, disable the unsafe runner, and investigate read-only; prioritize restoration over the original feature. Do not retry a failed isolation setup to improve the metric.

Only after these gates pass, run the integration and tear down its owned resources. Confirm the fix on the clean instance before drawing timing or correctness conclusions.

On macOS with Homebrew Postgres, `initdb`/`pg_ctl start` can fail with "postmaster became multithreaded during startup" under the default locale; run both with `LC_ALL=C` set to avoid it.

If an approval gate blocks a test/CI edit, honor that boundary: obtain approval or run an already-authorized read-only check. Do not switch tools or use shell writes to bypass the gate; changing the write mechanism does not authorize the edit.

## A queue/job test that mocks the consumer only proves the producer side

A webhook, event, or job-enqueue test that stubs or mocks the worker proves the message was accepted and queued — it does not prove anything ever drains it. A missing `consumer.on(...)`/`worker.process(...)`/`boss.work(...)` registration in the real production entrypoint can sit unnoticed indefinitely because every unit test exercises the producer in isolation. Verify producer and consumer together against a live queue at least once: enqueue for real, then assert the downstream side effect (a database row, a file, a sent reply) appears — not just that the enqueue call returned success.

## An entrypoint guard (`require.main`, `import.meta.url === ...`) only runs when the file is actually executed as main

Tests that import a module's exported functions directly (`import { buildApp } from './index.js'`) never execute that module's own "am I main" check, so a broken guard (a string comparison that silently never matches, e.g. because the path contains a character the two sides encode differently) stays green in every test forever while the compiled binary does nothing when actually run (`node dist/index.js`). To verify an entrypoint guard, run the built output directly as a subprocess and confirm the expected side effect (a listening port, a log line, a process that stays alive) — don't trust a test that only imports the module's named exports. For Node ESM specifically, compare with `pathToFileURL(path).href`, not a hand-built `` `file://${path}` `` template; the latter does not percent-encode characters (e.g. spaces) that `import.meta.url` does, so the comparison silently fails on any path containing one.

## Benchmark numbers drift with host load — reconcile before calling a doc done

A benchmark or speedup number written into a durable document (a report, a resume line, a spec) outlives the run that produced it. If a later run reproduces the same metric again — a rerun, a different session, a different machine under different load — reconcile the document against that latest run's log before calling it current; do not leave an earlier number standing once a fresher real measurement exists. When the metric is wall-clock and sensitive to host load, a 2x-3x spread across real reruns of identical code is normal under contention: report the range actually observed plus the latest value, not a single cherry-picked number, and state what target the range still clears.

## Shell working-directory state can get corrupted independently of your commands

When a `cd` fails against a directory that should exist (a worktree, a temp dir, another process's own cwd), the terminal's own working-directory state was corrupted by an earlier command's side effect — for example, a prior subprocess changed into or deleted a directory that no longer exists, and the shell is still pointed at it. Pass the target directory through the tool's own explicit working-directory parameter instead of chaining `cd` in the command string; that bypasses the corrupted shell state rather than fighting it, and confirms real `pwd` before trusting further relative paths in the same session.

## After a verification pass finds multiple fixes, commit them one concern per commit

A single verification session often turns up more than one real defect (a missing worker registration, an unrelated entrypoint bug, a version bump). Default to a separate commit per concern from the start — even unprompted, and especially once the user has said they want smaller commits — rather than bundling everything the session touched into one commit. If a bundled commit already landed and is confirmed NOT pushed or shared (check `git status -sb` / `git log origin/<branch>..HEAD`), split it with a targeted rebase instead of rewriting the whole branch:

```bash
git branch backup-before-split main   # safety net, delete once the split is verified
GIT_SEQUENCE_EDITOR="sed -i '' '1s/^pick/edit/'" git rebase -i <commit>^
git reset HEAD^                        # un-commits just that one commit, changes stay staged/in the worktree
# stage + commit concern 1, then concern 2, etc., building/testing between each
git rebase --continue                  # replays any commits that were already on top, unchanged
```

Before deleting the backup branch: `git diff backup-before-split main` must be empty (identical resulting tree) and the project's own check command must still pass. Never do this on a commit that might already be shared — splitting shared history rewrites it out from under anyone who pulled it.
