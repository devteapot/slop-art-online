# Hand-authored plans: a settlement laid out as written

## Sub-features

- A land seed's `map.params.plans` (`living_rules::settle::PlanSpec`, docs/AUTHORED_PLANS.md): levels at exact heights, streets, stairs, a square, a harbour (`sea`) and lots with explicit kinds, sizes, models and heights, in the plan's own frame (`origin`, `rotation_deg`).
- The planned settlement is one settlement row in the plan's `style` and `kind`; a seed town takes it by `site: <plan id>` (`Site::id` is the plan's id; `island::match_seed`).
- Its lot rows are the plan's lots in plan order (contiguous ids), each with its kind, `width_m` × `depth_m`, `model` ("" without one), `height_m` (6 for a building without one) and its level's height as `floor_m`; every door is walkable; blocking lots stand on `Wall` tiles like any lot.
- `homes` (household key → lot id): that household's members live at the lot's door (`character.home_x/y`) and own its house structure.
- `buildings[].lot`: the named building's sign stands at that lot's door (and its structure is the lot's own when the kinds match).
- `town_life` kinds `lot:<id>` (places and `work`): residents' `place` rows stand at that lot (its spots, else its door).
- The `land` row's digests equal a native regeneration (`floor_preview`), as for every land.
- Refusals before anything is written: `create_floor` (and `init`, through `island::params_of`) refuses a plan the generator cannot honour (`settle::validate_plans`: a stair whose rise disagrees with its levels, overlapping lots or levels, unknown levels, anything off the land, ...); hosting refuses a plan whose building doors no one reaches (`settle::stranded_doors`).
- Lands without `plans` are byte-identical to before: proved natively by `host::tests::pinned_digests_hold` (`cargo test -p living-rules`), not by this driver.

`living/rules/src/settle/plan.rs` (`resolve`, `validate`, `Ground`, `stamp_macro`, `site`, `build`, `retaining`, `stranded_doors`); `living/rules/src/land.rs` (`hydro_pass` stamps, `macro_pass` places the plan's site first); `living/rules/src/settle.rs` (`Staged` step `Plan`, the generated steps skipping `Settlement::planned`); `living/authority/src/island.rs` (`params_of`, `host`, `PlannedLot.key`/`spots`, `Planned.lots`); `living/authority/src/seed.rs` (`authored_households` with `homes`, `buildings` with `lot`); `living/authority/src/town.rs` (`spots_of` for `lot:<id>`).

## How to get to it (user POV)

Write a plan into a land seed's `map.params.plans` and publish it like any seed (`launch --seed plan-test`, or `create_floor` on a floor module). `living/seeds/plan-test.json` is the test seed: a 9-lot harbour town on seed 3 at 1024 m with two villages, two households bound to lots, a named building at a lot and `lot:` places.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-plans-$(date +%Y%m%d-%H%M%S) --feature worlds --seeds plan-test,floor-megacity-4k
```

The `plan-test` child runs every land check plus `check_plans` (`plan plan_test: ...` lines in its `checks.json`): one settlement in its style, its lots in order with their kinds, sizes, models, heights and level floors, walkable doors, each `homes` household owning and living at its lot, the named building's sign at its lot, each `lot:` place at its lot, and its town's community on it. `floor-megacity-4k` adds `create_floor refuses a plan whose stair disagrees with its levels` (the plan-test plan with `rise_m` 3 on its 4 m stair, refused with "rises 3 m"; `create-floor-bad-plan.log`).

## Gotchas

- The rules' `settle::plan::tests` cover the frame, every refusal, the lay-out as written, continuous ground with walled drops and repeatability natively; this driver proves the authority's rows and refusals, not the ground's shape.
- The plan is part of the compiled seed: editing `plan-test.json` without a rebuild changes nothing.
- Planned lots have no style margin: a row of houses sharing walls blocks with no gap between them.
