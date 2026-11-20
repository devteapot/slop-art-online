# Combat phase: where a dense battle's tick goes, and a plan for 60 Hz with players watching

Status: diagnosis and plan, 2026-11-20, branch `combat-phase` (Spark), cut from `origin/main` `0e310415`. Nothing here changes behaviour. The branch adds profiling spans and counters that run only while profiling with the `profile_detail` law, plus measurement tooling. The fixes below are proposals; each needs its own branch, and the ones marked **law** also need the owner's separate approval.

The [performance contract](PERFORMANCE_CONTRACT.md) asks for 200 local fighters at 60 Hz with players watching (immediate gate: 216 characters for 30 minutes). This note answers two questions on the agreed fixture: (a) what the AI-only battle costs, span by span, and whether that work is per fighter or per pair; (b) what the viewers add, per viewer and per pair. It then orders the fixes.

## In short

- **(a) Without viewers the battle is not the blocker.** On a fast core (X925) the AI-only tick holds 60 ticks/s.
  - Uninstrumented it uses 208–214 ms of a 1,000 ms second (3.5–3.7 ms a tick; two pinned runs each of main and this branch).
  - With profiling spans it uses 240–270 ms/s: tick p50 3.6–4.2 ms, p99 8–10 ms, at most 5 late slots a minute.
  - The fighters' 15 Hz evaluations are the largest part (57% with spans). Their cost is per fighter: 61–70 µs an evaluation at about 142 engaged fighters and 69–72 µs at about 70. Nothing measured grows as fighters squared at this density. The scans of the crowd (scenes, nearest target) cost about the same per call with 48 or 84 creatures in a scene, and a blow has about 25 onlookers with 70 or 140 fighters. The tick is about 1.5 ms per engaged fighter-second uninstrumented (1.8 with spans). The fight thins without refills (about 190 → 100 engaged over the window). At a sustained 200 the tick body would be about 300 ms/s uninstrumented.
- **(b) The viewers are the blocker, and their cost goes by (viewer × creature in sight) pairs.** At 16 viewers on the 10 m ring the world still runs at 59 ticks/s, but with 56–99 late slots a minute and a tick p99 of 11–13 ms. Each viewer adds about 12.4 ms/s to the database thread. That splits into views 6.7, the whole call's remainder (commit, read sets, subscription evaluation) 2.2, sweeps 1.7, frames 1.6 and cues 0.2 ms/s. That is about 130 µs a second for each pair. At 216 viewers on the same ring each viewer sees about 160 creatures, about 35,000 pairs. The thread saturates at 1.7–1.9 ticks/s (five pinned runs), with a tick taking about 530 ms: tick WASM 445–459 ms/s (perception sweeps 275), views 302–313 ms/s, and about 200 ms/s of the remaining overhead. Every reducer, including the keep-alive fixture's `admin_set_vitals`, waits 240–320 ms behind a tick. 16–30 viewers die in each window despite the keep-alive.
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

   **Expected from 5–6 (exact):** about 30–45% of the sweep. Sweeps go from about 1.7 to about 1.0 ms/s per viewer.

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
