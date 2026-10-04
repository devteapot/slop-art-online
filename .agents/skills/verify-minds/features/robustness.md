# Mind robustness

## Sub-features

- Invalid routine branches are removed before installation, `living/mind/src/mind.rs:362` and `living/rules/src/normalize.rs:47`.
- A wholly invalid graph produces rejected attempts and `mind_skip`, preserving the current revision, `living/mind/src/mind.rs:1423`.
- `LIVING_ONLY` restricts bootstrap and action dispatch, `living/mind/src/mind.rs:169` and `living/mind/src/mind.rs:945`.
- A module republish disconnects the binary; the launcher restarts it and it handles a fresh request, `living/mind/src/main.rs:141` and `living/tools/run-mind.sh:6`.

## How to get to it (user POV)

An operator selects the AI characters served by one process. Invalid model behavior must not enter their graphs. Updating the authority must leave a route to resume mind service.

## Driving it with verify_minds.py

```bash
R=minds-robust-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case prune --case reject --case only --case reconnect
```

`prune` returns a sequence with an unknown `teleport` skill and a valid wait. The exact invalid reply stays in the journal. Installed brain and routine snapshots must contain no teleport, and the valid wait must execute.

`reject` keeps a desires top level as setup, then returns an invalid graph string. The mind must record three deliberate attempts and an error thought through `mind_skip`. `brain-before.json` and `brain-after.json` must have the same revision and source. `pending-after.json` must be empty.

`only` creates requests for two AI adults but serves one. The excluded actor keeps its test graph and pending request, with no thoughts. Every journal exchange belongs to the included actor during the eight-second observation.

`reconnect` calls shared `launch --keep-data` again for the same scratch run while the mind is alive, then doctors it again. If the update disconnects the binary, exit 2 is required. An identical module publish can retain the connection; in that case the driver stops only its owned mind process. Both routes wait three seconds and restart the same isolated configuration, as `run-mind.sh` does. A new PID and a new subscription-ready log are required. `survival-graph-*.json`, `survival-pending-*.json` and `survival-cursor-*.json` must match across the update. The installed graph belongs to the served actor; the pending request belongs to a deliberately excluded adult so it cannot race with an answer. The cursor is explicitly seeded through `mind_consolidated` using the largest actual inbox ID or previously consolidated cursor. Bootstrap may already have consumed the inbox. A short pause holds the scene stable across the update, while the mind remains alive. `reconnect.json` records process IDs, exits and survival checks; after unpausing, `thoughts-after-update.json` must contain the fresh post-update reason.

## Gotchas

- A fresh `launch` deletes data. This case must use `--keep-data` with the same run name. Any graph, pending-request or cursor mismatch is a product finding with before/after evidence.
- The bare binary exits on disconnect. Recovery requires the documented restart loop. An unchanged module can be published without disconnecting clients; `reconnect.json` distinguishes that controlled restart from a module-induced disconnect.
- An invalid current-plan routine and an invalid top-level graph follow different paths. Test both. Needs restoration can replace an invalid graph when the current top level has lost its desires.
- `LIVING_ONLY` narrows actions, not the service's world-state subscriptions or authority permissions.
- The service has admin credentials. Cross-identity authorization belongs to `verify-client`.
