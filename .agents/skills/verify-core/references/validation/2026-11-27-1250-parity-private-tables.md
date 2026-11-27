# parity-private-tables: facts no player has a view of (`perceived_private_on`, off; `seen_pasture`)

Branch `parity-private-tables` from origin/main `3d41ec73d`, driven on `17b6997c9` (the change and the view), `2ba267b21` (feature pages) and `4737cbbb2` (a comment). Spark (aarch64), private servers `slop-psp-stdb` (scenes and verify-client, `127.0.0.1:3497`), `slop-psp-deta` (det_compare, copies on 3492–3495), `slop-psp-trials` (trials, `:3485`, with its own Neo4j `slop-psp-neo4j`), SpacetimeDB 2.14.1. Builds through `build-slot` with private target dirs, pinned to CPUs 0-4,10-14; launches under `trial-activity.lock`. No paid model calls.

**Change** (features/perceived-private.md, per audit row):

- `Target::Suitor`/`courted`, `Target::Partner`, `Target::Parent`: unchanged; parity since main's `my_bond_offers` and `my_kin` (and `my_characters`' own parents).
- `bedtime`, `evening`, `work_hours` (`rhythm`): unchanged; the character's own schedule over the public hour, its will as a player's plan is theirs. Compiling the hours into `hour` ranges would move the same numbers, not who knows them.
- `smells`: under the new ordinary law `perceived_private_on` (off as shipped), a person has no scent whatever a seed's species say (`common::scent_for`, in the graph's `smells`, a target smelled, an act's and a pursuit's reach). No shipped species gives a person one.
- `pasture`: exposed, not degraded: the new identity-scoped view `seen_pasture` gives a player the `pasture` rows of the chunks within its sight (`character_senses`) of its body, the rows a graph's `nearest grass` reads from there. The graph is unchanged. (A first version degraded it to the chunk one stands in, behind the law; without a memory a grazer would walk between two bare chunks, so it was replaced before any run.)
- `brain::alerts` `sole`: under the law, "You alone know how to …" is never raised (it scanned every living character's know-how).

**Det (law off)** against main `3d41ec73d`, each copy with its build's own script (`--scripts … --seed cullet`):

| Template | Result |
|---|---|
| Cullet, `spawn_battle` 200, 16 players, 3,600 ticks | **identical** (3,600 ticks, 113 tables, 47,567 rows) |
| Cullet town with a fight, `fov_on` set on the template: `spawn_battle` 20, 16 players, 7,200 ticks | **identical** (7,200 ticks, 113 tables, 26,631 rows) |

Where the touched code fires, the town template with the law set on the candidate alone (`--candidate-law perceived_private_on=true`): beyond the law's own rows the copies differ from tick 27 in `experience`, `deliberation` and `sex_seen`: off, Cullet's five sole knowers feel it (10,601 experience rows); on, none (10,596). The template step used a scratch copy of `det_compare.py` with `prepare --prep-law NAME=VALUE`; `run` is the tracked tool's.

**Scenes** (default seed).

| Scene (run) | Result |
|---|---|
| `perceived_private` (new, `core-ppt1-125024`) | **4/4** first attempt: P alone knowing pottery; law on, nothing in 75 s; law off, the feeling naming it |
| `grazing`, `teach`, `sight`, `tick` (`core-ppt1-125024`) | 3/3, 6/6, 6/6, 6/6 |
| `wildlife` (`core-ppt1-125024`, after `grazing`) | 2/2 then a timeout: it grazes the same deer `grazing` just grazed, and that chunk was bare ("the grass here is grazed bare" in its experience): the scene order, not the change |
| `wildlife` (fresh `core-ppt2-134125`) | its world was paused by the orphan guard at 600 s (the scene waits 21 min with no verify.py call; my launch kept the default lease) and the migration never came: not a result |
| `wildlife` (fresh `core-ppt3-144444`, `VERIFY_LEASE_SECONDS=3600`) | **14/14** |

**Law on versus off** (`trials.py run --fake`, Cullet, 6 fake-model minds, everyone else on Cullet's graphs, 10 min, two replicates an arm, all four at once; a scratch sampler of new `experience` rows every 5 s). A variant's law is set just after the world starts, after the first check of every calm grown person: Cullet's five sole knowers (medicine and wound tending, smoking, storage, torch, masonry) feel it at once in every arm. Batch `pptab3` then gives five subjects a technique no one else knows at minute 2 (`grant_know_how`: archery, fire_bolt, bridging, tanning, trapping):

| "You alone know how to" | off r1 · r2 | on r1 · r2 |
|---|---|---|
| at the start (before the law) | 5 · 5 | 5 · 5 |
| after the grants at minute 2 | 5 · 5 (each of the five, about a minute after) | 0 · 0 |
| all feelings | 69 · 70 | 65 · 66 |

Batch `pptab2` (the same without grants): 5 at the start in each of the four worlds and none after. The batch `pptab1` ran nothing (the second checkout lacked the trial server's Neo4j password file).

**Cleanup.** The trials' cleanup failed for one `pptab3` world ("could not read the replica commitlog"); `trials.py clean` paused, checked (SQL 404) and deleted all of `pptab2` and `pptab3`.

Evidence: `~/slop-evidence/parity-sound-private-20261127.tar.zst` (`.sha256` beside it): `.local/living/verify/{core-ppt1-125024,core-ppt2-134125,core-ppt3-144444,client-ppt1-125323,minds-ppt*}`, `.local/living/trials/{pptab2,pptab3}`, the det outputs (`ppt-c200`, `ppt-town`, `ppt-town-lawon`), the sampler, its report and the scratch trial and variant files.

**Not covered:** a person with a scent (no shipped species has one); the game client showing `seen_pasture` (it does not read it yet); `seen_pasture` beyond 16 m of sight driven (Cullet's 48 m day); det with the law on as a pass; the island seed.
