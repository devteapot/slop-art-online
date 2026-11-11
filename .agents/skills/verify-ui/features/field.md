# Facing sight (the field of view)

While the world's `fov_on` law is on, what a character sees depends on where its body faces (`living_rules::sight::sees`, docs/PERCEPTION.md "The field of view"). The client draws the same rule from the same law:

- `living/game/src/sightedge.rs`: `senses(a)` from the installed script gives `field` with five values (`focal_deg`, `side_deg`, `side_share`, `near_m`, `margin_deg`) while `fov_on` is on.
- `living/game/src/sightfield.rs`: the field texture is the sight lines AND `sight::reach` at each texel's angle off `body.heading`. The heading comes from `steer::pose` on my own `my_body` row. It is recomputed on a 2° turn, as well as on the old triggers. With no field it is exactly the old field.
- `living/game/src/facing.rs`: the readout and the switch. Two notes show on each change: "Facing sight on/off" and the five values. F5 switches it through an admin-only second connection, only with `LIVING_GAME_ADMIN_TOKEN_FILE` set and only to `verify-*` worlds.
- `living/game/src/ui/facing.rs`: Settings › Play › Facing sight, with the switch (read-only without the admin link), "Facing sight: on/off" and the values.
- `living/game/src/heardmark.rs`: a soft ground mark per `heard_sounds` row, keyed by its per-viewer key. It sits that compass way at its band's rough distance and fades after the row goes.
- `living/game/src/controls.rs` `look`: `human_face(dx, dy)`.
  - Facing the cursor: the cursor's direction, standing and walking.
  - Facing where you walk: only while a move is aimed, then released with `(0, 0)`.
  - A look is sent on changes over 4°, at most every 0.1 s. A send the bucket refused ("too many movement inputs") is retried.

## Sub-features

- `off`: with `fov_on` false, `facing_sight.on` is false, the field dumps have `"facing": null` and nothing changes.
- `switch`: F5, or Settings › Play › Facing sight's switch, calls `set_world_law("fov_on", …)` over the admin link. Each switch is a `law_change` row (owner SQL).
- `readout`: the log line `facing: Facing sight on — Focal ±70° · side ±110° at 33% of sight · near 3 m all round · margin 10°` and the two toasts (the dump's `toasts`).
- `match`: at a look (live script `look:DEG`, which `human_face` sends), the authority's `perceived` rows for the player agree with the client's field texel under each creature within 15 m. Creatures that the keep margins (1 m, 10°) or a light could decide are counted apart.
- `walk`: walking north while looking east, the body heading is held 30° off the travel (`look_walk_deg`). A release (F3 to "where you walk") snaps it back to the travel. Standing, a release leaves the facing where it was.
- `heard`: each authority `heard` row (owner SQL) has a live mark with the same key, bearing and band in the dump's `extra.heard`. None is for someone in sight. Marks fade after their rows go.

## How to get to it (user POV)

- A play scene with `"client": {"law_toggle": true}` (`living/tools/play.py`): F5, or Menu › Settings › Play › Facing sight.
- Without it the line in Settings reads "Facing sight: off (read-only)". The world's admin switches it (`verify.py call --as-admin set_world_law '["fov_on", "true"]'`).

## Driving it with drive.py

Preconditions: baseline, plus six residents (`residents(run, 6)`) placed round the player: north and south at 4.5 m, east and west at 5.5 m (past side vision's 3.7 m and its 1 m keep margin), one at 1.4 m and one 8 m to the south-east.

- **Scenario:** `check.py --run $R field`. It sets `fov_on` false first, as admin.
- **Client flags:**
  - `LIVING_GAME_CONTROL=cursor`;
  - `LIVING_SIGHT_FIELD_DUMP=<drive>/fields` (the field dumps, each with its `facing`);
  - `RUST_LOG=…,living_game::controls=debug` (the `look: human_face(…)` lines);
  - `--admin-link` (drive.py writes the admin token to `.local/living/verify/RUN/private/`, mode 600, and deletes it when the drive ends).
- **Snapshots:** `--sync 'hN=sql|SELECT … FROM body;sql|SELECT body FROM perceived WHERE viewer = 0x{ident};sql|SELECT key, target, bearing, band FROM heard WHERE listener = {me}'`. They are saved in `scene.json` under `snaps`, with their wall times. The comparison uses the last field dump before each snapshot (`fov_compare.json`).
- **Plan:** `frame:0;yaw:0;…;key:F5:tap;…;look:0;wait:2.5;sync:h0;dump:h0;…;look:90;hold:0;wait:2;sync:walk;key:F3:tap;…;click:@settings:facing_sight`.

## Gotchas

- Owner SQL returns an identity as a one-element list (`["0x…"]`). drive.py unwraps it for `{ident}`. A perceived query on the raw value matches nothing, so the authority seems to see no one.
- The field dumps are written at most once a second, when the field changed. Wait at least 2 s after a `look:` before the snapshot.
- A switch reinstalls the script (`set_world_law` writes a new `script.revision`). The client recompiles it, and the readout follows within a second.
- At night, sight is 6 m and `near_m` 2. A lit resident (a torch's glow) is seen in side vision too. The comparison leaves out what a light could decide.
