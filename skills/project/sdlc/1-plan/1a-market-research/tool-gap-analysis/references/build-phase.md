# Build phase — user approves the build list ("build all that")

The research task stays the home; the builds become ledger code tasks under it. Recipe for running several at once with no info lost (CS Code version-control rules apply: one file per doc, every change committed, nothing deleted without git history).

## Order

1. **Split** the approved builds into ledger tasks (group builds that touch the same files into one task; keep boundaries non-overlapping). `mkdir -p <research task>/systems/code tasks` first, then `ledger new` per task with goal + done-when (incl. non-goals · proof · stop) and `ledger move ready --owner --boundary --checks`.
2. **Non-code builds first, yourself**, in the same turn: memory trims, machine config, plugin installs. For each: snapshot the current state into git (or copy to a backup path) BEFORE changing it, then append a `result` row to `systems/decisions.jsonl` naming what changed + the undo/backup path. Example: shrinking Hermes memory = copy `MEMORY.md`, `USER.md`, `pending/memory/*.json` into a git-tracked `systems/hermes memory/` folder and commit, cut, write a `routes.json` saying where each removed group lives, commit the after-state.
3. **Sparse worktree per task** (24 GB repo, little free disk): `git worktree add --no-checkout -b <branch> <dir> HEAD` → `git -C <dir> sparse-checkout set --no-cone <paths>` → `git -C <dir> checkout`. Run the checks once in one worktree to get the baseline test count.
4. **Dispatch** one delegate_task child per task in a single call. Brief: packet path, worktree, branch, exact `ledger --no-orca move … running --worktree …` and `… submitted --report --checks-result --risks` commands, commit author + trailers, "proof files go in the worktree copy of the task folder", "stay in boundary", "never move to verified". End the turn with a short status.
5. **Cross-model review** each submitted branch (different provider than the builder): `challenge.py --repo <worktree> --base <base> --head HEAD --criteria <packet rows file> --implementer claude --out <review.json>`, all branches in parallel as one background job. Read every kept finding; adjudicate: real → `ledger move running --findings "<fix>"` + re-dispatch the owner; accepted risk / refuted → say why in `ledger move verified --findings`. Expect reviewer false positives on paths through tracked symlinks and on "tests not runnable" in its read-only sandbox.
6. **Integrate scoped**: for each verified branch, confirm main hasn't touched the branch's files since base (`git diff --name-only -z <base> <branch> | xargs -0 git diff --name-only <base> HEAD --` prints nothing), `git checkout <branch> -- <those files>`, `git commit --only -- <those files>` with branch@sha + review result in the message, then `ledger move integrated --merge …` (reruns checks on the combined tree) and `ledger move done --prevents …`.
7. **Close the loop** in the research task: 0 start status per build, decisions.jsonl rows, re-render doc.html.

## Pitfalls

- Commit with `git commit --only -- <own paths>`: the pre-commit validator checks the whole staged index, and the user's own staged files can fail it. Never unstage or rename their files to get a commit through.
- A rule change in a shared tool (e.g. making a ledger flag required) breaks other tests that build fixtures through that tool; the worker may only update those fixture calls and must list them in `--risks`.
- Two tasks editing the same tool at once collide at integration; serialize them or merge one before the other starts.
- A worker's "submitted" is a self-report: read the review JSON and rerun checks on the combined tree before telling the user anything is done.
