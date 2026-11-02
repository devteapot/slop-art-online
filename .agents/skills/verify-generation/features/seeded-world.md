# A seed produces its world

## Sub-features

- Realm and valley dimensions, complete 16×16 terrain chunks and valid terrain bytes.
- Towns, open settlements, household backgrounds, membership and named buildings with signs.
- Authored names and counts, sheets with resolved people and linked parents.
- Explicit people, structures, artifacts and communities.
- Wild-site and valley-homestead bands, family counts and camp structures.
- Species counts, resource presence and settlement resource promises within 24 tiles.
- No sheet `secret` field or exact nonempty secret string in exported public tables.

`living/authority/build.rs:19` selects `seeds/$LIVING_SEED.json`. `living/authority/src/seed.rs:443` generates the map, applies `city::lay_out`, inserts chunks, resources and seed content. `living/rules/src/map.rs:8` sets the classic valley to 96×96. `living/authority/src/seed.rs:738` sets settlement resource reach to 24 tiles.

## How to get to it (user POV)

Select a seed when building and publish its module. The world exists after `init`; no model service is needed. The browser observer receives the generated public tables.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-worlds-$(date +%Y%m%d-%H%M%S) --feature worlds
```

The five seeds cover drawn towns and wild bands (`realm`), explicit people, structures, artifacts and communities (`valley`), authored households (`authored-test`), authored named buildings and resource promises (`aske-coast`), and family bands with camps (`stage3-village`). Read each child's `checks.json` and table JSON files. All assertions must pass. The second `realm` also drives repeatability.

## Gotchas

- The seed is compiled into WASM. Changing the JSON without rebuilding changes nothing.
- `init` starts timers. Doctor runs before pausing; count checks include dead founders because a wolf can kill an animal before snapshots.
- Realm towns, villages and bands use `zip` or indexed sites. If a seed describes more settlements than sites, the missing rows fail these checks.
- Drawn `occupations` specify workers. `drawn_households` at line 1110 also adds random children. The driver checks worker occupations, child parent links and the resulting total separately.
- Explicit structures move to nearest walkable ground. The bounded position assertion allows three tiles in these fixtures.
- SQL exports are diagnostic snapshots of these small scratch worlds. They are not a routine gameplay data path or a subscription proof.
