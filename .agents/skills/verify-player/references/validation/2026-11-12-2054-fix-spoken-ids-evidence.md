# verify-player: fix-spoken-ids, the evidence row

Follows `2026-11-12-2019-fix-spoken-ids.md`. Trial service `slop-trials-stdb`, island seed, the run's own player identity.

- **`speak.py`** 20/20 (`player-ids2-214540`), with a new check: "the player's spoken_as row keeps what it wrote beside what was said". `my_experience` has one `spoken_as` row holding "verify speak: is #<resident> about?" and the words said. The earlier 19 checks still pass, including the line said without the id.

  Evidence: `.local/living/verify/player-ids2-214540/speak.json`.
- **`just living-check`** (build slot, pipefail): exit 0.
