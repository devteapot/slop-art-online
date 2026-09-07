Maintain Mermaid diagrams in `docs/diagrams/` when the task changes the architecture they describe. Follow `AGENTS.md` and the relevant nested instructions.

## Establish the diagram's scope

Read `docs/SIMULATION_VISION.md`, `docs/WORLD_VISION.md`, the current-status summary and linked evidence. Use `server/module/spacetimedb/AGENTS.md` and `server/bridge/AGENTS.md` to locate active source.

The foundation path is Bevy/participant clients, scoped SpacetimeDB authority and external agent reasoning. Legacy `NpcPendingDecision`, NPC tick/identity tables and ADR 005 diagrams must be labeled historical where they remain. Do not copy their template conversation, automatic belief propagation or fixed model-call quotas into a current diagram.

## Trace the actual flow

Inspect the relevant `simulation/` modules, foundation reducers/storage/client access, participant/MCP services, agent harness and Bevy foundation code. Show actual perception, intention, validation, effect and learning boundaries. Distinguish participant knowledge from operator audit access.

For database/subscription diagrams, consult official SpacetimeDB documentation and the pinned implementation. Distinguish current whole-World paths from proposed typed-row or spatial-subscription changes. A planned optimization is not an implemented incremental path.

## Format and verification

Each diagram should have a title, short description, Mermaid block and explicit current/target/historical status. Use solid edges for implemented flows and dashed edges for proposed flows. Prefer flowcharts for architecture, sequence diagrams for interactions and state diagrams for lifecycles. Keep diagrams small and label authority, client and external inference boundaries.

Update only affected diagrams and their source links. Preserve historical rationale and experiment outcomes. Check Markdown links and Mermaid structure; report what changed and which proposed behavior remains unverified. No runtime builds are needed for diagram-only work.
