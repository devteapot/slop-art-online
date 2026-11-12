# An offline player's character under the minds

Since 2026-11-09 (docs/PLAYER_MEMORY.md, "Presence and the offline character"). When a player's last connection has been closed for the `takeover_s` law (30 s), the world's minds control the character: this service sees it in `mine()` (`ai`, `controller` = its identity), thinks, talks and consolidates for it like any AI character. When its person connects again the authority hands it back at once.

## Sub-features

- A player joins over HTTP (the call's connection closes): its `presence` row has a takeover pending.
- After about 30 s: `presence.ai`, the character's `ai` and `controller` = the world admin; the deliberation the authority requests is answered and installed (`brain.source = mind`, plan `verify minds wait`). Its experience rows lived so far stay.
- The person's next call (`human_move`) hands it back first: `ai` false, `controller` the player, `brain.source = human` (waiting for them), the minds' graph kept on the presence row (`ai_graph`, `ai_plan`), no pending deliberation, no decided acts; the experiences lived under the minds are still in the window.
- Away again: the held graph is installed again (`source = mind`, the same plan), and the takeover asks for a fresh deliberation (its reason "A quiet moment to take stock…"; asked before the reinstall, which counts as having just thought).
- That deliberation, still in flight when the person returns, is refused (`not your character` in the mind log) and changes nothing.

## Driving it

```bash
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case takeover
```

The fake model delays the first takeover's deliberate reply 8 s and the second's 25 s, so the second is in flight at the handback. The case waits for that request in the fake log, then moves. `LIVING_ONLY` lists the player's character.

## Gotchas

- The case takes about two takeovers (≥ 60 s) plus model delays.
- Do not trigger the in-flight deliberation with a `set_behavior` think after the second takeover. The reinstall sets the deliberation clock, so the think node stays quiet for 45 s and `think_min_s` (20 s for people) declines a new ask. Before fix-takeover (2026-11-12) the case did this. It passed only when the test graph reached the takeover's prompt before the mind sent it, and failed under load when the driver's poll lagged by a few seconds.
- Without Neo4j (`LIVING_NEO4J=off` in this skill) player memory has no store, so the wait for the lived past is not exercised here: `verify-knowledge`'s `player_memory.py` proves it.
