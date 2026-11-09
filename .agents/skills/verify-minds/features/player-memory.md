# Player memory cadence (`LIVING_PLAYER_MEMORY=1`)

The mind service's part of [player memory](../../verify-knowledge/features/player-memory.md) (design: `docs/PLAYER_MEMORY.md`). The proof runs in `verify-knowledge`'s `player_memory.py`, because it needs a scratch Neo4j; this map names what it proves about the mind service.

## Sub-features

- **Off by default:** without the switch the subscriptions are the old list (`experience WHERE controller = <me>` and the rest), the log has no "player memory on" line, no `internalize` request is made, and residents' conversation turns run as before (phase "switch off").
- **Subscriptions with the switch on:** also `experience WHERE controller != <me>` and `settlement`. Rows of other controllers become `Event::Lived` only; they never start a conversation turn or a level-of-detail contact.
- **Cadence:** buffer (`LIVING_PLAYER_MEMORY_BUFFER`, default 40 meaningful; `_CAP` 200 in all), game day (`_EVERY_S`, default the world's day), session end (`_IDLE_S`, default 180 s without a new experience), death (at once). The free tier drives session end with `_IDLE_S=15`.
- **Off the real-time path:** background lane, the shared slow-work semaphore; the player's commands never wait on it.
- **Reconnect:** `lived_upto` on the character's `self` node; a restarted service logs "internalized up to N" and takes only later ids (phase "restart").
- **Modes:** `LIVING_PLAYER_MEMORY_MODE=direct|batch`, `_MODEL` (a profile), `_POLL_S`, `_BATCH_WAIT_S`.

Sources: `living/mind/src/mind/lived.rs`, `living/mind/src/main.rs`, `living/mind/src/mind.rs` (`Event::Lived`, `run`).

## Driving it

```bash
.agents/skills/verify-knowledge/scripts/player_memory.py run --run knowledge-pmem-$(date +%Y%m%d-%H%M%S) --mode direct
```

## Gotchas

- `LIVING_ONLY` applies to played characters too: list the player's id.
- Without a Neo4j store the switch does nothing (there is no memory to write).
