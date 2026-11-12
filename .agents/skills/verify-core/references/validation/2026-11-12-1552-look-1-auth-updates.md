# verify-core: look-1-auth, the update panic traced and guarded

## 2026-11-12 look-1-auth (dev-box)

This follows [2026-11-12-1454-look-1-auth.md](2026-11-12-1454-look-1-auth.md). That run found one `PANIC: tick … No such index` after publishing look-1-auth over a world made by main's module. Traced and guarded here (docs/LOOK.md §7 "The update panic, traced"). New: `common::schema_moved` first in `tick`, `housekeeping` and `genesis_step`; the driver `scripts/updates.py`; the feature file [updates.md](../../features/updates.md). The worker's own server `look1-stdb` (`v2.14.1`, `127.0.0.1:3337`).

- **Mechanism.** On the update the server log shows `ADDING TABLE COLUMN (incompatible layout)` for `projected` and `world`, then the two new tables. `st_index`: `world_id_idx_btree` 4268 → 4319, `world` 4192 → 4220. The backtrace is `tick` → `common::world` → `datastore_index_scan_point_bsatn`. Main's module, built with a panic hook naming itself, logged that the panic was its own, 20 ms after "Database updated". The new module's first tick resolved 4319 and ran. Ruled out: `init` on the planning database, `look.due`, a stale schedule. Evidence: `.local/look1/panic/` (server and module logs of each experiment, uncommitted instrumentation).
- **`updates.py --run core-updates-1112-164613 --relook fixture-1`**, on main `9d62be70` (`main-plan`), main + the guard patch alone (`main-guard`), this branch (`look-plan`) and this branch + one column on `world` (`look-col`, not committed):
  - main → look-plan: 1 PANIC (main's), ticking after it, `world` row, 9 characters and both timers kept; relook 5 looks, no panic.
  - main → main-guard → look-plan, three chains: 6 updates, 0 PANIC, one guard line on each step to look-plan; relook 5 looks each.
  - main-guard → look-plan → look-col: 2 updates, 0 PANIC, a guard line on each.
  - look-plan → look-col: 1 update, 0 PANIC, a guard line; the 5 looks kept.
- **Cost of the guard:** a temporary reducer timed 6,000 calls of `schema_moved` at 65–81 ms (about 11 µs each), so about 0.7 ms a second at 60 ticks plus housekeeping.
- A trap in the old instance discards nothing the new module needs. The new module's first instance starts with fresh ids.

Not covered: an update while players are connected; an update rewriting a table other than `world` that the old tick reads later in its call (the guard returns before any table is read, so it covers that too, but it was not driven); the shared server `sao-living_spacetimedb_1` and the reference worlds (not touched).
