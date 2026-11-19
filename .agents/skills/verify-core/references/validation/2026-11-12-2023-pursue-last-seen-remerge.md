# verify-core: pursue-last-seen after merging battle-scale and packs

## 2026-11-12 pursue-last-seen, main `b1f0af74` merged (Spark)

Follows `*-pursue-last-seen.md`. Merged battle-scale (`fe3b9093`: `brain.rs` familiarity, the 900 ms novelty cadence, the witness wake bound; this branch's `approaching` helper sat beside its `prune_familiar`, both kept, the diff against main in `brain.rs` is this branch's two additions only) and packs (`Goal.apart`: `Goal::creature` takes the target's place and `apart: 0.0`; `scenes.py` keeps main's `apart` scene and this branch's two).

- `core-pls4-190129`: `pursue_last_seen` 6/6, `flee_wall` 5/5, `intents` 24/24, `witness_wake` 5/5; `familiar_dense` and `notice_rate` failed (O knew 107 of a 360 crowd; 346 evaluations a second to 280 noticing passes). Both passed on main (`core-mainbs-192010`, this checkout at `0bfd8ad5`) and then on this branch (`core-brbs-192526`), host load 17–27: load, not the merge. `flee` on `stage1-acts` 4/4.
- After merging packs: `core-pls5-*` `pursue_last_seen` 6/6, `apart` 11/12 at host load 94 (wolves at `apart` 4: coverage 132°, a pair 1.0 m); `core-pls6-210823` `apart` 12/12 at load 49.
- `just living-check` passed (516 s).
