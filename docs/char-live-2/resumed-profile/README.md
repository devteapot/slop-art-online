# Resumed Cora profile fit

The fit starts from the stage-2 checkpoint at `01f5f67e2` and uses the lower-face rows reviewed in `297614b40`. Cora's jaw record sets `chin_taper=-0.27` and `jaw_taper=0.24`. The jaw arc uses the untapered reference grid. The two new rows carry 0.675 and 0.395 of the original arc displacement. The replay applies the reviewed cage change to the session's pinned generator revision, preserving its eye construction and procedural paint.

[Drawing and fitted orbit](stage-2-review.jpg) · [Measured front pair](stage-2-front-widths.jpg) · [First resumed fit](high-1/stage-2-review.jpg)

The first fit reached the three front tolerances. It replaced the overlapping dome and lining behind the ear with a single rolled edge. In the turned portrait, a hollow remained between the fringe and the skull, the throat had uneven shading and the low chin retained a corner.

The second fit continues the inner hair edge to the fitted scalp. It relaxes the lowest chin vertices around the fixed profile anchor and applies a continuous normal field below the mouth. The cervical rings follow the new jaw seam in angular order and curve forward through the upper throat. Their centre moves through +3.4 mm and returns to −1.5 mm before the collar. The upper neck and head retain their joint weights. The first run of this block stopped at the rim dye lookup. The corrected block selects the existing dark auburn pigment from the session palette.

## Evidence

[Front widths](stage-2-front-widths.json) · [Profile landmarks](profile.json) · [Per-expression pixel changes](stage-2-expressions.json) · [Material and skinning audit](audit.json) · [Factory replay](verification.json)

The drawing stations use the 356 px span between exposed hairline and chin. The model uses its corresponding 244 px span. Cheek and jaw are divided by this height. Chin width is divided by cheek width. The depth check uses the GLB triangles at the registered pixel rows. Profile projections use the crown-to-chin height.

Near and Middle use the 58° game-camera framing in the Blender asset view. The drawing supplies an overhead illustration for the comparison. The close views use matched portrait framing and studio lighting.

[Editable scene](cora-final.blend) · [Export](own-cora-live.glb) · [Journal](../session.jsonl) · [Replay entry point](../replay.py)

Run the factory command in [the stage-2 report](../stage-2.md) with a fresh output directory.

| Measurement | Drawing | Final fitted portrait | Tolerance |
|---|---:|---:|---:|
| Cheek / face height | 0.716 | 0.734 | ±0.025 |
| Jaw / face height | 0.553 | 0.561 | ±0.025 |
| Chin / cheek | 0.392 | 0.402 | ±0.030 |
| Chin-to-ear rise | 31.2° | 31.2° | ±4° |
| Brow projection / head height | 0.020 | 0.0203 | ±0.010 |
| Nose projection / head height | 0.108 | 0.1096 | ±0.015 |
| Upper lip projection / head height | 0.059 | 0.0599 | ±0.010 |

The rendered central spans were 179, 137 and 72 px. The GLB depth check measured 136 px at the jaw, one pixel narrower than the beauty image at the antialiased boundary. Both readings pass. In profile the hair now covers behind the ear and has a continuous edge. The lower jaw plane is softer and the turned silhouette tapers, with a small angular break remaining at the chin tip.

The GLB has 35,720 triangles, six embedded clips, 15 expression keys and COLOR_0 on each of its ten primitives. Each expression independently changed at least 642 pixels in the 440 px portrait. The return to neutral changed zero pixels. The final scene audit passed on 26 materials. All three embedded maps match the procedural files generated for this cage byte for byte.

The coordinator approved the face and ear at the second high fit, carrying the slight three-quarter chin corner forward to face shading. The independent factory replay reproduced all 27 frames pixel for pixel. Only buffer view 13 changed byte order in the GLB. It holds the hair indices. Its oriented triangles match exactly as a multiset; all vertex data, morphs, weights, clips, images and the entire JSON chunk are identical.

Resumed stage 2 began at 17:10 UTC. The first fit finished at 17:15 and the corrected second fit at 17:22. The independent replay finished at about 17:25. Usage was two artistic fits, one interrupted export and one independent rebuild. No image generation or paid calls. Token totals unavailable.
