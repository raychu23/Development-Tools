---
name: merge-files
description: Use when 2 versions of a skill or text file must become 1 (same-name skills from an outside repo, an upstream update, 2 agents' edits). 3-way merge against the recorded base, keep the best of each hunk, source-tag every kept part, A/B the result.
metadata:
  source: own
  takeaway: "3-way merge against the base, never drop his lines silently, keep it only if A/B not worse"
---

```notes
merge-files      raymond 2026-10-17: "i wont say never load skill same name merge keep what makes sense"
    why no tool             research 10-17 (T18 systems/research-provenance-merge-evals.md): no established skill-merge tool, only tiny repos
                            mergiraf has no markdown · weave (1.3k★, markdown-aware) = untried, trial OPEN
    1 base                  outside skill: the clone's own git history (git -C <clone> log -- <path>, the commit you last pulled)      own vs own: git merge-base
    2 merge                 python3 systems/merge-skill <ours> <theirs> --repo <clone dir> --commit <locked sha> --path <path in repo>
                            → <ours>.merged w zdiff3 hunks (ours · base · theirs)      clean parts already merged
    3 resolve each hunk     keep what makes sense: his own words + his style win on tone · outside wins on tested technique · both if they add up
                            never drop a raymond-written line silently: moved or dropped → say where + why in the commit message
    4 tag sources           every kept outside part: python3 systems/provenance tag <file> <from> <to> <repo>   → <!-- ext <repo> --> … <!-- /ext <repo> -->
                            frontmatter stays source: own (parts carry the ext markers)
    5 one name              the merged file replaces ours (same name)      theirs stays in its clone, removed from skills/systems/load.txt
    6 measure               A/B old-ours vs merged: skills/project/sdlc/4-verify/1-evals/promptfoo/run.sh      keep merged only if not worse
    7 commit                message: what came from which repo      (Assisted-by / Chat trailers are automatic)
```
