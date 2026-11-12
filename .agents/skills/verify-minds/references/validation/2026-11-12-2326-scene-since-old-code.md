# Minds validation record

## 2026-11-13 scene-since: the case against the old code (Spark)

Follows `2026-11-12-*-scene-since.md`. Branch `scene-since`, after main was merged in (`48fbc811`). Server: the trial container `slop-trials-stdb` (127.0.0.1:3320), on scratch `verify-minds-*` databases, with the fake model.

The old code was this branch with `living/authority/src/mind.rs`, `living/mind/src/mind.rs` and `living/mind/src/mind/animal.rs` taken from origin/main. This is the code without the fix, uncommitted, in the same checkout and target dir.

**First version of the case** (as committed in `1299d786`), on the old code: `minds-sceneold1` fails, on `rest_scene_taken_when_handed_on` only.
- The scene checks passed by chance. The think reply's routine rework ("reworks routines: current plan") merges an already-pending "I finished my plan." into the request, which refreshes its scene. That landed at 723.717 s, 0.4 s before the install, with the player already moved.
- The case's guard read only the arrival times of the lines that stayed, so it did not see this merge.

**Reworked case:** it holds the compile 8 s (Gwil's gap was a compile, about 5 s) and moves the player during the compile, after that merge. A merge between the move and the install now makes the case inconclusive, read from the row's `updated_ms`.
- `minds-sceneold2`, old code: **fails, all three checks.** The handed-on row and the next prompt place the player 1.4 m northeast while they stand 30 m off. The row's `updated_ms` is the last merge, 15.3 s before the install.
- `minds-scenenew2`, the fix restored (`git checkout HEAD`, rebuilt): **passes.** The handed-on row's `updated_ms` equals the install time, and the player is not in its scene or in the next prompt's.

Not rerun: the other cases of `minds-scenesince1` (2026-11-12 record). The change since then is in this case's script only.
