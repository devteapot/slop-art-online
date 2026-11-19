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
