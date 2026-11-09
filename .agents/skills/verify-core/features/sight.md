# Sight for minds and behaviour graphs

Since 2026-11-09 (docs/PERCEPTION.md, "Minds see what their character sees" and "What an observer perceives of a target"). Every perception path for minds and graphs uses `perception::in_sight`: within the observer's own sight (day, night, a torch) and a clear sight line. Others are described through the `perceived_of` projection (a name only when known).

## Sub-features

- A behaviour graph's scene (`nearest`, `sees`, a creature by id) holds only creatures with a clear sight line: a resident whose graph waves at someone it `sees` waves from the open and not from behind rock or a wall (`skill_use`).
- Witnessed events (`perceive::witnessed`): a fight is an experience (`kind` `fight`) for a minded resident in the open within sight, and for none behind rock or a wall.
- Percepts name others by the projection's label: "A stranger attacked you", "A stranger said to you" until the observer knows the name (family, community, someone its mind has feelings about, someone who said their name).
- Unchanged: hearing (speech, signals) and smell (scent) are not sight.

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py sight --run "$R" > ".local/living/verify/$R/sight.txt" 2>&1
```

On a default-seed run (`$V launch --run $R`). It finds the geometry on the world's map (`terrain_chunk`), spawns four minded people (`spawn_crowd 4 true`), places them with `place_at`, installs their graphs with `set_behavior` (two watchers that wave at the attacker when they see it, an attacker), and reads `skill_use`, `experience` and `chronicle` as the owner. Evidence: `sight-*.json`, `sight-actions.jsonl`.

## Gotchas

- Behaviour change, expected: residents no longer react to fights, people or deaths behind walls, rock or shut gates within their sight radius; they still hear speech through them.
- A map without a thin rock or wall run with open ground beside it fails with "no wall geometry", a fixture failure.
