# Cora’s eye frame

The approved plait export supplies the before frames. The front and −35° daylight portraits use the same idle frame. The drawing uses the corresponding two portraits on the face sheet. All measurements use native pixels before any crop or resizing. Screen-left and screen-right name the eyes as they appear in each image.

Face height runs from the exposed hairline to the chin, following stage 2. The central opening runs from the first visible iris or white below the upper lid to the lower rim, on the pupil column. The iris chord includes its dark rim at pupil height. Eye width runs from inner to outer canthus and excludes lash and wing extensions. To measure the outer lid, mark its lower ink edge five-sixths of the way from inner to outer canthus. Report its vertical height above the line through the two pupils at that column, accounting for head roll. The final wing tip lies beyond the canthus and is judged in the matched portraits. A one-pixel placement difference affects model heights by about 0.005 H and iris ratios by up to 0.045 on the far eye.

Each cell reads **drawing → approved → first fit**. [Matched daylight portraits and eye crops](eye-review.png) · [Landmarks](landmarks.json) · [Measurements](measurements.json)

| View and eye | Central opening / H | Outer lid above pupil axis / H | Iris width / eye width |
|---|---:|---:|---:|
| Front, screen-left | 0.070 → 0.082 → 0.082 | 0.018 → 0.025 → 0.032 | 0.507 → 0.360 → 0.465 |
| Front, screen-right | 0.070 → 0.082 → 0.082 | 0.017 → 0.025 → 0.029 | 0.493 → 0.370 → 0.490 |
| Three-quarter, screen-left | 0.074 → 0.082 → 0.079 | 0.014 → 0.026 → 0.031 | 0.445 → 0.380 → 0.491 |
| Three-quarter, screen-right | 0.067 → 0.070 → 0.070 | 0.021 → 0.042 → 0.045 | 0.543 → 0.477 → 0.545 |

All four iris chords were narrower than drawn before the fit. Each iris disk grew 27% along its own horizontal tangent. In front, the two ratios moved from 0.360 and 0.370 to 0.465 and 0.490. At three-quarter the near iris now exceeds the drawing by 0.046 of an eye width, and the far iris is within 0.002. Central openings changed by at most half a native pixel. The measured outer lid rose by 0.5 to 1.5 pixels, and sits higher above the pupil axis than the drawing on all four samples. The wing has a thicker root and visible short lashes. Its outer tip still looks shorter and blunter than the drawing, particularly at three-quarter.

The fit extends the existing upper strip by 4 mm and raises its terminal station 4.8 mm, with a separate 1.3 mm lift at the outer canthus. The outer band gains up to 24% thickness. Ten upper lash cards were lengthened and darkened. Each morph uses its own upper band and lash roots. These are possible generator parameters for lid fitting. [Fit block](fit.py) · [Fitted values](eye-fit.json)

**Expressions and play cameras.** All 15 single-key portraits changed, by 895 to 7,007 pixels at the registered 440 px camera. Blink closes both apertures. Eye-joy forms raised arcs, heavier than the neutral lash line. The returned neutral differs by zero pixels. At native 1600 × 900, the largest per-channel change anywhere in the 58° Near frame was seven levels. The widened eye and darker ink form no visible blot there. [Blink and eye-joy](blink-and-eye-joy.png) · [Orbit and both play distances](orbit-and-play.jpg) · [Native Near still](stills/01-clip-idle@0-near_0.png)

**Preservation.** All 12 hair and skin observations and all eight cloth windows pass. The contract audit has zero warnings and errors, and every scene-material audit passed. Hair spread is 1.870 cheek widths, crown lift 0.124 H and rear depth 0.519 H. All hair primitives, including the plait crest, retain their approved mesh attributes, indices and material definitions. The hair mask is byte-identical. The Near and Middle rear views, the rear portrait and the plait orbit are pixel-identical to approved. The export has 48,896 triangles, six clips and 15 expression keys. [Daylight report](calibration-report.json) · [Cloth windows](cloth.json) · [Scene audits](audit.jsonl) · [Export counts](game-counts.json)

[Editable scene](cora-final.blend) · [Game asset](own-cora-live.glb) · [Session journal](../session.jsonl) · [Factory entry point](../replay.py)

**Replay and usage.** A second Blender factory startup rebuilt the GLB, the face and hair sidecars, and the calibration JSON byte for byte. All 18 expression and registered portrait frames matched pixel for pixel. A second Bevy capture using the rebuilt export reproduced all 13 daylight stills pixel for pixel. [Replay and preservation results](replay-check.json) · [Verification script](verify_fit.py)

One artistic attempt at high. Reference measurement and scripting took place during the quiet window. The fit began at 22:16 UTC on 19 November and verification finished at 22:35 UTC. This interval includes roughly 17 minutes waiting for the gate and disk floor before the second daylight capture. Two factory runs and two 13-shot Bevy captures used the existing release binary. No private build tree was created.

The GC returned the first fit for a lid-stroke revision. The second high fit is waiting on the laptop’s decision about distance-field coverage for face parts. [Short client-hook proposal](lid-ink-proposal.md)

## Drawing widths for the general ink profile

Use these as projected targets for the proposed UV-width mode. The reference is the original face sheet. I followed the visible **screen-right eye in front** and the larger **screen-left eye at three-quarter**. Their canthus-to-canthus widths are 70 and 73 drawing pixels. The stage-2 440 × 440 registration maps 356 source pixels of face height to 244 portrait pixels. Applying that same scale to both views gives reference eye widths of **48.0 and 50.0 portrait pixels**. Stroke length follows its projected centreline around bends. Width is estimated across the local dark stroke, perpendicular to that centreline. The filled nose and neck shades are excluded. [Marked drawing](drawing-strokes.png) · [Native points, width profiles and lengths](drawing-strokes.json)

Every table entry uses **440-portrait pixels / fraction of eye width**. End widths run from the first to the last traced point. **T** means a free taper below about **0.7 px / 0.014 eye**, encoded as zero at the vector endpoint. A line that joins another line or exits behind hair can retain width at the end of its visible trace. Allow about one source pixel on clean edges and two where ink merges with the hair or another line. The turned brow length includes its estimated continuation behind the fringe. The jaw length follows the visible face/neck contour; its ends are landmarks and its peak is the dark line beside the shaded neck.

### Front

| Stroke | Thickest | Ends | Length |
|---|---:|---|---:|
| Upper lid + wing | 5.7 / 0.119 | T → T | 70.1 / 1.461 |
| Wing only | 5.7 / 0.119 | 5.7 / 0.119 → T | 13.3 / 0.278 |
| Lash 1 | 1.6 / 0.034 | 1.6 / 0.034 → T | 7.8 / 0.163 |
| Lash 2 | 1.9 / 0.040 | 1.9 / 0.040 → T | 7.7 / 0.161 |
| Outer lower lid | 1.9 / 0.040 | T → 1.9 / 0.040 | 28.4 / 0.593 |
| Brow | 7.7 / 0.161 | T → T | 71.5 / 1.489 |
| Jaw | 1.7 / 0.036 | 0.8 / 0.016 → 0.8 / 0.017 | 221.4 / 4.616 |
| Nostril a | 1.4 / 0.030 | T → T | 9.8 / 0.205 |
| Nostril b | 1.6 / 0.033 | T → T | 9.8 / 0.204 |

### Three-quarter

| Stroke | Thickest | Ends | Length |
|---|---:|---|---:|
| Upper lid + wing | 7.1 / 0.142 | T → T | 77.8 / 1.555 |
| Wing only | 7.1 / 0.142 | 6.3 / 0.126 → T | 20.0 / 0.400 |
| Lash 1 | 1.4 / 0.027 | 1.4 / 0.027 → T | 5.6 / 0.112 |
| Lash 2 | 1.7 / 0.034 | 1.7 / 0.034 → T | 5.1 / 0.102 |
| Outer lower lid | 2.1 / 0.041 | T → 2.1 / 0.041 | 32.8 / 0.656 |
| Brow | 8.0 / 0.160 | T → T | 86.6 / 1.730 |
| Jaw | 1.7 / 0.034 | 0.7 / 0.014 → 0.9 / 0.018 | 176.2 / 3.522 |
| Nostril | 1.3 / 0.026 | T → T | 11.6 / 0.232 |
| Underside | 1.6 / 0.032 | T → 0.8 / 0.016 | 23.8 / 0.476 |

At the same outer-third station as the opening study (five-sixths from the inner canthus), the upper lid is **5.3 px / 0.111 eye front** and **5.8 px / 0.116 eye three-quarter**. Approximately halfway from wing root to tip, the widths are **2.6 px / 0.055 eye front** and **3.6 px / 0.071 eye three-quarter**. The wing-only row is part of the upper-lid length. Lash rows measure the short offshoots independently. The front underside between the two nostrils is a soft colour boundary with no separately resolved dark stroke. The turned drawing has a short underside stroke joining the side contour and one visible nostril.

The draft follows the polyline input in `docs/HANDMADE_INK.md` at `5fffc0545`. It has two independent, uniformly scaled UV study panels, front on the left and three-quarter on the right. Each point is `[u,v,f]` with top-left origin and `f = measured source width / 12 px`. The order is recorded in the native data’s `draft_index`. These are drawing-derived coordinates for a width-mode test. The actual morph-following carriers need their own UV registration before use on Cora. The two panels describe different projections of the same features. [Draft STROKES.json](STROKES.json)
