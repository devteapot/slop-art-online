# Bevy browser simulation client

The foundation now runs in the existing Rust Bevy client compiled to WASM. Open [the local game client](http://127.0.0.1:18891). Rendering, world selection, panels and human input are Bevy systems; the HTML page contains only the canvas and loading message. SpacetimeDB owns simulation time, policies, perceptions and skill effects. This is a bounded development client for the current one-dimensional survival world, not a migration of legacy voxel/combat gameplay.

Current `m1-5` host details are in [Participant agents](PARTICIPANT_AGENTS.md). Its default is port 18891 and output `output/participant-agent-dev`; the m1-4 host on 18890 and verification below remain historical evidence. The current built-in harness has replaced the older host Reasoner dispatch.

Current presentation: [world observer and parallel sessions](WORLD_OBSERVER.md). The top-down 2D world is the primary surface; diagnostics can be overlaid or detached, and each view can focus a different hosted run. The older screenshots and verification below are historical; current flat tile/sprite verification is in the world observer guide. **New parallel session** now retains earlier clocks and harnesses; it does not replace or pause the old run.

## Run it

Versions: Rust stable (verified with **1.97.1**), Bevy **0.18.1**, SpacetimeDB module/server/SDK/bindings **2.1.0**, control CLI **2.7.1**, Trunk **0.21.14**. The lockfile includes `ethnum` **1.5.3**, which fixes the older dependency's build failure with Rust 1.97. Browser support first shipped in the released Rust SDK 2.1.0 ([release notes](https://github.com/clockworklabs/SpacetimeDB/releases/tag/v2.1.0)).

Run the database in Docker or rootless Podman with a Compose provider. The browser stack uses Compose project `sao-bevy`, port **3101**, and its own named volume `sao-bevy_spacetimedb-home`. The legacy `just dev` stack stays on port 3000 with a separate volume. Rust builds, Trunk and the browser host run on the host machine.

From the repository root:

```sh
rustup target add wasm32-unknown-unknown
spacetime version install 2.1.0 -y
spacetime version install 2.7.1 -y
# Install Trunk if absent: cargo install trunk --version 0.21.14 --locked
# Install just if absent: cargo install just --locked
# If Podman lacks a Compose provider: uv tool install podman-compose

# Select installed CLI binaries explicitly; no global version switch is needed.
export SPACETIME_CLI="$HOME/.local/share/spacetime/bin/2.1.0/spacetimedb-cli"
export SPACETIME_CONTROL_CLI="$HOME/.local/share/spacetime/bin/2.7.1/spacetimedb-cli"
export SPACETIME_CONFIG_PATH="$PWD/.local/credentials/bevy-cli.toml"

# Start the container and wait for database readiness.
just bevy-db-up                     # Docker
# Or: just runtime=podman bevy-db-up
just bevy-db-login                  # Once for this database volume.

# Build authority and browser client; checked-in bindings already match.
cargo build --locked -p server_module --target wasm32-unknown-unknown
cargo build --locked -p bridge --bin sao-dev-client --bin sao-agent-mcp
just bevy-web-build

# Leave running in a terminal; fixture mode creates no provider requests.
just bevy-dev
```

Open **http://127.0.0.1:18891** after the host prints `Bevy game client`. Use this exact address: the enrollment API checks the browser's Origin. The run starts paused; **Step** advances once and **Resume** starts the clock. **Participate as You** enables human controls. Default startup installs an authored fixture for Mira; Tovan awaits an external runtime. See [Participant agents](PARTICIPANT_AGENTS.md) for optional model configuration.

The host uses the 2.1.0 CLI for publishing and the **2.7.1 control CLI** for SQL and reducer calls. The latter supports JSON SQL output and string identity arguments; 2.1.0 did not support those control forms in the original verification. The exports above select both explicitly (adjust the install paths if needed). The host binds to `127.0.0.1` by default; `BEVY_DEV_BIND` changes the bind address and `BEVY_DEV_PORT` changes its port. Each host startup creates a new isolated database and bounded run without deleting an old one.

`bevy-db-login` saves a server-issued operator identity in `.local/credentials/bevy-cli.toml` with private file permissions, separate from your global CLI login. `just bevy-dev` selects that file automatically; the `SPACETIME_CONFIG_PATH` export also selects it when running `cargo run` directly. Keep it between restarts so you retain ownership of existing databases. A login issued by another server or a previous standalone instance is not valid for the new container: this can appear as `InvalidSignature`, HTTP 401 or a broken pipe while publishing. Use this project's login command after creating a new database volume, rather than replacing your global CLI login.

Use the same runtime for subsequent container commands:

```sh
just runtime=podman bevy-db-status
just runtime=podman bevy-db-logs # Follows logs; Ctrl-C returns to the shell.
curl --fail http://127.0.0.1:3101/v1/ping
python3 scripts/check_bevy_host.py

# Stop the browser host with Ctrl-C, then stop/remove its database container.
just runtime=podman bevy-db-down
```

Omit `runtime=podman` for Docker. `bevy-db-down` preserves the named volume; the next `bevy-db-up` reuses its data. Local evidence remains under `output/participant-agent-dev`, and private participant sessions remain under `.local/credentials`. Existing standalone database directories are not imported or deleted. If port 3101 is occupied by an older standalone server, stop that process before starting the container.

Without `just`, the database start commands are:

```sh
SPACETIMEDB_PORT=3101 podman compose -f deploy/docker-compose.yml -p sao-bevy up -d spacetimedb
SPACETIMEDB_PORT=3101 podman compose -f deploy/docker-compose.yml -p sao-bevy exec -T spacetimedb sh -s < deploy/wait-for-spacetimedb.sh
```

Then create the scoped login (first time only) and launch with the exports above:

```sh
umask 077
mkdir -p .local/credentials
"$SPACETIME_CLI" --config-path "$SPACETIME_CONFIG_PATH" login --server-issued-login http://127.0.0.1:3101
# After the builds above:
env -u NPC_REASONING_CONFIG cargo run -p bridge --bin sao-dev-client
```

For optional native presentation, with the same host running:

```sh
cargo run -p client --no-default-features --features foundation
```

The same `client/src/foundation` Rust systems are used on native and WASM targets. The foundation is now the default native client; the previous voxel/3D mode has been removed. Native window interaction was not tested in this slice. Development and optimized browser builds use the same rendering/input code; build with Trunk `--release` for optimization. The shipped local build uses `wasm-dev` (optimization 1, no debug info), about 69 MB before transport compression. `cargo run -p client` now opens the 2D behavior lab against the same development host.

## Share on a trusted local network

After the initial login and builds above, stop the existing browser host with Ctrl-C and run:

```sh
just runtime=podman bevy-lan 192.168.1.117
```

Replace `192.168.1.117` with this machine's LAN address (`ip -brief -4 address` on Linux); omit `runtime=podman` for Docker. This command recreates the database container's port mapping using the existing volume and starts the browser host. Both listen on `0.0.0.0`: TCP **18891** serves the application and TCP **3101** serves the database and WebSocket connection. Other devices open **http://192.168.1.117:18891**, not `0.0.0.0`. Local access through `http://127.0.0.1:18891` continues to work.

The equivalent environment settings are:

```sh
SPACETIMEDB_BIND_ADDR=0.0.0.0 just runtime=podman bevy-db-up
BEVY_DEV_BIND=0.0.0.0 BEVY_DEV_PUBLIC_URL=http://192.168.1.117:18891 just bevy-dev
```

`BEVY_DEV_PUBLIC_URL` is the exact HTTP origin accepted for LAN enrollment. The host derives the browser's database URL from its hostname, using port 3101. Operator calls and built-in agents still connect through loopback. Origin checks accept only the configured public URL and the loopback URL with the required client header; they do not trust arbitrary Host or Origin values. Restart with the updated public URL if the machine's IP changes. The developer broker lets anyone who can reach it become an observer or the single human participant, so this mode is for a trusted LAN.

On a host with a firewall, allow both TCP ports from the local subnet. For this Fedora host (zone `FedoraServer`, subnet `192.168.1.0/24`), an administrator can run:

```sh
sudo firewall-cmd --zone=FedoraServer \
  --add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" port port="18891" protocol="tcp" accept' \
  --add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" port port="3101" protocol="tcp" accept'
```

These runtime rules last until firewall reload or reboot. Repeat the command with `--permanent` to save just these rules for future reloads. Adjust the zone/subnet to the actual network. This setup does not configure router port forwarding.

Verify the advertised address and enrollment checks:

```sh
BEVY_DEV_URL=http://192.168.1.117:18891 BEVY_DEV_EXPECTED_DB_URL=http://192.168.1.117:3101 python3 scripts/check_bevy_host.py
curl --fail http://192.168.1.117:3101/v1/ping
```

To return to loopback-only access, stop the browser host and run `just runtime=podman bevy-db-up` and `just bevy-dev` without the LAN environment overrides.

LAN configuration was verified on 2026-09-05: both listeners bound to all interfaces, the database retained its named volume, and Chromium on the host connected through `192.168.1.117`, advanced tick 1 → 2 and reloaded successfully without browser errors. Enrollment checks passed for both LAN and loopback URLs, including their distinct advertised database addresses; three host tests cover address validation and exact-origin enforcement. Screenshots are under `output/local-dev/browser-lan*.png`. Access from a separate device still requires confirmation; this session could not change Fedora's firewall without administrator authentication.

## Container startup verification, 2026-09-05

Verified on Linux with rootless Podman **5.8.4**, podman-compose **1.6.0**, Rust **1.97.1**, and the versions above. `just runtime=podman bevy-db-up` passed readiness; the container was healthy on `127.0.0.1:3101` with `sao-bevy_spacetimedb-home` mounted at `/home/spacetime`. Publishing and control calls succeeded using the scoped operator login. The module, bridge and Trunk builds passed, along with **66** simulation/bridge tests and `scripts/check_bevy_host.py`.

Chromium rendered the client using WebGL 2 with SwiftShader in the headless verification environment. No browser errors occurred; software-renderer and unsupported optional GPU feature notices were expected. Actual UI interactions advanced tick 1 → 2, switched into participant mode, queued human movement, returned to observer and stepped to tick 3, where You moved from position 0 → 1. The run was left paused. Screenshots are retained locally under `output/local-dev/browser-*.png`; these are not committed artifacts. The older verification below describes the preceding implementation environment.

## Use the game

- Start in **observer**, paused at tick 1. Select Mira, Tovan or You in the roster/world. Mind shows motive, resources, personality and fallible beliefs; Policy shows the actual installed tree, execution path, branch and sequence cursors. Page through nodes; scroll either side panel for longer content.
- **History** selects stable event IDs. Parent buttons follow perception → speech → skill attempt → decision. The browser projection retains the latest 180 observer events; full records remain in the database and exported snapshot. Older parents outside that window require the operator archive. Displayed JSON details are capped at 650 characters.
- **Step** advances one authoritative tick while paused. **Resume/Pause** changes the server scheduler, which advances every 2.5 seconds independently of browser frames and model latency. Runs stop at 300 ticks or their normal simulation stop condition.
- **Participate as You** changes the server grant. Only the owned human's current state, memories and currently seen characters are supplied. Click a field cell or use left/right arrows for movement; Gather, Eat and Rest use shared skills. Press Enter or Speak, type chosen words, then Enter to submit. Escape closes entry. Physical keyboard text is supported; clipboard insertion and complex IME composition are not yet implemented. Speech is bounded to 1,000 UTF-8 bytes in this UI.
- While paused, submit a human intent, return to observer and Step to see its effect. To participate continuously, Resume first. The role switch does not change the character's controller or bypass skill requirements.
- **New parallel session** creates a new paused bounded run while earlier runs retain their clocks and harnesses. It preserves old data and exports. **Recorded model policy** opens the preserved Qwen run, labeled **archive / actual model output / read-only**. It has no time or participant controls. The generated policy's unguarded move branch failed to adapt and Mira died; this is evidence of that outcome, not a successful adaptive model demonstration.
- **Reconnect** and browser reload enroll a fresh anonymous SDK identity into the existing development session, revoke the previous grant, and restore the current run/role. No provider or operator credentials are supplied to the browser.

## Authority and access boundary

`sim_run`, `sim_audit`, `sim_client_access` and the clock table stay private. `sim_my_snapshot` is a caller-specific SpacetimeDB view. Its server-side projection supplies observer truth only when that caller has an observer grant. Participant payloads do not contain other minds, hidden hazards, global audit events or pending model context. Removing a grant removes the subscribed row. UI hiding is not the access control.

`sim_client_intent` derives the actor from the caller's grant. In participant mode it sends finite human actions through shared skill validation, queues speech independently, and routes policies through the versioned participant command path. It has no caller-selected actor parameter. Ownership is exclusive among participant grants. `sim_client_control` requires observer access; grant, revoke and operator stepping require run ownership; creation establishes a separate owned run, and participant-mode runs reject raw model results. No simulation stepping or skill effect implementation exists in the browser.

The enrollment broker is a **local developer tool**, not a public account/role service. A user with access to this application, over loopback or an explicitly enabled trusted LAN, may intentionally become an observer or participant. A random HttpOnly, SameSite=Strict session cookie, exact Origin check and custom request header protect its POST routes from unrelated webpages. The broker uses local CLI operator credentials internally. The SDK connects without a reused token; its returned token is ignored, so no authentication credential is placed in the WebSocket URL. Role isolation is enforced by the module after enrollment, but this broker must not be publicly exposed as production authentication. Production deployment needs an explicit authenticated role provisioning service. A developer who has already viewed observer truth cannot be made to forget it by switching roles.

## Reasoning and evidence

The preceding m1-4 host installed the explicitly authored `scenarios/reactive-client-fixture.json` through the actual result reducer. Both the audit metadata and in-game banner identify it as a fixture. No model calls were made for this client work. Bootstrap and generated policies are not relabeled as successful intelligence.

The preceding m1-4 host used an explicitly supplied `NPC_REASONING_CONFIG` to select the async `Reasoner`, with its provider settings, journals, expiry and cancellation. Calls run in server tasks while the authoritative scheduled reducer keeps ticking. Invalid output passes through existing validation and is never repaired into an authored policy. This optional host path was compiled; no fresh provider run was performed for it. The preceding completed Luna transport check and policy rejection remain separately documented in [streaming verification](CARLID_STREAMING_VERIFICATION.md).

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

Historical scope of the preceding verification: desktop-sized browser UI, procedural 2D presentation of the actual 1D core, one owned human, local developer enrollment, bounded in-game history, no production deployment, and no successful newly generated adaptive policy claim. Richer scene art, full accessibility/IME, public authentication, multi-human provisioning, and legacy game migration remain follow-up work.
