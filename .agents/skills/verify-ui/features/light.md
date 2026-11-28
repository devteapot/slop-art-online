# Light

The light and shading (`living/game/src/style.rs` `Look`, `CharRim`, `OutlineWeight`, `LookParams`; `contact_shadow.rs`; `daylight.rs`/`envs.rs`/`world.rs`/`island.rs`/`lookdev.rs` dusk/night local lamps and Look-dev sky stops; `post.rs`/`edges.wesl` scenery edge weight, crevice AO, colour grade, calibrated bloom and aerial depth; `sky.rs`/`sky.wesl` Look-dev sky; `terrain.wesl` calmed paving; `toon_light.wesl` `ld_*`, the look-dev branches in `toon.wesl` and `terrain.wesl`), look-dev steps 1–3 (`.local/living/lookdev/survey/PLAN.md` on the laptop). Two looks:

- **Classic** (the default): the look before look-dev step 1. Every look-dev shader term is compiled only into pipelines with the shader def `LOOKDEV` (`style.rs` `ToonKey`, `terrain.rs`, `sky.rs` `SkyKey`, `post.rs` `EdgesPipeline`), contact shadows are not spawned, look-dev-only lamps stay hidden, Bevy `ColorGrading`/`Bloom` keep main's defaults, and outlines/edges keep main's values at 100% render scale (pixel identity: see "Classic is main" below); only when 3D render scaling is active (`Upscale::active`, `< 100%`), `person_width` applies a render-pixel floor (`CLASSIC_MIN_RENDER_PX`, 1.5 render px clamped by the distance curve's own width down to `LD_MIN_RENDER_PX`) so 1x scaled silhouettes don't wash out under SMAA while 100% and 2x Retina stay unchanged. Switching the light compiles the other pipelines once.
- **Look-dev:**
  - Step 1 (four shader parts, timed one by one with `LIVING_GAME_PERF=ldsteps=N`):
    1. a sky/ground hemisphere fill in place of the flat fill (the sky's colour from above in the shadows' hue, the sunlit ground's warm bounce from below), and warmth-gated sun desaturation in shadows;
    2. the ramp: deeper cloth and scenery shadows, characters' own threshold and less brush breakup, warmer peach-rose daytime skin shadows (cool-harmonized at night);
    3. a cel-stepped specular by metallic and roughness (scenery's painted metal, copper and glass take their own values);
    4. rims: an asymmetric cel-stepped Fresnel rim on characters' sun side (hand-made hair too) with a faint cool sky rim on the far side, and scenery and ground keep a quarter of the classic rim.
  - Step 2 (contact shadows, Cullet lamps/braziers, smart outlines):
    1. a soft, foot-anchored, cool-tinted `AlphaMode::Multiply` contact shadow decal (`contact_shadow.rs`, `NotShadowCaster`, `StopPropagateOutline`) under each fitted 3D character, scaled by height/build/stance and fading while airborne;
    2. Cullet's outdoor street lamps, braziers/campfires, furnaces and ovens emit warm clustered `PointLight` pools (`Lamp::lookdev_only`, capped at 10 within 40 m and faded toward the cap cutoff so dense streets never pop) starting at dusk (`atmo.glow > 1.06`), with HDR-boosted emissives that catch bloom;
    3. ambient/time-of-day harmonized character outline tint (`ld_outline_color`, soft deep indigo at night), refined distance curve (thinner at portrait, crisp at Near/Middle, tapering at Far; widths are logical px, so a scaled 3D target keeps their display thickness, and never under one render pixel, `LD_MIN_RENDER_PX`, so thin lines don't break into dashes at 1x or below 100%), thinner per-submesh face outlines (`FacePart` / `_OUTLINE_WIDTH`), and scenery edge lines dialled down 20% (`post.rs`).
  - Step 3 (crevice AO, colour grade & bloom, aerial depth & terrain calm, sky richness):
    1. lightweight 6-tap view-space depth-horizon crevice AO inside `edges.wesl` (`CREVICE_AO` shader def, active only when Look-dev is on and `Quality::crevice_ao()` is true, i.e., `High`; off in `Medium`/`Low` and Classic), short ~0.74 m world radius fading over 20–32 m, tinted toward the cool shadow hue;
    2. time-of-day Bevy `ColorGrading` (gamma, gain, lift, exposure, white balance, post-saturation) paired with cool-shadow/warm-highlight RGB split-toning in `edges.wesl`, toned-down `Film::Soft` overlay (clearing dusk's salmon wash), and calibrated `Bloom` (`threshold = 1.05`, `threshold_softness = 0.35`, `BloomCompositeMode::Additive`); controlled by `post::Grade` (`Natural` default / `Vivid` / `Soft`);
    3. gentle cool depth-tinted aerial haze in `edges.wesl` beyond camera focus distance (~18.5–26.5 m start, stronger at dusk and night, never muddying foreground characters) plus widened tile-seam blending and calmer paving micro-contrast in `terrain.wesl`;
    4. richer azure-to-cerulean noon sky (`cullet.json` `lookdev_zenith`/`lookdev_horizon`/`lookdev_fog`, gated on Look-dev), warm-lit cloud tops with cool undersides, and bloom-catching sun-disc Mie scatter in `sky.wesl`.

The character rim (`style::CharRim`: Off, Subtle the default, Strong), outline weight (`style::OutlineWeight`: Fine, Standard the default, Bold), and colour grade (`post::Grade`: Natural the default, Vivid, Soft) are taste settings that act only with Look-dev. Characters' materials carry `ToonParams::character.x` (`lookdev.rs`, `characters/compose.rs`, `characters/outfit.rs`). It is not part of `lookdev.rs`'s material-sharing key: adding it there changed which materials share, and with that some recoloured skin by one level, in Classic.

## Sub-features

- `default`: a fresh settings file (`light`, `char_rim`, `outline_weight`, `grade` null or missing) and no `LIVING_GAME_LOOK`, `LIVING_GAME_CHAR_RIM`, `LIVING_GAME_OUTLINE_WEIGHT` or `LIVING_GAME_GRADE` start Classic with rim Subtle, outline weight Standard, grade Natural, and `crevice_ao` false; the client saves no choice until one is made.
- `choose`: Settings › Play › Light (Classic, Look-dev), Character rim (Off, Subtle, Strong), Outline weight (Fine, Standard, Bold) and Colour grade (Natural, Vivid, Soft); the log says `settings: light: <name>`, `settings: character rim: <name>`, `settings: outline weight: <name>` and `settings: colour grade: <name>`.
- `keep`: the settings file's `light`, `char_rim`, `outline_weight` and `grade`, read back at the next start.
- `start`: `LIVING_GAME_LOOK=classic|lookdev`, `LIVING_GAME_CHAR_RIM=off|subtle|strong`, `LIVING_GAME_OUTLINE_WEIGHT=fine|standard|bold` and `LIVING_GAME_GRADE=natural|vivid|soft` start in one (captures), over the settings file; also in the asset view (`LIVING_GAME_VIEW`).
- `switch`: the live script's `light:NAME`, `rim:NAME`, `outline:NAME` and `grade:NAME`, leaving open windows be.
- `pixels`: Look-dev changes the picture; Classic after Look-dev is Classic again (the two Classics far closer than either is to Look-dev); the rim and outline weight change people only; `grade:vivid` vs `grade:soft` changes the picture.

## How to get to it (user POV)

- Menu › Settings › Play › Light, Character rim, Outline weight, and Colour grade.

## Driving it with drive.py

Preconditions: baseline.

- **Scenario.** `check.py --run $R light` (with `uv run --with pillow --with numpy python`, for the pixel checks): deletes the drive's settings file; `dump:01`: `extra.light == "classic"`, `extra.char_rim == "subtle"`, `extra.outline_weight == "standard"`, `extra.grade == "natural"`, `extra.crevice_ao == false`, all `_saved` null; Settings › Light › Look-dev (`dump:02`, `extra.crevice_ao == true`), Character rim › Strong (`dump:03`), Outline weight › Bold (`dump:04`), Colour grade › Vivid (`dump:05`); the drive's `settings.json` has `"light": "lookdev"`, `"char_rim": "strong"`, `"outline_weight": "bold"`, `"grade": "vivid"`; a second drive reads them back (`dump:00`), holds a resident beside the player (`--place`), puts the cursor in the world and photographs `01_classic` … `09_grade_soft` from one view with `light:`, `rim:`, `outline:` and `grade:`. It refuses to run with `LIVING_GAME_LOOK`, `LIVING_GAME_CHAR_RIM`, `LIVING_GAME_OUTLINE_WEIGHT` or `LIVING_GAME_GRADE` set.
- **Look-dev stills.** The look-dev scene (`living/tools/lookdev_shoot.py`): the asset view with `--look lookdev` (and `--grade natural|vivid|soft`), and the Cullet plaza with `--look classic` vs `--look lookdev` (and `light:` / `grade:` switching in one drive).

## Classic is main

The client has no deterministic capture: blinking and cloud drift follow wall time, and the bloom spreads them as single-level speckles, so two runs of main's own binary differ in close-ups. Prove Classic against main's binary (built from main's worktree; the asset root is compiled in) on shots main reproduces exactly, and on the rest show the difference is no larger than main against itself:

- the asset view's play-camera stops (`near@0`, `middle@0`) of the calibration cast, and scenery models (`envs/cullet/lamp/lamp.glb` …), no sky in frame: identical;
- the Cullet plaza and the close-ups: main against main, and main against Classic, pixel for pixel (the changed pixels' share and where they are).

## Gotchas

- `light:` re-prepares every toon material once (a frame's hitch); wait about 0.8 s before a shot.
- The character rim and outline weight do nothing in Classic.
- `ldsteps` is for timing only: below 4 it drops later parts, so its pictures are not the look.
