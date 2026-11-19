# The fast lane's triggers

docs/FAST_LANE.md; `living/authority/src/fast.rs` (triggers, the `fast_ask` rows, the pump), `act.rs` `damage` (a blow taken), `combat.rs` `accepted` (a move seen), `mind.rs` `mind_patch` and `mind_fast_done`, the laws `fast_lane_on` (false), `seen_again_n` (3), `fast_lane_rate` (2), `fast_lane_inflight` (4), `fast_lane_gap_s` (6), `fast_lane_stale_s` (8) in `skills.rhai` `laws()`.

## What a run shows

`scenes.py seen_again`, on the authority alone (no mind service), with `fast_lane_on` and `fast_lane_inflight` 0, so a character's `fast_ask` row keeps its newest trigger and can be read:

- **The repeat.** B (a spear) strikes at A with its heavy blow over and over; A's own graph dodges every windup it sees, so the blows miss and the reason is not overwritten. The reason "<B as A perceives it> winds up an attack at you" first appears at B's 3rd windup at A, and on a fresh pair at the 2nd once `seen_again_n` is 2.
- **No count is told.** No reason, and nothing A was told, counts B's moves or says "again".
- **Unseen moves aren't counted.** With `fov_on`, C faces away from D, who shoots it from 8 m behind: C's reason is only its struck line ("An arrow struck you from somewhere you could not see: …").
- The scene puts the laws back after.

## The profiling counters

While profiling is on (`set_profile`), the lane counts what it does in the authority's `diag:` lines (`common::diag`; nothing is counted otherwise):
- **Triggers:** `fast:trigger_struck`, `fast:trigger_seen`, and `fast:merged` (a trigger on a row already waiting or served).
- **The pump:** `fast:issued`, `fast:stale` (a waiting row dropped after `fast_lane_stale_s`), `fast:expired` (an issued row unanswered for two stale windows) and `fast:gap_skip` (a row passed over inside its character's gap).
  - `fast:cap_inflight` and `fast:cap_rate` count pump passes stopped by the in-flight cap or an empty rate bucket with rows still waiting. A pass runs on every trigger and on every tick while a row waits, so these are passes, not calls.
- **The answers:** `fast:installed` (`mind_patch` on an unchanged plan), `fast:refused` (the plan check) and `fast:kept` (`mind_fast_done`).

They feed the battle run's measures (docs/FAST_LANE.md, "The battle run").

`scenes.py fast_diag` drives them with no mind service. Two victims are struck by two spearmen, and the scene keeps them alive with `admin_set_vitals`.
- **First phase:** in flight 1, rate 10, stale 3 s, gap 2 s. One row is issued, the other waits behind the cap and goes stale; an unanswered issue expires.
- **Second phase:** rate 0.2, in flight 5. Rows stop on an empty bucket.
- **The answers,** as the minds' controller gives them:
  - `mind_fast_done`, counted as kept;
  - `mind_patch` on an unchanged plan, counted as installed;
  - `mind_patch` after a `mind_install` changed the plan, counted as refused.
- Every counter must be above zero. A window after profiling stops must show no `fast:` keys. The laws are put back after.

What the mind service does with the rows is verify-minds `fast-lane` and `fast-takeover`; the caps' effect is verify-llm `fast-cap`; who may call the reducers is verify-client.
