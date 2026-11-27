# A sound out of sight, as heard (`perceived_sound_on`)

Perception parity phase 1, item 6 ([audit](../../../../docs/PERCEPTION_PARITY_AUDIT.md), the `Target::Sound` row). With sight on a field (`fov_on`), a creature within hearing and out of sight is heard, not seen. A player gets it as a `heard_sounds` row: what it sounds like, one of eight compass ways (`living_rules::sight::compass8`) and a distance band (`heard_band`: near within `heard_near_m`, close within `heard_close_m`, far beyond). The world law `perceived_sound_on` (an ordinary law, off as shipped) decides where a graph's sound is, in the two places a graph reads a heard position (`brain.rs`, `Ev::heard_at`):

- the target `"sound"` (the nearest creature heard and not seen: a `do`'s target, `sees`, `near`);
- an unseen speaker turned to: the target `"speaker"` for a skill or act's target, when whoever spoke is heard and not seen.

**Off (as shipped):** the creature's exact position (the leak: `(B!)` in the audit, a sharper position than any player hears).

**On:** `living_rules::sight::heard_point`: the point on the sound's compass way at the middle of its band (near: half of `heard_near_m`; close: between `heard_near_m` and `heard_close_m`; far: between `heard_close_m` and the listener's hearing). It measures back to the same way and band (rules test `sight::tests::a_heard_point_is_its_way_and_band`), so a graph's `near sound within N` and a body turning or walking to the sound get what a player's row gives and nothing finer.

Which sound is "the nearest" is still chosen by exact distance among those heard (always one in the nearest band). Without `fov_on` nothing is heard and not seen, so the law changes nothing. A mind's scene already told sounds only by way and band (`HEARD`).

Cost: off, one law read per resolve of the sound or an unseen speaker. On, one hearing read (`senses_of`) and the arithmetic.

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py perceived_sound --run "$R" > ".local/living/verify/$R/perceived_sound.txt" 2>&1
```

`scenes.py perceived_sound` (any seed, about 2 minutes): with `fov_on` on, a listener L on an open line faces east and S stands 6 tiles behind it to the west, 2 tiles off the line where the map has ground (heard, not seen). Each case places both again and turns L away first. L's graph turns to the `sound`; asks whether the sound is `near` within the midpoint between S's distance and its band's middle; and, after S says a line, turns to the `speaker`. The scene reckons the expected point with a Python copy of the rules' `compass8`, `heard_band` and `heard_point`, from the authority's own body positions. Law off: L turns to exactly where S stands (within 0.35 m) both times, and `near` measures S's distance. Law on: L turns to the heard point (within 5 cm) and not to S, whose way and band it keeps, and `near` measures the band's middle.

Evidence: `perceived_sound-case-<off|on>.json` (positions, the heard point, the way and band, the faced points, the `near` line), `perceived_sound-face-<law>-<sound|speaker>.json` (the activity rows), `perceived_sound-said-*.json`, `perceived_sound-line.json`, `perceived_sound-cast.json`.

## Gotchas

- Hearing reaches 9 m (`hearing_of_people`), under `heard_close_m` (15 m): in shipped worlds a sound is never far, so the scene's far-band arithmetic (hearing 9 m) is never used.
- The speaker is resolved through the body's target path only (`resolve_body`): `sees speaker` stays false for a speaker heard and not seen, law on or off.
- The scene restores `perceived_sound_on` and `fov_on` (both off) in a `finally`.
