# Staged genesis (verify-generation)

Branch `staged-genesis` (docs/STAGED_GENESIS.md): every seeded world is made by `genesis_step` after `init`; a land up to 2048 m keeps its inline resource draws. The worker's own server `sg-stdb` (v2.14.1).

- `generation-sg1` (the branch on main `0e310415`, rustc 1.97.1): island, plan-test, plan-test-floor, the authored worlds and the seed tests pass. Cullet's look-band checks ("the cases are of the world's generation", "each band case's resident wears its entry…") and both `cullet-laws` seeds' "the seed's laws are composed over the shipped script" fail exactly as on main (red on main; not genesis). `floor-megacity-4k` stalls after step 130 of 141: its hosting step runs out of energy (120 × 10⁹; `living/tools/genesis_fuel.py`), on main and on this branch alike (red on main, owner dev-box; the Spark's `cover-genesis` first). The run then stopped, before the second `realm`.
- `generation-sg2` (merged with main `a3ef6383e`, rustc 1.99.1): `realm` twice, **repeatability** (terrain, settlement sites, band sites, resource positions, names, ages, genes, animal spawn positions: all equal), **`floor-megacity-2k`** (made in 119 steps; on main its publish is refused, `init` out of energy), the malformed seed, original seeds unchanged and the seed tests: all pass.

## maintain-verification-skill, scoped to this change

Outcome: changed. `features/floors.md`, `features/seeded-world.md` and `features/repeatability.md` said worlds up to 2048 m are made inside `init`; they now describe staged genesis (`init` keeps the script, check and rules; `genesis_step` makes every seeded world; the harness waits for `genesis.done`), the 2k megacity's 119 steps and the 4k hosting step out of energy. No case was added or renamed; the README's rows still match the features.

Evidence: `.local/living/verify/generation-sg1/`, `generation-sg2/` (worktree, not in git).
