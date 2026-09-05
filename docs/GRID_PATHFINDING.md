# Surveyed grid and mixed-controller experiment

Implemented prototype, 2026-09-05, rules `m1-8-grid.1`.

The [woodland scenario](../scenarios/woodland-pathfinding.json) has a 24×16 authoritative grid, walls with multiple gaps, six food sites and two characters. Mira uses the host's built-in LLM harness. Tovan uses a separate model-driven process connected through MCP. The browser is an observer with no in-world character; no idle human can starve in this experiment.

## Where pathfinding belongs

The controller chooses a destination or a sequence of intermediate destinations. A persistent behavior tree requests movement and decides when to interrupt or abandon it. The scripted movement skill chooses how to use a terrain query, pays energy, advances one cell per 250 ms under the current laws, observes the reached location and reports success or failure. The Rust authority supplies deterministic graph search and commits the scripted effects. Bevy draws confirmed positions and never computes authoritative movement.

`Scenario.map` is optional, so existing one-dimensional scenarios retain their geometry. Grid locations use the existing integer API: `cell = y * width + x`, with `(0, 0)` at the northwest corner. Conditions, destinations, beliefs, perceptions and sites refer to the same cell IDs. The renderer converts these IDs to actual 2D positions; smaller decorative tiles alone would not introduce navigation.

[spatial.rs](../simulation/src/spatial.rs) provides bounded breadth-first search with stable north/east/south/west tie-breaking. Uniform cardinal edges make this a shortest route. The scenario permits at most 1,024 cells and dimensions of at most 64. Search is recomputed at each eligible destination-bearing skill step. Its result is supplied as `navigation.next` and `navigation.remaining_steps`; scripts can consume or ignore that capability. Rust does not decide a character's destination, food strategy or danger response. Scripted energy, timing and interruption remain shared across controllers.

The walking script rejects walls and out-of-bounds destinations, and reports `no route to destination` for a walkable but disconnected target. Exhaustion produces a separate failure. It never teleports over a wall. Existing reactive guards keep their semantics: a guard that only holds at the departure point can still abandon a valid route. The prototype does not repair authored policies to produce a preferred outcome.

## What the characters know

This first experiment deliberately gives both characters the same **surveyed static terrain map**. The map contains dimensions and walls only. Resource amounts, dangerous sites and other characters' private state are not part of it. Both receive the same unverified report about food at cell 92; their identities and nearby observations still differ.

Route search uses only this survey. It does not consult hidden danger or optimize for safety. A controller can choose intermediate destinations to take another corridor. Default hearing and character visibility now use Manhattan distance in the grid, preserving the previous radii of two and one cells. Walls do not yet occlude hearing or vision. Characters may share a cell; collision reservations, moving obstacles and crowd navigation are not implemented.

For a later exploration experiment, replace the public survey with a character's known terrain and an explicit unknown-cell policy. Then compare routes based on learned terrain or danger costs. Weighted routing, fog of war, dynamic doors, route caching and a richer coordinate API should be driven by those use cases, rather than added to make this particular model survive.

## Controllers and comparison limits

Both controllers use the same participant operations and authoritative behavior/skill executor. Hosting an NPC does not grant it observer truth or a different movement implementation. Model reasoning remains outside the SpacetimeDB reducer.

The built-in harness has independent behavior, communication and learning loops (default waits after completion: 15, 21 and 27 seconds). The external pilot invokes a separate MCP process per turn, initially behavior and then communication/learning/behavior with 45-second gaps. This is a comparison of those current controller configurations, including their scheduling and prompts. It does **not** isolate the effect of transport or establish that one controller is more intelligent. Motives, personalities, model randomness, start positions and call timing also affect outcomes.

The runner accepts `--npc-runtime pilot` to reproduce the previous shared orchestration, and `--scenario` to select a different experiment. `SAO_HARNESS_MAX_CALLS` adds a shared limit across the host's three loops; it limits model requests without installing a survival policy. `--calls-per-actor` applies to both sides. Host exchanges are in `reasoning/`; external exchanges and receipts are in `live-inference/actor-2/`. Process success is not an accepted policy or reflection: inspect authoritative receipts.

For a controlled follow-up, match observations, prompts and schedules, repeat several seeds/model samples, and swap identities between controller assignments. For an exploratory run, differing behavior is evidence to inspect, not a ranking. Delayed evidence/revision handling and event-driven reconsideration remain separate open contracts from the earlier pilot.

## Run and verify

Build the module and both controller paths, then the browser client:

```bash
cargo build -p server_module --target wasm32-unknown-unknown --release
cargo build -p bridge --bin sao-dev-client --bin sao-agent-mcp --example participant_live_agent
cd client
env -u NO_COLOR trunk build --cargo-profile wasm-dev --dist dist-participant
```

From the repository root, with the existing local SpacetimeDB and configured provider credential:

```bash
python3 scripts/run_living_clearing.py \
  --output output/woodland-new-run --port 18920 \
  --minutes 5 --calls-per-actor 12
```

The default scenario is now `woodland-pathfinding.json` and the default NPC runtime is `host`. The world advances while models reason. The five-minute cap stops it; the observer host remains available afterward. Existing evidence directories are never overwritten. Human participation remains available in other scenarios that include character 3 with a human controller.

Executed verification:

- 54 simulation tests passed, including grid detours, no row wrapping, blocked/unreachable destinations, exhaustion, route continuation after reload, emergency interruption, 2D visibility and actor-free observer projection.
- 30 bridge tests, five host tests and one archive compatibility test passed. Native client checking and optimized authority/browser WebAssembly builds passed.
- [verify_spatial.py](../scripts/verify_spatial.py) created a separate real SpacetimeDB run. Both authenticated participants followed the same 26-step detour from cell 147 to 92 and paid 26 energy. An observer enrolled with no character and its attempt to submit a participant command was denied. Evidence: `output/woodland-pathfinding-authority-check/verification.json` and `snapshot.json`.
- The actual Bevy browser connected to the two-character run, rendered the grid and walls, hid participation, and reported no JavaScript errors. Initial camera framing was adjusted to fit the taller map.

The real authority check uses explicit fixtures and is labeled separately from fresh model behavior. It ran concurrently with the live pilot on the same local database service, so that pilot is not a clean performance benchmark.

## First live run

[Detailed comparison with the earlier clearing](WOODLAND_RUN_ANALYSIS.md) traces the new memory failure, retained-but-unapplied movement lesson, communication outcomes and controller budgets.

Run `sim-bevy-1788616907633` completed at 300.005 simulation seconds, with 4,364 authority updates and no script errors. Evidence is retained in `output/woodland-pathfinding-20260905/`: `pilot.json`, the run's `snapshot.json`, both controller journals, sampled observations and browser screenshots. The observer remains at `http://127.0.0.1:18920` while its host is running.

| Character | Controller calls | Final state | Observed behavior |
|---|---:|---|---|
| Mira | 12 host calls | Health 100, food 4, energy 37, cell 148 | Gathered eight food at cell 147, moved to adjacent cell 148, then mostly waited and ate. Two behavior proposals failed parsing; two learning operations were accepted and one rejected because newer subjective evidence existed. |
| Tovan | 5 external calls | Health 100, food 1, energy 43, cell 124 | Started toward cell 92, but a departure-location guard abandoned movement after one cell. His later model revision improved food recovery but retained the departure guard. Recorded 115 failed eating attempts without carried food. |

Both survived, and three model-authored learning operations were accepted across the two controllers even though the learning contract was not changed. Neither model completed the long journey to cell 92. The independent authority fixture establishes that routing works; this stochastic run establishes that both controller paths operated on the new map, while policy authoring still prevented sustained travel. It does not establish successful strategic navigation or superiority of either runtime. The 12-versus-five call count also shows why matched scheduling/budgets and repeated comparisons matter.
