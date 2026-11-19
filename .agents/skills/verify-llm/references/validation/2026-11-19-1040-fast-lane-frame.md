# Maintenance pass for the balanced fast frame (scoped)

Branch `fast-lane-frame` (commit `ba6fabec`) adds the world law `fast_frame`, which selects 2, the balanced frame (shipped), or 1, the first frame. Only the mind's fast system text changes. Requests, routing, lanes and journals are unchanged.

- **Source.** `fake_llm.py` `purpose_of` still recognises a fast request in both frames: each opens with "Something has just happened to you (see Why now)". `features/fast.md` now says so. No other drift was found in `fast.md`.
- **Live.** `llm-flf-103125`: `fake-contract` (10 scenarios), `fast-route` and `fast-cap` all passed under frame 2, the default. Frame 1 is driven by verify-minds `fast-frame` (d).
- **Scope.** This pass covered the fast lane's feature only. The other eleven feature files were neither source-read nor re-driven, because nothing they map changed. Outcome: changed (one feature-file sentence).

Evidence: `.local/living/verify/llm-flf-103125*`.
