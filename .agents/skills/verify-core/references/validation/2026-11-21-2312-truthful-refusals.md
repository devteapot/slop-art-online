# Truthful refusals: why a target did not resolve (`truthful-refusals`)

Validated on the Spark on branch `truthful-refusals` from `origin/main` `67521779`, the module built from WIP commit `9c5b7463` (authority, rules and mind sources unchanged after it except one doc comment in `brain.rs`). Server: a private `clockworklabs/spacetime:v2.14.1` container, `slop-truthful-20261122` on `127.0.0.1:3393` with its own `/wasm` mount and volume, CPUs 0-4,10-14. No paid model calls. Scoped `maintain-verification-skill` pass for this change: `features/acts.md` (new section "Truthful refusals"), `features/graphs.md` (a failing leaf's words), the feature map row, the scene line in SKILL.md. Outcome: **changed** (this branch).

## Runs (`core-tr-233426`, default seed)

- `scenes.py truthful_refusals`: 26 of 26 (second run, with the walk-goal checks; the first run, before them, 24 of 24). Not acts named (speech, graph node, no such skill, a wrapper); attacker, speaker, hailer, suitor, partner and parent "unknown" in words; an unknown place, a place only B holds and a remembered-resource line as a name each "you know no place called …"; C beyond sight "no #C in sight"; controls: a wave at B done, A's own place and `{"place": "home"}` (no "home" row) each start a walk to that place / A's own home position (`steer` goal); a graph `goto` leaf "stuck: goto: you know no place called …", a `say` leaf told "nobody has spoken to you in the last minute"; a bush gathered (control) then stripped, "every berry bush in sight is bare"; B dead beside A "#B is dead: their remains lie in sight", C dead out of sight "no #C in sight".
- Neighbouring scenes, unchanged expectations: `refusal` 4/4, `act_replace` 6/6, `act_gaps` 12/12.
- The first attempt read `act_outcome` for A and timed out: a mind's character has no outcome row (only a played one); the scene reads A's `act` lines, and verify-player checks the codes.
- Evidence: `.local/living/verify/core-tr-233426/` (`truthful_refusals-results.json`, `truthful_refusals-evidence.json`, `*-actions.jsonl`).

## Offline

`living-rules` `acts::tests` (each non-act named) and `outcome::tests::the_codes_only_grow` (`moved`, `unknown` appended); `just living-check` ok.

## Not covered

`sound` and `commotion` targets, `{"named": …}`, and a filled role out of sight ("whoever hurt you is not in sight"): same function, not driven. Mechanics (`verify_mechanics.py`) was not rerun.
