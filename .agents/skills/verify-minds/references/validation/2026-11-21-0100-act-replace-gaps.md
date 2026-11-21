# act-replace-gaps: mind acts through the input bucket and the checked replacement

Branch `act-replace-gaps` (`mind_act` and `mind_act_checked` spend an input under `act_input_cost`; a replacing act is checked before the act under way is broken off under `act_replace_checks`). Private server `slop-actgaps-20261121` (SpacetimeDB 2.14.1), rustc 1.99.1, the fake model only.

- `minds-ag-011706`: `acts`, `dealings`, `roundtrip`, `fast-lane`, `takeover` PASS. `act-repair` and `queued` failed before driving anything: `KeyError: 'token'` reading the player's token from the run's `state.json` (player tokens live in the run's private credentials file since verify-credentials; main's harness, not this branch).
- `verify_minds.py` now reads the token through `player_token(run)` (the credentials file, else `state.json`), in `act-repair` (with `act-repair-stop` and `talk-act-repair`), `queued` and `alongside`. `minds-ag2-012433` (`--no-unit-tests`): `act-repair`, `queued`, `parked` PASS. `alongside` not rerun.

Not covered: the other cases; paid tiers (no model call was made).

Evidence: `.local/living/verify/minds-ag-011706-*/`, `minds-ag2-012433-*/` in `~/slop-evidence/act-replace-gaps-20261121.tar.zst`.
