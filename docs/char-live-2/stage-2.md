# Cora face profile — final xhigh checkpoint

**Stage 2 failed visual acceptance. Modelling stopped after two high fits and the final xhigh fit.** The cheek breadth and all four profile landmarks are in tolerance. The jaw is too narrow at the measured station, the chin holds too much width near its tip, and the hair shows irregular dark boundaries behind the ear. The reviewer requested a separate generator change, `cage-taper`, to control the jaw and low chin independently. The next face fit starts from this checkpoint after that change is reviewed. Face shading waits for the face. Hair volume, locks and palette can proceed independently when the laptop calibration command arrives.

[Drawing and model pairs](stage-2-review.jpg) · [Front width measurements on the portraits](stage-2-front-widths.jpg) · [First high fit](stage-2-high-1.jpg) · [Second high fit](stage-2-high-2.jpg)

## Shape

The front drawing has 356 px between the exposed hairline and the chin, at y=128 and 484. Cheekbone, jaw and chin were sampled at y=320, 414 and 458. At the last station, 26 px above the chin, the central facial contour is distinct from the neck on both sides. The fitted portrait uses 244 px between y=133 and 377, with the same fractional sample heights. The drawing widths are 255, 197 and 100 px. The final portrait widths are 179, 122 and 84 px. A depth check on the exported GLB independently located the boundaries in the fitted view. [Sample coordinates and ratios](stage-2-front-widths.json)

| Measurement | Drawing | Second high | Final xhigh | Tolerance | Result |
|---|---:|---:|---:|---:|---|
| Cheekbone width / visible face height | 0.716 | 0.840 | 0.734 | ±0.025 | Pass |
| Jaw width / visible face height | 0.553 | 0.664 | 0.500 | ±0.025 | Fail |
| Chin width / cheekbone width | 0.392 | 0.498 | 0.469 | ±0.030 | Fail |
| Chin-to-ear rise | 31.2° | 31.2° | 31.2° | ±4° | Pass |
| Brow projection / crown-to-chin height | 0.020 | 0.0203 | 0.0203 | ±0.010 | Pass |
| Nose projection / crown-to-chin height | 0.108 | 0.1096 | 0.1096 | ±0.015 | Pass |
| Upper lip projection / crown-to-chin height | 0.059 | 0.0599 | 0.0599 | ±0.010 | Pass |

The midline depth fit survived the transverse cheek and jaw changes. The chin now rises into a continuous under-jaw strip. The three-quarter mouth-to-chin contour still terminates in a squared pad. The upper neck reads as a straight column in profile. Rebuilding the cap and lining around the pinna covered the exposed angular scalp. The overlapping surfaces leave dark irregular edges at the ear, on the rear sweep and toward the braid. [Profile landmarks](stage-2-measures.json)

Front, three-quarter and profile pairs use matched crown-to-chin framing. The lower rows show the orbit and both 58° play stops. The reference sheet supplies an overhead drawing as the nearest available comparison for Near and Middle. The asset views use Blender studio lighting.

## Checkpoint and verification

[Editable Blender scene](cora-profile.blend) · [Stage-2 GLB](own-cora-live.glb) · [Session journal](session.jsonl) · [Factory replay script](replay.py)

The checkpoint contains 37,210 triangles, six embedded clips and all 15 expression keys. Each key independently changed at least 1,113 pixels in the 440 px portrait. The returned neutral frame exactly matched the original. After the final captures the audit visited 26 materials and found only the generator atlas, iris and tint. The journal retains the earlier failed audit with Blender's transient Render Result buffer and its recovery. [Expression pixel counts](stage-2-expressions.json) · [Material audit](stage-2-audit.json) · [Replay and export checks](stage-2-replay.json)

From the repository root with the lookdev clip library present:

```bash
OCIO="$PWD/docs/char-live-1/standard.ocio" CHAR_LIVE_OUTPUT="$PWD/.local/char-live-2/rebuilt" \
  "$HOME/.local/share/slop-tools/build-bin/blender" -b --factory-startup -t 2 \
  --python-exit-code 1 -P docs/char-live-2/replay.py
```

The independent factory replay reproduced the GLB byte for byte and all 27 compared frames pixel for pixel. Its final scene audit passed. The replay saves cora-final.blend and own-cora-live.glb inside the output directory. The final scene here is named cora-profile.blend to identify the stage.

## Generator back-port

Keep the nasal-root-relative depth stations and a separate projecting chin and lower-ear measurement as candidate controls for the cage. Fit the cheek, jaw and low chin against the same normalized front stations before accepting a new master. Preserve the correspondence between the two skin copies of the jaw seam, the under-jaw strip, the neck ring and the morphs. The current lateral taper and the reworked cap/lining did not pass and should stay in this inspection checkpoint.

The hair palette, per-lock highlight mask and shaded tint slot are still deliverables for a future generator pass. This checkpoint establishes drawing targets for them; it contains no calibrated implementation.

## Time and usage

The first two high fits occupied about seven minutes (16:34–16:41 UTC). The final xhigh measurements, fit and visual check took about eight minutes (16:43–16:51 UTC), followed by about two minutes for the independent replay check. Two high fit runs and one xhigh fit run used Blender factory startup; the final verification used another factory startup. Zero game builds, external image generations or paid calls. Token totals unavailable.
