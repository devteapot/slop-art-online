# Technical Debt & Deferred Work

## Architecture Migration: v1 → v2 (ADR 005) — COMPLETE

The NPC architecture has been migrated from a mode-switching two-layer system to a unified behavior tree with structured identity. See `docs/adr/005-npc-architecture-v2.md` and `server/module/spacetimedb/CLAUDE.md` for the design.

### Data Model Changes

- [x] **`NpcEmotion` table** — Six emotions (anger, fear, joy, sadness, surprise, disgust). Event-triggered changes, tick-driven decay toward personality baseline.
- [x] **`NpcKnowledge` table** — Learned world mechanics/facts, separate from beliefs. Categories: combat, trading, crafting, navigation, social, world. Expands behavior tree action space.
- [x] **`NpcPersonality` table** — Structured traits (aggression, sociability, curiosity, courage, empathy, discipline) replacing the `persona: String` field. Defines emotion baselines and decay rates.
- [x] **Unified `NpcBehavior`** — Replaced `{ mode, combat_tree, life_tree }` with `{ current_tree }`. NpcPlan removed (plans are Sequence nodes in the tree).

### Tick Loop

- [x] **Remove mode switching** — Single `evaluate_tree(current_tree)` call per NPC per tick.
- [x] **Emotion decay** — `apply_emotion_decay()` runs each tick before tree evaluation, lerps toward personality baseline.
- [x] **Tree regeneration detection** — Detects goal completion, near-death, and triggers `NpcPendingDecision("tree_generation")`.

### Behavior Tree

- [x] **Knowledge-gated entity references** — Vague (`SearchFor("healing")`) and concrete (`TravelToEntity`, `AttackEntity`, `SayToEntity`) action forms.
- [x] **Emotion conditions** — `EmotionAbove(emotion, threshold)`, `EmotionBelow`, `EmotionDominant` as BT condition nodes.
- [x] **Inline identity actions** — `SetBelief`, `AddKnowledge`, `AdjustRelationship`, `TriggerEmotionAction` as BT action nodes.
- [x] **Conversation protocol** — `MatchesGreeting`, `TopicMatchesKnowledge`, `TopicMatchesBelief`, `IsImportantConversation`, `RequestLlmResponse`. Engagement-based confidence in `send_chat_message`.

### Bridge

- [x] **Unified tree generation** — Single `tree_generation` decision type replaces all previous combat/plan/dawn types.
- [x] **Experience evaluation** — `experience` decision type for significant events. LLM returns identity deltas.
- [x] **Conversation content** — `conversation` decision type for novel conversations only.

### Propagation

- [x] **Belief/knowledge propagation reducer** — `propagate_beliefs_and_knowledge()` runs every 10 ticks (~5s). Confidence degrades through chain.
- [x] **Engagement-based confidence** — Implemented in `send_chat_message`. Overheard speech gets reduced confidence.

## Database Performance

- [ ] **`npc_event_log.npc_id` index** — `trigger_decision` does a full table scan of all events to find ones matching a single NPC. Add a btree index. Same for `npc_memory.npc_id`.
- [ ] **Spatial indexing** — `send_chat_message` iterates all NPCs for proximity checks. `find_nearest_player` is O(all players) per NPC per tick. Needs grid/quadtree partitioning at scale (>hundreds of NPCs).

## Code Organization

- [ ] **Split `lib.rs`** — The main module file is ~2500 lines. Extract `tick_npcs` and related helpers into a dedicated module. Extract player reducers. Extract world state management.
- [ ] **Split `npc_ai.rs`** — Extract tree builders, tree evaluation, and action execution into separate submodules.
