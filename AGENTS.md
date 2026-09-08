# Project guidance

Slop Art Online is a persistent living-world game built with Rust, SpacetimeDB and Bevy. The current client is a top-down 2D behavior lab; the voxel/3D client is retired. Human-controlled and AI-controlled characters share authority, capabilities and physical rules.

## Read first

- [Simulation vision](docs/SIMULATION_VISION.md) and [world vision](docs/WORLD_VISION.md): agreed direction and open design choices.
- [Current state](docs/CURRENT_STATE.md), [world roadmap](docs/WORLD_ROADMAP.md) and [work queue](docs/TODO.md): implementation evidence and remaining work.
- [Performance contract](docs/PERFORMANCE_CONTRACT.md): locked gameplay, latency, population and resource targets; benchmark acceptance rules.
- [Audit and experiments](docs/AUDIT_AND_EXPERIMENTS.md): causal evidence and acceptance requirements.
- [Module guidance](server/module/AGENTS.md), [authority guidance](server/module/spacetimedb/AGENTS.md) and [bridge guidance](server/bridge/AGENTS.md): local implementation rules.

The seven-stage roadmap has completed a bounded implementation pass. That does not establish autonomous ascension, sustainable large populations or performance acceptance. The locked target is 60 Hz active movement/combat, stable 60 FPS with higher refresh-rate support, and 2,000 active characters including a 200-character local battle for 8 hours within the performance contract's latency/resource limits. The immediate gate is 216 characters for 30 minutes at the same quality limits. Existing whole-World processing and finite actor limits are prototype constraints to address, not patterns to extend. Historical 20 Hz checkpoints, ADRs and old current-state sections do not override newer evidence or agreed design.

## Required SpacetimeDB documentation check

**Before designing, implementing or changing any feature that uses SpacetimeDB, always consult the relevant official SpacetimeDB documentation to understand the intended implementation pattern.** This includes tables, reducers, views, subscriptions, events, permissions, scheduling, persistence, client integration and performance. Do this before committing to an architecture; existing repository code and remembered API syntax are not sufficient guidance.

Start at the [official documentation](https://spacetimedb.com/docs/), then read the relevant [table design](https://spacetimedb.com/docs/tables/), [performance](https://spacetimedb.com/docs/tables/performance/), [indexes](https://spacetimedb.com/docs/tables/indexes/), [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/), [views](https://spacetimedb.com/docs/functions/views/) or [event tables](https://spacetimedb.com/docs/tables/event-tables/) guidance. Check APIs and feature availability against the versions actually pinned in manifests, generated bindings and the running service. Use official versioned source when current docs differ. Do not assume an announced feature is available. Record the relevant documentation links and design implications in the implementation explanation or accompanying design note. If documentation cannot be accessed, state that limitation and distinguish verified versioned-source evidence from assumptions.

For each affected data path, consider which rows it reads/writes, the indexes used, subscription recipients, update frequency, retained data and resource growth. Prefer typed tables grouped by access pattern, local indexed operations and incremental subscriptions. Do not introduce whole-World hydration, all-player scans, regeneration of every player's status or complete snapshots for routine local actions without documenting why they are necessary and measuring representative cost. Full exports remain appropriate for explicit checkpoints and diagnostics.

Spatial subscriptions are not permission boundaries by themselves: enforce perception and access on the authority. Separate current perception, remembered knowledge and developer audit truth. Transient notifications do not replace durable learning evidence or reconnect recovery.

## Working principles

- Keep reusable mechanics and balance separate from faction names, cultures and other seed content.
- Execute shared skill requirements, costs and effects for both controllers. Distinguish intention, attempt, failure, accepted operation and actual physical outcome.
- Preserve real-time behavior execution beneath asynchronous model interpretation and policy revision. Free-form communication and personal learning must not become silent proximity-based knowledge copying or prescribed narratives.
- Death is initially permanent. New identities do not automatically inherit memories, possessions or mastery.
- Preserve exact causal evidence, actual model exchanges, scoped privacy and original failed outcomes. A seed does not make fresh inference deterministic. Reported model explanations are not hidden chain-of-thought or proof of causation.
- Keep rules authoritative in SpacetimeDB and reusable in `simulation/`; Bevy handles presentation/input. External inference belongs in the Rust agent/bridge layer, never in reducers. Do not create a second approximate simulator for experiments.
- Retain shared logic when replacing storage boundaries. Generated types in `shared/` should be regenerated only for relevant interface changes, not hand-edited.

## Validation and resource discipline

Use focused correctness checks and representative actual-authority workloads. A passing synthetic transport fixture does not establish full model-workload access; small-world correctness does not establish scale. Declare population, duration, action rate, local density, subscriptions and observer/export load when making performance claims.

Measure reducer execution/queue time, subscription volume, table growth, WASM memory and service allocator/pool memory where relevant. Distinguish service-wide RSS across retained databases from a single world's footprint, and retained WAL size from cumulative writes. Keep historical evidence while planning bounded active-data retention. Do not hide growth with restarts or label a forced service stop graceful.

## Build and run

Use the [Justfile](Justfile), [browser runbook](docs/BEVY_BROWSER_CLIENT.md), [headless runbook](docs/M1_RUNBOOK.md) and [participant runtime guide](docs/PARTICIPANT_AGENTS.md). Verify the selected server, database, CLI and output paths before publishing or launching a run.

```bash
cargo test -p simulation --lib       # focused kernel checks
cargo test -p bridge                 # bridge checks
just bevy-web-build                  # browser assets
just bevy-dev                        # foundation development host
just client                          # native 2D client
```

`just bevy-db-up` starts the foundation database; see the browser runbook for initial setup and versioned CLI paths. `cargo run -p bridge`, `just dev` and the default `just publish` recipes serve the legacy path. Reset recipes delete database data; they are not routine update commands.

For documentation-only work, check links, terminology, current/target labels and `git diff --check`; do not build or regenerate bindings. Preserve unrelated workspace changes and immutable experiment artifacts.
