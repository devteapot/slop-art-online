# Cora blockout

[Review the four views and their 50% overlays](blockout-review.png). Columns use the same 763 px standing height and an orthographic camera. Reference crops translate horizontally onto the camera axis. They have no independent scale or warp. The three-quarter yaw is an estimated 35°. Use the front and side as the primary fitting views. The drawn three-quarter boots sit farther to the left than their projections.

The blockout is 1.65 m tall. The coat opening, apron, boots and sleeves are fitting volumes. The head includes the hair allowance. The eye-level guides are wire objects hidden in renders. The back drawing sets the braid attachment for the later hair pass.

The first orbit exposed thigh caps through the coat. Narrowing the hidden upper leg sections removed the intersections in the rest pose. A second comparison brought each upper sleeve in by 10 sheet pixels, angled the cuff and raised the sides of the coat hem. At the shoulder seam the final front silhouette spans 140 px against 139 px in the drawing. At the estimated knee it spans 144 px in both. These are outer spans, including any space between the legs, using alpha above 50% for the render and minimum RGB channel below 170 for the sheet.

## Replay and live edits

Run these commands in a writable copy of this directory. The Blender shim waits for the host gate at startup. Before each orbit check the gate and disk thresholds again.

```bash
BLENDER="$HOME/.local/share/slop-tools/build-bin/blender"
python3 make_replay.py
CHAR_LIVE_OUTPUT="$PWD/rebuilt" "$BLENDER" -b --factory-startup -t 2 --python-exit-code 1 -P replay.py
```

The adjacent session.jsonl contains every submitted Blender block, including the earlier fits and renders. The script replays them in order. The four final RGBA orbit images matched the live render pixel for pixel in a separate factory-startup process. Blender reported falling back to its built-in color management because the installed OCIO library supports 2.4 and the Blender config requests 2.5. This pass used grayscale workbench materials.

To start a fresh journal, copy bridge.py and drive.py to an empty session directory, launch the shim there with `-b --factory-startup -t 2 -P bridge.py`, and submit a Python file with `python3 drive.py STAGE file.py` from that directory. The bridge stays alive between submissions. Close it with `python3 drive.py close`. The review compositor expects turnaround.png and the four live orbit PNGs beside review.py.

The installed Grok Build CLI exposes Imagine through the agent. Its embedded feature documentation names the interactive command `/imagine`, the native tool `image_gen`, and the feature flag `features.image_gen`. Top-level and agent help have no standalone image subcommand. No Grok image was generated or billed as part of this check.
