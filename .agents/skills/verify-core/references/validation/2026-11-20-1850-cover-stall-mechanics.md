# Mechanics, four more iterations per arm (cover-stall)

This follows [2026-11-20-1656-cover-stall.md](2026-11-20-1656-cover-stall.md). The server is the same. Main is `f9b36cef`, and the branch is the merged `3e7ff54f` build (iterations 11–14; 1–10 ran on the `2b1bc8dc` build, whose activity code is the same).

| Arm | Iterations | 23 of 23 | Threat check | Other failures |
| --- | ---: | ---: | --- | --- |
| main | 14 | 14 | 14 of 14 | none |
| branch | 14 | 12 | 14 of 14 | iteration 6: "blows land on the yielded, and striking them is news" (no news row); iteration 10: "road, wall and gate built" (no gate) |

The threat flake did not show on either arm in 28 iterations. Neither branch failure recurred in iterations 11–14, and neither scene moves a body with `place_*` before its check. A rate of 2 in 14 against 0 in 14 does not settle, either way, whether the branch adds a flake. A longer series or the scene gate's retries would.
