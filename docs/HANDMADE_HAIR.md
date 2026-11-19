# Hand-made characters: the hair and face contract

**Status (2026-11-19): contract v1, agreed; the client side is built on branch `handmade-hair` (not merged).** This is the format that dev-box's live Blender session authors to. dev-box agreed phase 1's draft (f0463412) with one change, folded in here before any file was made to it: a sixth slot, `"tint"`, for layers multiplied over skin. Phase 2 built the client side: the profile, the classification, the forward turn and the calibration frame (`living/game/src/handmade.rs`, `living/tools/characters/calibrate.py`). From here, a change to any name or meaning below needs a new contract number (`slop.contract`).

**v1.1 (2026-11-19): lock ink lines,** for the opt-in profile only; see [lock ink lines](#lock-ink-lines-v11). It adds optional fields and the mask texture's G channel, and makes one change to v1's meaning: a mask texture no longer replaces `_HIGHLIGHT` but combines with it (the larger wins), so a texture made for ink alone keeps a file's per-vertex highlight. Files keep `"contract": 1`. A v1 file draws as before (one with both a mask texture and `_HIGHLIGHT` now shows the larger of the two; none has been made): no v1 file can carry ink fields, and ink is drawn only where they are set. The shader for v1.1 is in progress on branch `hair-ink`; `ink_field.py` and the audit are there now.

**Why:** dev-box's hand-made character Cora (`own-cora-live.glb`) read as a glossy helmet in the client. The diagnosis (`.local/living/cora-material/FINDINGS.md` on the laptop) found four causes:

- the gloss is painted into the hair's vertex colours;
- the asset view classes the hair `Plain`, so it takes the cream general rim;
- the grade (exposure, TonyMcMapface, bloom, soft film) lifts and washes the colours;
- the file has no way to say what it is.

The owner's art target is **flat cel bands, at most about three steps, plus one broad highlight.**

The contract gives a standalone character file five things:

1. a declaration that it is a character, and which way it faces;
2. a slot on each material (hair, skin, face, eyes, tint, cloth);
3. an opt-in hair profile with its own palette and two thresholds;
4. an explicit highlight mask;
5. the face's shadow data, in the format the client already reads.

Generated (composed) characters are not affected (see [compatibility](#compatibility)).

## Where the metadata lives

Everything this contract adds is in glTF `extras`, under one object named `slop`. The scene carries one, and each material carries one.

- **Why a namespace:** the generator's own keys are unprefixed (`hair_fit`, `outfit` and `clip_file` on scenes, `face_map` on materials, `rest_translation` on nodes; see [CHARACTERS.md](CHARACTERS.md)). Those files are written by our tools. A hand-made file comes out of Blender, whose exporter writes every custom property into `extras`. One `slop` object keeps our keys apart from whatever else an author's scene carries.
- **One existing key is reused unchanged:** a material's top-level `face_map` (see [the face shadow](#the-face-shadow)).
- **In Blender:**
  - Set the scene's and each material's custom property `slop`, with an ID-property group (a Python dict): `bpy.context.scene["slop"] = {...}` and `mat["slop"] = {...}`.
  - Export with *Include → Custom Properties* (`export_extras=True`).
  - The exporter writes a scene's custom properties to `scenes[i].extras` and a material's to `materials[i].extras`.
  - Object (node) custom properties are **not** read by this contract.
- **How the client reads it:** both paths read the scene's `slop` from the GLB's JSON before spawning, as they already read `extras.clip_file.figure_height` (`lookdev::figure_height`, `view.rs` `glb_json`). They read a material's `slop` from Bevy's `GltfMaterialExtras` on each mesh entity, as `face_map` is read today (`lookdev.rs` `face_map_of`).
- **Which file the client reads:** it loads `lookdev::animated(file)`. When an `anim/` copy of the file sits next to it, the client loads that copy, and the copy must carry the same extras. Sidecar files (`.face.png`, `.hair.png`) sit beside the file actually loaded.

Numbers are JSON numbers, and colours are arrays of three integers.

## The scene: what the file is

```json
"scenes": [{
  "name": "Scene",
  "nodes": [0],
  "extras": {
    "slop": {
      "contract": 1,
      "character": "handmade",
      "forward": "+Z"
    }
  }
}]
```

The scene read is `scenes[scene]`, the file's default scene, or 0.

| Key | Type | Values | Meaning |
|---|---|---|---|
| `slop.contract` | integer | `1` | This document's version. A file with a higher number than the client knows is treated as having no `slop` extras, with one warning. |
| `slop.character` | string | `"handmade"` | The file is a character. The asset view and live loading class its materials by their [slots](#materials-slots) and outline it as a person (`Outlined::Person`). Other values are reserved. An unknown value is treated as absent, with one warning. |
| `slop.forward` | string | `"+Z"` or `"-Z"` | The glTF axis the character's face points along, in the file's own frame, at rest. Required when `character` is set. |

**What `forward` changes:** which way the character stands, on every path, through one rule.

- **Every character file faces −Z in its root's frame** (VRM's convention), and every place that turns a character's root assumes it: live loading turns the root `yaw + π` (`characters::spawn`, and `live.rs` every frame), the asset view and the line-up turn a −Z file π to face the camera.
- **A `"+Z"` file is turned half round as its scene comes in** (`handmade.rs` `on_ready`, on Bevy's `WorldInstanceReady`): each top node of the scene turns π about the root's up. The skeleton and the skinned meshes hang under those nodes, so the whole character turns, and the roots' turns stay as they are. A `"-Z"` file is not turned. The asset view and the line-up give a hand-made file the −Z turn (π).
- **Cora faces +Z.** Blender's front (−Y) exports to glTF +Z, so a character modelled facing Blender's front view is `"+Z"`.
- **The fringe fallback follows it.** `toon.wesl` `facing()` (where character hair without a mask keeps its ring off the fringe) took the character's forward as the mesh's −Z. For a hand-made file the client works out the authored forward in each mesh's own frame, through the turns of the nodes between the mesh and the root (`handmade.rs` `local_forward`), and gives it to the material (`toon.file`). Cora's Armature node carries a half turn of its own, so the old −Z guess happened to hold for her; a file whose meshes are not under such a node now gets its forward right too. The hair profile never uses `facing()`: its highlight comes from the [mask](#the-highlight-mask). Face shading takes the head's forward from the face's own TEXCOORD_1.

When `forward` is missing or malformed on a `character` file, the client warns once and takes it as `"-Z"`.

This contract covers materials, the forward axis and the shading data only. The skeleton, clips, spring bones and morph-target names that live loading needs are those of [the client format](CHARACTERS.md#the-client-format). `character` does not change which animation the asset view plays: clips in the file play as today.

## Materials: slots

```json
"materials": [
  { "name": "Hair",  "extras": { "slop": { "slot": "hair", "hair": { "...": "see the hair profile" } } } },
  { "name": "Body",  "extras": { "slop": { "slot": "skin" } } },
  { "name": "Face",  "extras": { "slop": { "slot": "face" } } },
  { "name": "Eyes",  "extras": { "slop": { "slot": "eyes" } } },
  { "name": "Cloth", "extras": { "slop": { "slot": "cloth" } } }
]
```

`slop.slot` (string) is one of the six values below. In a file with `slop.character`, the slot overrides the name rules. Without a slot, the client classes the material by name and the file's `vrm` flag, as today (`…_HAIR`, `…Face…_SKIN`, `…_SKIN`, `…_FACE`, `…_EYE`; `lookdev.rs` `convert`). Cora's materials already carry VRoid-style names, so she is classed correctly in live loading but not in the asset view. A slot makes both the same.

| `slot` | Client kind (`style.rs` `Kind`) | Shading | Casts a sun shadow |
|---|---|---|---|
| `"hair"` | `Hair`, or the hair profile when `slop.hair` is present and valid | Without `slop.hair`: today's character hair (angel ring by the global shine preset, coloured hair rim, no general rim). With it: [the hair profile](#the-hair-profile). | yes |
| `"skin"` | `Skin` | Light, warm shadows at 45% of the plain depth; no core band. | yes |
| `"face"` | `Face` if a [face shadow map](#the-face-shadow) is found, else `Skin` | Shadow edge from the map and the sun's angle round the head. | no |
| `"eyes"` | `FacePart` | Unshaded except by cast shadows. For the drawn face parts: iris, eye whites, lashes, brows, eyelines, and the mouth's line and slit. Not tint layers. | no |
| `"tint"` | `Tint` | A layer **multiplied over the lit skin under it**: blush, freckles, anything darkening or warming skin. Its colour (base colour × vertex colour × texture) is a factor, mixed toward 1 by its alpha, and the blend multiplies what is drawn behind it (`AlphaMode::Multiply`: `skin × mix(1, tint, alpha)`). It therefore carries exactly the skin's light and shadow, and never glows on a shadowed cheek. Give it `alphaMode` BLEND (or MASK) and an alpha; an opaque tint multiplies its whole surface. It draws after the opaque skin, so it must lie on or just in front of it. | no |
| `"cloth"` | `Plain` | The general ramp and the general rim. | yes |

- A `character` file's material without a slot is classed by name with `vrm` true, and the client warns once naming the material.
- **How composed characters draw their tint layers (2026-11-19):** by name, as face parts. `characters/compose.rs` `kind_of` classes `…FaceTint_00_FACE` (lips and blush) and `…FaceOverlay_00_FACE` (lines and freckles) as `FacePart`: lit by the sun's colour at full strength whatever the angle, darkened only by cast shadows (`toon.face.z`), and alpha-blended over the skin. So they do not darken with the skin's own shade band. Composed characters are left as they are; the hand-made `"tint"` is the shaded multiply above.
- An unknown slot value is treated as `"cloth"`, with one warning.
- The materials' other glTF properties keep their meanings: `baseColorFactor`, `baseColorTexture`, `alphaMode`, `alphaCutoff` and `doubleSided`. Metallic, roughness, `KHR_materials_specular` and the other PBR terms have no effect: the toon shader never evaluates the BRDF.

## The hair profile

The profile is opt-in per hair material. A `"hair"` material whose `slop` object contains a `hair` object is shaded by it:

```json
"extras": {
  "slop": {
    "slot": "hair",
    "hair": {
      "shade":     [88, 42, 27],
      "mid":       [152, 72, 43],
      "light":     [184, 98, 60],
      "highlight": [214, 140, 96],
      "t1": -0.20,
      "t2": 0.40,
      "edge": 0.02,
      "highlight_feather": 0.08
    }
  }
}
```

In the example, `shade` and `mid` are the drawing's measured hair-shaded and hair-lit patches from the diagnosis. `light` and `highlight` are placeholders: sample the author's own values from the drawing.

| Key | Type | Unit or range | Default | Meaning |
|---|---|---|---|---|
| `shade` | `[r, g, b]` integers | sRGB, 0–255 | **required** | The colour in the shade band and in cast shadow. |
| `mid` | `[r, g, b]` integers | sRGB, 0–255 | **required** | The colour between `t1` and `t2`. |
| `light` | `[r, g, b]` integers | sRGB, 0–255 | **required** | The colour above `t2`. For two bands only, give the same value as `mid`. |
| `highlight` | `[r, g, b]` integers | sRGB, 0–255 | **required** | The broad highlight's colour, where the mask is set. |
| `t1` | number | N·L, −1 to 1 | `-0.20` | Shade→mid threshold. The default is today's general terminator (`style.rs` `threshold`). |
| `t2` | number | N·L, −1 to 1, > `t1` | `0.40` | Mid→light threshold. |
| `edge` | number | N·L, ≥ 0 | `0.02` | Half-width of each band's transition. Today's general softness is 0.02. The client never draws an edge narrower than one pixel (`fwidth(N·L)`), so 0 means "as sharp as the screen allows", not aliasing. |
| `highlight_feather` | number | mask units, 0–0.5 | `0.08` | Half-width of the highlight's edge round the mask's 0.5 contour, also never narrower than one pixel (`fwidth(mask)`). |

- **Validation:**
  - If any of the four colours is missing or malformed, or `t2 ≤ t1`, the client ignores `hair` for that material. It shades the material as plain character hair (the first row of the slot table) and warns once.
  - Unknown keys are ignored.
  - There is no brush noise in the profile: the bands are clean lines.
- **Colour space: sRGB, 0–255 integers.**
  - Swatches are picked from drawings and from the calibration frame's screenshots, which are sRGB.
  - Blender's colour picker shows sRGB hex.
  - The diagnosis's colours are sRGB 0–255.
  - The client's existing hair palette is sRGB values too (`toon.wesl` `hair_tints`).
  - The client converts each swatch to linear once, when it builds the material. Hex strings and floats are not accepted, so one value has one spelling.
- **Swatches are base colours (albedo), not screen colours.** They are lit like every other surface: by the sun's colour and the client's exposure, and they then pass through the grade. A swatch therefore never appears on screen as its own value. Authors tune swatches until the [calibration frame](#the-calibration-frame) measures the drawing's colours, the way the diagnosis recommends ("tune the asset's vertex dyes and atlas swatches against measured samples after the grade").
- **The palette replaces the hair's colour; it does not multiply it.** On profile hair, the RGB of the vertex colours (`COLOR_0`), of `baseColorFactor` and of `baseColorTexture` is ignored. Their alpha still multiplies, and still drives `alphaMode`/`alphaCutoff`, so cut-out cards work.
  - **Why replace:** Cora's gloss is painted into `COLOR_0`. Holding it constant was the one control that removed the broad sweep. Multiplying would keep the painted streak under the new bands, and the swatches could then be calibrated only against a per-vertex average.
  - **What three flat bands need:** one colour per band, from one place.
  - **Lock separation:** it must come from the form, as the diagnosis notes: lighting-normal breaks between the main masses, the outline, and silhouettes with comparable lock shapes. It cannot come from dye.
  - **Painted separation:** if paint is later needed for that, it becomes a second mask channel in a new contract version, not dye under the palette.

**What the client computes** (`toon.wesl` `hand_hair`), so that the swatches' meaning is exact. Here `aa(t, w, x) = smoothstep(t − w′, t + w′, x)` with `w′ = max(w, fwidth(x))`:

```
ndl   = dot(N, L)                                  // the shading normal and the sun's direction
vis   = sun shadow visibility (0..1)               // the same cascade lookup as other surfaces
s1    = aa(t1, edge, ndl) * vis                    // out of shade: in cast shadow s1 = 0
s2    = aa(t2, edge, ndl)
level = mix(shade, mix(mid, light, s2), s1)
h     = aa(0.5, highlight_feather, mask) * s1      // the highlight only where the sun reaches
base  = mix(level, highlight, h)
color = base * sun  +  base * sky_fill * mix(1, 0.45, s1)  +  point lights  +  emission
```

- The `shade` swatch *is* the shadow colour. There is no further hue-shifted darkening, no core band, no general rim, no Fresnel hair rim and no angel ring.
- The global hair-shine preset (`LIVING_GAME_HAIR_SHINE`, `style.rs` `HAIR_SHINES`) does not apply to profile hair.
- Rain's wet sheen and the camera's screen rim apply as they do to all characters.
- A hair material's profile is part of its content key, so every hair mesh with the same base material and the same `slop.hair` shares one material and batches.

## The highlight mask

The mask is one scalar per surface point: where the broad highlight lies. It comes from **one** of two sources.

### Per vertex: `_HIGHLIGHT`

- **glTF:** a custom attribute on each hair primitive, `"attributes": { "_HIGHLIGHT": <accessor> }`. The accessor is `SCALAR`, `componentType` 5126 (FLOAT), not normalized, values 0–1, one per vertex. Integer and normalized encodings are not accepted: Bevy's custom-attribute path needs `Float32`.
- **Blender:** a **Float** attribute on the **Point** domain named `_HIGHLIGHT`, exported with *Include → Attributes* (`export_attributes=True`). A Face Corner attribute is not exported as a vertex attribute, so paint on points. Split vertices where the highlight needs a hard boundary across an edge.
- **How it reaches the shader:** a standalone GLB's custom attribute does not reach the shader by itself. The client carries it the way composition carries `_GREY` and `_RING` (`characters/compose.rs`):
  1. `main.rs` registers it with the glTF loader as `add_custom_vertex_attribute("HIGHLIGHT", ATTRIBUTE_HIGHLIGHT)`. The gltf crate names `_HIGHLIGHT` `Semantic::Extras("HIGHLIGHT")`, without the underscore, as with `GREY`, `RING` and `OUTLINE_NORMAL`. Here `ATTRIBUTE_HIGHLIGHT = MeshVertexAttribute::new("Highlight", 0x5c3e_9a04, VertexFormat::Float32)`, the next of the client's own ids.
  2. When `lookdev::convert` converts a profile hair mesh, it removes the attribute and writes the mesh's second UVs (`handmade.rs` `pack_highlight`) (`ATTRIBUTE_UV_1`), once per mesh asset. It writes `x` = the vertex's `_GREY` if the file has one, else 0, and `y` = `1 + clamp(_HIGHLIGHT, 0, 1)`. Bevy's vertex path already brings UV1 to the fragment shader (`in.uv_b`), and the toon vertex shader turns UV1 only for a face's skin, so hair's arrives untouched.
  3. The profile's shader branch reads `mask = in.uv_b.y − 1`. A value of −1 (y = 0) means "no per-vertex mask".
- **Any TEXCOORD_1 a hair primitive carries is replaced.** Do not put other data in a profile hair's second UV map.

### Mask texture (optional): `<stem>.hair.png`

Use a texture when the highlight needs a sharper shape than the hair's triangles can trace.

- **File:** a PNG beside the GLB the client loads, named for it: `view/own-cora-live.glb` → `view/own-cora-live.hair.png`. A block-compressed copy `<stem>.hair.ktx2`, if present, is preferred, by the same rule as face maps (`lookdev::face_map_files`).
- **Override per material:** `slop.hair.highlight_map` (string), a path under the asset folder, for example `"view/cora-fringe.hair.png"`. It wins over the file beside the GLB.
- **Channel:** **R**, linear data, loaded with sRGB off. Write 8-bit greyscale (PNG colour type 0) or RGB/RGBA with the mask in R. **G** is the lock ink field (v1.1, [lock ink lines](#lock-ink-lines-v11)); B is reserved (write 0), A 255. The bundle step may compress it.
- **Coordinates:** the hair primitive's **TEXCOORD_0**, with glTF's convention (UV (0, 0) is the image's top-left). Blender's exporter flips V for you, so a mask painted in Blender against the hair's UV map lines up.
- **Not embedded in the GLB:** Bevy's glTF loader decodes any image that no material uses as a linear channel as sRGB colour. A mask embedded in the file would arrive gamma-encoded, so it is a sidecar, as face maps are.
- **Binding:** the client binds it in the face map's slot (`toon.wesl` binding 101/102). Hair materials leave that slot unused, so the texture adds one texture read and no new binding.
- **With both sources, the larger wins** (v1.1; v1 let the texture replace `_HIGHLIGHT`): mask = max(`_HIGHLIGHT`, R). A texture made only for ink (R = 0) therefore leaves a file's per-vertex highlight as it is, and R can add sharper shapes beside it.
- **The hair needs a real UV unwrap** for any texture: R, G, or both. Cora's exported hair has none: every hair vertex sits at UV (0, 1), so a texture reads one texel everywhere. The audit warns when a hair texture or ink fields meet hair UVs that span no area.

### Semantics

- **One painted silhouette per lock group, on the upper locks:** a broad, drawn shape that follows the locks' painted highlight across them. It is not a ring computed from the view.
- **Values:** 1 inside the highlight and 0 outside. The highlight's edge is the mask's **0.5 contour**.
  - On a per-vertex mask, values between 0 and 1 let the edge fall inside a triangle: a vertex at 0.75 next to one at 0.25 puts the edge halfway between them.
  - On a texture, paint a hard or slightly blurred shape; the client feathers it by `highlight_feather`.
- **0 everywhere else:** the fringe, lock undersides, inner surfaces, tips, and anything under a hat.
- **The mask stays on the model.** It moves with the locks and does not slide with the camera or the light. It shows only where the sun reaches (`h × s1` above): it is gone in the shade band and in cast shadow.
- **No mask means no highlight.** A profile hair with neither source draws three bands and nothing else. There is no fallback ring and no forward-axis guess.
- **Far meshes:** if the file has `Far*` hair nodes (the client's far switch beyond about 10 m), they wear a material with the same `slop` (or the same material). Each carries its own `_HIGHLIGHT`, or uses the same mask texture through matching UVs.

## Lock ink lines (v1.1)

Cora's drawing separates locks with thin dark ink lines where they meet; the client's outline draws only silhouettes, so the locks merge. The profile can draw those lines from a distance field in the mask texture.

**The field:** `<stem>.hair.png`, channel **G**, linear, in the hair's TEXCOORD_0 (like R): the distance from each texel to the nearest lock line, as G = min(1, d / `ink_range`), d in UV units (a texel is 1/width across, 1/height down). 0 is on a line; 1 (255), or a file without G (greyscale), is no ink. R stays the highlight mask; B is 0. Make it with the tool below; do not paint G by hand.

**The fields** (in `extras.slop.hair`, all optional):

| Key | Type | Default | Meaning |
|---|---|---|---|
| `ink` | `[r, g, b]` integers, sRGB 0–255 | `shade` × 0.6, in linear | The line's base colour. It is lit exactly as the shade band is, wherever the line falls (in the lit band too), and shadowed and graded with it: the sun never brightens it beyond the shade band's light. |
| `ink_px` | number, screen pixels | `1.25` | The line's width at the Near stop, in a view 900 pixels tall. It scales with the world size of a pixel at the line (`m_px` below), so lines thicken as the camera comes closer and thin as it goes, up to 4 × `ink_px`. |
| `ink_range` | number, UV units, > 0 | `0.004` | The distance G = 255 stands for. Must equal the `--range` the field was made with. Set it to about half the narrowest spacing between neighbouring lines, in UV: the fade below assumes so. |
| `ink_fade_px` | number, screen pixels | `3.0` | Lines fade out where neighbouring lines would come closer than this on screen (they would merge into a smear and shimmer). |

**When ink is drawn:** only on profile hair, only when the profile sets **at least one** of the four fields, and only when the material has a mask texture. v1 told authors to write G = 0, which here would mean "on a line everywhere", so a v1 texture without ink fields never draws ink. The audit warns when ink fields are set without a texture or with a G that is all 255, and when a texture has a G with lines in it but no ink field is set.

**What the client computes** (`toon.wesl` `hand_hair`):

```
d_uv  = G * ink_range                               // G < 1; the field's texel, bilinear
fw    = max(|∂uv/∂x|, |∂uv/∂y|)                     // UV a pixel spans, along its longer side (screen derivatives)
d_px  = d_uv / fw                                   // distance to the line in screen pixels
m_px  = |view depth| * 2 / (projection[1][1] * viewport height)   // metres a pixel spans at the point's depth
w     = ink_px * min(0.00805 / m_px, 4)             // 0.00805 m: a pixel at the Near stop (9.43 m, 42°, 900 px)
cov   = clamp(min(d_px + 0.5, w/2) - max(d_px - 0.5, -w/2), 0, 1)  // a 1-pixel box across a line w wide
space = 2 * ink_range * m_uv / m_px                 // neighbouring lines' spacing on screen, estimated
cov  *= smoothstep(ink_fade_px, 2 * ink_fade_px, space)
color = mix(color, ink * sun + ink * sky_fill, cov) // the shade band's light
```

- **The antialiasing** is a one-pixel box across the line: a line's coverage sums to its width w across it, wherever it falls among the pixels, so a line thinner than a pixel draws fainter instead of breaking up, and does not flicker as it moves by a fraction of a pixel.
- **The footprint estimate:** the distance field only says how far the nearest line is, not where the next one lies, so the spacing between lines is estimated from `ink_range` (set to half the narrowest spacing): `2 · ink_range` in UV, and on screen that times the hair's texel density `m_uv` (metres per UV unit: the median over the hair mesh's triangles of √(area / UV area), measured when the material is made; `handmade.rs` `metres_per_uv`) over the pixel's size `m_px`. When the spacing drops below `ink_fade_px` the lines fade out over the next doubling, so toward the Far stop the lines first thin with the zoom and then go before they merge.
- **Why the depth, not screen derivatives, for `w` and the fade:** derivatives are constant over each 2×2 pixel quad, so a fade or width driven by them steps from quad to quad, and the steps crawl as the camera moves. That measured as shimmer in the hand-made line's first build. The pixel's size at its depth and a per-material texel density are smooth on screen. `d_px` keeps `fw`, which measured steady. A mesh without UV area falls back to `2 · ink_range / fw`.
- **Sampling:** the field is sampled with the pixel's own UV gradients (`textureSampleGrad`), bilinear, in the same tap as R: no extra pass and no extra read where the highlight texture is already read; one read when ink alone brings the texture. A PNG has no mips, so it is read at level 0, like the face shadow map; a KTX2 copy's mips are used, and a mipped distance field only thins distant lines further.
- The line draws over the bands and the highlight, in cast shadow and in light alike.
- **`ink_fade_px` against shimmer** (laptop, 2026-11-19, `hair_shimmer.py` on a Cora copy with stand-in cylindrical hair UVs, 9 strokes, `ink_range` 0.05, `ink_px` 1.25). Ratios F_ink / F_edge, with ink px a frame in brackets; ≤ 1.5 passes:

  | `ink_fade_px` | Near pan | Middle pan | Middle zoom | Far pan / zoom |
  |---|---|---|---|---|
  | 1.0 | 1.00 (288) | 1.53 (119) | 0.82 (115) | 0.86 (47) / 0.97 (44) |
  | 1.5 | 1.00 (288) | 1.53 (119) | 0.82 (115) | 1.16 (27) / 1.17 (14) |
  | 2.0 | 1.00 (288) | 1.53 (119) | 0.83 (113) | faded |
  | 2.5 | 1.00 (288) | 1.71 (94) | 0.90 (81) | faded |
  | **3.0 (default)** | 0.99 (289) | **2.45 (4)** | 1.23 (1) | faded |
  | 3.5 | 0.85 (278)¹ | faded (0.6) | faded | faded |
  | 4.0 | 0.99 (241)¹ | faded (0.1) | faded | faded |
  | 5.0 | 1.63 (6)¹ | faded | faded | faded |

  ¹ From the first shimmer script, whose hair region was a fixed box round Cora's head; the rows without the mark are `hair_shimmer.py`'s. That script gave 0.83 for 3.0's Near pan and 1.97 for its Middle pan.
  - **No value passes the Middle pan with lines there.** Values of 3.5 and above pass it only by fading the lines out at Middle, and 5.0 fails the Near pan in the fade's tail. At 2.0 and below the Middle pan sits at 1.53, its floor with lines fully on, just above the threshold. At 3.0, Middle keeps about 4 faint ink pixels a frame (8–13 levels) in the fade's tail, which is what flickers.
  - **The default stays 3.0:** it shows lines at Near and fades them out by Middle. A file that wants lock lines at Middle can set `ink_fade_px` to 2.0, at a measured 1.53, which is steadier than 3.0's tail and just above the threshold. Values of 1.5 or less also keep lines at Far, where they measured steady (0.86–1.17).

**The tool:**

```
python3 living/tools/characters/ink_field.py LINES.png STEM.hair.png [--range 0.004] [--seams-as-lines --glb FILE.glb [--material NAME]] [--size WxH]
```

- **LINES.png:** the lock lines painted dark on light, at the hair texture's resolution, in the hair's UV space (glTF's top-left origin, as Blender exports an image). A texel is on a line where its luminance is below half (and, with alpha, its alpha above half). Paint lines **one or two texels wide**: the field measures from line texels, so a wide painted line draws wide when the camera is close.
- **The output:** an exact Euclidean distance transform, in UV units, written into G (8 bits: 1/255 of `ink_range` a step, 0.016 of a texel at 1024 px and the default range). R is kept from an existing `STEM.hair.png`, or 0 in a new one; B is 0.
- **`--seams-as-lines`** adds the borders of the hair's UV islands as lines: the edges of the hair primitives used by one triangle only, rasterized from `--glb`. Hair built of lock cards has a lock's outline there. LINES.png may then be `-`.
- Plain Python, no dependencies (the transform is Felzenszwalb and Huttenlocher's exact one, by columns then rows; a few seconds at 1024²). It prints the `ink_range` to put in the extras.

**Calibrating ink:** a patch on a line takes `"sample": "min5"` (the darkest pixel, by luminance, of a 5×5 window instead of the 9×9 median), so a one- or two-pixel line is measured rather than averaged away. Tune `ink` against the drawing's line colour the way the swatches are tuned.

## The face shadow

The face's shadow map path exists already (`toon.wesl` `face_lit`, `lookdev.rs` `convert`, `characters/compose.rs` `toon`). A hand-made face uses it unchanged: export exactly what `living/tools/face_normals.py` writes into VRoid files. A `"face"` material with no map found shades as `"skin"`, as Cora's face does today.

**In the GLB, on every primitive of the `"face"` material:**

| Attribute | glTF | Content |
|---|---|---|
| `TEXCOORD_0` | VEC2 FLOAT | The face's UVs, the ones the colour atlas uses. The shadow map is sampled with them. |
| `TEXCOORD_1` | VEC2 FLOAT | The head's rest-pose forward as `(x, z)` in the mesh's own (bind) space: the **same value on every vertex**. It is `(0, 1)` for a `"+Z"` file and `(0, −1)` for a `"-Z"` file. The toon vertex shader turns it by the skinning (`toon_vertex.wesl`, face kind only), so the face must be **skinned** to the head. |

- **In Blender:** give the face mesh a second UV map with the same value on every corner. Blender's exporter writes `v_gltf = 1 − v_blender`. So, in Blender:
  - for glTF `(0, 1)`, store `(0, 0)`;
  - for glTF `(0, −1)`, store `(0, 2)`.
- **Check the exported accessor:** the calibration command's audit prints it and fails a wrong one.

**The map:**

- **Where it lives:** `<stem>.face.png` beside the GLB the client loads, or its `<stem>.face.ktx2` copy (preferred). Alternatively, the face material's **top-level** extras `{"face_map": "<path under the asset folder>"}`. This is the existing key, outside `slop`. The file beside the GLB is looked for first.
- **Format:** RGB PNG, 8 bits a channel, square (512 or 1024 px), laid out in the face's TEXCOORD_0 space with glTF's top-left origin. It is linear data, loaded with sRGB off.
  - **R:** for light from the **character's own right**, the light's horizontal angle from the face's forward, as a fraction of 180° (0–255 ↔ 0–180°), up to which the texel stays lit.
  - **G:** the same for light from the character's left.
  - **B:** unused (write 0).
  - **Texels outside the face's UV islands:** write 255, 255 (lit), and grow the islands' values a few texels outward so filtering at seams reads no empty texel (`face_normals.py` grows 8).
- **How the shader uses it:** it compares the sun's horizontal angle round the head with R or G, by side, with an edge of `toon.face.x` (style `face_softness`). The shadow edge therefore sweeps across the face as the light turns, whatever the sun's height. A sun nearly overhead leaves the face lit: the lit share rises as the sun's horizontal component falls from 0.2 to 0.04, about 12° to 2° from vertical.
- **"The character's right" is defined by `forward`, not by the file's +X:**
  - for a `"-Z"` file, right is +X in the file;
  - for a `"+Z"` file, right is −X.

  The shader takes the side from the turned TEXCOORD_1, so the map is the same for both orientations: paint R for the cheek that falls into shade last when the light comes from the character's right.
- **How to make one:**
  - **Draw it:** the anime way ([the survey](CHARACTER_RESEARCH.md), §3, and `face_shadow.py`'s method in [designed shadows](CHARACTERS.md#designed-shadows)). Paint the shade for a series of light angles, turn each into a distance field, and interpolate into R and G.
  - **Or start from the ellipsoid:**

    ```
    python3 living/tools/face_normals.py IN.glb OUT.glb --flat 0 --hair 0 --png OUT.face.png
    ```

    This writes TEXCOORD_1 and an ellipsoid-derived map, and leaves face and hair normals as they were (`--flat 0`, `--hair 0`). It finds the face by material name (`…Face…_SKIN`). Cora's face material, `M00_000_00_Face_00_SKIN`, matches. A face material named otherwise needs the name, or TEXCOORD_1 and a map made another way.
- **Keep the face's material to the face only:** the neck and body take `"skin"`, so the jaw line reads where both are in shade.

## The calibration frame

One fixed daylight frame that authors render after every palette change and compare with the drawing, following the diagnosis's matched-control method.

**What is a target and what is tuned.** The colours sampled from the drawing are the **targets**: what the calibrated frame must show on screen, after the light, the exposure and the grade. The palette's base colours (`shade`, `mid`, `light`, `highlight`) are **tuned** until the rendered patches land within tolerance of the targets. A swatch is never set to the drawing's colour and left there: the palette is lit and graded, so a swatch equal to its target renders lighter and less saturated than the target. The tolerances to start with: about ±8 a channel on hair patches and ±10 on the cheek.

- **Scene:** the asset view (`LIVING_GAME_VIEW=view/<file>.glb`) with its default checker ground and the default style.
- **Light:** the sun fixed at 11:00 (`LIVING_GAME_HOUR=11`, `LIVING_GAME_DAY_MINUTES=0`), 9,000 lux.
- **Camera and grade:** the client's defaults for every character: EV100 9.7, toon exposure scale 0.82, TonyMcMapface, bloom 0.12, and the Soft film (`LIVING_GAME_FILM=soft`, as the diagnosis ran). The frame never changes the exposure or the curve: they move every character and the scene.
- **Size and pose:** 1600×900, headless, with the idle clip at 0 s (the file's first clip if it has no `idle`).
- **Shots**, in this order (`NN-` in the file names):
  - `portrait`: yaw 0°, pitch 8°, vertical FOV 35°, aimed at 88% of the height (`idle@0/0:8:0.36:0.88`);
  - `near`: the game camera's Near stop, 8 m up, 58° down, FOV 42°, aimed at the chest (`idle@0/near@0`);
  - `portrait45`: the portrait at yaw 45°, so the t2 band and the highlight show on a turned head (`idle@0/45:8:0.36:0.88`).
  - `--also middle@0` adds the Middle stop (12 m up, FOV 44°), and any other view shot.
- **The targets file:** `<stem>.calibration.json` beside the GLB (or `--targets`), written by the author. An example for Cora is [handmade-hair/cora.calibration.json](handmade-hair/cora.calibration.json): its targets are the drawing's colours (the diagnosis's samples, and the drawing's lighter lock and highlight for `light` and `highlight`), and its shot pixels were picked on the laptop's first Cora pass, on a debug copy whose four swatches were pure colours so each band could be told apart, with the stand-in highlight. A new export moves the bands, so pick the pixels again on the new stills. The palette that pass tuned to within tolerance is in [handmade-hair/cora.extras.json](handmade-hair/cora.extras.json): shade (48, 14, 5), mid (101, 35, 7), light (116, 40, 7), highlight (134, 50, 12), much darker and more saturated than their targets.

  ```json
  {
    "drawing": "/abs/or/relative/path/face.png",
    "tolerance": { "hair": 8, "other": 10 },
    "patches": {
      "hair shade": { "drawing": [553, 106], "swatch": "shade", "portrait": [874, 497] },
      "hair mid":   { "target": [152, 72, 43], "swatch": "mid", "portrait": [825, 264], "portrait45": [800, 270] },
      "skin cheek": { "target": [235, 164, 128], "portrait": [873, 414] }
    }
  }
  ```

  - A patch's target is `"target": [r, g, b]` (display sRGB, 0–255), or `"drawing": [x, y]`: the 9×9 median of the drawing (the top-level `"drawing"` image, relative to the targets file) at that pixel.
  - Each shot key (`portrait`, `near`, `portrait45`) gives the pixel to measure in that shot, as the 9×9 median. A patch can be measured in any of the shots.
  - `"sample": "min5"` (v1.1, for ink lines) takes instead the darkest pixel, by luminance, of a 5×5 window, in the shots and in the drawing.
  - Tolerance: the patch's own `"tolerance"`, else the file's `"tolerance"` by whether the patch's name starts with "hair", else 8 and 10.
  - `"swatch"` (optional): the palette swatch the patch tunes. The report then suggests that swatch's next value: each linear channel scaled by target ÷ measured, averaged over the shots. Rerun after each change, since the grade is not linear.
- **The command:**

  ```
  just living-game-calibrate view/own-cora-live.glb [--targets T.json] [--also middle@0] [--no-run]
  ```

  It builds the client (release; `CARGO_TARGET_DIR` is honoured) and runs `living/tools/characters/calibrate.py`. It writes `.local/living/calibrate/<stem>/<time>/`: `stills/<stem>/NN-<shot>.png`, `colours.csv` (each patch and shot: target, measured, Δ, tolerance, pass, luminance and saturation of both), `report.json` and `client.log`. It prints each patch's target, measured colour, Δ and pass or fail, the swatch suggestions, and **PASS** or **FAIL**. The command is free: no model calls and no world.
- **The audit**, printed first, fails the run on an error:
  - the scene's `slop`: `contract` 1, `character` "handmade", `forward` "+Z" or "-Z", and the face's and eyes' normals pointing the declared way;
  - every material's slot (a material without one is a warning, an unknown slot an error), a hair profile only on hair, its four swatches (three integers 0–255), `t2` above `t1`, unknown profile keys;
  - the mask: `_HIGHLIGHT`'s accessor (SCALAR FLOAT), its values and coverage (the share of hair vertices above 0.5), the mask texture if there is one, both at once (a warning: the texture wins), neither (a warning: no highlight);
  - the face: skinned, TEXCOORD_1 present, VEC2 FLOAT, the same on every vertex and equal to the declared forward, and a face shadow map found;
  - a tint that is opaque (a warning), and an `anim/` copy whose scene `slop` differs;
  - ink (v1.1, warnings): `ink_range` above 0, `ink_px` and `ink_fade_px` numbers, `ink` three integers; ink fields without a mask texture, or with a texture whose G is missing or holds no line; a G with lines but no ink field; hair UVs that span no area while a texture or ink is set.
- **Ink shimmer** (v1.1), for a file with ink fields:

  ```
  python3 living/tools/characters/hair_shimmer.py view/<file>.glb [--out DIR] [--binary PATH] [--plain-stills DIR] [--ink-stills DIR]
  ```

  It takes the file as it is, with its own `ink_range`, `ink_px`, `ink_fade_px` and `ink`, and as the reference a temporary copy without the ink fields (the hair-only profile, highlight and all; removed afterwards). It renders both through the asset view: 1600×900, 11:00, paused idle, springs off, at the Near, Middle and Far stops, a pan (16 stills, 0.1° a frame) and a zoom (16, the height up 0.3% a frame) each. For each sequence it prints the flicker ratio F = Σ|x(i+1) − 2·x(i) + x(i−1)| / Σx of the ink's darkening (F_ink) and of the profile's own band edges (F_edge), over the hair pixels round the ink, and **passes when F_ink ≤ 1.5 × F_edge**: the line flickers no more, per unit of what it draws, than the band edges already seen in motion, with half again for a line's two edges. A sequence whose ink darkens fewer than one pixel a frame by more than 8 levels is `faded`, not scored. Output goes to `.local/living/hair-shimmer/<stem>/<time>/` (`plain/`, `ink/`, `shimmer.json`); the exit code is 1 on a failing sequence. `--plain-stills` and `--ink-stills` reuse an earlier run's still folders. Plain Python; about 25 s to score, plus the two renders.
- **A palette is done** when every measured patch passes. The tolerances are starting values, to agree with the owner on the first Cora pass, and the owner judges the result in-game.

### Calibrating lock ink against the display floor

If the drawing's dark ink falls outside the rendered range at its registered patch, capture the same daylight frame with every hair palette colour and the ink set to black. Sample the same 5 × 5 min5 ink window on this control and the production portrait. Sample the production auburn mid in its registered 9 × 9 median window.

Decode each RGB triplet from sRGB into linear light. For each channel compute `floor + (drawing_ink / drawing_mid) * (rendered_mid - floor)`, then encode the result to sRGB and round to an 8-bit target. This preserves the drawing's ink contrast over the available range. Use a mid with a positive value in each channel. Record the measured floor, both source swatches, the measured mid, the patch coordinates and the resulting target in the calibration JSON. Use the rebased RGB as the ink patch's `target` and keep the original absolute result in the evidence. Repeat the floor measurement when confirming on another renderer or grade. [Cora's registered example](char-live-2/hair/final/own-cora-live.calibration.json)

## Compatibility

- **A file without `slop` extras behaves exactly as today** on both paths:
  - name rules gated by the `vrm` flag;
  - live spawn turned `yaw + π`;
  - the asset view's turn and `vrm` detection by `.vrm` extension, `vroid-` file name or VRM extension;
  - `_GREY`/`_RING` as composed hair carries them;
  - the global hair-shine preset.

  Measured on the laptop (2026-11-19), the branch against its base 8851982d2, through the asset view at 11:00 with springs off, in a three-quarter and a Near shot:
  - **A VRoid base:** `recipe:adult:3` with `LIVING_GAME_COMPOSE=0`, on a paused idle frame. 1 pixel differs, by 3 levels or less; the Near shot is identical. Shown on its own (`lookdev/vroid-…glb`), a VRoid base's procedural breathing runs on wall time, so two runs of the same build already differ, and a still says nothing about shading.
  - **A composed person:** `look:lk_000f47c0d8aa4056`, on a paused idle frame. The Near shot is identical. At three-quarter, 89 pixels differ by 3 levels or less, outside the eyes, whose blink differs between runs of the same build.
  - **A scenery model:** `envs/cullet/ash_house/ash_house.glb`. 1 channel value differs by 1.
  - **Cora's untouched file:** 3 pixels differ by 1 level against the diagnosis's raw stills, and its calibration patches equal the diagnosis's raw numbers.
- **Generated (composed) characters are not affected.** `characters/compose.rs` classes style materials by name (`kind_of`) and packs `_GREY` and `1 + _RING` into UV1 as now. Their hair keeps the ring presets. They move to the profile only after an art comparison across hair colours and silhouettes, as a separate decision.
- **A `character` file without a `hair` profile** gets the slot classification and the forward turn, and today's character hair. That alone removes the asset view's cream rim on Cora's hair.
- **Within a profile hair material:**
  - no general rim, no hair rim, no ring;
  - vertex-colour RGB ignored;
  - UV1 overwritten.

  These are the only behaviours that differ from today's character hair, and they apply only where `slop.hair` is set.

## Cost

The profile replaces the ring's half vector, UV noise, lock hashes, Fresnel and up to eight strand samples with two thresholds, one interpolated scalar and, at most, one texture read. It adds no draw and no pass.

**Measured on the laptop** (Apple M4 Pro, Metal, 2026-11-19): 8 Coras in the asset view (`LIVING_GAME_VIEW_COPIES=8`), today's character hair (slots, no profile) against the profile, uncapped (`LIVING_GAME_FPS_CAP=0`), in alternating runs, each run's median frame time over 10 s of steady frames.
- **Why frame time:** wgpu offers no timestamp queries on this Metal device, so Bevy's per-pass GPU times are absent, and there is no Xcode for a Metal trace. This is the whole frame, not an isolated GPU time.
- **8 near-drawn at the Near stop, 1600×900:** today 3.30 and 3.82 ms, the profile 3.40 and 3.24 ms.
- **The same 8 seen close over the crown at 3840×2160,** where hair covers 31% of the frame: today 8.22, 7.04, 7.88 and 7.99 ms, the profile 8.51, 7.50, 7.31 and 8.86 ms. Paired, the profile is +0.29, +0.45, −0.56 and +0.87 ms: a mean of +0.26 ms against about 1 ms of run-to-run spread.
- **The verdict:** no difference between the two paths is measurable on this machine. Other sessions shared the laptop, and the main world's own work varied between 2.0 and 3.7 ms a frame across runs.

## Cora, complete

What `own-cora-live.glb` would carry under this contract. The scene's extras:

```json
{ "slop": { "contract": 1, "character": "handmade", "forward": "+Z" } }
```

Each material's extras:

| Material | `extras` |
|---|---|
| `M00_000_Hair_00_HAIR` | `{"slop": {"slot": "hair", "hair": {"shade": [88,42,27], "mid": [152,72,43], "light": [r,g,b], "highlight": [r,g,b], "t1": -0.20, "t2": 0.40, "edge": 0.02, "highlight_feather": 0.08}}}`, with `light` and `highlight` sampled from the drawing |
| `M00_000_00_Body_00_SKIN` | `{"slop": {"slot": "skin"}}` |
| `M00_000_00_Face_00_SKIN` | `{"slop": {"slot": "face"}}` |
| `M00_000_00_Eye_00_EYE`, `…EyeIris_00_EYE`, `…FaceEyeline_00_FACE`, `…FaceBrow_00_FACE` | `{"slop": {"slot": "eyes"}}` |
| `M00_000_00_FaceTint_00_FACE` (freckles and blush, alpha-blended) | `{"slop": {"slot": "tint"}}` |
| `M00_001_01_Cloth_01_CLOTH` | `{"slop": {"slot": "cloth"}}` |

The mesh data and sidecars:

- **Hair primitives:** `_HIGHLIGHT` (SCALAR FLOAT), 1 on one shape per upper lock group. Alternatively, `own-cora-live.hair.png` in the hair's UV0.
- **Face primitives:** TEXCOORD_1 = (0, 1) on every vertex, and `own-cora-live.face.png` beside the file.
- **Calibration targets:** `own-cora-live.calibration.json`.

[handmade-hair/cora.extras.json](handmade-hair/cora.extras.json) is this as a spec for `living/tools/characters/handmade_extras.py IN.glb OUT.glb SPEC.json`, which writes a copy with the extras (and, with `--test-highlight`, a stand-in `_HIGHLIGHT` for trying the client before one is painted).

## Export checklist (Blender)

1. Set the scene custom property `slop` (contract, character, forward) and a `slop` on every material.
2. Hair: a Float, Point-domain attribute `_HIGHLIGHT`, and/or a mask PNG in the hair's UV0 (R channel).
3. Face: a second UV map holding the constant forward, in Blender's V-flipped value. The face must be skinned to the head.
4. Export GLB with *Include → Custom Properties* and *Include → Attributes* on.
5. Put the `.face.png`, the optional `.hair.png` and the `.calibration.json` beside the GLB, and beside its `anim/` copy if one exists.
6. Run the calibration frame (`just living-game-calibrate view/<file>.glb`) and read its contract audit before handing the file over.

## Sources in the code

- **The contract's reader:** `living/game/src/handmade.rs`: the scene's and materials' `slop`, slots to kinds, the profile's parameters, the mask's packing, the forward turn (`on_ready`) and the forward in a mesh's frame; used by `lookdev.rs` `convert`, the one conversion both the asset view and live loading go through.
- **The profile and the tint in the shader:** `toon.wesl` `hand_hair` (`Kind::HandHair`, 5) and the tint's multiply (`Kind::Tint`, 6); their parameters in `style.rs` `ToonParams::hand`, `hand_bands` and `file`, kept per material when the style changes.
- **The calibration frame:** `living/tools/characters/calibrate.py` (the `living-game-calibrate` recipe); the extras writer `living/tools/characters/handmade_extras.py`.

- **Material kinds and the name rules:** `living/game/src/lookdev.rs` `convert`; `style.rs` `Kind`, `Style::kind`.
- **UV1 packing and attribute ids:** `characters/compose.rs` (`ATTRIBUTE_GREY`, `ATTRIBUTE_RING`, `ATTRIBUTE_OUTLINE_WIDTH` 0x5c3e_9a01–03); loader registration in `main.rs`.
- **Hair light, the ring and `facing()`:** `toon.wesl` `hair_light` and `facing`; the presets in `style.rs` `HAIR_SHINES`.
- **The face map:**
  - the shader: `toon.wesl` `face_lit`; `toon_vertex.wesl` (turning TEXCOORD_1);
  - the client: `lookdev::face_map_files`, `face_map_of`;
  - the format: `living/tools/face_normals.py` (its docstring and `thresholds`).
- **The bands, shadow colour and sky fill the profile replaces:** `toon_light.wesl` `bands`, `banded`.
- **Forward turns:** `characters.rs` `spawn` (`yaw + PI`), `view.rs` (`turn`), `lookdev.rs` `build_lineup`.
