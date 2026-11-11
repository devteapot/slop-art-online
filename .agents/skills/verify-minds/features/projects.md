# Projects (`LIVING_PROJECTS=1`, experiment)

Self-chosen aims kept in the character's own Neo4j graph as `self -PURSUES {since, progress, next_step, …}-> project:<slug>`. Design: docs/LIVING_CORE.md, "Projects (experiment, 2026-11-11)". Off by default.

## Sub-features

- `projects-think`: with the switch on, every person's think request has a `# Your projects (what you have set out to achieve; key: aim)` section, `(none)` when none is open, at most 3 lines (`- key: aim (since …; so far: …; next: …)`) and a count of the rest; its system prompt asks for `"serves"`. The compile request has no projects section. `prompts::think_user`, `Minds::open_projects`, `projects::lines`.
- `projects-serves`: the think reply's `serves` resolves to an open project by key, bare slug or aim (`projects::serves`); the deliberation's thought row carries `detail.projects = {open, said, serves}` and its summary ends `[serves <key>]`; the served project is reinforced (`Store::serve_project`: `t`, `served`, `served_t`, `served_by`, `last_plan`).
- `projects-consolidate`: a person's consolidation request shows the same section and the system prompt's PROJECTS paragraph; the reply's `projects` array becomes `PURSUES` edges and `Project` nodes, `ended` entries close with an outcome (`memory::projects_into`); the log line adds `, n projects, m ended`.
- `projects-reorganize`: a reorganization (mind of at least 25 links) gets the section and may answer the same array (`sleep_prepare`, `sleep_finish`).
- Off: no section, no `serves` field, no `projects` paragraph, nothing read from or written to `PURSUES`.

## How to get to it (user POV)

Run a person's mind with `LIVING_PROJECTS=1` and a Neo4j store. The fake model answers projects only when the prompt carries them (verify-llm `references/fake-llm.md`): consolidation and reorganization write `project:verify_fake_shelter`, and a think step serves the first project listed.

## Driving it

This suite's cases run with `LIVING_NEO4J=off`, so they cannot reach projects (no store, no section). Drive it with a fake trial batch on the trial stack, default against projects:

```bash
python3 living/tools/trials.py build life
python3 living/tools/trials.py run --batch fp1 life --variants default,projects --replicates 1 --minutes 10 --fake
```

Check, for `life-projects-r1`: think requests in `<batch>/fake-requests.jsonl` contain `# Your projects` (first `(none)`, then `- project:verify_fake_shelter:`) and `"serves"`; `thoughts.jsonl` deliberation rows have `detail.projects.serves = "project:verify_fake_shelter"` after the first consolidation; `mind.log` has `1 projects, 0 ended`; Neo4j (`cypher-shell` in the trial container, run = the instance's database name) has an open `PURSUES` edge with `served > 0`. For `life-default-r1`: no request contains `# Your projects` or `"serves"`, and the run has no `PURSUES` edge. Then `trials.py clean --batch fp1`.

The store side (ending, fading, refusing to serve an ended project) is proved against a scratch Neo4j by `verify-knowledge`'s `projects_are_pursued_served_ended_and_faded`.

## Gotchas

- Projects fade at the night's fade (`sleep_prepare`, floor 0.2), so a 10-minute fake run shows no fading; the ignored store test covers it.
- The fake's project is fixed text: the run proves plumbing and prompt shape, not that a model chooses or keeps aims.
