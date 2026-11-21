# Truthful refusals through `human_act` (`truthful-refusals`)

Validated on the Spark on branch `truthful-refusals` from `origin/main` `67521779`, the module built from WIP commit `9c5b7463` (authority, rules and mind sources unchanged after it except one doc comment in `brain.rs`). Server: a private `clockworklabs/spacetime:v2.14.1` container, `slop-truthful-20261122` on `127.0.0.1:3393` with its own `/wasm` mount and volume, CPUs 0-4,10-14. No paid model calls. Scoped `maintain-verification-skill` pass: new `features/refusals.md` and `scripts/refusals.py`, the feature map row, `features/outcomes.md` (`unknown`), the invocation in SKILL.md. Outcome: **changed** (this branch).

## Runs (default seed)

- `player-tr-233838`: `refusals.py` 6 of 6: an unknown place `unknown` "you know no place called "verify nowhere""; `wave → attacker` `unknown` "nobody has hurt you in the last minute"; a resident 60 m off `unseen` "no #1 in sight"; controls: a wave at the resident beside the player `done`, `{"place": "home"}` with no home row a `goto` whose `steer` goal is the player's own home (40.5, 60.5); the resident killed beside it `refused` "#152 is dead: their remains lie in sight". Each line in `my_experience` carries the same words.
- On the same run afterwards, `outcomes.py` failed 2 of 7 (the player had already joined and eaten: "eat berries" was done, not refused) — run order, not the change. On a fresh run `player-tr2-233943`: `outcomes.py` 7/7 (14 PASS lines with its summary) and `told.py` all pass (exit 0). `refusals.md` now says to run it fresh or first.
- Evidence: `.local/living/verify/player-tr-233838/refusals.json`, `.local/living/verify/player-tr2-233943/`.

## Not covered

The other roles and bare resources through `human_act` (verify-core drives them through a mind's act; one function). Non-acts: `human_act` makes them a command graph.
