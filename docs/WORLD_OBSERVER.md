# World observer and parallel sessions

The foundation client now opens a full-window top-down 2D Bevy world. Characters, resource quantities, hazard coloring and death poses come from the caller's authoritative simulation snapshot. Trees and lateral character lanes are presentation of the existing one-dimensional survival core. The voxel/3D client, model assets and physics/meshing dependencies are removed; legacy server reducers remain outside this client.

## Controls

- **W / A / S / D** and **right drag** pan the map; **wheel** zooms. **F / Follow** tracks the selected character. Observer arrow keys also pan.
- Click a character to select it and open its **Mind / Policy / History** overlay. **I / Inspect** toggles it; **O / Labels** toggles world callouts. Callouts retain event IDs and ticks; they describe the latest available outcome, not a newly predicted action. Recent authorized speech appears beside its speaker.
- **Sessions** opens the roster. **New parallel session** creates and focuses a paused run without stopping earlier runs. Choose an existing run to focus it. **Step / Resume / Pause** affect only the focused run.
- **Close world** removes the rendered scene while keeping inspection and the server session available. **Peek into world** restores the focused scene. **Detach** opens an independent inspector tab (or a second native client process); allow the site's popup if the browser blocks it. The inspector can choose a different session and peek into that world. Closing either view does not stop server execution.
- **Participate as You**, under Sessions, uses the existing owned human. Click ground or use arrow keys to request movement; Gather, Eat, Rest and free-form speech remain authoritative skills. Enter starts/sends speech; Escape cancels entry. World changes appear after execution, not when an intent is submitted.

The default `cargo run -p client` and `just client` commands now open this 2D client. The `foundation` feature remains available for existing browser scripts.

Build/start with the [browser runbook](BEVY_BROWSER_CLIENT.md). Restart the Rust development host after updating it; the new UI needs `/api/runs` and `/api/focus`. No schema or binding regeneration is required. The host's initial run and each new run start paused; fixture startup makes no model calls.

## Boundaries

The browser and native client share scene and UI code. Rendering is detachable from execution; it is not an additional simulator. Participant sites are remembered observations with their observed tick, hidden hazards are absent, and other private minds are never part of the projection. Speech perceptions are associated with the reported speaker rather than the observer of the memory.

Hosted sessions are isolated runs in the host's database. Their clocks and agent harnesses continue independently of which view is open. The roster covers runs created during this host process and polls status every five seconds. Every hosted run is exported to its own evidence directory; restarting the host creates a new database and roster while preserving old files and databases. This is not yet discovery of arbitrary externally launched experiments.

The scene uses flat tiles and simple pixel sprites and is desktop-sized. Foundation spatial rules remain one-dimensional. Native interaction, production authentication, broad mobile/accessibility coverage and legacy world migration are outside the verified slice.

## Earlier 3D verification — 2026-09-05

- Native foundation check, browser WASM/Trunk build and Rust host build passed.
- 35 simulation/projection tests and four host enrollment tests passed.
- `BEVY_DEV_URL=http://127.0.0.1:18892 cargo run -p bridge --example world_session_probe` exercised the real broker, SDK and database: two concurrent clocks, separate view grants, retained old sessions, independent pause, focus persistence, unknown-run rejection and participant denial of roster/focus/new-run operations. Both runs were left paused. Final evidence runs: `sim-bevy-1788605616048` and `sim-bevy-1788605635015`, under `output/world-observer-dev`.
- `scripts/check_bevy_host.py` passed the exact-origin and HttpOnly session boundary checks.
- Chromium with WebGL2/SwiftShader rendered the actual 3D client without browser errors. Clicking Tovan opened his overlay over the world; Detach opened a separate inspector focused on the originating run. Human arrow-key movement stayed at position 0 until the observer stepped the authority, then rendered position 1 at tick 3 with matching completed-move event #72 in `sim-bevy-1788605635015`. Physical keyboard speech `Hi` was queued while paused, then emitted at tick 4 as event #99 and rendered beside You. Local screenshots are under `output/local-dev/world-*.png`.

The probe creates one additional fixture session and is intended for an isolated fixture host; it does not invoke models. These checks establish presentation and session isolation, not new model-quality claims.

## Top-down 2D verification — 2026-09-05

The default client and explicit `foundation` feature pass native checks. The WebGL2/WASM build passes. All 69 simulation, bridge and host tests pass with the updated lockfile. The client dependency tree contains no `bevy_voxel_world`, `avian3d`, `fast-surface-nets`, `bevy_pbr` or `bevy_gltf`; the old GLB assets and legacy client modules are deleted. See [ADR 015](adr/015-top-down-behavior-lab.md).

Chromium rendered the flat map and pixel sprites without browser errors. Clicking Tovan opened his mind overlay. Creating a session through the UI retained previous paused sessions. In `sim-bevy-1788606506471`, Gather at camp stayed pending while paused and completed as event #59 at tick 2: camp food changed from 3 to 2 and the human's carried food from 1 to 2, reflected in the map and trace overlay. Screenshots are in `output/local-dev/2d-*.png`. This used an authored fixture and made no model calls. Native window interaction remains untested.

A ground click on the trail left the human at position 0 while paused; after stepping to tick 3, completed move #82 placed the sprite at position 1. Camera pan/zoom and detachable inspection remain presentation-only.
