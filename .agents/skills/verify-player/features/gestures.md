# Gestures

A player's character greets, answers and turns through the same skills residents use (`wave`, `nod`, `face` in `living/scripts/skills.rhai`; docs/TOWN_LIFE.md), as deliberate acts through `human_act`.

## Sub-features

- `human_act {"do": "wave", "target": {"id": N}}` is accepted, shown to others as a `doing` row with the wave's `act_card` code, and recorded in `skill_use` (source `act`, outcome `greeted <name>`).
- The resident answers with a nod (within 5 tiles) or a wave from its own graph (source `graph`, outcome `answered <player>`); the player perceives "… answers your greeting (nod)." as an experience.
- An answer closes the greeting: the resident gestures once, not back and forth.
- A nod after the greeting closed greets anew and is answered.
- `face` turns the player's standing body toward its target (body `heading` + `turn` × `turn_s`).
- Refusals: waving at oneself is refused by the rules ("not to yourself", told back as an act experience); `use_skill("wave", …)` is refused because a gesture is not on the skill bar.

## How to get to it (user POV)

```bash
$V launch --run $R --seed island && $V doctor --run $R
python3 .agents/skills/verify-player/scripts/gesture.py --run $R
```

The script joins the run's player if needed, finds a resident keeping its post, and sets the scene with admin `place_at` (name it in the report). Results: `RUN/gesture.json`; calls in `actions.log`.

## Gotchas

- Acts walk into reach: a wave at someone farther than 12 tiles walks the player closer first.
- The resident answers only while its `greet` desire outweighs what it is doing (`hailed` × 2.2 for 6 s); a resident in a fight or fleeing does not answer.
