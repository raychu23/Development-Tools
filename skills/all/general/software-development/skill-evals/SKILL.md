---
name: skill-evals
description: Use when A/B testing a skill, prompt or tool's benefit.
metadata:
  source: own (CS Code, raymond + agents)
---

```notes
skill-evals      measure whether a skill / prompt / rule / outside tool delivers its claimed benefit (A/B two versions, merged vs original, before/after a shrink)
    why                     raymond wants every tool / skill / plugin measured against its claimed benefit with established eval tools
    tools                   promptfoo A/B: skills/project/sdlc/4-verify/1-evals/promptfoo (run.sh · promptfooconfig.yaml · cases.yaml · hermes_provider.py)
                            regressions: 1-evals/replay.py · system health: python3 systems/dora --days 30 (rework + change-fail rate)
    steps
        1 versions          write A and B to scratch files: git show <rev>:<path> > a.md · current file > b.md      (merge: ours / theirs / merged)
        2 cases             1 claim of the skill per case, asks shaped like his real ones (Context/1 takeaways.md §3)      mark them SYNTHETIC in cases.yaml
        3 run               REPEAT=3 sh run.sh a.md b.md      ~45 s per case-run      node via npx -p node@22.22 inside run.sh, model = hermes' own login (no api key)
                            a run longer than the 5-min execute_code cap: run it as a background terminal job with notify, not a foreground cell (the cell kills the kernel and loses state)
        4 read failures     open results-*.json reasons before trusting a score: a rubric can fail on a refusal ("no tools here") rather than the behaviour
        5 audit             snapshot git status + HEAD before the run, compare afterward and attribute changes to the eval sessions
                            undo only verified eval-owned changes, preserve concurrent user / agent work      audit generated pages and shared styles as well as commits
        6 record            per-case pass counts + verdict → promptfoo/results.jsonl (results-*.json gitignored) · task 0 start.md status
    pitfalls
        sandbox the model   cases are fake asks → provider must be tool-free and context-free: hermes chat -Q -t none --ignore-rules --source tool --max-turns 1, cwd = scratch
                            a tool-enabled agent treats them as real: edits task files, commits fake decisions in raymond's name, restyles shared docs
        dry-run prompt      without tools the model refuses to act → prompt asks "FILE ACTIONS: path → what" then "REPLY:" and rubrics grade the plan
        samples             ≥3 repeats per case before any verdict      1 sample per case swings 3/3 vs 1/3 on noise alone
        echoed input        hermes stdout echoes the prompt; keyword rubrics can 'find' planted items in the echo · strip the echoed prompt and code before grepping, then score the model's own words
        keyword rubric      a regex count is a proxy: read 2-3 raw answers by eye before trusting the count
        both fail           inspect shared failures before blaming the skill      failures can come from the rubric, absent tools/context, provider contamination or the skill itself
                            grade only behaviour the fixture makes possible      report a skill gap only after ruling out these confounds
        inference           a small observed difference is inconclusive, not proof of equivalence or no regression      report counts + uncertainty, gather more samples for consequential decisions
        scope               tool-free FILE ACTIONS evaluates proposed behaviour, not actual filesystem changes or end-to-end compliance      label results planning-only
        disk                promptfoo install ≈ 260 MB in the npx cache · check df first
        agent + real repo   measuring a TOOL's benefit for agents (not a prompt) needs real tools on a real repo: 3 conditions (no tool / tool offered / told to use it), keyed tickets written first, paired reps, harness-side accounting → references/agent-tool-ab.md
        key timestamps      write a key's 'written' field from the clock (datetime.now()), never by hand · hand-typed times drifted 9-13 min late and made keys look written after the runs
        shared machine      stop your own trial processes by pid (or screen -X quit on your own session names), never pkill -f a pattern: a pattern meant for a scratch daemon also killed another builder's test daemon
        silent green        a tool that reads 0 inputs can still print success (dependency-cruiser without typescript: 0 modules, '✔ no violations') · assert the input count before trusting a pass
        circular key        before citing any own-benchmark win: read the key's truth definition beside the system's mechanism · same signal (truth = code changed, system flags code change) = a definition, not a result
                            then score the mechanism on the field's own task + public dataset vs its published baselines → references/proving-better.md ("is ours better" asks, recognizable tests, benchmark standard)
        memory vs RAG       "do our records help a model predict / answer X": time-respecting corpus, equal evidence budget, shuffled-records control, 2 labelers + blind judge, protocol frozen first → references/proving-better.md §7b
        backtest / engine   "would it have caught later-failed changes" (SZZ / reverts, fit-check on ~6 first) · solver speed vs reference + LLM on the same instances → references/proving-better.md §7c-7d
        public bench first  a product-benefit metric ("agents follow decisions", "faster to a correct feature"): search for a public benchmark WITH a harness + scorer
                            (paper + repo, licence, last push) before designing one · add your arm beside theirs, scorer unchanged, rerun their baseline
                            on your harness (different harness = their number is context, never your control) · competitors' own benchmarks show which
                            cheap arm to include (repo search / rules file often matches a graph) · fairness: every arm gets the SAME decision text,
                            anything extra (scope, tags) only derived mechanically from that text by a script, never hand-added
        audit the scorer    before reading any arm difference from a public benchmark, open-code every failed check (why it failed) and look for scorer artefacts
                            a `git diff`-based check never sees UNTRACKED new files (most feature tasks create one): score after `git add --intent-to-add --all`
                            (a disclosed deviation), and save each run's full diff + worktree so any run can be rescored later; without them a found artefact can only be a caveat
                            report pass^k (all k epochs pass) beside the mean: equal pass^k across arms = the bench cannot separate them
                            arm setup files (the product's record dir, an injected CLAUDE.md) land in some arms' diffs but not others': exclude every arm's setup files
                            from the scored diff the same way, or rerun each grep check on the diff without them and report whether any score changed
        verifier arm        an arm with a judge or check that can force a fix: log its own counters per run (calls · flags · resumes · fixed-after-resume · tokens)
                            and compare flags with the scorer's violations on the same runs · 0 flags while the scorer sees violations = the verifier is blind, a finding independent of the score
        late arm            an arm added after the others ran (another day, other host load) is a cross-day comparison: say so as a confound, and interleave arms in the next protocol
        build on a harness  an A/B system for users = adapters on an established eval framework (Inspect AI tasks + its native logs so `inspect view` works · promptfoo for prompt A/B)
                            + stats from a standard library (scipy / statsmodels power) · not a home-grown runner
        sample size         compute runs per arm per task from the measured per-task paired-difference SD (statsmodels power) before freezing; copying the last run count is not a power calc
        pinned arms         a run that lasts hours reads the product from a pin, never the live tree: merges during the run change the frozen files
                            best pin = the SHIPPED artefact (build + `npm pack` the package, install it into the bench's scratch, record source commit + tarball sha256 in the protocol and every run record)
                            · else `git worktree add --detach` of the arm's commit · the runner refuses to start if the pin is missing or lacks the feature under test
        mechanism reach     before powering a mechanism arm (blocking hook, crisp rule) list which tasks can even trigger it (read each task's checks)
                            if few can: pre-register the mechanism outcomes as primary on those tasks (violations left at the end, fire rate, fix-after-fire rate), put most epochs there,
                            keep the all-task arm comparison secondary + descriptive · state the MDE at the chosen n honestly
                            then measure the BASE RATE of the blocked mistake in a no-context arm on those tasks (Wilson 95%) before powering any comparison:
                            a mechanism that never fires because no arm makes the mistake is untested, not a win or a loss (report "0 violations in either arm")
                            pre-register the rule (upper bound < ~20% → the bench can't test it → build seeded traps: an existing deprecated pattern the agent must not copy)
        scorer copies       a fix to the scorer lives in the file the RUNNER actually calls: grep the runner for its scorer path and test that file (a new untracked file
                            carrying the violation must fail the check) · two scorer copies drifted once (adapter fixed, runner's copy still blind)
        freeze check        name the hash file so the freeze tool's default `--check` finds it; record runner + scorer + pin hashes beside it and `shasum -c` them right before launch
                            gitignored runner copies (a private planning tree) exist per worktree: launch from the checkout whose copies were frozen
        which tests         rank every candidate test in a table on the user's named criteria (e.g. frontier × recruiter × user) + time before running any
                            baseline = the default workflow (ask the agent, tests passed), never a head-on named rival · say each test in plain words first
                            mechanism tests (precision, scale) are plumbing, not the proof · size to the stated time budget → references/proving-better.md
        human claim         a benefit for BEGINNERS (learning, comprehension) cannot be shown by agents: build a counterbalanced human study kit + scorer and ask for the people → references/human-study-kit.md
        trial round         several outside tools at once → rank a pool first (tool · which idea / workflow stage · free + local + no login · last release · why), then run the top ≤7      confirm each exists + is free before listing
                            account / sign-up tools → claims column only, logged as needs-raymond      a trial agent never signs up
                            score on the project's own frozen keys (the build loop's benches) so tool vs product numbers compare      new trial metrics get their own id family (TM9 …), never the loop's M ids
                            keys dated before the first run · check.py: keys predate runs, every evidence file exists, every number in the prose is in results.jsonl · a dated step log for the agents board
                            report per metric in raymond's format: what exactly + where the bar came from · core · what the tools advertise (dated quote, recent blog / changelog) · result table · what it says about the tool · what it means for the project (borrow · integrate · build · skip)
    report                  "A x/n vs B y/n (k repeats) · verdict · weak cases"      never call a difference real from 1 run
```
