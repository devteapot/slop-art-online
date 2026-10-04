# Reconnect after a dropped connection

## Sub-features

- Subscribe through a byte-forwarding local TCP relay.
- Close that connection's socket pair after two seconds of live updates.
- Observe the SDK disconnect signal.
- Wait three seconds, rebuild the connection, and resubscribe to the base and inspector query sets.
- Receive new initial rows and later updates after reconnect.

## How to get to it (user POV)

A program loses its authority connection, waits, creates a new connection, then subscribes again. The viewer schedules a retry in `living/viewer/src/net.rs:282` and calls `connect` at `net.rs:300`. Its inspector subscriptions must be recreated because they belonged to the old connection.

## Driving it with drive.py

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R"
```

The driver listens on an ephemeral loopback port and forwards to `127.0.0.1:3300`. The Rust probe writes `drop-request` only after the first subscription is live. The relay closes its client and upstream sockets exactly once. It keeps accepting the later connection.

`reconnect.json` must show a disconnect in round one and `applied` in round two. Round two must receive inspector experiences, positive live `body` and `stats` update counts, and a tick count greater than round one. `results.json` must report one drop and two accepted connections. The probe uses the viewer's three-second retry delay.

## Gotchas

- The relay never restarts, stops, or reconfigures the shared SpacetimeDB container.
- An anonymous reconnect creates a new identity, as the viewer's tokenless builder does. This test verifies observer recovery, not player credential recovery.
- The probe rebuilds connections explicitly. SDK 2.10.1 does not make this application policy automatic.
- This is a real network drop and authority connection, but it does not execute Bevy's `Net::pump`. Browser recovery belongs to the future UI skill (not built; see `verify`).
