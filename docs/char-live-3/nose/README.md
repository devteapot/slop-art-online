# Cora’s nose shading

The first high fit replaces the red tip spot with one soft side shade turning under the tip and a small warm highlight above it. The before arm is the first eye fit at `0fa84da0e`. The drawing, before and fitted portraits share the exposed-face scale and pupil-axis registration. The detail crops are centred on the nose. [Front and three-quarter review](nose-review.png) · [Full orbit and 58° Near and Middle](orbit-and-play.jpg)

| Daylight patch | Drawing RGB | First eye fit RGB | Nose fit RGB |
|---|---|---|---|
| Front highlight | 246, 209, 184 | 237, 180, 143 | 229, 206, 180 |
| Front shade | 201, 135, 104 | 238, 170, 134 | 203, 141, 109 |
| Three-quarter highlight | 244, 194, 161 | 237, 180, 144 | 230, 201, 172 |
| Three-quarter shade | 207, 139, 109 | 237, 173, 137 | 203, 140, 108 |

These descriptive samples use 3 × 3 medians. The report gives native windows, drawing landmarks and both Bevy frames’ readings at the same coordinates. The three-quarter shade is close in colour. In front its underside reads more rounded and diffuse than the drawing’s angular plane. The highlight has less red than the drawing in both views. [Nose sample coordinates](nose-samples.json)

The procedural paint takes its local base from adjacent generator skin. The cage tip is at UV (0.500, 0.713). The flank’s offset, curvature, upper and lower falloff, pigment and highlight radii are candidates for the generator. The drawing supplied visual and measurement targets. The paint script reads only the generated skin atlas. [Paint function](paint.py) · [Journal block](fit.py) · [Source and output hashes](nose-atlas.json)

All GLB properties and all binary data outside the skin atlas match the first eye fit, including every vertex, UV, rig weight, morph target, clip and material. The atlas changed on 10,568 texels in the nose region. The iris map, aperture geometry, tint and both sidecars match exactly. The four eye windows in the two daylight portraits differ by at most one RGB level. The rear Near and Middle, rear portrait and plait orbit match the approved frames pixel for pixel.

All **20 colour checks** passed. The contract audit has zero errors and warnings, and the material audit passed. Volume is 1.870 cheek widths of spread, 0.124 H crown lift and 0.519 H rear depth. Each of the 15 expressions changed its portrait, and the neutral return differs by zero pixels. An independent factory rebuild produced the same GLB, sidecars and calibration file byte for byte, the same 18 expression and registered portrait frames, and all 13 Bevy captures pixel for pixel. [Verification](replay-check.json) · [Calibration](calibration-report.json) · [Garments](cloth.json) · [Material audit](audit.jsonl) · [Blink](expressions/eye-Fcl_EYE_Close.png) · [Eye joy](expressions/eye-Fcl_EYE_Joy.png)

[Editable scene](cora-final.blend) · [Game asset](own-cora-live.glb) · [Journal](../session.jsonl) · [Factory replay](../replay.py)

Usage on 19 November was one high artistic fit, two factory runs and two 13-shot daylight captures with the existing release binary. Work ran approximately 22:39–23:00 UTC, including the wait for the gate and the 46 GiB floor. The brows have zero attempts. Item 2’s second attempt is reserved for the ink profile.
