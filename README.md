# Slop Art Online

A greenfield MMORPG built entirely in **Rust**. NPCs are living entities with structured identity — personality, beliefs, knowledge, goals, emotions, and relations — that evolve through experience. The LLM is used sparingly; most behavior is driven by deterministic behavior trees and rule-based systems.

```
Bevy Client (native + WASM)
    ↕ WebSocket (SpacetimeDB protocol)
SpacetimeDB (game state + logic + NPC brain)
    ↕ subscription (NpcPendingDecision)
LLM Bridge (thin, stateless Rust async service)
    ↕
LLM Backend (Cloud API or local Ollama)
```

## Features

- **Living NPCs** — unified behavior trees with priority layers (reactive → awareness → daily life → fallback); identity evolves via cheap inline BT actions and rare LLM experience evaluation
- **LLM-sparing AI** — trees handle combat, movement, and routines; the bridge is called mainly for tree generation (~1–3×/NPC/day) and novel conversation (~5% of exchanges)
- **SpacetimeDB backend** — game state and logic co-located as WASM reducers; clients subscribe to table diffs over WebSocket
- **Bevy client** — same codebase for native desktop and browser (WASM); ECS with client-side prediction
- **Voxel world** — editable terrain with chunked meshing (work in progress)

## Architecture

Three independent Rust tiers:

| Tier | Path | Role |
|------|------|------|
| **SpacetimeDB module** | `server/module/spacetimedb/` | Authoritative game state, reducers, NPC tick (500 ms), behavior trees |
| **Bevy client** | `client/` | Rendering, input, prediction, world presentation |
| **LLM bridge** | `server/bridge/` | Subscribes to pending decisions, calls Ollama/cloud, submits validated results |

**Design constraints:**

- Reducers are **deterministic** — no HTTP, no external randomness, no LLM inside WASM
- Shared types live in `shared/` (generated SpacetimeDB bindings)
- If the bridge crashes, NPCs keep running on behavior trees — no game outage
- LLM output is untrusted; every action is validated by a reducer before execution

For diagrams and deep dives, see [docs/diagrams/](docs/diagrams/) and [docs/adr/](docs/adr/).

## Prerequisites

- [Rust](https://rustup.rs/) (stable toolchain)
- [SpacetimeDB CLI](https://spacetimedb.com/docs) (`spacetime`)
- [Docker](https://docs.docker.com/get-docker/) (for local SpacetimeDB / optional Ollama UI)
- [just](https://github.com/casey/just) (command runner)
- [Ollama](https://ollama.com/) (optional — local LLM for the bridge; on macOS run natively, not in Docker)

WASM target for publishing the server module:

```bash
rustup target add wasm32-unknown-unknown
```

## Quick start

### 1. Start local services

```bash
just up          # SpacetimeDB (:3000) + Open WebUI (:8080) on mac profile
```

On Linux with an NVIDIA GPU you can use the `gpu` profile (includes containerized Ollama). See `deploy/docker-compose.yml`.

### 2. Publish the game module

```bash
just publish-reset   # clear DB and publish (first time / hard reset)
# or
just publish         # incremental publish
just generate        # regenerate Rust client bindings into shared/
```

### 3. Run the LLM bridge (optional but needed for smart NPCs)

```bash
# Defaults: SpacetimeDB at http://localhost:3000, Ollama at http://localhost:11434
export OLLAMA_MODEL=llama3.2   # or whatever you have pulled
cargo run -p bridge
```

### 4. Run the client

```bash
cargo run -p client
```

### Useful commands

| Command | Description |
|---------|-------------|
| `cargo build` | Build all workspace crates |
| `cargo test` | Run all tests |
| `just up` / `just down` | Start / stop docker-compose services |
| `just logs` | Tail SpacetimeDB / compose logs |
| `just publish` | Publish the SpacetimeDB module |
| `just publish-reset` | Delete DB data and republish |
| `just generate` | Regenerate `shared` module bindings |
| `just call <reducer> [args...]` | Call a reducer against the local DB |

## Project structure

```text
slop-art-online/
├── Cargo.toml                 # workspace root
├── Justfile                   # publish, generate, compose helpers
├── STACK_REFERENCE.md         # tech stack rationale
├── CLAUDE.md                  # project guidance for AI assistants
│
├── shared/                    # SpacetimeDB SDK bindings (shared types)
├── client/                    # Bevy game client
├── server/
│   ├── module/spacetimedb/    # WASM game module (reducers, tables, NPC AI)
│   └── bridge/                # LLM bridge service
├── deploy/
│   └── docker-compose.yml     # SpacetimeDB, Open WebUI, optional Ollama
├── docs/
│   ├── adr/                   # Architecture Decision Records
│   ├── diagrams/              # Mermaid system diagrams
│   └── TODO.md                # technical debt tracker
└── unity-client/              # experimental Unity client (optional)
```

## NPC AI (summary)

NPCs use a **unified behavior tree** (no mode switching) with priority layers:

1. **Reactive** — combat response, conversation protocol  
2. **Awareness** — threat evaluation, social cues  
3. **Daily life** — goal pursuit, tasks, exploration  
4. **Fallback** — wander, rest  

Identity evolves through experience:

- Inline BT actions (`SetBelief`, `AddKnowledge`, `AdjustRelationship`) — cheap, no LLM  
- Async experience evaluation after significant events — LLM returns identity deltas  
- Emotion system (anger, fear, joy, sadness, surprise, disgust) — event-triggered, decays toward personality baseline  

Cost model (rough):

| Tier | LLM usage |
|------|-----------|
| Mobs (thousands) | None — static default trees |
| Common NPCs (hundreds) | Tree at dawn + rare events |
| Key NPCs (dozens) | Trees + novel conversations |

See [`server/module/spacetimedb/CLAUDE.md`](server/module/spacetimedb/CLAUDE.md) for the full NPC architecture and [`docs/adr/005-npc-architecture-v2.md`](docs/adr/005-npc-architecture-v2.md) for the design rationale.

## Local services

| Service | Port | Notes |
|---------|------|--------|
| SpacetimeDB | 3000 | Game DB + logic |
| Open WebUI | 8080 | Model management UI (mac/gpu profiles) |
| Ollama | 11434 | Local LLM; native on macOS, container on `gpu` profile |
| LLM bridge | — | Connects to SpacetimeDB + Ollama |

## Documentation

| Doc | Contents |
|-----|----------|
| [STACK_REFERENCE.md](STACK_REFERENCE.md) | Stack overview, Bevy/voxel notes, hosting |
| [docs/adr/](docs/adr/) | Why major decisions were made (start with ADR 005) |
| [docs/diagrams/](docs/diagrams/) | System overview, tick loop, behavior trees, LLM usage |
| [docs/TODO.md](docs/TODO.md) | Migration checklist and tech debt |
| [server/module/spacetimedb/CLAUDE.md](server/module/spacetimedb/CLAUDE.md) | NPC identity, trees, tick loop |
| [server/bridge/CLAUDE.md](server/bridge/CLAUDE.md) | When/how the LLM is called |

## License

This project is licensed under the [MIT License](LICENSE).
