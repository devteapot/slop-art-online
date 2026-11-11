# Validation record (generation)


## 2026-11-11 every person a mind (lives-2, dev-box)

Branch `lives-2` at the units 2-4 tree (efcd489's content), own container `lives2-stdb` (2.14.1, port 3461), private `CARGO_TARGET_DIR`. `generation-l2b-022738`: 25 of 25 summary checks pass (the eight seeded worlds, the two megacity floors, authored compilation, repeatability, malformed seeds, original seeds unchanged). The island seed no longer carries `rules.minds`; a seed that does is refused at build. Rhythms and constitution genes are drawn from each person's id, so the world's random stream, and with it every digest, is unchanged.

## 2026-11-10 fix-rules-small (dev-box)

Own container `rules-small-stdb` (2.14.1). `generation.py --feature worlds` (`generation-rs-final`, head `9115e59`): all nine worlds pass, with the native digests, and repeatability passes every comparison, now required for resources, names, ages, genes and animal positions too (compared without ids). The 4096 m floor: three bad sizes refused, `resume_genesis` refused before creation, while a step is scheduled and once made, `stop_genesis` stalled the chain for 8 s, `resume_genesis` finished it (142 steps, no restarts). Owner SQL cannot stop the chain: 2.14.1 refuses "SQL writes to scheduled tables" (`generation-rs-floor1`).

## 2026-11-10 island food places (Mac)

Own scratch container `hunger-verify` (2.14.1, port 3382) through `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`; branch `hunger-1` (main `7e5de53` merged in). The island seed gains the places `berries` and `store` and `town_life.spread`; `town::seat` reads `spread` and looks each spot kind up once per settlement. The driver's place check now names every seed place, and a new check asserts that a spread place is spread.

- **`generation-hunger-110557`** (`--feature worlds --seeds island`): island 970 of 970. All 277 residents know `berries`, `evening`, `inn`, `square` and `store`; `berries` is spread over 275 distinct bushes for 277 residents.
- **`generation-hunger-085943`** (before `spread`, from `fe6ec66`): island 969 of 969.

## 2026-11-09 floors: staged creation, a runtime seed, the second-pass megacity (dev-box)

Own scratch container `megacity-stdb` (image `v2.14.1`, port 3394, `/wasm` mounted `:z`) through `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`; worktree `~/dev/slop-megacity`, branch `megacity-1` from `14f3a72`. The driver gained the floor child `floor-megacity-4k` (`--seed none`, `create_floor`, `genesis` polled to `done`, four floor checks), `--seeds`, district styles read from the seed, membership checks of the living, and the `animals.habitat` map skipped in the animal counts.

- **`generation-mc-20261109-223043`** (`--feature all`, before the driver fixes): realm, valley, authored-test, aske-coast, stage3-village, authored compilation and seed tests pass. The island failed "Fernhollow memberships" (Peya, an elder founder, died 5 s after creation: the old-age flake recorded below), and the driver crashed on the megacity seed's `animals.habitat` map (a count was expected).
- **`generation-mc2/3`** (`--seeds island,floor-megacity-2k,floor-megacity-4k`): both megacity children failed town life: residents' square and workplaces were seated at the core square's middle, now inside its arcology. A product fix in `island::host`/`town::seat` (a square whose middle is built on offers walkable points round its edge) left 6 of 105 residents without, then none.
- **`generation-mc4-20261109-224302`**: island 72/72, megacity 2048 m 67/67, megacity 4096 m floor 71/71 (created in 18 s, 138 steps, no restarts; a second `create_floor` refused; digests equal native).
- **`generation-mcall-20261109-224617`** (`--feature all`, final code): every result passes. The five seed tests, authored compilation (no network), all ten worlds with their cleanups (SQL 404), repeatability, the malformed seed's rejection (`missing_field_diagnostic_visible` true: `seed: missing field \`animals\`` now reaches the publication output; `panic_reported` false), and the original seeds unchanged.

Maintenance pass on this skill, same run:
- **Source wave:** one reader per feature file (seeded world; guards and repeatability; authored worlds).
- **Drift fixed:**
  - stale line citations in all four files, now replaced by function names;
  - the city's checks and description, written for the prototype generator (styles `metro`, `slum`, `works`; 40 core lots of 50 m), now read the seed's districts;
  - the "seven seeds" count, and the gotcha that forbade a 4096 m megacity;
  - the malformed seed's known issue (no longer a panic).
- **Added:** `features/floors.md`.
- **Harness gaps fixed:**
  - the habitat map crash;
  - memberships of dead founders (the old-age flake recorded below);
  - `--seeds` for focused reruns.
- **Product gap fixed outside the skill:** town life at a built-on square (above).
- **Not covered:** the 8192 m floor (generated through the same path by hand: 92 s; docs/FLOORS.md), and fuel margins (measured by `living/tools/land_fuel`, not by this skill).


## 2026-11-09 the Rhai boundary, rhai-1 (dev-box)

- **Setup:** private container `rhai-stdb` (2.14.1). The seed reads `max_hp` and `regrow` through the name tables now read at compile.
- **`generation-rhai1-195746`** (`--feature all`, on `33e3185`, `rhai-1` with `origin/main` `2a64837` merged): 20 of 22 pass.
  - The island fails "Fernhollow memberships" and "Reedmoor memberships". This is the known old-age flake: residents 129 and 182 died right after creation.
  - The megacity fails "wolf count including dead founders": 5 against 8. All 5 are alive with contiguous ids, so the other 3 were never placed. `seed.rs` looks for a pack's spot in 200 random tiles of forest and stops when none is found; a 2 km city has little forest.
- **`generation-rhai1base-200854`** (`--feature worlds`, on `origin/main` `2a64837`): the same megacity failure (5 wolves), and "Lanternquay memberships" on the island.
- **Conclusion:** both failures are on main and not from this change. The megacity's wolf placement is a seed or generator finding, left for its owner.

## 2026-11-09 floors: the megacity land and native digests (dev-box)

Own scratch container `slop-floors-stdb` (image `v2.14.1`, port 3330) through a `docker` name shim (`~/floors-shim`). The harness's hard-coded `127.0.0.1:3300` was patched to 3330 in the dev-box worktree only, not committed. Worktree `~/dev/slop-floors`, branch `floors-1` from `b7cf7fb`, uncommitted. The driver gained the derived seed `floor-megacity-2k` (`living/seeds/floor-megacity.json` at 2048 m, written into the run's directory and published through an absolute `--seed`), five city checks, and a native digest cross-check for every land seed (`floor_preview`).

- **`generation-floors-20261109-130139`** (`--feature all`, before the final generator fixes): 21 of 22 results pass.
  - The island passes 72 of 72, the megacity 67 of 67, and both land rows equal a native regeneration.
  - The one failure is the known flake, "Saltmere memberships" on the second `realm`.
- **`generation-floors-final-20261109-132017`** (`--feature all`, final code): 20 of 22 results pass.
  - The island passes 71 of 72, failing "Reedmoor memberships".
  - The megacity passes 66 of 67, failing "Saltline memberships": Corbasa, a seeded resident drawn at 502 days, died of old age 4.9 s after creation, and the death cleanup removed the membership. It is the same flake as Saltmere's and Reedmoor's; seed ages are drawn, not the city.
  - Every other check passes:
    - 25 wards, metro, slum and works styles, 105 core lots of 50 m or more, every other settlement outside the city, 1,030 gate tiles;
    - digests `e182d4d6b67f0e3b`/`78040b114f6a6db6`/`50372111eee395a3` equal native;
    - the island's `c19cc98e8f1471f0`/`16412fd044a2b0b0`/`d45f735150add4ba` equal native and are unchanged from `b7cf7fb`;
    - repeatability (terrain, settlement sites and band sites equal), the five seed tests, the malformed-seed rejection (its label now `seed.rs:603`), all nine cleanups with SQL 404, and the original seeds unchanged.

Maintenance pass on this skill, same day:
- **Source wave:** one reader per feature file.
- **Drift fixed:** stale source citations in all four feature files, the malformed seed's `known_issue` source (`seed.rs:444` → `:603`, also in `docs/LIVING_HANDOFF.md`), and the seed count. The new city checks and the digest cross-check are documented in `seeded-world.md` and `SKILL.md`.
- **Live coverage:** both runs above drove every feature (worlds, repeatability, authored compilation, guards).
- **Not covered:** the 4096 m megacity, whose `init` runs out of the reducer's fuel budget (docs/FLOORS.md).

## 2026-11-09 town life: places and starting ways (dev-box)

Own scratch container `slop-townlife-stdb` (image `v2.14.1`) through a `docker` name shim; worktree `~/dev/slop-townlife`, branch `townlife-1` from `b12fa45` with the town-life change (docs/TOWN_LIFE.md) uncommitted. The seed format gained `ways` and `town_life`; `place` and `routine` joined the snapshot tables, and the land check gained four town-life checks (places known, workers placed, workplaces in or by their settlement and walkable, residents on the seed's own ways).

- **`generation-town-1`** (`--feature all`): every seed passed except the island, 68 of 71. Three failures, all in the harness: "wolf count including dead founders" (10 against 6) is drift from the combat change, which added the seed's `packs` (4 bold wolves) without the check counting them; "workplaces lie in or by their settlement" counted farm fields beyond 1.5 × the radius as far, though they are the settlement's own lots; "residents start on the seed's own ways" counted infants, who start on their species' young instinct. The three checks were corrected and re-run offline on the same snapshot (70 of 70), then live.
- **`generation-town-2`** (`--feature worlds`): every result passes. The island passes 71 of 71: 269 residents know their places with none missing, 209 workers have a workplace, and every grown resident starts with the seed's `common` routines. Repeatability and cleanup passed.

## 2026-11-09 island ornaments, terraces and styled towns (dev-box)

`generation-orn-20261109-035123`, on `c5a2c00` plus the ornaments change (`docs/FIRST_WORLD.md`, "Ornaments, terraces and styled towns"). SpacetimeDB 2.14.1 ran in a scratch container of the run's own, `slop-orn-stdb` on port 3310. Port 3300 belonged to another agent's container, so the harness's port was patched locally and not committed. This change made the land check accept a styled town's site id, `<style>_<kind>` (`steampunk_town`), against the settlement row's `kind` and `style`.
- **Result:** 19 of 20 results pass. The island passes 65 of 66: 8 settlements including both styled towns on their sites, 546 lots, and wall tiles under every blocking lot.
- **An earlier run found a real defect:** the clock tower standing in its paved square did not block. It is fixed.
- **Flake:** "Reedmoor memberships" failed again in the same way as Saltmere below: a seeded grandparent died of old age right after creation.

## 2026-11-09 island land worlds (dev-box)

Host: the dev-box (Fedora, rootless podman, SELinux enforcing). SpacetimeDB 2.14.1 ran in scratch container `slop-game-stdb`, reached through a `docker` name shim; see `docs/ISLAND_AUTHORITY.md`, "Verification". This change added the `island` seed, the land checks (`check_land`) and the `land` map size to `generation.py`. Evidence is under `.local/living/verify/` in the dev-box worktree `~/dev/slop-game`.

- **`generation-20261109-021430`** (`dc34fdf` plus the change) exited 1. `realm` ×2, `valley`, `authored-test`, `aske-coast`, `stage3-village`, authored compile, guards and repeatability passed. The island failed two of 56 checks, both real defects, since fixed:
  - 12 market stalls and wells on the paved plaza did not block;
  - `body_scale` was written as an f32 widened to f64.
- **`generation-20261109-023510`** (`977a14c` plus the change and fixes) exited 1 with 19 of 20 results passing. The island passed 56 of 56: land row and digests, walkable arrival, 6 settlement rows linked to their communities and site kinds, 372 lots, door structures, walkable doors, wall tiles under all 263 blocking lots, owned lot houses, folk backgrounds, and no mind-controlled character.
- **Finding (not caused by this change):** `realm` child 0 failed "Saltmere memberships". A drawn grandparent (`drawn_households` ages 0.76–0.9 of a lifespan) died of old age 1.2 s after `init`, and death cleanup removes memberships. The membership check expects every seeded resident, dead or alive. Repeatability and the second `realm` passed.

## 2026-10-04 fix round

Commit `384fb50e379533b7db64698357efd0b2323f9452`, branch `living-core`. Host: Fedora, rootless podman, SELinux enforcing. The working tree had pre-existing changes, including `living/viewer/src/clock.rs`. This work edited only the generation skill and wrote scratch evidence. No product code or tracked seed was changed.

The final command was:

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-fix-final-20261004-171138
```

It exited 0. Every required result passed. Evidence is under `.local/living/verify/generation-fix-final-20261004-171138/` and its seven child directories. The console is `generation-fix-final-20261004-171138-console.log` beside the parent directory. Earlier runs are historical evidence only.

The driver called the current shared harness through its CLI for launch, doctor, admin pause, public SQL and cleanup. Both driver and harness hashes are in `driver-hashes.json`; `post-cleanup.json` confirms they remained unchanged through the run. Cargo compiled the working-tree authority with `--target-dir` under the run directory. Positive worlds ticked through doctor, then paused for snapshots of 33 public tables. Their populations were 90, 31, 19, 140, 41 and 87 characters. No mind, player, observer, Neo4j writer or paid model ran. These are generation checks, not performance evidence.

## A seed produces the described world

All paths below are under `.local/living/verify/`.

| Seed | Result | Evidence |
| --- | --- | --- |
| `realm`, twice | Pass. 256×256, 256 chunks, two towns, three wild bands, requested worker occupations and linked children, 36 deer and 6 wolves. 26 checks each. | `generation-fix-final-20261004-171138-0-realm/checks.json`, `generation-fix-final-20261004-171138-5-realm/checks.json` |
| `valley` | Pass. 96×96, 36 chunks, 12 people, explicit structures, artifacts and communities. 38 checks. | `generation-fix-final-20261004-171138-1-valley/checks.json` |
| `authored-test` | Pass. Seven authored residents, resolved sheets and parent links. 40 checks. | `generation-fix-final-20261004-171138-2-authored-test/checks.json` |
| `aske-coast` | Pass. Three settlements, 72 authored residents, named buildings and signs, eight resource promises within 24 tiles. 282 checks. | `generation-fix-final-20261004-171138-3-aske-coast/checks.json` |
| `stage3-village` | Pass. Three six-member family bands with camps. 22 checks. | `generation-fix-final-20261004-171138-4-stage3-village/checks.json` |

Each positive child retains `doctor.log`, `pause.log`, table snapshots and action logs. Exact nonempty sheet secrets and top-level secret fields were absent from all exported public tables.

## Repeatability

| Comparison | Result | Evidence |
| --- | --- | --- |
| Terrain | Pass. All 256 rows matched. SHA-256 `761e94d883330bc6544bb3223b31cae961ee93a604bcd71489f79bb3bad60081`. | `generation-fix-final-20261004-171138/repeatability.json` |
| Town and band sites | Pass. Both town sites and all three band sites matched. | Same file |
| Resources | Finding. 1,448 versus 1,445 rows, with 1,442 differing sorted pairs including unmatched rows. | Same file |
| Names, ages and genes | Finding. 90 versus 87 rows, with 90 differing pairs in each comparison. | Same file |
| Animal spawn positions | Finding. All 42 paired rows differed. | Same file |

Reducer RNG draws names, children, genes, resources and animal positions. These differences are observations, not failed terrain guarantees. Sorted pairs do not track individual creatures. Valley homestead placement was not compared twice.

## Authored worlds

| Check | Result | Evidence |
| --- | --- | --- |
| Cached compilation | Pass. Real `author_world.py aske-coast --compile-only`; output matched the committed seed semantically and byte for byte. | `generation-fix-final-20261004-171138/authored.json`, `compile.log`, `compiled-aske-coast.json`, `compile-differences.json` |
| Network isolation | Pass. Zero socket or urllib attempts. | `generation-fix-final-20261004-171138/network.json` |
| Tracked seed inputs | Pass. All original seed-tree hashes were unchanged. | `generation-fix-final-20261004-171138/results.json` |
| Authored parser tests | Pass. All five `seed::tests::` tests passed. | `generation-fix-final-20261004-171138/seed-tests.log` |

Only `author_world.py` and the Aske Coast bible, cast, template and cached sheets were copied. The compiler derives its root from its script path and writes `living/seeds/aske-coast.json` without an output-path option. That copy prevents a write to the tracked seed. Authority sources were not copied.

## Seed format guards

| Check | Result | Evidence |
| --- | --- | --- |
| Parser tests | Pass. All five seed tests ran against the working-tree authority. | `generation-fix-final-20261004-171138/seed-tests.log` |
| Malformed seed publication | Plain pass. A valid JSON seed missing `animals` built, reached publication, failed launch with exit 1, and answered world SQL with 404. | `generation-fix-final-20261004-171138-6-malformed/launch.log`, `publication.json`, `init-state.json`, `guards.json` |
| Panic observation | Confirmed. The database identity matched a server launch record; filtered logs included `seed::seed` and `rust_panic`. | `generation-fix-final-20261004-171138-6-malformed/server-init.log` |
| Cleanup | Pass. Shared cleanup required SQL 404, removed the module copy and kept evidence. | `generation-fix-final-20261004-171138-6-malformed/cleanup.log`, `cleanup.json` |

The guard asserts rejection only. It does not assert a readable error, so it is a plain pass rather than XFAIL. `guards.json` records `KNOWN ISSUE` and points to `docs/LIVING_HANDOFF.md`, "Still open", for the panic and unreadable publication error at `living/authority/src/seed.rs:444`. The shared harness truncates publication stderr and does not retain stdout. No missing-field diagnostic was visible in the retained output; this run does not certify the complete user-facing error. No new product issue was found or fixed.

## Fixes and cleanup

- Removed the shared Python import, Namespace calls and monkey-patching. Launch, doctor, SQL, pause and cleanup now use subprocess CLI calls.
- Used shared `--target-dir` for authority and parser builds. An absolute seed stem lets `build.rs` read the malformed seed under `.local` without copying authority sources or changing tracked inputs.
- Removed duplicate module-copy and post-delete HTTP logic. Shared cleanup confirms SQL 404; the driver checks cleanup status, retained evidence and module removal.
- Added startup preconditions and replaced the historical cleanup example with `<child-run>`.
- Replaced the old validation record with this full run.

All seven child cleanups exited 0 and confirmed SQL 404. `post-cleanup.json` confirms retained evidence, no published child databases, unchanged driver/harness hashes, and the original container still running with its 15:39:13 start time. No shared-harness change is requested for these checks. Complete publication-error retention remains a harness limitation for future readability checks.

## Documentation and compatibility

Consulted the official [documentation entry point](https://spacetimedb.com/docs/), [reducers](https://spacetimedb.com/docs/functions/reducers/), [SQL](https://spacetimedb.com/docs/reference/sql/) and [table performance](https://spacetimedb.com/docs/tables/performance/) guidance before changing the driver. Reducers own mutations; diagnostic SQL reads the public tables after an admin pause. These bounded exports do not add gameplay scans, subscriptions or indexes. Documentation is labeled 2.0.0; manifests and the actual server pin 2.10.1. The [versioned HTTP implementation](https://github.com/clockworklabs/SpacetimeDB/blob/v2.10.1/crates/client-api/src/routes/database.rs) and live calls support the endpoints used here.

`discovery.json` confirms the shared Codex/Mistral Vibe tree and existing Claude Code/Cursor links expose the same frontmatter and executable driver. Syntax, relative links and whitespace checks passed. No adapter change was needed. Runtime discovery and invocation in the other agents were not driven.

## What remains unverified

Fresh paid drafting and its second pass, complete publication-error readability, semantic privacy of authored prose, every numeric seed, repeated valley homestead placement, subscriptions, browser rendering, player actions, learning, later ecology and performance. Use the neighbouring verification skills and performance contract for those claims.

## Seeded lives (2026-11-10, branch `lives-1`)

`generation-lives-0256` on the dev-box, in a worker's own container (`LIVING_STDB_CONTAINER=lives-stdb`, `LIVING_STDB_URL=http://127.0.0.1:3412`, SpacetimeDB 2.14.1), from commit `2108cdc` plus the terrace-garden fix:

- `island` passes 968 of 968 checks. The new checks: hamlets laid out and peopled where the seed's `site: hamlet_village` entries ask (9 of 9); authored sheet relations as `relation` rows (2,348 of 2,348); authored places and the stages of known ways (9 residents, 60 stages, the longest 130.6 m); workplaces an author gave a resident exempt from the in-or-by-settlement check. The `land` digests (tiles `9b403da95bba9407`, heights `0d2f77752781845c`, layout `408df4be210092eb`) equal `floor_preview`'s.
- `authored island` compiles `living/seeds/worlds/island` offline (network blocked) to the committed `island.json`.
- One failure outside this change: "Saltmere memberships" in the second `realm` child. Roborpe (id 21) died within seconds of creation; death removes the membership but keeps the background the check counts. The first `realm` child passed. The check should compare living residents only.
- The previous run (`generation-lives-0247`) failed "open lots stay walkable" on a Kettlebridge garden laid across a terrace step. The planner now keeps gardens and fields off terrace steps (`settle.rs`, `try_lot`). It also failed "original seeds unchanged", because `island.json`'s setting text was edited during that run.
