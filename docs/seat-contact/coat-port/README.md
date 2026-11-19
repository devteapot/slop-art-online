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

Hold the bundle. The girl in her shipped cut clears terrain throughout all three ground clips. The seated loop also clears on the man and elder. The woman's cut still reaches 17.5 mm in the loop and the elder reaches 43.3 mm on the rise. The woman's trousers still cross her coat by 36.4 mm in the ground loop, against 36.8 mm in this matched control.

Across the full 36 runs, walk, brisk walk and run all stayed below the 2 mm crossing threshold. The largest standing-idle hem displacement across the tested cuts and both meshes was 7.8 mm in model space. No unsimulated ground or chair penetration increased at the precision reported in the table. One alternate fitting fails the relaxed rest rule for garment crossings. During ground sit-down on the girl in cut 0, trousers through coat increased from 5.036 mm in one sampled pose to 5.521 mm in two. Client spring-step cost and the laptop seat gate remain unmeasured.
