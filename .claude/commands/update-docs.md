Maintain project documentation against actual source and retained verification evidence. Follow `AGENTS.md` and applicable nested `AGENTS.md` files.

## Sources and scope

Start with `docs/SIMULATION_VISION.md`, `docs/WORLD_VISION.md`, `docs/CURRENT_STATE.md`, `docs/WORLD_ROADMAP.md`, `docs/TODO.md` and `docs/AUDIT_AND_EXPERIMENTS.md`. Historical ADRs explain previous decisions; they are not the current implementation specification.

Use `server/module/spacetimedb/AGENTS.md` and `server/bridge/AGENTS.md` for active source maps. Inspect `simulation/`, foundation storage/client access, participant runtimes and the Bevy foundation client. Inspect legacy `npc_ai.rs`, tables and bridge routing only when documenting that explicitly labeled path.

For SpacetimeDB architecture/API claims, consult the relevant official documentation and verify compatibility with pinned dependencies and actual runtime versions. Do not reproduce obsolete SDK snippets or infer implementation from a guide.

## Updates

- Update current-state descriptions and source maps to match the active code.
- Mark roadmap items accepted only when their required evidence exists. Tables, handlers, compilation or a successful model response alone are insufficient.
- Separate implemented mechanisms, observed autonomous behavior and unproven performance/sustainability. Preserve failed trials and their original conditions.
- Keep benchmark scope explicit: population, duration, workload, observer load, database inventory and resource measurements. Do not describe service-wide RAM as one world's footprint.
- Keep confirmed user design decisions; record unresolved implementation deviations without silently rewriting the vision. Ask for clarification only when the current task genuinely needs a new design decision not already settled in the conversation.
- Update affected diagrams using `.claude/commands/update-diagrams.md`; do not regenerate unrelated diagrams or relabel legacy ones as current.
- Update links to `AGENTS.md` and avoid duplicating volatile source details across guides.

For documentation-only changes, check local links, terminology and `git diff --check`. Do not build dependencies or regenerate bindings. Summarize changes and material unresolved discrepancies.
