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
- A land with a city (`map.params.metro`, `living/seeds/floor-megacity.json`, docs/FLOORS.md), published at 2048 m as the derived `floor-megacity-2k` (created inside `init`): one settlement per ward (the core plus every ring band and sector, `1 + rings × arterials`), a ward for every district style the seed names, at least six lots of 100 m or more in the core's district, every other settlement outside the city, and gate tiles where the arterials cross the wall. Town life works round a square whose middle is built on (the core's arcology): residents take the nearest reachable point of its edge.
- The same city at 4096 m as a floor: see [floors](floors.md).
- Every land world's `land` row digests equal the same seed regenerated natively by `living/rules/examples/floor_preview.rs` (WASM authority against a native client).
- Town life on a land world with `town_life` and `ways` (docs/TOWN_LIFE.md): residents know the seed's places (every name in `town_life.places`, on the island `square`, `inn`, `berries` and `store`, plus `evening`, as `place` rows, at most 5% missing), a place listed in `town_life.spread` (the island's `berries`) is shared out like work, so at least half its holders have distinct spots,, workers have a `work` place on walkable ground in or by their settlement (unless the seed gave that resident its own `work`), and every resident with an occupation starts with the seed's own `common` routines (`routine` rows).
- Seeded lives on the island (docs/SEEDED_LIVES.md): hamlets (`settlement.style = hamlet`) laid out, and peopled exactly where the seed has a `site: hamlet_village` entry (chosen by `near` and `region` in `island::match_seed`); every authored sheet relation between two people of the world is a `relation` row; every authored relation across communities is an introduction (`acquaintance`), and none marked `knows_name: false` is; the places an author gave a resident (`residents[].places`) exist as `place` rows, with `<name> 1..n` for a known way, each stage within 220 m of the last (`living_rules::ways`).
- Seeded records (docs/WORLD_RULES.md, since `rules-2`): a seed's `records` list makes `record` and `record_party` rows at genesis, after its communities, with parties by role naming a community or a person. A record naming a party that is not there is skipped and logged. The island has 13 `regard` stance records between its communities (`world.json` `records`, copied by `author_world.py`). Proved on an island run by verify-core `scenes.py dealings`: the records exist, and a relation filter reads one. This driver does not check them yet.

`living/authority/build.rs` selects `seeds/$LIVING_SEED.json` (or none: a floor module). `init` (`living/authority/src/lib.rs`) parses it and calls `floor::begin` (`living/authority/src/floor.rs`), which runs `seed::seed` in the same call when the land is at most 2048 m (`INLINE_MAX_M`), else schedules the staged creation ([floors](floors.md)). `seed::seed` (`living/authority/src/seed.rs`) generates the map (`realm`, `land` through `island::generate`, or the classic valley), applies `city::lay_out` to realm towns, inserts chunks, writes the world row (`world_row`), hosts a land (`island::build`), places resources and calls `populate` for the seed's content. `living/rules/src/map.rs` sets the classic valley to 96×96. `living/authority/src/island.rs` hosts a land world: `generate` runs `living_rules::land::generate` (all of `land::Gen`'s steps) and `host`, which runs `living_rules::host::hosted_map` and plans settlements and lots; `build` writes `land` and `lot` rows with door structures; `settle` writes `settlement` rows and folk backgrounds (see `docs/ISLAND_AUTHORITY.md`), then `town::seat` the residents' places (the seed's `town_life` and each resident's own `places`, a known way's stages along `Hosted::ways`). `seed::settle_authored` writes each sheet's relations as `relation` rows. A land's city comes from `living_rules::settle::metro` (`lay_out`, `ward_lots`, `ward_fill`, `ward_close`, `pave`), driven by `settle::Staged` when `LandParams.metro` is set. Animals go where the seed's `animals.habitat` says (wolves in the megacity's wastes), else forest for wolves and grass for the rest. `SETTLEMENT_REACH` in `seed.rs` sets settlement resource reach to 24 tiles.

## How to get to it (user POV)

Select a seed when building and publish its module. The world exists after `init`; no model service is needed. The browser observer receives the generated public tables.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-worlds-$(date +%Y%m%d-%H%M%S) --feature worlds
```

The eight seeds cover drawn towns and wild bands (`realm`), explicit people, structures, artifacts and communities (`valley`), authored households (`authored-test`), authored named buildings and resource promises (`aske-coast`), family bands with camps (`stage3-village`), the km-scale land with its settlements, lots and instinct-only residents (`island`; about 3 s of `init` and 20 MB of SQL snapshots), and the megacity floor at 2048 m (`floor-megacity-2k`, derived from `floor-megacity.json` in the run's directory and published through an absolute `--seed`; about 3.5 s of `init`), and the same city at 4096 m as a floor (`floor-megacity-4k`, [floors](floors.md)). Each land child also runs `cargo run --release --example floor_preview` in the run's target dir for the native digests (`native-digests.log`, `native/`). Read each child's `checks.json` and table JSON files. All assertions must pass. The second `realm` also drives repeatability.

## Gotchas

- The seed is compiled into WASM. Changing the JSON without rebuilding changes nothing.
- `init` starts timers. Doctor runs before pausing; count checks include dead founders because a wolf can kill an animal before snapshots; memberships are compared for the living, since an elder founder can die in those seconds and death ends membership.
- Realm towns, villages and bands use `zip` or indexed sites. If a seed describes more settlements than sites, the missing rows fail these checks.
- Drawn `occupations` specify workers. `drawn_households` in `seed.rs` also adds random children. The driver checks worker occupations, child parent links and the resulting total separately.
- Land worlds place no `bands` (their homestead search does not scale to 4.2M tiles); the module logs a warning instead.
- A land over 2048 m is not created in `init` (one reducer's fuel budget is 120 × 10⁹ instructions; the 4096 m megacity needs about 2.9 of them). It is created in steps after publication; the driver drives that through the floor module ([floors](floors.md)).
- Explicit structures move to nearest walkable ground. The bounded position assertion allows three tiles in these fixtures.
- SQL exports are diagnostic snapshots of these small scratch worlds. They are not a routine gameplay data path or a subscription proof.
