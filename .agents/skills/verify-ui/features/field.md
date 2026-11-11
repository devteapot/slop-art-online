# Facing sight (the field of view)

While the world's `fov_on` law is on, what a character sees depends on where its body faces (`living_rules::sight::sees`, docs/PERCEPTION.md "The field of view"). The client draws the same rule from the same law:

- `living/game/src/sightedge.rs`: my senses are the authority's `my_senses` row (sight, hearing and, while `fov_on` is on, the field's five values: `focal_deg`, `side_deg`, `side_share`, `near_m`, `margin_deg`). Without the row (before it arrives, or while minds hold the character) the client asks the installed script's `senses(a)` for the sight only, with no field.
- `living/game/src/sightfield.rs`: the field texture is the sight lines AND `sight::reach` at each texel's angle off `body.heading`. The heading comes from `steer::pose` on my own `my_body` row. It is recomputed on a 2° turn, as well as on the old triggers. With no field it is exactly the old field.
- `living/game/src/facing.rs`: the readout and the switch. Two notes show on each change: "Facing sight on/off" and the five values. F5 switches it through an admin-only second connection, only with `LIVING_GAME_ADMIN_TOKEN_FILE` set and only to `verify-*` worlds.
- `living/game/src/ui/facing.rs`: Settings › Play › Facing sight, with the switch (read-only without the admin link), "Facing sight: on/off" and the values.
- `living/game/src/heardmark.rs`: a soft ground mark per `heard_sounds` row, keyed by its per-viewer key. It sits that compass way at its band's rough distance and fades after the row goes.
- `living/game/src/controls.rs` `look`: `human_face(dx, dy)`.
  - Facing the cursor: the cursor's direction while standing; released while a direction is held (`FACE_WHILE_MOVING` off until look-2).
  - Facing where you walk: only while a move is aimed, then released with `(0, 0)`.
  - A look is sent on changes over 4°, at most every 0.1 s. A send the bucket refused ("too many movement inputs") is retried.
  - The look goes before the frame's move, so the release reaches the authority while the body still stands: the facing is kept, and the walk turns on its eased curve. A release mid-walk would snap the heading to the travel, a leg jump `look-walk` catches.

## Sub-features

- `off`: with `fov_on` false, `facing_sight.on` is false, the field dumps have `"facing": null` and nothing changes.
- `switch`: F5, or Settings › Play › Facing sight's switch, calls `set_world_law("fov_on", …)` over the admin link. Each switch is a `law_change` row (owner SQL).
- `senses`: after F5, the dump's `facing_sight` (`source: Authority`, `sight`, the field) equals the `character_senses` row for the player (owner SQL; `my_senses` is its view).
- `readout`: the log line `facing: Facing sight on — Focal ±70° · side ±110° at 33% of sight · near 3 m all round · margin 10°` and the two toasts (the dump's `toasts`).
- `match`: at a look (live script `look:DEG`, which `human_face` sends), the authority's `perceived` rows for the player agree with the client's field texel under each creature within 15 m. Creatures that the keep margins (1 m, 10°) or a light could decide are counted apart.
- `walk`: walking north with the cursor east, the client releases its look while a direction is held (`controls::FACE_WHILE_MOVING`, off until dev-box's look-2), so the body faces and walks north. With the switch on, the authority would hold the heading 30° off the travel (`look_walk_deg`); the check follows the switch. A release (F3 to "where you walk") leaves the walk on its travel. Standing, a release leaves the facing where it was.
- `heard`: each authority `heard` row (owner SQL) has a live mark with the same key, bearing and band in the dump's `extra.heard`. None is for someone in sight. Marks fade after their rows go.

## How to get to it (user POV)

- A play scene with `"client": {"law_toggle": true}` (`living/tools/play.py`): F5, or Menu › Settings › Play › Facing sight.
- Without it the line in Settings reads "Facing sight: off (read-only)". The world's admin switches it (`verify.py call --as-admin set_world_law '["fov_on", "true"]'`).

## Driving it with drive.py

Preconditions: baseline, plus six residents (`residents(run, 6)`) placed round the player: north and south at 5 m, east and west at 5.5 m (`place_at` puts them on tile centres; past the near ring's 3 m, side vision's 3.7 m and their 1 m keep margin), one at 1.4 m and one 8 m to the south-east.

- **Scenario:** `check.py --run $R field`. It sets `fov_on` false first, as admin.
- **Client flags:**
  - `LIVING_GAME_CONTROL=cursor`;
  - `LIVING_SIGHT_FIELD_DUMP=<drive>/fields` (the field dumps, each with its `facing`);
  - `RUST_LOG=…,living_game::controls=debug` (the `look: human_face(…)` lines);
  - `--admin-link` (drive.py writes the admin token to `.local/living/verify/RUN/private/`, mode 600, and deletes it when the drive ends).
- **Snapshots:** `--sync 'hN=sql|SELECT … FROM body;sql|SELECT body FROM perceived WHERE viewer = 0x{ident};sql|SELECT key, target, bearing, band FROM heard WHERE listener = {me}'`. They are saved in `scene.json` under `snaps`, with their wall times. The comparison uses the last field dump before each snapshot (`fov_compare.json`).
- **Hour:** the scenario sets noon first (`sync:noon`, `UPDATE world SET epoch_ms = {epoch_at:12}`, a scratch fixture through drive.py), so side vision is compared.
- **Plan:** `frame:0;yaw:0;…;key:F5:tap;…;look:0;wait:2.5;sync:h0;dump:h0;…;look:90;hold:0;wait:2;sync:walk;key:F3:tap;…;click:@settings:facing_sight`.

## Gotchas

- Owner SQL returns an identity as a one-element list (`["0x…"]`). drive.py unwraps it for `{ident}`. A perceived query on the raw value matches nothing, so the authority seems to see no one.
- The field dumps are written at most once a second, when the field changed. Wait at least 2 s after a `look:` before the snapshot.
- A switch reinstalls the script (`set_world_law` writes a new `script.revision`). The client recompiles it, and the readout follows within a second.
- At night, sight is 6 m and `near_m` 2. A lit resident (a torch's glow) is seen in side vision too. At night (the dump's sight under 11 m) the comparison leaves out what a light could decide. By day no one is lit, so side vision is compared.
