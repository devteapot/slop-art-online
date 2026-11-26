# neural-body-pilot: the player reducers serve body sessions too

Branch `neural-body-pilot` at `ea36f3d7a` (origin/main `fa2dbc3a6` merged in), island seed, private server `slop-nbpilot-1126` (2.14.1), CPUs 0-4,10-14.

Shape change: `human_move`, `human_face`, `use_skill` and `release_skill` resolve their character through `delegation::input_for`: the caller's played character first (unchanged), else a live body session's character while a `delegate` leaf runs (law `body_delegate_on`, off as shipped). For a person nothing changes: the same refusal ("you have no living character") for an identity without one, the plan replaced with waiting on taking the controls, skill uses recorded with source `player`.

| Check | Result |
|---|---|
| `scripts/combat.py --scene all` (`player-nb-001859`) | **60/60** |
| The body side of the same reducers | verify-minds `delegate-body` 32/32 (input accepted, a skill outside the scope refused, an older epoch fenced, a lapse refused) |
| Permission matrix (players and anonymous on `human_move`, `use_skill`, `release_skill`, `human_face`) | verify-client `client-nb-000849` 396/396 |

Not run: the other verify-player scripts (`intents.py`, `refusals.py`, …); det_compare with players (`--players`).
