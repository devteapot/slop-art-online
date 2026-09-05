# ADR 016: Scripted gameplay with Rhai

**Status:** Accepted and integrated into the current foundation game, 2026-09-05. See the [implementation contract and verification](../SCRIPTED_GAMEPLAY.md). Public player authoring and divine progression remain future work.

## Decision

Use **Rhai embedded in the authoritative Rust simulation** as the single gameplay scripting language. Start with the verified `rhai = 1.26.0` configuration: default features disabled, `std`, `no_float`, and `no_time` enabled. Keep SpacetimeDB and Bevy. Script source becomes versioned game content, rather than a reason to rebuild the Rust module.

All gameplay definitions belong in scripts: baseline movement and other skills, prerequisites, resource formulas, perception policies, periodic world processes, and laws governing their effects. This includes the gameplay rules for gaining and exercising rule-editing authority. Rust supplies capabilities, evaluates scripts, enforces execution/access boundaries, commits state, persists history, and delivers presentation/network data. The first authored game rules use the same contracts as later player-authored content.

This supersedes the vision's unselected-language status and its suggestion that scripting can wait until broader gameplay. Do not add another set of permanent Rust gameplay rules before introducing this boundary. The existing M1 behavior remains the regression reference during migration.

## Why Rhai

The deciding constraints are embedding in the existing raw WASM authority, executing gameplay logic rather than just configuring actions, bounded evaluation, and a direct Rust interface. Rhai offers a raw engine with a small initial surface and explicit registration of host capabilities. Scripts can be parsed into reusable ASTs without invoking the Rust compiler. These properties fit the proposed boundary. [Raw engine](https://rhai.rs/book/engine/raw.html), [AST compilation](https://rhai.rs/book/engine/compile.html).

The [embedding verification](../SCRIPTING_VERIFICATION.md) goes beyond browser-WASM claims: a Rhai module was compiled, published, and executed inside an isolated SpacetimeDB 2.1.0 instance. Runtime-submitted source changed movement behavior without republishing the module. The initial build exposed browser imports through wall-clock support; `no_time` resolved that failure. Default features must also remain disabled for raw WASM hashing configuration. [Rhai WASM guidance](https://rhai.rs/book/start/builds/wasm.html).

| Alternative | Decision rationale |
|---|---|
| Lua / Luau via `mlua` | Luau passed a native embedding test. The stock raw-WASM build failed on missing C/C++ target headers. `mlua` documents WASM support through Emscripten, a different target from our authority. A port may be possible, but we will not make that integration work the game's prerequisite. Lua itself was not separately compiled. [Supported targets](https://github.com/mlua-rs/mlua). |
| Rune | An expressive Rust-embedded language with instruction and memory controls; those do not automatically bound native callbacks. We have no demonstrated requirement that warrants a second runtime evaluation after Rhai passed the relevant embedding test. Not rejected as incompatible or slower. [Sandbox contract](https://rune-rs.github.io/book/sandboxing.html). |
| Starlark | Attractive for definition composition, but this game also needs executable action and world logic. We choose one language for both. Its Rust implementation does not prioritize minimal dependencies or API stability; it offers no demonstrated advantage for this slice that would change the choice. [Project scope](https://github.com/facebook/starlark-rust). |
| JavaScript / Boa | Familiar syntax is useful, but the engine documents incomplete JavaScript support. JavaScript compatibility is not a product requirement, and introducing that wider language surface is not necessary for our scoped world API. No comparative performance or target-compatibility claim is made. [Boa introduction](https://boajs.dev/docs/intro). |

Tradeoffs accepted: Rhai's language and tooling become part of the product; it is not Lua/Luau-compatible and does not provide Luau's authoring experience. Runtime type errors need good diagnostics. Language familiarity and target-population performance still need measurement. Avoid a multi-language abstraction layer or a custom language now. Stable world data and capability contracts are the boundary worth preserving.

## Execution responsibilities

Behavior chooses which skill to attempt and when to reconsider. A skill defines its step-by-step gameplay logic. Laws supply the applicable policies. These are roles within one authoritative execution path, not three schedulers.

The Rust executor advances simulation ticks and invokes bounded script entry points. Scripts return staged effects and explicit continuation state. They may request later work through the scheduler API; they cannot create another wall-clock loop. Persistent actions use serializable state and a next-tick reference, not a suspended interpreter stack or a coroutine that must survive database reloads.

The authority owns the installed definition registry and supplies the policy modules. A player's skill cannot substitute its own law validator or choose a more privileged execution context. Engine primitives mediate effects using those authoritative scripted policies; failures discard the staged effects for that invocation and produce an audit failure. Gameplay restrictions remain editable by an authorized change to the policy itself. Host identity, execution budgets, and the distinction between a policy context and a participant context remain engine boundaries.

Start with integer quantities and ticks. Fractional quantities can use an explicitly scaled representation; adding another numeric representation requires a defined arithmetic/replay contract. Give scripts no ambient clock, network, filesystem, or uncontrolled random source. Any game randomness comes through an authority-owned, recorded source. Stable input/order, source versions, and runtime configuration are part of reproduction; language choice alone does not ensure determinism.

## Law changes and actions already in progress

Adopt these initial temporal semantics:

1. Validate a proposed definition change and its edit authority against the currently active rules. The proposed rules cannot authorize their own installation.
2. Activate accepted changes atomically at the next tick boundary. Every evaluation within a tick sees one consistent active rule revision. Simultaneous conflicting updates use revision checks; they cannot silently overwrite each other.
3. Pin an action's skill definition and its composition dependencies when the action starts. On every subsequent step or event, evaluate it against the currently applicable world laws. Skill implementation remains stable during execution; its environment can change.
4. Do not retroactively rewrite completed effects. A projectile already exists at its recorded position, but future movement and impact use the active laws. An enchantment retains explicit instance state and its pinned definition; future pulses are evaluated under current laws. Migration or removal is a separate recorded action.
5. Keep prior source revisions while any live instance or retained replay references them. An incompatible state/API change requires an explicit migration or rejection, never an implicit reinterpretation of saved state.

For the first slice, use one effective world-law bundle, with named policy entry points and an explicit dependency list. Reject dependency cycles. Later territorial/domain composition must supply an explicit scripted resolver and conflict policy; do not introduce implicit last-loaded-wins behavior. The engine enforces resolution/evaluation semantics, while gameplay precedence belongs in the authored policy.

## Character powers and outside knowledge

Progression gates enforceable abilities: which operations a character can request, which definitions it can install/use, and which domains it can edit. An external controller may remember more or reason differently; the game does not claim it can force that controller to forget.

Controller and player-authoring contexts receive permitted character knowledge. Authoritative world-policy evaluation may use hidden facts to resolve consequences, but cannot expose those facts through unrestricted player callbacks. Human and AI controllers use the same capability checks. A skill-authoring unlock grants scoped authoring ability, not engine administration.

## Persistence and initial migration

Persist stable entity IDs, definition IDs/revisions, script-owned serializable state with schema versions, active rule revisions, and causal outcomes. Treat compiled ASTs as disposable caches, not saved world truth. Cache loss must not change behavior. Do not assume interpreter globals or database-process lifetime provide durable state.

The current whole-world serialized row can remain during the bounded migration. Separate storage from evaluation so that later entity/component tables do not change script contracts. Measure actual load before choosing partitioning or a different database.

Replace the closed skill enumeration at the external content boundary with versioned definition references. Compatibility adapters may map old action names during migration, but must dispatch through the same scripted execution path. The current foundation now moves its existing skill prerequisites/effects and world policies into scripts, preserving scenario outcomes and character scope checks; see the implementation contract for its bounded primitive vocabulary. Rust should retain the evaluator and generic capabilities rather than a parallel default-game implementation.

## Concrete first playable proof

Implement ordinary movement as a scripted action. Let a participant discover and author a reusable stride by composing movement operations under its granted capabilities. Have another character learn and use it through permitted communication. An authorized operator fixture then changes a movement law while a stride is in progress: the next step follows the new law, while prior position changes remain historical facts. A blocked or interrupted attempt reports a reason that the character can perceive and react to.

The current integrated verification demonstrates scripted steps, composition, reevaluation under changed laws, operator installation permissions, scoped participant calls and existing browser controls. It does **not** demonstrate discovery, teaching, divine progression, or the player experience of authoring. The integrated scenario must prove those relevant interaction contracts through the real simulation and Bevy client before broader mechanics grow around them.

Before accepting public player-authored scripts, implement aggregate allocation/output/host-call budgets, capability enforcement, definition installation validation, and meaningful failure/audit behavior. Per-operation and per-container limits alone are not a full resource budget. Native callbacks must account for their own work. [Rhai protection guidance](https://rhai.rs/book/safety/index.html).

The [roadmap](../TODO.md#scripted-gameplay-foundation-next-gate) makes this migration the next foundation gate. Language selection and the existing-game integration are complete; remaining work includes public authoring budgets, progression and the discovery/teaching experience.
