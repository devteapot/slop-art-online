# char-port-2 · S7 · The landmark-row re-measure in the measuring view

**What this is.** Step 2 of the GC's ortho sequence (2026-11-21): the cheek row defined by facial landmarks, the same way on the drawing and the render, measured in the laptop's measuring view (`view-ortho` `a92d5551a`: `LIVING_GAME_VIEW_ORTHO=1`, level, orthographic, with `LIVING_GAME_VIEW_CLIP=bind`). The outline and ink are on, as in play.

- **The types:** the 21, built at the interim factor 1.0 (`.local/char-port-2/s7/n1`, at `43313767a`).
- **The hair:** `swept_braid`'s three S6 cuts, on adult-f-b.
- **Nothing was built for this, and no geometry changed.**

## 1. The row, by landmarks

**The rule:** the cheek row lies `ROW_FRACTION` = **0.2967** of the way from the eye line to the chin (`drawing_spread.cheek_at`, `rule="landmark"`).

**Where 0.2967 comes from:** it is the row the drawing's 1.751 was measured at. On review.jpg that row is 206, between eye line 169.7 and chin 292.

**How the old rule went wrong:** the row was set as 0.030 m under the eyes in head heights of Cora's head, with the head's height taken from the eye spacing by stage-1's ratio (0.30). On a generated head, whose eye spacing is 0.38 of its height, that rule put the row 41–44 mm under the eyes instead of 30. `rule="spacing"` keeps it, so S6b's numbers can be reproduced.

**The landmarks:**

| | Drawing | Render |
|---|---|---|
| Eye line | the irises' centroids (the drawing tool's, unchanged) | the same |
| Chin | the tip of the chin on the midline: its ink point, the centre run of skin at its narrowest between mouth and neck (unchanged) | the same tip. A render has no ink there (the lit face runs into the shaded neck as unbroken skin), so the chin is the lowest pixel, on the eyes' middle column, of a **chin-ID** frame ([chin_id.py](../chin_id.py): the skin in front of the irises in yellow). That is `measure3d.chin`'s own definition, seen in the picture. |

**Known answers** ([drawing_spread_selftest.py](../../s6/drawing_spread_selftest.py), 33 of 33):
- a face that narrows under the eyes, so the row's height matters;
- the drawing's chin;
- a render's chin-ID chin, in pure, shaded and the client's own yellow ((227, 217, 113): a first threshold missed it);
- a chin-ID frame with no chin stops the measure. The first run fell back silently to the drawing's chin search, which on a render lands in the neck: 22 mm low.

**Through the client** (the 21 types), the 2D chin and eye line land on the file's 3D chin and eye line through the view's scale within ±5 mm. They shift together, so the row's fraction holds.

**The drawing at the landmark row:**
- review.jpg 1.751 (unchanged, by construction); stage-1 1.715 (was 1.701 on the spacing rule).
- The hair band is unchanged (the chin didn't move): body over eyes 3.146, band 2.973–3.319.
- The drawing's hair body over its cheek is 1.816 (was 1.823). See [spread.json](../../s6/spread/spread.json).

## 2. The face, 21 types, factor 1.0

**2D** is the measuring view, bind, outline on, at the landmark row. **3D** is the type file cut at its own landmark row (its eyes, `measure3d.chin`, the same fraction), as the front view projects it: each side's reach stops at the ear's inner edge, as the ear-ID mask stops the 2D run. The whole cut also counts the head behind the ear, which the front view hides.

| Type | 2D | 3D, front view | 2D − 3D | 3D whole cut | 2D against the drawing's 1.751 |
|---|---|---|---|---|---|
| adult-f-a | 1.716 | 1.681 | +2.1% | 1.681 | −2.0% |
| adult-f-b | 1.788 | 1.780 | +0.4% | 1.780 | +2.1% |
| adult-f-c | 1.817 | 1.840 | −1.3% | 1.891 | +3.8% |
| adult-m-a | 1.769 | 1.779 | −0.6% | 1.795 | +1.0% |
| adult-m-b | 1.831 | 1.832 | −0.1% | 1.841 | +4.6% |
| adult-m-c | 1.865 | 1.880 | −0.8% | 1.906 | +6.5% |
| child-u-a | 1.816 | 1.835 | −1.0% | 1.838 | +3.7% |
| child-u-b | 1.864 | 1.847 | +0.9% | 1.847 | +6.5% |
| child-u-c | 1.938 | 1.917 | +1.1% | 2.080 | +10.7% |
| elder-f-a | 1.824 | 1.804 | +1.1% | 1.869 | +4.2% |
| elder-f-b | 1.876 | 1.853 | +1.2% | 2.035 | +7.1% |
| elder-f-c | 1.914 | 1.889 | +1.3% | 2.098 | +9.3% |
| elder-m-a | 1.759 | 1.765 | −0.3% | 1.772 | +0.5% |
| elder-m-b | 1.804 | 1.821 | −0.9% | 1.845 | +3.0% |
| elder-m-c | 1.850 | 1.859 | −0.5% | 1.900 | +5.7% |
| youth-f-a | 1.715 | 1.684 | +1.8% | 1.684 | −2.1% |
| youth-f-b | 1.790 | 1.768 | +1.2% | 1.768 | +2.2% |
| youth-f-c | 1.816 | 1.840 | −1.3% | 1.891 | +3.7% |
| youth-m-a | 1.756 | 1.776 | −1.1% | 1.791 | +0.3% |
| youth-m-b | 1.816 | 1.829 | −0.7% | 1.888 | +3.7% |
| youth-m-c | 1.869 | 1.878 | −0.5% | 1.905 | +6.7% |

| Class mean | 2D | 3D, front view | against 1.751 |
|---|---|---|---|
| adult-f | 1.774 | 1.767 | +1.3% |
| youth-f | 1.774 | 1.764 | +1.3% |
| elder-m | 1.804 | 1.815 | +3.0% |
| youth-m | 1.814 | 1.828 | +3.6% |
| adult-m | 1.822 | 1.830 | +4.0% |
| elder-f | 1.871 | 1.849 | +6.9% |
| child-u | 1.873 | 1.866 | +6.9% |

**2D against 3D: reconciled.** The median is −0.3%, the range −1.3% to +2.1%, and the mean absolute difference 0.97%.
- **What is left:** whole pixels (1 px is 0.5% of a 190 px face) and where the ear's ID edge falls against its cut.
- **The outline doesn't enter.** It lies outside the silhouette, and the run counts skin only, as the drawing's counts skin and stops at its own line.

**What the old "~7%" was:**
- **perspective:** 2–4%, the laptop's measure;
- **the row's height:** the spacing rule's 41–44 mm against the 3D's 30;
- **the whole 3D cut** counting the head behind the ear.

**Against the drawing at factor 1.0,** every class is at or wider than 1.751. The women's lines are closest (+1.3%), then the men (+3–4%), then the elder women and the children (+6.9%). Within a class the a/b/c spread is kept (about 0.1 a class).

## 3. `swept_braid`, the same landmark rule

Measured on adult-f-b (factor 1.0, the same as S6b's women), in the measuring view. The hair counts above the chin row (the chin-ID chin), and the cheek is at the landmark row, ears masked.

| Cut | Body over eyes (band 2.973–3.319) | Whole over eyes | Body over the ear-masked cheek (drawing 1.816) |
|---|---|---|---|
| `.1` | **2.998** (in) | 3.102 | 1.683 |
| `.2` | **3.009** (in) | 3.094 | 1.688 |
| `.3` | **2.971** (0.002 under) | 3.028 | 1.667 |

- **In the measuring view the cuts sit at the band's lower edge,** not 2–3.5% under it as in the perspective bind frames. Most of that gap was perspective magnifying the eyes.
- **Body over cheek** is 1.67–1.69 against the drawing's 1.816. That is because our cheek is wider for its eyes (§2), not because the hair is narrower.

## 4. Not covered

- **The drawing has no known-answer test of its own pose's pitch.** The drawing is a level elevation by its nature. `square.py` shows its yaw and roll are square.
- **The three re-tune inputs** (S6b's factors, the ears' 0.47 and `swept_braid`'s volume) are numbers here, not decisions: step 3 is the GC's.

**Evidence:**
- [face.json](face.json): every type, with 2D, the 3D cuts, the rows, the chins and eye lines in file metres, and the scale.
- [cuts.json](cuts.json): the three cuts.
- [rows.png](rows.png): adult-f-b, adult-m-a, child-u-a and elder-f-c with their landmark rows, and cut 1's spread.
- **Frames:** `.local/char-port-2/s7/ortho/run1/`.

**Run:** `.local/char-port-2/s7/ortho1.sh`, which uses [ortho_measure.py](../ortho_measure.py).
