# Verify core after rebasing C2

Branch `battle-notice-delta` rebased onto `origin/main` at `05ce2376`. This follows the [original November 13 run](2026-11-13-0620-battle-notice-delta.md). The authority, rules, shipped script, seeds and bindings at the rebased tip match the tree tested at `1a27fe3c`. The scenes used the default `world` seed, scoped perception, and the private Spark server `slop-c2-rebase-stdb` on port 3389 (SpacetimeDB 2.14.1). Doctor passed on each launch. No mind service or paid model ran.

| Scene | Result | Comparison |
| --- | --- | --- |
| `notice_delta` | 8/8 | 14,044 incremental looks and 25,251 skipped structures checked, with zero missing familiarity rows. All eight walkers had a `last_look` row. The scene placed 16 structures and recorded 99 notice lines, including 32 about remains. With the law off, zero structures were skipped and 17 notice lines were recorded. |
| `notice_inplace` | 6/6 | 12,678 comparisons with the full list and zero differences. The full list was built for 378 looks. There were 108 notice lines with the law on and 32 with it off, when there were zero in-place checks. |
| `familiar_dense` | 4/4 | 342 distinct crowd familiarity rows for 360 spawned actors. Across all people in view, 347 tellings matched 347 rows. |
| `notice_rate` | 4/4 | Over 12 seconds, 319.1 looks/s against 476.8 evaluations/s for 297 minded characters. |
| `first_sight` | 22/22 | Covered the law off and on, refused and owed thoughts, gaps, far and known figures, return, sleep and a shared cue request. |

The first `notice_delta` attempt stopped before its comparison assertions when `set_behavior` in scene teardown returned HTTP 504, with durability confirmation timed out and outcome unknown. The first `notice_inplace` attempt found zero differences across 13,661 comparisons. Its law-off window produced zero notice lines because three placements were outside the map and the other three were beyond the walkers' sight. The fixture now uses a separate strip within sight for that window. Both scenes passed on separate fresh worlds. The original attempts remain in the evidence.

- `just living-generate` regenerated 332 files using the 2.14.1 CLI in the trials container and left the tracked bindings unchanged. No scene ran on that service.
- The targeted authority tests passed 4/4, including the 400-start grouped-versus-full-scan comparison. `just living-check` passed through the build slot. The follow-up rebuilt and tested the game (128 passed, one ignored) and ran rules tests (327 passed, 16 ignored). The check at `05ce2376` accepted the recorded passes on identical inputs and exited 0.
- The [client privacy run](../../../verify-client/references/validation/2026-11-18-1926-battle-notice-delta.md) verified the new table over WebSocket and HTTP under three identities. This pass covers the C2 scenes and the affected client permission path. It does not cover existing-world migration, the full client suite, or sustained battle scale.
- `git diff --check` and the merge-tree comparison passed. The repository-wide validation filename check still flags main's `2026-11-18-outline-attr-1.md`.

Evidence is under `.local/living/verify/{core-c2-rebase,core-c2-rebase-notice-delta,core-c2-rebase-notice-inplace,client-c2-rebase,c2-rebase}/`. Cleanup paused each scratch database, confirmed SQL returned 404 after deletion and stopped the scratch server. The selected evidence archive is `~/slop-evidence/battle-notice-delta-rebase-2026-11-18.tar.zst`, with SHA-256, decompression and file-list verification.
