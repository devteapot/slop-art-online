# char-port-2 · S6 · Step 4: the profile checks on the master (in progress)

**The setup:**
- **The set:** the whole hair set, built with `SLOP_PORT=hair,masters`: 92 files, 4 pages, 214 cells of 256.
- **The client:** main's (`b8c88d3fe`).
- **The style:** `swept_braid` (cut 1, Cora's side).
- **The steps:** S5's tools and rules ([s5/README.md](../../s5/README.md)).

## Passed

**The audit:** 0 errors and 0 warnings ([audit.txt](audit.txt)).
- `calibrate.py --no-run`: 0 / 0 on all 92 files.
- `--pages lookdev`: 0 / 0 over the four pages (`hair-masks.png` to `hair-masks-3.png`), one profile each.

**The luma bins at Middle,** with S5's margins ([luma.json](luma.json), [rows.png](rows.png)). Mean hair luma at 12 m, 58°:

| | black | brown | chestnut | auburn | blond | grey | white |
|---|---|---|---|---|---|---|---|
| `swept_braid` | **68.9** | **82.1** | 94.4 | 100.0 | 176.4 | **177.7** | 208.4 |
| `braid` (S5) | 69.5 | 82.3 | 95.2 | 100.7 | 177.3 | 178.5 | 209.1 |
| main's `braid` | 68.7 | 80.1 | 90.0 | 98.4 | 154.2 | 159.6 | 193.1 |

Against main's `braid`:
- **Black:** +0.2 over main's black (allowed: ≤ 8).
- **Brown − black:** 13.2 (≥ 12).
- **Grey − brown:** 95.6 (≥ 40).
- **The order:** black < brown < chestnut < auburn.

All pass.

**Shimmer** at fade 2.0 ([shimmer/](shimmer/)). Every sequence passes (≤ 1.5); the lines are faded at the game's stops, as decided.

| | Near, Middle, Far | portrait pan | portrait zoom |
|---|---|---|---|
| auburn | faded | 0.16 | 0.23 |
| black | faded | 0.27 | 0.30 |
| blond | faded | 0.11 | 0.20 |
| grey | faded | 0.14 | 0.22 |

**Flag off:** ten styles byte-identical to main (the volume step's run, at the same code).

## Failed: the calibration check, and why (an S5 defect)

[calcheck-bins.json](calcheck-bins.json): `calibrate_bins.py --style swept_braid --rounds 0`.
- **Auburn:**
  - **highlight:** on target (186, 97, 64 against 187, 99, 63);
  - **shade, mid and light:** 7 to 13 levels dark in every channel. Mid is (139, 64, 38) against (152, 72, 43).
- **The dark and brown bins:** likewise dark.

**The cause: the strands' mean.**
- **How the strands work:** under contract v1.3.1 the strands multiply the shade, mid and light levels by 2B (128 neutral). The highlight band is not multiplied, which is why it alone is on target.
- **The bake isn't neutral on average:** S5's strand bake writes B with its mean anywhere from 125 to 164 depending on the style ([strand-means.json](strand-means.json)):
  - `bob` 152.5;
  - `long` 138.6;
  - main's `braid` 133.2;
  - `swept_braid` 129.8;
  - the extremes `kerchief` 125.4 and `swept` 163.9.
- **The calibration hides it:** S5 calibrated the shared palette on `bob`, whose strands lift its bands about 19%, so the palette is set about that much dark for a style with neutral strands. `bob` passes and the others don't, by up to ±15%.
- **It isn't specific to S6:** `swept_braid` is the first other style checked against the targets.

**The fix I'd propose** (S5's code, flag-on only):
1. Hold each style's written strand texels to a mean of 128, keeping their contrast.
2. Recalibrate the anchors and the profile on `bob`.
3. Re-run S5's luma margins and this check on `swept_braid`.

Waiting on the coordinator.

## Not yet

- The bundle (`bundle.py --port hair,ink`, PNG and KTX2) after the calibration.
- The full S6 package.
