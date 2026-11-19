# Long hair, candidate 4

Geometry and fit checkpoint on the raised-brow head standard from `char-4-art` at `3670594b0`. The game-camera comparison and motion evaluation are pending.

The long styles have two tapered front locks per side, each with its own spring chain. The four chains use four additional upper-chest collision spheres. At heights 1.40 m and 1.30 m, the back curtain of the standard coated long third cut spans 273 mm and 260 mm respectively, measured across exported rear vertices within 30 mm of each height. In the corresponding main asset the spans were 230 mm and no vertices. The long second cut over the smock spans 277 mm and 248 mm in the same bands. Main had no rear vertices in either band.

The first front-lock path passed up to 22.2 mm inside the coat and 15.7 mm inside the smock in bind pose. The revised path follows the torso form and garment ease over the upper chest. I cast depth rays from chest-level vertices dominated by the new front joints to the front surface of the matching standard outfit. The minimum clearance was 12.5 mm for the coat (148 covered samples) and 21.8 mm for the smock (145). These values describe the standard exported assets before personal proportions and motion.

All 1,655 complete Near looks fit below 50,000 triangles. The peak is `lk_392e9ec54549841a`, the coated adult man with `shag.3`, at 40,292 triangles and 23,964 vertices. The largest worn hair mesh is `bob.3` at 11,272 triangles and 5,761 vertices. [Per-look geometry and spring counts](looks.csv) · [Geometry by part](parts.csv)

All 88 long-hair looks add 20 front-lock joints. The coat sample has 39 spring joints in total, and the smock sample has 64. The front-lock estimate is **5.46 µs per simulated character-step**. It uses the midpoint of the historical 2.4–2.6 µs/character-step measurement and its mean of 302 joints over 33 simulated characters. Multiplying 20 by 2.5 × 33 / 302 estimates the extra cost by joint count. Collider tests and fixed per-character costs affect the actual result. [Historical spring measurement](../../CHARACTERS.md)

The first raised-brow run exposed a swept-cut deviation of 3.9 mm from its position relative to the brow on the standard head. The short swept edge now follows more of the existing fringe bone's translation. The final check across 74 styles and 21 types put each type's lowest fringe 2.9 mm above its brow. Maximum deviation for an individual style was 2.7 mm. The separate brow check passed on all 21 generated types. [Fringe check by type](fringe.json)
