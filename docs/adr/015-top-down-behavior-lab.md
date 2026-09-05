# ADR 015: Top-down 2D behavior lab

**Status:** Implemented, 2026-09-05.

## Decision

Use a classic top-down 2D RPG-style interface to iterate on behavior and mechanics. Retire both the legacy voxel client and the recent 3D foundation presentation. Remove their terrain generation, Avian physics, surface-meshing dependencies and GLB model assets. Make the foundation the default client entry point.

Keep Bevy, Rust and SpacetimeDB. The change removes a presentation burden without changing authoritative mechanics, model APIs, perception filtering or audit evidence. A flat tile/sprite view is enough to see who moves, acts, speaks, consumes resources or dies. Keep camera pan/zoom, selection, optional overlays, independent session focus and detached inspection from ADR 014.

The current core still has one spatial axis. Decorative map tiles and sprite lanes do not supply additional movement, pathfinding or collision rules. Evolving real 2D mechanics belongs in the authoritative core and headless checks when that work is requested.

## Consequences

`cargo run -p client` now runs the same 2D foundation used by the browser. There is no alternate legacy client mode. Legacy server reducers and older evidence remain; removing the old renderer does not port their gameplay into the foundation.

A future 2.5D/3D official interface is a later decision, after behavior and mechanics are solid. It should consume the same authority boundary rather than moving rules into rendering code. No engine migration or new scripting runtime is introduced by this decision.
