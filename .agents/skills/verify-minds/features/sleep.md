# Reorganization at night (`LIVING_REORGANIZE`)

A mind tidies itself (purpose `reorganize`, `high` effort and the 24,000 cap on GLM Flash) once a night when due: at least `LIVING_REORGANIZE_MIN` integrations (2) and `LIVING_REORGANIZE_GAP_S` (1,200 s) since its last sleep. Night is the world clock's `LIVING_NIGHT` (default `20-6`). `night-batch` (default) sends everyone due as one provider job per route, a later round at most every `LIVING_REORGANIZE_BATCH_GAP_S` (60 s); `night` sends each directly; `timer` keeps the old rule (a rested mind with nothing salient to integrate). Design and numbers: docs/MIND_HARNESS.md, item 2.

## Sub-features

- People in a round are marked consolidating, so no integration interleaves; their `since_sleep` resets on success. A failed batch sends its people directly the next night.
- Animals are due by the same rule and only fade (no reorganization prompt).
- Log lines: `night N: k of n minds go to sleep (b in a batch, d direct; e due)` per round; `sleep: <name> slept (batch|direct, night Some(N), after i integrations)` per mind; `<name> slept on it (batch|direct): …` when a reply was applied. The thought (kind `reorganize`) has `how` in its detail.
- With `LIVING_PROJECTS=1`, the reorganization request shows the person's projects and may answer the same `projects` array as consolidation ([projects.md](projects.md)).

Sources: `living/mind/src/mind/sleep.rs`, `living/mind/src/mind.rs` (`check_consolidation`, tick), `living/mind/src/llm.rs` (`Llm::batch`).

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run minds-$(date +%Y%m%d-%H%M%S) --case night
```

With `LIVING_NIGHT=0-24`, no gap and one integration due, the adult's first integration is followed by a batch round of one and the end of its sleep. Neo4j is off, so nothing is sent; the knowledge suite's `sleep_batch` stage sends a real (fake-provider) batch job through an uploaded file and applies the answer. `living/tools/sleep_nights.py` counts sleeps per night for a whole town.
