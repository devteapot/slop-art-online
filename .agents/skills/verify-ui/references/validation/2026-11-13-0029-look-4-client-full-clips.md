# verify-ui: look-4-client with the full clip file

Follows `2026-11-13-0021-look-4-client.md`, same branch and head (`look-4-client` `7df25c430`: `c78e741d3` on main `d5a023e0d` with look-4, plus that record). Only the shared clip file changed.

## Why the first composed run failed

The first run's `own-clips` was baked with gen_person's default `KIMODO_DIR`, `.local/kimodo/outputs/library` in the main checkout.
- That copy is stale: 150 files, 30 of `clips.json`'s 86 entries, with no directional or turn takes.
- The library's home is `.local/kimodo/library`, which `clip-library-sync` keeps: 645 takes, 67 of 86 entries.
  - It has every directional and turn take.
  - It lacks only the `_v26`/`_v30`/`_v34`/`_v48` speed variants.

## The rebake

- **Command:** `KIMODO_DIR=/Users/carlid/dev/slop-art-online/.local/kimodo/library ONLY=present LOD=near gen_person.sh clips=man`.
- **Result:** "baking the 67 library entries present". `anim/own-clips.glb` is 4.70 MB, with 65 clips in its summary, including `walk_back`, `run_back`, `strafe_*`, `turn_*_90`/`_180` and `jump_back`.
- **`skeleton_check.py`:** 196 files, **0** with a bone at another place.
- **The 29-clip bake** is kept in `.local/landing/clips29/`.
- **The bundle install** is unchanged: KTX2 `dc0340f3`, as in the record before.

## The run

**World:** fresh island `verify-ui-1113-012349l4f`, the island seed with its looks, so people draw composed.
- The client log says "generated people take their clips from lookdev/anim/own-clips.glb".
- The look-walk player is composed (still: `look-walk-chest/steady135.png`).

**139 passed, 0 failed:**

| Scenario | Passed |
| --- | --- |
| `look-walk` | 91/91 (head, chest, loose, others, settings) |
| `turns` | 14/14 |
| `field` | 29/29 |
| `reversal` | 5/5 (no `reverse` frame within −0.3 to +1.0 s of the reversal) |

Evidence: `.local/living/verify/ui-1113-012349l4f/ui/` and `.local/landing/l4f-checks.txt`.

## Gaps and follow-ups

**Not covered:**
- a play-test replay;
- main's client against this clip file. The A arm was run only on the 29-clip file: look-walk 83/91 there, and 10 backwards frames per reversal.

**For play-test 7:** a laptop client baking own-clips needs `KIMODO_DIR` at the library's home. Without it, gen_person's default bakes the stale 29-clip copy, and composed people walk with no directional takes.
