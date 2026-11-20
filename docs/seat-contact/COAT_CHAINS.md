# Coat spring chains: what the generator must output

Status: **specification for the generator (char-4, asset work).** The client side landed in seat-2a and needs nothing more. This note says exactly what `living/tools/blender/person.py` must write into the coat style files so the client's seat contact applies to coats.

## Why the generator

The chains need the coat's vertices skinned to them. The client could only add bones; it would also have to rewrite each coat mesh's joints and weights at load time, in a second weighting rule beside the generator's `torso_w` and `skirt_shares`. The generator already builds the skirts' chains this way (char-4-skirts, `04b9ccc21`: `add_skirt_bones`, `skirt_shares`, `skirt_block`), so the coats follow the same path.

## What the client reads (seat-2a)

- **The group:** any VRM 0.x `secondaryAnimation.boneGroups` entry whose `comment` is `Coat` (any case) is cloth (`characters::CLOTH_GROUPS`), like `Skirt`. While its wearer sits on the ground and gets up, its tails keep to the ground's side of the seat's plane. No other client change is needed.
- **The joints:** every node below a group's `bones` roots is one simulated joint. A chain's last node has a tail 7 cm along its own offset, unless it has a child.
- **The colliders:** `colliderGroups` spheres are in their bone's own frame (Y up, the character facing −Z), and they scale with the bone (`characters::rig_springs`).

## The bones (8 a coat)

Each coat file (`coat-f.glb`, `coat-m.glb`, and any later coat style) has four two-bone chains, all children of the upper legs:

| Chain | Joint 0 (child of `J_Bip_{L,R}_UpperLeg`) | Joint 1 (child of joint 0) |
| --- | --- | --- |
| Left side | `J_Sec_L_CoatSide` | `J_Sec_L_CoatSide2` |
| Left rear | `J_Sec_L_CoatBack` | `J_Sec_L_CoatBack2` |
| Right side | `J_Sec_R_CoatSide` | `J_Sec_R_CoatSide2` |
| Right rear | `J_Sec_R_CoatBack` | `J_Sec_R_CoatBack2` |

- **No front chain:** the front stays open, and its panels keep their upper-leg weights.
- **No `_end` nodes:** a third node would be a ninth to twelfth joint. Joint 1's tail runs 7 cm on along its offset, down the coat, as a long skirt's does.
- **Placement:** on the coat's own surface, as `add_skirt_bones` places a skirt's. The side chain stands on the torso column `NT / 4` and the rear on column 8 (`SKIRT_CHAINS`' `Side` and `Back`). Joint 0 is at `SKIRT_TOP` (0.86 m) and joint 1 at `SKIRT_KNEE` (0.66 m), standing, `SKIRT_OFF` off the body. The names must not clash with `J_Sec_*_Skirt*`: a coat and a smock are never worn together today, but the names keep that possible.
- **Rest rotations:** identity, as every other spring bone. The bones are rigid children of the upper legs when unsimulated (a far character, or one past the client's near cap).
- **The rest rule** (relaxed 2026-11-19 from "deform exactly as without the chains", so weight can move from the hips onto the chains): unsimulated, the coat must be
  - **no worse than today's chain-less coat in every measured clip** (depth under terrain and body crossings; it may be better, e.g. a hem lifted away from the ground);
  - **free of new crossings** in walk, brisk walk and run, springs on or off;
  - **visually unchanged standing and walking** at the Middle (12 m) and Near (8 m) camera stops: a standing-idle and walk silhouette diff and still pair against the chain-less control, flagging any standing hem shift over about 10 mm before it ships.

## The weights

- **Below `SKIRT_TOP`:** the side and rear panels' share of their own side's upper leg passes to that side's chain bones, all of it `SKIRT_EASE` lower. Split it by where round the leg the vertex is (side or rear, as `skirt_shares` splits Front, Side and Back, with the front share staying on the leg) and by height between joint 0 and joint 1 (`SKIRT_BEND` round `SKIRT_KNEE`).
- **Above `SKIRT_TOP`:** unchanged. The waist and the hips stay on the body (`hip_share`).
- **Between the legs:** a share of the other thigh goes to that side's rear bone alone, as `torso_w` does for a skirt.
- **Four bones a vertex,** merged as `torso_w` merges them.
- **Both LODs skinned:** the far model is not simulated, so its chains rest rigid there.

## The VRM block

One group, as `skirt_block` writes the skirt's:

```json
{"comment": "Coat", "stiffiness": 8.0, "gravityPower": 0.0, "gravityDir": {"x": 0, "y": -1, "z": 0},
 "dragForce": 0.7, "center": -1, "hitRadius": 0.02,
 "bones": [<J_Sec_L_CoatSide>, <J_Sec_L_CoatBack>, <J_Sec_R_CoatSide>, <J_Sec_R_CoatBack>],
 "colliderGroups": [<left upper leg>, <right upper leg>]}
```

- **The colliders:** two groups, one per upper leg, with spheres at `SKIRT_SPHERES` (0.88, 0.76, 0.64, 0.52 m). Each sphere is the leg's own size there (`leg_at`), less where the coat at rest lies closer than a joint's radius. This is `skirt_block`'s rule, computed against the coat's own joint tails.
- **No gravity:** like the skirt, the coat keeps the place its thigh gives it, so a seated coat lies on the thighs as it does unsimulated.
- **Stiffness and drag:** 8.0 and 0.7 are the skirt's starting values. Tune them with `cloth_check.py --springs` through walk, brisk walk and run: what comes through must be what comes through unsimulated.

## What the client already measured

`cloth_check.py --terrain` places the body as the client does: the clip's hips' place scaled by `hips_k`, on ground where the rest figure's lowest point stands. On it, the coat vertices under the terrain by more than 5 mm are all on the side panels above the knee, plus a little of the rear. None are on the front, so the side and rear chains cover them:

| Line | `sit_ground_down` | `sit_ground` | `stand_up_ground` |
| --- | --- | --- | --- |
| coat-f (`lk_055747dcef6a3b03`) | side 40 mm, rear 8 mm | side 17 mm | side 75 mm, rear 39 mm |
| coat-m (`lk_003e6108dbe72915`) | rear 16 mm | none | side 32 mm |

Logs: [2a/coat-f-terrain.log](2a/coat-f-terrain.log), [2a/coat-m-terrain.log](2a/coat-m-terrain.log).

**Risk.** A chain root on the thigh's side sits near the ground in a cross-legged seat and in the rise. A tail contact cannot lift skin round a root that is itself at the ground. A short smock's single-joint chains show this: smock_74-m keeps 12 mm on the rise, all on `J_Sec_L_SkirtSide`, with that joint's own tail 5–7 mm off the ground. If coat-f's residual stays above 5 mm near the roots, root the side chains higher, at the hip's side (0.93 m), or give them a third joint.

## Acceptance for the generator's change

```bash
python3 living/tools/characters/cloth_check.py LINE.json --clip sit_ground_down,sit_ground,stand_up_ground --frames 16 --seat-contact
python3 living/tools/characters/cloth_check.py LINE.json --clip walk,walk_brisk,run --frames 16 --springs
```

- **Under the terrain:** coat-f and coat-m at most 5 mm in all three ground clips with `--seat-contact`, against today's coat-f 36.7 / 16.0 / 74.7 mm and coat-m 16.1 / 0.0 / 31.5 mm.
- **Crossings:** no new layer crossing in any clip.
- **Gaits:** walk, brisk walk and run with `--springs` come through no more than unsimulated.
- **In the client:** `check.py seat` shows coated residents reporting cloth joints (`seat: … 8 cloth joints`) with their lowest tail at or above the ground. The springs line's µs per character-step stays within dev-box's measured 2.64 µs per coated character-step.
