# Floors: a runtime seed and staged creation

## Sub-features

- A floor module: built without a seed (`LIVING_SEED=none`), published, its world empty until the admin calls `create_floor(seed_json)`.
- `create_floor` keeps the seed (private `floor_seed`), refuses a second call ("this floor already has its seed"), a module built with a seed, or a seed whose `rules` differ from the module's.
- A land over 2048 m is created by the scheduled `genesis_step`, one bounded step per call: `land::Gen`'s steps, hosting, terrain chunks, lots and resources in batches, then people and animals. The public `genesis` row shows `step`, `steps`, `label`, `restarts` and `done`; the world ticks once it is done.
- `create_floor` refuses a land whose side is not a multiple of 16 from 256 to 8192 m ("a land's side is a multiple of 16 …").
- `stop_genesis` (admin) unschedules the next step, leaving the creation as a failed step leaves it; `resume_genesis` (admin) schedules it again. `resume_genesis` is refused with no staged creation, while a step is scheduled and once the world is made; `stop_genesis` when no step is scheduled. A step returning an error keeps it in the `genesis` label ("stopped: …").
- The created world is the same as the seed regenerated natively (land digests), and passes the seeded-world checks (wards, districts, towers, gates, town life, minds off).

`living/authority/src/floor.rs`: `create_floor`, `check_rules`, `begin`, `genesis_step` (with the in-memory cache it checks against the `genesis` row), `expected`. `living/authority/src/seed.rs`: `active`, `load`, `world_row`, `populate`, `spawn_resources_rows`. `living/rules/src/land.rs`: `Gen`; `living/rules/src/settle.rs`: `Staged`.

## How to get to it (user POV)

`just living-floor floor-megacity <db>` builds the floor module with the seed's switches, publishes it and calls `create_floor`. Watch `SELECT * FROM genesis` until `done`; then the world ticks.

## Driving it with generation.py

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-floors-$(date +%Y%m%d-%H%M%S) --feature worlds --seeds floor-megacity-4k
```

The child `floor-megacity-4k` derives the megacity seed at 4096 m into the run's directory, launches with `--seed none`, calls `create_floor` as the admin, polls `genesis` every 3 s (up to 900 s) and then runs doctor, the snapshots, the seeded-world checks and the native digests. Its `checks.json` adds: `create_floor refuses a 5000 m land` (not a multiple of 16), `a 9216 m land` (above 8192) and `a 128 m land` (below 256), `resume_genesis is refused before any creation`, `create_floor accepted the seed`; at step 3 or later `resume_genesis is refused while a step is scheduled`, then `stop_genesis` and `a chain stopped midway stalls` (no `genesis_timer` row and the step count holding for 8 s; `genesis-stalled.json`), `stop_genesis is refused when no step is scheduled`, `resume_genesis carries the stopped creation on`; then `the staged creation finished` (with steps and seconds), `resume_genesis is refused once the world is made`, `no generation restarts`, `a second create_floor is refused`. Owner SQL cannot stand in for `stop_genesis`: 2.14.1 refuses "SQL writes to scheduled tables". `genesis-final.json` keeps the last `genesis` row. On the dev-box: 18 s and 138 steps.

## Gotchas

- The floor module and the seeded modules build in different target directories under the run (`target/floor`, `target/seeded`), so neither rebuild overwrites the other.
- `restarts` above 0 means the instance lost its in-memory generation and started over; the floor is still the same land (digests), but on a quiet scratch server it should be 0.
- Fuel per step is measured outside the authority, with `living/tools/land_fuel/run.sh SEED SIZE` (docs/FLOORS.md, staged generation); this skill proves the authority path, not the budget margin.
