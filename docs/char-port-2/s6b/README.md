# char-port-2 · S6b · Face proportions: checkpoint after the face step and its fixes

**Status:** the face step is done and checked, with the GC's three answers applied:
- the men's classes accepted as they are;
- elder-f's jaw-line swap (a measuring fault, below);
- the open-mouth fold fixed.

The ears, S6b's second step, come next.

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
- **The men's classes stop short of 1.75** (means 1.81–1.84). **This is a deliberate male difference (the GC's, 2026-11-21):** once the cheek narrows, the back of the jaw (at the jaw angle, about 80 mm behind the irises) sets the outline. A stronger factor would mostly make the lines alike (below).

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

**The three jaw lines** ([jaw.json](jaw.json), [jaw.py](jaw.py)):
- **How it's measured:** the face's width with the ears excluded where a level plane cuts the skin's surface, at 0.08, 0.12, 0.15, 0.18 and 0.20 H over the chin.
- **The order holds everywhere:** round wider than even, even wider than long, at every height in every class, before and after.
- **Elder-f's swap was a measuring fault, not the face:**
  - the first version of the tool took the vertices within 3 mm of each height;
  - on elder-f-b at 0.15 H no vertex row of the jaw's back fell in that band, so it read the jaw 11.8 mm too narrow (87.1 mm against the surface's 98.9);
  - by the surface, elder-f at 0.15 H is 104.4 / 98.9 / 95.4 mm (before: 118.7 / 109.4 / 105.3);
  - so no per-line nudge was made.
- **At 0.20 H, even and long come within 0.1–0.6 mm of each other** in every class but child-u (8.2 mm). There the narrowed outline is the jaw's back, which those two lines share. They were 1.1–4.2 mm apart before. The GC accepted this convergence at the lower cheek.
- **At the jaw itself (0.08–0.15 H)** the even and long lines stay 2.6–6.9 mm apart.

**Expressions: the open-mouth fold, and its fix** ([morph-new.json](morph-new.json), [morph_new.py](morph_new.py); [open-mouth.png](open-mouth.png)):
- **How it's counted:** the face skin's triangle pairs that cut through each other at full weight of an expression but not at rest.
  - Two triangles count as neighbours, and are left out, when they share a vertex's place, not only its index. Along a seam (the atlas's, and the midline under the chin) two vertices share a place, and their triangles' touching came and went with rounding.
  - The first count ([morph-check.json](morph-check.json)) compared totals, which let pairs that went offset pairs that came.
- **The cause:**
  - The skin already touches itself at rest in two places:
    - where the ear's root meets the skull's side;
    - along the jaw line's seam (on the man, under the jaw on one side).
  - The narrowed face brought these sheets to within a few hundredths of a millimetre.
  - A mouth shape moves them by only 0.01–0.4 mm (up to 2 mm under the man's jaw), from the jaw's drop fading back toward the hinge. That was enough to cross them.
  - It is not the jaw folding into the skull, and it can't be seen. [morph_where.py](morph_where.py) located the pairs.
- **Before the fix,** with faceprop:
  - the girl's talk (`MTH_A`) gained 32 pairs and her O 28, where the unnarrowed girl has 14 and 12;
  - the man's `MTH_A` gained 17, against 2;
  - the woman and the elder gained a few on I, U and E, against none.
- **The fix** (`person.expression_clearance`, under `faceprop`):
  - **The rule:** where an expression makes two skin triangles cross that do not at rest, the corners of both take one shared motion (their mean), round after round until none is left.
  - **Where it's checked:** as the file will hold it: Blender's own split of each quad, the head in place, in single precision. A pair that still crosses once its corners share one motion is crossing by rounding alone (two slivers a few hundredths of a millimetre apart), and those corners are held still for that expression.
  - **What it leaves alone:** the lids' meeting, meaning pairs within 8 mm of an eye opening's rim.
  - **The face at rest is untouched,** so the jaw lines and every ratio above are unchanged: the 21 types' face-width ratios are the same as before the fix, number for number.
  - **The motion changes little, and never at the mouth** (nothing within 30 mm of it), against the mouth's own 3.7–10.6 mm:
    - **the woman, elder and girl:** at most 0.28, 0.24 and 0.43 mm;
    - **the man:** at most 2.4 mm, under the jaw on one side, where the jaw line's seam crossed.
- **After the fix:**
  - **0 new pairs in every mouth shape** on the four bodies and on all 21 types (the unnarrowed types have 285 in `MTH_A` together).
  - The eye shapes on the four bodies are as on the unnarrowed bodies.
  - [open-mouth.png](open-mouth.png): the girl and the man at rest, talking and in O, three-quarter and profile; unnarrowed, with faceprop, and fixed.
- **Not fixed, for the GC: the blink on three round-line women.**
  - **What:** adult-f-a and youth-f-a gain 4 crossing pairs in `Fcl_EYE_Close` (3 to 7), and elder-f-a gains 6 (8 to 14).
  - **Where:** at the eye opening's outer corner, which on this head lies at the temple (71 mm out). The closing upper lid meets the skin under the corner, of the same kind as the 3–18 lid-contact pairs every unnarrowed type has at the lid's middle. The narrowed side brings the skin under the corner nearer.
  - **What fixing it by the same rule would do:** it would also reach the lids' own meeting, and changed adult-f-a's blink by up to 13.5 mm at 36 vertices. So it is not applied.

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

- **The blink-corner pairs** above: the GC's decision.
- **The ears** (the GC's second step): height 0.62 of eye-to-chin, lower end 0.47 under the eye line, the top kept, ±3%. Ours are 0.39–0.51 and 0.28–0.37.
- **Not yet run:** `cage_accept.py` and `face_types.py check` on all 21, the S4 audit and shimmer on the new types, the book and the bundle. They come with the ears.
