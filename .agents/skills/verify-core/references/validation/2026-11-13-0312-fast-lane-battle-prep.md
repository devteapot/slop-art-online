# verify-core: fast-lane-battle-prep

Branch `fast-lane-battle-prep` from origin/main `ec80c341`. Trial service `slop-trials-stdb`, `scoped`, private `CARGO_TARGET_DIR`, builds through `~/slop-mq/build-slot`.

- **The change.** Profiling-only counters in the fast lane (`common::diag`; nothing counted unless `set_profile` is on):
  - triggers, struck or seen-again; merged;
  - issued; stale; expired; gap-skipped;
  - the pump passes stopped by the in-flight cap or the rate bucket;
  - installed, refused and kept (`mind_patch`, `mind_fast_done`).

  No rule or behaviour changes.
- **`fast_diag`** (new scene) 12/12 (`core-flb2-035719`):
  - every counter fired: in its window, trigger_struck 46, trigger_seen 16, merged 49, issued 11, stale 3, expired 6, gap_skip 130, cap_inflight 935 and cap_rate 178 (passes), installed 1, refused 1, kept 1;
  - a window after profiling stopped showed no `fast:` keys.

  The first attempt (`core-flb-035544`) failed before any check: a victim died under 0.6 s strikes before the scene's health reset. Strikes are now every 2 s, with both victims topped up at each step.
- **The battle tool** (`living/tools/battle_diag.py`, not a verify surface): `--fast-real`, `--arm`, `--keep-plans`, `--fake-fast-patch`, and each sample's `defence`.
  - Free test `minds-flbt2-040645`: 20 fighters, 4 minutes, `--fast-lane --keep-plans --fake-fast-patch`.
  - Patches installed at about 1 a second, refused rarely; refills kept the fight going; the defence share was measured per window.
  - The world was deleted.
  - An earlier test without `--keep-plans` (`minds-flbt-040102`) stopped fighting after a minute. A "keep" compile rebuilt the fighters' bare fight graph around the body's needs, which is why the flag exists.
- **`just living-check`** (build slot, pipefail): exit 0 (864 s; authority, mind and viewer, viewer wasm, script gate, game, game tests, rules tests, seed laws).
