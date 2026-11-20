# fighter-tables: `seen_fighters_*` as a copy table, `seen_fighter_copy` (verify-client)

Branch `fighter-tables` (from `origin/main` `b3921c62e`), dev-box, `sg-stdb` (v2.14.1, 127.0.0.1:3344). Views step 3, fighters only (the GC):
- `seen_fighter_copy`: public, row-level security `viewer = :sender`, keyed by the private copy's key;
- `copy_state.fighters`, a new column with a default;
- the `fighter_tables_on` law, value-only, off by default;
- the frame's moves.

The Spark's two exact items wait for its review of the call shape and are not here.

**Shape change.** One public table and one RLS rule (`SEEN_FIGHTER_COPY_FILTER`), one column on the private `copy_state`, one law. The bindings were regenerated (`LIVING_GENERATE_CMD` through `sg-stdb`'s CLI). `maintain-verification-skill`, scoped:
- `drive.py`'s `RLS_TABLES` and owner guard;
- the probe (the table among the keyed ones);
- `gate-load` (`fighter_tables` option, privacy counts, windups from the copy);
- `battle_viewers.py --fighter-tables`, with its `--privacy` checks;
- `motion_tables.py` (34 checks);
- `SKILL.md`, `features/perception.md`, `features/README.md`, docs/PERCEPTION.md "Fighter copies as a table", docs/TICK_RATE.md's pin list, docs/BATTLE_VIEWERS.md addendum 5.

**Proofs:**
- **`motion_tables.py`** on a default world: 34 / 34, keyless (`client-ft1`) and keyed (`client-ft2`). A's table held B (near) and equaled `seen_fighters`; it was 0 to the owner with the law off and back on again.
- **The negative**, without the rule (`client-ftneg`): 5 / 34 fail (the fighter isolation checks, C's two subscribe-alls, "on again").
- **`battle_viewers.py --privacy --fighter-tables`** (16 viewers, 10 m ring, Cullet, 200 fighters): 17 / 17, both builds. Keyed: 195,243 fighter rows (plus 154,365 body and 55,719 character) checked by the viewers, 0 foreign.
- **The scene gate** (`cues`, `motion_tables`, `copy_privacy`, `--force --no-main-check`, genesis check off): all passed. They passed late, since the build-slot wrapper waited about 15 minutes at 40 GB free, under its 45 GB floor, until this worktree's test target was deleted.
- **Tests:** `cargo test -p living-rules` 359 passed; `living-authority frame::` 3 / 3 (`all_full` resets `FIGHTER_TABLES`); `cargo test -p living-game` 200 passed, 1 ignored.

**Measurement:** docs/BATTLE_VIEWERS.md addendum 5.
- **The keyless table** (the first build, a change a delete and an insert) cost 24–43 ms/s more tick WASM. Net database thread: 0 at 16 viewers, −22 ms/s at 216.
- **The keyed table:** −17.5 ms/s at 16 (about 12 µs/s a pair) and −37 ms/s at 216, with 16% more ticks a second.
- **The 0-viewer arm** now has its battle (`battle_viewers.py` fixed): 272 ms/s of tick WASM.

**On the way:** `sg-stdb` now runs in its own systemd user scope (`systemd-run --user --scope`). Its overlay filesystem helper had been killed with the creating shell call, about 5 minutes after each recreate ("unable to find user spacetime", port refused).

**Not covered:**
- the game client (the laptop's switch, with the default flip);
- an exact A/B of the moves with `det_compare.py` (the Spark's `ai-trims`, merging), which comes with the exact items.

Evidence: `.local/ft/runs/` (keyed), `.local/ft/runs-keyless/`, `.local/living/verify/client-ft*` (worktree, not in git).
