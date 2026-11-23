# Why the 216 gate case collapses in a 30-minute run

Status: **diagnosis and mechanical fixes, 2026-11-23, Spark (X925).** The measuring code is on branches `growth-diag-main` (main's direct arm with the human-fighter driver) and `growth-fix-relay` (the recorded relay build with the fixes), never for main. The fixes are on `growth-fix`, on main `62fccc74b` (which has `humans-map`).

The gate case passes 60 s windows on X925 ([HUMAN_FIGHTER_COST.md](HUMAN_FIGHTER_COST.md) §9), but a 30-minute run degraded and then collapsed in both earlier tries: ticks/s by 5-minute block 59.7 → 58.3 → 57.3 → 56.1 → 52.8 → 16.5.

## Bottom line

**Two effects, both from corpses piling up in the battle's chunks and hot paths that walk every structure near a spot.** Each death leaves a `remains` structure where the body fell (`act.rs:3082`). A person's remains last 48 game hours in Cullet (`seeds/worlds/cullet/laws.rhai:273`), which is 96 real minutes. At the fixture's ~2 deaths a second, the battle's few chunks held ~3,000 remains by minute 24 of the window.

1. **The collapse is dusk, not a slow crash.** A Cullet day is 48 real minutes and the world starts at 07:00. Dusk eases in from 19:00 (`laws.rhai` `night_hours`), about 24–26 real minutes after the world is made, which falls at minute 22–24 of the window in every run.
   - **The path:** from dusk, Cullet's `glow(a)` law (`laws.rhai:131`) reads `a.actor.lit` for every target of every sight test.
   - **The cost:** each read, once per creature per tick, is `common::lit_at` (`common.rs:1289`). It called `structures_near(at, widest_light)`, which copies every structure in the chunks round the spot, corpses included, sorts them, and keeps the lamps.
   - **Measured, relay arm, minute 22 → 26 → 28:**
     - `sight.player_candidates` per call: 28 → 138 → 222 µs;
     - minds' `scene.sensed`: 54 → 2,351 → 1,614 µs;
     - `join.sweep`: 0.7 → 29 ms;
     - DB thread: 546 → 962 → 958 ms/s;
     - ticks/s: 55.2 → 12.3 → 12.7.
2. **The decline before dusk (59.9 → 55.7 ticks/s, DB 495 → 570 ms/s) is the same pattern by day, in smaller amounts.** These parts grow in step with the `structure` row count:
   - `known::remember_gates` (`known.rs:177`): every structure in 48 m sight copied to find the gates (`known.mark` 9 → 35 ms/s);
   - the skill context's `lit` (`act.rs:312`/`350` → `lit_at`), for skill checks (`act.skill_ctx` 9 → 26, `check.ctx` 5 → 18);
   - minds' and graphs' noticing over every structure in sight (`noticed.structures` 5 → 29; by design, it notices remains);
   - residents' calm evaluations (`wake.eval.calm` 23 → 55, `brain.after` 28 → 80, which holds `known.mark`).
3. **The tables that grow with the dead are mostly memory, not CPU.**
   - Every reader of `line_seen` (+7.6k rows/min), `skill_use` (+2.7k/min), `sex_seen` (+5.5k/min) and `familiar` (+3.1k/min, bounded per actor) goes through a btree index by observer or actor.
   - The server's rows scanned per minute stayed flat (~16 M/min) while the DB thread doubled.
   - The `character` walks are small: `combat::human()` (fixed on main by `humans-map`, ~1 ms a rebuild at 3,400 rows) and housekeeping's once-a-second count (~1 ms/s at 3,800 rows, fixed here).

**What is the fixture's and what a real battle does too.**
- **The fixture's:**
  - the rate, ~2 deaths a second for 30 minutes, each followed 3 s later by a fresh character (gate-load's battle role);
  - all of it in one plaza.
- **Real play does the same at its own rate:**
  - **Remains:** death is permanent, each death leaves remains for 96 minutes in Cullet, and a long battle at a city site builds them up.
  - **Dusk:** it comes every 48 minutes in every Cullet session. From dusk every sight test reads lamplight.
  - **The dead keep rows:** `line_seen` until the person plays another character, and `skill_use` (24 per character) forever.
- **A real 200-character battle with permanent death** leaves at most its own dead, about 200 remains rather than 3,000. The cost per remains was the same. With lamps and houses nearby, the copying of every structure was a cost before any remains.

## 1. Method

**The case:** HUMAN_FIGHTER_COST §6, Cullet: 100 human fighters plus 116 walkers.
- The players read `experience_copy`.
- `series.sh` flags as recorded, `--seconds 1800`, plus `--law tick_marker_on=true --tick-marker --law profile_detail=true`.

**Arms:**
- **Relay, as recorded:** npc-measure `b18402236`, the same binaries as `gate216-marker` (sha256 in `binaries.sha256`).
  - The relay is not on main; it needs the npc-measure/gate-remeasure prototype.
- **Main's direct arm:** main `c5056f2e5` plus gate-driver-main's human-fighter driver (`growth-diag-main` `cd589a5ea`).
- **Relay with the fixes:** `growth-fix-relay` `c2e410ff9`. That is the recorded build plus `humans-map` plus both `growth-fix` commits; the same gate-load and relay binaries.

**Per minute** (`prof.py`):
- A 10 s window with `set_profile` on (L2 spans, `profile_detail`), from second 20 of each minute.
- `/v1/metrics` snapshots before and after it: every table's rows and bytes, reducer wasm time, rows scanned, inserted and deleted, jemalloc, the server's thread CPU by name, cgroup memory.
- The 50 s between windows is unprofiled. Its ticks/s and DB-thread CPU are the figures in the tables.
- `spans.py` gives each window's spans in ms/s; `ticks.py` splits each tick's spans and compares the slowest 5% of ticks with all of them.

**Host:**
- Private `clockworklabs/spacetime:v2.14.1` (`slop-growth-diag`), pinned to the X925 cores 5–9 and 15–19. Drivers, samplers and the poller ran on the A725 cores.
- `battle.lock` held per series, `trial-activity.lock` shared per run.
- The server was stopped by SIGINT between runs, never forced, and its log read first.

**What disturbed the runs:**
- **Relay arm:** minute 9's load reached 26 from outside.
- **Main's direct arm:** an unpinned ML job of another project ran on the X925 cores from minute 2 to about 13. Its own fighters also killed 56 of Cullet's 64 minded residents by minute 13 (they aim at the nearest perceived person). So its growth before minute 14 is not comparable. It is reported as context only.

**Profiling's own cost:** L2 slows the profiled 10 s. The spans are read as relative growth, minute by minute, and the ticks/s and DB-thread CPU come from the unprofiled 50 s.

## 2. The relay arm, minute by minute (as recorded, npc-measure `b18402236`)

Spans are ms/s of profiled window. Ticks/s and DB thread are the unprofiled 50 s before each window. Rows are at the window's start.

| Min | Ticks/s | DB ms/s | Tick p99 ms | `tick` | `sight.player_candidates` | `scene.sensed` | `tick.wakes` | `brain.after` | `known.mark` | `noticed.structures` | `act.skill_ctx` | `check.ctx` | `join.sweep` | `housekeeping` | `structure` rows | `character` rows | `line_seen` rows | `skill_use` rows | `sex_seen` rows | jemalloc MB |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 59.86 | 495 | 12.9 | 409 | 30 | 14 | 43 | 28 | 9 | 5 | 9 | 5 | 1 | 1 | 261 | 405 | 14,807 | 5,156 | 8,349 | 348 |
| 3 | 59.38 | 501 | 13.74 | 412 | 30 | 9 | 52 | 36 | 11 | 8 | 12 | 6 | 1 | 1 | 509 | 655 | 30,676 | 11,089 | 18,443 | 380 |
| 5 | 58.88 | 516 | 13.32 | 412 | 31 | 10 | 51 | 39 | 14 | 10 | 13 | 7 | 1 | 1 | 769 | 907 | 47,131 | 16,898 | 30,042 | 408 |
| 7 | 58.76 | 514 | 18.14 | 423 | 29 | 12 | 62 | 47 | 16 | 15 | 16 | 9 | 1 | 1 | 978 | 1,121 | 60,788 | 22,039 | 39,122 | 443 |
| 9 | 57.51 | 518 | 19.67 | 420 | 30 | 9 | 61 | 47 | 19 | 14 | 17 | 9 | 1 | 1 | 1,223 | 1,364 | 76,151 | 27,472 | 49,201 | 467 |
| 11 | 57.82 | 520 | 20.41 | 414 | 29 | 9 | 64 | 52 | 21 | 17 | 18 | 10 | 1 | 1 | 1,468 | 1,607 | 91,724 | 33,129 | 54,405 | 486 |
| 13 | 57.3 | 535 | 23.94 | 424 | 29 | 8 | 74 | 59 | 23 | 20 | 20 | 12 | 1 | 1 | 1,710 | 1,848 | 107,187 | 38,726 | 64,236 | 505 |
| 15 | 57.31 | 530 | 22.64 | 440 | 29 | 9 | 76 | 64 | 26 | 23 | 22 | 14 | 1 | 1 | 1,965 | 2,102 | 123,656 | 44,568 | 74,655 | 526 |
| 17 | 55.99 | 557 | 28.38 | 439 | 29 | 8 | 77 | 66 | 29 | 21 | 24 | 15 | 2 | 1 | 2,180 | 2,319 | 137,195 | 49,387 | 83,572 | 549 |
| 19 | 56.38 | 548 | 25.99 | 457 | 29 | 9 | 82 | 73 | 32 | 26 | 27 | 16 | 1 | 1 | 2,426 | 2,561 | 152,864 | 55,005 | 89,108 | 578 |
| 21 | 56.69 | 542 | 24.93 | 449 | 29 | 8 | 87 | 77 | 33 | 28 | 27 | 17 | 1 | 1 | 2,671 | 2,805 | 168,292 | 60,532 | 98,595 | 606 |
| 22 | 55.21 | 546 | 32.77 | 467 | 30 | 7 | 87 | 78 | 36 | 26 | 31 | 18 | 1 | 1 | 2,789 | 2,926 | 175,960 | 63,401 | 100,581 | 621 |
| 23 | 55.69 | 570 | 30.4 | 447 | 29 | 7 | 88 | 80 | 35 | 29 | 26 | 18 | 1 | 1 | 2,912 | 3,050 | 183,814 | 66,180 | 105,378 | 623 |
| 24 | 36.98 | 760 | 56.83 | 583 | 31 | 8 | 109 | 83 | 38 | 28 | 43 | 21 | 1 | 3 | 3,041 | 3,173 | 191,893 | 69,088 | 107,333 | 633 |
| 25 | 14.43 | 948 | 116.85 | 737 | 130 | 188 | 275 | 82 | 32 | 31 | 30 | 19 | 48 | 3 | 3,156 | 3,292 | 199,614 | 71,849 | 112,356 | 643 |
| 26 | 12.31 | 962 | 93.92 | 720 | 143 | 230 | 263 | 60 | 27 | 19 | 30 | 20 | 57 | 3 | 3,276 | 3,412 | 206,978 | 74,772 | 111,047 | 651 |
| 27 | 12.23 | 941 | 98.82 | 716 | 226 | 149 | 237 | 58 | 28 | 15 | 30 | 20 | 58 | 3 | 3,406 | 3,538 | 214,934 | 77,513 | 109,296 | 660 |
| 28 | 12.69 | 958 | 99.69 | 749 | 232 | 148 | 236 | 59 | 29 | 16 | 30 | 20 | 35 | 2 | 3,524 | 3,658 | 222,310 | 80,232 | 113,640 | 667 |
| 29 | 11.96 | 967 | 106.04 | 714 | 244 | 125 | 212 | 62 | 29 | 17 | 30 | 21 | 62 | 3 | 3,642 | 3,773 | 230,056 | 82,934 | 114,226 | 674 |

- **Minute 9:** load 26 from outside, one minute.
- **Dusk:** from minute ~22 (19:00 world time); 20:00, half light, falls at about minute 24–25.
- **The collapse's minutes (24–29):** every per-call cost rises. The sight paths rise ×5–40: `sight.player_candidates` per call 28 → 222 µs at the same ~10.5k calls, and `scene.sensed` 54 → 1,614–2,351 µs.
- **Rows scanned:** the server's `spacetime_num_rows_scanned_total` stayed at 15.4–16.5 M a minute until the collapse, and fell with the ticks after it. The earlier `gate216-confirm` run read the same. The growth was not in table scans; it was in walks of module-memory copies of the chunk structure lists.

## 3. Main's direct arm (context)

| Min | Ticks/s | DB ms/s | Tick p99 ms | `tick` | `sight.player_candidates` | `scene.sensed` | `tick.wakes` | `brain.after` | `known.mark` | `noticed.structures` | `act.skill_ctx` | `check.ctx` | `join.sweep` | `housekeeping` | `structure` rows | `character` rows | `line_seen` rows | `skill_use` rows | `sex_seen` rows | jemalloc MB |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 58.56 | 573 | 13.85 | 422 | 31 | 16 | 43 | 27 | 8 | 6 | 9 | 5 | 0 | 3 | 260 | 402 | 14,982 | 5,463 | 7,161 | 373 |
| 3 | 34.83 | 766 | 30.33 | 499 | 32 | 5 | 46 | 31 | 11 | 8 | 16 | 6 | 0 | 5 | 511 | 629 | 30,193 | 10,856 | 5,642 | 426 |
| 5 | 33.68 | 780 | 31.39 | 509 | 30 | 5 | 54 | 33 | 13 | 9 | 19 | 7 | 0 | 4 | 740 | 861 | 44,928 | 16,146 | 12,459 | 466 |
| 7 | 31.72 | 791 | 32.25 | 516 | 29 | 4 | 55 | 36 | 15 | 9 | 23 | 9 | 0 | 5 | 984 | 1,104 | 60,336 | 21,511 | 18,715 | 483 |
| 9 | 27.79 | 834 | 44.49 | 456 | 24 | 3 | 52 | 32 | 16 | 7 | 26 | 10 | 0 | 4 | 1,227 | 1,334 | 75,499 | 26,794 | 14,587 | 598 |
| 11 | 32.45 | 701 | 35.32 | 489 | 32 | 1 | 41 | 30 | 21 | 1 | 26 | 12 | 0 | 5 | 1,449 | 1,540 | 88,279 | 31,595 | 4,313 | 675 |
| 13 | 41.28 | 726 | 15.82 | 406 | 28 | 0 | 32 | 30 | 21 | 0 | 21 | 12 | 0 | 4 | 1,675 | 1,765 | 102,956 | 36,669 | 46 | 735 |
| 14 | 57.89 | 509 | 14.22 | 373 | 25 | 0 | 28 | 29 | 21 | 0 | 18 | 11 | 0 | 4 | 1,796 | 1,889 | 110,194 | 39,291 | 46 | 732 |
| 15 | 58.01 | 530 | 13.81 | 369 | 25 | 0 | 30 | 29 | 21 | 0 | 19 | 11 | 0 | 3 | 1,910 | 2,001 | 117,610 | 41,810 | 46 | 739 |
| 17 | 57.14 | 542 | 13.98 | 386 | 25 | 0 | 31 | 31 | 23 | 0 | 21 | 13 | 0 | 4 | 2,141 | 2,232 | 132,520 | 47,222 | 46 | 752 |
| 19 | 57.69 | 556 | 15.01 | 393 | 25 | 0 | 33 | 33 | 25 | 0 | 23 | 14 | 0 | 4 | 2,385 | 2,477 | 148,175 | 52,675 | 52 | 783 |
| 21 | 57.62 | 555 | 14.28 | 388 | 25 | 0 | 35 | 35 | 27 | 0 | 24 | 15 | 0 | 4 | 2,634 | 2,727 | 163,555 | 58,116 | 56 | 792 |
| 23 | 55.58 | 554 | 15.13 | 398 | 24 | 0 | 38 | 37 | 28 | 1 | 26 | 17 | 0 | 4 | 2,860 | 2,950 | 178,692 | 63,435 | 84 | 794 |
| 24 | 50.5 | 626 | 20.76 | 451 | 24 | 0 | 43 | 40 | 32 | 0 | 32 | 19 | 0 | 5 | 2,991 | 3,077 | 186,413 | 66,078 | 86 | 798 |
| 25 | 21.13 | 844 | 114.46 | 538 | 289 | 32 | 70 | 23 | 19 | 0 | 21 | 15 | 0 | 3 | 3,110 | 3,200 | 194,843 | 69,031 | 87 | 819 |
| 26 | 17.87 | 876 | 60.3 | 674 | 377 | 60 | 85 | 24 | 20 | 0 | 23 | 16 | 0 | 3 | 3,230 | 3,322 | 202,351 | 71,821 | 247 | 852 |
| 27 | 18.42 | 898 | 57.39 | 692 | 447 | 0 | 36 | 25 | 22 | 0 | 23 | 16 | 0 | 4 | 3,358 | 3,445 | 210,197 | 74,507 | 357 | 889 |
| 28 | 18.24 | 898 | 53.57 | 689 | 427 | 42 | 81 | 26 | 22 | 0 | 23 | 19 | 0 | 3 | 3,469 | 3,556 | 217,492 | 77,121 | 371 | 911 |
| 29 | 17.68 | 900 | 54.42 | 700 | 427 | 40 | 78 | 26 | 22 | 0 | 22 | 17 | 0 | 4 | 3,593 | 3,683 | 225,290 | 79,878 | 393 | 933 |

- **Disturbed minutes 2–13:** an unpinned ML job of another project ran on the X925 cores. This arm's own fighters also killed 56 of the 64 minded residents by minute 13: gate-driver-main's battle role aims at the nearest perceived person, while the relay arm's aims from the relay stream. From minute 14 the residents' graphs are mostly gone.
- **The dusk step is the same:** `sight.player_candidates` 24 → 289 → 427 ms/s at minute 25–29, and the DB thread 554 → 900 ms/s. So the step is in the players' sweep (`lit_at` per target), not only in the minds.

## 4. The fixes

### 4.1 Mechanical: the same answers, no walk of every structure (`growth-fix` `e4a83859d`)

- **`common::lit_at`** walks a per-chunk list of the kinds that give light (`common::chunk_few(ctx, chunk, Few::Lights)`).
  - **How the list is kept:** drawn from the chunk's cached structure list, and drawn again when that list is (the same `Rc`) or the script revision changes. That is the pattern `common::chunk_warming` set for warmth (BATTLE_SCALE.md, "Warmth without copying").
  - **Why the answer is the same:** a light reaches no farther than the widest light, and `any` does not depend on order.
- **`known::remember_gates`** walks the gates in sight only (`common::few_near(.., Few::Gates)`).
  - **Why the order is the same:** nearest first, a stable sort of the same subsequence that the full list's stable sort gave.
- **Housekeeping's population count** walks the living through the `alive` index (main, `humans-map`), in id order.
  - **`stats.deaths`** reads a new private `census` row, counted in `act::die_unseen`, the only place a character dies, in the death's own transaction.
  - **Made once:** where the row is missing (a new world, or one from before this table), it is made by a walk of the dead through the index.
  - **Order:** the id order replaces the table's scan order for the old-age and life-stage loop. The two differ only when two such events fall in one second.

### 4.2 Retention: `line_seen` per person, not per character played (`growth-fix` `191ab3fc8`, reported before merge)

- **What `line_seen` holds:** the copies of a player character's last 64 experience lines that its client is shown.
- **What happened to the dead's rows:** they stayed for every character a person ever played, while the `experience` rows they copy already go at death (`act::forget_dead`).
- **The only reader:** `my_experience`, for the person's current character, which is the dead one until they play another (the death screen).
- **The change:** they now go in `perception::set_player` when the person plays another character, beside `outcomes::forget`, which is the same rule `act_outcome` follows (PERCEPTION.md, "Retention").
- **Not evidence:** a trial records experiences from `experience` while it runs (`trials.py`), and no tool reads `line_seen`.
- **Not det-identical** where a scene rejoins with a new character, since the table is hashed.

### 4.3 Proposed, not built

- **`skill_use` of the dead: keep.**
  - **Why:** it is read as evidence after the fact. `trials.py` reads `skill_use WHERE actor = S` at a trial's end, and `arena_report.py` builds exposures from it.
  - **What it is now:** bounded per character (`USES_KEPT`, 24), with no scan over it, about 260 B a row.
  - **If memory matters:** move a character's rows at death into a same-type history table (the archive pattern of the [tables page](https://spacetimedb.com/docs/tables/)), or have long runs export them to the journal.
- **Noticing and minds' scene structures over remains.** `brain::new_structures_in_place` and `perceive::select_scene_structures` walk every structure in sight by design, since remains are noticed and counted. A per-chunk count of stranger remains, or a structure revision per chunk instead of one global, would bound them. That changes no rule but needs its own known-answer check (`notice_delta_check` exists).
- **`sex_seen`:** a mind's row per person whose body it has seen, kept for the observer's life. It is memory by design, but it is unbounded per observer, unlike `familiar` (bounded per actor). Propose a bound by age like `familiar`'s, as a design decision.
- **The global structures revision.** Every death bumps `STRUCTURES_REVISION` and clears every chunk's cache and every viewer's cached scene structures (`perceive::scene_structures`). A per-chunk revision would keep the battle's neighbours' caches.

## 5. The fixes measured at 30 minutes

**The clean run** (`long-relayfix2`, 11:41–12:12):
- the relay arm with `growth-fix-relay` `c2e410ff9`, the same flags as §2;
- host load 3.3–5.4, except a burst of outside work at minute ~19 (every core busy for about 2 minutes, load 34) and light outside load to minute ~25.

**The first try** (`long-relayfix`, 10:12–10:43) was disturbed from minute 11 to 25: two unpinned ML processes of another project ran at 100% each on the X925 cores the server uses. When they stopped at minute ~26, it held 57.4–57.9 ticks/s through dusk under full A725 load. Its record is kept, not used.

**On the step marker, the unprofiled 48 s of each minute only.** The `profile_detail` windows slow their own ticks. The method is `marker_steps.py` `e16a43e5e`, unmodified, in `unprof_marker.py`. The idle p99 is the X925 session's 17.88 ms (bound 18.38), since no idle world was run today.

| 5-min block | Recorded build: ticks/s, p99 ms, % over 25 ms | Fixed: ticks/s, p99 ms, % over 25 ms |
|---|---|---|
| 0–5 | 59.47, 17.63, 0.88 | 59.80, 17.62, 0.34 |
| 5–10 | 58.41, 17.68, 2.61 | 59.55, 17.60, 0.71 |
| 10–15 | 57.60, 17.81, 4.15 | 59.06, 17.56, 1.55 |
| 15–20 | 56.50, 17.82, 5.91 | 58.14, 17.74, 3.10 |
| 20–25 | 47.27, 84.56, 17.28 | 58.03, 17.80, 3.31 |
| 25–30 | 12.16, 118.35, 100 | 58.55, 17.67, 2.41 |

The recorded build reproduces the earlier finding (59.7 → 58.3 → 57.3 → 56.1 → 52.8 → 16.5).

**Per minute, the fixed build** (same columns as §2):

| Min | Ticks/s | DB ms/s | Tick p99 ms | `tick` | `sight.player_candidates` | `scene.sensed` | `tick.wakes` | `brain.after` | `known.mark` | `noticed.structures` | `act.skill_ctx` | `check.ctx` | `join.sweep` | `housekeeping` | `structure` rows | `character` rows | `line_seen` rows | `skill_use` rows | `sex_seen` rows | jemalloc MB |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 59.94 | 470 | 11.37 | 403 | 30 | 12 | 41 | 28 | 7 | 7 | 9 | 4 | 1 | 0 | 285 | 429 | 6,957 | 5,683 | 7,619 | 323 |
| 3 | 59.74 | 493 | 14.18 | 434 | 30 | 12 | 48 | 34 | 7 | 10 | 10 | 4 | 1 | 0 | 525 | 672 | 6,964 | 11,404 | 20,263 | 349 |
| 5 | 59.77 | 506 | 13.78 | 429 | 30 | 13 | 52 | 34 | 7 | 12 | 9 | 4 | 1 | 0 | 767 | 916 | 7,068 | 17,210 | 32,164 | 363 |
| 7 | 59.61 | 494 | 15.2 | 415 | 31 | 10 | 55 | 38 | 6 | 16 | 9 | 3 | 1 | 0 | 982 | 1,125 | 7,294 | 22,232 | 42,515 | 387 |
| 9 | 59.53 | 506 | 16.96 | 427 | 31 | 11 | 59 | 42 | 7 | 19 | 11 | 4 | 2 | 0 | 1,220 | 1,364 | 7,174 | 27,633 | 52,330 | 400 |
| 11 | 58.96 | 491 | 16.04 | 405 | 31 | 10 | 60 | 41 | 6 | 19 | 9 | 3 | 1 | 0 | 1,461 | 1,601 | 7,488 | 33,176 | 63,771 | 407 |
| 13 | 58.9 | 486 | 19.49 | 395 | 30 | 10 | 61 | 45 | 6 | 23 | 10 | 3 | 1 | 0 | 1,709 | 1,851 | 7,105 | 38,858 | 74,163 | 420 |
| 15 | 58.88 | 486 | 18.56 | 396 | 31 | 10 | 60 | 45 | 6 | 24 | 10 | 3 | 1 | 0 | 1,965 | 2,102 | 7,293 | 44,652 | 82,219 | 426 |
| 17 | 58.88 | 500 | 20.86 | 436 | 31 | 9 | 70 | 54 | 7 | 29 | 12 | 4 | 2 | 0 | 2,222 | 2,362 | 7,219 | 50,665 | 93,941 | 438 |
| 19 | 57.25 | 528 | 24.77 | 454 | 31 | 14 | 77 | 55 | 7 | 30 | 12 | 4 | 1 | 0 | 2,438 | 2,571 | 7,368 | 55,882 | 98,636 | 458 |
| 21 | 57.81 | 536 | 20.96 | 433 | 31 | 9 | 74 | 57 | 7 | 32 | 12 | 4 | 2 | 0 | 2,676 | 2,811 | 7,406 | 61,169 | 104,294 | 480 |
| 22 | 58.76 | 509 | 20.59 | 427 | 31 | 9 | 79 | 62 | 7 | 37 | 11 | 4 | 2 | 0 | 2,804 | 2,938 | 7,471 | 64,004 | 109,509 | 495 |
| 23 | 58.13 | 524 | 19.86 | 434 | 31 | 10 | 73 | 60 | 7 | 36 | 11 | 4 | 1 | 0 | 2,923 | 3,062 | 7,261 | 66,833 | 114,652 | 504 |
| 24 | 58.01 | 527 | 19.2 | 437 | 28 | 10 | 79 | 64 | 7 | 38 | 12 | 4 | 1 | 0 | 3,046 | 3,181 | 7,367 | 69,590 | 117,240 | 513 |
| 25 | 56.61 | 575 | 21.52 | 472 | 67 | 20 | 89 | 63 | 7 | 39 | 11 | 4 | 3 | 0 | 3,169 | 3,300 | 7,313 | 72,329 | 116,266 | 518 |
| 26 | 58.32 | 539 | 17.69 | 438 | 52 | 35 | 68 | 37 | 4 | 18 | 11 | 4 | 2 | 0 | 3,288 | 3,417 | 7,451 | 75,190 | 121,131 | 522 |
| 27 | 59.11 | 536 | 17.62 | 416 | 59 | 25 | 66 | 33 | 4 | 14 | 10 | 4 | 2 | 0 | 3,407 | 3,540 | 7,054 | 77,808 | 119,330 | 521 |
| 28 | 59.11 | 518 | 14.9 | 425 | 66 | 19 | 61 | 30 | 3 | 13 | 10 | 4 | 1 | 0 | 3,535 | 3,660 | 7,253 | 80,576 | 124,167 | 524 |
| 29 | 58.58 | 524 | 23.49 | 424 | 66 | 18 | 67 | 38 | 4 | 18 | 11 | 4 | 2 | 1 | 3,661 | 3,788 | 7,065 | 83,478 | 129,123 | 527 |

**What changed:**
- **No dusk collapse.** At minutes 26–29, with 3,288–3,661 structures, `sight.player_candidates` is 52–67 ms/s against 143–244, and `scene.sensed` 18–35 against 125–230. The DB thread is 518–539 ms/s against 941–967.
- **The day-time growers are flat:**
  - `known.mark` 7 → 7 (recorded 9 → 35);
  - `check.ctx` 4 → 4 (5 → 18);
  - `act.skill_ctx` 9 → 11 (9 → 26).
- **Memory:** `line_seen` holds 7.0–7.5k rows throughout (230k recorded), and jemalloc ends at 527 MB against 674.

**What still grows**, and keeps the case under the line after minute ~10:
- `noticed.structures` 7 → 38 ms/s;
- `brain.after` 28 → 64;
- `tick.wakes` 41 → 89.

These are minds' and graphs' noticing over every structure in sight (remains included, by design) and residents' calm evaluations (§4.3). Ticks/s falls about 1.7 over the run; the p99 stays within 17.8 ms.

### 5.2 det_compare (main `62fccc74b` against `growth-fix`, Cullet, 200 fighters plus 16 players, 1,800 ticks)

- **The control:** main against itself is identical (113 tables, every tick).
- **growth-fix against main:**
  - 112 of 113 tables are identical in every tick.
  - `seen_stock` differs only in its auto-increment ids. At the stop, its two differing rows are the same rows with ids 135 and 136 swapped: two players' sweeps in one tick inserted theirs in the other order.
- **Why the order moves:**
  - The order of the players' sweeps in a tick is the iteration order of `combat::humans()`'s std `HashMap` (`perception.rs:1127`). Its hash keys come from std's per-thread `RandomState` counter, which every `HashMap` or `HashSet` made in the instance advances.
  - **Variant B,** main plus one unused `HashMap::new()` in `lit_at`, gives the same difference with the same two hashes at tick 8.
  - **Variant A,** the light and gate change alone without the housekeeping part, also gives it.
  - The base's own hash at that tick also swapped between runs. So this is the comparison's sensitivity to the sweep order, not a rule's result.
- **growth-fix's own new map:** its cache is a `BTreeMap` for this reason (`fab19a631`).
- **Proposed separately:** sweeping the players in id order (sort `humans()`). It changes main's order once and removes the sensitivity.

### 5.3 Checks

- **`just living-check`:** ok, 2,716 s on `c4ffa3559`, then ok again in 786 s on the final code (`fab19a631`).
- **Bindings:** regenerated with the pinned image, a one-off `docker run` of `clockworklabs/spacetime:v2.14.1` as `LIVING_GENERATE_CMD`. Only `census_table.rs`, `census_type.rs` and `mod.rs` change.
- **verify-core `laws` on a `cullet-laws` world** (`core-gf-laws2`):
  - 15 parts pass, 1 skipped, the same staging skip as its last passing record (2026-11-13).
  - At night, someone standing in lamplight is seen from 28 m (21 m off), that is `lit_at` through the lights list. A carried light is seen from 48 m, and the dark's sight is 14 m.
  - The scene's own check of the installed script compared the overlay with the authority's appended world-law values included, and failed at its second check. It now compares without them (`install_script.without_world_laws`).

- **verify-core `known_ground` and `nav_belief`** (default seed, `core-gf-1`): both pass. They cover the gates remembered through `few_near`.
- **verify-player** (`player-gf-1`, default seed; `player-gf-3`, island):
  - `outcomes.py` passes, 14 checks: a death and the next join, the `set_player` path that now drops the former character's lines.
  - `combat.py --scene death --fresh` on an island world passes 4 of 4, twice: death, told, codes, and rejoin with a new identity and only the newcomer's kit.
  - On the default seed (`player-gf-1`) the death scene's player was never killed (its staging; `features/combat.md` runs it on `--seed island`).
- **verify-client `run.py`** (`client-gf-1`, `client-gf-2`): 44 parts pass in each run.
  - The private-table inventory check passes with `census` listed.
  - One timing-bound part failed in each, a different one each time, and each passed in the other run.
    - "combat feed scoped to its viewer": player-2's feed rows, kept 4 s, were gone before its probe while builds ran alongside; recorded twice before in `history.md`.
    - "per-character queries": the AI character's `routine_stat` rows within a 2 s probe.
- **Not covered:**
  - a paid model run;
  - the game client UI;
  - a scene that watches a lamp burn out (as before, `features/goods.md`);
  - main's direct arm with the fixes at 30 minutes;
  - the final 30-minute re-measure on main after all three fixes land (the coordinator's).

## 6. SpacetimeDB documentation and source consulted

- **Pages** (version 2.0.0 as shown on 2026-11-23; the pinned server is 2.14.1):
  - [Tables](https://spacetimedb.com/docs/tables/): "organize data by access pattern"; the archive pattern ("Move old records to an archive table while keeping the same schema").
  - [Performance](https://spacetimedb.com/docs/tables/performance/): "prefer indexed lookups over full table scans"; "Archive or delete old records".
  - [Indexes](https://spacetimedb.com/docs/tables/indexes/): prefix and trailing-range filters on multi-column btrees.
  - [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/): adding a table is allowed; `census` is a new private table, so no column changes and no client disconnects.
- **The tables page also says:** "tables keep their data resident in memory". So growth in `line_seen`, `skill_use` and the other tables of the dead is memory held for the database's life.
- **Source** (tag `v2.14.1`, `crates/table/src/table_index/same_key_entry.rs`): a non-unique btree key keeps its rows in a `SmallVec` up to 512 entries and a `HashSet` beyond. So the rows under one key, such as `alive = true`, come in no fixed order. Housekeeping therefore sorts the living by id.
- **Design implications:**
  - Per-chunk lists in module memory, not new tables, for the light and gate reads. They follow the chunk cache, which follows the `structure` table through `invalidate_structures`.
  - One new private one-row table for the dead count.
  - No subscription, view or client-facing table changes.

## 7. Data paths

| Path | Reads | Writes | Index | Recipients | Rate | Retained |
|---|---|---|---|---|---|---|
| `lit_at` | the chunk's cached structures, filtered once per chunk-list revision | none | `structure.chunk` (cache fill) | none | per creature per tick from dusk (glow law), per skill check | module memory, per chunk |
| `remember_gates` | the chunk's cached gates | `remembered` as before | as before | none (private) | per look | as before |
| housekeeping count | the living (`character.alive` = true), the `census` row | `stats` as before | `alive` btree | none (private) | 1 Hz | one row |
| `die_unseen` | `census` | `census` +1 | pk | none | per death | one row |
| `set_player` | `line_seen` (`by_observer_shown`, the old character, both values) | deletes them | `by_observer_shown` | the person's `my_experience` (already moved) | per join with another character | ≤ 64 rows per person |

## Evidence

- **Runs:** `~/slop-growth-diag/out/runs/{long-relay,long-main,long-relayfix,smoke-main}/`. Each holds `prof.jsonl`, `spans.json`, `ticks.json`, `mem.jsonl`, `cores.jsonl`, `ticks-watch.csv` (the marker), `battle-viewers.json` and the replica's module logs. Plus `out/driver.log` and the server logs.
- **Archive:** `~/slop-evidence/growth-diag-20261123.tar.zst` (sha256 beside it).
- **Tools:** `prof.py`, `spans.py`, `ticks.py`, `diag.py`, `table.py`, `driver.sh` and `driver-b.sh`, in the archive.
