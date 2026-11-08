---
name: load-repo
description: Use when Raymond asks to load, add, install or try an outside skill/tool repo (GitHub). Clone it named after the repo, place it by usage, link only the relevant skills, verify + eval them, and it shows in the skills map as ext <repo>.
metadata:
  source: own
  takeaway: "Link only the skills that fill a real gap, then eval them and unlink any with no gain"
---

```notes
load-repo      raymond 2026-10-17: "load whats relevant · name it the name of the repo · place it in the right place" · "i dont give a shit about license or json … list of repos and then the actual repos"
    rules
        relevant only       link what fits his topics + fills a gap      never every skill a repo ships
        name + place        folder = repo name, numbered like its neighbours, in the stage / topic where it gets used      never by source
        marker              automatic: a skill inside a clone = ext <repo> in the map      copied-in file: source: ext <repo> <url>
                            part of a file from a repo: <!-- ext <repo> --> … <!-- /ext <repo> -->   (python3 systems/provenance tag)
        same name           merge, dont skip: merge-files skill, kept outside parts get ext markers
        keep it simple      no json, no license files, no lock files      the map + the clone are the record
    steps
        1 look              what it does, stars, last push      dead or tiny → say so first
        2 clone             sh systems/add-repo.sh "<url>" "<usage path>/<n>-<repo>"      gitignored, own .git
        3 pick              python3 systems/repo-inventory "<dir>"   (prints skills + prompt cost, writes nothing)
        4 load              add kept paths to skills/systems/load.txt:  <path>      # → <category folder> · <why>
        5 sync + map        sh systems/sync.sh · python3 systems/skills-map      repo + skills now in skills/0 start.md + Context/overview.md
        6 verify            hermes chat -q "load skill <name> with skill_view, reply its first heading" --oneshot      no "Ambiguous skill name"
                            python3 systems/provenance check
        7 eval              does it deliver its claim? skill-evals skill (promptfoo A/B, tool-free, repeat ≥3) on the metric that matters      no gain → unlink
        8 commit            skills/.gitignore · skills/systems/load.txt · skills/0 start.md
    report                  "kept N of M · +T tokens/prompt · eval: A vs B" in 1 line
```
