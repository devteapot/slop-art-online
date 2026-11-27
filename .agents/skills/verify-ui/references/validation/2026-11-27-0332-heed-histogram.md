# heed-histogram: full 10-word cloth histogram & same-transaction `pin_at` card drop

**Branch** `heed-histogram` (from `origin/main` `e220bea8e`; follows `2026-11-27-0306-heed-client-2-pass3.md`). Laptop, shared SpacetimeDB `v2.14.1` at `127.0.0.1:3300`, release client built in `$HOME/.cache/heed-client-target` via `build-slot` (`BUILD_SLOTS=1`), assets linked from the main checkout.

**What changed** (game client, verify-ui checks and docs only; authority, bindings and `net.rs` untouched; [features/heed.md](../../features/heed.md), docs/ATTENTION_BUDGET.md "Built: the client side"):
- **Full 10-word cloth histogram (`living/game/src/throng.rs`):** Replaced `Row.colours` (`colour_a/b/c`, deprecated) with `Row.cloths: [u8; 10]` read from `SeenThrong.cloth_yellow`..`cloth_grey` in `living_rules::look::CLOTH` order. `tops_with` apportions each cell's `people` cards across all ten words in proportion to their histogram counts (largest-remainder scaling when the histogram sum exceeds `people`; only a remainder of person cards with no word left — lookless people — and bookless words like `grey` stay neutral; animals never take cloth colours), keeping deterministic smooth interleaving. Removed all client reads of `colour_a/b/c`. Dump field switched from `colours` to `cloths`.
- **Same-transaction `pin_at` card drop (`living/game/src/throng.rs`, `living/game/src/heed.rs`):** Extracted `Throng::step_frame` from `draw`; when a square shrinks (`count` drops) on the same frame as a newly marked/perceived individual arrives in the square, the live card closest to that individual is swapped into the fading tail (`target = 0.0`, `to = at`, `AlphaMode::Blend`), crossfading out over `OUT_S` with no pop and zero frames holding the old live card count alongside the individual (and deleted rows move directly into `leaving` on the arrival frame). `Heed` records `last_pick_cell` (`{cell, before, after}`) from `net::throng` on the exact frame `find_picked` sees the newly admitted `seen_characters` row.
- **verify-ui (`check.py`, `features/heed.md`):** Updated `throng_rows`, `rows_match`, `_expected_cloth_alloc`, `squares_ok` and `heed-throng` to validate all 10 `cloth_*` columns against owner SQL and verify dense cells draw >3 distinct look-book swatches; added a `heed-pins` check verifying `pin_at` removes E from its throng cell in the same update (`last_pick_cell == {cell: [51, 55], before: 1, after: 0}`, square absent from both client dump and authority SQL).

## Unit tests

- `cargo test --release -p living-game`: **238 passed, 0 failed, 1 ignored** (`ik::spots::uneven_ground_spots`), including:
  - `throng::tests::tops_apportion_the_full_ten_word_histogram_and_never_tint_animals` (full 8-word exact fit, sum below person count, sum above person count with largest-remainder scaling, bookless `grey`, mixed people/wolves/deer, all-lookless row);
  - `throng::tests::tops_interleave_deterministically_and_ignore_deprecated_colour_a_b_c` (deterministic smooth interleaving and proof that conflicting/populated `colour_a/b/c` fields are ignored);
  - `throng::tests::pin_at_same_transaction_drops_card_on_arrival_frame_without_pop` (real Bevy `World` frame-by-frame test for both 1→0 deleted cell and 4→3 shrunken cell with promoted individual in `marked_pts`).

## Runs

Island scenarios on scratch world `verify-ui-hist-isl` (deleted after run; evidence kept in `.local/living/verify/ui-hist-isl/`):
- `battle-views` **144/144** (regression, laws off).
- `heed-pins` **18/18** (including `last_pick_cell` `{cell: [51, 55], before: 1, after: 0}` on the arrival frame and cell removal on client & authority).
- `heed-throng` **20/20** (`on` and `far`: all 10 `cloth_*` columns matched against owner SQL, dense cells carrying 4–9 distinct swatches; `on` 95/101 tinted = 5.9% neutral, `far` 89/92 tinted = 3.3% neutral).
- Total: **182 passed, 0 failed** (`ui-hist-isl/ui/checks.json`), zero `ERROR` lines across all `client.log` files.

## Cullet plaza stills

Captured on fresh scratch Cullet world `verify-ui-hist-cul-50184` (deleted after capture; evidence in `.local/living/verify/ui-hist-cul-50184/`) on Cullet's flat arrival plaza `(540, 769)` (200-fighter sides battle at ~25–35 s, noon, heed on, zero `ERROR` lines). Three stills (`01_centre_middle.png`, `02_centre_far.png`, `03_edge_far.png`), `summary.json`, and `README.md` saved in `/Users/carlid/dev/slop-art-online/.local/living/heed-check/histogram/`:
- **Neutral-card share before (top-3 `colour_a/b/c`):** ~26.5% (`35/132` on `heed-client-2` `cul13`; 23.19% = `77/332` computed on these exact 3 shots).
- **Neutral-card share after (full 10-word histogram):** **5.42%** combined (`18/332`: **3.97%** in `01_centre_middle`, **3.80%** in `02_centre_far`, **7.87%** in `03_edge_far`), with big cells (`count >= 10`) carrying 5–8 distinct look-book swatches and remaining neutral cards purely from `about()` quantization shortfall.

## Laws-off identity

- `living/game/src/net.rs` is untouched (`git diff origin/main -- living/game/src/net.rs` is empty); `net::cue_tests::heed_off_leaves_every_set_as_it_was_and_on_adds_only_the_throng` passes; `battle-views` (144/144) and `heed-throng`'s laws-off checks pass.

## Not covered

- `heed-refusal` was not re-driven separately (refusal paths in `heed.rs` were unchanged; `heed-pins` exercised both the 5th-pin and empty `pin_at` refusals).
- Frame time with the throng drawn and dev-box's render pass; a real interactive window / hardware trackpad.
