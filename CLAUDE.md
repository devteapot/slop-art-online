# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**slop-art-online** is a greenfield MMORPG built entirely in Rust. NPCs are living entities with structured identity (personality, beliefs, knowledge, goals, emotions, relations) that evolve through experience. The LLM is used sparingly — most behavior is driven by deterministic behavior trees and rule-based systems.

For deep architectural context, see:
- `STACK_REFERENCE.md` — High-level tech stack and design rationale
- `docs/adr/` — Architecture Decision Records (start with ADR 005 for the current NPC architecture)
- `server/module/spacetimedb/CLAUDE.md` — NPC identity, behavior trees, tick loop
- `server/bridge/CLAUDE.md` — LLM bridge, when/how the LLM is called

## Build & Run

```bash
cargo build                # build all crates
cargo run                  # run the current entry point
cargo test                 # run all tests
cargo test <name>          # run a single test by name
just publish-reset         # clear DB and republish SpacetimeDB module
just generate              # regenerate client bindings
just up                    # start local dev services (docker-compose)
just logs                  # view SpacetimeDB logs
```

## Architecture

Three independent tiers, all Rust:

### 1. SpacetimeDB (backend) — `server/module/spacetimedb/`
- Database + game logic co-located as WASM modules inside the DB
- **Reducers** = atomic, deterministic transactions (player actions, NPC tick, LLM response validation)
- **Schedulers** = timed events (NPC tick every 500ms, day/night cycle)
- Single source of truth for all game state; clients subscribe to table diffs via WebSocket

### 2. Bevy Client (frontend) — `client/`
- Same codebase targets native desktop and WASM/browser
- ECS architecture: `FixedUpdate` (60 Hz) for deterministic logic, `Update` (uncapped) for rendering
- Implements client-side prediction + server reconciliation

### 3. LLM Bridge (separate service) — `server/bridge/`
- Thin, stateless Rust async service
- Subscribes to `NpcPendingDecision` table in SpacetimeDB
- Called only for: **tree generation** (~1-3 times/NPC/day) and **novel conversation content** (~5% of exchanges)
- **LLM output is untrusted**: the reducer validates every action before execution
- If the bridge crashes, NPCs fall back to behavior trees — no game outage

## NPC AI — How It Works

NPCs use a **unified behavior tree** (no mode switching) with priority layers:
1. **Reactive** — combat response, conversation protocol
2. **Awareness** — threat evaluation, social cues
3. **Daily Life** — goal pursuit, tasks, exploration
4. **Fallback** — wander, rest

The tree handles most situations through runtime conditions (emotions, beliefs, knowledge). The LLM regenerates the tree only at dawn, after major events, or when the tree is exhausted.

**Identity** evolves through experience:
- Inline BT actions (SetBelief, AddKnowledge, AdjustRelationship) — cheap, no LLM
- Async experience evaluation after significant events — LLM returns identity deltas
- Emotion system (anger, fear, joy, sadness, surprise, disgust) — event-triggered, decays toward personality baseline

See `server/module/spacetimedb/CLAUDE.md` for the full NPC architecture.

## Key Design Constraints

- **Reducers must be deterministic** — no HTTP, no randomness outside `ctx.rng`, no LLM inside WASM
- **Shared types live in `shared/`** — SpacetimeDB SDK bindings used by both server and client
- **Build target for SpacetimeDB modules is WASM** (`wasm32-unknown-unknown`)
- **The LLM bridge is the only tier that touches external APIs**
- **New code goes into existing modules** — never back into the monolith `lib.rs`

## Workspace Structure

```
Cargo.toml                      (workspace root)
shared/                         (SpacetimeDB SDK bindings, shared types)
server/
  module/
    spacetimedb/                (SpacetimeDB reducers — WASM target)
      src/
        lib.rs                  (reducers, tick_npcs, main game loop)
        tables.rs               (all table definitions)
        npc_ai.rs               (behavior trees, BT evaluation, actions)
        constants.rs            (tuning parameters)
        combat.rs               (combat logic)
  bridge/                       (LLM bridge service)
    src/
      main.rs                   (decision routing, LLM calls)
client/                         (Bevy game client)
deploy/                         (docker-compose)
docs/
  adr/                          (Architecture Decision Records)
  TODO.md                       (technical debt tracker)
```

## Local Dev Services (docker-compose)

| Service      | Port  | Notes                    |
|-------------|-------|--------------------------|
| SpacetimeDB | 3000  |                          |
| Ollama      | 11434 | optional GPU passthrough |
| LLM Bridge  | —     | connects to both above   |
