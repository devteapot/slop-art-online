# parity-commotion: a commotion only as perceived (`perceived_commotion_on`, off)

Branch `parity-commotion` from origin/main `dd434378e`, driven on `6d01b32b2` (the change) and `092599e28` (the scene). Spark (aarch64), private servers `slop-pcm-stdb-1127` (scenes, `127.0.0.1:3473`), `slop-pdet-a` (det_compare, copies on 3478–3479), `slop-pcm-trials` (trials, `:3483`, with its own Neo4j `slop-pcm-neo4j`), SpacetimeDB 2.14.1. Builds through `build-slot` with private target dirs, pinned to CPUs 0-4,10-14; launches under `trial-activity.lock`. No paid model calls.

**Change.** Under the new ordinary law `perceived_commotion_on` (off as shipped), a graph's commotion (the target `"commotion"` and the weight `commotion`) is `town::commotion_seen`: the nearest recent blow, threat or death chronicle row whose spot the character sees now (`perception::sees`: sight, field, light, a clear line), or someone in its scene visibly making a hostile move, a person or at a person. Off, `town::commotion`: the same rows within the sight radius, through walls. features/perceived-commotion.md.

**Det (law off)** against main `dd434378e`, each copy with its build's own script (`--scripts … --seed cullet`):

| Template | Result |
|---|---|
| Cullet, `spawn_battle` 200, 16 players, 3,600 ticks | **identical** (3,600 ticks, 113 tables, 48,561 rows) |
| Cullet town with a fight: `spawn_battle` 20 (at the arrival, as every battle), 16 players, 3,600 ticks | **identical** (3,600 ticks, 113 tables, 23,883 rows) |

**Scenes.**

| Scene (run) | Result |
|---|---|
| `perceived_commotion` (new, `core-pcm1-110001`, default seed) | try1 5/6: "law on, weight: O goes to the fight" failed with O seen going nowhere (O stands 3 m off; its walk ended between two 0.2 s polls, `try1/`); try2, the same scene, **6/6** (`try2/`); with the readout fixed (a `goto` toward the fight, or O's body off its spot by 0.6 m), **6/6** |
| `sight`, `fov` (`core-pcm1-110001`) | 6/6, 18/18 |
| island `town.py --scene wolf` (`core-pcmt-112711`), law off · law on (set with `set_world_law` on the same world) | **2/2** (16 residents within 14 tiles, 17 turned to face the commotion) · **2/2** (7 within 14 tiles, 5 turned) |

`perceived_commotion`: on the map's wall geometry, O in the open 3 tiles from a fight and X behind 1 to 3 tiles of rock; law off, both walk to it by target and by weight (X through the wall); law on, O does, X does not; O witnessed the fights, X none.

**Law on versus off** (`trials.py run --fake`, batch `pcmtown2`: Cullet, 6 fake-model minds, every other resident on its seeded graphs, 10 min, `spawn_skirmish` 6 at minutes 1, 4 and 7, two replicates an arm, all four at once; a scratch sampler of `activity` at about 1.4 Hz, bodies and the chronicle every 5 s; a sight line here is a straight tile line from the onlooker's sampled position, no rock or wall on it). Cullet's residents answer a commotion by facing it (their `look` desire runs `watch what happens`: `face` the commotion), so a resident's `face` aimed at a recent fight row's spot, or within 2 m of a fighter, counts as drawn:

| | off r1 · r2 | on r1 · r2 |
|---|---|---|
| fight and death rows | 472 · 505 | 325 · 317 |
| faces toward a fight · residents | 7 · 6 (2 · 2) | 18 · 12 (10 · 5) |
| of them with no straight line | 6 · 6 | 2 · 3 |
| distance p50 · max (m) | 15.5 · 51.4, 33.7 · 48.0 | 22.5 · 54.2, 30.6 · 47.3 |

Off, 12 of the 13 faces were through rock or walls, by 4 residents. On, 25 of 30 had a line; the 5 without are within this measure's error (positions up to 5 s from the act, a straight line where the authority traces its own sight with cover, a face within 2 m of a fighter for another reason). On draws more residents: a fight seen continues to draw between its chronicle rows (`visibly` combat), which off only the rows' 8 s did. One goto in an on arm (65 starts by one resident within 3–8 m of fighters) is not counted as drawn: Cullet's commotion faces and never walks, so it is some other errand of that resident's. Fights differed between arms by the skirmishes' own course. The first batch (`pcmtown1`) set its fights at `at` 60, 240 and 420, which trials read as minutes: no fight happened; it was stopped with SIGINT by PID, its kept worlds paused, checked and deleted with `trials.py clean`.

Evidence: `~/slop-evidence/parity-commotion-20261127.tar.zst` (`.sha256` beside it): `.local/living/verify/{core-pcm1-110001,core-pcmt-112711}`, `.local/living/trials/{pcmtown1,pcmtown2}`, the det outputs (`comm-c200`, `comm-fight`), the A/B sampler, its report and the Cullet tiles.

**Not covered:** the law under `fov_on` behind one's back (the scene's X is behind rock, not behind its back); heed's individuals; a threat (`threaten`) or a death alone as the commotion in a scene; det with the law on; the trials' cleanup failed for 2 of 4 `pcmtown2` worlds ("could not read the replica commitlog", their archive step), which were then paused, checked and deleted with `trials.py clean`.
