# Perception: what a player receives

What a player's client may read is what its character perceives now, plus its own state (docs/PERCEPTION.md). The authority works out each player's perceived set every 200 ms: creatures within its sight (day, night, or night with a torch) with a clear sight line (rock, walls and shut gates hide). The per-sender views return only those rows.

## Sub-features

- `seen_bodies` (the narrow motion row, `Moving`: no path, chunk or kind; the travel segment and the facing offset), `seen_fighters` and `seen_doing` hold the creatures the caller perceives, nothing else; `seen_characters` holds those and the caller's own living character. Since 2026-11-10 (`scale-1`) the caller's own body, fighter and doing rows are in `my_body`, `my_fighter` and `my_doing` (at most one row each), not in `seen_*`.
- `seen_characters` is what the caller perceives of each of them: the `perceived_of` projection (`SeenCharacter`: `id`, `name` when known else empty, `label`, `kind`, `stage`, `folk`, `style`, `own`, `band`, exact `hp`/`max_hp` or -1). No `controller`, `ai`, home, parents or cause. Two newcomers who were never told each other's names see each other as `a stranger`, health as a band (`seen-characters.json`). `seen_fighters` carries the projected band. The appraiser-and-bystander proof is `verify-player`'s `appraise.py`.
- In sight: two players 3 tiles apart on open ground receive each other's body and character; each gets its own body in `my_body` and not in `seen_bodies` (`sight.json`, step `in-sight`).
- Beyond sight: the same players 20-30 tiles apart receive no body, character, fighter or doing row of the other (step `beyond-sight`).
- Behind a wall or rock: two players at most 4 tiles apart (within even night sight, 6 tiles), on one axis with only rock or wall tiles between, receive nothing of the other (step `behind-wall`).
- `my_characters` is the one character the caller plays now (`perception::current`): the `player` row's character while its `controller` is the caller and it is not `ai`, the dead included until the person joins again (for the death screen); nothing while the world's minds hold it after a takeover. A person with no `player` row (a world from before the table) gets the old walk, its newest living character else its newest, until its next player reducer writes the row. It was every character the identity ever had until 2026-11-10. `player` (identity → character, private) is written at `join`, when a returning person takes the character back, and by `player_character` for a person who has no row yet. `my_body`, `my_fighter`, `my_doing`, `my_vitals`, `my_experience`, `my_places`, `my_inventory` and `my_know_how` hold only that character's rows; anonymous receives none of them and no `seen_*` rows (`own-*.json`). Since `stamina-1` `my_body` and `seen_bodies` rows (`Moving`) carry `running` (the rules' gait, for any controller; `body.running`, `motion_seen.running`), and the `my_vitals` row also carries breath and focus (`stamina`, `stamina_max`, `stamina_rate`, `stamina_from_ms` and the same for `focus`, docs/STAMINA.md). The suite checks each player's row is within its caps, with no row for an anonymous client (`own-*.json`, `my_vitals_rows`). `my_experience` holds the newest 64 lines of the living character, or of the last one while none lives (since 2026-11-10; it was every character's 400-line window).
- `my_senses` (since 2026-11-11, branch `rules-senses-outcomes`; docs/PERCEPTION.md "My senses") holds what the caller's living character senses: `CharacterSenses` (`id`, `sight`, `hearing`, `field`, `focal_deg`, `side_deg`, `side_share`, `near_m`, `margin_deg`, `at_ms`), the `senses` law's answer written at the player's frames only on change. It reads `character_senses` (private) by its key. The own-state check requires exactly one row, the caller's own character's, with sight and hearing above 0; `ClientAnon` gets its own and anonymous none; `character_senses` is in the private inventory (refused to anonymous and players). That the row follows nightfall and a law change, and is not rewritten while nothing changes, is `verify-player`'s `senses.py`.
- `my_act_outcomes` (since 2026-11-11, branch `rules-senses-outcomes`; docs/PERCEPTION.md "Act outcomes") holds how the caller's current character's acts and death came out: `ActOutcome` (`id`, the experience line's; `observer`, `at_ms`, `kind`, `ok`, `skill`, `code`, `what`, `why`, `other`). It reads `act_outcome` (private) by its `observer` btree index. The own-state check requires every row's `observer` to be the caller's character; anonymous gets none; `act_outcome` is in the private inventory. The codes, retention and the death row are `verify-player`'s `outcomes.py`.
- `my_offers` (since 2026-11-11, branch `rules-offers`; docs/PERCEPTION.md "Offers") holds the standing trade offers addressed to the caller's living character (`incoming` true) and the one it made (`incoming` false): `MyOffer` (`id`, `incoming`, `from`, `to`, `give_item`, `give_qty`, `want_item`, `want_qty`, `at_ms`, `until_ms`), character ids and no names. It reads `trade_offer` (private) by its `to` and `from` btree indexes. The own-state check requires every row's `from` or `to` to be the caller's and `incoming` exactly when `to` is; the offers step (after `in-sight`) has `ClientPrimary` offer 1 berries for 1 wood to `ClientSecond` with `human_act` and probes each identity: the maker reads it outgoing, the addressee incoming, `ClientAnon` and anonymous nothing (`offers.json`, `offers-*.json`). A player accepting it is `verify-player`'s `offers.py`.
- Frames (since 2026-11-10, docs/PERCEPTION.md "Frames"): others' rows in `seen_bodies`, `seen_fighters` and `seen_doing` are per-viewer copies (`motion_seen`, `fighter_seen`, `doing_seen`, private) that the tick writes at the viewer's frame, every 33–100 ms; the caller's own body, fighter and doing rows are read directly. Experience lines are released at the character's frame (`line_seen`, private). The four tables and `player` are in the driver's private inventory.
- In a `scoped` build the tables behind these views are private to anyone but the database owner, players included (`visibility.json`). In a `LIVING_PERCEPTION=open` build (diagnostics only; the default is `scoped`) they are public, so the views are correct but are not the boundary there.

## How to get to it (user POV)

A player connects with its identity, joins, and subscribes `SELECT * FROM seen_bodies` and the other views. As its character moves, the rows of creatures coming into and going out of its sight arrive as inserts and deletes; a perceived creature's steering updates arrive as updates at the player's next frame (within 100 ms).

## Driving it with drive.py

The fixed suite runs it after the combat and town checks:

```bash
LIVING_PERCEPTION=scoped .agents/skills/verify-client/scripts/run.py --run "$R"
```

`drive.py` finds the geometry on the world's own map (`terrain_chunk`, public): an open pair, a far point, and an opaque run between two walkable tiles. It places `ClientPrimary` and `ClientSecond` with the admin `place_at`, waits 1 s (five sweeps) and probes each player's `seen_*` views. `sight.json` holds the spots, each step's positions and what each player received.

## Gotchas

- The geometry search assumes the realm map has a thin rock or wall run (gap 1-3 tiles) somewhere; on a map without one the check fails with "no sight-check geometry", which is a fixture failure, not a product one.
- `drive.py` records which build it drives from the run's state (`perception`, set from `LIVING_PERCEPTION` at launch). Run the suite on both builds when a change touches visibility: `scoped` (the default) proves the boundary, `open` proves the diagnostic build still makes those tables public and the views still answer there.
- The sweep runs every 200 ms and frames every 33–100 ms; a probe right after `place_at` can still see the old set. The driver waits 1 s.
- Since 2026-11-09 the combat feed (`my_combat`) and minds' percepts see by the same rule (sight and a clear sight line): a blow behind a wall no longer reaches a player's feed. `verify-minds`'s `sight` case drives the minds' side.
- `my_experience` rows of a character the world's minds controlled while its person was away carry the mind service's identity as `controller`; the own-state check accepts the caller's identity or the world admin's.

## The field of view

Since 2026-11-11 (`fov-1`; docs/PERCEPTION.md, "The field of view (seventh change)"). `drive.py`'s `field_of_view` runs after the wall checks: two players 5 m apart on open ground (`sight_spots`' `field` pair, with open rows beside it), the admin's `set_world_law fov_on true`, and the primary player turning with the `face` act (`human_act`). Each look is a real subscription to `seen_*` and `heard_sounds` with the player's token.

- Facing away: the other is in neither `seen_bodies` nor `seen_characters`; `heard_sounds` holds a row to the east (bearing 2), near (band 0), kind `person`, with only `key`, `kind`, `bearing`, `band` and a key that is neither player's id.
- Facing it: seen, and no longer heard to the east.
- The field's edge: kept at 75° off facing once seen (through 45°), not seen afresh at 75° (through 100°).
- Off again (`set_world_law fov_on false`, then the 2 s linger): seen all round, nothing heard.

`heard`, `hear_salt` and `law_change` are in the private inventory (`PRIVATE`; `heard` and `law_change` also refused to a player), `heard_sounds` in `VIEWS`, and `set_world_law` in `ADMIN` (refused to players and anonymous callers with "admin only"). The probe reports `heard_sounds` in its `perception` map (`key` as a string).
