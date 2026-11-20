# genesis-followups: the world is marked done by a call after the last step (verify-generation)

Branch `genesis-followups` (from `origin/main` `b6aa74890`), dev-box, `sg-stdb` (v2.14.1, 127.0.0.1:3344).

**Change.** `genesis.updated_ms` on the done row was the last step's start (a module's only clock is its call's `ctx.timestamp`), about 4 s early on the island. Now:
- The last making step sets `steps` to `step` and schedules one more `genesis_step`.
- That call (`floor::finish`) sets `done`, the label `done` and `updated_ms`, and starts the tick.
- 2.14.1 stamps a scheduled call when its scheduler prepares it (`scheduler.rs` `scheduled_call_time`), after the scheduling step committed.
- No field was added. Step counts are unchanged.

Driven:
- **`verify.py launch --run client-gf1`** (default world): "world made in 1 genesis steps". Server log: the `genesis.world` span closed at 03:09:01.117; "the world is made (1 steps, 1646 ms)" at 01.127. The row's `updated_ms` is 1795144141127 (03:09:01.127Z), after the making step. Before this change the row would have shown that step's start, about 0.53 s earlier.
- **`verify.py launch --run generation-gfisland --seed island`**: "world made in 40 genesis steps". The `genesis.populate` span closed at 03:14:41.928 (1.84 s). "the world is made (40 steps, 7205 ms)" at 41.943. The done row reads `step 40, steps 40, label done`, `updated_ms − started_ms` = 7,205 ms, 15 ms after the last step. Before this change it would have shown populate's start, about 1.84 s earlier (about 4 s on the laptop).
- **`living/tools/genesis_fuel.py --seed world`** (its own stepping build): `steps` lists the one `world` step, 5,959,264,003 fuel (5.0%, as on main). `finish_fuel` is 82,779. `init` is 11.48 × 10⁹ (9.6%, as on main). Exit 0; the database was deleted by `world_delete`.
- **The mind's wait, on the same stepping module** (`.local/sg/tools/mind_wait.py`, database `verify-minds-gfwait-041131`): row before `step 0, steps 0, done false`. After two `resume_genesis` calls (the step, then the finishing call): `step 1, steps 1, label done, done true`, `updated_ms` after `started_ms`.

**Not run here:** genesis fuel for the island and the other land seeds (the coordinator's gate measures it for its seeds), `generation.py`, and the floor driver's stop and resume checks with the finishing call. `stop_genesis` between the last step and the finishing call leaves `step` = `steps`, so `resume_genesis` schedules the finishing call; this was not driven.

**`maintain-verification-skill`:** `features/floors.md` states the finishing call and `finish_fuel`. docs/STAGED_GENESIS.md "As built" records it.

Evidence: `.local/sg/gf-fuel-world.json`, `.local/sg/mindwait/` (worktree, not in git).
