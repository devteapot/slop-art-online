# Cover sight on the shipped Cullet seed

Ran the live proof on `verify-core-cover-012742` at `1d9eb7c1`, rebased onto `5b92e4c9`. All 23 assertions passed. This exercised the public policy defaults and readback, player visibility and lines, the trunk and brush missile outcomes, and both pending mind scenes without a model call. The scratch world was paused, read back as paused and deleted.

Generated the positions from `living/seeds/cullet.json`. The native dump preserved the tile, height and layout digests `aba9f73ec66f029b`, `9604d8ab11f4274f` and `b7c81bc388729a4a`. The rebased `just living-check` passed.

Evidence is in `.local/living/verify/core-cover-012742/cover-proof.jsonl` and `.local/cover-sight/phase2/preflight-main.log`.
