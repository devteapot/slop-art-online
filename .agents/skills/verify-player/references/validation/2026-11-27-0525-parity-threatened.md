# parity-threatened: player combat with `perceived_threat_on` off

Branch `parity-threatened` (`313d77868`, from origin/main `e220bea8e`). Spark, private server `slop-ppt-stdb` (`127.0.0.1:3391`, SpacetimeDB 2.14.1), island seed, run `player-ppt1-061300`. Build through `build-slot`, launch under `trial-activity.lock`, world deleted by cleanup.

The change gates what `threatened` reads for AI graphs and heed behind a new law, off as shipped; no player reducer or view changed. `combat.py --scene all`: **60 of 60** (`.local/living/verify/player-ppt1-061300/combat.json`).

**Not covered:** the law on with a player in the fight (the player's own decisions read `seen_fighters`, not `threatened`); heed for players (`heed_players`).
