# What a player perceives by facing

Since 2026-11-11 (`fov-1`; docs/PERCEPTION.md, "The field of view (sixth change)", "Heard, not seen"). While the world's `fov_on` law is on, the player's perceived set follows its body's facing, and what it hears but does not see comes through `heard_sounds` (`key`, `kind`, `bearing` 0 north clockwise, `band` 0 near / 1 close / 2 far), with no id. `scripts/fov.py` drives it with the player identity; admin `place_at`, `set_behavior` and `set_world_law` set the scene.

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

- 5.5 m, not 4: a creature already seen keeps 1 m (`keep_seen_m`) on the near ring (3 m) and on side vision (a third of 11 m by day), so 4 m stays seen by day.
- Other residents nearby are heard too: the script picks the row to the west in the close band.

## The player's look

`human_face(dx, dy)` turns `body.heading`; `(0, 0)` releases it. `scripts/face.py` drives it with the player identity, with the field on and a resident 5.5 m west.

- Standing: `human_face(-1, 0)` turns the body west (`my_body` at the end of its turn), and the resident comes into view.
- A look within 10° of the one held writes nothing (`my_body` row unchanged); a release while standing keeps the facing.
- Walking east (`human_move(1, 0)`) and looking north: the heading turns 30° north of east and no further (`look_walk_deg`). Released, it returns east. Looking north and stopping: the body stands and finishes the turn north.
- The movement input bucket, narrowed for the check with `set_world_law` (`input_hz` 0.2, `input_burst` 3): of eight looks 90° apart three or four are taken, the rest refused ("too many movement inputs"), and a `human_move` right after is refused too. The laws are put back (30, 15).
- Anonymous: refused ("you have no living character").

```bash
.agents/skills/verify-player/scripts/face.py --run "$R"   # any seed, about 1 min
```

Gotchas: HTTP calls are slower than the shipped refill (30 a second), so the bucket is only exhausted with the laws narrowed. `my_body`'s `heading` is the segment's start; the facing is `heading + turn × turn_s`.
