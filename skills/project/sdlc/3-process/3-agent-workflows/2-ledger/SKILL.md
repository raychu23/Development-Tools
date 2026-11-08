---
name: ledger
description: Track every code task through Raymond's ledger (proposed → ready → running → submitted → verified → integrated → done) with systems/ledger, so state, evidence and Orca cards stay in sync. Use when starting, claiming, finishing, reviewing, merging, blocking or listing code work.
metadata:
  source: own
  takeaway: "The task file is the state: every move needs evidence, and never review your own task"
---

```notes
ledger      (code tasks only · design: ../0-start.md · contract: ../1-task-template.md · tool: CS Code/systems/ledger)
    rule                    the task file is the state      chat is only an update      every move needs evidence, lands in 4 log/ledger.md + 1 git commit
    run                     python3 "$WORKSPACE/systems/ledger" <cmd> …      -h for every flag
    start                   ledger new "<project dir>" "<name>" --goal G --done-when "examples incl 1 failure / empty case" --repo <code repo>
                            project dir = the folder that holds the task folders (Mole: <abs>/Project/Mole/tasks)      new renumbers T<n> to the next free number there
                            pass the project root instead → the task lands beside tasks/ as T1-… (Mole 10-28)      check the printed path; mv + fix the name in its files before the first move
    ready                   ledger move <task> ready --owner <worker> --boundary "<allowed paths>" --checks "<exact test cmd>"
                            + --non-goals "<what not to touch>" --proof "<artifact that will show it works>" --stop "<when to stop / ask>"
                            all 3 required on proposed → ready (new takes them too)      blocked / failed → ready: --note only
    claim                   ledger move <task> running --orca --orca-repo id:<repoId>      (or --git-worktree, or --worktree PATH)
                            CS Code repo: --git-worktree does a FULL checkout (24 GB, disk fills, eval R1 open)      make it sparse first:
                            git worktree add --no-checkout -b <branch> <dir> HEAD → sparse-checkout set --no-cone <paths> → checkout → --worktree <dir>
                            work only inside that worktree      never the main checkout
                            hermes: /goal <task goal> + /goal gate add "<same --checks cmd>"      done blocked until the check exits 0 (T7 G12)
                            test / CI file edits ask raymond first (hook ~/.hermes/agent-hooks/test-guard.py)      -q / cron runs cant edit tests
    hand in                 ledger move <task> submitted --report "<diff summary>" --checks-result "<cmd → result>" [--risks …]
    review                  fresh context, not the owner: ledger move <task> verified --reviewer <you> --findings "<findings or none>" --checks-result …
                            hermes: /review focus on correctness vs done-when, P0/P1 only, reproducer per finding      runs on claude (auxiliary.review pin) = other family than the gpt implementer
                            changes needed: ledger move <task> running --findings "<what to fix>"
                            cross-model: python3 Project/sdlc/4-verify/4-adversarial-review/challenge.py --repo <worktree> --base <base> --criteria <done-when> --implementer claude|codex --out r.json
                            keeper decides kept · dropped      adjudicate each kept finding: fix · accepted risk · refuted with evidence      stop after 2 rounds
    merge                   ledger move <task> integrated --merge "<commit / branch>" --checks-result "<combined checks>"
                            CS Code main often has raymond's staged files → git merge refuses      scoped integrate instead:
                            git diff --name-only <base> HEAD -- <branch files> is empty → git checkout <branch> -- <files> → git commit --only -- <files>
                            after several tasks land, rerun every suite + eval replay on main: tasks break each other (T8: new ready rule broke eval R1)
    close                   ledger move <task> done --outcome "<where it lives>" --resources retain|archive|cleanup --prevents …
        prevents            "path[:line] [label]" = artifact that now stops the logged mistake (AGENTS.md line · hook · skill pitfall · reviewer check · eval case)
                            path must exist in the repo (else ledger root)      stamp it with the printed [source: <task>; added: <date>]
                            "none: <reason>" only when 4 log/ledger.md has no → blocked · → failed · submitted → running
    stuck                   ledger move <task> blocked --cause … --decision-owner raymond      later: ledger move <task> ready --note …
    see                     ledger board <scope>      ledger ready <scope>      ledger show <task>
    orca                    every move sets the card (todo · in-progress · in-review · completed) + comment      no orca on PATH → the exact command is printed
    never                   edit state: by hand · skip a state · review your own task · run 2 workers on 1 task · auto-merge
```
