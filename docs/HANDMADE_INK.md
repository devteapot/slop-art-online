# Hand-made characters: the ink contract (v1.2)

**Status (2026-11-19): contract v1.2, agreed with dev-box (with the width mode below); the client side is built on branch `handmade-ink` (not merged).** This extends [the hair and face contract](HANDMADE_HAIR.md) (v1, and v1.1's lock ink) with a **general ink profile**. Any material of a hand-made character file can opt in: the eyes (the lid line and the lash flicks), the brows, face lines such as the jaw outline, the skin, and the hair. Files keep `"contract": 1`. v1.2 only adds optional fields and sidecars, and a file or material without them draws exactly as it does today.

**Why a document of its own:** `HANDMADE_HAIR.md` is the hair's and the face's contract. Its v1.1 ink is a set of hair-profile fields, read from the hair mask's G channel. v1.2's ink belongs to no slot. It has its own map, binding, lighting rule per slot, audit and tools, and dev-box authors lid strokes against it without the hair's palette. One page for the ink keeps the hair contract stable. `HANDMADE_HAIR.md` links here, and the v1.1 fields stay defined there, unchanged ([hair's v1.1 fields](#hairs-v11-fields)).

**Where it comes from:** dev-box's lid-ink proposal (`docs/char-live-3/eye-frame/lid-ink-proposal.md` on `char-live-3`, 19fbb60b0) and the general coordinator's decision to make it general. What the code shows today (`origin/main` 97564818b):

- The `eyes` slot maps to `Kind::FacePart` (`handmade.rs` `kind_of`): unshaded except by cast shadows, and it casts none.
- Only `Kind::HandHair` samples a distance field (`toon.wesl` `hand_hair`).
- Cora's upper eyeline, `M00_000_00_FaceEyeline_00_FACE`, has every vertex at UV0 (0, 1), so no texture can draw on it.
- A toon material has one auxiliary texture binding (`ToonExt::face`, bindings 101/102). A face material holds its shadow map there, and a profile hair its `.hair.png`.

## What a file declares

The `ink` object goes on a material's `slop`, beside `slot`:

```json
{ "name": "LidInk", "alphaMode": "BLEND",
  "pbrMetallicRoughness": { "baseColorFactor": [1, 1, 1, 0] },
  "extras": { "slop": { "slot": "eyes",
    "ink": { "color": [34, 18, 16], "width": "uv", "min_px": 1.0, "range": 0.012 } } } }
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `color` | `[r, g, b]` integers, sRGB 0–255 | **required** | The line's base colour (an albedo). The material's own light then lights it ([how ink is lit](#how-ink-is-lit)). |
| `width` | `"px"` or `"uv"` | `"px"` | How the line's width is set ([width modes](#width-modes)). `"px"`: a screen-pixel line from `px`, as on the hair. `"uv"`: a world-sized stroke whose half-width is in the map (R × `range`), for shapes such as lid wings and brows. |
| `px` | number ≥ 0, screen pixels | `1.25` | `"px"` mode: the full-width line's width at the Near stop, in a view 900 pixels tall. As on the hair, it scales with the world size of a pixel at the line, up to 4 × `px`. Not read in `"uv"` mode. |
| `min_px` | number ≥ 0, screen pixels | `1.0` | `"uv"` mode: the narrowest the stroke draws, so a world-sized stroke keeps about a pixel at a distance (a tapered tip still goes to nothing). Not read in `"px"` mode. |
| `range` | number > 0, UV units | `0.004` | The UV distance that G = 255 stands for. It must equal the `--range` the map was made with. |
| `fade_px` | number ≥ 0, screen pixels | `3.0` | Lines fade out where neighbouring lines would come closer than this on screen. **`0` never fades.** |
| `map` | string, a path under the asset folder | the slot's sidecar | The ink map, instead of [the default sidecar](#the-map). |
| `taper` | boolean | `false` | `"px"` mode: whether the map's R is the line's local width fraction. Without it, every line is full width and R is not read. `"uv"` mode always reads R and ignores `taper`. |

- **Opting in:** a material with a valid `ink` object draws ink, and nothing else in v1.2 changes. A material without one is untouched.
- **What makes `ink` invalid:**
  - it is not an object;
  - `color` is missing, or is not three integers 0–255;
  - `range` is not above 0;
  - `width` is neither `"px"` nor `"uv"`;
  - a number field holds something that is not a finite number.

  Then the client ignores the `ink` object for that material, draws the material without ink and warns once. Unknown keys are ignored.
- **Which materials may carry it:** any material of a file whose scene declares `"character": "handmade"`, in any slot except `"tint"`. A tint is multiplied over the skin, so a line can't be laid over it; `ink` on a tint is ignored with a warning. Put that line on a [carrier](#carriers-lines-on-their-own-strips) or on the skin under it. A material without a slot (classed by its name) may carry `ink` only with an explicit `map`, since its sidecar is named by slot.
- **One colour, width and fade per material.** Two lines that need different colours or settings go on two materials.

### Hair's v1.1 fields

The hair profile's v1.1 fields keep their reader, their texture and their drawing exactly as [`HANDMADE_HAIR.md`](HANDMADE_HAIR.md#lock-ink-lines-v11) defines them. They mean the same as this profile with these values:

| v1.1, in `slop.hair` | v1.2, in `slop.ink` |
|---|---|
| `ink` (default `shade` × 0.6 in linear) | `color` (required) |
| `ink_px` | `px` |
| `ink_range` | `range` |
| `ink_fade_px` | `fade_px` (`0` never fades on both; the v1.1 shader's `smoothstep(0, 0, …)` already gave every spacing above 0 full strength) |
| the mask texture's **G** (`<stem>.hair.png` or `highlight_map`, binding 101) | `map` (a separate file, binding 106) |
| no width channel | `taper: false` |
| lit as the profile's shade band | lit as the profile's shade band (the `HandHair` row below) |

- **Both on one hair material:** `slop.ink` wins. The client then ignores the profile's `ink*` fields and the mask's G for drawing, and warns once. The mask's R stays the highlight.
- **v1.1 files draw as before.** Both paths share one coverage function (`toon.wesl` `ink_cover`), and Cora's accepted v1.1 file draws pixel-identical frames on the base and branch clients ([the proof](#the-proof-laptop-2026-11-20)).

## The map

**Its file.** The client takes the first of these that exists, each as its KTX2 copy first and then its PNG (the face maps' rule, `lookdev::face_map_files`):

1. `ink.map`, a path under the asset folder;
2. `<stem>.<slot>.ink.png` beside the file the client loads (its `anim/` copy, when there is one): `view/own-cora-live.glb` → `view/own-cora-live.eyes.ink.png`. Here `<slot>` is the slot's value as the file spells it: `eyes`, `hair`, `skin`, `face` or `cloth`.

- **Sharing a map:** the materials of one slot that opt in share that slot's sidecar, so their strokes must not overlap in UV0. VRoid's face atlas already lays its face parts out that way. Give a material its own `map` when its UVs overlap another's.
- **Distinct from the existing maps:** `.hair.png` (the hair mask), `.face.png` (the face shadow map) and `.hair.ink.png` (a hair's v1.2 ink) are three different files.
- **No map found:** the material draws without ink, and the client warns once.

**Its channels** (8 bits each):

| Channel | Content |
|---|---|
| **G** | The distance to the nearest stroke centreline, as G = round(255 · min(1, d / `range`)), with d in UV units. 0 is on a centreline, and 255 (at `range` or beyond) is no ink. This is hair's v1.1 encoding. |
| **R** | The width, 0–1 (0–255), of the stroke whose centreline is nearest; 0 is a tapered tip. In `"px"` mode with `taper`, it is a fraction of the full `px` width (255 is full width). In `"uv"` mode, it is the stroke's **half-width as a fraction of `range`**: the line covers the texels with d ≤ R × `range`. It is written at **every** texel, not only on the centreline: each texel takes the width of its nearest centreline point (a nearest-point fill), so bilinear filtering across a line reads that stroke's own width. In `"px"` mode without `taper`, R is not read; write 255. |
| **B** | Reserved; write 0. |
| **A** | 255, if present. |

- **PNG colour type:** RGB or RGBA (type 2 or 6), not greyscale. A greyscale map is decoded with R = G, so its R would read as a width. On a greyscale map the client ignores `taper` and warns, and a `"uv"` material draws no ink and warns.
- **The field is made, not painted:** `ink_field.py` makes it ([the tools](#the-tools)).

**Its format:**

- **Linear data:** loaded with sRGB off, as the face and hair maps are. Not embedded in the GLB, for the same reason as the hair mask: Bevy decodes an embedded image that no material reads as a linear channel as sRGB.
- **On TEXCOORD_0** of every primitive of the material, with glTF's convention: UV (0, 0) is the image's top-left. Blender's exporter flips V for you.
- **Mipmapped:** the bundled map is the KTX2 copy with a full mip chain, made by `bc7ktx encode` with `"colour": "linear", "mips": "box"`. The client prefers it. A PNG alone is read at level 0 only, which is enough for authoring and is what v1.1's hair measurements used. A mipped distance field only thins far lines further, and the fade has already removed them there.
- **Sampling:** `textureSampleGrad` with the pixel's own UV gradients (taken in uniform control flow), bilinear.
- **Padding:** keep each UV island's strokes at least `range` from the island's border, and keep islands at least 2 · `range` + 8 texels apart. Then filtering and the mips never carry one island's line onto another's surface.

**`range` against the line's width.** As on the hair, set `range` to about half the narrowest spacing between neighbouring centrelines, in UV, because the fade assumes so. On v1.2 surfaces it has a second bound:

- **In `"px"` mode:** a line is never wider in the world than `px` × 8.05 mm. It is that wide from the Near stop outward, and narrower in close-ups, where the 4× cap holds it. So `range` × `m_uv` (the material's metres per UV unit, below) must be at least half that, `px` × 4.03 mm, plus a pixel.
- **In `"uv"` mode:** the stroke's antialiased edge reaches half a pixel beyond its half-width, R × `range`, and must stay inside `range`. The fade lets a line show only where `range` is at least `fade_px` / 2 pixels on screen, so the bound holds wherever the line shows when **max R ≤ 1 − 1 / `fade_px`**: 0.67 at the default fade of 3, 0.5 at a fade of 2. With `fade_px` 0 nothing guards it: at a distance the `min_px` floor outgrows the range and the edge is cut.
- **What fails without it:** the line's edge is cut flat where G saturates, and that edge aliases.
- **The audit checks both.**

### Sharing the auxiliary binding

**Decision: a new texture binding, 106, for the ink map, sampled through binding 102's sampler.** The map does not go into binding 101 (the face map's or hair mask's slot).

- **Why not binding 101:** two of the slots that need ink already fill it. A `"face"` material with a shadow map holds the map there, and its R and G are taken. A jaw outline drawn on the face's own surface needs both textures in one draw. A profile hair with a mask texture holds `.hair.png` there, whose R is the highlight and so conflicts with the width channel. Packing the ink into the face map's spare B and A would tie the ink's authoring to `face_normals.py`'s output, and the face map is read at level 0 while the ink wants mips.
- **What binding 106 is:** texture only, with no sampler of its own. `toon.wesl` samples it with `face_sampler` (102). That sampler is the face map's when there is one and the fallback image's otherwise. Both are Bevy's default, `ImageSamplerDescriptor::linear()` in bevy_image 0.20.1: linear magnification, minification and mip filtering, clamped to the edge. Without a sampler, the per-stage sampler count, which Metal limits to 16, doesn't rise.
- **What every material pays:** one more entry in its bind group, bound to Bevy's shared fallback image when the material has no ink. That is no read and no new pipeline: every toon material shares one layout already.
- **Hair's v1.1 ink stays in binding 101's G** with no change. The v1.2 ink always comes from binding 106.

| Material | Binding 101 | Binding 106 | Texture reads for ink |
|---|---|---|---|
| Any material without `ink` | as today | fallback | 0 |
| `eyes`, `skin`, `cloth`, `face` without a shadow map, `hair` without a mask texture, with `ink` | as today | ink map | 1 |
| `face` with a shadow map, with `ink` | face map | ink map | 1 (on top of the face map's) |
| profile `hair` with a mask texture, with `ink` | `.hair.png` (R the highlight) | ink map | 1 (on top of the mask's) |
| profile `hair` with v1.1 fields only | `.hair.png` (R, G) | fallback | 0 (the mask's tap already reads G) |

## What the client computes

**Coverage** is hair's v1.1 computation with a width fraction (`toon.wesl`; one function for both paths):

```
tex   = textureSampleGrad(ink_map, face_sampler, uv0, ∂uv/∂x, ∂uv/∂y)    // binding 106
d_uv  = tex.g * range                              // no ink where tex.g = 1
fw    = max(|∂uv/∂x|, |∂uv/∂y|)                    // UV a pixel spans, along its longer side
d_px  = d_uv / fw                                  // distance to the centreline in pixels
m_px  = |view depth| * 2 / (projection[1][1] * viewport height)   // metres a pixel spans there
// "px": the line's width in pixels here, a fraction f of the full width
f     = taper ? tex.r : 1
w     = px * min(0.00805 / m_px, 4) * f
// "uv": the stroke's half-width from the map, in the world, turned into pixels
//       through the texel density and the depth (as the fade), with a floor
w     = tex.r > 0 ? max(2 * tex.r * range * m_uv / m_px, min_px) : 0
cov   = clamp(min(d_px + 0.5, w/2) - max(d_px - 0.5, -w/2), 0, 1)  // a 1-pixel box across it
space = m_uv > 0 ? 2 * range * m_uv / m_px : 2 * range / fw        // neighbouring lines' spacing
cov  *= fade_px > 0 ? smoothstep(fade_px, 2 * fade_px, space) : 1
```

- **`m_uv`:** the material's texel density, in metres per UV unit. It is the median, over the triangles of the mesh that makes the material, of √(area / UV area), measured at rest when the material is made (`handmade.rs` `metres_per_uv`, as for the hair).
- **Width modes:** see [below](#width-modes).
- **A mesh whose UV0 spans no area** has no `m_uv`. The client then draws no ink on it and warns once, rather than reading one texel everywhere.
- **The properties carried over from v1.1:**
  - the antialiasing sums to the width across the line wherever it falls, so a thin line moving by a fraction of a pixel neither flickers nor crawls;
  - the width and the fade follow the pixel's size at its depth, not screen derivatives, which step between 2×2 quads;
  - `d_px` keeps `fw`, which measured steady.

### Width modes

- **`"px"` (the default)** draws lines of a constant screen width from `px`, thickening as the camera comes closer up to 4 × `px`, and constant in the world from the Near stop outward. That is right for the hair's lock lines, whose separation matters more than their shape.
- **`"uv"`** draws a stroke shaped in the map: a lid wing thick over its outer third that tapers to nothing, a brow, a lash flick. Its half-width is R × `range` in UV, so it is world-sized and grows with the face in a close-up, with no cap.
  - **The width goes through the depth and texel-density path**, `m_uv / m_px`, the one the hair's width and fade use. Screen derivatives step between 2×2 pixel quads, and a width driven by them crawled on the hair's first build. The distance keeps `fw`, as on the hair.
  - **So a `"uv"` material needs one texel density across its UV islands and its triangles:** an island scaled up in UV for resolution draws its strokes wider than the others, and a strip whose triangles are stretched unevenly draws a ragged edge. The distance (through `fw`, per triangle) and the half-width (through the median density) then disagree differently from triangle to triangle. The first stand-in lid strip for the proof showed it: with 63% of its triangles within 25% of the median density, the lid's upper edge stepped in 1–2 pixel notches at its columns' spacing; mapped by its own 3D distances (80% within 25%), the edge was clean. Map a carrier's UVs by its own lengths (near-isometric, as Blender's *Follow Active Quads* or a ribbon's arc length gives). The audit warns when the densities spread (below).
  - **`min_px`** floors the width in pixels where the stroke has width at all (R > 0), so a lid line keeps about a pixel at the Far stop. A tip (R = 0) still draws nothing; R between 0 and the floor jumps to the floor, which is what a drawn line does.
  - **The fade applies** as in `"px"` mode, from `fade_px` and `range`.
  - **The coverage is the same box filter**, distance in pixels against half-width in pixels.

### How ink is lit

**Decision: the ink is an albedo, lit exactly as the material lights its own albedo at that point.** It has the same band, the same cast shadow and the same shadow depth. It takes no added shine.

| Material's kind | The ink's light |
|---|---|
| `FacePart` (`eyes`) | **Unshaded, except by cast shadows**, as the eyes are: `banded(ink, sun, shadow, 1 − shadow_depth × face.z, sc)`. A lid line in a hat's shadow darkens with the eye under it, and a lid line in the sun never shades by N·L. |
| `Skin` (`skin`; `face` without a map) | The skin's band and cast shadow, with its light, warm shadows at 45% depth: `banded(ink, sun, band × shadow, …)` with the skin's arguments. |
| `Face` (`face` with a map) | The face map's shadow shape and cast shadow: the line on the jaw goes into shade where the face's shadow edge passes. |
| `Plain` (`cloth`) | The general ramp and core band. |
| `Hair` (`hair` without a profile) | The hair's band and shadow. |
| `HandHair` (profile hair) | **The profile's shade-band light, in light and in shadow alike:** `ink × sun + ink × sky_fill`. This is v1.1's rule, so v1.1 and v1.2 hair ink draw alike. |

**Why this rule:**

1. **It keeps the cast-shadow response** the decision requires, on every slot, through the slot's own code path, not a copy of it.
2. **A line that keeps the sun's light where its surface goes into shade reads as floating or glowing.** That is the defect the tint slot was made to fix ("never glows on a shadowed cheek").
3. **One rule, and the author chooses the behaviour by the slot:** lines on eyes stay unshaded as anime draws them, and lines on skin shade with the skin. The ink colour is then tuned like a swatch, against the calibration frame.
4. **The hair keeps v1.1's shade-band rule** because its palette's `shade` swatch *is* the hair's shadow colour: the hair has no further band below it to share.

**The additive terms:**

- **Rims and the ring:** the general rim, the face rim, the hair's Fresnel rim and its angel ring are scaled by (1 − cov). A line takes no rim; a jaw outline at a three-quarter silhouette would otherwise be lit up exactly where it draws.
- **Point lights** light mix(albedo, ink, cov), as the hair profile does now (`lit_albedo`).
- **Unchanged:** the wet sheen, puddles and emission. The line is wet when the surface is, and v1.1 hair already draws so.
- **No sun:** the fallback without one (`has_sun()` false) draws no ink, as v1.1.

### Blending

**The ink is composited over the material's own lit colour** (Porter-Duff *over*). Here `a` is the material's own alpha after its `alphaMode` (1 for OPAQUE; 1 where MASK keeps the pixel):

```
alpha = cov + a * (1 - cov)
rgb   = (lit_ink * cov + lit_own * a * (1 - cov)) / max(alpha, 1e-4)
```

- **OPAQUE and MASK:** this is mix(lit_own, lit_ink, cov). The ink draws only where the material's own pixel survives its cutoff: a MASK discard happens before the ink, as today.
- **BLEND:** the output alpha rises with the ink, so a line can be drawn over a translucent surface.
- **Shadows and the prepass don't change:** the ink changes no depth, no normal and no shadow caster.

### Carriers: lines on their own strips

A **carrier** is a material that exists only to draw its ink. It has `ink`, `alphaMode` BLEND, and a `baseColorFactor` alpha of 0 with no `baseColorTexture`. Its own colour is then invisible (a = 0), so it draws `lit_ink` at alpha `cov` and is clear everywhere else. This is dev-box's lid strip, with its transparent filtering margin.

- **No outline volume:** the client gives a carrier none of its own, and it keeps the stencil, because its line *is* the drawing. A shell around the strip would draw the strip's outline.
- **Draw order:** the client draws a carrier after the other face parts of its character, so the eye whites, the iris and a tint don't cover the line. It sets the carrier's `StandardMaterial::depth_bias` to 0.05 (`lookdev.rs` `CARRIER_SORT_BIAS`): Bevy 0.20.1 adds it to the transparent sort distance (the view depth of the mesh's bounding-box centre, `TransparentSortingInfo3d`), and below 1 it adds no rasterizer offset (the bias is cast to an integer). The author doesn't set it.
- **Placement:** like the tint, a carrier must lie on, or just in front of, the surface it draws on (0.1–0.5 mm). It must reach at least `range` × `m_uv`, plus a pixel at the closest view, beyond each centreline, so the line never meets the strip's edge.
- **Normals:** on a shaded slot (a jaw line on a skin carrier), a carrier carries the normals of the surface under it (Blender: *Data Transfer*, custom normals). Its band and shadow edge then fall where the surface's do. On `eyes` the normals matter only to the shadow lookup's bias.
- **Slots:** a carrier's slot sets its light as above. A lid strip is `eyes`, so it is unshaded except by cast shadows and casts no shadow.

## Morphs: lines that blink and talk

A blink or an expression must carry its line with it. The ink lives in UV0, so it rides on whatever vertices it is mapped to:

- **On a surface's own material** (brows on the skin, a jaw line on the face): the surface's own morphs move it.
- **On a carrier:** the carrier must morph with the lid.
  - **Preferably as a primitive of the same glTF mesh** as the lid it draws on. glTF gives every primitive of a mesh the same targets, and the mesh's weights drive them all (Bevy's `MeshMorphWeights`), so the strip can't fall out of step.
  - **A carrier in a separate mesh** must carry targets with the same names. The client drives every face layer by name (`lookdev.rs` `rig` and `face`: "the face and every layer on it take the same weights").
  - **Every target that moves the lid moves the strip's vertices with it:** in Blender, shape keys on the strip transferred from the lid (*Surface Deform* bound at rest and applied per key), named as the lid's.
- **UVs are not morphed.** Bevy applies POSITION, NORMAL and TANGENT deltas only, so a TEXCOORD delta in a target is ignored. The stroke stays at its place on the strip, and a squashed strip draws the same line at the same pixel width.
- **The fade uses the rest density** (`m_uv` at rest). Where a morph squashes a strip to well under half its rest height across the lines (a full blink), the fade can come late. The lid's single line has no neighbour to merge with, so this matters only for close parallel strokes such as lash flicks.
- **Far meshes:** a `Far*` copy of a face mesh wears a material with the same `slop` (or the same material), with UVs matching the near mesh's, so it reads the same map.

## The audit

`calibrate.py`'s contract audit (also `--no-run`) checks every material with `slop.ink`.

**Errors (the run fails):**

- `ink` is not an object; `color` is missing or not three integers 0–255; `range` is not a number above 0; `px`, `min_px` or `fade_px` is not a non-negative number; `taper` is not a boolean; `width` is neither `"px"` nor `"uv"`.
- `ink` is on a `"tint"` slot, or on a material without a slot and without `map`.
- No map is found by the [resolution order](#the-map) (it names the paths it tried), or the map is not a PNG/KTX2 it can read.
- **UV0 is collapsed:** a primitive using the material lacks TEXCOORD_0, or its UV0 spans no area (the sum of its triangles' UV areas is 0). Cora's eyeline today is this case.
- A carrier (`baseColorFactor` alpha 0) that is not BLEND: MASK would discard it everywhere.

**Warnings:**

- The map's G is 255 everywhere: there are no lines.
- `taper` or `"uv"` on a greyscale map, or R is 0 everywhere (no line is drawn); or R varies while `"px"` mode has `taper` off (the widths are ignored).
- More than 5% of a primitive's triangles have zero UV area.
- **The range bound:** in `"px"` mode, `range` × `m_uv` is under `px` × 4.03 mm; in `"uv"` mode, max R × `range` + 2 mm / `m_uv` is over `range`. The line is then cut flat at its widest. The audit reports `m_uv`, measured from the GLB as the client measures it, and max R.
- In `"uv"` mode, the material's triangles' texel densities spread: fewer than 90% of them lie within 25% of the median `m_uv`, so strokes on some islands draw at the wrong width.
- Line texels (G = 0) lie within `range` of their UV island's border, so they may bleed across it at mips.
- Hair with both `slop.ink` and v1.1 `ink*` fields: `slop.ink` wins.
- A carrier with no morph targets while the face mesh it lies on has them, or a carrier in a separate mesh that lacks the face's target names: it won't blink with the lid.

**Facts recorded:** each inked material's resolved map, its size and levels, the G line-texel count, the R range, and `m_uv`.

The v1.1 hair checks stay as they are (warnings).

## Calibration, per slot

The calibration frame is [hair's](HANDMADE_HAIR.md#the-calibration-frame), with the same scene, light, grade, shots and targets file. An ink patch says which ink it tunes and takes a floor-relative target, the procedure the GC accepted for Cora's hair ink (`docs/char-live-2/hair/final/README.md` on `char-live-3`):

```json
"lid ink": { "drawing": [612, 288], "sample": "min5", "swatch": "ink", "slot": "eyes",
             "relative": "eye white", "portrait": [801, 402], "portrait45": [779, 405] },
"eye white": { "drawing": [640, 300], "portrait": [812, 410], "portrait45": [790, 412] }
```

**The patch keys v1.2 adds:**

| Key | Meaning |
|---|---|
| `"slot"` | The slot whose ink the patch measures and `"swatch": "ink"` tunes. Without it, the patch tunes the hair's ink, as in v1.1. |
| `"material"` | The material name, when more than one material of the slot carries `ink`. |
| `"relative"` | The name of a reference patch, usually the surface the line is drawn on. Its presence makes the target floor-relative. |
| `"floor"` | `"control"` (the default) or `[r, g, b]` measured elsewhere. |

- **Sampling:** `"sample": "min5"`, the darkest pixel by luminance of a 5×5 window, in the shots and in the drawing, as in v1.1.
- **The floor-relative target:** per shot, and per linear channel, after decoding every value from sRGB:

  ```
  target = floor + (drawing_ink / drawing_ref) * (measured_ref - floor)
  ```

  It is then encoded to sRGB and rounded once. Here `drawing_ink` is this patch's drawing colour, `drawing_ref` is the reference patch's drawing colour, and `measured_ref` is the reference patch measured in the same shot.
  - **Why relative:** an absolute ink target can be below what the grade can show, as Cora's (59, 27, 18) was; the floor's blue alone was 29. The relative target keeps the drawing's contrast of line against surface.
- **The floor (`"control"`):** the tool renders one more set of the shots from a temporary copy of the file. In the copy, every material of the patch's slot has a black albedo (`baseColorFactor` RGB 0 with its alpha and texture kept, so MASK cutouts stay; a hair profile's swatches 0) and black ink. The copy is removed afterwards. The floor is the min5 at the patch's pixel in that copy: what black renders as at that place, under that light and grade. The control renders only when some patch needs it.
- **Swatch suggestions** for `"swatch": "ink"` name the material's `ink.color`, scaled per linear channel by target ÷ measured, as for the other swatches.
- **`colours.csv` and `report.json`** record, for a relative patch, its floor, its reference and its computed target per shot.

## Shimmer, per slot

```
python3 living/tools/characters/ink_shimmer.py view/<file>.glb [--slot S] [--material NAME] [--out DIR]
                                               [--binary PATH] [--plain-stills DIR] [--ink-stills DIR]
```

- **The reference:** a temporary copy without the targeted ink. Without `--slot`, every ink is removed: each material's `slop.ink`, and the hair profile's v1.1 fields. With `--slot S`, only the ink of materials of slot S is removed, and with `--material`, only that material's.
- **Shots, metric and pass:** as `hair_shimmer.py`'s. Near, Middle and Far, a pan and a zoom each of 16 stills, F = Σ|x(i+1) − 2·x(i) + x(i−1)| / Σx, **pass at F_ink ≤ 1.5 × F_edge**, and `faded` below one ink pixel a frame darkened by more than 8 levels.
- **The region scored:**
  - for `--slot hair`, the hair's hue rule, unchanged;
  - for other slots, the union over the sequence's frames of the pixels the ink darkens by more than 2 levels, dilated by 3 px. Eye whites and skin fail the hair's saturation test, so the hue rule would drop the eye.
- **`--also SHOT`** adds a sequence at another view shot (for example `portrait`, where eye lines are many pixels wide) to the three stops.
- **Deciding a slot's fade:** `--fade A,B,…` scores the file once for each `fade_px` (each a temporary copy with that value on the targeted materials), and `--stills` writes a crop of the ink at the Near and Middle stops for each value, side by side with the reference (`stills/<stop>-fade<v>.png`, 4× nearest-neighbour). The table then reads fade by fade, so one run settles a character's eyes.
- **`hair_shimmer.py` stays** as a wrapper with its arguments, output folder (`.local/living/hair-shimmer/`) and numbers unchanged. It runs `ink_shimmer.py --slot hair`.

## The tools

**`ink_field.py`** keeps v1.1's hair layout and gains the ink layout. Which one it writes depends on the output name: `*.ink.png` gets the ink layout, and anything else the hair layout. `--layout hair|ink` overrides that.

```
python3 living/tools/characters/ink_field.py LINES.png STEM.hair.png [--range R] [--seams-as-lines --glb F [--material N]] [--size WxH]
python3 living/tools/characters/ink_field.py LINES.png|STROKES.json STEM.SLOT.ink.png [--range R] [--width W.png] [--size WxH]
                                             [--seams-as-lines --glb F --material N]
```

- **The hair layout:** exactly as v1.1, with G written, R kept, and B 0.
- **The ink layout:** G is the distance, and R the width of the nearest centreline point (a nearest-point fill, from the distance transform's nearest feature). R is 255 without a width source. B is 0.
- **`LINES.png`:** centrelines painted as in v1.1, dark on light, one or two texels wide. With `--width W.png`, a greyscale image at the same size, the value at each centreline texel is that point's width fraction.
- **`STROKES.json` (the stroke tool's output; dev-box's draft from the drawing, 16 polylines and 144 points, made a 2048² map in about a second):** exact centrelines, the better source:

  ```json
  {"size": [2048, 2048], "strokes": [{"points": [[u, v, f], [u, v, f], ...]}, ...]}
  ```

  Each stroke is a polyline in glTF UV (top-left origin), and `f` (0–1) is R at each point, interpolated along each segment: the width fraction in `"px"` mode, the half-width over `range` in `"uv"` mode. d is the exact distance to the nearest segment, not to a texel centre. R is the interpolated `f` at that nearest point. A tapered tip is a point with `f` 0. `"size": [W, H]` is the map's size (`--size` overrides it).
- **Plain Python:** an exact distance transform with the nearest feature kept, so R is filled from the nearest centreline texel. Distances to polylines are evaluated within `range` of each segment's box. It prints the `range` to put in the extras.

**`calibrate.py`** gains [the audit](#the-audit) and [the per-slot ink patches](#calibration-per-slot). **`ink_shimmer.py`** is [above](#shimmer-per-slot).

## Cost

- **Per opted-in material: one texture read at most** (binding 106), with no extra pass, no extra draw and no new pipeline. The rest is some arithmetic: the coverage, and the material's light evaluated once more for the ink albedo (`banded` is a few multiply-adds).
- **Per material without ink: nothing.** The branch is on a uniform flag; binding 106 holds the shared fallback and isn't read.
- **v1.1 hair ink:** unchanged, no extra read.
- **A carrier** is a primitive of its own, so a draw of its own, as today's eyeline primitive it replaces is. It adds no pass.
- **Measured:** 8 hand-made characters with lid and brow ink against the same file without it, at the Near stop and in a 4K close portrait: no measurable difference ([the proof](#the-proof-laptop-2026-11-20)). It is an A/B of median frame times in alternating runs, since this Mac's wgpu offers no GPU timestamps.

## Compatibility

- **A file or material without `slop.ink` draws exactly as today:** composed people, VRoid bases, scenery, and hand-made files of v1 and v1.1. Checked by pixel comparison against the base commit ([the proof](#the-proof-laptop-2026-11-20)).
- **An older client reading a v1.2 file** ignores `slop.ink` (an unknown key) and draws it without ink.
- **Composed characters are not affected:** `characters/compose.rs` reads no `slop`.

## What the client keeps per material

- **The profile and the map are part of the material's content key**, so materials with the same base, the same `ink` and the same resolved map share one material and batch. Materials that differ in either don't.
- **The style keeps them:** when the style changes (`style.rs` `apply`), the ink parameters are kept per material, as hair's are.
- **Slots are read through serde:** the sidecar name's `<slot>` comes from the `Slot` value's serde name, never a string literal in client code (the skill-name guard).

## Agreed with dev-box (2026-11-19)

1. **The lid strip is a primitive of the lid's own mesh.** The audit keeps its warning for a carrier in a separate mesh without the face's morph targets.
2. **`fade_px` for eyes keeps the default (3.0), not 0.** The shimmer tool (`ink_shimmer.py --slot eyes --fade …`) and the Near and Middle stills decide per character.
3. **Lid wings and brows use `width: "uv"`** with `min_px`, instead of a larger cap. dev-box measures the drawn lid's thickness at portrait; the client's proof includes a portrait still of the test strip in both modes.

## The proof (laptop, 2026-11-20)

On a test file: Cora's accepted file (`docs/char-live-2/hair/final/own-cora-live.glb`, v1.1 lock ink at fade 2.0) with stand-in ink, since dev-box's carriers were not made yet. Apple M4 Pro, Metal, the release client, the asset view at 11:00 and 1600×900 unless said. The evidence and the scripts are in `.local/living/handmade-ink/` of the laptop's `handmade-ink` worktree: `make_test.py` (the stand-in), `morphs.py`, `widths.py`, `cost.sh`, `identity.sh`.

**The stand-in:**

- **A lid carrier per eye:** a ribbon along the upper lid, 5 rows across (±4.5 mm) by 1 mm columns, 56 mm with a 4 mm wing. It is a new primitive of the face mesh with all 15 face targets, its deltas transferred from the 4 nearest face and eyeline vertices and smoothed along the strip, and its skin and normals taken from the skin. Material `LidInk`: `eyes`, BLEND, alpha 0, `width: "uv"`, `range` 0.05 UV (3 mm). The lid stroke has a half-width of 1.85 mm over its outer third, tapering to the inner corner and to a pointed wing tip, plus two lash flicks. The old opaque upper lid strokes within 4 mm of the line were dropped.
- **Brows as ink on the face's own skin** (`face`, which has a shadow map, so the face map and the ink map are both bound): the old brow mesh dropped, the strokes mapped into the face atlas, a peak half-width of 2.7 mm. Made from `STROKES.json` files by `ink_field.py`.

**Files without ink draw as before:** the base client (`b5a3a3c4d`) against the branch's, pixel by pixel (`identity.sh`).

| File | Shots | Pixels that differ |
|---|---|---|
| Cora's accepted file (v1.1 lock ink, the refactored coverage) | portrait, 45°, Near, face close-up | 0 |
| A VRoid base (`recipe:adult:3`, `LIVING_GAME_COMPOSE=0`) | three-quarter, Near | 0 |
| A composed person (`look:lk_000f47c0d8aa4056`) | three-quarter / Near | 0 / 44 (two runs of the base differ by 198 there: its blink) |
| Scenery (`envs/cullet/ash_house/ash_house.glb`) | three-quarter, Near | 0 |

**Shimmer** (`ink_shimmer.py`, the v1.1 metric, ≤ 1.5 passes):

| Ink, setting | Near / Middle / Far, pan and zoom | Portrait (pan / zoom) |
|---|---|---|
| Lid carrier, `fade_px` 3 (the default), 2 or 1 | all `faded` | 0.76 / 0.58 (about 600 ink px a frame) |
| Lid carrier, `fade_px` 0 | FAIL: Near pan 6.13 and zoom 3.02, Middle pan 2.26 and zoom 3.53, Far pan 7.61 (the Far zoom faded) | 0.76 / 0.58 |
| Brows on the face, `range` 4.5 mm, `fade_px` 3 | all `faded` | 0.18 / 0.22 |
| Brows on the face, `range` 12 mm, `fade_px` 2 / 1.5 | Near pan 2.72 / 2.19, zoom 1.84 / 1.90, FAIL; Middle and Far `faded` | (not run) |
| Every ink (lid and brows), defaults, at the portrait and two 0.229-zoom close-ups | all `faded` | 0.29–0.43 |
| The same, `LIVING_GAME_PERF=inkfw` (the half-width through the derivatives) | all `faded` | 0.29–0.46 |
| Cora's hair (v1.1 fields, fade 2.0), `hair_shimmer.py` | all `faded`, as dev-box's run | — |

- **What it shows:** with the default fade, face ink is steady wherever it shows (the portrait and the close-ups, where the person window brings the camera) and gone at the three play stops, as Cora's accepted hair ink is.
- **A carrier can't hold a line at Near.** A pixel there spans about 8 mm, so the whole 9 mm strip is about a pixel tall: a strip narrower than a pixel aliases whatever its shader draws, and with the fade off (0) the lid measured 2.3–7.6. The fade must take a carrier's line out before its strip gets that small. **For eyes, keep the default fade, and keep something other than ink to read as the eye at play distance** (the eye's own shapes, or the opaque stroke that the carrier replaces, kept for the Far mesh).
- **A brow on the skin with a wider range shows at Near but fails there** (1.8–2.7). At Near the whole face is about 20 px tall and the brow sits under the fringe's edge, whose own aliasing is inside the scored region. The default fade keeps it out.
- **The two half-width paths measure alike** (0.29–0.43 against 0.29–0.46 at the close-ups, about 4% fewer ink pixels through the derivatives). The density path stays the default, and `inkfw` stays as an A/B switch.

**The blink and talk keep the lid line on the lid:** stills at the extremes of `Fcl_EYE_Close`, `Fcl_EYE_Joy`, `Fcl_MTH_A`, and `Fcl_BRW_Angry` with `Fcl_MTH_O` (each a copy whose face mesh's default weights hold that key, which Bevy takes as the initial `MorphWeights`), front and at −35°, with the ink in its colour and in blue (`morphs-own-cora-ink.png`, `morphs-own-cora-inkblue.png`). The line closes with the lid and stays at the lash line in the blink and eye-joy. Talk and the angry brow leave it where it is.

**Widths at the portrait, in both modes** (`portrait-modes.png`, `widths.py`; blue ink against the same strips without ink; each stroke's covered width perpendicular to it, as a fraction of the eye's width, so as to compare with dev-box's drawing at any scale):

| Stroke | Drawing (front / three-quarter) | `"uv"` (front, two eyes / −35°, near eye) | `"px"`, `px` 1.25 with taper (front / −35°) |
|---|---|---|---|
| Upper lid, five-sixths from the inner corner | 0.111 / 0.116 | 0.099 and 0.150 / 0.087 | 0.052 and 0.091 / 0.041 |
| Brow, thickest | 0.161 / 0.160 | 0.197 and 0.274 / 0.207 | 0.052 and 0.077 / 0.061 |

- **At dev-box's 48 px reference eye,** `"uv"` gives the lid 4.8–7.2 px against the drawing's 5.3 (front), with world-sized strokes that grow with the face.
- **`"px"` holds a line about the hair's width** (5 px at the 4× cap here, 1.25 px at Near) whatever the stroke's own width.
- **The stand-in brow is too wide** (9.5–13 px at that scale against 7.7): on Cora's face atlas the triangles' texel densities spread (55% within 25% of the median), so the `"uv"` width converted through the median comes out wrong.

**Calibration per slot** (`calibrate.py` on the test file, targets in `own-cora-ink.calibration.json`):

- **The floor control** (the eyes and face black) measured (29, 27, 23), against dev-box's (34, 32, 29) on the AMD GPU.
- **The lid ink** (the drawing's (59, 27, 18) relative to a skin of (235, 164, 128)) targeted (65, 44, 36). The brow ink ((120, 60, 40), relative to the same skin) targeted (119, 75, 56).
- **One step of the suggested `ink.color`** brought the brow within ±10 ((125, 79, 58)). The lid moved only from (97, 73, 59) to (93, 69, 55): at the calibration portrait's scale its line is about 3 px wide and no pixel of the min5 window is fully covered. Measure a lid closer (a portrait at zoom 0.229 or nearer).
- **Cora's accepted file** still calibrates 9 of 9, its ink (66, 39, 32) against the accepted (65, 41, 33).

**Cost** (`cost.sh`): 8 Coras in the asset view (`LIVING_GAME_VIEW_COPIES=8`), uncapped, in alternating runs of the test file and the same file without its `slop.ink` (the same strips, maps unbound). Each run's median frame interval over the last 10 s of a 12 s settle (`LIVING_GAME_FRAMES`).

- **At the Near stop, 1600×900:** with ink 2.96, 2.94 and 2.95 ms; without 2.95, 2.94 and 2.93 ms.
- **A close portrait at 3840×2160:** with ink 5.51, 5.51 and 5.53 ms; without 5.50, 5.51 and 5.52 ms.
- **The verdict:** no measurable difference (at most +0.02 ms a pair). At Near the lines are faded but the map is still read, so the read is counted too.

**What the stand-in taught, for dev-box's carriers:**

1. **Map a carrier's UVs by its own lengths.** The first strip, its vertices snapped to the skin and its UVs from the unsnapped ribbon (63% of its triangles within 25% of the median density), drew a lid whose edge stepped in 1–2 px notches at its columns. Mapped by its 3D lengths (80%), the edge was clean. The audit's density warning flags it.
2. **Take a carrier's normals and its lie from the skin, not from lash cards.** The cards' normals twisted the first strip from column to column.
3. **Its morphs must follow the lid's edge.** Deltas from the skin alone left the closed lid's line above the lash line. Deltas taken from the eyeline and smoothed along the strip followed it. Blender's *Surface Deform*, bound at rest, gives the authored version.
4. **A jaw line on Cora's face atlas smears across the cheeks.** The atlas maps the cheek's side with narrow UV triangles over wide skin, so a stroke along the jaw's contour in the atlas drew whisker lines over both cheeks. Put the jaw on a carrier (or re-unwrap that border).
5. **dev-box's draft `STROKES.json`** (16 polylines, 144 points) went through `ink_field.py` as it is: a 2048² map in about a second, with tapered tips at its `f` 0 points.

## Sources in the code

- **The contract's reader:** `living/game/src/handmade.rs` (`material_of`, `ink_of`, `InkProfile` and its `apply`, `ink_map`, `Slot::name`, `kind_of`, `HairProfile`, `metres_per_uv`, `has_green`, `highlight_map`).
- **Material conversion, the content key and carriers:** `living/game/src/lookdev.rs` `convert` (`CARRIER_SORT_BIAS`).
- **Bindings and parameters:** `living/game/src/style.rs` `ToonExt` (101/102 face or hair map, 103/104 detail, 105 tints) and `ToonParams` (`hand_ink`, `hand_ink_range`).
- **The shader:** `living/game/src/toon.wesl` `ink_cover` (the coverage, both paths), `hand_hair` and `fragment` (the ink's light and blend, binding 106); `toon_light.wesl` `banded`, `rim_light`, `metres_per_pixel`.
- **Face-morph driving:** `living/game/src/lookdev.rs` `rig` and `face`.
- **The tools:** `living/tools/characters/ink_field.py`, `calibrate.py` (`ink_audit`, `black_copy`, `measure`), `ink_shimmer.py` (`hair_shimmer.py` its `--slot hair`), and `living/tools/bc7ktx`.
