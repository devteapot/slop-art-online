# Seed format guards

## Sub-features

- All five `seed::tests::` native tests run, including legacy and authored seeds.
- A valid JSON copy missing required `animals` builds and reaches module publication.
- Publication output and a filtered server traceback show the initializer's failure, including panic classification.
- SQL records whether any world state remains. Cleanup confirms database absence.

`living/authority/build.rs:29` parses generic JSON. `living/authority/src/seed.rs:444` parses the typed `Seed` with `expect("seed json")`. `living/authority/src/lib.rs:60` calls it during `init`. Parser tests start at `living/authority/src/seed.rs:1429`.

## How to get to it (user POV)

Build and publish a seed. Invalid JSON fails during the build; valid JSON with a missing required field passes the generic build check and fails during initialization.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-guards-$(date +%Y%m%d-%H%M%S) --feature guards
```

Read `seed-tests.log` for five passing tests. The malformed child keeps `seed.json`, `launch.log`, `actions.log`, `module.log`, `publication.json`, `server-init.log`, `init-state.log`, `init-state.json`, `guards.json` and `cleanup.json`. Rejection is a required pass and does not require a panic or HTTP 500. The driver requires a publication attempt, a failed launch and SQL 404 with no usable world. The check asserts rejection only, so it is a plain pass. Error readability is an observation, not an assertion. The shared harness truncates publication stderr, so this check cannot certify the complete diagnostic. `docs/LIVING_HANDOFF.md`, "Still open", records the defect at `seed.rs:444`. The filtered server traceback records panic classification for diagnosis.

## Gotchas

- The malformed file is under `.local/living/verify/`, never the product's `living/seeds/`.
- The expected rejection is successful verification. The unreadable error is a KNOWN ISSUE. It does not fail the driver when all required rejection and cleanup checks pass.
- Doctor cannot pass on a rejected publication. The positive seeds establish launch and doctor; the negative path records the failure directly.
- The rejected database has no readable module-log endpoint. Its name still resolves through `/v1/database/<name>/identity` before cleanup. The driver retains the matching launch record and seed/init panic records during its publication interval, and drops other worlds' records.
