# Rust stack reference

This document describes the retained technology and architectural boundaries. Product direction lives in the [simulation vision](docs/SIMULATION_VISION.md), implementation limitations in [current state](docs/CURRENT_STATE.md), and build order in the [roadmap](docs/TODO.md). It is not a second feature specification. Source/configuration review: baseline `1736fc1`, 2026-09-04; no build or deployment verification performed here.

The M1 kernel now lives in `simulation/`, called by `foundation.rs` in the existing authoritative module. The Rust bridge also supplies a scenario/model runner and local operator inspector. See the [runbook](docs/M1_RUNBOOK.md); legacy source findings below are not an inventory of the new foundation path.

## Retained architecture

| Tier | Responsibility | Source |
|---|---|---|
| SpacetimeDB Rust/WASM module | Authoritative simulation state, reducers, scheduling, NPC execution and validated consequences | [module](server/module/spacetimedb/Cargo.toml) |
| Bevy Rust client | Supported game client: rendering, input, physics, prediction, and UI | [client](client/Cargo.toml) |
| Rust LLM bridge | Pending-decision subscription, prompt/model calls and returned proposals | [bridge](server/bridge/Cargo.toml) |
| Shared bindings | Generated Rust SpacetimeDB types and reducer interfaces for client/bridge | [shared](shared/Cargo.toml) |

The workspace keeps related types and services together while each tier retains its responsibility. The simulation core must also run without the visual client for experiments. Observation and scenario tools consume this same authority; this milestone does not replace Rust, SpacetimeDB, or Bevy. The Unity client was retired; web-related files or helper commands are not a change in supported game-client direction.

SpacetimeDB reducers are transactional state updates; subscriptions carry state to consumers. Keep network/model calls outside reducers and use supported deterministic inputs and RNG. Deterministic reducer design is not a guarantee of identical full runs with fresh LLM calls or uncontrolled timing. See [replay requirements](docs/AUDIT_AND_EXPERIMENTS.md#fresh-experiments-versus-recorded-decision-replay).

## Dependencies observed in the manifests

| Component | Manifest declaration | Notes |
|---|---|---|
| SpacetimeDB module | `spacetimedb = =2.1.0` | Rust server crate; builds as `cdylib` for WASM |
| Client and bridge SDK | `spacetimedb-sdk = =2.1.0` | Exact SDK pin; match CLI/bindings when regenerating |
| Bevy | `0.18.1` | Game client; foundation uses browser WASM, native is optional |
| Behavior-tree data | `bonsai-bt = 0.11` with serde | Custom evaluator in `npc_ai.rs`; sequence lifecycle gap remains |
| Voxel/physics | `bevy_voxel_world = 0.15`, `avian3d = 0.6.0`, `fast-surface-nets = 0.2` | Existing client terrain/physics dependencies |
| Bridge transport | Tokio, reqwest, serde/serde_json | Current backend implementation calls Ollama |

These are repository declarations, not recommendations to upgrade or claims about the latest releases. `Cargo.lock` records resolved versions. `bevy_replicon` and the old stack document's hypothetical world/faction schemas are not established dependencies or implemented features.

## Game presentation and networking

Bevy remains responsible for rendering, input, physics, audio, and UI. The foundation [browser client](docs/BEVY_BROWSER_CLIENT.md) uses shared Rust render/input systems and caller-scoped subscriptions. Preserved [legacy_main.rs](client/src/legacy_main.rs) registers fixed-update movement/input work and update-time presentation; [player.rs](client/src/player.rs), [interpolation.rs](client/src/interpolation.rs), and [network.rs](client/src/network.rs) contain prediction/reconciliation, interpolation, and subscriptions. Authority stays on the server even when the client predicts presentation or movement. This review does not certify networking correctness, latency budgets, or a particular frame rate.

Native desktop and eventual WASM/browser use remain part of the client direction. Do not infer current browser support, performance parity, or verified packaging from the Rust architecture alone; test the actual target when that work is scheduled.

Existing voxel terrain work is preserved. The [client world module](client/src/world.rs) uses the voxel world plugin and procedural terrain. Server-authoritative editable terrain, NPC world editing through skills, LOD policy, and richer world-generation tooling should be evaluated later against the simulation's needs. Old numerical LOD thresholds and performance forecasts are not milestone requirements. [ADR 006](docs/adr/006-hy-world-2-integration-assessment.md) retains historical world-model research as deferred exploration.

## Local services and commands

Follow the [README quick start](README.md#quick-start) and actual [Justfile](Justfile). The current [compose configuration](deploy/docker-compose.yml) runs SpacetimeDB on port 3000, Open WebUI on 8080 with the mac/gpu profiles, and optional containerized Ollama on 11434 with the gpu profile. On macOS the documented model path is native Ollama; the bridge runs separately with Cargo.

`just publish` and `just publish-reset` use the configured local server; the reset recipe deletes database data. `just generate` generates Rust bindings into `shared/src/module_bindings`. The bridge currently fixes its DB destination in [main.rs](server/bridge/src/main.rs); only its Ollama URL/model are environment-configurable in [llm.rs](server/bridge/src/llm.rs). Concurrent experiments need configurable isolated destinations and recorded run manifests.

Compose uses floating service image tags, so its configuration is not a pinned replay environment. Record actual relevant service versions for experiments. Hosting prices, remote deployment defaults, and external backend choices are outside this document; consult current provider information when that work is requested.

## Architectural history

The useful retained decisions are a Rust workspace, server-owned simulation, generated bindings, a separate model bridge, and real-time behavior execution under model reasoning. [ADR 007](docs/adr/007-simulation-first-foundation.md) changes the implementation order and evidence requirements; [ADR 005](docs/adr/005-npc-architecture-v2.md) preserves unified-tree and identity rationale. Neither an old migration checklist nor a conceptual diagram proves completion.

Future social/economic systems can build on individual goals, communication, relationships, and consequences. Alliances, regional state, population targets, automatic world-balancing interventions, and specific emergent story sequences are not current commitments. Evaluate outcomes without forcing a predetermined narrative.
