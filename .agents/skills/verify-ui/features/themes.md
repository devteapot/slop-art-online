# Themes

The interface's look is a theme (`living/game/src/ui/wood.rs`): Glass (smoked translucent panels with a gradient, light text with a drop under it, smaller windows; the default since play-test 5), Clear (light neutral, flat), Night (dark translucent), Linen (warm flat) and Walnut (design D's walnut, brass and parchment). F4 cycles it and a note names it; Settings › Play › Look sets it; the settings file keeps it. A change rebuilds the UI and keeps the open windows where they were.

## Sub-features

- `default`: a fresh settings file (its `theme` null or missing) and no `LIVING_GAME_THEME` start in Glass.
- `cycle`: F4 goes Glass › Clear › Night › Linen › Walnut › Glass, with a note "Theme: <name> · F4 changes it".
- `choose`: Settings › Play › Look.
- `keep`: the settings file's `theme` (`LIVING_GAME_SETTINGS`; a drive's own `settings.json`).
- `rebuild`: open windows stay open on their anchors through a change.
- `start`: `LIVING_GAME_THEME=<name>` starts in a theme (captures), over the settings file.

## How to get to it (user POV)

- F4 while playing.
- Menu › Settings › Play › Look.

## Driving it with drive.py

Preconditions: baseline.

- **Default.** `check.py themes` first drives `themes-default` with its settings file deleted: `extra.theme == "glass"` (skipped when `LIVING_GAME_THEME` is set).
- **Cycle.** `key:KeyL:tap;key:KeyI:tap;dump:01;key:F4:tap;dump:02;…` through all five → `extra.theme` advances in `check.py`'s `THEMES` order (`ui::wood::Name::ALL`) in each dump; the log has `ui: Theme: Night  ·  F4 changes it`; `windows` stay `Log` Left and `Pack` Right.
- **Choose.** `click:@menu;click:@menu:Settings;click:@settings:theme:linen` → `extra.theme == "linen"`; the drive's `settings.json` has `"theme": "linen"`.
- **Stills per theme.** `LIVING_GAME_THEME=night check.py --run $R windows talk items` → `ui/<scenario>-night/` photographs.
- Scenario: `check.py --run $R themes`.

- **Contrast in Glass** (not a scenario; `glass-1`'s tools in `.local/living/glass-1/tools/`): `stills.py` takes the person window, its talk box, the pack and the bar in four views, then the same views with the windows closed; `contrast.py` composites the theme over the world behind each window in linear light, checks that model against the still (within about 0.01 luminance), and reports text and muted contrast. Day and night come from the world's own 12-minute day (`hour_of`: 07:00 at the epoch; 30 s a world hour).

## Gotchas

- The settings file of a drive name persists between drives of the same run: a later drive starts in the theme the last one left, unless `LIVING_GAME_THEME` is set.
- Glass's windows are narrower (`win::narrow_w()`, `wide_w()`): checks that compare rectangles take them from the dump, never from the 426/1076 constants.
- In a translucent theme what lies under a window shows through it: notes and hints that float over the world must sit above windows or wait while one covers them (tips do both), and take `wood::float_or(...)` as their ground.
- The old target frame and nameplates are not themed yet (the fight plate comes with step 6); the cluster is.
