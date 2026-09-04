# LLM Bridge Service

The bridge is a thin, stateless Rust async service that connects SpacetimeDB NPCs to LLM backends. It watches for `NpcPendingDecision` rows and routes them to the appropriate LLM handler.

For the full NPC architecture, see `server/module/spacetimedb/CLAUDE.md`.

## When the LLM Is Called

The LLM is expensive. The architecture minimizes calls through two principles:
1. **Behavior trees handle most situations** — combat, movement, routine tasks
2. **Conversation uses templates/knowledge first** — LLM only for novel content

### Decision Types (v2 — current)

| Decision Type | When | LLM Function | Returns | Reducer |
|---|---|---|---|---|
| `tree_generation` | Dawn, tree exhaustion, goal change, near-death, self-request | `generate_tree()` | Unified behavior tree JSON | `submit_npc_tree` |
| `experience` | After significant events (near-death, betrayal, discovery) | `generate_experience_eval()` | Identity deltas JSON | `submit_npc_identity_update` |
| `conversation` | Novel topic, important speaker, no template match | `generate_conversation()` | Message text | `submit_npc_speech` |

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
- Tree generation: submit empty string (clears pending decision, NPC keeps default tree)
- Experience: submit empty `{}` (no identity changes)
- Conversation: submit `"Hmm..."` (minimal acknowledgment)

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

Each decision type expects a different response format:
- `tree_generation` — JSON behavior tree (`Behavior<NpcBtAction>`)
- `experience` — JSON with `personality_deltas`, `beliefs`, `knowledge`, `relationship_updates`, `emotion_adjustments`
- `conversation` — plain text message (parsed via `parse_conversation_response()`)

Malformed responses trigger the fallback path.
