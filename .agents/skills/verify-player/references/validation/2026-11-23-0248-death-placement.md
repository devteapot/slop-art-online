# The death scene's staging (`death-placement`): the player surface

Validated on the dev-box on branch `death-placement` from `origin/main` (after `wolves-scene`). Server `mc-stdb` (private, `127.0.0.1:3390`); `performance` governor. No paid model calls.

**What changed.** Test-only:
- `scripts/combat.py`: the wolves scene's placement is now one helper, `beside_wolf`, with the rings `RING_5M` (wolves) and `RING_1M` (death);
- `scene_death` places the player 1 m from the first bold wolf, from where the wolf is now (`body_now`), at a spot where the player's own `seen_characters` holds it;
- it places the player again while the wolf is more than 7 m off before the player dies;
- the death check's detail lists the offsets; no check was added;
- [features/combat.md](../../features/combat.md) (Gotchas).

The scene list, reducers and views are unchanged, so the map has no drift.

## Runs (`dp-2`, island seed)

- **`combat.py --scene death --fresh`, 10 times, 5–20 s apart: 10 of 10 at 4/4.**
  - Each character died "killed by a wolf".
  - The dead player was told of the death and who saw it.
  - The death's codes and line were right.
  - Rejoining gave only the newcomer's kit.
  - The first spot (1 m east) was seen every time. One run placed the player a second time after the wolf walked off.
- **`combat.py --scene all --fresh`: 58 of 58.** The wolves scene used its 5 m ring, and the death scene used 1 m east.

Evidence: `.local/living/verify/dp-2/` and `.local/dp/repeat.log`, archived to `~/archive/worktree-evidence-20261123/death-placement.tar.zst`.

## Not covered

- A death scene with no bold pack: the player stays where it is, unchanged from main.
