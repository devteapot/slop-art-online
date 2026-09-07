# Authoritative simulation module

Follow the [root guidance](../../../AGENTS.md) and [parent SDK guidance](../AGENTS.md), including consulting official SpacetimeDB documentation before designing or implementing features. Product direction lives in the [world vision](../../../docs/WORLD_VISION.md); accepted evidence and open scale/autonomy work live in the [roadmap](../../../docs/WORLD_ROADMAP.md).

## Active source map

| Source | Responsibility |
| --- | --- |
| [foundation.rs](src/foundation.rs) | Foundation run creation, operator mutations, save boundary and durable audit insertion |
| [client_access.rs](src/foundation/client_access.rs) | Authenticated grants, participant operations, scheduled clock, scoped views and participant publication |
| [storage.rs](src/foundation/storage.rs) | Private storage tables, hydration, commit, compatibility views and owner procedures |
| [storage_codec.rs](src/foundation/storage_codec.rs) | JSON/blob representation, validated references, immutable payload reuse and retention |
| [simulation kernel](../../../simulation/src/lib.rs) | Shared gameplay state and execution; focused modules implement perception, behavior, knowledge, population, infrastructure, research and laws |
| [storage tests](src/foundation/storage_tests.rs) and [module integration tests](../../../simulation/tests/module_storage.rs) | Storage, scope, privacy and compatibility checks |

`src/lib.rs`, `tables.rs`, `npc_ai.rs`, `skill.rs` and the old combat/item modules also contain the retained legacy gameplay path. Its NPC-specific effects, respawn and propagation are not the foundation's shared skill, permanent-death or personal-learning implementation. Inspect the active caller before changing either path.

## Authority and scale constraints

The current foundation supports the seven bounded implementation slices, including paid numerical research and scoped/universal law editing. Autonomous invention/ascension and sustained large populations remain unproven. Existing whole-World hydration and all-participant status generation are known scale liabilities; they are not requirements for new features.

Design routine mutations around affected typed rows and explicit dependencies, using spatial/entity/owner indexes where appropriate. Avoid full-world snapshots and broad procedural views in local gameplay paths. Preserve the same authoritative mechanics when improving persistence; do not fork gameplay into a second simulator. A local operation can depend on remote infrastructure or applicable law, so FOV alone does not define its transaction dependencies.

Authenticate grants, controller epochs, current revisions, capabilities and effects at commit. Preserve atomic failure, exact resource costs, current-law binding and scope. Teaching source does not copy private experimental proof or mastery. Stored audit history must never restore a character's lost knowledge.

Keep observation provenance and read/learning consistency when replacing large captured contexts with smaller records. Permission checks must run before exposing private data. Shared regional subscriptions are suitable only for information all recipients may know.

## Validation

Use the [audit contract](../../../docs/AUDIT_AND_EXPERIMENTS.md) and [Stage 7 evidence](../../../docs/STAGE_7_EVIDENCE.md) for existing guarantees. Preserve source/copy/privacy and material invariants through storage changes. Measure actual authority execution, queueing, fan-out, memory and retention under the intended workload; do not equate native codec speed with server throughput.

Owner exports follow the [snapshot contract](../../../docs/OWNER_SNAPSHOT_API.md). SQL compatibility views and procedure exports have different overhead. Keep explicit checkpoints coherent and routine subscriptions narrow. Do not mutate frozen implementations or rewrite failed experiment outcomes when validating replacements.
