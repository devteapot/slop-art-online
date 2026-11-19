# fast_sight is private; the cleanup proof reads both deletion lines

Branch `fast-lane-frame` (commit `ba6fabec`, base main `97858bbb`) adds the private table `fast_sight` (docs/FAST_LANE_FRAME.md). `drive.py` `PRIVATE` now lists it.

- `client-flf-103257`: all 45 checks passed, including "private table visibility" (102 tables, scoped build). The run still exited 1 because its cleanup proof failed. The harness had deleted the database (HTTP 404 afterwards), but it logged "deleted … (name no longer resolves)". That is the line of the commitlog-archive path `trial_archive.finish`, added on main in `8d77a2fa`. `run.py` looked only for "(SQL now 404)". This is harness drift, not a product fault.
- `run.py` now accepts either line and repeats the HTTP 404 check itself.
- `client-flf2-103631`, after the fix: 45 checks passed, `cleanup-proof.json` `pass: true`, exit 0.

Only the scoped build was run. The `LIVING_PERCEPTION=open` build was not: `fast_sight` is private in both builds, and the perception switch does not touch it.

Evidence: `.local/living/verify/client-flf-103257/`, `.local/living/verify/client-flf2-103631/`, archived in `~/slop-evidence/fast-lane-frame-20261119.tar.zst`.
