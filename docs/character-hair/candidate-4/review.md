# Long hair, candidate 4

Candidate 4 uses the raised-brow standard from `char-4-art` at `3670594b0`. The main comparison row uses the original brows. The final long cuts use two joints per front lock.

The long styles have two tapered front locks per side, each with its own spring chain. The four chains use four additional upper-chest collision spheres. At heights 1.40 m and 1.30 m, the back curtain of the standard coated long third cut spans 273 mm and 260 mm respectively, measured across exported rear vertices within 30 mm of each height. In the corresponding main asset the spans were 230 mm and no vertices. The long second cut over the smock spans 277 mm and 248 mm in the same bands. Main had no rear vertices in either band.

The first front-lock path passed up to 22.2 mm inside the coat and 15.7 mm inside the smock in bind pose. The revised path follows the torso form and garment ease over the upper chest. I cast depth rays from chest-level vertices dominated by the new front joints to the front surface of the matching standard outfit. The minimum clearance was 12.5 mm for the coat (148 covered samples) and 21.8 mm for the smock (145). These values describe the standard exported assets before personal proportions and motion.

All 1,655 complete Near looks fit below 50,000 triangles. Two looks tie for the peak, `lk_392e9ec54549841a` and `lk_6614893f82acd0be`, at 40,292 triangles and 23,964 vertices. The largest worn hair mesh is `bob.3` at 11,272 triangles and 5,761 vertices. [Per-look geometry and spring counts](looks.csv) · [Geometry by part](parts.csv)

All 88 long-hair looks add eight front-lock joints. The coat sample has 27 spring joints in total and the smock has 52. The front-lock estimate is **2.19 µs per simulated character-step**. It uses the midpoint of the historical 2.4–2.6 µs/character-step measurement and its mean of 302 joints over 33 simulated characters. Multiplying eight by 2.5 × 33 / 302 estimates the extra cost. Collider tests and fixed per-character costs affect the actual result. [Historical spring measurement](../../CHARACTERS.md)

The first raised-brow run exposed a swept-cut deviation of 3.9 mm from its position relative to the brow on the standard head. The short swept edge now follows more of the existing fringe bone's translation. The final check across 74 styles and 21 types put each type's lowest fringe 2.9 mm above its brow. Maximum deviation for an individual style was 2.7 mm. The separate brow check passed on all 21 generated types. [Fringe check by type](fringe.json)

## Spring budget and motion comparison

The renderer switches visibility on the character's descendant Near and Far meshes. The spring scheduler selects character roots by inherited visibility and distance, sorts them by distance, and applies its own budget. Its defaults are 48 characters and a 40 m radius scaled by character height. A character drawing its Far mesh may still simulate its hair. See [mesh visibility](../../../living/game/src/lookdev.rs) and [spring scheduling](../../../living/game/src/characters.rs).

| Joints per front lock | Front joints per long-haired person | Estimated added µs per character-step | Eight long-haired characters with spring-near (00e545b3), µs/step | 48 long-haired characters, µs/step |
|---:|---:|---:|---:|---:|
| 5, comparison | 20 | 5.46 | 43.7 | 262.3 |
| 3, comparison | 12 | 3.28 | 26.2 | 157.4 |
| **2, selected** | 8 | 2.19 | 17.5 | 104.9 |

These estimates cover the extra front joints. Each frame can advance zero to three fixed steps. The 48-character scenario assumes every selected character wears long hair. The eight-character figure assumes all eight Near slots contain long-haired characters.

The laptop reports that queued client change `00e545b3`, due after play-test 10, limits springs to eight near-drawn characters and settles newly active chains for 60 steps against the current pose. The 8-cap estimate for three joints per front lock is 26.23 µs per simulation step when all eight characters have long hair. Compare tip motion during steady walk and idle after settling. The far-to-near transition is a separate client behavior.

The comparisons show all three joint counts at the same clip times, sampled at 60 Hz after settling at the initial pose. Each row uses the same camera and garment. The two-joint tips move with the stride and preserve the pointed silhouette over the chest. Five joints give the tips more travel, especially over the smock. At Middle there was no visible stiffness advantage to the extra joints. The two-joint version had a maximum head-relative displacement bound of 0.60 pixels/frame at Near and 0.37 at Middle during the walk. During idle these maxima fell to 0.18 and 0.11. These bounds use world-space joint displacement relative to the head and the camera projection at 1600 × 900. They include ordinary pose motion. [Coat walk and idle](coat-walk-idle.webp) · [Smock walk and idle](smock-walk-idle.webp) · [All 24 motion measurements](front-lock-motion.csv)

## Middle silhouette and value

At 1600 × 900 and 12 m, the coated long cut grows from 221 to 374 visible hair pixels front-on. The smock cut grows from 253 to 439. That gain mostly comes from the locks falling over the chest. Frontal width moves only from 19 to 20 pixels on the coat and 19 to 21 on the smock. Shino spans 30 pixels and covers 470. At 40° the gain in width is clearer: 19 to 24 on the coat and 21 to 26 on the smock, against Shino's 25. These are absolute screen measurements at the characters' own heights.

For the dark coated look, the frontal difference in median linear luminance between collar and hair rises from +0.054 to +0.124, and the face-to-hair difference from +0.269 to +0.305. Shino reaches +0.270 and +0.636 respectively. At 40° the coat still gains collar separation, but face separation falls from +0.302 to +0.270. The natural blond smock locks are clear against the dark collar. The silver variant nearly matches the face at both yaws. Blond, silver and copper keep their hue in the inner curtain, although the pale bob loses much of its fringe contrast against the face.

The CSV uses a second render with magenta hair, green skin and blue garment tags. Hair width spans the outermost detected hair pixels. Face and upper-garment samples come from a five-pixel neighbourhood of the hair in the head/collar region. The CSV includes sample sizes; the young man's short cut has only five garment pixels in the frontal main sample. Luminance uses linearized sRGB. Positive face-minus-hair or collar-minus-hair means the adjacent surface is lighter. [Middle measurements at front and 40°](middle-values.csv)

The front locks stay visible over both garments through the sampled walk and seated poses. The bob reads to the chin and the long cuts read past the collar. Shino still has a broader frontal silhouette, a less blocky transition from temple to cheek, and cleaner separation between fringe points. The shared highlight wraps across the panels, but the edge reads as a heavier, streaked stripe in portrait, particularly on the brown coat look. The central part still exposes a visible break. The strongest improvement is the chest silhouette and its contrast against clothing.

[Young woman](young-woman.png) · [Young man](young-man.png) · [Elder](elder.png) · [Child](child.png) · [Long coat](long-coat.png) · [Long smock](long-smock.png) · [Rest, idle, walk and sitting](motion.jpg)

The six sheets place Middle first, then Near and portrait. Main uses the original brow and candidate 4 uses the raised brow at `3670594b0`. Each light row changes the hair palette on the same character. Build and captures used the worktree's release renderer. Windowed laptop timing with the combined bundle remains the shipping gate.
