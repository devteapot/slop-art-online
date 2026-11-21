# mind-act-replace: human_act through submit_player

`human_act` now reaches the act queue through `acts::submit_player` (the same step as before; a mind's acts go through it only under `mind_act_replaces`). Private server `slop-actreplace-20261120`, main `7499c270` plus the branch.

- `player-mar-004918` (island): `combat.py --scene all` 53 PASS and 4 FAIL, all four in `bow` ("refused: out of breath": the scenes before it spent the player's breath); `--scene bow` alone in the same world 4/4 PASS. `teleport` 3/3 PASS (a jump put elsewhere ends; a move then moves; a resident's walk put elsewhere is broken off). `command.py` 4/4, `told.py` 12/12. `outcomes.py` failed 4 on the island (it needs the default seed: the player carried berries, so the refused eat was a done eat).
- `player-mar2-005314` (default seed): `outcomes.py` 14/14.

Evidence: `.local/living/verify/player-mar-004918/`, `player-mar2-005314/` in `~/slop-evidence/mind-act-replace-20261120.tar.zst`.
