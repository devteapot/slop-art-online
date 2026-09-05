# Simulation foundation: vision and design

Current participant iteration: [participant agent runtimes](PARTICIPANT_AGENTS.md) and [ADR 013](adr/013-participant-agent-runtimes.md). Rules `m1-5` use one scoped API for the built-in harness and external MCP runtimes, with independent tree, speech and learning operations. Earlier evidence and legacy runner descriptions below retain their historical scope.

This is the authoritative design entry point for SAO / Slop Art Online. The longer-term multiplayer game vision remains a living world that the user can observe and join. The development order changes: establish a concrete, inspectable simulation of individuals first, then build richer UI and gameplay around it. This document describes the target, not completed implementation.

Read next: [current implementation and gaps](CURRENT_STATE.md), [audit and experiment contract](AUDIT_AND_EXPERIMENTS.md), and [milestones and work queue](TODO.md). [ADR 007](adr/007-simulation-first-foundation.md) records this change in direction; older ADRs preserve historical rationale. [Stack reference](../STACK_REFERENCE.md) documents the retained Rust architecture.

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

- **Foundation:** the engine's vocabulary, authoritative validation, execution limits, and rules for applying changes. A coherent minimum contract must remain available to interpret editable content; the boundary between fixed machinery and editable laws still needs design.
- **World laws:** composable definitions that govern which actions are possible and how their consequences resolve. Divine authority operates here. Domains, territories, and conditions are possible scopes, not settled restrictions on the eventual game.
- **Skills:** reusable compositions of permitted operations under the applicable laws. Default skills are starting content; the target is for authored defaults and player-created skills to share the same composition and effect contracts.

Changing a law can change the usefulness, cost, or outcome of existing skills. For example, a technique that transfers heat might support warming, protection, or an attack; a change to local heat-transfer rules could alter all of them. Such examples illustrate composition rather than committing to a spell system or particular physics model. Overlapping laws need explicit precedence or conflict semantics, and edits need a defined activation boundary for actions already in progress.

Mechanical changes should also have consequences that other players can encounter and interpret: techniques spread through teaching, rivals develop responses, communities form practices, and repeated use can change environments. These are possible emergent outcomes, not mandatory scripted reactions. World changes do not automatically grant every character knowledge of them; perception and subjective understanding still apply.

## Discovery and deliberate skill authorship

Experimental discovery and deliberate authoring should layer together. Players can experiment with available capabilities, notice interactions, and formalize what they learn into reusable skills. They can also deliberately compose a technique and test whether it works. Authorship creates a definition or an attempt, not a guaranteed outcome.

Meta-skills can grant access to authoring capabilities: adjusting parameters, combining operations, expressing conditions or triggers, and potentially defining reusable abstractions. These are candidate progression steps, not a fixed unlock tree. The API determines what a character is entitled to express and execute; access to a scripting editor alone does not grant new world powers. The same character-level constraints apply to human and AI controllers.

Skills can be learned, shared, refined, or independently rediscovered. Social recognition may affect their adoption or legitimacy, but it is not yet a required approval gate for making a mechanically valid skill. How experimentation establishes character knowledge, how recipes are transmitted, and how authorship interacts with progression remain open.

Composition must preserve authoritative prerequisites, costs, timing, interruption, and actual effects. A definition cannot bypass a resource cost by renaming or nesting an operation. Useful inventions should remain possible within coherent constraints; the balance model and limits on combinations require later design.

## Scripting interface direction

Retain Rust as the authoritative engine and expose a deliberately scoped world/skill API through bindings to an embedded scripting language. The aim is to add and revise supported skills and rules without rebuilding or redeploying the Rust engine for every content change. New engine primitives can still require Rust changes. The scripting language, binding library, runtime placement, and player-facing authoring interface are not selected.

Lua, Luau, Rhai, Rune, Starlark, and embedded JavaScript are candidates for evaluation, not adopted dependencies or verified fits for the current runtime. The [preliminary comparison below](#preliminary-scripting-candidates) records their different tradeoffs. Evaluate options against the actual Rust/SpacetimeDB WASM execution environment before choosing. Prefer fast content iteration and a small operational footprint; assess embedding/build compatibility, execution and memory budgets, predictable execution, diagnostics, and versioning. Whether scripts execute within the authority or produce proposals that the authority resolves remains an architectural question; neither route may create a second simulation authority.

The API should expose permitted observations, composition operations, skill lifecycle requests, and authorized law edits through explicit capabilities. It must preserve the distinction between character knowledge and engine truth. Scripts do not receive unrestricted world-state mutation, host filesystem/network access, or authority merely because they are executable. Computation budgets and gameplay costs are separate constraints, both enforced by the engine. Recursive triggers and interacting scripts also need bounded execution and defined failure behavior.

Definitions, API contracts, and active laws need identifiable versions and traceable authorship or change authority. Later design must decide validation before activation, persistence of script state, treatment of existing instances and in-flight actions, and recovery from invalid edits. Experiments must retain enough versioned inputs to explain which rules produced an outcome, without claiming that a seed alone reproduces a whole evolving world.

The player interface could offer a structured composer, text scripting, or both over the same capabilities. How much programming knowledge participation requires is an open experience question. This authoring layer is distinct from the behavior layer: choosing when to use a known skill and defining what a new skill can do are different capabilities. No scripting runtime, public API signature, editor, or divine progression system is being commissioned by this vision update.

### Preliminary scripting candidates

Small documentation survey, 2026-09-05. Sources below are official project documentation or repositories. The fit assessments are design inferences, not benchmark results; no candidate was installed, compiled, or tested in SAO. Lua and Luau are grouped as related options so the comparison includes substantially different approaches.

| Candidate / Rust integration | Documented basis | Potential fit and unresolved tradeoff |
|---|---|---|
| **Lua / Luau through `mlua`** | `mlua` provides Rust bindings for both, including exposed Rust types and functions. Luau documents sandboxing and interruption mechanisms. [Bindings](https://github.com/mlua-rs/mlua), [Luau sandbox](https://luau.org/sandbox/). | Baseline for general skill scripting. Luau's embedding still requires the host to enforce its boundaries; evaluate each runtime's build requirements and actual module compatibility separately. |
| **Rhai** | Embedded Rust scripting with explicitly registered Rust functions, configurable operation limits, and documented WASM builds, including non-browser targets. [Rust API registration](https://rhai.rs/book/rust/functions.html), [operation limits](https://rhai.rs/book/safety/max-operations.html), [WASM targets](https://rhai.rs/book/start/builds/wasm.html). | Strong first candidate to investigate for a narrow Rust-owned skill API. Raw WASM has hashing/configuration requirements; operation limits are off by default and do not bound the work inside a native function. Actual SpacetimeDB integration remains unverified. |
| **Rune** | Embeddable dynamic language for Rust with a stack VM, hot reloading, pattern matching, and async support. Its sandbox documentation describes instruction and memory limits. [Project](https://github.com/rune-rs/rune), [sandboxing](https://rune-rs.github.io/book/sandboxing.html). | Candidate for more expressive skill programs and reusable abstractions. Native functions must cooperate with budgets. Assess compiler/runtime footprint, target support, and how suspended execution would map to authoritative ticks and persisted state; async support alone does not solve that lifecycle. |
| **Starlark through `starlark-rust`** | Python-inspired deterministic language with Rust interoperation and editor tooling. The Rust implementation includes language extensions and explicitly does not prioritize minimal dependencies or API stability across releases. [Project and compatibility notes](https://github.com/facebook/starlark-rust). | Interesting for composing law and skill definitions that the Rust engine subsequently executes. Evaluate whether its expression model fits active skill logic, plus dependency footprint and WASM compatibility. Language determinism does not make arbitrary host functions or a whole simulation deterministic. |
| **JavaScript through Boa** | Boa is an embeddable JavaScript engine written in Rust; its documentation describes partial language support and configurable runtime limits such as loop limits. [Introduction](https://boajs.dev/docs/intro), [runtime-limit documentation](https://boajs.dev/docs/debugging/debug_object). | Candidate if familiar player-facing syntax is a priority. An embedded engine need not entail a Node.js service, but we must assess language coverage, footprint, complete resource accounting, and the actual authority target. Loop limits alone are not a complete execution budget. |

Initial evaluation preference, not a selection: compare **Rhai** against the **Lua/Luau baseline** for executable skills, and include **Starlark** if authoring reusable definitions is the dominant use case. Keep **Rune** and **Boa** as alternatives for richer program structure or JavaScript familiarity. This order reflects the proposed API and iteration goals, not measured superiority.

When implementation is eventually scheduled, compare the same small scenario across shortlisted options: compose a skill from engine operations, revise an applicable law, execute under a bounded budget, and explain the result using recorded definition versions. Measure content validation/activation latency separately from engine build time, runtime cost, and memory. First establish compatibility with the deployed authority; browser WASM support by itself is insufficient evidence. This is a future evaluation outline, not current implementation work.

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
| How do editable laws compose, conflict, and change during execution? | Coherent authoritative resolution; changes can affect existing skills and must be traceable. |
| How can players gain and exercise divine rule-editing authority? | Player access is part of the long-term vision; progression, scope, and governance are unresolved. |
| How do experimentation, knowledge, meta-skills, and authoring fit together? | Discovery and deliberate composition coexist; default and player-created skills should share contracts. |
| Which embedded language, Rust bindings, and execution placement fit? | Scoped scripting API, fast content iteration, bounded execution, and one Rust world authority; the preliminary shortlist is not a selection. |
| What authoring interface and definition-update lifecycle should players use? | Capabilities follow character access; editor form, activation, compatibility, and migration policies remain open. |
| How are model responses correlated, authorized, versioned, and rejected when stale? | Untrusted output cannot directly determine world effects. |
| Which audit storage, retention/export format, query interface, and observer layout? | Durable causal history and common evidence; not just a short scratch buffer. |
| How are runs isolated, clocked, initialized, and replayed? | Real authoritative core, recorded inputs/outputs, explicit reproducibility limits. |
| How do animals and monsters fit? | Do not assume a settled taxonomy or universal intelligence ladder. |

Implementation status belongs in [CURRENT_STATE.md](CURRENT_STATE.md); execution order and completion evidence belong in [TODO.md](TODO.md). Keep these boundaries when updating the docs.
