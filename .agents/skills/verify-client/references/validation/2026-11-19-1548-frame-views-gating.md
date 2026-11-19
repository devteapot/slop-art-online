# frame-views: both delivery laws off take main's path (verify-client)

Follows `2026-11-19-1414-frame-views-subscribe-all.md`. Branch `frame-views`: with `cue_transport_on` and `near_tier_on` both off, no cue marks, no targets, no engagements and no near tier are worked out (`frame::DELIVERY`, `frame::near_set`). Server: the worker's own `views-stdb` (v2.14.1). Host shared (load 3.2–4.2 while these ran).

- `cues.py`: `client-viewsq-1545i` 20 of 21: one windup in the law-off phase (cues off, tiers on; a state the gating leaves as it was) reached A after 366 ms against a 150 ms bound, the other three in 35–49 ms. `client-viewsq-1545j` and `client-viewsq-1546k` (fresh worlds, the same build): 21 of 21 (law-off windups 25–67 ms). Recorded as a load outlier, not reproduced.
- `near_tier.py`, `client-viewst-1543g`: 7 of 7 (the `near_tier_on` off phase and back on).
- `living-check` (with its new `frame-tests` step: `frame::tests::both_delivery_laws_off_take_main_s_path` and the cue budget's test): passed.

Note: the probe binary (`.local/living/verify/target-client`) was removed twice by the host's idle-build cleanup during the day; rebuild it before driving (`SKILL.md`, "Run").
