# Validation record (entry point and shared harness)

## 2026-11-11: launch keeps a seed's own laws, read back (`fix-verify-laws`)

Regression from `exp-player-frame` (b7328bc0): `launch` installed the plain `skills.rhai` over HTTP after every publish, so `--seed cullet` worlds ran without Cullet's laws while their seeded state reflected them. goods-2 (main 3b09d4a7) restored the skip: a seed with its own laws keeps the script its world installed at creation. On top of that one path, `launch` now reads the `script` row back and stops unless it is the seed's script, the shipped script with the seed's laws composed over it by `living/tools/install_script.py`'s `seed_script` (the one Python copy of `floors::compose`; `trials.py` imports it). `doctor` checks the seed's laws. Driven on the Spark's trial server (`slop-trials-stdb`, `LIVING_STDB_URL=http://127.0.0.1:3320`), merge 0bb1041b plus this change. Evidence: `.local/living/verify/core-vlaws2-cullet/` and `core-vlaws2-world/` (with `living-check.log`); the first round, before the merge, in `vlaws-cullet/`, `core-vlaws-cullet/`, `core-vlaws-cullet-laws/` and `core-vlaws-world/`.

| Check | Run | Result |
| --- | --- | --- |
| Fresh Cullet world: no install; the row read back equals `seed_script("cullet")` | `core-vlaws2-cullet` (`launch.txt`) | `the seed carries its own laws: kept as installed at creation (no install_script); the script row read back is the seed's script (sha256 5dcee9b135ee)` |
| `doctor` on Cullet | `core-vlaws2-cullet` (`doctor.txt`) | `ok installed script carries seed cullet's laws (worlds/cullet/laws.rhai, 15146 bytes)`, `ok world day is the seed's day_minutes 48 (day_ms 2880000)`; the row holds `fn hunger_awake() { 2.4 }` and `fn base_rates(` (`script-row.rhai`) |
| The bare script installed over Cullet is caught | `core-vlaws2-cullet` | `doctor` `FAIL installed script carries seed cullet's laws` (`doctor-bare.txt`); a `--keep-data` launch over it stops with the remedy (`launch-keep-bare.txt`); `install_script.py … --seed cullet` restores it and doctor passes (`doctor-restored.txt`) |
| `--keep-data` update of the Cullet world | `core-vlaws2-cullet` (`launch-keep.txt`) | kept; read back equal |
| Default seed | `core-vlaws2-world` | `installed skills.rhai; the script row read back is the seed's script (sha256 4f01dd9eecfc)`; `ok installed script is the shipped one without a floor overlay` |
| verify-core `tick` on each | `core-vlaws2-cullet`, `core-vlaws2-world` | 6 of 6 PASS on both (`tick.txt`) |
| `cullet-laws` seed (first round, before the merge) | `core-vlaws-cullet-laws` | launch and doctor as for Cullet |
| Trial runner laws guard, fake hamlet instance | `.local/living/trials/vlaws1/` | `laws guard passed: the script row read back is the source sent; the seed laws are composed as the world composed them; day_ms 2880000` before the mind started; ran its 3 minutes (`stopped_by: duration`); database and Neo4j minds cleaned |
| Guard self-test | `living/tools/trials_laws_selftest.py` (`vlaws1/laws-selftest.txt`) | 16 of 16: each planted mismatch (bare row after install, creation composition differing, wrong day, `keep_laws` on a bare world, a `wasm_tag` row without the laws) refused through `Instance.publish` on a fake database, with an `error` event |
| `just living-check` (`set -o pipefail`) | `core-vlaws2-world/living-check.log` | ok in 575 s, exit 0 |

Not driven: `--seed none` (floor modules get the bare script; `create_floor` composes), a real `keep_laws` or `wasm_tag` trial variant (self-test only), and paid runs.

## 2026-10-04: harness after the surface split and the review round

The harness changed after the first run, at the surface workers' and reviewers' requests. Each change was driven on a real run:

| Change | Proving run | Result |
| --- | --- | --- |
| Cleanup checks that a deleted database returns SQL 404 | every later run, e.g. `harness-1004` | `deleted … (SQL now 404)` |
| `launch` records the database before publishing | `harness-1004` | state saved before `publish` |
| `launch --target-dir` builds in the run's evidence directory, and cleanup removes the module copy | `harness-1004` | module copy `living_authority_verify_harness_1004.wasm` created, then removed |
| `launch --keep-data` updates in place | `harness-1004` | player character 268 survived the update |
| `sql --as-admin` reaches private tables | `harness-1004` | `deliberation` refused anonymously (`no such table … may be marked private`) and readable as admin |
| `LIVING_STDB_URL` limited to the local container | `harness2-a` | `http://10.0.0.5:3300` refused |
| Container ownership saved before the build, and no stop while other `verify-*` databases live | code path only | not driven; the container was already up |
| Shared observer: registry with pid and start time, last user stops it | `harness2-a`, `harness2-b` | b joined a's observer; a's cleanup left it up for b; b's cleanup stopped it and removed `observer.json` |
| `call … --expect-refusal` | `harness2-a`, `player-1004-170040` | player and anonymous `set_paused` refused (`admin only`); `mind_skip` refused (`not your character`) |
| `doctor` freshness includes `living/rules/src`; a dead observer reports FAIL instead of raising | `harness2-a` (live observer only) | the dead-observer branch was not driven |
| Callers passing old-style arguments to `launch`/`sql` in-process still work | Python import check | `verify-generation` reruns in the fix round |


## 2026-10-04: first end-to-end run

Generated with P-Stack `create-verification-skill` and run once through its own instructions on the Fedora host (rootless podman, SELinux enforcing). Code: commit `384fb50` plus uncommitted user changes in `living/viewer/src/clock.rs`. Evidence: `.local/living/verify/smoke/` (git-ignored, local to this machine).

| Step | Result |
| --- | --- |
| Launch | The module built from the working tree in about 7 s. `verify-smoke` was published from the `realm-4` seed and `skills.rhai` installed. The container was already up from setup, so the run did not record starting it. |
| Doctor | All checks passed: image `v2.10.1`, `stats.ticks` 49 → 288 in 4 s (60 Hz). |
| Drive `player-character` | Fresh HTTP identity. `join` gave character 254 (`ai` false). A second `join` was refused (`you already have a living character`, HTTP 530). `move 1 0` set `vx` 2.50. `move 0 0` stopped the body after 3.3 tiles, with plan `moving yourself`. `act gather → tree` started `gather` in phase 0. `say` wrote the `speech` chronicle line. `set_paused` as the player was refused (`admin only`). |
| Observer | `trunk serve` and a headless Chromium screenshot showed `lab: verify-smoke`, `live`, 172 people, 82 animals and the map. The player's speech line had already scrolled out of the visible story feed, so it was proven by SQL, not the screenshot. |
| Cleanup | The observer was stopped by pid, `verify-smoke` was deleted, the token was removed and the evidence remained. |

Fixes made during the run:

- `doctor` waits for the first `stats` row.
- `sql --save` logs to stderr so its JSON can be piped.
- Cleanup stops the container with a 60 s grace period and reports a forced stop.

The first attempt's evidence is in `.local/living/verify/first-run/`.

After the run, the SpacetimeDB container was stopped by hand to restore its earlier state. Podman's default 10 s grace period expired and it was killed with SIGKILL (exit 137), a forced stop, with only paused reference worlds loaded.

## Not yet verified

- `steering.md` and `mechanics.md`: `verify_steering.py` and `verify_mechanics.py` were not run in this pass.
- `launch` starting a stopped container itself, and cleanup's container stop. `--seed` builds other than `world` were since used by `verify-core`, `verify-generation` and `verify-knowledge`.
- Interactive observer checks: inspector, follow, pan and zoom.
- The public observer path.
- `minds.md`: requires an authorized authentic run.
- Discovery of this skill by agents other than Claude Code. This stopped being a requirement on 2026-11-11, when the project moved to Claude only. Claude Code lists `verify` from `.claude/skills/`, as seen in a session's skill list on that date.
