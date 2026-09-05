# Project guidance

SAO / Slop Art Online retains its living-world game vision and Rust stack. Build the inspectable simulation foundation before expanding gameplay, visuals, or population scale.

The implemented M1 path is documented in the [runbook](docs/M1_RUNBOOK.md) and [verification report](docs/M1_VERIFICATION.md). Use `simulation/` and `foundation.rs` for foundation rules; the old gameplay reducers remain a separate legacy prototype.

## Read first

- [Simulation vision](docs/SIMULATION_VISION.md) is the authoritative design entry point, including vocabulary and open questions.
- [Current state](docs/CURRENT_STATE.md) distinguishes verified source structure from target behavior and concrete gaps.
- [Roadmap](docs/TODO.md) defines work order and milestone completion.
- [Audit and experiments](docs/AUDIT_AND_EXPERIMENTS.md) defines evidence, tooling, and acceptance requirements.
- [Stack reference](STACK_REFERENCE.md), [module guidance](server/module/spacetimedb/CLAUDE.md), and [bridge guidance](server/bridge/CLAUDE.md) provide implementation context.

Historical [ADRs](docs/adr/README.md) explain earlier choices; their old call quotas, template-first communication, population targets, and migration checkmarks do not override the current design.

## Working principles

“Players” includes human-controlled and AI-controlled characters. Existing `Player`/`Npc` identifiers do not imply different intended capabilities or world rules. Keep observer truth outside character perception; shared controllers do not require simulated human psychology or possession features.

All kinds of action are intended to be modular skills. Extend shared requirements/execution/consequences across controllers; do not add parallel NPC-only effects and call that parity. Distinguish intention, attempt, interruption/failure, validated result, and later identity change.

Preserve the real-time behavior layer with LLM interpretation/revision above it. The current implementation uses behavior trees and a custom evaluator; inspect sequence semantics before relying on multi-action plans. Do not assume an arbitrary graph engine or a specific redesign is required.

Free-form communication, experience-driven individual change, and individually varying reconsideration belong in the first integrated slice. Templates, roles, fixed schedules, and silent belief copying must not replace those requirements. Death is initially permanent; reincarnation is deferred.

Make mechanics inspectable through common visual/structured evidence and reusable headless scenarios. Keep audit history distinct from character memory. Retain actual model exchanges and reported explanations, not hidden chain-of-thought claims. A seed alone does not guarantee repeatable model outputs.

## Architecture constraints

- Rust SpacetimeDB module owns authoritative rules and state. Bevy owns game rendering/input/UI and presentation/prediction.
- Reducers must use supported deterministic inputs and SpacetimeDB RNG; no HTTP or external LLM calls inside WASM reducers.
- The Rust bridge handles external model calls. Outputs are untrusted; parsing alone is not complete authorization or effect validation.
- Shared client/bridge types come from generated bindings in `shared/`; regenerate only when schema/reducer changes require it.
- Run experiments using the actual authoritative core without Bevy. Do not implement a second approximate simulator or change stacks for tooling.
- Prefer focused modules for new logic rather than extending the `lib.rs` monolith. Preserve useful existing architecture.

## Build and run

See [README setup](README.md#prerequisites) and the [Justfile](Justfile). Common commands:

```bash
cargo build              # workspace build
cargo test               # workspace tests
cargo test <name>        # focused test
just up                  # local SpacetimeDB + Open WebUI, mac profile
just client              # Bevy client
cargo run -p bridge      # model bridge
just publish             # incremental local module publish
just publish-reset       # deletes DB data and republishes
just generate            # regenerate Rust bindings
just logs                # compose logs
```

For documentation-only changes, review links, terminology, current/target labels, and `git diff --check`; do not install dependencies, regenerate bindings, or run heavyweight builds. For runtime changes, verify the affected behavior and relevant scenario/audit acceptance checks. Do not mark a feature complete merely because its table or handler exists.
