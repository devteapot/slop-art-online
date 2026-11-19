# Cora’s rear locks and braid start

**Item 1 is submitted for the GC’s side-by-side verdict.** Open the play sheet first. It shows the approved asset and the second high fit from the back at 58° Near (8 m) and Middle (12 m), with native crops and nearest-neighbour enlargements. The lower row turns the camera to rear three-quarter. The turnaround supplies the back and overhead drawings. [Near and Middle](play-review.png) · [Profile, rear portrait and plait against the drawings](orbit-review.jpg) · [Native Bevy orbit](stills/)

The paired locks now meet the plait at staggered heights. The central crown section and two overlapping side folds form descending Vs. The plait begins higher in the rear portrait, and the profile shows shorter secondary folds among the long ones. The native play-camera gain is smaller. At Middle the braid still reads chiefly as a dark, narrow shape below the crown. Its upper lobes are darker and narrower than those in the drawing.

## What the game camera sees

A separate Bevy material-ID control tagged the original three braid islands on both meshes. The control uses the same triangles, weights, pose, depth testing, camera and daylight. Only the plait receives a bright green profile. The first marked row is the first pixel in the registered window where green increased by more than 32 display levels and exceeded both red and blue by more than 28. The visible first row moves upward by **2 native pixels at Near**, **1 at Middle** and **76 in the rear portrait**. The visible pixel counts in the play windows fell as the plait became narrower. These numbers locate the braid surface. Judge its auburn contrast on the unmarked sheet. [Marked crops](braid-visibility.png) · [Window coordinates and counts](braid-visibility.json)

| Fit | Rear depth / head height | Colour checks | Visual findings |
|---|---:|---:|---|
| Approved char-live-2 | 0.530 | 20/20 | Closely spaced lines continue almost the full height of the back. |
| First high | 0.699 | 19/20 | Paired sections converge, but the upper plait protrudes in shelves. The green channel of the 45° shade missed by 10 against ±8. [First fit](high-1/orbit-review.jpg) |
| Second high | 0.519 | 20/20 | Rounded strands seat against the nape. Front spread is 1.870 cheek widths and crown lift is 0.124 head heights. All three volume measures are within the approved ranges. [Volume](volume.json) |

The second pass used shade base (44,8,2). The registered shade measured (91,50,34) in front and (82,39,25) at 45°, against the drawing’s (88,42,27). All nine hair, three skin and eight garment measurements pass on the dev-box AMD GPU. The two portrait garments appear in both the standard and garment reports and count once. The contract audit had zero errors and warnings. Both Blender material audits found only the approved procedural atlas, iris and tint. [Daylight calibration](calibration-report.json) · [Garment checks](cloth.json) · [Material audit](audit.jsonl)

## Replay and generator parameters

The new journal opens the approved final char-live-2 blend from `475eefda5`. The final GLB and both sidecars matched the independent factory replay byte for byte, and all 13 Bevy stills matched pixel for pixel. The 48,896 triangles, six clips and 15 expression keys are preserved. A comparison with the approved asset verified the face morphs, all non-hair primitive data, the clips and the skinning. [Factory evidence](replay-check.json) · [Editable scene](cora-final.blend) · [GLB](own-cora-live.glb) · [Journal](../session.jsonl)

The reusable inputs are the crown and side stations expressed in cheek radii and head heights, pair asymmetry, separate parent and companion widths, layered convergence heights, plait root height, strand orbit and cross-section, and over/under phase. The guide gives each lock an independent start, end and crease width. Placement still depends on Cora’s existing scalp and registered UV islands. The dye adjustment is specific to the approved light and material. [Fit](fit.py) · [Stroke guide](strokes.py)

Run from the repository root with the lookdev clips installed and a fresh output directory.

```bash
OCIO="$PWD/docs/char-live-1/standard.ocio" CHAR_LIVE_OUTPUT="$PWD/.local/cora3-replay" \
  "$HOME/.local/share/slop-tools/build-bin/blender" -b --factory-startup -t 2 \
  --python-exit-code 1 -P docs/char-live-3/replay.py
```

Item 1 ran approximately 21:44–21:53 UTC on 19 November, including packaging and verification. It used two high artistic attempts, a baseline capture, independent replay and paired visibility controls. It reused the existing release binary. No private Cargo build tree was created. The four later items await the GC’s successive verdicts.

The GC retained the grouped locks and authorized one xhigh attempt on the plait alone. The final package compares all three arms at the fixed nape windows and records the close-view residual. [Final plait review](plait/README.md)
