Maintain project documentation against actual source and retained verification evidence. Follow `AGENTS.md` and applicable nested `AGENTS.md` files.

## Sources and scope

Start with `docs/SIMULATION_VISION.md`, `docs/WORLD_VISION.md`, `docs/CURRENT_STATE.md`, `docs/WORLD_ROADMAP.md`, `docs/TODO.md` and `docs/AUDIT_AND_EXPERIMENTS.md`. Historical ADRs explain previous decisions; they are not the current implementation specification.

Use [docs/LIVING_CORE.md](../../docs/LIVING_CORE.md) and the `living/` workspace for the active source map. Inspect the `living/` crates (authority, rules, mind, viewer). The removed legacy line (`simulation/`, `server/`, `client/`) is documented only as an explicitly labeled historical path; its last state is the `legacy-baseline` tag.

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
