# Hybrid character spike

**Verdict — adopt a mix by part.** Continue with authored garment panels and long hair cuts over the shared rig. Keep the procedural face types, expression system, body proportions and Far generator. The prototype is a viable way to build and vary more detailed clothes. This woman still falls short of Shino in portrait, and the seated outfit needs another fitting pass before release. [Comparison sheet](comparison.png) · [Measurements](measurements.json)

## What shows on screen

At 8 m the hybrid’s front locks frame the face and the collar, lapels and pleats divide the torso and skirt into readable shapes. The control reads as one blue smock. At 12 m the front panel and hair silhouette survive. The individual stitches and eyelash tips disappear. At portrait distance Shino has a coherent dark hair mass with a few bright edges, a clean fringe, a strong bow shape, and a clearly graduated iris. The hybrid has finer strand marks, but they repeat across adjacent locks. The crown has small ridges, the right temple lock hangs away at three-quarter view, and the jaw-to-neck line is still conspicuous. The Blue Protocol board also gives the eyes and mouth clear local contrast. Adding six lash triangles and sculpting the cheek did little for those features.

For an image measurement, I counted horizontal neighbours differing by at least 12 luma levels in a fixed front-view region. A matched plate and one-pixel erosion exclude most background and silhouette edges. At portrait, the percentage was **5.83% Shino, 3.58% control, 6.72% hybrid**. At Near it was 24.22%, 12.89% and 37.31%. At Middle it was 33.05%, 18.93% and 45.71%. Repeated strand and textile marks contribute to these counts. The hybrid has more small contrast changes than Shino even where its features are harder to read. The JSON records regions, denominators and counts.

The sheet uses Bevy’s asset view at 1600 × 900 with the idle clip held at 1 s. The play camera is 58° down, 8 m or 12 m vertically above chest focus, with 42° or 44° vertical FOV. Yaw is 0° or 38°. Each gameplay crop preserves source pixels. Portraits use a reduced common crop. The Shino recipe is 1.75 m. The matched pair are both 1.65 m, seed 71, with the same build, dyes, lighting and camera. The procedural files come from the bb944ef9 asset set. Its character generator and style tools match the spike's f592a072e base.

## Geometry and materials

Vertices are exported skinned POSITION entries counted across active primitives, including UV, normal and colour splits. The control wears the same underlying outfit pieces and long hairstyle family.

| Near part | Procedural vertices | Procedural triangles | Hybrid vertices | Hybrid triangles |
|---|---:|---:|---:|---:|
| Face, eyes, lines and tint | 4,370 | 7,184 | 4,388 | 7,190 |
| Exposed body skin | 3,027 | 4,616 | 3,027 | 4,616 |
| Long hair | 4,870 | 9,528 | 7,699 | 12,216 |
| Smock and authored panels | 2,363 | 4,384 | 4,550 | 8,108 |
| Jersey | 1,067 | 1,280 | 1,067 | 1,280 |
| Sleeve bands | 170 | 256 | 170 | 256 |
| Trousers | 1,702 | 2,096 | 1,702 | 2,096 |
| Boots | 1,550 | 2,680 | 1,550 | 2,680 |
| **Complete person** | **19,119** | **32,024** | **24,153** | **38,442** |

The hybrid leaves **11,558 triangles** under the revised 50,000 ceiling. Each Near export has 14 primitives and nine named material slots. Both Far compositions have 4,303 vertices, 7,212 triangles, seven primitives and three material slots. The original Far geometry is used throughout. Plain cloth on the Far model samples a neutral swatch of the same garment atlas.

Five outfit files reference **one** 1024² sRGB BC7 atlas on their existing cloth slot. Its 11 mips use **1,398,128 GPU bytes**, 1.33 MiB. The encoded KTX2 is 15,913 bytes on disk. The original face, tint, iris and strand resources are reused. A coloured atlas initially rotated a sleeve dye toward pink. A neutral atlas matched to the existing cloth colour mean corrected it. The packer needed one shared URI registered as class `atlas`. Its source survey found one texture and five users.

## Motion and variation

One editable Blender head master supplies two exported maturity profiles, 0.36 and 0.92. That sculpt is baked through the expression keys. A recipe supplies build through bones, and its seed supplies identity through the existing face rig. The head master also contains a weighted torso and leg fitting cage. Covered body geometry is removed from the dressed export. The high-detail edits concentrate on face, hands, hair and clothing. This spike does not establish an interchangeable full-body base for arbitrary outfits.

**Eighteen combinations were actually drawn** in Bevy, crossing two age profiles, three builds and seeds 71, 163 and 294. Three variations appear on the sheet and played all five clips. Age and seed changes remain subtle under the same fringe. The continuous profile and additional seeds can generate more recipes. The tested range covers heights 1.53–1.74 m and width multipliers 0.93–1.12. Children, elders, male fits and extreme values remain untested.

Idle, walk, run, talk and sit_idle each produced two rendered samples, at 0.18 and 0.58 s, plus joint records for the three variations. On the primary woman the largest measured J_Bip displacements between samples were 16, 706, 714, 108 and 18 mm respectively. All vertices have nonzero total skin weight, up to four influences, with maximum Near weight-sum error below 0.000001. Sitting reveals a failure despite valid weights. The hem spans the thighs almost horizontally, a hand is visible through the front, and a thin panel edge hangs below the right side. A seated cloth corrective and a side-view gait fit are prerequisites for adopting this cut.

## Frame cost

Headless Bevy on the shared dev-box, 1600 × 900, meadow, 64 composed actors, eight Near and 56 Far, no live world or observer. The repeated recipe isolates the per-person mesh change. Both cases ran twice for 24 seconds in control–hybrid–hybrid–control order through `crowd.py`. LOD diagnostics confirmed 56 Far each time. Terrain used its available fallback textures. The sampled view included 504 character mesh entities, nine character materials and 21 mesh/material pairs in every run. All four recorded 12 opaque multi-draw sets, 12 prepass sets and six shadow sets. The rendered texture count went from 23 to 24.

| Run | People triangles in view | Wall p50 | Wall p99 | GPU pass sum |
|---|---:|---:|---:|---:|
| Control 1 | 660k | 9.46 ms | 42.20 ms | 4.62 ms |
| Hybrid 1 | 711k | 7.72 ms | 18.97 ms | 4.13 ms |
| Hybrid 2 | 711k | 8.05 ms | 10.99 ms | 2.52 ms |
| Control 2 | 660k | 11.76 ms | 26.47 ms | 3.91 ms |

Wall percentiles use the second half of each frame record. GPU pass sum comes from the final periodic diagnostic. Host contention and the spread between repeats prevent a credible incremental millisecond estimate. The directly measured change is **51,344 additional people triangles and 40,272 additional exported Near vertices across eight people**, with equal phase batch counts. The laptop’s earlier repeated-index result was relayed by the coordinator and used a different workload. Windowed laptop timing with these real skinned meshes is still open.

## Scaling and reproduction

Use the garment and hair masters across people through the existing style files. For rollout across 21 types, evaluate the same cut against each head’s hair fit and fringe pivot, especially at the brow and temple. Fit body garments across current sex/build silhouettes, audit cuff and neck openings, and give long garments seated correctives. The outfit set needs a reusable atlas layout, named dyes and a pose check per cut. Keeping procedural face types avoids creating and maintaining 21 separate expression libraries. There is no throughput estimate for the full outfit set from one cut.

The three editable masters, authored construction scripts, labelled spring data, painted atlas and export tools are in [the Blender source directory](../../living/tools/blender/authored/). From the repository root, use a private worktree with the current PNG type/style files and pages, Shino and the shared clips installed. `make_masters.py` rebuilds the source masters. `generate.py` reads those masters and writes the type/style GLBs. A supplied bc7ktx executable selects direct BC7 output. Normal recipe composition, animation and rendering load them. The camera addition only supplies metric asset-view photographs. The shipped look book has no entries for these spike styles.

```bash
export BLENDER="$HOME/.local/share/slop-tools/build-bin/blender"
A=living/tools/blender/authored
L=living/game/assets/lookdev
python3 "$A/generate.py" "$L" --bc7 "$BC7KTX"
python3 "$A/audit.py" "$L"
python3 "$A/proof.py" photos "$GAME_BINARY" "$EVIDENCE/photos"
python3 "$A/proof.py" clips "$GAME_BINARY" "$EVIDENCE/clips"
python3 "$A/variation_grid.py" "$GAME_BINARY" "$EVIDENCE/grid"
python3 "$A/proof.py" crowd "$GAME_BINARY" "$EVIDENCE/frames"
python3 "$A/sheet.py" "$EVIDENCE/photos" "$EVIDENCE/clips" "$EVIDENCE/comparison.png"
```

**Time spent:** approximately **0.5 elapsed hours**, from branch creation at 09:30:38 CET through the final measurement and build-tree cleanup at about 10:00 CET. That includes model iterations, an 11 minute 44 second game build, render and verification time, with several operations overlapping. Quiet-window waiting is excluded. Hands-on modelling time was not separately timed.
