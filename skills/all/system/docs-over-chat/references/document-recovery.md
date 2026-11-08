# Recover and reconcile shared documents

Use when a required document is unavailable through the current harness but the task has linked local session records or an existing export.

## Procedure

1. **Separate dependencies.** Identify which work needs the missing content and which already has authoritative inputs. Continue authorized independent work; do not make the user export everything before doing any useful work.
2. **Discover current access once.** Check the available connector and relevant logged-in application. Distinguish a missing API route, authentication, unavailable input control and required consent. A screenshot establishes visible content, not edit capability. Do not overwrite a user's unsent draft to enlist another agent.
3. **Search only task-linked evidence.** Use the document identifier or the linked owning session to locate document-create/update requests and their matching results. Restrict extraction to document payloads; do not inspect credentials or broadly preload unrelated conversations.
4. **Build a verified archival reconstruction.** Pair each request with its result by request id; include only acknowledged successful writes. Start with the original document template and apply subsequent operations in source order. Preserve tab boundaries, supported rich directives, original wording and the last observed revision. Reject ambiguous replacements or unacknowledged operations rather than guessing missing text.
5. **Verify the reconstruction.** Compare unchanged tabs against their original payloads. Check ordered modifications for reconstructed tabs and compute hashes of the exact tab bodies. Record source path, source locations, observed revisions and the explicit limitation: archival recovery does not establish current live equality.
6. **Create the requested local mirror.** Preserve all requested tabs. Refresh active paths and add current verified results without silently rewriting historical claims as current results. Keep the requested filename/format; a reader UI is supplementary, not a replacement.
7. **Reconcile with live state before writing.** Read the live tabs and current task packet again when authorized access becomes available. Merge intervening user edits, comments and other agents' work. A queue may have been launched elsewhere while access was being investigated; do not overwrite that state with an earlier no-launch handoff.
8. **Verify live synchronization.** After updating, read back the exact document and every requested tab, check the paths table and decision-critical results, then record the observed live revisions. Until this succeeds, state `local mirror current; live sync open` and name the precise remaining gate.

## Pitfalls

- Check display registration before reconstructing content. An existing file can be invisible because the focused chat's stored session id is absent from the Docs-folder registry; cwd and a Claude artifact link do not register it. Verify the registry readback and the native app's rendered page, and distinguish a pointer stub from a recovered document. Never recreate an artifact solely because the picker is empty.
- Preserve shared-file edits during commits. If a registry or feedback file has unrelated working-tree changes, build only the owned addition against HEAD in a temporary Git index and use a normal commit. Require clean staging for the touched paths, detect concurrent HEAD/index changes, then synchronize only those committed paths in the default index. Verify unrelated staged entries remain unchanged and leave other working edits intact; `git commit --only <shared-file>` would include all its working changes.
- Recover source content from successful tool payloads, not assistant prose claiming a document was created — the payload supplies the actual text and the result establishes whether the write occurred.
- Keep original archival text separate from current corrections — replacing paths or results before verifying source equality destroys the recovery audit.
- Preserve accepted concurrent changes — an old packet can be correct for the previous handoff but false about current execution.
- Keep the limitation narrow — unavailable access to one document does not invalidate completed local work or establish permanent tool incapability.
- Recover a turn that died mid-way (401 expired token, model timeout) from `~/.hermes/sessions/request_dump_<session>_<time>.json`: its `tool_use` inputs hold the lost code; diff what they wrote against disk before redoing, so finished writes aren't duplicated or overwritten.
