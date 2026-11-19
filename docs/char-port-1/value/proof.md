# Household coat values at Middle

[Middle, 12 m](middle.png) · [Near, 8 m](near.png) · [Portrait](portrait.png)

Each column keeps the resident's original seed, body, height and hairstyle. The lower row requests the coat. The woman's long hair uses its collar fit, the man keeps his tousled hair, the elder keeps his cap, and the girl keeps her bob. The braid remains a seeded style option. Its separate forced fitting, motion samples, garment crossings and apron exclusion are documented in the [four-body fitting](../proof.md). The elder's belly and the trousers in ground sit and long strides remain apron risks. Garment geometry matches the first fitting. The revised comparison restores the original hairstyles and changes the garment colours and facing shading.

The game rendered the meadow at 15:00, 1280 × 720, idle at one second. Both play stops use the fixed 58° camera and 20° azimuth. Middle and Near show native pixels. The threshold applies to the rendered Middle crop. Coat and jersey must reach **2.5:1** and the figure against adjacent grass must reach **1.5:1**.

| Body | Coat | Layer ratio, main → port | Grass ratio, main → port | Port coat / jersey pixels | Near triangles | Vertices | Primitives, main → port | Material names, main → port |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| woman | dark | — → 4.33 | 1.34 → 2.80 | 613 / 41 | 34,192 | 21,120 | 15 → 13 | 9 → 9 |
| man | light | 1.58 → 2.63 | 1.23 → 1.67 | 1087 / 59 | 34,344 | 21,349 | 16 → 16 | 11 → 11 |
| elder | dark | 1.23 → 3.31 | 2.54 → 2.79 | 1211 / 73 | 32,422 | 20,456 | 18 → 18 | 11 → 11 |
| girl | dark | — → 3.49 | 2.38 → 2.72 | 299 / 9 | 32,006 | 19,940 | 14 → 13 | 9 → 9 |

The [checker](check.py) reads three lossless tiles per row of each [native crop](pixels). The first is the actual frame. The second marks coat and jersey with magenta and cyan to select their visible pixels. The third changes only the ground colour to isolate the figure. Layer contrast uses the median linear luminance of each garment with at least six marked pixels. Whole-figure contrast uses the median of per-pixel ratios against a 16-pixel strip of unshadowed meadow at the same scanline. Both use (lighter + 0.05) / (darker + 0.05). These measurements cover the flat meadow asset-view ground and this lighting and pose.

Run `python3 docs/char-port-1/value/check.py` to repeat the acceptance check. [Raw contrasts and sample sizes](contrast.json) · [Near geometry counts for both rows](counts.json) · [Original lines](main-lines.json) · [Port lines](port-lines.json)

## Household selection and look-book audit

A household draw selects dark coat (0.010–0.018 linear) over light jersey (0.32–0.40), or light coat (0.15–0.17) over dark jersey (0.0002–0.0005). The coat retains its dye hue. The household selects the coat value within the band and the wearer seed varies the jersey. The fold beside the opening receives a darker tone in the same material.

The published generation is `c4-e61b01c0`. Regenerating main with the available resident cache yields `c4-0d98a127`. The candidate with that same cache is `c4-d357edaf`. Across 887 entries, 246 line keys differ between the two same-cache runs. Coat cuts, collar fits, layer colours and the paint estimates derived from the built population contribute. Compared with the published generation, 714 entries differ (115 resident bands, 523 pool bands and 76 decor entries). Of these, 468 differ solely from cache drift, 142 solely from the port, and 104 from both. The checked-in generation remains published. Regenerating the resident cache can change these dry-run keys.

[Exact line keys and reasons](key-changes.csv) · [Changed resident and pool person keys](person-keys.csv)
