# battle-simplify: remove hidden-body reuse, keep cached `clip_root` and `body-return`

Follows [2026-11-27-2011-battle-spikes.md](2026-11-27-2011-battle-spikes.md) and [2026-11-27-2048-body-return.md](2026-11-27-2048-body-return.md). Controlled runs on dev-box (AMD 8060S: p99 12.46 ms with `nokeepbodies` vs 12.44 ms with reuse) and the laptop (Apple M4 Pro, `.local/living/battle-spikes/laptop/control/summary.md`: 1080p p99 7.77 ms off vs 8.30 ms on; native p99 9.97 ms off vs 9.75 ms on; 0–1 frames >16.7 ms either way) showed that keeping left-sight bodies hidden for reuse added no measurable frame-time gain over caching `anim::clip_root`.

**Branch** `battle-simplify`, from `origin/main` `f4eab28f3`. Laptop (Apple M4 Pro). All runs used private SpacetimeDB `2.14.1` containers with scratch worlds deleted after each run, a private `CARGO_TARGET_DIR` (`~/.cache/battle-simplify-target`), `build-slot` (`BUILD_SLOTS=1`), and the pinned render asset set `~/slop-assets/a7c606d204bb` linked via `render_set.py link`. Evidence is in `/Users/carlid/dev/slop-art-online/.local/living/battle-spikes/laptop/simplify/`.

**What changed** (game client, `verify-ui` skill/scenes and `docs/TOOLING.md` only; `living/authority`, `living/rules`, `living/scripts` and `living/bindings` untouched):

- **Removed:** hidden-body reuse in `live.rs` (`KEEP_S`, `KEEP_MAX`, `Kept`, `take_kept`, `dress_of`, `Shown::new`, `Shown::{stage,dress}`, `Live::{kept,parked,kept_bodies}`, the `nokeepbodies` perf flag, and `a_kept_body_is_shown_again_only_in_the_same_look`), plus reuse-only reset helpers `anim::afresh`, `ik::Legs::let_go`, and `characters::Springs::restart`, and the `kept` field of `ui/mod.rs`'s `bodies_json`.
- **Restored:** bodies leaving sight fade out where they were and are despawned (`live.rs`).
- **Kept:** `anim::clip_root` once-per-file cache; `Anim::stands`, `gait.rs` feet-log fields (`stand`, `stands`, `fade`, `entity`), and `ui/mod.rs` `bodies` (`drawn`) and `plates` dumps for `body-return`; `bench_battle.py`'s ANSI-strip fix; simplified `LIVING_GAME_PERF=diag` `bodies:` churn line (`gone`, `new`, `leaving`, `shown` every 2 s, no `HashMap`).
- **Updated:** `check.py body-return` simplified to one arm (15 checks, verifying every returner is built on a new entity with current pose, wound plate, look, and zero seated frames for C in the feet log), plus `SKILL.md`, `features/README.md`, `features/battle-views.md`, `features/body-return.md`, and `docs/TOOLING.md`.

## Unit tests

- `cargo test --release -p living-game`: **264 passed, 0 failed, 1 ignored** (`test-living-game.log`).
- `cargo test -p living-rules`: **386 passed, 0 failed, 17 ignored** (`test-living-rules.log`).

## verify-ui runs

All scratch worlds deleted after their runs; zero `ERROR` or panic lines in any `client.log`. Copies of `checks.json`, `body-return.json` and stills are in `/Users/carlid/dev/slop-art-online/.local/living/battle-spikes/laptop/simplify/tests/`.

- **Island (`ui-bsimp-isl-1128-022825`):** **250/250**
  - `body-return`: **15/15** (all three returners on new entities `same_entity: {A: False, C: False, B: False}`; A's plate 0.95 → 0.30; C 363 visible frames after `back`, 0 seated frames; B composed in new look)
  - `battle-views`: **144/144**
  - `camera`: **60/60**
  - `far`: **11/11**
  - `seat`: **20/20**
- **Cullet (`ui-bsimp-cul-1128-022825`):** **14/14**
  - `looks`: **14/14**

## Battle benchmark (interleaved, main vs battle-simplify)

`living/tools/bench_battle.py`, Classic, High 100%, uncapped, 3 reps per arm interleaved (`main` `f4eab28f3` vs `battle-simplify`), single `build-slot` hold (`BUILD_SLOTS=1`), 1-minute load < 4 before every rep (`load.log`, `series.log`, `summary.md` in `/Users/carlid/dev/slop-art-online/.local/living/battle-spikes/laptop/simplify/`):

| Resolution | Arm | Mean ms (rep range) | p99 ms (rep range) | Frames >16.7 ms (rep range) | Worst ms (rep max range) |
|---|---|---:|---:|---:|---:|
| 1920×1080 | main | 6.40 (6.22–6.61) | 8.06 (7.92–8.17) | 1/5,620 (0–1) | 244.93 (9.14–244.93) |
| 1920×1080 | simplify | 6.20 (6.06–6.30) | 7.76 (7.40–8.12) | 0/5,806 (0–0) | 11.29 (9.50–11.29) |
| 3024×1964 | main | 8.63 (8.58–8.66) | 9.87 (9.78–10.05) | 0/4,172 (0–0) | 11.66 (11.21–11.66) |
| 3024×1964 | simplify | 8.63 (8.58–8.70) | 9.92 (9.71–10.03) | 0/4,170 (0–0) | 12.48 (10.51–12.48) |

Matches the `nokeepbodies` arm of the laptop control (`1920×1080` p99 7.77 ms, `3024×1964` p99 9.97 ms, 0 frames >16.7 ms) within noise.

## Not covered

- `heed-throng`, `body-clock`, `hair`, `camera-lod`, `camera-faces` were not rerun (unchanged HUD/hair/camera paths).
- No dev-box battle bench run in this pass (laptop only; dev-box control already verified `nokeepbodies` 12.46 vs 12.44 ms).
