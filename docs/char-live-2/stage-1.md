# Cora target measurements

The [target sheet](stage-1-targets.jpg) pairs the two face drawings and the left profile from the turnaround with the inherited game portraits. The [baseline orbit](stage-1-inherited-orbit.png) includes the back and the 58° Near and Middle views from the final char-live-1 inspection.

Coordinates below use the original 1774 × 887 drawings, x right and y down. Heights include the hair. On the left profile the crown is at y=22 and the chin at (378,124), giving H=102 px. The lower ear attachment at (416,101) gives a 31.2° chin-to-ear rise. This chord measures the overall rise, including the portion obscured by the temple lock. From the nasal-root vertical at x=374 the brow (372,72), nose tip (363,96) and upper lip (368,106) project 2, 11 and 6 px forward. Reviewer tolerances are ±4° for the jaw, ±0.01 H for brow and upper lip and ±0.015 H for the nose.

On face.png the front crown and chin are at approximately y=16 and 484. The eye centres lie near (455,278) and (595,278), spanning 0.30 H. The mouth corners span about 75 px or 0.16 H. At three-quarter the crown and chin are near y=17 and 479, the eye centres near (1307,277) and (1417,277), and the mouth spans about 56 px. Eye line height is 0.56 H from the crown in both views. Preserve these proportions when adjusting depth.

The [draft calibration file](own-cora-live.calibration.json) records original pixel centres. Existing portrait centres come from the laptop contract. Zero portrait coordinates await the first corresponding rendered patches. All seven drawing swatches use a per-channel 9 × 9 median. Warm shadow uses the upper neck immediately under the jaw. Tint layers use the coordinator's new shaded tint slot.

The [image audit](stage-1-audit.json) covers every image in the inherited GLB and confirms the identical PNG bytes are packed in the source blend. The GLB hash matches char-live-1's factory replay. A fresh factory replay reproduced the byte-identical GLB and the full six-view contact sheet pixel for pixel. The final scene-node audit found 26 materials, the same three generator images, and zero failures.

Target measurement and sheet assembly took about four minutes (16:27–16:31 UTC). Zero Blender blocks, builds, image generations or paid model calls. Token totals unavailable.


## Volume and colour targets

On the front portrait the maximum hair spread is about 484 px (x=255–739). The visible cheek width is about 259 px at y=328 (x≈404–663), giving 1.87 face widths. Allow ±0.10. The frontal skull is hidden. Fitting the smooth skull arc from the exposed forehead and temple gives an estimated apex y≈61 against crown y=16, a lift of 0.096 H; allow ±0.035 H for that inference. In the turnaround left profile, the widest rear sweep reaches x≈470 behind the lower ear attachment at x=416. Target 0.53 H of depth, ±0.04 H, excluding the braid. Count distinct separated lock tips including the hanging jaw and neck strands, once per tip. I count about ten front and nine three-quarter; allow ±2 tips per view. Shared contours inside the mass do not count.

Using an upper-sweep hair mask on the front portrait, the 97th percentile of display luma (0.2126 R + 0.7152 G + 0.0722 B) was 114.2. A 9 × 9 patch wholly inside the bright streak at (472,114) gives (187,99,63), luma 115.1. The lit body target stays (171,88,56). The drawing cheek minus base is (−6,−19,−20). Check both absolute cheek colour (±10/channel) and the green and blue drops from the calibrated base; proposed relative tolerance ±6 for each drop. The shadow target is (192,121,90).
