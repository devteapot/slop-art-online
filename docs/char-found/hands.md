# Foundation hands

The man’s L2 peak hand stretch in sword slash fell from 7.2881× to 1.9059× in the Stage 1 wrist-region probe. All ten exports play the 87 shared clips. The grip has one visible weakness. The four fingers curl into the palm, while the thumb stays extended and leaves an open grip in profile.

[Idle and grip close-ups at both levels](hands.png) · [Five mixes at a shared scale, front and right profile](lineup.png)

## Geometry and bind

The generator takes the fitted-head export from checkpoint `3145c1e25`. It removes the old hand geometry from the skin primitive and fits one new hand at each wrist. The palm and finger layout comes from our B1 generator at `cc277e011`. Each palm has six 24-point sections, four shared finger webs including the thumb-index web, twelve-point finger sockets, support rings on both sides of the knuckle creases and a tapered thumb. The distal pads carry a subtle nail tint and the finger roots have a soft occlusion tint. Both use vertex colour on the existing skin material.

The socket positions follow the character’s own bind pivots. The sleeve-side wrist vertices and their original weights are shared by the new hands. Each wrist joins through 20 edges at L1 and 40 at L2. The arm and hand traverse every seam edge in opposite directions. L1 uses the finger cage directly. L2 applies one Catmull–Clark step before joining the wrist. The forward offset of the elder’s forearm eases out through the palm heel. The hand region uses the existing skin draw call.

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
| Thumb | 0.772–1.298 (1.857) | 0.780–1.291 (1.840) | 0.900–1.107 (1.544) |
| Index | 0.716–1.243 (1.409) | 0.716–1.243 (1.407) | 0.941–1.071 (1.131) |
| Middle | 0.661–1.252 (1.459) | 0.661–1.252 (1.459) | 0.909–1.094 (1.179) |
| Ring | 0.649–1.296 (1.906) | 0.649–1.296 (1.906) | 0.910–1.083 (1.174) |
| Little | 0.598–1.295 (1.906) | 0.598–1.295 (1.906) | 0.910–1.082 (1.174) |

In the original man L2 wrist region, slash p05–p95 is 0.8902–1.1780 and the minimum is 0.4121. Measuring the whole right hand gives 0.7245–1.2440, with a 0.2566 minimum and the same 1.9059 maximum. Across all ten whole right hands, the worst slash compression is 0.1790× on elder L2.

At 0.60 s in overhead grip, the base L2 middle fingertip comes within 54 mm of the palm centre, from 174 mm in idle. The index, ring and little fingertips reach 77, 46 and 58 mm respectively. The thumb-to-index-skin gap grows from 88 mm in idle to 121 mm in grip. The shared clip also leaves the distal thumb and index pivots 119 mm apart at that frame. These captures show the unarmed pose. Hilt contact and grip strength have not been tested. Wave carries the relaxed finger pose through the arm gesture.

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

The shared `shoot.sh` photographed all ten in the game with the shared daylight settings, a 2400 × 1350 frame, idle at 1.00 s and sword overhead at 0.60 s. The close-up sheet crops the right hand. The lineup uses the game’s level orthographic projection at 459.184 px/m with paired background plates. Both lineup rows use identical dimensions for all five mixes. Raw captures and playback logs are in the worker’s ignored `.local/tmp/hands/report/` and orthographic plates in `.local/tmp/stage2/hand-report-lineup/`.
