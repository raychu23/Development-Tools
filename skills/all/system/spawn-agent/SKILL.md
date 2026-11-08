---
name: "spawn-agent"
description: "Spawn a fresh agent session with its own brief (core duties, objective, context, output, limits) when Raymond says 'spawn:' or wants a new direction split off from a chat."
metadata:
  source: own
  takeaway: "Write a standalone 0 start.md brief; never delete the trigger, it deletes the session"
---

# Spawn a fresh agent (new subidea or fresh session)

Use this when Raymond says `spawn: <direction>`, when the topic switches inside a chat (a new subidea), or when the current session's context is ~60–70% full. It follows `~/Desktop/CS Code/rules.md` (§2 naming + levels, §3 level files + fresh session). Read rules.md first; if it disagrees with this skill, rules.md wins.

## 1. Decide which case
1. **New subidea** (topic switch inside a task): create `c <subidea>/` in the task folder. The previous current subidea becomes `o <name>`.
2. **Fresh session, same subidea** (context full): no new folder; refresh the subidea's `0 start.md` and launch from it.
3. **New task** (a new big goal): a new folder `T<n>-<name>` inside its project (n = next free number in that project). Each agent run on it is `T<n>-a<n>-<job>`. Ask for the task number only if it can't be inferred; otherwise pick the next free one and say so.

## 2. Write `0 start.md` (the brief), ≤40 lines
1. **came from**: the parent task or subidea path.
2. **core duties**: from the project README / AGENTS.md / rules.md and Raymond's prefs (numbering + a/b/c; code: own branch, test, review; class: follow instructions stringently; lit review: verify, rank, cut down).
3. **goal + done-when**: the new direction, with numbered deliverables.
4. **context to load**: only what's needed. Include items Raymond pinned; leave out what he dropped. Name the skills to load first.
5. **output**: exact files and where they go. Results go into the task files (`1 takeaways` for Raymond's fixes, `2 insights` for agent diagnosis, `3 workflow` for back-and-forth patterns).
6. **limits**: what not to touch, when to stop and ask, a timebox, and "Raymond may not be watching: make reasonable choices, state assumptions".

## 3. Save with version control
1. On the Mac (CS Code is a git repo): write the folder and `0 start.md`. Rename the old subidea's prefix `c` → `o` and fix links to it, in the same commit. Commit with a message naming the subidea and why.
2. Never create v2/copy/.bak files: one latest file, history in git.
3. If the Mac isn't linked, save to the attached project as `claude/agents/<name>/0 start.md` and say it still needs committing.

## 4. Launch the session
**In Hermes (Raymond's main harness, verified 2026-10-28):** a new chat that shows in the desktop sidebar under the project is a CLI session whose cwd is the project folder.
- Write the prompt to a file ("read your brief at <path> and do it"), then start it detached: `screen -dmS <name> bash -c 'hermes chat --query-file <prompt> --in "<project dir>" -m <model> --provider <provider> --source cli --run-budget <seconds> -Q > <scratch>/run.log 2>&1'` (screen, because tmux and some forks crash on this Mac).
- Always pass `-m` and `--provider`: the CLI uses `model.default` from `~/.hermes/config.yaml` (a small free model), not the desktop chat's model. Model for spawned agents: `-m claude-sonnet-5 --provider anthropic` (Raymond 10-29: "make sure future agent spawns use sonnet. at least for now"); their `delegate_task` subagents follow `delegation.model` = claude-sonnet-5 in config.yaml.
- Cost: `estimated_cost_usd` in state.db is an API-price estimate. Raymond's Hermes runs on his Claude subscription, so report it as usage ("≈$X at API prices, not billed"), never as money spent.
- Always pass `--source cli`: a non-TTY `-q` run is otherwise tagged `oneshot`, which the sidebar hides (`_PROJECT_TREE_EXCLUDED_SOURCES`). It shows as `local` once it ends.
- Check it in `~/.hermes/state.db` (`sessions`: id, source, cwd, model). Archive a false start with `hermes sessions archive --source local --cwd <dir> --after 30m --model <m> --include-open --yes`, which hides it without deleting anything.
- Map the session id to its folder in `Context/context-and-skills/systems/hermes session folders.json`.
- Worker agents on a ledger build each get a main file (Raymond 2026-10-29: "for each to have their own main file at least with sections including a main info/handoff, progress timeline, further work"). Add the agent to the project's registry before launch, then generate its file and a board of active and upcoming agents from `state.db` and the ledger; the agent writes only under its `Handoff notes`. The board flags a task still 'running' after its chat stopped (the ledger state alone hid this for 4 h). Example: Mole `context/agents/build_agents.py`.
- A builder can die silently mid-turn: its `run.log` ends with "Gateway disconnected; turn outcome is unknown" plus the session id, its screen is gone, and `state.db` shows its last message hours old with no final answer. Before trusting a "working" board row, check `screen -ls` and each run.log tail. Revive it with `hermes chat --resume <id> --query-file <note> --in <dir> -m <model> --provider <p> --source cli -Q` in a new screen; the note says the cut wasn't its fault, to re-check state first (git log/status in its worktree, the status script, its runs.jsonl), then continue its original brief. Don't relaunch it as a fresh chat: it would redo claimed work.
- To change its plan mid-run, don't kill it. The CLI only fronts the session: SIGINT ends the client, but the agent keeps working until its turn ends. `--resume` also refuses launch-only flags such as `--run-budget`. Instead, write the new plan to a file and resume the same chat once it has given its final answer: a no-agent cron watchdog (`cronjob_manage` with `no_agent`, a script that checks `state.db` for a final `stop` message, plus a marker file) launches `hermes chat --resume <id> --query-file <plan> --in <dir> --source cli -Q` exactly once.

**In Claude's app:**
Use `create_trigger` with `initiation: human_request` and `run_once_at` about 2 minutes ahead (get the time with `date -u`). It disables itself after firing.
- The prompt must be **fully standalone**: paste the whole `0 start.md` inline, plus "read ~/Desktop/CS Code/rules.md first" if the session will have the Mac. Spawned sessions are not bound to the project; tell the agent to read and write project docs only "if you have a Projects tool".
- Set `requires_local_device: true` only if the agent must touch files on the Mac.
- Name the scheduled task `Spawn: <name> <short job>`.
- **Never delete the trigger afterwards.** Deleting a trigger deletes the session it started.

## 5. Confirm and report
After it fires, check `list_triggers` (with `include_completed: true`) for `last_run.session_id` and status. Tell Raymond in one or two lines: which folder was created, that the session is running as its own session he can open from his scheduled-task runs, and which file its results will land in.

## 6. On return
Fold the results into the task files (`1 takeaways`, `2 insights`, `3 workflow`) and commit. Don't paste the agent's transcript into the parent chat; the files are the record.