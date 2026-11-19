# Verify-ui resident fixture isolation

Follows the [law-override client regression run](2026-11-19-2033-law-override-client.md). Gaze left resident #8 at (523.5, 697.5) under a 600-second wait, 1 m from cover's hedge eye. That resident became an unintended cursor or talk target while the intended hedge contact stayed hidden. This caused three cover failures per run.

Tested branch `verify-ui-isolation`, based on `origin/main` at `56a6ab457`, with the verification-only changes in this commit. Both worlds had a fresh scoped Cullet authority on a private local SpacetimeDB 2.14.1 container. The client was a native arm64 Bevy 0.20.1 release build. Both authority and client used a private Cargo target and the laptop build slot with `BUILD_SLOTS=1`. Generated assets came from local links. No mind service ran and no model was called.

Gaze, cover, looks, looks-band and the Brackenford camera scene save the body coordinates and graph for the residents they borrow. Cleanup runs on exit and attempts every resident restore even if a reducer refuses a call. Restoring at the source keeps cover's authored locations and the empty-cursor assertion useful without adding parking sites that could interfere with another fixture. The existing `place_at` reducer snaps to a free walkable tile and `set_behavior` reinstalls the graph with a fresh runtime and installation metadata. Gaze and cover also restore their epoch and effective sight-law values, including Cullet's authored defaults. Cover sets gaze off explicitly for its probes.

The owner SQL reads target only the borrowed resident IDs on `body` and `brain`. The existing admin reducers apply each placement and graph install in its own transaction. These are bounded setup and cleanup calls per scenario using the current schema, indexes, and subscription paths. [SpacetimeDB indexes](https://spacetimedb.com/docs/tables/indexes/) and [reducers](https://spacetimedb.com/docs/functions/reducers/).

Support moves only its player. Names reads existing resident positions. Grid and wheel-workplace move the player and choose structures by their clearance from current bodies. None of those Cullet scenarios parks residents.

## Native order runs

Each row used one invocation of `check.py --run RUN FIRST SECOND` against one fresh scratch database. Doctor passed for both worlds.

| Order | Scratch database | Gaze | Cover | Total | Evidence directory |
| --- | --- | ---: | ---: | ---: | --- |
| gaze → cover | `verify-ui-isolation-gc-212256` | 4/4 | 129/129 | 133/133 | `.local/living/verify/ui-isolation-gc-212256/` |
| cover → gaze | `verify-ui-isolation-cg-212256` | 4/4 | 129/129 | 133/133 | `.local/living/verify/ui-isolation-cg-212256/` |

In each directory, `order.out` and `ui/checks.json` report the assertions, `ui/gaze/gaze-proof.json` and `ui/cover-hedge/` hold the hedge evidence, and `actions.log` records the restore calls. In the forward run the server accepted the return of #8 near (528.18, 720.75) and the reinstall of its previous graph before cover started. All three formerly failing empty-cursor hedge checks passed. Both `cleanup.out` files confirm that the database name no longer resolves.

Offline, a driver exception triggered all restore calls and a refused placement still allowed the remaining restores. The sync matcher self-test and Python compilation also passed.

Camera, looks, looks-band and the other Cullet scenarios were checked by reading their fixtures. The live runs covered gaze and cover only. Hardware input, concurrent clients, mind service behavior, and performance were outside these runs.
