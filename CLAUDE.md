# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**slop-art-online** is a greenfield MMORPG built entirely in Rust. The authoritative architectural spec is in `STACK_REFERENCE.md` — read it before making significant design decisions.

## Build & Run

```bash
cargo build          # build all crates
cargo run            # run the current entry point
cargo test           # run all tests
cargo test <name>    # run a single test by name
```

Planned cargo aliases (not yet configured in `.cargo/config.toml`):
```bash
cargo dev       # run --package bridge (LLM bridge service)
cargo client    # run --package client (Bevy client)
cargo test-ai   # run --package npc_tester
```

## Architecture

Three independent tiers, all Rust:

### 1. SpacetimeDB (backend)
- Database + game logic co-located as WASM modules inside the DB
- **Reducers** = atomic transactions (player actions, NPC decisions)
- **Schedulers** = timed events (NPC ticks, resource respawns, world balance)
- Single source of truth for all game state; clients subscribe to table diffs via WebSocket
- Lives in `server/module/`

### 2. Bevy Client (frontend)
- Same codebase targets native desktop and WASM/browser
- ECS architecture: `FixedUpdate` (60 Hz) for deterministic logic, `Update` (uncapped) for rendering
- Implements **client-side prediction** + **server reconciliation** for low-latency feel
- Lives in `client/`

### 3. LLM Bridge (separate service)
- Thin, stateless Rust async service — not a game server
- Subscribes to `NpcPendingDecision` table in SpacetimeDB
- Assembles prompts → calls LLM API (Claude/GPT-4o-mini for key NPCs, local Ollama for common NPCs) → parses MCP tool calls → submits back via `submit_npc_decision` reducer
- **LLM output is untrusted**: the reducer validates every action before execution
- If the bridge crashes, NPCs fall back to behavior trees — no game outage
- Lives in `server/bridge/`

## NPC AI Decision Flow

```
npc_tick scheduler (SpacetimeDB)
  → situation interesting? NO → run behavior tree
  → YES → write NpcPendingDecision row

LLM Bridge (watching NpcPendingDecision)
  → assemble prompt (persona + world + memory + MCP tools)
  → call LLM
  → submit_npc_decision reducer

submit_npc_decision reducer
  → validate (LLM is untrusted!)
  → execute actions
  → delete NpcPendingDecision row
```

## Key Design Constraints

- **Reducers must be deterministic** — no HTTP calls, no randomness outside seeded RNG, no LLM inside SpacetimeDB WASM
- **Shared types live in `shared/`** — used by both server and client with zero-overhead
- **Build target for SpacetimeDB modules is WASM** (`wasm32-unknown-unknown`)
- The LLM bridge is the only tier that touches external APIs

## Planned Workspace Structure

```
Cargo.toml          (workspace root)
shared/             (domain types, game math, pathfinding)
server/
  module/           (SpacetimeDB reducers — WASM target)
  bridge/           (LLM bridge service)
client/             (Bevy game client)
tools/
  npc_tester/       (CLI to test NPC decisions in isolation)
deploy/             (docker-compose, Dockerfiles)
docs/adr/           (Architecture Decision Records)
```

## Local Dev Services (docker-compose)

| Service      | Port  | Notes                        |
|-------------|-------|------------------------------|
| SpacetimeDB | 3000  |                              |
| Ollama      | 11434 | optional GPU passthrough     |
| LLM Bridge  | —     | connects to both above       |
