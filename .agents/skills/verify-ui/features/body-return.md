# A body shown again with the character's state now

Since `battle-spikes` (2026-11-27), a body that leaves sight is kept hidden for a while and shown again when its character comes back (`live.rs`, "Leaving and coming back into sight"; the keeping itself is in [battle-views.md](battle-views.md)). A kept body is taken only for the same kind, look key, life stage and dress (`take_kept`; dress is the projection's folk and style, which a VRoid recipe takes when there is no key). Anything else draws a new body. A body that died in sight is never kept.

Everything else the body shows comes from what the character does now, as it would for a new body. The frame that shows it again runs the body's ordinary frame in `bodies`: place, facing, standing loop, one-shot, fade target (indoors too) and seat anchor. `anim::afresh` resets its pose state: its clips stop and its `Anim` is rebuilt from the current `Motion` (`anim::build`); its feet's IK holds are released (`ik::Legs::let_go`); its spring chains restart from rest (`characters::Springs::restart`). Its old seat anchor is removed.

What a returning body can carry, and where each comes from:

| State | Where it is drawn | On a body shown again |
| --- | --- | --- |
| Pose: sitting or standing, the standing loop | `town::shows` → `Motion::stand` each frame; `Anim::stands` blends it | `Motion` set the same frame; `Anim` rebuilt at the current loop (before the fix: blended from the loop it left sight in, ~0.22 s of a seated body rising while it faded in) |
| Activity: a one-shot or loop clip | `combat::actions`, `town::shows` → `Motion::action` each frame; `Anim::onces` | `Anim` rebuilt with no one-shot under way; the current one starts as on a new body |
| Seat | `live.rs` `seat_anchor` from the sitting state, each frame | the old `SeatAnchor` removed; set again if seated |
| Death | a death seen stays in `shown` playing `death` until `combat.deaths` lets it go | a body whose last one-shot is `death` is not kept |
| Wounds, health | the overhead plate's band (`ui/live.rs` `band`: the projection's exact health, else the fighter row's band), by id, each frame | nothing on the body; the plate is read from the tables |
| Gear: weapon drawn or sheathed, items held | not drawn on anyone's body: `weapon.rs` is my own client state, inventory is not drawn | nothing to refresh |
| Worn pieces, the look | the recipe from the look key (or folk and style without one) | `take_kept` compares the key, stage and dress; a change draws a new body |
| Feet, cloth | `ik::Legs` locks (world positions), `Springs` (tails, kept rotations) | released and restarted |

## Drive

- `check.py --run $R body-return` (island, explicit): three residents beside me in the street at noon, out of sight 30 m off, changed while away, back within `KEEP_S`; two arms, `kept` (default) and `anew` (`LIVING_GAME_PERF=nokeepbodies`). 34 checks.
  - A stands, then rests (sits) and is wounded (`admin_set_vitals` 30) while away.
  - C sits, then waits (gets up) while away.
  - B changes look key while away (owner SQL on `look`).
- **The dump's `bodies`** (each drawn body: `entity`, `stand`, `action`, `showing`, `stands`, `ground_seat`, `seat`, `fade`; and `kept`, the bodies kept hidden or fading out) and **`plates`** (each plate's `hp` band, `exact`, `hostile`).
- **The feet log follows C** (`LIVING_GAME_FEET_ID`). Its lines now carry `stand`, `stands`, `fade` and `entity`, so every frame C is drawn after `back` (fade under 1) is checked: standing clips, hips over 0.6 m, no seated loop blended.
- **The client log** (with a live script or `LIVING_GAME_PERF=diag`): `bodies: #ID shown again from its kept body E (person LOOK stage S; left sight T s ago)` and `bodies: #ID drawn anew: its kept body was drawn as … , it is now …`.
- Stills: `00_before`, `02_back` (about 0.7 s after `back`) and `03_late` in each arm's folder; `02_back` from the two arms is the pair to compare.

## Gotchas

- Choose residents who sit when they rest: `town.rs` stands about three in ten at ease (`world::hash(id, 0x5e47) < 0.3`; `rests_seated` in check.py).
- A projection is made as someone comes into sight, so a look changed while they are in sight shows only after they leave and come back. Each arm starts with the three out of my sight, after the look row is reset.
- The dumps come about 0.4 s after the body is shown again (a perception sweep after `place_at`), by which time a stale standing loop has blended out. Only the feet log's frames catch it: a client without `afresh` passes every dump check and fails the C-frames check (11 frames seated while fading in; `/Users/carlid/dev/slop-art-online/.local/living/battle-spikes/laptop/body-return/negative-control/`).
- Hidden time is about 4 s from `away` to the body shown again; `KEEP_S` is 6 s from the fade out. Slow admin calls push it toward the limit; past it the kept arm draws anew and fails "shown again".
- The scene puts me back where I stood before it (`start` snapshot): `battle-views` finds residents only round the arrival.
