# verify-knowledge: cullet-sweep, module memory and rollback

A documentation correction only, from the scoped maintenance for the new `knowledge_epoch` table.

- **`features/names.md`:** a self-introduction now also moves the hearer's private `knowledge_epoch` row in the same transaction. verify-core `sweep_marks` drives it live (`core-mem2`, the row named 0.22 s after a `mind_say` introduction).
- **No verify-knowledge case was run.** Names in memory, consolidation and Neo4j are not touched by this change.
