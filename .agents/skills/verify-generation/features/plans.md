# Hand-authored plans: a settlement laid out as written

## Sub-features

- A land seed's `map.params.plans` (`living_rules::settle::PlanSpec`, docs/AUTHORED_PLANS.md): levels at exact heights, streets, stairs, a square, a harbour (`sea`) and lots with explicit kinds, sizes, models and heights, in the plan's own frame (`origin`, `rotation_deg`).
- The planned settlement is one settlement row in the plan's `style` and `kind`; a seed town takes it by `site: <plan id>` (`Site::id` is the plan's id; `island::match_seed`).
- Its lot rows are the plan's lots in plan order (contiguous ids), each with its kind, `width_m` × `depth_m`, `model` ("" without one), `height_m` (6 for a building without one) and its level's height as `floor_m`; every door is walkable; blocking lots stand on unwalkable tiles like any lot (`Wall` where the model hides at eye height, `Low` where it does not; a lot naming no model in the table, as Cullet's and plan-test's do until Cullet's kit enters it, is `Wall` throughout above the eye).
- `homes` (household key → lot id): that household's members live at the lot's door (`character.home_x/y`) and own its house structure.
- `buildings[].lot`: the named building's sign stands at that lot's door (and its structure is the lot's own when the kinds match).
- `town_life` kinds `lot:<id>` (places and `work`): residents' `place` rows stand at that lot (its spots, else its door).
- `resources[]` (kind and point in the plan frame, anywhere on the land): a `resource_node` of each kind the rules know (`catalog::RESOURCES`) stands at the nearest walkable tile to its point; kinds the rules do not know yet are not placed (logged `plan resources: ... waiting for their kinds`).
- Authored land (`map.params.relief.outline`, `relief.stamps`: a coastline and stamps of height, region kind and ground; docs/AUTHORED_PLANS.md): checked here only through the land digests against `floor_preview` and the refusals; the shape is proved natively (`land::tests::an_authored_outline_and_stamps_shape_the_land`, `settle::plan::tests::the_cullet_seed_is_valid_and_reachable`).
- The `land` row's digests equal a native regeneration (`floor_preview`), as for every land.
- Refusals before anything is written: `create_floor` (and `init`, through `island::params_of`) refuses a plan the generator cannot honour (`settle::validate_plans`: a stair whose rise disagrees with its levels, overlapping lots or levels, unknown levels, anything off the land, a resource off the land or without a kind, ...) and bad authored relief (`land::validate_relief`); hosting refuses a plan whose building doors no one reaches (`settle::stranded_doors`). `seed::tests::the_cullet_seed_is_hosted` runs those same checks on Cullet's seed natively.
- The drops between its levels are `drop` tiles (8: unwalkable, see-through; docs/PERCEPTION.md "Drops"): `a planned settlement's drops are drop tiles` (at least one on the hosted tiles). That sight and the foot agree across them is proved by `verify-core`'s `drop` scene and `verify-player`'s `drop.py`.
- Lands without `plans`, `relief.outline` or `relief.stamps` keep their pinned digests (`host::tests::pinned_digests_hold`, `cargo test -p living-rules`, not this driver). Since eye-2 the pinned tiles digests are those of the eye-height cells; the test also checks that the height rule (no model's `eye_cells`) still gives the digests before eye-2 exactly, and that every moved tile went from `Wall` to `Low` or `Drop`.

`living/rules/src/settle/plan.rs` (`resolve`, `validate`, `Ground`, `stamp_macro`, `site`, `build`, `retaining`, `stranded_doors`); `living/rules/src/land.rs` (`hydro_pass`: the authored outline and relief stamps, then the plans' stamps; `macro_pass` places the plan's site first and applies region stamps; `tile_rows` ground stamps; `connect_pass` leaves a planned site's disc as it is; `validate_relief`); `living/rules/src/settle.rs` (`Staged` step `Plan`, the generated steps skipping `Settlement::planned`); `living/authority/src/island.rs` (`params_of`, `host`, `PlannedLot.key`/`spots`, `Planned.lots`, `Hosted.resources`); `living/authority/src/seed.rs` (`authored_households` with `homes`, `buildings` with `lot`, `plan_resources`); `living/authority/src/town.rs` (`spots_of` for `lot:<id>`).

## How to get to it (user POV)

Write a plan into a land seed's `map.params.plans` and publish it like any seed (`launch --seed plan-test`, or `create_floor` on a floor module). `living/seeds/plan-test.json` is the test seed: a 9-lot harbour town on seed 3 at 1024 m with two villages, two households bound to lots, a named building at a lot, `lot:` places and three authored resources (two fishing spots and a `kelp`, a kind that does not exist yet). `living/seeds/cullet.json` is the small city (written by `living/tools/cullet_plan.py`): 93 lots on an authored island, five named buildings at lots, 158 authored resources (93 of known kinds), and no people.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-plans-$(date +%Y%m%d-%H%M%S) --feature worlds --seeds plan-test,cullet,floor-megacity-4k
```

The `plan-test` child runs every land check plus `check_plans` (`plan plan_test: ...` lines in its `checks.json`): one settlement in its style, its lots in order with their kinds, sizes, models, heights and level floors, walkable doors, each `homes` household owning and living at its lot, the named building's sign at its lot, each `lot:` place at its lot, its town's community on it, `its N authored resources of known kinds stand where written` (within 2.5 m) and `authored resources of unknown kinds are not placed` (their counts in the detail). The `cullet` child runs the same checks on a town with no people: the people checks read `(none: the seed has no people)`. `floor-megacity-4k` adds `create_floor refuses a plan whose stair disagrees with its levels` (the plan-test plan with `rise_m` 3 on its 4 m stair, refused with "rises 3 m"; `create-floor-bad-plan.log`).

## Gotchas

- The rules' `settle::plan::tests` cover the frame, every refusal, the lay-out as written, continuous ground with drops closed to walking, sight but not walking across the drop (`people_see_across_the_plans_drop_but_cannot_walk_across`) and repeatability natively; this driver proves the authority's rows and refusals, not the ground's shape.
- The plan is part of the compiled seed: editing `plan-test.json` without a rebuild changes nothing.
- Planned lots have no style margin: a row of houses sharing walls blocks with no gap between them.
- `KNOWN_RESOURCES` in the driver is a copy of `living_rules::catalog::RESOURCES`; when goods become script data (goods-1), keep it in step, or the resource checks misjudge which kinds should be placed.
- `floor_preview` does not run the plan's validation, so a plan it previews can still be refused by `init`; run `cargo test -p living-rules the_cullet_seed` (or the authority's `seed::tests`) after editing a plan.
