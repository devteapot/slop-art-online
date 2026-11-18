# verify-llm: fix-fast-cap-test

Branch `fix-fast-cap-test` from origin/main `b02661f9`, the trial service `slop-trials-stdb`.

- **The fault.** `fast-cap` allowed at most 3 fast calls to start in one second, but the bucket (`fast::pump`: a burst of one second's worth, max(rate, 1) = 2, refilled 2 a second) can start 4. It failed on prompt-cache-order with 4 starts in 997 ms and in 923 ms.
- **The fix.** The limit is the burst plus one second's refill, 4 as shipped. Starts are counted at the authority's issue times (each answer's `issued_ms`), where the bucket acts. Arrival at the provider adds the mind's pickup jitter and is recorded (`arrived_at_provider_in_one_second_max`), not checked. The cap is unchanged.
- **Runs.** `fast-cap` passed three times (`llm-fct-161351`, `llm-fct2-161852`, `llm-fct3-162006`):
  - at most 4 issued at once and 4 in flight;
  - at most 3 issued in a second, while 4 arrived at the provider within one second each time (the jitter the old check counted);
  - 26–28 calls, 15–18 of 20 fighters with a call.
- `fast-route` passed (`llm-fct-161351`).
