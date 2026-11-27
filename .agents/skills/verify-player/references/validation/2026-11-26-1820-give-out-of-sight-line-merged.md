# give-out-of-sight-line after merging main's gate step 1 (told.py staging)

Follows 2026-11-26-1800-give-out-of-sight-line.md. Branch `give-out-of-sight-line` at merge `6fe07e92c` (origin/main `4b04768ac`), private server `slop-tgm2-20261126` (SpacetimeDB 2.14.1, `127.0.0.1:3592`). Builds through `build-slot` with a private `CARGO_TARGET_DIR`; launches under `trial-activity.lock`; worlds deleted by `verify.py cleanup`. No mind service, no model calls.

**Resolution of `told.py`.**
- Part 2 keeps main's step-1 staging: both gifts on a quiet open line; the receiver retreats to 5 m from the giver, past the 2.8 m completion reach and inside the 6 m unlit night sight; the gift is checked to be performing (world paused) before the move; a diagnostic is captured on a miss.
- The branch's 4.5 m offset is dropped. It served the same purpose, but was measured from wherever `place_near` had put the receiver, on ground that might block sight.
- Part 3 now stages on the same line: the giver on its spot, the receiver beside it, then 20 m along the line.

`just living-check`: exit 0. Every step was skipped, because the merged inputs are identical to runs that already passed (the merge brings no Rust change).

| Run | Result |
|---|---|
| `player-tgmm1-191317` | **28/28**. Part 2: one "…: they moved away" each. Part 3: the player's command gave "lost sight of them". The AI's graph gave one timer line ("meat … they moved away") and then the leaf's line ("stone … lost sight of them"). Deliberate acts gave one "they moved away." each |
| `player-tgmm2-191440` | **28/28**, the same paths |
| `player-tgmm3-191520` | **28/28**. Both graph forms gave the leaf's line on the first try |
| verify-core `truthful_refusals` (`core-tgmm-191447`) | **26/26** |

Every gift gave exactly one line, whichever path told it. Evidence: `.local/living/verify/player-tgmm{1,2,3}-*/`, `.local/living/verify/core-tgmm-191447/`.

**Not covered:** as in the record this one follows.
