# Light

The light and shading (`living/game/src/style.rs` `Look`, `LookParams`; `toon_light.wesl` `ld_*`, the look-dev branches in `toon.wesl` and `terrain.wesl`), look-dev step 1 (`.local/living/lookdev/survey/PLAN.md` on the laptop). Two looks:

- **Classic** (the default): the look before look-dev step 1. Every look-dev term is compiled only into pipelines with the shader def `LOOKDEV` (`style.rs` `ToonKey`, from `ToonParams::look.x`; `terrain.rs` the same for the ground), so Classic's pipelines compile main's shader code and the image is main's (pixel identity: see "Classic is main" below). Switching the light compiles the other pipelines once.
- **Look-dev:** four parts, timed one by one with `LIVING_GAME_PERF=ldsteps=N`:
  1. a sky/ground hemisphere fill in place of the flat fill (the sky's colour from above in the shadows' hue, the sunlit ground's warm bounce from below), and shadows that keep only part of the sun's colour, so a warm sun lights warm planes against cool shadows and dusk no longer turns monochrome brown;
  2. the ramp: deeper cloth and scenery shadows (depth 0.56 against 0.42), on characters a threshold that turns a little more of the form to shadow and less brush breakup, skin shadows a warmer peach-rose;
  3. a cel-stepped specular by the material's metallic and roughness (none from roughness 0.88 up; today's character files are all 0.8–0.9, so it shows on scenery's painted metal, copper and glass, which take their own values);
  4. rims: a cel-stepped Fresnel rim on characters' sun side (hand-made hair too), with a faint cool sky rim on the far side, and scenery and ground keep a quarter of the classic rim.

The character rim (`style::CharRim`: Off, Subtle the default, Strong) is a taste setting that acts only with Look-dev. Characters' materials carry `ToonParams::character.x` (`lookdev.rs`, `characters/compose.rs`, `characters/outfit.rs`). It is not part of `lookdev.rs`'s material-sharing key: adding it there changed which materials share, and with that some recoloured skin by one level, in Classic.

## Sub-features

- `default`: a fresh settings file (`light`, `char_rim` null or missing) and no `LIVING_GAME_LOOK` or `LIVING_GAME_CHAR_RIM` start Classic with the rim Subtle; the client saves no choice until one is made.
- `choose`: Settings › Play › Light (Classic, Look-dev) and Character rim (Off, Subtle, Strong); the log says `settings: light: <name>` and `settings: character rim: <name>`.
- `keep`: the settings file's `light` and `char_rim`, read back at the next start.
- `start`: `LIVING_GAME_LOOK=classic|lookdev` and `LIVING_GAME_CHAR_RIM=off|subtle|strong` start in one (captures), over the settings file; also in the asset view (`LIVING_GAME_VIEW`).
- `switch`: the live script's `light:NAME` and `rim:NAME`, leaving open windows be.
- `pixels`: Look-dev changes the picture; Classic after Look-dev is Classic again (the two Classics far closer than either is to Look-dev); the rim changes people only.

## How to get to it (user POV)

- Menu › Settings › Play › Light, and Character rim.

## Driving it with drive.py

Preconditions: baseline.

- **Scenario.** `check.py --run $R light` (with `uv run --with pillow --with numpy python`, for the pixel checks): deletes the drive's settings file; `dump:01`: `extra.light == "classic"`, `extra.char_rim == "subtle"`, both `_saved` null; Settings › Light › Look-dev (`dump:02`), Character rim › Strong (`dump:03`); the drive's `settings.json` has `"light": "lookdev"`, `"char_rim": "strong"`; a second drive reads them back (`dump:00`), holds a resident beside the player (`--place`), puts the cursor in the world and photographs `01_classic`, `02_lookdev`, `03_classic`, `04_rim_strong` and `05_rim_off` from one view with `light:` and `rim:`. It refuses to run with `LIVING_GAME_LOOK` or `LIVING_GAME_CHAR_RIM` set.
- **Look-dev stills.** The look-dev scene (`.local/living/lookdev/survey/LOOKDEV_SCENE.md`): the asset view with `LIVING_GAME_LOOK=lookdev`, and the Cullet plaza with `light:` switching in one drive (`shot:plaza_middle_noon_classic;light:lookdev;wait:0.8;shot:plaza_middle_noon_lookdev;light:classic`).

## Classic is main

The client has no deterministic capture: blinking and cloud drift follow wall time, and the bloom spreads them as single-level speckles, so two runs of main's own binary differ in close-ups. Prove Classic against main's binary (built from main's worktree; the asset root is compiled in) on shots main reproduces exactly, and on the rest show the difference is no larger than main against itself:

- the asset view's play-camera stops (`near@0`, `middle@0`) of the calibration cast, and scenery models (`envs/cullet/lamp/lamp.glb` …), no sky in frame: identical;
- the Cullet plaza and the close-ups: main against main, and main against Classic, pixel for pixel (the changed pixels' share and where they are).

## Gotchas

- `light:` re-prepares every toon material once (a frame's hitch); wait about 0.8 s before a shot.
- The character rim does nothing in Classic.
- `ldsteps` is for timing only: below 4 it drops later parts, so its pictures are not the look.
