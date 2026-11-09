# Repeatability

## Sub-features

- Two fresh publications of the same `realm.json` produce identical sorted `terrain_chunk` rows.
- Settlement names, coordinates and band camp sites match between publications.
- Resource positions, character names, seeded ages, genes and animal positions are compared and hashed.

`living/authority/src/seed.rs:607` and `:616` feed `seed.seed` to `realm::generate` or `map::generate` (a land seed goes through `island::generate` at `:611`). Town layout runs before chunk publication. `fresh_name` at line 1098, `drawn_households` at line 1287, and animal spawning from line 741 use `ctx.rng()`.

## How to get to it (user POV)

Build one seed and publish its module into two fresh databases. Inspect their initial terrain and settlement sites. A seed does not fix the reducer's RNG across separate publications.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-repeat-$(date +%Y%m%d-%H%M%S) --feature worlds
```

`repeatability.json` records equality, row counts, differing paired rows and SHA-256 for each table comparison. It also records both lists of band sites. `terrain.equal`, `settlement sites.equal` and `band sites.equal` must be true. Describe the other differences as measured findings.

## Gotchas

- Resource rows sort by kind and position. Differing paired rows count sorted-list differences, not matched entities moving.
- Animal positions use `character.home_x` and `home_y`, which retain spawn positions, rather than moving `body` segments. The driver filters out people for this comparison.
- Terrain and settlement sites are compared before either world runs long enough to reshape the map. This is evidence for `realm`, not every possible numeric seed.
- Valley band homesteads (`homestead`, `living/authority/src/seed.rs:1134`) use resource availability. Resources use reducer RNG, so those camp sites are outside the realm-site repeatability guarantee. The repeated `realm` places its bands at `r.wilds` sites (`seed.rs:719-723`), which do repeat.
