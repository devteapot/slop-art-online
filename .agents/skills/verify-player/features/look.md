# The player's own look

Since `look-1-auth` (2026-11-12, docs/LOOK.md §4). A player's character is given a look at `join`, like every person made after genesis: the world's pool entry `pool[pool_pick(world.seed, id, len(pool))]` (`living_rules::look::pool_pick`: `splitmix64(seed ^ id × 0xD1B54A32D192ED03) mod len`), and the line of that entry for its band. Since `sex-1` the pool is the sorted entries of the player's body sex (its `sex` row; an entry's sex is the last word of its lines' `form`), so a woman wears a woman's line. The look is the character's, not the connection's: a reconnect keeps it. No player reducer sets or changes a look; it changes only with the band (housekeeping, `grew`) and an admin's `relook`.

## Sub-features

- The world wears the seed's look generation (`world.look_book`).
- The player's `look` row (private; read as the owner) wears the pool entry `pool_pick` names among the entries of its sex, computed by the driver in Python independently of the authority, and that entry's line for its band.
- Its own `seen_characters` row (`own`), read as the player, carries the line's key; a second read (a new connection with the same identity) gets the same key.
- After `human_move`, `human_act`, `human_say`, `human_speak`, `human_face`, `use_skill` and `release_skill`, the look row is unchanged; a second `join` is refused.
- In the authority's source, `look` rows are written only in `look.rs` and deleted only in `perception::gone` (death).

## Driving it

On a launched and doctored `player-*` run whose seed has looks (`$V launch --run "$R" --seed plan-test`):

```bash
.agents/skills/verify-player/scripts/look.py --run "$R"
```

Evidence: `player_look.json` (the row, the pick, both reads, each call's status, the row after, the writers in the source).

## Gotchas

- The driver reads the pool from `living/seeds/<seed>.json` (the run's `state.json` names the seed); a seed without `looks` fails it at once.
- The SDK stream of the same row across a reconnect is verify-client's `look_rows.py`; this driver reads through HTTP SQL as the player.
