# LLM Bridge Service

The bridge is a thin, stateless Rust async service that connects SpacetimeDB NPCs to LLM backends. It watches for `NpcPendingDecision` rows and routes them to the appropriate LLM handler.

For the full NPC architecture, see `server/module/spacetimedb/CLAUDE.md`.

## When the LLM Is Called

The LLM is expensive. The architecture minimizes calls through two principles:
1. **Behavior trees handle most situations** — combat, movement, routine tasks
2. **Conversation uses templates/knowledge first** — LLM only for novel content

### Current Decision Types (v1)

| Decision Type | LLM Function | Returns | Reducer |
|---|---|---|---|
| `combat_start`, `combat_update` | `generate_combat_tree()` | JSON tree | `submit_npc_combat_tree` |
| `post_combat` | `generate_post_combat()` | JSON plan | `submit_npc_plan` |
| `idle` | `generate_plan()` | JSON plan | `submit_npc_plan` |
| `social` | `generate_social()` | JSON plan | `submit_npc_plan` |
| `reflection` | `generate_reflection()` | JSON (goals/beliefs/memories) | `submit_npc_reflection` |
| `dawn` | `generate_dawn()` | JSON life tree | `submit_npc_life_tree` |
| `significant` | `generate_significant()` | JSON plan + goals/beliefs | `submit_npc_plan` + extras |

### Target Decision Types (v2)

After migration to unified trees, the bridge will handle:

| Decision Type | When | Returns | Reducer |
|---|---|---|---|
| `tree_generation` | Dawn, tree exhaustion, goal change, near-death, self-request | Unified behavior tree JSON | `submit_npc_tree` |
| `experience` | After significant events (near-death, betrayal, discovery) | Identity deltas JSON | `submit_npc_identity_update` |
| `conversation` | Novel topic, important speaker, no template match | Message text | `submit_npc_speech` |

## Cost Model

| NPC Tier | Count | LLM Usage | Cost |
|---|---|---|---|
| Mobs | Thousands | No LLM, static default trees | Zero |
| Common NPCs | Hundreds | Tree at dawn + rare events | ~2-5 calls/day each |
| Key NPCs | Dozens | Trees + novel conversations | ~10-30 calls/day each |

## LLM Backend Strategy

| NPC Type | Backend | Latency |
|---|---|---|
| Key NPCs | Cloud API (Claude, GPT-4o-mini) | 500ms–2s |
| Common NPCs | Local Ollama (Llama 3 8B) | 100–300ms |
| Mobs | No LLM | 0ms |

## Architecture

```
SpacetimeDB                    Bridge                         LLM
─────────────                  ──────                         ───
NpcPendingDecision row  ──→  on_insert callback
                              routes by decision_type
                              assembles prompt (prompt.rs)  ──→  Ollama / Cloud API
                              parses JSON response          ←──  structured JSON
                              calls submit_* reducer        ──→  validates + applies
                              (fallback on failure)
```

### Key Properties
- **Stateless** — holds zero game state, all context comes from the decision row
- **Fault tolerant** — if bridge crashes, NPCs run behavior trees, game continues
- **Hot-reloadable** — swap models or prompt templates without redeploying the DB module
- **Independently scalable** — add more bridge workers for more concurrent LLM calls

### Fallback Behavior
Every decision type has a fallback if the LLM fails:
- Combat: default aggressive tree
- Plans: `["wander"]`
- Social: `"Greetings, traveler."`
- Reflection: empty `{}`
- Dawn: simple wander tree

## Files

| File | Purpose |
|---|---|
| `main.rs` | Connection setup, decision routing, reducer calls |
| `llm.rs` | LLM client (Ollama HTTP), response parsing |
| `prompt.rs` | Prompt templates per decision type |
| `tools.rs` | MCP tool definitions (unused, reserved for future) |

## Configuration

- `HOST` — SpacetimeDB URL (default: `http://localhost:3000`)
- `DB_NAME` — Database name (default: `slop-art-online`)
- LLM endpoint configured in `llm.rs` (default: Ollama at `http://localhost:11434`)

## Response Format

All LLM responses must be JSON. The bridge extracts:
- `steps_json` — behavior tree or plan steps
- `memories` — array of memory text strings
- `goals` — goal definitions (for significant events)
- `beliefs` — belief definitions (for significant events)
- `life_tree` — daily routine tree (for dawn)

Malformed responses trigger the fallback path.
