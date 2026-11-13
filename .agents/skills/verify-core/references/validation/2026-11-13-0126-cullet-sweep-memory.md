# verify-core: cullet-sweep, module memory and rollback

Follows `2026-11-13-0022-cullet-sweep.md`. Branch `cullet-sweep` after the module-memory review: the durable `knowledge_epoch` table, the committed-tick guard, the 150-sweep full re-projection, and the `memory_test` law. Merged with origin/main `27d3b183d`. The worker's own server `sweep-stdb` (v2.14.1, 127.0.0.1:3340), `scoped`, one build tree (`.local/sweep/target`).

- **New cases** (`scenes.py`, Cullet):
  - **`sweep_rollback`** 9/9 (`core-mem2`).
    - Failures injected: ticks failing after their sweep (296 lines); ticks panicking (24, a new instance reported); `place_at`, `kill` and `join` each failing after their writes and rolled back.
    - Kept state cleared 148 times after failed ticks. 891 rows compared, 0 differed.
  - **`sweep_marks`** 6/6 (`core-mem2`): with memory marks dropped (`memory_test` 6), `mind_say`'s introduction reached the player's row in 0.22 s through its `knowledge_epoch` row. 627 compared, 0 differed.
- **Mutants:**
  - Keeping a rolled-back tick's kept state fails `sweep_rollback` (`core-mut-rb`, 18 differed).
  - Reading the knowledge mark from memory only fails `sweep_marks` (`core-mut-mk`: the name never came, 32 differed).
- **`sweep_kept`** 7/7 (1,893 compared, 0 differed).
- **`regard_check`** on plan-test (`core-mem2p`): pass, 1,177 compared, 0 differed.
- **An earlier round** (`core-mem1`, before the net counter fix) passed the same three cases.
- **Rules test** `attention_cues_are_the_world_s_laws` now covers `memory_test`: 0 in play, words present, rounded.
- **`just living-check`** with pipefail: exit 0 (562 s).
- **Maintenance, scoped to what the new table and law touch:** `features/sight.md` (the two cases, the law), `features/README.md`, the SKILL.md drive list.
- **Not run:** the rest of the baseline; the cases on another seed (they need a law that reads distance).
