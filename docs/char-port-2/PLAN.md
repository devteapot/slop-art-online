# char-port-2: Cora's hair and face, back-ported into the generator (plan)

**Status: a plan, for the coordinator and then the GC. Nothing in it is built.** It follows char-port-1, the clothing back-port ([proof](../char-port-1/proof.md)), and turns what was done by hand on one character, Cora Stannard, into generator parameters or masters that make every resident. Cora's hand work sits in two sessions:

- **[char-live-2](../char-live-2/session-report.md)** (face profile, hair, face shading, cloth);
- **[char-live-3](../char-live-3/session-report.md)** (back hair and plait, eye frame, the ink batch).

**Sources read for this plan:**
- the two session reports, their journals and fit blocks;
- [CHARACTERS.md](../CHARACTERS.md), [HANDMADE_HAIR.md](../HANDMADE_HAIR.md) and [HANDMADE_INK.md](../HANDMADE_INK.md);
- the char-port-1 notes;
- in `living/tools/blender/`: `person.py`, `person_params.py`, `cage_head.py`, `head_mesh.py`, `hair.py` and `face_paint.py`;
- in `living/tools/characters/`: `types.json`, `look_lines.py`, `town.py`, `ink_field.py` and `calibrate.py`.

Line numbers below refer to `origin/main` at `735f01779`. Where I'm unsure, the text says so.

## 0. How a generated person reaches the screen, and why it shapes this plan

The back-port can't copy Cora's route. Cora is one **hand-made whole file** (`own-cora-live.glb`, `slop.character: "handmade"`), read by `living/game/src/handmade.rs`. A resident is **composed** by the client (`characters/compose.rs`, [CHARACTERS.md § The client since compose-1](../CHARACTERS.md#the-client-since-compose-1-2026-11-12)) from three parts:

- **the type file**, `lookdev/types/<type>.glb`, one of 21 types (child-u, youth, adult and elder × f/m × lines a/b/c). It holds the body and the cage head with its 15 `Fcl_*` keys.
- **shared style files**: hair cuts `lookdev/styles/hair/<style>[.N].glb`, outfit pieces, and overlays (lines, freckles, beards). Each is loaded once and shared by everyone who wears it.
- **the person's line** in the look book: identity values on 25 `J_Id_*` bones, proportions, height, colour tags (`_HAIR`, `_SKIN`, iris, outfit pieces), style names, `belly` and `grey`.

Three consequences shape the plan:

1. **Face geometry is per type, and varies per person through identity bones.** Anything Cora's fit did to the cage becomes either a **type record value** (`types.json`) or a range that the person's seed draws, moving existing bones. Anything that bones can't express (a new row, a new stroke) must exist in the **type file** and be posed by the bones.
2. **Paint is per type layout, and per person only through tags and overlays.** The atlas, tint and face-shadow map belong to the type file. A per-person difference (blush strength, freckles) is an overlay or a tag, not a repaint.
3. **The client's composed path reads no `slop`.** HANDMADE_HAIR.md § Compatibility: "`compose.rs` classes style materials by name … Their hair keeps the ring presets". So the hair profile (palette bands, highlight mask, lock ink) and the ink profile (carriers) **do nothing on a generated person today.**
   - The generator can write them as outputs (§3, §4), but a **client step** must teach the composed path to read `slop.hair` and `slop.ink` from type and style files and to resolve their sidecars beside the shared file.
   - It also needs a palette that follows the person's hair tag. That is new, because the profile palette *replaces* colour (§4.3).
   - This is game-client systems work: on Opus by the routing rule, and the long pole of the plan.

**Hero residents** keep the existing whole-file route: a recipe whose `base` is a hand-made file and that has no `person` line isn't composed (CHARACTERS.md, compose-1, "The switch"). Cora stays that way. A hero may also keep a person line with **overrides** (§2.9). There is no hero mechanism in the generator today; this plan proposes a small one.

## 1. Inventory of Cora's hand work

"Where" gives the file that holds the work today, on `char-live-3` until it is merged. "Measured" gives the values as fitted on Cora (H is the crown-to-chin head height, eye is the canthus-to-canthus width).

### 1.1 Face geometry

| Piece | What it is today | Where | Parameters as measured |
|---|---|---|---|
| Jaw and chin taper | **Already a generator row.** Two extra cage rows: `chin_taper` before `chin`, `jaw_taper` before `chin_top`. Width weights are `1-smooth((z-.095)/.05)` (chin) and `(z-.15)/.12` (jaw). | `cage_head.py:290-297, 342-351`. Optional keys in a type's `jaw` record, default 0. **No type sets them, and `person_params` has no knob.** | Cora: `jaw_taper` 0.24, `chin_taper` −0.27. Carry weights `jaw_taper` .395, `chin_taper` .675. Front widths: cheek/H 0.734 (drawing 0.716), jaw/H 0.561 (0.553), chin/cheek 0.402 (0.392), chin-to-ear rise 31.2°. |
| Row carry weights | How much of the jaw arc's displacement each row follows. | Only in Cora's replay (`docs/char-live-1/restart/replay.py:1301-1303`, `fit_cora_rows`). | `jaw 1, chin .85, chin_top .50, lip_low .29, mouth .19, lip_up .14, base .095, tip .07, cheek .04, under_jaw .36` |
| Depth stations (brow, nose, upper lip) | The midline profile moved to the drawing's projections. | char-live-2 stage-2 xhigh block (`session.jsonl`, `stage2-xhigh-mandible-temple-and-taper`). In the generator the matching inputs are the type's `sections.p00`, `nose.out`/`tip_y`/`bridge_z`, `brow.ridge`, `mouth.lips`, and the identity bones `J_Id_NoseTip` (`nose_tip` −10…12 ‰H), `J_Id_Glabella` (`brow_ridge` −4…12 ‰H), `J_Id_Mouth` (`lip_fullness` ×0.7–1.35). | Projection over H: brow 0.0203 (drawing 0.020), nose 0.1096 (0.108), upper lip 0.0599 (0.059). |
| Chin pad | The two lowest transverse stations relaxed into one oval pad; the low-chin corner rounded. | `resumed-stage2-high-2` block. | Smoothing on the two lowest stations, around a fixed profile anchor. |
| Neck curve | Cervical rings follow the new jaw seam in angular order and curve forward through the upper throat. | `resumed-profile` fit (char-live-2). The generator's inputs are the type's `jaw.roll` and `jaw.inset` (`cage_head.py:368-371`). | The ring centre moves +3.4 mm, then returns to −1.5 mm before the collar. |
| Under-jaw seam | The face's UVs, pigment and normals carried over the rolled underside to the neck seam (the triangular patch below the ear). | `docs/char-live-2/face-shading/under_jaw.py`. | Luma step across the upper join: median 22.5 → 2.6 levels over 38 columns. |

### 1.2 Eyes

| Piece | What it is today | Where | Parameters as measured |
|---|---|---|---|
| Iris ratio | The iris disc widened along its own tangent, keeping the pupil-column opening. | `docs/char-live-3/eye-frame/fit.py`. Generator: `cage_head._eye` (`:1138`), `head_mesh.IRIS_WIDE` .88, `IRIS_FILL` .47. | `iris_width_scale` 1.27. Iris/eye width in front: 0.465 / 0.490 (drawing 0.507 / 0.493). |
| Opening and outer canthus | The outer canthus lifted; the wing raised and extended. | eye-frame `fit.py`, `eye-fit.json`. | `outer_lift_m` .0013, `wing_lift_m` .0048, `wing_extension_m` .004. Central opening / face height 0.082 (drawing 0.070). |
| Old lid band, lash cards, lower line and brow strip | Generator geometry in materials `line` and `brow` (`head_mesh.Face._lines` `:576`, `_brow` `:669`). | **Removed on Cora and replaced by ink** (184 faces). | Generator: `LASH_OUT` .0045, lash band offset 1.2 mm, ink edge 1.6 mm, `BROW_OFF` .0016. |

### 1.3 Face paint and shading

| Piece | What it is today | Where | Parameters as measured |
|---|---|---|---|
| Skin red lift | The atlas skin rows scaled. | `face-shading/paint_features.py` `paint()`. | ×(1.114, .963, .935) below row 192 of 1024. |
| Cheek blush | A tint-layer oval. | Same file. Generator: `face_paint.BLUSH_PIGMENT` (0.70, 0.26, 0.22) and `look.blush`. | Centre \|u−.5\| .139, v .692; radii .089 × .050; pigment (.83, .53, .40); weight .51. Measured cheek − base drop (−2, −16, −16) against the drawing's (−6, −19, −20). |
| Freckles | The generator's small isolated pigment marks lifted into the tint. | `separate_freckles()`. | Components ≤ 11 texels, coverage ≤ 0.60. |
| Mouth crease, lower lip and lip shadow | The crease's dark centre restored; a diffuse lower lip; a cast shade under the lip. | `paint()` `second`/`final`. | Crease v .7944 + .0016·s², σ .00165. Lip oval .29 weight. Lip-shadow pad .60 toward (.60, .32, .23). |
| Face-shadow thresholds | The generator's signed light directions softened over temples and jaw. | `paint_features.shadow()`, after `face_normals.py --flat 0 --hair 0`. | Gaussian blur 8 px at 1024; R,G = .48 + .51·field; B = 0. |
| Nose: shade and glint | One flank shade, tightened against the underside; the highlight cut to a tip glint. | `docs/char-live-3/ink-batch/paint.py`, `maps/nose-paint.json`. Generator: `face_paint.py:210-222` (`nostril`, `nose_line`). | Flank u .484 ± .043, curve v .738, bend .012, tilt .004. Half-heights .0045 above and .0035 below. Pigment (.38, .41, .42). Glint at (.502, .711), radii .0045 × .0025, colour (255, 236, 211). |
| Nostrils | Two soft filled crescents painted on the face's own texels. | `docs/char-live-3/ink-batch-2/nostrils.py`, with `nose_texels()` in its `fit.py`. | Drawn centrelines through the pupil similarity; half-widths ×2.3; soft edge 0.3 mm; fill 0.75; multiply (.08, .05, .05). At 440 px: area 17/19 px (drawing 16/15). |

### 1.4 Neck

| Piece | What it is today | Where | Parameters as measured |
|---|---|---|---|
| Neck shade | Vertex colour on the neck: full from the jaw to `z_full`, then a smoothstep to `z_clear`. | `ink-batch/fit.py` `neck_shade()` (char-live-3). | `z_full` 1.422 m, `z_clear` 1.385 m, `side_rise` .025, `side_fade` .30, base (.754, .389, .247), strength (.601, .724, .728). Patch (189, 118, 88) against (192, 121, 90). |

### 1.5 Ink carriers (HANDMADE_INK v1.2)

All five rows below come from three files: `docs/char-live-3/ink-batch/carriers.py` and `design.py`, and `docs/char-live-3/ink-batch-2/design2.py`. They share the eyes map (range 5.5 mm, 0.26 m across 2048 px), `width: "uv"`, `min_px` 1, default fade 3, and placement at 0.3 mm with 0.35 mm clearance in every morph target.

| Piece | Parameters as measured |
|---|---|
| Upper lid with wing | Drawn half-widths (eye units), ×1.25 over t .12→.42 and the wing. Ink edge 0.5 mm into the opening. Colour (6, 2, 2). Front band 7.5 px against 7.3; darkness 0.59 against 0.59. |
| Lash fringe | Sawtooth from t .30 to .97: spacing 0.9 mm, spike length 0.8 mm, lean .35, root half-width 0.45 mm, root inset .35. |
| Lash flicks (2) | The drawn flicks, rooted on the band's top edge. |
| Outer lower lid | The drawn profile ×1.3, upper edge on the rim. |
| Brows | The drawn shape through the canthus similarity, ×1.0. Colour (57, 32, 20). Thickest 8.5 px against 7.7 front, 8.0 against 8.0 at three-quarter. |
| Lid core | Opaque `line` geometry inside the lid stroke: half-width = hw − max(.35·hw, 0.6 mm). It keeps the lid's value at play distance. |

The carriers add 1,156 triangles (lid 2 × 176, lash flicks 4 × 54, fringe 2 × 78, lower lid 2 × 54, brows 2 × 136, cores 2 × 26) against the 184 faces removed.

**Dropped:** the jaw carrier (it needs view-dependent strokes, §7) and the nostril carriers (replaced by paint).

### 1.6 Hair

| Piece | What it is today | Where | Parameters as measured |
|---|---|---|---|
| Lock layout | 32 UV islands, each a closed, tapered section with a ridged cross-section and its own normals: 14 sweep, 12 combed, 3 braid, support, tie, brush. | `docs/char-live-2/hair/final/lock-layout.json`, stage-4 xhigh blocks. | Spread 1.870 cheek widths (target 1.87 ± .10), crown lift .124 H, rear depth .519 H. Front tips 10, three-quarter 8. 22,674 hair triangles plus 1,602 plait crest. |
| Grouping and braid start | Rear locks grouped into a visible braid start at the nape. | `docs/char-live-3/back-hair/fit.py`, `strokes.py`. | Crown and side stations in cheek radii and H; parent and companion widths; staggered join heights; part offset; plait root lift and upper width. |
| Plait | Three strands, over/under phase descending to the middle. | `back-hair/plait/fit.py`, `highlights.py`. The generator already has a three-strand `_braid_mesh` (`hair.py:1297`, char-port-1). | Width gain from nape to tie; elliptical section; crest-shadow dye = auburn mid; a curved highlight per segment. 7.8 px Near, 5.1 px Middle. |
| Palette bands (hair profile) | Base swatches tuned so the calibration frame meets the drawing. | `slop.hair` in Cora's GLB. | Base sRGB: shade (43, 4, 1) (later 44, 8, 2), mid (104, 37, 8), light (119, 43, 6), highlight (135, 47, 3). t1 −0.20, t2 0.40, edge .02, `highlight_feather` .08. Highlight per upper lock group (`_HIGHLIGHT`, or R of `.hair.png`). |
| Lock ink lines | G of `.hair.png`, from painted lock lines. | `ink_field.py`, `hair/final/lock-lines.png`. | ink (4, 0, 0), `ink_px` 1.05, `ink_range` .009, `ink_fade_px` 2.0 (GC choice). |
| Floor-relative ink calibration | A drawing ratio applied above the measured black floor. | `hair/final/ink-contrast.json`, `calibrate.py` (`"relative"`, `"floor": "control"`), `ink-batch/ink_calibrate.py` (close shot). | Hair ink target (65, 41, 33); floor (29–34, 27–32, 23–29) depending on GPU. |

### 1.7 Profiles as files

| Piece | What it is today |
|---|---|
| The handmade-hair profile (`slop.hair`) and the ink profile (`slop.ink`), with their sidecars `.hair.png` and `<stem>.eyes.ink.png` | Written by hand-run tools on one file: `handmade_extras.py`, `ink_field.py`, and the session blocks. **The generator writes neither.** |

## 2. How each piece becomes a parameter or a master

**Rule of thumb for what varies how:**

- **The type** (sex × age band × line a/b/c) carries the means.
- **The person's seed**, through `person_params.draw` with its per-field streams, carries the spread. A family share follows the existing `family_share` .7.
- **Fixed style** is what the art direction holds constant for everyone: ink colours relative to the floor, the fade, the face-shadow remap, the band thresholds.

Ranges below are proposals, set so Cora's values sit inside them. Each must be confirmed by the four-body proof (§5) and by `face_types.py check`.

### 2.1 Jaw and chin taper

- **Where they go:** `jaw.jaw_taper` and `jaw.chin_taper` become values on **every type record**, and an identity draw is added in `person_params.draw` (new streams `jaw_taper`, `chin_taper`).
- **Ranges:** `jaw_taper` −0.10…+0.35, `chin_taper` −0.35…+0.10.
- **Type means (proposed):**
  - adult f: +0.20 / −0.22
  - adult m: +0.05 / −0.05
  - youth: 70% of adult
  - child-u: 0 / −0.10
  - elder: adult + 0.05 jaw (softer jaw)
- **Seed:** sd 0.08 each; family share .7.
- **Carry weights:** they move from Cora's replay into `cage_head` as module constants: `jaw_taper` .395, `chin_taper` .675, and the existing per-row carries above. They are fixed style, not drawn.
- **Unsure:** whether the carries generalise across lines a/b/c. Check with `cage_accept.py` across all 21 types.
- **As built in S1** ([s1/README.md](s1/README.md)):
  - **The means:** class means of `jaw_taper` −0.05 and `chin_taper` −0.18 for adult women, and lighter values elsewhere, in `living/tools/characters/port.json`.
  - **No new seed streams:** the identity bones `J_Id_Jaw` and `J_Id_Chin` already carry each person's spread.
  - **No carry weights:** they were Cora's own fit (`fit_cora_rows`), not the generator's.
- **Decision (GC, 2026-11-20): the three lines stay distinct.** a stays round, b even, and c long with the V. Tapers alone reach the drawing's chin-over-jaw (0.507) only on line c. Bringing lines a and b there would mean moving the types' jaw line itself, at the cost of the variety the lines exist for. Cora's V is one face in a town.

### 2.2 Depth stations

- **Approach:** compare Cora's fitted midline (brow .0203 H, nose .1096 H, lip .0599 H) with the `adult-f-*` types' `sections.p00` and `nose.out`.
  - Where Cora falls **inside** the identity ranges, there is nothing to port: her face is one draw of the type.
  - Where she falls **outside**, widen the identity bone's range, or shift the type mean if the drawing style asks for it on every woman.
- **New fields:** none expected beyond `jaw_taper`/`chin_taper`. If a station must move independently of the bone (the session moved stations directly on the cage), add `sections.p00_offsets` to the type record (per-row midline depth offsets, ‰H) rather than new bones.
- **Varies by:** type (means), seed (existing `J_Id_*` draws).
- **Stays per character:** the exact values, as a hero override (§2.9).

### 2.3 Chin pad and neck curve

- **Chin pad:** the relaxation of the two lowest stations becomes a fixed cage step in `cage_head` (`chin_pad_relax` 0–1, fixed style 1.0 for all types). It's topology, not identity.
- **Neck curve:** the forward throat curve becomes two `jaw` record fields, `neck_forward_mm` (Cora +3.4) and `neck_return_mm` (Cora −1.5), applied to the cervical rings in angular order. They vary by type; the seed draws ±1.5 mm. Child-u stays at 0.
- **Under-jaw seam** (UVs, pigment and normals carried to the neck seam): a **fixed generator fix** in `cage_head` for every type. It removes a seam rather than adding a look.

### 2.4 Eyes

- **`iris_wide`:** becomes a type record field `eye.iris_wide`, replacing the constant `IRIS_WIDE` .88 when present. Cora's ×1.27 on her pinned revision lands at about 1.12 on the constant's scale, but *unsure*: her disc was widened after export, on a cage that predates `_eye`'s current rings. Re-measure on the woman body in step S1.
  - **Varies by:** age (child larger), seed (sd 0.04).
- **Outer canthus:** `eye.outer_lift_mm` (Cora 1.3) by type, `eye.wing_mm` (rise 4.8, reach 4.0) as fixed style for women and youth, 40% for men. The wing is drawn by ink now (§2.6), so these fields set the *stroke*, not band geometry.
- **The old `line` band, lash cards and brow strip:** they stay generator geometry for files that don't opt into ink (`look.ink: false`). With ink on, the generator emits carriers and the lid core instead (§2.6).

### 2.5 Face paint, shading and neck

All of these move into `face_paint.py` / `person.py` as **named parameters**, in the type layout's UV terms. Because the atlas layout is shared across types (`EYE_ROWS`, the 192-row eye strip, the skin below), Cora's UV values carry over; *check* per line a/b/c, where the nose and mouth rows sit at different v.

| Parameter (proposed) | Value from Cora | Varies by |
|---|---|---|
| `paint.skin_lift` | (1.114, .963, .935) | Fixed style, tuned per skin tone in the calibration frame. *Unsure* it suits darker tones; measure on two. |
| `paint.blush` {centre_u, centre_v, rx, ry, pigment, weight} | .139, .692, .089, .050, (.83, .53, .40), .51 | Centre and radii by type line. Weight by `look.blush` (seed). Pigment fixed. |
| `paint.mouth` {crease_v, crease_sigma, lip_weight, lip_shadow} | .7944, .00165, .29, .55 | Type line (v). Weight by seed. |
| `paint.nose` {flank_u, flank_half_u, curve_v, bend, tilt, above, below, pigment} | .484, .043, .738, .012, .004, .0045, .0035, (.38, .41, .42) | Type (nose rows); `look.nose_line` scales pigment. |
| `paint.glint` {u, v, ru, rv, rgb} | .502, .711, .0045, .0025, (255, 236, 211) | Fixed style. |
| `paint.nostril` {gain, soft_mm, ratio, fill} | 2.3, 0.3, (.08, .05, .05), .75 | Centrelines from the cage's nose base and alae columns (not drawing registration). `look.nostril` scales width. Child: ×0.8 width. |
| `face_shadow` {blur_px, floor, gain} | 8, .48, .51 | Fixed style, in `face_normals.py`. |
| `neck_shade` {z_full, z_clear, side_rise, side_fade, strength} | Relative to the type's chin height (Cora: −8 mm, −45 mm below the chin bottom at 1.4304), .025, .30, (.601, .724, .728) | Heights by type proportion. Strength fixed (calibrated). |

**Nostrils are measured on the face**, as `nostrils.py` does: atlas texels rasterised to their front-view design points (`nose_texels`). In the generator the cage knows those points directly, so the painter takes the cage's nose rows instead of a drawing.

### 2.6 Ink carriers as a generator output

The carrier code (`carriers.py`: lift, harmonic fill, isometric flatten, binding, clearance, pinned packing) moves into `living/tools/blender/ink_carriers.py`, unchanged in substance. What changes is the **source of the strokes**: Cora's were registered from a drawing; a generated head takes its strokes from **cage-relative stroke definitions**, in eye units on the cage's own opening (`lid_top` × `C_E0…C_E3`), canthi and brow rows.

| Stroke | Definition (eye units on the cage) | Parameters and ranges | Varies by |
|---|---|---|---|
| Upper lid | Along the opening edge from the inner to the outer canthus, then a wing. Ink edge 0.5 mm in. | `lid.width` profile (Cora's drawn profile as the default curve, peak 0.115 eye); `lid.gain` 0.9–1.3 (Cora 1.25) over `gain_from`/`gain_to` .12/.42; `wing.length` 0–0.30 eye (Cora 0.27); `wing.rise` 0–0.10 eye (Cora 0.09) | **Sex:** women and youth-f wing 1.0, men 0.4, child 0. **Age:** elder ×0.85 width. **Seed:** gain sd 0.05. |
| Lash fringe | Sawtooth on the band's top edge. | `fringe.from`/`to` (.30/.97), `spacing_mm` .9, `length_mm` 0–1.0 (Cora .8), `lean` .35, `root_mm` .45 | **Sex:** women 1.0, men 0.5 (length). **Child:** 0.6. Seed: length sd 0.1. |
| Lash flicks | 0–3 flicks rooted on the band's top edge. | `flicks` count (Cora 2), positions t .71/.97, length .16 eye | Sex (men 0–1); seed. From `look.lashes`. |
| Outer lower lid | Outer part of the rim, from t .53 to the canthus. | `lower.gain` (Cora 1.3 × drawn 0.04 eye), `lower.from` .53 | Sex (men ×0.7); from `look.lower`. |
| Brows | The type's `brow` record (`above_eye`, `arch`, `tilt_deg`, `thick`) as the stroke's centreline and width; Cora's shape as a profile for the women's lines. | `brow.peak_eye` (Cora .16), `brow.inner_t`/`outer_t`, taper | Type (brow record); identity `J_Id_Brow` (height, tilt, thickness) still poses it; seed. |
| Lid core | Opaque, generated from the lid stroke. | `core_inset` .35, `core_margin_mm` .6 | Fixed. |

**Maps:** the carriers are laid out in a **shared UV layout**, the same for every type, and pinned by island as attempt 2 did. Width variation comes from carrier geometry (identity bones scale it) and from the stroke parameters above.

- **One map, or one per class.** Strokes that differ per person can't share one map. So per-person variation is limited to a small number of **stroke classes** (for example fringe on/off, wing long/short/none), each class an island set in one map per age-sex class.
- **The count:** `eyes.ink.png` ×6 at most (child, youth-f, youth-m, adult-f, adult-m, elder). They sit beside the type files and are shared like style files.
- **Unsure:** whether 6 maps × 1024² (KTX2 BC7 with mips, about 1.4 MB each) is enough resolution at 0.26 m across. Cora's map is 2048²; 1024² halves texel density to 0.25 mm. Test both in S4.

**Colours:** `ink.color` per material, calibrated once per class against the floor (the `ink_calibrate.py` procedure). Fixed style; the brow colour follows the hair tag (needs the client step, §0.3).

**Morphs:** carriers are primitives of the type's `Face` mesh. They are built on each expression's cage, as `_shell_lines` already are (`cage_head.py:1095`), rather than bound after export. They follow the 15 keys and the identity bones by construction. The clearance pass runs per key, as Cora's did.

**As built in S4** ([s4/README.md](s4/README.md)), to the laptop's final contract (HANDMADE_COMPOSED v1.3):
- **The page:** one shared ink page, `lookdev/types/types.eyes.ink.png`, 4096² with a 1024 cell per class at 0.25 mm a texel, replaces "one map per class" above.
- **Strokes:** in eye units, one stroke set and one carrier topology per class; per-person variation stays with the face's own shape and the identity bones.
- **Colours:** `ink.color` is Cora's for every class.
- **Materials:** lid and brow (`LidInk`, `FaceBrowInk`) for everyone.

### 2.7 Hair: see §3.

### 2.8 The profiles as generator outputs

- **`slop` on generated files:** `person.py` writes `slop` extras on the type file's and style files' materials whenever `look.ink` or a hair profile is on:
  - `slot` on every material;
  - `ink` on the carriers;
  - `hair` on profile hair.

  `face_normals.py` already writes TEXCOORD_1 and `.face.png`. The scene keeps `character` unset: composed files are not "handmade".
- **Sidecars:**
  - `<style>.hair.png`: R the highlight, G the lock ink;
  - `<class>.eyes.ink.png`.

  Both are written by `ink_field.py` from geometry the generator already knows (lock seams, carrier strokes), never painted. `share.py pages` must leave both out of the shared pages, as it now leaves `.iris` and `.tint`.
- **The audit:** `calibrate.py --no-run` runs on every type and style file in `town.py`'s check, and must report 0 errors and 0 warnings.

### 2.9 What stays per character: hero overrides

**Proposal:** a person line may carry an `overrides` object, outside the canonical look-book fields, so ordinary residents' keys don't change. It can hold:

- the type-record values (`jaw`, `nose`, `brow`, `eye`, `sections.p00_offsets`);
- the paint parameters;
- the ink stroke parameters;
- a hair master name with its parameters.

`person.py --params` applies them after `draw`. A hero built this way is still composed, from a **hero type file** written for them (`lookdev/types/hero-<name>.glb`); there is no per-person face file. Cora herself stays a hand-made whole file until her overrides reproduce her: that is the woman's comparison in §5.

**Unsure:** whether the look book should carry heroes at all, since it's append-only and keyless by design. Decide with the look-book owner.

### 2.10 Hero override contract (proposed; for agreement with the laptop before S3)

The GC approved a minimal hero mechanism (2026-11-20). This is the proposed shape, sent to the laptop for agreement before S3 builds.

**Where it lives.** A world seed names its heroes in one short block beside the town's residents. A hero is never a per-person blob for the whole town:

```json
"looks": {
  "generation": "…",
  "heroes": {
    "Cora Stannard": {
      "hero_file": "characters/heroes/own-cora-live.glb",
      "bands": [3],
      "override": {
        "type":  { "jaw": { "jaw_taper": 0.24, "chin_taper": -0.27 },
                   "eye": { "iris_wide": 1.12, "outer_lift_mm": 1.3 } },
        "paint": { "blush": { "weight": 0.51 }, "nostril": { "gain": 2.3 } },
        "hair":  { "master": "swept_braid", "colour": "#8a3b1f" }
      }
    }
  }
}
```

| Field | Type | Meaning |
|---|---|---|
| `heroes` | object, keyed by the resident's `name` in the seed | **At most 8 entries a world.** A name not among the seed's residents is an error. |
| `hero_file` | string, a path under `living/game/assets/`, optional | A hand-made whole file (HANDMADE_HAIR/INK contract, `slop.character: "handmade"`). When present, it is drawn for the bands in `bands` instead of a composed person. Its sidecars sit beside it. |
| `bands` | list of look bands (0–4), optional, default: the resident's band at genesis | The bands the hero file covers. The other bands are composed from the seed's draw plus `override`. |
| `override` | object, optional | Three sub-objects, each validated against the generator's parameter table (names and ranges in §2.1–§2.6, and §3 for hair). An unknown key or an out-of-range value is an **error** at seed check (`look_lines.py` and `town.py`), never silently clamped. |
| `override.type` | object | Type-record values (`jaw`, `nose`, `brow`, `eye`, `sections.p00_offsets`). They make a **hero type file** `lookdev/types/hero-<slug>.glb` (and its sidecars), because type values shape the cage. |
| `override.paint` | object | Paint parameters (§2.5). They are baked into the hero type file's atlas and tint. |
| `override.hair` | object | A hair master and its parameters (§3). They make a style file `lookdev/styles/hair/hero-<slug>.glb`. |

**How the generator and the composer use it:**

- **Generator (`town.py`, `look_lines.py`):** for a hero, it draws the person as for anyone, applies `override` on top, writes the hero type and style files, and writes the hero's look-book lines.
  - A line's `type` names `hero-<slug>` and its `styles.hair` names `hero-<slug>`.
  - For the bands in `bands`, the line also carries **`hero_file`**, a new canonical field. It enters the line's key, so the key changes only for heroes.
- **Composer (client, S3):**
  - A line with `hero_file` spawns that whole file (the recipe's `base`), as a recipe without a person line is drawn today.
  - Any other line composes as now: `lookdev/types/<type>.glb` plus its styles. A hero type is just another type file.
  - The client needs no override logic of its own: overrides are resolved at build time.
- **The book stays keyless about people:** it doesn't say a line is a hero's. Only the world seed names heroes, and it isn't shipped to clients.

**For the laptop to agree:**
1. `hero_file` as a canonical line field, drawn instead of composing.
2. `hero-<slug>` type and style names in the shared folders.
3. The 8-entry cap.
4. Whether a hero file's band coverage should also be checked client-side.

## 3. The hair system

**Recommendation: keep the procedural lock generator (`hair.py`) and add Cora's grammar to it as parameterised masters,** rather than shipping hand-made lock layouts.

- **What the generator already has:** layers, combing, ribbons, curl, springs (CHARACTERS.md § How hair is built), and since char-port-1, a three-strand plait.
- **What Cora's hair adds is a grammar, not a mesh:**
  - grouped locks (a parent with companions);
  - swept sections with a ridged cross-section and their own normals;
  - returning hooks;
  - staggered joins into a braid start at the nape;
  - per-group highlights.

**A master is a named parameter set** in `hair.py` (for example `swept_braid`, Cora's cut). It gives:

- the layer list;
- per-layer lock counts, root stations (in cheek radii and H, as the back-hair fit expressed them), widths (parent and companion), crease widths and stagger heights;
- plait parameters (root lift, upper width, width gain to the tie, phase);
- a highlight rule (which groups get one).

**Seeded variation:** lock count ±15%, root jitter ±0.05 cheek radius, length ±8%, curl, parting side, and the fringe from the existing `fringe`/`fringe_style`. The silhouette stays within the master's measured envelope (spread, lift and rear depth within the tolerances Cora was held to: ±0.10 cheek widths, ±0.035 H, ±0.04 H).

**Masters to start with:** `swept_braid` (Cora) only, proven before more are added. Later candidates are the women's `long`, `braid` and `bun` re-expressed in the grammar.

**Triangle budget per master: ≤ 12,000** (cap included). That is about half of Cora's 24,276, so lock sections must drop from Cora's ridged sections (more vertices across) to the generator's 5-across ribbon with a ridge normal, *and keep the look*. This is the hair's main risk; the proof judges it (§5).

**How a generated hair asset gets its `.hair.png` and palette automatically:**

1. **UV.** Each lock (or lock group) gets its own UV island, laid out by its own lengths, as Cora's stage-4 UV block did. Today every lock shares one column of the 256×512 strand texture; the profile path doesn't need that texture.
2. **Highlight (R).** Islands of the groups the master marks are filled with the highlight shape (a band along the lock at a fixed fraction of its length), rasterised by the generator. The alternative is `_HIGHLIGHT` per vertex, which needs no texture.
3. **Lock ink (G).** `ink_field.py --seams-as-lines --glb <style>.glb` takes the island borders as lines: exactly the lock boundaries. Cora's hand-painted `lock-lines.png` wasn't needed for that part. It also added interior crease lines; the generator can rasterise those from each lock's crease, using the same `--width` path.
4. **`ink_range`** is set per master to half the narrowest line spacing in UV, printed by the tool. `ink_px` 1.05 and `ink_fade_px` 2.0 are taken from Cora as fixed style.
5. **Palette.** The profile palette *replaces* the hair's colour, so a shared style file can't carry one fixed palette for every wearer. Proposal: a **relative palette** in a contract bump (HANDMADE_HAIR v1.3):
   - `slop.hair.palette: "tag"` with four multipliers `shade_k`, `mid_k`, `light_k`, `highlight_k`, applied in linear light to the person's `_HAIR` tag colour, and the thresholds as today;
   - Cora's base swatches relative to her mid give, in linear light (red / green): shade 0.18 / 0.13, light 1.30 / 1.27, highlight 1.72 / 1.48. Multipliers are therefore per channel, not one number;
   - the client builds the palette per tag, so materials are keyed by tag bin, as `SAME_SOURCE` keys toons now.

   This is client and contract work. *Unsure* whether a single set of multipliers holds across black, blond and grey hair. The calibration frame must check dark, auburn and light hair, and multipliers may need to vary with lightness.
6. **The floor-relative ink calibration** runs once per hair-colour bin on the four bodies. Its targets come from the drawing's ratio, as accepted for Cora; it doesn't run per resident.

**As built in S5** ([s5/README.md](s5/README.md)), to the laptop's final contract (HANDMADE_COMPOSED v1.3), behind `SLOP_PORT=hair`:
- **UV:** every piece of a style is its own island at 1 mm a texel (`hair.page_layout`), on the shared hair-mask page (4096², cells of 512). The far mesh takes the near pieces' places.
- **Highlight:** `_HIGHLIGHT` per vertex and the page's R, a scalloped band on the upper hair.
- **Lock ink:** grouped into locks: a curving line of its own length up each notch, and shorter companions inside the lock (`hair.LOCK_LINES`). They are rasterised into G by `hair_page.py`, not `ink_field.py --seams-as-lines`, and island borders aren't drawn as lines. `ink_range` is 6 texels, so the lines fade before Near: close-up only, as the GC decided.
- **Parting:** a pale strip in R where the hair parts (over-sheet styles, curtain fringes, braids): the structure that holds in play, with the bands.
- **The strands (B2, the GC's choice over B1's lock-wise band breaks):** main's strand picture under the bands at low contrast, in the page's B, behind the profile's `strands` flag (HANDMADE_COMPOSED v1.3.1).
- **Lock-line colour:** a darker shade of each anchor's own mid swatch (0.65 × its lightness, at least 0.12 below it), never near-black on hair that isn't.
- **Palette:** the contract's `palette: "tag"` with `ref` and anchors replaces the per-channel multipliers in step 5 above. There are four anchors (black, brown, blond, grey); v1.3.1 allows 4.
- **Calibration:** run once per bin on a composed woman, not on the four bodies.
  - **Cora's profile:** channel by channel.
  - **The anchors:** lightness and chroma size only. Their hue is the palette's own, so no anchor carries a correction for the calibration frame's light; grey's had turned its shadow side blue.
  - **Light hair's highlight:** a small step over its light band, in its chroma.
  - **Black and brown:** floored to what play distance needs. At Middle black is within 4 of main's luma, and brown is 14 above it.
  - **Result:** chromatic bins within ±5. Auburn's shade is held 15–17 light by the sky fill. Black and grey are neutral, showing the scene's warm light per channel.
- **Capacity:** the generator's 86 style files need three pages, at 1 mm (the GC's decision).

## 4. The client step this needs (summary of §0.3, §2.6, §3)

- **`compose.rs` reads material `slop`** from type and style files, and turns it into the same `InkProfile`/`HairProfile` that `handmade.rs` builds. Reuse `handmade::material_of`; don't copy it.
- **Sidecars:**
  - **Resolution:** `<stem>.hair.png` beside the style file and `<class>.eyes.ink.png` beside the type file; KTX2 copies preferred.
  - **Sharing:** loaded once, like the strand picture.
- **The relative hair palette** (HANDMADE_HAIR v1.3) and brow ink following the hair tag.
- **The material content key** includes the profile, the map and the tag bin, so batching holds.
- **Compatibility:** a file without `slop` draws exactly as today. Test it as the handmade-ink proof did, by pixel comparison of a composed person against the base client.

## 5. The four-body proof

As in char-port-1: **woman, man, elder and girl**, the same seeds, identities and types as char-port-1's, so the clothing proof's bodies are reused.

| Arm | What it is |
|---|---|
| **main** | The bodies' current generator output, composed. |
| **port** | The same bodies built only from the new parameters (types.json values, draws, paint, ink, hair master where the style allows). No hand edits. |
| **Cora** (woman only) | Her session asset, `docs/char-live-3/ink-batch-2/own-cora-live.glb`, against a **woman built with Cora's overrides**: Cora's type values, paint and ink parameters, `swept_braid` and her colours. |

**Judged side by side:**
- **Shots:** portrait, three-quarter, 58° Near and Middle, at the calibration frame's 11:00 daylight with the composed client after S3.
- **Measures:**
  - the front widths (cheek, jaw, chin);
  - the depth projections;
  - the lid band and darkness (`lidweight.py`);
  - nostrils (`noseweight.py`);
  - hair spread, lift and depth (Cora's `volume.json` method);
  - the 20 colour checks for the Cora arm, and the hair and skin patches for all four.

**Pass criteria (proposed):**
- **Cora arm:** within the tolerances Cora was accepted at (front widths ±0.025 H, projections ±0.010–0.015 H, lid band ±1 px at 440, colours ±8/±10).
- **Port arms:** no regression against main on char-port-1's checks (crossings, braid scalp gap).
- **Audits:** clean on every file.
- **Shimmer:** passing per slot.
- **Expressions:** all 15 move and neutral returns exactly.
- **Play stills:** no blots at Near and Middle.
- **The GC's eye** decides likeness, as for every character stage.

## 6. Budget and cost

**Triangles, near, per person** (main today: woman 30,264, man 33,304, elder 31,382, girl 27,582; after char-port-1 32–36k):

| Part | Today (woman, main → port-1) | After char-port-2 (estimate) |
|---|---|---|
| Body and head with shell lines | about 17k (the cage head 7,092, +420 with tapers) | +420 (tapers), about 0 for the rest |
| Old eye lines, lash cards and brows | about 400 | −400 (removed where ink is on) |
| Ink carriers and lid core | 0 | +1,100 to +1,300 (Cora: 1,156) |
| Hair | long 11.1–11.6k; bob 5.6–6.8k; braid 5.8–7.0k | `swept_braid` ≤ 12,000 |
| Clothes | about 13–15k | unchanged |
| **Total** | 32–36k | **about 36–40k for a woman in `swept_braid`; others +1.5k at most** |

- **Ceiling:** the 50,000 near ceiling (`docs/character-hybrid-spike/verdict.md`) holds with about 10k to spare.
- **Cora is the outlier**, at 49,702 with 24,276 in hair. She stays a hero.
- **Far model:** unchanged. Ink fades long before the far switch at 10 m; the far head keeps its own 16 mm jaw line.

**Cost at 8 near characters**, measured the way HANDMADE_HAIR/INK measured it: frame time, because wgpu has no GPU timestamps on the laptop's Metal.
- **Setups:**
  - **dev-box AMD (Radeon 8060S):** 8 composed people (`LIVING_GAME_CROWD` with 8 named recipes, since `LIVING_GAME_VIEW_COPIES` copies whole files only) at the Near stop at 1600×900, and in a 4K close portrait.
  - **The A/B:** the same 8 with `slop` stripped from their files, a temporary copy as `ink_shimmer.py` makes.
  - **The 64-resident Cullet crowd** against its pass-3 baseline: near about 10.8 ms, far 8.4 ms, empty scene 6.4 ms (CHARACTERS.md § Crowd cost).
- **Readings:**
  - **Frame time:** the median over 10 s of steady frames, uncapped (`LIVING_GAME_FPS_CAP=0`), in alternating runs, three pairs each.
  - **Draw load and memory:** `LIVING_GAME_PERF=diag` for batches, texture bytes and mesh-material pairs, and `frames` for ready time.
  - **CPU:** `live_crowd.py` p50/p99 frame interval, and the client's compose time per person at spawn.
- **Expected:** ink is one texture read per inked material, and carriers are one draw per inked material per person: two (lid and brow). Hair profile cost was not measurable on the laptop (+0.26 ms ± 1 ms at 4K). The likely costs are the **extra draws** (2 × 8 per frame, and 128 in the 64-crowd) and **texture memory** (6 ink maps + 1 hair mask per master, about 10 MB in KTX2).
- **Budget to accept (proposed):** at most +0.3 ms at 8 near, at most +1.0 ms on the 64-crowd, on the dev-box.

## 7. Staging

Each step is mergeable on its own, behind `look.ink` and the profile flags, so main never draws a half-ported person. Effort is in focused agent hours, excluding gate waits.

**Models:** asset and generator work runs on **Claude Opus 5.5** until Codex returns on 25 November; then the GC decides (GPT-6.2 Astra for asset generation by the routing rule). Client and contract work (S3) is game-client systems: **Opus, high**, by the routing rule. Measurement runs (S0 and parts of S7) can move to GPT-6.2 Sol after the 25th.

| Step | Contents | Acceptance and checks | Effort, model |
|---|---|---|---|
| **S0 · Baseline** | Build the four bodies on main; record counts, the 20-check frame for the woman, `lidweight`/`noseweight`/volume on all four, and the 8-person and 64-crowd frame times. Confirm whether Cora's head carried `_shell_lines` (unknown). | Numbers recorded; reruns reproduce counts and frames (two builds, same seed). | 3 h · Opus (Sol after 11-25) |
| **S1 · Face geometry** | `jaw_taper`/`chin_taper` on every type and in `draw`; carry constants; chin-pad relax; neck fields; under-jaw seam fix; `eye.iris_wide`, `outer_lift_mm`; any `p00_offsets` found necessary. | `face_types.py check` and `cage_accept.py` on 21 types; `brow_check.py`; the four bodies' front widths and projections within type ranges; Cora's overrides land within Cora's tolerances; 15 keys move, neutral exact. | 6–8 h · Opus high |
| **S2 · Face paint and neck** | The `paint.*` parameters, the nostril painter on cage points, `face_shadow` remap, `neck_shade`. | `eye_colours.py --check`, `shade_mean.py --check`; skin and neck patches on the woman within ±10; the GC's sheet at portrait, three-quarter, Near and Middle. | 4–6 h · Opus high |
| **S3 · Client: composed `slop`** | `compose.rs` reads `slop.ink`/`slop.hair`; sidecar resolution; relative palette (HANDMADE_HAIR v1.3); content keys. | Pixel identity of unflagged composed people and whole files against the base client; `verify-ui` (`crowd.md` compose); `calibrate.py` audit on composed files; the cost A/B at 8 near. **Run `maintain-verification-skill` on verify-ui and update CHARACTERS.md / HANDMADE_*.md.** | 8–10 h · Opus high (client systems) |
| **S4 · Ink carriers from the generator** | `ink_carriers.py` in `living/tools/blender`; cage-relative stroke definitions; built per expression; lid core; class maps via `ink_field.py`; `slop.ink` on the type files; old lines kept when ink is off. | The audit 0/0 on 21 types; `ink_shimmer.py --slot eyes` passing at portrait and close-up and faded at the play stops; morph stills (blink, joy, talk, angry brow) on 4 bodies; `lidweight` within ±1 px of the class target; triangles within §6. | 8–12 h · Opus high |
| **S5 · Hair profile output** | Per-lock UV islands; `.hair.png` (R highlight, G seams and creases) by `ink_field.py`; `slop.hair` relative palette; calibration per colour bin (dark, auburn, light, grey). | The audit 0/0; `hair_shimmer.py` passing at fade 2.0; hair patches within ±8 per bin; existing styles unchanged when the profile is off. | 6–8 h · Opus high (Astra after 11-25) |
| **S6 · Hair masters** | The `swept_braid` grammar in `hair.py` with seeded variation; ≤ 12k triangles. | Spread, lift and depth within Cora's tolerances on the woman; front and three-quarter tip counts in Cora's range (10 ± 2, 9 ± 2); plait visible at Near and Middle (width within 0.5 px of the drawn rear); char-port-1's braid scalp gap and collar checks; springs. | 10–14 h · Opus high (Astra after 11-25) |
| **S6b · Face proportions** (added 2026-11-21, the GC) | Narrow the faces against their eyes toward Cora's drawing: the face's width at the cheekbones over the eye spacing, **1.75** (the drawing's 1.75 and 1.70 in its two copies; ours 1.86 at the GC's count, 1.93 on the S6 front portrait). The width through the type's cheek and jaw parameters (S1's), the eyes left as they are. On the critical path to looking like the reference. | **The acceptance (the GC's, 2026-11-21):** the 2D front-render measure, as `drawing_spread.py` measures the drawing, with the ears masked by the ID render (`drawing_spread.face_render`, [s6b/ear_id.py](s6b/ear_id.py), [s6b/face2d.py](s6b/face2d.py)); the 3D slice ([s6b/face_width.py](s6b/face_width.py)) reported. Per-class factors toward 1.75, the children milder, the variety reported. The ears: the lower end 0.47 ±3% and the tops govern; the height is reported. First defined as the ratio by S6's spread's definition (the face's outline at the cheek row with nothing over it, iris centre to iris centre) within ±0.05 of 1.75 on the woman's front portrait, and its change on the four bodies; `face_types.py check` and `cage_accept.py` on 21 types. **The hair measures:** S6's cheek-based spread (reported, not held) should then approach its eye-based one; re-measure both. | after S6 · Opus high |
| **S7 · Four-body proof and cost** | §5 and §6 on all arms; the Cora comparison; the eye-joy fix (below). | §5's criteria; §6's budget. **Must-fix (GC, 2026-11-20):** no eye white or iris showing above a closed lid in any expression: blink, eye-joy, and every key that closes the eye. On main a sliver of the eyeball shows above the eye-joy arc, an eye-geometry defect that S4 found ([s4/README.md](s4/README.md)). The GC's verdict. | 5–6 h · Opus high (Sol for the runs after 11-25) |
| **S8 · Town and bundle** | `town.py` for Cullet; look book generation bump (append-only); the bundle per commit, PNG and KTX2, with checks for the laptop. | The bundle checks of the char-4 practice (`eye_colours`, `shade_mean`, `look_lines wear --check`, `skeleton_check`, `brow_check`, `cloth_check`, book drift) plus `calibrate.py --no-run` on every file; the 64-crowd frame time. | 3–4 h · Opus (Sol after 11-25) |

**Measuring tools: a known-answer test first** (the GC's standing rule, 2026-11-21, for this track and any measuring tool whose numbers a decision rests on). Before its numbers are used, a tool passes a known-answer test: a synthetic shape of known size, with ears and features, goes through the tool's own code and must return the known answer. The test is runnable beside the tool (`*_selftest.py`) and is run again whenever the tool changes. Why: in S6b three tools that sampled vertices near a height or left the ears out by bone weight gave wrong numbers that decisions were taken on (elder-f's jaw "swap", the ears' heights, and the face's width, which counted part of the ear as face).
- [s6b/measure3d_selftest.py](s6b/measure3d_selftest.py): `face_width.py`, `jaw.py`, `ears.py` and `ear_id.py`.
- [s6/drawing_spread_selftest.py](s6/drawing_spread_selftest.py): `drawing_spread.py` (the drawing's measure), its `render` (image_spread.py's) and `face_render` (S6b's acceptance).

**Order:**
- S0 → S1 → S2 (face) can start now.
- S3 (client) can run **in parallel** with S1–S2; it gates S4's and S5's on-screen acceptance, but not their file checks.
- Then S4 → S5 → S6 → S6b → S7 → S8.

**Total:** about 55–70 agent hours plus gate time.

## 8. Risks and open questions

1. **View-dependent strokes (client follow-up from char-live-3).**
   - **Lid at three-quarter:** the lid runs about 25% heavy, because a stroke on the surface can't thin as the lid turns toward the camera. The generator inherits this on every person.
   - **Jaw outline:** Cora's jaw carrier was dropped. Note that the generator already has an inside-out hull jaw line (`_shell_lines`, 1.9 mm under the chin, 1.0 mm along the jaw), which *is* view-dependent geometry: it shows only where the jaw stands over the neck. *Unknown whether Cora's head carried it* (S0 checks). It may answer the jaw for generated people at close range; it doesn't thin with distance as ink does.
   - **Proposal:** a client technique (screen-space edge or a facing-ratio width term in `ink_cover`), designed separately; this plan doesn't depend on it.
2. **The plait's luma** (about 25% over the drawing at Near and Middle) and **close-view transitions** (segment gaps, nape and tie). In the master they become parameters: the crest-shadow dye and the segment overlap. Fix them in S6 rather than port the defect, and judge them in S7.
3. **Reproducibility.**
   - **Seeded streams:** the generator's per-field streams (`rnd(seed, name)`) keep old fields stable when new ones are added, but new parameters change GLB bytes for everyone. Every step bumps the look-book generation, and keys change only where canonical fields change.
   - **Blender's exporter orders triangles in index buffers non-deterministically** across mesh changes (seen in both sessions). Compare GLBs by oriented triangle multisets, as the session checks did, not by bytes, whenever the face mesh changes.
   - **Pin Blender 5.2.2 and numpy** in the builder. The carriers' harmonic fill and spring flatten are iterative; fixed iteration counts keep them deterministic.
4. **The bundle per commit for the laptop.**
   - **New files:** the ink class maps and hair masks are new shared files, so the bundle's file list and `MANIFEST.txt` grow.
   - **Pictures:** `pictures.py bundle` must carry them in both PNG and KTX2 (linear, mipped: `bc7ktx encode` with `"colour": "linear", "mips": "box"`), and `share.py pages` must leave them out.
   - **Shared pictures:** the laptop's client must have S3 before a bundle with `slop` is useful. Order the merges so the laptop never gets maps it can't read.
5. **Identity bones and ink widths.** Carriers scale with the face's bones, so a wide-jawed or small face draws slightly wider or thinner strokes. `m_uv` is measured at rest per type. *Unsure* how far `J_Id_*` extremes move widths; S4 checks the 4 bodies at identity extremes, as `brow_check.py` does for brows.
6. **Children's faces** are small: the ink fades at a closer distance than an adult's, and the carriers' 3–5 mm grid is coarse on a small face. They may need a denser carrier grid (more triangles) or no fringe.
7. **The relative hair palette** is a contract change (v1.3) and a client change. Until it lands, profile hair can't follow the hair tag. A fallback is one style file per hair-colour bin (more files, simple client).
8. **Atlas layout across type lines.** The paint parameters are UV positions in a layout shared by types. If lines a/b/c move the nose and mouth rows, the parameters need per-line values (§2.5). S2 checks this.
9. **Calibration per GPU.** The floor differs between the dev-box AMD (34, 32, 29) and the laptop M4 (29, 27, 23). The floor-relative targets absorb that, but the absolute ink colours were tuned on the dev-box. Recalibrate once on the laptop at S7.
10. **Hero overrides in an append-only, keyless book** (§2.9) need the look-book owner's decision.
11. **Cost of extra draws** at 64 people: two inked materials per person add 128 draws. If the crowd budget is exceeded, the lid and brows can share one material and map (one colour), at the cost of the brow colour following the lid's.
