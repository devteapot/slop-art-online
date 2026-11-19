# Public-feed scoping

docs/FEED_SCOPING.md ("Authority shapes"). `scripts/feed_scope.py --run client-feed-…` on a launched run (any seed) takes the world to stage 2 (`feed_scope_on`, `feed_scope_grace_s` 1), stages a remains far beyond the player's sight and a storage by a second player, and reads through the SDK probe (`drive.py --query`, WebSocket) and HTTP SQL:

- the private tables (`structure_held`, `gate_held`, `resource_held`, `thing_seen`, `remembered_thing`, `owner_seen`, `fuel_seen`, `owned_by`, `lot_door`, `id_seq`, `seen_structures_scoped`) refused to anonymous and player SQL; subscriptions to three of them rejected by the server ("no such table … may be marked private" in the probe's record, not a driver refusal);
- the legacy `structure`, `gate` and `resource_node` feeds empty at stage 2;
- `my_things` without the unseen remains or the other player's storage; the owner's `thing_seen` holding the second player's copy of its storage and none of the remains for the player (truth control);
- in sight, a live `my_things` insert of the remains with presence only (kind, place, `lit`, `owner` 0);
- a new connection with the same identity gets the copy, and `my_remembered_things` its memory, in the first result;
- `feed_scope`, `map_structure` (architecture kinds only) and `map_resource` (no stock fields) public.

Build the probe first (SKILL.md); the probe knows the new tables and views. Evidence: `feed-ws-*.jsonl`, `feed_scope.json`. The fixed suite's inventories (`drive.py` `PRIVATE`, `VIEWS`, `BASE_QUERIES`) list the new private tables, the five views and the observer's `structure_held`, `gate_held` and `resource_held` queries; in a stage-0 world those three are empty.
