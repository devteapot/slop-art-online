---
name: verify-knowledge
description: "Verify living-core know-how and memory: techniques taught, practised and experimented with, tablets and signs, death cleanup, truthful feedback, the personal memory graph (scratch Neo4j), recall, projection and fading, names and strangers in memory, and player memory. Use when changing knowledge rules, artifacts, memory.rs, mind recall or projections, authored pasts or mind/lived.rs."
---

# Verify knowledge and memory

Read the [`verify` entry point](../verify/SKILL.md) first. It owns authority launch, doctor, the player identity, SQL, cleanup and evidence rules.

This skill drives two paths. Scripted characters learn and use techniques through the real authority. The real `living-mind` integrates experience through a local fake model endpoint and its own throwaway Neo4j.

## Preconditions

SpacetimeDB must be running. When it is down, `.agents/skills/verify/scripts/verify.py launch --run <run>` starts it. Or run `docker start sao-living_spacetimedb_1` and poll `curl -s http://127.0.0.1:3300/v1/ping` until it answers.

The runner works with podman (the Fedora host) and Docker Desktop (the laptop). Docker lists the image by its short name, which the runner accepts. On Docker, start SpacetimeDB before the run (`docker compose --env-file .local/living/neo4j.env -f living/deploy/compose.yml -p sao-living up -d --no-deps spacetimedb`); a run that starts it also stops it during cleanup, before its final SQL check.

The Neo4j image must be present locally, because the runner does not pull it. Pull it with the exact fully qualified name the runner uses: `docker pull docker.io/library/neo4j:2026.09.0`. Short image names do not resolve without a terminal on this host, so the full `docker.io/...` name is required. Check the image with `docker images`.

## Run every feature

Run from the repository root with Python 3, Cargo, the WASM target and the host's docker CLI available. The SpacetimeDB service must already be running. Keep port 7691 free. The fully qualified image `docker.io/library/neo4j:2026.09.0` must appear in `docker images`.

```bash
R=knowledge-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-knowledge/scripts/verify_knowledge.py run --run "$R"
```

The helper calls shared `launch --seed authored-test` and `doctor`, starts its Neo4j container, builds the mind, drives every mapped feature and cleans up in `finally`. Builds and proof artifacts stay under `.local/living/verify/`. The shared harness retains its normal authority build paths.

The database is `verify-$R`. The container is `sao-verify-neo4j-$R`, labeled with the run, bound only to `127.0.0.1:7691` and created without a named volume. Each Cargo test and the real mind receive explicit `LIVING_NEO4J_URI` and `LIVING_NEO4J_PASSWORD`. The random password exists only in `knowledge-state.json`, mode 0600, and the container's auth environment. Cleanup removes it from the state.

Never use Neo4j A on 7689 or Neo4j B on 7690. Never change the shared fake model server or runner. All model profiles in this proof point to the run's loopback fake endpoint.

## A world's own technique

Teaching a technique only a world's laws add (Cullet's glassmaking) has its own action, authority only, on a `cullet-laws` world ([feature](features/know-how.md)); it uses no Neo4j and no mind, and cleans up the same way:

```bash
.agents/skills/verify-knowledge/scripts/verify_knowledge.py world-know-how --run knowledge-glass-$(date +%Y%m%d-%H%M%S)
```

`--target-dir DIR` builds the module in `DIR` (the shared harness's option), for both actions. With `CARGO_TARGET_DIR` set, both actions build the module there and `run` builds the mind and its tests there too (otherwise in `.local/living/verify/build-knowledge`), so a worker keeps one build tree (recipes-1). Both actions read `LIVING_STDB_URL` (and the shared harness `LIVING_STDB_CONTAINER`) for a worker's own server.

## Player memory

What a human-played character lives, internalized into its own graph (player memory, on by default) ([feature](features/player-memory.md), design in `docs/PLAYER_MEMORY.md`), has its own runner on an island world, with the same scratch Neo4j, fake model and cleanup:

```bash
.agents/skills/verify-knowledge/scripts/player_memory.py run --run knowledge-pmem-$(date +%Y%m%d-%H%M%S) --mode direct
.agents/skills/verify-knowledge/scripts/player_memory.py run --run knowledge-pmem-$(date +%Y%m%d-%H%M%S) --mode batch
```

Its paid tier, `scripts/player_memory_real.py --allow-live`, runs only after the user authorizes that run.

A resident's mind made from the world's facts (docs/SEEDED_LIVES.md; every person has a mind from the start) has its own runner on an island world, [features/facts-minds.md](features/facts-minds.md):

```bash
.agents/skills/verify-knowledge/scripts/facts_mind.py run --run knowledge-facts-$(date +%Y%m%d-%H%M%S)
```

Its paid tier, `scripts/residents_real.py --allow-live --run knowledge-residents-real-<name>`, runs only after the user authorizes that run (the models file as shipped; the key from the main checkout's `.env`, into the mind's environment only).

Names learned from a lived line, down to the memory graph ([features/names.md](features/names.md)), on any Neo4j given by `LIVING_PRIVACY_NEO4J=container:host:port` and `LIVING_PRIVACY_NEO4J_ENV` (a file with `LIVING_NEO4J_PASSWORD=`; on the Spark, the trial stack's `slop-trials-neo4j:127.0.0.1:7699`), nodes under the run's own name and deleted after:

```bash
.agents/skills/verify-knowledge/scripts/names.py --run minds-names-$(date +%Y%m%d-%H%M%S)
```

Two strangers stay two people in memory ([features/strangers.md](features/strangers.md)): two players the mind does not know by name say different things, the fake model folds both under one description, and the graph, recall and a later introduction keep them apart. Same environment as `names.py`, plus a `CARGO_TARGET_DIR` holding a release `living-mind` (the recall replay is built there):

```bash
.agents/skills/verify-knowledge/scripts/strangers.py --run minds-strangers-$(date +%Y%m%d-%H%M%S)
```

## Doctor

The run records the shared doctor result in `actions.log`, confirms `RETURN 1` against its scratch graph, records the image and mounts in `neo4j-doctor.log`, and checks the fake's `/health`. It requires the real mind's subscription and scratch Neo4j connection log before checking memory effects.

For a running attempt:

```bash
.agents/skills/verify/scripts/verify.py doctor --run "$R"
```

## Drive and evidence

[features/README.md](features/README.md) lists every proof. [references/design.md](references/design.md) records source ownership and documentation implications. [references/validation/](references/validation/README.md) holds one record per actual run; the newest files are the last validated runs.

The runner asserts table changes, exact knowledge sources, preserved row IDs and acquisition times, negative effects for blocked actions, successful practice counts, graph content, projected rows and recalled prompt content. Admin reducers prepare and drive deterministic authority scenes. They do not prove player permissions.

Eleven ignored memory tests (`TESTS` in the runner, `strangers_stay_apart` and `a_far_figure_joins_the_person` among them) create and delete graphs inside this scratch Neo4j. `recall_replay` requires `LIVING_RECALL_CASES`; the runner generates nonempty cases against the real mind's graph and asserts budgets and recalled content from its output. It also runs the two focused truthful-feedback rules tests.

Evidence remains in `.local/living/verify/$R/`. Inspect `results.json`, the recorded SQL snapshots, `graph-*.cypher` and `graph-*.txt`, `recalled-deliberation.json`, Cargo test logs, `requests.jsonl`, `journal/` and `cleanup.json`. `knowledge-state.json` and shared `state.json` are private operational state, not evidence to share.

## Cleanup

The runner stops only its recorded PIDs, copies and byte-checks the mind journal, removes the original `verify-knowledge-*` journal, calls shared database cleanup and requires SQL to return 404. It stops and removes its scratch Neo4j with `docker rm -v`, which also removes anonymous image volumes. It leaves the shared authority service running.

After an interrupted run, repeat cleanup with the same run name:

```bash
.agents/skills/verify-knowledge/scripts/verify_knowledge.py cleanup --run "$R"
```

Confirm `cleanup.json` reports database and container removal and journal removal, and that `results.json` and captured evidence still exist. A failed scene keeps its `failure.log` and partial results. Use a fresh run name for a rerun.

## What this skill does not prove

- General skills, combat, ticks and physical rules belong to `verify-core`.
- Seed compilation and world placement belong to `verify-generation`.
- Subscription permissions and reconnect visibility belong to `verify-client`.
- Human controls and refusal permissions belong to `verify-player`.
- Mind scheduling, conversations and behavior installation belong to `verify-minds`.
- Provider routing, retries and paid model quality belong to `verify-llm`.
- Memory presentation belongs to the future UI skill (not built; see `verify`).
- These small scenes do not establish scale, retention bounds or performance acceptance.

The entry point's triage sends a "character forgot or misremembers something" symptom here, after `verify-minds` and before `verify-llm`.
