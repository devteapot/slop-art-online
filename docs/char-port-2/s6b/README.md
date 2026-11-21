# char-port-2 · S6b · Face proportions: checkpoint after the face step

**Status:** the face step is done and checked. The ears, S6b's second step, wait for the coordinator.

The change is behind `SLOP_PORT=faceprop`, with S1–S4's port (`jaw,jaw_shell,paint,neck,ink`). With the flag off, the types are byte-identical: adult-f-b's file and shadow map compared with the installed ones.

## The measure (the GC's: ears excluded)

**The ratio:** the face's width at the cheek row over the eye spacing.
- **The cheek row** is 0.030 m under the iris centres.
- **The width** is seen from the front, orthographic as a drawing is, with the vertices skinned to the ear bones left out.
- **The eye spacing** is iris centre to iris centre.

**The tool:** [face_width.py](face_width.py), on each type file.

**The drawing's own:** 1.75 (1.70 in its smaller copy). It is the face's contour up to the ear's front edge: her ears show just beyond it, behind an inked line, mostly hidden by hair.

## What changed

**The rule:** one width factor a type class (`port.json`, feature `faceprop`) on the type's sections (`face_types.faceprop`).
- **Where it acts:**
  - whole from 0.14 to 0.30 H over the chin;
  - fading to none at the chin (S1's taper stays the chin's);
  - fading to none by 0.46 H for the outline's sections (`w30`, `wide`);
  - fading to none by 0.40 H for the front plane (`w15`).
- **Why the front plane stops lower:** it is the plane the brows lie on. Narrowed up to the brows, a brow at the widest `face_width` sank 0.1–0.8 mm behind the skin on the round line.
- **What stays as it was:** the eyes, nose and mouth. A class's three lines take the same factor.

| Class | Factor |
|---|---|
| adult-f, youth-f | 0.885 |
| adult-m | 0.86 |
| youth-m | 0.865 |
| elder-f | 0.865 |
| elder-m | 0.885 |
| child-u | **0.93** (milder: children keep their rounder faces) |

## Results

[ratios-before.json](ratios-before.json) · [ratios-after.json](ratios-after.json) · [spread.json](spread.json)

**The ratio, ears excluded (target 1.75), per class:**

| Class | Before (a / b / c) | After (a / b / c) | After, ears included |
|---|---|---|---|
| adult-f | 1.92 / 1.90 / 1.94 | **1.78 / 1.75 / 1.80** | 1.81 / 1.86 / 1.96 |
| adult-m | 1.89 / 1.95 / 1.98 | **1.78 / 1.84 / 1.89** | 1.89 / 1.98 / 2.05 |
| child-u | 1.97 / 2.00 / 2.05 | **1.87 / 1.91 / 1.93** | 1.92 / 1.99 / 2.04 |
| elder-f | 1.93 / 2.00 / 2.07 | **1.73 / 1.76 / 1.82** | 1.87 / 1.93 / 1.99 |
| elder-m | 1.83 / 1.92 / 1.96 | **1.74 / 1.82 / 1.87** | 1.94 / 2.00 / 2.05 |
| youth-f | 1.92 / 1.90 / 1.94 | **1.78 / 1.75 / 1.80** | 1.81 / 1.86 / 1.96 |
| youth-m | 1.88 / 1.94 / 1.98 | **1.77 / 1.83 / 1.88** | 1.88 / 1.97 / 2.04 |

- **The eye spacing is unchanged** on every type.
- **The men's classes stop short of 1.75** (means 1.81–1.84). Each step of factor buys less there, because once the cheek narrows, the jaw's back (at the jaw angle, about 80 mm behind the irises) sets the outline. A stronger factor would mostly make the lines alike (below).

**Variety across the 21 types:**

| | Min | Max | Mean | Standard deviation |
|---|---|---|---|---|
| Before | 1.832 | 2.074 | 1.946 | 0.055 |
| After | 1.729 | 1.934 | 1.815 | **0.057** |

Within each class (a to c), the spread goes:

| Class | Before | After |
|---|---|---|
| adult-f | 0.036 | 0.047 |
| adult-m | 0.094 | 0.104 |
| child-u | 0.075 | 0.060 |
| elder-f | 0.144 | 0.091 |
| elder-m | 0.127 | 0.131 |
| youth-f | 0.036 | 0.047 |
| youth-m | 0.096 | 0.108 |

The town keeps its spread of widths.

**The three jaw lines** ([jaw.json](jaw.json)), the face's width with the ears excluded at 0.08, 0.15 and 0.20 H over the chin:
- **0.08 H (the jaw's front):** the order holds in every class. The gaps change by under 13%, except the round line of elder-f and youth-f, whose gap to the even line narrows by about 57%.
- **0.15 H:** the order holds except elder-f, where the even and long lines swap by 1.1 mm (87.1 against 88.2).
- **0.20 H:** the even and long lines become equal (within 0.1–0.7 mm) in adult-f, adult-m, elder-f and youth-f. They were 2–3 mm apart before. At that height the narrowed outline is the jaw's back, which those two lines share.
- **So the lines stay distinct at the jaw** (0.08–0.15 H, but for elder-f's swap). **At the lower cheek, even and long now look alike from the front.**

**Expressions** ([morph-check.json](morph-check.json); [expressions.png](expressions.png): neutral, blink, eye-joy, talk and angry brow on the four bodies, before and after):
- **How it's counted:** the face skin's crossing triangle pairs at rest and in each of 15 expressions at full weight, on the woman, man, elder and girl; [morph_check.py](morph_check.py).
- **The baseline:** the skin crosses itself in hundreds of pairs at rest, before and after, from its overlapping shells (lips, mouth). What counts is what each expression adds.
- **Woman and elder:** nothing new.
- **The girl's and the man's mouth shapes add crossings with `faceprop`:** the girl's talk (`MTH_A`) +17 and O +18 against −5 before; the man's `MTH_A` +9 against −8.
- **Where:** [morph_where.py](morph_where.py) puts them low on the side of the head, 72–95 mm out, 7–43 mm under the eyes and 51–90 mm behind them, where the jaw's back meets the ear root. The opening jaw folds a little into the narrowed skull side there. It is out of sight from the front, but real; a fix would carry the jaw's back in with the cheeks.
- **The stills render correctly.**

**Children and elders:**
- **[types-child-elder.png](types-child-elder.png):** child-u a/b/c, elder-f-b, elder-m-b, adult-f-b and adult-m-b, in bob, front and three-quarter, before and after.
- **Children** keep their rounder faces with the milder factor: child-u 1.87–1.93, against 1.73–1.89 for the others.
- **Elders** narrow like the adults.

**The four bodies:** [four-bodies.png](four-bodies.png), the woman, man, elder and girl, front and three-quarter, before and after.

**The type checks:**
- `brow_check`: 21 types, every brow at least 0.3 mm before the skin in every pose;
- `eye_colours`: passes;
- the ink page: 237 strokes for 7 classes.

**The hair-over-cheek measure per cut** ([cuts/](cuts/)): the S6 measures with the `faceprop` types installed.

| Cut | Cheek measure (drawing 1.823) | Before | Hair body over eye spacing (band 2.973–3.319) |
|---|---|---|---|
| `swept_braid` | **1.832** | 1.615 | 3.109 |
| `.2` | **1.840** | 1.622 | 3.127 |
| `.3` | **1.792** | 1.593 | 3.071 |

The two measures now agree, as the GC expected once the face narrowed.

## Not yet

- **The ears** (the GC's second step): height 0.62 of eye-to-chin, lower end 0.47 under the eye line, the top kept, ±3%. Ours are 0.39–0.51 and 0.28–0.37.
- **Not yet run:** `cage_accept.py` and `face_types.py check` on all 21, the S4 audit and shimmer on the new types, the book and the bundle. They come with the ears.
