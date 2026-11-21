# Verification cleanup after a fixture clock change

Validated on branch `verify-cleanup` from `origin/main` at `a9f024284` with uncommitted Python tooling and documentation changes. The native client and island authority WASM were built through `build-slot` with `BUILD_SLOTS=1` and a private `CARGO_TARGET_DIR`. Generated assets were read through symlinks to `/Users/carlid/dev/slop-play10/living/game/assets/`. The local server and CLI were SpacetimeDB 2.14.1 at `127.0.0.1:3300`. No model service ran.

## Design

Commit `8d77a2fa5` introduced the recorded epoch as a world incarnation check. A database reset can keep the database identity while reinitializing the world. Commit `04cdf3d4f` added clock bookkeeping for inactivity leases, but the fixture SQL fell through to a plain update on PID-supervised runs. Recording the fixture epoch in both guard modes reuses that bookkeeping and keeps the reset check. The UI driver surfaces failed owner SQL at a scenario sync point.

Cleanup requires a matching run name, server and launched database identity and refuses the kept play and walk prefixes. Legacy records without an identity can no longer use the name-only deletion path. The existing pause and read-back precede deletion by identity. The clock fixture reads and updates the singleton `world` row through owner SQL and updates two local JSON records under the guard lock. There are no new database rows or subscriptions. [Database HTTP API](https://spacetimedb.com/docs/http/database/), [SpacetimeDB 2.14.1 routes](https://github.com/clockworklabs/SpacetimeDB/blob/v2.14.1/crates/client-api/src/routes/database.rs), [CLI reference](https://spacetimedb.com/docs/cli-reference/).

## Live checks

- `verify-ui-cleanup-20261119-141609` used the PID-supervised guard. Doctor confirmed advancing ticks. `check.py --run ui-cleanup-20261119-141609 camera-rotate` passed all 19 checks. The noon sync changed `epoch_ms` from `1795094209651` to `1795094084766`. Owner SQL, `state.json`, `world-guard.json` and the recorded fixture query agreed on the new value before cleanup. Cleanup deleted the world without an epoch restore, released its guard, and removed the module copy. The database name returned HTTP 404. Evidence is in `.local/verify-cleanup/live.log` and `.local/living/verify/ui-cleanup-20261119-141609/` (`epoch-before.json`, `epoch-after.json`, `actions.log`, `ui/checks.json`, `ui/camera-rotate/scene.json` and `ui/camera-rotate/client.log`).
- `verify-ui-cleanup-lease-20261119-141746` used the default inactivity guard. An owner fixture UPDATE changed `epoch_ms` from `1795094277386` to `1795094267386` and both records matched. Cleanup released the guard and the database name returned HTTP 404. See `.local/verify-cleanup/lease.log` and `.local/living/verify/ui-cleanup-lease-20261119-141746/`.
- Cleanup exited 1 for the dummy run with `no launch record`, a dummy legacy record with `no database identity in launch record`, and `verify-play-1` with `kept verification world`. Read-only HTTP metadata requests for the kept name returned 200 before and after. See `.local/verify-cleanup/refusals.log`.
- Focused mocked checks exercised a changed database identity and an unrecorded epoch change. Each refused before any pause or delete request. See `.local/verify-cleanup/safety.log`.

Python compilation, the validation filename check and `git diff --check` passed. The live runs covered cleanup in both guard modes and the real camera rotation fixture. Guard expiry, commitlog archiving and other UI scenarios were outside this run.
