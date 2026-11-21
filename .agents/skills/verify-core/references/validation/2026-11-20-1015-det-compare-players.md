# det-compare-players: `det_compare` with players watching (verify-core)

Branch `det-compare-players` (from `origin/main` `641082645`), dev-box, `sg-stdb` (v2.14.1). Tools and the `det_clock` diagnostic only; play is unchanged. This is the Spark's three points, for prototype A/Bs with viewers:
1. **Content without the id columns.** The players' tables (`perceived`, `projected`, `seen_character_copy`, `act_outcome`, `line_seen`) are hashed by content with their id columns left out, in `det.rs`'s trace and in `det_compare.py`'s comparison of every table at the stop (`CONTENT`).
   - A sweep inserts `perceived` and `projected` rows in a hash set's order, which a module instance's history decides, so their ids, and their ranks, differ between two copies.
   - Their row counts stay in the hash. The other auto-increment tables keep their ids by rank, as before.
   - A gap pattern of the ids was tried and dropped. 2.14.1's random sequence skips put the gaps anywhere (they differed from tick 27), and ranks absorb skips only when the insert order is the same.
2. **The hearing salt follows `det_clock`:** a constant under the law (`SEED ^ 0x4EA2_5A17`), drawn as before in play.
3. **`prepare --players N --ring LO,HI`** (players joined over HTTP with no connection, placed round the battle) and **`run --cpus ""`** (unpinned: the dev-box's rootless podman has no cpuset controller). The output records `pinned` and `cpus`.

**Proof: this branch against itself** (`dc.wasm` both sides; Cullet, 200 fighters, 16 players on the 10 m ring, 1,200 ticks, unpinned):
- **Identical:** 1,200 ticks, 0 differing; 113 tables and 43,998 rows compared at the stop; 249 characters alive at the stop, so the battle was killing.
- **Before the fixes**, on the same fixture: 1,199 ticks differed. First `hear_salt` and `heard`, then, with the salt fixed, `perceived` and `projected` (by rank), `seen_character_copy`, `act_outcome` and `line_seen`.

**Not covered:** a run proving that a real difference still shows; a 216-player run.

Evidence: `.local/dc/` (worktree, not in git).
