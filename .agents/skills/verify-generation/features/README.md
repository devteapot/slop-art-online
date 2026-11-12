# Generation verification map

| Feature | File |
| --- | --- |
| A floor module given its seed at runtime; staged creation of a large land; a seed's own day and laws, compiled in or given at runtime | [floors.md](floors.md) |
| A hand-authored settlement plan laid out as written; homes, named buildings and places by lot | [plans.md](plans.md) |
| A seed produces the described world: terrain, towns and cities, open settlements, households, wild-site and valley bands, packs, resources and animals | [seeded-world.md](seeded-world.md) |
| Cached authored-world compilation and sheet resolution | [authored-worlds.md](authored-worlds.md) |
| Parser guards and failed publication | [seed-guards.md](seed-guards.md) |
| Terrain, sites and what creation draws at random (resources, animals, names, ages, genes) repeat | [repeatability.md](repeatability.md) |

All drivers use `.agents/skills/verify-generation/scripts/generation.py` from the repository root. The default command drives all six features (floors and plans run with the worlds). Scratch names begin `generation-`; databases begin `verify-generation-`.
