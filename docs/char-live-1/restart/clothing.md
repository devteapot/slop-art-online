# Clothing restart

The live scene opened the blockout from commit 8e0b15a73. The new journal contains the blockout history from that commit, followed by the restart. Both clothing checkpoints use geometry and flat dye. The sketches enter only the separate review-sheet compositor. No source from the rejected face-fitting journal enters the rebuild.

The [first orbit](clothing-review.png) showed a broken jersey neckline and nearly invisible apron ties. It includes lapels, cuffs, pocket welts, apron's bow and tails, boot laces and soles. A sleeve-ring indexing error before that first orbit is recorded in the journal. The scene was restored from the blockout before correcting the ring index.

The [second orbit](clothing-fit-review.png) shows a clean V, readable apron ties, and stronger pocket and cuff separation. The jersey now crosses the coat in the chest and shoulder regions. From behind, its red collar forms a ledge. This fit fails the clothing gate. The xhigh fitting target is to fit the underlayer inside the actual coat surface everywhere except its front opening, with enough clearance at the neck, shoulder and chest. Leave the accepted coat silhouette and apron visible while fitting. Hair is pending.

The four orthographic views include 50% overlays. The two perspective views use the Bevy play-stop framing in Blender, with a 58° pitch, yaw 25°, vertical offset 8 or 12 m, and vertical FOV 42° or 44°. Native-resolution crops appear above reduced full frames. Final Bevy judgment remains pending.

The [material audit](audit.jsonl) walks every material node tree including nested groups and checks all image datablocks. The generator-image allowlist is empty at this stage. The original checkpoint contained Blender’s Render Result buffer, which failed the first audit. The journal records removal of that buffer and the passing result. After each orbit the buffer is cleared before auditing and saving. Both clothing fits passed with zero image datablocks. The second fit contains 17 material datablocks including earlier unused blockout materials. This is not an exported primitive or draw count.

A factory-startup replay rebuilt the blockout, restored it and repeated the revised pipeline. All six final RGBA images matched pixel for pixel. To reproduce from this directory after checking disk and the host gate:

```bash
python3 make_replay.py
OCIO="$PWD/../standard.ocio" CHAR_LIVE_OUTPUT="$PWD/rebuilt" "$HOME/.local/share/slop-tools/build-bin/blender" -b --factory-startup -t 2 --python-exit-code 1 -P replay.py
```

Restart, clothing, two six-view reviews and replay took about four minutes wall time. No image-generation calls or game build were used. Model-token usage and cost were unavailable.
