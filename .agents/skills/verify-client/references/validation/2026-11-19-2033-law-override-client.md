# The game client subscribes `law_override` (`law-override-client`)

- **Branch:** `law-override-client`, on `origin/law-override` `ee92c9e90`. Game client only: the authority, tables and bindings are unchanged.
- **Shape change:** the client's base set (`PERCEIVED`) grows from 24 to 25 queries with `SELECT * FROM law_override`, beside `script WHERE name = 'skills'`.
  - Its connection-lifetime queries are 34 with the tiered set, or 28 plus `gate` with the untiered one.
  - `perception_law` reads the delivery laws again whenever the laws in force change (`Rules::laws_key`), not once per script revision.
  - [features/game-client.md](../../features/game-client.md) is updated.
- **Proof:** a real game-client connection, through verify-ui's `check.py law-override`. See [verify-ui's record](../../../verify-ui/references/validation/2026-11-19-2033-law-override-client.md).
  - The base set's first result held every override: `world subscribed after … (6 law overrides)`. That was after a reconnect whose rows changed while the client was offline, and again on a fresh client.
  - Each value-only edit arrived as a `law_override` row update. The client laid it over in place with the `script` revision unchanged.
- **Not run here:** the SDK probe suite (`run.py`, `cues.py`, `near_tier.py`). No table, view or permission changed. `law_override`'s visibility and first result are the authority branch's record ([2026-11-19-1901-law-override.md](2026-11-19-1901-law-override.md)).
- **Found, not changed:** `scripts/cues.py:188` and `scripts/near_tier.py:120` still read `world_law` for the value to restore. This branch's authority no longer writes that table, so on a world where a law was set since the migration, they restore the migrated value.
