# The reference character, taken apart

What the VRoid reference is made of, measured from its files beside our generated people, and what our generator (`living/tools/blender/person.py`, pass 2) should change to close the gap the owner sees. Research for branch `ref-1`, 2026-11-11. The general survey of character generation is being written separately (`docs/CHARACTER_RESEARCH.md`, branch `res-1`); this document covers only the reference itself. The generator is described in [CHARACTERS.md](CHARACTERS.md).

The owner, on pass 2: "This is definitely progress. But yeah, we are still lacking, I think, depth and probably in the shape, how it is structured internally. What are the points that you can tweak to get different shapes that still make sense, right?"

## In short

- **Ours reads as a smooth form with features placed on it because that is how it is built.** `head_form.py` is a superellipse loft with Gaussian bumps added for nose, brow, sockets, cheeks and lips. Gaussians blend everything into everything. The reference is a broad, nearly flat front, with eye sockets in it. It turns at a defined corner into the cheek and temple planes, has a straight jaw line running to a pointed chin, and sits on a large round cranium.
- **Measured:** 0.15 head heights behind the bridge of the nose, the reference's face is 0.70 H wide at the forehead and 0.69 H at the brow. Ours is 0.55 H and 0.59 H (woman) and 0.49 H and 0.50 H (man). Its eyes sit 39% of the way up the head and ours 47% (woman) and 51% (man). Its eyes are 0.39 H apart and ours 0.28 H and 0.25 H.
- **The depth is not in the reference's normals.** Its normals are the geometry's own smooth normals (median 0° from recomputed ones). Its MToon face ramp barely darkens (shade shift −0.9, toony 0, shade colour almost white). In our game both heads are shaded by the same `face_normals.py` shadow map anyway. The depth comes from three places:
  - the form: silhouette and the outline drawn on it;
  - how the eye is built: the iris is 4 mm behind the lid skin, a white bowl 15 mm deep lies behind it, and the lid-line and lash cards stand up to 10 mm in front of the lids;
  - a few painted cues.
- **VRoid's face is one template.** Shino and Vivi share the same 2,339 vertices, triangles and UVs. Only the positions differ, by a mean of 3.2 mm on a 23 cm head after scaling. The expressions are the same morphs, scaled to each face. VRoid's sliders are bounded offsets of one well-structured mesh. That is why any setting still makes sense, and it is the parameter model to copy.
- **Licence:** each file's own metadata says CC0. Shino's CC0 status is also asserted by third-party mirrors that cite an official pixiv page, which we could not open. Vivi's is unverified. pixiv's guidelines say content it provides, "including the base models", "is not CC0".
- **Recommendation:** rebuild the same structure ourselves. Use a low-poly cage of planes, with landmarks and crease lines, subdivided by script, and fit it to the reference's measurements. Do not ship VRoid's mesh. That is about two to three passes for the form and one for the parameters. A cheap shading pass follows on top: a shadow map drawn from the planes.

## 1. What is open

| Item | Where | Licence | Notes |
|---|---|---|---|
| VRM 0.x spec | [vrm-specification/specification/0.0](https://github.com/vrm-c/vrm-specification/tree/master/specification/0.0) | none stated (the repository has no licence file) | Our files are 0.x. `materialProperties` keeps MToon settings as Unity property names. |
| VRM 1.0 spec | [VRMC_vrm-1.0](https://github.com/vrm-c/vrm-specification/tree/master/specification/VRMC_vrm-1.0), [VRMC_springBone-1.0](https://github.com/vrm-c/vrm-specification/tree/master/specification/VRMC_springBone-1.0), [VRMC_materials_mtoon-1.0](https://github.com/vrm-c/vrm-specification/tree/master/specification/VRMC_materials_mtoon-1.0) | none stated | MToon 1.0: `shading = linearstep(-1 + toony, 1 - toony, N·L + shift)`; outline widths in metres or as a share of screen height |
| UniVRM (Unity) | [vrm-c/UniVRM](https://github.com/vrm-c/UniVRM) | MIT ("Copyright (c) 2020 VRM Consortium", "Copyright (c) 2018 Masataka SUMI for MToon") | MToon 0.x in `Packages/VRM/MToon`, 1.0 in `Packages/VRM10/MToon10`. Our files say `UniGLTF-1.24`. |
| three-vrm (three.js) | [pixiv/three-vrm](https://github.com/pixiv/three-vrm) | MIT ("Copyright (c) 2019-2026 pixiv Inc.") | `three-vrm-materials-mtoon` (the shader); `three-vrm-materials-v0compat` (the 0.x → 1.0 mapping, the clearest open statement of what the 0.x numbers mean) |
| MToon source | [Santarh/MToon](https://github.com/Santarh/MToon) (v3.9, `MToonCore.cginc`) | MIT ("Copyright (c) 2018 Masataka SUMI") | 0.x ramp: half-Lambert, then a linear clamp between `_ShadeShift` and `lerp(1, _ShadeShift, _ShadeToony)`; world outline offset `0.01 * _OutlineWidth * widthTex * normal` (so the value is in cm) |
| The two sample models | our copies: [madjin/vrm-samples](https://github.com/madjin/vrm-samples) `vroid/beta/` (no licence of its own); a CC0 re-upload on OpenGameArt ("VRoid Studio CC0 models", by user hecko, not pixiv) | see [§5](#5-the-licence-and-whether-to-start-from-it) | Exported by `VRoidStudio-0.8.1` |
| **VRoid Studio itself** | — | **closed** | Its source is not public. Its guidelines (vroid.com/en/studio/guidelines, citing Article 5 of the Terms of Use) prohibit "reverse engineering, decompiling, or disassembling the program". Reading a CC0 export's glTF data is not that; we did nothing to the program. |

pixiv's sites (vroid.com, vroid.pixiv.help, hub.vroid.com) and OpenGameArt refused automated reads (HTTP 403). What is quoted from them below comes from search-engine extracts, and is marked as such. The research notes with every URL are in the figures tarball (`notes/web-findings.md`).

## 2. What was taken apart

- **Files:** `vroid-Sendagaya_Shino.glb`, 15,074,328 bytes, SHA-256 `1e177c1a…a49b5`, the control the board calls `vroid=recipe:shino`. `vroid-Vivi.glb`, 18,089,136 bytes, `eaf902e0…3a9d`. Both are copied into `.local/ref/src/` (git-ignored).
- **Ours:** pass 2's `woman` and `man` presets (`man` with `beard.style=none`, so the chin is skin), built by `person.py` at this branch's base.
- **Tools:** `living/tools/characters/reference/` (numpy, Pillow, Blender 5.2), run by one command:

  ```bash
  living/tools/characters/reference/run.sh            # writes .local/ref: dumps, measurements, figures (about a minute)
  ```

  Every script that reads a VRoid file runs under `python3 -I`. Blender imports the GLBs to render; the numbers come from the glTF buffers directly.
- **Figures:** they are in `.local/ref-1.tar.gz` (unpacks to `ref-1/fig/`, `ref-1/dump/`, `ref-1/measure/`, `ref-1/notes/`, 39 MB) and stay out of git; the paths below are inside it. `run.sh` writes the same into `.local/ref/`.

| Figure | Shows |
|---|---|
| `fig/form-compare.jpg` | Shino, Vivi, our woman and man: quad wireframe front, three-quarter and side; plain Lambert from the geometry; the surface split into ten planes by normal |
| `fig/sections.png` | Horizontal sections and three profiles, Shino against our woman and man, scaled to head height |
| `fig/toon-compare.jpg` | One hard toon step from a key light and a side light, on geometry normals and on the file's normals |
| `fig/eye-sections.jpg` | A vertical section through the left eye: every layer of the reference's eye against ours |
| `fig/shino-blendshapes.jpg` | Where the eye bones' weights reach; 16 of the 41 morphs as heat maps (0 to 10 mm) |
| `fig/template.jpg` | Shino's and Vivi's identical wireframes, and where Vivi's face differs from Shino's after scaling |
| `fig/shino-face-textures.jpg`, `fig/shino-eye-textures*.jpg`, `fig/shino-hair-textures.jpg` | The face, eye, lash, brow and hair textures |
| `fig/<head>/…` | Every single render behind the sheets |

## 3. The reference's head

### 3.1 How it is divided

The face is one glTF mesh, `Face.baked`: ten primitives over one shared buffer of 2,339 vertices, so every part shares the morph targets. Positions are in metres. The model faces −Z (VRM 0.x).

| Primitive (material) | Triangles | Vertices | What it is | Material |
|---|---|---|---|---|
| `Face_00_SKIN` (two primitives) | 1,064 + 278 | 633 + 186 | The face mask (forehead to chin, cut flat behind at the ear line) and the ears | opaque |
| `FaceMouth_00_FACE` | 496 | 532 | The inside of the mouth, teeth, tongue | opaque |
| `EyeWhite_00_EYE` | 96 | 142 | A bowl behind each opening | opaque |
| `EyeIris_00_EYE` | 192 | 122 | A disc per eye, on the eye bone | cut-out |
| `EyeHighlight_00_EYE` | 192 | 122 | A second disc just in front of it | blended |
| `FaceEyeline_00_FACE` | 384 | 274 | The lid lines: cards above and below the opening | blended, two-sided |
| `FaceEyelash_00_FACE` | 224 | 168 | Lash cards flaring out | blended, two-sided |
| `FaceBrow_00_FACE` | 160 | 110 | One brow card per side, a few mm off the skin | blended, two-sided |
| `EyeExtra_01_EYE` | 64 | 50 | A `><` squint overlay, parked 3 cm inside the head until `EyeExtra_On` brings it forward | blended |

- The skin has no back of the skull. Behind the ears the head is the body mesh's `HairBack` (394 triangles, a blended scalp texture) under 46 hair locks.
- The whole face is 3,150 triangles, of which the skin is 1,342. Ours is 8,912 triangles of skin alone. The reference's form is not a matter of density.

### 3.2 The form

Every figure is scaled by the head's height H, from the chin to the crown (Shino 23.3 cm, our woman 25.0 cm, our man 28.7 cm). Our skin stops at the hairline, so our crown is taken from `head_form` exactly as `person.py` places it.

**Where the features sit:**

| | Shino | Vivi | Ours: woman | Ours: man |
|---|---|---|---|---|
| Eye centre, share of H above the chin | 0.39 | 0.37 | 0.47 | 0.51 |
| Eye opening width / H | 0.16 | 0.17 | 0.19 | 0.14 |
| Eye opening height / width | 0.73 | 0.91 | 0.77 | 0.63 |
| Eye centres apart / H | 0.39 | 0.40 | 0.28 | 0.25 |
| Inner corner from the midline | 2.7 cm | 2.5 cm | 1.2 cm | 1.5 cm |
| Nose tip, share of H above the chin | 0.25 | 0.27 | 0.31 | 0.35 |
| Mouth width / H | 0.09 | 0.12 | (slit not a hole) | |

The reference's eyes are set far apart and low. Ours are close together, and the gap between them is half the reference's. A narrow front cannot hold wide-set eyes, which is the next table.

**How broad the front is** (the face's full width within a given depth behind the bridge of the nose, / H):

| Height (share of H) | Shino, within 0.15 H / 0.30 H | Vivi | Ours: woman | Ours: man |
|---|---|---|---|---|
| 0.76 (forehead) | 0.61 / 0.72 | 0.60 / 0.71 | 0.45 / 0.61 | 0.45 / 0.53 |
| 0.64 (forehead) | 0.70 / 0.78 | 0.68 / 0.78 | 0.55 / 0.69 | 0.49 / 0.59 |
| 0.52 (brow) | 0.69 / 0.76 | 0.65 / 0.76 | 0.59 / 0.69 | 0.50 / 0.58 |
| 0.40 (eyes) | 0.64 / 0.72 | 0.63 / 0.72 | 0.57 / 0.67 | 0.50 / 0.56 |
| 0.28 (cheekbone) | 0.59 / 0.65 | 0.59 / 0.66 | 0.51 / 0.59 | 0.45 / 0.51 |
| 0.20 (nose base) | 0.52 / 0.57 | 0.56 / 0.61 | 0.44 / 0.52 | 0.41 / 0.46 |
| 0.12 (mouth, jaw) | 0.38 / 0.42 | 0.48 / 0.51 | 0.34 / 0.43 | 0.34 / 0.38 |
| 0.04 (chin) | 0.19 | 0.26 | 0.17 / 0.20 | 0.22 |

The same thing as depth: 0.3 H out from the midline, the reference's surface has fallen back 0.11 to 0.12 H at the brow and forehead and 0.17 H at the cheekbone. Ours has fallen back 0.14 to 0.17 H at the brow and forehead and 0.27 H at the cheekbone (woman). Its cheek starts going round straight away.

What the sections, profiles and plane maps show (`fig/form-compare.jpg`, `fig/sections.png`):

- **Front planes.** The reference's front, from the brow to below the cheekbones, is two broad, nearly flat planes meeting at a shallow angle down the midline. The plane map gives each half of the face one plane. Ours is a narrow rounded front: the plane map cuts it into vertical strips that run through the eyes.
- **The side turn.** Its front turns into the cheek and temple planes at a corner that runs from the temple past the outer eye to the jaw. In the profile 0.3 H off the midline, the reference's surface stays about 0.1 H ahead of ours from the forehead to the jaw.
- **The jaw.** A nearly straight line from under the ear to a pointed chin. Its outline from the front tapers from 0.59 H at the cheekbone to 0.19 H at the chin. There is a distinct plane under the jaw. Ours narrows more softly, and a wide jaw keeps the lower face full.
- **The cranium.** A large dome, ahead of ours at the forehead in the midline profile and taller above the brow. The eyes are low because the cranium is big, not because the face is short.
- **The sockets.** The eye opening sits in a hollow. The brow plane stands over it and the cheek plane runs under it (see the three-quarter Lambert). In the toon renders the shadow's edge breaks cleanly at the socket and the cheek corner. On ours the edge wanders, and the nose ridge draws a long stripe from the brow to the lip (`fig/toon-compare.jpg`).
- **The nose.** A small wedge on the front planes. It stands well forward at the tip and is barely there at the bridge. Ours is a ridge from between the eyes down.
- Both of our heads carry a soft ridge across the cheek from the ear toward the mouth (visible on the man without a beard, in `fig/form-compare.jpg`). Its cause was not traced here.

### 3.3 Topology

| | Shino's skin | Our woman's skin |
|---|---|---|
| Triangles | 1,342 | 8,912 |
| As quads (Blender's tris-to-quads, 60°) | 585 quads + 172 triangles | 4,396 quads + 120 triangles |
| Interior vertices: valence 4 / 3 / 5 / 6+ | 450 / 19 / 120 / 21 | 4,251 / 11 / 57 / 15 (four of 9 to 16, where the eyes are stitched) |
| Poles by region: mouth, eyes, nose and cheek, jaw, brow, cranium, sides and ears | 45, 24, 19, 15, 10, 2, 45 | 7, 27, 2, 3, 32, 0, 13 |
| Boundary loops | outer edge 38; mouth slit 32 (2.1 cm wide); each eye 24 | the hairline, the eyes, the mouth slit |

- **The reference's edge flow follows the features.** Each eye has concentric rings of 24 vertices. The mouth has rings round its 32-vertex slit, and lines fan from it toward the nose and chin. The forehead and cranium are a coarse grid, and the poles sit where the feature loops meet that grid: round the mouth, the nose wings and the jaw corner.
- **Density goes where form changes.** The eyes, nose and mouth are dense, and the forehead and cheeks are sparse.
- **Ours is a uniform cube-sphere grid** with the eyes cut out and zipped to a ring. Nothing in the mesh follows a feature or a plane. Our expressions rebuild the whole face per state, so the missing loops do not hurt deformation. But the mesh has no lines to carry a crease or a plane break.

### 3.4 One template for every face

Shino and Vivi have identical index buffers in all ten face primitives, and identical UVs: the maximum difference is 0.0. Only positions differ (`fig/template.jpg`, `dump/vivi_vs_shino.txt`):

- After matching scale (Vivi's head is 1.10 times smaller), position and turn (0.65°), the skin differs by **3.2 mm on average** (median 2.8, 90th percentile 5.6, at most 11.1 mm, on a 23 cm head).
- The differences sit in the cheeks and jaw (Vivi's lower face is wider), the nose, the mouth, the brows and the eye openings (Vivi's are taller). The cranium hardly changes.
- **The expressions are the same morphs.** For every one tested (`ALL_Joy`, `ALL_Surprised`, `EYE_Close`, `EYE_Joy`, `MTH_A`, `MTH_O`, `MTH_Down`, `BRW_Angry`), the same vertices move, the directions agree to a cosine of 0.975 to 1.000, and the sizes differ by 1% (mouth) to 22% (eyes, brows). They are authored once and rescaled to the face.

### 3.5 The eye

A vertical section through the left eye, forward to the right (`fig/eye-sections.jpg`):

- The skin's lid edges fold inward into the opening.
- **The iris is a nearly flat disc whose front is 4 mm behind the skin at the lids** (skin 80 mm forward of the head's axis at the opening, iris front 76 mm), with the highlight disc just in front of it.
- **The white is a bowl 15 mm deep** (75 to 60 mm). The iris therefore stands proud of a white that falls away behind it.
- **The lid line and lash cards stand forward of the lids**, up to 10 mm (to 90 mm). The upper lid line rises about 1.3 cm from the lid and leans forward, like a visor. The lash card flares forward and up from it, and the lower lid line angles down and out.
- The brow card floats a few mm in front of the skin.
- The white's texture paints the lid's shadow across its top.
- **Two bones per eye.** `J_Adj_L_FaceEyeSet` sits at the front of the eye and carries 176 skin vertices with partial weights round the whole eye region (`fig/shino-blendshapes.jpg`, first panel). `J_Adj_L_FaceEye`, 5.5 cm behind it and 2.0 cm from the midline, turns the 122 iris and highlight vertices. The VRM look-at block gives 8° to 12° of horizontal turn and 10° vertical.

**Ours:** the white and iris lie on a ball of 8 cm radius, 7 to 10 mm behind the skin at the opening (skin 90 to 91 mm, eye 80 to 83 mm), at the end of a rim turned inward. The white is a shell only 3.5 mm deep in this section. The iris sits at the back of a short tunnel, and the white does not fall away behind it. The lid line is a small drawn shape flat on the skin.

### 3.6 UVs

The face skin's UVs are a front projection of the mask onto one 1,024² texture, with the ears in the corners. The cards and eye parts each have their own strip texture: lid lines, lashes and brows 1,024×256; white, iris and highlight 1,024×512; mouth 512². Everything in the face is on these ten textures plus an 8×8 flat normal map and a black map. Ours puts the whole head, the eyes and the ears on one 1,024² atlas.

### 3.7 Blend shapes

41 morph targets on all ten primitives, all with normal deltas. The VRM block binds 15 expression groups to them (`A I U E O`, `Blink`, `Blink_L`, `Blink_R`, `Angry`, `Fun`, `Joy`, `Sorrow`, `Surprised`, `Extra`, `Neutral`).

| Morphs | Vertices moved (of 2,339) | Largest move | What moves |
|---|---|---|---|
| `ALL_Angry`, `ALL_Fun`, `ALL_Joy`, `ALL_Sorrow`, `ALL_Surprised` | 833 to 1,532 | 16 to 26 mm | The sum of that emotion's `BRW_`, `EYE_` and `MTH_` morphs, to within 1.4 mm (`ALL_Fun` 4.7 mm) |
| `BRW_Angry`, `BRW_Fun`, `BRW_Joy`, `BRW_Sorrow`, `BRW_Surprised` | 110 (the brow cards; `Angry` also 18 lash vertices) | 7 to 20 mm | Brow cards only: down 11 to 14 mm for angry and sorrow, up 4 to 8 mm for joy, fun and surprise. No skin moves. |
| `EYE_Close`, `EYE_Close_L`, `EYE_Close_R` | 713 (358 one side) | 36 mm | Lids, lid lines, lashes, the white's rim, 207 skin vertices. Both sides equal L + R exactly. |
| `EYE_Joy` (and `_L`, `_R`) | 728 | 17 mm | The lower lid up and the upper lid down to a smiling arc |
| `EYE_Angry`, `EYE_Sorrow`, `EYE_Surprised` | 384 to 700 | 5 to 7 mm | Lid shapes; `Surprised` also shrinks the iris and highlight (122 vertices each) |
| `EYE_Extra` | 1,094 | 30 mm | The eyes shut flat for the `><` overlay |
| `EYE_Natural` | 0 | | Empty |
| `MTH_A`, `MTH_I`, `MTH_U`, `MTH_E`, `MTH_O` | 648 to 682 | 10 to 23 mm | The mouth's inside (532) and 116 to 150 skin vertices round it. `O` moves most. `U` pulls back and in. |
| `MTH_Up`, `MTH_Down`, `MTH_Angry`, `MTH_Neutral`, `MTH_Fun`, `MTH_Joy`, `MTH_Sorrow`, `MTH_Surprised` | 305 to 727 | 3 to 26 mm | Mouth shapes for the emotions. `Joy` and `Surprised` open widest; `Angry` and `Neutral` also touch 12 white vertices. |
| `HA_Fung1`, `HA_Fung1_Low`, `HA_Fung1_Up`, `HA_Fung2`, `HA_Fung2_Low`, `HA_Fung2_Up` | 52 to 130 (mouth only) | 5 to 6 mm | Fangs |
| `EyeExtra_On` | 50 | 46 mm | Brings the `><` overlay out of the head |

Ours has 15 morphs: a sound subset under the same names. The reference shows two things worth copying: separate brow, eye and mouth morphs from which each whole emotion is summed, and brows that move as cards rather than as skin.

### 3.8 Rig round the face, neck and shoulders

- **Head:** `J_Bip_C_Head` (at 1.417 m, 3 cm above the chin, near the jaw's hinge) carries the face mask, the two eye-set bones and 15 hair chains. The chains have 3 to 7 joints: seven of 3, two of 4, three of 5, two of 6 and one of 7.
- **Face weights:** each vertex has 1 to 3 influences. 1,235 vertices have one, 1,064 two and 40 three. The face uses only the head and the four eye bones. The jaw has no bone: the mouth opens by morphs.
- **The neck** (body mesh, |x| < 17 cm): fully on `J_Bip_C_Neck` at 1.36 m; half neck and half head at 1.39 m, which is the chin's height; all head from 1.40 m. The head's weight reaches 6 cm down the neck.
- **The shoulders:** up to 4 influences per vertex. From 1.22 to 1.34 m, `UpperChest` (0.5 falling to 0.1), `Shoulder` (up to 0.23) and `UpperArm` (up to 0.24) blend. No vertex there is weighted to a single bone.

Ours uses the same `J_Bip_*` skeleton and eye bones. Its eye bones carry only the iris layer: no skin round the eye follows them.

### 3.9 Hair, brows and lashes

- **Hair** is 46 locks of the `HAIR_01` material (108 to 700 triangles each, 16,216 in all), plus 2 small pieces of `HAIR_02` (the hair clip) and the `HairBack` scalp in the body mesh. Each lock has a front and a back surface a few vertices across, mapped root to tip on one 512×1024 strand texture. [CHARACTERS.md](CHARACTERS.md#what-was-learnt-from-vroid) has the detail from pass 2; this pass confirmed it.
  - The highlight is **emission**: the `Hair_00_spe` texture is the emission map, times an emission colour of (0.26, 0.28, 0.41).
  - A rim matcap (`Matcap_RimHair`) is added through `_SphereAdd`.
  - Hair has no outline (`_OutlineWidth` 0).
  - Springs: 15 groups, stiffness 0.4, drag 0.4, hit radius 2.4 cm, against 10 collider groups (head sphere 10 cm, neck, chest, arms, legs).
- **Brows** are one blended card per side, 55 vertices, textured from a 1,024×256 strip and tinted by the material's colour (Shino's are blue-black, (0.18, 0.21, 0.45)). They move only by `BRW_` morphs.
- **Lashes and lid lines** are cards with drawn alpha strips: the lid lines thick at the top with a wing, the lashes as flared spikes. They are two-sided, alpha-blended and tinted warm red-brown, (0.44, 0.16, 0.16).

### 3.10 Materials and how the face is shaded

Every material is `VRM/MToon` (0.x) with `KHR_materials_unlit` as the fallback.

| Material | Ramp: `_ShadeShift` / `_ShadeToony` | `_ShadeColor` | Outline | Other |
|---|---|---|---|---|
| Face skin | −0.9 / 0 | (1.00, 0.94, 0.94): almost white | world 0.075 cm (0.75 mm), fixed colour (0.28, 0.09, 0.13), **times a width mask** | Normal map `Face_00_nml`; rim matcap |
| Body skin | −0.6 / 0 | (1.00, 0.84, 0.84) | world 0.075 cm, mixed colour | Its own normal map |
| Cloth | −0.6 / 0 | (1.00, 0.84, 0.84) | world 0.075 cm, fixed | Cut-out, two-sided |
| Mouth, eye white, iris, highlight, lid lines, lashes, brows, eye overlay | −0.6 / 0 | white or the part's tint | none (no outline keyword) | Render queue: white 2000, iris 2450, lines and highlight 3000, lashes 4500 |
| Hair locks | −0.3 / 0 | (0.25, 0.21, 0.44): a cool purple | none | Cut-out; emission highlight; rim matcap |

What makes the face's shading:

- **No edited normals.** The skin's normals in the file differ from the geometry's own smooth normals by a median of 0° (mean 2.5°, 90th percentile 5.6°, at most 89° on the mask's cut edge). VRoid 0.8.1 did not sculpt or transfer normals. The help pages say the "anime-style face shading" ("shades are weaker at the front and follow the face outline") arrived with the stable 1.0 release ([extract] vroid.pixiv.help article 4405597671193), so these beta files predate it.
- **The ramp hardly darkens the face.** With shift −0.9 and toony 0, MToon 0.x's ramp runs linearly over almost the whole of N·L (from −0.9 to +1), towards a shade colour of 94% white. Under MToon the face is nearly flat colour.
- **The normal map** is flat except at the lid crease, the nose and the lip: 90% of its texels lean under 7°, 99% under 19°.
- **The outline width mask** (`Face_00_out`, 256²) is black over the eyes and the mouth and grey along the nose, so no outline is drawn round the features. Only the silhouette gets one.
- **The paint** is almost flat:
  - texel luminance stays between 207 and 230 across the face, apart from the sockets;
  - warmer at the cheeks (236, 184, 159) and under the chin (236, 178, 154) than at the forehead (244, 208, 187);
  - a soft pink ring inside each socket, a short nose mark and a 2 cm mouth line (`fig/shino-face-textures.jpg`).

**In our game none of the MToon settings apply.** `toon.wesl` is the game's own shader, outlines come from `bevy_mod_outline` at 1.8 px on the silhouette, and both the reference and our people go through `face_normals.py`: the face's normals become 90% those of an ellipsoid fitted to the face's bounds, and a shadow map from that ellipsoid decides where the face's shadow edge falls. In the game, then, the reference's "planes that catch the light" come from:

1. **its silhouette**, which the outline traces: the cheek corner, the jaw line and the chin point;
2. **its eye:** the forward lid visor, the iris level with it and the white falling away;
3. **the 10% of its geometry that the normals keep**, and its paint.

## 4. VRoid Studio's parameter model

**Documented** (from search-engine extracts of vroid.pixiv.help, which refused direct reads; to confirm in a browser):

- "How to edit faces" lists **17 categories**; 11 named in the extract: Face Sets, Eyes Sets, Irises, Eye Highlights, Scleras, Eyebrows, Eyelid, Eyeliner, Eyelashes, Nose, Mouth. Each item has Color and Parameters ("its position and size") and Edit Texture. A v1.26 release note's preset kinds suggest Mouth Inside, Lips, Cheeks and Face Paint among the other six (inferred).
- Slider limits can be exceeded by typing numbers ("you can edit parameters beyond the limit set by sliders").
- Version 1.0 unified the male and female face models into one ("今までは男女で分かれていた顔モデルを共通化", CGWorld) and went from 7 face categories to 16. One article counts 35 face parameters. It also widened the range for "the eye area, nose bridge, face outline and neck thickness" (MoguraVR).
- No verbatim list of the face-shape sliders (jaw, chin, cheek, contour) could be read. Lists with such names that turn up in searches belong to other products.

**Inferred from the files** (0.8.1 beta; the stable version has more parameters):

- **One base mesh, offset by sliders.** Two different characters share every index and UV (§3.4), so a VRoid face is a fixed template whose vertex positions the sliders move. The two faces differ by 3.2 mm on average: the sliders' range is small next to what the template already fixes. The planes, the sockets, the jaw line and the loops are the template's, and every character inherits them.
- **Regions are moved by bones as well as by shape.** The eye-set bones carry the skin round each eye with soft partial weights (§3.5). Moving, turning or scaling that bone moves the whole eye area and fades out into the head. That is a likely way for an eye's position, size and tilt sliders to stay valid (inferred; the exported files show only the result).
- **Expressions are authored once and carried by the template**, rescaled to each face's feature sizes (§3.4). A new face never breaks a blink or a vowel.
- **Why combinations stay valid:** every slider is a bounded, smooth displacement of a template that is already a good head, and each feature is moved by its own region (bone or offset field). So no setting can push an eye out of its socket, or a nose off the front plane, by much.

## 5. The licence, and whether to start from it

**Each file's own VRM `meta`** (read 2026-11-11):

| Field | Shino | Vivi |
|---|---|---|
| `title` | "Sendagaya Shino" | "Vivi" |
| `author`, `contactInformation`, `reference`, `version` | "" (all empty) | "" (all empty) |
| `licenseName` | "CC0" | "CC0" |
| `allowedUserName` | "Everyone" | "Everyone" |
| `commercialUssageName` | "Allow" | "Allow" |
| `violentUssageName`, `sexualUssageName` | "Allow", "Allow" | "Allow", "Allow" |
| `otherPermissionUrl`, `otherLicenseUrl` | "" | "" |
| `exporterVersion` | "VRoidStudio-0.8.1" | "VRoidStudio-0.8.1" |

In VRM 0.x, modification and redistribution are not fields of their own. They follow from `licenseName`, and CC0 places no conditions on either.

**The publisher's terms** (pixiv's pages refused direct reads; quoted from search extracts and from mirrors that reproduce them):

- **Shino:** pixiv's help article "Do VRoid Studio's sample models come with conditions of use?" has a section "CC0 license models": "The CC license* for these models is CC0. This model can be edited and used freely. Copyright is waived, and there is no particular limit when using them." The madjin mirror's README reproduces it without naming the models. Two third-party redistributors list Shino among them: a Booth listing ("全モデルはCC0です。", all models are CC0) citing pixiv's per-model page `vroid.pixiv.help/hc/ja/articles/360013482714`, and the OpenGameArt upload. We could not open the official page.
- **Vivi:** no official page, OpenGameArt entry or Booth entry names it. It is only in the mirror's `vroid/beta` folder, beside hair samples and preset defaults. Treat it as **not established CC0**: an exporter writes whatever `meta` it likes.
- **pixiv's VRoid Studio guidelines** ([extract], vroid.com/en/studio/guidelines, edited 2023-12-21): "all content provided by pixiv, including the base models when creating a new avatar, is not CC0", and "even when using a sample model or included textures, please refer to the sample model's conditions of use". Shino's face *is* VRoid's base template (§3.4). So its mesh's CC0 status rests entirely on the sample's own release, not on VRoid's base models in general.
- CC0 waives copyright only: "No trademark or patent rights held by Affirmer are waived" (CC0 legal code, 4(a)). The names VRoid, pixiv and Sendagaya Shino should not appear in the game.

**Verdict:**

- Shino is very probably CC0: the file says so, and two independent redistributors cite pixiv's own page for it. But the one page that would settle it is pixiv's, and we could not read it.
- Vivi is unverified.
- Under this task's rule ("if in doubt, keep them in `.local/`"), **no VRoid file, mesh, UV or texture is committed**, and none is used as a source for ours. Both files stay under `.local/ref/src/` and `living/game/assets/lookdev/` (git-ignored), as before.

**Whether to start from it.** Three ways were weighed:

| | Shino's face as a base mesh we deform | Its topology only (its connectivity, our positions) | Rebuild the structure ourselves |
|---|---|---|---|
| Licence | Needs the official page confirmed; copies pixiv's base template | The same: connectivity is the template's data | None |
| What it gives | The exact planes, sockets, jaw and loops, and 41 morphs that transfer to any face | The loops and pole layout; the form still ours | What we build; measured against the reference |
| What it lacks | A mask: no back of the skull (bald, cropped and elderly heads need one), no neck join of ours, one young woman's face to stretch to men, elders and small children; its lid and lash cards are blended cards, where we chose strands | The same gaps; still has to be fitted to a form | The work of building it |
| Fit with "tools we own" | An outside mesh on the path of routine work, fetched from a mirror without a licence | Partly | Fully: our script, our parameters |

**The recommendation:** rebuild the same structure ourselves ([§6.1](#61-the-heads-underlying-form-a-skull-sockets-a-jaw-planes)), and use the two VRoid files in `.local/` only as a **measured target**. Fit the new form until its sections land on Shino's, and keep VRoid's loop pattern (rings of about 24 round each eye and about 32 round the mouth) as a technique, which is not content.

- The gap the owner sees is form, not mesh detail. A cage of a few hundred vertices that we write gets the planes, and it carries our parameters, sexes, ages and full skull from the start.
- If the owner confirms the official CC0 page in a browser, the base-mesh route becomes open. It would be the fastest way to a young woman's face, but it still needs every other part of the rebuild for the rest of the town. So it is not the cheaper road overall.

The decision is recorded in [THIRD_PARTY.md](../living/tools/blender/THIRD_PARTY.md).

## 6. What our generator should change

Ordered by how much each closes the gap the owner sees.

### 6.1 The head's underlying form: a skull, sockets, a jaw, planes

**Now:** `head_form.Head` is a loft of superellipses (half width, profile front and back, boxiness by height), plus additive Gaussian bumps for the nose, brow ridge, eye hollows, cheeks, jowls and lips. `head_mesh.Face` projects a cube-sphere onto it. Every feature is a soft bump, so nothing has an edge and nothing is a plane.

**Change:** build the head in the order a head is built, as a low-poly quad cage written in the script, with named landmarks, subdivided by script.

1. **The cranium:** a dome set by width, depth and height. The reference's is wide (0.70 H of front within 0.15 H of depth at the forehead, against our 0.55) and full at the forehead.
2. **The face block on it:** brow line, nose base and chin as the three thirds, and the cheekbone width.
3. **The planes:**
   - two front planes meeting at a shallow angle down the midline;
   - the corner line where the front turns into the cheek and temple planes, with a crease weight for how sharp it is;
   - the jaw line from the angle of the jaw (height and width) to the chin point (width and how far it juts);
   - the plane under the jaw.
4. **The sockets:** a recess in the front planes for each eye, under the brow plane and over the cheek plane. The eye opening is cut inside it with rings of about 24.
5. **The features on the planes:**
   - the nose as a wedge (bridge, length, tip, width);
   - the mouth with rings of about 32 round its slit;
   - the ears.

How:

- A cage of about 250 to 400 vertices.
- One or two levels of Catmull–Clark subdivision in numpy. Crease weights go on the plane breaks: the brow line, the cheek corner, the jaw line, the edge of the under-jaw plane.
- The result is a face of about 2,500 to 4,000 triangles in place of 8,900. That also serves the crowd ([CHARACTERS.md](CHARACTERS.md#crowd-cost)).
- `head_form`'s lookups that `face_paint.py` and the beard use (`eye_inside`, `lid`, `mouth_line`, `beard_cover`, `project_front`, `point`) keep their signatures, answered from the landmarks. Painting and beards then follow unchanged.
- The back of the skull and the hairline cap come from the same cage, so bald and cropped heads work, which a VRoid-style mask could not do.

The eye, as part of the socket:

- Set the iris's front about 4 mm behind the lid skin; ours is 7 to 10 mm.
- Let the white fall away behind it, as a bowl about 15 mm deep in place of the 8 cm ball's shallow shell.
- Stand the upper lid line and the lashes forward of the lids, up to about 10 mm, as a visor, not a mark on the skin.
- Let the eye-set bones carry the skin round each eye with soft weights, as the reference does. Moving an eye then moves its region.

**Acceptance:** `run.sh`'s sections and front-width table.

- With `stylise` 1, the woman's front widths at each height are within 0.03 H of Shino's.
- Her eye centre is within 0.02 H of 0.39, and her eye spacing within 0.02 H of 0.39.
- She is judged in the game renderer beside the control (`faces.py`, `capture.sh`).
- Men, elders and children keep their own shapes by the parameters below.

**Cost:**

- `head_form.py` rewritten: about 300 lines now, about 600 after.
- The mesh builder in `head_mesh.py` replaced: the cube-sphere, cut and zip, about 400 of its 776 lines. The expression rebuild, eyes and ears adapted.
- `face_paint.py` checked against the new lookups.
- Two to three passes, and the stylise table in [CHARACTERS.md](CHARACTERS.md#style-the-numbers-set-toward-the-reference) re-measured.
- No new dependency; Blender is not needed for the form.

### 6.2 A parameter model that follows how a head is built

**Now:** 34 face values, each about −1 to 1, move features and bumps round an average. They are independent, so extremes combine into heads that do not make sense, and none of them sets the structure (no cranium size, no front breadth, no cheek corner, no socket depth, no jaw angle).

**Change:** parameters by layer. Each layer is set in the units of the one it sits on, so children follow their parents and stay inside them. That is the reference's own rule (bounded offsets of a sound template, regions carried by bones), made explicit.

| Layer | Parameters (each −1 to 1 round the person's average) | Sits in |
|---|---|---|
| Skull | cranium width, depth, height; forehead slope and fullness; back of the head | head height |
| Face block | face height share (where the brow line, nose base and chin fall: the thirds); width at the cheekbones; width at the angle of the jaw; height of that angle | the skull |
| Planes | how broad the front is; how sharp the cheek corner is; cheekbone height and how far forward it stands; temple hollow; jaw line straight or curved; chin width, length, how far it juts, pointed or square | the face block |
| Sockets | socket size, depth; brow ridge projection | the planes |
| Eyes | size within the socket, spacing (a share of the face's width), height in the socket, tilt, opening, lid fold | the socket |
| Nose, mouth, ears | as now, set from the landmarks: the nose from the brow line to the nose base, the mouth between the nose base and the chin | the face block |

- **Keeps faces valid:**
  - every landmark is placed in its parent's frame and clamped to it;
  - the thirds, the eye spacing and the eye's size share the face's width, so no eye can leave its socket and no mouth can pass the chin;
  - `sex`, `age`, `family` and `stylise` move the averages, as now.
- **The existing 34 mostly carry over**, with the same names where they mean the same: `jaw_width` becomes the width at the jaw's angle, `brow_ridge` the projection, `eye_spacing` a share of the width. Some become derived values. The new ones are the plane and skull rows.
- **Expressions stay valid** by construction: they are built from the landmarks, per state.
- **Proof:** a sheet of the extremes in pairs (each value at ±1 against each other value) through the game renderer, plus an automatic check on each head: no self-intersection, eye inside its socket, the thirds in order, no mesh fold.

**Cost:**

- `person_params.py`'s `FACE` table and `resolve`.
- `head_form.py`, after 6.1.
- The parameter tables in [CHARACTERS.md](CHARACTERS.md#a-persons-parameters).
- One pass after 6.1.
- `family` and seeds keep working: each value still has its own random stream. Existing seeds will give different faces.

### 6.3 Face shading

**Now:** our heads and the reference go through the same `face_normals.py`: normals 90% of a bounds ellipsoid, and a shadow map from that ellipsoid. With our narrow, rounded form, the ellipsoid's sweep and the 10% of geometry left draw the same soft shapes for any face.

**Change, after 6.1:**

- **A shadow map from the planes.** `face_normals.py` (or `person.py` writing its map itself) gives each texel its threshold from the cage's plane, not from a bounds ellipsoid:
  - the front planes stay lit longest;
  - the cheek and temple planes go dark as the light passes the corner;
  - the sockets and the plane under the jaw darken early;
  - the nose wedge throws a small, fixed shape, not a stripe.

  This is how the hard toon step in `fig/toon-compare.jpg` breaks on the reference's geometry, kept clean.
- **Normals from the cage:** blend toward the subdivided cage's plane normals, not toward the ellipsoid, so the remaining share follows the planes.
- **Paint** toward the reference:
  - warmth on the cheeks and under the chin;
  - a soft ring in each socket;
  - the lid's shadow painted across the top of the white;
  - nose and mouth as small marks (already on the pass-3 list in [CHARACTERS.md](CHARACTERS.md#what-later-passes-need)).
- No outline is drawn on the features. The game's outline is already silhouette-only, so that holds.

**Cost:** small: about 100 lines in `face_normals.py` or a map written by the generator, and a few changes in `face_paint.py`. It must be judged in the game renderer at the game's camera and close up, against the control.

### Not recommended

- **Raising mesh density or adding subdivision to the present form.** The reference's face has 1,342 skin triangles to our 8,912. More of the same grid gives the same smooth form.
- **Copying MToon's numbers.** The game does not use MToon, and the reference's own ramp is almost flat.
- **A second style number.** The [style table](CHARACTERS.md#style-the-numbers-set-toward-the-reference) already shows that `stylise` 1 cannot reach the reference's eye height or head width. Those need the form in 6.1.

## 7. Paths

- This document: `docs/CHARACTER_REFERENCE.md`
- The tools: `living/tools/characters/reference/` (`run.sh` runs them all)
- The licence record: `living/tools/blender/THIRD_PARTY.md`
- Measurements, dumps and figures: `.local/ref/` (git-ignored); the tarball of figures, dumps and web notes: `.local/ref-1.tar.gz`
