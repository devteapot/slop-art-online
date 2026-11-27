# lookdev-1-light pass 2: critic tuning pass on pinned render set a7c606d204bb

Branch `lookdev-1-light` on main `9e8547d60` (pass-2 tuning over `4886c7803`). Laptop (M4 Pro), Docker SpacetimeDB 2.14.1, private `CARGO_TARGET_DIR` (`~/.cache/lookdev1-target`), builds through `build-slot` with `BUILD_SLOTS=1`; pinned render asset set `~/slop-assets/a7c606d204bb` (`c4-cbcc40bf`) linked via `render_set.py link`; no mind service, no model calls.

- Cullet `verify-ui-ld1p2-1127-161505` (fresh, deleted after): `looks` in Look-dev **14 passed, 0 failed** (every resident in sight composed, 0 VRoid fallbacks).
- Island `verify-ui-ld1p2i-1127-162754` (fresh, deleted after): `light` **9 passed, 0 failed**; `hair` in Look-dev **11 passed, 0 failed**.
- Unit tests: `cargo test --release -p living-game` **248 passed, 0 failed, 1 ignored**; `cargo test -p living-rules` **382 passed, 0 failed, 17 ignored**.
- Classic against main (`9e8547d60`), pixel by pixel on pinned render set `a7c606d204bb`: scenery props 12/16 identical (0 px differ outside drifting sky clouds at noon/dusk/night); composed characters play-camera stops (`near@0`, `middle@0`) 6/6 exact 0 px differ at dusk and night, 4/6 exact 0 px at noon (1 blink + 1 px bloom); evidence `/Users/carlid/dev/slop-art-online/.local/living/lookdev/step1/pass2/identity/identity.txt`.
- Pass-2 stills and frame-time evidence: `/Users/carlid/dev/slop-art-online/.local/living/lookdev/step1/pass2/`.
- Not covered: the gate's `seat`, `camera-faces`, `camera-lod`, `far`, `body-clock`.
