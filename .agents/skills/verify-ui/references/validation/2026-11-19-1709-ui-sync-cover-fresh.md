# Cover rerun on fresh Cullet

Follows the [shared Cullet run](2026-11-19-1657-ui-sync-cullet.md) and the [island camera run](2026-11-19-1702-ui-sync-island.md). Branch `verify-sync-match` at `1454c821c` with the working-tree canopy diagnostic fix. Same native headless release client, read-only play-test 10 assets and local SpacetimeDB 2.14.1 server. A fresh scoped Cullet database isolated cover from gaze's resident placements. The authority built through `build-slot` with `BUILD_SLOTS=1` into the private target. No models ran.

`check.py --run ui-sync-cover-fresh cover` passed **129 checks, 0 failed**. The trunk, edge, brush and hedge fixtures passed 31 each. The canopy passed all five, including four exact `envs/cullet/hanger_tree/hanger_tree_2.glb` fade matches within their own sync segments. The intended resident stayed hidden in all three hedge checks, and no other resident was picked.

Evidence is in `.local/living/verify/ui-sync-cover-fresh/` with `check.log`, `ui/checks.json`, `ui/cover-canopy/client.log`, and receipts, dumps and stills for each drive. Both doctor checks showed advancing ticks and the Cullet laws. Cleanup deleted `verify-ui-sync-cover-fresh`. The run covered scripted headless visibility, targeting, Shade and canopy cutaway.
