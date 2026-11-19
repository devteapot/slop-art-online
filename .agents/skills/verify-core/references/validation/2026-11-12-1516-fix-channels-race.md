# verify-core: fix-channels-race

## 2026-11-12 fix-channels-race: `speech.py channels` staging (Spark)

Branch `fix-channels-race` (`ba0b5202`, main `b02661f9` merged), the trial service `slop-trials-stdb`, the default seed, private `CARGO_TARGET_DIR`. Only `.agents/skills/verify-core/scripts/speech.py` and `features/speech.md` differ from main.

`channels` failed when an unrelated row landed in the window of a check that a line wrote nothing else, and those checks read the cast's whole experience log. Three causes were found by reusing one world:

- **Takeover.** A scene's players never connect, so after the `takeover_s` law's 30 s the minds took the listener over, and its first look round ("discovered", "saw") landed in a check (2 of 4 runs on fix-sleep-talk). `Person` now raises `takeover_s` to 3600 for the scene before the first join, and `main` restores it (also after SIGINT). A new check confirms the player listener is still played at the end.
- **Dusk.** The scene takes about 8 game hours of the 12-minute day, and e (seen by day) and the queued checks need daylight. A fresh launch starts at 07:00; a reused world does not. On `core-chrace1`, runs 4 and 5 ran into dusk and night. The scene now waits for the morning (06:00–07:00) unless it starts between 06:00 and 11:00.
- **Ambient rows.** A row no line writes ("Some of your berries spoiled", kind `body`) failed "whisper to c at 4 m is refused" in `core-chrace1` run 9. Such kinds (`body`, `discovered`, `saw`, `feeling`, `life`) are no longer counted as a line's rows. A resident wandering into earshot also learned c's name (`core-chrace2` attempt 1, run 2), so name learning is now counted among the cast only.

Proof: on one reused world, `core-chrace2`, five runs in a row on the final scene, each 32/32 (`five.txt`; runs 1, 2 and 4 waited for the morning). Before them, `attempt1` on the same world: 32, 31 (the wandering resident), 32. `regress` 8/8 and `ways` 21/21 on fresh runs (`core-chrace2-regress`, `-ways`). The `channels` entry on the red-on-main list is dropped with this change.
