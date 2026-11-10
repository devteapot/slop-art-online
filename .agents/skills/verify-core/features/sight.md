# Sight for minds and behaviour graphs

Since 2026-11-09 (docs/PERCEPTION.md, "Minds see what their character sees" and "What an observer perceives of a target"). Every perception path for minds and graphs uses `perception::in_sight`: within the observer's own sight (day, night, a torch) and a clear sight line. Others are described through the `perceived_of` projection (a name only when known).

Since `laws-2` (2026-11-11) how far each creature sees and hears is the script's `senses(a)` law (docs/WORLD_RULES.md, "Laws"): 11 m by day, 6 at night, 9 with a torch in the pack, hearing 9 m (one tile is one metre). The authority asks it per creature through `common::senses_of`, which gathers only the fields the law reads (`act::law_ctx`), keeps the answer per state (`Scripts::senses`) and per creature for one moment. Onlookers and listeners are gathered within the law's `reach` (`senses_law()`), then each one's own senses are tested.

## Sub-features

- A behaviour graph's scene (`nearest`, `sees`, a creature by id) holds only creatures with a clear sight line: a resident whose graph waves at someone it `sees` waves from the open and not from behind rock or a wall (`skill_use`).
- Witnessed events (`perceive::witnessed`): a fight is an experience (`kind` `fight`) for a minded resident in the open within sight, and for none behind rock or a wall.
- Noticing structures (`brain.rs` `noticed`, since `feedback-1`): new tiles of one kind and owner that touch (within 1.5 tiles) are one structure, noticed once with its extent ("You notice a gate about 7 by 8 tiles, 6 tiles southwest"), and not at all when part of it was already familiar. Unit test `a_row_of_gate_tiles_is_one_gate` (the island's first gate, 24 tiles); in a real island arrival a newcomer's percepts held 24 gate lines before and 1 after (trials `fbbase`, `fbbr`, docs/MIND_FEEDBACK.md).
- Percepts name others by the projection's label: "A stranger attacked you", "A stranger said to you" until the observer knows the name (family, community, someone its mind has feelings about, someone who said their name).
- A mind's scene (`perceive::scene_json`, the `deliberation.scene` a mind reads) lists, since `arm-scene`:
  - resources per kind with `count` (in sight), `with_some` (with some left) and `nearest`: the nearest with some left, else the nearest bare one and `note` "none in sight has any left";
  - structures with touching tiles of one kind and owner as one entry (`tiles`, `extent`, through `brain.rs` `joined_tiles`), except storages, houses, remains, signs, campfires, shelters and traps, which stay one entry each; storages, houses and remains in sight are always listed (up to 12), then the nearest others, up to 16 entries;
  - a person farther than their own hearing (`common::hearing_for`, a per-creature law) with `earshot` "out of earshot: they would not hear you from here", and `time.hearing`, the character's own hearing;
  - `you["places in sight"]`: the character's own places that pass `perception::in_sight`.
  Resources and structures in the scene, like the behaviour graph's scene, are those within sight range; no sight line is tested for them (creatures and places are). A storage's `contents` are listed for any storage within sight range, not only one in reach.
- Unchanged: hearing (speech, signals) and smell (scent) are not sight.
- Senses as a law (`scenes.py senses`): watchers 5, 8, 10 and 13 m from a subject on an open line face it only when they see it. The shipped law by day: 5, 8, 10 (at night: 5). Speech heard at 5 and 8, not 10. An installed overlay with day sight 14 and hearing 12: 13 m seen, 10 m heard. An overlay where it is always dark for the eyes: only 5 m seen, and a torch granted to the 8 and 10 m watchers makes 8 m seen and 10 m not. The shipped script is installed again at the end.

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py sight --run "$R" > ".local/living/verify/$R/sight.txt" 2>&1
python3 .agents/skills/verify-core/scripts/scenes.py senses --run "$R" > ".local/living/verify/$R/senses.txt" 2>&1
```

`senses` finds an open line of 16 tiles on the map (`terrain_chunk`), spawns five minded people, and installs overlays of the shipped script with `install_script` (admin), as a floor would. It reads the hour from `world` and `clock` and expects the night's values after 20:00; it waits 30 s when within 25 s of dusk or dawn. Evidence: `senses-uses-*.json`, `senses-line.json`, `senses-actions.jsonl`.

On a default-seed run (`$V launch --run $R`). It finds the geometry on the world's map (`terrain_chunk`), spawns four minded people (`spawn_crowd 4 true`), places them with `place_at`, installs their graphs with `set_behavior` (two watchers that wave at the attacker when they see it, an attacker), and reads `skill_use`, `experience` and `chronicle` as the owner. Evidence: `sight-*.json`, `sight-actions.jsonl`.

## Gotchas

- Behaviour change, expected: residents no longer react to fights, people or deaths behind walls, rock or shut gates within their sight radius; they still hear speech through them.
- A map without a thin rock or wall run with open ground beside it fails with "no wall geometry", a fixture failure; `senses` fails with "no open line" on a map without 16 open tiles in a row.
- `senses` leaves the shipped script installed even when a check fails (a `finally`); a run interrupted mid-scene keeps an overlay until cleanup deletes the database.
