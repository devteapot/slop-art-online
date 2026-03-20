# Technical Debt & Deferred Work

Items we intentionally skipped for now that should be revisited as the project scales.

## Database Indexes

- **`npc_event_log.npc_id`** — `trigger_decision` does a full table scan of all events to find ones matching a single NPC. Add a btree index so lookups are O(log n). Same applies to `npc_memory.npc_id`.
- Currently tolerable with <100 NPCs, becomes a bottleneck at scale.

## Spatial Indexing

- **`send_chat_message`** iterates all NPCs to check proximity for `heard_chat` events. Fine with hundreds of NPCs, but needs spatial partitioning (grid or quadtree) if NPC count grows to thousands.
- Same issue applies to `find_nearest_player` in combat (already O(all players) per NPC per tick).
