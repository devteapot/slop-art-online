# The fast lane's triggers

docs/FAST_LANE.md; `living/authority/src/fast.rs` (triggers, the `fast_ask` rows, the pump), `act.rs` `damage` (a blow taken), `combat.rs` `accepted` (a move seen), `mind.rs` `mind_patch` and `mind_fast_done`, the laws `fast_lane_on` (false), `seen_again_n` (3), `fast_lane_rate` (2), `fast_lane_inflight` (4), `fast_lane_gap_s` (6), `fast_lane_stale_s` (8) in `skills.rhai` `laws()`.

## What a run shows

`scenes.py seen_again`, on the authority alone (no mind service), with `fast_lane_on` and `fast_lane_inflight` 0, so a character's `fast_ask` row keeps its newest trigger and can be read:

- **The repeat.** B (a spear) strikes at A with its heavy blow over and over; A's own graph dodges every windup it sees, so the blows miss and the reason is not overwritten. The reason "<B as A perceives it> winds up an attack at you" first appears at B's 3rd windup at A, and on a fresh pair at the 2nd once `seen_again_n` is 2.
- **No count is told.** No reason, and nothing A was told, counts B's moves or says "again".
- **Unseen moves aren't counted.** With `fov_on`, C faces away from D, who shoots it from 8 m behind: C's reason is only its struck line ("An arrow struck you from somewhere you could not see: …").
- The scene puts the laws back after.

What the mind service does with the rows is verify-minds `fast-lane` and `fast-takeover`; the caps' effect is verify-llm `fast-cap`; who may call the reducers is verify-client.
