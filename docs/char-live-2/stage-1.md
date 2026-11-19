# Cora target measurements

The [target sheet](stage-1-targets.jpg) pairs the two face drawings and the left profile from the turnaround with the inherited game portraits. The [baseline orbit](stage-1-inherited-orbit.png) includes the back and the 58° Near and Middle views from the final char-live-1 inspection.

Coordinates below use the original 1774 × 887 drawings, x right and y down. Heights include the hair. On the left profile the crown is at y=22 and the chin at (378,124), giving H=102 px. The lower ear attachment at (416,101) gives a 31.2° chin-to-ear rise. This chord measures the overall rise, including the portion obscured by the temple lock. From the nasal-root vertical at x=374 the brow (372,72), nose tip (363,96) and upper lip (368,106) project 2, 11 and 6 px forward. Proposed working tolerances are ±4° and ±0.02 H given the line thickness at this resolution.

On face.png the front crown and chin are at approximately y=16 and 484. The eye centres lie near (455,278) and (595,278), spanning 0.30 H. The mouth corners span about 75 px or 0.16 H. At three-quarter the crown and chin are near y=17 and 479, the eye centres near (1307,277) and (1417,277), and the mouth spans about 56 px. Eye line height is 0.56 H from the crown in both views. Preserve these proportions when adjusting depth.

The [draft calibration file](own-cora-live.calibration.json) records original pixel centres. Existing portrait centres come from the laptop contract. Zero portrait coordinates await the first corresponding rendered patches. All seven drawing swatches use a per-channel 9 × 9 median. Warm shadow uses the upper neck immediately under the jaw. Tint layers use the coordinator's new shaded tint slot.

The [image audit](stage-1-audit.json) covers every image in the inherited GLB and confirms the identical PNG bytes are packed in the source blend. The GLB hash matches char-live-1's factory replay. Fresh scene-node audit and replay await the host's Blender disk floor.

Target measurement and sheet assembly took about four minutes (16:27–16:31 UTC). Zero Blender blocks, builds, image generations or paid model calls. Token totals unavailable.
