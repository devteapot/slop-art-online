# verify-ui: talk-turns-client on main

Follows `2026-11-12-2316-talk-turns-client.md`. This is the same change, rebased onto main.

## The rebase

**The branch:** `talk-turns-client` is one commit, `994e85d9f`, on main `3c08a2180`. Main has talk-turns (`28dd8b1a`) and look-4-client.

**Two conflicts, both in verify-ui docs; both sides were kept:**
- `features/README.md`: main's talking row with `bubble-once`, and this branch's bar row with `move-off`.
- `features/talking.md`: this branch's `room-detail` paragraph, and main's `bubble-once` line.

**Tests:**
- living-game: 128 passed, 1 ignored.
- living-rules: `the_game_client_names_no_new_skills` passed.

**Characters:**
- The KTX2 bundle `dc0340f3`, installed whole (record `2026-11-13-0021-look-4-client.md`).
- `own-clips` baked from the clip library's home (`KIMODO_DIR=/Users/carlid/dev/slop-art-online/.local/kimodo/library`): 65 clips.
- `skeleton_check.py`: 196 files, 0 with a bone at another place.
- Island people draw composed. Every drive's client log: "0 on VRoid bases … every person in sight is composed".

## Runs on head `994e85d9f`

**Fresh island world `verify-ui-1113-015920t4`, 59 passed, 0 failed:**

| Scenario | Passed |
| --- | --- |
| `room-detail` | 11/11 |
| `move-off` | 8/8 |
| `talk` | 22/22 |
| `unheard` | 12/12 |
| `own` | 6/6 |

`move-off/02_waving.png` shows the composed player's arm raised in the wave while it walks on.

**Fresh Cullet world `verify-ui-1113-015920t4c`:** `names` **4/4**.

**Before look-4-client reached main:** the same scenarios ran on an intermediate head `49f4fbfbe` (main `28dd8b1a3`, without look-4-client). Fresh worlds `verify-ui-1113-015321tt` and `…ttc` gave the same counts: 59/59 and 4/4.

## Evidence and gaps

**Evidence:**
- `.local/living/verify/ui-1113-015920t4/ui/`
- `.local/living/verify/ui-1113-015920t4c/ui/`
- `.local/landing/tt4-island.txt`, `tt4-cullet.txt`

**Not covered:** a resident's own named turn answered by a mind. No mind service runs on these worlds; verify-minds `named-turn` covers it.
