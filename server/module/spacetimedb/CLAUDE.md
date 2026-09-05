# Authoritative simulation module

Read the [simulation vision](../../../docs/SIMULATION_VISION.md), [current-state assessment](../../../docs/CURRENT_STATE.md), [roadmap](../../../docs/TODO.md), and [audit/experiment contract](../../../docs/AUDIT_AND_EXPERIMENTS.md). Those own product direction, verified gaps, and acceptance requirements. This file is local implementation guidance, not a second design specification. [ADR 005](../../../docs/adr/005-npc-architecture-v2.md) is historical and partially superseded.

M1 runs use [foundation.rs](src/foundation.rs) and the shared [simulation kernel](../../../simulation/src/lib.rs); see the [runbook](../../../docs/M1_RUNBOOK.md) and [verification](../../../docs/M1_VERIFICATION.md). The legacy gaps below remain relevant when migrating the old gameplay path, not as a description of the foundation sequencer.

## Source map

| Source | Responsibility |
|---|---|
| [lib.rs](src/lib.rs) | Reducers, scheduled tables including short-term NPC events, NPC tick, model submission paths, human skills/chat |
| [tables.rs](src/tables.rs) | Player/NPC state, behavior, identity, skill, inventory, and other tables |
| [npc_ai.rs](src/npc_ai.rs) | `bonsai-bt` data evaluation, action dispatch, role defaults, emotion/goal logic, decision context, propagation |
| [skill.rs](src/skill.rs) / [combat.rs](src/combat.rs) | Skill calculations and combat/death paths |
| [equipment.rs](src/equipment.rs), [consumable.rs](src/consumable.rs), [loot.rs](src/loot.rs) | Existing item capabilities |
| [constants.rs](src/constants.rs) | Current tuning, not immutable design requirements |

## Foundation constraints

The module remains authoritative. Human and AI controllers should submit intentions to shared skill requirements, execution, and consequences. Current NPC `Attack` bypasses the human `use_skill` path; this is a gap, not a pattern to extend.

`NpcBehavior.current_tree` exists, but `evaluate_tree` selects only the last action from a successful `Sequence`, and the tick executes it once. It does not execute earlier actions or persist sequential progress. Fix and verify lifecycle semantics before describing multi-action plans or inline post-action learning as working. Do not infer completion from a `bonsai-bt` type or tree JSON.

Separate world truth, eligible perceptions, subjective interpretation, and player memory. Current proximity-based belief/knowledge copying bypasses chosen communication. Free-form speech must fit the shared action/perception chain and affect future choices. World effects require authoritative validation; speech does not grant mechanical abilities.

Identity growth must be causally traceable and feed back into behavior. Map needs and underlying ends separately from roles and chosen approaches. Ensure relevant structured personality/emotion/knowledge actually enters decisions; current context assembly does not establish this.

Shared permanent death and durable history are target requirements. Current human respawn and NPC deletion paths differ. The five-minute event buffer is short-term context, not a lasting audit record, and is separate from persistent identity/memory tables.

When changing mechanics, update causal records, scenario initialization, and structured/visual inspection together. Use run-scoped isolation and controlled inputs for experiments against this core. Verify timing/order and version assumptions before promising replay.

## Implementation discipline

Use the existing Rust/SpacetimeDB structure and supported APIs; read [parent SDK guidance](../CLAUDE.md) for local conventions and check actual pinned code for API details. Do not introduce a stack migration. Preserve deterministic reducer inputs, use the SpacetimeDB RNG, and keep model/network work in the bridge.

Model results need validation beyond JSON parsing: authorized request/controller, known/permitted context, capability, stale/version checks, and effect validation at execution. Rejections and fallbacks need inspectable records. A pending request must not silently freeze activity or fabricate progress.

New logic should go into focused modules. Review existing indexes before adding new ones; event/memory indexes already exist although callers still scan. Do not optimize for thousands of entities before the first small, inspectable proof works.
