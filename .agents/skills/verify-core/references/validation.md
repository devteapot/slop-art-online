# Core validation record

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
