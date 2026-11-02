---
name: verify-generation
description: Verify how the Slop Art Online living core generates worlds from compiled seeds. Use for changes to seed parsing, terrain, settlements, bands, authored sheets, resources, animals, or cached authored-world compilation.
---

# Verify world generation

Read the [`verify` entry point](../verify/SKILL.md) first. It owns the shared launch, doctor, SQL, cleanup and evidence rules.

## Run

Preconditions: SpacetimeDB 2.10.1 must answer on `http://127.0.0.1:3300`. If it is down, run `docker start sao-living_spacetimedb_1`, then poll `curl -s http://127.0.0.1:3300/v1/ping` until it answers. The driver uses the existing container and leaves it running.

Run from the repository root:

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-$(date +%Y%m%d-%H%M%S)
```

Use a fresh run name. The driver calls the shared harness through its CLI for launch, doctor, admin pause, SQL snapshots and cleanup. `launch --target-dir .local/living/verify/<run>/target` isolates Cargo outputs from other runs and reuses dependencies across seeds. The harness creates a temporary module copy in the server's `/wasm` mount and removes it during cleanup. Tracked authority and seed files remain untouched.

Only cached compilation uses `.local/living/verify/<run>/source/living/`. That copy contains `author_world.py` and the Aske Coast bible, cast, template and cached sheets. The compiler derives its root from its script path and writes `living/seeds/aske-coast.json`; it has no output-path option. Copying those inputs keeps the tracked seed untouched. The malformed seed uses an absolute seed path under `.local` through `--seed`; `build.rs` accepts it without copying authority sources.

Each database is `verify-<run>-<index>-<seed>`. The driver publishes `realm`, `valley`, `authored-test`, `aske-coast`, `stage3-village`, a second `realm`, and one malformed seed. Doctor first proves the world ticks. An admin `set_paused(true)` then holds it still for generation snapshots. No mind or browser observer starts.

For a focused rerun:

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-worlds-$(date +%Y%m%d-%H%M%S) --feature worlds
.agents/skills/verify-generation/scripts/generation.py --run generation-authored-$(date +%Y%m%d-%H%M%S) --feature authored
.agents/skills/verify-generation/scripts/generation.py --run generation-guards-$(date +%Y%m%d-%H%M%S) --feature guards
```

`worlds` includes repeatability. `authored` executes the real `author_world.py aske-coast --compile-only` in the copied tree with network calls blocked and recorded. `guards` runs all five `seed::tests::` native tests and publishes a valid JSON seed missing `animals`. The malformed copy stays in `.local`.

## Evidence and cleanup

`results.json` summarizes assertions. Each positive child run has the original seed, doctor output, public table snapshots, `checks.json`, publication actions, and `cleanup.json`. The rejected child has failure logs and `guards.json` instead of doctor and table snapshots. The parent directory has parser test output, compilation output and differences, the network-attempt record, and `repeatability.json`.

The driver calls shared cleanup for every database in `finally`. Shared cleanup requires SQL HTTP 404 after deletion. The driver checks its exit status, module removal and retained evidence. Evidence and build files remain. If the process is interrupted before cleanup, use the shared harness for each child run shown in the console log:

```bash
.agents/skills/verify/scripts/verify.py cleanup --run <child-run>
```

Use the interrupted child run's name for `<child-run>`. Do not clean unrelated `verify-*` databases. Do not stop the shared container.

`checks.json` failures are failures. RNG differences in `repeatability.json` are findings. A cached compilation difference is a finding to inspect in `compile-differences.json`; compilation failure or attempted network access fails the driver. The malformed-seed check asserts rejection only, so rejection is a plain pass. It does not assert a readable error. The unreadable error is a KNOWN ISSUE in `docs/LIVING_HANDOFF.md` under "Still open" at `seed.rs:444`. The shared harness truncates publication stderr; this run cannot certify the complete user-facing diagnostic. The driver exits 0 if every required check passes. `server-init.log` keeps the launch matching the scratch name's resolved database identity and seed panic frames from the publication window. `guards.json` records the panic and whether a missing-field diagnostic surfaced.

## Opt-in model drafting

`living/tools/author_world.py aske-coast` without `--compile-only` calls `draft_household` for missing household sheets and may make a second pass to fill one-sided family ties. Those are paid model calls. They are outside this driver and require authorization for the specific run. Cached sheets and deterministic compilation do not prove fresh model output.

## Feature map

[features/README.md](features/README.md) lists every generation feature. [references/validation.md](references/validation.md) records actual runs. Use `maintain-verification-skill` when these entry points or tables change.

## What this skill does not prove

- Rule execution after generation, long-term ecology, or scale: use `verify-core` and the performance contract.
- Subscription visibility and permissions: use `verify-client`. Anonymous public SQL checks exact sheet fields and secret strings, not semantic privacy of authored prose.
- Mind interpretation or fresh drafting: use `verify-minds` and `verify-llm`.
- Remembered knowledge: use `verify-knowledge`.
- Player actions and map presentation: use `verify-player` and the future UI skill (not built; see `verify`).
