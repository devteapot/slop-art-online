# Perception: what a player receives

What a player's client may read is what its character perceives now, plus its own state (docs/PERCEPTION.md). The authority works out each player's perceived set every 200 ms: creatures within its sight (day, night, or night with a torch) with a clear sight line (rock, walls and shut gates hide). The per-sender views return only those rows.

## Sub-features

- `seen_bodies` (the narrow motion row: no path, chunk or kind), `seen_characters`, `seen_fighters` and `seen_doing` hold the caller's own living character and the creatures it perceives, nothing else.
- In sight: two players 3 tiles apart on open ground receive each other's body and character, and their own (`sight.json`, step `in-sight`).
- Beyond sight: the same players 20-30 tiles apart receive no body, character, fighter or doing row of the other (step `beyond-sight`).
- Behind a wall or rock: two players at most 4 tiles apart (within even night sight, 6 tiles), on one axis with only rock or wall tiles between, receive nothing of the other (step `behind-wall`).
- `my_characters` (the dead included), `my_vitals`, `my_experience`, `my_places`, `my_inventory` and `my_know_how` hold only the caller's characters' rows; anonymous receives none of them and no `seen_*` rows (`own-*.json`).
- In a `scoped` build the tables behind these views are private to anyone but the database owner, players included (`visibility.json`). In an `open` build they stay public for the game client of 2026-11-09, so the views are correct but are not the boundary yet.

## How to get to it (user POV)

A player connects with its identity, joins, and subscribes `SELECT * FROM seen_bodies` and the other views. As its character moves, the rows of creatures coming into and going out of its sight arrive as inserts and deletes; a perceived creature's steering updates arrive as updates.

## Driving it with drive.py

The fixed suite runs it after the combat and town checks:

```bash
LIVING_PERCEPTION=scoped .agents/skills/verify-client/scripts/run.py --run "$R"
```

`drive.py` finds the geometry on the world's own map (`terrain_chunk`, public): an open pair, a far point, and an opaque run between two walkable tiles. It places `ClientPrimary` and `ClientSecond` with the admin `place_at`, waits 1 s (five sweeps) and probes each player's `seen_*` views. `sight.json` holds the spots, each step's positions and what each player received.

## Gotchas

- The geometry search assumes the realm map has a thin rock or wall run (gap 1-3 tiles) somewhere; on a map without one the check fails with "no sight-check geometry", which is a fixture failure, not a product one.
- `drive.py` records which build it drives from the run's state (`perception`, set from `LIVING_PERCEPTION` at launch). Run the suite on both builds when a change touches visibility: `scoped` proves the boundary, `open` proves the compatibility path still serves today's game client.
- The sweep runs every 200 ms; a probe right after `place_at` can still see the old set. The driver waits 1 s.
- The combat feed (`my_combat`) uses sight radius without a sight line, as minds' percepts do (docs/PERCEPTION.md, open items). A blow behind a wall within sight still reaches a player's feed.
