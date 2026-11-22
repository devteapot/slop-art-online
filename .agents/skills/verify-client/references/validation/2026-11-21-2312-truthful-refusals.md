# The outcome code `unknown` (`truthful-refusals`)

Validated on the Spark on branch `truthful-refusals` from `origin/main` `67521779`, the module built from WIP commit `9c5b7463` (authority, rules and mind sources unchanged after it except one doc comment in `brain.rs`). Server: a private `clockworklabs/spacetime:v2.14.1` container, `slop-truthful-20261122` on `127.0.0.1:3393` with its own `/wasm` mount and volume, CPUs 0-4,10-14. No paid model calls. Scoped `maintain-verification-skill` pass: the change adds a value (`unknown`) to `act_outcome.code`, no table, column, view, reducer or subscription; `features/perception.md` says where the codes are proven. Outcome: **changed** (one sentence).

## Run

- `client-tr-000525` (`run.py`, scoped build, default seed): 45 PASS, no FAIL; own-state views (`my_act_outcomes` among them) return only the caller's rows; the reducer permission matrix 307 calls, 0 mismatches; cleanup confirmed (SQL 404, token removed). Evidence: `.local/living/verify/client-tr-000525/` (`results.md`, `cleanup-proof.json`).

## Game client

`living/game/src/verbs.rs` `outcome_of` maps no code to words or icons: a refused row shows its `why`; only `moved` is treated apart. The browser viewer reads no outcome code. No client change needed.

## Not covered

The open-perception build (no visibility change).
