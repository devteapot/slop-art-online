# Repeatability

## Sub-features

- Two fresh publications of the same `realm.json` produce identical sorted `terrain_chunk` rows.
- Settlement names, coordinates and band camp sites match between publications.
- Founding animals (herds and packs) start at the same kinds and points: placement draws from a generator seeded from the world's seed (`seed::animal_rng`), not from `ctx.rng()`.
- Resource positions, character names, seeded ages, genes and animal positions by id are compared and hashed.

`init` calls `floor::begin`, which runs `seed::seed` (`living/authority/src/seed.rs`) for a compiled seed. `seed::seed` feeds `seed.seed` to `realm::generate` or `map::generate`, or to `island::generate` for a land seed. Town layout runs before chunk publication. `fresh_name`, `drawn_households` and animals' ages use `ctx.rng()`. Since 2026-11-10 the founding animals' start points (herds in `populate`, then the seed's `packs`) use `animal_rng(seed.seed)`, and `init` logs `founding animals: N, starts digest X`.

## How to get to it (user POV)

Build one seed and publish its module into two fresh databases. Inspect their initial terrain and settlement sites. A seed does not fix the reducer's RNG across separate publications.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-repeat-$(date +%Y%m%d-%H%M%S) --feature worlds
```

`repeatability.json` records equality, row counts, differing paired rows and SHA-256 for each table comparison. It also records both lists of band sites. `terrain.equal`, `settlement sites.equal`, `band sites.equal` and `founding animal starts.equal` must be true. Describe the other differences as measured findings.

## Gotchas

- Resource rows sort by kind and position. Differing paired rows count sorted-list differences, not matched entities moving.
- Animal positions use `character.home_x` and `home_y`, which retain spawn positions, rather than moving `body` segments. The driver filters out people for this comparison. `animal spawn positions` pairs them by id, which also depends on how many people were drawn first; `founding animal starts` sorts kinds and points without ids.
- Terrain and settlement sites are compared before either world runs long enough to reshape the map. This is evidence for `realm`, not every possible numeric seed.
- Valley band homesteads (`homestead` in `living/authority/src/seed.rs`) use resource availability. Resources use reducer RNG, so those camp sites are outside the realm-site repeatability guarantee. The repeated `realm` places its bands at `r.wilds` sites (the bands loop in `populate`), which do repeat.
