# Light

The light and shading (`living/game/src/style.rs` `Look`, `CharRim`, `OutlineWeight`, `LookParams`; `contact_shadow.rs`; `daylight.rs`/`envs.rs`/`world.rs`/`island.rs`/`lookdev.rs` dusk/night local lamps; `post.rs` scenery edge weight; `toon_light.wesl` `ld_*`, the look-dev branches in `toon.wesl` and `terrain.wesl`), look-dev steps 1–2 (`.local/living/lookdev/survey/PLAN.md` on the laptop). Two looks:

- **Classic** (the default): the look before look-dev step 1. Every look-dev shader term is compiled only into pipelines with the shader def `LOOKDEV` (`style.rs` `ToonKey`, from `ToonParams::look.x`; `terrain.rs` the same for the ground), contact shadows are not spawned, look-dev-only lamps stay hidden and outlines/edges keep main's values, so Classic's image is main's (pixel identity: see "Classic is main" below). Switching the light compiles the other pipelines once.
- **Look-dev:**
  - Step 1 (four shader parts, timed one by one with `LIVING_GAME_PERF=ldsteps=N`):
    1. a sky/ground hemisphere fill in place of the flat fill (the sky's colour from above in the shadows' hue, the sunlit ground's warm bounce from below), and warmth-gated sun desaturation in shadows;
    2. the ramp: deeper cloth and scenery shadows, characters' own threshold and less brush breakup, warmer peach-rose daytime skin shadows (cool-harmonized at night);
    3. a cel-stepped specular by metallic and roughness (scenery's painted metal, copper and glass take their own values);
    4. rims: an asymmetric cel-stepped Fresnel rim on characters' sun side (hand-made hair too) with a faint cool sky rim on the far side, and scenery and ground keep a quarter of the classic rim.
  - Step 2 (contact shadows, Cullet lamps/braziers, smart outlines):
    1. a soft, foot-anchored, cool-tinted `AlphaMode::Multiply` contact shadow decal (`contact_shadow.rs`, `NotShadowCaster`, `StopPropagateOutline`) under each fitted 3D character, scaled by height/build/stance and fading while airborne;
    2. Cullet's outdoor street lamps, braziers/campfires, furnaces and ovens emit warm clustered `PointLight` pools (`Lamp::lookdev_only`, capped at 10 within 40 m) starting at dusk (`atmo.glow > 1.08`), with HDR-boosted emissives that catch bloom;
    3. ambient/time-of-day harmonized character outline tint (`ld_outline_color`), refined distance curve (thinner at portrait, crisp at Near/Middle, tapering at Far), thinner per-submesh face outlines (`FacePart` / `_OUTLINE_WIDTH`), and scenery edge lines dialled down 20% (`post.rs`).

The character rim (`style::CharRim`: Off, Subtle the default, Strong) and outline weight (`style::OutlineWeight`: Fine, Standard the default, Bold) are taste settings that act only with Look-dev. Characters' materials carry `ToonParams::character.x` (`lookdev.rs`, `characters/compose.rs`, `characters/outfit.rs`). It is not part of `lookdev.rs`'s material-sharing key: adding it there changed which materials share, and with that some recoloured skin by one level, in Classic.

## Sub-features

- `default`: a fresh settings file (`light`, `char_rim`, `outline_weight` null or missing) and no `LIVING_GAME_LOOK`, `LIVING_GAME_CHAR_RIM` or `LIVING_GAME_OUTLINE_WEIGHT` start Classic with rim Subtle and outline weight Standard; the client saves no choice until one is made.
- `choose`: Settings › Play › Light (Classic, Look-dev), Character rim (Off, Subtle, Strong) and Outline weight (Fine, Standard, Bold); the log says `settings: light: <name>`, `settings: character rim: <name>` and `settings: outline weight: <name>`.
- `keep`: the settings file's `light`, `char_rim` and `outline_weight`, read back at the next start.
- `start`: `LIVING_GAME_LOOK=classic|lookdev`, `LIVING_GAME_CHAR_RIM=off|subtle|strong` and `LIVING_GAME_OUTLINE_WEIGHT=fine|standard|bold` start in one (captures), over the settings file; also in the asset view (`LIVING_GAME_VIEW`).
- `switch`: the live script's `light:NAME`, `rim:NAME` and `outline:NAME`, leaving open windows be.
- `pixels`: Look-dev changes the picture; Classic after Look-dev is Classic again (the two Classics far closer than either is to Look-dev); the rim and outline weight change people only.

## How to get to it (user POV)

- Menu › Settings › Play › Light, Character rim, and Outline weight.

## Driving it with drive.py

Preconditions: baseline.

- **Scenario.** `check.py --run $R light` (with `uv run --with pillow --with numpy python`, for the pixel checks): deletes the drive's settings file; `dump:01`: `extra.light == "classic"`, `extra.char_rim == "subtle"`, `extra.outline_weight == "standard"`, all `_saved` null; Settings › Light › Look-dev (`dump:02`), Character rim › Strong (`dump:03`), Outline weight › Bold (`dump:04`); the drive's `settings.json` has `"light": "lookdev"`, `"char_rim": "strong"`, `"outline_weight": "bold"`; a second drive reads them back (`dump:00`), holds a resident beside the player (`--place`), puts the cursor in the world and photographs `01_classic`, `02_lookdev`, `03_classic`, `04_rim_strong`, `05_rim_off`, `06_outline_bold` and `07_outline_fine` from one view with `light:`, `rim:` and `outline:`. It refuses to run with `LIVING_GAME_LOOK`, `LIVING_GAME_CHAR_RIM` or `LIVING_GAME_OUTLINE_WEIGHT` set.
- **Look-dev stills.** The look-dev scene (`living/tools/lookdev_shoot.py`): the asset view with `--look lookdev`, and the Cullet plaza with `--look classic` vs `--look lookdev` (and `light:` switching in one drive).

## Classic is main

The client has no deterministic capture: blinking and cloud drift follow wall time, and the bloom spreads them as single-level speckles, so two runs of main's own binary differ in close-ups. Prove Classic against main's binary (built from main's worktree; the asset root is compiled in) on shots main reproduces exactly, and on the rest show the difference is no larger than main against itself:

- the asset view's play-camera stops (`near@0`, `middle@0`) of the calibration cast, and scenery models (`envs/cullet/lamp/lamp.glb` …), no sky in frame: identical;
- the Cullet plaza and the close-ups: main against main, and main against Classic, pixel for pixel (the changed pixels' share and where they are).

## Gotchas

- `light:` re-prepares every toon material once (a frame's hitch); wait about 0.8 s before a shot.
- The character rim and outline weight do nothing in Classic.
- `ldsteps` is for timing only: below 4 it drops later parts, so its pictures are not the look.
