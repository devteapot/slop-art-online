# char-port-2 · S6 · Step 4: the profile checks on the master, and S5's calibration corrected

**The setup:**
- **The set:** the whole hair set, built with `SLOP_PORT=hair,masters`: 92 files, 4 pages, 214 cells of 256.
- **The client:** main's (`b8c88d3fe`).
- **The steps:** S5's tools and rules ([s5/README.md](../../s5/README.md)), measured on six styles: `bob`, `long`, `braid`, `swept`, `swept_braid` and `short`.

## What step 4 found in S5, and the correction

**The defect:**
- **The calibration was off on most styles.** The first calibration check on `swept_braid` failed: its shade, mid and light bands were 7 to 13 levels dark, and its highlight was on target.
- **The cause is S5's strand bake.** The bake left each style's mean strand value (the page's B, by which the client multiplies those three bands ×2B, 128 neutral) anywhere from **125 to 164** depending on the style. `bob`, S5's only calibration style, was 152.
- **So S5's palette was tuned dark** for every style with weaker strands. Measuring one style is how it went unnoticed.

**The correction (S6 step 4):**
1. **The strands held at a neutral mean** (`hair_page.py`):
   - each style's written strand texels are shifted to a mean of 128, keeping their contrast;
   - all 92 now sit at **127.5–127.7**;
   - [strand-means.json](strand-means.json) lists each style's mean before and after.
2. **The audit checks it** (`composed_audit.py`): a style whose strands average more than 2 off 128 fails. On the old pages that check fails 88 of the 92 styles.
3. **The palette recalibrated on six styles together:**
   - `calibrate_bins.py` takes several styles, tunes to their mean, and passes only when each passes;
   - the palette is the joint run's first round ([six-styles.json](six-styles.json));
   - auburn's mid is (101, 34, 5), where S5's was (92, 30, 5).
4. **The rule (the GC's):**
   - **mid, light and highlight:** S5's rule, ±5 per channel (near-neutrals ±5 luma and a neutral swatch);
   - **the shade band: ±12.**

   **Why the shade band is held looser, on purpose, not as a waiver:** it is lit by the sky alone, and part of it lies in the hair's own cast shadow, under its outer layers. That shadow varies by about 10 levels with each style's geometry: `long` and `swept_braid` stayed 8–11 under in every round, and lifting them put `bob` and `swept` 6–7 over. The palette doesn't try to cancel a style's own self-shadowing.

[The S5 README](../../s5/README.md) carries a note that its calibration was `bob`-only and was corrected here.

## Calibration on six styles

[calibration-six.json](calibration-six.json)

| Style | Result | Mid-band pixels |
|---|---|---|
| `bob` | **pass** | 2,920 |
| `long` | **pass** | 4,599 |
| `braid` | **pass** | 1,321 |
| `swept` | **pass** | 1,161 |
| `short` | **pass** | 259 |
| `swept_braid` | **fails two mid bands** | 1,036 |

`swept_braid`'s two failing mid bands:
- **dark mid:** luma −5.7 against ±5; channels (−6, −5, −12);
- **brown mid:** −7 in blue against ±5; channels (−6, −4, −7).

**What causes `swept_braid`'s mid** (reported, not fixed): [swept-braid-midband.png](swept-braid-midband.png), the mid band in cyan.
- **Where it is:** its mid band is a thin strip at the sweep's hem at the far temple (128 px in the portrait, 907 in the three-quarter). There the hair mass shows just under the lifted sweep.
- **Why it's dark:** since the volume step, the sweep stands off the mass by up to 19 mm (`off`). So the mass under its hem lies in the sweep's own shadow, and on this style that sliver is the whole of the mid band.
- **The rest of the style is in band:** its auburn mid, and every light and highlight band, pass.
- **What would fix it,** if wanted later: a wider mid band on the sweep's own surface, or less stand-off at the hem. Neither is made here, and the mid band's tolerance is not widened.

## The rest of step 4

**The audit:** 0 errors and 0 warnings on all 92 files, and over the four pages ([audit.txt](audit.txt); and after the correction, with the strand-mean check: 0 errors).

**The luma bins at Middle** (S5's margins), each style beside main's own file of that style (main's `braid` for `swept_braid`), on the held strands. All six pass ([six-styles.json](six-styles.json) `luma`):

| Style | black − main's black (≤ 8) | brown − black (≥ 12) | grey − brown (≥ 40) | black < brown < chestnut < auburn |
|---|---|---|---|---|
| `bob` | +2.1 | 14.2 | 97.5 | yes |
| `long` | +2.4 | 13.1 | 94.1 | yes |
| `braid` | +1.2 | 13.8 | 96.0 | yes |
| `swept` | −0.6 | 14.3 | 93.8 | yes |
| `swept_braid` | +0.9 | 14.4 | 96.0 | yes |
| `short` | +3.6 | 13.7 | 97.6 | yes |

**Shimmer** at fade 2.0 on `swept_braid` ([shimmer/](shimmer/)). Every sequence passes (≤ 1.5); the lines are faded at the game's stops, as decided.

| | Near, Middle, Far | portrait pan | portrait zoom |
|---|---|---|---|
| auburn | faded | 0.16 | 0.23 |
| black | faded | 0.27 | 0.30 |
| blond | faded | 0.11 | 0.20 |
| grey | faded | 0.14 | 0.22 |

**Flag off:** ten styles byte-identical to main. Every change here is behind `SLOP_PORT=hair`.

## Not yet

- The bundle (`bundle.py --port hair,ink`, PNG and KTX2).
- The full S6 package.
