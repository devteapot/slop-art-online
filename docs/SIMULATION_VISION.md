# Simulation foundation: vision and design

Current scripting implementation: [scripted gameplay](SCRIPTED_GAMEPLAY.md), rules `m1-6-rhai`, integrates the existing foundation skills and policies with the selected Rhai runtime. Public authoring and divine progression remain future work.

Previous participant iteration:  [participant agent runtimes](PARTICIPANT_AGENTS.md) and [ADR 013](adr/013-participant-agent-runtimes.md). Rules `m1-5` use one scoped API for the built-in harness and external MCP runtimes, with independent tree, speech and learning operations. Earlier evidence and legacy runner descriptions below retain their historical scope.

This is the authoritative design entry point for SAO / Slop Art Online. The longer-term multiplayer game vision remains a living world that the user can observe and join. The development order changes: establish a concrete, inspectable simulation of individuals first, then build richer UI and gameplay around it. This document describes the target, not completed implementation.

Read next: [current implementation and gaps](CURRENT_STATE.md), [audit and experiment contract](AUDIT_AND_EXPERIMENTS.md), and [milestones and work queue](TODO.md). [ADR 007](adr/007-simulation-first-foundation.md) records this change in direction; older ADRs preserve historical rationale. [Stack reference](../STACK_REFERENCE.md) documents the retained Rust architecture.

## Modularity and independent inspection

Components should fit together through explicit contracts while remaining independently understandable, executable and deeply inspectable. This applies across the project: skill evaluation, world policies, perception, belief and identity updates, behavior, persistence, controllers and presentation. Each component should expose its relevant inputs, owned state, outputs, dependencies and failure evidence. Boundaries should make it possible to exercise a mechanic without starting unrelated systems; they do not require a separate service or runtime for every component.

For example, inspect a skill against supplied actor facts and law revisions, including its proposed effects and continuation state. Separately, inspect how a supplied perception and interpretation change a character's beliefs, confidence and provenance. These experiments must invoke the same implementation used by the integrated game. End-to-end runs remain necessary to establish that the components' contracts compose correctly and that the player experience works.

Prefer reusable tooling that can generate and execute focused experiments for a concrete use case or question. Retain targeted deterministic checks for important contracts and known regressions, without making a large collection of fixed expected narratives the main way to investigate an evolving world. The [component experiment contract](AUDIT_AND_EXPERIMENTS.md#component-experiments) describes this direction. Dedicated tooling and further decomposition are future work, not an implementation requirement for this design clarification.

## Players and controllers

A **player** is an in-world character, whether human-controlled or AI-controlled. Qualify the controller when it matters. Both have the same character capabilities and authoritative world rules; different controllers choose intentions. Existing code names such as `Player`, `Npc`, and `NpcSkill` describe today's separate implementation, not the final product taxonomy.

The user observes the simulation and optionally participates as a human-controlled player **inside the existing Bevy game client**. Browser-hosted Bevy WASM is the primary development path, with shared rendering/input for release builds and optional native targets. In-game observer and participant modes are the product experience. External browser inspectors, HTTP intent controls and scenario tools serve developer auditing and experiments; they do not fulfill this in-game requirement. The current interface is a classic top-down 2D RPG-style view with diagnostic information overlaid on actual world state. Prioritize behavioral and mechanic iteration over visual complexity. The voxel/3D client is retired; 2.5D or 3D can be reconsidered for the official interface after the foundation is solid. The observer remains a movable camera over that world. Inspection and rendering can detach from execution: parallel sessions continue independently, and an observer can focus one and peek into its world. Observer access to world truth is outside a character's knowledge. Observation must not feed privileged information into an AI controller or its perception context. Shared rules do not require simulated human psychology, controller switching, or possession features.

Players pursue goals, respond to interruptions, communicate, interact with the environment, and fight other players or monsters. Remaining still, waiting, resting, and exploring can all be intentional activities. Random movement alone does not demonstrate a reason to act; an intentional wait has a purpose and conditions for continuing or reconsidering it.

## Individuals become different through living

Needs, motives, personality, relationships, emotions, knowledge, beliefs, and circumstances contribute to decisions. A role describes a means or social position, not necessarily an underlying end: a guard might work to earn money to feed a family. Represent the distinction between ends, goals, and chosen approaches. Work, family, and economy illustrate the broader vision; they are not mandatory first-slice mechanics.

Authored baseline categories supply initial identities and capabilities. Individuals need neither blank starting minds nor complete handcrafted biographies. A baseline is a starting point, not a fixed destiny: experience can produce substantial divergence, including changes of role or approach.

Becoming a different individual is central to the first proof. Experiences can change beliefs, emotions, relationships, knowledge, personality, and subsequent decisions. Different individuals may interpret the same event differently. State updates should have traceable sources; a trait change without an effect on future choices does not demonstrate the full loop. Not every event must change every component, and change need not be beneficial.

## Truth, perception, and subjective understanding

World state records what actually happened. Perception records what a particular player could observe or hear. Interpretation produces that player's understanding, including uncertainty, errors, competing reports, and forgotten or stale information. Calling a record “knowledge” must not make it an omniscient source of world truth.

A player's decision context is assembled from permitted perceptions, remembered experiences, subjective state, and known capabilities. The authority can check hidden world facts when resolving an attempt, but must not expose those facts to the controller merely because it can query them. Audit whether a reference was known or perceived separately from whether the referenced entity exists.

For example, someone can be missing without survivors knowing they died. Death is initially permanent for in-world characters regardless of controller. A death may influence survivors only through what they perceive or later learn; no automatic global bereavement or perfect knowledge. Reincarnation and souls are explicitly deferred.

Character memory and external audit history are different systems. A character can forget or misunderstand while an observer can still inspect the original evidence and the history of that misunderstanding.

## Every kind of action is a skill

Skills are modular action building blocks for the evolving simulation, not only combat abilities. Design toward shared skill requirements, execution, and consequences for either controller. Survival, movement, rest, waiting, communication, and combat belong to this model; later work and trade should extend it.

The controller chooses an intention and an approach. Behavior execution requests a skill attempt; authoritative rules decide whether it can start, how it progresses, whether it is interrupted, and what effects actually occur. Skill ownership/capability, relevant resources, targets, timing, and environmental constraints are validated where applicable. An intended outcome is not a guaranteed effect. This is an architectural direction, not a requirement to force every skill into today's combat attribute schema.

Free-form speech uses text as expressive content within an action. It does not require authoring a skill or template for every utterance. Saying “I healed you” cannot directly grant healing, and saying “the path is safe” does not make the path safe. Listeners may still believe either claim.

## A world whose rules can evolve

The long-term target is a dynamic world inhabited by dynamic players, with influence flowing both ways. Players develop through the world's consequences, and their discoveries, inventions, and eventual authority can reshape the world itself. Composable skills alone are insufficient if the laws and surrounding world remain static.

World rules should be composable and editable. Higher-order in-world entities, analogous to gods, govern laws within whatever authority the game grants them. A player could eventually attain such a position and reshape how the world behaves. How authority is gained, transferred, contested, or lost is deliberately unresolved. This is a future design direction, not an implemented system or an addition to the first proof.

Distinguish three conceptual layers:

- **Engine capabilities and evaluation:** Rust supplies the execution machinery and primitives through which scripts operate: state access, spatial queries, event delivery, scheduling, persistence, and committing effects, for example. It owns evaluation semantics, execution limits, and enforcement of access boundaries. The precise primitive API remains open; gameplay policy belongs above this boundary.
- **World laws:** composable scripted definitions that govern which actions are possible and how their consequences resolve, including the gameplay conditions for acquiring and exercising divine authority. Domains, territories, and conditions are possible scopes, not settled restrictions on the eventual game.
- **Skills:** scripted compositions of engine capabilities under the applicable laws. All default actions, including movement, rest, communication, and combat, belong here alongside player-created skills. Defaults use the same scripting and effect contracts; they are not a permanently hardcoded class of actions.

The intended boundary is **engine capabilities and evaluation in Rust; game logic in scripts**. The whole game's rule logic should be eligible for evolution, rather than limiting scripts to custom additions around fixed mechanics. Eligibility for change does not give every player permission to change every definition. Engine integrity and host access remain execution boundaries, while in-world progression and rule-editing permissions are gameplay policies evaluated through those boundaries.

Changing a law can change the usefulness, cost, or outcome of existing skills. For example, a technique that transfers heat might support warming, protection, or an attack; a change to local heat-transfer rules could alter all of them. Such examples illustrate composition rather than committing to a spell system or particular physics model. Overlapping laws need explicit precedence or conflict semantics, and edits need a defined activation boundary for actions already in progress.

Mechanical changes should also have consequences that other players can encounter and interpret: techniques spread through teaching, rivals develop responses, communities form practices, and repeated use can change environments. These are possible emergent outcomes, not mandatory scripted reactions. World changes do not automatically grant every character knowledge of them; perception and subjective understanding still apply.

## Discovery and deliberate skill authorship

Experimental discovery and deliberate authoring should layer together. Players can experiment with available capabilities, notice interactions, and formalize what they learn into reusable skills. They can also deliberately compose a technique and test whether it works. Authorship creates a definition or an attempt, not a guaranteed outcome.

Meta-skills can grant access to authoring capabilities: adjusting parameters, combining operations, expressing conditions or triggers, and potentially defining reusable abstractions. These are candidate progression steps, not a fixed unlock tree. The API determines what a character is entitled to express and execute; access to a scripting editor alone does not grant new world powers. The same character-level constraints apply to human and AI controllers.

Skills can be learned, shared, refined, or independently rediscovered. Social recognition may affect their adoption or legitimacy, but it is not yet a required approval gate for making a mechanically valid skill. How experimentation establishes character knowledge, how recipes are transmitted, and how authorship interacts with progression remain open.

Composition must respect the currently applicable scripted prerequisites, costs, timing, interruption, and effects. A definition cannot evade an applicable cost by renaming or nesting an operation, but an authorized law change can alter or remove that cost. The engine evaluates and enforces the active definitions rather than permanently hardcoding a balance model. Useful inventions should remain possible within coherent constraints; the initial balance model and limits on combinations require later design.

## Scripting interface direction

Use **Rhai embedded in the authoritative Rust simulation**, as selected in [ADR 016](adr/016-scripted-gameplay-rhai.md). The target is for all gameplay logic, including baseline actions, periodic world processes, and world laws, to be defined in the scripting layer. The aim is to revise that logic without rebuilding or redeploying the Rust engine for every content change. New engine primitives or changes to evaluation machinery can still require Rust changes. The player-facing editor and detailed capability API remain to be designed. The current foundation's seven skills and world policies now execute through Rhai; the bounded engine capability vocabulary and installation contract are documented in [scripted gameplay](SCRIPTED_GAMEPLAY.md).

For movement, the engine might expose spatial queries and a validated mechanism to commit position changes. Scripts define whether movement is possible, how it progresses, its speed and cost, and what happens when it encounters an obstacle. Walking, flying, or teleporting can then express different policies over engine capabilities. An API that only exposes a fixed Rust `walk` implementation with adjustable speed would not meet this direction. Exact spatial primitives and evaluation semantics still need design; this example does not select a physics implementation.

The [initial comparison below](#preliminary-scripting-candidates) preserves the alternatives considered. The [executed embedding checks](SCRIPTING_VERIFICATION.md) establish Rhai's fit with the actual SpacetimeDB WASM host, including runtime source changes. Scripts execute inside the authority and produce staged effects; Rust evaluates the applicable scripted policies and commits accepted effects. There is one simulation authority. The [subsequent integration](SCRIPTED_GAMEPLAY.md) verifies this path in the actual foundation game, including operator source updates and existing Bevy controls.

The API should expose permitted observations, composition operations, skill lifecycle requests, and authorized law edits through explicit capabilities. It must preserve the distinction between character knowledge and engine truth: authoritative rule evaluation may require world facts that a character's authoring or controller context cannot inspect. Scripts do not receive unrestricted world-state mutation, host filesystem/network access, or authority merely because they are executable. Computation budgets protect the evaluator; gameplay costs are scripted policy. The engine enforces both at their respective boundaries without treating a mana or stamina formula as an immutable execution limit. Recursive triggers and interacting scripts also need bounded execution and defined failure behavior.

Definitions, API contracts, and active laws need identifiable versions and traceable authorship or change authority. ADR 016 settles the initial lifecycle: authorize changes under current rules, activate at the next tick boundary, pin an action's skill revision, and evaluate future steps against current laws. Preserve completed effects; persist explicit continuation state rather than interpreter stacks. Incompatible changes need explicit migrations. Experiments must retain enough versioned inputs to explain which rules produced an outcome, without claiming that a seed alone reproduces a whole evolving world.

The player interface could offer a structured composer, text scripting, or both over the same capabilities. How much programming knowledge participation requires is an open experience question. This authoring layer is distinct from the behavior layer: choosing when to use a known skill and defining what a new skill can do are different capabilities. The [next foundation gate](TODO.md#scripted-gameplay-foundation-next-gate) introduces scripted baseline gameplay before broader mechanics; a public editor and divine progression system remain later work.

### Preliminary scripting candidates

Initial documentation survey, 2026-09-05, retained as historical comparison. Sources below are official project documentation or repositories. These initial fit assessments were design inferences without executable tests. Subsequent [verification](SCRIPTING_VERIFICATION.md) and [ADR 016](adr/016-scripted-gameplay-rhai.md) supersede the unselected-language status and unverified-target notes below. Lua and Luau are grouped as related options so the comparison includes substantially different approaches.

| Candidate / Rust integration | Documented basis | Potential fit and unresolved tradeoff |
|---|---|---|
| **Lua / Luau through `mlua`** | `mlua` provides Rust bindings for both, including exposed Rust types and functions. Luau documents sandboxing and interruption mechanisms. [Bindings](https://github.com/mlua-rs/mlua), [Luau sandbox](https://luau.org/sandbox/). | Baseline for general skill scripting. Luau's embedding still requires the host to enforce its boundaries; evaluate each runtime's build requirements and actual module compatibility separately. |
| **Rhai** | Embedded Rust scripting with explicitly registered Rust functions, configurable operation limits, and documented WASM builds, including non-browser targets. [Rust API registration](https://rhai.rs/book/rust/functions.html), [operation limits](https://rhai.rs/book/safety/max-operations.html), [WASM targets](https://rhai.rs/book/start/builds/wasm.html). | Strong first candidate to investigate for a narrow Rust-owned skill API. Raw WASM has hashing/configuration requirements; operation limits are off by default and do not bound the work inside a native function. Actual SpacetimeDB integration remains unverified. |
| **Rune** | Embeddable dynamic language for Rust with a stack VM, hot reloading, pattern matching, and async support. Its sandbox documentation describes instruction and memory limits. [Project](https://github.com/rune-rs/rune), [sandboxing](https://rune-rs.github.io/book/sandboxing.html). | Candidate for more expressive skill programs and reusable abstractions. Native functions must cooperate with budgets. Assess compiler/runtime footprint, target support, and how suspended execution would map to authoritative ticks and persisted state; async support alone does not solve that lifecycle. |
| **Starlark through `starlark-rust`** | Python-inspired deterministic language with Rust interoperation and editor tooling. The Rust implementation includes language extensions and explicitly does not prioritize minimal dependencies or API stability across releases. [Project and compatibility notes](https://github.com/facebook/starlark-rust). | Interesting for composing law and skill definitions that the Rust engine subsequently executes. Evaluate whether its expression model fits active skill logic, plus dependency footprint and WASM compatibility. Language determinism does not make arbitrary host functions or a whole simulation deterministic. |
| **JavaScript through Boa** | Boa is an embeddable JavaScript engine written in Rust; its documentation describes partial language support and configurable runtime limits such as loop limits. [Introduction](https://boajs.dev/docs/intro), [runtime-limit documentation](https://boajs.dev/docs/debugging/debug_object). | Candidate if familiar player-facing syntax is a priority. An embedded engine need not entail a Node.js service, but we must assess language coverage, footprint, complete resource accounting, and the actual authority target. Loop limits alone are not a complete execution budget. |

The initial preference was to compare Rhai against Lua/Luau. That evaluation now selects **Rhai**. The embedding probe exercises scripted movement, composition, changed laws, and bounded failure inside SpacetimeDB; the [integrated verification](SCRIPTED_GAMEPLAY.md) now exercises these contracts through the real authority. Player discovery and teaching remain a separate gameplay proof. Measure content activation latency separately from engine build time, runtime cost, and memory as the foundation grows.

## Behavior execution and LLM reasoning

Preserve the layered design: a dynamic behavior graph handles real-time activity and reactivity; LLM reasoning interprets experiences and revises approaches above it. “Graph” describes this architectural role. Current code uses `bonsai-bt` tree data and a custom evaluator; no arbitrary graph engine is being declared implemented or mandated.

Useful existing concepts include reactive priorities, runtime conditions, identity state, asynchronous decision requests, and continued activity while a model request is pending. The representation and refinement strategy remain open: replacing a whole tree, revising subtrees, or another compatible approach must be evaluated against concrete needs. First establish correct multi-action progress, completion, failure, and interruption semantics in the existing execution path.

AI-controlled players should recognize an approach is failing and reconsider without waiting only for dramatic external events. Lack of progress, repeated failed attempts, a mismatch between expected and actual results, and self-initiated reflection are candidate signals. Propensity and rate vary by individual attributes: personality, self-awareness/introspection, and possibly intelligence. The exact linkage is unresolved; neither a single fixed global schedule nor an intelligence formula is settled.

Budget and latency matter, but fixed call ratios, “rare conversation” quotas, and thousands of entities are not first-milestone requirements. A pending or failed model request must have explicit execution and trace semantics. Continued tree execution alone does not prove graceful recovery or meaningful fallback behavior.

## Communication from the first slice

Free-form communication is required from the first slice. Players choose to speak, listen, respond, withhold, or disengage in relation to intentions and beliefs. Conversations must be able to influence decisions and individual development. Templates can be optional conveniences, never the boundary of what can be expressed.

Keep the chain explicit: chosen speech action → emitted text → eligible listeners' perceptions → interpretation → possible belief, relationship, goal, or behavior change. Hearing a statement does not imply accepting or fully understanding it. Nearby friendly players must not acquire one another's beliefs through silent automatic copying presented as conversation.

Structured internal event records and validated action schemas are compatible with unrestricted phrasing. They support execution and inspection without limiting dialogue to predefined messages.

## Architecture and evidence

Rust and SpacetimeDB remain the authoritative simulation core, with the Rust bridge for external model calls and Bevy as the supported game client. Run the real core without the visual client for experiments; do not build a second approximate simulator. Observation and scenario tooling are consumers of the core, not a new game stack.

Inspection and experimentation are foundation requirements. Live visual inspection and structured, queryable access for LLM-assisted development must use the same evidence. The connected chain is:

World event → player perception → relevant beliefs/goals/state → decision → behavior execution → skill attempt → actual result → subsequent changes.

Record intentions, attempts, failures, interruptions, validated effects, and later state changes distinctly. Retain model inputs, returned decisions, concise reported explanations, and relevant versions. Explanations are not hidden chain-of-thought or proof of actual causation; execution records and state changes are evidence. See the [audit and experiment contract](AUDIT_AND_EXPERIMENTS.md) for requirements and acceptance checks.

## First proof and expansion

Start with a small population and basic survival. A few players managing food, rest, and danger is a recommended working example, not a fixed population count or settled mechanic list. They use shared skills, communicate freely, hold imperfect beliefs, experience consequences, and change subsequent behavior. Include a minimal Bevy in-game observer interface, structured developer trace access, and a modest scenario runner with multiple isolated runs and comparison from the start.

Judge properties and emergent outcomes rather than requiring one predetermined story. Depth and inspectability precede large populations, rich visuals, complex economies, alliances, and political systems. Optional human participation follows the shared-controller model. Animals and monsters might use related foundations with different cognitive capacities, but their taxonomy and cognitive range are not finalized.

## Open design decisions

The bounded M1 choices are now recorded in [ADR 008](adr/008-m1-authoritative-survival-slice.md) and the [runbook](M1_RUNBOOK.md). The questions below remain relevant to refinement beyond those defaults; no implementation choice should silently become a fixed product requirement:

| Question | Constraint already settled |
|---|---|
| Exact survival skills, resources, starting population, and baseline attributes? | Small, consequential, inspectable first proof; examples above are illustrative. |
| How do needs, motives, goals, and approaches relate in data? | Preserve underlying ends versus means; roles do not dictate destiny. |
| How should execution persist progress and handle interruption or revision? | Real-time behavior layer below LLM reasoning; correct skill lifecycle required. |
| How are beliefs, knowledge, interpretation, and memory represented? | Subjective understanding can be incomplete or wrong; no observer truth leakage. |
| What triggers introspection, and how do individual traits affect it? | Self-initiated reconsideration and individual variation; no fixed formula yet. |
| Which skill contract unifies current controller paths? | Same character capabilities and authoritative requirements/effects. |
| How will territorial/domain laws compose beyond the first bundle? | ADR 016 fixes next-tick activation, pinned skill revisions, current-law evaluation, and explicit conflict handling; richer domain resolution remains open. |
| How can players gain and exercise divine rule-editing authority? | Player access is part of the long-term vision; progression, scope, and governance are unresolved. |
| How do experimentation, knowledge, meta-skills, and authoring fit together? | Discovery and deliberate composition coexist; default and player-created skills should share contracts. |
| What detailed capability API and resource accounting should the Rhai runtime expose? | Rhai inside the Rust authority is selected; staged effects, bounded evaluation, and one execution path are required. |
| What authoring interface and migration tooling should players use? | Capabilities follow character access; the initial update lifecycle is fixed in ADR 016, while editor form and migration implementation remain open. |
| How are model responses correlated, authorized, versioned, and rejected when stale? | Untrusted output cannot directly determine world effects. |
| Which audit storage, retention/export format, query interface, and observer layout? | Durable causal history and common evidence; not just a short scratch buffer. |
| How are runs isolated, clocked, initialized, and replayed? | Real authoritative core, recorded inputs/outputs, explicit reproducibility limits. |
| How do animals and monsters fit? | Do not assume a settled taxonomy or universal intelligence ladder. |

Implementation status belongs in [CURRENT_STATE.md](CURRENT_STATE.md); execution order and completion evidence belong in [TODO.md](TODO.md). Keep these boundaries when updating the docs.
