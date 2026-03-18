# MMORPG Tech Stack Reference

## Stack Overview

```
Bevy Client (native + WASM)
    ↕ WebSocket (SpacetimeDB protocol)
SpacetimeDB (game state + logic + NPC brain)
    ↕ subscription (NpcPendingDecision table)
LLM Bridge Service (thin, stateless, Rust async)
    ↕
LLM Backend (Cloud API or Local Ollama)
```

- **Server:** SpacetimeDB (logic + database + NPC orchestration)
- **Client:** Bevy (Rust, native desktop + optional WASM/browser)
- **NPC AI:** LLM Bridge (thin external service, stateless)
- **Language:** Rust across the entire stack

---

## Project Structure

### Why Rust Workspace Monorepo
- Single `cargo build` builds everything
- Shared crates (types, utils) referenced locally with zero overhead
- Single `Cargo.lock` = reproducible builds across all crates
- Each crate compiles independently for its target
  (WASM for SpacetimeDB, native/WASM for Bevy, native for bridge)

### Folder Structure

```text
mmorpg/
│
├── Cargo.toml                  ← workspace root
├── .cargo/
│   └── config.toml             ← build targets, aliases
│
├── shared/                     ← shared code, no game logic
│   ├── types/                  ← domain types shared across ALL crates
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── entities.rs     ← Player, Npc, Region structs
│   │       ├── actions.rs      ← NpcDecision, ToolCall, ActionType
│   │       ├── beliefs.rs      ← Belief, Goal, AllianceStatus
│   │       └── events.rs       ← WorldEvent, CombatEvent
│   │
│   └── math/                   ← game math utils (grid, pathfinding, etc.)
│       ├── Cargo.toml
│       └── src/
│           └── lib.rs
│
├── server/
│   ├── module/                 ← SpacetimeDB reducers (compiles to WASM)
│   │   ├── Cargo.toml
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── tables/
│   │       │   ├── mod.rs
│   │       │   ├── player.rs
│   │       │   ├── npc.rs      ← NpcDisposition, NpcGoal, NpcMemory...
│   │       │   ├── alliance.rs
│   │       │   └── world.rs    ← RegionState, WorldEvent
│   │       ├── reducers/
│   │       │   ├── mod.rs
│   │       │   ├── player.rs   ← move, attack, interact
│   │       │   ├── npc.rs      ← npc_tick, submit_npc_decision
│   │       │   ├── alliance.rs ← propose_alliance, accept, dissolve
│   │       │   └── world.rs    ← resource_tick, world_balance
│   │       ├── schedulers/
│   │       │   ├── mod.rs
│   │       │   ├── npc_tick.rs
│   │       │   ├── resource.rs
│   │       │   └── invisible_hand.rs
│   │       └── logic/          ← pure deterministic logic, no I/O
│   │           ├── mod.rs
│   │           ├── combat.rs
│   │           ├── belief_propagation.rs
│   │           ├── goal_evaluation.rs
│   │           ├── validation.rs
│   │           └── behavior_tree.rs
│   │
│   └── bridge/                 ← LLM bridge service (thin, stateless)
│       ├── Cargo.toml
│       └── src/
│           ├── main.rs
│           ├── subscriber.rs   ← watches NpcPendingDecision table
│           ├── prompt/
│           │   ├── mod.rs
│           │   ├── assembler.rs ← builds LLM prompt from context snapshot
│           │   └── templates/   ← prompt template files (.txt or .jinja)
│           │       ├── merchant.txt
│           │       ├── guard.txt
│           │       └── warlord.txt
│           ├── llm/
│           │   ├── mod.rs
│           │   ├── client.rs   ← trait LlmBackend
│           │   ├── cloud.rs    ← Claude / GPT-4o-mini impl
│           │   └── local.rs    ← Ollama impl
│           ├── mcp/
│           │   ├── mod.rs
│           │   ├── tools.rs    ← MCP tool definitions
│           │   └── parser.rs   ← parse LLM output → structured ToolCall
│           └── moderation.rs   ← output filter / jailbreak guard
│
├── client/
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs
│       ├── lib.rs              ← WASM entry point (wasm target)
│       ├── network/
│       │   ├── mod.rs
│       │   ├── spacetimedb.rs  ← connection, subscriptions
│       │   └── reconcile.rs   ← server reconciliation logic
│       ├── prediction/
│       │   ├── mod.rs
│       │   └── input_buffer.rs ← stores unacknowledged inputs
│       ├── systems/
│       │   ├── mod.rs
│       │   ├── movement.rs     ← FixedUpdate prediction systems
│       │   ├── combat.rs
│       │   ├── npc.rs          ← rendering NPC state + dialogue UI
│       │   └── world.rs        ← terrain, regions, events
│       ├── ui/
│       │   ├── mod.rs
│       │   ├── hud.rs
│       │   ├── dialogue.rs     ← NPC conversation interface
│       │   └── minimap.rs
│       └── assets.rs           ← asset loading handles
│
├── assets/                     ← Bevy assets (loaded at runtime)
│   ├── models/
│   ├── textures/
│   ├── audio/
│   ├── shaders/
│   └── ui/
│
├── tools/                      ← internal dev tooling
│   ├── map_editor/             ← optional: custom Bevy editor tool
│   └── npc_tester/             ← CLI to test NPC decisions in isolation
│
├── deploy/
│   ├── docker-compose.yml      ← local dev: SpacetimeDB + Ollama + bridge
│   ├── bridge.Dockerfile
│   └── spacetimedb.Dockerfile
│
└── docs/
    ├── MMORPG_STACK_REFERENCE.md  ← this document!
    ├── architecture/
    │   ├── npc_ai.md
    │   ├── combat.md
    │   └── emergence.md
    └── adr/                    ← Architecture Decision Records
        ├── 001-spacetimedb.md
        ├── 002-bevy.md
        └── 003-llm-bridge.md
```

### Workspace `Cargo.toml`

```toml
[workspace]
resolver = "2"
members = [
    "shared/types",
    "shared/math",
    "server/module",
    "server/bridge",
    "client",
    "tools/npc_tester",
]

# Shared dependency versions across all crates
[workspace.dependencies]
bevy        = "0.15"
tokio       = { version = "1", features = ["full"] }
serde       = { version = "1", features = ["derive"] }
serde_json  = "1"
anyhow      = "1"
tracing     = "1"

# Your shared crates — referenced locally
types = { path = "shared/types" }
math  = { path = "shared/math" }
```

### `.cargo/config.toml`

```toml
[alias]
dev     = "run --package bridge"
client  = "run --package client"
test-ai = "run --package npc_tester"

[target.wasm32-unknown-unknown]
runner = "spacetime publish"
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| `shared/types` imported by all crates | Define once, no copy-paste structs across crates |
| `server/module/logic/` is pure functions | No I/O = easily unit testable, provably deterministic |
| `tools/npc_tester` | Test NPC/LLM behavior without running the full stack |
| `docs/adr/` | Record *why* each major decision was made |

---

## SpacetimeDB

### What it is
A database + game server merged into one. Application logic (reducers)
runs inside the database as WebAssembly modules. Clients connect directly
via WebSockets — no separate server layer needed.

### Key Features
- Real-time state sync pushed automatically to all subscribed clients
- Reducers = atomic, transactional game logic (ACID guaranteed)
- Built-in schedulers for timed events (NPC ticks, respawns, world events)
- One module = your entire backend
- Single source of truth for ALL state (game, NPC, world, alliances)

### Server Logic Options
| Language | Notes |
|---|---|
| Rust | Best performance |
| C# | Easier for Unity-background devs |

### Client SDKs
| Platform | SDK |
|---|---|
| Bevy / Native Rust | Rust SDK ✅ |
| Unity | C# ✅ (most mature) |
| Unreal Engine | C++ + Blueprint ✅ |
| Web | TypeScript ✅ |
| Godot | ❌ No official SDK |

### Hosting
- **Maincloud** (managed): free tier ~3M reducer calls/month,
  Pro at $25/month (~120M calls/month)
- **Self-host**: open source (AGPL)

### Caveats
- No built-in auth (wire up OpenAuth or similar)
- Single-node per database (scales vertically, not horizontally)
  — fine for indie/mid-size, evaluate Enterprise for massive scale
- APIs can still shift between major versions

### Proof of Concept
- **BitCraft Online** — full MMORPG running entirely on SpacetimeDB
  (chat, inventory, terrain, player positions)

---

## Client: Bevy

### Why Bevy
- Rust-native, same language as SpacetimeDB server logic
- Compiles to both **native desktop** and **WASM (browser)** from the
  same codebase
- Built on `wgpu` → WebGPU-powered rendering on both targets
- ECS architecture maps naturally to SpacetimeDB's table/entity model

### Key Crates
| Crate | Purpose |
|---|---|
| `bevy` | Core engine (rendering, ECS, audio, input, etc.) |
| `wgpu` | WebGPU rendering backend (used by Bevy internally) |
| `bevy_replicon` | Entity replication, prediction & reconciliation |
| `bevy_voxel_world` | Chunk management, dynamic editing, LOD, multithreaded meshing |
| `block-mesh-rs` | Underlying greedy mesh generation (used by bevy_voxel_world) |
| `avian3d` | Physics + collision (preferred over rapier for voxel worlds) |
| `noise` | Procedural terrain generation |

### ⚠️ Warning
Bevy still has breaking API changes roughly every 3 months. Pin your
version in `Cargo.toml`.

---

## Voxel World

### Design Goals
- Fully editable by both players and NPCs in real-time
- High resolution small voxels — blockiness becomes grain, not a visual problem
- Performant at world scale via chunking + LOD

### Shape Decision: Cubes
True 3D hex/oct voxels don't tessellate 3D space (they leave gaps).
Shapes that do tessellate: cubes, truncated octahedra, rhombic dodecahedra.
At high resolution the visual difference between these is negligible.
**Cubes are used** — far simpler mesh generation, better ecosystem support,
no meaningful visual downside at small voxel sizes.

### Architecture

```
SpacetimeDB (authority)          Bevy Client (rendering)
─────────────────────            ───────────────────────
chunk table                      bevy_voxel_world plugin
  chunk_pos: (i32, i32, i32)       ↓ set_voxel() on diff
  data: Vec<u8> (compressed)     chunk remeshes automatically
  dirty: bool

edit_voxel reducer               Player/NPC edits locally
  → validates edit               → calls edit_voxel reducer
  → updates chunk table          → SpacetimeDB broadcasts diff
  → broadcasts to all clients    → all clients remesh affected chunk
```

### Chunk Data Flow
```
Player/NPC edits voxel
  → edit_voxel reducer (SpacetimeDB)
  → chunk table updated
  → all subscribed clients receive diff
  → each client: set_voxel() → chunk remesh (multithreaded)
```

### LOD Strategy
```
< 64 units   → full resolution voxels
64–256 units → merged/simplified chunk mesh
> 256 units  → impostor mesh or heightmap
```

### Ecosystem State (March 2026)
The Bevy voxel ecosystem is not mature — no production-shipped game uses it.

| Crate | Role | Status |
|---|---|---|
| `bevy_voxel_world` | World system, LOD, editing | Best available, tracks Bevy 0.18 |
| `bevy_meshem` | Mesh algorithms only | Pre-release, behind on Bevy versions |
| `vx_bevy` | Reference architecture | Archived, Bevy 0.13 |
| `logic_voxels` | Multiplayer reference | Archived, Bevy 0.10 |

**No voxel crate handles networking** — SpacetimeDB fills this gap via
chunk table subscriptions.

### Build Order
1. Static 3D world rendering (terrain gen + chunk rendering, no editing)
2. Single-player editing (local set_voxel, no sync)
3. Networked editing (edit_voxel reducer + SpacetimeDB broadcast)
4. NPC world editing (NPCs call edit_voxel reducer)
5. LOD + performance pass

---

## Web / Browser Target

### GPU Acceleration
WebGPU is the browser GPU API, fully supported as of early 2026:
| Browser | Status |
|---|---|
| Chrome / Edge | ✅ Since v113 (2023) |
| Firefox | ✅ Since v147 (Jan 2026) |
| Safari | ✅ Since iOS/macOS Tahoe 26 |

WebGPU maps to Vulkan / Metal / Direct3D 12 under the hood.

### Web vs. Native Performance
| Metric | Web (WebGPU) | Native |
|---|---|---|
| GPU rendering | ~80–90% | 100% |
| CPU logic (WASM) | ~80–90% | 100% |
| Memory | Browser-sandboxed | Full system RAM |

For an MMORPG this gap is acceptable — 60fps in browser is easily
achievable.

### Caveats
- ~30% of global users may need a WebGL fallback
- Some GPU vendor-specific driver bugs exist

---

## Networking Architecture (High APM Combat)

### The Problem
Naive authoritative-server model:
```
Player presses key → server → processes → client renders
```
Every action is delayed by RTT (60–200ms). Unacceptable for high APM
combat.

### The Solution: 3 Pillars

**1. Client-Side Prediction**
- Client immediately simulates the result of player input locally
- No waiting for server — player feels 0ms latency on own actions

**2. Server Reconciliation**
- Server sends back authoritative state
- Client compares to its predicted state
- If diverged: replay unacknowledged inputs on top of server state
- Minimizes rubber-banding

**3. Entity Interpolation**
- Other players' positions interpolated between last two server snapshots
- Smooth appearance even at 20 server ticks/sec
- Rendered ~100ms in the "past" — acceptable trade-off

---

## Bevy Scheduling

```
FixedUpdate (60Hz)   → game simulation (prediction, physics, cooldowns)
Update (uncapped)    → rendering, interpolation, VFX, UI
```

- Game logic is deterministic at 60 ticks/sec
- Rendering runs at max GPU speed (144fps, 240fps, etc.)
- Bevy handles Transform interpolation between fixed ticks automatically

---

## Combat System Design

| Concern | Solution |
|---|---|
| Skills feel instant | Client-side prediction |
| Cooldowns feel accurate | Run timer locally, validate server-side |
| Hit detection | Server-authoritative, show FX immediately on client |
| Iframes / dodge windows | ±1–2 frame server tolerance for latency |
| Ability queuing | Queue 1–2 inputs ahead locally, flush to server each tick |

> **Design tip:** GW2's combat feels great at high latency because of
> generous server-side tolerance windows on dodge iframes.
> Design *around* latency, don't fight it.

---

## NPC AI System

### Core Principle
```
SpacetimeDB = the NPC's body, memory, and rules of physics
LLM Bridge  = the NPC's creative thought process
```

The body works fine without creative thought (behavior trees kick in as
fallback). The creative thought has no power without the body executing
and validating it.

### Why a Separate LLM Bridge is Needed

SpacetimeDB reducers are ACID transactions that must be **fully
deterministic**. LLMs are stochastic (non-deterministic) by nature.
Additionally, reducers run in a WASM sandbox with no outbound HTTP access.

Therefore:
- **~90% of NPC AI logic** → SpacetimeDB reducers
- **~10% (LLM inference only)** → thin external bridge service

### What Lives Where

| Component | Location |
|---|---|
| Belief storage + retrieval | ✅ SpacetimeDB tables + reducers |
| Belief propagation rules | ✅ Reducer logic |
| Relationship score updates | ✅ Reducer logic |
| Goal evaluation (rule-based) | ✅ Reducer logic |
| Alliance formation rules | ✅ Reducer logic |
| Validation gate | ✅ Reducer logic |
| NPC scheduling / ticks | ✅ SpacetimeDB schedulers |
| World state changes | ✅ Tables + reducers |
| Action execution | ✅ Reducers |
| LLM inference call | ❌ LLM Bridge only |
| MCP tool orchestration | ❌ LLM Bridge only |
| Prompt assembly | ❌ LLM Bridge only |

### Decision Flow

```
1. SpacetimeDB scheduler fires npc_tick(npc_id)
        │
        ├── Interesting situation? → NO → run behavior tree, done
        │
        └── YES → write NpcPendingDecision row

2. LLM Bridge (subscribed to NpcPendingDecision)
        ├── reads context snapshot from row
        ├── assembles prompt (persona + world context + memory + tools)
        ├── calls LLM API
        └── calls reducer: submit_npc_decision(npc_id, decision)

3. submit_npc_decision reducer
        ├── validation gate (LLM is untrusted!)
        ├── executes valid actions (modifies world, broadcasts to clients)
        └── deletes NpcPendingDecision row
```

### LLM Bridge Properties
- **Stateless** — holds zero game state
- **Fault tolerant** — if it crashes, NPCs fall back to behavior trees,
  game keeps running
- **Hot-reloadable** — swap models or prompt templates without touching
  the DB module
- **Independently scalable** — add more bridge workers without touching
  SpacetimeDB

### Why Keep the Bridge Decoupled

| Reason | Why it matters |
|---|---|
| Swappable LLM backends | Swap Claude → Llama → GPT-4o-mini freely |
| Independent scaling | Scale LLM workers horizontally |
| Cost control | Rate-limit, queue, and batch LLM calls independently |
| Fault isolation | Bridge crash → game runs fine on behavior trees |
| Hot reload | Update prompts/models without redeploying DB module |

---

## NPC Data Model (SpacetimeDB Tables)

```rust
// NPC core identity
pub struct NpcDisposition {
    pub npc_id: u64,
    pub archetype: Archetype,       // Merchant, Guard, Warlord, Cultist...
    pub core_values: Vec<Value>,    // Wealth, Safety, Power, Loyalty...
    pub risk_tolerance: f32,        // 0.0 coward → 1.0 reckless
    pub political_alignment: Faction,
}

// What the NPC wants right now
pub struct NpcGoal {
    pub npc_id: u64,
    pub goal: GoalType,             // Survive, Accumulate, Avenge, Protect...
    pub priority: f32,
    pub triggered_by: Option<EventId>,
    pub target_entity: Option<u64>,
}

// What the NPC remembers about players
pub struct NpcMemory {
    pub npc_id: u64,
    pub player_id: u64,
    pub summary: String,            // LLM-compressed conversation summary
    pub relationship: i32,          // -100 hostile → +100 trusted
    pub last_seen: Timestamp,
}

// What the NPC believes (possibly heard from other NPCs)
pub struct NpcBelief {
    pub npc_id: u64,
    pub belief: String,             // "Player123 is a thief"
    pub confidence: f32,
    pub source_npc_id: Option<u64>, // heard from another NPC?
}

// NPC-to-NPC relationships
pub struct NpcRelationship {
    pub from_npc: u64,
    pub to_entity: u64,
    pub trust: i32,                 // -100 to +100
    pub shared_beliefs: Vec<BeliefId>,
    pub alliance_status: AllianceStatus, // None, Tentative, Formal, Sworn
}

// Bridge communication
pub struct NpcPendingDecision {
    pub npc_id: u64,
    pub context_snapshot: Vec<u8>, // serialized context for prompt assembly
    pub requested_at: Timestamp,
}
```

---

## MCP Tools (NPC Capabilities)

Each NPC type has a defined set of MCP tools it can invoke. The LLM
proposes tool calls; the validation gate in SpacetimeDB decides if they
are legal.

| MCP Tool | What the NPC can do |
|---|---|
| `query_nearby_players` | Sense who is around, their level/faction |
| `query_world_state` | Time of day, weather, active events |
| `query_npc_memory` | Recall past interactions with a player |
| `start_quest` | Offer a quest to a player |
| `open_trade` | Initiate a trade interface |
| `move_to` | Navigate to a location |
| `attack_target` | Initiate combat (server-validated) |
| `emit_emotion` | Trigger animation states (wave, cower, etc.) |
| `update_relationship` | Adjust relationship score with a player |
| `broadcast_belief` | Tell nearby NPCs something (NPC-to-NPC gossip) |
| `propose_alliance` | Formally propose an alliance to another NPC |
| `recruit_npc` | Invite an NPC to join a faction/alliance |

---

## LLM Backend Strategy

| NPC Type | Backend | Latency | Notes |
|---|---|---|---|
| Named/key NPCs | Cloud API (Claude, GPT-4o-mini) | 500ms–2s | Best quality |
| Common NPCs | Self-hosted Llama 3 8B (Ollama) | 100–300ms | Good quality |
| Bulk ambient NPCs | Fine-tuned TinyLlama / behavior tree | ~100ms | Cost-effective |

### Handling LLM Latency Gracefully
- Show a **"thinking" animation** while awaiting response
- Use **streaming** — display dialogue word-by-word as it generates
- **Pre-generate** ambient dialogue during NPC idle time and cache it
- **Fallback lines** if LLM times out — plausible generic dialogue

---

## Emergent Narrative System

### How Emergence Arises
No scripting required. Emergence falls out naturally from:
- NPCs pursuing individual goals
- Beliefs propagating through the NPC social graph
- Alliance formation when goals align
- World state reacting to NPC and player actions

### Belief Propagation Example
```
Player kills merchant's son
  → Merchant: belief "Player123 is murderer", relationship → -100
  → Tells Innkeeper (trust 90) → refuses player service
  → Tells Guard Captain (trust 70) → raises regional threat level
  → Tells Guild Master (trust 85) → blacklists player, issues bounty
  → Assassin NPC accepts bounty contract
```

### Alliance Formation Example
```
Players over-farm Eastern Forest
  → WoodcutterNPC goal: PROTECT_RESOURCE
  → Shares belief with RangerNPC (aligned goal: PROTECT_NATURE)
  → Alliance: Tentative → DruidNPC joins → Formal
  → Alliance recruits WolfPackNPC → controls forest access
  → Players must negotiate treaty or be hunted
  → MerchantNPC notices lumber shortage → prices rise
  → Builders Guild opposes alliance → players must choose sides
```

### Emergence Layers

| Layer | Description |
|---|---|
| 1 — Individual | Single NPC reacts to player actions |
| 2 — Social | Beliefs and reputation spread NPC-to-NPC |
| 3 — Alliance | NPCs coordinate toward shared goals |
| 4 — Political | Internal hierarchies emerge within alliances |
| 5 — Economic | Resource control shifts prices, drives new alliances |
| 6 — Historical | Alliances carry cultural memory of their origins |

### World State Tables

```rust
pub struct RegionState {
    pub region_id: u64,
    pub controlling_faction: Option<FactionId>,
    pub threat_level: f32,
    pub resource_levels: HashMap<ResourceType, f32>,
    pub active_conflicts: Vec<ConflictId>,
    pub laws: Vec<Law>,
    pub tax_rate: f32,
}

pub struct WorldEvent {
    pub event_id: u64,
    pub event_type: WorldEventType, // War, Famine, Plague, Festival, Treaty
    pub instigated_by: EntityId,    // NPC or player who caused it
    pub affected_regions: Vec<u64>,
    pub start_time: Timestamp,
    pub resolved: bool,
}
```

### Guardrails (Prevent Runaway Emergence)

| Risk | Guardrail |
|---|---|
| NPCs dominate the entire world | Cap max faction territory / power |
| Runaway negative feedback loops | Resources have a slow regeneration floor |
| Alliance grief-locks new players | Starter zones are faction-neutral |
| Inappropriate alliance goals | Goal type whitelist |
| World becomes unplayable | "Invisible Hand" world balance scheduler |

### The Invisible Hand
A background SpacetimeDB scheduler periodically checks world balance.
If any faction controls >40% of the world, it triggers a counter-event
(rival faction rises, new resource appears, charismatic NPC spawns to
rally opposition). Players see the consequence, never the mechanism.

---

## Build Order Recommendation

Build the NPC system in layers — each is independently shippable:

1. **Behavior trees only** — deterministic, no LLM, prove the game loop
2. **Belief propagation** — NPC-to-NPC gossip, reputation spreading
3. **LLM dialogue** — named NPCs converse with players
4. **Goal system** — NPCs pursue individual goals
5. **Alliance formation** — goal alignment triggers cooperation
6. **World-state consequences** — alliances reshape regions and economy
7. **Emergent political structures** — faction hierarchies, treaties, wars

---

## Local Dev Environment

```yaml
# deploy/docker-compose.yml
services:
  spacetimedb:
    image: clockworklabs/spacetimedb:latest
    ports:
      - "3000:3000"
    volumes:
      - spacetimedb_data:/var/lib/spacetimedb

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]  # remove if no GPU

  bridge:
    build:
      context: .
      dockerfile: deploy/bridge.Dockerfile
    environment:
      SPACETIMEDB_URL: ws://spacetimedb:3000
      OLLAMA_URL: http://ollama:11434
      CLOUD_LLM_API_KEY: ${CLOUD_LLM_API_KEY}
    depends_on:
      - spacetimedb
      - ollama

volumes:
  spacetimedb_data:
  ollama_data:
```

---

## Full Architecture Diagram

```
┌──────────────────────────────────────────────┐
│              Bevy Client                     │
│                                              │
│  FixedUpdate (60Hz)                          │
│    ├── Capture input                         │
│    ├── Client-side prediction                │
│    │     (movement, skills, cooldowns)       │
│    └── Send reducer calls                    │
│                                              │
│  Update (uncapped FPS)                       │
│    ├── Interpolate remote entities           │
│    ├── Reconcile prediction vs server        │
│    └── Render + VFX + UI                    │
└──────────────────┬───────────────────────────┘
                   │ WebSocket
┌──────────────────▼───────────────────────────┐
│              SpacetimeDB                     │
│                                              │
│  Player state + combat                       │
│  NPC state (beliefs, goals, relationships)   │
│  Alliance state (members, treaties)          │
│  World state (regions, resources, events)    │
│                                              │
│  Reducers                                    │
│    ├── Validate + apply all actions          │
│    ├── Belief propagation engine             │
│    ├── Goal evaluation engine                │
│    ├── Alliance formation rules              │
│    └── Broadcast diffs to all subscribers   │
│                                              │
│  Schedulers                                  │
│    ├── NPC tick → NpcPendingDecision         │
│    ├── Resource regeneration                 │
│    └── Invisible Hand world balancer         │
└──────────────────┬───────────────────────────┘
                   │ subscription (NpcPendingDecision)
┌──────────────────▼───────────────────────────┐
│         LLM Bridge Service (thin)            │
│              Rust async, stateless           │
│                                              │
│    ├── Assemble prompt from context          │
│    ├── Call LLM API                          │
│    ├── Parse response → structured decision  │
│    └── Call submit_npc_decision reducer      │
│                                              │
│    Fallback: if bridge is down,              │
│    SpacetimeDB NPCs run behavior trees       │
└──────────────────┬───────────────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
┌──────▼──────┐       ┌────────▼────────┐
│  Cloud API  │       │  Local Ollama   │
│  (Claude /  │       │  (Llama 3 8B)   │
│  GPT-4o)    │       │                 │
│  Named NPCs │       │  Common NPCs    │
└─────────────┘       └─────────────────┘
```

---

## Quick Reference: Alternatives Considered

| Option | Verdict |
|---|---|
| Unity + SpacetimeDB | ✅ Best for small teams / Unity experience |
| Unreal + SpacetimeDB | ✅ Best for high-end 3D visuals |
| Web (TypeScript + Phaser/Three.js) | ✅ Best for browser accessibility |
| Godot + SpacetimeDB | ❌ No official SDK |
| macroquad (Rust) | ✅ Good for simple 2D, not ideal for MMORPG scale |
| Fyrox (Rust) | ✅ Has editor, but WASM support less polished |
| Raw wgpu (Rust) | ⚠️ Max control, write your own renderer from scratch |

---

## Useful Links

- [SpacetimeDB Docs](https://spacetimedb.com/docs)
- [Bevy Engine](https://bevyengine.org)
- [Are We Game Yet? (Rust ecosystem)](https://arewegameyet.rs)
- [wgpu](https://wgpu.rs)
- [bevy_replicon](https://github.com/projectharmonia/bevy_replicon)
- [BitCraft Online (SpacetimeDB showcase)](https://bitcraftonline.com)
- [Ollama (local LLM hosting)](https://ollama.com)
- [Model Context Protocol](https://modelcontextprotocol.io)
