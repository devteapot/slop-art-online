# refusal-tell: truthful_refusals' missing say-leaf line (not reproduced) and `say` 29/37 on main (a reverted scene fix)

Branch `refusal-tell` from main. The runs were on `35b0ea218` (2026-11-23) and `6b71513d5` (2026-11-26). Spark (aarch64), on a private server `slop-reftell-20261123` (SpacetimeDB 2.14.1, `127.0.0.1:3655`, container pinned to CPUs 0-4,10-14). Builds went through `build-slot` with a private `CARGO_TARGET_DIR`. Every launch was under `trial-activity.lock`, and every world was deleted by `verify.py cleanup` (a confirmed pause, then `world_delete`). No mind service and no model calls.

## 1. truthful_refusals: "You failed to say …" not written (gate-say-path step 1, gate-1123072442-8633b3)

**The path.** A `say` leaf that cannot resolve its listener goes from `Ev::say_failed` to `act::refused`, then `news`, then `tell`. The status ("stuck: say: …", written by `Ev::after`) and the line are written in the same tick transaction. `tell` skips the line in only these cases:

- `news` finds a mark under the same `failure_mark(what, why)` key (FNV-1a into 0xE000-0xEFFF) inside `repeat_failure_s` (120 s). `set_graph` keeps these marks across installs.
- The character is not a mind's (`!ai`) and is not played.
- `percept` declines because the character is dead, an infant or instinct-only.

The commit log of the original world (replica 419 on `slop-gatesay2-20261123`) is gone with that server's volume. Its server log shows replica 419 deleted at 06:35:58.5 UTC, 10 s after the say graph was installed (06:35:47.97). The host load was about 12 then.

**Collision check on the failing world's own strings.** The say leaf's key is 0xE620. A's ten act failures in that scene (from its evidence, `wave → #272 | no #272 in sight` among them) give other keys, so there was no collision there.

**Repro.** Each world ran act_gaps, act_replace and truthful_refusals in the gate's order, followed by a focused repro (`.local/reftell/say_leaf_repro.py`). The repro gives 2 × 10 fresh minded actors the scene's step 7: a goto graph to an unknown place, then the say leaf to "speaker". It then reads the line, status, fails, marks and character row of each.

| Series | Worlds | truthful_refusals | Focused say leaves told |
| --- | --- | --- | --- |
| quiet (2 lanes; host load 5-9) | 8 | 8/8 | 160/160 |
| induced load: 15 busy loops on 0-4,10-14, 2 lanes (load 22-45) | 12 | 12/12 | 240/240 |
| the same, 6 worlds at once on the server | 18 | 18/18 | 360/360 |
| the same, 12 worlds at once (load 44-55, the gate's spike) | 36 | 36/36 | 720/720 |
| quiet, on `6b71513d5` | 2 | 2/2 | 40/40 |
| **total** | **76** | **76/76** | **1,520/1,520** |

Every told leaf carried `fails` 1 and the key mark at the same millisecond as its line. The gate's own record over all retained runs is 1 failure in 19 first runs. A true rate of 1 in 20 would give 0 failures in 76 worlds with p ≈ 2%. The miss therefore depends on something these series did not have, or is much rarer than 1 in 20. Cause not established; no rules change was made.

**Change (test-only).** When the scene's say-leaf wait times out, it now keeps everything that decides whether the line is written: A's `mind_state` (marks, fails, status), its `character` row (ai, alive, stage, controller), its activity, its brain and its experience rows, the clock, and the key computed in Python. They go to the scene's evidence as `say leaf missed`, so the next miss names its cause without a commit-log post-mortem.

Unrelated failures seen under load, not looked into: verify-core `act_gaps` failed 11 of 76 first runs ("turned back on: seven walks given up for one the other way are noticed and told once") and `act_replace` 8 of 76 ("on: a gaze change or an unreadable act replaces nothing": the goto under way had ended), all with host load 20-50 at the start; none in the quiet series.

## 2. `say` 29/37 on main

The say-scene-once fix (`04ca8a6f6`, merged `933ca7fea`) is not in main's `scenes.py`. `relation-fight`'s commit `70629b4f7`, whose parent is `933ca7fea`, removed that hunk (the `phrases` list and the line text), apparently by writing a stale copy of the file. The hunk is the only deletion in the commit that the branch did not intend, and `35b0ea218` merged it normally (not a criss-cross). `git log -G` shows no other commit touching those lines. The runs used this checkout's own `scenes.py`, so no other copy was involved.

| Scene | Build | Result |
| --- | --- | --- |
| main's `say` (fresh world each) | `35b0ea218`, load 12-45 | 29/37 ×3, the same 8 `mind_install` forms (14, 15, 16, 18, 19, 20, 22, 24; 13, 17, 21 and 23 spoken, as say-once predicts) |
| main's `say` | `6b71513d5`, quiet (load 6-7) | 29/37 |
| the hunk restored, identical to `933ca7fea`'s `say` | `35b0ea218`, load 20-45 | 37/37 ×3 |
| the same | `6b71513d5`, quiet | 37/37 |
| this branch's `scenes.py` (both changes) | `6b71513d5`, one fresh world | say 37/37, truthful_refusals 26/26; the diagnostic queries checked on that world |

This branch restores the hunk. Problems 1 and 2 do not share a cause. Problem 2 is say-once (`speech::said_to_recently`) holding back the near-identical lines as intended. It is not a refusal and is not a line that should have been told.

Evidence: `.local/reftell/` in this worktree, untracked: `series/summary.txt` and each world's scene logs, `*-focus/rounds.jsonl`, `say/`, `final/`.
