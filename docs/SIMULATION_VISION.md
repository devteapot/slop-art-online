# Simulation foundation: vision and design

Current participant iteration: [participant agent runtimes](PARTICIPANT_AGENTS.md) and [ADR 013](adr/013-participant-agent-runtimes.md). Rules `m1-5` use one scoped API for the built-in harness and external MCP runtimes, with independent tree, speech and learning operations. Earlier evidence and legacy runner descriptions below retain their historical scope.

This is the authoritative design entry point for SAO / Slop Art Online. The longer-term multiplayer game vision remains a living world that the user can observe and join. The development order changes: establish a concrete, inspectable simulation of individuals first, then build richer UI and gameplay around it. This document describes the target, not completed implementation.

Read next: [current implementation and gaps](CURRENT_STATE.md), [audit and experiment contract](AUDIT_AND_EXPERIMENTS.md), and [milestones and work queue](TODO.md). [ADR 007](adr/007-simulation-first-foundation.md) records this change in direction; older ADRs preserve historical rationale. [Stack reference](../STACK_REFERENCE.md) documents the retained Rust architecture.

## Players and controllers

A **player** is an in-world character, whether human-controlled or AI-controlled. Qualify the controller when it matters. Both have the same character capabilities and authoritative world rules; different controllers choose intentions. Existing code names such as `Player`, `Npc`, and `NpcSkill` describe today's separate implementation, not the final product taxonomy.

The user observes the simulation and optionally participates as a human-controlled player **inside the existing Bevy game client**. Browser-hosted Bevy WASM is the primary development path, with shared rendering/input for release builds and optional native targets. In-game observer and participant modes are the product experience. External browser inspectors, HTTP intent controls and scenario tools serve developer auditing and experiments; they do not fulfill this in-game requirement. Observer access to world truth is outside a character's knowledge. Observation must not feed privileged information into an AI controller or its perception context. Shared rules do not require simulated human psychology, controller switching, or possession features.

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
| How are model responses correlated, authorized, versioned, and rejected when stale? | Untrusted output cannot directly determine world effects. |
| Which audit storage, retention/export format, query interface, and observer layout? | Durable causal history and common evidence; not just a short scratch buffer. |
| How are runs isolated, clocked, initialized, and replayed? | Real authoritative core, recorded inputs/outputs, explicit reproducibility limits. |
| How do animals and monsters fit? | Do not assume a settled taxonomy or universal intelligence ladder. |

Implementation status belongs in [CURRENT_STATE.md](CURRENT_STATE.md); execution order and completion evidence belong in [TODO.md](TODO.md). Keep these boundaries when updating the docs.
