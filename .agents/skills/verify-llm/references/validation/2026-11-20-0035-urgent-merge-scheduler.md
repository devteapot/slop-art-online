# Scheduler fixes: preparation order, kept turns, grants for every ticket

The local tier ran the release mind at `1a770e94`, on pinned main `48550720`, on a private SpacetimeDB 2.14.1 container (`slop-urgent-opus-stdb`). Runtime code is the same at `5fb3cb6f`.

- **Fake-provider contract:** all ten scenarios passed (`llm-uo-vf2-fake-contract`, `llm-uo-vf3-fake-contract`).
- **`llm::tests`:** 37 passed, 2 ignored. The new scheduler tests:
  - `steady_urgent_turns_leave_routine_turns_their_share`
  - `a_backlog_prepares_in_parallel_when_slots_are_free`
  - `a_held_up_ticket_does_not_stop_the_grants`. On the code before `4b5cd4c8`, and in main's form, 0 of 6 ready calls were granted in 2 s with 16 free slots.
  - `a_turn_behind_a_long_call_prepares_when_its_slot_frees`
- **Every local case passed:**
  - `basic`, the five routing cases, `overflow`, `capacity-overflow`, `capacity-retry`, `retry-fallback`, `error-overflow`, `outage`, `repair`, `deliberation-retry` and `retry-exhausted` in `llm-uo-vf2`;
  - `timeout`, `missing-default-key`, `mix`, `fast-route` and `fast-cap` in `llm-uo-vf3`.
- **Interrupted case:** the `llm-uo-vf2` run was stopped in its `timeout` case for a trial-server reclaim. Its owned processes were already gone. Its journal was copied to `llm-uo-vf2-timeout/journal-recovered`, and its database was paused and deleted with `verify.py cleanup`. The remaining cases were rerun as `llm-uo-vf3`.
- **Earlier failure, not the scheduler:** `fast-cap` in `llm-uo-vf` at `4b5cd4c8` failed in setup, when the authority's `place_at` found no free walkable tile within 6 m, before any model call. It passed in `llm-uo-vf3`.

Not covered: real providers (paid tier), and pacing under real 429s beyond the fake contract.
