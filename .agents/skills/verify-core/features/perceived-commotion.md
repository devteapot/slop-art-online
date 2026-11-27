# Commotion, as perceived (`perceived_commotion_on`)

Perception parity phase 1 ([audit](../../../../docs/PERCEPTION_PARITY_AUDIT.md), the `commotion` row; the audit lives on branch `perception-parity-audit`). The world law `perceived_commotion_on` (an ordinary law, off as shipped) decides where a graph's commotion is, in both places it is read (`brain.rs`, `Target::Commotion`):

- the target `"commotion"` (a `do`'s target, `sees`, `near`);
- a desire's weight `commotion` (1 while the target resolves).

**Off (as shipped):** `town::commotion`: the nearest `attack`, `threat`, `killing` or `death` chronicle row of the last 8 s within the character's sight radius, by distance alone: through walls and rock, behind its back under `fov_on` (the leak).

**On:** `town::commotion_seen`, through the perception path players' sets use:

- the spot of one of those chronicle rows that the character sees now (`perception::sees`: its sight, its field under `fov_on`, the light, a clear line); a death's remains and a fight's fighters are there to see;
- or someone in its scene (`Ev::creatures`: sight, line, field; under heed, its individuals) visibly making a hostile move (`perception::visibly`, a `fighter` row's move with a hostile shape), when the maker or its target is a person (the chronicle's fights); at the maker.

The nearest of these. A fight behind a wall draws no one; an animal fight among animals draws no one, as before.

Cost: off, one law read per resolve. On, a sight-line test per recent chronicle row within sight (rows are few, read once per transaction), and one `fighter` and at most one `doing` point read per creature in the scene, only when a graph asks for the commotion.

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py perceived_commotion --run "$R" > ".local/living/verify/$R/perceived_commotion.txt" 2>&1
```

`scenes.py perceived_commotion` (any seed, about 3 minutes): on the map's own wall geometry (`wall_geometry`, as `sight`), a fight at `eye` is watched by O in the open 3 tiles off and by X behind 1 to 3 tiles of rock or wall. Both walk to the commotion, as a target or by a desire's weight. Attackers A and B take turns, so each case is a fight's first blow with its chronicle line. Law off: both go, X through the wall (the leak). Law on: O goes, X does not; O witnessed the fights and X none.

Evidence: `perceived_commotion-activity-<off|on>-<target|weight>-<id>.json`, `perceived_commotion-spots.json`, `perceived_commotion-cast.json`.

## Gotchas

- A body is not second-guessed for 45 s after it arrives; the scene sleeps until then.
- O stands 3 m from the fight: its walk can end between two polls, so "went" is a `goto` toward the fight or its body off its spot by 0.6 m (the first run, before this, missed O once).
- Cases are 9 s apart: a chronicle row draws for 8 s (`COMMOTION_MS`).
- The scene restores `perceived_commotion_on` in a `finally`.
