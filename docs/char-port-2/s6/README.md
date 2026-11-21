# char-port-2 · S6 · Hair masters: `swept_braid`

S6 ports Cora's hand-made hair into the generator as a **master**: a named set of parameters in the generator's own terms (`hair.MASTERS`), never a mesh. Everything is behind `SLOP_PORT=masters` (with `hair`). With the flag off, the generator writes exactly what main does.

**Steps:**
1. [Step 1](step1/README.md): the skeleton.
2. [Step 2](step2/README.md): Cora's front and the first full build.
3. [Step 3](step3/README.md): flyaways, the ears, cuts, lines and the fourth page.

**Since step 3:**
- [the mirror check](mirror/README.md);
- [the spread re-derived from the drawing](spread/spread.json).

## Status (2026-11-21): the S6 package

| Acceptance | Result | Where |
|---|---|---|
| Hair body over eye spacing (band 2.973–3.319) | cut 1 **3.119**, `.2` **3.135**, `.3` **3.077** | [volume/](volume/README.md) |
| Cheek measure (report only) | 1.615 / 1.622 / 1.593 (drawing 1.823) | [volume/](volume/README.md) |
| No flyaways (outline check, 4 px) | front 1.0, three-quarter 1.0, back 1.4 px | [volume/](volume/README.md) |
| Tips (front 10 ± 2, three-quarter 7–8) | 9 and 7 | [volume/tips.png](volume/tips.png) |
| The plait at play distance | width 7.18 / 4.70 px (drawn 7.4 / 4.6); luma 66.7 / 69.4 (drawn 69.1) | [volume/](volume/README.md) |
| The fit (9 female types × 3 cuts) | 0 collar contacts, root ≤ 0.906 mm, ears 3/3 | [volume/](volume/README.md) |
| Triangles (≤ 12,000) | ≤ 11,632 | [volume/](volume/README.md) |
| Calibration on six styles (mid, light, highlight ±5; shade ±12) | bob, long, braid, swept, short **pass**; **swept_braid's dark and brown mid fail** (−5.7 luma, −7 blue): the mass under the sweep's lifted hem, in its shadow (reported, not fixed) | [step4/](step4/README.md) |
| Luma bins at Middle (S5's margins), six styles | all pass | [step4/](step4/README.md) |
| Shimmer at the three stops | all pass; faded at Near, Middle, Far | [step4/](step4/README.md) |
| The audit | 0 / 0 on 92 files and four pages, strand means included | [step4/](step4/README.md) |
| Flag off | ten styles byte-identical to main | [volume/](volume/README.md) |
| The bundle (PNG and KTX2) | both pass every check | [step4/](step4/README.md) |
| The mirror | the generator's output an exact mirror; the client's own fault is the laptop's track | [mirror/](mirror/README.md) |

**Found and corrected on the way:**
- **S5's strands and calibration:** S5's strand bake and its `bob`-only calibration (step 4).
- **The ear opening:** the drawing shows the ears; the master had covered them.
- **The mirror:** the curl wave in the generator.

## Acceptance

### The spread: hair body over eye spacing (the GC's choice, 2026-11-21)

**The measure** ([drawing_spread.py](drawing_spread.py), [image_spread.py](image_spread.py)):
- **The hair's body** is its width above the chin, with every part narrower than the outline check's 15 px (scaled by head size) taken off. Curls and thin locks don't count.
- **The eye spacing** is iris centre to iris centre: the iris pieces, parted into two eyes at the widest gap across.
- **No face width enters it.**

**On the drawing:** Cora's front drawing, measured in its two copies:
- [review.jpg](../../char-live-2/hair/final/review.jpg) (the largest);
- [stage-1-targets.jpg](../../char-live-2/stage-1-targets.jpg).

**On a cut:** the game's front portrait, from main's client:
- the setup is a composed woman in auburn at `0:8:0.36:0.88`, 1600×900, 11:00, soft film, springs off;
- **the moment is 2.0 s into the idle clip**, when the head is square to the camera;
- **the hair** is the all-hair ID copy (`part_id.py --all`);
- **the eyes** come from the same frame drawn with no hair (`part_id.py --none`);
- each cut is measured on its own parting side.

**The band:** the drawing's value, ± 0.10/1.82 of it. That is the cheek measure's ±0.10 about 1.82, scaled in proportion.

| | Body / eye spacing |
|---|---|
| Drawing, review.jpg | 3.171 |
| Drawing, stage-1 targets | 3.121 |
| **Target (mean)** | **3.146** |
| **Band** | **2.973 – 3.319** |

### The cheek measure: reported, not held

`body` is the hair body over the face's width at the cheekbones. The cheekbones are the cheek row, 0.030 m under the eye line, scaled by head height from the eye spacing.
- **The face's width there** is its outline with nothing over it:
  - **on the drawing,** as drawn, since no hair covers the cheeks at that height;
  - **on a render,** the frame drawn with no hair. At this head's cheek row the ears join the outline; the generator's head has no line between ear and face.
- **The drawing:** 1.811 and 1.835 (mean 1.823).

**Why it isn't held:** our face is wider than the drawing's for its eyes. The cheek over the eye spacing is 1.93 on our front portrait, against the drawing's 1.75 and 1.70. A cheek-based spread would charge the face's width to the hair. The face-proportion pass ([S6b](../PLAN.md)) narrows the face toward 1.75; after it the two measures should agree.

### The rest of S6's acceptance

- **The silhouette, as a generator guard** on seeded variation (not the acceptance), measured in 3D (`Hair.measures`):
  - spread about the master's own, 2.006 ± 0.10. It was Cora's 3D 1.87 ± 0.10 until the volume step; this head's wide face takes the image acceptance to 2.0 in 3D;
  - crown lift 0.096 ± 0.035 (Cora's);
  - rear depth 0.53 ± 0.04 (Cora's).

  A cut out of these even unvaried stops the build.
- **No flyaways:** the outline check (`back_views.py outline`) holds front, three-quarter and back to 4 px.
- **Tips** (char-live-2's method): front 10 ± 2; three-quarter 7–8, if the spread allows the near section's fifth point.
- **The plait at play distance:** width within 0.5 px of the drawn rear (7.4 px Near, 4.6 px Middle), and luma within 5% of 69.1.
- **The fit:** char-port-1's braid checks on the nine female types × three cuts over a coat:
  - no plait triangle touching the collar or upper back;
  - the root at the scalp.
- **The ears open:** 3 of 3 rays each side.
- **Triangles:** ≤ 12,000 on the near mesh.
- **Flag off:** byte-identical to main.
- **Step 4:** calibration by the S5 rule, the luma bins at Middle, shimmer at the three stops, and the audit.

## Where the cuts stand

**After [the volume step](volume/README.md):** all three cuts are in band, each on its own side.

| Cut | Body / eye spacing | In band | Cheek measure (report) |
|---|---|---|---|
| `swept_braid` (cut 1) | **3.119** | yes | 1.615 |
| `.2` | **3.135** | yes | 1.622 |
| `.3` | **3.077** | yes | 1.593 |

The re-checks after the volume step all pass:
- flyaways at front, three-quarter and back;
- the plait's fit on 27 fittings;
- the ears;
- the plait's width and luma;
- the tips (front 9, three-quarter 7);
- the triangle budget;
- flag off.

The details are in [volume/README.md](volume/README.md).

### Before the volume step

Each cut is measured on its own parting side. Cut 1 parts as Cora's drawing does.

| Cut | Body / eye spacing | In band | Body width (px) | Eye spacing (px) | Cheek measure (report) |
|---|---|---|---|---|---|
| `swept_braid` (cut 1) | 2.838 | no | 199 | 70.1 | 1.474 |
| `.2` | 2.871 | no | 201 | 70.0 | 1.489 |
| `.3` | 2.812 | no | 197 | 70.0 | 1.459 |

All three are 4–6% under the band's floor. The floor needs 7–11 px more body (about 4–6 mm a side); the target needs 19–23 px (about 10 mm a side).

## The mirror

The same seed parted either way is now an exact mirror in the generator's output: the measures, every part's reach, the front sections' vertices, the bone weights, and the composed file. Main's client still draws the two differently; that is the laptop's track ([mirror/README.md](mirror/README.md)). Each cut is measured as it ships, on its own side.
