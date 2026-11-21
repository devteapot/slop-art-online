# verify-ui: recolour-order (a shared material's recolour source, order-independent)

**2026-11-20, branch `recolour-order` from `origin/main` `75e26fcab`.** Laptop (Apple M4 Pro, Metal), Docker SpacetimeDB 2.14.1 (`sao-living_spacetimedb_1`, already running), private `CARGO_TARGET_DIR` (`~/.cache/recolour-order-target`), builds through `build-slot` with `BUILD_SLOTS=1`. No mind service and no model calls.

- **Assets:** the main checkout's bundle (generation `c4-e61b01c0`), cloned into the worktree (`cp -c`, git-ignored), so the photographs' eye holds wrote only the clones.
- **Outcome:** passed. The client change alters no surface's shape: no tables, reducers, views, controls or commands. So the feature map is unchanged.

## The change

`characters.rs` `recolor`: a type or VRoid material learns its recolour source (`recolor_from`, mode 3) from a mesh's `mean_color`.

- **Before:** the first mesh the query visited set it. Bevy's query order is archetype, then table order, and it moves when a component or resource is added.
- **Now:** every mesh that first wears the material in that frame offers its mean (`Sources`). The least `SourceKey` wins: primitive index, then file path, then mesh index, from the mesh asset's glTF label. Equal keys are settled by the colour.
- **Composed style materials** keep the source they were made with, as before.

## The order dependence on main, shown

**How:** `living-game-main-diag` is main plus a log and a switch that reverses the query's order (`.local/recolour-order/main-diag.patch`, never committed).

**The deciding frame** (asset view, four composed people) had six candidates for one toon, `M00_000_00_Body_00_SKIN`. That toon is shared by every type file through the shared pages:

| Candidate | Mesh | hsv value |
|---|---|---|
| `adult-f-a`, `adult-m-b`, `elder-f-c` bodies | `Mesh2/Primitive0`, `Skin` | 0.762 |
| The same files' neck patches | `Mesh0/Primitive5`, `Face` | 0.719 |

`Body_01_SKIN` (the far skin) and `FaceBrow_00_FACE` had one candidate from each of the three files, with slightly different means.

**What each order chose:**
- **Main's order:** `adult-f-a`'s body, far skin and brow.
- **Reversed:** `elder-f-c`'s neck patch, far skin and brow. 74,668 pixels differ from main on 24 of 49 shots, up to 49 levels.

**The S3 note corrected:** char-port-2-s3's note said main took the neck patch. In this view main takes the body, and the neck patch is what a changed order gives.

## Pixel identity

**The tool:** `.local/recolour-order/stills.sh` (the asset view, 1600×900, hour 11, springs off, eyes held), 49 shots. Every person shot is a clip-held frame (`idle@…`). A first `back` shot, discarded, lets each model settle.
- **Why clip-held:** free-posed shots of people differ from run to run on main itself.

**The subjects:**
- **Four composed people** (`look:lk_b23bcf72f485a061` adult-f-a, `lk_c10f255e70477c0c` adult-m-b, `lk_3a24378c7d67ec75` elder-f-c, `lk_785d5fa2c550b36c` child-u-b) at three-quarter, Near (`near@40`), a head close-up and side;
- **VRoid bases** (`recipe:ranger`, `scholar`, `engineer` with outfit pieces, and a look line with `LIVING_GAME_COMPOSE=0`) at the same shots;
- **Cora's hand-made file** (`docs/char-live-2/final/own-cora-live.glb`) at four shots;
- **Cullet scenery** (`ash_house`) at three shots.

**Results** (`.local/recolour-order/pixel-summary.txt`):

| Comparison | Pixels differing |
|---|---|
| Main against main, runs b and c | 0 |
| Main, run a against run b | 272, in one shot only: the child's freckle overlay at the close-up. The noise floor. |
| **Fix against main** (runs a and b against main's b and c) | **0 on all 49 shots** |
| Fix with the reversed order against main | 0. A first try differed by 93 pixels, up to 5 levels, on the elder's eye lines. The same run again gave 0, and the chosen sources were identical in both orders: 8 materials in the composed run, 30 in the VRoid run (`fixdiag-*.src`). |

## Driven

**`verify-ui-rocul`** (fresh, `--seed cullet`): `check.py looks`, **14 passed, 0 failed.**
- **Book mismatch, as S3 met it:** the world's look generation is `c4-cbcc40bf` and the bundle's book `c4-e61b01c0`, so 44 of 64 keys miss. On the bundle's book the run gave 7 passed, 7 failed.
- **The test book:** `.local/recolour-order/test_book.py` takes the bundle's book and the world's generation. It adds each of the world's 45 missing keys as a copy of the bundle line with the nearest words (form, then garments). The map is in `looks-test.json.map.json`.
- **Installed for the run only:** it went over the worktree's `characters/looks.json` and was restored afterwards.

**`verify-ui-roisl`** (fresh, `--seed island`), with the same test book: `check.py camera-lod`, **23 passed, 0 failed** (camera-lod 15, camera-lod-lol 8). No look warnings.

**Cleanup:** both databases were deleted with `$V cleanup`. The evidence is in `.local/living/verify/ui-rocul/` and `.local/living/verify/ui-roisl/`; copies of both `checks.json` and the pixel evidence are in `.local/recolour-order/`.

## Tests

- **`living-game`:** 202 passed, 1 ignored (`uneven_ground_spots`, a tool).
  - **New tests:** `source_key_reads_a_primitives_place`, and `recolour_source_does_not_hang_on_order`. The second offers all 40,320 orders of the case above and expects the same source each time; the old first-wins rule gives two different sources.
- **`living-rules ui::`:** 38 passed.

## Not covered

- **Asset arrival:** a material's first frame decides, so a mesh whose file arrives in a later frame is not a candidate, as on main. That depends on asset loading, not on system or entity order.
- **`hair`:** it wasn't run, because hair takes the grey-tag or palette paths first and its source rule is unchanged.
- **A live crowd's stills:** in a live game the deciding frame holds whichever people spawn first. Live output follows the rule, but nothing photographs it against main.
