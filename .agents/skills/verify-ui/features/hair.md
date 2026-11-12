# Hair shine

The highlight on hair (`living/game/src/toon.wesl` `hair_light`), by name from the style profile's table (`style.rs` `HAIR_SHINES`): each shine is the ring's eight values (strength, width, edge softness, comb teeth, strand break-up, tangent shift, how far up a surface must face, from how far it faces the character's forward it fades).

- **Crown** (the default since hair-ring-2): a hard band over the crown, broken where locks part, never across a fringe.
- **Soft:** a softer, wider band broken by the strands.
- **Today:** the ring before hair-ring-1, one hard band that crosses a smooth fringe.

## Sub-features

- `default`: a fresh settings file (`hair_shine` null or missing) and no `LIVING_GAME_HAIR_SHINE` start on Crown, and the client saves no choice until one is made.
- `choose`: Settings › Play › Hair shine; the log says `settings: hair shine: <name>`.
- `keep`: the settings file's `hair_shine`, read back at the next start.
- `start`: `LIVING_GAME_HAIR_SHINE=crown|soft|today` starts in one; `LIVING_GAME_HAIR_RING=strength,width,soft,teeth,strands,shift,up,front` sets single values over any (look-dev captures).
- `pixels`: switching changes the hair and nothing else.

## How to get to it (user POV)

- Menu › Settings › Play › Hair shine.

## Driving it with drive.py

Preconditions: baseline.

- **Scenario.** `check.py --run $R hair` (run it with `uv run --with pillow --with numpy python`, for the pixel checks):
  - deletes the drive's settings file;
  - `dump:01`: `extra.hair_shine == "crown"`, `extra.hair_shine_saved` null;
  - Settings › Hair shine › Soft, then Today (`dump:02`, `03`); the drive's `settings.json` has `"hair_shine": "today"`;
  - a second drive reads it back (`dump:00`), sets `shine:crown`, places a resident beside the player (`--place`), opens their window (the camera on their face) and photographs `01_crown`, `01b_crown`, `02_today` and `03_soft` from one view;
  - Crown against Today and Soft differs near the heads (`seen` in `dump:04`), and away from every head changes no more than `01b_crown` against `01_crown`.
- It refuses to run with `LIVING_GAME_HAIR_SHINE` or `LIVING_GAME_HAIR_RING` set.

## Gotchas

- Opening Settings closes the other windows: compare shines in one view with `shine:`, not with Settings.
- Live residents are VRoid bases until look-1 lands; composed people (char-4's) are judged in look-dev and the asset view (`docs/CHARACTERS.md`).
