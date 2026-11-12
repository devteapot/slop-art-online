# Validation record (generation)

**2026-11-12, branch `arrival-open`.** `generation.py --run generation-arrival-235935 --feature worlds --seeds island,plan-test,floor-megacity-2k,cullet`: all four pass, each land row matching its native regeneration (`floor_preview`). The island's layout digest is now `e798f6a9f302d538` (arrival (406.5, 257.5), open ground) and megacity-2k's `fce494ea2cf1e408`; tiles and heights are unchanged, and Cullet's arrival does not move.

## 2026-11-12 goods-3: Cullet's tools in the cast (laptop host)

`generation-g3-004430`, own container `goods3-stdb` (2.14.1, port 3333), `--feature worlds --seeds island,cullet`: island 979 of 979, cullet 332 of 332, original seeds unchanged. The Cullet seed carries the Cone's tools in six residents' packs (blowpipes, crucibles, the mould, a pot; compiled from the cast with `author_world.py cullet --compile-only`). Its laws add the items, recipes and build recipes, so `floor::check` accepts the seed's items. The run's build tree was deleted after it passed.

## 2026-11-11 hearth-1: a household's own structures inside its lot (dev-box)

Branch `hearth-1` (from `9c6ca13c`; merged with origin/main `d124c0f7`), own container `hearth1-stdb` (2.14.1, port 3331, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), `scoped`, no minds. The plan format gained `lots[].inside`; an owned structure placed for a lot without a spot stands on the lot's own tiles ([authored plans](../../../../docs/AUTHORED_PLANS.md#a-households-own-things-stand-inside-its-lot)); `check_plans` gained three checks (inside its lot, within 1.5 m of a tile joined to the door, each household's house, store and fire).

- `generation-hearth1-20261111-223528` (`--feature worlds --seeds island,plan-test,cullet,floor-megacity-2k`): **island 979, plan-test 86, cullet 332, floor-megacity-2k 77**, all pass; `land` digests equal `floor_preview`'s. plan-test: 4 household structures inside (`storage` 3, `campfire` 1; 3 on a floor); Cullet: 43 (`hearth` 21, `house_store` 22; all on a floor), 22 households with house, store and fire.
- `generation-hearth1m-20261111-225211` (merged tree, `--seeds island,plan-test,cullet`): 979, 86 and 332 pass; original seeds unchanged.
- `generation-hearth1base-20261111-223941` (the branch point, `git archive 9c6ca13c` into `.local/hearth1/base`, `--seeds island,floor-megacity-2k`): 979 and 77 pass; its `structure`, `lot`, `resource_node` and `land` snapshots equal the branch's (`.local/hearth1/unplanned-compare.json`).
- Not run: `authored`, `guards` (the native `seed::tests` ran separately: 21 pass), floor-megacity-4k and the other seeds.

## 2026-11-11 layout-2: plan fixtures that block, open lots with spots (dev-box)

Branch `layout-2` merged with main `e301aa9f` (kit-2, rules-3), own container `layout2-stdb` (2.14.1, port 3329, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), `scoped`, no minds. The plan format gained `fixtures[]` (lines with gaps and rectangles; those with `blocks` become `Wall` or `Low` tiles at hosting) and Cullet's courts and plots became open lots with spots ([authored plans](../../../../docs/AUTHORED_PLANS.md#fixtures-that-block), [Cullet's layout, pass 2](../../../../docs/CULLET_LAYOUT.md#pass-2-2026-11-11)). A scoped maintain pass on the plans feature went with it: `check_plans` gained four checks, the `lot:` place check holds each resident's place to one of the lot's spots (it allowed anything near the door), and spots are computed from the plan (`spot_pt`), since `lot_pt` reads the front off the row's door and is wrong for a lot whose door point was moved to walkable ground.

- `generation-layout2m-20261111-214828` (`--feature worlds --seeds cullet,plan-test`): **cullet 329 of 329, plan-test 83 of 83**, `land` digests and arrival equal `floor_preview`'s on both, original seeds unchanged, both scratch databases gone after cleanup.
  - Cullet: `its 203 lots, in order`; `its 261 blocking fixtures (261 lines) stand on tiles no one walks on`; `a blocking fixture above the eye hides (Wall tiles), a lower one is seen over`; `every gap in a blocking line is open at its middle`; `every one of its lots' 387 spots is ground one can stand on`; the six new named places each `at lot <id>, on one of its N spots` for all 64 residents (the Bleach 4, the Readers' yard 11, the boatyard 5, the clay pit 2, the ropewalk 1, the wrack stance 6); 56 authored structures where written; doors walkable. The four law and rhythm checks that failed for layout-1 pass: the harness keeps a seed's laws again.
  - plan-test: `its 10 lots, in order` (the garth is the tenth); `its 3 blocking fixtures (2 lines) ...` (the bench, which does not block, is not among them); `every one of its lots' 7 spots ...`.
- An earlier run before the merge (`generation-layout2-20261111-212731`) found the two faults named above in the new checks themselves: with `lot_pt`, spots of older lots (the Counting House's seventh bay, the Watchglass's tip) computed onto walls and water, and the Readers' yard's place looked far. It also failed "original seeds unchanged" because I rewrote `cullet.json` while it ran.
- `cargo test -p living-rules`: 227 passed, 10 ignored, with `a_blocking_fixture_blocks_walking_and_the_eye_rule_decides_sight`, `a_lines_tiles_leave_no_leak_and_a_gap_opens_at_least_one`, `validation_refuses_a_fixture_that_is_neither_a_line_nor_a_rectangle`, the extended `the_cullet_seed_is_valid_and_reachable` and `host::tests::pinned_digests_hold` (the island and the megacity floor unchanged).
- Not run: every other seed, `authored`, `guards` (the authority's native `seed::tests`, `the_cullet_seed_is_hosted` among them), and no refusal of a bad fixture through `create_floor` (the refusals are proved natively).


## 2026-11-11 kit-2: Cullet's lots in the model table (dev-box)

Branch `kit-2` (origin/main through layout-1, `3c73d835`, merged), own container `kit2-stdb` (2.14.1, port 3322, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private target directories, `scoped`, no minds. The change: `gen_cullet.sh` now puts Cullet's 88 lot models into `living/rules/data/buildings.json` as style `cullet`, each with `eye_solid` and `eye_cells`, so their hosted tiles hide by shape (1,384 `Low` tiles on Cullet where there were none); 18 root plots and three open lots gained a `model`; lots carry `lit` (ignored by the rules). No entry point or table changed, so no maintain pass; the SKILL names the new writer of the table.

- `generation-kit2-20261111-195631` (`--feature worlds --seeds island,plan-test,cullet,floor-megacity-2k,floor-megacity-4k`, before layout-1): island 979, plan-test 78, floor-megacity-2k 77, floor-megacity-4k 92 pass. Cullet failed 4 of 317 (`the seed's laws are composed over the shipped script`, `seeded rhythms are as given`, two authored-relations checks: four elders dead of old age 6 s after creation). "Original seeds unchanged" failed because `cullet.json` was regenerated during the run.
- `generation-kit2main-200618` (a clean detached checkout of origin/main `6a31176a`, `--seeds cullet`): the same 4 of 317 fail, so they were main's (fixed there by goods-2: the verify launch keeps a seed's laws again).
- `generation-kit2c-20261111-204204` (the final tree, `--seeds cullet,plan-test`): cullet 317 and plan-test 78 pass; original seeds unchanged.
- Not run: `authored` and `guards`, the other seeds after layout-1.

## 2026-11-11 layout-1: Cullet's plan redrawn (dev-box)

Branch `layout-1` (origin/main `6caebe20` merged: rates-2, lives-3, ground-1), own container `layout1-stdb` (2.14.1, port 3324, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), `scoped`, no minds. The seed changed in its plan's geometry only ([Cullet's layout](../../../../docs/CULLET_LAYOUT.md)): 13 levels (three new), 46 streets, 19 stairs, 59 of the 93 lots moved; the lot ids, kinds, resources' kinds and structures are as they were, so no shape changed and no maintain pass was run.

- `generation-layout1b-20261111-194848` (`--feature worlds --seeds cullet,plan-test`): plan-test 78 checks pass. Cullet 313 of 317 pass, with every plan check among them: its 93 lots in order with their kinds, sizes, models, heights and level floors; doors walkable; blocking lots on wall, low or drop tiles; its drops drop tiles; 158 authored resources and 34 authored structures where written; the 22 households own and live at their lots; `land` digests equal `floor_preview`'s; original seeds unchanged.
- **The four Cullet failures are the harness's, not the plan's**: `the seed's laws are composed over the shipped script`, `seeded rhythms are as given` (Anselm Faro, Greta Dunmore, Halvard Dunmore and Ode Pontil have no row), `authored relations are relation rows` and `authored relations across communities are introductions`. The snapshot's `script` row is revision 4 and holds the shipped `skills.rhai` (133,739 characters) with no `// ---- floor overlay ----`. `verify.py launch` installs `living/scripts/skills.rhai` over HTTP after publishing (since the merge of `exp-player-frame`, `b7328bc0`), which replaces the script `init` composed with Cullet's laws. Under the shipped life law the four elders then die of old age within 8 s (`character.cause`), and their rhythms and relations go with them. Not fixed here (it is the shared harness's; a launch should install the composed script, or none, for a seed with `laws`). Not rerun on plain `origin/main` to show the same four there.
- An earlier run (`generation-layout1-20261111-193401`) had the same result and also failed "original seeds unchanged", because I regenerated `plan.json` while it ran.
- `cargo test -p living-rules`: 171 passed, 9 ignored, with `settle::plan::tests::the_cullet_seed_is_valid_and_reachable`; that test refused three earlier drafts of the plan (a lot on a new lane each time), which `land_dump` alone had let through.
- Not rerun: every other seed, `authored`, `guards`.


## 2026-11-11 rules-3: household stores owned, lots' own door structures (dev-box)

Branch `rules-3` (from `93019a37`, origin/main `1d71e6c2` merged), own container `rules3-stdb` (2.14.1, port 3325), `scoped`, no minds. A maintain pass of the plans feature scoped to this change (`plan.rs` `StructureSpec.owner`, `LotSpec.structure`; `seed.rs` `plan_structures`, `authored_households`; `island.rs` door kinds; `floor.rs` households), not a source wave.

- `generation-r3-200638` (`--feature worlds --seeds island,plan-test,cullet`): island 979 of 979, plan-test 79 of 79 (new: `its 1 household structures are placed and owned by their household's house owner`), cullet 318 of 319. The failure was the check, not the world: `authored structures and lot stores hold what the plan says` compared the 22 household stores exactly, and in the seconds the world ran before the snapshot (doctor) 17 households had already taken smoked fish from their own store (one baked roots with its peat, one stored ash), found through `like: "storage"`. Peat and roots were otherwise exact. The check now lets a household store hold less of the plan's items than placed (never more) and reports the use.
- `generation-r3c-201236` (`--seeds cullet`, the corrected check): 319 of 319, including `2 lots have their own door structure (peat_barn, store)`, `its 22 household structures are placed and owned by their household's house owner` and `authored structures and lot stores hold what the plan says (17 household stores already used by their people)`; original seeds unchanged.
- After merging origin/main `25c1fb92` (layout-1's plan, goods-2): `generation-r3m-210752` (`--seeds plan-test,cullet`): plan-test 79 of 79, cullet 319 of 319, the same household, door and store checks passing.
- `seed::tests::a_plan_naming_kinds_the_world_lacks_is_refused` now also refuses an unknown door kind (`structure \`silo\``), a store owned by `household:nobody` (naming the 22 households) and any owned store on a seed with no residents.
- Not rerun: realm, valley, authored-test, aske-coast, stage3-village, the megacity floors, cullet-laws, the guards and authored features (seeds without plans or owners; the parser and plan changes are covered by the rules and authority tests).

## 2026-11-11 rates-2: plan resources, structures and stores; unknown plan kinds refused (dev-box)

Branch `rates-2` (from `f2d803fa`, origin/main `12fd78ef` merged, with the cast of Cullet), own container `rates2-stdb` (2.14.1, port 3320, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), `scoped`, no minds. A maintain pass of the plans feature scoped to this change: the map was read against the source it changed (`plan.rs`, `seed.rs` `plan_resources`/`plan_structures`/`put_authored`/`house_at`, `floor.rs` `plan_kinds`), not by a source wave.

- `generation-rates2-20261111-174238` (`--feature worlds --seeds cullet,plan-test,island,floor-megacity-4k`): cullet 305 (64 residents; 158 authored resources where written with their max, regrowth and four pools; 34 authored structures where written, each lit for its fuel at its kind's rate; the Store's and the Cone yard's stores), plan-test 76, island 977, floor-megacity-4k 90 (with `create_floor refuses a plan naming a resource or structure kind the world does not have`); original seeds unchanged.
- The first run after merging the cast (`generation-rates2-20261111-173512`) failed four Cullet checks, `household fenwick owns the house on lot mid_2` and three like it. main's `house_at` gave a household bound to a lot the first unowned structure at its door, which could be the plan's hearth there. Fixed in the authority: the structure the lot row names comes first. The rerun above passes.
- Not rerun: valley, realm, authored-test, aske-coast, stage3-village, cullet-laws, cullet-laws-floor, floor-megacity-2k.

## 2026-11-11 lives-3: rhythms at any hour, Cullet's ways, Cullet's life law (dev-box)

Branch `lives-3` (from the coordinator's main `3faa7bfb`, origin/main `12fd78ef` merged, with Cullet's 64 drafted residents), own container `lives3-stdb` (2.14.1, port 3321, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no minds. New checks in every child: `people without a seeded rhythm have a drawn one (no working hours, no second sleep)` and `seeded rhythms are as given (any rising hour, working hours, a second sleep)` (the `rhythm` table is snapshotted now).

- `generation-l3-171418` (before the merge; `--feature worlds --seeds island,aske-coast,cullet`): island 979 and aske-coast 286 checks pass (277 and 68 drawn rhythms, none with working hours or a second sleep). Cullet, then a town with no people but with `town_life`, failed 5 town-life checks that assume residents (places known, workers' workplaces, `lot:` places); and "original seeds unchanged" failed because I regenerated `cullet.json` (the ways' `holds` fix) while the run was going. Neither is a generation defect; the town-life checks still assume people wherever a seed has `town_life`.
- `generation-l3b-172604` (after the merge and `author_world.py cullet --compile-only`): island 979, aske-coast 286, cullet 313 checks pass; original seeds unchanged. Cullet: 64 seeded rhythms as given, 50 workers with a workplace, 149 authored places, every resident on the seed's own ways.
- Not run: `authored` and `guards` features, the other seeds.

## 2026-11-11 kit-1: Cullet's lots name their models (dev-box)

Branch `kit-1` (origin/main `a107fdfa` merged at `cba7d89b` for the runs below; `view-1`, `29cd401f`, merged afterwards at `4e080ecf`: it changes only the game client and docs, so the generation run was not repeated), own container `kit1-stdb` (2.14.1, port 3316, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), `scoped`, no minds. Evidence under the worktree's `.local/living/verify/`. The seed changed only in its plan lots' content: 73 lots carry `model` (`cullet/<folder>/<id>.glb`), every lot a `seed`, and three glasshouses a `repair` of 0.9; no shape changed, so no maintain pass.

- `generation-kit1b-20261111-165531` (`--feature worlds --seeds cullet,plan-test`): cullet 65 and plan-test 72 checks pass; `land` digests equal `floor_preview`'s; original seeds unchanged. Before the merge, `generation-kit1-20261111-163847`: cullet 64, plan-test 71.
- The real game client connected to `verify-kit1-cullet-170011`, and after merging `view-1` to `verify-kit1-cullet-172154` (a fresh player, headless): digests matched (tiles `07290076efd70ae6`, heights `bc0680832fd92c40`, layout `bc262d3ed04f5cb2`), the `lot` rows' models drew, none reported as not on disk.
- After merging main again (`ee477fbc`: Cullet's 64 residents compiled into the seed, ui-1, the asset board), `generation-kit1c-20261111-173034` (same features and seeds): cullet 301 and plan-test 72 checks pass; original seeds unchanged. The seed then has both the residents and the lots' models (`cullet_plan.py --check` passes).
- Not covered: `authored`, `guards`, the other seeds (unchanged by this branch).


## 2026-11-11 eye-2: eye-height cells in the model table (dev-box)

Branch `eye-2` (from main `eead7a29`, uncommitted at the time of the runs), own container `eye2-stdb` (2.14.1, port 3317, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no model calls. Every scratch database answered 404 after cleanup. `generation.py --feature worlds --seeds island,plan-test,cullet,floor-megacity-2k` (`generation-eye2v`): every world passes (island 977 checks, cullet 65, floor-megacity-2k 75, plan-test passes), original seeds unchanged. The island's live and native tiles digest is `e051dd1788c4d9f9` (heights `0d2f77752781845c`, layout `8ff57472b004a13f`), with 9,153 low and 4,116 drop tiles; plan-test 595 low and 188 drop. The blocking-lot check now accepts a drop at a lot's centre (a part of a model that does not hide over a drop's edge stays `Drop`) and reports `wall_at_centre` separately. Maintained: seeded-world.md, plans.md (pinned digests since eye-2), SKILL.md (rerun after the model table is regenerated).

## 2026-11-11 drop-1: drop (8) and low (9) tiles (dev-box)

Branch `drop-1` (from `6a905c31`, origin/main `fd2030c3` merged), own container `drop1-stdb` (2.14.1, port 3315, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`, no minds. Evidence under the worktree's `.local/living/verify/` (git-ignored).

- `generation-drop1b-20261111-151550` (`--feature worlds --seeds island,plan-test,floor-megacity-2k,cullet-laws`): island 977, plan-test 70, floor-megacity-2k 75 and cullet-laws 41 checks pass; original seeds unchanged. Tiles: island drop 4,116, low 61, wall 44,253; plan-test drop 198, low 3 (`a planned settlement's drops are drop tiles`); megacity drop 0, low 590. Blocking lots stand on wall or low tiles: 450, 42, 2,468 of as many. `land` digests equal `floor_preview`'s: island `1a2a9a096caa8e21 0d2f77752781845c 8ff57472b004a13f`, plan-test `00d85c20a07e8312 b668d5f2c3e777c2 089870648749a822`, megacity `a3d6f6164c07192c c06f16f3dcac1290 0c6b3f2c51f13129`.
- After merging main `3f2f3443` (plan-2's Cullet), `generation-drop1m-20261111-160203` (`--seeds cullet,plan-test,island`): cullet 65 (drop 1,753, low 0, wall 4,362; `a planned settlement's drops are drop tiles`), plan-test 72 (drop 188, low 3) and island 977 checks pass; native digests match (cullet `07290076efd70ae6 bc0680832fd92c40 18b1e66d0eb92a78`, plan-test `8ebb2aa8efa58eb7`, island `1a2a9a096caa8e21`); original seeds unchanged.
- The first attempt (`generation-drop1-20261111-151031`) failed the native digest comparison on the three lands with low tiles: `floor_preview` counted tiles by class in an array of 8 and panicked on class 9; fixed in the example. cullet-laws is not a land seed (no drops or low tiles there).

## 2026-11-11 the hamlet seed (exp-hamlet-births, Spark)

Branch `exp-hamlet-births` from main `4df9a89`, worktree, the trial service `slop-trials-stdb` (2.14.1, `LIVING_STDB_URL=http://127.0.0.1:3320`; its port is published on `0.0.0.0`, which `verify.py` now accepts as local), private target dirs. `generation.py --feature worlds --seeds hamlet,authored-test` (`generation-hamlet-20261111-141545`): `hamlet` 59 of 59 checks (both settlements' 8 and 4 authored residents, sheets, parents, memberships, promised fishing spots and berry bushes, no animals), `authored-test` 40 of 40, original seeds unchanged. `--seeds` now accepts any tracked seed. The first attempt stopped at launch: the harness refused the trial service's `0.0.0.0` port binding.

After merging main `fd2030c` (rules-1), with the hamlet on Cullet's day (`day_minutes` 48) and laws (`laws_file` `worlds/cullet/laws.rhai`), `life_pace` 0.0357: `generation-hamlet-20261111-150942`, `hamlet` 61 of 61 and `authored-test` 42 of 42, original seeds unchanged.

After merging main `7837320`: `generation-hamlet-20261111-160615`, `hamlet` 61 of 61, original seeds unchanged.

## 2026-11-12 the hamlet-6 seed (births-2-prep, Spark)

Worktree branch `births-2-prep`, the trial service `slop-trials-stdb` (2.14.1, `LIVING_STDB_URL=http://127.0.0.1:3320`). `generation.py --feature worlds --seeds hamlet-6` (`generation-hamlet6-20261112-061500`, main `2ff786aa` with trials-bi1) passed `hamlet-6` with 99 of 99 checks: 24 authored residents in two settlements (14 and 10), 8 households and 8 houses, sheets, parents (one parent for Wren, Dagny, Tam, Sefa and Lio), promised fishing spots and berry bushes, no animals. After merging main `49dfc2cd`, `generation-hamlet6-20261112-063859` passed `hamlet-6` 99 of 99 and `hamlet` 63 of 63, and the original seeds were unchanged.

## 2026-11-11 plan-2: Cullet's plan, authored relief, plan resources (dev-box)

Branch `plan-2` (from the plan-1 merge `bcbde99d`), own container `plan2-stdb` (2.14.1, port 3314, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. A maintain pass of this skill ran with it: a source reader each for [plans](../features/plans.md) and [seeded-world](../features/seeded-world.md) (the features the change touched; plan-1's pass earlier the same day covered the rest), then every feature driven live. Drift fixed: the `cullet` seed and the authored resources and relief in plans, seeded-world and SKILL.md; the seed-test count (seven); the people-less town's checks.
- `generation-plan2b-20261111-152231` (`--feature worlds --seeds cullet,plan-test,island`): cullet 62, plan-test 69, island 975 checks pass; `land` digests equal `floor_preview`'s; original seeds unchanged. New checks: `plan cullet: its 93 authored resources of known kinds stand where written`, `... of unknown kinds are not placed` (greens 11, kelp 12, peat 18, roots 18, sand 6); plan-test's 2 fishing spots placed and its `kelp` not. The cullet town has no people: `households own lot houses (none: the seed has no people)` and the like.
- `generation-plan2-worlds-20261111-152524` (`--seeds floor-megacity-4k`): 87 checks pass, `create_floor` refusing the bad plan among them. `generation-plan2-authored-20261111-152524`: aske-coast and island compile offline. `generation-plan2-guards-20261111-152524`: 7 `seed::tests` pass (with `the_cullet_seed_is_hosted`), the malformed seed refused.
- After merging main (`90f6fac1`, with rules-1's `cullet-laws` seeds), `generation-plan2m-20261111-153709` (`--seeds cullet,plan-test,cullet-laws,cullet-laws-floor`): 64, 71, 41 and 46 checks pass; original seeds unchanged.
- An earlier run (`generation-plan2-20261111-145116`) failed cullet's people-dependent checks (backgrounds, building places, households owning houses), which assumed every seeded town has people; the driver now skips them for a town with neither `residents` nor `occupations`. Its one missing Weirs fishing spot lay in the water more than 2.5 m from land; the plan moved it onto the shore.

## 2026-11-11 rules-1: a seed's own day and laws (dev-box)

Branch `rules-1`, own container `rules1-stdb` (2.14.1, port 3312). `generation-rules1-135536 --feature worlds --seeds cullet-laws,cullet-laws-floor`: `cullet-laws` (compiled, `laws_file` read in by `build.rs`) 41 of 41 and `cullet-laws-floor` (`create_floor` with the seed from `seed_text.py`; refusals of an unread laws file, broken laws and a zero day) 46 of 46; cleanups and original seeds pass. The other seeds were not rerun with the new day and script checks.

## 2026-11-11 plan-1: hand-authored plans (dev-box)

Branch `plan-1` (from `6593f725`), own container `plan1-stdb` (2.14.1, port 3311, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. A maintain pass of this skill ran with it (new [plans](../features/plans.md) feature; drift fixed in seeded-world, floors, seed-guards, authored-worlds, repeatability and SKILL.md).
- `generation-plan1b-20261111-135743` (`--feature worlds --seeds island,plan-test,floor-megacity-2k,floor-megacity-4k`): island 975, plan-test 67, floor-megacity-2k 73 and floor-megacity-4k 87 checks pass; `land` digests equal `floor_preview`'s on all four; original seeds unchanged. plan-test's `check_plans`: one `cullet` settlement, 9 lots in plan order with their kinds, sizes, models, heights and level floors, walkable doors, households `hollis` and `wren` owning and living at `house_a` and `house_d`, the Tally Hall's sign at lot `hall`, the `hall` and `inn` places at their lots. The 4 km floor: `create_floor refuses a plan whose stair disagrees with its levels` ("rises 3 m"); staged creation 142 steps in 43.1 s with other runs on the server.
- `generation-plan1w-20261111-140418` (the other worlds and a second `realm`): realm 26, valley 38, authored-test 40, aske-coast 282, stage3-village 22, realm 26; repeatability passes. `generation-plan1a-20261111-140418`: authored aske-coast and island compile offline. `generation-plan1g-20261111-140418`: the six `seed::tests`, the malformed seed refused.
- An earlier attempt (`generation-plan1-20261111-134705`) failed plan-test's generic town-life checks ("workers have a workplace", "residents start on the seed's own ways") because the seed had no `town_life.work` or `ways`; the seed gained both. "Original seeds unchanged" failed there because `living/seeds/cullet.json` was written during the run.

## 2026-11-11 every person a mind (lives-2, dev-box)

Branch `lives-2` at the units 2-4 tree (efcd489's content), own container `lives2-stdb` (2.14.1, port 3461), private `CARGO_TARGET_DIR`. `generation-l2b-022738`: 25 of 25 summary checks pass (the eight seeded worlds, the two megacity floors, authored compilation, repeatability, malformed seeds, original seeds unchanged). The island seed no longer carries `rules.minds`; a seed that does is refused at build. Rhythms and constitution genes are drawn from each person's id, so the world's random stream, and with it every digest, is unchanged.

## 2026-11-11 laws-2 (dev-box)

Branch `laws-2` (from `445db09`), worktree `~/dev/slop-laws2`, own container `laws2-stdb` (2.14.1, port 3447, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`), private `CARGO_TARGET_DIR`, `scoped`. Evidence archived on the Mac under `.local/living/laws-2/verify/`. `generation.py --feature worlds --seeds island,floor-megacity-4k` (`generation-l6c`): 972 and 87 checks pass, including the new `the seed's rules are kept as the world's laws` (the island's `{"minds": false}` as one `world_law` row; the floor module given its seed by `create_floor`, without `LIVING_RULES`). The full `generation-l6` run before that check passed too (its child worlds' evidence kept).

## 2026-11-10 fix-rules-small (dev-box)

Own container `rules-small-stdb` (2.14.1). `generation.py --feature worlds` (`generation-rs-final`, head `9115e59`): all nine worlds pass, with the native digests, and repeatability passes every comparison, now required for resources, names, ages, genes and animal positions too (compared without ids). The 4096 m floor: three bad sizes refused, `resume_genesis` refused before creation, while a step is scheduled and once made, `stop_genesis` stalled the chain for 8 s, `resume_genesis` finished it (142 steps, no restarts). Owner SQL cannot stop the chain: 2.14.1 refuses "SQL writes to scheduled tables" (`generation-rs-floor1`).

## 2026-11-10 island food places (Mac)

Own scratch container `hunger-verify` (2.14.1, port 3382) through `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`; branch `hunger-1` (main `7e5de53` merged in). The island seed gains the places `berries` and `store` and `town_life.spread`; `town::seat` reads `spread` and looks each spot kind up once per settlement. The driver's place check now names every seed place, and a new check asserts that a spread place is spread.

- **`generation-hunger-110557`** (`--feature worlds --seeds island`): island 970 of 970. All 277 residents know `berries`, `evening`, `inn`, `square` and `store`; `berries` is spread over 275 distinct bushes for 277 residents.
- **`generation-hunger-085943`** (before `spread`, from `fe6ec66`): island 969 of 969.

## 2026-11-09 floors: staged creation, a runtime seed, the second-pass megacity (dev-box)

Own scratch container `megacity-stdb` (image `v2.14.1`, port 3394, `/wasm` mounted `:z`) through `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`; worktree `~/dev/slop-megacity`, branch `megacity-1` from `14f3a72`. The driver gained the floor child `floor-megacity-4k` (`--seed none`, `create_floor`, `genesis` polled to `done`, four floor checks), `--seeds`, district styles read from the seed, membership checks of the living, and the `animals.habitat` map skipped in the animal counts.

- **`generation-mc-20261109-223043`** (`--feature all`, before the driver fixes): realm, valley, authored-test, aske-coast, stage3-village, authored compilation and seed tests pass. The island failed "Fernhollow memberships" (Peya, an elder founder, died 5 s after creation: the old-age flake recorded below), and the driver crashed on the megacity seed's `animals.habitat` map (a count was expected).
- **`generation-mc2/3`** (`--seeds island,floor-megacity-2k,floor-megacity-4k`): both megacity children failed town life: residents' square and workplaces were seated at the core square's middle, now inside its arcology. A product fix in `island::host`/`town::seat` (a square whose middle is built on offers walkable points round its edge) left 6 of 105 residents without, then none.
- **`generation-mc4-20261109-224302`**: island 72/72, megacity 2048 m 67/67, megacity 4096 m floor 71/71 (created in 18 s, 138 steps, no restarts; a second `create_floor` refused; digests equal native).
- **`generation-mcall-20261109-224617`** (`--feature all`, final code): every result passes. The five seed tests, authored compilation (no network), all ten worlds with their cleanups (SQL 404), repeatability, the malformed seed's rejection (`missing_field_diagnostic_visible` true: `seed: missing field \`animals\`` now reaches the publication output; `panic_reported` false), and the original seeds unchanged.

Maintenance pass on this skill, same run:
- **Source wave:** one reader per feature file (seeded world; guards and repeatability; authored worlds).
- **Drift fixed:**
  - stale line citations in all four files, now replaced by function names;
  - the city's checks and description, written for the prototype generator (styles `metro`, `slum`, `works`; 40 core lots of 50 m), now read the seed's districts;
  - the "seven seeds" count, and the gotcha that forbade a 4096 m megacity;
  - the malformed seed's known issue (no longer a panic).
- **Added:** `features/floors.md`.
- **Harness gaps fixed:**
  - the habitat map crash;
  - memberships of dead founders (the old-age flake recorded below);
  - `--seeds` for focused reruns.
- **Product gap fixed outside the skill:** town life at a built-on square (above).
- **Not covered:** the 8192 m floor (generated through the same path by hand: 92 s; docs/FLOORS.md), and fuel margins (measured by `living/tools/land_fuel`, not by this skill).


## 2026-11-09 the Rhai boundary, rhai-1 (dev-box)

- **Setup:** private container `rhai-stdb` (2.14.1). The seed reads `max_hp` and `regrow` through the name tables now read at compile.
- **`generation-rhai1-195746`** (`--feature all`, on `33e3185`, `rhai-1` with `origin/main` `2a64837` merged): 20 of 22 pass.
  - The island fails "Fernhollow memberships" and "Reedmoor memberships". This is the known old-age flake: residents 129 and 182 died right after creation.
  - The megacity fails "wolf count including dead founders": 5 against 8. All 5 are alive with contiguous ids, so the other 3 were never placed. `seed.rs` looks for a pack's spot in 200 random tiles of forest and stops when none is found; a 2 km city has little forest.
- **`generation-rhai1base-200854`** (`--feature worlds`, on `origin/main` `2a64837`): the same megacity failure (5 wolves), and "Lanternquay memberships" on the island.
- **Conclusion:** both failures are on main and not from this change. The megacity's wolf placement is a seed or generator finding, left for its owner.

## 2026-11-09 floors: the megacity land and native digests (dev-box)

Own scratch container `slop-floors-stdb` (image `v2.14.1`, port 3330) through a `docker` name shim (`~/floors-shim`). The harness's hard-coded `127.0.0.1:3300` was patched to 3330 in the dev-box worktree only, not committed. Worktree `~/dev/slop-floors`, branch `floors-1` from `b7cf7fb`, uncommitted. The driver gained the derived seed `floor-megacity-2k` (`living/seeds/floor-megacity.json` at 2048 m, written into the run's directory and published through an absolute `--seed`), five city checks, and a native digest cross-check for every land seed (`floor_preview`).

- **`generation-floors-20261109-130139`** (`--feature all`, before the final generator fixes): 21 of 22 results pass.
  - The island passes 72 of 72, the megacity 67 of 67, and both land rows equal a native regeneration.
  - The one failure is the known flake, "Saltmere memberships" on the second `realm`.
- **`generation-floors-final-20261109-132017`** (`--feature all`, final code): 20 of 22 results pass.
  - The island passes 71 of 72, failing "Reedmoor memberships".
  - The megacity passes 66 of 67, failing "Saltline memberships": Corbasa, a seeded resident drawn at 502 days, died of old age 4.9 s after creation, and the death cleanup removed the membership. It is the same flake as Saltmere's and Reedmoor's; seed ages are drawn, not the city.
  - Every other check passes:
    - 25 wards, metro, slum and works styles, 105 core lots of 50 m or more, every other settlement outside the city, 1,030 gate tiles;
    - digests `e182d4d6b67f0e3b`/`78040b114f6a6db6`/`50372111eee395a3` equal native;
    - the island's `c19cc98e8f1471f0`/`16412fd044a2b0b0`/`d45f735150add4ba` equal native and are unchanged from `b7cf7fb`;
    - repeatability (terrain, settlement sites and band sites equal), the five seed tests, the malformed-seed rejection (its label now `seed.rs:603`), all nine cleanups with SQL 404, and the original seeds unchanged.

Maintenance pass on this skill, same day:
- **Source wave:** one reader per feature file.
- **Drift fixed:** stale source citations in all four feature files, the malformed seed's `known_issue` source (`seed.rs:444` → `:603`, also in `docs/LIVING_HANDOFF.md`), and the seed count. The new city checks and the digest cross-check are documented in `seeded-world.md` and `SKILL.md`.
- **Live coverage:** both runs above drove every feature (worlds, repeatability, authored compilation, guards).
- **Not covered:** the 4096 m megacity, whose `init` runs out of the reducer's fuel budget (docs/FLOORS.md).

## 2026-11-09 town life: places and starting ways (dev-box)

Own scratch container `slop-townlife-stdb` (image `v2.14.1`) through a `docker` name shim; worktree `~/dev/slop-townlife`, branch `townlife-1` from `b12fa45` with the town-life change (docs/TOWN_LIFE.md) uncommitted. The seed format gained `ways` and `town_life`; `place` and `routine` joined the snapshot tables, and the land check gained four town-life checks (places known, workers placed, workplaces in or by their settlement and walkable, residents on the seed's own ways).

- **`generation-town-1`** (`--feature all`): every seed passed except the island, 68 of 71. Three failures, all in the harness: "wolf count including dead founders" (10 against 6) is drift from the combat change, which added the seed's `packs` (4 bold wolves) without the check counting them; "workplaces lie in or by their settlement" counted farm fields beyond 1.5 × the radius as far, though they are the settlement's own lots; "residents start on the seed's own ways" counted infants, who start on their species' young instinct. The three checks were corrected and re-run offline on the same snapshot (70 of 70), then live.
- **`generation-town-2`** (`--feature worlds`): every result passes. The island passes 71 of 71: 269 residents know their places with none missing, 209 workers have a workplace, and every grown resident starts with the seed's `common` routines. Repeatability and cleanup passed.

## 2026-11-09 island ornaments, terraces and styled towns (dev-box)

`generation-orn-20261109-035123`, on `c5a2c00` plus the ornaments change (`docs/FIRST_WORLD.md`, "Ornaments, terraces and styled towns"). SpacetimeDB 2.14.1 ran in a scratch container of the run's own, `slop-orn-stdb` on port 3310. Port 3300 belonged to another agent's container, so the harness's port was patched locally and not committed. This change made the land check accept a styled town's site id, `<style>_<kind>` (`steampunk_town`), against the settlement row's `kind` and `style`.
- **Result:** 19 of 20 results pass. The island passes 65 of 66: 8 settlements including both styled towns on their sites, 546 lots, and wall tiles under every blocking lot.
- **An earlier run found a real defect:** the clock tower standing in its paved square did not block. It is fixed.
- **Flake:** "Reedmoor memberships" failed again in the same way as Saltmere below: a seeded grandparent died of old age right after creation.

## 2026-11-09 island land worlds (dev-box)

Host: the dev-box (Fedora, rootless podman, SELinux enforcing). SpacetimeDB 2.14.1 ran in scratch container `slop-game-stdb`, reached through a `docker` name shim; see `docs/ISLAND_AUTHORITY.md`, "Verification". This change added the `island` seed, the land checks (`check_land`) and the `land` map size to `generation.py`. Evidence is under `.local/living/verify/` in the dev-box worktree `~/dev/slop-game`.

- **`generation-20261109-021430`** (`dc34fdf` plus the change) exited 1. `realm` ×2, `valley`, `authored-test`, `aske-coast`, `stage3-village`, authored compile, guards and repeatability passed. The island failed two of 56 checks, both real defects, since fixed:
  - 12 market stalls and wells on the paved plaza did not block;
  - `body_scale` was written as an f32 widened to f64.
- **`generation-20261109-023510`** (`977a14c` plus the change and fixes) exited 1 with 19 of 20 results passing. The island passed 56 of 56: land row and digests, walkable arrival, 6 settlement rows linked to their communities and site kinds, 372 lots, door structures, walkable doors, wall tiles under all 263 blocking lots, owned lot houses, folk backgrounds, and no mind-controlled character.
- **Finding (not caused by this change):** `realm` child 0 failed "Saltmere memberships". A drawn grandparent (`drawn_households` ages 0.76–0.9 of a lifespan) died of old age 1.2 s after `init`, and death cleanup removes memberships. The membership check expects every seeded resident, dead or alive. Repeatability and the second `realm` passed.

## 2026-10-04 fix round

Commit `384fb50e379533b7db64698357efd0b2323f9452`, branch `living-core`. Host: Fedora, rootless podman, SELinux enforcing. The working tree had pre-existing changes, including `living/viewer/src/clock.rs`. This work edited only the generation skill and wrote scratch evidence. No product code or tracked seed was changed.

The final command was:

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-fix-final-20261004-171138
```

It exited 0. Every required result passed. Evidence is under `.local/living/verify/generation-fix-final-20261004-171138/` and its seven child directories. The console is `generation-fix-final-20261004-171138-console.log` beside the parent directory. Earlier runs are historical evidence only.

The driver called the current shared harness through its CLI for launch, doctor, admin pause, public SQL and cleanup. Both driver and harness hashes are in `driver-hashes.json`; `post-cleanup.json` confirms they remained unchanged through the run. Cargo compiled the working-tree authority with `--target-dir` under the run directory. Positive worlds ticked through doctor, then paused for snapshots of 33 public tables. Their populations were 90, 31, 19, 140, 41 and 87 characters. No mind, player, observer, Neo4j writer or paid model ran. These are generation checks, not performance evidence.

## A seed produces the described world

All paths below are under `.local/living/verify/`.

| Seed | Result | Evidence |
| --- | --- | --- |
| `realm`, twice | Pass. 256×256, 256 chunks, two towns, three wild bands, requested worker occupations and linked children, 36 deer and 6 wolves. 26 checks each. | `generation-fix-final-20261004-171138-0-realm/checks.json`, `generation-fix-final-20261004-171138-5-realm/checks.json` |
| `valley` | Pass. 96×96, 36 chunks, 12 people, explicit structures, artifacts and communities. 38 checks. | `generation-fix-final-20261004-171138-1-valley/checks.json` |
| `authored-test` | Pass. Seven authored residents, resolved sheets and parent links. 40 checks. | `generation-fix-final-20261004-171138-2-authored-test/checks.json` |
| `aske-coast` | Pass. Three settlements, 72 authored residents, named buildings and signs, eight resource promises within 24 tiles. 282 checks. | `generation-fix-final-20261004-171138-3-aske-coast/checks.json` |
| `stage3-village` | Pass. Three six-member family bands with camps. 22 checks. | `generation-fix-final-20261004-171138-4-stage3-village/checks.json` |

Each positive child retains `doctor.log`, `pause.log`, table snapshots and action logs. Exact nonempty sheet secrets and top-level secret fields were absent from all exported public tables.

## Repeatability

| Comparison | Result | Evidence |
| --- | --- | --- |
| Terrain | Pass. All 256 rows matched. SHA-256 `761e94d883330bc6544bb3223b31cae961ee93a604bcd71489f79bb3bad60081`. | `generation-fix-final-20261004-171138/repeatability.json` |
| Town and band sites | Pass. Both town sites and all three band sites matched. | Same file |
| Resources | Finding. 1,448 versus 1,445 rows, with 1,442 differing sorted pairs including unmatched rows. | Same file |
| Names, ages and genes | Finding. 90 versus 87 rows, with 90 differing pairs in each comparison. | Same file |
| Animal spawn positions | Finding. All 42 paired rows differed. | Same file |

Reducer RNG draws names, children, genes, resources and animal positions. These differences are observations, not failed terrain guarantees. Sorted pairs do not track individual creatures. Valley homestead placement was not compared twice.

## Authored worlds

| Check | Result | Evidence |
| --- | --- | --- |
| Cached compilation | Pass. Real `author_world.py aske-coast --compile-only`; output matched the committed seed semantically and byte for byte. | `generation-fix-final-20261004-171138/authored.json`, `compile.log`, `compiled-aske-coast.json`, `compile-differences.json` |
| Network isolation | Pass. Zero socket or urllib attempts. | `generation-fix-final-20261004-171138/network.json` |
| Tracked seed inputs | Pass. All original seed-tree hashes were unchanged. | `generation-fix-final-20261004-171138/results.json` |
| Authored parser tests | Pass. All five `seed::tests::` tests passed. | `generation-fix-final-20261004-171138/seed-tests.log` |

Only `author_world.py` and the Aske Coast bible, cast, template and cached sheets were copied. The compiler derives its root from its script path and writes `living/seeds/aske-coast.json` without an output-path option. That copy prevents a write to the tracked seed. Authority sources were not copied.

## Seed format guards

| Check | Result | Evidence |
| --- | --- | --- |
| Parser tests | Pass. All five seed tests ran against the working-tree authority. | `generation-fix-final-20261004-171138/seed-tests.log` |
| Malformed seed publication | Plain pass. A valid JSON seed missing `animals` built, reached publication, failed launch with exit 1, and answered world SQL with 404. | `generation-fix-final-20261004-171138-6-malformed/launch.log`, `publication.json`, `init-state.json`, `guards.json` |
| Panic observation | Confirmed. The database identity matched a server launch record; filtered logs included `seed::seed` and `rust_panic`. | `generation-fix-final-20261004-171138-6-malformed/server-init.log` |
| Cleanup | Pass. Shared cleanup required SQL 404, removed the module copy and kept evidence. | `generation-fix-final-20261004-171138-6-malformed/cleanup.log`, `cleanup.json` |

The guard asserts rejection only. It does not assert a readable error, so it is a plain pass rather than XFAIL. `guards.json` records `KNOWN ISSUE` and points to `docs/LIVING_HANDOFF.md`, "Still open", for the panic and unreadable publication error at `living/authority/src/seed.rs:444`. The shared harness truncates publication stderr and does not retain stdout. No missing-field diagnostic was visible in the retained output; this run does not certify the complete user-facing error. No new product issue was found or fixed.

## Fixes and cleanup

- Removed the shared Python import, Namespace calls and monkey-patching. Launch, doctor, SQL, pause and cleanup now use subprocess CLI calls.
- Used shared `--target-dir` for authority and parser builds. An absolute seed stem lets `build.rs` read the malformed seed under `.local` without copying authority sources or changing tracked inputs.
- Removed duplicate module-copy and post-delete HTTP logic. Shared cleanup confirms SQL 404; the driver checks cleanup status, retained evidence and module removal.
- Added startup preconditions and replaced the historical cleanup example with `<child-run>`.
- Replaced the old validation record with this full run.

All seven child cleanups exited 0 and confirmed SQL 404. `post-cleanup.json` confirms retained evidence, no published child databases, unchanged driver/harness hashes, and the original container still running with its 15:39:13 start time. No shared-harness change is requested for these checks. Complete publication-error retention remains a harness limitation for future readability checks.

## Documentation and compatibility

Consulted the official [documentation entry point](https://spacetimedb.com/docs/), [reducers](https://spacetimedb.com/docs/functions/reducers/), [SQL](https://spacetimedb.com/docs/reference/sql/) and [table performance](https://spacetimedb.com/docs/tables/performance/) guidance before changing the driver. Reducers own mutations; diagnostic SQL reads the public tables after an admin pause. These bounded exports do not add gameplay scans, subscriptions or indexes. Documentation is labeled 2.0.0; manifests and the actual server pin 2.10.1. The [versioned HTTP implementation](https://github.com/clockworklabs/SpacetimeDB/blob/v2.10.1/crates/client-api/src/routes/database.rs) and live calls support the endpoints used here.

`discovery.json` confirms the shared Codex/Mistral Vibe tree and existing Claude Code/Cursor links expose the same frontmatter and executable driver. Syntax, relative links and whitespace checks passed. No adapter change was needed. Runtime discovery and invocation in the other agents were not driven.

## What remains unverified

Fresh paid drafting and its second pass, complete publication-error readability, semantic privacy of authored prose, every numeric seed, repeated valley homestead placement, subscriptions, browser rendering, player actions, learning, later ecology and performance. Use the neighbouring verification skills and performance contract for those claims.

## Seeded lives (2026-11-10, branch `lives-1`)

`generation-lives-0256` on the dev-box, in a worker's own container (`LIVING_STDB_CONTAINER=lives-stdb`, `LIVING_STDB_URL=http://127.0.0.1:3412`, SpacetimeDB 2.14.1), from commit `2108cdc` plus the terrace-garden fix:

- `island` passes 968 of 968 checks. The new checks: hamlets laid out and peopled where the seed's `site: hamlet_village` entries ask (9 of 9); authored sheet relations as `relation` rows (2,348 of 2,348); authored places and the stages of known ways (9 residents, 60 stages, the longest 130.6 m); workplaces an author gave a resident exempt from the in-or-by-settlement check. The `land` digests (tiles `9b403da95bba9407`, heights `0d2f77752781845c`, layout `408df4be210092eb`) equal `floor_preview`'s.
- `authored island` compiles `living/seeds/worlds/island` offline (network blocked) to the committed `island.json`.
- One failure outside this change: "Saltmere memberships" in the second `realm` child. Roborpe (id 21) died within seconds of creation; death removes the membership but keeps the background the check counts. The first `realm` child passed. The check should compare living residents only.
- The previous run (`generation-lives-0247`) failed "open lots stay walkable" on a Kettlebridge garden laid across a terrace step. The planner now keeps gardens and fields off terrace steps (`settle.rs`, `try_lot`). It also failed "original seeds unchanged", because `island.json`'s setting text was edited during that run.
