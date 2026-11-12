# Film

The finishing pass's film (`living/game/src/post.rs` `Film`, `edges.wesl`): a warm gradient from the top of the frame, screen-blended. Soft (the default since film-1) weighs it by each pixel's own light by day, so the sky and lit things take it as before and dark hair, cloth and shadows keep their colour; by night (the atmosphere's light at or below 2800 lux) it is the screen, the night's moonlit haze. Full is the screen on every pixel (the look before film-1). None turns it off. The UI is drawn after the film; only what shows through Glass panels changes.

## Sub-features

- `default`: a fresh settings file (`film` null or missing) and no `LIVING_GAME_FILM` start in Soft; the client saves no choice until one is made, so a later default reaches viewers who never chose.
- `choose`: Settings › Play › Film (Soft, Full, None); the log says `settings: film: <name>`.
- `keep`: the settings file's `film`, read back at the next start.
- `start`: `LIVING_GAME_FILM=soft|screen|off` starts in one (captures), over the settings file.

## How to get to it (user POV)

- Menu › Settings › Play › Film.

## Driving it with drive.py

Preconditions: baseline.

- **Scenario.** `check.py --run $R film` deletes the drive's settings file, then: `dump:01` (`extra.film == "soft"`, `extra.film_saved` null); Settings › Film › Full (`dump:02`, `03`: `screen`), › None (`dump:04`: `off`), › Full again; the drive's `settings.json` has `"film": "screen"`; a second drive reads it back (`dump:05`). Stills `01_soft`, `03_screen`, `04_off` from one place, the unseen ground's edge in view. It refuses to run with `LIVING_GAME_FILM` set.
- **Glass over the world.** `LIVING_GAME_FILM=<mode>` per drive (opening Settings closes the other windows, so a mode cannot be switched with them open), then glass-1's `contrast.py` on the shots and their bare twins (film-1's `glass.py`, kept with its evidence).

## Gotchas

- Day and night come from the world's own 12-minute day: run night stills between 20:00 and 06:00 world time (`hour_of` on the `world` row's `epoch_ms` and `day_ms`).
- By night Soft and Full draw the same; compare them by day.
