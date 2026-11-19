# Seed format guards

## Sub-features

- All six `seed::tests::` native tests run, including legacy and authored seeds.
- A valid JSON copy missing required `animals` builds and reaches module publication.
- Publication output and the filtered server records show the initializer's failure: `init` returns `seed: missing field ...` (no panic since `megacity-1`).
- SQL records whether any world state remains. Cleanup confirms database absence.

`living/authority/build.rs` parses generic JSON (and accepts `LIVING_SEED=none`, a floor module with no compiled seed). `init` in `living/authority/src/lib.rs` parses the typed `Seed` and returns `Err("seed: ...")` when a required field is missing, before `floor::begin`. Parser tests are the `seed::tests` module at the end of `living/authority/src/seed.rs`. An absolute `--seed` path works because `build.rs` joins it onto the seeds directory, and joining an absolute path replaces the base.

## How to get to it (user POV)

Build and publish a seed. Invalid JSON fails during the build; valid JSON with a missing required field passes the generic build check and fails during initialization.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-guards-$(date +%Y%m%d-%H%M%S) --feature guards
```

Read `seed-tests.log` for six passing tests. The malformed child keeps `seed.json`, `launch.log`, `actions.log`, `module.log`, `publication.json`, `server-init.log`, `init-state.log`, `init-state.json`, `guards.json` and `cleanup.json`. Rejection is a required pass and does not require a panic or HTTP 500. The driver requires a publication attempt, a failed launch and SQL 404 with no usable world. The check asserts rejection only, so it is a plain pass. Error readability is an observation, not an assertion. The shared harness truncates publication stderr, so this check cannot certify the complete diagnostic. `docs/LIVING_HANDOFF.md`, "Still open", records the old defect (a panic that did not name the field). `guards.json` records `missing_field_diagnostic_visible` and `panic_reported` (expected false now) for diagnosis.

## Gotchas

- The malformed file is under `.local/living/verify/`, never the product's `living/seeds/`.
- The expected rejection is successful verification. Whether the error names the field is observed, not asserted (KNOWN ISSUE: publication stderr is truncated). It does not fail the driver when all required rejection and cleanup checks pass.
- Doctor cannot pass on a rejected publication. The positive seeds establish launch and doctor; the negative path records the failure directly.
- The rejected database has no readable module-log endpoint. Its name still resolves through `/v1/database/<name>/identity` before cleanup. The driver retains the matching launch record and init error or panic records during its publication interval, and drops other worlds' records.
