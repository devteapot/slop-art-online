# Middle contrast after knit and dye calibration

Generation `c4-5d64f53e` has 887 lines. Of 201 coat lines, 86 (42.8%) draw dark and 115 (57.2%) draw light. The household draw and coat hues are preserved. Using the [prior histogram boundaries](../sample/README.md), final exported colours are orange/brown 66, blue 41, low saturation 40, yellow 19, purple 14, red 11 and cyan 10. Two lines moved from blue to purple at the quantized hue boundary.

## Native measurements

The release client rendered the same 15:00 meadow at the fixed Middle stop, 1280 × 720, idle at one second and 20° azimuth. Seed 20261120 sampled 30 sorted coat-line keys uniformly without replacement. The previous 15 failing identities were independently mapped to their new keys by body, proportions, identity and worn styles. The [CSV](sample.csv) includes the old keys and both group memberships. Every PNG beside it has the same three native tiles used by the [checker](../check.py).

| Group | Dark / light | Mean layers | Minimum layers | Mean figure / grass | Minimum figure / grass |
|---|---:|---:|---:|---:|---:|
| Fresh random 30 | 12 / 18 | 3.390 | 2.922 | 2.215 | 1.684 |
| Previous 15 failures | 0 / 15 | 3.265 | 2.976 | 1.796 | 1.571 |

Distinct lines rendered: 60. Failing keys: none.

## Generator constraints

In the prior 30-line capture, near-black jersey dye under a light coat rendered at 0.091–0.111 on grass at 0.406. Cutting the jersey dye alone left the additive toon rim visible. A five-line paired trial kept the dyes and mesh fixed and rounded the front knit shading normals upward. The jersey medians fell to 0.040–0.045. The accepted coat meshes retain their opening, lapels, placket, panel paint and topology. Only the coat-worn jersey uses the revised normals. The standalone jersey retains its shading.

The light coat targets 0.083–0.092 in linear dye at 1.50 m and above. The band tapers to 0.074–0.075 at 1.38 m and below. The first candidate left a fair-haired 1.33 m child at 1.471:1 against grass (trial key `lk_4cbe69c0a438389f`). All original sample identities were retained for regression, alongside the final generation’s independent sorted-key draw. Cached native tiles were reused only where the line key and the shared meshes were identical. Its jersey target is limited by both coat value and the available contrast above the knit floor. Trousers and boots target 0.004 and 0.002 while preserving their dye hues. The generator tests the final sRGB bytes against a calibrated 2.8:1 layer budget and excludes coat values whose estimated rendered upper bound would fall within 1.5:1 of meadow grass. These are per-line dye checks. The whole-figure ratios above come from the actual silhouette and local grass, including headwear, hair and body proportions.

Repeat both native checks with `python3 docs/char-port-1/value/calibrated/verify.py`. The 115 light lines change key relative to `c4-d357edaf`. The remaining 772 keys are identical. The coat-worn jersey shading is in the shared asset. [Published-to-final line-key audit](../key-changes.csv) · [Person keys](../person-keys.csv)
