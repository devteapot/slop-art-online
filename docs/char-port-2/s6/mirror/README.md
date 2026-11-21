# char-port-2 · S6 · The mirror check (kept for the laptop's client track)

**Kept, not to be deleted in later steps** (the coordinator's instruction).

These are the same seed of `swept_braid` (cut 1, seed 2015), parted each way. The generator writes them as exact mirrors: every part's reach, the sweep's 754 and the near section's 544 vertices (to under 1 mm), the bone weights, and the file composed onto adult-f-b offline. Main's client draws them differently: 208 against 192 px of hair at the front portrait, idle 2.0 s, with the near section standing as a slab over the cheek on one side only. The laptop has taken that as its own track. **Its answer ([hair-mirror](../../hair-mirror/README.md)):** the idle clip turns the head 11–12° at 2.0 s. In the bind pose, the two builds draw 201 and 201 px wide, as mirrors (mismatch 0.028).

## The builds (read-only)

| Build | Path (on the dev-box) | sha256 |
|---|---|---|
| Parted left (`SLOP_MASTER_PARTING=-0.55`, Cora's side) | `/home/carlid/.t3/worktrees/slop-art-online/t3-3fb95567-51da5b50b200809d/.local/char-port-2/s6/mirror-keep/parted-left/swept_braid.glb` | `a041bb5ee67948e00799ab52ba3c195be1d2cd529d38ba3a54bd39993d7d826a` |
| Parted right (`SLOP_MASTER_PARTING=0.55`) | `/home/carlid/.t3/worktrees/slop-art-online/t3-3fb95567-51da5b50b200809d/.local/char-port-2/s6/mirror-keep/parted-right/swept_braid.glb` | `0ec541e539d922a3705db61b718d90cb9a918c1b39e0e9d1d5e876eb79e5ecfe` |

**What each folder holds:**
- **The style file,** paged by `hair_page.py`, exactly as rendered.
- **Its own page,** `hair-masks.png` and `hair-masks.json`.
- **`swept_braid.hairpage.json`,** with its measures: `measures.parts_x` gives each part's reach.

**Built** by this branch at `a00beb7d0` with `SLOP_PORT=hair,masters` through `gen_styles.sh hair/swept_braid`.

**To draw one,** copy it to `living/game/assets/lookdev/styles/hair/swept_braid.glb`, and its page to `hair-masks.png` beside it. Both files name their page `lookdev/styles/hair/hair-masks.png`.

## The evidence here

- **[render-pair.png](render-pair.png):** main's client (`b8c88d3fe`) at the front portrait, idle 2.0 s. Left to right: the left build, the right build, and the left build mirrored.
- **[mirror.json](mirror.json):** the 3D measures of both builds, the vertex check, and the image measure of each.
- **The measuring tools:**
  - [image_spread.py](../image_spread.py), the acceptance measure;
  - [drawing_spread.py](../drawing_spread.py);
  - [part_id.py](../part_id.py): `--all` and `--none` copies.
