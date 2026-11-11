# A mind sees what its character sees

Since 2026-11-09 (docs/PERCEPTION.md, "Minds see what their character sees"). Every perception path for minds uses the players' rule: sight by light and a clear sight line (rock, walls and shut gates hide).

## Sub-features

- Three AI residents are placed by the admin on the world's own map: the eye, one at most 4 tiles away behind rock or wall, and one 3 tiles away in the open. The deliberation the eye is asked for (`deliberation.scene`) and the prompt the model is sent list the one in the open and not the hidden one (`sent-prompt.txt`).
- Drops and low tiles do not hide (they block only the foot): [drop.md](drop.md) proves a mind sees across them.
- Both others are killed (admin `kill`): the eye's experiences hold the death in the open and not the one behind the wall.

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case sight
```

## Gotchas

- The geometry search reads `terrain_chunk` (public) for a thin rock or wall run with open ground on the eye's side; a map without one fails with "no wall geometry", a fixture failure.
- Players' side of the same rule is `verify-client`'s perception checks; the combat feed's is covered there and in `verify-core`.
