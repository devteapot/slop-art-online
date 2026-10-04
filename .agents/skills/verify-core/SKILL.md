---
name: verify-core
description: Verify the living core authority's rules and scheduled loop. Use when changing ticks, behavior graphs, Rhai skills or laws, needs, life stages, wildlife, combat, steering, deliberate acts, or viewer display sync. Covers living/viewer/src/sync.rs display-sync tests only on the viewer. Runs offline Cargo checks and real scripted scenes on verify-core-* scratch databases.
---

# Verify the core rules and loop

Read the [`verify` entry point](../verify/SKILL.md) first. It owns launch, doctor, identities, the observer, cleanup and evidence. This skill adds core checks. It never starts a mind service or calls a model.

Run commands from the repository root. Use a new run name for every attempt. Scripts reject names outside `core-*`; their databases must be `verify-core-*`. Preserve failed evidence and clean up failed attempts too.

Preconditions: `python3 .agents/skills/verify/scripts/verify.py launch --run "$R"` starts the local SpacetimeDB container if it is down. Use only the local service.

## Launch and doctor

```bash
V=.agents/skills/verify/scripts/verify.py
C=.agents/skills/verify-core/scripts
R=core-$(date +%Y%m%d-%H%M%S)
E=.local/living/verify/$R
mkdir -p "$E"
python3 "$V" launch --run "$R" > "$E/launch.txt" 2>&1
python3 "$V" doctor --run "$R" > "$E/doctor.txt" 2>&1
```

Stop driving if launch or doctor fails. Run cleanup and retain the error. The scenes use the in-container admin CLI. Do not mix a remote `LIVING_STDB_URL` with `stdb -s local`.

## Drive the baseline

```bash
python3 "$C/cargo_checks.py" --run "$R"
python3 "$C/scenes.py" tick --run "$R" > "$E/tick.txt" 2>&1
python3 "$C/scenes.py" needs --run "$R" > "$E/needs.txt" 2>&1
python3 "$C/scenes.py" seize --run "$R" > "$E/seize.txt" 2>&1
python3 "$V" cleanup --run "$R" > "$E/cleanup.txt" 2>&1
```

Record each exit status. Unexpected failures exit 1. Run the remaining independent checks, then report the failure. `seize` checks refusal from an unyielded healthy person, seizure from a yielded healthy person, exact transfer, witnesses and lethal intent. If the yielded seizure fails, it still drives the badly-hurt path and exits 1. A check marked known (`XFAIL`/`XPASS`) exits 1 when it starts passing, so the stale expectation gets reviewed.

`cargo_checks.py` saves separate transcripts for these commands:

```bash
cargo test --manifest-path living/Cargo.toml -p living-rules
cargo test --manifest-path living/Cargo.toml -p living-authority --lib seed::tests
cargo test --manifest-path living/Cargo.toml -p living-mind
cargo test --manifest-path living/Cargo.toml -p living-viewer sync::tests
```

The authority seed tests run on the host despite its WASM `cdylib` target. Rules registers 46 tests, including one ignored reference printer. The mind's five ignored Neo4j tests stay skipped. Do not add `--ignored`. `just living-check` builds the authority WASM, the mind, and the native and WASM viewer targets. Only its test step runs rules tests. The commands above also run authority seed, mind and viewer sync tests. Viewer coverage is limited to `living/viewer/src/sync.rs`; no other viewer code is verified here.

## Drive the existing mechanics and steering scripts

These drivers publish and delete their own worlds. Run them after the baseline launch builds the default `living_authority.wasm`. The recorder uses their existing `LIVING_STDB` hook to retain calls and SQL. It also records ownership in `state.json` for shared cleanup after a driver crashes.

```bash
M=$R-mechanics
S=$R-steering
mkdir -p ".local/living/verify/$M" ".local/living/verify/$S"
CORE_VERIFY_RUN="$M" LIVING_STDB="$PWD/$C/record_stdb.py" \
  python3 living/tools/verify_mechanics.py --db "verify-$M" \
  --out ".local/living/verify/$M/mechanics.json" \
  > ".local/living/verify/$M/mechanics.txt" 2>&1
python3 "$V" cleanup --run "$M"
CORE_VERIFY_RUN="$S" LIVING_STDB="$PWD/$C/record_stdb.py" \
  python3 living/tools/verify_steering.py --db "verify-$S" \
  > ".local/living/verify/$S/steering.txt" 2>&1
python3 "$V" cleanup --run "$S"
```

Expect 23 mechanics checks and five steering checks. Inspect every result and keep failures even when another fresh world passes. The driver has a recorded mechanics flake. Use the recognition and investigation steps in [mechanics.md](features/mechanics.md), and retain every failing result. Do not convert these intermittent failures into XFAIL or discard them after a passing retry. `docs/LIVING_CORE.md:414` retains the historical 14-check count.

## Drive life and wildlife

Use fresh `stage1-acts` worlds. The seed has eight people including an infant, 16 deer, three wolves, `year_days: 4` and `life_pace: 0.0714`. The day remains 12 real minutes. `lab-lifecycle` also compresses lives but does not explicitly list an infant. Gestation uses species life fractions, not `laws.gestation_days`.

```bash
L=$R-life
mkdir -p ".local/living/verify/$L"
python3 "$V" launch --run "$L" --seed stage1-acts > ".local/living/verify/$L/launch.txt" 2>&1
python3 "$V" doctor --run "$L" > ".local/living/verify/$L/doctor.txt" 2>&1
python3 "$C/scenes.py" lifecycle --run "$L" > ".local/living/verify/$L/lifecycle.txt" 2>&1
python3 "$V" cleanup --run "$L"

W=$R-wildlife
mkdir -p ".local/living/verify/$W"
python3 "$V" launch --run "$W" --seed stage1-acts > ".local/living/verify/$W/launch.txt" 2>&1
python3 "$V" doctor --run "$W" > ".local/living/verify/$W/doctor.txt" 2>&1
python3 "$C/scenes.py" wildlife --run "$W" > ".local/living/verify/$W/wildlife.txt" 2>&1
python3 "$V" cleanup --run "$W"
```

Start lifecycle promptly after doctor while the seeded infant is still an infant. Wildlife holds initial character graphs on wait, drives grazing, kills deer and waits for the actual 20-minute migration cooldown. It then checks one more minute without another arrival. Run independent checks on separate databases during that wait. Do not accelerate the clock, patch species data or restart the service.

## Keep the evidence

[features/README.md](features/README.md) maps the checks. [references/validation.md](references/validation.md) records the real runs and defects. Keep this map current with `maintain-verification-skill` when behavior changes.

`scenes.py` saves named snapshots, `<scene>-actions.jsonl` and `<scene>-results.json`. The recorder saves `stdb-actions.jsonl`, including the original drivers' before and after SQL. Cargo saves transcripts and `cargo-results.json`. `scenes.py` reads back the installed `brain` row after every graph replacement. The recorder captures complete `brain` rows after `set_behavior` and complete `routine` rows whenever the drivers probe an actor's routines. Compare those rows to the requested scene before interpreting results when normalization can change a graph or routine. Outputs belong under `.local/living/verify/`, never in this skill tree.

After cleanup, confirm result files still exist and SQL reports each scratch database absent. The shared harness verifies HTTP 404 after deletion. Existing drivers delete their own database too. The recorder retains cleanup ownership until the shared harness confirms HTTP 404; check their recorded CLI outcomes and actual absence. Stop only observer processes the run started. Preserve the shared container and reference worlds.

For a visible check, use shared `observer start` and T3's collaborative preview when available. Save captures under the run's evidence directory. Core assertions use tables and client transcripts; screenshots do not replace them.

For a focused grazing rerun, launch a fresh `stage1-acts` run and call the same grazing helper directly:

```bash
G=$R-grazing
mkdir -p ".local/living/verify/$G"
python3 "$V" launch --run "$G" --seed stage1-acts
python3 "$V" doctor --run "$G"
python3 "$C/scenes.py" grazing --run "$G" > ".local/living/verify/$G/grazing.txt" 2>&1
python3 "$V" cleanup --run "$G"
```

If arrival assertions fail after real migration, preserve that attempt's files first. While the same owned database is still live, this command reruns the arrival checks from its retained `wildlife-empty.json` checkpoint. It does not republish or reset the cooldown.

```bash
python3 "$C/scenes.py" arrival --run "$W" > ".local/living/verify/$W/arrival.txt" 2>&1
python3 "$V" cleanup --run "$W"
```

## What this skill does not prove

- Sustained performance acceptance, resource bounds, long-term ecology or every graph and skill combination.
- World generation and authored-world compilation. Use `verify-generation`.
- Subscriptions, visibility and permissions across identities. Use `verify-client`.
- The human player's own identity and complete command path. Use `verify-player`.
- Mind-service execution, model decisions and providers. Use `verify-minds` and `verify-llm`.
- Personal memory, recall and knowledge persistence. Use `verify-knowledge`.
- Observer rendering, interaction, frame rate and visual smoothness. Use the future UI skill (not built; see `verify`).
