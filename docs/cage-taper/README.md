# Independent chin and jaw widths

Cora’s fitted young-woman head (`adult-f-c`, age 26) passes the three front tolerances together. The comparison uses the live session’s 440 px orthographic portrait, its exposed hairline at row 133 and chin at row 377. At each registered row, the measurement is the inclusive central span of visible face skin. A depth test against the triangulated scene separates skin from hair and neck. Applying that test to the archived face reproduced all three original spans.

| Measure | Drawing | Archived Cora | New Cora | Tolerance |
|---|---:|---:|---:|---:|
| Cheek / face height, row 265 | 0.716 | 179/244 = 0.734 | 179/244 = 0.734 | ±0.025 |
| Jaw / face height, row 329 | 0.553 | 122/244 = 0.500 | 134/244 = 0.549 | ±0.025 |
| Chin / cheek, row 359 | 0.392 | 84/179 = 0.469 | 70/179 = 0.391 | ±0.030 |

The chin-to-pinna chord rises **31.200°**. Relative to the nasal root, brow, nose and upper lip project **0.02029, 0.10957 and 0.05986** crown-to-chin heights. These reproduce the stage-2 profile measurements. Broad shading planes are still visible below the mouth and along the side of the jaw. [Cora portraits and front measurement lines](cora.webp)

## Applying the fit

The two optional fields belong to the type’s `jaw` record. Their values are fractional offsets to local half-width. The chin has full influence below 0.095 head heights and blends into the jaw by 0.145. Jaw influence fades between 0.15 and 0.27. The rows follow the rising jaw edge, and the neck ring retains its own radius. Either nonzero value adds both rings and enables the same topology for the closed head, skin and all expressions. Both values default to zero.

For the live session, retain the fitted type, its established profile and the stage-2 width edits. Set the two fields **before building the head**.

```python
tf["jaw"].update(chin_taper=-0.27, jaw_taper=0.24)
```

The session also has its own `fit_cora_rows` override. Compute the old `jaw_arc` displacement against the **untapered** grid, so applying that displacement preserves the new widths. Extend its row carry weights with `chin_taper=0.675` and `jaw_taper=0.395`, the means of the adjoining weights. The demo uses those two adaptations and the live journal’s matched eye mesh and paint. No existing type record, look key or generation ID changed. Cullet’s generation is `c4-e61b01c0`.

To check the controls separately, four rebuilds used the same hair and camera. With the jaw offset held at +0.24, changing the chin offset from zero to −0.27 narrowed the chin from 82 to 70 px and the jaw from 136 to 134 px. With the chin held at −0.27, changing the jaw offset from zero to +0.24 widened the jaw from 118 to 134 px and the chin from 68 to 70 px. These probe spans use the front skin and hair. The acceptance table uses the full scene.

## Defaults and expressions

Against main at `9d112a515`, all **21 types** had identical neutral vertex positions, polygon indices, all 15 morph delta arrays and front, three-quarter and profile pixels. These stills show the full generator face with vertex colour and directional lighting. [21-type comparison, main on the left](types.webp)

The four body presets were generated separately on main and the candidate with their requested types and baked identities. Eleven of twelve Workbench portraits matched exactly. The own-man front had one pixel differing by one 8-bit RGB level at 240 × 240. Blender used the host’s fallback colour management on both runs. [Four-body portrait comparison](bodies.webp)

On the opt-in Cora head, each of the 15 keys changed the 440 × 440 Cycles portrait, from 1,015 pixels for brow anger to 5,917 for eye joy. Returning every key to zero restored **every RGBA pixel**. All 56 pairs of skin and underside vertices on the jaw seam coincided exactly in Basis and in every key, including talk and smile. [Expression portraits, neutral through return to zero](expressions.webp)

## Geometry cost

Counts are for the exported whole head on `adult-f-c`, using the woman look and the demo offsets, with the head isolated from hands and neck. Vertices are glTF POSITION counts across material primitives, including seam splits. The near count includes paint and lines. The far head retains its coarse grid, but a different set of down-facing polygons qualifies for the jaw outline.

| LOD | Default vertices | Taper vertices | Extra | Default triangles | Taper triangles | Extra |
|---|---:|---:|---:|---:|---:|---:|
| Near | 4,324 | 4,534 | +210 | 7,092 | 7,512 | +420 |
| Far | 1,057 | 1,065 | +8 | 1,996 | 2,012 | +16 |

Default heads add zero vertices and triangles. The verification used the generator, Blender and GLB exports. The game renderer and merge gate remain for coordinator review.
