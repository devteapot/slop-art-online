# Combat phase: where a dense battle's tick goes, and a plan for 60 Hz with players watching

Status: diagnosis and plan, 2026-11-20, branch `combat-phase` (Spark), cut from `origin/main` `0e310415`. Nothing here changes behaviour. The branch adds profiling spans and counters that run only while profiling with the `profile_detail` law, plus measurement tooling. The fixes below are proposals; each needs its own branch, and the ones marked **law** also need the owner's separate approval.

The [performance contract](PERFORMANCE_CONTRACT.md) asks for 200 local fighters at 60 Hz with players watching (immediate gate: 216 characters for 30 minutes). This note answers two questions on the agreed fixture: (a) what the AI-only battle costs, span by span, and whether that work is per fighter or per pair; (b) what the viewers add, per viewer and per pair. It then orders the fixes.

## In short

- **(a) Without viewers the battle is not the blocker.** On a fast core (X925) the AI-only tick holds 60 ticks/s.
  - Uninstrumented it uses 208–214 ms of a 1,000 ms second (3.5–3.7 ms a tick; two pinned runs each of main and this branch).
  - With profiling spans it uses 240–270 ms/s: tick p50 3.6–4.2 ms, p99 8–10 ms, at most 5 late slots a minute.
  - The fighters' 15 Hz evaluations are the largest part (57% with spans). Their cost is per fighter: 61–70 µs an evaluation at about 142 engaged fighters and 69–72 µs at about 70. Nothing measured grows as fighters squared at this density. The scans of the crowd (scenes, nearest target) cost about the same per call with 48 or 84 creatures in a scene, and a blow has about 25 onlookers with 70 or 140 fighters. The tick is about 1.5 ms per engaged fighter-second uninstrumented (1.8 with spans). The fight thins without refills (about 190 → 100 engaged over the window). At a sustained 200 the tick body would be about 300 ms/s uninstrumented.
- **(b) The viewers are the blocker, and their cost goes by (viewer × creature in sight) pairs.** At 16 viewers on the 10 m ring the world still runs at 59 ticks/s, but with 56–99 late slots a minute and a tick p99 of 11–13 ms. Each viewer adds about 12.4 ms/s to the database thread. That splits into views 6.7, the whole call's remainder (commit, read sets, subscription evaluation) 2.2, sweeps 1.7, frames 1.6 and cues 0.2 ms/s. That is about 130 µs a second for each pair. At 216 viewers on the same ring each viewer sees about 160 creatures, about 35,000 pairs. The thread saturates at 1.7–1.9 ticks/s (five pinned runs), with a tick taking about 530 ms: tick WASM 445–459 ms/s (perception sweeps 275), views 302–313 ms/s, and about 200 ms/s of the remaining overhead. Every reducer, including the keep-alive fixture's `admin_set_vitals`, waits 240–320 ms behind a tick. 16–30 viewers die in each window despite the keep-alive.
- **Step 2, the exact sweep fixes, measured** ([results](#step-2-results-exact-sweep-fixes), branch `sweep-exact`): a sweep at 216 viewers on the 10 m ring costs 574–634 µs against 689–711 (8–19% less), on the far ring 3–9% less, and no measurable change at 16 viewers. What players and minds perceive is unchanged, checked in the same tick for every sweep. The expected 30–45% rested on a misreading of hearing's cost.
- **The gap is about 15–20× per pair.** To fit 216 viewers and 200 fighters at 60 Hz, the per-viewer side has about 300–360 ms/s. That is roughly 7–10 µs a pair-second against about 130 today. The built table delivery (dev-box's `seen_body_copy` and `seen_character_copy`) removes about a third of the view cost. Converting the remaining views and making the sweep exact-cheaper might reach 3–4×. The rest needs fewer pairs or fewer refreshes, and every such option changes what players perceive or when, so it is a **law** for the owner.

## Fixture and method

**Host and server.** Spark (GB10: 10 Cortex-X925 cores at 3.9 GHz, CPUs 5–9 and 15–19; 10 Cortex-A725 cores at 2.8 GHz). Private server `slop-combatphase-20261120`, image `clockworklabs/spacetime:v2.14.1`, 127.0.0.1:3477, its own volume. Module and `gate-load` were built with rustc 1.99.1 (`RUSTUP_TOOLCHAIN=1.99.1`, private target directory, build slot). `base-cullet.wasm` is `origin/main` `0e310415`; `spans-cullet.wasm` is this branch's instrumentation on the same commit. Both have the Cullet seed compiled in (`LIVING_SEED=cullet`).

**Workload** (agreed with dev-box, `~/slop-mq/notes/combat-phase-fixture.md`):
- `living/tools/battle_viewers.py`, a fresh world per run. `spawn_battle` stages 200 AI fighters (or 100) within 7 m of (540.5, 746.5) with the fight graph: attack the nearest person, dodge or block when threatened. About 24 Cullet residents live elsewhere in the world. No mind service and no model calls.
- **Viewers:** 216 or 16 `gate-load` SDK players. Each has its own identity and WebSocket connection, the gate's subscriptions, the near/far tiers and the cues (`--tiers --cues`); every third viewer samples freshness.
- **Placement:** paused while the viewers join and are placed on a ring: 10 m (`--ring 10,10`, the density case) or 26–32 m (clean liveness). The world is unpaused at `ready`. The viewers walk small circles (a new direction every 1.5 s).
- **Keep-alive:** every 0.5 s, `admin_set_vitals` restores each hurt viewer to full health. This is a test fixture through an admin reducer, not a game rule. Liveness is reported as deaths and heals in the window.
- **Arms:** a 0-viewer arm at 200 and at 100 fighters, for the per-viewer subtraction and for scaling. At 16 and 216 viewers, an arm with dev-box's table delivery: laws `motion_tables_on` and `characters_table_on` on, viewers subscribed to `seen_body_copy` and `seen_character_copy` instead of the two views.
- **Timing:** 20 s warm-up, then a 60 s measured window. No observer and no export load. Subscriptions are the gate's set per viewer and nothing else.

**Population and density, declared.** The fight is not sustained: nobody replaces the dead. The engaged-fighter census (`eval:combat_due` × 4 / ticks) falls from about 170–215 to about 100 over a 200-fighter window, a mean of 129–144. In the 100-fighter arm it falls from about 90 to about 50, a mean of 69–74. With viewers on the 10 m ring the census also counts viewers under attack, about 260–290. Each run's census is in table T1. Contract-shaped acceptance needs a keeper that holds 200 (as `battle_diag.py` does on island). This fixture's per-fighter figures are normalized to engaged fighter-seconds.

**Measurement levels.**
- **L0:** profiling off. Server metrics only: the tick's WASM time and whole call, views, subscription evaluation, per-thread CPU. These are the uninstrumented costs.
- **L1:** `set_profile` on. Tick-phase spans and the evaluation spans that always log.
- **L2:** L1 plus `profile_detail=true`: every detail span and counter, including this branch's. That is about 25,000 log lines a second.

Per-call costs come from L2 and are upper bounds. On pinned runs at 0 viewers, the tick WASM was:
- L0: 208–214 ms/s. Main (`base`) gave 213.0 and 214.0, this branch 208.0 and 213.9: with profiling off the instrumentation costs nothing measurable.
- L1: 230–250 ms/s.
- L2: 242–271 ms/s.

At 216 viewers, L0 and L2 gave the same tick rate (1.73–1.86).

**Discipline.**
- Every run held `~/slop-mq/battle.lock`: one acquisition per series, four series.
- Each run started only when `flock -n ~/slop-mq/lock true` succeeded, MemAvailable was at least 40 GB and disk free at least 45 GB. The merge queue held its lock 02:05–02:08, 02:48–03:00 and 03:02–03:07; the series waited.
- Host load is recorded every second of each window (`load.log`) and is shown per run. It ranged from about 1 to 28 from other sessions' work.
- Two or more runs per arm.

**Finding about the host, which affects every Spark measurement.** Where the scheduler puts the database thread changes the tick's cost by up to about 40–50%.
- Unpinned, the uninstrumented AI-only tick took 265–412 ms/s (265 at load 1.7, 370 at load 6, main 371–412 at load 4–16), and L2 took 349 ms/s at load 1.6.
- Pinned to the X925 cores, the same arms took 208–214 (L0) and 242–271 (L2) at load 2–8.
- The clock ratio is 3.9/2.8 = 1.39, consistent with the thread spending time on A725 cores; which core it ran on was not sampled. From 02:32 the container was pinned to the X925 cores (`docker update --cpuset-cpus 5-9,15-19`). The tables use pinned runs. The unpinned ones are kept in T1, marked "any". Earlier Spark tick figures that did not record core placement carry this spread. The contract's reference hardware needs to name core types, not only a vCPU count.

**Logs.** Detail spans log tens of thousands of lines a second. The CLI's `logs -n` tail drops some of them, and the replica's log lands late: 5 s after a window it held a quarter of the window's tick spans. `battle_viewers.py --full-log` now reads the replica's whole module log from the server's data directory. It reads again until the window's tick spans match the server's tick counter (`log_ticks` in each `result.json`; complete in every L1/L2 run). Three runs read before this fix were re-read afterwards from their replicas.

## (a) The AI-only battle

### T2: AI-only spans (0 viewers, L2, pinned; ranges over the runs)

Shares are of the mean `tick` span. Spans nest (`tick.combat` ⊃ `eval.combat` ⊃ `brain.graph` ⊃ `brain.leaf` ⊃ `brain.begin` ⊃ `begin.check`), so shares do not add up. Detail spans add their own cost (L2 against L0 above).

#### AI-only spans, v0-L2 (pinned)

runs: series-20261120-020507/v0-L2-r2, series3-20261120-032451/v0-L2-r1; tick span 252.7 ms/s; engaged fighters (mean) 142.0

| Span | Calls/s | Mean µs | p99 µs | ms/s | Share of tick | µs per engaged fighter-second |
|---|---:|---:|---:|---:|---:|---:|
| `tick` | 59.9–60.0 | 3985.1–4441.9 | 8064–10035 | 239.1–266.2 | 100% | 1779 |
| `tick.combat` | 59.9–60.0 | 2180.8–2588.8 | 3971–5590 | 130.8–155.2 | 57% | 1007 |
| `eval.combat` | 2057.6–2112.6 | 60.6–70.2 | 248–296 | 124.6–148.2 | 54% | 961 |
| `brain.graph` | 2428.1–2458.2 | 48.8–54.5 | 235–261 | 118.6–133.9 | 50% | 889 |
| `brain.leaf` | 2656.3–2794.0 | 19.4–20.0 | 181–192 | 51.6–55.8 | 21% | 378 |
| `brain.begin` | 1292.8–1352.2 | 36.9–38.1 | 197–216 | 47.7–51.6 | 20% | 350 |
| `begin.check` | 750.1–786.1 | 33.9–35.3 | 81–94 | 25.4–27.8 | 11% | 187 |
| `begin.start` | 131.1–136.5 | 104.7–113.2 | 208–262 | 14.3–14.8 | 6% | 103 |
| `brain.scene` | 2381.0–2413.3 | 12.1–12.2 | 59–62 | 28.8–29.4 | 12% | 205 |
| `brain.target` | 1812.2–1867.9 | 13.0–13.0 | 26–80 | 23.6–24.2 | 9% | 168 |
| `brain.nearest` | 1699.7–1776.4 | 12.7–13.6 | 25–88 | 22.6–23.2 | 9% | 161 |
| `brain.cond` | 1122.3–1336.3 | 8.8–10.4 | 69–81 | 11.7–11.8 | 5% | 83 |
| `brain.load` | 2428.2–2458.3 | 7.3–8.2 | 38–44 | 17.8–20.2 | 8% | 134 |
| `brain.after` | 2428.1–2458.2 | 10.0–10.5 | 175–192 | 24.2–25.8 | 10% | 176 |
| `after.mind` | 260.4–284.5 | 50.2–51.3 | 368–434 | 13.4–14.3 | 5% | 97 |
| `brain.alerts` | 273.6–415.3 | 11.7–12.6 | 53–60 | 3.2–5.2 | 2% | 30 |
| `brain.noticed` | 49.1–57.4 | 131.3–173.2 | 480–607 | 7.5–8.5 | 3% | 56 |
| `tick.wakes` | 59.9–60.0 | 659.7–684.2 | 2745–3463 | 39.6–41.0 | 16% | 284 |
| `wake.eval.fight` | 217.0–233.6 | 107.5–128.6 | 404–504 | 23.3–30.0 | 11% | 188 |
| `wake.eval.calm` | 41.6–73.6 | 204.9–234.2 | 615–815 | 9.7–15.1 | 5% | 87 |
| `tick.activity` | 54.3–58.9 | 580.2–620.3 | 3368–3640 | 31.5–36.5 | 13% | 240 |
| `act.complete` | 71.1–74.3 | 418.0–506.6 | 2194–2562 | 31.1–36.0 | 13% | 236 |
| `act.apply` | 72.1–77.4 | 236.3–306.2 | 1810–2291 | 18.3–22.1 | 8% | 142 |
| `act.damage` | 29.3–31.1 | 569.0–652.8 | 2512–2871 | 16.7–20.3 | 7% | 130 |
| `fold.blow` | 31.5–33.1 | 291.2–294.8 | 408–449 | 9.3–9.6 | 4% | 67 |
| `act.die` | 1.7–2.3 | 865.2–976.9 | 1400–1459 | 1.7–2.0 | 1% | 13 |
| `perceive.witnessed` | 2.7–4.2 | 692.2–834.3 | 1405–1459 | 2.3–2.9 | 1% | 18 |
| `perceive.request_waking` | 18.1–21.0 | 114.2–180.8 | 999–1075 | 2.1–3.8 | 1% | 21 |
| `perceive.scene_json` | 2.2–4.0 | 893.8–900.9 | 991–1178 | 2.0–3.6 | 1% | 20 |
| `tick.fold` | 59.9–60.0 | 190.6–220.1 | 1109–1231 | 11.4–13.2 | 5% | 87 |
| `fold.flush` | 59.9–60.0 | 158.9–189.3 | 1044–1173 | 9.5–11.4 | 4% | 74 |
| `fold.labels` | 18.0–20.1 | 402.1–429.7 | 948–1115 | 7.2–8.6 | 3% | 56 |
| `fold.write` | 18.0–20.1 | 70.0–76.3 | 317–357 | 1.3–1.5 | 1% | 10 |
| `tick.slots` | 58.8–59.1 | 163.6–216.7 | 688–790 | 9.7–12.7 | 4% | 79 |
| `eval.slot.calm` | 26.4–40.2 | 238.7–246.4 | 609–738 | 6.3–9.9 | 3% | 57 |
| `eval.slot.fight` | 39.9–44.5 | 62.3–68.3 | 230–257 | 2.5–3.0 | 1% | 19 |
| `tick.motion` | 59.9–60.0 | 155.9–169.9 | 576–644 | 9.3–10.2 | 4% | 69 |
| `tick.perception` | 1.8–9.9 | 11.2–35.1 | 104–107 | 0.1–0.1 | 0% | 1 |
| `tick.frames` | 59.9–60.0 | 16.5–21.3 | 28–37 | 1.0–1.3 | 0% | 8 |
| `tick.cues` | 59.9–60.0 | 7.4–9.6 | 14–19 | 0.4–0.6 | 0% | 4 |
| `tick.missiles` | 28.5–46.5 | 1.4–1.6 | 3–3 | 0.0–0.1 | 0% | 0 |

#### AI-only spans, v0-f100-L2 (pinned)

runs: series-20261120-020507/v0-f100-L2-r2, series3-20261120-032451/v0-f100-L2-r1; tick span 151.9 ms/s; engaged fighters (mean) 69.65

| Span | Calls/s | Mean µs | p99 µs | ms/s | Share of tick | µs per engaged fighter-second |
|---|---:|---:|---:|---:|---:|---:|
| `tick` | 60.0–60.0 | 2470.5–2593.4 | 5331–6688 | 148.2–155.6 | 100% | 2181 |
| `tick.combat` | 60.0–60.0 | 1235.8–1289.8 | 2420–3157 | 74.1–77.4 | 50% | 1088 |
| `eval.combat` | 1030.5–1031.8 | 68.7–71.5 | 279–321 | 70.8–73.7 | 48% | 1037 |
| `brain.graph` | 1271.8–1279.8 | 55.3–58.0 | 254–284 | 70.8–73.7 | 48% | 1038 |
| `brain.leaf` | 1531.3–1541.4 | 20.1–21.3 | 198–205 | 30.7–32.9 | 21% | 457 |
| `brain.begin` | 744.9–762.0 | 38.0–39.9 | 220–236 | 28.3–30.4 | 19% | 421 |
| `begin.check` | 392.1–422.2 | 38.8–40.1 | 103–123 | 15.2–16.9 | 11% | 231 |
| `begin.start` | 76.9–80.2 | 100.1–104.6 | 221–293 | 8.0–8.1 | 5% | 115 |
| `brain.scene` | 1250.6–1258.6 | 11.2–11.7 | 81–83 | 14.2–14.6 | 9% | 207 |
| `brain.target` | 877.6–904.7 | 11.4–11.5 | 65–80 | 10.0–10.4 | 7% | 147 |
| `brain.nearest` | 861.9–895.1 | 11.1–11.1 | 64–80 | 9.6–10.0 | 6% | 140 |
| `brain.cond` | 823.6–855.3 | 6.7–7.0 | 70–71 | 5.7–5.8 | 4% | 83 |
| `brain.load` | 1271.9–1279.9 | 8.8–8.9 | 45–47 | 11.3–11.4 | 7% | 163 |
| `brain.after` | 1271.8–1279.8 | 12.5–12.9 | 189–198 | 16.0–16.4 | 11% | 233 |
| `after.mind` | 196.3–219.4 | 46.3–49.9 | 341–345 | 9.8–10.1 | 7% | 143 |
| `brain.alerts` | 299.9–312.8 | 12.2–13.5 | 59–69 | 3.8–4.1 | 3% | 56 |
| `brain.noticed` | 58.1–58.8 | 101.9–107.0 | 380–434 | 6.0–6.2 | 4% | 88 |
| `tick.wakes` | 60.0–60.0 | 479.9–484.8 | 2338–2921 | 28.8–29.1 | 19% | 415 |
| `wake.eval.fight` | 111.9–115.9 | 127.2–140.3 | 449–551 | 14.7–15.7 | 10% | 219 |
| `wake.eval.calm` | 67.1–73.9 | 176.4–183.2 | 511–556 | 12.3–13.0 | 8% | 182 |
| `tick.activity` | 57.8–58.1 | 325.4–362.0 | 2559–2910 | 18.9–20.9 | 13% | 286 |
| `act.complete` | 44.4–46.5 | 396.9–460.4 | 2336–2545 | 18.5–20.5 | 13% | 280 |
| `act.apply` | 44.6–47.5 | 215.2–262.8 | 2109–2219 | 10.2–11.7 | 7% | 158 |
| `act.damage` | 14.2–15.8 | 642.3–682.5 | 2502–2904 | 9.1–10.8 | 7% | 143 |
| `fold.blow` | 15.4–16.2 | 281.5–289.3 | 371–416 | 4.3–4.7 | 3% | 65 |
| `act.die` | 0.9–1.2 | 964.8–987.7 | 1426–1688 | 0.9–1.1 | 1% | 15 |
| `perceive.witnessed` | 1.8–2.5 | 739.4–834.5 | 1314–1353 | 1.5–1.8 | 1% | 24 |
| `perceive.request_waking` | 9.9–10.3 | 205.8–245.0 | 994–1066 | 2.0–2.5 | 2% | 33 |
| `perceive.scene_json` | 2.3–2.7 | 875.5–879.0 | 965–1206 | 2.0–2.4 | 1% | 31 |
| `tick.fold` | 60.0–60.0 | 133.4–133.7 | 630–702 | 8.0–8.0 | 5% | 115 |
| `fold.flush` | 60.0–60.0 | 111.1–114.0 | 595–660 | 6.7–6.8 | 4% | 97 |
| `fold.labels` | 19.0–21.7 | 231.0–254.1 | 527–632 | 4.8–5.0 | 3% | 71 |
| `fold.write` | 19.0–21.7 | 49.8–56.8 | 258–275 | 1.1–1.1 | 1% | 16 |
| `tick.slots` | 59.3–59.6 | 171.1–181.0 | 587–697 | 10.1–10.8 | 7% | 150 |
| `eval.slot.calm` | 41.1–41.3 | 207.4–219.0 | 533–624 | 8.5–9.1 | 6% | 126 |
| `eval.slot.fight` | 18.4–19.9 | 72.1–72.5 | 245–272 | 1.3–1.4 | 1% | 20 |
| `tick.motion` | 60.0–60.0 | 104.2–119.3 | 499–578 | 6.2–7.2 | 4% | 96 |
| `tick.perception` | 5.9–15.6 | 4.1–6.3 | 57–60 | 0.0–0.1 | 0% | 1 |
| `tick.frames` | 60.0–60.0 | 17.6–20.1 | 27–42 | 1.1–1.2 | 1% | 16 |
| `tick.cues` | 60.0–60.0 | 6.6–7.5 | 12–18 | 0.4–0.4 | 0% | 6 |
| `tick.missiles` | 44.4–48.4 | 1.5–1.8 | 3–4 | 0.1–0.1 | 0% | 1 |

**Per fighter or per pair.** The 100-fighter arm (69 engaged on average) against the 200-fighter arm (139) answers this.
- **Evaluations:** about the same per evaluation, 69–72 µs → 61–70 µs, so the total goes with fighters.
- **Crowd scans:** `brain.scene` costs 11.7 → 12.1 µs a call with 48 → 84 creatures in a mean full scene, and `brain.target` (which holds `brain.nearest`) 11.5 → 13.0 µs. That is about 0.04 µs per extra creature: fixed cost per evaluation at this density, not per pair. The lazy scene's sight tests (about 49,000 a second) are about 0.6 µs each.
- **Onlookers:** 25.7 → 25.4 per blow, about 12 µs each in `fold.blow`. Folded lines (`fold.labels`, 0.43 ms a line), first sights (`brain.noticed`) and wakes therefore go with events, and events go with fighters.

The spans that do grow with fighters roughly doubled from 69 to 139 engaged fighters, not quadrupled. At this packing (everyone within about 7 m), the sight and field-of-view limits cap how many each one deals with. Pair terms would show only in a wider battle in which everyone still sees everyone.

**What a fighter's evaluation does** (L2, 0 viewers, 200-fighter arm):
- **Begins:** about 1,300 begins a second, of which about 135 start. The rest are refused (about 1,160 a second):
  - "out of breath" about 570 a second, the skill script's pool check (Rhai: `begin.check`, about 34 µs);
  - "still recovering from your last move" about 325 and "you already face it" about 146, the authority's own gates before the script;
  - a dodge not ready yet about 58, yielding about 40.
- **Fixed cost per evaluation:** loading (`brain.load` 7 µs), the after-step (`brain.after` 10 µs) and the sleep check (2 µs) come to about 46 ms/s together.
- **Wakes:** woken evaluations of fighters already on the 15 Hz cadence (`wake.eval.fight`, 217–234 a second at 108–129 µs) cost 23–30 ms/s.

**Spikes.** The tick's p99 is 8–10 ms and its maximum 12–18.5 ms on X925 (L1/L2). The largest single items are a death (`act.die` 1–4 ms with `perceive.witnessed` 0.8–2.5 ms) and a struck victim's first request to think (`perceive.scene_json` 0.9 ms). They land in single ticks.

## (b) What the viewers add

### T3: viewer-side spans and views (L2, pinned)

#### Viewer-side spans, v216r10-L2 (pinned)

runs: series-20261120-020507/v216r10-L2-r2, series3-20261120-032451/v216r10-L2-r1; tick span 451.9 ms/s; engaged fighters (mean) 262.25

| Span | Calls/s | Mean µs | p99 µs | ms/s | Share of tick |
|---|---:|---:|---:|---:|---:|
| `tick` | 1.7–1.8 | 245140.9–265362.1 | 355171–387700 | 444.9–459.0 | 100% |
| `tick.perception` | 1.7–1.8 | 151401.0–161080.1 | 230040–241709 | 274.8–278.6 | 61% |
| `sweep.one` | 370.3–391.3 | 703.6–746.9 | 2902–3006 | 275.3–276.6 | 61% |
| `sweep.setup` | 370.6–391.6 | 20.5–21.8 | 40–45 | 8.0–8.1 | 2% |
| `sight.player_candidates` | 370.6–391.6 | 96.1–96.6 | 206–208 | 35.8–37.6 | 8% |
| `sweep.attention` | 14.5–56.4 | 1.4–1.4 | 4–5 | 0.0–0.1 | 0% |
| `sweep.hear` | 370.6–391.6 | 100.0–114.3 | 306–349 | 39.1–42.4 | 9% |
| `sweep.rows` | 368.6–389.0 | 113.5–115.4 | 617–628 | 42.5–44.2 | 10% |
| `sweep.scene` | 369.1–390.6 | 52.0–59.9 | 149–180 | 20.3–22.1 | 5% |
| `sweep.project` | 370.6–391.6 | 313.0–327.5 | 1941–2014 | 121.4–122.6 | 27% |
| `tick.frames` | 1.7–1.8 | 8134.9–8305.3 | 12154–12669 | 14.4–14.8 | 3% |
| `tick.cues` | 1.7–1.8 | 2745.1–2850.8 | 3074–3114 | 4.9–5.0 | 1% |
| `tick.activity` | 1.7–1.8 | 29797.4–35252.1 | 53682–77149 | 54.1–61.0 | 13% |
| `tick.wakes` | 1.7–1.8 | 24617.1–27239.2 | 38743–39889 | 44.7–47.1 | 10% |
| `tick.fold` | 1.7–1.8 | 21515.0–23557.1 | 45038–60788 | 39.0–40.7 | 9% |
| `tick.combat` | 1.7–1.8 | 5792.7–6193.6 | 8495–9136 | 10.5–10.7 | 2% |
| `tick.slots` | 1.7–1.8 | 414.9–462.0 | 1071–1516 | 0.8–0.8 | 0% |
| `tick.motion` | 1.7–1.8 | 3175.7–3180.8 | 4737–5077 | 5.5–5.8 | 1% |

| View | Calls/s | µs a call (with materializing) | ms/s |
|---|---:|---:|---:|
| `seen_characters` | 369–386 | 388–393 | 144.9–150.0 |
| `seen_bodies_far` | 362–379 | 176–176 | 63.7–66.5 |
| `seen_fighters_far` | 350–369 | 129–132 | 46.1–47.6 |
| `seen_bodies_near` | 356–376 | 43–46 | 16.2–16.4 |
| `my_combat` | 185–189 | 75–84 | 14.1–15.5 |
| `seen_fighters_near` | 334–348 | 31–33 | 10.7–10.9 |
| `my_body` | 307–308 | 9–11 | 2.8–3.4 |
| `seen_doing_far` | 73–85 | 6–8 | 0.5–0.6 |
| `my_vitals` | 32–34 | 11–14 | 0.4–0.5 |
| `my_experience` | 2–2 | 165–172 | 0.4–0.4 |

| Reducer | Calls/s | Mean wait ms |
|---|---:|---:|
| `tick` | 1.7–1.8 | 103.6–111.1 |
| `human_move` | 143.0–143.1 | 285.2–297.2 |
| `admin_set_vitals` | 1.0–1.2 | 239.4–317.1 |
| `join` | 0.3–0.3 | 297.9–350.9 |

Per second (mean of the runs): sweep:viewers 378, sweep:candidates 155937, sweep:seen 60212, visible:add 8438, visible:drop 8227, frames:rows 60869, cues:rows 349, cues:deferred 21882

#### Viewer-side spans, v216r26-L2 (pinned)

runs: series-20261120-020507/v216r26-L2-r2, series3-20261120-032451/v216r26-L2-r1; tick span 433.2 ms/s; engaged fighters (mean) 149.3

| Span | Calls/s | Mean µs | p99 µs | ms/s | Share of tick |
|---|---:|---:|---:|---:|---:|
| `tick` | 11.5–13.0 | 32607.6–38579.8 | 147413–148345 | 424.6–441.8 | 100% |
| `tick.perception` | 11.5–13.0 | 17153.7–20179.8 | 85043–87511 | 223.6–231.1 | 52% |
| `sweep.one` | 999.3–1011.7 | 219.9–230.1 | 1213–1238 | 222.5–230.0 | 52% |
| `sweep.setup` | 999.3–1011.7 | 9.8–10.3 | 27–28 | 9.9–10.3 | 2% |
| `sight.player_candidates` | 999.3–1011.7 | 71.8–73.7 | 181–183 | 72.7–73.7 | 17% |
| `sweep.attention` | 24.1–28.2 | 2.2–2.3 | 5–9 | 0.1–0.1 | 0% |
| `sweep.hear` | 999.3–1011.7 | 18.1–19.1 | 73–77 | 18.4–19.1 | 4% |
| `sweep.rows` | 919.6–921.4 | 28.9–30.0 | 259–262 | 26.7–27.6 | 6% |
| `sweep.scene` | 973.8–989.2 | 8.2–8.5 | 46–47 | 8.1–8.3 | 2% |
| `sweep.project` | 999.3–1011.7 | 78.5–83.0 | 788–807 | 79.4–82.9 | 19% |
| `tick.frames` | 11.5–13.0 | 1554.2–1691.6 | 4294–4314 | 19.4–20.2 | 5% |
| `tick.cues` | 11.5–13.0 | 527.5–566.5 | 1098–1111 | 6.5–6.9 | 2% |
| `tick.activity` | 11.5–13.0 | 4287.7–5023.9 | 26364–27266 | 55.9–57.6 | 13% |
| `tick.wakes` | 11.5–13.0 | 3770.2–4800.4 | 21629–23958 | 49.2–55.1 | 12% |
| `tick.fold` | 11.5–13.0 | 1496.5–1912.7 | 10924–14320 | 19.5–21.9 | 5% |
| `tick.combat` | 11.5–13.0 | 3020.3–3513.4 | 7056–7416 | 39.4–40.3 | 9% |
| `tick.slots` | 11.5–13.0 | 459.8–484.3 | 1050–1286 | 5.5–6.0 | 1% |
| `tick.motion` | 11.5–13.0 | 833.7–947.3 | 2498–2700 | 10.9–10.9 | 3% |

| View | Calls/s | µs a call (with materializing) | ms/s |
|---|---:|---:|---:|
| `seen_characters` | 819–831 | 161–165 | 134.2–135.0 |
| `seen_bodies_far` | 789–797 | 74–76 | 58.6–59.7 |
| `seen_fighters_far` | 526–528 | 55–56 | 29.0–29.7 |
| `my_combat` | 119–129 | 105–109 | 12.9–13.6 |
| `seen_bodies_near` | 476–488 | 23–23 | 11.0–11.3 |
| `my_body` | 323–337 | 10–12 | 3.5–3.8 |
| `seen_fighters_near` | 136–164 | 17–19 | 2.6–2.9 |
| `my_experience` | 11–12 | 150–153 | 1.6–1.9 |
| `seen_doing_far` | 54–67 | 6–7 | 0.3–0.5 |
| `my_vitals` | 27–28 | 12–14 | 0.3–0.4 |

| Reducer | Calls/s | Mean wait ms |
|---|---:|---:|
| `tick` | 11.5–13.1 | 4.2–6.5 |
| `human_move` | 144.3–144.7 | 59.8–68.0 |
| `admin_set_vitals` | 2.2–2.2 | 3.6–5.6 |
| `join` | – | – |

Per second (mean of the runs): sweep:viewers 999, sweep:candidates 301555, sweep:seen 55812, visible:add 4878, visible:drop 4910, frames:rows 57521, cues:rows 2543, cues:deferred 5764

#### Viewer-side spans, v16r10-L2 (pinned)

runs: series2-20261120-024732/v16r10-L2-r1, series2-20261120-024732/v16r10-L2-r2; tick span 331.6 ms/s; engaged fighters (mean) 149.45

| Span | Calls/s | Mean µs | p99 µs | ms/s | Share of tick |
|---|---:|---:|---:|---:|---:|
| `tick` | 58.8–59.0 | 5605.4–5653.0 | 10720–11741 | 330.8–332.3 | 100% |
| `tick.perception` | 58.8–59.0 | 458.0–484.8 | 1589–1700 | 27.0–28.5 | 8% |
| `sweep.one` | 80.0–80.0 | 328.5–346.6 | 1117–1243 | 26.3–27.7 | 8% |
| `sweep.setup` | 80.0–80.0 | 16.4–17.1 | 31–33 | 1.3–1.4 | 0% |
| `sight.player_candidates` | 80.0–80.0 | 45.7–45.7 | 86–96 | 3.7–3.7 | 1% |
| `sweep.attention` | 69.4–69.6 | 2.1–2.2 | 3–3 | 0.1–0.1 | 0% |
| `sweep.hear` | 80.0–80.0 | 55.9–61.4 | 148–152 | 4.5–4.9 | 1% |
| `sweep.rows` | 78.0–79.6 | 35.0–36.9 | 196–221 | 2.7–2.9 | 1% |
| `sweep.scene` | 80.0–80.0 | 32.4–35.8 | 93–98 | 2.6–2.9 | 1% |
| `sweep.project` | 80.0–80.0 | 134.4–139.7 | 695–776 | 10.8–11.2 | 3% |
| `tick.frames` | 58.8–59.0 | 440.2–448.0 | 976–1016 | 26.0–26.3 | 8% |
| `tick.cues` | 58.8–59.0 | 54.2–55.1 | 123–130 | 3.2–3.2 | 1% |
| `tick.activity` | 58.5–58.9 | 706.3–714.6 | 3802–3891 | 41.6–41.8 | 13% |
| `tick.wakes` | 58.8–59.0 | 766.5–782.5 | 3067–4119 | 45.2–46.0 | 14% |
| `tick.fold` | 58.8–59.0 | 269.0–290.3 | 1345–1353 | 15.9–17.1 | 5% |
| `tick.combat` | 58.8–59.0 | 2518.8–2551.7 | 4738–4785 | 148.1–150.6 | 45% |
| `tick.slots` | 58.8–59.0 | 215.5–215.5 | 685–724 | 12.7–12.7 | 4% |
| `tick.motion` | 58.8–59.0 | 186.0–187.3 | 682–715 | 11.0–11.0 | 3% |

| View | Calls/s | µs a call (with materializing) | ms/s |
|---|---:|---:|---:|
| `my_combat` | 183–192 | 166–168 | 30.3–32.3 |
| `seen_bodies_far` | 275–280 | 83–83 | 22.7–23.2 |
| `seen_characters` | 96–100 | 232–234 | 22.2–23.3 |
| `seen_fighters_far` | 241–250 | 69–69 | 16.7–17.3 |
| `my_experience` | 25–27 | 203–207 | 5.2–5.5 |
| `seen_bodies_near` | 90–99 | 42–43 | 3.8–4.2 |
| `seen_fighters_near` | 86–97 | 35–37 | 3.2–3.4 |
| `seen_doing_far` | 51–57 | 9–10 | 0.5 |
| `my_body` | 20–22 | 18–18 | 0.4–0.4 |

| Reducer | Calls/s | Mean wait ms |
|---|---:|---:|
| `tick` | 59.0–59.2 | 0.1–0.1 |
| `human_move` | 10.7–10.8 | 2.5–2.5 |
| `admin_set_vitals` | 2.2–2.3 | 0.1–0.1 |
| `join` | – | – |

Per second (mean of the runs): sweep:viewers 80, sweep:candidates 14464, sweep:seen 6253, visible:add 367, visible:drop 379, frames:rows 25884, cues:rows 702, cues:deferred 0

#### Viewer-side spans, v216r10-tab-L2 (pinned)

runs: series2-20261120-024732/v216r10-tab-L2-r1, series2-20261120-024732/v216r10-tab-L2-r2; tick span 625.4 ms/s; engaged fighters (mean) 283.79999999999995

| Span | Calls/s | Mean µs | p99 µs | ms/s | Share of tick |
|---|---:|---:|---:|---:|---:|
| `tick` | 2.3–2.5 | 249925.1–265425.0 | 379418–389471 | 622.6–628.1 | 100% |
| `tick.perception` | 2.3–2.5 | 158144.8–169888.7 | 250219–257507 | 397.4–398.5 | 64% |
| `sweep.one` | 493.6–531.9 | 743.8–802.3 | 3020–3203 | 395.6–396.0 | 63% |
| `sweep.setup` | 494.5–532.7 | 22.1–23.2 | 43–44 | 11.5–11.8 | 2% |
| `sight.player_candidates` | 494.5–532.7 | 94.8–94.9 | 200–202 | 46.9–50.6 | 8% |
| `sweep.attention` | 31.9–75.1 | 1.4–1.4 | 4–5 | 0.0–0.1 | 0% |
| `sweep.hear` | 494.5–532.6 | 106.0–112.5 | 335–339 | 55.6–56.4 | 9% |
| `sweep.rows` | 492.0–526.8 | 131.6–140.6 | 686–721 | 69.2–69.3 | 11% |
| `sweep.scene` | 493.4–531.7 | 61.0–68.2 | 183–192 | 32.4–33.6 | 5% |
| `sweep.project` | 494.5–532.7 | 321.5–357.8 | 2054–2210 | 171.3–176.9 | 28% |
| `tick.frames` | 2.3–2.5 | 9861.9–10590.2 | 15403–16833 | 24.8–24.8 | 4% |
| `tick.cues` | 2.3–2.5 | 2699.5–2702.3 | 3037–3039 | 6.3–6.8 | 1% |
| `tick.activity` | 2.3–2.5 | 30831.6–32575.2 | 56429–62648 | 75.9–77.5 | 12% |
| `tick.wakes` | 2.3–2.5 | 19156.5–20130.7 | 40831–41700 | 44.6–50.6 | 8% |
| `tick.fold` | 2.3–2.5 | 21284.0–23579.9 | 42547–43928 | 53.5–54.9 | 9% |
| `tick.combat` | 2.3–2.5 | 6357.6–6436.2 | 10077–11211 | 14.8–16.2 | 2% |
| `tick.slots` | 2.3–2.5 | 404.9–440.2 | 1215–1348 | 0.9–1.1 | 0% |
| `tick.motion` | 2.3–2.5 | 2612.4–2681.9 | 4030–4031 | 6.2–6.6 | 1% |

| View | Calls/s | µs a call (with materializing) | ms/s |
|---|---:|---:|---:|
| `seen_fighters_far` | 470–497 | 136–153 | 67.5–71.8 |
| `my_combat` | 266–294 | 129–130 | 34.2–38.1 |
| `seen_fighters_near` | 452–467 | 32–32 | 14.5–15.1 |
| `my_body` | 340–351 | 8–9 | 3.0–3.1 |
| `my_experience` | 4–4 | 156–171 | 0.7–0.7 |
| `seen_doing_far` | 91–94 | 6–6 | 0.5–0.6 |
| `my_vitals` | 40–41 | 10–11 | 0.4–0.5 |

| Reducer | Calls/s | Mean wait ms |
|---|---:|---:|
| `tick` | 2.4–2.5 | 65.1–79.6 |
| `human_move` | 140.7–141.4 | 210.0–225.5 |
| `admin_set_vitals` | 1.7–1.7 | 166.4–172.1 |
| `join` | 0.8–0.9 | 189.0–207.6 |

Per second (mean of the runs): sweep:viewers 516, sweep:candidates 209814, sweep:seen 87402, visible:add 10060, visible:drop 9967, frames:rows 88237, cues:rows 496, cues:deferred 27690

#### Viewer-side spans, v16r10-tab-L2 (pinned)

runs: series2-20261120-024732/v16r10-tab-L2-r1, series2-20261120-024732/v16r10-tab-L2-r2; tick span 352.3 ms/s; engaged fighters (mean) 156.1

| Span | Calls/s | Mean µs | p99 µs | ms/s | Share of tick |
|---|---:|---:|---:|---:|---:|
| `tick` | 58.4–59.1 | 5957.1–6041.9 | 11790–13392 | 351.9–352.6 | 100% |
| `tick.perception` | 58.4–59.1 | 557.3–576.7 | 1913–2089 | 32.9–33.7 | 9% |
| `sweep.one` | 80.0–80.0 | 403.2–411.5 | 1421–1458 | 32.3–32.9 | 9% |
| `sweep.setup` | 80.0–80.0 | 18.0–18.6 | 33–35 | 1.4–1.5 | 0% |
| `sight.player_candidates` | 80.0–80.0 | 46.4–49.3 | 91–106 | 3.7–3.9 | 1% |
| `sweep.attention` | 69.4–70.9 | 1.8–2.1 | 3–3 | 0.1–0.1 | 0% |
| `sweep.hear` | 80.0–80.0 | 60.8–61.8 | 160–165 | 4.9–4.9 | 1% |
| `sweep.rows` | 79.2–79.5 | 57.8–59.5 | 293–296 | 4.6–4.7 | 1% |
| `sweep.scene` | 80.0–80.0 | 40.7–41.1 | 105–116 | 3.3–3.3 | 1% |
| `sweep.project` | 80.0–80.0 | 169.9–172.8 | 899–907 | 13.6–13.8 | 4% |
| `tick.frames` | 58.4–59.1 | 523.2–535.2 | 1125–1197 | 30.9–31.2 | 9% |
| `tick.cues` | 58.4–59.1 | 54.5–58.6 | 132–143 | 3.2–3.4 | 1% |
| `tick.activity` | 57.6–57.9 | 767.1–789.7 | 4316–4599 | 44.2–45.7 | 13% |
| `tick.wakes` | 58.3–59.1 | 706.7–830.9 | 3705–4340 | 41.7–48.5 | 13% |
| `tick.fold` | 58.3–59.1 | 295.4–332.5 | 1444–1471 | 17.4–19.4 | 5% |
| `tick.combat` | 58.4–59.1 | 2552.2–2748.6 | 4713–4902 | 149.0–162.4 | 44% |
| `tick.slots` | 58.3–58.9 | 196.1–227.7 | 695–777 | 11.5–13.3 | 4% |
| `tick.motion` | 58.3–59.1 | 169.0–188.7 | 593–701 | 10.0–11.0 | 3% |

| View | Calls/s | µs a call (with materializing) | ms/s |
|---|---:|---:|---:|
| `my_combat` | 203–206 | 181–189 | 36.7–38.9 |
| `seen_fighters_far` | 265–268 | 76–81 | 20.2–21.8 |
| `my_experience` | 29–33 | 202–207 | 6.1–6.7 |
| `seen_fighters_near` | 97–101 | 38–40 | 3.9–3.9 |
| `seen_doing_far` | 60–65 | 9–9 | 0.6–0.6 |
| `my_body` | 21–24 | 17–19 | 0.4–0.4 |

| Reducer | Calls/s | Mean wait ms |
|---|---:|---:|
| `tick` | 58.5–59.3 | 0.1–0.2 |
| `human_move` | 10.8–10.8 | 2.2–2.2 |
| `admin_set_vitals` | 2.5–2.5 | 0.0–0.1 |
| `join` | – | – |

Per second (mean of the runs): sweep:viewers 80, sweep:candidates 14759, sweep:seen 7635, visible:add 416, visible:drop 427, frames:rows 29439, cues:rows 799, cues:deferred 0

**At 216 viewers on the 10 m ring the thread is saturated.**
- **Rate:** the tick runs 1.7–1.9 times a second. Its whole call is 952–966 ms of every second: tick WASM 445–459, views 302–313, and about 200 ms/s more of commit, read-set upkeep and subscription evaluation (Update CPU about 45 of it).
- **Sweeps:** because a tick takes longer than 200 ms, every viewer's sweep is due in every tick. That is 216 sweeps a tick at about 735 µs each, 275 ms/s. One sweep:

  | Part | µs |
  | --- | ---: |
  | Projections (`sweep.project`; about 53 re-projections at about 6 µs, about 23 of them for newcomers) | 326 |
  | Perceived-row churn (`sweep.rows`; about 23 entering and 23 leaving sight a sweep, rows and copies) | 118 |
  | Hearing (`sweep.hear`; a second gather of the crowd within hearing range and a second senses read) | 109 |
  | Sight tests (`sight.player_candidates`; about 420 candidates, about 160 seen) | 98 |
  | Frames' scene (`sweep.scene`) | 56 |
  | Setup | 21 |

- **Views:** per call (with materializing), `seen_characters` costs 391 µs (about 200 rows), `seen_bodies_far` 177, `seen_fighters_far` 128, `my_combat` 83.
- **Queueing:** on average `human_move` waits 285–297 ms, `admin_set_vitals` 239–317 ms and `join` 298–351 ms. The keep-alive therefore heals late, and 16–30 viewers die in each window.

**On the 26–32 m ring** the tick runs 11.5–13.1 times a second with no viewer deaths (130–132 heals a window):
- Each sweep sees about 57 creatures with 5 in and 5 out. A sweep costs 220–230 µs (11 re-projections).
- The whole call is still 872–888 ms/s: WASM 428–444, views 256–257 and about 190 ms/s more.

**Per viewer at contract cadence (16 viewers, 10 m ring, about 59 ticks/s).** This arm shows the per-viewer cost at 60 Hz, which the saturated 216 arm cannot. Against the 0-viewer arm (L2, pinned) the 16 viewers add about 230 ms/s to the whole call. Some of that is fighting: viewers are attacked, and the engaged census rises from about 139 to about 149. The viewer-side terms:

| Per viewer (16-viewer arm, L2) | ms/s per viewer | µs/s per (viewer, creature in sight) pair, about 94 in sight |
| --- | ---: | ---: |
| Views (rebuilds with materializing) | 6.7 | 71 |
| Whole call's remainder: commit, read sets, subscription evaluation (Update CPU 0.6 of it) | 2.2 | 23 |
| Sweeps (5 a second at about 347 µs) | 1.7 | 18 |
| Frames (copies at frame cadence) | 1.6 | 17 |
| Cues | 0.2 | 2 |
| **Total** | **about 12.4** | **about 130** |

The rest of the about 230 ms/s (about 14.4 per viewer) is the extra fighting.

Extrapolated linearly, 216 viewers with about 160 in sight each (about 35,000 pairs) would need about 4.5 s of database thread a second at 60 Hz. The saturated 216 arm is not a per-second measure of this: with 530 ms ticks, every sweep and most of each viewer's views run in every tick.

**Dev-box's table delivery, measured here.** These are laws `motion_tables_on` and `characters_table_on` on, with clients on `seen_body_copy` and `seen_character_copy` (16 viewers: 2 runs; 216 viewers: 2 runs at host load 9–28).
- **16 viewers:** views fall from 108 to 70 ms/s. `seen_characters` and the body views are gone; `my_combat` (37 ms/s) and `seen_fighters_far` (20 ms/s) remain. Tick WASM rises by about 21 ms/s for the mirror writes and copies; a sweep rises from 328–347 to 403–411 µs. Subscription bytes rise about 40% (as dev-box measured). The whole call falls 20 ms/s, about 1.3 ms/s per viewer.
- **216 viewers:** ticks rise from 1.77 to 2.43 a second (+37%) and views fall to about 125 ms/s. Each tick still spends about 160 ms in 216 sweeps. Viewer deaths rise to 54–63 a window: the faster world fights more, and the keep-alive still waits behind ticks.

## Ranked costs

Shares are of the AI-only tick (253 ms/s with detail spans, 0 viewers) or of the 216-viewer whole call (about 960 ms/s), on pinned runs. "Unit" says what the cost grows with: F is fighters, E is events (proportional to F), P is pairs of fighters near each other, V is viewers, and V×C is viewers times creatures in each one's sight.

| # | Cost | Where measured | ms/s | Share | Per call | Unit | Owner |
| ---: | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | Per-viewer view rebuilds (`seen_characters`, `seen_bodies_*`, `seen_fighters_*`, `my_combat`) | 216 r10 | 307–310 | 32% | 391 / 177 / 128 / 83 µs | V×C × refresh rate | dev-box |
| 2 | Perception sweeps (`tick.perception`) | 216 r10 | 275 | 29% | 735 µs a sweep (about 4.6 µs a seen pair) | V×C at 5 Hz | Spark (tick body); dev-box's frames read its output |
| 3 | Whole call's remainder: commit, read-set upkeep (2.14.1 walks every view's read set per refresh), subscription evaluation | 216 r10 | about 200 | 21% | – | V×C writes | shared; needs a host profile to split |
| 4 | Fighters' 15 Hz evaluations (`tick.combat`) | 0 viewers | 131–155 | 57% | 61–70 µs an evaluation; a begin 37 µs; the Rhai check, where it runs, 34 µs | F | Spark |
| 5 | Wakes (`tick.wakes`: fighters woken on top of their cadence 23–30, others 10–15) | 0 viewers | 40–41 | 16% | 108–129 / 205–234 µs | E (onlookers about 25 a blow) | Spark |
| 6 | Completions and damage (`tick.activity`: `act.complete` 418–507 µs, `act.damage` 569–653 µs, `fold.blow` 291–295 µs) | 0 viewers | 32–37 | 13% | – | E | Spark |
| 7 | Frames (`tick.frames`, copy writes) and cues | 16 r10 | 26 + 3 (1.8 ms/s per viewer) | – | 450 µs a tick | V×C | dev-box |
| 8 | Folded onlooker lines (`tick.fold`: `fold.labels` 0.40–0.43 ms a line) | 0 viewers | 11–13 | 5% | – | E × participants | Spark |
| 9 | Slot evaluations (residents, 1 Hz) | 0 viewers | 10–13 | 4% | 239–246 µs calm | population | Spark |
| 10 | Motion (`tick.motion`) | 0 viewers | 9–10 | 4% | – | moving bodies | Spark |
| 11 | Reducer queueing behind long ticks (mean wait: `human_move` 285–297 ms, `admin_set_vitals` 239–317 ms) | 216 r10 | – | – | – | a symptom of 1–3 | – |

## Plan

**Budget.** The database thread has 1,000 ms a second. To leave room for reducers and spikes, aim for a whole tick call of at most about 600 ms/s (10 ms a tick). The AI tick body at a sustained 200 fighters is about 300 ms/s uninstrumented, and exact trims (steps 8–11) could bring it to about 240. That leaves about 300–360 ms/s for everything per viewer: about 1.4–1.7 ms/s per viewer at 216, or about 7–10 µs/s per pair at 160–200 in sight, against about 130 today. The steps below are ordered by expected gain on that gap. Each is measured on this fixture (0, 16 and 216 viewers, both rings, pinned) before the next.

### Delivery: per-viewer views to tables (dev-box)

1. **Switch on the built table paths** (`motion_tables_on`, `characters_table_on`), after their rollout gates. Measured here: −38 ms/s of views at 16 viewers, about −1.3 ms/s per viewer net, and +37% ticks at 216.
   - Delivery only; what each player perceives is unchanged (dev-box's isolation and equality checks).
2. **`my_combat` as an event table filtered per viewer.** This is the cue pattern: `combat_seen` stays private for reconnect and the minds, and a public event table carries each new row to its viewer.
   - Event tables exist in the pinned 2.14.1 (`#[table(..., event)]`, used by the cues). Views cannot read them, and they are delivered once at commit ([event tables](https://spacetimedb.com/docs/tables/event-tables/)).
   - A reconnecting client then needs the current rows another way: one read of `my_combat` at subscribe, or keep the view for the first subscription.
   - Expected: about −37 ms/s at 16 viewers, the largest view left after step 1. Delivery only.
3. **`seen_fighters_*` and `seen_doing_*` as row-level-security copy tables**, like `seen_body_copy`. Expected: about −24 ms/s at 16 viewers. Delivery only.
4. **Then measure the remainder** (#3 in the ranking). Fewer views should shrink the read-set walk in 2.14.1. Take a host-side profile (`perf` on the server's database thread, our own container) to split commit, read sets and subscription evaluation.

   **Expected after 1–3:** views from about 6.7 to about 0.5 ms/s per viewer (delta rows only, about 1 µs a row at the cue tables' measured rate). Copies and mirrors add some tick WASM: about +21 ms/s at 16 viewers in step 1. Total per viewer from about 12.4 to about 7 ms/s, about 2×.

### Sweeps: exact, cheaper per sweep (Spark, tick body; coordinate with dev-box in `perception.rs`)

5. **Hear from the sweep's own gather.**
   - `hear` gathers the crowd again within hearing range and reads the senses a second time, only to keep the creatures not seen.
   - When the hearing radius is within the sight gather (or the gather is widened to the larger of the two), filtering the one list gives the same set.
   - Expected: about −90 µs of 735 a sweep at the 10 m ring (−12%), more on the far ring (110 of 227, about −45%).
6. **Projection by memo.** About 6 µs a re-projection, about 53 a sweep at the 10 m ring, of which about 23 are newcomers. Memoize the projection on its inputs (the law's input, health band, stage, knowledge epoch) per tick across viewers: many viewers project the same target with the same input in the same tick. Exact by construction, checkable with the existing `regard_cache_check`. Expected: a large share of `sweep.project` (326 µs).
7. **Row churn.** Sight changes as viewers turn and fighters move: about 23 in and 23 out a sweep on the 10 m ring, 118 µs. Batch the perceived-row and copy writes, and keep a creature's copy across a short absence instead of a delete and an insert. The second is not exact for what a client sees (a copy lingers), so it is a **law**.

   **Expected from 5–6 (exact):** about 30–45% of the sweep. Sweeps go from about 1.7 to about 1.0 ms/s per viewer. **Measured** ([Step 2 results](#step-2-results-exact-sweep-fixes)): 8–19% of the sweep at 216 viewers on the 10 m ring, 3–9% on the far ring, none measurable at 16. Hearing's second gather was 9 µs, not about 90; the rest of a sweep is mostly its own row reads and writes.

### The AI tick body: exact trims (Spark)

8. **Per-evaluation fixed cost:** load, after and sleep come to about 19 µs an evaluation, about 46 ms/s. Fewer row reads per evaluation (the compiled graph and settled needs read once per tick per character). Expected: −15 to −25 ms/s.
9. **Refused begins:** about 1,150 a second. The skill check's context is built for the whole plan, then the script refuses for breath.
   - First split `begin.check` into context building and the Rhai run (one more detail span).
   - Then either build only the fields the plan reads before the pool test, or memoize a refusal on the exact fields the check read. The memo applies only when the plan does not read `roll`.
   - Expected: up to −25 ms/s.
10. **One sight answer per pair per tick.** Scenes, fold onlookers and the sweep's candidates each run `sees` for the same pair in the same tick. Memoize per tick on (observer, target), dropping an entry when either body, the observer's senses or the light on the target change in the tick (a check law compares it with a fresh test, as the other exact paths have). Expected: part of 29 + 9 ms/s at 0 viewers, plus part of the sweep's 98 µs.
11. **Folded lines' labels:** `fold.labels` at 0.43 ms a line. Memoize labels per (observer, target, knowledge epoch) within the tick. Expected: −5 to −8 ms/s.

    **Expected from 8–11:** about 60–80 ms/s of the AI tick body (25–30%). Not needed for AI-only 60 Hz on X925, but it frees budget for viewers.

### What exact work cannot reach: decisions for the owner (each a law, off by default, measured before it is proposed)

Steps 1–11 might bring the per-viewer cost from about 12.4 to about 5–6 ms/s, 2–3×. Without fewer pairs or fewer refreshes, 216 viewers at about 160–200 in sight would still need roughly 1–1.3 s/s. The options, all of which change what players perceive or when:
- **Bounded far tier with crowd rows** (BATTLE_VIEWERS option C): copies only for the nearest and engaged (`NEAR_MAX` 32), and per cell aggregates for the rest of a dense crowd. Pairs per viewer fall from about 160–200 to about 32 plus a few, about 5×.
  - Changes what a player perceives of far fighters. AI perception (scenes, minds) is untouched. That asymmetry is itself a rules question: the same rules for players and AI.
- **Density-following sweep and frame cadence** (option D): far sweeps and far frames slower when many are in sight. Cuts sweeps and copies in proportion, but makes perception later.
- **Bystander wakes for fighters already on the 15 Hz cadence:** leave them to the cadence, up to 50 ms later. About −23 ms/s.
- **The combat cadence itself** (15 Hz): about −45 ms/s at 10 Hz. Changes fighters' reaction timing. Not recommended unless the budget still fails after the rest.

### Order and expected state

| After | Per viewer ms/s (16 r10) | Pair µs/s | AI tick body, sustained 200 (ms/s) | Expected at 216 viewers, 10 m ring |
| --- | ---: | ---: | ---: | --- |
| Today | about 12.4 | about 130 | about 300 | 1.7–1.9 ticks/s (measured) |
| 1 (built, measured) | about 11.2 | about 120 | about 320 | 2.4 ticks/s (measured, loaded host) |
| 1–4 | about 7 | about 75 | about 320 | about 4 ticks/s (estimate) |
| 1–11 | about 5–6 | about 55–65 | about 250 | about 6–8 ticks/s (estimate) |
| + a far tier or cadence law | about 1.5–2 | – | about 250 | toward 60, to be measured |

The estimates assume costs stay proportional to pairs and refreshes. Each step's own measurement replaces its row.

**Measurement for every step.**
- This fixture, pinned to X925, battle lock, two or more runs per arm, L0 for the totals and L2 for the parts.
- Each paired with this note's runs, or rerun against main in the same window.
- Plus a sustained fixture that holds 200 fighters. `spawn_battle` thins to about 100 within the window, so `battle_viewers.py` needs a keeper, as `battle_diag.py` has.
- Liveness stays a result: deaths and heals, and the keep-alive's wait behind ticks.

## Step 2 results: exact sweep fixes

Status: measured, 2026-11-20, branch `sweep-exact` (Spark), cut from `combat-phase` `836a27be` and later merged with `origin/main`. Steps 5 and 6 of the plan, plus the other exact savings the per-viewer sweep's spans showed. Nothing a player or a mind perceives changes, nor when.

**In short.** At 216 viewers on the 10 m ring a sweep costs 574–634 µs against 689–711 on main with combat-phase: 8–19% less. `tick.perception` falls from 273–280 to 244–254 ms/s, and the world runs 1.83–1.99 ticks/s against 1.83. On the 26–32 m ring a sweep costs 204–209 µs against 216–223 (3–9% less). At 16 viewers (one or two sweeps a tick) there is no measurable change. The plan's expected 30–45% is not reached. Its split of a sweep (the [T3 table](#t3-viewer-side-spans-and-views-l2-pinned)) put about 109 µs of hearing in "a second gather of the crowd". Finer spans show that gather costs 8.7 µs at the 10 m ring and 2.5 µs at the far ring. Hearing's cost is reading the viewer's own `heard` rows and writing the changes. Most of what remains in a sweep is likewise row reads and writes that an exact change cannot remove.

### What changed (`perception.rs`, `common.rs`)

- **One gather for sight and hearing.** A sweep gathers once, within the larger of the sight gather and the hearing reach (`common::creatures_near_filed`, unsorted, each creature with the chunk it is filed under). Sight keeps those within its gather whose chunk its own gather covers. Hearing keeps those within hearing, not seen, whose chunk the hearing reach covers. The chunk test is what makes this exact: a body is filed under the chunk where its segment began, so near a chunk edge it can stand in a neighbour that a smaller gather does not visit. Hearing is still told only while the senses have a field, as `heard` does.
- **Hearing matches rows by target** (a map, first row for each target, as the linear search found) instead of a search of the viewer's rows for each sound.
- **A tick's sweeps share** (`Shared`): each creature's health and record read once, and each projection worked out once per target and answer of the law (`project_shared`). A projection is a function of the target's record, health and look and the law's answer alone (`project_as`), and no sweep writes any of these. The memos run only when two or more viewers sweep in the tick (a lone sweep would fill them for no one).
- **The law's input once per kind.** Within a viewer's sweep, a target with no reveal held has nothing revealed. Its input is therefore one of a few (target kind, name known, itself), built once each, and the law's answer and band at each whole metre are asked once per input. `law_band_of` no longer clones its key on a hit. A reveal is read only for a target it holds for (`revealing`, read once a sweep).
- **No health read where the law hides health** (Cullet past `known_within`): the row's fields are the same whatever the health is.
- **An integer hasher for the sweep's own id maps** (`IdHasher`): the kept rows, the previously perceived set, the tick's memos, hearing's maps. Only maps whose order of iteration decides no row's content; at most it orders the deletes of rows leaving sight.
- **The kept sweep projects, then writes.** A projection reads none of the rows the writes touch, so the rows written are as before. Finer detail spans: `sight.gather`, `hear.read`, `rows.out`, `rows.in`, `project.test`, `project.regard`, `project.as`, `project.write`, `project.show`. New counters while profiling: `hear:now|rows|update|insert|delete`, `project:insert|update|same`, `sweep:health_read`, `sweep:dist_read`.

No table, reducer, view, subscription or law changed. The memos are local values in one tick's call. Module memory across transactions is unchanged (`KEPT`, `HEARD_LAST`), and so are its rollback rules.

### Exactness

A cross-build per-tick diff of perceived rows is not deterministic here: a tick's `now` comes from the host's clock, and `ctx.rng()` draws from the transaction. The same seeded battle therefore diverges between two runs within a second, on either build. Instead, every sweep compares the new path with the old one in the same tick, on the same state, under the existing `regard_cache_check` law:

- each sweep's one gather against the two it replaces: `creatures_near` within the sight gather, and `heard` (the old function, kept as the reference). They must hold the same creatures, at bit-identical positions and distances, with the same kinds;
- each projection given from the tick's memo against a fresh `project_as`;
- every row of every viewer after each kept sweep against a fresh `project` (the existing `check_rows`: one row per creature seen and one for the viewer, each equal to projecting it afresh);
- every shared answer against a fresh one (the existing regard-answers check).

The results go in `sweep exact: gathers_checked=… sight_differed=… heard_differed=… memo=… memo_compared=… memo_differed=…`, beside `sweep kept: … compared=… differed=…`.

| Run (battle_viewers fixture, `regard_cache_check=true`, 30 s window) | Sweeps' gathers compared | Projections from the memo compared | Rows and shared answers compared | Differed |
|---|---:|---:|---:|---:|
| first build (hearing, memo, law input), 216 viewers, 10 m ring | 14,639 | 538,736 | – | 0 |
| `sx`, 216 viewers, 10 m ring | 15,045 | 553,599 | 2,408,995 | 0 |
| `sx`, 216 viewers, 26–32 m ring | 38,286 | 269,274 | 2,134,513 | 0 |
| final, 216 viewers, 10 m ring | 15,105 | 546,504 | 3,327,643 | 0 |
| final, 16 viewers, 10 m ring | 4,491 | 4,268 | 690,881 | 0 |

(With 16 viewers the memo runs only in the ticks where two or more sweep.) The scenes below drive every path again on scripted worlds. Row ids (`projected.id`, auto-increment) can differ between any two runs: the order of a `HashSet`'s iteration, which orders the inserts, already depends on the instance's history in 2.14.1's WASM (`RandomState` with fixed keys, incremented per map). Rows are compared by (viewer, body) and content.

### Measurement

The [fixture](#fixture-and-method) as above. `battle_viewers.py`, a fresh Cullet world per run, 200 AI fighters, `--tiers --cues --paused-placement --keep-alive 0.5 --fresh-every 3`. Density case `--ring 10,10` with 216 viewers; clean case `--ring 26,32` with 216; and 16 viewers on the 10 m ring. 20 s warm-up and a 60 s window. L0 is `--no-profile`; L2 is `--full-log --law profile_detail=true`.

- **Arms.** `cp` is the merged `combat-phase` head `836a27be` (main `b6aa7489` with the diagnosis). `sx` is `sweep-exact` at `74ddd30e`. The final build is `a51d6b55` (as `sx`, with the memos only when two or more viewers sweep in a tick). Built with rustc 1.99.1, the Cullet seed compiled in.
- **Order.** Series `ab` interleaved `cp` and `sx` arm by arm, twice (24 runs). Series `conf` interleaved `cp` and the final build at 16 viewers (L0 and L2), twice, with two runs of the final build at 216 r10 L2.
- **Placement.** Private server `slop-sweep-20261120`, pinned to the X925 cores (`docker update --cpuset-cpus 5-9,15-19`) before the first run. Each run's start line in `series.log` records the cpuset (`5-9,15-19` in all 34). Which core the database thread ran on was not sampled.
- **Discipline.** Every series held `~/slop-mq/battle.lock`. Each run started only when `flock -n ~/slop-mq/lock true` succeeded (the merge queue held it 04:31–05:02, 05:18–05:31 and 05:47–06:01) and MemAvailable was ≥ 40 GB and the disk ≥ 45 GB free. Host load per run is in the table (1-minute load, median of the window). The proofs ran on a second private server pinned to the A725 cores, with builds on those cores too.

#### T4: A/B per arm (ranges over runs)

| Arm | Build | Runs | Ticks/s | Tick WASM ms/s | Whole tick call ms/s | Views ms/s | `tick.perception` ms/s | µs a sweep | Seen a sweep | µs a sweep per creature seen | Per viewer ms/s | Viewer deaths / heals (window) | Host load (median) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| v216r10-L2 | `cp` | 2 | 1.83 | 456.1–456.3 | 958.1–959.3 | 302.1–306.8 | 272.9–280.0 | 689–711 | 156 | 4.42–4.57 | – | 22 / 62, 28 / 56 | 5.5, 3.1 |
| v216r10-L2 | `sx` | 2 | 1.83–1.91 | 432.9–434.7 | 956.2–958.1 | 318.6–323.3 | 248.5–253.6 | 613–634 | 152–165 | 3.85–4.02 | – | 31 / 64, 28 / 59 | 4.4, 7.9 |
| v216r10-L2 | final | 2 | 1.91–1.99 | 424.5–435.0 | 962.7–963.7 | 325.1–328.2 | 243.7–246.5 | 574–600 | 151–157 | 3.80–3.81 | – | 20 / 61, 23 / 68 | 5.7, 5.0 |
| v216r10-L0 | `cp` | 2 | 1.45–1.75 | 411.8–447.4 | 960.8–967.1 | 254.3–315.1 | – | – | – | – | – | 29 / 27, 29 / 59 | 10.0, 3.6 |
| v216r10-L0 | `sx` | 2 | 1.76–2.01 | 416.1–430.0 | 962.0–962.1 | 322.7–333.6 | – | – | – | – | – | 24 / 52, 27 / 67 | 37.7, 3.5 |
| v216r26-L2 | `cp` | 2 | 12.53–12.99 | 425.8–435.4 | 865.3–876.1 | 255.3–260.0 | 220.1–224.9 | 216–223 | 55–56 | 3.90–3.96 | – | 0 / 71, 0 / 113 | 10.5, 3.7 |
| v216r26-L2 | `sx` | 2 | 11.81–12.78 | 421.4–423.7 | 875.5–879.8 | 257.9–267.5 | 208.1–210.7 | 204–209 | 56–59 | 3.52–3.67 | – | 0 / 110, 0 / 128 | 6.2, 2.4 |
| v16r10-L2 | `cp` | 4 | 58.07–59.02 | 319.4–348.3 | 466.8–505.3 | 106.9–115.3 | 26.0–30.1 | 320–367 | 83–93 | 3.70–4.21 | – | 0 / 148, 0 / 173, 0 / 152, 0 / 136 | 4.3, 2.2, 10.6, 6.5 |
| v16r10-L2 | `sx` | 2 | 58.97–59.02 | 328.4–335.8 | 480.7–496.2 | 110.5–117.6 | 28.1–28.5 | 342–347 | 88–91 | 3.82–3.90 | – | 0 / 163, 0 / 176 | 5.5, 5.0 |
| v16r10-L2 | final | 2 | 58.47–58.82 | 337.6–340.0 | 486.4–499.0 | 101.5–117.2 | 29.0–29.6 | 353–360 | 82–94 | 3.75–4.36 | – | 0 / 146, 0 / 153 | 7.7, 25.4 |
| v16r10-L0 | `cp` | 4 | 58.74–59.35 | 275.0–305.0 | 435.7–476.5 | 110.9–124.5 | – | – | – | – | 13.4–15.9 | 0 / 141, 0 / 198, 0 / 147, 0 / 197 | 31.8, 4.4, 7.5, 14.3 |
| v16r10-L0 | `sx` | 2 | 58.65–59.01 | 276.6–311.0 | 437.3–484.6 | 117.0–123.8 | – | – | – | – | 13.1–16.1 | 0 / 178, 0 / 163 | 21.9, 4.4 |
| v16r10-L0 | final | 2 | 59.39 | 261.4–281.8 | 420.7–437.5 | 113.1–116.8 | – | – | – | – | 12.1–13.1 | 0 / 175, 0 / 150 | 6.1, 10.4 |
| v0-L0 | `cp` | 2 | 60.25–60.40 | 212.1–215.5 | 219.8–224.1 | 0.0 | – | – | – | – | – | – | 19.5, 3.5 |
| v0-L0 | `sx` | 2 | 60.26–60.37 | 218.7–219.1 | 227.2–227.4 | 0.0 | – | – | – | – | – | – | 11.7, 3.9 |

Per viewer is (whole tick call − the same build's 0-viewer call) / 16, at L0; the final build is taken against `sx`'s 0-viewer arm (with no viewer nothing it changed runs). The 16-viewer arms differ between runs by how much the viewers are fought over (heals 136–198 a window), which moves the whole call by ±20 ms/s; per creature seen the sweep is the same.

#### T5: the sweep's parts (µs a sweep, L2; `cp` has the parts the diagnosis spanned)

| Part | 216 r10 `cp` | 216 r10 `sx` | 216 r10 final | 216 r26 `cp` | 216 r26 `sx` | 16 r10 `cp` | 16 r10 `sx` | 16 r10 final |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `sweep.one` | 689–711 | 613–634 | 574–600 | 216–223 | 204–209 | 320–367 | 342–347 | 353–360 |
| `sweep.setup` | 19–20 | 19 | 18–19 | 9–10 | 9 | 15–19 | 16 | 16–17 |
| `sight.player_candidates` | 97–98 | 80 | 78–80 | 71–72 | 60–62 | 45–48 | 39–42 | 41–42 |
| `sweep.hear` | 98–99 | 94–102 | 86–92 | 17–18 | 19 | 56–62 | 56–57 | 58–62 |
| `sweep.rows` | 112–116 | 109–113 | 102–108 | 26–27 | 28–29 | 33–37 | 36–38 | 39–40 |
| `sweep.scene` | 49–51 | 52–58 | 48–50 | 8 | 8–9 | 32–40 | 36–37 | 38–39 |
| `sweep.project` | 303–320 | 252–256 | 233–244 | 78–79 | 72–75 | 129–150 | 150 | 150–151 |

#### T6: the finer split (µs a sweep)

The "before" columns are one run each of `cp` with the finer spans and no other change (`fa5d4678`, series `split`, host load 16–20 against 2–8 for most of `ab`). The "after" columns are the `sx` runs of series `ab`. Read the parts' shares from it; T5 holds the A/B.

| Part | 216 r10 before | 216 r10 after | 216 r26 before | 216 r26 after | 16 r10 before | 16 r10 after |
|---|---:|---:|---:|---:|---:|---:|
| `sweep.one` | 687 | 613–634 | 234 | 204–209 | 395 | 342–347 |
| `sweep.setup` | 20 | 19 | 10 | 9 | 19 | 16 |
| `sight.player_candidates` | 97 | 79–80 | 73 | 60–61 | 48 | 39–42 |
| `sight.gather` | 17 | 6 | 13 | 5–6 | 8 | 5 |
| `sweep.hear` | 96 | 94–102 | 19 | 19 | 66 | 56–57 |
| `hear.read` | – | 21–23 | – | 6–7 | – | 17–18 |
| `sweep.rows` | 108 | 109–113 | 28 | 28–29 | 42 | 36–38 |
| `rows.out` | 38 | 37–40 | 9 | 9–10 | 17 | 14 |
| `rows.in` | (70) | 65–67 | (19) | 15–16 | (26) | 18–19 |
| `sweep.scene` | 50 | 51–58 | 8 | 8–9 | 45 | 36–37 |
| `sweep.project` | 306 | 252–255 | 87 | 72–75 | 165 | 150 |
| `project.test` | 72 | 66 | 27 | 21–23 | 76 | 67–72 |
| `project.regard` | 62 | 37 | 16 | 11 | 22 | 18–19 |
| `project.as` | 40 | 11–13 | 11 | 7 | 17 | 16–17 |
| `project.write` | 64 | 65–68 | 16 | 15–16 | 22 | 20–21 |
| `project.show` | 59 | 62–66 | 12 | 12–13 | 19 | 16–17 |

`rows.in` in the spans build was scoped wrongly: it ran on to the end of the sweep, over the scene and the projections. The bracketed values are `sweep.rows` less `rows.out`.

### What the finer split says

- **Hearing (86–102 µs a sweep at 216 r10, 56–62 at 16).** The second gather was 9 µs at the 10 m ring and is gone (`sight.gather` also fell from 17 to 6 µs: it no longer sorts). The rest is the viewer's `heard` rows:
  - reading them: `hear.read`, 21–23 µs for about 100 rows at 216 r10, 17–18 µs for about 63 at 16;
  - writing what changed: at 16 viewers, per sweep, 46–48 sounds, about 5 bearing or band updates, 6 new and 7 gone.
  The by-target match saved about 5 µs. Fewer reads would need the rows in module memory, across transactions. That is the `KEPT` pattern, exact only while every writer marks it.
- **The change test (`project.test`, 66–72 µs).** About 0.4 µs a seen creature with health warm (216 viewers sweeping in one tick). At 16 viewers, health is read cold in almost every sweep: 108 `vitals` reads for 137 seen. Neither the hasher nor skipping hidden health moved it measurably at the 10 m ring, where Cullet's `known_within` (24 m) covers almost everyone.
- **Projections (`project.regard` 62 → 37 µs, `project.as` 40 → 11–13 µs at 216 r10).** The memos and the input built once per kind remove most of what the law and the projection cost. Writes (`project.write`, 62–68 µs) and newcomers' fighter and doing copies (`project.show`, 59–66 µs, `frame.rs`) are writes and stay. At 16 viewers, 7.5 of the 9.5 re-projections a sweep are newcomers, each a row insert (`project:insert`).
- **Row churn (`sweep.rows` about 110 µs at 216 r10).** Perceived rows in and out, and their motion copies: writes, unchanged.

So at 60 Hz with few viewers in a tick, the exact savings found here are small. The per-viewer cost is row I/O: reading what the viewer had (perceived, heard, projected rows) and writing what changed.

### What next, each for its owner

- **Exact, dev-box (`frame.rs`).** `show_fighter` reads back the projection just written for each newcomer (`perceived_band`). The kept sweep holds that band, so passing it in would save one row read a newcomer. And `deliver` could take the sweep's health readings for the same tick (same formula, no write between); today it reads them again.
- **Module memory across transactions (Spark, needs a decision).** Keep each viewer's `heard` rows and the tick-to-tick health readings in memory, like `KEPT`. Exact only while every writer marks it; `KEPT_REFRESH_SWEEPS` bounds a missed mark. That is the same bounded imprecision the kept sweep accepts, so it is the coordinator's call, not an exact fix.
- **Fewer pairs or refreshes:** the laws in [What exact work cannot reach](#what-exact-work-cannot-reach-decisions-for-the-owner-each-a-law-off-by-default-measured-before-it-is-proposed), unchanged.

### Proofs

On the merged head `eed2505e` (the final build with `origin/main` `8031d785` merged in; main's changes since the base touch no file of this change), on a second private server `slop-sweep-verify-20261120` pinned to the A725 cores. Fake model only, no Neo4j.

| Surface | Scene | Result |
|---|---|---|
| exactness | the same-tick checks above, under `regard_cache_check` | 0 differed in every run (87,677 sweeps' gathers, 1.91 M memo projections) |
| verify-core | `tick`, `sight`, `senses`, `refusal` (default world) | pass (6, 6, 7, 4 checks) |
| verify-core | `skirmish` (island) | pass (8) |
| verify-core | `sweep_marks` (Cullet) | pass (6) |
| verify-core | `sweep_kept`, `sweep_rollback` (Cullet) | 0 rows differed, but each fails its volume threshold: 524 rows compared (needs 1,000) and 369 (needs 500). `cp` fails both the same way on this server (526 and 357), as does `sx` (536 and 363). The cause is this server and its CLI log tail, not the change. |
| verify-client | `cues` with `near_tier`, `motion_tables` | pass (22, 7, 27) |
| verify-player | `combat --scene all` (island) | 54 of 54 |
| verify-player | `combat --scene shot`, alone | `sx` 2 of 5 and `cp` 3 of 5, failing the same check: the unseen archer's arrow did not strike within 12 s (no line, `hurt_by` still the near archer). The `shot` scene is a known flake in staged geometry (scene gate). |
| verify-player | `fov` (heard and not seen, `heard_sounds`) | `sx` 1 of 1. Merged head: 3 of 4. The failing run (12 of 18) never saw R, either way, in a placement found at the sixth try. Two reruns passed 18 of 18, and a third passed with `regard_cache_check` on (111 sweeps' gathers compared, none differed). |
| build | `just living-check` | ok on `74ddd30e` (1,266 s) and on `eed2505e` (734 s) |

Not covered:
- verify-minds and verify-knowledge. Minds' percepts and scenes (`Sensing`, `heard`, `project`) are unchanged code, but their scenes were not run.
- The scene gate as a whole.
- A sustained 200-fighter battle, and the 30-minute and 8-hour gates.
- Real clients' input rates.
- These numbers are one host's A/B. They do not establish acceptance or capacity.

### SpacetimeDB documentation

Read 2026-11-20 (docs version 2.0.0; the pinned server and crates are 2.14.1):
- [Reducers](https://spacetimedb.com/docs/functions/reducers/): "Every reducer runs inside a database transaction"; on an error all of its changes are rolled back. "Global and Static Variables Are Undefined Behavior": module-level state is not guaranteed between calls, a rolled-back transaction's change to it "may remain", and a reducer may run in a fresh instance or concurrently in another.
  - The design follows from this. The new memos (`Shared`) are local values within one tick's call, made at its sweep and dropped at its end, so neither rollback nor another instance can carry them.
  - Module memory across calls is unchanged: `KEPT` and `HEARD_LAST`, with their tick-continuity clearing ([PERCEPTION.md](PERCEPTION.md#module-memory-and-rollback)). Only the hasher of their maps changed.
- No table, index, view, subscription or event table changed, so the data paths are as in the diagnosis. The same rows are read and written in the same order, minus repeated reads of `character`, `vitals`, `reveal` and the second chunk gather within one tick.

### Evidence

`~/slop-evidence/sweep-exact-20261120.tar.zst` and `.sha256`. It holds the series (`split`, `split1`, `ab`, `conf`: each run's `result.json`, `metrics.json`, `threads.json`, `ticks.json`, `load.log` and `module.log`, plus `series.log` and `arms.txt`), the check runs (`chk1`–`chk4`), the diagnostic runs, the rollups (`rollup-ab.json`, `rollup-conf.json`) and their scripts, the proofs' run folders and logs, and every wasm measured.

## Instrumentation added on this branch

All spans are detail spans (`common::detail_span`) and all counters are `common::diag`. With profiling off they cost a thread-local read each. L0 runs of the branch and of main are in T1; the pinned main-against-branch pairs are in series 3 and 4.

- **`tick.rs`:**
  - `eval.combat`: each 15 Hz cadence evaluation.
  - `eval.slot.fight` / `eval.slot.calm`: each slot evaluation, fighters apart.
  - The counter `eval:combat_due`: fighters due on the cadence this tick, the census.
- **`perception.rs`:**
  - `sweep.one`: each viewer's sweep.
  - Its parts: `sweep.setup`, `sweep.attention`, `sweep.hear`, `sweep.rows`, `sweep.scene`, `sweep.project`. `sight.player_candidates` was already there.
  - The counters `sweep:viewers`, `sweep:candidates`, `sweep:seen`.
- **`living/tools/battle_viewers.py`:**
  - `--no-profile` (L0 with server metrics).
  - `--full-log` (the replica's whole module log, read again until complete).
  - `--character-tables` (viewers on `seen_character_copy`).
  - `load.log` per window (the 1-minute load and MemAvailable every second).
  - The replica number in `result.json`.
- **`living/tools/span_report.py`:** per span, calls/s, ms/s, mean, p50 and p99. Per `diag:` key, its rate. Scene sizes. Reads a `--detail` run directory.

## SpacetimeDB documentation and source consulted

Read on 2026-11-20 (docs version 2.0.0; the pinned server and crates are 2.14.1):
- [Views](https://spacetimedb.com/docs/functions/views/): a per-sender view is computed and change-tracked per subscriber and re-runs whole when anything in its read set changes. Anonymous views and views with arguments are shared per argument.
  - The page says query-builder views update incrementally. Dev-box's reading of the 2.14.1 source ([battle viewers](BATTLE_VIEWERS.md), option E) found them table-wide in 2.14.1. The versioned source decides; treat that as unverified for 2.14.1.
- [Event tables](https://spacetimedb.com/docs/tables/event-tables/): rows are delivered at commit and never kept in the client cache. Row-level security applies with the same semantics. Views cannot read them, and they cannot be the lookup side of a subscription join.
  - The pinned `spacetimedb-bindings-macro` 2.14.1 accepts `event`, used today by `seen_body_cue` and the other cue tables.
- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): overlapping queries process and serialize rows twice; identical queries are shared. The page does not discuss `:sender` cost. Dev-box measured about 1 µs a row for RLS-pruned delta evaluation on the cue tables.
- [Table performance](https://spacetimedb.com/docs/tables/performance/): split tables by access pattern, keep private what clients do not need, and batch writes in one reducer.
- [Row-level security](https://spacetimedb.com/docs/how-to/rls): experimental; the docs prefer views. Steps 1–3 extend RLS use, with the cue tables' safeguards (isolation gate, owner subscribe-all guard, kill switch, upgrade checklist).

Data paths for the plan's steps:
- **Steps 1–3:** write the same rows as today; the copies are moved or mirrored, not added, except `my_combat`'s event rows, one per perceived combat event per viewer. Each row goes to its one viewer by RLS.
- **Steps 5–6 and 8–11:** write nothing new. Their memos live in module memory for one tick and are rebuilt by a fresh instance.
- **Step 7 and the far-tier law:** change rows and need their own data-path notes.

## Evidence and coverage

- **Archive:** `~/slop-evidence/combat-phase-20261120.tar.zst` and `.sha256`. It holds every run directory, the series logs, the rollup (`rollup.json`) and its scripts, and both wasm builds.
- **Series:** series 1 (all arms), series 2 (16-viewer and table arms), series 3 (one pinned run of each series-1 arm) and series 4 (a second pinned L0 pair of main and this branch at 0 viewers).
  - Each run directory has `result.json`, `metrics.json`, `threads.json`, `ticks.json`, `load.log`, `module.log` (complete for L1/L2), `events-*.jsonl` and `players-*.stderr`.
  - Series 1 started at 02:05 (container pinned from 02:32), series 2 at 02:47, series 3 at 03:24 and series 4 at 03:44, all on 2026-11-20 CET.
- **Tables:** regenerate with `python3 .local/cp/rollup.py && python3 .local/cp/tables.py` from the archive's `cp/` directory, run at the repository root.
- **Not covered:**
  - A sustained 200-fighter battle (the fight thins).
  - Minds (no mind service).
  - The 30-minute and 8-hour gates.
  - Client frame pacing, network RTT, and real players' input rates (viewers walk circles).
  - The split of the whole-call remainder, which needs a host profiler.
  - The table arms' privacy proofs (dev-box's `motion_tables.py`).
- **Not established:** these numbers are a diagnosis on one host. They do not establish acceptance or capacity.

## T1: every run

Core: `X925` when the container was pinned to the X925 cores for the window, `any` before. Engaged fighters: the cadence census over the first 5 s, the window and the last 5 s (L1/L2 runs only). Deaths and heals: viewer deaths in the window and `admin_set_vitals` calls in the window.

| Arm | Rep | Core | Viewers | Ticks/s | Tick WASM ms/s | Whole tick call ms/s | Views ms/s | Sub. Update CPU ms/s | Serialize ms/s | DB thread CPU ms/s | Host load min/med/max | Engaged fighters start→mean→end | Viewer deaths (window) / heals |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| v0-L0 | 20261120-020507/r1 | any | 0 | 59.91 | 265.0 | 273.3 | 0.0 | 0.3 | 0.0 | 276.2 | 1.5/1.7/1.9 | – | – |
| v0-L0 | 20261120-020507/r2 | any | 0 | 58.54 | 370.4 | 381.4 | 0.0 | 0.4 | 0.0 | 383.5 | 5.5/6.3/7.6 | – | – |
| v0-L0 | 20261120-032451/r1 | X925 | 0 | 60.22 | 213.9 | 221.6 | 0.0 | 0.3 | 0.0 | 223.6 | 5.6/5.8/6.3 | – | – |
| v0-L0 | 20261120-034454/r2 | X925 | 0 | 60.29 | 208.0 | 215.4 | 0.0 | 0.3 | 0.0 | 217.1 | 6.4/7.3/7.9 | – | – |
| v0-L1 | 20261120-020507/r1 | any | 0 | 59.55 | 281.1 | 288.5 | 0.0 | 0.3 | 0.0 | 290.7 | 1.1/1.3/1.8 | 167.8→136.7→100.6 | – |
| v0-L1 | 20261120-020507/r2 | X925 | 0 | 60.07 | 250.3 | 258.5 | 0.0 | 0.3 | 0.0 | 255.8 | 4.9/6.0/7.1 | 171.1→139.3→97.6 | – |
| v0-L1 | 20261120-032451/r1 | X925 | 0 | 60.25 | 230.1 | 237.5 | 0.0 | 0.3 | 0.0 | 239.2 | 5.4/6.1/6.4 | 172.4→129.2→82.9 | – |
| v0-L2 | 20261120-020507/r1 | any | 0 | 59.21 | 348.7 | 356.4 | 0.0 | 0.3 | 0.0 | 358.5 | 1.2/1.6/1.9 | 191.6→137.4→93.1 | – |
| v0-L2 | 20261120-020507/r2 | X925 | 0 | 60.11 | 242.4 | 249.2 | 0.0 | 0.3 | 0.0 | 251.4 | 2.1/2.8/3.4 | 186.4→139.6→100.9 | – |
| v0-L2 | 20261120-032451/r1 | X925 | 0 | 60.18 | 270.6 | 278.7 | 0.0 | 0.3 | 0.0 | 277.8 | 5.3/6.7/7.8 | 214.4→144.4→90.4 | – |
| v0-base-L0 | 20261120-020507/r1 | any | 0 | 57.58 | 370.6 | 382.4 | 0.0 | 0.7 | 0.0 | 378.4 | 4.0/8.6/16.4 | – | – |
| v0-base-L0 | 20261120-020507/r2 | any | 0 | 57.91 | 412.1 | 423.5 | 0.0 | 0.4 | 0.0 | 424.9 | 4.2/5.2/6.2 | – | – |
| v0-base-L0 | 20261120-032451/r1 | X925 | 0 | 60.22 | 214.0 | 222.0 | 0.0 | 0.4 | 0.0 | 223.8 | 6.9/7.3/7.6 | – | – |
| v0-base-L0 | 20261120-034454/r2 | X925 | 0 | 60.30 | 213.0 | 220.6 | 0.0 | 0.3 | 0.0 | 222.5 | 6.4/6.9/7.4 | – | – |
| v0-f100-L2 | 20261120-020507/r1 | any | 0 | 59.99 | 259.0 | 266.4 | 0.0 | 0.4 | 0.0 | 268.5 | 2.7/4.1/4.8 | 90.1→74.1→51.8 | – |
| v0-f100-L2 | 20261120-020507/r2 | X925 | 0 | 60.16 | 159.3 | 165.5 | 0.0 | 0.3 | 0.0 | 164.0 | 6.2/8.0/9.3 | 86.0→69.3→48.4 | – |
| v0-f100-L2 | 20261120-032451/r1 | X925 | 0 | 60.27 | 152.0 | 157.5 | 0.0 | 0.3 | 0.0 | 159.4 | 6.1/6.6/7.4 | 92.7→70.0→56.6 | – |
| v16r10-L0 | 20261120-024732/r1 | X925 | 16 | 59.07 | 271.7 | 418.6 | 106.6 | 10.1 | 7.0 | 428.2 | 8.4/9.6/10.3 | – | 0 / 135 |
| v16r10-L0 | 20261120-024732/r2 | X925 | 16 | 58.87 | 274.6 | 430.3 | 113.5 | 11.1 | 7.7 | 440.8 | 5.3/5.7/7.3 | – | 0 / 164 |
| v16r10-L2 | 20261120-024732/r1 | X925 | 16 | 58.95 | 336.3 | 487.1 | 107.3 | 10.5 | 7.6 | 491.2 | 9.2/9.9/10.3 | 194.8→146.9→109.6 | 0 / 130 |
| v16r10-L2 | 20261120-024732/r2 | X925 | 16 | 59.18 | 335.4 | 485.9 | 108.3 | 10.2 | 7.4 | 494.8 | 16.6/17.9/19.4 | 193.3→152.0→112.9 | 0 / 136 |
| v16r10-tab-L2 | 20261120-024732/r1 | X925 | 16 | 58.55 | 356.8 | 465.0 | 68.1 | 10.8 | 8.8 | 469.5 | 9.6/10.7/11.7 | 178.5→151.7→111.7 | 0 / 152 |
| v16r10-tab-L2 | 20261120-024732/r2 | X925 | 16 | 59.29 | 356.5 | 468.2 | 72.5 | 10.8 | 9.1 | 477.1 | 4.7/5.2/5.5 | 182.0→160.5→112.5 | 0 / 145 |
| v216r10-L0 | 20261120-020507/r1 | any | 216 | 1.75 | 445.5 | 961.1 | 310.9 | 49.7 | 79.6 | 1000.9 | 5.8/6.8/9.6 | – | 26 / 50 |
| v216r10-L0 | 20261120-020507/r2 | X925 | 216 | 1.73 | 452.1 | 963.3 | 307.4 | 49.1 | 64.2 | 1001.1 | 4.4/4.8/6.2 | – | 23 / 57 |
| v216r10-L0 | 20261120-032451/r1 | X925 | 216 | 1.86 | 447.1 | 965.6 | 312.8 | 49.3 | 75.0 | 1002.7 | 11.7/15.6/16.9 | – | 16 / 61 |
| v216r10-L2 | 20261120-020507/r1 | any | 216 | 1.73 | 455.6 | 952.5 | 300.8 | 48.1 | 68.4 | 996.3 | 3.8/5.5/6.5 | 276.1→266.5→254.3 | 30 / 57 |
| v216r10-L2 | 20261120-020507/r2 | X925 | 216 | 1.81 | 444.9 | 961.3 | 309.6 | 46.9 | 64.4 | 993.8 | 5.8/7.0/7.9 | 229.8→259.8→224.5 | 17 / 63 |
| v216r10-L2 | 20261120-032451/r1 | X925 | 216 | 1.73 | 459.1 | 960.6 | 302.6 | 48.9 | 66.4 | 1001.9 | 8.2/11.1/17.5 | 248.3→264.7→259.4 | 20 / 55 |
| v216r10-tab-L2 | 20261120-024732/r1 | X925 | 216 | 2.51 | 628.2 | 938.7 | 122.1 | 45.2 | 87.0 | 986.3 | 13.8/24.7/28.1 | 292.3→286.2→252.4 | 54 / 87 |
| v216r10-tab-L2 | 20261120-024732/r2 | X925 | 216 | 2.35 | 622.7 | 935.5 | 129.5 | 44.5 | 73.4 | 990.6 | 8.7/11.2/14.4 | 281.2→281.4→256.7 | 63 / 82 |
| v216r26-L2 | 20261120-020507/r1 | any | 216 | 11.47 | 436.5 | 882.6 | 260.1 | 36.1 | 51.5 | 919.3 | 4.1/4.9/7.6 | 57.3→156.5→77.9 | 0 / 99 |
| v216r26-L2 | 20261120-020507/r2 | X925 | 216 | 11.50 | 444.5 | 888.1 | 257.4 | 37.2 | 37.7 | 921.0 | 3.5/6.3/7.8 | 69.6→149.6→105.8 | 0 / 132 |
| v216r26-L2 | 20261120-032451/r1 | X925 | 216 | 13.09 | 428.1 | 871.6 | 255.6 | 36.2 | 45.8 | 906.3 | 12.0/14.2/17.5 | 57.9→149.0→118.8 | 0 / 130 |

## Step 3 results: exact AI trims (Spark, branch `ai-trims`)

Status: built and measured, 2026-11-20, branch `ai-trims` from `origin/main` 8031d785, final 1eac83d0. Not merged. This section reports plan steps 8–11 ("The AI tick body: exact trims"): what was built, what was tried and dropped with the data that decided it, how exactness was proven, and the A/B against main.

### In short

- **About 9–13% off the AI-only tick, exactly.** Uninstrumented, 0 viewers, pinned to the X925 cores: main 193.9–213.1 ms/s against ai-trims 180.4–193.6 (and 182.5 for the same code one commit earlier). With the same detail spans on both sides (L2), an evaluation costs 60.4–61.6 µs against the base's 69.5 (−12%), and the tick per engaged fighter-second 1,716–1,767 µs against 1,901 (−8 to −10%). With 16 viewers on the 10 m ring: main 256.7–298.9 against 247.2–251.5 ms/s.
- **The plan expected 25–30%; the measured data took three of its four levers away:**
  - A refused begin cannot be cheap and exact by a memo: of "out of breath" refusals, 8% repeat with byte-identical input (and 9% more differ only in the breath level). The check reads breath and other values that move every tick.
  - Sight answers repeat within a tick for 1.4% of tests: a memo would cost about what it saves.
  - A folded line labels about 92 people once each, so a memo of labels within a tick has nothing to share.
  - What remained, the fixed cost per evaluation, gave the 12%. The Rhai check itself (21 µs, 17 ms/s at L2) is unchanged.
- **Exact, proven tick by tick:** a new comparator runs two builds from one copied world under a deterministic clock and compares a hash of all 113 tables at every tick and every row at the stop. Every batch of trims, and the final build, is identical to the base over 3,600 ticks of the 200-fighter Cullet battle. So is a control build with every hash map's keys moved.
- **One deliberate change that is not exact with main:** held-back bystander wakes are now delivered in id order. Main delivered them in a `HashMap`'s order, which on wasm32 depends on memory addresses and so differs between builds. That order is the order in which the woken are evaluated in a tick. Two builds of main's code that differed only in profiling spans already diverged at the 76th tick. Without this fix no two builds can be compared exactly; with it, the order no longer depends on the build.

### What was built (each exact)

| Trim | Where | Why it is exact | Measured (L2, base → ai-trims) |
| --- | --- | --- | --- |
| A scene's candidates are ordered only as far as a reader goes: a min-heap on `common::nearest_key` (the distance as `f32::total_cmp` orders it, then the gathered place). | `perception::Sensing`, lines of the AI scene only (not the sweep) | It pops exactly the order of `creatures_near`'s stable sort. `perception::sensed` (the `scene_lazy_check` reference) still sorts all at once. | `brain.scene` 11.9 → 7.1 µs; `brain.nearest` 9.2 → 6.8 µs |
| A move's check before it starts builds only the target fields its plan reads (what the target knows and carries, its body sex, distance, activity and stage), with one read of the actor's body. | `act::target_facts_reading`, `facts_at`, `skill_ctx_with` | A field the check does not read cannot change its answer. `check_ctx_check` compares with the whole context. | `check.ctx` 12.5 → 10.1 µs |
| A move's start (`perform`) builds only what its check and windup read, plus a paced skill's genes and practice. | `act::Reads::of_start` | The same, compared under `check_ctx_check`. One roll is drawn either way. | `act.skill_ctx` 51.8 → 39.3 µs; `begin.start` 107 → 95 µs |
| A needs recompute gives the `rates` law the fields it reads (kind, warmth, activity, stage, inventory), and the genes its answer is finished with. | `act::rates_facts` | Its memo key and its per-body finishing (`NeedLaw::rates`: hunger, energy, genes) read nothing else. | `needs.rates` 27.2 → 19.2 µs |
| A graph leaf reads the body's activity once and hands it to `act::begin_with`. The end of an evaluation reads it once for `town::settle_with` and `perceive::slept_with`. | `brain::Ev::leaf`, `evaluate` | Nothing writes the activity between those reads. A reflex that breaks off a deliberate act reads it again. | `brain.leaf` 19.9 → 18.3 µs; `brain.slept` 1.7 → 0.7 µs |
| The sleep check reads the character only when the body woke; the nearest pick reads the chosen character once. | `perceive::slept_with`, `Ev::nearest` | Characters are never deleted, and no write intervenes. | included above |

Same rules for players and AI: `use_skill` goes through `act::begin`, so a player's start gets the same trimmed context and the same answer. verify-player `combat` passed 54/54. No table, reducer, view or subscription changed, and no new module memory is kept (one counter and one flag under the diagnostic law below).

### Tried and not kept

- **A memo of refusals.** Measured with a profiling counter over the battle (`check:same_input` / `check:same_but_pools` / `check:new_input`, now removed). Per second of the comparator's run, "out of breath" refusals came 89.0 with new input, 9.9 with the same input but for the pools, and 8.9 with identical input. The check's plan reads breath, hurt and yield times and the target's health, which change between looks.
- **Sharing the context's nested maps in Rhai** (so a helper call copies pointers, not the maps). Natively it took `attack_check` from 8.2 to 6.8 µs, but it changes value semantics for a script that aliases `a.actor` or `a.target` (`let t = a.target;`). Left alone.
- **A sight memo per tick** (plan step 10). 109 + 6 repeats against 7,690 + 332 first tests per second of the run: 1.4%.
- **A label memo per tick** (step 11). A line labels each of its about 92 people once, and an onlooker's lines are 2 s apart. Labels repeat only across ticks, where their inputs (distance band, knowledge, far handles) can change. That is the projection memo's ground (sweep-exact), not a per-tick memo.
- **A blow's onlookers through the `controller` index** (decode only minded characters, about 25, rather than all about 250 nearby). Exact by the invariant that an `ai` character's controller is the world's admin, but its cost scales with every minded character in the world, a regression for a large town with a small fight.

### The exact comparator

- **Deterministic stepping** (the `det_clock` law, a diagnostic, off in play; `living/authority/src/det.rs`):
  - a tick's clock is the last tick's plus 1/60 s;
  - its random draws come from a generator seeded by the tick (`seed::Creating`; the tick path's `ctx.rng()` calls go through `seed::rng`);
  - housekeeping runs inside every 60th tick.
  - Each tick logs `det tick N all=… <table>=<hash>/<rows> …` for 113 tables, a multiset hash so storage order does not count.
  - `det_stop` pauses the world at a given tick.
- **Ids.** SpacetimeDB 2.14.1 skips an auto-increment sequence ahead to its next block of 4,096 at random, about once in 4,096 values: `should_simulate_sequence_reallocation` in `crates/datastore/src/locking_tx_datastore/mut_tx.rs`, seeded from the operating system each time a database is loaded (`committed_state.rs`). The same rows therefore get other ids on two servers. The docs say only that sequences "do not guarantee sequential ordering" and may skip ([auto-increment](https://spacetimedb.com/docs/tables/auto-increment)).
  - The hashes name each auto-increment row by its rank, and rename the references the battle writes the same way: far handles in text and in experiences, structures in inventories, rot and familiarity, lines heard, missiles' uses.
  - Main's experience window is checked when `id % 32 == 0`; under the law it is checked on every 32nd insert instead (`det::window_due`).
- **`living/tools/det_compare.py`:**
  - `prepare` makes a paused Cullet battle (`spawn_battle` 200) with `det_clock` on, stops the server cleanly and copies its volume as a template.
  - `run` copies the template twice (the two copies are treated alike: a server resumes sequences differently after another restart history), publishes one build on each as an update with the data kept, runs both to `det_stop`, and compares every tick's hashes and every table at the stop, renamed the same way.
  - It found the hash-order dependence (`--stop 84`: residents 25, 27 and 29 evaluated in another order) before the wake-order fix.
- **The control:** a build with `LIVING_DET_PERTURB=7` (compile time) makes seven extra hashers at its first tick, which moves the keys of every hash map made after them. It compared identical with its unperturbed self after the fix.

| Comparison (Cullet battle, 200 fighters and about 24 residents, ticks 9–3608, no viewers, no minds) | Ticks | Tables | Rows at the stop | Result |
| --- | ---: | ---: | ---: | --- |
| The same build on both copies | 3,600 | 113 | 45,234 | identical |
| Base 491d4b2c against itself with moved hash keys | 3,600 | 113 | 45,234 | identical |
| Base against 1cb9a71c (scene order, check context, rates facts, character reads) | 3,600 | 113 | 45,234 | identical |
| Base against the leaf and end-of-evaluation activity reads, then the start context (5e3437fb) | 3,600 each | 113 | 45,234 | identical |
| Base against the final 1eac83d0 | 3,600 | 113 | 45,234 | identical |
| Two builds of main's code before the wake-order fix | 3,600 | 113 | – | differed from tick 84 (`experience`, `familiar`, `sex_seen`: the same rows in another order) |

The diagnostic laws were also run on the final code over the same battle, with profiling on to count them: `check_ctx_check` made 142 comparisons and `scene_lazy_check` 357 per second of the 500 s run, with no difference and no error line.

### A/B measurement

- **Fixture:** dev-box's agreed fixture, as in this note's method: `battle_viewers.py`, Cullet compiled in, 200 fighters, 20 s warm-up and a 60 s window. 0 viewers, and 16 viewers on the 10 m ring (`--tiers --cues --paused-placement --keep-alive 0.5 --fresh-every 3`). L0 is profiling off (`--no-profile`); L2 is `profile_detail` with `--full-log`.
- **Server:** the private `slop-aitrims-20261120` (127.0.0.1:3511), pinned to the X925 cores (`docker update --cpuset-cpus 5-9,15-19`) for each run's window, recorded per run. It went back to the A725 cores between runs.
- **Discipline:** one series under `~/slop-mq/battle.lock` (07:15–08:10 CET), each run started only with `~/slop-mq/lock` free (the series waited 11 minutes for a merge), at least 40 GB of memory and 45 GB of disk free. Arms were interleaved, the second rep in reverse order.
- **Builds:** main 8031d785 against ai-trims 1eac83d0 (two runs per arm and level, plus one of 6f2b60fa, the same code with profiling-only counters). For the L2 split, the base fa5d4678 (main with the comparator harness and the same detail spans) against ai-trims.
- **Host load:** recorded per second (`load.log`). Two windows had load 12–20 from other sessions: `atbasev0l2r4` and `attrimv0l0r3`.

| Run | Build | Viewers | Level | Core | Ticks/s | Tick WASM ms/s | Whole tick call ms/s | Views ms/s | Load min/med/max |
|---|---|---:|---|---|---:|---:|---:|---:|---|
| atmainv0l0r1 | main 8031d785 | 0 | L0 | X925 | 60.01 | 213.1 | 220.6 | – | 4.8/5.1/5.7 |
| attrimv0l0r1 | ai-trims 6f2b60fa | 0 | L0 | X925 | 59.99 | 182.5 | 189.6 | – | 4.1/5.7/6.3 |
| attrimv0l0r2 | ai-trims 1eac83d0 | 0 | L0 | X925 | 60.01 | 180.4 | 187.5 | – | 5.5/6.2/6.5 |
| atmainv0l0r2 | main 8031d785 | 0 | L0 | X925 | 60.01 | 202.4 | 209.7 | – | 3.8/4.0/5.0 |
| attrimv0l0r3 | ai-trims 1eac83d0 | 0 | L0 | X925 | 59.99 | 193.6 | 201.1 | – | 7.4/11.3/15.6 |
| atmainv0l0r3 | main 8031d785 | 0 | L0 | X925 | 60.00 | 193.9 | 200.9 | – | 3.2/4.4/5.2 |
| atmainv16l0r1 | main 8031d785 | 16 | L0 | X925 | 58.68 | 271.3 | 425.1 | 112.8 | 3.5/3.9/4.3 |
| attrimv16l0r1 | ai-trims 6f2b60fa | 16 | L0 | X925 | 58.96 | 247.2 | 400.8 | 112.5 | 2.7/3.0/4.4 |
| attrimv16l0r2 | ai-trims 1eac83d0 | 16 | L0 | X925 | 58.92 | 251.5 | 412.2 | 118.5 | 8.3/9.6/12.3 |
| atmainv16l0r2 | main 8031d785 | 16 | L0 | X925 | 58.61 | 298.9 | 462.0 | 119.7 | 6.0/6.4/7.2 |
| attrimv16l0r3 | ai-trims 1eac83d0 | 16 | L0 | X925 | 59.09 | 249.4 | 404.1 | 113.1 | 2.2/2.4/2.8 |
| atmainv16l0r3 | main 8031d785 | 16 | L0 | X925 | 59.00 | 256.7 | 398.3 | 102.3 | 2.7/3.0/3.3 |
| atbasev0l2r3 | base fa5d4678 | 0 | L2 | X925 | 60.00 | 264.4 | 271.6 | – | 3.0/3.9/4.6 |
| attrimv0l2r3 | ai-trims 1eac83d0 | 0 | L2 | X925 | 59.97 | 242.2 | 249.3 | – | 3.5/4.9/5.1 |
| attrimv0l2r4 | ai-trims 1eac83d0 | 0 | L2 | X925 | 60.00 | 246.4 | 253.5 | – | 4.2/4.8/6.2 |
| atbasev0l2r4 | base fa5d4678 | 0 | L2 | X925 | 59.88 | 328.9 | 338.4 | – | 12.8/17.8/19.6 |
| atmainv0l2r1 | main 8031d785 | 0 | L2 | X925 | 60.00 | 239.7 | 246.2 | – | 1.9/2.4/3.3 |
| atmainv0l2r2 | main 8031d785 | 0 | L2 | X925 | 60.00 | 246.2 | 253.3 | – | 11.3/11.7/15.9 |

Main's L2 has fewer detail spans than the base and ai-trims, so it is not the L2 reference. The two L2 runs of 6f2b60fa, at 288–296 ms/s, carried two exploratory profiling counters that cost a hash insert per sight test while profiling. Those counters were removed in 1eac83d0 and those runs are left out.

The fight is not sustained, so each run's census differs (engaged fighters 131–146 on the L2 runs). The L2 split below normalizes per evaluation and per engaged fighter-second. It uses the low-load runs, base r3 against ai-trims r3 and r4.

| Span (L2, X925) | Base fa5d4678: calls/s, µs | ai-trims 1eac83d0: calls/s, µs (r3; r4) |
| --- | --- | --- |
| `tick` per engaged fighter-second | 1,901 µs (137.2 engaged) | 1,716 (139.1); 1,767 (137.4) |
| `eval.combat` | 2,016/s, 69.5 | 2,046/s, 60.4; 2,032/s, 61.6 |
| `brain.load` | 2,376/s, 10.8 | 10.2; 10.4 |
| `brain.scene` | 2,332/s, 11.9 | 7.1; 7.2 |
| `brain.nearest` | 2,280/s, 9.2 | 6.7; 6.9 |
| `brain.leaf` | 2,737/s, 19.9 | 19.0; 17.6 |
| `brain.begin` | 1,339/s, 37.6 | 35.5; 34.4 |
| `begin.check` (`check.ctx` + `check.rhai`) | 786/s, 35.4 (12.5 + 21.1) | 831/s, 33.3 (10.2 + 21.3); 747/s, 33.0 (10.0 + 21.1) |
| `begin.start` / `act.skill_ctx` | 107.1 / 51.8 | 96.1 / 40.4; 93.2 / 38.2 |
| `needs.rates` | 186/s, 27.2 | 19.3; 19.1 |
| `brain.after` / `brain.slept` | 10.7 / 1.7 | 10.2 / 0.7; 10.7 / 0.7 |
| `wake.eval.fight` | 221/s, 125.6 | 111.6; 115.2 |
| `act.complete` / `fold.blow` / `fold.labels` | 479.9 / 294.2 / 437.0 | 489.8 / 285.9 / 487.7; 462.3 / 301.6 / 406.7 |
| Refused begins (of them out of breath) | 1,207/s (575) | 1,249/s (615); 1,175/s (533) |

Refused begins cost a `brain.begin` each (34–36 µs on the trimmed build, 37.6 on the base), of which the Rhai check is 21 µs when it runs ("out of breath"; refusals by the timing gate and the facing test stop before it).

**Not established:**
- A sustained 200-fighter battle (the fight thins; no keeper).
- The 216-viewer arm (the viewers' cost is sweep-exact's and dev-box's; the AI side is the same code).
- Minds connected.
- Acceptance or capacity: one host, one fixture.

### Proofs

- The comparator results above, and the diagnostic laws over the battle (no difference).
- **Scene gate** (`scene_gate.py run --base 8031d785 --force --no-main-check`, private server `slop-aitrims-gate-20261120` on the A725 cores): passed.
  - verify-core: `tick` 6/6, `sight` 6/6, `senses` 7/7, `refusal` 4/4, `skirmish` 8/8, `mechanics` 23/23.
  - verify-player: `combat` 54/54 over 17 scenes.
  - verify-minds: `roundtrip`, `acts`, `dealings` and `conversation`.
  - verify-client: `cues` and `motion_tables`.
  - `mind-unit`, and generation on world, island, Cullet and cullet-laws.
  - `mechanics`, `cues` and `motion_tables` failed their first launch with "world query HTTP 0" (three launches at once on the slow cores) and passed alone.
- **Genesis fuel** against the merge queue's gate of main 8031d785 on the same rustc: init island −0.18%, Cullet −0.01%, cullet-laws −0.06%, plan-test −0.11%, world +0.07%. The two checkouts' paths differ in panic strings. Largest steps unchanged within 0.3%.
- verify-core `cheap_check_ctx` (11,995 move checks and starts compared with the whole context, none differed) and `scene_lazy` (20,709 lazy answers compared with the sorted scene, none differed) on the final tree.
- `just living-check` passed all nine steps (471 s).
- Records: `.agents/skills/verify-{core,player,minds,client,generation}/references/validation/2026-11-20-0645-ai-trims.md`.

### Tooling fixed on the way

`span_report.py` and `look_cost.spans` matched only spans printed in µs, ms or s. 2.14.1 prints a span under a microsecond in ns, so short spans were dropped: their calls were undercounted and their means overstated. That is why this note's T2 shows `after.mind` at about 260 calls/s against about 2,400 evaluations. Both now read ns. The ms/s of the larger spans in T2 are unaffected.

### SpacetimeDB documentation and source consulted

Read on 2026-11-20 (docs 2.0.0; the pinned server and crates are 2.14.1):
- [Auto-increment](https://spacetimedb.com/docs/tables/auto-increment): values are allocated in batches of 4,096. Gaps can appear, ordering is not guaranteed, and no value is ever reused. The versioned source (`mut_tx.rs`, `committed_state.rs`) shows the random skip and its per-load seed, and that values still increase. The comparator relies on that last point, and verified it on these runs.
- [Reducers](https://spacetimedb.com/docs/functions/reducers/), "Global and Static Variables Are Undefined Behavior". The trims keep nothing new in module memory. The comparator's insert counter and the control's flag live in module memory only under the diagnostic law, on fresh instances on both copies.
- Host source (`wasm_instance_env.rs`, `instance_env.rs`): every timing span is formatted and written to the module log, with no threshold. That is the detail spans' cost under L2.

### Evidence

- **Archive:** `~/slop-evidence/ai-trims-20261120.tar.zst` and `.sha256`. It holds:
  - the comparator runs (`det-compare.json` and per-tick hash logs of each), the template's record and the comparator profiles;
  - the A/B series (each run's `result.json`, `metrics.json`, `threads.json`, `load.log`, `placement.json` and L2 `module.log`; `rollup.md` and `rollup.json`);
  - the gate's evidence directories and log;
  - the wasm builds compared and measured.

## Wake order: rotating the held-back bystander wakes (Spark, branch `battle-laws`, Part D)

Status: built and proven, 2026-11-20, commit on `battle-laws` from `origin/main` 1511d5e8. A deliberate change of behaviour, not a law.

**Why.** Step 3 delivered the bystander wakes held back by `witness_wake_ms` in id order, so that the order no longer depended on the build. The order of these wakes is the order the woken are evaluated in the tick, and the first evaluated acts first. In id order alone the same low ids went first in every tick: a small but systematic advantage in a fight.

**The change** (`common::due_bystander_wakes`). The due ids are still sorted, and the delivery starts at `tick mod n` (n due), wrapping round. The start depends on the tick count alone, so every build delivers the same order. Under `det_clock` each tick with wakes due logs `det wakes tick=N due=[…] start=k`. A build compiled with `LIVING_DET_NOROTATE` set starts at 0, the control below. Nothing else changed: no table, reducer, view, subscription or law.

**Proof** (`living/tools/det_compare.py`, the Cullet battle of 200 fighters from one template, ticks 1–3,600, 113 tables, no viewers, no minds; private servers on the A725 cores):

| Comparison | Result |
| --- | --- |
| main 1511d5e8 against this commit built with `LIVING_DET_NOROTATE` (the logging and the refactor, no rotation) | identical: 3,600 ticks, 45,027 rows at the stop |
| no-rotation control against the rotated build | identical up to tick 75. Every one of the 387 ticks with wakes due up to the first difference had the same due set in both. The first difference is tick 76, the first tick the rotation reordered anything: 21 due, start 13 |
| main against main with every hash map's keys moved (`LIVING_DET_PERTURB=7`) | identical: 3,600 ticks |
| the rotated build against itself with moved hash keys | the per-tick hashes differ in `deliberation` alone from tick 1,564 for 141 ticks; every table at the stop is identical. The difference is not the build's: a far handle's id in a deliberation scene's JSON (`"id":1000008249` on one server, `1000006804` on the other) is the same row on both (the 2,326th far handle, observer 39, target 19, the same `first_ms`), numbered apart by SpacetimeDB 2.14.1's random sequence skip. The comparator renamed far handles only in `#…` text; its at-stop check now renames them in scene JSON too, and the rows then compare identical. The per-tick hash (`det.rs`) does not rename them yet |

**Cost.** 2.4 wakes are due a tick on average (at most 21) when any are; the rotation is one `rotate_left` of that list. Part A's 0-viewer arms below run on this build.

**What a fighter notices.** Among bystanders woken in the same tick, which one is evaluated first now changes from tick to tick instead of always being the lowest id.

## battle-laws: one per-pair series, the fighters' scheduling laws, and what is left (Spark, Parts A–C)

Status: measured, 2026-11-20, branch `battle-laws` (Spark) from `origin/main` 1511d5e8, merged with main 0c14a944 (`det_compare` with players). Nothing here is on by default. The owner's summary is docs/BATTLE_LAWS.md §4 (branch `battle-laws-devbox`); this section is its detailed source. Part D is the [wake order](#wake-order-rotating-the-held-back-bystander-wakes-spark-branch-battle-laws-part-d) above; Parts A–C feed dev-box's owner note on battle laws (`docs/BATTLE_LAWS.md`, frame-views). Law names here are the ones built; BATTLE_VIEWERS.md's options C (a bounded far tier) and D (a far cadence that follows density) keep their letters.

### In short

- **Where main stands, per (viewer, creature in sight) pair** (all exact steps in, the rotated wake order, copy tables on as shipped, 16 viewers on the 10 m ring): **about 130 µs/s per pair** (L1 at host load 1.5: 129.8–130.4; 119–144 over all six such runs; about 133 uninstrumented), about 11–12 ms/s per viewer. The copy tables off: 159–162 at low load (147–175 over four runs). The contract needs about 7–10, so the gap is still about **13–19×**.
- **216 viewers, per pair per tick** (the thread is saturated, so per second says little): 10 m ring 10.6 µs with the copy tables, 16.3–16.8 without; 26–32 m ring **1.9–2.3 µs with the copy tables, 5.8–6.7 without**. On the far ring the copy tables take 216 viewers from 10.6–12.1 to **23.7–28.1 ticks/s**, the largest single gain measured on this fixture. At 60 Hz the target is about 0.12–0.17 µs per pair per tick.
- **The fighters' scheduling laws** (new, off or at today's value; value-only in `law_override`):
  - `combat_eval_hz` 10 or 7.5 (today 15): **at a sustained 200 fighters (0 viewers) the tick falls 321 → 266 / 256 ms/s (−55 / −65 ms/s, −17% / −20%)**; on the thinning fixture the cadence evaluations cost 16% / 37% less per engaged fighter-second. At 216 viewers on the 10 m ring every law state ran 6–8% more ticks than off, within what the saturated arm varies; on the far ring nothing measurable. The per-pair cost does not move: these laws touch the AI side only.
  - `fighter_bystander_wakes` off (dev-box's (c); measured under its earlier name `fighter_bystander_wake_cadence` on, the same code): **at a sustained 200, −11 ms/s (321 → 310, −3.5%)**, about half the diagnosis's −23 (which counted the fighters' party wakes too). 194–2,736 bystander wakes a second are left to the cadence; per pair, nothing.
  - **Behaviour** (3 matched battles each, deterministic stepping): reaction to an attack aimed at a fighter is unchanged under every law (p50 17 ms, about 64% of attacks met by a block or dodge before they resolve). It comes from the party wake, not the cadence. At 7.5 Hz the slow tail between moves grows by about 11% (p90 1,300–1,450 → 1,517–1,566 ms), blocks fall 1.4 points and misses rise from 4.8% to 5.1–5.7% (10 Hz the most). Deaths and engagement length stay within the spread between battles.
- **Module memory across transactions** (Part C, built behind the diagnostic `sweep_keep_memory`, off): keeping each viewer's `heard` rows and the creatures' health readings in memory saves **25–35 µs of a 340–380 µs sweep at 16 viewers** (`hear.read` 17 → 1 µs, the change test 63–73 → 54 µs, `vitals` reads 64–69 → 2 a sweep; L2) and **6–21 µs of a 240-µs sweep at 216 on the far ring** (`hear.read` 7 → 0.6 µs). That is about −2..−3 ms/s at 16 viewers and −6..−22 ms/s at 216 on the far ring; on the 10 m ring at 216 the L1 runs showed nothing measurable. Kept heard rows never differed from the table (0 of 31,313 compared). Kept health differed in its raw value 13–14% of the time, but never in band (0 of 392,155). Not worth its risk on its own; the per-viewer cost is row writes, views and the call's remainder, not these reads.
- **Exactness.** With every new law off, the branch is identical to main tick by tick: without players over 3,600 ticks, and with 16 players over 1,800 ticks. A planted one-row difference was caught at its tick and table (the negative control).

### Fixture and method

As in [Fixture and method](#fixture-and-method): `battle_viewers.py`, a fresh Cullet world per run, 200 AI fighters, `--tiers --cues --paused-placement --keep-alive 0.5 --fresh-every 3`, 20 s warm-up and a 60 s window. Rings `--ring 10,10` (density) and `--ring 26,32` (liveness). Copy tables **on**: laws `motion_tables_on` and `characters_table_on` true (shipped) and the viewers on `seen_body_copy` and `seen_character_copy`; **off**: both laws false and the viewers on the views.

- **Levels.** L1 (`--full-log`: `set_profile` on, phase spans and `diag:` counters, no detail spans) for every arm, because the per-pair method needs the creatures in sight (`sweep:seen` / `sweep:viewers`) and the sweep and frame spans. L0 (`--no-profile`) for the 0- and 16-viewer arms as the uninstrumented reference. L2 (`profile_detail`) only for the sweep split of Part C.
- **Server.** Private `slop-battlelaws-20261120` (127.0.0.1:3533), `clockworklabs/spacetime:v2.14.1`, pinned to the X925 cores (`docker update --cpuset-cpus 5-9,15-19`) for every run's window and back to the A725 cores between runs; each run's `placement.json` records `5-9,15-19` (all 70 runs). Which core the database thread ran on was not sampled.
- **Builds** (rustc 1.99.1, Cullet compiled in): Part A `rot-de2c4208.wasm` (Part D's authority code; the Part D commit ac0b765f adds only docs and the comparator); Parts B and C `laws-ca236fa6.wasm` (this branch's laws, identical to the rotated build with them off, below).
- **Discipline.** Every series held `~/slop-mq/battle.lock`, each run started only with `~/slop-mq/lock` free (the series waited 10:13–10:28 for a merge) and MemAvailable ≥ 40 GB, disk ≥ 45 GB. Two or more runs per arm, interleaved, the second rep in reverse order. Host load (1-minute, median of the window) is in each table. Some first reps ran under load 17–55 from other sessions' builds and, from 09:33 to 09:43, this branch's own scene gate before it was moved to the A725 cores. Those runs are kept, and each table gives its load.
- **Per pair.** µs/s per (viewer, creature in sight) pair = (DB-thread CPU ms/s − the same build's 0-viewer arm at the same level) ÷ (viewers × mean creatures in sight a sweep), × 1000. Per pair per tick = (DB-thread ms per tick − the 0-viewer arm's ms per tick) ÷ pairs. Per viewer = the same difference ÷ viewers. The 0-viewer arm with the same law state is the reference in Part B.

### Part A: the per-pair series on main (rotated build)

| Arm (L1, X925) | Runs | Ticks/s | Tick WASM ms/s | DB thread ms/s | Views ms/s | Sweeps (`tick.perception`) ms/s | Frames ms/s | Call's remainder ms/s | Creatures in sight | Per viewer ms/s | **Pair µs/s** | **Pair µs/tick** | Viewer deaths / heals | Load (median) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 0 viewers | 2 | 59.97–59.99 | 222.4–226.7 | 230.8–234.2 | 0 | 0.1–0.2 | 1.2–1.7 | 7.0–8.8 | – | – | – | – | – | 1.3, 17.8 |
| 16, 10 m, copy tables off | 2 | 58.30–58.87 | 272.8–313.6 | 440.4–480.2 | 112.1–116.6 | 26.5–30.7 | 25.3–28.6 | 41.0–48.5 | 88.6 | 14.2 | 147–175 | 2.54–3.08 | 0/143, 0/159 | 5.2, 33.5 |
| 0 viewers, low load (series A3) | 2 | 60.01 | 200.9–201.8 | 209.2–210.1 | 0 | 0.1 | 1.0 | 6.6–6.8 | – | – | – | – | – | 1.5, 1.4 |
| 16, 10 m, off, low load (A3) | 2 | 58.61–58.92 | 273.7–280.8 | 437.9–452.4 | 113.1–120.2 | 25.7–26.8 | 24.4–25.5 | 41.2–42.1 | 88.0–95.2 | 14.7 | 159–162 | 2.77–2.80 | 0/178, 0/162 | 1.9, 1.9 |
| 16, 10 m, on, low load (A3) | 2 | 59.70–59.86 | 267.7–279.9 | 377.5–398.9 | 66.8–72.2 | 26.1–29.2 | 25.0–27.5 | 35.1–38.2 | 80.8–90.7 | 11.2 | 130 | 2.18–2.20 | 0/172, 0/130 | 1.6, 1.5 |
| 16, 10 m, on | 2 | 58.92–59.80 | 285.3–343.5 | 403.2–446.5 | 70.7–71.8 | 29.0–34.1 | 28.3–34.1 | 36.5–45.8 | 89.7–92.9 | 12.0 | 119–144 | 2.00–2.49 | 0/147, 0/132 | 5.0, 55.2 |
| 216, 10 m, off | 2 | 1.63–1.68 | 401.0–436.1 | 924.9–994.1 | 291.3–314.9 | 239.4–252.4 | 13.8–14.9 | 203.0–264.1 | 160.1–161.9 | 3.4 | 20.0–21.8 | 16.30–16.81 | 24/41, 28/50 | 11.5, 53.7 |
| 216, 10 m, on | 2 | 2.42–2.48 | 572.7–589.1 | 934.5–961.9 | 121.9–126.1 | 356.7–365.0 | 25.1–25.9 | 217.6–240.7 | 166.3–167.4 | 3.3 | 19.4–20.3 | 10.57–10.69 | 51/57, 61/62 | 23.0, 31.2 |
| 216, 26–32 m, off | 2 | 10.61–12.09 | 400.6–401.5 | 885.1–891.5 | 255.1–264.2 | 202.1–202.6 | 20.8 | 199.8–229.5 | 55.2–56.2 | 3.0 | 54.3–54.7 | 5.76–6.67 | 0/123, 0/83 | 28.9, 22.9 |
| 216, 26–32 m, on | 2 | 23.65–28.12 | 528.3–528.8 | 777.4–787.6 | 64.8–69.6 | 249.5–261.1 | 31.7–33.6 | 143.5–148.7 | 57.1–60.5 | 2.6 | 42.5–44.2 | 1.93–2.25 | 0/132, 0/160 | 18.9, 20.2 |

Uninstrumented (L0, X925, 2 runs each): 0 viewers 221.8–232.6 ms/s tick WASM, DB thread 228.8–238.4; 16 viewers off: DB thread 443.1–453.0, views 105.8–110.8, 57.7–58.4 ticks/s, 13.4 ms/s per viewer (about 151 µs/s per pair at L1's 88.6 in sight); on: DB thread 420.0–425.2, views 72.2–72.6, 59.1–59.3 ticks/s, 11.8 ms/s per viewer (about 133 µs/s per pair). Part B's law-off arms on the laws build add two more L1 runs of every "on" arm at low load (1.5–2.1): 16 viewers 128–144 µs/s per pair (2.16–2.43 per tick); 216 at 10 m 2.54–2.66 ticks/s, 9.78–9.80 µs per pair-tick; 216 at 26–32 m 26.9–28.5 ticks/s, 1.75–1.94 µs per pair-tick.

What the series says:
- **At 16 viewers** the per-viewer cost is 11.2 ms/s at low load (L1, series A3; 11.8 at L0, 12.0 in the first series) with the copy tables, against 14.7 (13.4 at L0) without. Series A3 was run after the others at host load 1.4–1.9, to replace two first-series 16-viewer runs taken at load 33–55; the per-pair figures above use each series' own 0-viewer arm. Views fall from 112–120 to 67–72 ms/s. In the low-load series the tick WASM did not rise with the copy tables (274–281 off, 268–280 on), within the spread; the first series showed +12..+30 ms/s. Of 11.2 ms/s per viewer (A3, on): views 4.2–4.5, the call's remainder 1.8–2.0, sweeps 1.6–1.8, frames 1.5–1.7, and the rest (about 2) is the extra fighting the viewers draw (the census rises from about 130 to about 158 engaged).
- **At 216 viewers on the 10 m ring** every viewer sweeps in every tick (a tick takes about 400 ms). The copy tables raise ticks from 1.6–1.7 to 2.4–2.5; the sweeps then cost 357–365 ms/s (690 µs a sweep, 4.1 µs per creature in sight), and the keep-alive's heals wait behind ticks (51–61 deaths a window with the tables on, 24–28 off, because the faster world fights more).
- **On the 26–32 m ring** the copy tables more than double the tick rate (10.6–12.1 → 23.7–28.1), with no deaths. Views fall from 255–264 to 65–70 ms/s and the remainder from 200–230 to 144–149. Sweeps are then the largest viewer cost: 250–261 ms/s, about 240 µs a sweep at about 58 in sight.

### Part B: the fighters' scheduling laws

**The laws** (`living/rules/src/script.rs` `Laws`, `living/scripts/skills.rhai`; value-only, `ValueOnly::Delivery` in `VALUE_ONLY` like the delivery laws, so switching is one `law_override` row read at the next tick with no install: `law_override_check::the_fighters_scheduling_laws_are_value_only`):
- `fighter_bystander_wakes` (bool, on as before; dev-box's (c) in docs/BATTLE_LAWS.md, whose prototype on its branch is the same rule; these runs used this branch's earlier name for it, `fighter_bystander_wake_cadence`, true meaning off): off, a creature on the combat cadence is not woken as a bystander (`common::wake_bystander`, and a held-back wake when it falls due). "On the cadence" means `mind_state.fast_until` reaches at least one cadence period ahead (`common::on_cadence`), so its next cadence evaluation is sure to come. That evaluation sees what happened. The percept is written at once either way, and a party to an act (its subject, or the one it is done to) is woken at once.
- `combat_eval_hz` (number, 15): creatures in a fight are evaluated every `round(60 / combat_eval_hz)` ticks, staggered by id (`Laws::combat_every_ticks`; 15 → 4 ticks as before, 10 → 6, 7.5 → 8).

Both govern the scheduling of graph evaluations, and both apply to every character on the combat cadence. **For players:** a player's character in a fight is evaluated on the same cadence, but what it evaluates is its waiting or command graph (`human_act`). Its skills (`use_skill`, `release_skill`) start when the player asks, so these laws do not change what a player can do or how fast. At 10 or 7.5 Hz a command graph in a fight (approach and strike) re-plans every 6 or 8 ticks instead of 4, up to 133 ms later. What a player perceives of the world is unchanged; what changes is how AI opponents behave (below).

**Exactness, off.** `det_compare.py` (two builds stepped from one copied world under `det_clock`; every table's hash every tick and every row at the stop):
- the rotated build against the laws build with every new law off (Cullet battle, 3,600 ticks, 113 tables, 48,431 rows): identical;
- with 16 players on a 10 m ring (dev-box's player mode, main 0c14a944): main against this branch with every new law off and the no-rotation control (`LIVING_DET_NOROTATE`): identical over 1,800 ticks (48,446 rows at the stop). The branch against itself with moved hash keys: identical. The rotation against the control: identical until tick 119, the third tick it reordered anything, with the same due set (10 due, start 9) in every tick up to there;
- **negative control:** a temporary build that adds 1 to one creature's `max_hp` at tick 900, and nothing else (`LIVING_DET_PLANT`, never committed). Reported: first difference at tick 900, in `vitals` alone, and in `vitals` at the stop.

**A/B** (laws build, L1, X925, 2 runs per arm and state, interleaved; `law_override` set at publish). "Engaged" is the cadence census: `eval:combat_due` × ticks between evaluations ÷ ticks per second.

| Arm | Law state | Ticks/s | Tick WASM ms/s | `tick.combat` ms/s | `tick.wakes` ms/s | Engaged | Tick WASM µs per engaged fighter-s | `tick.combat` µs per engaged fighter-s | Cadence evals/s | Fighters' woken evals/s | Wakes left to the cadence/s | Pair µs/s | Pair µs/tick | Load |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0 viewers | as shipped (15 Hz) | 60.00 | 191.6–247.9 | 95.3–117.4 | 31.0–41.3 | 130 | 1,471–1,904 | 732–901 | 1,913 | 210 | 0 | – | – | 16.7, 1.7 |
| 0 viewers | bystander wakes off | 60.00 | 202.9–257.1 | 107.4–129.2 | 28.1–37.9 | 136 | 1,474–1,905 | 780–957 | 2,010 | 192 | 194 | – | – | 20.8, 1.8 |
| 0 viewers | 10 Hz | 59.99 | 180.4–255.0 | 80.8–109.9 | 31.8–46.1 | 140 | 1,284–1,839 | 575–793 | 1,359 | 226 | 0 | – | – | 28.6, 1.3 |
| 0 viewers | 7.5 Hz | 59.98 | 166.2–205.7 | 61.0–73.4 | 33.6–41.9 | 130 | 1,277–1,580 | 469–564 | 955 | 207 | 0 | – | – | 14.9, 1.4 |
| 16, 10 m | off | 59.55–59.74 | 285.8–313.6 | 113.1–118.2 | 35.4–41.4 | 159 | 1,800–1,979 | 712–746 | 2,309 | 258 | 0 | 128–144 | 2.16–2.43 | 9.3, 1.5 |
| 16, 10 m | bystander wakes off | 59.74–59.81 | 272.5–296.2 | 105.1–118.5 | 30.6–33.6 | 153 | 1,812–1,901 | 699–760 | 2,247 | 203 | 345 | 112–133 | 1.88–2.24 | 13.1, 1.9 |
| 16, 10 m | 10 Hz | 59.46–59.56 | 257.4–282.9 | 80.9–93.1 | 33.0–36.5 | 158 | 1,672–1,741 | 526–573 | 1,527 | 263 | 0 | 110–130 | 1.87–2.21 | 6.9, 1.6 |
| 16, 10 m | 7.5 Hz | 59.18–59.61 | 249.4–288.1 | 70.5–81.3 | 34.3–42.8 | 159 | 1,563–1,827 | 442–515 | 1,152 | 265 | 0 | 124–150 | 2.09–2.56 | 7.6, 2.8 |
| 216, 10 m | off | 2.54–2.66 | 574.2–600.1 | 12.3–12.6 | 41.5–43.0 | 293 | 1,979–2,025 | 42–43 | 120 | 341 | 0 | 19.2–20.4 | 9.78–9.80 | 18.8, 2.0 |
| 216, 10 m | bystander wakes off | 2.66–2.83 | 598.8–600.5 | 15.7–16.2 | 35.4–35.8 | 293 | 2,028–2,063 | 53–56 | 165 | 206 | 2,736 | 19.9–21.0 | 9.62–9.70 | 19.7, 3.3 |
| 216, 10 m | 10 Hz | 2.74–2.87 | 599.9–604.1 | 11.4–11.5 | 39.9–41.4 | 301 | 1,996–1,998 | 38 | 92 | 336 | 0 | 19.8–19.9 | 8.76–9.14 | 12.4, 3.4 |
| 216, 10 m | 7.5 Hz | 2.64–2.89 | 598.9–603.3 | 8.3–8.9 | 39.5–40.5 | 289 | 2,000–2,173 | 28–32 | 69 | 292 | 0 | 19.3–20.6 | 8.76–8.99 | 29.4, 2.4 |
| 216, 26–32 m | off | 26.94–28.46 | 504.2–522.3 | 57.9–65.3 | 49.3–49.9 | 151 | 3,388–3,413 | 389–427 | 988 | 241 | 0 | 40.6–42.5 | 1.75–1.94 | 18.7, 2.1 |
| 216, 26–32 m | bystander wakes off | 26.47–29.33 | 508.4–515.5 | 56.8–70.0 | 40.1–46.6 | 155 | 3,269–3,328 | 365–452 | 1,037 | 192 | 317 | 39.1–40.8 | 1.71–1.85 | 9.7, 4.4 |
| 216, 26–32 m | 10 Hz | 25.77–28.13 | 511.6–515.5 | 50.5–51.0 | 48.8–51.3 | 164 | 3,059–3,226 | 300–322 | 690 | 265 | 0 | 40.4–42.0 | 1.80–1.92 | 3.2, 9.0 |
| 216, 26–32 m | 7.5 Hz | 27.44–30.36 | 504.1–508.6 | 39.9–43.2 | 50.6–51.0 | 161 | 3,116–3,188 | 244–273 | 550 | 251 | 0 | 41.9–42.6 | 1.64–1.80 | 5.6, 3.9 |

Reading it:
- **`combat_eval_hz`.** The cadence evaluations fall in proportion (1,913 → 1,359 → 955 a second at 0 viewers) and `tick.combat` per engaged fighter-second by 16% at 10 Hz and 37% at 7.5 Hz (means; the first reps ran at load 15–29). Woken evaluations do not rise to fill the gap (207–226 a second against 210). The AI tick falls about 7% (10 Hz) and 15% (7.5 Hz) per engaged fighter-second. At 160 engaged fighters that is about −20..−29 and −40..−48 ms/s of a 60 Hz second (the 16-viewer arm: `tick.combat` 115.7 → 87.0 and 75.9 ms/s). At 216 viewers on the 10 m ring the saturated world ran 6–8% more ticks under every law state, the wake law included, so that is the arm's spread rather than this law. On the far ring the gain is within the spread.
- **`fighter_bystander_wakes` off.** 194–2,736 bystander wakes a second are left to the cadence, and the fighters' woken evaluations fall from 210–341 to 192–206 a second. `tick.wakes` falls 3–7 ms/s. The tick as a whole does not move measurably, because most of a fighter's wakes are as a party (threats aimed at it), which the law keeps. The diagnosis's −23 ms/s counted every woken evaluation of a fighter, parties included.
- **Per pair** neither law moves the viewers' cost: they schedule AI evaluations only. The differences in the pair columns are within the spread of the off arm.

**At a sustained 200 fighters** (the table above is on the thinning fixture: the cadence census falls from about 180 to about 90 over a 0-viewer window). `battle_viewers.py --keep-fighters 1` (built on this branch) counts the fighters alive every second and replaces the dead one for one with `spawn_battle`. The newcomers get the same profile (a spear, the fight graph) and are placed within the site's 7 m. This is a respawn the game does not have, as `battle_diag.py`'s refills are; it keeps deaths and their witnessed events in the fight, where reduced damage would remove them. About 2.0–2.6 refills a second. Fighters alive at every census: 191–200, a mean of 195.9–197.9 in every run. The cadence census (fighters plus viewers under attack) at the window's first 5 s, mean and last 5 s is given per arm. Laws build, L1, X925, 2 runs each, interleaved, series `partS-1120`, host load 1.8–7.5 (one run 13.0).

| Arm | Law state | Cadence census start → mean → end | Ticks/s | Tick WASM ms/s | DB thread ms/s | `tick.combat` ms/s | `tick.wakes` ms/s | Fighters' woken evals/s | Wakes left to the cadence/s | Pair µs/s | Pair µs/tick |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 viewers | as shipped | 210–212 → 210–212 → 208–215 | 59.93–59.98 | 321.0–321.0 | 337.4–339.2 | 160.7–161.8 | 48.9–49.2 | 337–344 | 0 | – | – |
| 0 viewers | bystander wakes off | 207–214 → 209–212 → 206–208 | 59.94–60.04 | 307.8–311.9 | 324.4–328.5 | 158.2–162.3 | 41.9–44.6 | 307–314 | 283–309 | – | – |
| 0 viewers | 10 Hz | 211–213 → 209–213 → 201–204 | 59.95–60.01 | 263.8–268.2 | 280.9–284.6 | 115.1–122.0 | 44.1–44.6 | 331–350 | 0 | – | – |
| 0 viewers | 7.5 Hz | 195–216 → 211–212 → 205–214 | 59.94–59.96 | 255.9–256.0 | 270.6–272.9 | 99.4–100.7 | 48.2–48.6 | 340–348 | 0 | – | – |
| 16, 10 m | as shipped | 227–230 → 226 → 204–221 | 57.30–57.81 | 391.5–429.2 | 525.5–561.9 | 156.3–168.3 | 45.8–55.1 | 365–372 | 0 | 89–112 | 1.65–2.09 |
| 16, 10 m | bystander wakes off | 224–225 → 224–226 → 224–225 | 56.93–58.62 | 404.8–413.0 | 541.0–553.5 | 160.3–165.4 | 47.0–47.5 | 321–324 | 553–644 | 114–122 | 2.15–2.16 |
| 16, 10 m | 10 Hz | 228–232 → 226–228 → 221–230 | 58.31–58.48 | 375.5–379.9 | 519.4–532.9 | 122.1–123.7 | 51.3–52.1 | 374–375 | 0 | 117–118 | 2.05–2.10 |
| 16, 10 m | 7.5 Hz | 224 → 222–225 → 224–227 | 58.37–58.74 | 339.2–339.8 | 479.4–487.2 | 96.5–97.3 | 48.4–50.6 | 366–368 | 0 | 106–110 | 1.88–1.92 |
| 216, 26–32 m | as shipped | 121–147 → 223–231 → 163–178 | 13.93–16.23 | 562.2–597.7 | 832.6–884.4 | 52.0–59.7 | 58.3–58.7 | 326–357 | 0 | 31.1–34.6 | 3.09–3.40 |
| 216, 26–32 m | bystander wakes off | 102–125 → 233–237 → 207–215 | 14.73–15.64 | 597.0–599.2 | 881.1–892.6 | 60.3–63.7 | 51.4–52.2 | 298–304 | 630–697 | 34.0–34.6 | 3.17–3.31 |
| 216, 26–32 m | 10 Hz | 131–140 → 238–243 → 206–246 | 15.87–16.32 | 588.7–590.7 | 872.1–882.7 | 49.0–49.5 | 58.4–63.4 | 357–359 | 0 | 37.8 | 3.12–3.21 |
| 216, 26–32 m | 7.5 Hz | 119–128 → 237–240 → 209–216 | 15.60–16.83 | 585.3–590.2 | 870.8–887.3 | 37.5–39.9 | 61.9–62.4 | 356–357 | 0 | 36.6–37.0 | 2.91–3.11 |

(At 216 the census's first 5 s read low because the tick rate then differs from the window's mean, which the census divides by. The keeper's count of fighters alive held 193–200 throughout.)

The gain at a sustained 200:
- **`fighter_bystander_wakes` off: −11 ms/s at 0 viewers** (tick WASM 321.0 → 309.9, DB thread 338.3 → 326.4; −3.5%). Of that, `tick.wakes` −5.8 ms/s, with 283–309 bystander wakes a second left to the cadence and the fighters' woken evaluations 341 → 310 a second. This corrects the diagnosis's −23 ms/s: that figure counted every woken evaluation of a fighter (`wake.eval.fight`), and most of them are as a party, which the law keeps. At 16 and 216 viewers the change is within the spread.
- **`combat_eval_hz` 10: −55 ms/s** (321.0 → 266.0, −17%; `tick.combat` 161.2 → 118.5). **7.5: −65 ms/s** (→ 255.9, −20%; `tick.combat` → 100.1). At 16 viewers: −33 and −71 ms/s of tick WASM, −18 and −60 of the DB thread. At 216 on the far ring: ticks 15.1 → 16.1 and 16.2 (+7%), per pair per tick 3.25 → 3.17 and 3.01.
- **Per pair** neither law changes the viewers' own cost: the per-pair columns subtract the same law state's 0-viewer arm, and they move within their spread (16 viewers 89–122 µs/s across all four states).

**Behaviour** (`behave_det.py`: one det template per battle, copied once per law state, stepped under `det_clock` at exactly 1/60 s a tick whatever the server's speed; `skill_use` and `fight_seen` read every second and merged; 3 battles (Cullet, `spawn_battle` 200, even ids dodge and odd ids block when threatened), 55 s of game time each from the fifth second, 0 viewers, A725 cores. Real-time runs on the loaded slow cores ran at 49–58 ticks/s and varied more between runs than between laws, so they are not used.)

| Measure (3 battles) | As shipped (15 Hz, woken) | Bystander wakes off | 10 Hz | 7.5 Hz |
|---|---|---|---|---|
| Attacks met by a block or dodge decided before they resolved | 63.6% | 64.0% | 64.0% | 63.3% |
| Reaction: from the attack's windup start to that decision, p50 / p90 ms | 17 / 567–583 | 17 / 567–583 | 17 / 567–583 | 17 / 567–600 |
| Reaction mean, ms | 169–177 | 170–178 | 170–187 | 175–186 |
| From the end of a fighter's own move to its next decision, p50 / p90 ms | 317–333 / 1,300–1,450 | 317–334 / 1,334–1,400 | 350 / 1,350–1,433 | 317 / 1,517–1,566 |
| Blows: hit / blocked / dodged / missed | 52.4 / 32.0 / 10.7 / 4.8% | 52.5 / 32.8 / 10.0 / 4.8% | 53.2 / 31.2 / 10.0 / 5.7% | 52.6 / 30.6 / 11.7 / 5.1% |
| Hits taken per fighter | 5.53–5.84 | 5.47–6.03 | 5.29–6.17 | 5.53–5.78 |
| Deaths in 55 s | 98–100 | 90–107 | 87–101 | 91–97 |
| From a fighter's first blow to its death, p50 s | 26.1–31.6 | 24.3–27.2 | 26.8–29.3 | 26.2–30.4 |
| Turns to face (uses) / attacks begun | 1,075 / 12,101 | 975 / 11,867 | 975 / 11,848 | 1,024 / 12,294 |

**What changes for fighters, and what a player would notice:**
- **Reaction to an attack aimed at oneself** does not change under any of these laws. The attack's windup wakes its target as a party, and the target decides in the next tick (p50 17 ms) whatever the cadence.
- **`combat_eval_hz`** slows everything else a fighter does between threats: choosing and closing on a target, turning to face, starting the next attack once recovered. At 7.5 Hz the slow tail between moves is about 11% longer (p90 1,517–1,566 against 1,300–1,450 ms). Blocks fall 1.4 points (more blows land or are dodged, not blocked), and at 10 Hz misses rise from 4.8% to 5.7% (strikes started at a target that moved). A player fighting AI would meet opponents that retarget and close later: evaluated every 100 ms (10 Hz) or 133 ms (7.5 Hz) instead of every 67. Their defence against the player's own strikes is unchanged. Not recommended unless the budget still fails after the rest (as the diagnosis said); if it is used, 10 Hz costs the least behaviour for about −25 ms/s.
- **`fighter_bystander_wakes` off**: nothing measured in this fight. In a fight graph that reacts to others (an ally struck, a death seen), that reaction would come at the fighter's next cadence evaluation, up to 50 ms later at 15 Hz. A player would see AI bystanders in a fight turn to what happened near them up to 50 ms later. Its gain is about 11 ms/s at a sustained 200, so it is not worth a rule change on its own.

### Next: tick body and module memory (Part C)

One row per option, for the owner note. Gains are at the fixture's arms (pinned X925; ms/s of the database thread unless marked). "Exact" means nothing a player or mind perceives changes, nor when; "law" means it would need the owner's decision.

| # | Option | Where | Gain (measured or estimated, with its source) | Risk | Exactness | What a player notices |
|---:|---|---|---|---|---|---|
| 1 | **Keep each viewer's `heard` rows in module memory across ticks** (built: `sweep_keep_memory`, diagnostic, off) | `perception::hear`, `HEARD_KEPT` | Measured (L2, 2 runs each): `hear.read` 17.1–17.7 → 1.1 µs a sweep at 16 viewers, 6.9–7.2 → 0.6 at 216 on the far ring. Before: `hear.read` was 17–23 µs a sweep at 16 viewers and at 216 on the 10 m ring, 6–7 µs on the far ring (Step 2's T6): about 1.4 ms/s at 16 viewers, 7–12 ms/s at 216 | Low: `hear` and `forget` are the only writers of `heard`. Memory is cleared on a skipped or repeated tick and outside the tick, and read afresh every 150 sweeps | Exact in practice: 0 of 31,313 kept lists differed from the table (`sweep_keep_check`, 16 and 216 viewers). Exact by construction while one instance runs every tick; another instance's write is caught at the next refresh | Nothing |
| 2 | **Keep creatures' health readings across ticks** (built, same law) | `perception::health_now`, `VITALS_KEPT` | Measured (L2): the change test (`project.test`) 62.7–72.9 → 53.7–54.1 µs a sweep at 16 viewers and 26.2–27.6 → 22.2–23.6 at 216 on the far ring; `vitals` reads 64–69 → 2.2–2.4 a sweep (16) and 6.9–7.5 → 0.2 (216). Whole sweep with row 1: 339–378 → 346–353 µs at 16 (in sight 78–93 against 90–93), 239–247 → 226–232 µs at 216 on the far ring. At L1, per sweep per creature in sight 4.08–4.34 → 3.84–4.31 µs at 16 viewers, 3.68–3.78 → 3.72–3.91 at 216 on the 10 m ring (none), 3.86–3.96 → 3.61–3.68 on the far ring (−7% per creature; per sweep 230–237 → 224–236 µs, about −1..−7 ms/s at 1,080 sweeps a second) | Medium: a `vitals` row is written in many places (needs settled at evaluations, breath, eating) and only `health_moved` marks it. A missed write stands until the reading is renewed (60 ticks) | **Inexact**: the kept reading's raw health differed from the table's in 13–14% of 392,155 comparisons. Its band never differed (0), so no row a player sees changed. The exact-health rows (one's own, a reveal) are written by `health_moved` at once anyway | Nothing measured; a revealed exact health could lag up to 1 s between blows |
| 3 | Rows 1–2 extended to the viewer's `perceived` rows (each sweep reads all of them to diff against what it sees) | `perception::sweep_one` | Estimated −20..−30 µs a sweep at 160 in sight (the read part of `rows.out` + `rows.in`, 102–113 µs at 216 r10, Step 2's T6; reads about 0.2 µs a row from `hear.read`), about −10..−16 ms/s at 216 on the 10 m ring, −1.5 ms/s at 16 | Medium: `perceived` is also written by joins, deaths and `sweep_now`; each needs a mark | Exact while every writer marks it (the `KEPT` rule), bounded by a refresh | Nothing |
| 4 | Frames take the sweep's band and health instead of reading them again (`show_fighter` reads back the band just written for each newcomer; `deliver` reads health again) | `frame.rs` (dev-box) | Step 2: part of `project.show` (59–66 µs a sweep at 216 r10) and of `tick.frames` (25–34 ms/s at 16 viewers with the copy tables) | Low | Exact (same values, no write between) | Nothing |
| 5 | **The call's remainder** (commit, read-set upkeep, subscription evaluation): 36–46 ms/s at 16 viewers (about 2.0–2.6 ms/s per viewer), 144–149 on the far ring and 218–241 on the 10 m ring at 216 | SpacetimeDB 2.14.1 host | Unknown until split: needs a host profile (`perf` on the database thread of our own container). The copy tables already cut it from 200–230 to 144–149 on the far ring | – | – | – |
| 6 | **Sweeps themselves**: 250–261 ms/s at 216 on the far ring, 357–365 on the 10 m ring, about 4.1 µs per creature in sight, mostly row writes (projections, perceived rows, copies) | `perception.rs` | Exact work found little more (Steps 2 and 3). Fewer pairs or fewer refreshes are BATTLE_VIEWERS's option C (a bounded far tier: pairs per viewer from about 160 to about 32, about 5×) and option D (a far cadence that follows density) | – | **Law** (C changes what a player perceives of far fighters; D, when) | Far fighters shown as crowd rows (C), or refreshed less often (D) |
| 7 | `combat_eval_hz` 10 (built, off) | `tick.rs` | −55 ms/s at a sustained 200 (tick 321 → 266, −17%); per pair nothing; 216 on the far ring +7% ticks | Low (one value) | **Law** | AI opponents retarget and close up to 33 ms later than at 15 Hz (every 100 ms instead of every 67); more misses (4.8 → 5.7%) |
| 8 | `combat_eval_hz` 7.5 (built, off) | `tick.rs` | −65 ms/s at a sustained 200 (→ 256, −20%); per pair nothing; 216 on the far ring +7% ticks | Low | **Law** | Evaluated every 133 ms instead of every 67; slow tail between moves about +11%; blocks −1.4 points |
| 9 | `fighter_bystander_wakes` off (built; on as shipped) | `common.rs` | −11 ms/s at a sustained 200 (−3.5%; the diagnosis's −23 corrected); per pair nothing | Low | **Law** | AI bystanders in a fight turn to others' acts up to 50 ms later |
| 10 | The skill script's pool check run natively before Rhai when the plan's first test is the pool (`check.rhai` 21 µs for about 570 "out of breath" refusals a second, Step 3) | `act.rs` / `skills.rhai` | Up to about −12 ms/s at 0 viewers (L2's 17 ms/s for the Rhai check, of which the breath refusals are about 70%) | Medium: the native test must equal the script's for every skill, and the script is the world's (a world may change it) | Exact only if the native test is derived from the script's spec and checked against it (a `_check` law) | Nothing |

**Module memory across transactions.** SpacetimeDB says module memory is not kept between reducer calls: "Relying on global variables, static variables, or module-level state to persist across reducer calls is undefined behavior", because "SpacetimeDB may run each reducer in a fresh WASM or JS instance", and "if you modify global state and then roll back the transaction, the modified value may remain for subsequent transactions" ([reducers](https://spacetimedb.com/docs/functions/reducers/), "Global and Static Variables Are Undefined Behavior", docs 2.0.0, read 2026-11-20; the pinned server is 2.14.1). `KEPT` (docs/PERCEPTION.md, "Module memory and rollback") is built for that:
- what it keeps only stands in for a read, and an empty memory is always correct;
- `SWEPT_TICK` clears it whenever this instance's sweeps skip a tick (another instance ran one) or see one again (it rolled back);
- a sweep outside the tick (`sweep_now`, a join) leaves nothing kept for that viewer;
- a mark another instance made and this one missed stands at most `KEPT_REFRESH_SWEEPS` (150 sweeps, about 30 s);
- the `memory_test` law proves the rollback cases in scenes.

`HEARD_KEPT` and `VITALS_KEPT` follow the same rules: cleared with `KEPT`, removed by `forget` and outside the tick, and read afresh every 150 sweeps (heard) or 60 ticks (vitals). The heard keep is exact while one instance runs the ticks, because only the sweep and `forget` write `heard`. The health keep is inexact by design, because most `vitals` writes do not mark it.

**What this says about the next order of magnitude.** The reads that cross transactions are small (rows 1–3 together about 5–10% of a sweep). What remains per viewer is row writes in the sweep, views and the call's remainder, and all three go with pairs × refreshes. The exact rows here (1, 3, 4, 10) together might take 30–50 ms/s at 216 viewers and 15–20 ms/s at 16, about 12 of it the pool check, which does not grow with viewers. A 13–20× gap per pair needs option C or D (row 6), the owner's decision.

### Proofs

- **Exactness:** `det_compare.py` as above (no players: main = no-rotation control, the rotated build = the laws build with every new law off; 16 players: main = this branch with the laws off and no rotation, branch = branch with moved hash keys; the negative control caught at tick 900 in `vitals`).
- **Scene gate** (`scene_gate.py run --base 1511d5e8 --force --no-main-check` on the private `slop-battlelaws-gate-20261120`, A725 cores, head 35a8c4c8 before the history was squashed into 11f5db8c: the same authority and rules code but for two shorter comments in `skills.rhai`): passed. verify-core `tick`, `sight`, `senses`, `refusal`, `skirmish`, `mechanics`; verify-player `combat`; verify-client `cues`, `motion_tables`, `copy_privacy`; verify-minds `roundtrip`, `acts`, `dealings`, `conversation`; `mind-unit`; generation on world, island and Cullet. Evidence `.local/living/verify/gate-1120093433-0e6503*`.
- **Genesis fuel** (the gate's fresh publishes, same server and checkout; main 1511d5e8 measured the same way): Part D alone is identical to main on every seed (island 11.568e9, Cullet 37.363e9, cullet-laws 37.259e9, plan-test 11.527e9, world 11.478e9). With the four new laws: Cullet +0.28% (37.468e9; the script's law descriptions are read at each compile and Cullet compiles its composed script more often), cullet-laws +0.05%, island +0.05%, plan-test and world −0.01..+0.01%. Shorter comments changed nothing (37.471e9 → 37.468e9). Every seed keeps 68.8% or more headroom.
- `cargo test -p living-rules`: 359 passed (the new laws' defaults, clamps and `combat_every_ticks`).
- `just living-check` on the merged head c853eec8 (the same tree as 11f5db8c but for docs): ok (1,094 s; the known red `look::tests::the_island_wears_the_pool` as on main).

### Evidence

`~/slop-evidence/battle-laws-20261120.tar.zst` and `.sha256`: every run directory of the series (`partA-1120-0915`, `partA2-1120` (L0), `partA3-1120` (low-load reruns), `partB-1120`, `partC-1120` (L2 split), `partS-1120` (sustained 200)), the rollups (`rollup.py`, `rollup_b.py`, `partA.json`, `partB.json`, `partB.md`), the behaviour runs (`behdet/t1–t3`, `behave.py`, `behave_det.py`, `behaviour.json`), the keep check (`keepcheck/`), the det comparisons (`.local/bl/det/*`), the gate logs and the wasm builds.

### Not covered

- A sustained 200-fighter battle: the fight thins, so engaged counts differ between runs. Part B normalizes per engaged fighter-second.
- Minds connected, and real clients' input and frame pacing.
- The 30-minute and 8-hour gates.
- The split of the call's remainder (needs a host profile).
- Behaviour with players fighting AI under the laws (the behaviour runs are AI-only); behaviour in fight graphs that react to bystander events.
- One host. Nothing here establishes acceptance or capacity.
