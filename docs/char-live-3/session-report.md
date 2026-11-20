# Cora Stannard · char-live-3

[Final drawing and Bevy sheet](final/review-sheet.png) · [Five-second Middle walk](final/middle-walk.webm) · [Playable GLB](ink-batch-2/own-cora-live.glb) · [Eyes ink map](ink-batch-2/own-cora-live.eyes.ink.png) · [Editable Blender scene](ink-batch-2/cora-final.blend)

char-live-3 closed the five follow-ups char-live-2 left on Cora:

- **Back of the hair:** the rear locks are grouped and run into a visible plait from the nape.
- **Eyes:**
  - the eye is slightly larger and more open;
  - the iris is wider;
  - the lid is a bold winged ink band with a lash fringe;
  - there is a short outer lower lid.
- **Brows:** heavier and darker, in the drawing's shape.
- **Nose:** the shade is narrowed against the underside, the highlight is now a tip glint, and the nostrils are two soft filled shapes.
- **Neck:** the shade starts right under the jaw, and the collar-like band is gone.

The lid, lower lid and brows are drawn by the general ink profile ([HANDMADE_INK.md](../HANDMADE_INK.md), v1.2). It reached main during the session; the strokes sit on carriers that are primitives of the face mesh, so blink, talk and the brow keys move them. The jaw outline was dropped: it needs a view-dependent technique (follow-ups below).

**The final asset:**
- 49,702 triangles (of 50,000), six embedded clips and 15 expression keys;
- all 20 colour checks pass;
- the contract audit has 0 errors and 0 warnings, and 12 material audits have 0 failures.

[Final calibration](final/calibration-report.json) · [Cloth windows](final/cloth.json) · [Material audits](final/material-audit.jsonl) · [Counts](final/game-counts.json) · [Closing replay check](final/replay-check.json)

## Item decisions and effort

Times are UTC, 19–20 November 2026. They include gate and disk waits where noted. Token and billing totals are unavailable.

**Models.** Items 1, 2 (first fit) and 4 (first fit), and the drawing measurements for the ink batch, ran on GPT-6.2 Astra (Codex). Astra then reached its usage limit; it is unavailable until 25 November. Under the owner's fallback rule the work continued on Claude Opus 5.5 from the last checkpoint: both ink attempts and this close.

| Item | Verdict and recorded defects | Time, effort, attempts, model |
|---|---|---|
| 1 · Back hair and plait | **Passed.** The play-camera defect is fixed: the plait reads below the nape at both 58° play stops, within 0.5 px of the drawn width (7.8 px Near, 5.1 px Middle). Recorded: plait luma about 25% over the drawing (Near 86 vs 69, Middle 89 vs 69); close-view segment gaps and harsh nape and tie transitions. [Grouped locks](back-hair/README.md) · [Plait](back-hair/plait/README.md) | 21:44–22:02. High fit 1 (archived), high fit 2 (grouped locks, kept), then xhigh fit 3 on the plait alone. Three attempts, Astra. |
| 2 · Eye frame: iris, opening, lid | **First fit passed** for the iris (widened 27% along its tangent) and the opening. Its lid stroke failed: heavy, uniform and jagged. The lid then waited on the general ink profile; the [hook proposal](eye-frame/lid-ink-proposal.md) became HANDMADE_INK v1.2. The ink batch rebuilt the lid; attempt 1 was too light and thin. **Attempt 2 passed:** in front it matches the drawing's width (7.5 vs 7.3 px) and darkness (0.59 vs 0.59). Recorded: about 25% over the drawing at three-quarter. The outer lower lid **passed** in attempt 1. [First fit](eye-frame/README.md) · [Ink attempt 1](ink-batch/README.md) · [Ink attempt 2](ink-batch-2/README.md) | First fit 22:16–22:35, high, Astra. Lid ink attempt 1 at high and attempt 2 at xhigh, Opus. |
| 3 · Brows | **Passed** in ink attempt 1: heavier and darker, in the drawing's shape (thickest 8.5 / 8.0 px against 7.7 / 8.0, front / three-quarter). Recorded: blunt inner ends. | One attempt, high, Opus, inside the ink batch. |
| 4 · Nose | **First fit accepted for colour**: the pink spot is replaced by one soft side shade and a highlight. Ink attempt 1 narrowed the shade, cut the glint and drew nostril strokes, which read as a squiggle. **Attempt 2 passed:** two soft filled crescents painted on the face, matching the drawing's area (17 / 19 vs 16 / 15 px) and place from the tip. Recorded: slightly light (about 22 levels at the core) and flat (3–4 px tall vs 5). [First fit](nose/README.md) | First fit 22:39–23:00, high, Astra. Ink attempt 1 at high and attempt 2 at xhigh, Opus. |
| 5 · Jaw and neck | **Neck kept:** the shade holds full strength from the jaw to z 1.422 m, fades by 1.385 m and spans the neck's width. The collar band is gone, and the upper-neck patch reads (189, 118, 88) against the target (192, 121, 90). **Jaw line dropped** by the general coordinator without spending an attempt: a static carrier can't follow a view-dependent silhouette, and in both views it read as a seam or mask edge. | One attempt (the batch), high, Opus. |
| Ink batch attempt 1 (items 2–5) | See the items above. [Package](ink-batch/README.md) | 00:24–02:37: high, Opus; one combined attempt. Includes the client build, about 15 min waiting on another worker's gate, and the handmade-ink merge and re-check. |
| Ink batch attempt 2 (lid, nostrils) | Both passed. [Package](ink-batch-2/README.md) | 02:38–03:15: xhigh, Opus; the last attempt for both. |
| Close | This sheet, the walk, the factory replay and audits on merged main (`f53d46700`), and this report. | 03:16–about 03:35: high, Opus. |

## What is now parameters and what is per-character hand work

**Parameters that generalise to other heads.** Each was journaled with its values, ready for the back-port.

- **Eye frame:**
  - iris horizontal scale along its own tangent;
  - outer-canthus lift;
  - wing rise and reach;
  - band thickness;
  - lash length.

  [eye-fit.json](eye-frame/eye-fit.json)
- **Ink carriers (strokes registered from drawing traces).** [design.py](ink-batch/design.py) · [carriers.py](ink-batch/carriers.py) · [design2.py](ink-batch-2/design2.py)
  - **Registration:** through canthus and pupil similarities, in eye or face units.
  - **Lid:** placed on the skin's own eye-opening edge, its ink edge 0.5 mm into the opening, with the drawn width profile, ×1.25 over the outer two-thirds and the wing. A lash fringe runs along the top: a sawtooth with spacing, length, lean, root width and envelope.
  - **Carrier geometry:**
    - lifted along the view, with a harmonic fill over openings;
    - smooth polynomial spines, so rows never fold;
    - mapped by their own lengths;
    - bound to the triangles they ride;
    - a clearance pass for every morph target;
    - reach of range plus margin;
    - pinned map islands, so a passed stroke keeps its texels.
  - **Lid core:** an opaque core inside the lid keeps its value at play distance, where the ink fades.
- **Ink colour calibration:** floor-relative, at a close shot. [ink_calibrate.py](ink-batch/ink_calibrate.py)
- **Measures against the drawing at 440 px:**
  - stroke widths across the stroke's own direction, by recolouring each ink in turn ([widths.py](ink-batch/widths.py));
  - the lid's band width and mean darkness ([lidweight.py](ink-batch-2/lidweight.py));
  - the nostrils' area, place and value ([noseweight.py](ink-batch-2/noseweight.py)).
- **Nose paint:**
  - the tip landmark;
  - flank curve and half-heights;
  - pigment;
  - glint place and radii;
  - nostril crescents from drawn centrelines, measured on the face through texel-to-design rasterisation, with gain, soft edge, value ratio and fill.

  [paint.py](ink-batch/paint.py) · [nostrils.py](ink-batch-2/nostrils.py)
- **Neck shade:** full height, clear height, side rise and side fade, with a strength calibrated to the drawing's patch.
- **Plait:**
  - three-strand over/under phase;
  - nape attachment;
  - upper radius;
  - taper and section;
  - width gain from the nape to the tie;
  - the crest-shadow dye;
  - a curved highlight per segment.

  [Plait fit](back-hair/plait/fit.py)
- **Grouped rear locks:**
  - crown and side guide stations, normalised by head size;
  - parent and companion widths;
  - staggered join heights.

  [Locks fit](back-hair/fit.py)

**Per-character hand work, journaled but not yet general:**
- Cora's lock layout, the plait's segment choices and its highlight shapes.
- The choice of which drawn strokes become carriers and which are painted.
- The drawing's per-stroke landmarks (canthi, pupils, nostril traces).
- The per-stroke width gains, which came from Cora's measured portraits (brow 1.0, lower lid 1.3, nostrils ×2.3 painted).
- The decision to drop the jaw line.

## Follow-ups

1. **View-dependent strokes (client):**
   - **The lid at three-quarter** is about 25% over the drawing. A stroke on the surface can't thin as the lid turns toward the camera.
   - **The jaw outline**, dropped. It needs a view-dependent edge technique: a static carrier can't follow a silhouette.
2. **Brows:** the inner ends are blunter than the drawing's rounded start.
3. **Nostrils:** slightly light (about 22 levels at the core) and flat (3–4 px tall vs 5).
4. **Plait luma:** about 25% over the rear drawing at Near and Middle (86 and 89 vs 69). Adjust one band value.
5. **Plait close view:** harsh segment gaps, and harsh transitions at the nape and the tie.

The char-live-2 garment follow-ups still stand: the heather fleck and pocket stitching, the apron's bow, the coat's fall at the hips, and the trousers breaking through the apron in gait and ground sitting.

## Reproduction and the closing checks

The journal replays from the approved char-live-2 scene, from Blender factory startup. Attempt 1's records are archived; [ink-batch-2/fit.py](ink-batch-2/fit.py) replaces them.

```bash
BLENDER="$HOME/.local/share/slop-tools/build-bin/blender"
OCIO="$PWD/docs/char-live-1/standard.ocio" CHAR_LIVE_OUTPUT="$PWD/.local/cora-live-3-rebuild" \
  "$BLENDER" -b --factory-startup --python-exit-code 1 -P docs/char-live-3/replay.py
```

**On merged main (`f53d46700`, staged genesis landed):**

- **Factory replay:** it rebuilt the GLB, the face and hair sidecars, the calibration JSON and the eyes ink map byte for byte against [ink-batch-2](ink-batch-2/). It takes about 45 s.
- **Material audits:** all 12 passed.
- **Release client:** rebuilt from that tree with the pinned rustc 1.99.1, it is bit-identical to the client that rendered attempt 2's package.
- **Calibration:** 14 of 14 patches pass, plus 8 of 8 cloth windows, which are identical to the previous packages.
- **Contract audit:** 0 errors, 0 warnings.

[Replay check](final/replay-check.json)

**The final sheet** follows char-live-2's layout, from the calibration client at 11:00 daylight with idle at 0 s:

- drawing and Bevy pairs, front, three-quarter, profile and back, face and full body;
- the 58° Near and Middle native crops beside the overhead drawing;
- four walk samples;
- the calibration frame.

[Native stills](final/stills/) · [Sheet script](final/review_sheet.py)

**The walk** plays the file's own embedded clip (`LIVING_GAME_SHARED_CLIPS=0`) at 30 fps: five one-second cycles at the Middle camera (12 m, 58°), turning from yaw 20° to 34.9°. It is encoded as lossless RGB VP9, 1600 × 900, 150 frames. Frames 0, 7, 74 and 149 decode exactly to their source stills. [Walk check](final/walk-check.json) · [Walk script](final/walk.py)

To view the asset, copy the GLB, `own-cora-live.eyes.ink.png`, the face and hair sidecars and the calibration JSON to `living/game/assets/view/`. Use a client from main at or after the handmade-ink merge.

Disk stayed at or above 56 GB through the close. Each private build tree was deleted after its build. `living-check` is left to the merge gate. No paid model or image calls were made, and no database was used.
