# ADR 001 — NPC Combat Strategy Revision Loop

## Status
Planned

## Context

The current NPC AI calls the LLM once at the start of an encounter (when the player
enters detection range) and generates a behaviour graph the NPC follows for the rest
of the fight. This has two problems:

1. The initial context is minimal — just position, health, and player distance.
   The LLM has nothing meaningful to differentiate strategies with.
2. The NPC cannot adapt mid-fight regardless of how the battle unfolds.

## Decision

Replace the single LLM call per encounter with a **condition-driven revision loop**:

```
Encounter starts
  → NPC uses default combat graph immediately (no LLM wait)
  → SpacetimeDB accumulates combat stats each tick
  → Revision triggered when ANY condition is met:
      - damage_received > damage_dealt (I'm losing)
      - health drops below 50% threshold
      - interval elapsed (every ~10s) while fight is ongoing
  → LLM receives full battle report as context
  → New graph submitted, stats reset, loop continues
```

## New Table: NpcCombatStats

```rust
NpcCombatStats {
    npc_id: u64,           // primary key
    damage_dealt: i32,
    damage_received: i32,
    combat_start: Timestamp,
    last_revision: Timestamp,
}
```

- Created when NPC first detects a player
- Updated each tick by the `execute_action` logic (attack hits → damage_dealt++)
- Deleted when NPC returns to idle (combat over)

## Richer LLM Context

The `NpcPendingDecision` context will include the full battle report:

```json
{
  "npc_id": 5,
  "npc_health": 30,
  "npc_health_max": 100,
  "damage_dealt": 20,
  "damage_received": 70,
  "fight_duration_seconds": 15,
  "current_node": "attacking",
  "revision_trigger": "losing",
  "nearby_players": [...]
}
```

## Revision Triggers (priority order)

| Trigger | Condition | Priority |
|---|---|---|
| Critical health | health < 25% | High |
| Losing badly | damage_received > damage_dealt * 2 | High |
| Losing | damage_received > damage_dealt | Medium |
| Periodic | 10s elapsed since last revision | Low |

## Scaling Properties

- **Predictable LLM load** — at most one revision per 10s per NPC in combat,
  regardless of tick rate
- **Richer decisions** — LLM reasons about actual battle outcomes, not just
  initial snapshot
- **Natural phase changes** — NPC strategies shift as the fight evolves
  (aggressive → defensive → flee) without scripting
- **Fallback safe** — if bridge is down, NPC keeps running current graph unchanged

## Future: NPC Archetypes

Archetype data will be included in the context to shape strategy:

| Archetype | Tendency |
|---|---|
| Berserker | Never flees, attacks even when losing |
| Coward | Flees immediately when health < 50% |
| Ambusher | Only engages when player is very close |
| Protector | Prioritises keeping other NPCs alive |

The LLM prompt will include archetype personality so the revised graph
reflects the NPC's character, not just optimal play.

## What This Does NOT Change

- Behaviour graph schema (same actions and conditions)
- `submit_npc_graph` reducer (same interface)
- Bridge architecture (same Ollama call, richer context)
- Fallback behaviour (default graph still runs while LLM thinks)
