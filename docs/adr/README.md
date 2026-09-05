# Architecture decision history

Start with the [simulation vision](../SIMULATION_VISION.md) for current direction, [current state](../CURRENT_STATE.md) for verified code findings, and [roadmap](../TODO.md) for work order. ADRs preserve the rationale at the time of each decision; historical “current,” “implemented,” and numerical claims are not present-day verification.

| Record | Status and scope |
|---|---|
| [001 — Combat strategy revision](001-npc-combat-strategy-revision.md) | Historical, superseded; revisiting failing approaches remains relevant under ADR 007. |
| [002 — NPC behaviour trees](002-npc-behaviour-trees.md) | Historical proposal, superseded by 003/005; not a directive to replace `bonsai-bt`. |
| [003 — Behavior trees and plans](003-npc-behavior-trees.md) | Historical implementation record, partially superseded by 005/007. |
| [005 — Identity, emotion, unified trees](005-npc-architecture-v2.md) | Partially superseded by 007; identity and layered execution rationale retained, scale/template quotas revised. |
| [006 — HY-World integration assessment](006-hy-world-2-integration-assessment.md) | Deferred research, not a selected dependency; dated external claims have not been revalidated. |
| [008 — Authoritative survival slice](008-m1-authoritative-survival-slice.md) | Implemented M1 defaults, scope and limits; verification is linked separately. |
| [007 — Simulation-first foundation](007-simulation-first-foundation.md) | Accepted current direction; links canonical design and milestone requirements. |

The numbering follows existing repository history; there is no ADR 004 file in this checkout.

- [ADR 009 — Pluggable NPC reasoning](009-pluggable-npc-reasoning.md): implemented provider boundary and evidence policy; live OpenRouter validation is tracked separately.

- [ADR 010 — Generic Chat Completions](010-generic-chat-completions.md): explicit endpoint/auth/capability declarations and response modes; retains specialized adapters.

- [ADR 011 — Persistent reactive policies](011-persistent-reactive-policies.md): model-generated conditions/branches, durable execution, and separate damage/request validity.

- [ADR 012 — Browser-hosted Bevy foundation](012-bevy-browser-foundation.md): shared WASM/native presentation, caller-specific authority views and local development enrollment.

- [ADR 013 — Participant agent runtimes](013-participant-agent-runtimes.md): shared scoped API, independent behavior/speech/learning, and official MCP adapter.

- [ADR 014: World observation and independent session focus](014-world-observer-and-session-focus.md) — implemented 3D presentation, detachable inspection and independent hosted runs.

- [ADR 015: Top-down behavior lab](015-top-down-behavior-lab.md) — retire the voxel/3D client and use 2D for mechanics iteration.

- [ADR 016: Scripted gameplay with Rhai](016-scripted-gameplay-rhai.md) — accepted language and execution boundary, rule-change semantics, and next migration gate; embedding verified, production migration pending.
