# classic-outline-floor: Classic character outlines at reduced render scale

**Branch** `classic-outline-floor`, from `origin/main` `8ad4eacb4`. Laptop, shared SpacetimeDB `2.14.1` at `127.0.0.1:3300`. The release client was built in `$HOME/.cache/classic-floor-target` through `build-slot` (`BUILD_SLOTS=1`), with the pinned render set `~/slop-assets/a7c606d204bb` linked into the checkout's assets.

**What changed.** `living/game/src/style.rs` only, plus the `light` feature map's Classic note.
- **Cause:** Classic's `person_width` does not thin at portrait distance (`1.75` logical px at Portrait and Near, `1.125` at 30 m; no `FacePart` or `OutlineScale` multiplier). At 1x 100%, `1.75` render px covers 2 render pixels on 75% of scanlines; at 1x 75%, `1.75 * 0.75 = 1.3125` render px drops to 1 render pixel on 69% of scanlines (and `< 1.0` render px beyond 21.8 m). Along smooth noon silhouettes, SMAA running in linear light on the scaled target blends a 1-render-pixel dark line between bright noon surfaces toward grey before `upscale.wesl` runs, washing out the ink (`(43, 28, 25)` → `(53, 42, 36)`) and opening a 21-row gap along the right hair edge (`93.4%` → `68.9%`). A 1.0-render-px floor does not bind at Portrait (`1.75 > 1.375`) and leaves it unchanged.
- **Fix:** `person_width` takes `px_per_logical` (`Camera::target_scaling_factor()`) and `scaled` (`Upscale::active`), and — gated to `scaled == true` (render scales below 100%) — floors non-zero widths at `base.clamp(LD_MIN_RENDER_PX, CLASSIC_MIN_RENDER_PX)` render pixels (`CLASSIC_MIN_RENDER_PX = 1.5`, rounded up in 1/8 px steps). At 1x 75%, Portrait/Near lift from `1.75` (`1.31` rpx) to `2.0` logical (`1.50` rpx) and Far (30 m) lifts from `1.125` (`0.84` rpx) to `1.5` logical (`1.125` rpx), preserving the distance taper. At 100% (1x and 2x) the floor is gated off so Classic is bit-identical to main; on 2x Retina (`px_per_logical >= 1.34` even at 67%) it never binds. Look-dev (`ld_person_width`) is untouched.

Evidence and measurements: `/Users/carlid/dev/slop-art-online/.local/living/lookdev/classic-outline-floor/README.md`.

## Unit tests

- `cargo test --release -p living-game`: **266 passed, 0 failed, 1 ignored**.
  - New: `style::tests::classic_outline_floor_binds_only_when_scaled`.
- `cargo test -p living-rules`: **386 passed, 0 failed, 17 ignored**.

## Runs

| World | Scenarios | Result |
|---|---|---|
| Island `verify-ui-cof-island` | `light`, `graphics` | **`light` 10/10, `graphics` 13/13** |
| Cullet `verify-ui-cof-cullet` | `looks` | **14/14** |

- **Cleanup:** both scratch databases were deleted; both answer HTTP 404.
- **Evidence:** `.local/living/verify/ui-cof-{island,cullet}/ui/`, copied to `/Users/carlid/dev/slop-art-online/.local/living/lookdev/classic-outline-floor/verify-ui/`.
- **Client logs:** no `ERROR` lines.

## Not covered

- **Live 2x Retina fullscreen captures:** not run; the floor never binds on 2x (`px_per_logical >= 1.34` even at 67%, so `ceil8(1.5 / 1.34) = 1.125 <= 1.75` and `ceil8(1.125 / 1.34) = 0.875 <= 1.125`), covered by `classic_outline_floor_binds_only_when_scaled`.
- **dev-box (Linux/AMD) re-run:** not run from the laptop.
- **Performance:** not measured; the change only adjusts `OutlineVolume::width` in `fog_outlines`.
