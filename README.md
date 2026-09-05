# Slop Art Online

A Rust game about individuals who pursue goals, form imperfect beliefs, communicate, and become different through experience. We are building the **simulation foundation first**, then richer UI and gameplay around it. “Players” includes human-controlled and AI-controlled characters with shared capabilities and authoritative world rules.

Start with the [simulation vision and design](docs/SIMULATION_VISION.md). The next milestone is a small, inspectable survival simulation with free-form communication, evolving individuals, shared skills, permanent death, and scenario tooling. These are target capabilities, not claims that the current prototype already provides them.

## Architecture and current status

The existing Rust stack stays: **SpacetimeDB** owns world state and rules, **Bevy** is the supported game client, and the **Rust LLM bridge** supports reasoning above real-time behavior execution. Experiments should run the same authoritative core without the visual client.

```text
Bevy game client / M1 observer and scenario tools
    ↕ SpacetimeDB protocol
SpacetimeDB (authoritative state, reducers, NPC behavior execution)
    ↕ NpcPendingDecision subscription and submission reducers
Rust LLM bridge
    ↕ HTTP
Ollama (current backend; cloud integration remains an option)
```

M1 now has an executable survival foundation with shared skills, persistent behavior sequences, free-form model speech, subjective perception, individual change, permanent death, durable evidence, and isolated scenario runs. The default client is a top-down 2D behavior lab; the old voxel/3D client has been retired. The [browser-hosted Bevy game client](docs/BEVY_BROWSER_CLIENT.md) now provides in-game observer and owned human participant modes, using the same authoritative foundation. The external HTML inspector remains developer audit tooling. See the [M1 runbook](docs/M1_RUNBOOK.md) and [verification report](docs/M1_VERIFICATION.md) for exact scope and model limitations.

With the isolated local SpacetimeDB server and Ollama running:

```bash
just sim-build
just sim-run scenarios/survival.json output/my-run qwen2.5:7b 18877
# Later, reopen the retained evidence without advancing the simulation:
just sim-inspect output/my-run 18877
```

## Prerequisites

- [Rust](https://rustup.rs/) (stable toolchain)
- [SpacetimeDB CLI](https://spacetimedb.com/docs) (`spacetime`, version **2.1.0** to match the pinned Rust SDK and generated bindings)
- [Docker](https://docs.docker.com/get-docker/) with Compose, **or** [Podman](https://podman.io/) with a Compose provider (`docker-compose` or `podman-compose`)
- [just](https://github.com/casey/just) (command runner)
- [Ollama](https://ollama.com/) (optional — local LLM for the bridge; on macOS run natively, not in Docker)

WASM target for publishing the server module:

```bash
rustup target add wasm32-unknown-unknown
```

Use the matching CLI version before publishing or regenerating bindings:

```bash
spacetime version install 2.1.0
spacetime version use 2.1.0
```

NPC model backends are configurable per run: see [Ollama, OpenRouter, and compatible endpoint reasoning](docs/NPC_REASONING.md).

## Quick start

### Browser simulation (primary development interface)

Follow the [Bevy browser runbook](docs/BEVY_BROWSER_CLIENT.md) for first-time tool installation and explicit CLI paths. The current foundation uses a containerized database on port **3101** and the browser client on **18891**:

```bash
export SPACETIME_CLI="$HOME/.local/share/spacetime/bin/2.1.0/spacetimedb-cli"
export SPACETIME_CONTROL_CLI="$HOME/.local/share/spacetime/bin/2.7.1/spacetimedb-cli"
just bevy-db-up                      # or: just runtime=podman bevy-db-up
just bevy-db-login                   # first time; keeps the global CLI login separate
cargo build --locked -p server_module --target wasm32-unknown-unknown
just bevy-web-build
just bevy-dev
```

Open [127.0.0.1:18891](http://127.0.0.1:18891), then **Step** or **Resume**. Default startup uses an authored NPC fixture without model calls. `just bevy-db-down` stops the database while preserving its named volume; use the same `runtime=podman` override if you started with Podman. `bevy-db-status` and `bevy-db-logs` inspect this stack. The optional legacy server recipes still target port 3000; they are not the 2D client setup.

To share the browser simulation on your LAN, stop the browser host and run `just runtime=podman bevy-lan <your-lan-ip>` (omit the runtime override for Docker). This binds both services to `0.0.0.0` and advertises the LAN database address to browsers. Open `http://<your-lan-ip>:18891` from another device. See [LAN setup and firewall commands](docs/BEVY_BROWSER_CLIENT.md#share-on-a-trusted-local-network).

### Native 2D client

With the same development host running:

```bash
just client                 # cargo run -p client
# To use a different development host:
BEVY_DEV_URL=http://127.0.0.1:18892 cargo run -p client
```

The browser and native clients use the same flat tile/sprite presentation and authoritative rules. See [world controls and session inspection](docs/WORLD_OBSERVER.md). There is no voxel terrain, 3D physics or model asset pipeline in the client. A future 2.5D/3D interface can consume the same simulation boundary.

### Mechanics and model iteration

Use [headless scenarios](docs/M1_RUNBOOK.md) for repeatable mechanic checks and [participant runtimes](docs/PARTICIPANT_AGENTS.md) for model configuration. Rebuild the authoritative module when its Rust rules change, then restart the development host to create a fresh isolated run. Regenerate bindings only when changing public schema/reducer interfaces. The original bridge binary and `just dev` / `publish` recipes serve the retained legacy server prototype, not the current client harness.

### Useful commands

| Command | Description |
|---------|-------------|
| `cargo build` | Build all workspace crates |
| `cargo test` | Run all tests |
| `just client` | Run the native 2D behavior lab against the development host |
| `just dev` | Start/publish the legacy server prototype on port 3000 |
| `just up` / `just down` | Start the database / remove containers while retaining data |
| `just status` | Show container status and health |
| `just logs` | Tail SpacetimeDB logs |
| `just publish` | Publish the SpacetimeDB module |
| `just publish-reset` | Delete DB data and republish |
| `just generate` | Regenerate `shared` module bindings |
| `just call <reducer> [args...]` | Call a reducer against the local DB |

All container commands accept `runtime=podman`, e.g. `just runtime=podman down`.

### Storage and optional services

SpacetimeDB stores its data and local keys in the Compose-managed `spacetimedb-home` named volume. `just down` retains this volume, so stopping and starting the environment preserves the world. Avoid `compose down --volumes` unless you intend to erase it. The port is bound to loopback for local development.

The old `deploy/spacetimedb-data/` bind mount is no longer used and is left untouched. The new volume starts with a fresh database. Existing worlds are not automatically imported; retain that directory if you need the old state. Do not copy data from a newer SpacetimeDB server into the pinned 2.1.0 server.

Open WebUI and Ollama are optional and are not started by `just dev`. For Open WebUI with native Ollama on macOS (substitute `podman` for `docker` as needed):

```bash
docker compose -f deploy/docker-compose.yml --profile mac up -d open-webui
```

The existing NVIDIA GPU profile is available with Docker on Linux after configuring its NVIDIA container runtime:

```bash
OLLAMA_BASE_URL=http://ollama:11434 docker compose -f deploy/docker-compose.yml --profile gpu up -d
```

SpacetimeDB itself does not need a GPU or either optional profile.

## Project structure

| Path | Purpose |
|---|---|
| `server/module/spacetimedb/` | Authoritative Rust/WASM simulation, tables, reducers, NPC AI |
| `server/bridge/` | Rust service routing pending decisions to Ollama |
| `client/` | Bevy rendering, input, prediction, and game UI |
| `simulation/` | Shared authoritative M1 Rust rules invoked by SpacetimeDB |
| `shared/` | Generated SpacetimeDB Rust bindings |
| `deploy/` | Local service configuration |
| `docs/` | Canonical design, implementation gaps, roadmap, diagrams, historical ADRs |

## Local services

| Service | Port | Notes |
|---------|------|--------|
| SpacetimeDB | 3000 | Game DB + logic |
| Open WebUI | 8080 | Model management UI (mac/gpu profiles) |
| Ollama | 11434 | Local LLM; native on macOS, container on `gpu` profile |
| LLM bridge | — | Connects to SpacetimeDB + Ollama |

## Documentation

| Document | Purpose |
|---|---|
| [World vision](docs/WORLD_VISION.md) | Agreed living-world design, faction seed, population, knowledge and open decisions |
| [World development roadmap](docs/WORLD_ROADMAP.md) | Evidence stages from a viable settlement to societies, invention and AGI |
| [Simulation vision](docs/SIMULATION_VISION.md) | Authoritative direction, vocabulary, architecture boundaries, open questions |
| [Audit and experiments](docs/AUDIT_AND_EXPERIMENTS.md) | Common evidence, live/historical inspection, isolated runs, replay limits, acceptance checks |
| [Current state](docs/CURRENT_STATE.md) | Static implementation assessment and foundation gaps |
| [Roadmap](docs/TODO.md) | First milestone, dependencies, later stages, technical debt |
| [Stack reference](STACK_REFERENCE.md) | Retained technology and source/configuration pointers |
| [Diagrams](docs/diagrams/README.md) | Labeled target flows and current tick reference |
| [ADR index](docs/adr/README.md) | Decision history and supersession boundaries |
| [Root guidance](CLAUDE.md) | Working rules for coding agents |
| [Module guidance](server/module/spacetimedb/CLAUDE.md) / [bridge guidance](server/bridge/CLAUDE.md) | Local source maps and implementation constraints |

## License

This project is licensed under the [MIT License](LICENSE).
