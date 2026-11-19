# frame-views after the Spark's review (verify-player)

Follows `2026-11-18-2334-frame-views.md`. Branch `frame-views` after the seven review items. Server: the worker's own `views-stdb` (v2.14.1). Host shared (load 3–6).

- `player-vbranch-0846`: `approach.py` 3 of 6, the same three failures as main (`player-vmain-2313`): R's first-sight line names R ("walk → <name>"), "the walking player is perceived walking toward R" and "the player standing still is perceived as wait" (player None), on the mind's path; the bystander's client row of the walking player (polled within 1.5 s) passed. `fov.py` 36 passed; `face.py` 64 passed.

Evidence: `.local/living/verify/player-vbranch-0846/`.
