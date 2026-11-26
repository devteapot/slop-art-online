# char-port-2 · S7 · The bind re-measure

**What this is.** The GC asked for this on 2026-11-21, after [hair-mirror](../../hair-mirror/README.md): bind is now the acceptance pose for every image measure taken against the drawing. This is the re-measure in bind, with nothing built. Every number below is the old one (idle 2.0 s) next to the new one (bind), each labelled with its pose.

- **Client:** hair-mirror's (`8b474464f`), at 1600×900, 11:00, soft film, springs off.
- **Run with:** `.local/char-port-2/s7/bindmeasure.sh` and `pitch0.sh`; the tables are built by [table.py](table.py).

## 1. The pose's known answer: is the drawing square?

[square.py](../square.py) measures how far the eyes' middle sits from the face's axis, the axis being the median middle of the lower face's run of skin. It also measures the eye line's tilt and the lower face's mirror mismatch. Its known-answer test, [square_selftest.py](../square_selftest.py), passes 24/24 on synthetic faces: square, eyes moved 6 px, leaned 5°, one cheek fuller, and an ear joined at the cheek, each through both the drawing path and the frame path.

| Source | Pose | Eyes off the axis | Eye-line tilt | Outline mismatch | Square |
|---|---|---|---|---|---|
| review.jpg front drawing | the drawing | 0.0 px (0.000 of spacing) | −0.33° | 0.018 | yes |
| stage-1 front drawing | the drawing | −0.2 px (−0.003) | −0.72° | 0.018 | yes |
| 21 types, S7's set | bind, pitch 8 | 0.2 to 0.6 px | −0.34° to 0.16° | ≤ 0.05 | 21/21 |
| 21 types, S7's set | idle 2.0 s, pitch 8 | 10.4 to 13.5 px (0.15 to 0.20 of spacing) | 2.3° to 2.7° | | 0/21 |

**The band's source is square.** Bind matches the drawing; idle does not. Idle's numbers repeat hair-mirror's +12.8 px.

## 2. A second variable: the camera's pitch

**The setup:** the portrait shot `0:8:0.36:0.88` puts the camera 8° above the head (`view.rs`, `YAW:PITCH:ZOOM:AIM`). The drawing is a level elevation. Under idle the clip lifts the chin, so the 8° was partly cancelled. In bind it is not.

**The effect:** in bind the camera's pitch moves the face measure by 0.1 to 0.27. At pitch 8 the women's and children's ear lobes rise off the cheek row, so the row passes under them, through the gap between the jaw and the lobe (marked ° in the table). At pitch 0 every type's row meets its ear, as the drawing's row meets her ear.

**What I propose:** bind at **pitch 0** (`0:0:0.36:0.88`) as the like-for-like with the drawing. Both pitches are reported; the choice is the GC's.

## 3. S6b's face/eye ratio, 21 types

The measure is the face's width at the cheek row over the eye spacing, the ears masked by the ear-ID copies, as `drawing_spread.face_render` measures the drawing.
- **The drawing:** 1.751 (review.jpg), 1.701 (stage-1).
- **The type sets:** S6b's is `fp21j`, main's faceprop types. S7's is `fp21b`, which adds S7's jaw rise.

| Type | S6b idle·p8 | S6b bind·p8 | S6b bind·p0 | S7 idle·p8 | S7 bind·p8 | S7 bind·p0 |
|---|---|---|---|---|---|---|
| adult-f-a | 1.707 | 1.342° | 1.451 | 1.707 | 1.342° | 1.451 |
| adult-f-b | 1.724 | 1.343° | 1.500 | 1.724 | 1.343° | 1.500 |
| adult-f-c | 1.774 | 1.430° | 1.644 | 1.774 | 1.430° | 1.644 |
| adult-m-a | 1.668 | 1.471 | 1.559 | 1.668 | 1.471 | 1.559 |
| adult-m-b | 1.729 | 1.490 | 1.641 | 1.729 | 1.490 | 1.641 |
| adult-m-c | 1.806 | 1.608 | 1.737 | 1.806 | 1.608 | 1.737 |
| child-u-a | **1.764** | 1.379° | 1.487 | **1.724** | 1.379° | 1.487 |
| child-u-b | 1.780 | 1.345° | 1.511 | 1.780 | 1.345° | 1.511 |
| child-u-c | 1.828 | 1.391° | 1.617 | 1.828 | 1.391° | 1.617 |
| elder-f-a | 1.705 | 1.408° | 1.547 | 1.705 | 1.408° | 1.547 |
| elder-f-b | 1.736 | 1.372° | 1.568 | 1.736 | 1.372° | 1.568 |
| elder-f-c | 1.784 | 1.492° | 1.758 | 1.784 | 1.492° | 1.758 |
| elder-m-a | 1.681 | 1.517 | 1.594 | 1.681 | 1.517 | 1.594 |
| elder-m-b | 1.745 | 1.588 | 1.678 | 1.745 | 1.588 | 1.678 |
| elder-m-c | 1.814 | 1.690 | 1.737 | 1.816 | 1.690 | 1.737 |
| youth-f-a | 1.708 | 1.355° | 1.453 | 1.708 | 1.355° | 1.480 |
| youth-f-b | 1.744 | 1.334° | 1.516 | 1.744 | 1.334° | 1.516 |
| youth-f-c | 1.773 | 1.412° | 1.644 | 1.773 | 1.399° | 1.644 |
| youth-m-a | 1.691 | 1.487 | 1.578 | 1.691 | 1.487 | 1.578 |
| youth-m-b | 1.742 | 1.513 | 1.661 | 1.742 | 1.513 | 1.661 |
| youth-m-c | 1.829 | 1.622 | 1.730 | 1.829 | 1.622 | 1.730 |

° the cheek row misses the ear (it passes under the lobe).

| Class mean | idle·p8 | bind·p8 | bind·p0 | bind·p0 against the drawing's 1.751 |
|---|---|---|---|---|
| adult-f | 1.735 | 1.372 | 1.532 | −12.5% |
| youth-f | 1.742 | 1.363 | 1.547 | −11.7% |
| elder-f | 1.742 | 1.424 | 1.624 | −7.3% |
| child-u | 1.777 (S6b 1.791) | 1.372 | 1.538 | −12.2% |
| adult-m | 1.734 | 1.523 | 1.646 | −6.0% |
| youth-m | 1.754 | 1.541 | 1.656 | −5.4% |
| elder-m | 1.747 | 1.598 | 1.670 | −4.6% |

The class means are S7's set; S6b's are the same except where noted.

**What it says:**
- **Idle widened every face.** The turned head brings the side of the head between cheek and ear into view on one side ([runs.png](runs.png)). In bind, square-on, the run stops at the face's own outline.
- **Every type is under the drawing in bind**, by 5% to 12% at pitch 0 and more at pitch 8.
- **The class order flips.** S6b narrowed the men (factors 0.935–0.95) because in idle they read wider than the drawing. In bind the men are the *widest* classes, and women and children the narrowest. S6b's per-class factors were derived from a pose artefact.
- **child-u-a's 1.724 against S6b's 1.764 was the idle pose.** In bind S6b's and S7's sets give the same number (1.379 at p8, 1.487 at p0); the jaw rise doesn't touch the cheek row. The "known measuring artefact" note in must-fixes.md becomes "an idle-pose artefact, gone in bind".
- **S7's set equals S6b's** on 19 of 21 types in bind. The exceptions are youth-f-a (p0 +0.027) and youth-f-c (p8 −0.013).
- **The 3D measure against the 2D: the cheek row is at different heights** (corrected; the first version of this note took the "front" of the head as +z, when the face looks down −z, and its "in front of the ear" values were wrong):
  - **3D** (`face_width.py`) cuts the head 0.030 m under the irises' centres.
  - **2D** (`drawing_spread.cheek_at`) drops 0.030 m in head heights of Cora's standard head, with the head's height taken from the eye spacing by the drawing's ratio (spacing = 0.30 of head height). On our heads the spacing is 0.38 of head height (adult-f-b: 97.8 mm against 256 mm), so the 2D row lands 0.43 × spacing under the eyes: **42 mm, not 30 mm**. That is lower on a face that narrows toward the jaw.
  - **At the 2D row's own height, the 3D and 2D agree:**

    | Type | 3D at 30 mm | 3D at the 2D row | 2D bind·p0 | Remainder |
    |---|---|---|---|---|
    | adult-f-b | 1.787 | 1.533 (42 mm) | 1.500 | −2.2% |
    | child-u-a | 1.708 | 1.498 (44 mm) | 1.487 | −0.7% |
    | adult-m-a | 1.702 | 1.566 in front of the ear, 1.613 whole (41 mm) | 1.559 | −0.4% |

  - **What the remainder is made of** (not separated yet; the ortho view will separate the perspective term):
    - **Perspective:** about 1 m off, the eyes (in front) read wider apart than the cheek's outline (further back), which makes the 2D smaller.
    - **The outline ink and anti-aliasing:** one ink pixel and one blended pixel a side, which also makes it smaller.
    - **The eye centres:** 2D takes the visible iris's centroid, 3D the iris mesh's centre.
  - **The ear mask takes no cheek pixels** at pitch 0. The run ends at the face's own ink, and the ear's ID lies beyond a gap of background (adult-m-a: `EEEEsk.k|sss`).
  - **The landmarks don't agree across the measures either.** The drawing's cheek row is 0.30 of its eye-to-chin (review.jpg 0.297, stage-1 0.307), and the 3D's 30 mm is 0.295 of adult-f-b's. On our renders, though, the 2D row is 0.34 (adult-f-b) and 0.38 (child-u-a) of the 2D eye-to-chin, and the 2D chin (the narrowest run under the mouth) and the 3D chin (the lowest skin by the midline) disagree too: eye-to-chin over spacing is 1.26 in 2D and 1.04 in 3D on adult-f-b, against the drawing's 1.45. Step 2 (a row defined by landmarks the same way on both) starts here.

## 4. The S6 cuts: hair body over eyes, and over the ear-masked cheek

The figure is the woman (adult-f-b, auburn) in `swept_braid`, with adult-f-b's ear-ID copy installed so the cheek stops at the ears.
- **The band** is 2.973–3.319 (the drawing's 3.146 ± 0.10/1.82).
- **The drawing's body over cheek** is 1.823.

| Cut | Old: S6 README, idle | S6b types, idle (this binary) | S6b types, bind·p8 | S6b types, bind·p0 | S7 types, bind·p8 | S7 types, bind·p0 |
|---|---|---|---|---|---|---|
| **body over eyes** | | | | | | |
| `.1` | 3.119 | 3.118 | **2.893** | **2.869** | **2.893** | **2.869** |
| `.2` | 3.135 | (3.135, S6b) | **2.922** | **2.921** | **2.922** | **2.921** |
| `.3` | 3.077 | (3.077, S6b) | **2.874** | **2.892** | **2.874** | **2.892** |
| **body over the ear-masked cheek** | | | | | | |
| `.1` | | 1.787 | 2.186 | 1.927 | 2.186 | 1.944 |
| `.2` | | (1.810, S6b) | 2.206 | 1.954 | 2.206 | 1.954 |
| `.3` | | (1.762, S6b) | 2.175 | 1.954 | 2.175 | 1.954 |

- **This binary reproduces the old idle numbers exactly** (cut 1: 3.118 and 1.787, as S6b's). The change is the pose, not the client.
- **All three cuts fall under the band in bind**, by 0.05–0.10 (2–3.5%), at either pitch. The camera's pitch hardly moves the hair (±0.02).
- **The body over the cheek** rises to 1.93–1.95 at p0 (2.18–2.21 at p8). That is because the bind cheek is narrower (§3), not because the hair is wider.
- **S7's types give the same hair numbers as S6b's.** The woman's face is unchanged at the cheek row and above.
- **hair-mirror's 2.661 for `swept_braid`** is on the laptop's `mirror-keep` build and render set, not S6's final cut. This is a different build from the one measured here.

## 5. What falls outside, and what it needs

1. **`swept_braid`'s side volume.** All three cuts are 2–3.5% under the band in bind. Under the GC's rule this becomes an S7 must-fix, decided together with the mid-strip remedy (a), then the flyaways, collar and six-style calibration re-checked. Nothing is built until the GC answers.
2. **The face width.** In bind every type is 5–12% under the drawing (p0), and the class order is the reverse of the one S6b's factors were set on. This is bigger than a re-tune, and the measure itself needs the GC's decision first:
   - **Pitch:** pitch 0 (proposed) or 8.
   - **Perspective:** whether the 4% perspective term should be removed. A longer lens or an orthographic view would need a client change, which is a build.
   - **The ear's position:** whether the cheek row's meeting with the ear (a free lobe at p8) is part of what's compared.

   Then whether S6b's per-class factors are re-derived in bind. That reopens the ears' height (0.47) and the men's narrowing.
3. **Unchanged by bind:** the 3D measures (face_width, jaw, ears), cage_accept, the crossings and the eye-joy fix. None of them is an image measure.

**Evidence:**
- [face.json](face.json): every ratio, with pose and pitch.
- [cuts.json](cuts.json): the cuts, with pose and pitch.
- [runs.png](runs.png): idle·p8, bind·p8 and bind·p0, on adult-f-b, adult-m-a and child-u-a, with the cheek run drawn.
- The frames are in `.local/char-port-2/s7/bind/`.
