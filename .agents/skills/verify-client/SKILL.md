---
name: verify-client
description: Verify the living core client protocol through real Rust SDK WebSocket connections. Use when changing subscriptions, public or private tables, identity-scoped views, reducer permissions, or reconnect behavior, or when a program receives unexpected authority data.
---

# Verify the client protocol

Read the [`verify` entry point](../verify/SKILL.md) first. It owns the shared launch, doctor, player identity, cleanup, and evidence rules. This skill adds a standalone Rust SDK probe and a Python driver. It uses a fresh `verify-client-*` database and makes no model calls.

## Run

Preconditions: run from the repository root with the shared container up on `http://127.0.0.1:3300`. If it is down, run `docker start sao-living_spacetimedb_1`, then poll `curl -s http://127.0.0.1:3300/v1/ping` until it answers. `run.py` and `drive.py` require the container to be up before launch.

```bash
R=client-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-client/scripts/run.py --run "$R"
cat ".local/living/verify/$R/results.md"
cat ".local/living/verify/$R/cleanup-proof.json"
```

`run.py` builds the probe, calls the shared harness for launch, doctor, and `player join ClientPrimary`, drives every mapped feature, then calls shared cleanup even after a failure. It refuses an existing run directory and a stopped shared container. It never restarts the container. The harness confirms SQL returns HTTP 404 after deletion. The wrapper records that cleanup result, token removal, the shared container's status and whether `.local/living/token` changed. It uses the harness's container and HTTP helpers.

The probe is outside the `living/` workspace. Build it separately with:

```bash
CARGO_TARGET_DIR="$PWD/.local/living/verify/target-client" cargo build --locked --manifest-path .agents/skills/verify-client/scripts/probe/Cargo.toml
```

To drive a database you already launched through the shared harness:

```bash
V=.agents/skills/verify/scripts/verify.py
R=client-manual-$(date +%Y%m%d-%H%M%S)
$V launch --run "$R"
$V doctor --run "$R"
$V player --run "$R" join ClientPrimary
.agents/skills/verify-client/scripts/drive.py --run "$R"
$V cleanup --run "$R"
```

Run cleanup after a failed manual attempt too. The automatic recipe is preferred because it keeps cleanup and proof together.

## Check one query during triage

Build the probe with the command above. On a scratch run launched and checked through the harness, subscribe anonymously to the row missing from the UI:

```bash
.agents/skills/verify-client/scripts/drive.py --run "$R" \
  --query "SELECT * FROM chronicle WHERE kind = 'speech'" \
  --seconds 10 --save speech-anonymous
```

While that command runs, use a second terminal with the same run name:

```bash
V=.agents/skills/verify/scripts/verify.py
$V player --run "$R" join ClientTriage
$V player --run "$R" say VERIFY_CLIENT_TRIAGE_SPEECH
```

Join only if this run has no player yet. Wait for the probe's `initial` line before speaking. It prints the initial received rows, then each live `insert`, `update` and `delete`, and saves the same JSON lines to `speech-anonymous.jsonl` in the run directory. A matching live chronicle insert establishes that the client received the speech. If the UI omits that row, continue triage at the future UI skill (not built; see `verify`).

Add `--as-player` to subscribe with the harness player's identity after joining. The default identity is anonymous. `--seconds` defaults to 10 and accepts 0 through 300. `--save` is an optional fresh basename containing letters, digits or hyphens; without it the driver picks a unique name. Existing evidence is never overwritten. SDK stderr goes to `<basename>-sdk.log`. Refused queries and broken connections exit 1 and retain the error. An applied query with no matching rows succeeds and records empty `tables`.

`drive.py` hides the probe's stdin request format. It passes URI, scratch database, identity token, SQL and duration in memory. No CLI token is needed. This mode uses one subscription, not the fixed suite's base query set. It supports tables and views present in the generated bindings. A keyless view reports changes as inserts and deletes. Rows leaving a query filter are client-cache deletes, even if the authority retained them.

## Checks and evidence

[features/README.md](features/README.md) indexes every check. [references/validation.md](references/validation.md) records the real runs.

The driver compares its copied base queries against `living/viewer/src/net.rs` and checks the private-table and reducer inventories against the authority source. A changed inventory stops the run so the map cannot silently omit a new permission path.

Every subscription uses `living/bindings` over WebSocket. The probe waits for `on_applied`, reads the client cache, counts live `body` and `stats` updates, and records exact subscription errors. Reducer calls use the HTTP call API with the same client identities. Admin SQL never proves client visibility or permission.

Evidence stays in `.local/living/verify/<run>/`. It includes `source-inventory.json`, `anonymous-base.json`, `inspected-character.json`, `visibility.json`, `privacy-*.json`, `view-*.json`, `reducers.json`, `reducers.md`, `reducer-effects.json`, `reconnect.json`, `adhoc-suite.jsonl`, `results.md`, and `cleanup-proof.json`. The probe snapshots the rows it actually receives. These can include every character's perceptions under the known privacy issue. Keep evidence local.

`PASS` means the assertion held. `FAIL` means a required behavior or fixture failed. `XFAIL` means the known privacy defect in [LIVING_HANDOFF.md, Still open](../../../docs/LIVING_HANDOFF.md) is still observable. `XPASS` means the privacy assertion now holds. The driver exits 1 for `FAIL` or `XPASS`, so a privacy fix triggers review of the expected-fail check and the viewer query set. A transport error or an empty fixture is a failure, never a known-issue success. The driver checks privacy access before the base set too, so a new refusal records `XPASS` even when the viewer still includes that now-private table.

Tokens stay in process memory except the shared harness's primary player token in `state.json`. The anonymous connection transfers its issued token through an inherited pipe so later HTTP calls use that same identity. The second player's token comes from `POST /v1/identity`. The admin SDK connection uses the shared harness's `admin_token()` helper. Admin scene setup uses `verify.py call --as-admin`. No token is printed or saved into evidence. Cleanup removes the primary token and a credential scan checks the evidence.

## Documentation and pinned versions

Consulted on 2026-10-04, before probe design:

- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/). Rechecked for this fix round. Initial rows are ready in `on_applied`; row callbacks prove later changes. The probe copies the viewer's SQL because the task verifies its actual query set. It keeps inspector queries separate from the base subscription.
- [Views](https://spacetimedb.com/docs/functions/views/). `ViewContext.sender()` selects per-identity rows. Subscribe to `my_deliberations` using each real identity. An empty player view alone cannot prove filtering, so the driver samples the foreign views between two positive admin observations.
- [Rust client SDK](https://spacetimedb.com/docs/clients/rust/). Generated bindings provide the connection and cache. `frame_tick` must run to process callbacks. Omitting a token creates an anonymous identity; the supplied token restores an identity on a later connection.
- [HTTP database API](https://spacetimedb.com/docs/http/database/). Calls accept a JSON argument array and carry the caller identity. SQL without authorization sees public tables. Use HTTP only for reducer results and anonymous query refusals; subscription evidence comes from WebSocket.
- [HTTP identity API](https://spacetimedb.com/docs/http/identity/). `POST /v1/identity` returns a new identity and token. The driver never reuses the admin identity as a player.

`living/Cargo.toml`, `living/Cargo.lock`, and `living/bindings/Cargo.toml` pin SDK 2.10.1. The shared doctor verifies server image `v2.10.1`. The standalone lockfile pins the same SDK. Generated bindings already contain `my_deliberations`; they are imported without regeneration or edits.

The general docs show version 2.0.0 and the HTTP page lists v1 WebSocket subprotocols. The released SDK's `.cargo_vcs_info.json` points to official commit `3d7607082ab47257adeb7c25164536511237f2b5`. Its [table callback source](https://github.com/clockworklabs/SpacetimeDB/blob/3d7607082ab47257adeb7c25164536511237f2b5/sdks/rust/src/table.rs) verifies insert/delete callbacks and primary-key updates used by query mode. Its [WebSocket source](https://github.com/clockworklabs/SpacetimeDB/blob/3d7607082ab47257adeb7c25164536511237f2b5/sdks/rust/src/websocket.rs), [connection source](https://github.com/clockworklabs/SpacetimeDB/blob/3d7607082ab47257adeb7c25164536511237f2b5/sdks/rust/src/db_connection.rs), and [subscription source](https://github.com/clockworklabs/SpacetimeDB/blob/3d7607082ab47257adeb7c25164536511237f2b5/sdks/rust/src/subscription.rs) verify the pinned APIs. The SDK uses `ws::v2::BIN_PROTOCOL`. The probe delegates negotiation and decoding to SDK 2.10.1 rather than hand-writing the older documented wire format. Both `tick` and `housekeeping` return HTTP `404 No such procedure` to external callers on this version; their internal scheduled-only guards are not reached through that API.

## Access patterns and limits

The observer's base set has 27 full public-table subscriptions. It retains those matching rows in its local cache and receives `body` updates on steering changes and `stats` updates from housekeeping. Inspector queries use the `experience.observer` and `routine.actor` btree indexes and join `routine_stat.id` to `routine.id`. The view uses `deliberation.controller`. Each private-table check gets its own short-lived connection, so a refusal cannot mask another table.

Ad-hoc mode reads and retains only the requested subscription's cache. `chronicle.kind` has no index, so the speech filter scans chronicle at subscription time. Later matching rows arrive incrementally for that connection. JSONL evidence grows with matching changes over the chosen duration. It is a bounded diagnostic, with no retention or performance claim.

The privacy check deliberately subscribes to all `experience` rows to expose access across controllers. It also receives `thought.detail` containing scripted marker text, without contacting a model. This is diagnostic coverage of current access, not a recommended client query or a model-behavior test.

Reducer fixtures touch three joined player characters. Each attempts every admin reducer, each `mind_*` reducer on an AI character, another player, and itself, both scheduled reducers, and every player reducer. Safe admin arguments request zero spawned actors and zero granted items so an unexpected authorization success cannot create a large workload. An authorized admin `set_behavior` call creates a view fixture on one AI character. The authority's tick creates the actual deliberation row. The probe waits up to 55 seconds for that actor because a `think` node has a 45-second settling gate after spawn at `brain.rs:424`. It stops as soon as the client receives the row.

The reconnect proxy forwards bytes without logging them, drops only its own client socket pair, and leaves the server running. The probe waits three seconds, rebuilds its connection, and resubscribes to the base and inspector queries. The anonymous reconnect gets a new identity as the viewer does. This proves the SDK recovery recipe. The Bevy viewer's own `Net::pump` state and rendering belong to the future UI skill (not built; see `verify`).

## What this skill does not prove

- Gameplay or mechanics correctness beyond these client observations. Use `verify-core` and `verify-player`.
- World generation. Use `verify-generation`.
- The mind service, authentic model replies, or personal knowledge. Use `verify-minds`, `verify-llm`, and `verify-knowledge`.
- Browser controls, visual state, or the public observer tunnel. Use the future UI skill (not built; see `verify`).
- Population, latency, memory, retention, or long-run performance acceptance. Follow the performance contract and `AGENTS.md`.

Use `maintain-verification-skill` when these tables, queries, views, or reducers change.
