# verify-core: admin-set-vitals

Branch `admin-set-vitals` (one commit on origin/main `1dc58639`; driven with main `80e75932` merged in). Trial service `slop-trials-stdb`, `scoped`, private `CARGO_TARGET_DIR`.

- **The change.** A new admin reducer `admin_set_vitals(id, hp)`, generic, named for what it does. It sets a living body's health to `hp`; more than its maximum is its maximum. It re-anchors the vitals row, refreshes the fight band and what others see, and writes an `admin` chronicle line for each use. 0 or less, and a dead character, are refused and write nothing.
  - Its only user is the trial runner's new `vitals` step, which R3's arenas use to start each meeting at full health (docs/COMBAT_MIND.md §5.4). summary.json `admin_vitals` lists every use.
  - Bindings were regenerated with `just living-generate`. They also gained `fight_seen`, a table main had without bindings.
- **`admin_vitals`** (new scene) 7/7, before and after merging main (`core-vit2-010520`, `core-vit3-011233`):
  - set to 40 and read back;
  - 1000 reads back as the maximum;
  - two `admin` lines;
  - 0 refused ("health must be above 0"), writing nothing;
  - refused after `kill` ("no living character with that id").

  The first run (`core-vit-010444`) failed only its `-5` case: the admin CLI reads "-5" as a flag, so the value never reached the reducer. That case was dropped, and the scene says why.
- **Migration** (`core-vitmig-011000`). A world was published fresh from origin/main `80e75932`'s module, then updated in place with this branch's module (`verify.py launch --keep-data`).
  - Data kept: 267 characters before and after.
  - Doctor passed and the clock kept ticking.
  - `admin_set_vitals(167, 55)` as admin set 98 → 55, with the line "admin set Iseka's health 98 -> 55". The same call made anonymously was refused "admin only".
  - The world was deleted.
- **`just living-check`** (build slot, pipefail): see the verify-client record of the same date.
