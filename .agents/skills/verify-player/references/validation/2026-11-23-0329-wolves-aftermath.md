# The wolves scene leaves the player alive (`wolves-aftermath`): the player surface

Validated on the dev-box on branch `wolves-aftermath` from `origin/main` `794d2f73e` (after `wolves-scene` and `yield-news`). It folds in `death-placement` (validation record 2026-11-23-0248). Server `wa-stdb` (private, `127.0.0.1:3390`); `performance` governor. No paid model calls. Test-only: `scripts/combat.py` and [features/combat.md](../../features/combat.md) (Gotchas).

## The failure

The scene gate of `death-placement` (batch 68), `gate-1123034937-7633c6-a-player`:
- `wolves` passed: the player was placed where wolf 307 sees it at 03:55:48, and the attack check passed at 03:55:50 (6.6 damage).
- `onlooker` then crashed: `RuntimeError('sql SELECT x, y FROM body WHERE id = None …')`. `main`'s placement before it had already been refused (`place_at[null, …]`).
- `death` failed: "a living character to die: none".

**The cause.** Since `wolves-scene` the pack reliably attacks the player. A player already worn down by the earlier scenes (`fast_lane`'s four 9-damage blows) can die to the pack within the scene's first seconds. Nothing after the scene put a living character back, or moved the player away.

## The fix

- **`scene_wolves`:**
  - sets the player to full health before the pack ("a healthy adult", as the check says);
  - after the attack check, places the player at the arrival point, far from the pack;
  - new check: "the player leaves the pack alive".
- **`main`:** calls `living()` before every scene. When an earlier scene left no living character, it joins again, as a player would at the death screen, and logs it.
- **The death scene's staging,** from `death-placement`.

## Runs (`wa-1`, island seed, one world throughout)

| Run | Script | Result |
|---|---|---|
| `--scene all --fresh` × 5 | fixed | 59/59, 59/59, 59/59, **58/59**, 59/59 |
| `--scene all --fresh` × 3 | main's | 58/58, 58/58, **57/58** |
| `--scene wolves,onlooker,death`, the player set to 8 HP first | main's | **3 of 5**: the gate's failure exactly (`onlooker` crashed on `None`, `death` "none") |
| the same | fixed | **12 of 12**: attacked, left the pack alive, killed by a wolf in `death` |
| `living()` directly, the player killed first | fixed | joined again: a new living character (4213 → 4214) |

- **The one failure in each script** is the bow scene's "the player is told where its arrow went" ("it flew out of your sight"). It came in the fourth run on the same world for the fixed script and in the eighth for main's.
  - That scene comes before the wolves and is untouched here.
  - It passed in all 27 gate runs kept in the coordinator's worktree, so it is very likely the reused world's state. It is not this change.
- **No `--scene all` run needed a rejoin:** "no living character" was logged 0 times. With full health the pack does not kill the player.

Evidence: `.local/wa/` (`repeat.log`, `combat-fixed-*.json`, `combat-main-*.json`, `combat-lowhp-*.json`) and `.local/living/verify/wa-1/`, archived to `~/archive/worktree-evidence-20261123/wolves-aftermath.tar.zst`.

## Not covered

- The other surfaces. The bow scene's reused-world failure is not diagnosed.
