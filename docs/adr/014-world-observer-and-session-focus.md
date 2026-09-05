# ADR 014: World observation and independent session focus

**Status:** Session/inspection boundaries retained. 3D presentation superseded by [ADR 015](015-top-down-behavior-lab.md), 2026-09-05.

The simulation is the game world. Its normal visual surface is a Bevy scene viewed through a floating camera, with optional diagnostic overlays. Minds, policies and causal records remain available while watching their confirmed consequences on characters and resources.

SpacetimeDB remains the only authority. The current foundation's one-dimensional positions map onto a three-dimensional scene; lateral character lanes, trees and camera transforms are presentation. This does not migrate the separate legacy voxel/combat reducers or introduce new spatial mechanics. Client interpolation runs only between confirmed positions. Queued intents never create local skill effects.

Rendering, inspection and execution have independent lifetimes. Closing the world view removes its scene entities without pausing the run. A detached inspector has its own SDK identity and development session. Each view focuses one hosted run, and focus changes rebind only that view's grant. Creating another run retains earlier clocks, agent harnesses and evidence exports. Pause, resume and step operate on the focused run through existing authoritative controls.

The broker lists only runs created by that host process. Observer privilege is required for listing, focusing and creating runs. Participant projections remain server-filtered. The roster is refreshed every five seconds; full snapshots use the caller-specific SDK subscription. This is local developer orchestration, not a persistent experiment catalog or production role service.

See [world observer verification](../WORLD_OBSERVER.md) for controls, evidence and scope.
