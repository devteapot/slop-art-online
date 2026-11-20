# frame-views after the Spark's review (verify-core)

Follows `2026-11-18-2334-frame-views.md`. Branch `frame-views` after the seven review items (the near tier in new tables, `cue_transport_on` off by default, `frame::creature_gone` pruning profiling history at a death). Server: the worker's own `views-stdb` (v2.14.1). Host shared (load 3–6).

- `core-views-0846` (default seed): `tick` 6 passed; `senses` 7 passed; `health_seen` 9 passed and its known XFAIL.
- `core-viewsc-0846` (`--seed cullet`): `sweep_kept` 7 passed; `sweep_rollback` 9 passed; `sweep_marks` 6 passed (named after 0.29 s; 660 rows compared, none differed).
- `living-rules`: `cue_transport_on_is_off_until_accepted_and_separate_from_attention_cues` passed.

Not run this time: `doing_seen` (red on main). Evidence: `.local/living/verify/core-views-0846/`, `.local/living/verify/core-viewsc-0846/`.
