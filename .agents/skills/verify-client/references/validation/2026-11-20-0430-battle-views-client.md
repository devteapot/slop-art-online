# The game client's subscriptions with the copy tables (`battle-views-client`)

- **Branch:** `battle-views-client` from `origin/main` `715aeb1ca`. Client-only: the authority, its tables, rules and bindings are unchanged.
- **Scope:** `maintain-verification-skill` on [features/game-client.md](../../features/game-client.md), for the change alone.
  - What changed in the game client's query set:
    - `seen_characters` left the base set (`PERCEIVED`, now 24) for the perception set (`net::Feed`).
    - `seen_body_copy` replaces the motion views while `motion_tables_on` is on.
    - `seen_character_copy` replaces `seen_characters` while `characters_table_on` is on.
  - With both table laws off, the queries are still main's.
  - The readers, `net::characters`/`find_character`, index the copy tables. A body now waits for its character row.
- **Live:** driven through verify-ui on `ui-bv-045109`, the real headless client: [verify-ui's record](../../../verify-ui/references/validation/2026-11-20-0430-battle-views-client.md).
  - Every switch subscribed the new set beside the old.
  - Each table-set subscription was accepted, and its rows were the player's own.
  - The kill switch emptied each table to the owner in 41–45 ms.
  - A reconnect and a fresh client subscribed the tables set only.
  - Bytes per client went through a TCP relay (`battle-views-cost`).
- **Not run here:** `motion_tables.py` (row-level-security isolation with three players and an anonymous connection). The tables, rules and module are main's, unchanged since its 27/27 on `battle-views` (2026-11-19-2200-battle-views-mirror.md). The scene gate's `motion_tables` case runs it on the merge.
- **Evidence:** `.local/living/verify/ui-bv-045109/`.
