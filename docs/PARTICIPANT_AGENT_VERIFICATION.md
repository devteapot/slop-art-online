# Participant runtime verification — 2026-09-05

Implementation rules: `m1-5`, contract `sao-participant-v1`, official MCP Rust SDK 3.2.0. See [the runbook](PARTICIPANT_AGENTS.md) for reproducible commands and protocol sources.

## Executed checks

- `cargo test -p simulation -p bridge`: **64 passed** — 35 simulation/projection tests, 28 provider/streaming tests and one old-archive compatibility test. Log: `output/participant-regression-final.log`.
- Authority WASM build, bridge/MCP/probe build, Trunk `dist-participant` build, native foundation check and default legacy client check passed. Logs: `output/participant-{module,bridge,wasm,native,legacy}-final.log`. Existing module warnings and an unused macro-router field warning remain; no build errors.
- `target/debug/examples/participant_authority_probe`: passed against final module in database `sim-bevy-db-1788599743338`. Separate proof run: `sim-participant-proof-1788599763548`. Report: `output/participant-agent-dev/sim-participant-proof-1788599763548/verification.json`, adjacent MCP setup/inspect results and harness journals. Log: `output/participant-authority-probe-final.log`.
- Actual MCP `server/discover`, `tools/list` and `tools/call`, including observation, replacement, stale patch rejection, idempotent speech retry and independent reflection. Protocol 2026-07-28. Same session reconnect restored scope. Three real SDK identities exercised ungranted access, private-table denial, exclusive ownership and participant time-control denial. Legacy owner intent/model-result bypasses rejected participant runs. Foreign reflection sources rejected and revoked views removed.
- The built-in harness made **one local mocked-provider learning call** deliberately delayed while the real authority advanced three ticks. Both internal and MCP external characters moved to position 3; the harness's eventual reflection preserved its movement attempt and policy revision. Equivalent speech was perceived; equivalent learning changed the intended individual only. No fresh real-model inference occurred.
- `python3 scripts/check_bevy_host.py` passed against the new default port 18891: missing/cross-origin requests and unauthenticated binding denied; scoped cookie enrollment works. `BEVY_DEV_URL` can select the preserved old host.

## Real browser human participation

In-app browser tab 10 loaded the actual Bevy WASM canvas on 18891. Run `sim-bevy-1788599746344` starts paused in explicit fixture mode. Participating as You changed the view to the owned individual's perceptions. Clicking land cell 4 installed finite movement decision #37; keyboard input submitted `Walking and talking` independently (#38). Returning to observer preserved both choices.

At tick 2, movement attempt #56 advanced to position 1 and speech #62 was delivered from that actual position, with listener perceptions #63 and #64. At tick 3, progress #81 continued the **same movement attempt** to position 2. Environmental damage then correctly interrupted it (#87); speech did not interrupt it. The run remains paused at tick 3. Full evidence: `output/participant-agent-dev/browser-verification.json` and that run's `snapshot.json`.

Both 18890 and 18891 returned HTTP 200 after these checks. The old host/bundle, original databases, Qwen archive and Luna transport/rejection evidence were retained. No proxy restart or modification, commit, push or merge was performed for this iteration.

## What this establishes

These checks establish a runnable shared participant boundary, real MCP transport, scoped authority access, asynchronous harness integration and preserved human Bevy participation. They do not establish fresh successful model-generated adaptive behavior, all-client MCP compatibility, production authentication, or persistent autonomous external scheduling. The external client supplies its full runtime and decides when to call tools. Receipt idempotency and subjective history are bounded as documented in the runbook.
