# Item 1 · final plait review

The plait is visible as auburn below the nape at both 58° play distances. The final mean width is **7.8 px at Near** and **5.1 px at Middle**, within 0.5 px of the registered rear drawing. The final plait is brighter than both drawing samples. The back portrait shows the brighter tops of the interwoven sections. Several bright-to-dark edges at the nape and towards the tie are more angular and higher in contrast than the drawing. The GC passed the final plait. [Native play comparison and enlargements](play-review.png) · [Back, profile and plait comparison](orbit-review.jpg)

## Measurements

Each cell is **mean display luma / mean width in native camera pixels**. Approved is the completed char-live-2 asset. Grouped is the second high fit at `fb8ed870a`. The final arm is the single xhigh plait fit.

| Camera and measured length | Rear drawing | Overhead drawing | Approved | Grouped | Final |
|---|---:|---:|---:|---:|---:|
| Near, 17 rows from the nape | 69.1 / 7.4 | — | 56.8 / 7.2 | 59.8 / 6.2 | **86.0 / 7.8** |
| Middle, 10 rows from the nape | 69.1 / 4.6 | — | 63.4 / 4.8 | 66.2 / 3.9 | **89.1 / 5.1** |
| Near, 6 rows at the nape | — | 80.6 / 12.2 | 53.8 / 8.2 | 57.3 / 7.2 | **86.8 / 9.8** |
| Middle, 3 rows at the nape | — | 80.6 / 7.6 | 57.0 / 5.0 | 58.3 / 4.3 | **87.4 / 6.3** |

Over the first and last thirds of the full Near interval the final plait tapers from 10.2 to 6.2 px. The drawing tapers from 9.8 to 5.3 px. At Middle those widths are 6.3 to 4.0 px in the final and 6.1 to 3.3 px in the drawing. [Measurements at full precision](measurements.json)

The rear reference uses the 118 original scanlines from y=112 through 229 on the turnaround. The traced plait outline includes the dark edges. The crown spans 108 reference pixels, 29 native pixels at Near and 18 at Middle. Widths use the corresponding transverse scale. Length uses that scale times cos(58°), rounded to the nearest whole native row. All three render arms use x=775–830 and the same nape registration, y=432 at Near and 439 at Middle. The top-down drawing exposes only two lobes above the crown. For that comparison the visible strip is y=563–580, scaled by its own 80 px crown width and projected with sin(58°). Its precise correspondence along the hidden plait is uncertain.

Display luma is the mean of 0.2126R + 0.7152G + 0.0722B on 8-bit sRGB pixels. Drawing luma is integrated inside the original outline, and its width is converted to the native scale. The renderer measurement uses three registered material-ID controls to select visible plait pixels. The production daylight frame supplies all measured colours. Width is the count of selected pixels divided by the fixed number of rows. Partial edge pixels and the one-pixel rounding of a window matter particularly at Middle. The two native window files stack approved, grouped and final from top to bottom, with beauty on the left and the green ID control on the right. [Near windows](near-windows.png) · [Middle windows](middle-windows.png) · [Registration and measurement code](measure.py)

## Fit and verification

The three existing strands widen by up to 44% across the upper lobes. The gain falls smoothly to zero before the tie. The upward surface of each crossing uses a local hair material whose darkest band takes the established auburn mid dye. A curved highlight in the three plait R islands follows each turn. The material adds one primitive. The sun and cast-shadow settings are the same across all three arms. A fixed-palette control confirmed that mid and highlight dyes were reachable at the registered windows.

All **12 hair and skin and 8 garment checks pass**. The contract audit reports zero errors and warnings. The scene audit matched all packed images to the approved generator outputs. Spread is 1.870 cheek widths, crown lift 0.124 head heights and rear depth 0.519 head heights. The export has 48,896 triangles, ten primitives, six clips and 15 expressions. [Daylight audit](calibration-report.json) · [Garments](cloth.json) · [Volume](volume.json) · [Material audit](audit.jsonl)

A triangle-by-triangle comparison found identical positions, corner normals, UVs, colours and rig attributes on all **20,868 hair triangles outside the plait**. All original material definitions, face and garment primitives, face morphs, clips and skinning matched the grouped asset. The hair mask changes only in R on the three braid islands. Across the 1600 × 900 rear game frames, one Near pixel and zero Middle pixels outside a four-pixel margin of the marked plait differed by more than eight channel levels from the grouped fit. The rear portrait had ten such pixels. Factory replay regenerated the GLB and both sidecars byte for byte and reproduced all 13 Bevy stills pixel for pixel. [Replay and preservation evidence](replay-check.json) · [GLB](own-cora-live.glb) · [Editable scene](cora-final.blend) · [Journal](../../session.jsonl) · [Replay](../../replay.py)

The final item-1 attempt ran approximately 21:54–22:02 UTC on 19 November. Usage was one xhigh artistic fit, fixed-dye and visibility controls, one independent replay and two full daylight capture sets using the existing release client. Item 1 used two high attempts and one xhigh in total. Item 2 awaits the coordinator’s verdict and effort reset.

## GC verdict

Item 1 passed. The play-camera defect is fixed. For the later tuning pass, adjust one plait band value. Mean luma is about 25% above the rear drawing (Near 86 against 69, Middle 89 against 69). The close-view segment gaps and the transitions at the nape and tie are harsh.
