# Player verification map

| Feature | File |
| --- | --- |
| Player character: join, move, act, speak, refusals | [player-character.md](player-character.md) |
| Combat skills: use, refusals, strike, killing a person, bow, fire bolt, block, dodge, heal, wolves, death and rejoin | [combat.md](combat.md) |
| Gestures: wave, nod and face through `human_act`, answered by residents; refusals | [gestures.md](gestures.md) |

Baseline: `verify-<run>` published by `$V launch` and `$V doctor` passing. One identity per run; `join` succeeds once per identity while its character lives. For a second player, use a second run name, or mint another identity with `curl -X POST http://127.0.0.1:3300/v1/identity`.
