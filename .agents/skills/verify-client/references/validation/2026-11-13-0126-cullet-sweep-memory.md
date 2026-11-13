# verify-client: cullet-sweep, module memory and rollback

Follows `2026-11-13-0022-cullet-sweep.md`. A new private table, `knowledge_epoch`, and regenerated bindings. The regeneration also brought in `fight_seen`, battle-fold's private table, which main's bindings lacked. The worker's own server `sweep-stdb`; the probe rebuilt against the new bindings.

- **The suite** (`drive.py`, default seed, `client-mem-suite`): 43 PASS, no FAIL. `drive.py` `PRIVATE` gains `knowledge_epoch`; its inventory check passed. An anonymous subscription to `knowledge_epoch` is rejected as private (`private-knowledge_epoch.json`).
- **`sweep_rows.py --expect-kept`** on Cullet (`client-mem-rows`): 11/11, 2,058 rows compared, 0 differed.
- **`--compare`** against current main `dfe4718d4`'s module (`client-mem-main`, driven from an archive of main, built in a temporary tree since deleted): the same rows of the scene's people at all 7 steps.
- **`look_rows.py`** on Cullet (`client-mem-look`): 10/10.
- **Maintenance, scoped:** `features/visibility.md` (the table) and `scripts/drive.py` (`PRIVATE`).
- **Not run:** the open build; `far_label.py`, `earshot.py`, `room_address.py`, `house_label.py`.
