# ADR 007: Simulation foundation before gameplay expansion

**Status:** Accepted direction, 2026-09-04. Implementation pending; see the [roadmap](../TODO.md).

## Context

The living-world game vision remains. Earlier work emphasized gameplay, scale, and minimized model calls before demonstrating a coherent simulation of changing individuals. Documentation mixed target designs, historical migration steps, and implementation claims. The existing Rust/SpacetimeDB/Bevy/bridge architecture is useful and should be retained.

## Decision

Use the [simulation vision](../SIMULATION_VISION.md) as the single authoritative design entry point, supported by a [source-backed implementation assessment](../CURRENT_STATE.md), [audit/experiment contract](../AUDIT_AND_EXPERIMENTS.md), and staged roadmap.

Prove a small survival simulation first. Human-controlled and AI-controlled players share capabilities and authoritative rules, with all action kinds modeled as modular skills. Free-form communication, imperfect understanding, experience-driven individual development, permanent death, and individually varying reconsideration are foundational. Observe world truth independently of character knowledge.

Keep the real-time behavior layer under asynchronous model interpretation and revision. Current behavior-tree code is the starting point; graph representation and refinement strategies remain open. Build live visual and structured inspection over common durable causal evidence, plus reusable scenarios, isolated parallel runs against the real core, and comparison from the first milestone.

## Supersession boundaries

| Earlier material | Retained | Revised or deferred |
|---|---|---|
| ADR 001–003 | Motivation for revisable approaches and behavior execution separate from model calls | Old combat/plan splits and current-status language are historical; introspection policy remains open. |
| ADR 005 | Structured evolving identity, reactive behavior priorities, unified-tree starting point, external bridge | Population-first priorities, fixed model-call ratios, template-first/rare free speech, automatic belief copying as communication, exhaustive triggers, and settled mob/NPC taxonomy are superseded as requirements. Sequence examples are not implementation proof. |
| ADR 006 | Dated world-generation research | Integration is deferred; old next steps and product evaluations are not active milestone requirements or freshly verified recommendations. |

## Consequences

Audit/scenario tooling and individual change are delivered alongside mechanics, not postponed until after gameplay. The first proof is deeper and smaller. Cost and scale remain engineering concerns, measured after core behavior works. The implementation assessment records concrete gaps without runtime changes in this documentation task.

Exact survival mechanics, schemas, execution/refinement details, introspection linkage, retention storage, and replay mechanics remain explicit [open design decisions](../SIMULATION_VISION.md#open-design-decisions). Reincarnation/souls are deferred. No stack migration, possession system, simulated human psychology, or fixed animal intelligence model is implied.
