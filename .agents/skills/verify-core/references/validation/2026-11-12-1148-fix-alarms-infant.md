# verify-core: fix-alarms-infant

## 2026-11-12 fix-alarms-infant: two scenes red on main, fixed in the scenes (Spark)

The trial service `slop-trials-stdb`, private `CARGO_TARGET_DIR`. Both scenes are on the red-on-main list (`reds`: `alarms`, `infant`, main `41d40f50`); drop them there when this merges.

- `alarms`, red on main (`core-mainalarms`, main `41d40f50`): 5 PASS, then "a meter naming a field the vitals row lacks is refused" got "meters: `stamina` is declared twice". The overlay's meter was `stamina`, which has been a shipped meter and a row field since stamina-1. It now uses `thirst`. Fixed: `core-fixalarms` (main `41d40f50`'s module) and `core-fixalarms2` (main merged, `63335d2d`) 6/6.
- `infant`, red on main (`core-maininf2`, main `41d40f50`, about 2 h): the last check timed out. The fallback cry did reach exactly the nearest caring adult (#3), but its request reads "A baby is crying and looks warm, hungry". Since fix-kill-name (`28bfa9c9`) a cry names the baby only to whoever knows its name, and the check required the name. It now accepts the baby as the carer knows it. A second flake fixed in the same scene: "warm anchor lies outside crying hearing" (> 30 m) failed at 13.78 (`core-maininf-attempt1`), 26.98 (`core-fixinf1`) and 28.68 m (`core-fixinf2`), because the anchor stood wherever `spawn_crowd` put it. It is now placed 40 m away (or the next free offset). `core-fixinf3` (`ca352efd`, main `f7af6d49` and later merged): 18/18. `--resume-infant` on the two-hour-old main world failed ("no such body"), so it was not used as evidence.
- Only `.agents/skills/verify-core/scripts/scenes.py` differs from main.
