# Bevy browser simulation client

The foundation now runs in the existing Rust Bevy client compiled to WASM. Open [the local game client](http://127.0.0.1:18890). Rendering, world selection, panels and human input are Bevy systems; the HTML page contains only the canvas and loading message. SpacetimeDB owns simulation time, policies, perceptions and skill effects. This is a bounded development client for the current one-dimensional survival world, not a migration of legacy voxel/combat gameplay.

## Run it

Versions: Bevy **0.18.1**, SpacetimeDB module/server/SDK/bindings **2.1.0**, Trunk **0.21.14**. Browser support first shipped in the released Rust SDK 2.1.0 ([release notes](https://github.com/clockworklabs/SpacetimeDB/releases/tag/v2.1.0)). The upgrade is limited to that requirement. The existing 2.0.1 server/data on port 3100 was retained; the new server uses port 3101 and separate storage. No global CLI default was changed.

From the repository root:

```sh
rustup target add wasm32-unknown-unknown
spacetime version install 2.1.0 -y
# Install Trunk if absent: cargo install trunk --version 0.21.14 --locked

# Separate terminal; retain this data directory between restarts.
~/.local/share/spacetime/bin/2.1.0/spacetimedb-cli start \
  --listen-addr 127.0.0.1:3101 --data-dir /tmp/sao-bevy-browser-2-1-b0b2

# Build authority, matching bindings and browser client.
cargo build -p server_module --target wasm32-unknown-unknown
~/.local/share/spacetime/bin/2.1.0/spacetimedb-cli generate --lang rust \
  --out-dir shared/src/module_bindings \
  --bin-path target/wasm32-unknown-unknown/debug/server_module.wasm --no-config -y
just bevy-web-build

# Separate terminal; explicit fixture mode creates no model requests to providers.
env -u NPC_REASONING_CONFIG cargo run -p bridge --bin sao-dev-client
```

The host uses the 2.1.0 CLI for publishing and the installed **2.7.1 control CLI** for SQL and reducer calls. The latter supports JSON SQL output and string identity arguments; 2.1.0 did not support those control forms in this test. Override paths with `SPACETIME_CLI` (publish) and `SPACETIME_CONTROL_CLI` (SQL/call). The host binds only to `127.0.0.1`; `BEVY_DEV_PORT` changes its port. Each host startup creates a new isolated database and bounded run without deleting an old one.

For optional native presentation, with the same host running:

```sh
cargo run -p client --no-default-features --features foundation
```

The same `client/src/foundation` Rust systems are used on native and WASM targets. Native foundation and preserved default legacy modes compile; native window interaction was not tested in this slice. Development and optimized browser builds use the same rendering/input code; build with Trunk `--release` for optimization. The shipped local build uses `wasm-dev` (optimization 1, no debug info), about 69 MB before transport compression. The default legacy entry point remains available through `cargo run -p client`.

## Use the game

- Start in **observer**, paused at tick 1. Select Mira, Tovan or You in the roster/world. Mind shows motive, resources, personality and fallible beliefs; Policy shows the actual installed tree, execution path, branch and sequence cursors. Page through nodes; scroll either side panel for longer content.
- **History** selects stable event IDs. Parent buttons follow perception → speech → skill attempt → decision. The browser projection retains the latest 180 observer events; full records remain in the database and exported snapshot. Older parents outside that window require the operator archive. Displayed JSON details are capped at 650 characters.
- **Step** advances one authoritative tick while paused. **Resume/Pause** changes the server scheduler, which advances every 2.5 seconds independently of browser frames and model latency. Runs stop at 300 ticks or their normal simulation stop condition.
- **Participate as You** changes the server grant. Only the owned human's current state, memories and currently seen characters are supplied. Click a field cell or use left/right arrows for movement; Gather, Eat and Rest use shared skills. Press Enter or Speak, type chosen words, then Enter to submit. Escape closes entry. Physical keyboard text is supported; clipboard insertion and complex IME composition are not yet implemented. Speech is bounded to 1,000 UTF-8 bytes in this UI.
- While paused, submit a human intent, return to observer and Step to see its effect. To participate continuously, Resume first. The role switch does not change the character's controller or bypass skill requirements.
- **Fresh fixture run** pauses the old run and creates a new bounded run. It preserves old data and exports. **Recorded model policy** opens the preserved Qwen run, labeled **archive / actual model output / read-only**. It has no time or participant controls. The generated policy's unguarded move branch failed to adapt and Mira died; this is evidence of that outcome, not a successful adaptive model demonstration.
- **Reconnect** and browser reload enroll a fresh anonymous SDK identity into the existing development session, revoke the previous grant, and restore the current run/role. No provider or operator credentials are supplied to the browser.

## Authority and access boundary

`sim_run`, `sim_audit`, `sim_client_access` and the clock table stay private. `sim_my_snapshot` is a caller-specific SpacetimeDB view. Its server-side projection supplies observer truth only when that caller has an observer grant. Participant payloads do not contain other minds, hidden hazards, global audit events or pending model context. Removing a grant removes the subscribed row. UI hiding is not the access control.

`sim_client_intent` derives the actor from the caller's grant, checks human ownership, and enters the existing `World.submit` path. It has no caller-selected actor parameter. Ownership is exclusive among participant grants. `sim_client_control` requires observer access; create, grant, revoke, raw model results and operator stepping remain owner-only. No simulation stepping or skill effect implementation exists in the browser.

The enrollment broker is a **local developer tool**, not a public account/role service. A user with access to this loopback application may intentionally become an observer or participant. A random HttpOnly, SameSite=Strict session cookie, exact Origin check and custom request header protect its POST routes from unrelated webpages. The broker uses local CLI operator credentials internally. The SDK connects without a reused token; its returned token is ignored, so no authentication credential is placed in the WebSocket URL. Role isolation is enforced by the module after enrollment, but this broker must not be publicly exposed as production authentication. Production deployment needs an explicit authenticated role provisioning service. A developer who has already viewed observer truth cannot be made to forget it by switching roles.

## Reasoning and evidence

Default mode installs the explicitly authored `scenarios/reactive-client-fixture.json` through the actual result reducer. Both the audit metadata and in-game banner identify it as a fixture. No model calls were made for this client work. Bootstrap and generated policies are not relabeled as successful intelligence.

An explicitly supplied `NPC_REASONING_CONFIG` selects the existing async `Reasoner`, with its provider settings, journals, expiry and cancellation. Calls run in server tasks while the authoritative scheduled reducer keeps ticking. Invalid output passes through existing validation and is never repaired into an authored policy. This optional host path was compiled; no fresh provider run was performed for it. The preceding completed Luna transport check and policy rejection remain separately documented in [streaming verification](CARLID_STREAMING_VERIFICATION.md).

`output/bevy-browser-dev/active.json` identifies the current database/run/URL. Each new run retains its resolved scenario, fixture when used, Cargo.lock, module WASM, mode label, full snapshot and optional reasoning journals. Reproduction means restoring the matching authority/input history; fresh stochastic inference is not claimed deterministic. Earlier experiment directories were left unchanged.

## Verification, 2026-09-05

- `cargo test -p simulation -p bridge`: **55 passed** (26 core/projection, 28 provider/streaming, one archive compatibility).
- Module WASM build, Trunk browser build, native foundation check, and preserved default legacy client check passed.
- `cargo run -p bridge --example bevy_access_probe`: three real SDK identities verified ungranted/private-table denial, owner-only grants, exclusive human ownership, participant time-control denial, no other-actor input, participant data filtering, actual shared movement/speech and view removal on revocation. Report: `output/bevy-browser-dev/access-verification.json`.
- `python3 scripts/check_bevy_host.py`: missing/cross-origin requests denied, unauthenticated bind denied, scoped session cookie and public descriptor checked.
- Browser GPU verified in the in-app Chromium browser: Bevy reports **ANGLE Metal / Apple M4 Pro**, backend **Gl / WebGL 2.0**. WebGPU is an optional compile feature, not the tested backend. WebGL capability notices disable unused OIT/depth-of-field and GPU preprocessing; rendering continues. Bevy's documented browser rendering options are covered by its [WASM examples](https://github.com/bevyengine/bevy/blob/v0.18.1/examples/README.md#wasm).
- Real browser UI: observer selection/tree, authoritative Step, participant data boundary, human move from 0 to 1 at tick 3, and typed `Avoid the clearing` at tick 4. Speech event #142 linked skill #141; Mira perception #143 and Tovan #144 linked the same speech. These IDs belong to preserved run `sim-bevy-1788593422693`.
- Browser reload and Reconnect restored the same run. Resume advanced the server from tick 1 to tick 8, Pause held it, and Fresh fixture run created `sim-bevy-1788594073308` at tick 1 while preserving the previous paused run. Final-load console had no errors; the WebGL capability notices above remain. Summary: `output/bevy-browser-dev/browser-verification.json`.
- Browser testing exposed and fixed a mutex held across async SDK construction and the older CLI identity argument incompatibility. Those failed attempts were not treated as successful verification.

Known scope: desktop-sized browser UI, procedural 2D presentation of the actual 1D core, one owned human, local developer enrollment, bounded in-game history, no production deployment, and no successful newly generated adaptive policy claim. Richer scene art, full accessibility/IME, public authentication, multi-human provisioning, and legacy game migration remain follow-up work.
