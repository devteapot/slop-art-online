# Foundation hands

All five mixes at both levels close the thumb in the overhead sword grip. The thumb tip finishes 30.9–44.8 mm from the middle segment of the index. The man’s L2 sword-slash peak remains 1.9059×, down from the original 7.2881×. All ten exports play the 87 shared clips.

[Idle and grip close-ups at both levels](hands.png) · [Five mixes at a shared scale, front and right profile](lineup.png)

## Geometry and bind

The generator takes the fitted-head export from checkpoint `3145c1e25`. It removes the old hand geometry from the skin primitive and fits one new hand at each wrist. The palm and finger layout comes from our B1 generator at `cc277e011`. Each palm has six 24-point sections, four shared finger webs including the thumb-index web, twelve-point finger sockets, support rings on both sides of the knuckle creases and a tapered thumb. The distal pads carry a subtle nail tint and the finger roots have a soft occlusion tint. Both use vertex colour on the existing skin material.

The socket positions follow the character’s own bind pivots. The sleeve-side wrist vertices and their original weights are shared by the new hands. Each wrist joins through 20 edges at L1 and 40 at L2. The arm and hand traverse every seam edge in opposite directions. L1 uses the finger cage directly. L2 applies one Catmull–Clark step before joining the wrist. The forward offset of the elder’s forearm eases out through the palm heel. The hand region uses the existing skin draw call.

The earlier thumb cap followed Thumb3, but its rest pad continued straight along the distal bone. In grip it swung away from the palm. The refit sets positive local scales on Thumb1 and Thumb2, rebuilds the three inverse binds, and directs the distal pad across the palm. The first ring blends from the thumb-index web. The distal ring blends about 60% Thumb3, 33% hand and the remainder across Thumb1 and Thumb2 to limit shear. The two thumb creases each have a bisecting support ring.

The default multiplies the fitted natural hand by 1.135 about the wrist. It starts from the shared finger pivots and the body mix’s hand-size parameter. The old placeholder’s 1.11 scale is discarded with its geometry. The hand nodes carry the scale so the finger pivots enlarge with the skin. The head mesh, head bind, all expression data, materials, images and face sidecar match the head checkpoint. No hair was authored.

| Mix | Wrist to middle fingertip at L2, natural → export | L1 hands, pair | L2 hands, pair |
|---|---:|---:|---:|
| Base | 211.71 → 240.29 mm | 2,816 | 11,088 |
| Woman | 196.42 → 222.93 mm | 2,816 | 11,088 |
| Man | 248.71 → 282.29 mm | 2,816 | 11,088 |
| Elder | 211.65 → 240.22 mm | 2,816 | 11,088 |
| Child | 128.16 → 145.46 mm | 2,816 | 11,088 |

The natural column uses a second export of the same mix at `--size 1.0`. All ten measured enlargement ratios are 1.135. The man's native hand is already the longest before this increase. L1 has 5,440 body and 7,028 head triangles, for 15,284 total with hands. L2 has 21,760 body and 7,060 head triangles, for 39,908 total. Each export has 82 skin joints, 11 used materials, three embedded images and one face sidecar. The game viewer independently reported those triangle totals and material counts.

## Playback and deformation

`clip_check.py --bind-scales` sampled all 87 takes on each export in Blender. The skeleton check compared all ten with the pinned clip library. All joint-local rest translations match. `clips_compare.py` reported 0.00° rotation and 0.0 cm translation drift on every take. The source animation table and sampler bytes also match. The shoulder p05–p95 envelope across all exports remains 0.7115–1.2453 in walk and 0.7123–1.2248 in run.

Each cell below gives **p05–p95 (maximum)** of posed edge length divided by bind length for the right hand. The interval takes the lowest per-export p05 and the highest per-export p95 across the five mixes at both levels. The probe uses every frame, 75 each for the two sword clips and 90 for wave. It includes edges with at least 12% average endpoint influence from that digit, including its side of the web. It excludes bind edges below 0.1 mm. The whole-hand test includes fingertips beyond the Stage 1 wrist radius.

| Digit | Sword slash | Overhead sword grip | Open-hand wave |
|---|---:|---:|---:|
| Thumb | 0.476–1.403 (2.015) | 0.476–1.403 (1.997) | 0.784–1.108 (1.472) |
| Index | 0.716–1.298 (1.557) | 0.716–1.298 (1.556) | 0.941–1.072 (1.131) |
| Middle | 0.661–1.265 (1.459) | 0.661–1.265 (1.459) | 0.909–1.094 (1.179) |
| Ring | 0.649–1.296 (1.906) | 0.649–1.296 (1.906) | 0.910–1.083 (1.174) |
| Little | 0.598–1.295 (1.906) | 0.598–1.295 (1.906) | 0.910–1.082 (1.174) |
| Whole hand | 0.595–1.271 (2.015) | 0.598–1.271 (1.997) | 0.889–1.088 (1.472) |

The man L2 slash probe at the wrist measures 0.8576–1.1750 at p05–p95, with a minimum of 0.3374 and a maximum of 1.9059. Across his whole right hand the interval is 0.6095–1.2663, with a minimum of 0.2374 and the same maximum. Thumb compression increased during opposition. Across ten whole right hands the lowest individual edge ratio in slash is 0.2112× (child L1), and the highest is 2.0148× (elder L2).

## Grip clearance

The right hand is sampled at idle 1.00 s and overhead sword grip 0.60 s. Distances follow the deformed fingertip cap, including its morph and all skin influences. Middle-segment distance uses the closest point on the posed Index2–Index3 centreline. All distances below are millimetres. The prior export is `ab98fee91`.

| L2 mix | Current tip to tip, idle → grip | Tip to index middle segment in grip, prior → current | Current tip to tip in grip with thumb held at idle |
|---|---:|---:|---:|
| Base | 65.4 → 43.9 | 138.3 → 38.8 | 91.0 |
| Woman | 60.6 → 40.8 | 128.3 → 36.0 | 84.5 |
| Man | 76.3 → 50.8 | 162.5 → 44.7 | 106.5 |
| Elder | 65.2 → 43.8 | 138.3 → 38.6 | 90.9 |
| Child | 44.6 → 33.3 | 83.7 → 30.9 | 59.3 |

On base L2, the thumb tip’s distance to the nearest index skin vertex previously grew from 87.7 to 121.0 mm. It now falls from 51.8 to 29.6 mm. The tip reaches 31.0 mm from the skin over the middle phalanx. Its distance from the palm centre falls from 144.1 to 118.1 mm. As a control, the probe holds only the three thumb rotations at idle while the rest of the hand plays the grip. Releasing those rotations closes the tip-to-tip gap from 91.0 to 43.9 mm. The left thumb in bow draw also closes against the held-thumb control on all ten exports. The game captures show an empty hand. Contact against a weapon hilt remains unmeasured.

[Per-mix checks, hashes and grip landmarks](evidence/hand-checks.json) · [All frames aggregated by mix, side, digit and clip](evidence/hand-strain.json)

## Reproduction

Run from the repository root, after generating the matching body and head checkpoint. Both fitted levels and all morph mixes use the same command. The input wrist ring determines the level.

```bash
src=living/game/assets/view/stage2-verify/man-l2.glb
out=living/game/assets/view/found-hands-l2/own-man.glb
python3 living/tools/blender/found/hands.py "$src" "$out" --size 1.135
python3 living/tools/blender/found/hand_check.py "$src" "$out"
export PATH="$HOME/.local/share/slop-tools/build-bin:$PATH" JOBS=3
blender -b -t 3 --python-exit-code 1 -P living/tools/blender/found/strain.py -- \
  "$PWD/$out" /tmp/found-man-hand-strain.json --digits
```

A repeat generation of elder L2 was byte-identical. The hand geometry and vertex colours are project-generated. The hand pass uses no outside meshes or textures.

The shared `shoot.sh` photographed all ten in the game with the shared daylight settings, a 2400 × 1350 frame, idle at 1.00 s and sword overhead at 0.60 s. The close-up sheet crops the right hand and pairs the earlier and current L2 grip profiles at the same framing. The lineup uses the game’s level orthographic projection at 459.184 px/m with paired background plates. Both lineup rows use identical dimensions for all five mixes. Raw captures and playback logs are in the worker’s ignored `.local/tmp/thumb/publish/` and orthographic plates in `.local/tmp/stage2/thumb-publish-lineup/`.
