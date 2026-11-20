# char-port-2 · S5 · The hair profile from the generator

The generator now lays every hair style out for the handmade-hair profile on the shared hair-mask pages, behind a flag: `SLOP_PORT=hair`. A composed person's hair is then drawn by the profile: bands, a highlight, lock lines, a parting, and main's strands under the bands at low contrast. It takes one palette relative to the person's hair tag, with anchors for black, brown, blond and grey. With the flag off, nothing changes.

This follows the laptop's contract, [HANDMADE_COMPOSED.md](../../HANDMADE_COMPOSED.md) **v1.3.1** ("The hair-mask page", "The palette") and [HANDMADE_HAIR.md](../../HANDMADE_HAIR.md) v1.1. v1.3.1 holds the two amendments S5 needed: up to 4 anchors, and the `strands` flag. [Plan](../PLAN.md) §3, §7.

**Three passes:**
1. **The first** (`e73de3751`) built the profile output.
2. **The second** (`f0be41c37`) did the dark palette, the structure at play distance (B1 and B2 side by side; the GC took B2), the parting and the fringe's lines.
3. **The third** (this commit) set the line colour relative to the hair, took the band off light hair's hairline, made grey's shading neutral, and wrote the two amendments to the laptop's terms. [The third pass](#the-third-pass).

[Rows: every colour, S5 beside main](rows.png) · [Lines on light hair, before and now](lines.png) · [Before, now and main at Near and Middle](compare.png) · [The strands across a cell border](border.png) ([numbers](border.json)) · [Middle luma](luma.json) · [Lock-line close-ups](closeups.png) ([numbers](closeups.json)) · [Page 0](page0.png) · [bob's cells at 1:1](page-bob.png) · [Calibration](bins.json) ([check on the final build](bins-check.json)) · [Shimmer](shimmer/) · [Surface flicker](flicker.json) · [Audit](audit.txt)

![Rows](rows.png)

## The GC's decisions (2026-11-20)

1. **Capacity:** three pages at 1 mm a texel, no contract change.
2. **Lock lines:** close-up only, like Cora's face ink. Fading before Near is accepted.
3. **Parting:** added, as one more source of lines in the generator. Structure at play distance comes from the bands and the parting.

## The third pass

**Before** is the second pass (`f0be41c37`), **now** is this one. Every number here is on the final build.

### 1. Line colour: a darker shade of the hair's own

**The problem:** on blond, grey and white the lock lines were near-black strokes, (59, 45, 18), (41, 41, 41) and (55, 55, 53). They read as scratches on pale hair. The line colour was one ink, Cora's (4, 0, 0) at auburn, moved to each colour by the palette.

**The rule** (`hair_page.INK_RULE`, `line_ink`), on the profile and on every anchor, so the palette moves it between them like a swatch:
- the line is **the mid swatch's own colour**, its OKLab a and b, **at 0.65 times its lightness**;
- **and at least 0.12 below it** (the minimum contrast). On black hair, whose mid is near black (L 0.12), that holds the line at black.

| Mid swatch → line | auburn | black | brown | blond | grey | white (moved) | chestnut (moved) |
|---|---|---|---|---|---|---|---|
| mid | (92, 30, 5) | (6, 5, 5) | (39, 25, 15) | (151, 116, 52) | (118, 118, 118) | (175, 175, 172) | (59, 32, 16) |
| line | (56, 0, 0) | (0, 0, 0) | (11, 2, 0) | (91, 58, 0) | (63, 63, 63) | (90, 90, 88) | (25, 4, 0) |
| OKLab L, mid → line | 0.33 → 0.21 | 0.12 → 0 | 0.23 → 0.11 | 0.58 → 0.38 | 0.57 → 0.37 | | |

[lines.png](lines.png) shows black, blond, grey and white at portrait and three-quarter, before and now. The lines on blond are golden brown, on grey and white a mid grey, on black still black.

**Up close** (close-ups at zoom 0.36–0.10), the line darkens the pixel by:
- **42–52 levels on black** (unchanged: the minimum contrast holds);
- **58–77 on auburn,** where it was 68–86 with Cora's near-black ink.

### 2. The band at the hairline: the highlight, lowered on light hair

**Which it was:** rendered with the page's R zeroed (no highlight texture, no parting), and again with B at 128 (no strands), the band stayed both times. It is the **highlight band**, which the per-vertex `_HIGHLIGHT` also carries.

On light hair the highlight was near white and grey: blond's drew (223, 218, 211). Moved from the drawing by ratio and held under the lightness ceiling, it lost the hair's chroma and stood 0.07 above the light band. That read as a hairband.

**The fix** (`calibrate_bins.targets`): for bins whose light band is above the drawing's (light hair), the highlight target is **a small step over the bin's own light band** (the drawing's step at auburn, 0.04 in OKLab lightness), **in the light band's chroma**. Blond's highlight target is now (229, 194, 138) where it was near white. Dark and auburn hair keep their targets.

[compare.png](compare.png): blond and grey at Near and Middle, before, now and main. The white band is gone; the highlight reads as a lighter part of the hair.

### 3. Grey: neutral, fixed in the anchor

**Which it was:** with the grey anchor's swatches replaced by neutral ones of the same luminance, the shadow side at three-quarter went neutral. So the blue was **the anchor**, not the toon shade's fill. The anchor was (56, 61, 73) shade, (113, 119, 131) mid, and so on: the calibration had corrected it **channel by channel** toward a neutral target as seen in the calibration frame's warm 11:00 light. That pushed blue into the swatch, which showed wherever the light wasn't the frame's.

**The fix, for every anchor** (`calibrate_bins.py`; not grey alone):
- **Lightness** is tuned (all channels by the luminance's target / measured).
- **The size of its chroma** is tuned where the target has one (target chroma above 0.03).
- **Its hue is never tuned:** it stays the palette's own, Cora's swatches moved to the bin.
- **Near-neutral targets** (black, grey) keep the palette's neutral swatches.
- **Auburn,** Cora's own, is still calibrated channel by channel, as her calibration was.

The grey anchor is now (61, 61, 61), (118, 118, 118), (150, 150, 150), (193, 193, 193).

**The calibration check,** re-measured on the final build ([bins-check.json](bins-check.json)):

| Bin | shade | mid | light | highlight |
|---|---|---|---|---|
| auburn | (1, **15, 17**) | (0, 0, 2) | (0, 0, 2) | (0, 0, 3) |
| black | (1, 1, 0) | (5, 2, −7) | (2, 1, −6) | (5, −1, −9) |
| brown | (4, 2, 0) | (−1, 1, −2) | 0 | (−1, 1, −2) |
| blond | (4, −1, 2) | (1, 0, 1) | (0, 1, −1) | (−2, 2, 0) |
| grey | (5, −1, **−13**) | (6, −1, **−13**) | (6, 0, **−12**) | (6, 0, **−12**) |

- **Chromatic bins** are within ±5 per channel.
- **Auburn's shade** is the sky-floor exception, as before.
- **Black and grey** keep neutral swatches. Per channel they now show the scene's warm light: the screen is warmer than a neutral target, R up to +6 and B down to −13. That is the same warmth main's neutral grey has in the sun. Their luminance is within 2 levels (grey −0.6 to +0.4, black up to +2.0).

**I propose checking near-neutral bins by luminance (±8) and a neutral swatch, not per channel.** Holding ±8 per channel there means correcting the swatch toward blue, which is what made the shadow blue.

### 4. The contract: v1.3.1, the laptop's terms

**(a) 4 anchors, as written:**
- `handmade.rs` reads the profile's own plus 4, with its cap of 5 entries and its warning text.
- The audit reports a 5th anchor as an error.
- The contract says that a v1.3 client drops the 4th.
- The unit test is `strands_and_four_anchors`.

**(b) The strands are a material flag:**
- **The flag:** `slop.hair.strands` (boolean, default false, page-wide), in `hand[0].w`.
- **The shader:** `level *= select(1.0, 2.0 * tex.b, toon.hand[0].w > 0.5)`. The `B > 0.004` test is gone.
- **The generator:**
  - writes 128 in every texel of a strand page's B that has no strands, cell padding included;
  - keeps B in 0.35–0.65 (`STRANDS_RANGE`);
  - sets `strands: true` on every file of a page that has strands.
- **The audit** reports a non-boolean `strands`, and a strand page with any B texel at 0, as errors.
- **A bug the flag work found:** the second pass baked B with `max` over a page already filled with 0.5, so the strands could only lighten. B ran 128–196. It now fills 0.5 only where nothing was baked, and B runs 89–166 (mean 139–150).

**The proof:**

- **No dark fringe across a cell border** ([border.png](border.png), [border.json](border.json), [border_proof.py](border_proof.py)). A page holds bob with strands at cells [0, 0, 2, 1], beside short without them at [2, 0, 2, 1]. A woman in auburn wears each, at Far and Middle. The mean hair luma and the hair's rim luma, against the same page with `strands` off:

  | | bob, Far | bob, Middle | short, Far | short, Middle |
  |---|---|---|---|---|
  | `strands` on: hair / rim | +4.6 / +3.8 | +5.1 / +4.5 | **+0.1 / +0.1** | **+0.1 / +0.1** |
  | control (B 0 where no strands): hair / rim | +4.3 / +3.8 | +5.1 / +4.5 | −25.9 / −20.5 | −32.1 / −21.4 |

  - **The strand-less cut is unchanged** (128 multiplies by 1.004).
  - **The strand cut's rim moves with its hair, not darker.**
  - **The control shows the fringe the 128 fill prevents:** without it, the strand-less cut goes dark.
- **Shimmer on a strand cut at the three stops:** the lock lines fade before Near (the GC's decision), so the three stops have no ink to score. What can shimmer there is the strands, so they are measured as the surface's own flicker ([surface_flicker.py](surface_flicker.py), [flicker.json](flicker.json)). That is bob in auburn, `strands` on against off, and main:

  | F | Near pan | Near zoom | Middle pan | Middle zoom | Far pan | Far zoom |
  |---|---|---|---|---|---|---|
  | strands on | 0.0037 | 0.0162 | 0.0026 | 0.0132 | 0.0031 | 0.0129 |
  | strands off | 0.0034 | 0.0112 | 0.0032 | 0.0108 | 0.0029 | 0.0092 |
  | main | 0.0069 | 0.0321 | 0.0064 | 0.0301 | 0.0057 | 0.0279 |

  The strands add up to 0.005 to the zooms, and the result stays 2–2.5 times under main's flicker. The PNG page is read without mips; the game's KTX2 copy has them.
- **Main's files, flag off, under both clients:** main's bob in seven colours, drawn by main's client and by this one, measures the same hair luma at Middle to the decimal (black 66.9, brown 80.0, … white 196.6; [luma.json](luma.json), `main-old` against `main-new`).

## The second pass

### (a) The dark palette: black reads black, brown sits between

**The problem:** the first pass's dark anchor raised black's four bands to OKLab lightness 0.35–0.55, so black and brown hair read as grey at Near and Middle.

**Why brown needs its own anchor.** One anchor moves a swatch's lightness by the tag's ratio to its `ref`. Brown (51, 34, 23) is 1.8 times black's lightness. So with one dark anchor, a black that is readable put brown above auburn (first pass at Middle: brown 115, auburn 105, black 94). No single dark anchor gives both, so brown takes an anchor of its own.

**The change:**
- **Anchors:** black, brown, blond and grey. The contract allowed 3, which is the first amendment below.
- **Floors:** black's and brown's floors are lowered to what play distance needs (`calibrate_bins.py` `FLOOR`):
  - black: shade 0.30 (the sky floor), mid 0.31, light 0.345, highlight 0.44;
  - brown: 0.32, 0.39, 0.43, 0.47.
- **Up close,** the lock lines (ink, near black) and the highlight carry dark hair, not a lifted palette.

**Acceptance: mean hair luma at Middle** (12 m, 58°). The hair pixels are where the white row and the black row differ by more than 40 levels; the luma is 0.2126 R + 0.7152 G + 0.0722 B of the screen's sRGB. Source: [luma.json](luma.json), from `hair_rows.py luma`.

| Middle, mean hair luma | black | brown | chestnut | auburn | blond | grey | white |
|---|---|---|---|---|---|---|---|
| **S5, third pass (final)** | **70.0** | **84.5** | 98.3 | 104.2 | 182.0 | **183.4** | 213.0 |
| S5, second pass (B2) | 70.6 | 84.5 | 98.7 | 104.6 | 184.4 | 185.7 | 213.2 |
| B1, the other variant | 70.8 | 84.8 | 98.7 | 104.6 | 183.2 | 184.8 | 212.7 |
| S5, first pass | 94.2 | 115.1 | 106.1 | 104.8 | 184.0 | 185.6 | 215.5 |
| main | 66.9 | 80.0 | 91.0 | 100.2 | 157.0 | 162.5 | 196.6 |

On the final build:
- **Black is 70.0**, 3.1 levels above main's black (the margin allows 8).
- **Brown − black is 14.5** (≥ 12; main's is 13.1).
- **Grey − brown is 98.9** (≥ 40; main's is 82).
- **The order holds:** black < brown < chestnut < auburn. Black sits 113 below grey and brown 99 below, so black is further below grey than brown is.

The second pass met all four margins too (black 70.6, brown − black 13.9).

The first pass failed two of these: black was 27 above main's, and brown sat above auburn.

**The margin proposed, and why:**

- **Black ≤ main's black + 8.** Black reads as black as main's does. 8 levels is the calibration's own tolerance.
- **Brown − black ≥ 12.** That is main's own separation of the two at Middle (13), and about 0.04 in OKLab lightness at these levels. It is roughly three just-noticeable steps, so black and brown hair tell apart on a 240-pixel head.
- **Grey − brown ≥ 40.** Grey must read as grey-haired, not as light brown.
- **Black below brown,** so black sits further below grey than brown does. Brown also stays below chestnut and auburn.

**Calibration:** the second pass held every bin within ±4, with the anchors corrected channel by channel. The third pass changed that for the reasons in [3. Grey](#3-grey-neutral-fixed-in-the-anchor); its table is there.

### (b) Structure at play distance: B1 and B2, side by side

Both variants carry the parting (below) and the new lock lines. [compare.png](compare.png) shows black, brown, grey and blond at Near and Middle, B1 beside B2 beside main.

![B1, B2 and main](compare.png)

- **B1, band-structure variation** (`SLOP_HAIR_LOOK=b1`, `hair.Hair._lock_round`): each lock, a point of a sheet's hem from notch to notch, is shaded as a low cylinder. Its normals turn across it toward its sides, by up to 0.6 times the lock's own amount, more toward the hem. The bands' edges then break lock by lock.
- **B2, main's strands under the bands** (the default, `hair_page.strands_bake`): main's strand picture, at each vertex's own strand mapping, times main's per-vertex shading (root, notches, hem), is baked into the page's **B** at 0.9 of its contrast. The client multiplies the three bands (not the highlight or the ink) by 2 B. This is the second amendment, and it needs a client step: three lines in `toon.wesl` `hand_hair`.

**Shimmer, both under 1.5.** `hair_shimmer.py` on bob at fade 2.0; the lines fade before Near, so the game stops are faded and not scored.

| | portrait pan, auburn / black | portrait zoom, auburn / black |
|---|---|---|
| B1 | 0.23 / 0.38 | 0.21 / 0.24 |
| B2, the side-by-side (before B2's recalibration) | 0.79 / 0.33 | 0.21 / 0.21 |
| B2, the final build | 0.26 / 0.32 | 0.22 / 0.21 |

**The surface's own flicker** ([surface_flicker.py](surface_flicker.py), [flicker.json](flicker.json)). B2's strands are a texture, and the test reads the PNG page without mips (the game reads its KTX2 copy with mips). So I measured how much the hair's surface itself flickers in the game camera's pans and zooms. The figure is F, the second temporal difference over the luminance, on bob in auburn.

| F | Near pan | Near zoom | Middle pan | Middle zoom | Far pan | Far zoom |
|---|---|---|---|---|---|---|
| B1 | 0.0029 | 0.0109 | 0.0027 | 0.0072 | 0.0024 | 0.0104 |
| B2 | 0.0033 | 0.0139 | 0.0029 | 0.0105 | 0.0030 | 0.0111 |
| main | 0.0069 | 0.0321 | 0.0064 | 0.0298 | 0.0057 | 0.0279 |

**B2 is 10–45% above B1, and both are 2–3 times steadier than main.**

**Which reads better: B2.**
- **At portrait and three-quarter:** B2's hair reads as hair, with fine streaks along the locks in every band, as main's did, and the bands and lines on top. B1's lock-wise band breaks read as facets: blocks of light and dark on the side hair.
- **At Near:** B2 keeps a little of main's grain, and B1 is smooth with its band edges broken.
- **At Middle:** both are mostly the two bands and the highlight. B2 keeps a faint grain on the light hair, and B1 a broken lower edge.

Neither is as busy as main, whose speckle is also what flickers.

**The cost of B2:**
- **The client step:** `hand_hair` reads B in the tap it already makes, with a select and a multiply.
- **The contract:** B as strands, 0 meaning none.

B1 needs neither; `SLOP_HAIR_LOOK=b1` builds it again if the GC prefers it.

### The parting

Where the hair parts:
- **Over-sheet styles** (shag, bob, bob_parted, long): `Hair.over` records the line between the two sides' roots, from the front over the top to the crown, 84°–122° from the front.
- **Curtain fringes:** from 70°, where the fringe parts too.
- **Braids:** down the middle.

`hair_page.parting_strip` draws it into R, the highlight: a pale strip 10 mm wide tapering to its ends. It goes on whatever lies within 14 mm of the scalp along the line, which is the cap between the two sides and the sides' root edges. It shows in the lit band as the scalp does in a parting. Light-independent, it is the one structure that holds at every distance, with the band edges.

- **Coverage:** 57,780 texels over the 86 files.
- **Close-up:** the parting is the pale strip; it isn't drawn as ink.

### (c) The fringe's lock lines

**The first pass:** one line straight up each notch, all to 55% of the way. They read at portrait as two or three stiff vertical slits.

**Now** (`hair.Hair._lock_lines`, `LOCK_LINES`), grouped into locks, as the plait's "melon stripes" lesson asks:
- **Notch lines:** up each notch, a line 30–72% of the way to the root. It bends across by up to 1.3 columns (t²·², so it curves as the lock turns), and its length and bend are its own.
- **Companions:** beside half the notches, inside the lock, a shorter one (16–40%) starts 30–55% of the way to the point's tip and bends with its notch.
- **Edges:** never on a sheet's own edge columns, so a line keeps `ink_range` from its island's border.
- **Random numbers:** the lines have their own, so the hair's shape doesn't change.

The lines are bilinear on the sheet's grid, in page texels. There are 1,772 over the 86 files; the first pass had 868.

## What it builds

**[`hair.page_layout`](../../../living/tools/blender/hair.py)** lays out each style's hair at 1 mm a texel; `person.make_hair` calls it with the flag on.
- **Pieces:** each connected run of faces is its own UV island. The scalp's cap is laid out flat, from above; every other piece keeps its strand mapping, scaled to its own lengths.
- **Density:** each piece's median triangle is exactly 1 mm a texel.
- **Packing:** the smallest of 1×1, 2×1, 1×2 and 2×2 cells of 512 texels, with padding of 2 × `ink_range` + 8, skyline-packed and turned where needed.
- **The far mesh:** each `FarHair` piece takes the place of the near piece its vertices lie nearest to.

`person.make_hair` writes `<style>.hairpage.json`, holding the rectangle, the lock lines in texels and the parting, and the near mesh's `_HIGHLIGHT`. With B2 it also writes `_STRANDU`, `_STRANDV` and `_STRANDK`, which `hair_page.py` reads and removes.

**[`hair_page.py`](../../../living/tools/characters/hair_page.py)** puts the files on the pages, 190 cells on three pages.
- **The material:** it drops the texture and `_RING`, and takes the profile. The scene opts in.
- **The page:** R the highlight and the parting; G the lock lines' distance field over 6 texels; B the strands.
- **The manifest:** it writes `hair-masks.json`, which lists `pages`.

**The profile** (the same on every file of a page):

| | |
|---|---|
| `palette` | `"tag"`, `ref` auburn (102, 46, 26), Cora's hair |
| swatches at `ref` | shade (35, 1, 0), mid (92, 30, 5), light (108, 39, 4), highlight (138, 53, 3): calibrated with the strands under them |
| thresholds | `t1` −0.2, `t2` 0.4, `edge` 0.02, `highlight_feather` 0.08 (Cora's) |
| lock ink | `ink` (56, 0, 0) by the line rule (each anchor has its own), `ink_px` 1.05, `ink_fade_px` 2.0 (Cora's), `ink_range` 6/4096, `ink_m_uv` 4.096 |
| `anchors` | black (19, 17, 17), brown (51, 34, 23), blond (158, 125, 71), grey (133, 133, 133) |
| `strands` | true: the page's B is the strands (v1.3.1) |
| `highlight_map` | the file's page |

**The client** these renders use (`living-game-s5c`) is main's client with v1.3.1. Its build tree was deleted after the build. Its tests: `cargo test -p living-game handmade::` gives 18 of 18, including `strands_and_four_anchors`.

## Acceptance

### The audit: 0 / 0

[audit.txt](audit.txt). `calibrate.py --no-run` gives **0 errors and 0 warnings on all 86 files.** `--pages lookdev` is **0 / 0** over all three pages:
- every file opts in;
- one profile per page;
- every hair UV inside the file's cells;
- no overlap;
- density within 10%.

The audit now:
- reads a manifest's `pages`;
- allows 4 anchors and reports a 5th as an error;
- checks `strands` and a strand page's B.

### The rows

[rows.png](rows.png): bob on a composed woman, in black, brown, auburn, chestnut, blond, grey and white, at portrait, three-quarter, Near and Middle (12 m, 58°), S5 beside main. [hair_rows.py](hair_rows.py) draws it.

- **A 1–2 px dark dot on the crown at Near** is in main's geometry too: main draws it at the same pixel, and main's speckle hides it. S5 didn't cause it.
- **On white hair** the highlight is too close to the light band to show, since the ceiling holds both near the top.

### Lock lines up close at the 1 mm page

[closeups.py](closeups.py): bob in auburn and black, and long in auburn, with and without the hair's ink. Zooms 0.36, 0.18 and 0.10, each front and three-quarter. [closeups.png](closeups.png), [closeups.json](closeups.json).

| | lines (≥ 6 px) | width, median / p90 (px) | gaps | darkest |
|---|---|---|---|---|
| bob, auburn, 0.36 → 0.10 | 7–14 | 5–6 / 7–10 | 0 | 61–77 (one shot 136, likely a blink) |
| bob, black, 0.36 → 0.10 | 6–10 | 5 / 7–12 | 0 | 42–52 |
| long, auburn, 0.36 → 0.10 | 7–18 | 5.5–7 / 8–13 | 0 | 58–74 (one shot 148, likely a blink) |

- **The lines hold at the 1 mm page:** the same width in pixels across a 3.6× zoom, and no breaks.
- **More lines than the first pass's 3–6,** grouped. The wider p90 is likely where a companion runs close beside its notch line; I haven't traced it line by line.
- **On black hair the line darkens the pixel by 42–52 levels;** on auburn by 58–77, now that the line is a darker red-brown rather than near black. The line holds black on black hair (the rule's minimum contrast), which is what keeps black hair readable up close without lifting it.

### Shimmer at fade 2.0, on the final build

Shimmer on the final build: the third pass's line colours, strands and palette. The results are in [shimmer/](shimmer/); the `side-by-side-*` files are the second pass's variant runs.

| | Near, Middle, Far | portrait pan | portrait zoom |
|---|---|---|---|
| bob, auburn | faded | **0.19** (1356 px) | 0.21 (1380) |
| bob, black | faded | **0.68** (1009) | 0.16 (1022) |
| bob, blond | faded | **0.18** (1387) | 0.23 (1371) |
| bob, grey | faded | **0.21** (1341) | 0.27 (1368) |
| long, auburn | faded | **0.26** (2141) | 0.29 (2242) |

Every sequence passes (≤ 1.5). The lines are faded at the game stops, as the GC decided.

**The blink guard is now 10 px** (`ink_shimmer.GUARD`; it was 3). Bob in black first scored 3.84 on its portrait pan. All of that was one frame in which one render caught a blink: the eye's lighter pixels were left out, but the open eye's darker lashes and iris beside them were not. Re-scored from the same stills with the whole eye left out, it is 0.68. The others went down too (auburn 0.33 → 0.19, long 0.57 → 0.26), since part of their flicker had also been eye pixels the 3 px guard missed.

### Flag off: byte-identical

Ten styles were built with main's generator (`origin/main` at `d05d01b9f`, its `living/tools`) and with this branch without `SLOP_PORT`:
- bob, long.2.collar, braid.3.collar.full, braids, balding.3, crop.cap, bun, tail.m, kerchief and shag.2.

**Every GLB binary chunk is identical,** and the JSON is identical but for the strand picture's relative URI. No `.hairpage.json` is written without the flag. Main's own files also draw the same under the new client (above).

The `ink_shimmer.py` fixes from the first pass stay:
- the clock blink is left out;
- grey and black hair have their own region rule.

## Not covered

- **S7's work:** the four-body proof and the cost budget.
- **Hair masters in Cora's grammar** (§3's `swept_braid`): a later step.
- **The game's KTX2 path:** the pages are PNG here. The `hairmask` class converts them with mips, which only steadies the strands further.
