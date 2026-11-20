# Cora’s ink batch, attempt 2: lid and nostrils

This is the last attempt for the upper lid (item 4) and the nostrils (item 5), run at xhigh effort after the general coordinator's per-stroke verdict on [attempt 1](../ink-batch/README.md).

| Stroke | Verdict | This attempt |
|---|---|---|
| Lower lid | Passed | Kept |
| Brows | Passed (blunt inner ends noted for later) | Kept |
| Jaw line | Dropped | Removed |
| Upper lid | Not yet: too light and thin | **Reworked** |
| Nose | Not yet: nostrils read as a squiggle | **Reworked** |

**Jaw follow-up.** The jaw outline needs a view-dependent edge technique (client). A static carrier cannot follow a silhouette that changes with the view. The neck shade that starts under the jaw is kept; it is what removed the collar band.

[Review sheet: drawing, approved, attempt 1, attempt 2](review-sheet.jpg) · [Morph sheet](morph-sheet.jpg) · [Play stills](play-stills.jpg) · [Game asset](own-cora-live.glb) · [Editable scene](cora-final.blend)

## Upper lid

**Measurement.** [lidweight.py](lidweight.py) measures each image at the 440 px registration, on the eye the drawing was traced on (48 px eye front, 50 px three-quarter). It measures across the outer two-thirds of the eye. Darkness runs from 0, the lid's own skin, to 1, full ink: the drawing's darkest lid ink, or in a render what black ink renders as there, (61, 42, 31). [Numbers](lidweight.json)

- **Band width** is the dark run from the opening up, lashes included.
- **Mean darkness** is averaged over a fixed box from the opening up 0.16 of the eye's width.

| Front / three-quarter | Drawing | Approved asset | Attempt 1 | **Attempt 2** |
|---|---|---|---|---|
| Band width, mean (px) | 7.3 / 6.2 | 8.4 / 8.9 | 5.5 / 6.8 | **7.5 / 7.9** |
| Band width at ⅚ (px) | 6.7 / 5.0 | 8.3 / 7.6 | 5.4 / 4.1 | **6.9 / 6.2** |
| Band width, widest (px) | 9.2 / 7.9 | 10.8 / 15.2 | 7.5 / 15.4 | **9.6 / 10.3** |
| Mean darkness | 0.59 / 0.55 | 0.70 / 0.73 | 0.41 / 0.48 | **0.59 / 0.68** |

In front the lid now matches the drawing in width and darkness. At three-quarter it is about 25% heavier than the drawing: viewed at three-quarter, the near lid's surface turns toward the camera, and a stroke on the surface cannot thin with the view. The approved asset's heavy band was heavier still in both views.

**Colour.** The lid ink is now (6, 2, 2). In the close shot it renders as (64, 43, 32), against (61, 42, 31) for pure black ink. The renderer's grade lifts black that far, so the lid is as dark as it can be. The drawing-relative colour target is (76, 48, 35); the lid is now about 12 levels darker than that, deliberately, as the general coordinator asked for weight. [Calibration](ink-calibration.json)

**What changed.** [design2.py](design2.py) reuses attempt 1's [design.py](../ink-batch/design.py) and [carriers.py](../ink-batch/carriers.py) unchanged.

- **Width.** The drawn half-widths are ×1.25 over the outer two-thirds and the wing: a smoothstep from 0.12 to 0.42 of the canthus-to-canthus fraction, so the inner corner still tapers to nothing. The stroke grows upward from the same opening edge, with its ink edge 0.5 mm into the opening, so the opening keeps its place.
- **Lash fringe.** A sawtooth along the band's top edge, on its own map island so it cannot thin the band, from 0.30 to 0.97 of the eye. Spikes are every 0.9 mm and up to 0.8 mm out of the band, leaning 0.35 outward, with 0.45 mm half-width roots inside the band. It ends before the outer canthus, so the wing root stays clean. At portrait it reads as a filled, slightly ragged top edge; at close range, as lashes.
- **Wing.** It takes the same gain and still tapers linearly to a point.
- **Lash flicks.** The two drawn flicks now sit on the wider band's top edge.
- **Core.** The opaque core under the ink is generated from the wider stroke. It keeps the lid's value at play distance.
- **Fade and map.** Fade stays at the default (3); the lid keeps `width: "uv"` and the eyes map's 5.5 mm range.

## Nostrils

The nostrils are now two soft filled crescents painted into the skin atlas, in place of attempt 1's nostril carriers. They are drawn over the kept tightened shade and glint.

The journal block rasterises the face's own triangles near the nose into the atlas, so every texel knows the front-view point it shows. [nostrils.py](nostrils.py) then measures the drawn crescents there:

- the drawing's nostril centrelines, through the pupil similarity;
- their drawn half-widths ×2.3;
- a 0.3 mm soft edge on each side;
- the inside of each crescent filled at 75%;
- a multiply of (0.08, 0.05, 0.05) on the skin.

Measuring on the face rather than in the atlas avoids the atlas's own stretch. 412 texels changed, all inside the nose window. [Parameters and centrelines](maps/nostrils.json)

[noseweight.py](noseweight.py) measures the front portrait at 440 px. Cora's 3D nose sits about 9 px higher under the eyes than the drawing's, so place is measured from each nose's own tip glint. [Numbers](noseweight.json)

| Per nostril (left / right) | Drawing | Attempt 1 | **Attempt 2** |
|---|---|---|---|
| Dark area (px, D > 0.5) | 16 / 15 | 8 / 4 | **17 / 19** |
| Box w × h (px) | 8×5 / 8×5 | 6×3 / 8×3 | **6×4 / 8×3** |
| From the tip, across (px) | −8.3 / +7.3 | −8.9 / +9.0 | **−7.4 / +8.1** |
| Below the tip (px) | 10.8 / 10.8 | 7.8 / 10.5 | **8.2 / 10.2** |
| Core colour (D > 0.6, median) | (104, 61, 45) / (96, 55, 44) | – | **(126, 84, 63) / (120, 80, 57)** |

- **Size and place** now match the drawing.
- **Shape.** The shapes are a little flatter than drawn (3–4 px tall against 5), because the nose's underside is foreshortened from the front.
- **Value.** The core reads about 22 levels lighter than the drawing's. These shapes are two to four pixels across, so their cores are mostly anti-aliased edge pixels; the painted colour itself is near black.
- **Softness.** The edges are soft. The drawing's nostrils sit inside a brown underside shape, which this measure counts as soft edge (softness 12–13 drawn, against 4–6 here); the visual comparison is in the review sheet.

## Kept exactly, and the checks

[Verification output](replay-check.json) · [Verification script](verify.py)

**Against attempt 1, byte-identical:**
- every vertex attribute, index and morph target of the iris, eye whites, face skin, tint, neck and body, hair, plait crest and cloth;
- the iris and tint images, and the hair, face-map and calibration sidecars.

**The brows' carrier.** Every vertex attribute and morph target is byte-identical. It has the same triangles with the same winding. Only the order of those triangles in its index buffer moved: the exporter orders triangles across the whole face mesh, and this attempt changed that mesh.

**The eyes map.** The brows' and outer lower lids' islands are pinned to attempt 1's layout. Their four strokes are reproduced exactly, and their texels are unchanged (0 changed). The new lid, lash and fringe islands sit in the space around them.

**Removed:** the jaw and nostril carriers, and with them the skin ink map. 49,702 triangles of the 50,000 allowed.

| Check | Result |
|---|---|
| Colour | **20 / 20 pass**: 14 calibration patches, each within 1 level of attempt 1, and 8 cloth windows identical to attempt 1's. [Report](calibration-report.json) · [Cloth](cloth.json) |
| Audits | Contract audit 0 errors, 0 warnings; every Blender material audit passed. [Audit log](audit.jsonl) |
| Expressions | All 15 keys change the face, by 399 to 7,010 pixels in the Blender sweep, and neutral returns with **0** changed pixels. In Bevy, the wider lid and its fringe close with the lid in blink and eye-joy and move with the brows' and mouth's keys. [Morph sheet](morph-sheet.jpg) · [Frames](expressions/) |
| Shimmer (eyes slot, the only ink left) | Faded at Near, Middle and Far. Passes at portrait (0.46 / 0.43) and at close-up (0.24 / 0.18). [Table](shimmer-eyes.json) |
| Play stills (58°) | No blots. Against the approved asset, Near changes 229 pixels and Middle 93, all at the eyes and nose, single pixels at most 118 levels darker: the lid core and a nostril. The eye reads as before. [Sheet](play-stills.jpg) |
| Plait frames | The rear Near, Middle and both rear portraits are pixel-identical to attempt 1. |
| Factory replay | The journal from factory startup rebuilt the GLB, both sidecars, the calibration JSON and the eyes map byte for byte, and all 18 expression and registered frames pixel for pixel. |
| Second capture | A second Bevy capture of the rebuilt export reproduced all 17 daylight stills pixel for pixel. |

The renders come from the client built from merged main (rustc 1.99.1), the same one attempt 1's package was confirmed with.

```bash
BLENDER="$HOME/.local/share/slop-tools/build-bin/blender"
OCIO="$PWD/docs/char-live-1/standard.ocio" CHAR_LIVE_OUTPUT="$PWD/.local/ink-replay" \
  "$BLENDER" -b --factory-startup --python-exit-code 1 -P docs/char-live-3/replay.py
```

**Viewing it.** Copy the GLB, `own-cora-live.eyes.ink.png`, the face and hair sidecars and the calibration JSON to `living/game/assets/view/`. Attempt 1's `own-cora-live.skin.ink.png` is no longer referenced.

## Journal

- **Attempt 1's records** (its block and its expression sweep) are archived; [fit.py](fit.py) replaces them in the replay.
- **New records:** the general coordinator's verdict, the jaw follow-up, this block and its sweep are in [session.jsonl](../session.jsonl).
- **For the generator back-port:**
  - the lid's width gain over the outer two-thirds;
  - the fringe's parameters;
  - pinned islands, so a passed stroke keeps its texels when others change;
  - texel-to-face rasterisation for painted features.

## Usage

One attempt at xhigh effort, from 02:38 to about 03:15 UTC on 20 November. It covered:

- five Blender journal runs of about 40 s each, plus two factory replays;
- about seven Bevy capture sets;
- one shimmer run.

No client rebuild was needed: the merged-main client built for attempt 1 was used. Some time was lost waiting on the general coordinator's gate lock for Blender. Free disk stayed at 56 GB or more. No paid calls, no database.

Per the stop rule, the lid and the nostrils now go to the general coordinator as they stand.

## GC verdict

**Both pass.**
- **Lid:** in front it matches the drawing's width and darkness, which was the goal.
- **Nostrils:** they read as the drawing's two nostrils.

**Recorded follow-ups:**

- **View-dependent strokes (client).** One follow-up with two items:
  1. **The lid at three-quarter** is about 25% over the drawing, because a stroke on the surface can't thin as the lid turns from the camera.
  2. **The jaw outline**, dropped from attempt 1: a static carrier can't follow a silhouette that changes with the view.
- **The nostrils** are slightly light (about 22 levels at the core, at 440 px) and flat (3–4 px tall against the drawing's 5).
