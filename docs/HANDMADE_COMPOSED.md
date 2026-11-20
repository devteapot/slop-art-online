# Composed characters: hair profiles, ink and heroes (contract v1.3, amended v1.3.1)

**v1.3.1 (2026-11-20, char-port-2 S5, agreed by the laptop and the GC):** two amendments.
1. **Up to 4 anchors** (was 3): see [the palette](#the-palette-relative-to-the-hair-tag).
2. **The strands:** a hair profile's `strands` flag makes the hair-mask page's B a low-contrast modulation of the bands. See [the hair-mask page](#the-hair-mask-page).

Both are optional fields. A v1.3 file is a v1.3.1 file, and with `strands` off a page draws exactly as before.

**Status (2026-11-20): v1.3, agreed by dev-box and the GC (6b6a48ac3, with the shared pages added after); built on branch `char-port-2-s3` (not merged): the client, the tools and the proof ([built](#built-char-port-2-s3)).** This is step S3 of the char-port-2 plan (`docs/char-port-2/PLAN.md` on branch `char-port-2`, §0.3, §2.6, §2.8, §2.10, §3.5, §4). It extends [the hair and face contract](HANDMADE_HAIR.md) (v1, v1.1) and [the ink contract](HANDMADE_INK.md) (v1.2) from hand-made whole files to **composed people**: residents that the client builds from a type file, shared style files and a look line (`characters/compose.rs`; [CHARACTERS.md § The client since compose-1](CHARACTERS.md#the-client-since-compose-1-2026-11-12)). Files keep `"contract": 1`: v1.3 only adds optional fields, file names and line fields.

**Why a document of its own:** v1.3 touches four things that `HANDMADE_HAIR.md` doesn't own:

- the ink maps of `HANDMADE_INK.md`;
- the look book's line fields ([LOOK.md §5](LOOK.md));
- the composed client's material sharing ([CHARACTERS.md](CHARACTERS.md));
- the bundle's file list.

Its one hair-specific part, the palette relative to the hair tag, is also usable by hand-made files. Keeping it here leaves the two agreed contracts stable. Both link here, and nothing below changes a v1–v1.2 field's meaning.

**What it adds:**

1. **[Composed files read `slop`](#composed-files-and-slop).** A type file or style file opts in through its scene, and its materials carry `slop.hair` and `slop.ink` as hand-made files do.
2. **[A palette relative to the hair tag](#the-palette-relative-to-the-hair-tag).** One authored profile is recoloured for each person's hair colour.
3. **[Two shared pages](#the-shared-pages).** Every cut's hair mask is a cell of one hair-mask page, and every class's ink carriers are a cell of one ink page. Profile hair stays one material, and the lid and brow carriers are two.
4. **[Heroes](#heroes).** A look line may name a hand-made whole file. Everything else about a hero is resolved at build time into files of their own. This adopts dev-box's §2.10 with four amendments.
5. **[Bundles](#bundles), [compatibility](#compatibility), [the audit and tools](#the-audit-and-tools) and [the cost plan](#cost-plan).**

## What the code does today

`origin/main` 715aeb1ca:

- **A type file** (`lookdev/types/<type>.glb`) is the character's scene, the recipe's `base`. Its materials go through `lookdev.rs` `convert`, which reads `slop` only when `handmade::of(file)` finds `"character": "handmade"`. Type files declare nothing, so they're classed by name.
- **Style files** (`lookdev/styles/hair|outfit|overlay/…`) are attached by `compose.rs` `attach`. Their materials are made by `Composer::toon`, which reads no `slop`:
  - its kind comes from the name rule (`compose.rs` `kind_of`);
  - its content key is `"{kind:?} {face_map:?} {base:?}"`;
  - a toon is shared with any existing toon of that content whose source colour is within `SAME_SOURCE` (0.004, linear).

  Every hair cut's hair is one toon today (one strand picture, one mean; [CHARACTERS.md § One shading mean a class](CHARACTERS.md#one-shading-mean-a-class)).
- **A person's colours** reach the shader per mesh, in its `MeshTag` (`characters.rs` `recolor`):
  - **Ordinary tag:** sRGB bytes in bits 0–23, with bit 24 set (`tag_color`).
  - **Greying hair** (`grey_tag`): bits 0–7 hold the natural colour's place and bits 8–15 the silver's, both on `HairTints` (binding 105, 256×2). Bits 16–23 hold the person's `grey`, and bits 24 and 26 are set.
  - **Scenery:** bit 25 is wind sway; plants carry bit 25 and a class from bit 26 up, with bit 24 clear.
- **Which colour a mesh takes** is decided by its material name (`characters.rs` `slot`):
  - `_HAIR` and `FaceBrow` take `colors.hair`;
  - `…Overlay…_HAIR` takes `colors.beard`;
  - `_SKIN` takes `colors.skin`;
  - `EyeIris` takes `colors.eyes`;
  - outfit pieces take `colors.outfit[piece]`.

### Where hair tags come from in look lines

From `person_params.py` `person_line`:

| Line field | Value | Who has it |
|---|---|---|
| `colors.hair` | `mix(hair_natural, hair_silver, grey_mean(grey))` as `#rrggbb`. `hair_natural` is one of `HAIR_COLOURS`: black `#131111`, dark_brown `#201814`, brown `#332217`, chestnut `#4a2b1a`, auburn `#662e1a`, sandy `#7a5730`, blond `#9e7d47`, grey `#858585`, white `#c7c7c2`. | everyone |
| `colors.hair_natural`, `colors.hair_silver`, `grey` | The natural colour, the silver (`mix(grey, white, smooth((grey − 0.5)/0.5))`) and the amount | people with `grey` > 0.02 |
| `colors.beard` | The beard's colour | everyone |

So a town has at most 9 natural colours, plus one silver per distinct `grey`, rounded to bytes.

## Composed files and `slop`

**The scene opts in.** A composed type or style file declares:

```json
"scenes": [{ "extras": { "slop": { "contract": 1 } } }]
```

- **No `character` key.** `character: "handmade"` keeps its v1 meaning (a whole file, slots decide kinds, the forward turn), and v1 already treats a scene without `character` as not hand-made, silently. An older client therefore draws an opted-in composed file exactly as today.
- **A higher `contract`:** the file's `slop` is ignored, with one warning, as in v1.
- **Without the scene key,** a composed file's material `slop` is ignored. That is the [compatibility](#compatibility) guarantee: no generated file today carries it.
- **Which file is read:** the one the client loads, or its `anim/` copy when there is one (HANDMADE_HAIR v1). Both must carry the same extras.

**Materials** carry `slop` exactly as on a hand-made file (`materials[i].extras.slop`):

```json
{ "name": "M00_000_Hair_00_HAIR",
  "extras": { "slop": { "slot": "hair",
    "hair": { "palette": "tag", "ref": [102, 46, 26],
              "shade": [44, 8, 2], "mid": [104, 37, 8], "light": [119, 43, 6], "highlight": [135, 47, 3],
              "ink": [4, 0, 0], "ink_px": 1.05, "ink_range": 0.009, "ink_fade_px": 2.0, "ink_m_uv": 0.214 } } } }
```

```json
{ "name": "M00_000_00_FaceBrowInk_00_FACE", "alphaMode": "BLEND",
  "pbrMetallicRoughness": { "baseColorFactor": [1, 1, 1, 0] },
  "extras": { "slop": { "slot": "eyes",
    "ink": { "color": [57, 32, 20], "ref": [102, 46, 26], "width": "uv", "min_px": 1.0, "range": 0.021154, "m_uv": 0.0123 } } } }
```

**What differs from a hand-made file:**

- **The name rule still decides the kind.**
  - `slot` doesn't override `compose.rs` `kind_of` or `lookdev::convert`'s name rules. For example, `…FaceTint_00_FACE` stays a face part and isn't turned into the hand-made multiply.
  - Only `slop.hair` changes a kind: a valid profile on a material that the name rule classes as `Hair` makes it `HandHair`.
  - `slot` is still required on an inked material, to name its sidecar (unless `ink.map` is given), and it gates `hair` to hair materials. The generator writes it on every material it gives `slop` (plan §2.8).
- **Tags still follow the material name** (`characters.rs` `slot`). An ink carrier that should follow the person's hair is named with `FaceBrow` in it, as above, and a lid carrier's name takes no colour.
- **No forward turn.** Composed files already face −Z.
- **Profile hair packs `_HIGHLIGHT`, not `_RING`.**
  - **Today:** a composed hair mesh packs `(_GREY, 1 + _RING)` into its second UVs.
  - **With a profile:** it packs `(_GREY, 1 + _HIGHLIGHT)` (`handmade.rs` `pack_highlight`), and `_RING` is dropped, since a profile has no ring.
  - **Sharing:** a mesh asset is shared by everyone who wears its file, and it's packed once.
  - **Far meshes:** a style file's `FarHair` must wear the same material, or one with the same `slop`, so the colours don't jump at the far switch.

**Sidecars, resolved beside the composed file** (each as its KTX2 copy first, then its PNG, by `lookdev::face_map_files`):

| Sidecar | Order |
|---|---|
| Hair mask | `hair.highlight_map`; then `<file stem>.hair.png` beside the style file. Generated cuts name the [hair-mask page](#the-hair-mask-page) with `highlight_map`. |
| Ink map | `ink.map`; then `<file stem>.<slot>.ink.png` beside the file (v1.2's order, unchanged). Generated type files name the [ink page](#the-ink-page) with `ink.map`. |

### Declared texel density (new, optional)

The ink's width and fade read a material's texel density `m_uv` (HANDMADE_INK, "What the client computes"). The client measures it from the first mesh that makes the material.

**The problem it solves:** a material shared by several files (several hair cuts, or the types of one class) would then take whichever file spawned first, so the drawing would depend on spawn order.

**The fields:**
- `slop.ink.m_uv`;
- `slop.hair.ink_m_uv`, for v1.1 lock ink.

**What they mean:** a number above 0, in metres per UV unit. When set, the client uses it instead of measuring. It is part of the material's content, so files that agree on it can share one material.

**What the generator writes:** the shared pages' fixed densities: 1.024 on ink carriers and 4.096 on profile hair ([the shared pages](#the-shared-pages)).

**The audit:** it warns when a file's measured `m_uv` is more than 10% off the declared value.

## The palette relative to the hair tag

v1's palette *replaces* the hair's colour (HANDMADE_HAIR, "The palette replaces the hair's colour"), so a shared style file can't carry one fixed palette for every wearer. v1.3 keeps the four swatches and their thresholds as authored, but **anchors them to a reference hair colour**. The client moves them from that reference to each person's tag colour.

### The fields (in `slop.hair`)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `palette` | `"fixed"` or `"tag"` | `"fixed"` | `"fixed"`: v1's absolute swatches. `"tag"`: the swatches follow the mesh's tag colour, as below. |
| `ref` | `[r, g, b]` integers, sRGB 0–255 | **required** with `"tag"` | The hair tag colour the swatches were tuned on, as it appears in a line's `colors.hair` (for example auburn `[102, 46, 26]`). Its OKLab lightness must be at least 0.05. |
| `shade`, `mid`, `light`, `highlight`, `ink`, thresholds | as v1 and v1.1 | as v1 and v1.1 | Unchanged. They are the palette **at `ref`**. A person whose tag equals `ref` draws exactly these values. |
| `anchors` | array of up to 4 objects | none | More tuned palettes: each object has `ref` and the four swatches (`ink` optional), tuned on another hair colour, for example S5's black, brown, blond and grey bins. See [several anchors](#several-anchors). **v1.3.1:** up to 4, was 3. One dark anchor moves brown by black's lightness ratio, past auburn, so brown takes its own. **A v1.3 client drops the 4th** (it reads 3 and warns once); the audit reports a 5th as an error, never dropping it silently. |
| `strands` | boolean | `false` | **v1.3.1.** The hair-mask page's B is the strands under the bands ([the hair-mask page](#the-hair-mask-page)). Page-wide: every cut on a page carries the identical `slop.hair`, this flag with it. |

`slop.ink` gains `ref` with the same meaning: when it is set and the mesh has a tag colour, `color` is moved by the same rule. For example, a brow carrier's ink follows the hair, and a lid carrier, whose name takes no colour, keeps `color`.

- **Invalid values:**
  - `palette` is neither value;
  - `ref` is missing, malformed or too dark;
  - an anchor is malformed.

  The client then draws the absolute swatches (`"fixed"`), or drops just that anchor, and warns once.
- **A mesh without a tag colour** (bit 24 clear) draws the absolute swatches.
- **An older client** reading a `"tag"` profile ignores the new keys and draws the swatches at `ref`, so every wearer gets the reference's hair colour. That is visible but harmless. The bundle order in plan §8.4 keeps such bundles away from older clients.

### The maths

**The space: OKLCh** (Björn Ottosson's OKLab, in polar form), from linear sRGB. Every colour, swatch or tag, is decoded from sRGB bytes to linear light first.

- **Why OKLab:** a lightness step there is a perceived step, and its hue is stable when lightness changes.
- **Why lightness and chroma as ratios, and hue as an offset:** a ratio never pushes black hair below black, and it keeps grey and white hair neutral (their chroma ×k stays about 0). That is what one auburn reference must extrapolate to. Additive lightness offsets were tried on the worked example below: they took black hair's shade to (0, 0, 0), the outline's colour.

**For each swatch `s` against the reference `r`**, worked out once when the material is made:

```
kL = clamp(L_s / L_r, 0, 4)
kC = clamp(C_s / max(C_r, 0.02), 0, 4)
dh = wrap180(h_s − h_r)      if C_r ≥ 0.02 and C_s ≥ 0.02, else 0     (degrees)
```

**For a tag colour `t`:**

```
L = min(kL · L_t, 1)
C = kC · C_t
h = h_t + dh
rgb = linear sRGB of OKLCh(L, C, h)
```

**Gamut:** if any channel of `rgb` falls outside [0, 1] (beyond 1e-6), C is reduced by bisection (24 steps, keeping the largest C found in gamut) at the same L and h. Then each channel is clamped to [0, 1], encoded to sRGB, and rounded as `floor(255·x + 0.5)`. A swatch's lightness and hue are therefore never traded away; only chroma is, at the gamut's edge.

**The clamps:**

| Clamp | Value | What the audit says |
|---|---|---|
| `kL`, `kC` | at most 4 | a warning, naming the swatch |
| `C_r` floor | 0.02 | none: below it the reference is effectively grey, and chroma ratios against it mean nothing |
| `dh` | none | a warning when \|dh\| > 30°: a hue shift that large across bands is probably a tuning slip |
| L | at most 1 | none |

**The result is a palette entry:** five sRGB byte triples, the four swatches and the ink. The **ink** is v1.1's `ink` when given; else the anchor's `shade` × 0.6 in linear light, taken at `ref` and moved like a swatch. When a v1.2 `slop.ink` wins on the material, it is that ink's moved `color`. So everything the shader reads for a person is exact 8-bit data, computed on the CPU and unit-testable.

**Greying hair** (a person with `hair_natural`, `hair_silver` and `grey`): two entries, one for the natural colour and one for the silver. The shader mixes each swatch as `mix(natural, silver, clamp(grey × _GREY, 0, 1))` on the **sRGB-encoded** values, then linearises. This is exactly how `recolor` mixes the one hair colour today, so a profile greys lock by lock like today's hair.

### Several anchors

With `anchors`, each anchor `i` (the profile's own swatches are anchor 0) gives its own `(kL, kC, dh)` per swatch.

**The blend:** the client mixes them by inverse squared distance in OKLab between the tag and each anchor's `ref`:

- **Weights:** `w_i = 1 / (ΔE_i² + 1e-4)`.
- **Ratios and hue offsets:** arithmetic means weighted by `w_i`.
- **A tag within ΔE 0.001 of an anchor's `ref`** draws that anchor's own swatches, exactly. Its ratios alone wouldn't give them back when the reference is near grey, since such a reference has no hue to offset from.

**Why distance, not lightness alone:** grey hair and blond hair sit at similar lightness and must not borrow each other's chroma. The blend is continuous, so two people with nearly the same hair never jump between palettes. Per-tag swatch tables are the special case where every colour in use is an anchor.

### Worked example: Cora's palette on two hair colours

**The reference:** Cora's accepted hair swatches (`docs/char-live-3/ink-batch-2/own-cora-live.glb`, `M00_000_Hair_00_HAIR`) as the profile at `ref` = auburn `#662e1a` = (102, 46, 26), whose OKLCh is (0.3737, 0.0867, 39.79°).

| Swatch | sRGB at `ref` | OKLCh | kL | kC | dh |
|---|---|---|---|---|---|
| shade | (44, 8, 2) | (0.1994, 0.0618, 35.30°) | 0.5337 | 0.7131 | −4.50° |
| mid | (104, 37, 8) | (0.3607, 0.1035, 40.62°) | 0.9654 | 1.1932 | +0.83° |
| light | (119, 43, 6) | (0.3960, 0.1153, 41.60°) | 1.0597 | 1.3291 | +1.81° |
| highlight | (135, 47, 3) | (0.4294, 0.1296, 41.09°) | 1.1493 | 1.4948 | +1.30° |
| ink | (4, 0, 0) | (0.0670, 0.0275, 29.23°) | 0.1793 | 0.3170 | −10.56° |

**Applied to two of `HAIR_COLOURS`:**

| Swatch | **Black** `#131111` (0.1800, 0.0033, 17.46°) | **Blond** `#9e7d47` (0.6095, 0.0826, 78.55°) |
|---|---|---|
| shade | (3, 3, 3) | (70, 47, 12) |
| mid | (18, 16, 16) | (156, 117, 48) |
| light | (22, 19, 19) | (176, 134, 53) |
| highlight | (26, 23, 23) | (199, 149, 55) |
| ink | (0, 0, 0) | (9, 3, 0): out of gamut at C 0.0262, reduced to 0.0240 |

- **What this shows:** at the reference the swatches come back byte for byte. Black stays neutral and keeps three distinguishable steps. Blond keeps the auburn palette's band contrast and warmth around its own hue.
- **What it does not settle:** whether those steps are *right* for black and blond is a calibration question. Black hair's shade at (3, 3, 3) is darker than the drawing style may want. S5 calibrates per colour bin and adds anchors where a bin misses its targets; that is what `anchors` is for.
- **Grey** `#858585` gives (53, 53, 53), (127, 127, 127), (144, 144, 144), (161, 161, 161) and ink (4, 4, 4): neutral, as it must be.
- **The check:** phase 2 tests the client's and the audit's implementations against this table.

### How the client draws it

- **Palette entries per material:** each profile material whose `palette` is `"tag"` (and each material whose `slop.ink` has `ref`) owns a 256×5 RGBA8 **palette image**:
  - **Columns:** one per entry, at most 256.
  - **Rows:** shade, mid, light, highlight, ink.
  - **Binding:** it sits in binding 105 (`ToonExt::tints`), which only composed hair uses today, for `HairTints`. Profile hair doesn't need `HairTints`, because greying goes through entries. So there is no new binding.
- **Tags:**
  - **The palette tag form:** `characters.rs` `recolor` gives such a mesh this tag:

    ```
    natural entry | silver entry << 8 | grey << 16 | 1 << 24 | 1 << 27      (bit 25 clear)
    ```

  - **Without greying:** silver = natural, and grey = 0.
  - **Bit 27 is new.** Bit 24 set with bit 25 clear already means "a character's colour", so plants (bit 25) never read it.
  - **The source colour:** entries are computed from the tag colour the name rule gives (`colors.hair`, `colors.beard`), or from `hair_natural`/`hair_silver` for greying hair.
- **Capacity:** a material's image holds 256 entries, against at most 9 natural colours and a few dozen silvers in a town. A colour that finds no room takes the nearest existing entry by OKLab distance, with one warning.
- **The shader:**
  - **Where:** `hand_hair` reads the four swatches, and the ink, from the palette image when bit 27 is set. With greying, that is 8 or 10 loads (`textureLoad`, no filtering).
  - **Without the bit:** it reads `toon.hand` as in v1.
  - **The base colour:** `recolor` leaves the albedo as it is under a palette tag, since profile hair ignores the albedo's RGB.
  - **A relative `slop.ink`** reads row 4 of its entry in the same way.

## The shared pages

**Decision (2026-11-20, the GC and dev-box):** composed people's hair masks are on **one shared hair-mask page**, and their ink carriers' maps are on **one shared ink page**. That keeps profile hair one material and gives two carrier materials (lid and brow) for everyone, which the crowd's cost limit needs ([cost plan](#cost-plan)). Both pages follow one rule.

**The rule: a file's UV0 is already in page coordinates.** The generator lays each file's islands into the cells assigned to it and writes the file's TEXCOORD_0 there. Every file of a page then names the same page with the same profile, so:

- **The client addresses no cell.** A mesh samples the page with its own UV0. There is no UV transform, no per-mesh tag for it, no new lookup and no material split.
- **The assignment is recorded for the tools, not the client:** a JSON manifest beside the page, which the audit and the bundle check read.
- **One page is one material.** Files whose profiles differ can't share a page: a second page (`…-1`) is a second material.

### The hair-mask page

| | |
|---|---|
| **File** | `lookdev/styles/hair/hair-masks.png` and its `.ktx2` copy; further pages `hair-masks-1.png`, … |
| **Content** | HANDMADE_HAIR's mask texture: **R** the highlight (v1; generated cuts also draw the parting there, a pale strip), **G** the lock-ink distance field (v1.1), **B** the strands when the profile's `strands` is on (v1.3.1, below), else 0, A 255. RGB, linear, with mips in KTX2 (class `hairmask`). |
| **The strands (B, v1.3.1)** | **With `slop.hair.strands` true:** the client multiplies the three bands (not the highlight, not the ink) by `2 · B`, so **0.5 (128) is neutral**. The generator writes 128 in every texel of B that has no strands, cell padding included, so filtering and mips never read an island's edge as dark. Recommended range: about **0.35–0.65**, a low contrast of the bands × 0.7–1.3. The generator bakes main's strand picture, times main's per-vertex shading, at 0.9 of its contrast, clamped to that range. **With it false, or absent:** B is ignored, so v1.1 and v1.2 `.hair.png` files and v1.3 pages draw exactly as before. There is no threshold on B. Shader: `level *= select(1.0, 2.0 * tex.b, strands)`, the flag packed in `hand[0].w`. The audit reports a non-boolean `strands`, and a strand page with any B texel at 0, as errors. |
| **Size** | 4096 × 4096 texels. |
| **Cells** | A grid of 512 × 512-texel cells, 8 × 8, numbered `[col, row]` from the top-left (glTF's UV origin). |
| **What a file takes** | A rectangle of whole cells, `[col, row, w, h]`. A short cut takes 1 × 1; a long cut or a plait may take 2 × 1, 1 × 2 or 2 × 2. |
| **Packing** | Files in sorted path order, each placed at the first free position scanning rows top to bottom, then columns left to right, where its rectangle fits. The result depends only on the file list and the sizes, so a rebuild with the same cuts gives the same page. |
| **Islands in a cell** | Each lock (or lock group) is its own island (plan §3.1). Islands keep at least `2 · ink_range · 4096 + 8` texels apart, and at least 8 texels from the rectangle's edge. Line texels (G = 0) keep at least `ink_range` from their island's border (v1.2's padding). |
| **Texel density** | **1.0 mm a texel** at rest, on the cut's own figure, so **`ink_m_uv` = 4.096** (m per UV unit) on every cut. Islands are scaled to it, never up for resolution. The audit warns when fewer than 90% of a cut's triangles lie within 25% of it, as for `"uv"` ink. |
| **Far meshes** | A file's `FarHair` takes UVs inside the same rectangle. It may overlap the near mesh's islands, since the two never show together. |
| **The profile** | Every cut on a page carries the **same `slop.hair`** object: palette, `ref`, anchors, swatches, thresholds, ink fields, `ink_m_uv` 4.096 and `highlight_map` = the page's path. |
| **The material** | Profile hair on a page has **no `baseColorTexture`**: the strand picture would be read through page UVs, and a profile ignores the base colour's RGB anyway. Alpha comes from `baseColorFactor`. |
| **Manifest** | `lookdev/styles/hair/hair-masks.json`: `{"page": "lookdev/styles/hair/hair-masks.png", "size": 4096, "cell": 512, "density_mm": 1.0, "files": {"bob.glb": [0, 0, 1, 1], "long.glb": [1, 0, 2, 2], …}}`. Written by the generator (S5); read by `calibrate.py` and `pictures.py check`. |

**Capacity:** 64 cells. Main's hair folder has about 45 cut files, most 1 × 1, so one page holds them. A cut whose islands don't fit 2 × 2 cells at 1 mm a texel is over the hair budget (plan §3: 12,000 triangles) and goes back to the generator, not onto a bigger rectangle.

### The ink page

| | |
|---|---|
| **Files** | `lookdev/types/types.<slot>.ink.png` and its `.ktx2` copy, one page per slot that carries ink. Today that is `types.eyes.ink.png`, for the lid and brow carriers. |
| **Content** | HANDMADE_INK's ink map: **G** the distance, **R** the width, B 0. RGB, linear, with mips in KTX2 (class `ink`). |
| **Size** | 4096 × 4096 texels. |
| **Cells** | A grid of 1024 × 1024-texel cells, 4 × 4, numbered `[col, row]` from the top-left. **One cell a class**, in this fixed order: `child-u` [0, 0], `youth-f` [1, 0], `youth-m` [2, 0], `adult-f` [3, 0], `adult-m` [0, 1], `elder-f` [1, 1], `elder-m` [2, 1]. Cells from [3, 1] onward are free for hero types and new classes, assigned in the manifest. |
| **A class** | An age-sex group of types: the type id up to its last `-` (`adult-f-b` → `adult-f`). All three lines of a class draw from their class's cell. |
| **Islands in a cell** | The class's carriers (lid, lash flicks, lower lid, brow, left and right) as islands, laid out by their own lengths (v1.2: near-isometric). Padding as v1.2: strokes at least `range` from an island's border, and islands at least `2 · range · 4096 + 8` texels apart. |
| **Texel density** | **0.25 mm a texel** at rest, so **`m_uv` = 1.024** on every carrier. A class whose faces are smaller (a child) keeps the same density; its islands are just smaller. |
| **The profiles** | Each carrier kind carries the **same `ink`** object on every type: the lid carrier one, the brow carrier another (`map` = the page's path, `m_uv` 1.024, one `range`, `width`, `min_px`, `fade_px` and `color`, plus `ref` on the brow). The lid and brow are therefore **two materials** for every person in the town. |
| **Manifest** | `lookdev/types/types.ink.json`: `{"pages": {"eyes": "lookdev/types/types.eyes.ink.png"}, "size": 4096, "cell": 1024, "density_mm": 0.25, "classes": {"child-u": [0, 0], …}, "types": {"hero-3f9a0c21": [3, 1]}}`. Written by the generator (S4); read by `calibrate.py` and `pictures.py check`. |

**The class maps become cells of the page.** There are no `<class>.<slot>.ink.png` files and no class lookup:

- **Map resolution** stays v1.2's: `ink.map`, then `<file stem>.<slot>.ink.png` beside the file.
- **Generated type files** always name the page with `ink.map`.
- **A hero type** either names the page (its cell assigned under `types` in the manifest) or brings its own `<stem>.<slot>.ink.png`, which costs it its own material.

**If S4 finds 0.25 mm too coarse** (plan §2.6 left 1024² against 2048² per class open): the cell becomes 2048 at 0.125 mm on two 4096 pages (4 classes each). That gives two lid and two brow materials, which is still a fixed count, and the manifest records it.

**The UV requirement:**

- **Within a type:** the people of one type already share one layout. They share the type's mesh, identity bones move only vertices, and Bevy doesn't morph UVs.
- **Across a class's types:** the inked primitives must have the same TEXCOORD_0: the same vertex count and order, and UVs within half a texel of the page.
- **How the generator gets it:** carriers are built from cage-relative strokes on a shared topology and pinned by island (plan §2.6).
- **Texel density:** each type's measured `m_uv` must be within 10% of the declared 1.024.
- **Only carriers.** An inked material on a type file must be a carrier (BLEND, base alpha 0, no texture), since its UV0 lives on the page and not in the face atlas. The materials `share.py types` pages (the far head's picture and the lip layer's) must not carry ink, because their UVs are moved per type.

**Binding and drawing:** `lookdev::convert` (a type file is the character's scene) loads the page into binding 106 and applies the ink with the declared `m_uv`. Morphs, draw order and blending are v1.2's: carriers are primitives of the face mesh, they morph with it, they take `CARRIER_SORT_BIAS` and they get no outline volume.

**Fallback:** a page that isn't found leaves its carriers without ink, with one warning, as v1.2. With ink on, S4 removes the old lid band and brow strip, so a missing page would leave everyone without lids. **The bundle check refuses that case** ([bundles](#bundles)).

## Heroes

**Adopted from dev-box's proposal** (plan §2.10 on `char-port-2`, d5369a9b1), with the amendments below.

**The model:**
- **Build time:** a world seed names at most 8 heroes in `looks.heroes`, each with optional `hero_file`, `bands` and `override` (`type`, `paint` and `hair`, validated as errors at seed check). The generator resolves `override` into a **hero type file** and a **hero hair style file**, and writes the hero's look lines. Those lines name the hero type and hair style, and they carry `hero_file` for the bands it covers.
- **Draw time:** the client applies no overrides of its own. A hero type or style is just another file. So the only new line field the client reads is `hero_file`.

### `hero_file` (a look-line field)

```json
{ "type": "hero-3f9a0c21", "height": 1.64, "colors": {"hair": "#8a3b1f", "…": "…"},
  "styles": {"hair": "hero-3f9a0c21", "outfit": ["…"], "overlays": []},
  "hero_file": "lookdev/heroes/hero-3f9a0c21.glb" }
```

| Aspect | Rule |
|---|---|
| **The value** | A path under `living/game/assets/`, which **must** match `lookdev/heroes/<id>.glb`. Its sidecars (`.face.png`, `.hair.png`, `<slot>.ink.png`, `.calibration.json`) sit beside it, per v1 and v1.2. |
| **The key** | `hero_file` joins the canonical drawn fields (`look_lines.py` `DRAWN`). It enters the hash only when present, so every existing key stands. |
| **When it is used** | Only with composing on (`LIVING_GAME_COMPOSE` not `0`), and only when the file exists and its scene declares `"character": "handmade"` with `contract` ≤ 1. The line is then drawn as that whole file: the recipe's `base` is the file, and there is no person line, as a hand-made recipe is drawn today. |
| **Height** | The line's `height` sets the figure's height, so a hero stands as tall as their words and the authority say. |
| **What it ignores** | `proportions`, `identity`, `colors`, `styles`, `belly` and `grey` don't apply to the whole file. A hand-made file's palette is absolute, and the file has no tag. |
| **Its own contract** | It is a hand-made file, so v1–v1.2 apply to it unchanged: the forward turn, slots, its profiles and its ink. |
| **Precedence** | `hero_file`, then the composed line (its `type` and `styles`, which a hero line still carries), then the recipe's own `base` (today's VRoid fallback). |

**Failure fallbacks.** Each case warns once per key; the client never draws nothing where the line can be composed.

| Case | Drawn as |
|---|---|
| `hero_file` isn't under `lookdev/heroes/` or doesn't end in `.glb` | The composed line |
| The file is missing on disk | The composed line |
| The file doesn't declare a hand-made character this client reads (no `slop.character`, another value, or a higher `contract`) | The composed line |
| The hero type or style file is missing too | Today's rule: the recipe's base, with one warning |
| The file passed the check but fails to load in Bevy | As any failed base file today: the character is missing, and the load error is logged |

### The amendments to dev-box's §2.10

These need dev-box's agreement:

1. **Opaque hero ids, not slugs.**
   - **The problem:** `hero-<slug>` type and style names, and `characters/heroes/own-cora-live.glb`, ship in the client book and the bundle. They would put a resident's name in both, which LOOK.md §5 rules out ("No book entry carries a name").
   - **The proposal:** `<id>` = `hero-` + the first 8 hex digits of SHA-256 over `"<world seed's look generation>|<resident name>"`. The seed's `heroes` block keeps the name; only the seed maps the name to the id.
2. **`lookdev/heroes/`, not `characters/heroes/`.** Hero files then live with the other drawn files, and the bundle step (`pictures.py`, which works under `lookdev/`), `MANIFEST.txt` and `share.py` see them.
3. **Per-character render values ride in the hero's own files.**
   - **Values:** palette swatches, ink colour, ink width and ink fade.
   - **Where:** in the hero type's and hero hair style's `slop`, for example a `"fixed"` palette or the hero's own anchor, and the hero carriers' own `ink` values.
   - **Instead of:** a line-level override block. The laptop's first sketch had `override: {hair: {…}, ink: [{material | slot, color, px, min_px, fade_px}]}` on the line, read by the client.
   - **Why the change:** dev-box's build-time route already makes a hero their own files, so the client-side block would duplicate it. Dropping it keeps the client free of per-person override logic and leaves the shipped line shape at one new field.
   - **If dev-box needs it after all:** for example, a hero who shares a generated type and differs only in colour. That sketch is the shape to restore.
4. **Band coverage isn't checked client-side** (dev-box's question 4).
   - **Why:** the client draws whatever a line says, and a line without `hero_file` composes. Coverage is a generator and seed-check property (`look_lines.py`, `town.py`).
   - **What the client does check:** the file and its declaration (above).
   - **dev-box's questions 1 and 3:** agreed. `hero_file` is canonical and drawn instead of composing, and the cap is 8 entries.

**Cost of a hero:**
- **Materials:** a hero type and a hero hair style are a few materials of their own: the face, the carriers and the hair.
- **A hero file:** about Cora's 49,702 triangles and her own materials, only where they're seen.
- **At the cap:** with 8 heroes in view, that is at most 8 × (about 6) materials.

## Bundles

dev-box's composed bundles (`char-4-composed-<sha>.tar.gz` and its `-ktx2` twin, [CHARACTERS.md § Pictures as KTX2](CHARACTERS.md#pictures-as-ktx2)) carry:

| File | Where | KTX2 class |
|---|---|---|
| The ink page and its manifest | `lookdev/types/types.<slot>.ink.png`, `lookdev/types/types.ink.json` | New class `ink`: **linear**, full mips (`"colour": "linear", "mips": "box"`), RGB kept |
| The hair-mask page and its manifest | `lookdev/styles/hair/hair-masks.png` (and `-1`, …), `lookdev/styles/hair/hair-masks.json` | New class `hairmask`: linear, full mips |
| Hero files | `lookdev/heroes/<id>.glb`, with its sidecars | Its own files, under the existing classes (`face`, and the two above) |
| The book | `characters/looks.json`, its lines carrying `hero_file` | (not a picture) |

**`MANIFEST.txt`** lists each file with its sha256, as it lists everything else.

**What `pictures.py check` adds:**
- For every composed file whose scene opts in, each inked material resolves an ink map **inside the bundle**, by the order above. Each profile hair that names a mask finds it.
- `ink` and `hairmask` pictures are KTX2 linear with a full chain, and no converted PNG is left behind. `handmade::has_green` treats a KTX2 without its PNG as a colour map, so maps are never encoded from greyscale.
- Every line's `hero_file` exists in the bundle, and its scene declares a hand-made character.
- Every file a page manifest lists exists and opts in, and its UV0 lies inside its rectangle or cell (within half a texel). Every opted-in file that names a page is in its manifest. A missing page is the "no lids" case above, which fails the bundle.

**`share.py`:**
- `types` and `pages` must keep a material's `slop` extras when they rewrite `extras` (`face_map` is merged into the object, never replacing it).
- `strands` must leave a profile hair's own UVs alone.
- None of them pages `.ink` or `.hair` pictures: they are sidecars, never embedded.

## Compatibility

- **Composed people without these fields render exactly as today.**
  - **Why:** without the scene's `slop`, no material `slop` is read, and the content keys and the mesh packing are today's.
  - **The proof (phase 2):** pixel comparison against the base client, as the v1 and v1.2 proofs did:
    - a composed person (`look:` key) at three-quarter and Near;
    - a VRoid base;
    - scenery;
    - Cora's accepted file.
- **Hand-made files behave as under v1.2.**
  - **Unchanged:** `"fixed"` is the default, a whole file has no tag in practice, and `ink.m_uv` and `hair.ink_m_uv` are optional.
  - **One change, confined to opted-in files:** `palette: "tag"` on a hand-made file whose meshes do carry a tag (a recipe with `colors.hair`) follows the tag. A v1.2 file can't have it.
- **Lines:** existing lines and keys are unchanged. Only hero lines carry `hero_file`.
- **Older clients:** an older client ignores the scene key, the new fields and `hero_file`. It draws composed people as today and draws a hero line composed.

## The audit and tools

**`calibrate.py` (the contract audit; `--no-run`)** recognises an opted-in composed file by its scene (`contract`, no `character`), and checks:

- **The scene:** `contract` is 1 and there is no `character`. Material slots: a slot whose kind differs from the name rule's (for example `tint` on a `…_FACE` name) is a warning, since the name rule decides.
- **`palette`:**
  - **Errors:** the value; `ref` (three integers, OKLab L ≥ 0.05); anchors (at most 4, each complete; a 5th is an error); `strands` not a boolean.
  - **Warnings:** a clamp hit on `kL` or `kC`; |dh| > 30°.
  - **Facts:** the [entries](#the-maths) for the nine `HAIR_COLOURS`, two silvers and the anchors' refs, with any gamut-reduced swatch marked.
- **Ink:** v1.2's ink audit, plus:
  - the map's resolution, saying whether it was `ink.map` (a page) or the file's own sidecar;
  - the declared `m_uv` against the measured value (a warning beyond 10%);
  - `ref` on a material whose name takes no tag (a warning: `ref` does nothing there).
- **Hair:** the mask's resolution, `_RING` on profile hair (a warning: it's ignored), and a `FarHair` whose material lacks the near hair's `slop` (a warning).
- **`--pages lookdev`:** both pages against their manifests:
  - each listed file's inked or profile primitives lie in its cell or rectangle (an error), and no two files' rectangles overlap (an error);
  - every file on a page carries the same `ink` object per carrier name, or the same `slop.hair` (an error: it would split the material);
  - for each class: the same TEXCOORD_0 on the inked primitives across its types, by count and within half a texel (an error);
  - the density: each file's measured `m_uv` against the page's (a warning beyond 10%);
  - the page's line texels kept within the islands (v1.2's border check).
- **`--line LINE.json` or `--book looks.json`:** every `hero_file` is checked for its path rule, then audited as a hand-made file.

**The calibration frame on a composed person:**

```
calibrate.py --line LINE.json [--targets T.json]
```

- **How it draws the person:** it writes a one-line book with the line under its key and runs the view on `look:<key>` with `LIVING_GAME_LOOK_BOOK`.
- **Targets:** they work as in v1, by colour bin. A targets file names its bin's tag (`"tag": "#662e1a"`).
- **Suggestions:** a `"swatch"` suggestion names the swatch **at the anchor whose `ref` is that tag**.

**Shimmer:** `ink_shimmer.py look:<key>|--line LINE.json [--slot S]`.

- **The reference:** the same person through the client's measurement switch `LIVING_GAME_COMPOSED_SLOP`. Values:
  - `on`, the default;
  - `off`: composed files' `slop` is ignored, which is today's drawing;
  - `noink`: profiles stay and ink goes;
  - `noink:<slot>`: only that slot's ink goes.
- **Why a switch, not a temporary copy:** the hand-made path copies the file. A composed person is several shared files plus two shared pages, so a switch is simpler.
- **The rest is unchanged:** the stops, sequences, metric (pass at F_ink ≤ 1.5 × F_edge, `faded` rule) and folders are as they are.
- **Cost A/B:** the same switch serves it.

## Cost plan

**The limits** (approved; ink on, windowed, uncapped):

| Scene | Limit |
|---|---|
| 8 composed people at the Near stop | **+0.3 ms** |
| Cullet's 64 crowd | **+1.0 ms** |

**The A/B:** the same build and files, with `LIVING_GAME_COMPOSED_SLOP=off` against `on`. Frame time is the median over 10 s of steady frames, in alternating runs, three pairs each, as in HANDMADE_INK § Cost. `LIVING_GAME_PERF=diag` records materials, batch sets and texture bytes.

**Where the cost could come from, and how v1.3 keeps it down:**

| Source | Today | With v1.3 | How it is held |
|---|---|---|---|
| **Hair materials** | All composed hair cuts are **one** toon (one strand picture, one source mean; `SAME_SOURCE`). The 64 crowd's game camera shows 26 materials and 17 batch sets today (CHARACTERS.md, compose-client-2). | **One** profile hair toon a page: every cut names the same page with the same profile ([the hair-mask page](#the-hair-mask-page)). | Decided: one page. A second page would be a second material. |
| **Palette per person** | A recolour per fragment from the tag (hsv maths) | 4 `textureLoad`s (8 when greying, +1 or 2 for ink) per profile-hair fragment; entries made on the CPU once per (material, colour), in microseconds | It replaces `hair_light`'s ring maths and up to 8 strand samples (HANDMADE_HAIR § Cost: no measurable difference). No material is split per colour, since the colour rides in the tag. |
| **Carriers** | The lid band, lash cards and brow strip are primitives of the type's face, in shared materials (the brows are one material for every type) | Carriers replace them (S4): net draws about 0 per person. **Two** materials for everyone, the lid and the brow ([the ink page](#the-ink-page)). | Decided: one page. Lever left (plan §8.11): one material if the lid and brow share a colour. |
| **Ink sampling** | 0 | One read (binding 106) per carrier fragment. At Near the lines are faded but still read, as measured on hand-made files (+0.02 ms at most for 8) | — |
| **Texture memory** | — | Two 4096² pages, BC7 with mips: about 22 MB each, so about 45 MB, plus a 5 KB palette image per palette material. That is about a fifth of the people's 202 MiB of textures today (CHARACTERS.md). | KTX2 only in bundles. A page's empty cells cost memory, not reads. |

**How the composed material keys change:**

- **`Composer::toon`** (style files): the content key becomes `"{kind:?} {face_map:?} {base:?}"` + (only when the file opts in) ` {slop:?}`. Here `slop:?` covers:
  - the parsed profile, with `palette`, `ref` and anchors;
  - the resolved mask path;
  - the ink profile, with its declared `m_uv`;
  - the resolved ink map.

  A file without `slop` keeps exactly today's key and its `SAME_SOURCE` sharing. A profile material's source colour is irrelevant, since its colour comes from the palette, so profile materials share by content alone.
- **`lookdev::convert`** (type files): `by_content` already includes `{profile:?} {hair_map:?} {ink:?} {ink_map:?}`, and it now reads them for opted-in composed files too. The profile's `Debug` grows the new fields, so the key distinguishes `"tag"` from `"fixed"`, and the declared `m_uv` makes a class's carriers identical. `by_source` (the glTF material's id) stays valid: there is no per-person material on type files, because heroes have their own type files.
- **The palette image** is per material, made once with the material. Entries are added as people arrive. The bind group is refreshed when the image grows, as `HairTints.grown` does today.

**If a limit is missed:**
1. Merge the lid and brow materials.
2. Report the remainder with `diag` counts rather than trimming ink.

## Built (char-port-2-s3)

**Where it lives:** the client, the tools and the proof are on branch `char-port-2-s3`. The evidence is in the laptop worktree's `.local/char-port-2-s3/` and `.local/living/verify/ui-s3{cul,isl}/`. The verify-ui record is [2026-11-20-0641-char-port-2-s3](../.agents/skills/verify-ui/references/validation/2026-11-20-0641-char-port-2-s3.md).

**What differs from the text above, as built:**

- **Palettes are made by commands.**
  - **How:** `palette::register` and `tag_later` queue them; `Composer` (an observer) adds them directly. `Palettes` is made on first use and sits in no system's parameters.
  - **Why:** registering it when the app was built shifted every later component id. That reordered which mesh a type's shared `Body_00_SKIN` takes its recolour source from (`recolor` takes the first mesh's vertex mean, an order dependence that is on main), and people without `slop` drew up to 31 levels differently on the neck.
- **`noink`** drops a profile's v1.1 lock ink as well as `slop.ink`.
- **Two measurement switches beside `LIVING_GAME_COMPOSED_SLOP`:**
  - `LIVING_GAME_VSYNC=0|immediate|mailbox` (main.rs): a windowed run presents without vsync and updates without focus (Bevy's game settings run an unfocused window at 60 Hz);
  - `live_crowd.py --settings` seeds a camera's stops, since a window without focus takes no zoom.

**The stand-in files:** `living/tools/characters/composed_fixture.py` makes an opted-in copy of a lookdev tree until S4 and S5 write the real files. It differs from the contract in three ways, which the audit reports:

- **Carrier topology:** carriers are copies of today's eyeline and brow primitives (lifted 0.3 mm). Today's types don't share topology across a class's lines, so each type takes a quadrant of its class's cell, and `calibrate.py --pages` fails the class check, as it should.
- **Densities:** 0.5 mm a texel for ink, since a whole eyeline with its lash cards is about 210 mm across, and 2 mm for hair, since a cylindrical projection isn't S5's packed lock islands.
- **The 64 cells:** main's bundle has 74 hair files but 64 distinct hair meshes, and files with identical hair share a cell. That exactly fills the 8 × 8 page.

**The proof** (laptop, Apple M4 Pro, Metal):

- **Pixel identity:** main's client (`715aeb1ca`, built in its own worktree, since the asset root is compiled in) against the branch's, on main's files. 0 pixels differ on every shot:
  - two composed people at three-quarter and Near;
  - a VRoid base;
  - scenery;
  - Cora's hand-made file at four shots.
- **Palette:** auburn, black, dark brown, blond, grey and a greying elder.
  - **Dark anchor:** it lifts black and dark-brown hair from near black to readable greys.
  - **The worked example:** `palette.py --self-test` and the client's unit tests reproduce it.
- **Hero:** a line with `hero_file` draws Cora's file at the line's height. A line naming `characters/heroes/…` warns once and is composed.
- **Shimmer** (`ink_shimmer.py look:<key>`, pass ≤ 1.5):
  - **eyes:** faded at all three stops; portrait 1.42 and 1.39;
  - **hair:** Near 0.40 and 0.43; Middle and Far faded; portrait 0.43 and 0.40.
- **Cost** (windowed, uncapped, alternating; `on` the opted-in files, `main` main's files on the same client):
  - **8 near** (live, the Cullet arrival at the Near stop, the cap's 8 full models): +0.055 ms mean over 3 pairs (+0.078, +0.073, +0.013), limit +0.3.
  - **The 64 crowd** (meadow, game camera): −0.08 ms (−0.188, +0.007, −0.059), limit +1.0. On full models (`LIVING_GAME_FAR=1000`): medians 6.02 against 5.83 ms, paired mean −0.22, noisy.
  - **Against `off`** (the same files with `slop` ignored), `on` is 0.2–0.5 ms faster: a profile skips the ring and strand samples.
- **verify-ui:**
  - `looks` 14/14 (Cullet, everyone opted in);
  - `hair` 11/11 on the opted-in files and 11/11 on main's (a profile ignores the shines, so the second run is the shine's evidence);
  - `camera-lod` 23/23.
- **Tests:**
  - `living-game`: 195 passed;
  - `living-rules ui::`: 38 passed (the skill-name guard).

**Not yet covered:**

- S4's and S5's real files;
- a bundle's KTX2 pages (`pictures.py check`'s new checks ran on the fixture tree);
- a live scenario for ink or palette;
- a hero in a live world.

## Sources in the code

| What | Where |
|---|---|
| The reader | `handmade.rs`: `hair_of` and `ink_of` read `palette`, `ref`, `anchors`, `ink_m_uv` and `m_uv`; `composed_of`, `composed_scene` and `composed_material` read a composed file's scene and materials; `ComposedSlop` is the switch. `ink_map` is unchanged: the pages are named by `ink.map` and `highlight_map`. |
| The palette maths, entries and images | `characters/palette.rs` (OKLab, bisection, anchors, `Palettes`, `register`, `tag_later`, `tag`; unit tests against the worked example) and its Python mirror `living/tools/characters/palette.py` |
| Style materials | `compose.rs` `toon` (reads `slop` through `glb_json` by material name) and the `_HIGHLIGHT` packing |
| Type materials | `lookdev.rs` `convert` (composed files' `slop`) |
| Tags | `characters.rs` `recolor` (palette tags) |
| The shader | `toon.wesl` `hand_hair` and `recolor` (bit 27) |
| Heroes | `compose.rs` `prepare` and `characters/book.rs` (`hero_file`) |
| The book's canonical fields | `look_lines.py` `DRAWN` |
| Tools | `calibrate.py` with `composed_audit.py` (the composed audit and `--pages`), `ink_shimmer.py` (`look:<key>`), `pictures.py` (`ink`, `hairmask`, `composed_checks`), `live_crowd.py` (`--settings`, `--pre`), `composed_fixture.py` (the stand-in files); `share.py` needs no change (it merges `face_map` into extras, and pages no sidecars) |
