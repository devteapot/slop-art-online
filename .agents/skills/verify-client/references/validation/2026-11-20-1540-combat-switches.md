# combat-switches: the game client's half of views steps 2 and 3 (verify-client map)

Branch `combat-switches` (from `origin/main` `75e26fcab`), laptop. The game client (`living/game`) changes as follows:
- it reads `seen_fighter_copy` in place of the fighter views while `fighter_tables_on` is on;
- it reads the `combat_feed` event table in place of `my_combat` while `combat_feed_on` is on;
- in that case `my_combat` is read once at connect, and both sources are merged by id;
- `my_combat` itself moved from the client's base set into its perception set.

The authority, its tables, rules and bindings are unchanged.

**Maintenance** (`maintain-verification-skill`, scoped to this change): `features/combat.md` names the client's new subscriptions and points to verify-ui's [combat-switches](../../../verify-ui/features/combat-switches.md); `features/perception.md` points the fighter table at the same page. No verify-client script or inventory changed: neither the RLS tables nor the owner guard changed, and the game client is not an owner program.

**What was run:** nothing on this surface's scripts. The authority's privacy and equality proofs for both tables (`motion_tables.py` 34/34, `combat_feed.py` 17/17, `battle_viewers.py --privacy` at battle density) are dev-box's, recorded in `2026-11-20-0640-combat-feed.md` and `2026-11-20-0930-fighter-tables.md`, and this change does not touch them. What the connecting game client receives and shows across the switches is verify-ui's record `2026-11-20-1536-combat-switches.md`:
- the switch, kill switch, reconnect and fresh client: 197 / 197;
- no event missing, with 30 of 30 `combat_seen` rows taken;
- the death screen equal from both sources: 12 / 12;
- kB/s and near ages with each law on against off.

**Not covered here:** `game-client.md`'s byte recipe was not re-run; the per-player bytes on and off are in verify-ui's cost run instead.
