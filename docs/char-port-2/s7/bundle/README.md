# char-port-2 · S7 · The bundle

**Built:** 2026-11-23, 10:15–10:47, at `132a737fa` (S7 with that morning's main merged in). The manifest's commit is `257e636c9`: the same tree plus the §6 docs, committed while the build ran.
- **Port:** `hair,ink`.
- **The run:** [bundle7.log](bundle7.log).
- **The script:** `.local/char-port-2/s7/bundle7.sh` (scratch).

**Rebuilt at the merged head, against S7's final builds:**
- types: 66 files, 0 differ;
- overlays: 72 files, 0 differ;
- hair set: 189 files, 0 differ (`swept_braid` t2 0.65 on its own page).

The hair build's closing `fringe_check` looked in the wrong folder and returned non-zero. The bundle's own `fringe_check` passed on all 92 styles.

**Flag-off parity against main, 78 of 78 files identical.** The comparison checked out main's versions of the eight generator files S7 changes (`cage_head`, `face_paint`, `head_form`, `person`, `shade_mean`, `port.json`, `hair.py`, `hair_page.py`), then S7's, and built with no port flag. It covered the 21 types, four overlays, three hair styles (bob, long, braid) and the four bodies.

**The bundle's checks:** all pass.
- `eye_colours`;
- `shade_mean`: 192 files, 0 off their mean;
- `look_lines wear`;
- `skeleton_check`: 372 files, 0 bones moved;
- `book_drift`: book `c4-cbcc40bf` rebuilt identically;
- `brow_check`: 21 types;
- `fringe_check`;
- `cloth_check` on seven residents;
- `pictures check`, PNG and KTX2;
- the pages audit: 0 errors, 0 warnings.

**The files** (`~/archive/deliverables/` on the dev-box):

| File | Files inside | Size | sha256 |
|---|---|---|---|
| `char-composed-s7-257e636c.tar.gz` (PNG) | 343 | 44.6 MB | `f076a169c43be94652738b5fb8b95097df04faaea4b0ea91b05e4c0ef3669a07` |
| `char-composed-s7-257e636c-ktx2.tar.gz` (KTX2, BC7) | 558 | 48.8 MB | `61ff8495492decab9bd9bca088bb0a1abc1f05316444bbf7f770b563c56ed05d` |

**Contents** (at their repository paths): [MANIFEST.txt](MANIFEST.txt) lists every file with its sha256.
- **Types:** `lookdev/types`, the 21 S7 types and the shared ink map.
- **Pages:** `lookdev/pages`, the tint, iris and far pages and `types.json`.
- **Styles:** `lookdev/styles/{hair,outfit,overlay}`, including the 92 hair files with `swept_braid` on its own page and the 72 S7 overlays.
- **Look data:** the look book (`characters/looks.json`, generation `c4-cbcc40bf`), and Cullet's and the island's world look data.
- **At the root:** `cullet-people.json` and `MANIFEST.txt`.

**What stays out:** `lookdev/anim/own-clips.glb`. The laptop bakes its own on this skeleton, as the manifest's `clips:` line says; the dev-box's bake has 84 clips. The person files (`own-*.glb`) and the scratch builds stay out too.

**Delivery:** held. The coordinator keeps it ready until the owner says go on S8.
