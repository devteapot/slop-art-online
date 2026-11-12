# Battle scale: why a battle of minded fighters collapses (diagnosis and fix design, 2026-11-12)

Status: **fixes 1–3 built on `battle-scale` and accepted as a step (2026-11-12): the collapse is gone, but 60 Hz is not reached at 200 fighters (see [Acceptance runs](#acceptance-runs-fixes-13-quiet-box-2026-11-12)). Fix 4 (folding) and the remains' caching built on `battle-fold`; the fighters' cheaper paths 1–3 on `battle-cheap`. Measured in the second quiet window with a sustained 200-fighter battle: 45.8 ticks/s with all of them, against 36.0 with the fold and 30.0 with fixes 1–3; 17.7% of ticks over 16.7 ms against 40.6% and 59.4%. The contract's 60 Hz is not reached.** The diagnosis below was measured on `battle-diagnosis` (from main `b36a938c`). Its only code change was diagnostics: profiling-only counters (`common::diag`, one `diag:` log line a second while `set_profile` is on, nothing otherwise), spans on `brain.noticed`, `brain.graph`, `brain.after` and `perceive.scene_json`, and the measurement tool `living/tools/battle_diag.py`. The target is the performance contract's 200-character local battle (docs/PERFORMANCE_CONTRACT.md) under the owner's rule: **no attention cap; everything within vision at full detail.**

## Workload

- **World and service:** seed `island` on the trial service (SpacetimeDB 2.14.1, port 3320), on the DGX Spark (20 cores). The server, the load generator and other agents' builds shared the host; its 1-minute load is given per window, from 3.5 to 30.
- **Population:** the island's own 310 characters, all AI (about 280 people, 24 deer, 9 wolves), plus:
  - **fighters:** 100 minded people (`spawn_crowd`, AI), packed within 7 m of the battle site 20 m north of the arrival square, inside the first town. Each fights the nearest person: strike; dodge or block when threatened; heal below half health.
  - **walkers:** 116 minded people walking as foragers across the island.
  - **refills:** a dead fighter is replaced at the site by the load generator, about 1 to 2 a second. This is a respawn the game does not have; it keeps the battle's population, and it adds a character and a remains for every death.
- **Minded share:** every character is AI and every one but the instinct-only animals receives percepts.
- **Density:** a packed fighter sees 70 to 106 others, 80 to 106 onlookers per fight start, plus the remains (people's remains last 120 game hours, an hour of real time here).
- **Blow rate:** 25 to 43 skill uses a second (strikes, blocks, dodges, heals), 22 to 31 new fights a second, about 1 to 2 deaths a second.
- **Minds:** three arms.
  - **No mind service** (`--no-mind`): requests to think stay pending. This is the workload that collapsed in the cue-cache run.
  - **Fake model:** think 5 s, compile 4 s; a fighter's compile reinstalls its fight.
  - **200 variant:** 200 fighters and 16 walkers, no mind service.
- **Sampling:** every 60 s, a 30 s profiled `bench.py` window (tick spans, the `diag:` counts), the row counts of the tables that grow, this database's WASM memory and retained commitlog size, the alive population and the load.

## What happens

**100 fighters, no mind service** (`minds-bdnm-122050`; stopped at minute 13, collapsed). Columns: tick work in ms of the database thread per second (1,000 is saturation); percepts written per second by kind; evaluations of behaviour graphs per second by trigger.

| min | Ticks/s | Over 16.7 ms | Tick work: all / wakes / activity / combat (ms/s) | Experiences/s | Fight / saw / death percepts per s | Wakes/s | Evals by wake / combat / slot per s | Scene renders/s | experience / structure / familiar rows | Commitlog MB | Load 1 min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 42.9 | 469 | 571 / 293 / 98 / 135 | 2,487 | 1,890 / 147 / 58 | 2,296 | 1,478 / 639 / 294 | 28 | 48,097 / 600 / 21,862 | 269 | 16.4, 12.9 |
| 1.0 | 21.0 | 453 | 758 / 529 / 98 / 100 | 2,336 | 1,745 / 187 / 52 | 2,171 | 1,153 / 223 / 140 | 29 | 51,105 / 653 / 29,604 | 565 | 12.4, 10.9 |
| 2.0 | 13.9 | 416 | 810 / 621 / 98 / 64 | 2,343 | 1,734 / 273 / 60 | 2,254 | 1,015 / 94 / 94 | 29 | 52,652 / 714 / 34,359 | 812 | 11.3, 10.9 |
| 3.0 | 14.0 | 412 | 816 / 619 / 99 / 70 | 3,266 | 1,731 / 1,057 / 86 | 3,035 | 957 / 96 / 92 | 32 | 52,471 / 783 / 35,334 | 1,065 | 9.6, 9.4 |
| 4.0 | 5.6 | 170 | 878 / 648 / 139 / 60 | 9,263 | 1,127 / 7,442 / 53 | 8,644 | 421 / 30 / 37 | 26 | 45,674 / 848 / 29,198 | 558 | 14.2, 26.4 |
| 5.0 | 5.1 | 157 | 873 / 744 / 57 / 52 | 22,574 | 433 / 20,861 / 28 | 21,239 | 263 / 19 / 34 | 16 | 37,621 / 899 / 25,276 | 1,099 | 29.4, 27.8 |
| 6.0 | 36.1 | 440 | 665 / 320 / 62 / 244 | 2,418 | 651 / 1,772 / 24 | 2,572 | 706 / 585 / 242 | 25 | 57,625 / 937 / 36,189 | 1,388 | 26.1, 19.3 |
| 7.0 | 23.2 | 520 | 714 / 438 / 72 / 178 | 6,858 | 802 / 5,427 / 30 | 6,343 | 748 / 366 / 151 | 29 | 59,698 / 989 / 37,270 | 855 | 17.8, 14.1 |
| 8.0 | 10.5 | 326 | 795 / 591 / 74 / 115 | 19,250 | 694 / 17,512 / 29 | 18,257 | 474 / 133 / 70 | 28 | 54,614 / 1,063 / 34,330 | 1,393 | 13.9, 14.1 |
| 9.0 | 8.8 | 264 | 831 / 673 / 50 / 95 | 28,843 | 468 / 26,005 / 26 | 26,467 | 348 / 75 / 57 | 22 | 47,998 / 1,121 / 30,954 | 1,176 | 18.4, 15.7 |
| 10.0 | 9.3 | 286 | 813 / 642 / 45 / 111 | 27,679 | 389 / 25,831 / 17 | 26,214 | 334 / 85 / 61 | 24 | 50,856 / 1,173 / 31,961 | 1,922 | 15.9, 14.3 |
| 11.0 | 1.6 | 49 | 875 / 839 / 30 / 0 | 38,648 | 466 / 34,013 / 25 | 34,483 | 103 / 2 / 9 | 24 | 40,348 / 1,223 / 23,925 | 1,737 | 13.4, 11.4 |
| 12.0 | 3.2 | 98 | 876 / 800 / 18 / 49 | 38,641 | 128 / 34,620 / 10 | 34,736 | 115 / 10 / 20 | 11 | 35,049 / 1,261 / 20,375 | 1,597 | 11.0, 14.1 |

**Where a woken evaluation's time goes** (`minds-bdat-124436`, the same workload on a nearly quiet host, load 3.5–9). It follows the same curve as the loaded run, so host load is not the cause:

| min | Ticks/s | Tick (ms/s) | in noticed() | graph run | after() incl. noticed | scene build | Evals/s (wake / combat / slot) | Recently-seen checks/s | misses = familiar lookups/s | familiar evictions/s | saw / fight percepts per s | Load 1 min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 41.6 | 586 | 203 | 148 | 241 | 34 | 1,412 / 625 / 282 | 182,960 | 28,824 | 0 | 133 / 1,713 | 5.1, 5.2 |
| 1.0 | 24.4 | 757 | 441 | 108 | 474 | 26 | 1,110 / 311 / 170 | 168,336 | 108,465 | 0 | 273 / 1,543 | 4.8, 4.8 |
| 2.0 | 15.1 | 810 | 530 | 89 | 558 | 23 | 948 / 147 / 102 | 180,187 | 174,712 | 75 | 279 / 1,627 | 4.4, 3.7 |
| 3.0 | 13.9 | 826 | 552 | 88 | 580 | 24 | 915 / 124 / 90 | 206,466 | 203,153 | 900 | 892 / 1,477 | 3.5, 3.9 |
| 4.0 | 8.7 | 831 | 602 | 64 | 625 | 18 | 599 / 64 / 58 | 135,136 | 133,210 | 15,290 | 13,741 / 1,134 | 3.7, 9.1 |
| 5.0 | 5.0 | 864 | 721 | 39 | 735 | 11 | 362 / 22 / 32 | 77,504 | 75,280 | 29,933 | 28,579 / 753 | 9.1, 9.0 |
| 6.0 | 28.7 | 711 | 414 | 109 | 447 | 25 | 723 / 520 / 187 | 204,768 | 194,074 | 943 | 978 / 710 | 7.6, 5.8 |

**200 fighters, no mind service** (`minds-bd200-123543`): at 7.8 ticks a second from the first minute, before remains have piled up; 31 fight starts a second seen by 106 onlookers each.

| min | Ticks/s | Over 16.7 ms | Tick work: all / wakes / activity / combat (ms/s) | Experiences/s | Fight / saw / death percepts per s | Wakes/s | Evals by wake / combat / slot per s | Scene renders/s | experience / structure / familiar rows | Commitlog MB | Load 1 min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 7.8 | 235 | 878 / 692 / 157 / 16 | 4,320 | 3,275 / 358 / 125 | 3,915 | 983 / 20 / 43 | 38 | 65,649 / 681 / 42,219 | 527 | 13.2, 11.7 |
| 1.0 | 9.1 | 273 | 851 / 651 / 147 / 37 | 3,984 | 2,411 / 1,044 / 120 | 3,663 | 896 / 54 / 54 | 34 | 58,941 / 773 / 40,080 | 786 | 10.9, 15.4 |
| 2.0 | 7.8 | 234 | 836 / 635 / 136 / 48 | 10,729 | 1,818 / 7,939 / 86 | 9,810 | 657 / 56 / 45 | 32 | 53,452 / 848 / 35,931 | 1,139 | 16.8, 18.7 |
| 3.0 | 4.7 | 142 | 788 / 675 / 67 / 35 | 25,382 | 827 / 22,729 / 44 | 23,531 | 319 / 23 / 26 | 23 | 40,508 / 924 / 28,003 | 1,056 | 19.6, 28.3 |
| 4.0 | 4.0 | 116 | 870 / 777 / 50 / 33 | 27,664 | 387 / 24,374 / 28 | 24,740 | 193 / 15 / 18 | 14 | 34,330 / 976 / 23,618 | 1,559 | 25.3, 22.7 |
| 5.0 | 26.9 | 496 | 707 / 416 / 75 / 188 | 2,611 | 958 / 1,888 / 18 | 2,975 | 862 / 464 / 159 | 32 | 67,596 / 1,012 / 43,834 | 981 | 19.6, 15.0 |

**100 fighters with the fake model** (`minds-bd100d-120959`): the battle thins within a minute (fight percepts 1,491 then 212 a second) because a mind's plan competes with the body's needs. It stays near 60 Hz, so it is not the case to size a fix by.

| min | Ticks/s | Over 16.7 ms | Tick work: all / wakes / activity / combat (ms/s) | Experiences/s | Fight / saw / death percepts per s | Wakes/s | Evals by wake / combat / slot per s | Scene renders/s | experience / structure / familiar rows | Commitlog MB | Load 1 min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 41.8 | 428 | 536 / 264 / 97 / 130 | 2,123 | 1,491 / 161 / 59 | 1,914 | 1,331 / 631 / 276 | 27 | 48,501 / 609 / 22,271 | 228 | 22.1, 17.5 |
| 1.0 | 56.5 | 94 | 404 / 98 / 48 / 161 | 386 | 212 / 52 / 5 | 492 | 432 / 814 / 423 | 17 | 54,116 / 620 / 26,662 | 367 | 15.1, 13.8 |
| 2.0 | 55.8 | 70 | 413 / 95 / 41 / 171 | 267 | 99 / 38 / 4 | 374 | 337 / 807 / 400 | 15 | 53,339 / 633 / 27,540 | 447 | 14.3, 13.5 |
| 3.0 | 55.9 | 33 | 378 / 80 / 32 / 148 | 165 | 57 / 24 / 2 | 310 | 281 / 676 / 415 | 16 | 54,185 / 641 / 28,348 | 521 | 14.0, 12.4 |
| 4.0 | 56.7 | 19 | 307 / 62 / 24 / 101 | 125 | 31 / 36 / 3 | 251 | 230 / 463 / 433 | 12 | 50,059 / 660 / 27,745 | 591 | 12.2, 12.7 |
| 10.0 | 59.7 | 0 | 133 / 18 / 13 / 26 | 36 | 0 / 2 / 0 | 64 | 61 / 166 / 433 | 7 | 47,812 / 708 / 35,971 | 840 | 22.8, 17.3 |
| 15.0 | 56.6 | 18 | 214 / 44 / 15 / 29 | 23 | 0 / 3 / 0 | 122 | 119 / 114 / 433 | 5 | 44,620 / 717 / 36,934 | 1,071 | 20.2, 29.0 |
| 20.0 | 59.6 | 0 | 99 / 13 / 12 / 2 | 12 | 0 / 1 / 0 | 49 | 49 / 10 / 425 | 0 | 38,922 / 721 / 38,040 | 563 | 18.5, 15.6 |
| 25.0 | 58.3 | 16 | 203 / 53 / 17 / 8 | 17 | 0 / 3 / 0 | 176 | 174 / 34 / 429 | 6 | 33,327 / 723 / 38,968 | 747 | 14.5, 19.1 |
| 29.0 | 61.0 | 2 | 197 / 45 / 21 / 3 | 26 | 0 / 5 / 0 | 118 | 118 / 10 / 436 | 6 | 30,222 / 723 / 39,569 | 903 | 17.1, 19.6 |

**Table growth and memory** (no-mind run, 13 minutes):
- `experience` stays bounded at 35k–60k rows: 400 a character, and the dead's rows go.
- `skill_use` grows about 25–43 rows a second (20,170 at minute 13).
- `character` grows by one row per refill (545 to 1,128).
- `structure` grows by one remains per death (600 to 1,261).
- `familiar` stays at 20k–43k rows (capped per character).
- `deliberation` holds 109–477 pending rows (no mind service).
- WASM memory: flat at 111 MB (its high-water mark from world creation).
- Retained commitlog: 0.3–1.9 GB as segments roll, written at about 4–5 MB a second in the first minutes. That rate is mostly `mind_state` rewritten at every evaluation (its 96-entry `seen` list) and experience rows.

## Where the rate comes from, and which cost dominates

1. **The first blow of every fight is told to every onlooker at salience 0.7, and 0.7 wakes them** (`act.rs` `{a} attacked {b}`; `perceive::percept` wakes at 0.6 and above). At 100 fighters: 22 fight starts a second × about 80 onlookers = 1,700–1,900 percepts a second, 2,100–2,300 wake requests, and 1,000–1,500 extra graph evaluations a second (`eval:wake`). Deaths add about 60 a second at 1.0. Later blows are not told to onlookers at all today. Players see each blow through `combat_seen`; minds see only the fight's start, yields and deaths.
2. **Every evaluation re-checks everything in sight for novelty, and that check is the dominant cost.** `Ev::noticed` runs on every evaluation (woken, combat cadence 15 Hz, slot). It checks each creature and structure in sight against a 96-entry recently-seen list, and a miss is a `familiar` index lookup. With 80–200 things in sight the list thrashes: 180k checks a second, misses rising from 29k to 175k–203k a second. `brain.noticed` grows from 203 to 530–720 ms/s; the graphs themselves cost 40–150 ms/s.
3. **The runaway: familiarity forgets what is still in sight.** `familiar` is capped at 256 rows a character, pruned oldest `last_ms` first, and `last_ms` is refreshed only every 30 s while a thing stays in sight. Once people plus accumulating remains in sight pass 256, it evicts things that are in view (75 a second at minute 2, then 15k–30k a second), and they are noticed again. A remains is noticed at salience 0.8 ("You notice a remains — the remains of …"), which wakes the observer, whose evaluation notices again. `saw` percepts go from 150 to 34,000 a second, experiences to 38,600 a second, and the tick to 1.6 steps a second. It recovers briefly when a cohort of remains is familiar again, then falls further.
4. **Writing what was seen is not the cause.** `tick.activity`, the blows and the witnessed percepts' rendering and inserts, stays at 90–100 ms/s (150 at 200 fighters) until the runaway. The rows (1,700–3,300 fight percepts a second) and the commitlog volume matter for an 8-hour run, not for the collapse.
5. **At 200 fighters, waking alone breaks the tick:** 983 woken evaluations a second at 0.7 ms each (200 in sight) is 692 ms/s, before any runaway.

## Fix design (fixes 1–3 built on `battle-scale`, fix 4 on `battle-fold`)

Sized for the contract's 200-character battle:
- 200 fighters packed (each seeing about 200 creatures);
- about 30 fight starts, 35–60 blows and 2 deaths a second;
- several hundred to thousands of remains in sight over an hour;
- plus ordinary world work around it, at 60 Hz.

Four changes, each behind a law where it changes timing, each measured on its own:

1. **Familiarity that never forgets what is in sight** (the runaway).
   - A `familiar` row is evicted by age only: not seen for an hour (or a game day), never one touched within twice its touch period.
   - The per-character bound is sized above what can be in sight (for example 2,048; about 90 kB a character), not 256.
   - The recently-seen fast path becomes a set sized to the scene, kept off `mind_state`, so it is not rewritten at every evaluation.
   - Each remains is then noticed once per observer, as the design intended.
2. **Novelty once per character per second, not per evaluation.**
   - `noticed()` runs on the character's own 1 Hz slot evaluation, and on a woken one at most once a second.
   - What enters sight is still noticed within a second, as now on the slot. A combat-cadence evaluation (15 Hz) then runs the graph only.
   - This removes most of the 180k checks a second at 100 fighters, and about 3,000 noticing passes a second at 200.
3. **A witnessed event wakes a bystander at most once per `witness_wake_ms`** (a law, default 500 ms).
   - The percept is still written at once and in full. Only the extra graph evaluation is coalesced.
   - Whoever is party to the event (its subject or object, or the one it is aimed at) is woken at once, as now. Being attacked, threatened or hailed stays immediate.
   - At 100 fighters, extra evaluations fall from 1,000–1,500 a second to at most 200 (100 onlookers × 2 a second); at 200, from about 4,000 a second to at most 400.
4. **Fold what an onlooker sees of fights into one percept every `witness_fold_ms`** (a law, default 2,000 ms). It is optional for the collapse and needed for the rows and the 8-hour volume.
   - **One row per blow, not per onlooker.** Each blow, block, dodge, miss, yield and death is written once to a private `fight_seen` row. The row holds who did what to whom, the outcome, where, and the onlookers who could see it under the sight rule at that instant (`witnessed`'s own test, facing included).
   - **One line per onlooker per fold.** Each onlooker gets one experience line naming every pair it saw, with counts and outcomes: "Grim struck Ada three times (twice hit, once blocked); Ada fell. Tor and Bram are fighting: Tor blocked twice."
   - **The witness's word.** A death the onlooker saw still goes into that line in full.
   - **Rows.** At 200 fighters, about 100 `fight_seen` rows a second plus 100 folded percepts a second replace 3,300 fight percepts.
   - **More content than now.** Minds get every blow they could see, which they do not today.
   - **Bounds.** The rows expire after their fold, so the table holds a few seconds of fights.

**Everything within vision at full detail.**
- No event is dropped, and no onlooker is excluded by distance, count or "nearest fight".
- Every blow an onlooker could see is in its record, with who struck whom, how many times and the outcome. That is more than today, where onlookers' minds hear only the first blow.
- Novelty and waking change when work is done, not what is perceived. Sight and the sight test are unchanged.

**The same rule for every controller.**
- Folding (4) applies to every character's experience rows, a player's included: `my_experience` shows the same folded line.
- The player's per-blow `combat_seen` feed and frames are unchanged.
- Familiarity (1, 2) and wake coalescing (3) govern evaluating behaviour graphs, which only AI controllers run. A player's character sees and is told the same things at the same moments.

**Expected cost at 200 fighters after 1–3.** These are estimates from the measured per-call costs, to be measured, not claimed:
- the graphs at combat cadence: about 3,000 a second at 0.05–0.07 ms, 150–200 ms/s;
- noticing at 1 Hz with O(1) checks: about 20 ms/s;
- coalesced wakes: at most 400 a second without noticing, about 30 ms/s;
- writing: 100–150 ms/s.

That gives roughly 300–450 ms/s of tick work against 1,000 available: 60 Hz with margin, if the estimates hold.

## Fixes as built (`battle-scale`)

1. **Familiarity forgets by age only, never what is in view** (`brain.rs`):
   - `FAMILIAR_LIMIT` is 2,048 rows a character, up from 256.
   - Over it, `prune_familiar` removes the oldest rows by `last_ms`. It never removes one touched within `FAMILIAR_KEEP_MS` (60 s), nor one whose thing is in the character's seen set within `SEEN_MS` (90 s). The count is checked every 64 new rows of that character.
   - **The seen set.** The recently-seen fast path is now a per-character set (`SEEN`, thread-local, the durable `familiar` rows behind it), holding what was looked at within 2 minutes. The 96-entry list on `mind_state` is no longer written, so that row is not rewritten with it at every evaluation.
   - **Memory.** A `familiar` row is 48 bytes in its page (u64, u32, u64, u64, u64, u32, aligned to 8), plus its entries in three btree indexes: the primary key on `id`, `actor`, and `by_actor_thing`. That is about 16–32 bytes each with node overhead, so **about 120 bytes a row**: about **240 kB a character at the 2,048 cap**, and about **480 MB at 2,000 characters if every one were at the cap**. In these runs a character held 40–80 rows on average (20k–43k rows for about 520 characters), and the fighters at the site several hundred: a few kB to about 50 kB each. The seen set adds about 30 bytes per thing looked at within 2 minutes, in the module's memory, and empties as things leave sight.
2. **Novelty about once a second.** `noticed()` runs at most once per `NOTICE_MS` (900 ms, a little under the 1 Hz slot, since a slot can come a tick early) per character, not at every woken or combat-cadence evaluation. Cues keep their own interval (`cue_check_s`).
3. **Bystanders woken at most once per `witness_wake_ms`** (a law, default 500; 0 means woken by each sight, as before):
   - **Written in full.** A witnessed event's percept is written at once and in full to every onlooker (`perceive::witnessed`, `witnessed_shot` → `percept_seen`).
   - **Parties at once.** Its subject, and the one it was done to or aimed at, are woken at once.
   - **Bystanders coalesced.** A bystander is woken at most once per window (`common::wake_bystander`). A wake held back is delivered when the window ends, each tick before the wakes (`due_bystander_wakes`).
   - **Remains.** A remains noticed is a bystander's sight of a death.
4. **Deleting a busy world.** The verify harness's cleanup and `trials.py` pause a world and read the pause back before deleting it (fix-sleep-talk, fix-trials-pause). `living/tools/world_delete.py` does the same for the tools that delete scratch databases outside both: `verify_mechanics.py` and `verify_steering.py` (verify-core's Cargo checks), `gate.py`, `latency.py` and `play.py`.

## Acceptance runs (fixes 1–3, quiet box, 2026-11-12)

Two 30-minute runs of `battle_diag.py --no-mind` on `battle-scale` `a7485376`, in a quiet window given for them: every other agent paused, and the seven other worlds on the trial service were paused, so none was ticking. Host load over the window (one sample every 10 s, 381 samples): 1.8 to 5.0, median 3.1. `committed` was run first in the same window and passed 16 of 16 (`core-qcm-141636`).

**Workload:** as in [Workload](#workload): the island's 310 residents and animals, all AI. Fighters are packed within 7 m of the battle site, walkers forage, and there is no mind service. A dead fighter is refilled at the site (the load generator's respawn, which the game does not have).

- **`minds-q100-141730`:** 100 fighters and 116 walkers.
- **`minds-q200-144827`:** 200 fighters and 16 walkers.

**Sampling:** a 30 s profiled `bench.py` window every minute; tick counts are of the sampled ticks. Each run directory holds `windows.md` (the table per window), `load.log` and the `bench-NN.json` files.

| | 100 fighters | 200 fighters |
|---|---|---|
| Creatures in a graph's scene, mean (range over windows) / max | 43 (23–58) / 96 | 87 (50–120) / 187 |
| Fight starts a second, onlookers each | 20.5, about 59 | 38.8, about 102 |
| Skill uses a second (strikes, blocks, dodges, heals) | 23.8 | 44.1 |
| Deaths (refills) a second | 0.9 | 1.8 |
| Alive, start → end | 520 → 453 | 508 → 441 |
| Structures (mostly remains), start → end | 597 → 2,207 | 650 → 3,830 |

**Against the contract** (sustained 60 Hz; the nominal step is 16.667 ms, so a tick over 16.7 ms misses its step). Before is the diagnosis on the same tool and workload. `minds-bdat-124436` (100) ran on a nearly quiet host, load 3.5–9, and was stopped after 7 minutes at collapse. `minds-bd200-123543` (200) ran at load 10–28, and its first minute, before remains piled up, was already 7.8 ticks a second.

| | Ticks/s | Ticks over 16.7 ms | Tick p99 per window: median (worst) |
|---|---|---|---|
| 100, before | 19.5, collapsing to 1.6 | 63.7% | 89 ms (233) |
| **100, after (30 min)** | **55.0**: 56.9 in the first 5 min, 50.4 in the last 5 | **4.4%** (2,179 of 50,016) | **23 ms** (48) |
| 200, before | 10.0 | 84.4% | 273 ms (467) |
| **200, after (30 min)** | **26.8**: 37.7 in the first 5 min, 16.1 in the last 5 | **60.6%** (14,777 of 24,401) | **83 ms** (243) |

**Reading:**

- **The runaway is gone.** Nothing in view is forgotten and noticed again: `familiar` evictions are 0–4 a second at 100 and at most 150 at 200 (against 15k–30k before), and every `saw` percept is a first sight with its new `familiar` row. Woken evaluations stay flat, at 370–440 a second at 100 and 490–680 at 200. 100 fighters hold near 60 Hz for 30 minutes.
- **First sights still grow, with the refills.** At 100, first sights go from 75 to 1,321 a second over the run; at 200, from 402 to 3,329. `familiar` rows go from 20k to 159k at 100, and from 56k to 416k at 200: about 50 MB at about 120 bytes a row. Each refill is a new character that has seen none of the remains at the site: 2,207 at 100 and 3,830 at 200 by the end. This is the load generator's respawn more than a battle's.
- **Neither run meets the contract.** 100 is close: 4.4% of ticks are over budget, and the rate declines slowly. 200 is far from it.

**Where the time goes at 200** (span ms per second of wall time, mean of the first and last five windows; spans nest, so they do not add up):

| Span | First 5 min | Last 5 min |
|---|---|---|
| `tick` (all) | 603 | 799 |
| `tick.wakes` (woken evaluations) | 108 | 335 |
| `tick.combat` (the fighters' 15 Hz evaluations) | 224 | 253 |
| `tick.activity` (blows, and writing what onlookers saw) | 233 | 184 |
| `brain.graph` | 189 | 221 |
| `brain.noticed` | 33 | 217 |
| `brain.scene` | 55 | 120 |

- **What the fight costs from the start.** `tick.activity` (about 230 ms/s) and the fighters' own evaluations at 15 Hz (`tick.combat`, about 230) are the two largest. `tick.activity` holds all of a blow's resolution, not only the 4,700–6,100 fight percepts a second written to onlookers. The paired runs on `battle-fold` put those lines at about 70–100 ms/s of it; see [Fix 4 as built](#fix-4-as-built-battle-fold).
- **What grows.** Noticing (33 → 217 ms/s) and scene building (55 → 120) grow as remains pile up at the site: 3,830 structures by the end, each refill a new character that has seen none of them. Remains are static, so these costs are what caching them by their `familiar` row addresses. Part of the growth comes from the refills themselves, so the next acceptance runs keep deaths permanent.
- **At 100 the same costs, smaller.** `tick.combat` goes from 165 to 306 ms/s, `brain.scene` from 37 to 113 and `brain.noticed` from 11 to 57, with 2,207 structures by the end.

## Fix 4 as built (`battle-fold`)

The coordinator's conditions (2026-11-12): every blow an onlooker saw kept, in order, with who struck whom, counts and the outcomes it could see; a blow at or by the onlooker never folded; players fold the same way in their experience lines, their per-blow feed unchanged; a verify-minds case showing a watcher can still tell who is winning and who fell; the saving measured at 200 fighters.

- **One row per blow** (`fold::blow`, from `act::damage`, the dodge and the miss):
  - Each blow that lands, is blocked, dodged or missed is written once to the private `fight_seen` table.
  - The row holds the attacker, the victim, the outcome, whether it began the fight, whether it killed, the missile, the place, and everyone who could see it under `witnessed`'s own test (`minds_near`, `in_sight`: walls and facing). The two in it are excepted.
  - A missile's onlooker who saw where it struck but not who shot is marked so.
- **One line per onlooker per window** (`fold::flush`, each tick; the `witness_fold_ms` law, default 2,000 ms; 0 restores the old lines):
  - Each onlooker's windows end at its own phase (spread by id), so a crowd's lines are spread over the window's ticks.
  - A blow falls in exactly one window of each onlooker (unit test). A row is deleted once every onlooker's window holding it has been told, so the table holds at most one window of fights.
  - The line, `living_rules::fold::line`, has one sentence a pair, in the order each pair was first seen: "A stranger (#271) attacked a stranger (#272): 3 blows (2 landed, 1 blocked), and a stranger (#272) fell."
- **Names.** Each one is named as the onlooker perceives them when its line is written (`perception::labels`).
  - A mind's line anchors everyone it cannot name by the id its scene knows them by (`far::id_for`, a far figure's handle), because one line can hold many strangers' fights. A line's own `subject` and `object` anchor only one pair.
  - A player's line reads as its screen shows it, without ids.
  - The dead are named as if near, because their body is gone when the line is written.
- **Unchanged:**
  - A blow at or by someone is told to them at once, as before (`attacked`, `combat`).
  - A death is still told at once on its own line, as well as in the fold.
  - A fight's first landed blow wakes its onlookers as bystanders when it lands, as its own line did (fix 3). The folded line wakes no one.
  - Players' `combat_seen` feed is untouched.
- **Module memory.** The pending blows are rows, not module memory. The [reducers docs](https://spacetimedb.com/docs/functions/reducers/) call relying on global or static state across reducer calls undefined behaviour: SpacetimeDB "may run each reducer in a fresh WASM or JS instance", and state changed in a rolled-back transaction "may remain". The module's thread-locals stay caches of rows (a lost one is recomputed), or wakes whose loss only delays an evaluation.
- **Updating a running world in place** (2026-11-12, `core-mig-162455`, asked after dev-box's look-1 update panicked with "No such index"):
  - Main's module `9d62be70` was published to a scratch world, then `battle-scale` `cbbb5eb8` over it with its data kept, then `battle-fold` over that.
  - Each first tick and the ticks after ran at about 60 a second, with no panic in the log.
  - `battle-scale` adds no table or index: the seen set is module memory backed by `familiar`, and the cap is a constant. `battle-fold`'s update logged "Creating table `fight_seen`". Its `at_ms` index was read by every tick's flush, and a staged fight's blows were then written through it and folded.
  - So it did not reproduce here; dev-box traces its own cause.
- **More than before.** Onlookers' minds get every blow they could see, with counts and outcomes. Before, they got only each fight's first blow, yields and deaths.

**What it saves at 200 fighters** (two runs at the same time on the same build, so both see the same host load, 40–70; 7 minutes each, 200 fighters and 16 walkers, refills on, `--no-mind`, `profile_detail`; `minds-fon-155257` with folding at 1,000 ms against `minds-foff-155257` with `witness_fold_ms` 0):

| | Fold off | Fold on (1,000 ms) |
|---|---|---|
| Ticks/s (both loaded) | 31.3 | 32.5 |
| Experience rows written a second | 3,367 | 1,070 |
| Onlookers' fight lines a second | 1,404 (first blows only) | 74, holding 2,315 blows |
| `tick.activity` + `tick.fold` (ms/s) | 238 + 0 | 174 + 52 |

- **Rows.** Experience rows fall by two thirds, so does what they write to the commitlog, and so do the lines a mind's prompt and consolidation read, while every blow is now told.
- **CPU.** Almost none is saved, about 12 ms/s. The writes saved (about 64 ms/s) go into the flush. The flush is mostly naming: `fold.labels`, 43–51 ms/s, is each onlooker's labels for everyone in its line. That is about as many label lookups as the per-start lines needed, since a line names everyone the onlooker saw fighting.
- **The 2,000 ms window.** At 2,000 ms (`minds-fwhy-161344`), lines fall to 32 a second, holding 2,725 blows, and the flush to 61 ms/s. The saving is small, because a longer window names more people a line.
- **What is left.** The fold's CPU is the cost of naming everyone in view, which the owner's rule requires (no attention cap). A cheaper label would need answers shared across ticks (`regard` is cached per transaction). That is not built.

## Remains (`battle-fold`)

- **Not merged into a pile.** Who lies where stays: each person's remains are their own structure.
- **Scene building.** An evaluation's structures are gathered only when it reads one (`Ev::structures`: a structure target, a cue, noticing, a region summary). A fighter's 15 Hz evaluation no longer copies and sorts every remains in sight.
  - At 200, `brain.scene` is 26–28 ms/s, against 55–120 on `battle-scale`.
  - The structures, gathered by about 300 evaluations a second, cost 3–5 ms/s (`brain.scene.structures`).
- **Noticing.** It checks each structure's id against the seen set. It copies their details only when something in sight is new, so a remains seen lately costs one check of its id at a look, once a second. Those checks still grow with the remains in sight: a look is a pass over everything in view, which the owner's rule keeps.
- **Expiry: the law exists.** `remains_h`, per kind in `skills.rhai`, is game hours before remains are gone (`rot` rows, `tick::expire_remains`): a person's 120 game hours, a deer's or a wolf's 60. On the default day that is an hour of real time for a person and 30 minutes for an animal. Remains holding a tablet or sign stay. Measured on the island (`minds-fwhy-161344`, `battle_diag.py`'s new `remains` sample): every person's remains lasted exactly 3,600,000 ms. So 30-minute runs never see one expire, and an 8-hour battle holds about an hour of the dead.
- **Still to measure.** The remains' cost over a whole battle, with deaths permanent, in the acceptance runs.

## The fighters' 15 Hz evaluations (analysis; nothing built)

Measured on `minds-fdet-160348` and `minds-fwhy-161344`: 200 fighters, `profile_detail` on (the parts of each evaluation timed), host load 30–50. Rates are what the loaded host ran, 26–40 ticks a second, so at 60 Hz the counts would be about 1.5–2 times higher.

**Where an evaluation's time goes** (µs a call, about 1,900 evaluations a second, of which 440–550 are the fighters' 15 Hz evaluations):

| Part | µs a call | ms/s |
|---|---|---|
| Graph run (`brain.graph`) | 84 | 162–193 |
| … of which starting an act (`brain.begin`) | 60 | 109–134 |
| … … of which the skill's rules check (`begin.check`) | about 41 | 75–84 |
| … of which resolving targets (`brain.target`: the nearest person among 100–200 in sight) | 19 | 26–29 |
| The body's alarms (`brain.alerts`) | 31 | 61–81 |
| … of which the `status_of` law (`brain.status`) | 27 | 52–68 |
| After the run (`brain.after`) | 23 | 45–55 |
| Loading and needs (`brain.load`: rows, `settle_needs`, `act::warmth`) | 20 | 39–54 |
| The scene (`brain.scene`, creatures only) | 17 | 26–28 |

**What the acts it starts come to** (`begin:` counts, `minds-fwhy-161344`, per second):
- refused "out of breath" (strike): 307;
- heal not ready: 93;
- strike still recovering: 82;
- face refused (already facing): 29;
- dodge out of breath: 29;
- step aside refused (no one coming): 28;
- heal still recovering: 25;
- heal not enough mana: 16;
- strikes started: 28.

So most of the cost is a fighter asking, many times a second, for a strike its breath does not allow. Each ask runs the skill's whole rules script (`sc.check`) to be told so.

**Cheaper paths that change nothing a fighter perceives** (not built; for the coordinator):

1. **Remember a check's refusal while nothing it reads has changed.** A strike refused "out of breath" stays refused until the pool reaches the cost. That is a time known from the pool's level and rate, unless the pool row changes first (a blow, a heal). Keyed by actor, skill and the pool row's state, a refusal answered from memory is the same answer the script would give.
   - Saves most of `begin.check`: about 75 of 84 ms/s.
   - The refusal is still recorded as now.
2. **The body's alarms from their bands, not every evaluation.** `status_of` is asked at every evaluation (27 µs). Its answers change only when a field crosses one of the law's levels: the pattern `settle_needs` already uses for the rates (`NEED_CUTS`).
   - Asking the law for its cut points and keeping the answer per band saves most of `brain.status`: about 50 ms/s.
   - The alarms are the same, at the same tick.
3. **Warmth without copying.** `settle_needs` calls `act::warmth` at every evaluation, which copies and sorts every structure within warmth reach. At the battle site that is every remains under the fighters. Visiting the chunk's structures in place, and skipping kinds that neither shelter nor warm (remains), gives the same answer.
   - Part of `brain.load`; it grows with the remains at the site.
4. **The psychological drives at most once a second.** Restless, lonely, longing and the secret kept weigh minutes of state, and are recomputed in `alerts` 15 times a second.
   - Computing them on the noticing cadence (once a second) changes when a drive is first felt by at most a second. That is a timing change, so it is listed last, for the owner.

Paths 1–3 together would remove an estimated 130–150 ms/s of about 190 in `tick.combat` at 200 fighters, on this host. To be measured, not claimed.

## Notes for Cullet's perception sweep (from `battle-fold`, for dev-box)

Dev-box owns the sweep (300–440 ms/s at 216 players on Cullet). Nothing here changes it. What the fold's measurements and code reading show about the same paths:

- **The law's answer is not the cost.** `perception::regard_of` already keeps the `perceived_of` law's answers by their whole input, across transactions (`REGARDS`). That input includes `dist` in whole metres when the law reads it (`regard_dist`; Cullet's does, the island's does not). Cullet's law only asks whether `dist` exceeds `known_within` (24 m), so whole metres give about 24 to 200 keys a pair of kinds where two would do. But each key is computed once and then kept.
- **The cost is gathering the input, per observer and target, per transaction.** The per-transaction cache (`with_answers`, keyed by observer, target, dist and `now`) is empty at each tick. So every tick, for every pair asked, `regard` does:
  - two body reads for the distance;
  - `knows_name` (acquaintance, community and family lookups);
  - `revealed`;
  - the observer's techniques, once per observer.
- **The fold's measurement of that cost.**
  - The fold names everyone in an onlooker's line through `perception::labels`, then `far::id_for`, whose `made_out` reads `far_handle` by observer and target.
  - On the island, whose law reads no distance, that cost about 15 µs a name at host load 30–70: `fold.labels`, 43–51 ms/s for about 3,000 names a second.
  - A sweep re-projecting every row every time pays the same per pair.
- **The lever both share.** Keep the gathered input per observer and target across ticks, not per transaction:
  - the distance only as the law's bands (its cut points, as `settle_needs` asks the rates law for its levels in `NEED_CUTS`);
  - the name knowledge and reveals invalidated by the writes that change them (acquaintance, membership, reveal rows).
  - A thread-local may hold this only as a cache of rows: it must give the same answers when it is empty. The SpacetimeDB reducers docs make module memory across calls undefined.
  - Not built here: it is the sweep's design, and the fold would use it too.
- **Familiarity.** Nothing in fixes 1–4 is on the sweep's path. The seen set, `familiar` and noticing serve minds' graphs, not players' perceived sets.

## The cheaper paths as built (`battle-cheap`)

The coordinator approved paths 1–3 of [the 15 Hz analysis](#the-fighters-15-hz-evaluations-analysis-nothing-built) (2026-11-12), each to be proven to change nothing a fighter perceives or does. Each is a law, on by default, with a diagnostic `_check` law that also works its answer out the old way and counts any difference (`diag:` `…:differed`).

1. **A move's check on the fields it reads** (`check_ctx_plan`; `act::checked`).
   - **Why not a remembered refusal.** The approved design was to remember a refusal while nothing the check reads has changed and the pool is short of the cost. It is exact, but it would almost never hit for a person. The strike check reads, through the predators' `dares()` branch, the fighter's hunger, the time since its last blow and its target's health. The script layer's plan of what a check reads cannot tell that branch runs only for animals, and all three change at every look (a probe of the key). So it was not built.
   - **What is built.** The check before a move starts is given a context of the fields its plan reads alone (`Scripts::check_plan`, `Reads`). The fighter's warmth, its kin near (a scan of the crowd), practice, community and home, inventory, know-how, genes and terrain are left out when unread. So are the target's community, home, owner and hosting, and its bearing and closing.
   - **Exact by construction.** The script is given every field it reads. The random roll is drawn once either way, so the world's later draws are the same. Its refusals, and the lines told from them, are the check's own.
2. **The body's alarms from their cell** (`alarm_cells`; `brain::alarm_statuses`, `BodyFacts::next_change_ms`).
   - **Why not cut points.** `status_of` states no levels of its own, so they cannot be read from it.
   - **The cell.** Each character's last answer is kept until the first moment any fact the law reads can change: a rounded level crossing its next half, a whole second more since a blow. That moment comes from the body row's levels and rates. The cell also ends on any change to that row, the stage, night or the script.
   - **The memo key.** `status_of`'s shared memo is now keyed by the facts it reads alone (`Scripts::status_reads`, from the field analysis), so focus and the rates it never reads no longer split its answers.
   - **Exact.** The law's input is the same throughout a cell, so its answer is too. The rules test `alarm_cells_give_the_law_s_answer_at_every_moment` replays five fighters' rows millisecond by millisecond over 15 s, 75,000 moments; the kept answer is the law's at every one, while the law is asked under a tenth as often.
3. **Warmth without copying** (`act::warmth`, `common::chunk_warming`).
   - Only the structures that can warm or shelter are visited, in place. They come from a per-chunk list drawn from the chunk's cached structures, and drawn again whenever that list is.
   - Remains are never in it, so the answer, an OR over those structures, is the same. `warmth_check` compares it with the full copy.

**Proofs** (verify-core, `scenes.py cheap_check_ctx`, `cheap_alarms`, `cheap_warmth`): 12 fighters on an open line, a campfire, a shelter and three dead among them, with every diagnostic law on for 60 s of strikes, blocks, heals and refusals.
- Checks on a plan's fields: about 9,400, none differing from the whole context.
- Alarm answers kept: about 20,000–23,000, against about 10,700 asked, none differing from the law.
- Warmth: about 60,000 comparisons, none differing.
- verify-player combat and `just living-check` pass.

**A hazard found on the way.** The shipped `laws_about` is close to the engine's 2,000-operation limit. Five more descriptions with an `if … else` pushed it over, and it then returned nothing: the install refused the script for want of a description of its first law (`address_m`), and every Cullet test failed. The new laws' descriptions are plain words. The next law with a conditional description may hit it again, so the limit, or the descriptions' shape, wants a look.

**Measured** in the second quiet window: see [Acceptance](#acceptance-second-quiet-window-2026-11-12-18341956-utc).

## The fourth path: the drives once a second (not built)

What it is: `brain::alerts` works out, at every evaluation, the psychological drives (restless, lonely, longing for a child, a secret kept) besides the body's alarms. A fighter's 15 Hz evaluations recompute them 15 times a second. Computed at most once a second per character instead (on the noticing cadence), they would cost a fifteenth.

**What it buys at 200.**
- **The measure.** With `profile_detail` (`minds-fdet-160348`), `brain.alerts` cost 61–81 ms/s, of which the alarm law (`brain.status`) was 52–68. The drives are the rest: about 9–13 ms/s at 26–40 ticks a second.
- **At the sustained run's rate.** 1,711 combat evaluations a second with `battle-cheap` scales that to about 15–25 ms/s. Once a second it would be about 2.
- **The gain.** About 15–20 ms/s of about 580 in the tick: some 3%, about 1–2 ticks a second at the sustained run's 45.8. Not enough to reach the contract.

**What it changes in timing.** A drive would be felt up to a second later than now (up to 900 ms, as noticing). The drives weigh minutes of state: 12 minutes uneventful for restlessness, 14 alone for loneliness, the longing's wait. So the lag is small against them, but it is a change in when a mind is told, and in when a request to think is made. A sleeper's waking or an alarm of the body would not move (path 2 keeps those exact).

**Recommendation:** not worth building for scale. The 15 Hz evaluations' remaining cost is the graph run itself (`brain.graph`, 160 ms/s with `battle-cheap`) and resolving targets among about 100 in sight.

## Acceptance, second quiet window (2026-11-12, 18:34–19:56 UTC)

Three worlds ran at once on the same box, each with the same `battle_diag.py`:
- `battle-scale` `109690de` (fixes 1–3, the before arm);
- `battle-fold` (fix 4);
- `battle-cheap` (the cheaper paths on top).

The island seed: its about 310 residents, all AI, and no mind service. Fighters are packed within 7 m of the site, walkers forage, and profiling is on. The four other worlds on the service were paused, none ticking. Host load over the window, one sample every 10 s (487 samples): 1.7 to 12.5, median 4.4. Evidence: `.local/living/verify/minds-a100*-193501`, `minds-a200*-200652` and `minds-r200*-203858`, with `acceptance-2/` (the load log and summaries).

**As approved: deaths permanent, 30 minutes each** (`--no-refill`).
- At 100 fighters (116 walkers) the battle is over in about 2 minutes: about 40 fighters are left at minute 1 and 15 at minute 2.
- At 200 (16 walkers) it also lasts about 2 minutes: 160 at the first sample, 33 at minute 2. Then 2–6 fighters remain, among the dead.
- Population starts at about 500 and ends at 286–386.
- During the battle a fighter's scene held about 50 others at 100 (max 98), and 91–106 at 200 (max 158–170). Skill uses were 10–18 a second in the first minute.

| | Arm | Whole run: ticks/s, over 16.7 ms, p99 median | The battle's first minutes |
|---|---|---|---|
| 100 | `battle-scale` | 60.8, 0.2% (110 of 53,961), 4.7 ms | 56.8 then 58.5 ticks/s; 91 then 17 ticks over |
| 100 | `battle-fold` | 59.3, 0.2% (114 of 53,909), 4.3 ms | 52.8 then 58.8; 107 then 7 |
| 100 | `battle-cheap` | 59.3, 0.2% (102 of 53,944), 4.7 ms | 53.1 then 59.3; 100 then 2 |
| 200 | `battle-scale` | 59.8, 0.4%, 3.9 ms | first 2 min: 54.9 ticks/s, 5.0% over, p99 median 24 ms |
| 200 | `battle-fold` | 59.9, 0.2%, 3.6 ms | 57.8, 3.0%, 17 ms |
| 200 | `battle-cheap` | 59.8, 0.3%, 3.7 ms | 58.7, 3.4%, 20 ms |

- **The battle is too short** to separate the arms with deaths permanent. Its first sample is often only one or two of the 30.
- **The aftermath** is the rest of each run: about 60 Hz with all the remains lying at the site (129 at 100, 217–225 at 200). Remains at rest cost almost nothing.
- **Remains** lasted their law in every arm: a person's 3,600,000 ms (an hour of real time), an animal's 1,800,000 ms. No 30-minute run sees one expire.

**Added within the window: the sustained battle**, 200 fighters and 16 walkers with refills on, 15 minutes (`minds-r200*`). It is the workload the first window measured alone at 26.8 ticks/s. About 520 alive; about 93–96 others in a fighter's scene (max 187–192); 47–48 skill uses a second; about 1,700 refills.

| Arm | Ticks/s | First 5 min → last 5 | Over 16.7 ms | p99 median (worst) | Experiences/s |
|---|---|---|---|---|---|
| `battle-scale` | 30.0 | 36.0 → 19.1 | 59.4% (9,621 of 16,206) | 49 ms (262) | 6,932 |
| `battle-fold` | 36.0 | 41.4 → 25.4 | 40.6% (7,992 of 19,695) | 35 ms (181) | 2,401 |
| `battle-cheap` | 45.8 | 48.6 → 34.3 | 17.7% (4,443 of 25,099) | 28 ms (84) | 2,356 |

- **What the fold saves.** Writing what onlookers see (`tick.activity`) falls from 223 to 138 ms/s; the fold's own flush takes 58–63 back. Experience rows fall by two thirds.
- **What the cheaper paths save.** A fighter's evaluation at combat cadence costs 0.13 ms with them, against 0.18 with the fold alone and 0.23 before it (`tick.combat` over its evaluations: 224 ms/s for 1,711 a second, 244 for 1,320, 243 for 1,042). The faster world runs more evaluations in the same time.
- **The drift** comes with the refills, about 1,700 in 15 minutes, and the about 1,750 remains at the site. The load generator dropped every refill into the battle, all the dead at once every 3 s.
- **The load generator is fixed** (`battle-cheap`, `battle_diag.py`).
  - A refill now appears 30 m off (`--refill-from`) at a random bearing, one at a time, at most one every 0.5 s (`--refill-gap`).
  - It walks in, and is given the fight within 9 m of the site.
  - A 3-minute test with 40 fighters (`minds-loadgen-*`): 43 refills arrived one by one as fighters fell, 1–5 walking in at any moment, 33–40 fighting throughout.
- **An offset between builds.** Idle, the `battle-scale` world ticks 61.5 times a second and the other two 59.5, with no tick over budget. The tick interval (16,667 µs) and `bench.py` are the same in both, so it lies in how the ticks are scheduled, not in the work. To be looked at.

## Verification it would need

- **Unit tests:**
  - familiarity eviction keeps rows touched within the horizon, and evicts by age;
  - the novelty schedule;
  - the wake coalescing law (party immediate, bystander coalesced);
  - the fold's text: counts and outcomes from a list of seen events;
  - the fold's sight list: an onlooker behind a wall, or facing away under `fov_on`, is not in a blow's list.
- **verify-core scenes:**
  - *dense novelty:* an observer among 150 people and 300 remains notices each remains exactly once in 5 minutes, and no `familiar` row of a thing in view is evicted;
  - *witness fold:* O watches A against B (hit, block, kill) and C against D. O's folded line names both pairs, the counts and the death. A watcher behind a wall gets nothing of A and B. A and B still get their own `attacked`/`combat` lines and fight reports at once;
  - *witness wake:* a bystander's graph reacts within `witness_wake_ms`, and a party reacts in the same tick.
- **verify-player and verify-client:**
  - a player onlooker's `my_experience` has the same folded line;
  - its `combat_seen` feed is unchanged;
  - `fight_seen` is private.
- **verify-minds:** the folded line reaches a think prompt and consolidation with its counts. Consolidation's input volume per minute of battle is measured before and after.
- **Scale:** `battle_diag.py` at 100 and 200 fighters, 30 minutes each:
  - 60 Hz holds, with over-budget ticks counted;
  - woken evaluations, `familiar` lookups and evictions stay flat over time;
  - table growth and commitlog rate are bounded;
  - then the 216-character gate (`gate.py`) with the battle inside the town, against the gate's last record.
- **Quiet host:** these acceptance runs need a quiet box: about 70 minutes, two 30-minute runs and setup. The collapse measured here does not, since it is the same on a quiet and a loaded host.

## An incident during this measurement

Deleting the scratch database of `minds-bdat-124436` while its world still ran 35–54 ms ticks made SpacetimeDB 2.14.1 panic ("local durability: actor vanished: SendError", `crates/durability/src/imp/local.rs:358`, while "exiting database"). The panic took the whole trial server down for about a minute at 12:52 UTC.

- **Restoring it:** I started it again and re-applied its open-files limit; the other databases came back.
- **Other agents:** mind services connected to it then exited on the disconnect.
- **The guard:** `battle_diag.py` now pauses a world and waits before deleting it. `cue_cost.py` (on `cue-cache`) needs the same guard.
- **Earlier deletions:** deleting a collapsed world at 1.6 ticks a second did not crash the server.

## SpacetimeDB documentation and source consulted (2026-11-12; docs 2.0.0, pinned 2.14.1)

- [Performance](https://spacetimedb.com/docs/tables/performance/): "smaller, more focused tables"; fewer fields touched per update.
  - `mind_state` is rewritten at every evaluation with its 96-entry `seen` list, a large share of the 4–5 MB/s commitlog. Fix 1 moves that list off the row.
- [Indexes](https://spacetimedb.com/docs/tables/indexes/): btree equality lookups, which is what `familiar.by_actor_thing` is.
  - Each lookup is cheap. The cost is their number: up to 200k a second.
- [Tables](https://spacetimedb.com/docs/tables/) and [access permissions](https://spacetimedb.com/docs/tables/access-permissions/): a private `fight_seen` table is readable by reducers and the owner only.
  - It is a new table, a safe automatic migration.
- [Reducers](https://spacetimedb.com/docs/functions/reducers/), "Global and Static Variables Are Undefined Behavior" (read for fix 4):
  - Relying on module memory across reducer calls is undefined: an instance may be fresh, replaced on publish, run concurrently or restarted, and memory changed in a rolled-back transaction may remain.
  - So the fold's pending blows are `fight_seen` rows. Thread-locals stay caches of rows.
  - The same page says "If a reducer throws an exception or returns an error, all of its changes are automatically rolled back."
- [Event tables](https://spacetimedb.com/docs/tables/event-tables/) were considered for `fight_seen` and not used: their rows exist "only for the duration of the transaction that created them", and the fold must hold blows across ticks.
- Versioned source: `crates/durability/src/imp/local.rs:358`, where the delete-time panic is.
