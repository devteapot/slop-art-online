# char-port-2 · measure-view: an orthographic view for 2D measures

**Why:** dev-box measures faces and hair from 2D renders against reference drawings. The portrait camera (`0:8:0.36:0.88`) is a perspective camera about 1 m away, 8° above the head. It bends those measures, and S7 found a gap it could not explain: on adult-f-b the 2D face/eye ratio was about 11.5% under the 3D slice. S7 put 4% of that down to perspective and left the other 7% unexplained ([S7 bind README](../s7/bind/README.md) §3, on `origin/char-port-2-s7`). Before this branch, the 2D render path had no known-answer test.

**What this adds:**
- **The measuring view:** a level orthographic camera in the asset view with exact, recorded pixels per metre.
- **A known-answer test:** a head of known size through the real client, with the outline and ink on.
- **The gap explained:** S7's gap on real types, taken apart.

## The measuring view

Turn it on in the asset view (`LIVING_GAME_VIEW=…`, `view.rs`):

| Env | Meaning |
|---|---|
| `LIVING_GAME_VIEW_ORTHO=1` | Every shot through an orthographic camera, level (pitch 0). The yaw is the shot's: `front` (the default shot in this mode) is dead front, the model's forward (a hand-made file's declared `forward`; the usual turn otherwise). The shot's pitch, zoom, aim and camera stop are ignored. Its clip and time are kept, so combine it with `LIVING_GAME_VIEW_CLIP=bind` for a square head. |
| `LIVING_GAME_VIEW_ORTHO_M=<m>` | The frame's height in metres. Pixels per metre is the frame's height in pixels over this, exactly (1600x900 and 0.30 give 3000 px/m). The default is the model's height × 1.1. |
| `LIVING_GAME_VIEW_ORTHO_Y=<m>` | The height of the frame's middle above the ground. The default is the model's middle. Across, the frame's middle is the model's middle. |

- **What each photograph records:** `NN-<shot>.ortho.json`, also listed under `ortho` in the model's `report.json`:
  - `px_per_m`, `frame_px` and `frame_m`;
  - `camera_height_m` and `camera_m` (the camera's place);
  - `frame_middle_m` and `ground_row_px`;
  - `yaw_deg`, `pitch_deg` (always 0), `standoff_m`, `near_m` and `far_m`.
- **Pixel coordinates:** a height y (m) lies on row `ground_row_px − y · px_per_m`. A point x m right of the middle lies on column `frame_px[0]/2 + x · px_per_m`. Rows count from the top edge and columns from the left, and a pixel's middle is at +0.5. The log line is `view: <file> <shot>: orthographic, <k> px/m, frame <m> m high, camera <y> m up`.
- **Lines:** the outline and the ink stay on, as in play. `LIVING_GAME_PERF=nooutlines` turns off the shell outline and `noedges` the finishing pass (its lines, rim and film), to measure what each adds. Both are the existing measurement switches (`perf.rs`).
- **Measuring views only:** without `LIVING_GAME_VIEW_ORTHO` nothing changes. Play's camera and every default are untouched (pixel identity, below).
- **What changed in the client:**
  - **The finishing pass** reads an orthographic depth as distance. `post.rs` sends −far, and `edges.wesl` `dist` turns the linear depth back into metres. Without this it read every pixel as 0 m away.
  - **`lookdev::far_models`** counts an orthographic camera's pixels per metre. Without this every character drew its far model in the measuring view.
  - Both paths are unchanged for a perspective camera.

## The known answer

[ortho_shape.py](../../../living/tools/characters/ortho_shape.py) writes the subject, a hand-made character file (`forward: "+Z"`, slots `skin` and `eyes`):
- **The head:** an ellipsoid 0.150 m wide, 0.200 m deep and 0.240 m tall, its middle at 1.55 m. Its equator and its ±x and ±z meridians are vertices, so its widest outline is exact.
- **The eyes:** two dark spheres 0.064 m apart, standing 9.3 cm in front of the head's widest outline.
- **The neck:** a cylinder down to the ground.

[ortho_selftest.py](../../../living/tools/characters/ortho_selftest.py) draws it through the real client and holds the pictures to the known sizes:

```bash
CARGO_TARGET_DIR=<your target> python3 living/tools/characters/ortho_selftest.py [--binary BIN] [--out DIR]
```

- **The run:** 1600x900 at 3000 px/m, in the bind pose, each photograph with its plate (`LIVING_GAME_VIEW_PLATE=1`).
- **The measure:** a pixel is the model's where it differs from its plate by more than half the model's own contrast, the edge's 50% crossing.
- **Dependencies:** none beyond the Python standard library. It writes `selftest.json` and exits 1 on any failure.
- **Where the subject goes:** `living/game/assets/measure/` (git-ignored). The binary must be built from the same checkout.

Results ([selftest.json](selftest.json), this branch's binary):

| Run | Front width | Side depth | Head's top | Eye spacing |
|---|---|---|---|---|
| bare (`nooutlines,noedges`) | 450 px = 0.15000 m (**0.00%**) | 600 px = 0.20000 m (**0.00%**) | 1.6700 m (0.0% of the height) | 0.06416 m (+0.25%) |
| outline off, ink on | 450 px (0.00%) | 600 px (0.00%) | | 0.06409 m |
| as in play (both on) | 454 px = 0.15133 m (+0.89%) | 603 px = 0.20100 m (+0.50%) | | 0.06409 m |

- **The outline's contribution:** the shell outline adds 2 px a side at the 50% crossing: +4 px across the front, +3 px across the side (sub-pixel). That is a fixed pixel count, not a length.
  - At 3000 px/m it is within 1%. At a coarser scale it is not: subtract 4 px, or measure with `LIVING_GAME_PERF=nooutlines`.
  - It lies outside the silhouette, so a measure of the model's own colour (skin, hair) is untouched.
- **The ink's contribution:** the finishing pass draws a 1 px line outside each edge. It darkens the background by about 20% (34 of the skin's 74 levels against the plate), below the 50% crossing, so it adds 0 px to the width.
- **The eyes:** read 0.25% wide. Their centroids are of the visible part of spheres half sunk in the head.

## Where S7's gap comes from

### On the known subject

The old portrait reads the width over the eye spacing 7.7% low level (`0:0`) and 8.1% low at pitch 8 (`0:8`). The orthographic frame reads it within 0.25%.

- **The mechanism:** the eyes stand 9.3 cm nearer the camera than the outline. At about 1 m, perspective magnifies them by about 10% against it.
- **What it depends on:** that share depends on the face's own depth. A real face's cheek outline lies nearer its eyes.

### On real types

[face_rows.py](face_rows.py) draws a type in bind with no hair and its ear-ID copy, in three frames:
- the portrait level and at pitch 8;
- the measuring view at 1500 px/m.

It measures each frame with S6b's 2D rule (`drawing_spread.face_render`) and cuts the type file in 3D with S6b's `measure3d` at the same heights. The pinned render set is `a7c606d204bb` (S6b's bundle, `port: none`). Its men are not S6b's narrowed `fp21j` men, so their values differ from S7's; the women and children are the same types.

| Type | 2D rule, portrait level | portrait pitch 8 | measuring view | perspective's share | Row: drop under the eyes (file mm) | 2D in the measuring view | 3D cut, ears excluded | 2D against 3D |
|---|---|---|---|---|---|---|---|---|
| adult-f-b | 1.519 (S7: 1.500) | 1.375 (S7: 1.343) | **1.576** | +3.7% | 3D rule, 30.0 | 1.785 | 1.787 | **−0.14%** |
| | | | | | 2D rule, 42.1 | 1.578 | 1.559 | +1.2% |
| adult-m-a | 1.689 | 1.564 | **1.723** | +2.0% | 30.0 | 1.784 | 1.788 | −0.22% |
| | | | | | 41.1 | 1.723 | 1.726 | −0.22% |
| child-u-a | 1.522 (S7: 1.487) | 1.360 (S7: 1.379) | **1.561** | +2.6% | 30.0 | 1.798 | 1.749 | +2.8% |
| | | | | | 43.6 | 1.560 | 1.534 | +1.7% |

- **The scale between view and file metres:** the eye spacing on the measuring frame over the file's. It agrees with the eye line's height over the file's to 0.3%: 0.9128 against 0.9104 on adult-f-b, 0.6955 against 0.6940 on the child.
- **Perspective's share:** 2.0–3.7% of the ratio, as S7 estimated. Pitch 8 takes a further 7–11% off (level to pitch 8: −9.5%, −7.4%, −10.6%). The measuring view removes both.
- **The remaining "7%" is the row, not the camera:**
  - **The two rules cut at different heights.** The 2D rule puts its cheek row `CHEEK_DROP_H × spacing / EYE_SPACING_H` under the eyes, from the drawing's proportions: 41–44 mm in the file's metres. The 3D rule (`face_width.py`) cuts 30 mm under the irises.
  - **The face narrows fast there:** about 1.6% of the ratio per millimetre. In the measuring view, at the same height, 2D and 3D agree to −0.1 to −0.2% on the adults and +1.7 to +2.8% on the child (the ear's front edge against the whole cut).
  - **S7's 1.695** is the 3D cut in front of the ear's front edge at the 3D row. It compares 2D at about 42 mm with 3D at 30 mm.
  - **Adding it up on adult-f-b:** 1.519 (portrait) → 1.576 (orthographic, +3.7%) against 1.559 (3D at the 2D row, +1.2%).
- **Picture:** [rows-adult-f-b.png](rows-adult-f-b.png) shows the measuring frame with the two rows: the 3D rule's above, the 2D rule's below, under the ear lobes.

**What it means for S7:** measure in the measuring view at pitch 0, and compare 2D and 3D at one height. Either cut the 3D at the 2D rule's row, or move the 2D row to 30 mm in file metres, which is `0.030 × scale × px_per_m` pixels under the eyes. Which row matches the drawing is the GC's question, not a measuring one.

## Pixel identity, and play unchanged

- **Without the env, main's binary against this branch's:** 36 of 36 deterministic frames byte-identical.
  - **The frames:** a composed person (adult-f-b, `bob`) at `idle@2.0` portrait and front, `idle@1.0` three-quarter, `walk@0.3` side, `near@0` and `game`; the KayKit Knight's 24 clip frames; the fixture's six default views.
  - **Excluded:** 12 view shots of models whose animation runs freely during the still (Vivi's procedural sway, the Knight's clip). They differ between two runs of main's binary too.
- **verify-ui on a scratch island world (`verify-ui-vo-i`, deleted):** `hair` 11/0, `camera-lod` 15/0 and `camera-lod-lol` 8/0. Record: [.agents/skills/verify-ui/references/validation/](../../../.agents/skills/verify-ui/references/validation/).
- **Unit tests:** `cargo test --release -p living-game` 215 passed, 0 failed, 1 ignored, with four new `view::tests` and the extended far-model test. `living-rules ui::` 38/38.

## Not covered

- **dev-box's render pass:** this is a rendering branch, and the pass is needed before merge.
- **The other 18 types:** only adult-f-b, adult-m-a and child-u-a were taken apart.
- **S7's own type set** (`fp21b`): the women and children match it; the men here are unnarrowed.
- **Hair spreads in the measuring view:** not re-measured. S7 found the pitch barely moves them (±0.02).
- **A real window:** runs were headless.
