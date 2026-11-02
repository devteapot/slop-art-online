# Generation verification map

| Feature | File |
| --- | --- |
| A seed produces the described world | [seeded-world.md](seeded-world.md) |
| Terrain and sites repeat; RNG differences are measured | [repeatability.md](repeatability.md) |
| Cached authored-world compilation and sheet resolution | [authored-worlds.md](authored-worlds.md) |
| Parser guards and failed publication | [seed-guards.md](seed-guards.md) |

All drivers use `.agents/skills/verify-generation/scripts/generation.py` from the repository root. The default command drives all four features. Scratch names begin `generation-`; databases begin `verify-generation-`.
