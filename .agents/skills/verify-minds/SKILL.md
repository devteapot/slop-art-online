---
name: verify-minds
description: Verify the living core's internal mind service with the real living-mind binary and a local fake model. Use when changing deliberation, deliberate acts, conversations, consolidation, reconnect handling, LIVING_ONLY, or mind level of detail.
---

# Verify internal minds

Read the [`verify` entry point](../verify/SKILL.md) first. It owns scratch database launch, doctor, identities, SQL, observer and cleanup. This skill drives the real `living/target/release/living-mind` through its subscriptions and `mind_*` reducers.

## Run the free tier

Preconditions: run from the repository root. If SpacetimeDB is down, run `docker start sao-living_spacetimedb_1`, then poll `curl -s http://127.0.0.1:3300/v1/ping` until it answers.

```bash
R=minds-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R"
.agents/skills/verify-minds/scripts/paid_safety.py --run "minds-duel-safety-${R#minds-}"
cat ".local/living/verify/$R/results.json"
```

The command builds the release mind, runs its non-ignored tests, then launches and doctors a separate `verify-minds-*` database for each case. It drives all nine mind cases, stops its own processes, deletes each scratch database and confirms the evidence remains. The second command proves paid-wrapper safety with inert children and no model calls. Allow several minutes for the real timing gaps. It never starts or stops the shared container.

The driver imports lifecycle helpers from [`verify-llm`](../verify-llm/scripts/verify_llm.py) and invokes its [fake server](../verify-llm/scripts/fake_llm.py). Read the [fake interface](../verify-llm/references/fake-llm.md) when changing replies. Temporary profiles point only to loopback and use a dummy key. The admin token stays in process memory and `LIVING_TOKEN`; `.local/living/token` stays untouched. Every mind uses a separate `LIVING_RUN`, an explicit `LIVING_ONLY`, and `LIVING_NEO4J=off`. No tracked seed changes are needed.

To rerun one feature:

```bash
R=minds-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case conversation
```

`--case` can repeat. Cases are `roundtrip`, `acts`, `conversation`, `consolidation`, `prune`, `reject`, `only`, `reconnect` and `lod`. Exit 0 means every ordinary check passed and known defects remain XFAIL. Exit 1 means FAIL or XPASS; inspect XPASS before removing its known-issue expectation. Inspect `results.json`, the case's `result.json`, and `failure.txt` when present. Consolidation retains its XFAIL KNOWN ISSUE check linked to `docs/LIVING_HANDOFF.md`, under "Still open". LoD requires merged reasons, urgent upgrades and player-contact release to pass.


## Evidence and cleanup

Each case writes `.local/living/verify/<suite>-<case>/`. Keep `actions.log`, `driver.log`, `fake-requests.jsonl`, `mind.log`, copied `journal/`, table snapshots, `result.json` and `cleanup.json`. The suite keeps build and test logs and source hashes. Full requests and replies stay in the fake log and journal. Authority snapshots prove their application.

Cleanup runs in `finally`, including after a failed check or Ctrl-C. If cleanup itself fails, use the shared command for the affected case:

```bash
.agents/skills/verify/scripts/verify.py cleanup --run "$R-conversation"
```

First stop any surviving owned PIDs listed in that case's `processes.json`, after checking that the PID still belongs to this run. Do not kill by process name. Never clean another surface's database or a paused reference world.

The [feature map](features/README.md) gives the source paths and assertions. The [validation record](references/validation.md) lists proven behavior and remaining failures. Use `maintain-verification-skill` after changing the mind protocol or launch commands.

## Opt-in real-model tier

Run only after the user authorizes this specific paid run. The wrapper also requires `--allow-live`. It collects for 60 seconds, limits model calls to four per minute and imposes a separate 90-second deadline including setup. Two duel characters have minds. It is a smoke check, not a deterministic assertion or a cost guarantee.

```bash
R=minds-duel-$(date +%Y%m%d-%H%M%S)
V=.agents/skills/verify/scripts/verify.py
$V launch --run "$R"
$V doctor --run "$R"
cargo build --manifest-path living/Cargo.toml -p living-mind --release
.agents/skills/verify-minds/scripts/real_models.py --allow-live --run "$R"
$V sql --run "$R" "SELECT * FROM thought" --save duel-thoughts
$V sql --run "$R" "SELECT * FROM brain" --save duel-brains
$V sql --run "$R" "SELECT * FROM chronicle" --save duel-chronicle
$V cleanup --run "$R"
```

Both paid commands use the same [config resolver](../verify-llm/scripts/models_config.py). An explicit `--models PATH` wins, then `LIVING_MODELS` from the environment or non-overriding `.env`, then `living/configs/models.json`. This follows the running mind's configuration. On this host `.env` selects `.local/living/models.json`, whose Luna endpoint is the local proxy on port 8787. The repository example points Luna at `codex.carlid.dev`; forcing that example would bypass the host's selected route. The dry check loads no provider keys and contacts neither endpoint.

The wrapper passes the admin token in memory through `LIVING_TOKEN` and disables Neo4j. `duel.py` republishes this scratch database and chooses a separate `duel-*` journal name. On a completed report, the wrapper copies and checks the journal and log, then removes their originals. On failure without a report, preserve partial `duel-*` evidence and run shared cleanup.

A detached guardian owns the driver process group. It stops that group after driver exit, watchdog expiry or wrapper death, including SIGKILL. It escalates to SIGKILL when needed, reaps orphaned descendants and records the group-gone check in `duel-cleanup.json`. Linux child-subreaper support is required. A killed wrapper cannot run database cleanup, so use shared cleanup afterward.

Prove the guard and termination without paid calls:

```bash
.agents/skills/verify-minds/scripts/paid_safety.py --run minds-duel-safety-$(date +%Y%m%d-%H%M%S)
```

This runs inert children for normal driver exit, killed driver, watchdog expiry, killed wrapper and SIGTERM of the wrapper. The child ignores SIGTERM so escalation is exercised. It also proves the missing-`--allow-live` refusal before any run directory, keys, process or database is created. `results.json`, `guard.log` and each scenario's `duel-cleanup.json` survive cleanup. This dry proof is separate from the mind suite. Run both commands when changing this wrapper.

## What this skill does not prove

- Model transport, routing, overflow, retries and outage handling belong to `verify-llm`.
- Relations, beliefs, judgments and places projected WITH a store, Neo4j persistence, recall, fading, know-how and teaching belong to `verify-knowledge`.
- Rule correctness beyond these scenes belongs to `verify-core`; seed generation belongs to `verify-generation`.
- Subscription privacy and reducer permissions across identities belong to `verify-client`.
- The human control API belongs to `verify-player`; rendered results belong to the future UI skill (not built; see `verify`).
- Small scratch scenes do not prove population, latency, resource limits, eight-hour stability or autonomous learning.
