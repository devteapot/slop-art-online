# A character returning to sight with its state now

A body that leaves sight fades out where it was and is despawned (`live.rs`, "Leaving sight"). When that character comes back into sight, the client builds a new body from its current recipe and fades it in (while `anim::clip_root` caches each shared clip file's root once so spawning does not re-parse the clip glTF JSON).

`battle-spikes` (2026-11-27) briefly kept left-sight bodies hidden for 6 s and reused them; controls on dev-box and the laptop showed reuse added no measurable frame-time benefit over the cached `clip_root`, so `battle-simplify` (2026-11-28) removed hidden-body reuse and `anim::afresh`. This scene stays as a regression test so any future change to body lifecycle still draws returning characters in their current state without a stale pose frame.

What a returning character shows, and where each comes from:

| State | Where it is drawn | On return |
| --- | --- | --- |
| Pose: sitting or standing, the standing loop | `town::shows` → `Motion::stand` each frame; `Anim::stands` blends it | New body built with the current standing loop; no stale seated loop blended while fading in |
| Activity: a one-shot or loop clip | `combat::actions`, `town::shows` → `Motion::action` each frame; `Anim::onces` | Current one-shot starts cleanly on the new body |
| Seat | `live.rs` `seat_anchor` from the sitting state, each frame | Set only if seated now |
| Wounds, health | The overhead plate's band (`ui/live.rs` `band`: the projection's exact health, else the fighter row's band), by id, each frame | Read from the tables |
| Worn pieces, the look | The recipe from the look key (or folk and style without one) | Built from the current projection's look key |

## Drive

- `check.py --run $R body-return` (island, explicit): three residents beside me in the street at noon, out of sight 30 m off, changed while away, then brought back. 15 checks.
  - A stands, then rests (sits) and is wounded (`admin_set_vitals` 30) while away.
  - C sits, then waits (gets up) while away.
  - B changes look key while away (owner SQL on `look`).
- **The dump's `bodies`** (each drawn body: `entity`, `stand`, `action`, `showing`, `stands`, `ground_seat`, `seat`, `fade`) and **`plates`** (each plate's `hp` band, `exact`, `hostile`).
- **The feet log follows C** (`LIVING_GAME_FEET_ID`). Its lines carry `stand`, `stands`, `fade` and `entity`, so every frame C is drawn after `back` (fade under 1) is checked: standing clips, hips over 0.6 m, no seated loop blended.
- Stills: `00_before`, `02_back` (about 0.7 s after `back`) and `03_late` in `body-return/`.

## Gotchas

- Choose residents who sit when they rest: `town.rs` stands about three in ten at ease (`world::hash(id, 0x5e47) < 0.3`; `rests_seated` in check.py).
- A projection is made as someone comes into sight, so a look changed while they are in sight shows only after they leave and come back. The scene starts with the three out of my sight, after the look row is reset.
- The dumps come about 0.4 s after the body returns (a perception sweep after `place_at`), by which time a stale standing loop would have blended out. The feet log's per-frame check on C catches any stale seated frame during fade-in.
- The scene puts me back where I stood before it (`start` snapshot): `battle-views` finds residents only round the arrival.
