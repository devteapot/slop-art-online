# Graphics quality and 3D render scale

Controls in Settings › Play (`living/game/src/graphics.rs`, `living/game/src/ui/settings.rs`, `living/game/src/keys.rs`) that tune GPU cost on HiDPI displays and lighter GPUs while keeping the UI and HUD sharp at native resolution.

## Sub-features

- `defaults`: a fresh settings file (`quality` and `render_scale` null or missing) and no env overrides start at `Quality::High` (`Bloom::NATURAL` `max_mip_dimension = 512`, `ShadowFilteringMethod::Gaussian`, 2048 px shadow map, 3 cascades) and `RenderScale::Native` (`100%`, direct `Camera3d` rendering with no offscreen image or extra pass).
- `quality`: every tier filters shadows `Gaussian` (since look-dev 4b: `Hardware2x2` stair-stepped shadows to save 0.16-0.41 ms). `Low` (`Bloom` off, 1024 px, 2 cascades 16/60 m, `crevice_ao = false`), `Medium` (`Bloom` half-res `max_mip_dimension = 256`, 2048 px, 2 cascades 18/72 m, `crevice_ao = false`), `High` (default, `crevice_ao = true`). Tags: `settings:quality:low|medium|high`. Env override: `LIVING_GAME_QUALITY=low|medium|high`.
- `render-scale`: `67%`, `75%`, `85%`, `100%`, `Auto` (caps 3D height near 1440 px on HiDPI displays; stays native at ≤1440 px height). When scaled (`< 100%`), `Camera3d` renders to a scaled sRGB `ImageRenderTarget` whose `scale_factor` matches the output's logical viewport height, while a native-resolution `Camera2d` (`IsDefaultUiCamera`, order 1) composites it behind all Bevy UI through a fullscreen `MaterialNode<UpscaleMaterial>` (`upscale.wesl`, look-dev 4c: Catmull-Rom resampling then contrast-adaptive sharpening at `Upscale::SHARPNESS`, 1.0, both in gamma 2 (sqrt of linear), then clamped to the min and max of the 2x2 nearest source texels, so ink keeps its authored colour and the ground beside it does not halo; `LIVING_GAME_PERF=upscale=clamped|clamped-cas|bilinear` for the A/B filters, `sharpen=S` for another strength, A/B only). Tags: `settings:render_scale:67|75|85|100|auto`. Env override: `LIVING_GAME_RENDER_SCALE=67|75|85|100|auto`.
- `edge-width`: the `edges.wesl` line width is the style's width times the 3D target's pixels per logical pixel (`post.rs`, `params.z`); a fractional width mixes the outer ring of neighbours in by the fraction, so a 2x display keeps about 2 physical px at every render scale (before 4b it rounded: 1 px at Auto and 67%, 2 px at 75% and 85%). Whole widths (100% at 1x or 2x) take the same single ring as before.
- `persist`: choices save to `game.json` (`"quality"`, `"render_scale"`) once picked in Settings and reload on next launch unless overridden by env.

## How to get to it (user POV)

- Menu › Settings › Play › Quality (`Low`, `Medium`, `High`).
- Menu › Settings › Play › 3D render scale (`67%`, `75%`, `85%`, `100%`, `Auto`).

## Driving it with drive.py

Preconditions: baseline.

- Open Settings (`click:@menu;wait:0.3;click:@menu:Settings;wait:0.4`), scroll to the bottom of Play if needed (`cursor:0.55,0.5;scroll:-700;wait:0.3`), then click `@settings:quality:medium` / `@settings:quality:low` / `@settings:quality:high` and `@settings:render_scale:75` / `@settings:render_scale:100`.
- Verify `dump:` JSON: `extra.quality`, `extra.quality_saved`, `extra.render_scale`, `extra.render_scale_saved`, `extra.render_scale_px` (the 3D camera's physical viewport `[w, h]`, matching scaled pixels when `< 100%` and full output pixels at `100%`), `extra.upscale` (`{method, sharpness}` while a scaled picture is composited, `catmull-rom+cas-clamped` by default, null at 100%) and `extra.shadow_filter` (the 3D camera's `ShadowFilteringMethod`: `Gaussian` on every tier; `Hardware2x2` only under `LIVING_GAME_PERF=shadowfilter=hw`).
- `check.py --run RUN graphics` drives all of it on an island world: fresh defaults, Low, Medium + 75%, back to 100%, the settings file and the next start.
- Verify `client.log`: `settings: quality: …`, `settings: render scale: …`, and `graphics: render scale …`.

## Gotchas

- `LIVING_GAME_PERF` flags (`nobloom`, `bloom=full|half|quarter|off`, `shadowfilter=hw|gaussian`, `shadowmap=N`, `cascades=N`, `firstcascade=M`, `shadowfar=M`) override `Quality` for isolated pass benchmarking.
- At `100%` (or `Auto` at 1600×900 / 1920×1080), no `ScaledCompositeCamera` is spawned; `extra.render_scale_px` equals the full output resolution.
- Headless drives render at scale factor 1, so the edge width there is 1 px at every scale and the 2x behaviour never shows. For a live 2x look use `LIVING_GAME_WINDOW=1 LIVING_GAME_FULLSCREEN=1` (borderless fullscreen, `main.rs`; 3024x1898 on the laptop's notched display, the menu bar's strip left out) with `--size 1512x982`; a `shot:` then photographs the window.
