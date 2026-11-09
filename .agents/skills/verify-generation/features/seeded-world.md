# A seed produces its world

## Sub-features

- Realm and valley dimensions, complete 16×16 terrain chunks and valid terrain bytes.
- Towns, open settlements, household backgrounds, membership and named buildings with signs.
- Authored names and counts, sheets with resolved people and linked parents.
- Explicit people, structures, artifacts and communities.
- Wild-site and valley-homestead bands, family counts and camp structures.
- Species counts, resource presence and settlement resource promises within 24 tiles.
- No sheet `secret` field or exact nonempty secret string in exported public tables.
- Land worlds (`map.kind = "land"`, `living/seeds/island.json`): the side from `map.size`, the `land` row (seed, size, digests, walkable arrival point), a `settlement` row per settlement linked to its seeded community and site kind, `lot` rows 0..n with the right structure exactly at every building's door, walkable doors, `Wall` tiles under blocking lots, house structures that are lot houses and owned by households, residents' `folk` and `body_scale`, and with `rules.minds` false no AI or admin-controlled character.
- A land with a city (`map.params.metro`, `living/seeds/floor-megacity.json`, docs/FLOORS.md), published at 2048 m as the derived `floor-megacity-2k`: one settlement per ward (the core plus every ring band and sector, `1 + rings × arterials`), ward styles `metro`, `slum` and `works`, at least 40 lots of 50 m or more in the core, every other settlement outside the city, and gate tiles where the arterials cross the wall.
- Every land world's `land` row digests equal the same seed regenerated natively by `living/rules/examples/floor_preview.rs` (WASM authority against a native client).
- Town life on a land world with `town_life` and `ways` (docs/TOWN_LIFE.md): residents know the seed's places (`square`, `inn`, `evening` as `place` rows, at most 5% missing), workers have a `work` place on walkable ground in or by their settlement, and every resident with an occupation starts with the seed's own `common` routines (`routine` rows).

`living/authority/build.rs:18-20` selects `seeds/$LIVING_SEED.json`. `seed::seed` at `living/authority/src/seed.rs:602` generates the map (`realm` at `:607`, `land` at `:611`), applies `city::lay_out` (`:639`), inserts chunks, resources and seed content. `living/rules/src/map.rs:8` sets the classic valley to 96×96. `living/authority/src/island.rs` hosts a land world: `generate` runs `living_rules::land` and `living_rules::host::hosted_map`, `build` writes `land` and `lot` rows with door structures, and `settle` writes `settlement` rows and folk backgrounds (see `docs/ISLAND_AUTHORITY.md`), then `town::seat` the residents' places. A land's city comes from `living_rules::settle::metro` (`lay_out`, `place_lots`, `pave`), called from `settle::plan` when `LandParams.metro` is set. `living/authority/src/seed.rs:935` sets settlement resource reach to 24 tiles.

## How to get to it (user POV)

Select a seed when building and publish its module. The world exists after `init`; no model service is needed. The browser observer receives the generated public tables.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-worlds-$(date +%Y%m%d-%H%M%S) --feature worlds
```

The seven seeds cover drawn towns and wild bands (`realm`), explicit people, structures, artifacts and communities (`valley`), authored households (`authored-test`), authored named buildings and resource promises (`aske-coast`), family bands with camps (`stage3-village`), the km-scale land with its settlements, lots and instinct-only residents (`island`; about 3 s of `init` and 20 MB of SQL snapshots), and the megacity floor at 2048 m (`floor-megacity-2k`, derived from `floor-megacity.json` in the run's directory and published through an absolute `--seed`; about 3.5 s of `init`). Each land child also runs `cargo run --release --example floor_preview` in the run's target dir for the native digests (`native-digests.log`, `native/`). Read each child's `checks.json` and table JSON files. All assertions must pass. The second `realm` also drives repeatability.

## Gotchas

- The seed is compiled into WASM. Changing the JSON without rebuilding changes nothing.
- `init` starts timers. Doctor runs before pausing; count checks include dead founders because a wolf can kill an animal before snapshots.
- Realm towns, villages and bands use `zip` or indexed sites. If a seed describes more settlements than sites, the missing rows fail these checks.
- Drawn `occupations` specify workers. `drawn_households` at `seed.rs:1287` also adds random children. The driver checks worker occupations, child parent links and the resulting total separately.
- Land worlds place no `bands` (their homestead search does not scale to 4.2M tiles); the module logs a warning instead.
- The megacity seed itself is 4096 m, and at that size `init` runs out of the reducer's fuel budget ("reducer ran out of energy", docs/FLOORS.md, scale). The driver therefore publishes the derived 2048 m seed; do not add `floor-megacity` itself to `SEEDS`.
- Explicit structures move to nearest walkable ground. The bounded position assertion allows three tiles in these fixtures.
- SQL exports are diagnostic snapshots of these small scratch worlds. They are not a routine gameplay data path or a subscription proof.
