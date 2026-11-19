# Repeatability

## Sub-features

- Two fresh publications of the same `realm.json` produce identical sorted `terrain_chunk` rows.
- Settlement names, coordinates and band camp sites match between publications.
- Resource positions, character names, seeded ages, genes and animal positions match too (since 2026-11-10), and are hashed.

`init` calls `floor::begin`, which runs `seed::seed` (`living/authority/src/seed.rs`) for a compiled seed. `seed::seed` feeds `seed.seed` to `realm::generate` or `map::generate`, or to `island::generate` for a land seed. Town layout runs before chunk publication. Every random draw in `seed.rs` goes through `seed::rng`: while a step of world creation runs (`Creating`: the resources, with their first tile row, then `populate`) it draws from a generator seeded by the world seed and the step; at any other time (a birth, a migration, an admin's crowd) from the reducer's own RNG, which SpacetimeDB seeds from the call's timestamp. Before 2026-11-10 creation drew from the reducer's RNG too, so resources, animals, packs, names and ages differed between two publications of one seed.

## How to get to it (user POV)

Build one seed and publish its module into two fresh databases. Inspect their initial terrain, settlement sites and what creation placed at random.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-repeat-$(date +%Y%m%d-%H%M%S) --feature worlds
```

`repeatability.json` records equality, row counts, differing paired rows and SHA-256 for each table comparison. It also records both lists of band sites. `terrain`, `settlement sites`, `band sites`, `resource positions`, `names`, `ages`, `genes` and `animal spawn positions` must all be equal.

## Gotchas

- Resource rows sort by kind and position. Differing paired rows count sorted-list differences, not matched entities moving.
- Characters and genomes are compared without their ids (names; names and ages; genes; kinds and spawn positions). On 2026-11-10 two island publications created the same 311 characters, but one numbered them up to 4318 after its id sequence jumped.
- Animal positions use `character.home_x` and `home_y`, which retain spawn positions, rather than moving `body` segments. The driver filters out people for this comparison.
- Terrain and settlement sites are compared before either world runs long enough to reshape the map. This is evidence for `realm`, not every possible numeric seed.
- Valley band homesteads (`homestead` in `living/authority/src/seed.rs`) use resource availability; resources repeat now, so those camp sites should too, but the repeated seed is `realm`, which places its bands at `r.wilds` sites (the bands loop in `populate`).
- Only `seed.rs` draws are seeded. Other creation code that draws from `ctx.rng()` directly is not (none places rows these comparisons read).

- `--seeds` replaces the seed list, and the second `realm` is not added to it: pass `realm` twice (`--feature worlds --seeds realm,realm`) to drive repeatability alone.
