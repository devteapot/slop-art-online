# Graphics quality and 3D render scale

Controls in Settings › Play (`living/game/src/graphics.rs`, `living/game/src/ui/settings.rs`, `living/game/src/keys.rs`) that tune GPU cost on HiDPI displays and lighter GPUs while keeping the UI and HUD sharp at native resolution.

## Sub-features

- `defaults`: a fresh settings file (`quality` and `render_scale` null or missing) and no env overrides start at `Quality::High` (`Bloom::NATURAL` `max_mip_dimension = 512`, `ShadowFilteringMethod::Gaussian`, 2048 px shadow map, 3 cascades) and `RenderScale::Native` (`100%`, direct `Camera3d` rendering with no offscreen image or extra pass).
- `quality`: `Low` (`Bloom` off, `Hardware2x2`, 1024 px, 2 cascades 16/60 m, `crevice_ao = false`), `Medium` (`Bloom` half-res `max_mip_dimension = 256`, `Hardware2x2`, 2048 px, 2 cascades 18/72 m, `crevice_ao = false`), `High` (default, `crevice_ao = true`). Tags: `settings:quality:low|medium|high`. Env override: `LIVING_GAME_QUALITY=low|medium|high`.
- `render-scale`: `67%`, `75%`, `85%`, `100%`, `Auto` (caps 3D height near 1440 px on HiDPI displays; stays native at ≤1440 px height). When scaled (`< 100%`), `Camera3d` renders to a scaled sRGB `ImageRenderTarget` whose `scale_factor` matches the output's logical viewport height, while a native-resolution `Camera2d` (`IsDefaultUiCamera`, order 1) composites the linear-filtered `ImageNode` behind all Bevy UI. Tags: `settings:render_scale:67|75|85|100|auto`. Env override: `LIVING_GAME_RENDER_SCALE=67|75|85|100|auto`.
- `persist`: choices save to `game.json` (`"quality"`, `"render_scale"`) once picked in Settings and reload on next launch unless overridden by env.

## How to get to it (user POV)

- Menu › Settings › Play › Quality (`Low`, `Medium`, `High`).
- Menu › Settings › Play › 3D render scale (`67%`, `75%`, `85%`, `100%`, `Auto`).

## Driving it with drive.py

Preconditions: baseline.

- Open Settings (`click:@menu;wait:0.3;click:@menu:Settings;wait:0.4`), scroll to the bottom of Play if needed (`cursor:0.55,0.5;scroll:-400;wait:0.3`), then click `@settings:quality:medium` / `@settings:quality:low` / `@settings:quality:high` and `@settings:render_scale:75` / `@settings:render_scale:100`.
- Verify `dump:` JSON: `extra.quality`, `extra.quality_saved`, `extra.render_scale`, `extra.render_scale_saved`, and `extra.render_scale_px` (the 3D camera's physical viewport `[w, h]`, matching scaled pixels when `< 100%` and full output pixels at `100%`).
- Verify `client.log`: `settings: quality: …`, `settings: render scale: …`, and `graphics: render scale …`.

## Gotchas

- `LIVING_GAME_PERF` flags (`nobloom`, `bloom=full|half|quarter|off`, `shadowfilter=hw|gaussian`, `shadowmap=N`, `cascades=N`, `firstcascade=M`, `shadowfar=M`) override `Quality` for isolated pass benchmarking.
- At `100%` (or `Auto` at 1600×900 / 1920×1080), no `ScaledCompositeCamera` is spawned; `extra.render_scale_px` equals the full output resolution.
