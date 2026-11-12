# The fast lane's route and caps

docs/FAST_LANE.md. Purpose `fast` (`llm.rs` `Lane::for_purpose`: the urgent lane), routed by `rethink.json` `fast.route`; `fast.timeout_ms` drops a late reply (`mind/fast.rs`, journaled as a timeout). The caps are world laws the authority applies when it issues `fast_ask` rows: `fast_lane_rate` (2 a second) and `fast_lane_inflight` (4). The fake tells a fast request by its system prompt (`fake_llm.py` `purpose_of`) and keeps the plan by default.

## Cases

- `fast-route`: one pair (spawned minds, spears), only the victim served, `fast_lane_on` on.
  - Purpose `fast` goes to a profile of its own (`fastp`), never to the default one; journaled with `profile`, the urgent `lane`, `latency_ms` and `queue_wait_ms`.
  - The first reply is held 5 s past the 3 s timeout: journaled as a timeout, a `fast` thought "kept: timed out".
  - Later replies keep the plan.
- `fast-cap`: a battle of 20 (ten pairs attacking each other), all served, the laws as shipped, each fast reply held 2.5 s, 30 s.
  - At most 4 rows issued at once (sampled) and 4 requests in flight at the provider.
  - At most 4 issued in any one second: the bucket's burst (one second's worth, 2) plus one second's refill (2). Counted at the authority's issue times, not at the provider, where the mind's pickup adds jitter (recorded as `arrived_at_provider_in_one_second_max`). Until fix-fast-cap-test (2026-11-12) the test allowed 3 and failed when 4 started within a second, which the bucket permits.
  - Records how many fighters got a call and how long each trigger waited (`result.json`). Fake model only; no tick numbers, which a battle would confound (docs/FAST_LANE.md).
