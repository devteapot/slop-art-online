# Project guidance

Slop Art Online is a persistent living-world game built with Rust, SpacetimeDB and Bevy. The active implementation is the living core (`living/` workspace, `just living-*` recipes). The earlier `simulation/`/`server/`/`client/` line was removed on 2026-11-02; its last state is the `legacy-baseline` tag. Human-controlled and AI-controlled characters share authority, capabilities and physical rules.

## Read first

- **[Living core](docs/LIVING_CORE.md)**: the active core since 2026-09-26 (`living/` workspace, `just living-*` recipes). The legacy `simulation/`, `server/`, `client/`, `prototypes/`, `experiments/` and `shared/` trees are removed; their runbooks and evidence remain in `docs/` as history, resolving at `legacy-baseline`.

- [Simulation vision](docs/SIMULATION_VISION.md) and [world vision](docs/WORLD_VISION.md): agreed direction and open design choices.
- [Current state](docs/CURRENT_STATE.md), [world roadmap](docs/WORLD_ROADMAP.md) and [work queue](docs/TODO.md): implementation evidence and remaining work; the legacy sections are historical.
- [Performance contract](docs/PERFORMANCE_CONTRACT.md): locked gameplay, latency, population and resource targets; benchmark acceptance rules.
- [Audit and experiments](docs/AUDIT_AND_EXPERIMENTS.md): causal evidence and acceptance requirements.
- [Characters](docs/CHARACTERS.md): the character generator that replaces VRoid bases, its parameters and commands.

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
- Keep rules authoritative in the living authority and expressed in its shared rules and skill scripts; Bevy handles presentation/input. External inference belongs in the mind service (`living/mind`), never in reducers. Do not create a second approximate simulator for experiments.
- Retain shared logic when replacing storage boundaries. Generated bindings in `living/bindings` are regenerated via `just living-generate`, not hand-edited.
- Build tools we own. When a capability matters to the game, such as characters, animation, models, textures or measurement, start from the best existing tool or asset, then bring it inside: our own scripts and parameters, judged in the game's renderer, so results can be regenerated and varied. The clip library and the Blender generators were made this way. Do not leave an outside application or a manual step on the path of routine work.

## Validation and resource discipline

Use focused correctness checks and representative actual-authority workloads. A passing synthetic transport fixture does not establish full model-workload access; small-world correctness does not establish scale. Declare population, duration, action rate, local density, subscriptions and observer/export load when making performance claims.

Measure reducer execution/queue time, subscription volume, table growth, WASM memory and service allocator/pool memory where relevant. Distinguish service-wide RSS across retained databases from a single world's footprint, and retained WAL size from cumulative writes. Keep historical evidence while planning bounded active-data retention. Do not hide growth with restarts or label a forced service stop graceful.

## Build and run

Use the [Justfile](Justfile) and the [living core](docs/LIVING_CORE.md). The legacy runbooks ([M1 runbook](docs/M1_RUNBOOK.md), [Bevy browser client](docs/BEVY_BROWSER_CLIENT.md), [participant agents](docs/PARTICIPANT_AGENTS.md)) and [stack reference](STACK_REFERENCE.md) are retained as historical evidence for the removed line. Verify the selected server, database, CLI and output paths before publishing or launching a run.

```bash
just living-check     # authority wasm + mind + both observers + game client + rules tests; run before every commit
just living-game-assets # regenerate the game client's git-ignored assets (needs Blender; Kimodo cache for clips)
just living-test      # rules tests
just living-up        # SpacetimeDB + Neo4j containers
just living-reset     # fresh world from the seed (DELETES world data)
just living-mind      # mind service
just living-web       # browser observer
```

Reset recipes delete database data; they are not routine update commands.

For documentation-only work, check links, terminology, current/target labels and `git diff --check`; do not build or regenerate bindings. Preserve unrelated workspace changes and immutable experiment artifacts.

## Agent setup

- Project instructions live in this `AGENTS.md`. Claude Code reads it when no project `CLAUDE.md` is present, so do not add one.
- Project skills live in `.agents/skills/`, with links in `.claude/skills/`. They are the verification skills listed under [Verification surfaces](#verification-surfaces) and the two skills that create and maintain them. `.agents/vendored-skills.md` records where those two came from.

## Models and coordination

All agent work on this project runs on Claude.

- **Coordinators:** each machine has one coordinator thread on Claude Opus 5.5 (`claude-opus-5-5`) at high reasoning effort.
- **Subagents:** Claude Opus 5.5 at high reasoning effort by default.
- **Fable exceptions:** use Claude Fable 5.2 (`claude-fable-5-2`) at high reasoning effort for asset generation, such as 3D models and textures, and for a task that Opus has attempted and could not solve. Say in the report when a task was moved to Fable and why.
- A model or provider the owner asks for by name overrides these defaults for that task.
- A model named inside a skill does not override this section. This section does not switch the model of a thread the owner started.

Each machine has one role:

- **Laptop:** the game client and the owner's play-tests.
- **dev-box:** the first game version.
- **Spark:** experiments on the mind and the rules.

Coordinators run as T3 Code threads owned by their machine and are started through T3's linked environments. Set the model and effort explicitly when starting a thread on another machine: it otherwise takes that machine's default. Each thread works in its own worktree from `origin/main`, and code moves between machines only through git. Use Rex for long remote jobs and interactive steps.

## Verification surfaces

The living core is verified surface by surface, so a failure can be traced to the layer that owns it. `.agents/skills/verify/SKILL.md` is the entry point. It maps changes and symptoms to surfaces and owns the shared harness: scratch `verify-<run>` databases, the player identity, the observer, cleanup and evidence. The surface skills are:

- `verify-core`: rules and the tick.
- `verify-generation`: worlds from seeds.
- `verify-client`: what a connecting client sees and may call.
- `verify-player`: human players.
- `verify-minds`: the mind service.
- `verify-llm`: model integration.
- `verify-knowledge`: know-how and memory.
- `verify-ui`: the game client's interface (interface D), clicked through headless.

The browser observer has no skill; it is a simple developer client that the game UI replaces. When the external-agent connector is implemented, add `verify-agent-external` with a scripted tier and a real-agent tier.

- Before reporting a living-core change as working, run the skill of every surface it touches. Report what was driven, the evidence paths and what was not covered.
- To locate a failure, step down the layers: screen → client → player, or minds → llm and knowledge → core and generation. Name the lowest layer that reproduces it.
- When a change alters a surface's shape, run `maintain-verification-skill` on that surface's skill in the same change. Shape means tables, reducers, views or subscriptions; the mind protocol; seed or model-config formats; UI controls; or launch and run commands. When a change adds a surface, create its skill with `create-verification-skill` and add it to the entry point's surface table. A skill whose map no longer matches the code is a defect, not documentation debt.
- Free tiers use scratch databases and a fake model server. Paid tiers make real model calls and run only after the user authorizes that run. These skills do not establish performance or scale; those claims follow the evidence rules above. Never point a verification run at the paused reference worlds.
