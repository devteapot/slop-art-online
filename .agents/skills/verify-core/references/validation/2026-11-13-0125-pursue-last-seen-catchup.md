# verify-core: pursue-last-seen caught up with main (admin-set-vitals, battle-cheap, packs-2, pack-reflex-on)

## 2026-11-13 pursue-last-seen, main `da9dd6cb` merged (Spark, scratch server `slop-move-stdb` 127.0.0.1:3361)

`scenes.py` conflicted only where both sides added scenes before the `SCENES` line: main's (`howl_reach`, `pack_reflex` and the rest) are kept with their `SCENES[...]` registrations, and this branch's `pursue_last_seen` is added to the line. Every file that differs from main is one this branch's own commits touched.

- `core-pls7-*` (default seed): `pursue_last_seen` 6/6, `flee_wall` 5/5, `intents` 24/24, `apart` 12/12, `howl_reach` 4/4 (`pack_reflex` needs its own seeds:) `--seed pack-reflex-on` 5/5, `--seed pack-reflex-off` 3/3.
- `flee` on `stage1-acts` 4/4.
- verify-player `combat --scene all` (island): 54/54.
- `just living-check` passed (through `build-slot`).
