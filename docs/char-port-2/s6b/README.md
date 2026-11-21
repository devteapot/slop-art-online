# char-port-2 · S6b · Face proportions: the ears and the final checks, and a measure corrected

**Status (2026-11-21): not final.**
- **The GC's acceptance:** the 2D front-render measure, ears masked by the ID render ([below](#the-acceptance-the-2d-front-render-measure)).
- **Done:** the known-answer tests, and the factors re-derived on it. The blink and ears steps are done.
- **Next:** the two must-fixes (the lid-ink density warnings, the 7 value-end faults), the hair-over-cheek re-check per S6 cut, the full check list on the re-derived factors, the four-body portraits, and the bundle.

Everything here is behind `SLOP_PORT=faceprop`, with S1–S4's port (`jaw,jaw_shell,paint,neck,ink`). With the flag off, a type (adult-f-b: its file and shadow map) and a body (the woman) are byte-identical to before; the body's file differs only in the names of its own pictures.

## The acceptance: the 2D front-render measure

**The measure** (the GC's, 2026-11-21): the face's width at the cheek row over the eye spacing, measured as `drawing_spread.py` measures Cora's drawing, on the game's front portrait.
- **The ears are masked by an ID render:** [ear_id.py](ear_id.py) makes a copy of each type whose ears draw pure magenta; [face2d.py](face2d.py) draws each type as a composed person with no hair at image_spread.py's portrait (`idle@2.0`, `0:8:0.36:0.88`); `drawing_spread.face_render` takes the skin run on the cheek row from the face's centre, stopping at the ear's front edge, as the drawing's run stops at the line before her ear ([face2d_measure.py](face2d_measure.py)).
- **The drawing:** 1.751 (review.jpg) and 1.701 (stage-1's copy). The target is 1.75.
- **The 3D slice** ([face_width.py](face_width.py)) is reported. It reads higher (mean 1.818 against 1.749 on the re-derived types): it takes in the head's side behind the ear's front edge, which the front view hides behind the ear.

**Known-answer tests** (the GC's standing rule, now in [PLAN.md](../PLAN.md) §7): every tool here passes one before its numbers are used.
- [measure3d_selftest.py](measure3d_selftest.py): `face_width.py`, `jaw.py`, `ears.py` and `ear_id.py`, on synthetic heads of analytic width with ears (across the cheek row and above it), a nose and irises: 29 checks pass. It caught one assumption on the way, now written into `measure3d.chin`: the chin is found in front of the irises, so the irises must sit behind the face's front, as the generator's do.
- [../s6/drawing_spread_selftest.py](../s6/drawing_spread_selftest.py): `drawing_spread.py`'s drawing measure, `render` (image_spread.py's) and `face_render`, on synthetic pictures (a drawing with ink lines before the ears; a render with the ears joined; its ear-ID copy, shaded and plain; no ears): 15 checks pass. The S6 drawing results are unchanged by the refactor.

**The factors, re-derived** ([ratios-2d.json](ratios-2d.json)):
- **The rule:** from each type's two measured points (unnarrowed, and the face step), the ratio's change per unit of narrowing; each class's factor set so its mean is 1.75. The children take half the narrowing that would bring them there.
- **The women need none:** adult-f and youth-f are at 1.740 and 1.751 unnarrowed. The old tool's 1.90 counted part of the ear.

| Class | Factor (face step → now) | Unnarrowed (a / b / c) | The face step | **Re-derived** | Mean |
|---|---|---|---|---|---|
| adult-f | 0.885 → **1.0** | 1.721 / 1.724 / 1.774 | 1.569 / 1.596 / 1.648 | **1.707 / 1.724 / 1.774** | 1.735 |
| adult-m | 0.86 → **0.935** | 1.759 / 1.802 / 1.884 | 1.618 / 1.663 / 1.744 | **1.671 / 1.728 / 1.807** | 1.735 |
| child-u | 0.93 → **0.973** | 1.778 / 1.845 / 1.889 | 1.698 / 1.716 / 1.760 | **1.765 / 1.782 / 1.829** | 1.792 |
| elder-f | 0.865 → **0.957** | 1.774 / 1.810 / 1.853 | 1.569 / 1.612 / 1.669 | **1.707 / 1.737 / 1.783** | 1.742 |
| elder-m | 0.885 → **0.961** | 1.737 / 1.774 / 1.845 | 1.605 / 1.688 / 1.754 | **1.679 / 1.745 / 1.816** | 1.747 |
| youth-f | 0.885 → **1.0** | 1.722 / 1.744 / 1.787 | 1.568 / 1.579 / 1.644 | **1.708 / 1.744 / 1.773** | 1.742 |
| youth-m | 0.865 → **0.95** | 1.763 / 1.798 / 1.843 | 1.602 / 1.667 / 1.723 | **1.689 / 1.742 / 1.829** | 1.753 |

- **Every adult class's mean is within 0.015 of 1.75;** the children 1.792.
- **The women's a lines read 1.707 with no narrowing,** against 1.721 unnarrowed: the ears step's longer ears reach the cheek row further forward.
- **Variety:** over the 21 types, 1.721–1.889 (standard deviation 0.050) unnarrowed, **1.671–1.829 (0.047)** re-derived. The lines keep their order, a < b < c, in every class.

## The face-width measure, corrected (3D; superseded as the acceptance by the 2D measure above)

**What was wrong:** the first [face_width.py](face_width.py) left the ears out by their bone weights: the vertices within 3 mm of the cheek row weighing under 0.5 on the ear bones counted as face.
- The ear's own lower front vertices weigh less than that.
- On adult-f-a the widest "face" point the tool found was an ear vertex (weight 0.43), 83 mm behind the irises.
- So the ratio the face step was tuned on, and the GC's decisions on it, included part of the ear.

**The corrected measure:**
- the level plane at the cheek row cuts the skin's triangles (not the vertices near it);
- the ears are left out whole: the face skin's two small connected pieces;
- the outline it then finds is the jaw's back, 68 mm behind the irises, in front of the ear.

[ratios-corrected.json](ratios-corrected.json); the target is 1.75.

| Class | Before (a / b / c) | After the face step | The old tool said | With the ears step, ears included |
|---|---|---|---|---|
| adult-f | 1.67 / 1.79 / 1.91 | **1.49 / 1.58 / 1.72** | 1.78 / 1.75 / 1.80 | 1.82 / 1.89 / 1.96 |
| adult-m | 1.79 / 1.87 / 1.94 | **1.60 / 1.69 / 1.79** | 1.78 / 1.84 / 1.89 | 1.93 / 1.99 / 2.06 |
| child-u | 1.75 / 1.81 / 2.08 | **1.64 / 1.69 / 1.94** | 1.87 / 1.91 / 1.93 | 1.93 / 2.00 / 2.07 |
| elder-f | 1.87 / 2.04 / 2.11 | **1.62 / 1.77 / 1.86** | 1.73 / 1.76 / 1.82 | 1.87 / 1.94 / 2.00 |
| elder-m | 1.79 / 1.87 / 1.93 | **1.65 / 1.73 / 1.81** | 1.74 / 1.82 / 1.87 | 1.95 / 2.01 / 2.07 |
| youth-f | 1.67 / 1.77 / 1.91 | **1.49 / 1.56 / 1.72** | 1.78 / 1.75 / 1.80 | 1.82 / 1.88 / 1.96 |
| youth-m | 1.78 / 1.86 / 1.93 | **1.59 / 1.67 / 1.78** | 1.77 / 1.83 / 1.88 | 1.91 / 1.98 / 2.05 |

| Over the 21 types | Min | Max | Mean | Standard deviation |
|---|---|---|---|---|
| Before | 1.668 | 2.111 | 1.864 | 0.116 |
| After the face step (and the ears step: the same) | 1.486 | 1.939 | 1.686 | 0.114 |

**What this means:**
- **The unnarrowed faces were about 6% wider than the drawing,** not the 11% the old tool showed.
- **The face step overshot:** every class's b line is under 1.75 but elder-f-b (1.77), and the round lines are at 1.49–1.65.
- **The decisions taken on the old numbers need taking again:**
  - the men "stopping short of 1.75" as a deliberate male difference: by the corrected measure the men are at 1.59–1.81, not short of it;
  - the factors themselves, which were set on the old tool's numbers: by this one they leave the b lines at 1.56–1.77.
- **The narrowing keeps the variety** (the standard deviation 0.116 before, 0.114 after) and the three jaw lines' order.
- **Two other measures here leave the ears out the same corrected way:** [jaw.py](jaw.py) (its numbers are unchanged: the ears don't reach the jaw's rows) and [ears.py](ears.py).

## The face step as first measured (superseded by the section above)

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
- **The men's classes stop short of 1.75** (means 1.81–1.84). The GC took this as a deliberate male difference (2026-11-21). By the corrected measure above they are at 1.59–1.81, so the decision needs taking again.

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

The two measures now agree, as the GC expected once the face narrowed. A caution with the correction above: on our renders the cheek measure's width at the cheek row takes in the ears (S6's README: at this head's cheek row the ears join the outline), so this agreement is not a measure of the face alone.

## The blink: the close-up and the verdict

**The GC's rule:** (a), accept the new blink pairs as lid contact, if a close-up shows nothing at the outer corner; (c) if it shows anything; never (b).

**What the close-up showed** ([blink.png](blink.png): adult-f-a, blink 0, 0.5 and 1.0, front and three-quarter, unnarrowed against faceprop; [blink-corners.png](blink-corners.png): the outer corner at 4×, adult-f-a and adult-f-b):
- **With faceprop the eyeliner's wing broke at the outer corner:** at half a blink in three-quarter its end stood apart from the lid line, and at full closure it was ragged. With the eyes open it was whole.
- **adult-f-b showed it too, faintly** (a 1–2 px gap near the wing's tip). So it is not the round line's alone.
- **(c) did not touch it:** the band ended at the eyes (0.26–0.38 H) on the three round-line women left the blink pairs (7 / 14 / 7) and the break as they were, and cost 0.045 in ratio. The skin at the corner is the same in every build: the same vertices, motion and lid travel.
- **The cause is the ink, not the skin's pairs:**
  - each vertex of the lid's ink ribbon is projected onto the head and lifted 1.4 mm, with flat quads between;
  - at the wing's end the temple turns away, sooner once the face is narrowed, and the quads' middles sank behind the skin: up to 2.5 mm on adult-f-a and 2.8 mm on adult-f-b, against 1.8 and 0.8 mm unnarrowed, over 2–3.7% of the ribbon against 0.6–1.5%.
- **The fix** (`ink_carriers.clear_of_skin`, under `faceprop`, the upper lid and its wing only):
  - each ribbon corner is raised along its normal by the most any of its quads lacks to stand 0.7 mm before the skin, sampled across the quad, against the skin facing the same way;
  - behind the skin it leaves 0.16–0.86% of the ribbon on adult-f-a and 0.46–0.82% on adult-f-b, at or under the unnarrowed types' own;
  - the lower lid is left as built: lifted the same way, its line drew darker and fuller than the unnarrowed type's.
- **After it, the wing is whole** at every stage of the blink on both women, as on the unnarrowed types (the third column of [blink-corners.png](blink-corners.png); the right column of [blink.png](blink.png)).

**The verdict: (a).** The new pairs in the skin are the closing lid meeting the skin under the outer corner, of the same kind as the lid contact every unnarrowed type has. Nothing shows of them at the corner.

**Two differences that remain, reported:**
- **At half a blink, front,** the faceprop lower lid's line stays whole where the unnarrowed type's is partly covered by skin. It does so with or without the clearance.
- **The audit's ink-density warning on three types** (below).

**A note on the stills:** a person file reads the installed types' ink page. Rendered with the unnarrowed page, a faceprop face drew heavy black brows and a broken lid line; [expressions.png](expressions.png) of the face step has that fault. Every still here uses its own build's page.

## The ears

**The GC's targets:** height 0.62 of eye-to-chin, the lower end 0.47 under the eye line, the top kept, each ±3%.

**The rule** (under `faceprop`): `cage_head` sets the lobe's height (`EAR_LOW` 0.47 of eye-to-chin under the eye line), and `head_mesh._ears` draws the whole ear out downward to it from its top. The far head's ears are made the same way.

**The measure was corrected here too** ([ears.py](ears.py)): each ear's own shell. The first measure (vertices weighing 0.5 or more on the ear bones) cut the ear off where the bone's reach fades. It gave heights of 0.39–0.51, where the shells' are 0.48–0.63.

[ears.json](ears.json) · [ears.png](ears.png): the four bodies before and after the ears, front, three-quarter and profile.

| | Top over the eye line | Bottom under it | Height |
|---|---|---|---|
| Drawing | 0.15 | 0.47 | 0.62 |
| Before | 0.085–0.242 | 0.375–0.470 | 0.477–0.632 |
| After | **kept, to the digit** | **0.461–0.478: 21 of 21 in band** | 0.560–0.703: **8 of 21 in band** |

- **The height can't hold with the top kept:** height = top + bottom, and the tops run 0.085–0.242 by line (about 0.18 on a, 0.13 on b, 0.09 on c; the children's higher). Only a top of 0.13–0.17 gives 0.62 ± 3% with the bottom at 0.47.
- **In band on height:** adult-f-b, adult-m-a, child-u-c, elder-f-a, elder-f-b, elder-m-a, youth-f-b and youth-m-a.
- **Out:** the c lines and the men's b lines run short (0.56–0.60); adult-f-a, youth-f-a and the children's a and b run long (0.65–0.70).
- **Both ears are alike on every type.**

## The final checks (every S6b change, the 21 types `fp21h` and the four bodies)

| Check | Result |
|---|---|
| Crossings, mouth shapes | **0 new pairs** on the four bodies (every mouth shape) and the 21 types (`MTH_A`) ([morph-new.json](morph-new.json) `bodies_final`, `types_final`) |
| Crossings, eye shapes | as unnarrowed on the bodies; the three round-line women's blink-corner pairs, accepted as lid contact (above) |
| `brow_check` | 21 types, every brow at least 0.3 mm before the skin in every pose |
| `eye_colours` | passes |
| Ink page | 237 strokes for 7 classes |
| The S4 audit, types and bodies ([final/audit.txt](final/audit.txt)) | 0 errors; **3 warnings**: the lid ink's texel density on adult-f-a, elder-f-a and youth-f-a (87.5–88.4% of its triangles within 25% of the median). It comes with faceprop (adult-f-a: 0.940 unnarrowed, 0.882 with faceprop, 0.875 with the wing clearance), at the wing's run-out where the ribbon wraps the temple. Not waived: open. |
| The S4 audit, pages | not yet: the installed hair pages are the old ones (86 errors, all the strand means S6 corrected); it runs with the bundle, on S6's hair set |
| Shimmer (S4's, eyes) | **passes** on the woman, man and girl: faded at Near, Middle and Far; portrait and close-up pan and zoom ≤ 0.84 ([final/](final/)) |
| `face_types.py check` | every type ok, 200 of 200 people valid; value ends 60,641 of 60,648 valid: **7 faults, "at 0.20 the front is wider than the head within 0.30 H", new with faceprop** (flag off 60,648 of 60,648). A value's fixed offset (`front_breadth`) outweighs the margin the narrowing left between the two planes. Open. |
| `cage_accept.py` ([final/](final/)) | **14 of 21** within 0.03 H with faceprop, against 3 of 21 flag off and 1 of 21 with no port at all: the tool fails without S6b too. The seven failures (the women's a and c lines, adult-f-b) are at 0.04 and 0.12 H, the chin and jaw rows S1's taper reshaped, by 0.034–0.046 H. |
| Jaw lines ([jaw.json](jaw.json)) | the order holds at every height in every class |
| Flag off | a type and a body byte-identical (the body's own picture names aside) |

## Not yet

- **The face step's acceptance by the corrected measure:** the GC's decision.
- **Open:**
  - the lid-ink density warning on three types;
  - the 7 value-end faults at 0.20 H;
  - the ears' heights where the top is kept.
- **The book and both bundles** (PNG and KTX2, with `pictures.py check`) and the pages audit: after the decision.
