# X925 floor: the 0-viewer battle and the per-viewer cost at 16 viewers, measured on the Spark

Status: measurement, 2026-11-22, Spark. This answers dev-box's question 1 in docs/BATTLE_DELIVERY_PATHS.md §6 (branch `battle-delivery-doc`, `ac47baea9`): X925 at L0 on a recent build. Nothing here changes main; the helper scripts live on branch `x925-floor`.

## Fixture

- **Build:** main `d0c2f4e85`, clean tree. Authority with Cullet compiled in (`LIVING_SEED=cullet`), rustc 1.99.1, wasm sha256 `0ba0ca698b7b…`. gate-load from the same commit, sha256 `239f59691e58…`.
- **Same code as dev-box's runs:** between dev-box's `a6375a70e` (E2 / VIEWER_FLOOR; their branches were proven identical to it with every switch off) and `d0c2f4e85`, the only authority, rules or scripts change is 3 lines in `lib.rs` (`7a4eb77ed`, `spawn_battle_sides`, which this fixture does not use). `battle_viewers.py` and gate-load are unchanged.
- **The battle:** `living/tools/battle_viewers.py` on Cullet. 200 AI fighters, kept at 200 (`--keep-fighters 1`); 197.3–197.8 alive on average, at least 193, with 2.1–2.7 refills a second. `--keep-alive 0.5 --paused-placement --battle-after-placing --ring 10,10`.
- **Delivery:** the shipped defaults (every delivery law is on by default on main). `--tiers --cues --motion-tables --character-tables --fighter-tables --combat-feed`. `--sides` was not used, and `--fresh-every` was off.
- **Window:** a fresh world per run, a 20 s warm-up, then a 60 s window.
- **Levels:** L0 is `--detail --no-profile` (the server's metrics and thread CPU, no spans). L1 is `--detail --full-log`, added to separate profiling level from host.
- **Runs:** L0 has 3 runs per arm, interleaved 0, 16, 16, 0, 0, 16. L1 has 2 per arm, interleaved 0, 16, 16, 0.
- **Cost:** the `wasm-*` thread's CPU in ms/s (the database thread, as VIEWER_FLOOR measures it). Per viewer = (16-viewer arm − 0-viewer arm) / 16. Uncertainty is the standard error of the difference of the arm means, plus the extreme pairing as a range.
- **Density:** at L1, 114.3–116.0 creatures in sight per viewer sweep (`sweep:seen` / `sweep:viewers`), which is the dense ring (dev-box: 108–128). The engaged census was about 224.

## Host and discipline

- **Server:** a private `slop-x925floor-20261122` (`clockworklabs/spacetime:v2.14.1`, 127.0.0.1:3591, its own volume).
- **Pinning:** the container was pinned to the X925 cores (`--cpuset-cpus 5-9,15-19`) from each run's publish to its end, and moved back to 0-4,10-14 between runs. In every 1-second sample of every window, the database thread ran on an X925 core (CPUs 5–9 and 15–19, all ten used).
- **Side jobs on the A725 cores:** the driver, the per-second sampler, `battle_viewers.py` and gate-load all ran under `taskset -c 0-4,10-14`. The build ran before the series, through `build-slot` on the A725 cores. Nothing was built during the series.
- **Locks:** `~/slop-mq/battle.lock` was taken first, with nothing else held, and kept across each plan. The wait was 09:46–14:00, behind heed-e4's plan2. The L0 series ran 14:00–14:10 and the L1 series 14:11–14:19. Each run started only with the merge lock free, load1 < 4, MemAvailable ≥ 40 GB and disk ≥ 45 GB. Each `battle_viewers.py` ran under `flock -s ~/slop-mq/trial-activity.lock`.
- **Validity:** load1 at the start was 1.1–3.7. In the window the median was 3.0–3.6 and the maximum 3.1–3.96 (the redo threshold is 8). No redo. The viewers suffered no deaths.

## Results

### L0 (uninstrumented), 3 runs per arm

| Arm | DB thread ms/s: mean of runs (range) | Per-second DB ms/s: mean / p50 / p95 (mean over runs) | Tick reducer ms/s | Ticks/s | Per-tick ms p50 | Ticks over 10 ms | Ticks over 25 ms |
|---|---:|---|---:|---:|---:|---:|---:|
| 0 viewers | **294.9** (289.4–303.8), sd 7.8 | 294.3 / 293.3 / 326.6 | 286.8 (281.6–295.1) | 59.98–60.01 | 3.8–4.3 | 0.22–0.36% | 0 |
| 16 viewers, 10 m ring | **442.7** (439.4–444.4), sd 2.8 | 441.8 / 443.3 / 483.7 | 428.9 (425.8–430.5) | 59.73–59.92 | 7.4–7.5 | 7.2–7.5% | 0 |

- **Per viewer (L0): 9.24 ± 0.30 ms/s** (standard error; range 8.47–9.69). Tick reducer alone: 8.88 ± 0.28.
- **What the 16 viewers add, besides the tick:**
  - subscription evaluation (`tick` `Update`): 10.9–11.4 ms/s;
  - views: 8.4–9.3;
  - `human_move`: 2.2–2.3;
  - `admin_set_vitals`: 0.6–0.8 (2.7–3.3 heals a second).
- **Per-second minimum ticks:** 58.9–59.9 in the 0-viewer arm, 58.0 in the 16-viewer arm.
- **The per-tick figures** come from the server's `spacetime_reducer_plus_query_duration_sec` histogram. Its buckets are 5, 10, 25 and 50 ms, so p95 and p99 are not resolvable at L0. At 0 viewers, p95 lies between 5 and 10 ms. At 16 viewers it lies between 10 and 25 ms. No tick in any run took over 25 ms.

### L1 (`--full-log`), 2 runs per arm, the same build

| Arm | DB thread ms/s (range) | Per-second DB ms/s: mean / p50 / p95 | Ticks/s | Ticks over 10 ms |
|---|---:|---|---:|---:|
| 0 viewers | 321.5 (318.4–324.5) | 320.9 / 320 / 346 | 59.92–59.96 | 0.6% |
| 16 viewers | 458.4 (455.2–461.6) | 458.1 / 457 / 500 | 59.66–59.75 | 9.9–10.0% |

- **Per viewer (L1):** 8.56 ± 0.28 ms/s (range 8.17–8.95).
- **Per pair (L1):** 74.3 µs/s per (viewer, creature in sight), at 115 in sight.
- **Profiling on X925** adds about 27 ms/s to the 0-viewer battle and about 16 to the 16-viewer arm. The per-viewer difference between L1 and L0, −0.68 ± 0.41, is indistinguishable from 0. Unlike dev-box, X925's 0-viewer arm does not run higher at L0 than at L1.

## Comparison

| Quantity | VIEWER_FLOOR's X925 (scaled) | dev-box, same code | X925 measured here |
|---|---:|---:|---:|
| R, 0-viewer sustained battle, L0 | – | 377.6 (370–392) | **294.9** (289–304) |
| R, L1 | 338 (`1511d5e8`, battle-laws) | 361.9 (VF) / 371.5 (E2) | 321.5 (318–325) |
| R ratio, X925/dev-box | 0.91–0.93 | – | **0.78** (L0), 0.87–0.89 (L1) |
| Per viewer, 16 viewers on the 10 m ring, as shipped, L1 | 11.6–14.0 (`1511d5e8`) | 11.08 (E2 `b-off`, 128 in sight) | **8.56** (115 in sight) |
| Per viewer, L0 | – | not measured as shipped (VF: L1 is about 0.5 over L0, so ≈10.6) | **9.24** |
| Per-viewer ratio, X925/dev-box | **1.16** (1.05–1.26) | – | **0.77** per viewer at L1; **0.86** per pair (74.3 against 86.6 µs/s); ≈0.87 at L0 against dev-box's estimated 10.6 |
| Per-viewer budget at 216, B / 216, L0 | 1.21 in X925 terms, 1.05 in dev-box terms | 1.03 | **1.41** (1.37–1.44) in X925 terms; 1.62–1.83 in dev-box terms |

**Why VIEWER_FLOOR's "X925 dearer per viewer" does not hold.** Its X925 per-viewer figure came from battle-laws at `1511d5e8`. That build had neither the fighter copy table (`fighter_tables_on`) nor the combat feed (`combat_feed_on`). Neither law exists in `1511d5e8`'s `script.rs`, and both exist in `a6375a70e`'s. Dev-box's 11.08 already had both. The 1.16 ratio was therefore comparing delivery paths, not cores.

On the same code, X925 is cheaper than dev-box on both sides:
- the AI battle costs 0.78–0.89 of dev-box's (depending on level);
- each viewer costs 0.77–0.87.

**The gate, by VIEWER_FLOOR §7.2's method with these inputs (an estimate).** Take the playable case: plausible cuts, attention at 16, the game's views. Dev-box's f is 2.41 ms/s per viewer at contract density. On X925 that is ×0.77–0.87 = 1.86–2.10. Then N = 305 / f ≈ **145–164 viewers at 60 Hz on X925**, against VIEWER_FLOOR's 93 (86–103). Two caveats:
- the ratio is taken on the dense ring at 16 viewers, as shipped, and f comes from contract density on the `viewer-floor` branch (VIEWER_FLOOR did the same);
- the L0 ratio rests on dev-box's L0 per-viewer figure, which is estimated, not measured.

216 on X925 still needs f ≤ 1.41 ms/s per viewer in X925 terms, about 1.62–1.83 in dev-box terms.

**Fighters at 10 Hz on X925** were not measured at L0. VIEWER_FLOOR's −17% applied to 294.9 gives R ≈ 245, so B ≈ 355 and about 1.64 ms/s per viewer at 216 (estimate).

## Not measured / caveats

- **Dev-box's main-as-shipped 16-viewer arm at L0.** The L0 ratio uses VF's −0.5 L1 inflation. Rerunning dev-box at `d0c2f4e85`, L0, 0 and 16 viewers on this fixture would give the ratio on identical code and level.
- **Tick p95 and p99 at L0** cannot be resolved below the server histogram's bucket edges (above).
- **Creatures in sight at L0:** no counters at L0. L1's 114–116 is taken as the L0 density, since it is the same fixture.
- **Run count:** 3 runs per arm at L0 and 2 at L1. The spread was small (16-viewer sd 2.8 ms/s, 0-viewer sd 7.8), so no extra runs were added.
- **Host load** includes the run's own client processes on the A725 cores (gate-load with 16 connections, the keeper, the keep-alive and the sampler). Load was 1.1 when the first run started and about 3.3 in its window.

## Evidence

Archived as `~/slop-evidence/x925-floor-20261122.tar.zst`, with its `.sha256`. It holds:
- `runs/<run>/`: `battle-viewers.json`, `v<n>/{result,metrics,threads}.json`, `load.log`, `samples.jsonl` (per-second thread CPU, core and tick metrics), `procs-*.txt`, `cmd.json`, `series-run.json`, and the L1 `module.log`;
- `series.log`;
- `rollup.json` (L0) and `rollup-l1.json`;
- `tick-shares.txt`;
- `replica-logs/` (every replica's module log);
- the scripts `series.py`, `sampler.py`, `analyze.py`, `build.sh` and `smoke.sh`, with `build.log`, `commit.txt` and `artifacts.sha256`;
- the smoke run (`smoke/`, on the A725 cores, functional only);
- the measured wasm.
