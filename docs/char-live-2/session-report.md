# Cora Stannard · char-live-2

[Final drawing and Bevy sheet](final/review-sheet.png) · [Five-second Middle walk](final/middle-walk.webm) · [Playable GLB](final/own-cora-live.glb) · [Editable Blender scene](final/cora-final.blend)

Cora’s face now has the measured jaw rise and nose and lip projections, and her front silhouette tapers to the measured chin width. The swept auburn locks reach the drawing’s front spread and depth. The coat now measures **(153,125,134)** against the drawing’s light heather **(156,126,135)**. The final near asset has **48,896 triangles**, six embedded clips and 15 expression keys. The character still uses one cloth material. [Asset counts](final/game-counts.json) · [Cloth comparison](final/cloth-review.jpg)

## Stage decisions and effort

Times are UTC on 19 November 2026. They include review and shared-host holds where indicated. Some evidence packaging overlapped the next stage. Token and billing totals were unavailable.

| Stage | Decision and outstanding defects | Time and effort |
|---|---|---|
| 1 · Targets | Reviewer approved the amended targets. The crown lift is an estimate because the hair hides the skull. The sheet records its wider tolerance. | 16:27–16:31 for the initial measurement and sheet, followed by the amended measurements and a fresh baseline replay. High. [Targets](stage-1.md) |
| 2 · Face profile | The first stop identified a cage limitation. After the generator gained two independent taper rows, the reviewer passed the front widths, profile and ear. The slight three-quarter chin corner carried into stage 3. | First cycle 16:34–16:53, two high fits and one xhigh. Resumed 17:10–17:25, two high fits and an independent replay. [Initial checkpoint](stage-2.md) · [Approved fit](resumed-profile/README.md) |
| 4 · Hair | GC passed front and three-quarter. The back and profile still read as evenly spaced parallel stripes, and the braid start is hidden. The GC selected fade 2.0 and accepted floor-relative ink calibration. There are 10 front and 8 three-quarter tips. | 17:23–20:54, including quiet windows and waiting for the ink shader. Two high fits and one xhigh. One private release build, two shimmer runs and two delivered 150-frame comparison walks. [Hair decision and evidence](hair/final/README.md) |
| 3 · Face shading | GC passed. The vertical cheek seam is gone, and the blush, rounded chin and mouth line read clearly. The four follow-up items are listed below. | 20:57–21:30 including the quiet window. Two high fits, one xhigh, a black-floor control and independent factory replay. [All three attempts and verdict](face-shading/README.md) |
| 5 · Cloth and final Bevy review | The eight garment measurements, retained hair and skin calibration, contract audit and factory replay pass. The GC passed the cloth and closed char-live-2. The GC judged that Cora reads as the drawing in every view. | 21:32–21:42, including final replay and walk verification. Two high dye fits. Reused the private release binary for the floor, material identification, daylight comparisons, orbit and 150-frame final walk. [Daylight measurements](final/cloth-measurements.json) · [Factory check](final/replay-check.json) |

## Cloth

The fixed 1600 × 900 daylight portrait uses the original coat and jersey centres from the laptop. The other six cloth windows use a front view that contains the full garment at a large enough scale for a 9 × 9 median. The material-ID render identified the cloth group at each window. The black control sets the existing cloth vertex RGBs to zero in a copy of the same GLB. All eight drawing targets clear their measured RGB floors. Each fit kept the absolute drawing targets and the original windows. The first dye fit passed seven garment windows. The lapel needed a second fit. [Drawing, baseline and both fits](final/cloth-review.jpg) · [Dye values and floor readings](final/cloth-dyes.json) · [Black portrait](final/black-cloth-portrait.png) · [Black full-body control](final/black-cloth-full.png)

| Garment | Drawing | Inherited daylight | Final daylight | Final minus drawing |
|---|---|---|---|---|
| Heather coat | 156,126,135 | 142,125,137 | 153,125,134 | −3,−1,−1 |
| Jersey | 118,50,43 | 132,53,42 | 120,50,44 | +2,0,+1 |
| Lapel | 152,131,140 | 187,164,165 | 144,123,134 | −8,−8,−6 |
| Apron | 214,190,167 | 215,190,163 | 215,190,166 | +1,0,−1 |
| Cuff | 193,171,167 | 204,180,167 | 199,175,169 | +6,+4,+2 |
| Trousers | 74,59,57 | 88,70,61 | 75,60,58 | +1,+1,+1 |
| Boots | 115,74,53 | 124,79,51 | 116,75,54 | +1,+1,+1 |
| Pocket | 149,126,135 | 159,130,139 | 152,128,137 | +3,+2,+2 |

The standard calibration measures 14 portrait patches. Six additional full-body patches use the same calibration tool’s per-channel median on the extra shot, giving **20 distinct passing measurements**. The side-by-side sheet includes the largest error on the lapel. Values were tuned on AMD Linux. [Standard calibration and contract audit](final/calibration-report.json) · [Original targets and registered windows](final/own-cora-live.calibration.json) · [Full-body measurement script](final/measure_cloth.py)

## Generator and hand work

- **Available to other heads.** The reviewed generator change at `297614b40` adds independent `jaw_taper` and `chin_taper` controls with zero defaults. Cora sets them to 0.24 and −0.27. Her jaw arc uses the untapered grid. The corresponding carry weights are 0.395 for jaw and 0.675 for chin. The nose, brow and lip depth stations, neck curvature and chin relaxation are still specific to the journaled fit. [Stage-2 fit](resumed-profile/README.md)
- **Available to other hair assets.** The client supports the handmade hair palette, two thresholds for three bands with a separate highlight mask, the ink distance field on UV0 and per-file screen-width/fade controls. The ink-field writer, shimmer test and calibration tools are shared. The floor-relative ink procedure is documented. Cora’s swept paths, lock ordering, per-lock normals and UVs, highlight shapes, ink guides and braid remain authored for this head. A reusable hair generator should emit those islands and masks plus the palette and ink range from a parametric cut. [Asset contract](../HANDMADE_HAIR.md) · [Hair and mask evidence](hair/final/README.md)
- **Face and garments.** Cora uses the existing generator’s cage, 15 expressions and procedural atlas, iris and tint. Her lid fit, cheek swatches, jaw normals, local nose and lip paint, and face-shadow thresholds are journaled per character. The eight cloth dyes are recorded as linear corner colours and can be reproduced on the fitted outfit. Applying them to a new garment requires mapping its dye groups and calibrating its own daylight areas. [Face paint](face-shading/paint_features.py) · [Cloth fit](final/cloth.py)

## Focused follow-up

The GC assigned the back-of-hair and face details to one follow-up session. Group the rear locks into a visible braid start at the nape. Vary their line spacing and weight, judging the crown and back at the 58° camera. On the face, give the slightly larger, more open eye a thick winged upper lid and visible lashes. Shape heavier, darker brows. Replace the pink nose-tip spot with one soft side shade and a small highlight. Resolve the horizontal collar-like neck band into a clean single jaw outline over a soft neck shade.

## Later garment work outside colour

Add the heather fleck and pocket stitching, model the apron’s full bow, and straighten the coat’s fall at the hips. The inherited rig defect also remains: the trousers break through the apron during gait and ground sitting. The final walk shows the garment in motion.

## Reproduction

From the repository root with the project’s lookdev clip library installed, run the journal against an empty output directory. The full replay starts from Blender factory startup. It rebuilds the editable scene, character GLB, both sidecars and all review and expression views. [Session journal](session.jsonl) · [Replay entry point](replay.py) · [Final audit](final/material-audit.jsonl)

```bash
BLENDER="$HOME/.local/share/slop-tools/build-bin/blender"
OCIO="$PWD/docs/char-live-1/standard.ocio" CHAR_LIVE_OUTPUT="$PWD/.local/cora-session-rebuild" \
  "$BLENDER" -b --factory-startup --python-exit-code 1 -P docs/char-live-2/replay.py
```

For a new daylight check, copy the final GLB, both PNG sidecars and the calibration JSON together to `living/game/assets/view/`. The first command renders the coordinates used by the full-body garment checks. The second reads the resulting standard report and verifies all eight registered cloth patches.

```bash
just living-game-calibrate view/own-cora-live.glb --also middle@0 --also 0:5:1.14:0.50
python3 docs/char-live-2/final/measure_cloth.py path/to/report.json
```

The independent factory run reproduced the packaged GLB and both sidecars byte for byte. All six final Blender orbit/play views and all 17 expression check images matched the checkpoint pixel for pixel. Every key moved and neutral returned exactly. Comparing the complete GLB with the approved stage-3 asset found one changed buffer view, the existing garment’s `COLOR_0`. The GLB JSON, other buffer views and both sidecars matched. All three embedded textures matched the fresh generator outputs. The final Blender material audit covered 26 materials and reported zero failures. The full audit log retains the two earlier checks that encountered Blender’s transient Render Result image and their subsequent recoveries.

The walk uses the embedded clip at 30 fps, five one-second cycles, with Cora at Middle, 12 m. The 58° camera turns slowly from 20° to 34.9°. Four decoded frames matched their native 1600 × 900 source stills pixel for pixel. The cloth pass reused the session’s release client. Its private Cargo build tree had already been deleted. The host had 59 GiB free at packaging. [Walk encode check](final/walk-check.json)
