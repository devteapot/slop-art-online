# mind-act-replace: acts scenes, the new scene, mechanics, det_compare

Branch `mind-act-replace` on main `7499c270` (the authority and rules of the commit that adds this record). Private server `slop-actreplace-20261120` (SpacetimeDB 2.14.1), rustc 1.99.1. No mind service, no model.

- `core-mar-1121-0028` (default seed): `tick` 6/6, `teach` 6/6, `refusal` 4/4, `committed` 16/16 PASS. `act_replace` 6/6 and `food` 4/4 PASS on their second run in the same world; the first run of each died on a 504 from the server ("durability confirmation timed out", `set_world_law` and `set_behavior`) while two `det_compare` copies wrote 200-fighter battles to the same disk. Not a check failure.
- `core-mar-mech-0044`: `verify_mechanics.py` 23 of 23 (the driver publishes `/wasm/living_authority.wasm`, copied into the private mount from the default-seed build).
- `det_compare.py` (Cullet battle of 200, main `7499c270` against the branch, both `LIVING_SEED=cullet`): identical over 3,600 ticks, 113 tables, 46,254 rows at the stop; with 16 players on the 10 m ring, identical over 1,500 ticks, 44,682 rows. Negative control (branch against itself, `--candidate-law mind_act_replaces=true`): differs from the first tick in `law_override`, `law_change`, `law_revision` and `chronicle` (the law's line and the ids after it) and in no other table over 3,600 ticks. The battle has no mind acts, so the law has nothing to act on there; an act-level comparison cannot be made with this tool (a call from outside the tick takes the wall clock as its time, which differs between the copies; an attempt with walks sent at the start tick differed only in those times).

Not covered here: the steering driver, the town and battle scenes other than these, and an act-level det comparison (above). The law's effect on bodies is measured in docs/INPUT_LATENCY.md "Mind acts replace".

Evidence: `.local/living/verify/core-mar-1121-0028/`, `core-mar-mech-0044/`, `.local/actreplace/det/` in `~/slop-evidence/mind-act-replace-20261120.tar.zst`.
