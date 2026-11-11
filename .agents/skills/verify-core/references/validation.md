# Core validation record


## 2026-11-11 rates-2: spoiling, regrowth, traps and remains in game time; the decay scene (dev-box)

Branch `rates-2` (from `f2d803fa`; origin/main merged twice, at `d92c67d5` with the cast and at `d538967f`), own container `rates2-stdb` (2.14.1, port 3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no minds. A maintain pass scoped to the features this change touches (laws, wildlife's remains, goods): their maps were read against the changed source, not by a source wave.

- `core-rates2-goods` (goods fixture): `goods` and `stock` pass. `core-rates2` (default seed): `needs`, `food`, `refusal` pass; `tick` failed `pause stops ticks, housekeeping and completion` because the giver's 3 s wait ended before the pause landed (its activity was already the final `wait 120`; four worlds shared the server). Rerun `core-rates2-tick` after the first merge: 6 of 6.
- `core-rates2-remains` (stage1-acts): `remains` passes with `remains_h` 3 game hours (90 s on the 12-minute day), its `rot` row due `remains_h × day_ms / 24` after `built_ms`.
- `core-rates2-laws` (cullet-laws): 15 pass, the mirrored dark spot skipped (as on rules-1).
- `decay` (new): the first run (`core-rates2-decay`) aimed the store act at `{"id": <structure>}`, which names a creature; it now aims at the nearest storage, and stores 100 (a storage holds `storage_holds`). `core-rates2-decay2`, a whole Cullet game day (48 real minutes): spoiling passes (543 of 1,000 carried left, the law 547; 87 of 100 stored), the node's `regen` passes; the regrowth check failed (7 gathered against 5.86 grown): gathering by `nearest` walked on to the valley's wild greens beds. It now reads the bed's own row after one gathering. The rerun on a fresh world (`core-rates2-decay3`, a whole game day) passes all five: 553 of 1,000 carried and 78 of 100 stored raw fish left after 48.0 real minutes (the law: 547 and about 82), and the emptied greens bed had regrown 5.891 units over 22.06 game hours, its `regen` of 0.131 a real minute (`regrow_per_h` 0.262) exactly.
- Cargo: `cargo test -p living-rules` 161 pass (9 ignored); `rates_check::rates_are_bit_identical` with `LIVING_OLD_SKILLS` (f2d803fa's script): 50,725 states, none differ.
- Not run on this change: seize, sight, senses, doing, moves, death-names, skirmish, low, drop, dealings, town, lives, infant, lifecycle, family_laws, wildlife, grazing, flee; mechanics and steering.

## 2026-11-11 lives-3: rhythms at any hour, Cullet's trades, Cullet's life law (dev-box)

Branch `lives-3` (from the coordinator's main `3faa7bfb`; origin/main `12fd78ef`, with Cullet's 64 drafted residents, then `bade5c09` merged), own container `lives3-stdb` (2.14.1, port 3321, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR` and `--target-dir`, `scoped`, no minds. Evidence under the worktree's `.local/living/verify/` (git-ignored).

- Cargo: rules 171 (163 pass, 8 ignored; new: `rhythm::tests` 4, `cullet_check::life_tests` 3, `cullet_check::ways_tests` 1), authority 18 (new: `drawn_rhythms_keep_their_phase`, `seeded_rhythms_rise_at_any_hour`), mind 82; `just living-check` exits 0. The phase test failed once in a first draft (an hour within float rounding of rising read as bedtime); the rule keeps the old `h < rise + 24` term since.
- `rhythm.py` (new scene, derived Cullet seed, 12-minute day): `core-l3rhythm1` (before the merge, cast compiled without sheets) 17 of 20: the habits' `take` walked to a storage that had none and back (fixed: `take` targets a storage that `holds` the item), and the scene's people had no food (the seed has no stores yet; the scene now gives them some). `core-l3rhythm2` (after the merge, the seed's own residents with sheets) 19 of 20: "the night stoker is asleep at home in the morning" counted only `sleep`, while in bed hours a rested person rests at home (`keep warm`); the check now counts asleep or resting (re-scored from the same samples: 1.0). `core-l3rhythm3` (final tree) 20 of 20: Thessaly rises at 14:00, bed 31.0, works 22:00–06:00; Anselm 13:00, works 19:30–06:00; Pieter's second sleep 13:00–19:00; Tobiah (16) and Col (15) adults, Halvard (70) an elder; the stokers and the blower start with `stoke the Cone` and `blow glass`; 09:00–13:30 the day stoker at the Cone 32 of 32 samples, the furnace lit 31 of 32, `feed` and `make` seen, the night stoker in bed at home 0.97; 15:00–18:30 she is up 25 of 25 and off work, the baker asleep 25 of 25; 23:00–04:00 she is at the Cone 0.85 and keeps the furnace lit 28 of 33 with 8 feeding samples, the day stoker in bed at home 33 of 33, the lamp keeper at the Watchglass 33 of 33; nobody died of age.
- `town.py` on an island run (`core-l3-town`): 22 of 23. "A resident faces someone who comes up behind them" failed, and failed again in 3 reruns on that world and 2 of 3 on a fresh one (`core-l3-town2`). On an origin/main build (`bade5c09`, no authority or rules change since the merge point; `core-l3base-town`, evidence kept in `.local/lives3/base-evidence/`) it passed 1 of 5. The recorded flake, more frequent today on both builds; not this change.
- `lives.py --minutes 24` on island runs: `core-l3-lives` 17 of 19 (two carriers did not set out), `core-l3-lives2` 18 of 19, and `core-l3base-lives` on the origin/main build 18 of 19 with the same failure: Tavvik, the meat carrier, never leaves (stages reached none of 10). Not this change (the island's graphs have no `work_hours`, its rhythms are drawn and unchanged); a finding for the lives owner: the 2026-11-11 `core-hunger-101946-lives` run had 19 of 19.
- After merging origin/main again (`f793143a`: eye-2's sight, kit-1's plan fixtures): `rhythm.py` 20 of 20 (`core-l3rhythm4`), rules 166 pass (8 ignored), authority 18, `just living-check` exits 0.
- Not run on this change: tick, needs, food, refusal, seize, sight, senses, moves, skirmish, dealings, goods, stock, laws, infant, lifecycle, wildlife, remains, flee; mechanics and steering.


## 2026-11-11 rules-offers: every know-how can be taught (Spark)

Branch `rules-offers` (from main `74a6d8a`, then `35c0717` merged), on the Spark, in the trial container `slop-trials-stdb` (2.14.1, port 3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped` unless named, no model calls. Every scratch database answered 404 after cleanup. `scenes.py teach` (new) on `core-teach-1111-184247`: 6 of 6, twice (`teach-results-fixed-2.json`). With origin/main's `skills.rhai` installed on the same world it gave 2 of 6: the teacher was told "there is no technique called fire_bolt (the techniques are: spear, fire, masonry, …)" (`teach-results-main-rules.json`). Cargo: `every_know_how_can_be_taught` and `cullet_s_glassmaking_can_be_taught` pass.

## 2026-11-11 eye-2: things open at eye height are see-through (dev-box)

Branch `eye-2` (from main `eead7a29`, uncommitted at the time of the runs), own container `eye2-stdb` (2.14.1, port 3317, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no model calls. Every scratch database answered 404 after cleanup.

| Scene | Run | Result |
| --- | --- | --- |
| `sight` (default world) | `core-eye2v` | 6 of 6 |
| `senses` (default world) | `core-eye2v` | 6 of 6 |
| `low` (island; 9,153 low tiles since eye-2) | `core-eye2v-skirmish` | 5 of 5; the run crossed low tiles at (437, 174)–(437, 175) (`low-spots.json`), no longer only a cart's |
| `drop` (plan-test) | `core-eye2v-drop` | 5 of 5 |
| Rules | `cargo test -p living-rules` (in `just living-check`) | 154 passed, including `host::tests::a_well_and_an_open_stall_are_seen_through_but_a_closed_building_is_not`, `sight_is_blocked_only_above_eye_height`, `eye_cells_decode`, `pinned_digests_hold`, `map::tests::drops_and_low_things_are_told_in_words` |

Maintained in the same change: sight.md (low things since eye-2, the rules tests, the night-sight gotcha of `drop`/`low`), SKILL.md, features/README.md and `scenes.py`'s docstring no longer say a low thing is a cart.

## 2026-11-11 drop-1: drops and low things are see-through (dev-box)

Branch `drop-1` (from `6a905c31`, origin/main `fd2030c3` merged), own container `drop1-stdb` (2.14.1, port 3315, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no minds. Evidence under the worktree's `.local/living/verify/` (git-ignored).

- `core-drop1-20261111-153740` (default seed): cargo checks (rules 148, authority 12, mind 82, viewer sync 5), `sight` 6 of 6, `senses` 7 of 7, `moves` 5 of 5. Its steering run failed to publish (the module copy's name has underscores for hyphens: `living_authority_verify_<run with _>.wasm`); rerun in `core-drop1b-20261111-154703-steering`: 5 of 5.
- `core-drop1-20261111-153740-island`: `sight` 6 of 6 on the island.
- First `drop` (plan-test) and `low` (island) runs in `core-drop1-20261111-153740-drop`/`-island`: sight across both passed; the walk check failed on a harness defect, not a rule: it compared CLI samples about 2 s apart (a 2.8 m "jump" was a walk round the drop's end), and the geometry picked the obstacle's very end. The check now walks the route the authority keeps (`body.path`) and the geometry keeps away from the ends.
- `core-drop1b-20261111-154703-drop` (plan-test): `drop` 5 of 5. `core-drop1b-20261111-154703-island`: `low` 5 of 5 (a cart's tiles; the watcher across it waves and witnesses; the walker's route never crosses it).
- Not run on this change: tick, needs, food, refusal, seize, skirmish, dealings, town, lives, laws, infant; mechanics.
## 2026-11-11 the laws of starting a family and of the longing for a child (exp-hamlet-births, Spark)

Branch `exp-hamlet-births` from main `4df9a89`, worktree, the trial service `slop-trials-stdb` (2.14.1, `LIVING_STDB_URL=http://127.0.0.1:3320`), private `CARGO_TARGET_DIR`. New scene `family_laws` (`core-family-20261111-142152`, stage1-acts): 9 of 9. Its first attempt (`core-hamlet-20261111-141837-family-laws`) passed the conceive checks and then failed for two scene bugs. One was a `str.format` on the script. The other came after it was fixed (`core-family-20261111-141949`): the empty-handed adult dropped its food only after the law was installed, so it had felt the longing for a moment with food in hand. The scene now empties hands first. `lifecycle` 6 of 6 (`core-hamlet-20261111-141837-lifecycle`). Baseline `core-hamlet-20261111-141837`: tick, needs, food, refusal, seize, sight, senses and moves pass (42 checks). `cargo_checks.py`: rules (the new `laws_with` longing values, `longing_wait_ms` equal to the old `20 − nurture/6`, and the `deathline` values `births_report.py` ports), authority 12, mind 82 and viewer sync 5 pass. `just living-check` exits 0. Not run: skirmish, dealings, town, lives, infant (about 2 h; cry routing is untouched), mechanics, steering, wildlife.

After merging main `fd2030c` (rules-1: a seed's day and laws; only the night call in `brain.rs` conflicted): `family_laws` 9 of 9 (`core-family-20261111-150942`), `lifecycle` 6 of 6 (`core-life-20261111-151946`), `just living-check` exits 0 (rules 145), authority lib tests 12 of 12.

After merging main `7837320` (fix-death-labels, fix-perceived-moving, plan-2; only the verify skills conflicted): `family_laws` 9 of 9 (`core-family-20261111-155914`), `lifecycle` 6 of 6 (`core-life-20261111-160034`), `just living-check` exits 0.

## 2026-11-11 fix-death-labels (Spark)

Branch `fix-death-labels` (rebased on main `6a905c3`, then on `a8d95fc`), the trials stack's container `slop-trials-stdb` (2.14.1, port 3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`; `verify.py` now accepts its `0.0.0.0` binding), private `CARGO_TARGET_DIR` and `--target-dir` per seed, no minds.

- **Reproduced before the fix** (`core-deathnames-before`, main `4df9a89`, new scene `death-names`): the member who saw it read "A stranger was killed by a stranger" and "the remains of a stranger"; the killer read "A stranger was killed by Walker3" (his own name). 2 of 6 checks passed.
- After the fix: `death-names` 8 of 8 on `4df9a89` + change (`core-deathnames-after`, with and without the victim yielding) and on the rebased `2cd7fa0` (`core-deathnames-rebased`): member "Walker1 was killed by a stranger after yielding" and "the remains of Walker1", killer "A stranger was killed by you after yielding", bystander strangers; one `acquaintance` row (the member's).
- `cargo_checks.py` pass (rules 145, authority 13 with `the_one_an_event_was_done_to_reads_it_as_done_to_them`, mind 82, viewer-sync 5); tick, needs, food, refusal, seize, sight, senses, moves pass; `skirmish` 8/8 (island).
- `remains` (stage1-acts): `core-deathnames-rb-remains` failed "a wander keeps its heading between waits" (4 of 6 turns within 1.6 rad; fatal, so the expiry check did not run); a fresh world `core-deathnames-rb-remains2` passed 10/10, as did the pre-rebase `core-deathnames-remains`. Wander is not touched by this change; six turns is a small sample.
- `laws` (cullet-laws, `core-deathnames-rb-laws`): all pass, including names only within 24 m; one SKIP (the mirrored dark spot is not open ground, a fixture limit).
- `just living-check` exit 0.
- On `a8d95fc` + this change (`core-deathnames-head`, `core-deathnames-head-laws`): `cargo_checks.py` pass (rules 145, authority 15, mind 82, viewer-sync 5); death-names 8/8 with the same texts; doing, tick, needs, food, refusal, seize, sight, senses, moves pass; `laws` pass (the same SKIP); `just living-check` exit 0. `remains` and `skirmish` were not rerun on this base (last run on `6a905c3`).
- Not run: town, lives, infant, lifecycle, wildlife, mechanics, steering, dealings.
## 2026-11-11, branch fix-graph-say-id (a graph's say: the speaking limit, feedback)

Spark, the trial stack's server (`slop-trials-stdb`, v2.14.1, :3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), worktree on `origin/main` 7a75f6b, private `CARGO_TARGET_DIR`, no minds. Report checked: "a resident's `say` to `{"id": N}` silently fails while `strike` to the same id works".

- Before the change (`core-sayid-i`, island, world hour 7.6, speaker and listener 3 m apart in the open): all 24 combinations of four written forms, three target spellings (`{"id": N}`, `N`, `{"nearest": …}`) and two install paths (`set_behavior`, `mind_install`) spoke to the listener; `do` wave and strike to the same id acted. What failed: the second of two lines within the 2 s speaking limit (two installs back to back, or two says in one `seq`) was never spoken, and a say to someone out of sight left no experience (`say-prefix.txt`, `say-back-to-back.json`, `say-two-lines.json`, `say-out-of-sight-feedback.json`). Cause: the say node set its 45 s pacing mark before `speak`, so a line refused as "speaking too fast" was skipped as done on the next look; a missing listener failed with no feedback.
- After (`core-sayid-j`, island): the new `scenes.py say` passed 34/34; the second lines came 2.15–2.25 s after the first; the out-of-sight line gave one `own` experience ("You failed to say "…": no #313 in sight").
- Baseline on the default seed (`core-sayid-d`, say placed after refusal): tick 6, needs 7, food 4, refusal 4, say 34, seize 6, sight 6, senses 7, moves 5 passed; `doing` failed, as it did twice in `core-sayid-b`. All three failures read the observer's scene at night (`time.night`, sight 6 m, world hour 1.2–4.8), with the walkers and follower 8–10 m away; the passes (`core-sayid-c` say then doing, and the `origin/main` control `core-sayid-main` senses then doing, without the change) ran by day (sight 11 m). So `doing` depends on the world's hour, not on the change: a baseline long enough to reach the default seed's night fails it. An earlier reading here (the say scene's actors crowding the scene) was wrong; the say scene still moves its actors off the line, and now runs last in the baseline so it does not push `doing` toward dusk. The `doing` scene should hold its cast within night sight or wait for day; not changed here.
- Cargo (`cargo_checks.py`, `core-sayid-c`): rules 145, authority 14, mind 82, viewer sync 5. `just living-check` passed. Skirmish 8/8 (`core-sayid-j`), mechanics 23/23, steering 5/5 (published from the run's own module with `--wasm`).
- On the pushed head b9f9662: `just living-check` passed (a first attempt failed in `living-authority`'s build script, compiled for the removed control worktree with its seed path; `cargo clean -p living-authority` on the shared target dir fixed it: `core-sayid-head/living-check-attempt1-stale-build-script.txt`). `core-sayid-head` (default seed, documented order, say last): cargo 4/4, tick 6, needs 7, food 4, refusal 4, seize 6, sight 6, senses 7, moves 5, say 34 passed; `doing` failed at world hour 1.4 (night, sight 6 m) before say had run. The control `core-sayid-main2` (`origin/main` 7a75f6b, senses then doing) passed both by day (hour 10.4). `core-sayid-headi` (island, hour 7.7): say 34/34 (second lines 2.25 s after the first), skirmish 8/8.
- Not run: dealings, town, lives, laws, infant, lifecycle, wildlife (no shipped instinct or seed graph has a say node; only mind-written graphs do), and verify-minds (the mind protocol is unchanged).

## 2026-11-11 rules-1: a world's own day and laws (dev-box)

Branch `rules-1`, own container `rules1-stdb` (2.14.1, port 3312), private `CARGO_TARGET_DIR`, no minds. Baseline `core-rules1-base` (default seed): cargo checks (rules 138, authority 12, mind 82, viewer sync 5) and tick, needs, food, refusal, seize, sight, senses, moves: 45 of 45. New `laws` scene on `cullet-laws` (`core-rules1-cullet`): day and rates, 48 m by day, names within 24 m pass; the first night attempt saw nothing (`laws-attempt3.txt`: the HTTP player had been taken over by the world's minds after `takeover_s`), fixed by a player call before each snapshot; the night rerun passed (14 m, a torch at 44 m, lamplight at 21 m, no cold harm). Two earlier attempts failed on the scene itself (a regex for `sight_in`'s `_` arm; no 54-tile east-west line on the 96 m map, replaced by `open_ray`).

## 2026-11-11 plan-1 (dev-box)

Branch `plan-1` (hand-authored plans, docs/AUTHORED_PLANS.md; it adds `lot:<id>` place kinds in `town::seat` and seed `homes`, unused by the island), own container `plan1-stdb` (2.14.1, port 3311), private `CARGO_TARGET_DIR`. `town.py` `core-plan1-town-20261111-135920` on the island: 22 of 23; the failure is the recorded flake "a resident faces someone who comes up behind them" (Cuth Marrow, player stopped 1.6 tiles away). Not run: the baseline scenes, skirmish, dealings, lives, infant, lifecycle, wildlife.


## 2026-11-11 goods-1: goods as data, fires that eat fuel (dev-box)

Branch `goods-1` (origin/main `4df9a895` merged), own container `goods1-stdb` (2.14.1, port 3313, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. Evidence in the worktree's `.local/living/verify/`.

- `cargo_checks.py` (`core-g1-11111404`): rules 136, authority 12, mind 82, viewer sync 5 pass. `just living-check` exits 0.
- Baseline `core-g1-11111404` (default seed): tick, food, refusal, seize, sight, senses, moves pass. Its doctor failed only "module newer than sources" (the shipped campfire's `light` was removed after the build). `needs` failed on a harness race, not the rules: after the cloak the scene waited for `rate_key` to change and caught the reset (0) the new rest writes, so it read an awake rate (`needs-cloaked.json`, key 0). The scene now waits for the key holding the cloak, rest and night bits. `codes.py` failed its two refusal checks because the test skill `zap` had no `zap_spec()`, which installs have required since 2026-11-10; it now declares one.
- Rerun on the final build `core-g2-11111431`: doctor clean; `needs` and `codes.py` pass.
- Mechanics 23 of 23 (`core-g1-11111404-mechanics`), steering 5 of 5 (`-steering`), `skirmish` and `dealings` on island worlds pass.
- New: `goods` 20 of 20 and `stock` 4 of 4 on the goods fixture (`core-g1-11111404-goods`). An earlier attempt (`core-goods-135558`) passed the 20 fire and recipe checks and failed the shared-stock check because the valley also grows wild fishing spots; the stock check moved to its own scene, which selects pooled nodes.
- Harness: `install_script` goes over HTTP (the script passed 128 KiB, past one command-line argument): `verify.py launch` and `call @FILE`, `Scene.call` for large arguments, `codes.py`.
- **After merging origin/main `6a905c31` (rules-1, plan-1)**, on the merged build: `cargo_checks.py` (`core-g3-11111501`) rules 149, authority 12, mind 82, viewer sync 5; tick 6, needs 7, food 4, refusal 4, seize 6, sight 6, senses 7, moves 5, `codes.py` 14, all pass; mechanics 23, steering 5, skirmish 8, dealings 16 pass; `goods` 22 (the fixture now names Cullet's laws: the seeded hearth lit for its fuel's burn and a seeded kelp bed, then the same chain) and `stock` 4 pass; rules-1's `laws` on `cullet-laws` (`core-g3-laws-11111501`, its lamp now burning seeded oil) 15 pass. `set -o pipefail; just living-check` exits 0.
- **After merging origin/main `90f6fac1` (feel-5, talk-1, sight-2)**: `just living-check` exits 0; `cargo_checks.py` (`core-g4-11111539`) rules 149, authority 14, mind 82, viewer sync 5; tick, food, sight, senses, moves, mechanics 23, `goods` 22 and `stock` 4 pass; verify-client `client-g4-11111552` 31 of 31.
- **After merging origin/main `3f2f3443` (cullet.json with its laws; plan resources)**: `just living-check` exits 0 (rules 152); authority tests 15 (with `the_cullet_seed_is_hosted`); verify-generation `generation-g5-11111604` island 977, cullet 64, cullet-laws 41, plan-test 71 checks pass; `goods` 22 and `stock` 4 pass (`core-g5-11111607-goods`).
- Not run: `town.py`, `lives.py`, `infant`, lifecycle, wildlife, remains, flee (long scenes; the rules they read did not change except warmth, which the goods scene and `needs` cover).


## 2026-11-11 lives-2 after merging laws-2 (dev-box)

Branch `lives-2` at `2c1fb5a` (main `8e6bae4` merged), own container `lives2-stdb` (2.14.1, port 3461), private `CARGO_TARGET_DIR`. The script installs (every law described, `minds` gone). `core-laws-053424`: tick, needs, food, refusal pass. `town.py` `core-laws-town-054630`: 21 of 23; own hours, one new day each and evenings out pass; "faces someone who comes up behind" (recorded flake) and "faces someone who speaks" failed, and both passed on a fresh world (`core-laws-speak-*`: speak, approach, speak), so a timing flake. Also verify-minds `resident` and verify-client 30 of 30 on the same build; `just living-check` exits 0; rules tests 130, mind tests 82.

## 2026-11-11 every person a mind, survival secondary, no lockstep (lives-2, dev-box)

On the dev-box worktree `~/dev/slop-lives2`, branch `lives-2` (d87310d unit 1, 6157bf0/055d80e/efcd489 units 2-4, 45d4ac6 the new-day fix), own container `lives2-stdb` (2.14.1, port 3461, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, fake model only. Several suites ran at once (load 25-45); one batch failed on a full disk (`No space left on device`, the whole dev-box at 98 %) and was rerun.

- Unit 1 baseline `core-l2u1-015035`: tick, needs, food, refusal, seize, sight pass.
- Units 2-4 `core-l2b-022738`: needs, food, refusal, seize, sight pass; tick missed 60 Hz at load 44 (49.7 Hz); `core-l2c-030713-tick` passes at load 34. Reruns `core-l2c-030713`: needs (the new cold law: a cloak removes the cold's tiring, an ordinary night does not hurt), food, refusal pass; infant passes (a summer night's cold does not hurt the exposed infant).
- `town.py` `core-l2c-030713-town`: 21 of 23. New checks pass: each keeps their own hours (277 rhythms, rising 4.0-8.0 h sd 0.75, bed 19.5-25.4 h sd 1.22), each person's new day begins once (268 people, at most 1 each), the square and the inn fill with those whose evening is out. The two failures are recorded flakes: step-aside (three approaches, no step) and facing someone who comes up behind. `core-l2b-022738-town` failed the evening check before it counted only evenings out (people whose evening place is their work were "at their evening place" at midday).

## 2026-11-11 laws-2 (dev-box)

Branch `laws-2` (from `445db09`), worktree `~/dev/slop-laws2`, own container `laws2-stdb` (2.14.1, port 3447, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. Evidence archived on the Mac under `.local/living/laws-2/verify/`. The first parallel batch (`*-l6`, eleven worlds at once) overloaded the server and then filled the dev-box disk; its tick (45 Hz) and needs timeouts were load, and its failures are kept.

- `cargo_checks.py` pass; `scenes.py` tick, needs, food, refusal, seize, sight, moves pass (`core-l6c`); `senses` 7 of 7 (`core-x4-senses`); `skirmish`, `dealings` (`core-l6-*`), `town.py`, `infant` pass; `lives.py` 24 min pass (`core-l6c-lives`); mechanics and five steering checks pass (`core-l6-mechanics`, `-steering`).
- **Found and fixed:** `needs` timed out on the first rerun: a new body never got its need rates, because the key with unknown thresholds could equal the initial key (unit 3's `NeedLaw::cuts`). A body whose thresholds are not known now always asks the law. The first `lives` failure (a fish runner reaching no stage) was the same bug.
- **Scene fixes:** `senses` failed three times on its own graph: a watcher already facing a spot is refused ("you already face it"), so it now faces the subject and then turns away, and the scene waits for the expected watchers (at most 30 s) instead of a fixed sleep. The same scene against the unit-2 build failed the same way, so it was the scene, not the rules.

## 2026-11-10 fix-rules-small (dev-box)

Own container `rules-small-stdb` (2.14.1, port 3417), private `CARGO_TARGET_DIR`, head `9115e59` for the sweep. `cargo_checks.py` pass; `scenes.py` tick 6/6, food 4/4 (new), refusal 4/4 (new), seize, sight, needs pass (`core-rs-final`); flee 4/4 (new) and grazing 3/3 with its new `doing` check (`core-rs-final-stage`, stage1-acts); steering 5/5; mechanics 23/23; skirmish and dealings pass; `town.py` 20 of 21, failing "a resident faces someone who comes up behind them", the scene's recorded flake (above, on base worlds too). Not run: lives, infant, lifecycle, wildlife (its 20-minute migration).

## 2026-11-10 world rules on records (Mac)

Branch `rules-2` (`eaee6b0`, from main `bbf7271`) in a worktree, the worker's own container `sao-rules2-stdb` (2.14.1, port 3342), private `CARGO_TARGET_DIR`. `scenes.py dealings` (new; island): 16 of 16 on `8bc4f14` and again on `eaee6b0` (`core-rules2-deal1/`, `core-rules2-final-dealings/`). Regression: `tick`, `needs`, `seize` 6/6 each (default seed, `core-rules2-final/`), `skirmish` 8/8 (island). `just living-check` exit 0, rules 120 passed. Not run: `town.py`, `lives.py`, `infant`, mechanics. Design and numbers: docs/WORLD_RULES.md.

## 2026-11-10 island food: berries and store places, a food round (Mac)

Branch `hunger-1` (main `7e5de53` merged in) in a worktree, the worker's own container `hunger-verify` (Docker Desktop, 2.14.1, port 3382) through `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`: `town_life.places` gains `berries` and `store`, `town_life.spread` shares `berries` out like work, and the island's own "find food and eat" walks a round when nothing edible is in sight ([D2](../../../../docs/SOAK.md#d2-the-islands-residents-starve-in-the-first-hours)). Free tier only.

- `cargo_checks.py` (`core-hunger-101946`): rules, authority, mind and viewer sync pass. `tick` 6 of 6, `needs`, `seize` and `sight` pass.
- `town.py` (`core-hunger-101946-town`) 20 of 21: the step-aside scene's three approaches got no step (its recorded flake, above). Rerun of that scene alone (`core-hunger-101946-aside`) 1 of 1: made way on the second approach.
- `lives.py --minutes 24` (`core-hunger-101946-lives`) 19 of 19.
- The same checks on the seed before `spread` (`core-hunger-080229`, from `fe6ec66`): tick, needs, seize, sight pass; town 21 of 21; lives 19 of 19.

## 2026-11-10 walking routes (Mac)

Branch `path-1` (from `fe6ec66`) in a worktree, the worker's own container `path-stdb` (Docker Desktop, 2.14.1, port 3391): walks planned leg by leg over regions and areas, acts walking to a place outlast `APPROACH_MS` (docs/PATHS.md). Free tier only.

- `cargo_checks.py` (`core-path1`): rules 116 (4 new `nav::` tests), authority 11, mind 66, viewer sync 4. `tick` 6 of 6.
- `verify_steering.py` (`core-path1-steering2`, `--wasm living_authority_verify_core_path1.wasm`: on a worker's own server the driver's default `/wasm/living_authority.wasm` does not exist) 5 of 5; `verify_mechanics.py` (`core-path1-mechanics`, same `--wasm`) 23 of 23.
- `town.py` (`core-path1-town`) 20 of 21: "a resident faces someone who comes up behind them" failed (the scene's recorded flake, above; its 6 m approach is a clear straight line, which `route_leg` answers without planning). "A worker reached a workplace away from home": 239 tiles from home.
- Walking load (`walk_times.py --residents 150` with `bench.py`, docs/PATHS.md "The tick with many walkers"): 150 of 150 residents moving at every 10 s sample for 7 min, 165 km walked, tick p99 1.64 ms, 0 ticks over 16.7 ms; the same orders on `fe6ec66` moved nobody, tick p99 5.0 ms, 4 ticks over.

## 2026-11-10 hospitality and habit engagements (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), branch `townlife-2` (main `015707b`, the `harness-1` merge, merged in) in a worktree: town life layer 2, phase 2 (docs/TOWN_LIFE.md): woken minds made from facts and their ring, the `woken` route, the stage cap, `host`, the `habit` engagement class, names only when known (a feeling is no longer an introduction).

- `cargo_checks.py` (`core-cargo-tl2`): rules 109, authority 10, mind 64, viewer sync 3.
- `town.py`: `core-town-tl2b` on the final code 21 of 21; `core-town-tl2` before the name rule 20 of 21 (the step-aside scene's three approaches got no step; residents look once a second, layer 1's open risk).

## 2026-11-09 town life layer 2, phase 1 (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `14f3a72` plus the uncommitted town life layer 2 phase 1 change (docs/TOWN_LIFE.md, "Layer 2"): the `woken`, `prior` and `prior_head` tables, the `wakes` and `woken_ring` laws. Free tier only; no model calls.

- `cargo_checks.py` (`core-cargo-l2`): rules 108, authority 10, mind 49, viewer sync 3.
- `town.py` (`core-town-l2`, island): 21 of 21. The player's wave and speech now wake the resident they reach; its starting ways still answer and face.
- Tick cost, `core-wakebench`: three fresh island arms back to back, 300 s each (base `14f3a72`, this change at rest, 20 residents woken by `wake_many.py`). p50 2.16 / 2.12 / 2.14 ms, p99 4.58 / 4.92 / 5.07 ms, none over 16.7 ms; the Mac's load average was 3.5–8.2 from other sessions. Ring: 1.45 entries a second at rest. Numbers and caveats in docs/TOWN_LIFE.md, "Phase 1 measurements".

## 2026-11-09 the Rhai boundary, rhai-1 (dev-box)

- **Setup:** a private container `rhai-stdb` (2.14.1, own volume, port 3392), driven through `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`. Worktree `~/dev/slop-rhai`, branch `rhai-1`.
- **Before the merge of main** (`1bc1327`), run `core-rhai1-184757`:
  - `cargo_checks.py`: rules 108, authority 10, mind 49, viewer sync 3.
  - `tick`, `needs`, `seize`, `sight` pass. In `needs`, the exposed and cloaked HP rates differ by 2, through the rates that are now parameters.
  - `codes.py`: 14 of 14, including the three install refusals. Each names its function, and the revision stays 5.
  - Skirmish (island): 8 of 8. Steering: 5 of 5.
- **Mechanics:** the first run crashed in the yield scene. The walker who yielded heard no "had yielded" news and was later killed; the next `place_near` then found no body. Base (`9ea831f`) against branch, alternating, on fresh worlds (`rhai1-mech-ab`): branch 23 and 23, base 23 and 23. It did not reproduce, so it is recorded as this driver's intermittent failure, not as caused by the change.
- **After merging `origin/main` `2a64837`** (`33e3185`, scoped perception):
  - Town: `core-rhai1-town-192712` passed 20 of 21, failing "a resident faces someone who speaks to them".
  - Town again, branch against main: branch 20 of 21 (failing "faces someone who comes up behind them"), main 20 of 21 (failing step-aside).
  - That is the scene's movement flakiness on both arms.
- **Not run:** the infant, lifecycle and wildlife scenes.

## 2026-11-09 minds' sight (Mac)

On the Mac (Docker Desktop, shared `sao-living_spacetimedb_1`, 2.14.1), main `81b9dd8`/`dc5e41b` plus the uncommitted minds'-sight, projection and presence change (docs/PERCEPTION.md, "Second change"; docs/PLAYER_MEMORY.md, "Presence and the offline character"). Fake model only; every scratch database answered 404 after cleanup. `core-perc2`: `cargo_checks.py`, `tick`, `needs`, `seize`, `sight` (new: 6 of 6) pass; `core-perc2-skirmish` passes; `core-perc2-mechanics` and `-steering` pass. `core-perc2-town` 20 of 21: "a resident faces someone who comes up behind them" failed, and failed in three solo runs on one world; on a base (`972aefd`) world the scene passed once and failed on the next run, so it is the scene's known flakiness, not shown to be this change. The infant scene was not run.


## 2026-11-09 town life (dev-box)

Own scratch container `slop-townlife-stdb` (image `v2.14.1`, own volume, `/wasm` from the worktree's `.local/target`) through a `docker` name shim (`~/townlife-shim`); worktree `~/dev/slop-townlife`, branch `townlife-1` from `b12fa45` with the town-life change uncommitted (docs/TOWN_LIFE.md). No mind service, no model calls. Evidence under the worktree's `.local/living/verify/`.

- **Cargo** (`core-town-cargo2`): rules 87 (adds `island_ways_are_valid` and two `social` tests), authority 10, mind 47, viewer sync 3. A first run (`core-town-cargo`) did not compile the authority tests: one still read `Seed::habits`, which moved to the seed's ways; fixed.
- **Baseline** (`core-town-base`, default seed): `tick`, `needs` and `seize` passed; `skirmish` passed 8 of 8 on an island run. `verify_mechanics.py`: 21 of 23 (`-mechanics-1`, failing the documented conception and expecting-parent pair) and 23 of 23 (`-mechanics-2`). `verify_steering.py`: 5 of 5. These ran before the climate moved from the script's laws into the seed (until then a default-seed world could rain); on the final code `core-town-final-mechanics` passed 23 of 23. Both drivers were given the default-seed module explicitly (`--wasm living_authority_verify_core_town_base.wasm`): this container's `/wasm` mount is the island build directory, so its `living_authority.wasm` is the island's.
- **Town life** ([features/town.md](../features/town.md), `scripts/town.py`): `core-town-4` 18 of 19 (the first step-aside scene found no guard at a gate; rewritten to find any narrow spot), `core-town-5` 21 of 21, `core-town-6` 20 of 21 on the final rules (the approach scene placed the player on unwalkable ground behind the resident; the driver now picks a walkable lane from behind and walks until close). `core-town-7` re-ran greet, approach, speak and aside on the final code: the first three passed, step-aside did not get a response (residents look once a second; the walker can pass the 2.5 tiles between two looks), so the scene now makes up to three approaches; `core-town-8` passed on the first. Making way was seen on 3 of 4 single approaches across runs, and the step itself was "broken off" after 0.4 s until `aside` skills latched like finishing work (`brain.rs`).
- **Census** (`core-town-census`, `--scene census`): the hour-by-hour table in docs/TOWN_LIFE.md.
- **Not run here:** the infant, lifecycle and wildlife scenes (30 minutes or more each); this change does not touch those rules, and with no `weather` in their seeds those worlds never rain.

## 2026-11-09 island land worlds (dev-box)

`core-20261109-021430` ran on the dev-box with the scratch 2.14.1 container `slop-game-stdb` (`docs/ISLAND_AUTHORITY.md`, "Verification"), on `dc34fdf` plus the island change: patched map cache, `Map::path` without whole-map arrays, `rules.minds`.
- **Cargo:** rules 72, authority 10, mind 47, viewer sync 3.
- **Scenes:** `tick`, `needs` and `seize` passed.
- **Drivers:** `verify_mechanics.py` passed 23 of 23, including road, wall and gate built, and gate shut and opened. `verify_steering.py` passed 5 of 5.
- **Not run:** the infant, lifecycle and wildlife scenes (30 minutes or more each). The births change (`rules.minds`) keeps the old controller when the flag is on.

## 2026-10-04 fix round

Ran the skill on Fedora with rootless podman and SELinux enforcing. Branch `living-core`, commit `384fb50e379533b7db64698357efd0b2323f9452`. The existing `living/viewer/src/clock.rs` change was preserved. This task changed only `.agents/skills/verify-core/`. No product source, shared harness, adapter, reference world or Neo4j A was changed.

The running container and CLI are SpacetimeDB 2.10.1. The CLI commit is `3d7607082ab47257adeb7c25164536511237f2b5`. Version evidence is in `core-fix-20261004-impl/stdb-version-flag.txt`. The unsuccessful `stdb version` probe is also retained; the supported flag is `--version`.

Evidence paths below are relative to `.local/living/verify/`. The baseline run is `core-fix-20261004-impl`. Its fresh companion worlds are `-life`, `-steering`, `-mechanics-1` through `-mechanics-4`, and `core-fix-20261004-impl-retry-wildlife`. Every database has the `verify-core-*` prefix.

| Feature | Result | Current evidence |
| --- | --- | --- |
| Tick, housekeeping, pause and resume | PASS, exit 0. The cadence probe observed 324 ticks over 5.4 seconds of authority time. Paused clock, stats and activity stayed unchanged; resume completed the gift. Actual profiling spans were retained. | `core-fix-20261004-impl/tick-results.json`, `tick-actions.jsonl`, paused snapshots, `tick-profile.txt`, `tick-exit.txt` |
| Graph parsing, normalization, evaluation and routines | PASS in Cargo, live mechanics and steering. Installed graphs and full routine rows are retained. | `core-fix-20261004-impl/rules.txt`; `core-fix-20261004-impl-mechanics-4/installed-brain-*.json`, `installed-routine-*.json`, `stdb-actions.jsonl`; `core-fix-20261004-impl-steering/stdb-actions.jsonl` |
| Skills, laws and exchanges | The four mechanics attempts passed 21/23, 23/23, 16/23 and 23/23. The complete four-attempt results appear below. Steering passed runtime law replacement and input refusals. | `core-fix-20261004-impl-mechanics-*/mechanics.json`, `mechanics.txt`, `stdb-actions.jsonl`; `core-fix-20261004-impl-steering/steering.txt` |
| Needs over time | PASS, exit 0. Hunger, idle energy, rest and eating changed as expected. The cloak increased night healing rate from 1.5143297 to 3.5143297. | `core-fix-20261004-impl/needs-results.json`, `needs-actions.jsonl`, idle, rest, food, cold and cloaked snapshots, `needs-exit.txt` |
| Life course | PASS, exit 0. A new infant was born, pregnancy was removed, rearing began, birth was chronicled and the seeded infant aged to child. Mechanics attempt 4 passed death cleanup and expecting-parent retention. | `core-fix-20261004-impl-life/lifecycle-results.json`, `lifecycle-actions.jsonl`, born, expecting, rearing and aging snapshots; `core-fix-20261004-impl-mechanics-4/mechanics.json` |
| Wildlife and ecology | PASS, exit 0. All 13 checks passed on the documented fresh wildlife world. Five adult founders arrived after the real cooldown; all spawned on edge grass and the next minute kept the same founders. | `core-fix-20261004-impl-retry-wildlife/wildlife.txt`, `wildlife-actions.jsonl`, `wildlife-results.json`, grazing, extinction, newcomers, chronicle and cooldown snapshots, `wildlife-exit.txt` |
| Combat and graded force | PASS for five ordinary scene checks. Healthy yielded seize was `XFAIL KNOWN ISSUE` until the 2026-10-04 fix (`act.rs` `skill_ctx`), after which `core-seize-01` showed it passing and it became an ordinary check. Mechanics attempt 4 passed threat, hurt, yield and wolf reluctance. | `core-fix-20261004-impl/seize-results.json`, `seize-actions.jsonl`, `seize-yielded-seize-feedback.json`, yield, inventory, witness and killed snapshots, `seize-exit.txt`; `core-fix-20261004-impl-mechanics-4/mechanics.json` |
| Deliberate acts | All five reported checks passed in mechanics attempt 4. Attempt 1's conception failed; its gift reported PASS despite a blocked-path refusal. The weak gift predicate limits what its PASS establishes. Cargo passed single-node act validation. | `core-fix-20261004-impl-mechanics-4/mechanics.json`, `stdb-actions.jsonl`; `core-fix-20261004-impl-mechanics-1/diagnostic-walkers.json`; `core-fix-20261004-impl/rules.txt` |
| Steering and viewer display sync | PASS, exit 0. All five live steering checks and three display-sync tests passed. This is all the viewer code covered by this skill: `living/viewer/src/sync.rs`. | `core-fix-20261004-impl-steering/steering.txt`, `stdb-actions.jsonl`, `steering-exit.txt`; `core-fix-20261004-impl/viewer-sync.txt` |

## Offline checks

`cargo_checks.py` ran its four documented commands. No ignored tests ran. No mind service or model provider ran.

| Package and filter | Result | Evidence in `core-fix-20261004-impl/` |
| --- | --- | --- |
| `living-rules` | 45 passed, one ignored | `rules.txt` |
| `living-authority --lib seed::tests` | Five passed | `authority-seed.txt` |
| `living-mind` | 15 passed, five ignored | `mind.txt` |
| `living-viewer sync::tests` | Three passed | `viewer-sync.txt` |

All four exits were 0, recorded in `cargo-results.json`. The status-contract probe in `known-status-contract.json` separately verified XFAIL exits 0 and XPASS exits 1 without changing the product. The real seizure scene exercised XFAIL; a product-fixed XPASS scene was not available.

The cadence window had 173 living people and 82 animals. It used admin SQL, no body subscription or observer, and a short profiling interval after the cadence probe. Other verification databases shared the service. This short functional check does not establish latency, memory, resource or population acceptance. Steering uses a real body subscription; life and wildlife use admin calls and SQL on the eight-person, 16-deer, three-wolf `stage1-acts` seed.

## Historical 16/23 failure

This is history, retained for comparison. The unchanged driver passed 23/23 in `core-1004-tests/`, 16/23 in `core-1004-proof-mechanics/`, then 23/23 in `core-1004-final-mechanics/`. The preserved failed run contains the following exact failed keys.

| Failed check | Recorded output and state in `core-1004-proof-mechanics/` |
| --- | --- |
| `tablet written and given` | `false` in `mechanics.json`, `FAIL` in `mechanics.txt`. Artifact 5 stayed with holder 259, Walker1, rather than 260, Walker2. Chronicle recorded the tablet write six times. |
| `reading taught spear` | `false` and `FAIL`. Walker2's know-how query returned only `writing` from `granted`, without `spear`. |
| `learned technique used (spear crafted)` | `false` and `FAIL`. Repeated inventory queries returned berries 3, stone 3 and wood 4, without a spear. |
| `atomic trade` | `false` and `FAIL`. No trade chronicle appeared. Walker2's feedback later said "You failed to accept → Walker1: they moved away". |
| `teaching` | `false` and `FAIL`. Walker2's know-how remained only the granted writing entry, without planting. |
| `act: conception chosen by both as acts` | `false` and `FAIL`. The expected Walker3/Walker4 pregnancy never appeared. The retained expecting rows were unrelated animals. |
| `death clears the body's rows; an expecting parent keeps its genes` | `false` and `FAIL`. The diagnostic printed `lived True`, all five cleared-table counts 0, and `parent kept False`. There was no qualifying walker pregnancy. |

The raw SQL and calls are in `stdb-actions.jsonl`. The relevant original actor feedback was extracted, without changing the original evidence, to `core-fix-20261004-impl/historical-experience-259.txt`, `historical-experience-260.txt` and `historical-experience-261.txt`. Successful CLI calls did not establish the expected physical outcomes.

## Four fresh mechanics runs

Each run published a fresh database, used the unmodified `living/tools/verify_mechanics.py`, saved calls, SQL and installed graph rows through the recorder, then used shared cleanup. Product source was unchanged between runs. Counts are driver-reported results, subject to the weak predicates below.

| Run | Pass count | Exit | Failing checks |
| --- | --- | --- | --- |
| `core-fix-20261004-impl-mechanics-1` | 21/23 | 1 | `act: conception chosen by both as acts`; `death clears the body's rows; an expecting parent keeps its genes` |
| `core-fix-20261004-impl-mechanics-2` | 23/23 | 0 | None |
| `core-fix-20261004-impl-mechanics-3` | 16/23 | 1 | The same seven keys as the historical 16/23 run above |
| `core-fix-20261004-impl-mechanics-4` | 23/23 | 0 | None |

Every row has its own `mechanics.json`, `mechanics.txt`, `mechanics-exit.txt`, `stdb-actions.jsonl` and `cleanup.txt`. Failures remain FAIL. They were not turned into expected failures or removed after a passing retry.

## Likely causes and driver limits

The fresh attempt 1 diagnostic gives a concrete route failure. Walker3's feedback says "give berries → Walker4: the way is blocked" and "conceive → Walker4: the way is blocked". Walker4 says "conceive → Walker3: cannot reach them". Those rows are in `core-fix-20261004-impl-mechanics-1/diagnostic-walkers.json`; its wall and gate setup is preserved in `stdb-actions.jsonl` and `diagnostic-structures.json`.

Placement and unsynchronized setup are likely contributors. `living/authority/src/lib.rs:123,124` randomizes spawn positions. `living/authority/src/seed.rs:679` randomizes genes. `living/authority/src/lib.rs:132` installs a forager repertoire; the driver waits at `living/tools/verify_mechanics.py:77,79`, then leaves later scene actors running instincts until their turn. `place_near` at `living/authority/src/lib.rs:262` places a body one tile east without checking that the tile is free. The driver builds wall and gate tiles at `living/tools/verify_mechanics.py:164,165`, then places the act pair in that area at `living/tools/verify_mechanics.py:185,186`. Blocked routes in fresh attempt 1 are observed. Exact overlap with a particular wall or terrain tile, and the original tablet failure's cause, are not proven by the retained snapshots.

`living/authority/src/act.rs:794` rechecks distance at completion and reports a moved-away target. `living/authority/src/brain.rs:365,366` restarts a failed sequence. That explains how a failed give can repeat writing, but does not identify which refusal caused the original give failure. Nearby AI activity, fixed waits such as `living/tools/verify_mechanics.py:113`, and terrain-dependent movement remain plausible contributors rather than established causes of every failure.

Two driver predicates can report PASS without the named outcome. The gift predicate at `living/tools/verify_mechanics.py:197` accepts any berries in Walker4's inventory, including spawn or gathered berries. The feedback predicate at `living/tools/verify_mechanics.py:199` can match the preceding successful eat. Fresh attempt 1 therefore reported gift PASS while actor feedback recorded its refusal.

The conception predicate at `living/tools/verify_mechanics.py:141` accepts any pregnancy. In fresh attempt 1 it returned animal rows before either walker had conceived. The next scene replaced their graphs at `living/tools/verify_mechanics.py:147,148`. Its final death check selected no expecting walker, so the failure does not by itself establish broken inheritance retention. Attempt 2 drove a real expecting walker and passed retention.

[mechanics.md](../features/mechanics.md) tells readers how to recognize the intermittent failures, preserve dependencies and distinguish them from a possible regression under controlled preconditions. These findings are recorded here; the product driver and authority were not patched.

## Changes made in this round

- `scenes.py` writes PASS, FAIL, XFAIL and XPASS statuses. Ordinary failures and XPASS exit 1; XFAIL alone does not fail the run.
- `scenes.py` reads the installed brain row after every graph replacement. `record_stdb.py` reads complete brain rows after `set_behavior` and complete routine rows after actor-specific routine probes. Reducer acceptance cannot substitute for checking normalized graphs.
- The recorder retains cleanup ownership after the driver deletes its database so the shared harness confirms HTTP 404. Mechanics attempt 2 exercised this path.
- All feature file-and-line references were checked against source. Seize witnesses are at `living/authority/src/act.rs:913,917`; life-stage changes start at `living/authority/src/tick.rs:213`. Needs and real-time act references were corrected too. The 52-reference audit is in `core-fix-20261004-impl/source-reference-audit.json`.
- `SKILL.md` states that `just living-check` builds authority WASM, mind and both viewer targets, while its test step runs only rules tests. It includes startup preconditions, removes "now verifies", and limits viewer coverage to `living/viewer/src/sync.rs`.
- The graph map describes lenient normalization and discarded warnings in `living/rules/src/graph.rs:385,386,459,460`, rather than a strict parser.
- Wildlife was driven on its own fresh documented world. The first attempt, `core-fix-20261004-impl-wildlife`, timed out waiting for grazing after delayed setup. It was cleaned up and its files remain. The complete retry uses its own launch, doctor, grazing, migration and cleanup evidence. No other scene's files were renamed into its run.

## Documentation and compatibility

Consulted the [official documentation](https://spacetimedb.com/docs/), [reducers](https://spacetimedb.com/docs/functions/reducers/), [scheduled reducers](https://spacetimedb.com/docs/functions/reducers/lifecycle/) and [indexes](https://spacetimedb.com/docs/tables/indexes/). The served pages identify version 2.0.0. Actual APIs, tables and flags were checked against pinned and running 2.10.1 source and CLI.

Design implications remain the same. A reducer transaction can accept an intention before its later physical result. Let the real scheduled reducers execute, inspect actor-indexed outcomes and retain original refusals. No authority schema, index, subscription or persistence design changed. Whole-population queries are bounded fixture setup or diagnostics, and scratch cleanup limits active data retention.

The shared skill source, frontmatter, feature headings, links, executable flags and Python syntax were checked. Claude Code and Cursor links resolve to the same `.agents/skills/verify-core/` source that Codex and Mistral Vibe discover. `core-fix-20261004-impl/discovery-audit.json` records these static checks. Live registration and invocation in the four runtimes remain unverified. No adapter changes were needed.

The recorder keeps using `living/tools/stdb` for admin scenes and the existing drivers' CLI subscription protocol. It does not duplicate token parsing or container ownership checks. Launch, doctor and cleanup remain with the shared harness. No shared-harness change was requested.

## Cleanup and remaining limits

All nine owned databases are absent with SQL HTTP 404, including the failed wildlife attempt and all four mechanics worlds. Their evidence and cleanup transcripts remain. `core-fix-20261004-impl/cleanup-audit.json` records each database and its retained result files. The already-running shared container remains up; no observer process was started or stopped. `product-state-start.json` and `product-state-finish.json` confirm unchanged product source hashes and the preserved unrelated viewer change.

The known healthy-yielded seizure defect remains open at `living/authority/src/act.rs:238` and `living/scripts/skills.rhai:496,500`. Mechanics is intermittent, and its gift and broad conception predicates can overstate coverage. The exact original tablet-transfer failure remains unresolved.

This run does not establish sustained performance, resource bounds, long-term ecology, wolf migration, every graph combination, natural old-age death, act queue limits, genuine model inference, player permissions, private subscriptions, or observer UI behavior. Use the neighbouring skills listed in `SKILL.md`. Display-sync tests are the entire viewer coverage here.


## Infant thermal perception and cry requests, 2026-10-04

The scoped `baby-warmth` pass added `scenes.py infant`, `scripts/infant.json` and the documented infant baseline. Product commit `6001413` fixes an evaluator-timer defect found during the live run. The thermal phase used the original infant implementation at `b2f115c`; the final cry interval used that implementation plus the exact product changes subsequently committed as `6001413`. The baseline authority was built from `6db8d1f` in the temporary `baby-baseline` worktree. The verification driver and fixture were shared; no baseline product changes were applied.

### Scene and predicates

The seed has four adult family members and their infant. The scene adds a caring witness and a remote shelter anchor. It holds behavior on rest and waits for real night and hunger at least 70, suppressing positive healing. There is no time-setting reducer; `set_paused` was used during diagnosis and the in-place fix, outside the final interval. Species, rules and vitals were not patched.

The sheltered infant's parent-visible `looks` was `warm, hungry`, with HP rate 0. The exposed infant's `looks` was `cold, hungry`, with HP rate -2 per minute. Derived HP fell from 100.93207 to 100.6487 across the exposure probe. Thermal predicates passed on both authorities; the old authority omitted the new appearance assertion.

The cry phase feeds adults to suppress their own survival alarms, cloaks the infant and gives a bounded berry meal. Hunger then crosses 55 through real rates. An explicit signal/wait graph emits cries about every seven seconds. For a 250-second window, one parent acknowledges through `mind_skip`; the other leaves its request pending. No minds connect and no model calls occur. The changed authority passed parent-only routing, one prompt for the pending parent, an answered-parent reminder gap of 126.453 seconds, an unchanged hunger-only cause for over 120 seconds, and a caring witness receiving signal experiences without crying deliberations. With parents and witness over 75 tiles away, caring adults at one and two tiles yielded exactly one cry request for the nearest adult.

### Counts and method

| Authority/run | Valid windows | Authority seconds | Created | Merged | Prompts per infant per minute |
| --- | --- | --- | --- | --- | --- |
| `6db8d1f`, `core-infant-before-01` | 1 | 251.704 | 5 | 13 | 4.290754 |
| `6001413` product, `core-infant-after-01` | 1 | 251.572 | 3 | 0 | 0.715501 |

Each window contains one crying infant and seven live characters: infant, parents, witness, two fallback adults and the remote anchor. Six dead preparation actors remain as retained rows, so each world has 13 character rows. Four actors occupy the local cry site; alternatives are remote during measurement. Admin SQL polls at about 1 Hz plus CLI overhead; there are no core SDK subscriptions, model service or observer. This is a bounded prompt-workload comparison, not a performance or model-call claim. The initial prompt is included; fallback is outside the rate window.

The changed branch counts `InfantCry.prompted` stamps matched to actual crying request rows. The baseline matches signal `experience.at_ms` to a request containing the baby's crying reason whose requested/updated interval spans that stamp. Actor/stamp pairs are deduplicated. This excludes unrelated dawn and reflection request updates while preserving those raw observations. Per-event records carry the full corresponding request and classify creation versus merge using `requested_ms`.

There were three preparation interruptions and two invalid/interrupted measurement attempts per authority, retained in `preparation-*` and `measurement-*`. Attempt 1 counted unrelated request updates; attempt 2 missed the initial stamp because the driver captured its start clock after installing the signal graph. The final driver captures time first and uses cry-specific stamps. One valid interval per revision completed after these corrections. `--resume-infant` reused the thermal checkpoint on the same owned world. `infant-verification.json` combines the original passed thermal checks with the final cry checks and points to both source result files; original failures remain intact.

### Evaluator-timer defect and fix

`mind_state.marks` holds graph evaluator markers alongside action-owned markers. The merge retained only evaluator IDs below `0xD000`, dropping reserved root-completion, failure and reflection timers at `0xFFFE`, `0xFFFD` and `0xFFFC`. After quiet reflection became due, a pending request refreshed roughly every two seconds. `6001413` preserves these evaluator timers through merges and clears them on graph replacement, while retaining action-owned markers below that reserved range. No schema or bindings changed. Both `reflection-proof.json` files preserve the comparison: baseline lacks the reflection marker and advances request `updated_ms` during ten seconds; the changed branch retains it and leaves `updated_ms` unchanged. Independent source review found no remaining concrete defect in this fix or the corrected cry counter.

### Baseline, visibility and evidence

`core-smoke-infant-{01,02}` ran Cargo, tick, needs and seize before and after the fix. Every command exited 0. Both runs passed rules 47 (one ignored), authority 9, mind 28 (five ignored) and viewer sync 3. Tick, needs and seize each passed six live predicates. `baseline-exits.json`, `cargo-results.json`, transcripts and individual scene results retain the outcomes. The scoped graph and needs maps were maintained; unrelated core features were not re-audited or driven in this pass.

`client-infant-visibility-{01,02}` ran the entire documented client wrapper before and after the fix: all eleven private tables, including `infant_cry`, refused anonymous SDK subscriptions and HTTP SQL; all 164 reducer-permission calls matched. Views, live updates, reconnect and ad-hoc speech passed. Public `experience` and `thought` leaks remain known XFAILs. See the client validation record.

Evidence lives under `.local/living/verify/`. Infant runs retain `infant-verification.json`, `infant-prompt-rate.json`, `infant-prompt-events.jsonl`, `infant-request-observations.jsonl`, thermal/cry/fallback snapshots, action transcripts, diagnostics and cleanup. `.local/living/verify/baby-live/report.md` records commands, commits and limits. The baseline evidence was copied into the branch before removing its temporary worktree.

### Documentation, compatibility, cleanup and limits

Consulted official [documentation](https://spacetimedb.com/docs/), [tables](https://spacetimedb.com/docs/tables/), [indexes](https://spacetimedb.com/docs/tables/indexes/), [performance](https://spacetimedb.com/docs/tables/performance/), [views](https://spacetimedb.com/docs/functions/views/) and [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) before the authority fix. Served docs identify 2.0.0; pinned/running 2.10.1 was checked against [official versioned Rust bindings](https://github.com/clockworklabs/SpacetimeDB/blob/v2.10.1/crates/bindings/src/lib.rs). The fix keeps the existing row-local mind-state representation. Diagnostics read a bounded fixture, with primary-key vitals/cry queries and small request/experience snapshots. No production tables, indexes, subscription recipients or retention policy changed.

Shared discovery links, frontmatter, executable helpers, local documentation links and Python syntax were checked for Codex, Claude, Cursor and Mistral Vibe. Scoped source-reader reviews checked needs, graph markers and client visibility. The existing adapters resolve to shared files and required no edits. Live runtime menu and instruction-loading checks remain unverified.

All six scratch databases were deleted with SQL HTTP 404. Their evidence remains; module copies and player tokens were removed. The baseline worktree was removed. The shared server stayed running; reference worlds and Neo4j were untouched. There were no new environment symlinks or real model calls.

Live winter damage, infant campfire placement, starvation, wounds, urgent changed-cause routing, connected mind responses, multi-infant rates, long-term survival, scale/resource acceptance and browser presentation remain unproven here. Rule/authority unit checks cover some policy variants; they do not establish those live outcomes.


## Cry reminders with unrelated pending requests, 2026-10-04

Authority commit `722975d` changes only the pending-cry predicate in `perceive.rs`. Reminder timing remains in the existing infant episode's per-carer stamps. The predicate recognizes this infant's visible and hearing-only reason forms; unrelated pending reasons and other infants' cries do not suppress a due reminder. The existing exact-reason guard remains. No tables, reducers, views, subscriptions, bindings or model protocol changed.

`cargo test --manifest-path living/Cargo.toml -p living-authority -p living-rules` passed: authority 10, rules 47 with one existing ignored test. Feeding the old `pending.is_some()` input to the new cadence regression failed on the unrelated due reminder, exit 101. Restoring the cry-specific input made the full command pass again. Transcripts are in `.local/living/verify/core-cry-01/`.

The documented infant launch used `R=core-cry-01`, `I=$R-infant`, the skill's `scripts/infant` fixture and `living/target/verify-infant`. Launch and doctor exited 0. The original full scene, using the driver from `722975d`, passed all 16 checks and exited 0. Dawn naturally created the answered parent's unrelated request 64.439 seconds after the initial cry. The reminder merged into that row at 126.352 seconds, retaining its requested timestamp and dawn reason. Pending cry suppression, physical checks, witness experiences and nearest-carer fallback passed. This attempt is preserved under `.local/living/verify/core-cry-01-infant/ordinary/`, including `natural-overlap-summary.json` and its original driver.

The added deterministic step installs a one-shot unrelated `think` graph at 60 seconds, saves its request, then returns the parent to rest. A doctor-checked `--resume-infant` run drove both new assertions successfully: the unrelated request appeared at 60.701 seconds and received the cry at 126.770 seconds with its original timestamp and reason preserved. Its cadence and pending-cry checks passed too. The rerun nevertheless exited 1 during subsequent fallback setup: `place_near(1, 7)` reported `no such body`. The retained remote anchor had died of starvation during the additional elapsed time. `resume-anchor-character.json`, `resume-anchor-body.json` and `resume-anchor-death.json` prove that separate fixture failure. Per the task's narrow-fix constraint, it was reported without expanding the product fix. The full modified scene has not yet passed end to end on a fresh fixture.

Consulted official [tables](https://spacetimedb.com/docs/tables/), [indexes](https://spacetimedb.com/docs/tables/indexes/) and [performance](https://spacetimedb.com/docs/tables/performance/) guidance before implementation. The existing primary-key request and infant lookups remain; only a due selected carer's request is merged. Pinned dependencies, lockfile, CLI and running server image are 2.10.1; existing accessors were checked against the installed versioned official Rust crate. No environment symlink or model service was needed. Codex and Mistral read the shared source; Claude and Cursor discovery links resolve to it. Runtime menu invocation was not exercised. This scoped pass did not re-audit other core features, run mind/client/browser checks, or establish performance, scale or hearing-only live behavior.

Cleanup exited 0, removed the published module copy and confirmed the scratch database absent with SQL HTTP 404. Both attempts' evidence remains. The shared server stayed up; reference worlds and Neo4j were untouched.

## 2026-11-09 starter combat skills (dev-box)

Own scratch container `slop-combat-stdb` (v2.14.1); worktree at `e0c9d1f` plus the combat change (docs/COMBAT.md). `core-combat-20261109-054716`: `cargo_checks.py` pass (rules 82, authority 10, mind 47, viewer sync 3); `tick`, `needs`, `seize` pass; steering 5 of 5; mechanics 21 of 23 (net and the chained smoke/craft check failed: the walker crafted a net and gathered no fish; reruns below); `skirmish` (island) 8 of 8: graphs used strike, bow shot, block, dodge and heal; uses recorded from acceptance; arrows struck; no cooldown violated; bands shown; deaths by the death rule left no `fighter` or `readiness` rows.

A first skirmish benchmark showed no blocks or dodges: `{"threatened": true}` counted only the older attack skills. It now counts `strike`, `bowshot` and `firebolt` windups too.

Mechanics: the net check (and the smoking/crafting check chained to it) failed in 3 of 3 fresh worlds with the change, against 0 of 2 on the base commit (`core-base-mech-1`, `-2`: 23 and 22, the 22 failing forest clearing). An instrumented copy of the driver showed "the fishing_spot is depleted": residents had emptied the walker's nearest spot. The driver now takes the nearest spot holding at least two fish (features/mechanics.md, "A fished-out spot"). Afterwards `core-combat-mech-4`, `-5` and `core-combat-dbg3`: 21 (net again, no recorded reason), 21 (conception and expecting parent) and 23 of 23. Evidence copied to the Mac checkout's `.local/living/verify/combat-evidence/`.

## 2026-11-09 one damage rule (Mac)

Shared container `sao-living_spacetimedb_1` (v2.14.1), Mac checkout at `b7cf7fb` plus the change removing the hurt/kill mode (docs/COMBAT.md "One damage rule"). Scratch databases only, no model calls. Evidence under `.local/living/verify/`.

- `core-fm-base`: `cargo_checks.py` pass (rules 87, authority 10, mind 47, viewer sync 3); `tick` 6/6, `needs` 6/6, `seize` 6/6. The seize scene's last check is now "a blow can kill someone who yielded, and striking them is news": `seize-struck-yielded.json` ("Walker1 struck Walker2, though Walker2 had yielded"), `seize-killed.json` ("killed by Walker1, after yielding"), `seize-killing.json`.
- Mechanics: `core-fm-mechanics` 22 of 23. The new check "blows land on the yielded, and striking them is news" failed in the driver, not the rule: the yield, the news and J's "though you had yielded" percept were all present, but J's health was read after the post-yield blow had landed. The check now reads the damage J was told. With that: `core-fm-mechanics-2` and `-3` 23 of 23.
- `core-fm-skirmish` (island) 8/8; `core-fm-town` (island) 21/21; `core-fm-codes` 10/10.
- Every database was deleted by cleanup and absent from `stdb list` afterwards.

## 2026-11-10, branch fix-agreement-terms

Shared container, laptop, island seed. `dealings` passed all 15 checks in `core-terms-202051-dealings` (the scene composes its own short `due_by_dark`, so it covers the hooks, not the new minimum). Cargo `agreements_and_demands_are_rules_on_records` checks the new deadline: accepted at 7:00, due in 13 h, told "by dusk today"; at 14:00, due in 30 h, "by dusk tomorrow". The description change was replayed against glm-flash on the two real backwards `offer_terms` decisions (docs/TRIALS.md, "Fast iterations").

## 2026-11-11, branch iter-11 (person needs paced to real time)

Shared container, laptop. `needs` passed all 7 checks in `core-pace-095608`, with its thresholds scaled by `person_pace` (0.3), and `food` all 4. `infant` passed all 18 checks in `core-pacei2-100737-infant`, with its hunger waits divided by the pace (about 2 hours in all). The first `infant` attempt (`core-pacei-095616-infant`) failed its setup check "warm anchor lies outside crying hearing" at 15.6 m: the witness and anchor come from `spawn_crowd` at random spots, so that check can fail by chance; it passed on the rerun and on plain e6b7e698 (`core-maini2-095803-infant`, all 18). Rules: all 132 tests pass, the five that pinned the old person rates now expect them times the pace (animals still bit-exact).

## 2026-11-11, branch fix-perceived-moving (activity derived from the body)

Spark, the trial stack's own server (`slop-trials-stdb`, v2.14.1, :3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), worktree on `origin/main` 6a905c3 plus the change. Default seed, `core-fixperc-1`: launch and doctor passed. Cargo passed: rules 145, authority 14 (including `perception::doing_tests`), mind 82, viewer-sync 5. `tick` 6/6, `sight` 6/6, `senses` 7/7 and `moves` 5/5 passed. The new `doing` scene timed out there: a `think` leaf asks only when the last deliberation is over 45 s old, and the scene's people were newcomers. Fixed in the scene, which now waits 47 s after spawning, and walks W2 in from 10 m. Then `doing` passed 7/7 twice in `core-fixperc-4`: O's scene read `goto → person`, `goto → (10,10)`, `follow → person` and `wait`, each equal to its activity label, and no AI body had `steer.goal` 3. Evidence: `core-fixperc-1/` and `core-fixperc-4/` (`doing-scene-1.json`, `doing-2.txt`, `doing-activities.json`, `doing-steer.json`). Not run: `needs`, `food`, `refusal`, `seize`, and the island, infant, town, lives and laws runs. The change does not touch them; it touches the perception of activity only.
