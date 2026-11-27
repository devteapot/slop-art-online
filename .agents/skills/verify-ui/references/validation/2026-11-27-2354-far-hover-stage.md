# Far hover staging on the island

The island version of `check.py far` puts the player on the existing open-grass fixture before the driver places and holds the subject. At the arrival, a passing resident could overlap the pointed subject and correctly win the screen-space pick. The scene still tests the same subject, waits, hover labels, authority speech target and sent line. [Scene staging](../../scripts/check.py) · [Talking](../../features/talking.md)

The new sync uses the existing admin `place_at` reducer on the scratch player's body. The driver then uses its usual `place_at` and `set_behavior` calls for the subject. No schema, subscription or gameplay change is needed. [SpacetimeDB reducer documentation](https://spacetimedb.com/docs/functions/reducers/)

## Runs

- Branch `far-hover-stage`, fixture commit `c62682fde57df013006a790c6ae6bda159f6d69f` on `origin/main` `e29ce862d1134115d8e4d45111162927967f11f9`.
- Merge arm added `lookdev-4c` `d2decb27ddafd4ef071ebad6214b8985773fe878` without committing. Tested tree `933dc756ce7ff9927afeb68f03cf12516e65cff0`.
- Dev-box, standalone SpacetimeDB 2.14.1, scoped island worlds, pinned render set `eab260ef1df8`. Release client at High / 100%. Each fresh-world trial used a new island and ran `check.py --run RUN far`. Odd runs had no added load. Even runs ran alongside eight CPU workers.

| Build | No added load | With added load |
|---|---:|---:|
| Main with staging | 10/10 | 10/10 |
| Main with staging and 4c | 10/10 | 10/10 |

On the reused 4c island, `hair` (11/11), `seat` (20/20), `camera-faces` (3/3), and `camera-lod` (23/23) ran in gate order before `far` (11/11). The gate log scan found no shader, asset, stale-set or panic errors. At all three hover stops in each run, the subject was the only outline containing the cursor and was the selected character. The recorded placements remained on the intended sides of the 4 m cutoff.

Evidence lives under `.local/living/verify/`. Fresh trial directories are `ui-sol-far-stage-main-1` through `ui-sol-far-stage-main-20` and `ui-sol-far-stage-merge-1` through `ui-sol-far-stage-merge-20`. Each retains `ui/checks.json`, the scene placement calls, picker dumps and screenshots under `ui/far/`. The reused run is `gate-sol-far-stage-reused-island`, with `ui/checks-far.json` and the preceding cases' results. The `sol-far-stage-study` directory holds the per-run summary and scratch-server logs.

This validation covered the island's headless UI at native render scale. Other seeds, reduced render scales and the remaining merge-gate groups were outside this run.
