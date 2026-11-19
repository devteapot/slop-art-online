# Hand-made characters: the hair and face contract

**Status (2026-11-19): contract v1, proposed. Nothing in it is implemented yet.** This is phase 1 of the handmade-hair track. It is the format that dev-box's live Blender session authors to. Phase 2 builds the client side after the character team agrees the contract. A change to any name or meaning below needs a new contract number (`slop.contract`).

**Why:** dev-box's hand-made character Cora (`own-cora-live.glb`) read as a glossy helmet in the client. The diagnosis (`.local/living/cora-material/FINDINGS.md` on the laptop) found four causes:

- the gloss is painted into the hair's vertex colours;
- the asset view classes the hair `Plain`, so it takes the cream general rim;
- the grade (exposure, TonyMcMapface, bloom, soft film) lifts and washes the colours;
- the file has no way to say what it is.

The owner's art target is **flat cel bands, at most about three steps, plus one broad highlight.**

The contract gives a standalone character file five things:

1. a declaration that it is a character, and which way it faces;
2. a slot on each material;
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

**What `forward` changes:** the root's turn, so the character faces where the game says.

- **Live loading** (`characters::spawn`) turns the root `yaw + π` today, because VRM 0.x files face −Z. A `"+Z"` file is turned `yaw`, and a `"-Z"` file `yaw + π`.
- **The asset view** turns a `"+Z"` file 0 and a `"-Z"` file π, so both face the camera.
- **Cora faces +Z.** Blender's front (−Y) exports to glTF +Z, so a character modelled facing Blender's front view is `"+Z"`.

`toon.wesl` `facing()` assumes a −Z file (`-m[2]`). The hair profile never uses it, because its highlight comes from the [mask](#the-highlight-mask). Face shading takes the head's forward from the face's own TEXCOORD_1, not from `facing()`.

When `forward` is missing on a `character` file, the client warns once and keeps today's turn for that path: 0 in the asset view and π live. A `"+Z"` file then faces backwards live.

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

`slop.slot` (string) is one of the five values below. In a file with `slop.character`, the slot overrides the name rules. Without a slot, the client classes the material by name and the file's `vrm` flag, as today (`…_HAIR`, `…Face…_SKIN`, `…_SKIN`, `…_FACE`, `…_EYE`; `lookdev.rs` `convert`). Cora's materials already carry VRoid-style names, so she is classed correctly in live loading but not in the asset view. A slot makes both the same.

| `slot` | Client kind (`style.rs` `Kind`) | Shading | Casts a sun shadow |
|---|---|---|---|
| `"hair"` | `Hair`, or the hair profile when `slop.hair` is present and valid | Without `slop.hair`: today's character hair (angel ring by the global shine preset, coloured hair rim, no general rim). With it: [the hair profile](#the-hair-profile). | yes |
| `"skin"` | `Skin` | Light, warm shadows at 45% of the plain depth; no core band. | yes |
| `"face"` | `Face` if a [face shadow map](#the-face-shadow) is found, else `Skin` | Shadow edge from the map and the sun's angle round the head. | no |
| `"eyes"` | `FacePart` | Unshaded except by cast shadows. Use it for every drawn face part: irises, eye whites, lashes, brows, eyelines, mouth interior, blush and tint layers. | no |
| `"cloth"` | `Plain` | The general ramp and the general rim. | yes |

- A `character` file's material without a slot is classed by name with `vrm` true, and the client warns once naming the material.
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

**What the client will compute (phase 2)**, so that the swatches' meaning is exact. Here `aa(t, w, x) = smoothstep(t − w′, t + w′, x)` with `w′ = max(w, fwidth(x))`:

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
- **How it reaches the shader:** a standalone GLB's custom attribute does not reach the shader today. The client will carry it the way composition carries `_GREY` and `_RING` (`characters/compose.rs`):
  1. `main.rs` registers it with the glTF loader as `add_custom_vertex_attribute("HIGHLIGHT", ATTRIBUTE_HIGHLIGHT)`. The gltf crate names `_HIGHLIGHT` `Semantic::Extras("HIGHLIGHT")`, without the underscore, as with `GREY`, `RING` and `OUTLINE_NORMAL`. Here `ATTRIBUTE_HIGHLIGHT = MeshVertexAttribute::new("Highlight", 0x5c3e_9a04, VertexFormat::Float32)`, the next of the client's own ids.
  2. When `lookdev::convert` converts a profile hair mesh, it removes the attribute and writes the mesh's second UVs (`ATTRIBUTE_UV_1`), once per mesh asset. It writes `x` = the vertex's `_GREY` if the file has one, else 0, and `y` = `1 + clamp(_HIGHLIGHT, 0, 1)`. Bevy's vertex path already brings UV1 to the fragment shader (`in.uv_b`), and the toon vertex shader turns UV1 only for a face's skin, so hair's arrives untouched.
  3. The profile's shader branch reads `mask = in.uv_b.y − 1`. A value of −1 (y = 0) means "no per-vertex mask".
- **Any TEXCOORD_1 a hair primitive carries is replaced.** Do not put other data in a profile hair's second UV map.

### Mask texture (optional): `<stem>.hair.png`

Use a texture when the highlight needs a sharper shape than the hair's triangles can trace.

- **File:** a PNG beside the GLB the client loads, named for it: `view/own-cora-live.glb` → `view/own-cora-live.hair.png`. A block-compressed copy `<stem>.hair.ktx2`, if present, is preferred, by the same rule as face maps (`lookdev::face_map_files`).
- **Override per material:** `slop.hair.highlight_map` (string), a path under the asset folder, for example `"view/cora-fringe.hair.png"`. It wins over the file beside the GLB.
- **Channel:** **R**, linear data, loaded with sRGB off. Write 8-bit greyscale (PNG colour type 0) or RGB/RGBA with the mask in R. G, B and A are reserved: write 0 in G and B, and 255 in A. The bundle step may compress it.
- **Coordinates:** the hair primitive's **TEXCOORD_0**, with glTF's convention (UV (0, 0) is the image's top-left). Blender's exporter flips V for you, so a mask painted in Blender against the hair's UV map lines up.
- **Not embedded in the GLB:** Bevy's glTF loader decodes any image that no material uses as a linear channel as sRGB colour. A mask embedded in the file would arrive gamma-encoded, so it is a sidecar, as face maps are.
- **Binding:** the client binds it in the face map's slot (`toon.wesl` binding 101/102). Hair materials leave that slot unused, so the texture adds one texture read and no new binding.
- **When a mask texture is found, it replaces the per-vertex mask** for that material. A `_HIGHLIGHT` in the same file is ignored there, with one warning, so one source draws each highlight.

### Semantics

- **One painted silhouette per lock group, on the upper locks:** a broad, drawn shape that follows the locks' painted highlight across them. It is not a ring computed from the view.
- **Values:** 1 inside the highlight and 0 outside. The highlight's edge is the mask's **0.5 contour**.
  - On a per-vertex mask, values between 0 and 1 let the edge fall inside a triangle: a vertex at 0.75 next to one at 0.25 puts the edge halfway between them.
  - On a texture, paint a hard or slightly blurred shape; the client feathers it by `highlight_feather`.
- **0 everywhere else:** the fringe, lock undersides, inner surfaces, tips, and anything under a hat.
- **The mask stays on the model.** It moves with the locks and does not slide with the camera or the light. It shows only where the sun reaches (`h × s1` above): it is gone in the shade band and in cast shadow.
- **No mask means no highlight.** A profile hair with neither source draws three bands and nothing else. There is no fallback ring and no forward-axis guess.
- **Far meshes:** if the file has `Far*` hair nodes (the client's far switch beyond about 10 m), they wear a material with the same `slop` (or the same material). Each carries its own `_HIGHLIGHT`, or uses the same mask texture through matching UVs.

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
- **Check the exported accessor:** phase 2's checker prints it.

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

    This writes TEXCOORD_1 and an ellipsoid-derived map, and leaves face and hair normals as they were (`--flat 0`, `--hair 0`). Today it finds the face by material name (`…Face…_SKIN`). Cora's face material, `M00_000_00_Face_00_SKIN`, matches. Phase 2 makes it accept `slop.slot = "face"` instead.
- **Keep the face's material to the face only:** the neck and body take `"skin"`, so the jaw line reads where both are in shade.

## The calibration frame

Phase 2 builds the frame, and the measurements follow the diagnosis's matched-control method. It is one fixed daylight frame that authors render after every palette change and compare with the drawing.

- **Scene:** the asset view (`LIVING_GAME_VIEW=view/<file>.glb`) with its default checker ground and the default style.
- **Light:** the sun fixed at 11:00 (`LIVING_GAME_HOUR=11`, `LIVING_GAME_DAY_MINUTES=0`), 9,000 lux.
- **Camera and grade:** the client's defaults for every character: EV100 9.7, toon exposure scale 0.82, TonyMcMapface, bloom 0.12, and the Soft film (`LIVING_GAME_FILM=soft`, as the diagnosis ran). The frame never changes the exposure or the curve: they move every character and the scene.
- **Size and pose:** 1600×900, headless, with the idle clip at 0 s (`LIVING_GAME_VIEW_CLIP=idle`).
- **Shots:**
  - Portrait: yaw 0°, pitch 8°, vertical FOV 35°, aimed at 88% of the height (`idle@0/0:8:0.36:0.88`).
  - Near game camera: 8 m up, 58° down, FOV 42°, aimed at the chest (`idle@0/near@0`).
  - Phase 2 adds a portrait at yaw 45°, so the t2 band and the highlight show on a turned head.
- **Swatch targets:** a JSON file beside the GLB, `<stem>.calibration.json`, written by the author:

  ```json
  {
    "drawing": "path/to/reference.png",
    "patches": {
      "hair shade":     { "drawing": [553, 106], "portrait": [874, 497] },
      "hair mid":       { "drawing": [474, 165], "portrait": [825, 264] },
      "hair light":     { "drawing": [0, 0],     "portrait": [0, 0] },
      "hair highlight": { "drawing": [0, 0],     "portrait": [0, 0] },
      "skin cheek":     { "drawing": [601, 336], "portrait": [873, 414] }
    }
  }
  ```

  Pixel centres are in each image, and the role names are free text. Unmeasured roles carry zeros (`[0, 0]`) and are skipped. The values shown are Cora's patches from the diagnosis (`sample-points.json`). The tool measures the 9×9 median of each patch in display sRGB in the drawing and in the shot. It reports each role's RGB, Δ against the drawing, relative luminance and HSV saturation, as the diagnosis's `colours.csv` does.
- **The command (phase 2):**

  ```
  just living-game-calibrate view/own-cora-live.glb
  ```

  It writes `.local/living/calibrate/<stem>/<time>/`: the stills, a contact sheet beside the drawing, `colours.csv` and the client log. It also prints the file's contract audit: slots, profile values, the mask source and its coverage, TEXCOORD_1 on the face, and the face map found. The command is free: no model calls and no world.
- **A palette is done** when every measured hair role's Δ is within about ±8 on each channel and the cheek's within about ±10. These are starting tolerances, to agree with the owner on the first Cora pass, and the owner judges the result in-game.

## Compatibility

- **A file without `slop` extras behaves exactly as today** on both paths:
  - name rules gated by the `vrm` flag;
  - live spawn turned `yaw + π`;
  - the asset view's turn and `vrm` detection by `.vrm` extension, `vroid-` file name or VRM extension;
  - `_GREY`/`_RING` as composed hair carries them;
  - the global hair-shine preset.

  Phase 2's acceptance includes identical pixels for a VRoid base, a composed person and a scenery model before and after.
- **Generated (composed) characters are not affected.** `characters/compose.rs` classes style materials by name (`kind_of`) and packs `_GREY` and `1 + _RING` into UV1 as now. Their hair keeps the ring presets. They move to the profile only after an art comparison across hair colours and silhouettes, as a separate decision.
- **A `character` file without a `hair` profile** gets the slot classification and the forward turn, and today's character hair. That alone removes the asset view's cream rim on Cora's hair.
- **Within a profile hair material:**
  - no general rim, no hair rim, no ring;
  - vertex-colour RGB ignored;
  - UV1 overwritten.

  These are the only behaviours that differ from today's character hair, and they apply only where `slop.hair` is set.

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
| `M00_000_00_Eye_00_EYE`, `…EyeIris_00_EYE`, `…FaceEyeline_00_FACE`, `…FaceBrow_00_FACE`, `…FaceTint_00_FACE` | `{"slop": {"slot": "eyes"}}` |
| `M00_001_01_Cloth_01_CLOTH` | `{"slop": {"slot": "cloth"}}` |

The mesh data and sidecars:

- **Hair primitives:** `_HIGHLIGHT` (SCALAR FLOAT), 1 on one shape per upper lock group. Alternatively, `own-cora-live.hair.png` in the hair's UV0.
- **Face primitives:** TEXCOORD_1 = (0, 1) on every vertex, and `own-cora-live.face.png` beside the file.
- **Calibration targets:** `own-cora-live.calibration.json`.

## Export checklist (Blender)

1. Set the scene custom property `slop` (contract, character, forward) and a `slop` on every material.
2. Hair: a Float, Point-domain attribute `_HIGHLIGHT`, and/or a mask PNG in the hair's UV0 (R channel).
3. Face: a second UV map holding the constant forward, in Blender's V-flipped value. The face must be skinned to the head.
4. Export GLB with *Include → Custom Properties* and *Include → Attributes* on.
5. Put the `.face.png`, the optional `.hair.png` and the `.calibration.json` beside the GLB, and beside its `anim/` copy if one exists.
6. Run the calibration frame (phase 2) and read its contract audit before handing the file over.

## Sources in the code

- **Material kinds and the name rules:** `living/game/src/lookdev.rs` `convert`; `style.rs` `Kind`, `Style::kind`.
- **UV1 packing and attribute ids:** `characters/compose.rs` (`ATTRIBUTE_GREY`, `ATTRIBUTE_RING`, `ATTRIBUTE_OUTLINE_WIDTH` 0x5c3e_9a01–03); loader registration in `main.rs`.
- **Hair light, the ring and `facing()`:** `toon.wesl` `hair_light` and `facing`; the presets in `style.rs` `HAIR_SHINES`.
- **The face map:**
  - the shader: `toon.wesl` `face_lit`; `toon_vertex.wesl` (turning TEXCOORD_1);
  - the client: `lookdev::face_map_files`, `face_map_of`;
  - the format: `living/tools/face_normals.py` (its docstring and `thresholds`).
- **The bands, shadow colour and sky fill the profile replaces:** `toon_light.wesl` `bands`, `banded`.
- **Forward turns:** `characters.rs` `spawn` (`yaw + PI`), `view.rs` (`turn`), `lookdev.rs` `build_lineup`.
