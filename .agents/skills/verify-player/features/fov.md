# What a player perceives by facing

Since 2026-11-11 (`fov-1`; docs/PERCEPTION.md, "The field of view (seventh change)", "Heard, not seen"). While the world's `fov_on` law is on, the player's perceived set follows its body's facing, and what it hears but does not see comes through `heard_sounds` (`key`, `kind`, `bearing` 0 north clockwise, `band` 0 near / 1 close / 2 far), with no id. `scripts/fov.py` drives it with the player identity; admin `place_at`, `set_behavior` and `set_world_law` set the scene.

## Sub-features

- The `face` act (`human_act {"do": "face", "target": {"at": [x, y]}}`) turns the player's body: `my_body` heading at the end of its turn.
- Off: a resident 5.5 m behind is in `seen_bodies`; `heard_sounds` is empty.
- `set_world_law` as the player is refused ("admin only").
- On, facing away: the resident is not in `seen_bodies` and is heard as a person to the west, close; the row has only `key`, `kind`, `bearing`, `band`; the key is not the id and holds while the sound lasts.
- Facing it: seen, and its heard row goes.
- The field's edge, 5.5 m off: seen at 65° off facing; kept at 75° once seen (the 10° margin); gone at 100°; not seen afresh at 75°.
- Off again: seen behind; heard rows go within the linger (2 s). Both changes in `law_change`, by the admin.

## Driving it

```bash
.agents/skills/verify-player/scripts/fov.py --run "$R"   # any seed, about 1 min
```

## Gotchas

- `place_at` takes the nearest walkable tile: the script retries residents until the player stands 5.25–5.9 m from R, since at 5 m or less R is heard near, not close.
- 5.5 m, not 4: a creature already seen keeps 1 m (`keep_seen_m`) on the near ring (3 m) and on side vision (a third of 11 m by day), so 4 m stays seen by day.
- Other residents nearby are heard too: the script picks the row to the west in the close band.

## The player's look

`human_face(dx, dy)` turns the body's facing: the travel `heading` plus a facing offset with its own turn (`my_body`'s `face_off`, `face_turn`, `face_turn_s`; `living_rules::steer::facing`); `(0, 0)` releases it. Since `look-2` (2026-11-11) a held look never bends the travel. `scripts/face.py` drives it with the player identity, with the field on and a resident 5.5 m west on an open sight line.

- Standing: `human_face(-1, 0)` turns the body west (`my_body` at the end of its turn), with no facing offset, and the resident comes into view.
- A look within 10° (`look_slack_deg`) of the one held writes nothing (`my_body` row unchanged) while walking, or standing when it is also within 10° of where the body faces; a first look within 10° of a standing body's facing is free too. A release while standing keeps the facing. Non-finite input is refused ("direction must be finite").
- Walking east (`human_move(1, 0)`) on open ground off the road (`open_ground`, from `terrain_chunk`), each look its own walk from the same spot, with the look 45, 90, 135 and 180° north of the way. The travel, measured from successive position anchors (each `my_body` row's x, y at its `t_ms`) over at least 3 rows and about 4 s, is 0° (within 0.5°) at the cruise speed (within 1%) with no sideways part (under 1%). The facing turns at the turn rate (`face_turn` ±6 rad/s for span/6 s) and, sampled only after that turn has settled (`t_ms + face_turn_s` + 0.3 s), is 45, 75 and 75° north and, for the 180° look from a facing on the travel, 75° **south** (`wrap(π)` is +π; within 0.5°). After a look north first, a 180° look keeps the north shoulder (`steer::BEHIND_BAND`). Released, the facing returns to the travel at the turn rate.
- Facing sight while walking: a second resident Q 3 m behind and 5.5 m north (118.6° off the travel) is out of view standing east, in view while walking east with the look north, and out of view again when the look is released mid-walk.
- Looking north and stopping: the body stands and finishes the turn north, legs and facing.
- The walk reversing with the look held aside (`look-4`): play-test 6's 22:04:12 moment (44 walk keys and looks, only those, at their own timing) from a stand on open ground (`open_ground` with a 24 × 24 m box) facing the first walk's way. Four threads read `my_body` throughout. No row turns the facing faster than 6 rad/s (the travel's turn and the offset's together, `row_rate`); at every row seen the facing goes on from where the row before left it, within twice the turn rate over the 99th-percentile time between reads plus one 60 Hz tick (what one row written and replaced between reads could explain); rebuilt every 10 ms, it has no stretch over 90° in 0.25 s. On the module before `look-4` this scene fails all three (a 92.5° step, 192° in 0.25 s, a standing-turn row at 30 rad/s). `--scene reversal` runs only it.
- The movement input bucket, narrowed for the check with `set_world_law` (`input_hz` 1, the least the laws take: a lower value is clamped to 1; `input_burst` 3): of eight looks 90° apart three or four are taken, the rest refused ("too many movement inputs"), and a `human_move` right after is refused too. The laws are put back (30, 15).
- Anonymous: refused ("you have no living character").

```bash
.agents/skills/verify-player/scripts/face.py --run "$R"   # any seed, about 2.5 min; --scene reversal for step 3b alone
```

Not driven live (covered by source and the rules tests only): a path, pursuit or flight (any walk not under the keys) drops the held look; a look sent during a glide or a dash is taken when the body stands; the `face` act turns the whole body but leaves a held look held, so the next walk under the keys turns the facing back to it; setting off from a standing look, the facing turns back within 75° of the travel at the turn rate (`look-4`; the rules tests `steer::reversal_tests` cover it, and step 3b's moment contains such starts).

Gotchas: HTTP calls are slower than the shipped refill (30 a second), so the bucket is only exhausted with the laws narrowed, and a walker covers about 2.7 m per call-and-wait: set a scene's look before walking rather than after. `my_body`'s `heading` is the segment's start: the travel at the end of its turn is `heading + turn × turn_s`, and the facing then adds `face_off + face_turn × face_turn_s`. `place_at` takes the nearest walkable tile, which can put a wall between the player and the resident: the scene tries residents until the line is open. Polling `my_body` misses a row that lives less than a read (about 30 ms on a busy world): one reader thread missed three in the reversal scene, so it reads with four and bounds steps by the time between reads. A walk next to a wall slides along it (steering's slide plan, a heading 0.5 or 1 rad off the keys), and separation from a body close ahead bends it; that is steering, not the look. The pre-`look-2` check ("the heading turns toward the look, at most 30°") failed on the laptop with −1.02 and −0.02 rad against −0.52: exactly −0.52 ∓ 0.5, the slide plan around something ahead of a walker placed in town, not the clamp. `facing_end`/`heading_end` ignore the `next_ms` cap; the checks use `facing_at`, which keeps it.
