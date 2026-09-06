# Observer tail authority regression

`scripts/verify_observer_tail.py` is prepared for a local database containing the composite `sim_audit(run, event_id)` index and bounded `sim_my_snapshot` query. Preparation ran `--help` and offline projection/contiguity fixtures before live execution. The subsequent isolated authority check passed on the new module; details are below.

Run after publishing the new module:

```sh
python3 scripts/verify_observer_tail.py \
  --active /absolute/path/to/active.json \
  --output /absolute/path/to/new-probe-output
```

The script reads only `server` and `db` from the active metadata. It creates its own `sim-audit-tail-check-*` participant run, grants fresh observer and participant identities, installs an explicit observation policy, and manually steps while the clock remains paused. It does not start inference, attach model controllers, or mutate the active metadata's original run. Credentials remain in memory. Cleanup pauses only the fixture and revokes its grants; captured files contain no tokens.

The check creates more than 360 actual authority events and compares the authenticated observer view with the final 180 raw authority events after the exact presentation transformations from `simulation/src/client_view.rs`. A second step must advance the tail. The range must be `[World.next_event - 180, World.next_event)`, sorted and gap-free. It also compares the participant's event list to that character's own memory projection, checks exclusion of other minds and observer pending state, and rejects model or engine-error events in the fixture.

Optional `--export-snapshot /path/to/snapshot.json` performs an offline check of an existing host export from an isolated `sim-audit-tail-check-*` run. It checks IDs `1..World.next_event`, no duplicates or future events, matching run, bounded tick/time and no unflushed world events. The script does not itself attach or exercise the host's incremental polling loop; omit this option for the bounded-tail integration check alone.

Evidence is `verification.json`, the exact captured authority `snapshot.json`, and observer/participant projections. The report distinguishes a live assertion failure from cleanup failure. The capture precedes grant revocation, which may add later authority events.

Offline preparation checked 180-event trimming, model-request/model-result presentation redaction, input immutability, valid full export acceptance, and rejection of truncated, duplicate, missing-first and unordered exports. Those fixtures validate the checker, not the deployed database index or query plan.

## Verified authority execution

The new diagnostic database passed on isolated run `sim-audit-tail-check-1788659916805758845`. Forty manual steps produced 379 actual events and `World.next_event = 380`; the authenticated observer received exactly projected events 200–379. The tail advanced after the final step. The participant received only its own memory projection, and no model or engine-error event occurred. Pausing the fixture and revoking both grants completed without cleanup errors. The diagnostic host’s original paused run was not mutated.

[Verification evidence](../output/society-lab/research-m6-3-authority-check/observer-tail/verification.json) includes the database, exact run, interval and assertions. The accompanying authority and identity-specific snapshots retain the comparison inputs. No optional host export was supplied; this result verifies the authority view, not the incremental host polling loop or sustained service under load.
