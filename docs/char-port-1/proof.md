# Four-body coat and braid fitting

The [revised household values and original-hairstyle comparison](value/proof.md) supersede the dye values and front comparison below. This first fitting retains the four forced braids for the separate scalp and collar test.

[Middle, 12 m](middle.jpg) · [Near, 8 m](near.jpg) · [Portrait](portrait.jpg) · [Back](back.jpg) · [Profile](profile.jpg)

Each sheet uses the original recipe in the upper row and the same body, identity and seed wearing the open coat and single braid below. Middle and Near are central crops of the fixed play stops, photographed at the same scale.

| Body | Near triangles, main → port | Vertices | Primitives | Material names | Hair primitives |
|---|---:|---:|---:|---:|---:|
| woman | 30,264 → 32,128 | 18,322 → 20,004 | 15 → 13 | 9 → 9 | 1 → 1 |
| man | 33,304 → 34,960 | 20,490 → 21,510 | 16 → 16 | 11 → 11 | 1 → 1 |
| elder | 31,382 → 35,654 | 19,597 → 21,963 | 18 → 17 | 11 → 11 | 1 → 1 |
| girl | 27,582 → 32,314 | 16,809 → 20,026 | 14 → 13 | 9 → 9 | 1 → 1 |

Counts sum the near primitives in the type and worn files. A material shared across files counts once by name.

## Garment crossings

Maximum distance in millimetres that an inner garment crossed its outer garment, across all measured layer pairs at 12 samples per clip. Each cell gives main → port. The JSON files list the pairs, times, bones, number of affected frames and seat contact separately.

| Body | Idle | Walk | Run | Chair | Ground |
|---|---:|---:|---:|---:|---:|
| woman | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 | 31.3 → 36.1 |
| man | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 | 18.7 → 18.8 |
| elder | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 | 21.6 → 21.6 | 15.0 → 15.0 |
| girl | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 | 26.0 → 1.0 |

Motion plates show three held times per clip in idle, walk, run, chair and ground order. [woman](motion-woman.jpg) · [man](motion-man.jpg) · [elder](motion-elder.jpg) · [girl](motion-girl.jpg)

The Cora apron and its ties are excluded. The original fit allowed the trousers through on the ground and in stride. Seated belly clearance on the heavy elder remains unmeasured for that apron.

## Braid clearance

| Body | Root to scalp, mm | Upper-back/collar intersections, first → final | Left ear visible | Right ear visible |
|---|---:|---:|---:|---:|
| Woman | 0.016 | 0 → 0 | 3/3 | 3/3 |
| Man | 0.812 | 173 → 0 | 1/3 | 1/3 |
| Elder | 0.770 | 328 → 0 | 1/3 | 1/3 |
| Girl | 1.592 | 0 → 0 | 3/3 | 3/3 |

The distances use the root joint and nearest skin triangle after identity and proportions, in the type rig's metres before scene height fitting. Intersections count distinct braid triangles touching rear cloth above the upper-chest joint in that pose. Each ear score counts unobstructed lateral rays to its pivot and points 8 mm above and below it. The man and elder have partial ear coverage. The numerical measurements cover rest. The motion plates and turned-head views show the animated fit. [First fit](braid-first-fit.json) · [Final fit](braid.json) · [Turned heads](neck-turn.jpg)

The motion loops use six held times per clip across all four bodies. [Idle](idle.webp) · [Walk](walk.webp) · [Run](run.webp) · [Chair](sit_idle.webp) · [Ground](sit_ground.webp)

## Generator and reproduction

The fitting lines record both arms, the identity, type, seed, age, proportions and build. The control uses the coordinator's supplied lookdev assets. Both arms use the same release client built at main revision `8851982d2` and a rebake of all 84 available picked clips. The camera pitch is 58° at both stops. Middle is 12 m with a 44° field of view. Near is 8 m with a 42° field of view. [Fitting lines](fittings.json)

Select `outfit.coat=coat` for the open coat or `none` for the standalone jersey. A seed selects one of three cuts. Set `outfit.coat_cut` to 0, 1 or 2 to retain a cut while varying its dye. Each cut carries its hem, opening and cuff depth. The household or family sets the coat dye's target luminance within 0.25–0.34, while the wearer sets the jersey's within 0.075–0.105. These are linear dye targets before shading. Excluding the apron leaves three garment bands. The checked-in look book stays at `c4-e61b01c0`. Rebuilding it will change affected lines and keys.

The port reuses the garment shoulders and sleeve seam from `142baa72c`, the neckline and neck flare from `b670baba2`, and the fitted lapels and placket from `7e2a772f2` on `char-4-combined`. The value adjustment follows that branch's use of linear-light targets and separate household and wearer draws. The procedural panels use the existing cloth colour attribute and material. Cora's replay supplied the pocket and cuff construction and the three-strand crossing order, taper, binding and brush. Generated export checks the joined cloth's active colour and the resulting GLB's `COLOR_0`.

To repeat the crossing measurement, extract either `main` or `port` for one body from `fittings.json` to a line file and use the matching generated outfit and type files. The ground comparison uses the common cross-legged clip for all four bodies.

```sh
python3 living/tools/characters/cloth_check.py line.json --terrain --seat-contact \
  --clip idle,walk,run,sit_idle,sit_ground --frames 12 --json crossings.json
```

The standalone jersey exports 4,320 near triangles in each form. The coat-worn export keeps 2,128. Each has one primitive with vertex colour. The ten cloth dyes reached each of the four endpoint luminances to within 1e−8 across twenty seeds. Child wardrobe draws now include the coat, and existing explicit recipes retain their chosen outfit.

Repeat the static braid measurements with the Blender shim and the [measurement script](measure_braid.py) from the worktree root.

```sh
"$HOME/.local/share/slop-tools/build-bin/blender" -b --python-exit-code 1 -P docs/char-port-1/measure_braid.py
```

## Dye values used in the fittings

Linear luminance of the sRGB colours sent in each composed line, before toon lighting and texture.

| Body | Hair | Coat | Jersey | Trousers |
|---|---:|---:|---:|---:|
| woman | 0.033 | 0.299 | 0.078 | 0.040 |
| man | 0.010 | 0.287 | 0.091 | 0.040 |
| elder | 0.428 | 0.338 | 0.084 | 0.040 |
| girl | 0.019 | 0.312 | 0.084 | 0.040 |

The release asset viewer also counted every attached mesh, including far geometry. All four final reports found vertex colours.

| Body | Attached meshes, main → port | Attached triangles, main → port |
|---|---:|---:|
| woman | 23 → 19 | 37,046 → 38,986 |
| man | 23 → 23 | 39,948 → 42,296 |
| elder | 26 → 24 | 37,288 → 42,962 |
| girl | 21 → 19 | 33,852 → 39,246 |
