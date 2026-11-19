# law-override: scripts read the world's own law values through one helper

This record follows the [law-override records](../../../verify-core/references/validation/2026-11-19-1901-law-override.md). On branch `law-override`, the world's own law values live in `law_override`, and `world_law` is no longer written. Verification scripts and trials that read `world_law` would restore or compare stale values, or wait forever. The coordinator fixed `cues.py` and `near_tier.py` in 860f2e0c by reading `law_override`. This change moves every reader onto one helper.

## The helper

`own_laws(query)` in `living/tools/law_values.py` returns `{name: value as JSON text}`:

- it lays `law_override` over `world_law`, so it reads a current module and one from before `law-override` (trials' before arms, older wasm tags);
- `world_law` exists on every module, so a failure to read it is raised;
- a failing `law_override` query (no such table) counts as no rows;
- a wrong call (`TypeError`) is raised, not taken for "no rows".

`living/tools/law_values_selftest.py` passes 4/4, and the harness skill documents the helper under "Identities and state".

**Switched readers:**

- verify-core `scenes.py`: `law_value`, and the waits on `cues_on`, `stranger_by_name`, `first_sight_thinks` and `heard_first_rethinks`; `lazy`'s `fov_on`;
- verify-core `law_override.py`'s `value_of`;
- verify-client `cues.py`, `near_tier.py`;
- verify-player `combat.py` (`breath`'s `run_share`, `onlooker`'s `witness_fold_ms`), `first_sight.py`, `offers.py`;
- verify-minds `cues_mind.py`, `verify_minds.py` (`watch-fight`, `first-sight`, `think-framing`);
- verify-generation `generation.py`: the seed's `rules` kept, read from both tables;
- `living/tools/trials.py`: a variant's `world_laws` read back.

**Not changed:** verify-ui `check.py` (the laptop's, around line 1668).

## Runs

All runs used a private server, `slop-lawfix-stdb` (v2.14.1, 127.0.0.1:3474), at 860f2e0c plus these changes. There were no model calls (fake model).

| Surface | Run | Scene | Result |
| --- | --- | --- | --- |
| verify-core | `core-lawfix-a` | `cues` | 14 pass |
| verify-core | `core-lawfix-b` | `stranger_filter` | 9 pass |
| verify-core | `core-lawfix-c` | `sleeper` (with `sleeper_cue`) | 25 pass |
| verify-core | `core-lawfix-d` | `moves` (`law_value`) | 6 pass |
| verify-core | `core-lawfix-e` | `first_sight` | 22 pass |
| verify-core | `core-lawfix-f` | `heard_first` | 12 pass |
| verify-core | `client-lawfix-island` | `law_override.py checks` | 55/55 |
| verify-client | `client-lawfix-cues` | `cues.py`, `near_tier.py` | 21/21, 7/7 |
| verify-player | `player-lawfix-combat` (island) | `combat.py --scene breath,onlooker` | 12/12 |
| verify-player | `player-lawfix-first-sight` | `first_sight.py` | pass |
| verify-player | `player-lawfix-offers` | `offers.py` | 17/17 |
| verify-minds | `minds-lawfix-cases` | `watch-fight`, `first-sight`, `think-framing` | pass |
| verify-minds | `minds-lawfix-cues` | `cues_mind.py` (slop-trials-neo4j) | 6/6, Neo4j cleanup 0 |

`cues.py` and `near_tier.py` each restored the delivery laws to `true` through the helper, with no row before.

`first_sight.py` read back `{"first_sight_thinks": "true", "first_sight_gap_s": "0"}` from `law_override` through the helper.

`trials.py` imports, and `trials_laws_selftest.py` passes.

## Not covered

- verify-generation was not driven: one line laying `law_override` over `world_law`, beside the snapshot that already holds every public table.
- No trial batch, and no live run of the helper on a module from before `law-override`. Only the self-test covers the fallback.
- verify-ui `check.py`.
