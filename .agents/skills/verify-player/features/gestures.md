# Gestures

A player's character greets, answers and turns through the same skills residents use (`wave`, `nod`, `face` in `living/scripts/skills.rhai`; docs/TOWN_LIFE.md), as deliberate acts through `human_act`.

## Sub-features

- `human_act {"do": "wave", "target": {"id": N}}` is accepted, shown to others as a `doing` row with the wave's `act_card` code, and recorded in `skill_use` (source `act`, outcome `greeted <label>`: the resident as the player perceives it, `a stranger` until it knows the name; docs/PERCEPTION.md).
- The resident answers with a nod (within 5 tiles) or a wave from its own graph (source `graph`, outcome `answered <label>`: `answered a stranger` until the resident is told the player's name); the player perceives "… answers your greeting (nod)." as an experience.
- An answer closes the greeting: the resident gestures once, not back and forth.
- A nod after the greeting closed greets anew and is answered.
- `face` turns the player's standing body toward its target (body `heading` + `turn` × `turn_s`).
- The game client sends the same `human_act` from its keys: **G** waves, **B** nods (`living/game/src/town.rs`), at the person under or nearest the cursor, else the nearest person within the gesture's reach (12 m for a wave, 6 m for a nod), ahead first. With nobody in reach it sends the gesture without a target and the rules refuse it. Its own clip is predicted at the press and dropped after 600 ms unless the player's `doing` row confirms it.
- Refusals: waving at oneself is refused by the rules ("not to yourself", told back as an act experience); `use_skill("wave", …)` is refused because a gesture is not on the skill bar.

## How to get to it (user POV)

```bash
$V launch --run $R --seed island && $V doctor --run $R
python3 .agents/skills/verify-player/scripts/gesture.py --run $R
```

The script joins the run's player if needed, finds a resident keeping its post, and sets the scene with admin `place_at` (name it in the report). Results: `RUN/gesture.json`; calls in `actions.log`.

From the game client's own path: run the client headless on the island run (`LIVING_GAME_LIVE`, see [verify-client game-client](../../verify-client/features/game-client.md)) with a plan such as `ready;sync:greet;wait:7;gesture:wave;wait:2;shot:greet;quit`. `gesture:wave|nod[:ID]` goes through the same code as the G and B keys; `sync:NAME` waits for `<dir>/NAME.go`, written after an admin `place_at` puts the client's character about 2.6 m in front of a resident keeping its post (a number in the file turns the view to that yaw). Check the player's `skill_use` (`wave`, source `act`, outcome `greeted <name>`), the resident's (`nod`, source `graph`, outcome `answered <player>`) and the player's `experience` "… answers your greeting (nod)."; the photographs show the wave, the nod and the answering resident's nameplate.

## Gotchas

- Acts walk into reach: a wave at someone farther than 12 tiles walks the player closer first.
- The resident answers only while its `greet` desire outweighs what it is doing (`hailed` × 2.2 for 6 s); a resident in a fight or fleeing does not answer.
