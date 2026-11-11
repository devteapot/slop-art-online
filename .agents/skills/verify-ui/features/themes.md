# Themes

The interface's look is a theme (`living/game/src/ui/wood.rs`): Clear (light neutral, flat, the default), Night (dark translucent), Linen (warm flat) and Walnut (design D's walnut, brass and parchment). F4 cycles it and a note names it; Settings › Play › Look sets it; the settings file keeps it. A change rebuilds the UI and keeps the open windows where they were.

## Sub-features

- `cycle`: F4 goes Clear › Night › Linen › Walnut › Clear, with a note "Theme: <name> · F4 changes it".
- `choose`: Settings › Play › Look.
- `keep`: the settings file's `theme` (`LIVING_GAME_SETTINGS`; a drive's own `settings.json`).
- `rebuild`: open windows stay open on their anchors through a change.
- `start`: `LIVING_GAME_THEME=<name>` starts in a theme (captures), over the settings file.

## How to get to it (user POV)

- F4 while playing.
- Menu › Settings › Play › Look.

## Driving it with drive.py

Preconditions: baseline.

- **Cycle.** `key:KeyL:tap;key:KeyI:tap;dump:01;key:F4:tap;dump:02;…` → `extra.theme` advances in order in each dump; the log has `ui: Theme: Night  ·  F4 changes it`; `windows` stay `Log` Left and `Pack` Right.
- **Choose.** `click:@menu;click:@menu:Settings;click:@settings:theme:linen` → `extra.theme == "linen"`; the drive's `settings.json` has `"theme": "linen"`.
- **Stills per theme.** `LIVING_GAME_THEME=night check.py --run $R windows talk items` → `ui/<scenario>-night/` photographs.
- Scenario: `check.py --run $R themes`.

## Gotchas

- The settings file of a drive name persists between drives of the same run: a later drive starts in the theme the last one left, unless `LIVING_GAME_THEME` is set.
- The old target frame and nameplates are not themed yet (the fight plate comes with step 6); the cluster is.
