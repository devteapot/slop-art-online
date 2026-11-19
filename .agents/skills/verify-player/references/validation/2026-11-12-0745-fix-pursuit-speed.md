# verify-player: fix-pursuit-speed

## 2026-11-12 fix-pursuit-speed (Spark)

`combat.py --scene all` on a fresh island world with the fix (`player-pursuit-fixc-083817`): 44 of 44. On a world that had run other scenes first (`player-pursuit-080916`), "bold wolves attack a healthy adult player" failed three times (no blow within 20 s at 5 m) while the next scene's wolves killed the player. The `wolves` scene alone on two fresh island worlds, one built with main's condition (`player-pursuit-mainc-083723`) and one with the fix (`player-pursuit-fixc-083817`), passed on both: the reused world's state, not the change. A player's own `use_skill` does not walk into reach (`act::begin`); the change reaches a player's character through `human_act` and graphs.
