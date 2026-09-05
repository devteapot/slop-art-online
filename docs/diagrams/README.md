# Simulation diagrams

Read the [simulation vision](../SIMULATION_VISION.md) first. Diagrams summarize it; they do not independently define requirements. Unless labeled current source flow, boxes and arrows describe target responsibilities, not implemented components.

| Diagram | Scope |
|---|---|
| [System overview](system-overview.md) | Retained stack and target observer/scenario/evidence interfaces |
| [Behavior execution](behavior-tree.md) | Layered decisions, action progress, and shared skills; current sequence caveat |
| [Identity](npc-identity.md) | Baselines, individual experience, change, and future choices |
| [Perception and knowledge](knowledge-progression.md) | Subjective understanding versus authoritative truth |
| [Communication](conversation-protocol.md) | Free-form speech and its causal consequences |
| [LLM reasoning](llm-usage.md) | Experience, reconsideration, conversation, and returned proposals |
| [Current NPC tick](npc-tick.md) | Static source flow and foundation gaps |

The previous template percentages, fixed call budgets, and migration diagrams have been replaced here. [ADR 005](../adr/005-npc-architecture-v2.md) preserves their historical rationale. [Current state](../CURRENT_STATE.md) and the [roadmap](../TODO.md) track the difference between target and implementation.
