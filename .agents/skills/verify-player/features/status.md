# The player's statuses (the pills)

How the player's body is, as the game client shows it: the installed script's `status_of` over the player's own `my_vitals` row (`living/game/src/ui/live.rs` `my_body`: `BodyFacts::of`, then `Scripts::status_of`; a status whose tone is `plain` is the body's words when all is well and gets no pill). Since status-parts (docs/STATUS_PARTS.md, docs/WORLD_RULES.md "The body: meters and statuses") the shipped law is the join of eight declared parts (`status_parts()`), and every client asks by the parts, each kept on what it reads.

## What it does (user POV)

- The player reads its own `my_vitals` row (owner-only view) and the public `script` row, and works its statuses out locally, as the authority's alarms and the minds' body words do: one set of thresholds.
- Asked by the parts or whole, the statuses are the same list in the same order, every field alike.

## Driving it

`scripts/status.py --run "$R"` on a default-seed run (about 30 s; builds the `living-rules` example `status_check` in `$CARGO_TARGET_DIR`):

1. The player joins. Its `my_vitals` row, read with its own identity, and the `script` row give a list by the parts that equals the whole law's, by day and at night; the script declares 8 parts.
2. Admin fixtures (not a player's act: `admin_set_vitals` health 25, owner SQL `UPDATE vitals` hunger 85, energy 5): the parts give `very_hungry`, `exhausted`, `badly_hurt`, `slowed`, the same as the whole law; the pills are the statuses that are not plain.
3. Set well again (health full, hunger 10, energy 95): `fed`, `well_rested`, `unhurt`, the same both ways, and no bad pill.

Evidence: `RUN/status.json` (each step's `my_vitals` row, the facts handed to the example, its answer both ways, the felt words), `RUN/status-script.rhai`.

## Not covered

The game's drawing of the pills (verify-ui's bar checks); statuses that need a fight or the night (verify-core `status_parts`).
