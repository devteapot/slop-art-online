# Project guidance

Slop Art Online is a persistent living-world game built with Rust, SpacetimeDB and Bevy. The current client is a top-down 2D behavior lab; the voxel/3D client is retired. Human-controlled and AI-controlled characters share authority, capabilities and physical rules.

## Read first

- **[Living core](docs/LIVING_CORE.md)**: the active core since 2026-09-26 (`living/` workspace, `just living-*` recipes). Legacy `simulation/`, `server/` and `client/` remain as historical baseline.

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

## Agent and skill compatibility

This project supports Cursor, Codex, Claude Code and Mistral Vibe. This is a compatibility requirement for all project skills and agent setup, including P-Stack, regardless of which agent is making a change.

- Keep shared project instructions in this `AGENTS.md`. Current Claude Code reads it through its default AGENTS.md fallback when no project Claude instruction file is present. Do not add a separate `CLAUDE.md` or duplicate policy unless a supported runtime requires an adapter; keep any required adapter limited to importing the shared instructions.
- Prefer the standard Agent Skills format and `.agents/skills/` as the shared source for project-authored skills. Keep runtime-specific discovery paths, tool names, model IDs, option mappings and instruction loading in thin adapters. Claude Code uses `.claude/skills/` links to the shared tree; Mistral Vibe can discover `.agents/skills/` directly. Maintain Cursor's required discovery adapters as well.
- When creating, changing, configuring, updating or removing a skill, review the effect on all four agents in the same change. A request made through Claude, Cursor, Codex or Mistral is project-wide unless the user explicitly limits it to that agent. Update the shared source and every affected adapter, link, setup record and invocation example.
- Keep shared model roles, reasoning baselines and budgets in the project configuration. Within T3, resolve provider/model/options from its live catalog. Translate into the active agent's supported tools instead of hardcoding the current provider into a shared workflow or writing independent global model sheets.
- The vendored P-Stack trees deliberately differ: `.agents/skills/` contains the Codex/Claude-compatible port and `.cursor/skills/` contains the original Cursor version. Preserve their provenance and runtime-specific behavior; coordinate any required edits to both variants. See `.agents/pstack-installation.md`.
- Verify relevant skill discovery, instruction loading, configuration and supported workflows for each affected agent using available read-only or fake-provider checks. Report any unverified runtime or missing capability as remaining compatibility work.

## P-Stack in T3 Code

When using any P-Stack workflow, first read `.agents/pstack-models.md` and, when T3 orchestration is available, `.agents/pstack-t3.md`. These project-local instructions override the vendored skills' harness-specific model defaults, global model-sheet locations and delegation examples. Resolve models and options through T3's live `orchestrator_capabilities` catalog, including enabled custom providers and models. Never limit discovery to the native agent tool's model list. P-Stack workflows do not override the SpacetimeDB documentation check, validation discipline or performance-evidence rules above.

Use T3-owned child tasks for cross-provider work and for models the native subagent tool cannot run. Leave runtime and interaction modes inherited. Resolve model/role effort baselines and budgets from `.agents/pstack-effort.json` through `.agents/scripts/pstack-effort.ts` against the live catalog before dispatch, and pass its validated effort options. When no baseline applies, the session preset leaves effort unchanged; cross-provider defaults may differ from the parent's. Keep Astra manual-only and preserve provider-specific approval settings. Outside T3, use the native runtime's tools and verified models, with the current session model as the fallback. The installed skills are explicitly invoked; no plugin routing hook is installed.

For `setup-pstack`, refresh T3's live catalog, show the resolved project roles and reasoning budgets, and apply requested model choices to `.agents/pstack-models.md` and effort choices to `.agents/pstack-effort.json`. Follow the project adapter's setup procedure instead of the vendored global-sheet and SessionStart-hook steps.

GPT-6.1-Sol is the default implementation coordinator; Claude Opus 5.5 leads UI work (Bevy presentation, input and interaction) and judgment at their saved high-effort baselines. For mixed features, delegate the UI portion to Opus and the authority, simulation and agent logic to Sol with clear interface and file ownership, then verify integration. UI scope overrides generic workflow model defaults for that portion. The policy does not switch the current conversation's provider. See `.agents/pstack-models.md` for routing and unavailable-model behavior.

For quick, easy, narrowly scoped non-UI changes and bounded mechanical batches, use GLM 5.3 through Mistral Vibe at its saved max-effort baseline as the bulk-work delegate. Sol coordinates and reviews the result. Keep UI work with Opus and broad, architectural or unknown-cause work with Sol/judgment; return a GLM assignment to the coordinator if its scope grows.

## Verification surfaces

The living core is verified surface by surface, so a failure can be traced to the layer that owns it. `.agents/skills/verify/SKILL.md` is the entry point. It maps changes and symptoms to surfaces and owns the shared harness: scratch `verify-<run>` databases, the player identity, the observer, cleanup and evidence. The surface skills are:

- `verify-core`: rules and the tick.
- `verify-generation`: worlds from seeds.
- `verify-client`: what a connecting client sees and may call.
- `verify-player`: human players.
- `verify-minds`: the mind service.
- `verify-llm`: model integration.
- `verify-knowledge`: know-how and memory.

The browser observer has no skill; it is a simple developer client that the proper game UI will replace. When that UI is integrated, add a UI skill that clicks through it. When the external-agent connector is implemented, add `verify-agent-external` with a scripted tier and a real-agent tier.

- Before reporting a living-core change as working, run the skill of every surface it touches. Report what was driven, the evidence paths and what was not covered.
- To locate a failure, step down the layers: screen → client → player, or minds → llm and knowledge → core and generation. Name the lowest layer that reproduces it.
- When a change alters a surface's shape, run `maintain-verification-skill` on that surface's skill in the same change. Shape means tables, reducers, views or subscriptions; the mind protocol; seed or model-config formats; UI controls; or launch and run commands. When a change adds a surface, create its skill with `create-verification-skill` and add it to the entry point's surface table. A skill whose map no longer matches the code is a defect, not documentation debt.
- Free tiers use scratch databases and a fake model server. Paid tiers make real model calls and run only after the user authorizes that run. These skills do not establish performance or scale; those claims follow the evidence rules above. Never point a verification run at the paused reference worlds.
