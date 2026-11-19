# Cora’s stage 3 face shading

The final dev-box AMD daylight calibration passed all 12 patches. The cheek measured **(236,165,128)** against a base of **(238,181,144)**. Its green and blue drop by 16 levels each, within the agreed ±6 of the drawing’s drops of 19 and 20. The upper-neck shadow measured **(195,128,98)** against **(192,121,90)**. The GLB has 48,896 triangles, six embedded clips and 15 expression keys. The final artistic attempt is submitted for the GC’s side-by-side verdict. [Matched front, three-quarter, profile, back, Near and Middle](review.jpg) · [Face detail against the drawing and second attempt](face-detail.jpg) · [Daylight calibration and contract audit](calibration-report.json)

| Fixed portrait patch | Drawing target | First high | Second high | Final xhigh |
|---|---|---|---|---|
| Base at (815,432) | 241,183,148 | 238,181,145 | 238,181,144 | 238,181,144 |
| Cheek at (853,411) | 235,164,128 | 240,167,131 | 236,165,128 | 236,165,128 |
| Upper neck at (800,506) | 192,121,90 | 214,142,102 | 200,137,105 | 195,128,98 |
| Cheek minus base | −6,−19,−20 | +2,−14,−14 | −2,−16,−16 | −2,−16,−16 |

All three attempts use these same 9 × 9 channel medians at 1600 × 900, 11:00 daylight and idle at zero seconds. The nine retained hair measurements also passed on the final face. Each pass has a material audit and recorded measurements. [First pass](high-1/review.jpg) · [First measurements](high-1/colours.csv) · [Second pass](high-2/review.jpg) · [Second measurements](high-2/colours.csv) · [Final measurements](colours.csv)

## Neck floor and jaw join

Before the final attempt, a diagnostic copy of the second fit set the skin, face and tint RGB factors to pure black. The registered upper-neck window at x = 796–804 and y = 502–510 measured **(28,28,22)**. The drawing target clears this floor in every channel. The original absolute target was used for the final calibration. [Control portrait](neck-black-floor.png) · [Marked window and final comparison](neck-floor-window.png) · [Floor and target in the calibration JSON](own-cora-live.calibration.json)

A material-ID capture traced the triangular patch below the ear to the duplicate cage rings where the underside of the jaw joins the throat. On the second pass the underside’s normals pointed steeply down, while the neck normals pointed sideways. The final pass carries the face’s UVs, pigment and normals over the underside and interpolates them to the neck attachment. The median display-luma step across the upper join fell from 22.54 to 2.59 levels over 38 columns at three-quarter. Across the lower neck attachment the median went from 6.43 to 11.44. There is still a short mark just below the ear, beside the lock. The final close-up shows its size. [Join measurements](jaw-join.json) · [Under-jaw fit](under_jaw.py)

## Face features and replay

The upper lashes and brows use the existing rigged strips and tapered lash cards. The corrections carry through every shape key. The skin and tint maps come from the generator. The cheek and freckles use the tint layer. The fine mouth crease follows the existing mouth UVs, and the soft cast shade beneath the lower lip continues onto the chin where the lip tint ends. The R/G threshold sidecar softens the directional cheek transition. The small nose shade is softer than the drawn nose. The chin pad was rounded on its existing rings. [Procedural paint](paint_features.py) · [Blender fit](fit_features.py) · [Counted geometry and clips](game-counts.json)

The submitted camera pairs use Bevy. The lower row pairs the drawing’s overhead reference with the native 58° Near and Middle cameras. The independent factory rebuild uses the checked-in Standard OCIO profile and the project Blender shim. The replay check includes separate results for both sidecars, the GLB, the six Blender review frames, every expression and the return to neutral. [Factory comparison](replay-check.json) · [Material audit](material-audit.jsonl) · [GLB](own-cora-live.glb) · [Editable scene](cora-final.blend) · [Session journal](../session.jsonl) · [Replay entry point](../replay.py)

```bash
BLENDER="$HOME/.local/share/slop-tools/build-bin/blender"
OCIO="$PWD/docs/char-live-1/standard.ocio" CHAR_LIVE_OUTPUT="$PWD/.local/cora-face-replay" "$BLENDER" -b --factory-startup --python-exit-code 1 -P docs/char-live-2/replay.py
```

The factory rebuild reproduced the packaged GLB and both sidecars byte for byte. All six Blender views and 17 expression frames matched pixel for pixel. Each of the 15 expressions changed the neutral image, and releasing the key restored it exactly. The three embedded images matched the regenerated atlas, iris and tint files byte for byte.

## Stage time and usage

Stage 3 ran from approximately 20:57 to 21:30 UTC on 19 November, including the shared-host quiet window. The two high attempts produced their review frames by 21:21 and 21:23. The black-floor control finished at 21:24, the final xhigh calibration at 21:27 and its independent factory verification at 21:30. The factory run took 2 min 56 s. Three artistic attempts used the existing release client on the dev-box AMD GPU. Disk had 51 GiB free at submission.
