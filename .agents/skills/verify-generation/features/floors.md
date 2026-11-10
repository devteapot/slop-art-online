# Floors: a runtime seed and staged creation

## Sub-features

- A floor module: built without a seed (`LIVING_SEED=none`, its `rules` switches from `LIVING_RULES`), published, its world empty until the admin calls `create_floor(seed_json)`.
- `create_floor` keeps the seed (private `floor_seed`), refuses a second call ("this floor already has its seed"), a module built with a seed, or a seed whose `rules` differ from the module's.
- A land over 2048 m is created by the scheduled `genesis_step`, one bounded step per call: `land::Gen`'s steps, hosting, terrain chunks, lots and resources in batches, then people and animals. The public `genesis` row shows `step`, `steps`, `label`, `restarts` and `done`; the world ticks once it is done.
- The created world is the same as the seed regenerated natively (land digests), and passes the seeded-world checks (wards, districts, towers, gates, town life, minds off).

`living/authority/src/floor.rs`: `create_floor`, `check_rules`, `begin`, `genesis_step` (with the in-memory cache it checks against the `genesis` row), `expected`. `living/authority/src/seed.rs`: `active`, `load`, `world_row`, `populate`, `spawn_resources_rows`. `living/rules/src/land.rs`: `Gen`; `living/rules/src/settle.rs`: `Staged`.

## How to get to it (user POV)

`just living-floor floor-megacity <db>` builds the floor module with the seed's switches, publishes it and calls `create_floor`. Watch `SELECT * FROM genesis` until `done`; then the world ticks.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-floors-$(date +%Y%m%d-%H%M%S) --feature worlds --seeds floor-megacity-4k
```

The child `floor-megacity-4k` derives the megacity seed at 4096 m into the run's directory, launches with `--seed none` and `LIVING_RULES` from the seed, calls `create_floor` as the admin, polls `genesis` every 3 s (up to 900 s) and then runs doctor, the snapshots, the seeded-world checks and the native digests. Its `checks.json` adds: `create_floor accepted the seed`, `the staged creation finished` (with steps and seconds), `no generation restarts`, `a second create_floor is refused`. `genesis-final.json` keeps the last `genesis` row. On the dev-box: 18 s and 138 steps.

## Gotchas

- The floor module and the seeded modules build in different target directories under the run (`target/floor`, `target/seeded`), so neither rebuild overwrites the other.
- `restarts` above 0 means the instance lost its in-memory generation and started over; the floor is still the same land (digests), but on a quiet scratch server it should be 0.
- Fuel per step is measured outside the authority, with `living/tools/land_fuel/run.sh SEED SIZE` (docs/FLOORS.md, staged generation); this skill proves the authority path, not the budget margin.
