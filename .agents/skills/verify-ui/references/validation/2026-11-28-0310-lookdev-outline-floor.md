# lookdev-outline-floor: Look-dev character outlines never under one render pixel

**Branch** `lookdev-outline-floor`, from `origin/main` `f4eab28f3`. Laptop, shared SpacetimeDB `2.14.1` at `127.0.0.1:3300`. The release client was built in `$HOME/.cache/outline-floor-target` through `build-slot` (`BUILD_SLOTS=1`), with the pinned render set `~/slop-assets/a7c606d204bb` linked into the checkout's assets.

**What changed.** `style.rs` and `graphics.rs` only, plus the `light` feature map's description of the outline width.
- **`ld_person_width`:** it no longer multiplies by the render scale. `bevy_mod_outline` widths are logical pixels, and the scaled 3D target's own scale factor already scales them. It never returns less than `LD_MIN_RENDER_PX` (1.0) render pixel, measured by the 3D camera's `target_scaling_factor`.
- **`Upscale::factor`:** removed; nothing else read it.
- **Classic:** its `person_width` is untouched.

The trigger is dev-box's 4c spot check: Look-dev Portrait and Near outlines broke into dashes at 1x output, 75%. Evidence and measurements: `/Users/carlid/dev/slop-art-online/.local/living/lookdev/outline-floor/README.md`.

## Unit tests

- `cargo test --release -p living-game`: **266 passed, 0 failed, 1 ignored**.
  - New: `style::tests::ld_outline_never_under_one_render_pixel`.
  - `ld_outline_distance_curve_thins_at_portrait_and_far_and_on_faces` is now evaluated at 2x.
- `cargo test -p living-rules`: **386 passed, 0 failed, 17 ignored**.

## Runs

**First attempt.** Scratch worlds `verify-ui-olf-island` and `verify-ui-olf-cullet` were also used for the live 2x stills. Their 10-minute leases lapsed while the build slot was held by other sessions' benchmarks. Both checks then failed at their start with `scratch world is paused`, and both worlds were cleaned up.

**Rerun on fresh worlds:**

| World | Scenarios | Result |
|---|---|---|
| Island `verify-ui-olf2-island` | `light`, `graphics` | **`light` 10/10, `graphics` 13/13** |
| Cullet `verify-ui-olf2-cullet` | `looks` | **14/14** |

- **Cleanup:** all four databases were deleted; each answers 404.
- **Evidence:** `.local/living/verify/ui-olf2-{island,cullet}/ui/`, copied to `/Users/carlid/dev/slop-art-online/.local/living/lookdev/outline-floor/verify-ui/`.
- **Client logs:** no `ERROR` lines.

## Not covered

- **Live 2x Classic at 75% with the fix.** The fullscreen captures came back black: the owner was using the laptop, and main's capture was black too then. It is covered by the unchanged code path and by bit-identical 1x Near frames.
- `windows`, `camera` and `body-clock` were not rerun. They don't read outline widths.
- **dev-box (Linux/AMD)** was not rerun.
