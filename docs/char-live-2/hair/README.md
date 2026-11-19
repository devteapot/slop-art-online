# Cora hair review on the dev-box

The Blender fit keeps the approved opening around the ear and the back plait. The swept forelocks, returning hooks and long jaw strands are closed, tapered sections. The side groups follow the skull around the pinna towards the nape. Each has a ridged cross-section and its own normals. The support and braid have flat studio pigment. The game's handmade profile replaces RGB on the hair, applies three cel tones and uses the float point-domain _HIGHLIGHT attribute to draw the authored upper-lock highlights.

The drawing targets are display sRGB. To register the patches after changing the shape, a temporary copy of the same GLB assigned four distinct colours to the four bands. Each registered 9 × 9 patch sits wholly inside its intended band in that control frame. The calibration compares the normal fixed daylight render against the drawing targets. The render device is the dev-box AMD GPU on Linux. The laptop's Apple GPU confirmation is separate.

| Volume measure | Drawing target | Fitted GLB |
|---|---:|---:|
| Front width / cheek width | 1.87 ±0.10 | 1.870 |
| Crown lift / head height | 0.096 ±0.035 | 0.124 |
| Rear depth from pinna / head height | 0.53 ±0.04 | 0.530 |

Front width includes the hanging side strands. The cheek width comes from the approved scaled 179 px frontal station. Lift uses the rest skin crown beneath the hair and depth uses the back silhouette above the pinna base. [Measured geometry](volume.json)

The first fit reached 1.949 cheek widths and 0.124 H crown lift, with 0.572 H rear depth. Six of eight hair samples passed. The temple-to-nape surface read too continuously. The second fit carries the swept sections into this area and adds a returning upper side hook. [First fit](high-1/review.jpg) · [First calibration](high-1/colours.csv)

The colour fit on Linux AMD passes all eight fixed patches. The worst channel error is +8 green in frontal shade. The scene and GLB material audits passed. The GLB has 48,896 triangles, six clips, and all 15 expression keys. The point mask exceeds 0.5 on 1,536 of 36,033 exported hair vertices. [Reference pairs](review.jpg) · [Calibration and contract audit](report.json) · [Channel deltas](colours.csv)

| Role | Drawing target | Tuned base sRGB | Rendered front | Rendered 45° |
|---|---|---|---|---|
| Shade | 88, 42, 27 | 45, 7, 2 | 92, 50, 34 | 83, 37, 24 |
| Mid | 152, 72, 43 | 101, 36, 7 | 152, 73, 46 | 152, 70, 40 |
| Light | 171, 88, 56 | 119, 43, 6 | 171, 88, 60 | 171, 87, 60 |
| Highlight | 187, 99, 63 | 135, 47, 3 | 185, 96, 69 | 185, 94, 65 |

**Silhouette self-check, second high fit.** I count approximately 6–7 distinct front tips against the target range of 8–12, and 4–5 at the matched three-quarter angle against 7–11. The long jaw strands are visible. Several shorter tips merge against the side mass when turned, and the profile shows angular colour blocks across the crown. The lower end of each estimate counts clearly separated endpoints. The upper end includes one partially occluded tip. The sheet compares the drawing and the fixed daylight beauty frame without the diagnostic colours. The overhead drawing is the nearest available reference for the two 58° views.

The reviewer returned this second high fit for an xhigh correction to the crown normals, braid reading and lock definition. Its full factory replay reproduced the six review frames pixel for pixel, the face-shadow map byte for byte and every oriented triangle and vertex attribute. The two GLBs differ in generated mesh name suffixes and the ordering of one triangle index buffer. Stage 4 began around 17:23 UTC. The calibrated second high fit reached review at 17:51 UTC after two shape fits and four production daylight palette passes. Two diagnostic colour renders registered the patches. Shared-host quiet windows are included in elapsed time. [Factory replay](replay-check.json)
