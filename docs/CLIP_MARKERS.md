# Clip sidecars and foot-down markers

Every animated character file under `living/game/assets/lookdev/anim/` has a sidecar beside it,
`<file>.clips.json`, written by the clip bake ([`animate.py`](../living/tools/blender/animate.py),
`wolf.py`, `deer.py`). It holds each clip's length, loop, speeds and direction, and for every gait
each foot's contact windows (`contacts`) in normalised clip time. The client reads it for every
body ([`gait.rs`](../living/game/src/gait.rs) `of`): which gaits a body has (forward, back,
strafes, diagonals, crossovers), how fast each one travels, the shared phase they blend at, and
where IK plants a foot. A file without a sidecar falls back to `walk` and `run` (`Gaits::fallback`)
with no clip information at all.

[`marker_check.py`](../living/tools/marker_check.py) reads a file and its sidecar and fails when a
gait or a foot has no contact window, or when the floor guard made a clip jerk. `gen_anim.sh` runs
it on the VRoid bases, the wolf and the deer; `gen_person.sh` on the shared clip file
`own-clips.glb`; `render_set.py build` on a set's clip files.

## What went wrong (clip-markers, 2026-11-21)

verify-ui `look-walk` was 92/8 on dev-box's pinned render asset sets (`79072c65d37f`, and the same
anim files in `a7c606d204bb`): leg-turn easing, the steady leg offsets, and strafe and backpedal
playing plain walk. It passed 100/100 on the laptop's own bake. Two separate defects were found.

**1. The sets shipped `own-clips.glb` without its sidecar (the cause of the 8 failures).**
`bundle.py --with-clips` packed `lookdev/anim/own-clips.glb` alone, so every set from
`79072c65d37f` to `a7c606d204bb` has no `own-clips.clips.json`. Every composed person (an `own-*`
file or a type under `lookdev/types/`) takes its clips from `own-clips.glb` (`anim.rs`
`clip_file`), so on those sets every person drew with the fallback gaits: no directional takes
(strafe and backpedal play `walk`), no clip lengths or markers (the legs snap round, and they
settle square on the travel). The A/B, on set `a7c606d204bb` with one client
(`7f73c04c8`), island worlds, no model calls:

| Arm | `lookdev/anim` | `look-walk` |
| --- | --- | --- |
| A | the set as is (`own-clips.glb` `ee2b536e`, no sidecar) | 92 passed, 8 failed (the same 8) |
| B | the laptop's bake (`f74c80cc`, with its sidecar) | 100 passed |
| C | the set's own `ee2b536e` bake with its own sidecar, from dev-box's build worktree | 100 passed |

C shows that dev-box's bake was right; only its sidecar was missing. The fix: `bundle.py
--with-clips` packs `own-clips.clips.json` with the bake (a bundle fails when either is missing),
`render_set.py build` refuses a set whose clip files lack a sidecar or fail `marker_check.py`, and
`render_set.py check` prints a warning for a set without one (the verdict is unchanged, so the
pinned set keeps working until it is rebuilt).

**2. Two gaits lost their contact windows on the VRoid bases (`marker_check` failed).**
dev-box's `gen_anim.sh` ended in `marker_check` failures: `strafe_run_left_v48` had no left-foot
window on Sendagaya_Shino or Vivi, and `run_diag_br_v48` no right-foot window on Vivi. This was not
the library or `ONLY=present`: the picked takes (`strafe_run_left_v48_s2`, `run_diag_br_v48_s28`)
are byte-identical in the library home and dev-box's copy, and the same takes kept their windows
on the shared clip figure. It did not cause the `look-walk` failures (people use `own-clips`, which
had every window), but a VRoid base walking those gaits had nothing to plant a foot by. One bug in
`animate.py`'s `clean_contacts`, used both by the planting (`plant_feet`, on Kimodo's contact
labels) and by the marker detection (`foot_markers`, on the baked take):

- **A contact across a loop's seam was judged as two halves.** `clean_contacts` drops contacts
  shorter than two frames and fills gaps up to two, but on a loop it judged a run that crosses the
  seam as two runs. The same bug filled a long gap across the seam as if it were short, so some
  gaits had phantom contact frames at phase 0.
- **`run_diag_br_v48` on Vivi:** the baked right foot is down for frames 15, 16, 0 and 1 (four
  frames). Read as two runs of two, both were dropped, and the foot had no window.
- **`strafe_run_left_v48`** (the fastest sideways run, 3.2-3.3 m/s; its library note: 0 of 24
  takes pass every check): Kimodo labels the left foot's stance for two frames either side of the
  cut's seam. The planting dropped both halves, so the foot was never pinned and slid at
  0.33-0.67 m/s under the body. It was within 3 cm of the floor for 7 frames but still (under
  0.3 m/s) for only 2, which the marker detection dropped too.

Fixed: a loop is read from the start of a run, so no run crosses the end (rotation-invariant on
20,000 random loops; one-shots unchanged). With it the left foot of `strafe_run_left_v48` is
planted (slide 0.4 cm on Vivi) and gets its window (0.47-0.63 on both bases), and Vivi's
`run_diag_br_v48` right foot its own (0-0.24).

After the fix `marker_check` passes on both bases and on `own-clips` (0 errors; warnings 53 on
Sendagaya_Shino, 76 on Vivi, 35 on `own-clips`, against 55, 76 and 44 on dev-box's bake). Against
dev-box's bake, the fix moves the windows of 26-27 of each file's 39 gaits by a frame or two at
the seam, changes the planting of 18-19 (`L_fix_m`, `R_fix_m`, the floor guard's lift) and the
loop's start (`phase_shift`) of 8-9; the other clips bake as before.

## Rebuilding the pinned set

The fix changes the generator trees (`living/tools/blender`, `living/tools/characters`), so the
pinned set is stale against a main that holds it, and a rebuild is needed anyway. Rebuild it on
dev-box from that main as [TOOLING.md, "Building the render asset set"](TOOLING.md#building-the-render-asset-set)
says, steps 1 to 7, with the full clip library: step 1 (`just living-game-assets`) rebakes the
VRoid bases (`gen_anim.sh`), and step 5 (`ONLY=present LOD=near living/tools/blender/gen_person.sh
clips=man`) the shared clip file with its sidecar. `gen_anim.sh` and `gen_person.sh` now stop on a
failing `marker_check`, and `render_set.py build` refuses a set without `own-clips.clips.json`.

The files that change in a set: `lookdev/anim/own-clips.glb`, the new
`lookdev/anim/own-clips.clips.json`, and `lookdev/anim/vroid-{Sendagaya_Shino,Vivi}.{glb,clips.json,face.png}`.
The library home needs no change.
