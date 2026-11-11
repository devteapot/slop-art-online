# Across a drop between ground levels

Since 2026-11-11 (docs/PERCEPTION.md, "Drops: sight across ground levels"). A drop between two ground levels (a terrace's, a planned settlement's) is a `drop` tile (8): it blocks walking like a wall, but sight and missiles pass over it.

## Sub-features

- Two players either side of a drop, a few metres apart, each find the other in `seen_bodies` and `seen_characters` (their own views).
- The one above walks straight at the drop with `human_move` for 4 s: no sample of its body (every 0.2 s) is on a drop or other blocked tile, and it ends on the upper level.
- Told to go to the one below (`human_act {"do": "goto", ...}`): its body is never on a blocked tile and never moves more than 1.5 m between 0.2 s samples (no jump over the drop). It goes round by a stair, or the walk is refused; the report gives the outcome, where it ended and how far it walked.
- The one above shoots the one below with `use_skill bowshot` (the plan-test newcomer has a bow): the outcome is `struck …` and the target's health falls. Missiles follow the sight rule.

## How to get to it (user POV)

On a terraced street, stand at the edge of the upper level above someone on the lower one: you see them and they see you. Walking off the edge stops at it; the way down is the stair. An arrow shot down at them hits.

## Driving it

```bash
R=player-drop-$(date +%Y%m%d-%H%M%S)
python3 "$V" launch --run "$R" --seed plan-test
python3 .agents/skills/verify-player/scripts/drop.py --run "$R"
python3 "$V" cleanup --run "$R"
```

It mints the run's player identity and a second one (`token2`) if the state lacks them, and joins both. It finds the geometry on the hosted tiles (`terrain_chunk`, public) and the plan's two levels from `living/seeds/plan-test.json` (the plan's frame: east-north metres from `origin`, turned by `rotation_deg`): a row tile and a quay tile on one axis with only drop tiles (1 to 3) between and walkable ground behind each. Admin `place_at` sets the scene; admin SQL reads `body` and `vitals`. Evidence: `drop.json`, `drop-geometry.json`, `actions.log`.

## Gotchas

- The authority has no heights; the script finds which side is above from the plan's level polygons. On a seed without a plan it fails with "no drop between the plan's levels".
- Sight at night is shorter (6 m on the shipped law); the two stand at most 6 m apart, so the scene holds by day or night.
- The arrow strikes the first body on its line; another resident walking between can take it. Rerun, and say so.
