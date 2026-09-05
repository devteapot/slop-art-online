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

M1 now has an executable survival foundation with shared skills, persistent behavior sequences, free-form model speech, subjective perception, individual change, permanent death, durable evidence, and isolated scenario runs. The legacy Bevy gameplay path remains separate while the foundation is proved. The [browser-hosted Bevy game client](docs/BEVY_BROWSER_CLIENT.md) now provides in-game observer and owned human participant modes, using the same authoritative foundation. The external HTML inspector remains developer audit tooling. See the [M1 runbook](docs/M1_RUNBOOK.md) and [verification report](docs/M1_VERIFICATION.md) for exact scope and model limitations.

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
- [Docker](https://docs.docker.com/get-docker/) (for local SpacetimeDB / optional Ollama UI)
- [just](https://github.com/casey/just) (command runner)
- [Ollama](https://ollama.com/) (optional — local LLM for the bridge; on macOS run natively, not in Docker)

WASM target for publishing the server module:

```bash
rustup target add wasm32-unknown-unknown
```

Use the matching CLI version before regenerating bindings:

```bash
spacetime version install 2.1.0
spacetime version use 2.1.0
```

NPC model backends are configurable per run: see [Ollama, OpenRouter, and compatible endpoint reasoning](docs/NPC_REASONING.md).

## Quick start

### 1. Start local services

```bash
just up          # SpacetimeDB (:3000) + Open WebUI (:8080) on mac profile
```

On Linux with an NVIDIA GPU you can use the `gpu` profile (includes containerized Ollama). See `deploy/docker-compose.yml`.

### 2. Publish the game module

```bash
just publish-reset   # clear DB and publish (first time / hard reset)
# or
just publish         # incremental publish
just generate        # regenerate Rust client bindings into shared/
```

### 3. Run the LLM bridge (needed for model-backed decisions)

```bash
# Defaults: SpacetimeDB at http://localhost:3000, Ollama at http://localhost:11434
export OLLAMA_MODEL=llama3.2   # or whatever you have pulled
cargo run -p bridge
```

### 4. Run the Bevy client

For the primary foundation development interface, use the [Bevy browser runbook](docs/BEVY_BROWSER_CLIENT.md) and open [127.0.0.1:18890](http://127.0.0.1:18890). The command below starts the preserved legacy gameplay mode.

```bash
just client      # cargo run -p client
```

### Useful commands

| Command | Description |
|---------|-------------|
| `cargo build` | Build all workspace crates |
| `cargo test` | Run all tests |
| `just client` | Run the Bevy game client |
| `just up` / `just down` | Start / stop docker-compose services |
| `just logs` | Tail SpacetimeDB / compose logs |
| `just publish` | Publish the SpacetimeDB module |
| `just publish-reset` | Delete DB data and republish |
| `just generate` | Regenerate `shared` module bindings |
| `just call <reducer> [args...]` | Call a reducer against the local DB |

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
