# char-port-2 · S6 · The volume step (after the GC's eye-spacing acceptance)

**Why:** all three cuts were under the band on their own sides: 2.838, 2.871 and 2.812, against 2.973–3.319 ([../README.md](../README.md)). The GC's rule puts volume only on a cut outside the band, and every cut was, so it goes on the master.

## What changed (`hair.MASTERS["swept_braid"]`)

- **Volume at the sides, from mass, not tips.**
  - **The mechanism:** the sheets' `off`, a stand-off over the head that grows from the root along each column. The sweep gets 19 mm, coming in over 55% of each column's length (`off_from`, a new sheet option whose default, 0.25, leaves every other style as it was). The near section gets 14 mm.
  - **Why not lift:** a lock's lift holds it at one height off the head over its whole length, so raising it lifted the crown as much as the sides (crown lift 0.142–0.152, against Cora's 0.131).
  - **Why not volume:** the sheets' swell (`volume`) added 1 px.
- **Flare:** the sweep's flare is down from 0.012 to 0.006. With the sheet standing out, its outer hem point broke the front outline at 0.012 (10 px).
- **Points and tips:**
  - the near section has its fifth point (the GC's: the spread allows it);
  - both sections' points are a little longer (depth 0.030);
  - three jaw strands a side, where there were two.
- **The plait's lobes** turn their lower faces down less (`crest_up` −0.20), which keeps the plait's luma within 5% at both stops with the fuller sides beside it.
- **The seeded cuts' 3D guard:** the spread is held about the master's own value, 2.006 ± 0.10, in place of Cora's 3D 1.87 ± 0.10. The S6 acceptance is the image measure, which this head's wide face takes to 2.0 in 3D. Crown lift and rear depth stay Cora's.

## The acceptance: hair body over eye spacing, each cut on its own side

[spread/](spread/): `image_spread.py` at idle 2.0 s.

| Cut | Body / eye spacing (band 2.973–3.319, target 3.146) | In band | Before | Cheek measure (report only; the drawing's 1.823) |
|---|---|---|---|---|
| `swept_braid` (cut 1, Cora's side) | **3.119** | yes | 2.838 | 1.615 |
| `.2` | **3.135** | yes | 2.871 | 1.622 |
| `.3` | **3.077** | yes | 2.812 | 1.593 |

## The re-checks

| Check | Result |
|---|---|
| **Flyaways** (the outline check, 4 px), [outline.png](outline.png) | front 1.0 px, three-quarter 1.0, back 1.4: all pass. Profile (not held) 13.2: the fringe ends over the brow, side-on |
| **The fit** (char-port-1's checks, 9 female types × 3 cuts over a coat), [plait-fit.json](plait-fit.json) | 0 plait triangles touching the collar or upper back; root to scalp ≤ 0.906 mm |
| **The ears** | 3 of 3 rays open each side, on all 27 |
| **The plait at play distance**, [measure-crest.json](measure-crest.json), [back-views.png](back-views.png) | width 7.18 px Near (drawn 7.4, −0.22) and 4.70 Middle (4.6, +0.10); luma 66.7 (−3.5%) and 69.4 (+0.4%) against the drawn 69.1 |
| **Tips**, [tips.png](tips.png) | front 9 (10 ± 2); three-quarter 7 (7–8; marks 3 and 4 may be one lock) |
| **The silhouette guard** (3D) | spread 2.002 / 2.004 / 1.959; crown lift 0.113 / 0.116 / 0.118; rear depth 0.567 |
| **Triangles** (near mesh, ≤ 12,000) | cut 1 11,632; `.2` 11,508; `.3` 10,840 |
| **Flag off** (ten styles against main) | byte-identical, the same file list |

[front-parts.png](front-parts.png) shows the front set and its parts ID.
