# Technical Debt & Deferred Work

## Architecture Migration: v1 → v2 (ADR 005)

The NPC architecture is being migrated from a mode-switching two-layer system to a unified behavior tree with structured identity. See `docs/adr/005-npc-architecture-v2.md` and `server/module/spacetimedb/CLAUDE.md` for the target design.

### Data Model Changes

- [ ] **`NpcEmotion` table** — Six emotions (anger, fear, joy, sadness, surprise, disgust). Event-triggered changes, tick-driven decay toward personality baseline.
- [ ] **`NpcKnowledge` table** — Learned world mechanics/facts, separate from beliefs. Categories: combat, trading, crafting, navigation, social, world. Expands behavior tree action space.
- [ ] **`NpcPersonality` table** — Structured traits (aggression, sociability, curiosity, courage, empathy, discipline) replacing the `persona: String` field. Defines emotion baselines and decay rates.
- [ ] **Unified `NpcBehavior`** — Replace `{ mode, combat_tree, life_tree }` with `{ current_tree }`. Remove `NpcPlan` table (plans become Sequence nodes in the tree).

### Tick Loop

- [ ] **Remove mode switching** — Currently `tick_npcs` has if/else chains on `beh.mode` (sleeping/combat/plan/life_tree/idle). Replace with single `evaluate_tree(current_tree)` call.
- [ ] **Emotion decay** — Apply `lerp(emotion, baseline, decay_rate)` each tick before tree evaluation.
- [ ] **Tree regeneration detection** — Detect exhaustion (N ticks with no action), goal completion, near-death, and trigger `NpcPendingDecision` with new type.

### Behavior Tree

- [ ] **Knowledge-gated entity references** — Two action forms: vague (`SearchFor("healing")`) when NPC lacks knowledge, concrete (`TravelToEntity(Poi, 3)`) when NPC knows. LLM prompt constrains references to NPC's knowledge.
- [ ] **Emotion conditions** — `EmotionAbove(emotion, threshold)`, `EmotionBelow`, `EmotionDominant` as BT condition nodes.
- [ ] **Inline identity actions** — `SetBelief`, `AddKnowledge`, `AdjustRelationship`, `TriggerEmotion` as BT action nodes that execute as side effects during normal tree evaluation.
- [ ] **Conversation protocol** — BT subtree in reactive layer: Listen (always, log with engagement-based confidence) → Respond (templates/knowledge/personality/LLM tiered).

### Bridge

- [ ] **Unified tree generation** — Replace separate `generate_combat_tree()`, `generate_plan()`, etc. with single tree generation that covers all situations via priority layers.
- [ ] **Experience evaluation** — New decision type for significant events. LLM returns identity deltas (personality, beliefs, knowledge, goals, emotions).
- [ ] **Conversation content** — New decision type for novel conversations only (~5% of exchanges).

### Propagation

- [ ] **Belief/knowledge propagation reducer** — NPCs near each other share beliefs/knowledge scaled by trust level. Confidence degrades through chain. Pure reducer logic, no LLM.
- [ ] **Engagement-based confidence** — Overheard speech gets reduced confidence (focused=1.0, overhearing=0.2). Topic relevance modifier (1.0 if matches role/goals, 0.5 otherwise).

## Database Performance

- [ ] **`npc_event_log.npc_id` index** — `trigger_decision` does a full table scan of all events to find ones matching a single NPC. Add a btree index. Same for `npc_memory.npc_id`.
- [ ] **Spatial indexing** — `send_chat_message` iterates all NPCs for proximity checks. `find_nearest_player` is O(all players) per NPC per tick. Needs grid/quadtree partitioning at scale (>hundreds of NPCs).

## Code Organization

- [ ] **Split `lib.rs`** — The main module file is ~2500 lines. Extract `tick_npcs` and related helpers into a dedicated module. Extract player reducers. Extract world state management.
- [ ] **Split `npc_ai.rs`** — Extract tree builders, tree evaluation, and action execution into separate submodules.
