# Heed for players: the combat scenes beside it (branch `heed-player`)

Follows 2026-11-26-1300-heed-player.md, which left `combat.py` not re-driven. Branch `heed-player` at `346f0ccb5` (origin/main `b0720fd94`), private `hp-stdb` (SpacetimeDB 2.14.1). No change to this surface's shape beyond that record's.

| Run | Seed | Driven | Result |
|---|---|---|---|
| `player-island-142423` | island (the scene gate's player seed) | `combat.py --scene all` | **60/60** |
| `player-combat-140500` | default world | `combat.py --scene all` | 43 of 57: the 14 failures are the default world's lack of what the scenes need (no healing or fire know-how, no bow, no bold pack, so the death scene never ran), not this change; the island run above is the comparison |

With the heed laws off (as shipped, as here) `combat::show` gives every onlooker the rows main gives: both parties are individuals while heed does not apply, so nothing is masked. Evidence: `.local/living/verify/player-island-142423/combat.json`, `.local/living/verify/player-combat-140500/combat.json`.

**Not covered:** the combat scenes with the heed laws on (`heed.py` and verify-client's `heed_rows.py` drive the feed's rule under heed).
