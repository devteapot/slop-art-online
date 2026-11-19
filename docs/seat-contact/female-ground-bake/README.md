# Ground-sit clips for the female outfit family

The shared clip file is `lookdev/anim/own-clips.glb`. Regenerate it with the usual `ONLY=present LOD=near living/tools/blender/gen_person.sh clips=man` and the picked Kimodo library. Each ground entry generates its original and its female variant. The bake generates the same female trousers and boots used by the outfit generator, fits the seat and sole vertices to the shared ground pose, and accounts for the generated female foot scale.

## Laptop playback selector

| Logical clip | Animation for the female outfit family |
|---|---|
| `sit_ground_down` | `sit_ground_down_f` |
| `sit_ground` | `sit_ground_f` |
| `stand_up_ground` | `stand_up_ground_f` |

For the initial selector, use the variants on generated adult types (`adult-*`) wearing `trousers-f` and `boots-f`. Use the originals for children, youths, elders and the male outfit family. The two pieces identify the actual geometry, including form overrides. The elder-f trial below is the reason for the elder exception.

Keep the logical ground motion for state, timing, ground contact and the `sit-hips` height blend. Resolve its animation name at playback for both transitions and the loop. Fall back to the original animation when a shared library predates these variants. The same mapping applies to asset-view playback.

## Verification

The shared reference was regenerated from the 84 picked entries on the dev-box. All original sampler times, values, interpolation modes, channel targets and sidecar entries match main, including the three original ground clips. The three additional animations bring the total to 87. Both boots mark the full seated loop as planted. The standing ends match the originals, and the descent, loop and rise join within 0.001° and 0.001 mm. [Channel hashes](channel-hashes.csv)

The fitted tool from `origin/sit-hips` at `9b526a9bc` evaluated 32 samples per clip with `--terrain --ground-hips height`. For the family trial the three variant animation names were mapped to their logical names in a measurement copy, so the tool applied the actual ground-clip height rule. Signed seated boot and trousers heights below are world millimetres. [Main](main.csv) · [Family trial, including the elder-f experiment](family-trial.csv)

| Body | Main boots | Variant boots | Main trousers | Variant trousers |
|---|---:|---:|---:|---:|
| Average woman, 1.68 m | +14.91 | −0.02 | +30.25 | +0.54 |
| Short woman, 1.55 m | +13.95 | +0.06 | +29.29 | +1.88 |
| Elder woman, 1.69 m, experimental selection | +16.43 | +2.35 | +31.24 | +0.95 |

With the selector specified above, the average man, child, elder man and elder woman produced byte-identical height CSVs versus main across all 96 samples per body.

**Garment clearance.** A second check with springs and seat contact enabled (16 samples per clip) found seated smock hems 22.56 mm below terrain on the average woman and 13.23 mm below on the short woman. Main placed them 6.53 and 13.62 mm above terrain. Their peak rise penetrations increased from 23.88 to 49.97 mm and from 21.07 to 33.51 mm, respectively. The elder woman's experimental variant also lowers the smock below terrain (−19.74 mm seated) and its minimum rise boot clearance goes from −2.54 to −9.67 mm. Retaining her original preserves the elder baseline. These results cover the fitted tool and exported animations. The laptop's selector plays them live: [sit-f-select.md](../sit-f-select.md) (branch `sit-f-select`), which reproduces these numbers in the tool and the client.
