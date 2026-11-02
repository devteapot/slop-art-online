---
name: verify-llm
description: Verify the living core mind service's OpenAI-compatible requests, model routing, overflow, retries, outage recovery, JSON repair and journals. Use after changes to living/mind/src/llm.rs, model configuration or model reply parsing.
---

# Verify model integration

Read the [`verify` entry point](../verify/SKILL.md) first. It owns the shared launch, doctor, SQL, player identity and database cleanup. This skill drives the real release `living-mind` against local fake providers. It makes no paid calls in its default tier.

## Run the local tier

Preconditions: run from the repository root. If SpacetimeDB is down, run `docker start sao-living_spacetimedb_1`, then poll `curl -s http://127.0.0.1:3300/v1/ping` until it answers.

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S)
```

The command builds with `cargo build --manifest-path living/Cargo.toml -p living-mind --release`, checks all nine fake-server scenarios, runs the `llm::tests` checks, including pacing, priority and a direct fake HTTP exchange, then launches one fresh `verify-llm-*` database per case through `verify.py`. Each launch passes `doctor` before any mind starts. It drives every local feature in [features/README.md](features/README.md). The first `think` node waits for the authority's 45-second settling period. The timeout case deliberately waits for the real 180-second HTTP timeout.

To repeat a specific case on a new database:

```bash
.agents/skills/verify-llm/scripts/verify_llm.py --run llm-$(date +%Y%m%d-%H%M%S) --case outage
```

Repeat `--case` to select several. Read the map for the exact case names. A failed assertion exits nonzero after cleanup. An HTTP success passes only when the expected journal and authority evidence also exist.

The driver selects one living adult for most cases and two adults plus a child for routing. It sets `LIVING_SERVER`, `LIVING_DB`, `LIVING_RUN`, `LIVING_SEED`, `LIVING_MODELS`, `LIVING_ONLY`, `LIVING_LLM_PER_MIN`, `LIVING_CONCURRENCY`, `LIVING_TOKEN`, `LIVING_ROOT`, `LIVING_LOD` and `LIVING_NEO4J` explicitly. `LIVING_NEO4J=off` overrides the host's Neo4j configuration. Profiles point only to `127.0.0.1` and use dummy keys. The admin token comes from `living/tools/stdb login show --token` into process memory. The driver never overwrites `.local/living/token` or writes that token into evidence.

The runner checks that the container's `/wasm` bind mount exists and is writable before publishing. Shared `verify.py` copies this run's own build to a uniquely named module there when launched from a worktree. An unavailable mount stops the case with `mount-check.json` and `failure.txt`, records `database_not_created` in cleanup, and leaves the shared service untouched. Worktrees never publish a stale module from another checkout.

## Evidence and cleanup

The command prints each evidence directory under `.local/living/verify/<suite>-<case>/`. The suite directory contains `build.log`, `cargo-tests.log` and `results.json`. Each case keeps the temporary models file, fake scripts and request logs, `mind.log`, `driver.log`, shared `actions.log`, authority snapshots, `result.json` or `failure.txt`, and `cleanup.json`.

Cleanup sends SIGTERM by owned pid and records any SIGKILL escalation. It copies every actor journal into the case's `journal/`, checks byte equality, then removes only `.local/living/journal/verify-llm-<suite>-<case>/`. Shared `verify.py cleanup` deletes the database and confirms HTTP SQL 404 before marking state unpublished. The helper records that verified state in `cleanup.json`. The existing SpacetimeDB container stays running.

If the runner was killed before `finally`, inspect `processes.json` and verify each pid still belongs to the recorded mind or fake command before stopping it. Copy the journal into the evidence directory before removing the original. Finish database cleanup using the shared command, with the exact case run name printed by the runner:

```bash
.agents/skills/verify/scripts/verify.py cleanup --run llm-interrupted-outage
```

Never use a reference world or a broad process-name kill. Use a new run name for retries so failed outcomes remain intact.

## Reuse the fake server

[references/fake-llm.md](references/fake-llm.md) documents the interface shared with `verify-minds` and `verify-knowledge`, including scripted replies, 429 and 500, delay, timeout, malformed JSON, content arrays and a closed listening port.

```bash
.agents/skills/verify-llm/scripts/fake_llm.py --port 18181 --log .local/living/verify/llm-manual/requests.jsonl --scenario valid
```

Wait for `READY http://127.0.0.1:18181/v1 pid=...`. Stop that pid with SIGTERM. Fake logs never record authorization headers. To check the reusable server independently:

```bash
.agents/skills/verify-llm/scripts/fake_contract.py --run llm-fake-$(date +%Y%m%d-%H%M%S)
```

This checks reply overrides, status codes, malformed content and envelope JSON, delays, caller timeout, a closed port, request logs and owned-process cleanup. Its shortened caller timeout proves fake behavior. The real mind timeout is a separate case.

## Opt-in live tier

Do not run this tier without authorization for that particular paid run. It loads `.env` without overriding existing variables, resolves the active models config, and sends one minimal request per keyed provider base URL. It has no retries, caps the output at 64 tokens and writes credential-free results. It does not start a mind or connect to Neo4j.

After authorization:

```bash
.agents/skills/verify-llm/scripts/live_probe.py --allow-live --run llm-live-$(date +%Y%m%d-%H%M%S)
```

This checks provider access and response shape through Python HTTP. The local tier proves the Rust client. A live success does not establish full model-workload access or model judgment.

[references/validation.md](references/validation.md) records the actual local run. Use `maintain-verification-skill` after this interface changes.

Both paid commands share [models_config.py](scripts/models_config.py). An explicit `--models` wins, then `LIVING_MODELS` from the environment or non-overriding `.env`, then `living/configs/models.json`. This matches the active mind configuration. Inspect the selected config before authorizing the paid tier; an explicit reviewed Mistral-only file avoids probing a legacy model chosen alphabetically at the same endpoint. The free tier supplies its own loopback fake config.

## What this skill does not prove

- Model judgment, autonomous behavior or the complete mind lifecycle. Use `verify-minds`.
- Durable Neo4j memory, recall, knowledge privacy or learning. Use `verify-knowledge`.
- Core physical rules or world generation. Use `verify-core` and `verify-generation`.
- Client subscription permissions, human controls or observer presentation. Use `verify-client`, `verify-player` and the future UI skill (not built; see `verify`).
- Provider limits, tokenizer accuracy, caching economics, performance acceptance, large populations or the eight-hour workload.
