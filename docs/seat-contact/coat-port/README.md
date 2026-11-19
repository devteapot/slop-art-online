# Coat chains on the seeded open coats

The chainless control is the released c4-5d64f53e outfit. The candidate retains the cut, cuffs, opening, panels and silhouette of each generated garment. Each side and rear chain starts at 0.930 m. Its second joint is 60% of the way to the seeded hem, at 0.794, 0.763 and 0.785 m for cuts 0, 1 and 2 respectively. Each coat adds eight joints. All eight carry vertices in both LODs. Both LODs together retain 9,124 triangles, two primitives and one material per coat file. All 541 coat lines in the archive, including retained generations, resolve their outfit files.

The [four lookdev fittings](../../char-port-1/fittings.json) were also measured in each alternate cut. Each matched run used 16 poses per clip, fitted bounds, the height-dependent hips blend, and the same rebake of the selected library takes. The adult woman played the female ground family. The other three fittings played the original ground clips. The ten logical clips supplied 13 baked animations.

[All fitted measurements](fittings.csv) give ground penetration in world millimetres. Chair-top, chair-back and layer distances are in the checker's model millimetres. The chair is fitted to the seated trousers in sit_idle. [Layer crossings](crossings.csv) compares control and unsimulated candidate for every layer pair and clip exceeding the 2 mm threshold in either arm.

[Near, 8 m](near.png) and [Middle, 12 m](middle.png) compare springs-off standing idle and two walk phases at front and 40°. Each pair uses the same body, pose and lighting. The archived game renderer used its orbit camera at 57.999° pitch. Camera distance and central pixel scale were calibrated to the heights and vertical fields of view of the two play stops. The sheets are unscaled central crops. The [ground sheet](ground.png) is a side projection of the checker meshes at the worst sampled terrain depth in each clip.

## Elder coat front

The elder fitting has belly 0.398. Among covered front samples with at least 10% belly-joint weight, the nearest jersey sample stayed 18.3 mm inside the coat at rest, 17.8 mm inside during standing idle and 16.4 mm inside during chair idle. In the ground loop, the jersey crossed the front by 20.3 mm and the trousers by 9.5 mm. Control and candidate gave the same maxima. These are garment-to-garment normal distances. The model omits skin underneath opaque clothes.

## Residual at the woman's side panel

The worst sampled female seated-loop vertex on cut 2 lies at 0.835 m in bind pose. It carries about 60% upper leg, 25% hips and 15% spring roots. A diagnostic trial moved the eligible upper-band leg and hip shares to a spring. Its remaining model-space seated depth was 15.1 mm and it introduced trousers-through-coat crossings of 18.6 mm in walk and 21.0 mm in run. That trial was excluded.

## Review decision

The GC approved shipping the chains on the released fittings, with cut 0 excluded from child wardrobe draws. The girl in her shipped cut clears terrain throughout all three ground clips. The seated loop also clears on the man and elder. The woman's cut still reaches 17.5 mm in the loop and the elder reaches 43.3 mm on the rise. The woman's trousers still cross her coat by 36.4 mm in the ground loop, against 36.8 mm in this matched control.

Across the full 36 runs, walk, brisk walk and run all stayed below the 2 mm crossing threshold. The largest standing-idle hem displacement across the tested cuts and both meshes was 7.8 mm in model space. No unsimulated ground or chair penetration increased at the precision reported in the table. The excluded alternate fitting fails the relaxed rest rule for garment crossings. During ground sit-down on the girl in cut 0, trousers through coat increased from 5.036 mm in one sampled pose to 5.521 mm in two. Client spring-step cost and the laptop seat gate remain unmeasured.

## Ground residuals and next work

Maximum world penetration in millimetres with springs and seat contact enabled, from the shipped fittings in [the full sweep](fittings.csv).

| Fitting | Ground sit-down | Ground loop | Ground rise |
| --- | ---: | ---: | ---: |
| Woman, cut 2 | 17.90 | 17.52 | 17.52 |
| Man, cut 0 | 3.90 | 0 | 9.49 |
| Elder, cut 2 | 26.04 | 0 | 43.30 |
| Girl, cut 1 | 0 | 0 | 0 |

1. Laptop, Opus: implement a hem-against-ground constraint in the client's spring step. The next step is **not more weighting**. The discarded side-panel trial above introduced crossings in walk and run. Rerun seat gate 2a and measure spring-step cost.
2. Character assets, Astra: address garment layering at the woman's trousers and the elder's jersey against the coat front. Both crossings already occur in the ground-loop control. The woman's trousers reach 36.4 mm (control 36.8 mm) and the elder's jersey reaches 20.3 mm in both.

The [wardrobe lines diff](changed-keys.csv) compares the released generation c4-5d64f53e with c4-cbcc40bf. Six child lines changed only their coat piece and its corresponding dye key. The other 881 active keys match exactly. No current child draw wears cut 0. Historical keys remain in the client book for existing worlds.

## Shared clip bake and coat weights

The original and coat-chain measurements used the same rise take (s109, frames 0–74).
The shared dressed bake model puts all its garments in one cloth mesh. The seat
fitter selected contact by dominant bone, so a spring-weighted hem could still
count as hip or thigh support. At 0.967 s the coat-branch rise put the hips
26.57 mm below the pre-chain bake. On the same v2 fittings this moved the
16-pose rise depths from 0 to 9.49 mm for the man and from 25.60 to 43.30 mm
for the elder. Dropping all vertices influenced by secondary joints still moved the rise hips
by 29.30 mm: some of those hem vertices contributed to the reference contact
surface before spring skinning. The shared clip source therefore keeps its coat
on the original body weights. The contact fitter also skips secondary-joint
vertices on skinned inputs. Renderable wardrobe pieces retain their chains.

The usual local clip-bake command reproduces all 87 reference animations from
f7ecc7398 exactly by decoded key time and value, including the rise hips.
The coatless youth also matches all 87 reference animations. At 16 poses the
shipped man and elder reach 0 and 25.60 mm on the rise. All four shipped
fittings clear the 2 mm layer threshold in walk, brisk walk and run with
springs off and on.
