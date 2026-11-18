# verify-llm: fast-lane-slots

Branch `fast-lane-slots` from origin/main `71d24077`. Trial service `slop-trials-stdb`, the fake model, private `CARGO_TARGET_DIR`, builds through `~/slop-mq/build-slot`.

- **The change.** Purpose `fast` is on its own lane, `Lane::Fast` (journaled `lane` "fast", no longer "urgent").
  - It has its own slots, as many as the world's `fast_lane_inflight` (`prompts::fast_slots`, set on every rules refresh). It never waits on the shared pool and never takes a slot from it.
  - Per-profile rates, outage gates and global pacing still apply.
  - Cause: the battle run's pilot, where fast calls waited 1.8/4.0 s for a shared slot and 15% timed out.
- **`fast-route`** pass (`llm-slots-fast-route-052902-fast-route`): purpose `fast` to its own profile, journaled with lane `fast`, latency and queue wait; a late reply dropped and journaled as a timeout.
- **`fast-cap`** pass on the third run (`llm-slots-fast-cap3-053215-fast-cap`): issued at once at most 4, in flight at the provider at most 4, issued in one second at most 3 (limit 4), 30 calls, 18 of 20 fighters served.
  - Run 1 (`llm-slots-fast-cap-052955`) failed in setup: an admin `place_at` found "no free walkable tile within 6 m". That's scene placement, before any call.
  - Run 2 (`llm-slots-fast-cap2-*`) failed main's old one-second limit (3) with 4 started in one second, the bucket's real maximum. fix-fast-cap-test (`80fe0649`, pushed 2026-11-12, never merged) is cherry-picked here; its record comes with it.
- **Unit tests:** `living-mind` 124 passed, 14 ignored, including the new `the_fast_lane_has_its_own_slots` and `lane_mapping` (fast → `Lane::Fast`).
- **Queue wait by class** (docs/FAST_LANE.md, "The fast lane's own slots"; free fake-model battles at 200):
  - fast: 4.0/4.8 s with 106 of 206 timed out, then 0.0/0.1 s with 0 of 478;
  - urgent slow: 5.2/16.5 s, then 5.2/17.7 s, unchanged;
  - ordinary slow: 0.5/1.7 s, then 0.7/2.3 s.

  A guaranteed urgent share was tried, never acted, and was taken out.
