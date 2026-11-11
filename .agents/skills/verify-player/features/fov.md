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
- `human_face` (the player's facing input) is not built yet; this file covers the `face` act.
