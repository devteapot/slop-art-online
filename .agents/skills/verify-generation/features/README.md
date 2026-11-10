# Generation verification map

| Feature | File |
| --- | --- |
| A seed produces the described world | [seeded-world.md](seeded-world.md) |
| Terrain, sites and what creation draws at random (resources, animals, names, ages, genes) repeat | [repeatability.md](repeatability.md) |
| Cached authored-world compilation and sheet resolution | [authored-worlds.md](authored-worlds.md) |
| Parser guards and failed publication | [seed-guards.md](seed-guards.md) |
| A floor module given its seed at runtime; staged creation of a large land | [floors.md](floors.md) |

All drivers use `.agents/skills/verify-generation/scripts/generation.py` from the repository root. The default command drives all five features (floors run with the worlds). Scratch names begin `generation-`; databases begin `verify-generation-`.
