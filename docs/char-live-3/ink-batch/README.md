# Cora’s ink batch

This is one combined high attempt at five strokes, drawn by the general ink profile ([HANDMADE_INK.md v1.2](../../HANDMADE_INK.md), merged here from `origin/handmade-ink` at `dea8d2ade`). The five strokes are:

1. the upper lid, with its wing and two lash flicks;
2. a short outer lower lid;
3. the brows;
4. the jaw line, over a neck shade moved up to the jaw;
5. the nostrils, with the nose shade tightened and the highlight cut to a glint.

Every stroke is a carrier: a transparent primitive of the face mesh itself, so blink, talk and the brow keys move it. The drawing supplied only measurements: centrelines and widths from [drawing-strokes.json](../eye-frame/drawing-strokes.json). Nothing was painted from it.

[Review sheet: drawing, approved, ink fit](review-sheet.jpg) · [Morph sheet](morph-sheet.jpg) · [Play stills](play-stills.jpg) · [Game asset](own-cora-live.glb) · [Editable scene](cora-final.blend)

## Per stroke

Widths are measured in the Bevy daylight portraits by [widths.py](widths.py), on the eye the drawing was traced on. They are given at the 440 px registration (48 px eye front, 50 px three-quarter), as the drawing’s targets are.

Method: each ink is recoloured pure blue in turn. The stroke's coverage is summed across its own local direction, sampled every 0.25 px. Anti-aliasing puts about ±0.5 px on a measurement, so a 1–2 px line reads to about 30%. [All stations](widths.json)

| Stroke | Drawing front / ¾ | Ink fit front / ¾ | Notes |
|---|---|---|---|
| Upper lid, ⅚ from the inner canthus | 5.3 / 5.8 | **6.1 / 5.0** | Thin at the inner corner (1.2 / 1.3 at 5%, 3.5 / 2.4 at ⅙). Thickest 6.4 / 5.7, against the drawing's 5.7 / 7.1. |
| Wing (canthus → tip) | 2.6 / 3.6 mid-wing | 4.0 → 1.4 → 0 / 5.0 → 4.6 → 2.3 | Pointed tip beyond the canthus. Two tapered lash flicks off its outer third. |
| Outer lower lid | 1.9 / 2.1 | **2.1 / 1.8** | Thin from about mid-eye to the canthus. Its upper edge sits on the rim. |
| Brow, thickest | 7.7 / 8.0 | **8.5 / 8.0** | Heavy at the inner end, tapering outward: 3.3 / 2.1 near the inner tip, 1.1 / 2.9 near the outer. |
| Jaw | 1.7 | **2.1 at the chin** / 1.3 | Ends 1.6 / 1.4 front and 1.1 / 0.8 at ¾. On the near side at ¾ the line reaches 3.9 where the jaw turns toward the camera. |
| Nostrils | 1.6 / 1.3 | **2.1 / 1.7** | At or near the measurement floor for a line this thin. |

**Colours** were calibrated floor-relative at a close shot by [ink_calibrate.py](ink_calibrate.py), following the laptop's finding that a lid line at the calibration portrait never fully covers a pixel. Each target is the drawing's line against its neighbouring skin, applied over a black-ink floor control. One step from the first guesses converged. Residuals, measured minus target: lid (−9, −2, −1), brow (+8, +2, +1), jaw (+6, +1, +1), nostrils (+6, +3, +2). Sample sites at their deepest covered pixel, with their sizes, are in [ink-calibration.json](ink-calibration.json).

| Ink | Slot (light) | sRGB albedo |
|---|---|---|
| Lid, lashes, lower lid | eyes (unshaded except cast shadow) | 14, 5, 4 |
| Brows | eyes | 57, 32, 20 |
| Jaw | skin (skin band and shadow) | 27, 11, 7 |
| Nostrils | skin | 30, 11, 9 |

**Neck.** The collar-like band came from the throat shade, which peaked about 30 px below the chin and left a lighter neck under the jaw. The shade now holds full strength from the jaw down to z 1.422 m, then fades out by z 1.385 m. It runs evenly across the neck's width (side fade 0.74 → 0.30). Its strength was recalibrated in one step to keep the drawing's upper-neck patch, which now reads (189, 118, 88) against the target (192, 121, 90). Down the centre column of the portrait the neck reads uniform from the jaw line (row 500) to row 528, then fades by row 560.

**Nose.** The accepted first-fit paint was redone from the same generator atlas with a tighter shade (half-heights 0.0045 / 0.0035 UV above and below, from 0.010 / 0.006) and a tip glint about 40% of the old highlight's radius. [paint.py](paint.py) · [Parameters](maps/nose-paint.json)

**Not drawn: the three-quarter underside stroke.** The drawing's three-quarter underside line is the nose's midline profile, a silhouette. Laid on the surface, it would draw a vertical line under the tip in the front view, and the front drawing has none there; the front underside is only a soft colour boundary. The underside is therefore carried by the tightened painted shade. At three-quarter the near nostril shows as the dark stroke.

## Construction (what generalises)

The block is [fit.py](fit.py). The geometry is in [design.py](design.py) and [carriers.py](carriers.py), and the resulting values are in [fit-report.json](fit-report.json).

- **Registration.** Lid, lashes, lower lid and brow use the similarity that maps the drawing's canthi onto the skin's own eye-opening corners. Nostrils use the one through the pupils.
- **Lid placement.** The lid follows the skin's eye-opening edge, with its lower ink edge 0.5 mm inside the opening. Its width profile is the drawn one along the lid. The wing and lashes keep their drawn shape relative to the canthus.
- **Jaw placement.** The jaw runs just inside the face's front outline, 0.3 mm in, with the drawn width profile. It ends 8 mm below the drawn ends, behind the hair, where the side of the face turns edge-on to the front.
- **Carrier geometry.**
  - Carriers are lifted along the view onto the skin. Openings and steep turns are filled with a smooth harmonic depth.
  - Each carrier's spine is a polynomial fit smooth enough that its rows never fold.
  - Carriers are mapped by their own 3D lengths: the audit reads 99.9% (eyes) and 99.7% (skin) of triangles within 25% of the median density.
  - Each carrier reaches range + 1.8 mm beyond its strokes.
  - A clearance pass keeps every point of every quad 0.35 mm in front of the skin, in every morph target.
- **Morphs.** Carriers are bound to the triangles they ride: the skin for lids and features, and the old brow strip's triangles for the brows, whose keys move only that strip. Per-key displacements are smoothed along the grid. Skin weights come from the same anchors.
- **Maps.** There are two ink maps, made by `ink_field.py` from the registered `STROKES.json`:
  - `eyes`: range 5.5 mm, 0.26 m across 2048 px;
  - `skin`: range 3.5 mm, 0.21 m across 2048 px.

  Fade is the default (3), `width: "uv"` and `min_px` 1. [Strokes in UV](maps/)
- **Replaced geometry.** The opaque upper bands, the lower-lid line, the lash cards and the brow strips are removed: 184 faces. The lid crease and mouth lines stay.
- **Play distance.** An opaque lid core, generated from the lid stroke and lying inside it, keeps the lid's value at Near and Middle, where the ink fades by design.
- **Budget.** The carriers and cores add 1,260 triangles, for 49,806 of the 50,000 allowed. They are coarse grids, 3–5 mm columns of 2–3 quad rows; the clearance pass is what makes so coarse a grid possible.

**Parameters worth porting to the generator:** the canthus similarity; the lid's skin-edge offset and overlap; the clearance; the spine smoothing; the jaw's outline inset and end drop; and the per-stroke width gains (brow 1.0, nostril 0.8, lower lid 1.3). The gains came from one measured portrait. Three procedures also carry over as written: the floor-relative close-shot calibration, the neck's full and clear heights, and the nose shade half-heights.

## Acceptance

- **Portrait and three-quarter.** Each stroke is shown in the [review sheet](review-sheet.jpg), with measured widths in the table above. The approved column is the accepted nose fit (`70261f01e`), which carries the eye-frame first fit.
- **Blink, eye-joy, talk and angry brow.** Bevy stills hold each face key at 1, at front and three-quarter for the eyes and front low for the jaw. The lid line closes with the lid in blink, single-eye blink and eye-joy. The jaw line opens with the mouth in A and O. The brows move with all four brow keys. [Morph sheet](morph-sheet.jpg) · [Morph script](morph_stills.py)
- **All 15 expressions and neutral.** The Blender sweep changes 513 to 8,076 pixels per key, and the returned neutral differs by **0** pixels. [Expression frames](expressions/)
- **Play stills (58°).** Near and Middle show no dark blots. The eye reads as before, through the iris, the opening and the lid core; the ink itself has faded there. Near differs from approved in 273 pixels (largest change 70 levels) and Middle in 87 (largest 105), all on the face. [Play stills](play-stills.jpg)
- **Shimmer.** `ink_shimmer.py`, per slot, pan and zoom, passes at ratio ≤ 1.5. [eyes](shimmer-eyes.json) · [skin](shimmer-skin.json)

  | Slot | Near | Middle | Far | Portrait (pan / zoom) | Close 0:8:0.16:0.91 (pan / zoom) |
  |---|---|---|---|---|---|
  | eyes (lid, lashes, lower lid, brows) | faded | faded | faded | 0.49 / 0.46 pass | 0.23 / 0.15 pass |
  | skin (jaw, nostrils) | faded | faded | faded | 0.84 / 0.78 pass | 0.51 / 0.50 pass |

## What held

[Verification output](replay-check.json) · [Verification script](verify.py)

- **Colour.** All **20** colour checks pass: the 14 calibration patches ([report](calibration-report.json), [colours](colours.csv)) and the 8 cloth windows ([cloth](cloth.json), identical to the nose fit's). Against the nose fit, every patch moved at most 1 level, except the upper-neck shadow, which this batch changed on purpose (−6, −10, −10).
- **Audits.** The contract audit reports 0 errors and 0 warnings, ink checks included. Every Blender material audit passed. [Audit log](audit.jsonl)
- **Unchanged against the accepted nose fit.**
  - Byte for byte: every vertex attribute, index and morph target of the iris, eye whites, face skin, tint, hair, plait crest and cloth.
  - The iris and tint images, and the hair mask, face shadow map and calibration sidecars.
  - Volume: spread 1.870, crown lift 0.124 and rear depth 0.519.
- **Changed against the accepted nose fit.**
  - The eye-line primitive: bands out, lid core in.
  - The neck's vertex colours.
  - The skin atlas: nose paint only.
  - The brow primitive, which is gone.
  - The four new ink primitives.
- **The plait.** Its primitives are unchanged. The rear Near and Middle frames are pixel-identical to approved. The two rear portraits differ in 500 and 202 pixels, by at most 18 levels: the darker neck shows inside the collar, and its bloom spreads around it.
- **Factory replay.** A fresh factory-startup run of [the journal](../session.jsonl) through [replay.py](../replay.py) rebuilt the following byte for byte: the GLB, the face and hair sidecars, the calibration JSON and both ink maps. All 18 expression and registered frames matched pixel for pixel. A second Bevy capture of the rebuilt export reproduced all 17 daylight stills pixel for pixel.

```bash
BLENDER="$HOME/.local/share/slop-tools/build-bin/blender"
OCIO="$PWD/docs/char-live-1/standard.ocio" CHAR_LIVE_OUTPUT="$PWD/.local/ink-replay" \
  "$BLENDER" -b --factory-startup --python-exit-code 1 -P docs/char-live-3/replay.py
```

**Viewing it.** Copy the GLB, both ink maps (`own-cora-live.eyes.ink.png` and `own-cora-live.skin.ink.png`), the face and hair sidecars and the calibration JSON together to `living/game/assets/view/`. Use a client built with the ink profile: branch `handmade-ink`, or `char-live-3`. Only PNG maps are delivered; the laptop's bundle step makes the KTX2 copies.

## Known gaps

- **Jaw at three-quarter.** The near-side line kinks slightly at the chin corner. It follows the face's front outline, which jumps there from the chin pad to the jaw ridge.
- **Brow inner ends.** They read blunter than the drawing's rounded start.
- **Nostrils.** They measure slightly heavier than drawn, 2.1 against 1.6 px, at the limit of the measurement for lines this thin.
- **No underside stroke** at three-quarter, as explained under Per stroke.

## Usage

One combined artistic attempt at high effort, ran from 00:24 to 02:20 UTC on 20 November. That time included:

- one release client build (2 min 56 s, warm sccache), with its 2.6 GB build tree deleted straight after;
- one design iteration that met the 50,000-triangle cap, then fixes to fold-free carriers, the clearance pass, the exporter's vertex split and custom normals;
- two ink-colour calibration steps and one neck calibration step;
- about 11 Blender journal runs of about 1 min 10 s each, plus two factory replays;
- about 15 Bevy capture sets;
- about 15 minutes waiting while another worker's merge gate held the Blender lock.

No paid model or image calls were made, and no database was used. Free disk stayed at or above 42 GB during the other worker's gate and was 56 GB at packaging. A reserved second attempt at high may follow for any stroke the general coordinator fails.
