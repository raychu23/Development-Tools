---
name: prior-art-first
description: "Use before building, fixing or measuring anything non-trivial. Search the best existing work first; build only the gap."
metadata:
  source: own
  takeaway: "Never invent an approach, metric or test design: find how the field already does it, cite it, then build only what's missing"
---

```notes
prior-art-first      (core · every harness · every task that builds, fixes, designs a test or picks a metric)
    rule                    before the first line of code or the first answer key: find the best existing work on this exact problem      build only the gap
    why                     raymond 10-29: "again dont just make shit up pls for any given issue search up all th ebest resources alaready availble before you start building.
                            this should be a core skil or somehting baked in"      REPEAT of rules.md §5 'before building'
                            seen: a matcher threshold fitted by hand (Mole T19), a record→line match guessed (T32 0.63 precision), a too-easy test (T30 tie at 15/15)
    when                    a new feature · a fix that failed once · a metric, benchmark or answer key · a design choice · "how should X work" · a resume or pitch number
    steps
        1 name it           the field's own term for the problem (rename detection, traceability link recovery, test impact analysis, program comprehension study …)
                            several synonyms → one query each
        2 search            papers (arXiv, ACM/IEEE, Google Scholar) · open-source implementations (GitHub, by stars + recent commits) · vendor docs, engineering blogs,
                            changelogs (recent first) · public benchmarks and their scoring      ≥5 primary sources, fetched, not snippets
        2b recency          AI tooling moves in weeks (raymond 11-01: "placing more emphasis on newer sources … some nuance"): date every source
                            tools, benchmarks, stars, SOTA → last ~3-6 months first · re-check live numbers (API stars, leaderboards), not the post's
                            older sources only when they define the task, dataset or method · say why it still holds
        3 save              <task>/4 log/prior-art.md: approach · who uses it · their reported numbers (dated) · fits us? · what we borrow      pages saved under research/ with URL + date
        4 pick              the approach with the best evidence for our case · our metric = the one the field reports (same name, same scoring) so numbers compare
                            a published bar or baseline beside every target
        4b fit check        a pattern from another company or field is a hypothesis, not a design (raymond 11-01: "critically evaluate first … then integrate if proven good")
                            why it works THERE (conditions) → do they hold HERE → evidence for + against → fits · test first · doesn't fit
        5 build the gap     reuse a library or published method before writing our own · say in the commit or contract which source it follows
        6 nothing found     write the queries tried and where · then label the design INFERENCE · never present a guess as standard practice
    product claims          before any feature pitch, product page or resume line: search competing PRODUCTS, not only papers (funded startups + their roadmaps, OSS by stars, platform built-ins)
                            table per claim: closest existing · what it does · our difference · verdict unique / better / exists      exists → integrate or read its data, never rebuild a worse copy
                            raymond's products (said 3×, 10-29 D47 → 10-31): his USP = EASE, one tool in the editor instead of ~20 · a startup or small repo
                            doing a piece = validation, never a strike · judge the ASSEMBLY (tools replaced, setup, places to look), never a per-feature "unique?" column
                            name the biggest threat plainly (who could ship our center next) · only unique or measurably better claims get pitched (his products: "one place, less setup" IS the claim; measure tools + setup, not novelty)
    checks                  the task's checks-first commit names prior-art.md · a reviewer rejects a bench or method with no prior-art.md (loop rule R0, Mole tasks/loop-goals.json)
    numbers for people      resume, pitch, page claims: use metrics real companies and papers publish (catch rate, precision/recall, p95 latency, test time saved,
                            time to first PR, merge rate) with their source · never a metric only we use, unless it's labelled as ours
```
