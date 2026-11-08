---
name: repository-migrations
description: Use when moving files across Git or symlink boundaries.
metadata:
  source: own
  takeaway: "Settle which repo versions the moved files before moving; a clean move alone is not done"
---

# Repository migrations

## When to Use

Use for directory relocations between repositories, converting a linked folder into a real folder, or moving a canonical data store while old paths and shared symlinks remain in use. For ordinary code changes within one repository, use code-work.

## Procedure

Move the canonical copy, not just the visible entry point. Before changing paths, settle ownership and versioning; a successful filesystem move is not enough.

1. **Discover the boundary.** Inspect both source and destination with `stat`, `git rev-parse --show-toplevel`, path-scoped `git status`, ignore rules (`git check-ignore`), and the actual symlink tree. Search live readers, generators, and links for both paths. Separate historical evidence from current routing.
2. **Decide the target contract.** State which directory is canonical, which old paths need compatibility, which links remain shared, and which Git repository will version the new private files. If a move would make them unversioned or publish them in a public repo, resolve the private versioning choice with the user *before* moving; neither privacy loss nor loss of current history is an innocuous side effect.
3. **Protect and move.** Fingerprint regular files and record each symlink's resolved target. Check that the destination is empty or the expected link. Move the directory once rather than copying and deleting; rebase relative symlinks to their original targets, and add an old-path compatibility link only when it cannot loop. Preserve concurrent edits and unrelated shared files.
4. **Repair live consumers.** Update startup packets, current links, source catalogs, and generators that assert or recreate the old topology. Retain old paths as historical evidence in archives; do not bulk-rewrite those. Keep the privacy policy explicit in the destination repo's ignore/tracking rules.
5. **Verify the *new* contract.** Compare hashes or an inventory, resolve every symlink, run the affected render/test/full-refresh paths, parse generated local links, inspect both Git statuses and ignore behavior, and confirm the startup packet still meets its size limit. Use `set -e` for multi-command shell checks so a later successful command cannot mask a failed assertion. Recheck after concurrent writers finish.
6. **Hand off honestly.** Name the real canonical folder and old alias, which checks passed, and any remaining versioning or portability gap. Do not claim a tracked or portable backup merely because the old repository retains historical commits.
