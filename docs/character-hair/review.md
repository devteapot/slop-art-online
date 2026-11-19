# Hair at the play stops

The chin-length bob now frames the jaw at 8 m. At 12 m its wider outline and darker side pieces survive better than its individual fringe points. The first trial smoothed the crown. The second added cheek panels but still ended above the jaw. A third trial moved the cut down, recessed a dark curtain behind the outer panels and split the forward fringe into four overlapping pieces. The first version of that shell was too wide. Reducing the lift preserved the longer cheek silhouette.

On the standard exported bob, I measured the full left-to-right vertex span in three height bands, divided by the span of the fitted scalp in each band. The bands were 1.66–1.70, 1.70–1.74 and 1.74–1.77 m above the mesh origin. Main measured 1.17, 1.14 and 1.16. The first larger shell measured 1.40, 1.39 and 1.47. The final cut measured 1.28, 1.25 and 1.30. This uses the scalp as a skull proxy and includes the back hair in the projected width.

The young woman's outer tips still group into a fairly square hem in profile. Shino has cleaner gaps between tips and a more continuous highlight. Middle shows the overall shape more clearly than the interior layering. Grey is still visible under the elder's kerchief, and intermediate grey can form conspicuous stripes on loose long hair.

## Six matched looks

Each sheet has Shino, main and the final trial. Bevy rendered at 1600 × 900, daylight hour 10, idle held at 1 s, eyes held open. Each distance shows front, 40° and profile. Portrait uses a common reduced crop. Near and Middle preserve source pixels using the 8 m and 12 m play stops at 58° pitch. The six controls and trials share body, face, clothes, seed and colour. Shino has her own proportions and height.

| Sheet | Near vertices | Near triangles | Hair vertices | Hair triangles |
|---|---:|---:|---:|---:|
| [Young woman](young-woman.png) | 20,200 | 33,992 | 5,454 | 10,700 |
| [Young man](young-man.png) | 16,905 | 27,798 | 3,083 | 5,872 |
| [Elder](elder.png) | 16,966 | 27,106 | 850 | 1,528 |
| [Child](child.png) | 17,666 | 29,106 | 3,509 | 6,648 |
| [Long, coat](long-coat.png) | 23,640 | 39,678 | 6,436 | 12,648 |
| [Long, smock](long-smock.png) | 20,368 | 34,348 | 5,750 | 11,288 |

## Budget and checks

- Across 1,655 book entries the largest complete Near look is `lk_392e9ec54549841a`, an adult man wearing a coat, full beard and `shag.3`. It uses 24,084 vertices and 40,540 triangles including 5,744 vertices and 11,272 triangles of hair. The largest hair mesh uses 6,478 vertices and 12,732 triangles in the long third cut on the male back. Counts use exported POSITION entries and indexed triangles on Near nodes including scalp, UV splits and all worn overlays. [All looks](looks.csv) · [Per-part mesh and material counts](parts.csv)
- All 74 hair variants retained their primitive and material assignments. The renderer reported identical mesh and named-material counts for each of the six matched pairs. Far triangle counts matched across all variants. Maximum coordinate difference in the Far hair POSITION accessors was below 4e-17 m. The shared texture changes at both distances.
- The shared neutral map encoded as 512×1024 BC7 sRGB with 11 levels and 699,088 GPU bytes. The sheets used lookdev PNG assets. The standalone encoding check covered the production format and mip chain. Windowed laptop timing and motion shimmer on the combined bundle remain shipping checks.
- The fringe check passed across 21 face types and 74 styles. The lowest fringe sat 5.1–5.6 mm above the brow across types, with a maximum 2.4 mm deviation from the standard head for a given style. The look-book drift check passed the existing one-level outfit-colour tolerance. The committed look book and generation ID were retained.
- All exported Near hair weights summed to one within quantization tolerance. Four base long-hair variants shortened their side spring chains as the shorter cheek pieces changed the sampled hanging length. The sampled rest, idle, walk and sitting frames show cap and kerchief fit and the long hair against both garments. These held frames cover specific poses and camera angles. [Pose samples](motion.jpg)
- The worktree release client built with shared sccache. The combined fold owns the full living check and scene gate. The budget figures here apply to the faces and outfits used for this comparison.
