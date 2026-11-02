# Slop Art Online

A Rust game about individuals who pursue goals, form imperfect beliefs, communicate, and become different through experience. Human-controlled and AI-controlled characters share capabilities, authority and physical rules.

The active implementation is the **[living core](docs/LIVING_CORE.md)**: a lean SpacetimeDB authority, LLM minds with Neo4j personal knowledge graphs, and a Bevy observer. The earlier `simulation`/`server`/`client` line was removed from the tree on 2026-11-02; its last state is one checkout away at the `legacy-baseline` tag, and its evidence documents remain in `docs/` as history.

Worlds grow one layer at a time in small lab worlds. A stage passes only when its measured criteria hold, and only then does the next layer go on top ([stages](docs/STAGES.md)).

## Architecture

```text
Bevy observer (living-viewer: native or browser)
    ↕ SpacetimeDB subscriptions
SpacetimeDB authority (living-authority: 60 Hz tick, typed tables, Rhai skills)
    ↕ deliberation and consolidation requests
Rust mind service (living-mind)
    ↕ HTTP            ↕ Bolt
LLM providers        Neo4j personal knowledge graphs
(living/configs/models.json)
```

## Prerequisites

- [Rust](https://rustup.rs/) (stable toolchain) with the `wasm32-unknown-unknown` target (`rustup target add wasm32-unknown-unknown`)
- [Docker](https://docs.docker.com/get-docker/) with Compose
- [just](https://github.com/casey/just) (command runner)
- API credentials for the configured model providers (`living/configs/models.json`)

## Quick start

```bash
just living-up        # SpacetimeDB (:3300) and Neo4j (:7476/:7689) containers
just living-reset      # fresh world from the seed (DELETES world data)
just living-mind       # the mind service
just living-web        # browser observer at http://127.0.0.1:8330/
```

Common recipes (see the [Justfile](Justfile)):

| Command | Description |
|---|---|
| `just living-check` | Authority WASM, mind, native and browser observers, rules tests — run before every commit |
| `just living-test` | Rules tests |
| `just living-seed <name>` | Choose the active seed (`living/seeds/<name>.json`); takes effect at the next reset |
| `just living-publish` | Update the module in place and install the current skill rules |
| `just living-sql "<query>"` | Query the living database |

Reset recipes delete database data; they are not routine update commands.

Verification of changes is skill-driven; start at `.agents/skills/verify/SKILL.md` (see [AGENTS.md](AGENTS.md)).

## Project structure

| Path | Purpose |
|---|---|
| `living/` | The living core: authority, rules, bindings, mind, viewer, seeds, tools |
| `docs/` | Active design docs plus retained historical evidence |
| `.agents/skills/` | Shared verification and project skills |

## Documentation

| Document | Purpose |
|---|---|
| [Living core](docs/LIVING_CORE.md) | The active core: architecture, data model, decisions |
| [Stages](docs/STAGES.md) | Lab protocol, stage criteria, and every recorded run |
| [World vision](docs/WORLD_VISION.md) | Agreed living-world design and open decisions |
| [Simulation vision](docs/SIMULATION_VISION.md) | Original authoritative direction and vocabulary |
| [Current state](docs/CURRENT_STATE.md) | Historical assessment of the removed legacy implementation |
| [Roadmap](docs/TODO.md) | Milestones, dependencies, technical debt |
| [ADR index](docs/adr/README.md) | Decision history and supersession boundaries |
| [Root guidance](AGENTS.md) | Working rules for coding agents |

Runbooks and evidence describing the removed line — the M1 runbook, Bevy browser client, participant agents, stack reference, iteration and scaling reports — are retained as historical evidence; their source links resolve at the `legacy-baseline` tag.

## License

This project is licensed under the [MIT License](LICENSE).
