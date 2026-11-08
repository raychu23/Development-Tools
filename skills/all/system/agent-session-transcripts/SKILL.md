---
name: agent-session-transcripts
description: Use when reading or routing chats across all 3 harnesses.
metadata:
  source: own
  takeaway: "A big unrouted count is a detector bug: fix the script, never route fake chats by hand"
---

```notes
agent-session-transcripts      every chat session of raymond's 3 harnesses (claude code · codex · hermes) · read it · count it · route it to its task folder
    tools (CS Code)     Context/context-and-skills/T16-notes-foundation-org/c overview/systems/
                            more.py = sessions + routing      overview.py → Context/overview.md + Context/overview chats.md
                            chat routes.json = hand routes (id → folder · why · key · routed; id ending in * = prefix)      routes.py = check rows + render <folder>/4 log/chats.md
                        T16/systems/my_words.py = raymond's typed msgs → 4 log/my words.md + key table in 2 insights      --hermes <id> adds a hermes chat

    1 route unrouted chats      (order)
        a run overview.py      read the "none" rows in overview chats.md
        b sanity-check the count first      a big unrouted count = detector bug → fix more.py (root cause), rerun      never route fake chats by hand
        c per real chat: dump first 3 user msgs + last assistant msg w a scratch script (not the whole transcript, some are 100+ MB)
        d pick folder: existing task w 0 start.md > topic Context folder (Class/Context, Work/Context …)      never make a new T just to hold a chat
        e 1 row in chat routes.json: why = what the chat was · key = outcome, numbers, paths fr its last reply · guesses labeled INFERENCE
        f hermes chat → also "<id>": "<abs folder>" in Context/context-and-skills/systems/hermes session folders.json (Docs button)
        g routes.py → overview.py → git commit --only -- <own paths>
        h rerun just before commit: raymond starts new chats mid-task, a fresh "none" row is normal → route it too

    2 session stores + pitfalls
        hermes      ~/.hermes/state.db (open read-only: file:…?mode=ro)      sessions + messages tables
                    parent_session_id set = subagent → helper under parent, not a chat
                    message_count 0 = never used → skip      empty cwd = unknown → unrouted, not "outside"
                    ids start w the date (20261013_…): an 8-char prefix match hits any date text → match full id or the hex tail only
                    typed msgs = messages role=user, skip injected "[System: …" / "[IMPORTANT: …" rows      timestamp = unix → convert to UTC to line up w claude jsonl
                    cron runs = cron_<job>_<time> ids → 1 prefix route "cron_<job>_*"
        codex       ~/.codex/sessions/**/rollout-*-<uuid>.jsonl
                    read only the 1st session_meta: forks + guardians replay the parent's meta after their own, overwriting parent/cwd
                    parent_thread_id or source.subagent = helper      no user msg AND no parent = never used → skip (spawned helpers have no user msg, keep them)
                    real ask = response_item message role=user, minus <environment_context>, plugin lists, AGENTS.md preamble (ask = text after </INSTRUCTIONS>)
                    thread_source agent_created_thread = agent-run test threads → route to the project they tested
                    ids are time-ordered: 2 files can share the 8-char prefix → key routes by full id
        claude      ~/.claude/projects/<cwd-slug>/<id>.jsonl      typed msg = type user, not isMeta, string content

    3 my words (typed msgs = raymond's notes)
        cats key    "yyyy-mm-dd hh:mm" fr claude rows · "yyyy-mm-dd hh:mm hermes <hex tail>" fr hermes rows      2 live chats on 1 task can type in the same minute
        untagged row after a rerun = raymond typed in the other chat on this task → tag it (to = where it belongs), dont answer it here
        he then asks the same thing here → the other chat's answer is already in files: git log -- <task> + its 2 insights first · recheck it vs current state · add a dated recheck block, dont redo the work
        dedupe rows on (time, kind, text), not text alone      the same words typed again in another chat are a real 2nd msg

    4 writing into other tasks' folders
        only generated pointer files (4 log/chats.md) · never rewrite their 0 start
        skip folders inside a nested git repo (eg Project/Mole) and folders whose "4 log" is 1 file → the route still counts via chat routes.json
        another live chat may share the folder: patch, dont whole-file write · commit --only own paths
```
