# Cora Stannard live character review

[Reviewer sheet](review-sheet.png) · [Playable near GLB](own-cora-live.glb) · [Editable Blender scene](cora-final.blend) · [Four-body back-port plan](../four-body-proof.md)

Cora loads in the Bevy asset view with her layered town outfit, centre-back braid and all 15 face keys. The review sheet pairs the head drawings with game portraits, then shows the fixed 58° camera at Near and Middle and two frames from the project’s motion library. The [full rig review](rig-play-review.jpg) shows six poses from front, three-quarter, side, back and both play stops. All poses used the release game on the dev-box. The seat review used the character alone on the checker.

**Rig acceptance is open.** In the first high fit, the moving thigh showed through the apron and the pocket welt separated from the coat in a seat. The second high fit subdivided the panels through the hip, transferred pocket weights from their supporting triangles, seated the neck ring and trimmed hidden trouser and apron surfaces. The running front improved. Chair sitting now exposes a gap between the apron and knees, and the ground seat shows cut edges and a poor drape. Normalized weights and successful playback did not settle the garment fit. [Seated detail](seat-final-detail.jpg) · [Weights](rig-weights.json)

**Known face defect for the dedicated profile session.** The chin runs into the neck without a rising jaw. The brow, nose and lips read flat in profile. The dark hair lining behind the ear forms a blunt lobe. These appear in the [Bevy profile](game/profile.png) and [matched Blender overlay](face-c-profile-review.png). The three-quarter portrait keeps the green iris, catchlight, freckles, smaller shaped ear and short closed mouth.

## Model, colour and animation

| Near GLB | Count |
|---|---:|
| Render triangles | 32,308 |
| Exported vertices | 21,834 |
| Used materials | 9 |
| Mesh primitives | 10 |
| Expression keys | 15 |
| Maximum joint influences per vertex | 4 |

The renderer’s triangle, vertex and primitive counts agree with the GLB accessors. UVs, colours and normals can split an authored vertex on export. The outfit shares one cloth slot with per-corner linear dyes. Hair and its two loose temple strands share one hair slot. The only loaded images are the locally generated face atlas, iris and tint. The logged audit walked all material node trees and checked all loaded image datablocks against their generator hashes. [Bevy report](game/report.json) · [Export counts](game-counts.json) · [Audit](audit.jsonl)

The complete fitted figure ships here as a standalone GLB. The type/style composer expects a canonical type mesh, separately indexed clothing and hair masters, a look record and their common rest rig. Cora has fitted rest joints, one-off panels and a generated three-map face fitted to this cage. Splitting those parts into reusable library entries is the proposed back-port. The export packs the actual idle, walk, run, talk, sit_idle and sit_ground channels from the project’s shared J_Bip clip file. The game stills explicitly select embedded clips. Each clip has its original sampling and duration.

The final daylight check put the front coat at linear luminance 0.257, jersey at 0.091, apron at 0.539 and trousers at 0.070. The corresponding sheet picks were 0.207, 0.065, 0.516 and 0.049. The lit game values are higher, while the four layers keep their order and the coat reads as heather through the turn. [Pixel samples](bevy-values.json) · [Final shading orbit](game-shading-review.png)

The hand fit uses the generator’s articulated palm, thumb and four individually weighted fingers. A second fit reduced thumb reach and rotated the palms to clear the cuffs. The poses are readable at character scale. The palms have less modelling across the knuckles and heel than the hand drawing. [Hand comparison](hands-b-detail.png) · [Hand orbit](hands-b-review.png)

Each of the 15 keys changed the rendered face independently. Blink closes both lids, talk opens the lip slit, smile lifts the corners, and surprise combines a raised brow with a round O aperture. Returning to neutral restored the original pixels. The sheet shows a stronger surprise in the eyes. [Expression comparison](expression-sheet.png) · [Per-key pixel counts](expression-counts.json) · [Expression orbit](expressions-b-review.png)

## Time and usage

Times are approximate wall-clock durations. Stages overlap with the build or another check, and the coordinator’s review intervals separate the working periods.

| Stage | Observed time |
|---|---|
| Reference sheets and landmarks | At least 3m 17s from session-directory creation at 13:41:41 UTC to the reference commit at 13:44:58. Invocation times before directory creation are unavailable. Four GPT Image sheets, zero Grok images. |
| Bridge, blockout and orbit | About 4m 40s between the reference commit and the verified blockout commit. |
| First face/hair method, superseded | About 12m for the high fits including the host gate, then 6m for the xhigh check. Its projected materials were discarded at restart. |
| Restart, audit and clothing | About 4m for two high fits and 2m 30s for xhigh and replay. |
| Modelled hair | About 4m 30s including two fits, orbit and replay. |
| Generator face fit | About 6m 40s for the high fits and 9m for xhigh and replay. |
| Shading | About 2m for restart and the Blender fit. A later Bevy comparison identified the missing active colour set on the joined export, followed by roughly 2m of daylight dye adjustment and verification at 15:14–15:16 UTC. |
| Hands | About 1m 40s including both fits and review. |
| Expressions | About 1m 15s including the revised O and brow, full-key check and orbit. |
| Rig, export and game | First bind at 15:03 UTC. First game series started at 15:04:35. The second rig fit was captured by 15:10:28. Final daylight grading and replay followed. |
| Release build | 2m 14s with the shared sccache, overlapping the art passes. |
| Back-port plan and review package | Began during the earlier face fits. Final plan, counts and review package assembled after the game captures. Independent plan-writing time was not metered. |

The session used one game build. The remaining passes used zero external image generations. Model-token and billing totals were unavailable.

## Replay

The [ordered journal](session.jsonl) includes the Blender blocks for the restart. The [replay script](replay.py) builds the scene and GLB from factory startup. Run inside this repository with the game's lookdev assets present, including lookdev/anim/own-clips.glb. The generator eye and paint modules come from local revision 6cab88bcd. The external comparison scripts are the only consumers of the drawings. Use the session’s [Standard OCIO config](../standard.ocio). The [replay comparison](final-replay.json) records pixel differences, map audit and GLB hashes.

```bash
OCIO="$PWD/../standard.ocio" CHAR_LIVE_OUTPUT="$PWD/rebuilt" \
  "$HOME/.local/share/slop-tools/build-bin/blender" -b --factory-startup -t 2 \
  --python-exit-code 1 -P replay.py
```
