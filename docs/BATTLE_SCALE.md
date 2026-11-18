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

*Correction (2026-11-13):* the ticks per second in this table come from `bench.py`, which then divided the `stats` row's count (written once a second) by the wall time around two SQL calls. Each carries up to about ±3% from that division; ticks over 16.7 ms and p99 come from the tick log and are unaffected. `bench.py` was fixed in `battle-cheap`; see "An offset between worlds, not builds" below.

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

*Correction (2026-11-13):* the ticks per second here carry the same `bench.py` error, up to about ±3%; the rows and span costs do not.

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
- **An offset between worlds, not builds: the measurement.** Idle, the `battle-scale` world measured 61.5 ticks a second and the other two 59.5, with no tick over budget. `bench.py` took its counts from the `stats` row, which housekeeping writes once a second with its stamp, but divided them by the wall time around two SQL calls. So a window could gain or lose one second's ticks, about ±2 a second over 30 s. Windows every 60 s keep one phase to housekeeping, so a world kept its offset for the whole run; `battle-cheap` alone, in another run, measured 62.3. Since `battle-cheap`, `bench.py` divides the counts by the stamps' interval. The acceptance tables above carry that error: each run's ticks per second within about ±3% (±1 at 30, ±2 at 60). Ticks over 16.7 ms and p99 come from the tick log and do not.

## The lazy scene (`scene-lazy`)

The profile after battle-cheap (2026-11-13; 200 fighters sustained with the fixed load generator, `profile_detail` on, host load 25–42, so per-call costs and shares only) put the graph run at 25% of the tick, about 88 µs an evaluation:
- starting acts, 60 µs (the move's check 54 µs, mostly refusals for want of breath);
- the body's alarms, 41 µs;
- the scene, 21 µs, of which the sight test of every creature in range was 16 µs;
- the nearest pick, 4.3 µs, scanning 2.5 of about 64 creatures in sight.

The rest of the tick: combat resolution 30%, woken evaluations 24%, the fold's lines 12%, noticing 10%.

**What is built** (the `scene_lazy` law, on; `scene_lazy_check` a diagnostic):
- **Lazy sight.** A graph's scene is what the body senses (`perception::Sensing`): every creature within gathering range, nearest first, each tested for sight only when a reader comes to it. The nearest pick (`Ev::first_seen`) and a creature looked up by id (`Ev::seen_by_id`: `visible_creature`, and the `threatened` condition while sight has a field) test only as far as their answer needs: a fighter tests two or three creatures, not all in sight.
- **Whole-list readers** (`Ev::creatures`: desires, `count`, `doing`, cues, noticing, the stranger filter) test every one. Resources and the heard list are gathered when first asked for.
- **No copy.** The nearest pick reads the list in place, not a copy of the scene.
- **Exact.** Same candidates, same order (`creatures_near`'s, by distance, ties in a fixed order), same sight test. `perception::sensed` is now `Sensing::all`, so both paths share one implementation. No state outlives an evaluation, so rollback and module memory do not arise.
- **The proof** (verify-core `scene_lazy`): 12 fighters with `scene_lazy_check` on compared 10,195 lazy answers with sight all round and 9,152 by facing (1,561 by id). None differed. With the law off, no lazy answer was made and the battle went on.
- **Expected saving** from the profile: about 11–13 ms/s of the sight tests and 3 ms/s of the copy at 200 fighters. That is about 3% of the tick, about +1.5 ticks a second at the 45.8 of the second window. To be measured in the next acceptance.
- **One profiling count changed meaning.** `graph_scenes.seen_mean` (`note_scene`) counts only scenes whose whole list was built (noticing, desires, cues), not every graph evaluation's.

## Profile: combat resolution and woken evaluations (`battle-profile`, 2026-11-13)

**The run:**
- `minds-prof200c-034627`, on main with scene-lazy (`battle-profile` 99a574a3).
- `battle_diag.py --battle 200 --walkers 16 --minutes 8 --refill-gap 0.25 --no-mind --law profile_detail=true`, on :3320 after the R3 batch had ended.
- 161–177 fighters held at the site, about 500 alive in all. Host load 5–13.
- Figures are the mean of windows 3–9: 48.9 ticks/s, tick 243.9 ms/s. Shares are of the tick.
- With `profile_detail` on, spans and counters add their own cost, so per-call costs are upper bounds.
- **Evidence:** `.local/living/verify/minds-prof200c-034627` in the `battle-profile` checkout, archived in `~/slop-evidence/battle-profile-20261113.tar.zst`.
- **Instrumentation:** committed on `battle-profile`, gated by `profile_detail`. Also archived as a diff: `~/slop-evidence/battle-profile-instrumentation-20261113.diff`.

| Part | ms/s | Share | Calls/s | Per call |
|---|---|---|---|---|
| Fighters' 15 Hz evaluations (`tick.combat`) | 93.7 | 38% | 474 | 198 µs |
| **Combat resolution (`tick.activity`)** | 59.4 | 24% | 55 completions | 1.07 ms |
| … a blow's effects (`act.damage`) | 46.1 | 19% | 28.9 | 1.6 ms |
| … … the chronicle's repeat check (`common::chronicle`) | 17.7 | 7% | 18.7 | 0.95 ms |
| … … what onlookers saw (`fold::blow`, about 62 onlookers a blow) | 11.6 | 5% | 29.7 | 0.39 ms |
| … … the victim's request to think (`request_waking`; nearly all its `scene_json`) | 9.5 | 4% | 18.8 | 0.51 ms |
| … … percepts, noise, deaths | about 9 | 4% | | |
| … the skill's context, check, script and finish | about 12 | 5% | | |
| **Woken evaluations (`tick.wakes`)** | 42.8 | 18% | 154 | |
| … fighters (on the combat cadence) | 32.1 | 13% | 132 | 138 µs |
| … everyone else | 9.6 | 4% | 22 | 246 µs |
| Onlookers' folded lines (`tick.fold`; naming, `fold.labels`, 16.8) | 28.2 | 12% | 39 lines | 0.73 ms |
| Slot evaluations (`tick.slots`) | 16.1 | 7% | 82 | |

- **The chronicle's repeat check is the largest single item in combat resolution.**
  - Each first blow and each killing writes a chronicle line (`common::chronicle`).
  - To fold repeats ("(×3)"), it reads every chronicle row of the last two minutes, then compares the newest 40.
  - At about 19 lines a second, that is about 2,300 rows read for 40 compared. Its cost does not grow with the battle's length, only with its rate.
  - **An exact fix (E):** read only the newest rows. Read the last second; widen the window (4 s, 16 s, then the full 120 s) until it holds 40 rows or more.
    - The 40 newest rows are the same, in the same order: the same index range scan, cut later.
    - A `chronicle_recent_check` law would compare it with the full read.
    - Saves about 15–17 ms/s, about 7% of the tick.
- **Fold's per-blow sight tests** (`fold::blow`) cost about 6 µs per onlooker. That is the cost of the rule (every onlooker who could see it, by `witnessed`'s test); nothing exact is left to remove.
- **The victim's request to think** builds its `scene_json` (0.46 ms) at every first blow, whether or not a mind service is connected. Building it when the mind service takes the request would see a later scene, so that would not be exact.
- **What wakes whom** (wakes a second, by caller):
  - a bystander's held-back wake coming due: 52.5;
  - an act ending, which wakes its actor: 36.8;
  - a fight's first blow, waking its onlookers: 31.3;
  - a percept with salience 0.6 or more: 20.7;
  - a windup's target: 17.4;
  - a struck victim: 14.7;
  - others: 4.
  - Of 154 woken evaluations a second, 132 are fighters already on the 15 Hz combat cadence. A wake that comes in the tick of the fighter's own cadence slot costs nothing extra (one evaluation a tick).
  - **Not exact:** skipping bystander wakes for those on the cadence would delay their response by up to three ticks (50 ms). It would save up to about 10 ms/s. It is a timing change, so it is listed here, not proposed.
- **Profile counts:**
  - 709 evaluations a second, with 5.8 graph-node visits each.
  - 560 skill-script calls a second.
  - The `status_of` law asked 298 times a second (its cells answered 411 more), of which its memo answered 30 and 268 ran (note B).
- **Remains grew linearly:** 120 to 845 at the site over 8 minutes (about 1.6 a second). A look's structures went from 19 to 112, and noticing them from 3.3 to 16.6 ms/s (note C).

## Design note C: noticing structures (not built)

**What a look does now** (`Ev::noticed`, about once a second for each character a mind runs, fighters included):
1. It gathers every structure within sight radius (`Ev::structures` → `common::structures_near`). Each one is copied, with its `kind` string, and the list is sorted by distance.
2. For each structure, it checks the id against the seen set (`recently_seen`, a hash lookup in module memory). A hit whose mark is older than 45 s is re-marked.
3. Only a structure missing from the seen set goes to `familiarity`. That reads its `familiar` row by index, inserts one at first sight, and otherwise refreshes `last_ms` and `times` at most every 30 s.
4. Only when something is new are the details copied and tiles joined (`joined_tiles`), and the "You notice …" line written.

Structures are noticed by radius alone: no facing, no walls. In a battle the remains are structures. They last `remains_h` (an hour of real time for a person on the default day), so a site holds about an hour of its dead.

**What it costs** (the profile above):
- **Per look:** 65 structures on average, rising from 19 to 112 as the remains grew from 120 to 845. Of these, 1.4% were new (169 a second, over 183 looks a second).
- **Noticing structures** (`noticed.structures`): 62 µs a look, 11.4 ms/s, 4.7% of the tick. It rose from 3.3 to 16.6 ms/s over the run.
- **Gathering and sorting the list** (`brain.scene.structures`): 12.7 µs, built by noticing in 103 of 109 builds a second. The rest is the per-structure checks and the new ones' rows and lines.
- **Projected to an hour of remains:** about 5,800 at the site, about 7 times the end of this run. That puts noticing structures near 115 ms/s, about half of today's tick.
- So C matters for the 8-hour target, not for 30-minute runs.

**What decides the lines.** `familiar` is private. For structures, the authority reads it in two places only: newness (whether a row exists) and `prune_familiar`.
- **Newness.** Every structure that is looked at gets a row at its first look. So "new to me" is "I have no row for it". The seen set is a fast path in front of that row.
- **Pruning.** Over 2,048 rows a character, the oldest by `last_ms` go first. A row touched in the last 60 s is spared, and so is a thing in the seen set within 90 s.
- **`times`** is never read.
- So the lines can differ only if the same rows do not exist at the same looks, which depends on what pruning takes.

**How often a battle crosses 2,048 rows:**
- **Never in this run.** 3.9 prune checks a second (one per 64 new rows of a character) found no character over 2,048.
- **Fighters never get near it.** They live about 95 s (about 1.8 deaths a second at 170 fighters), gaining about 1.5–2.5 rows a second: a few hundred rows a life.
- **Long-lived onlookers can.** Walkers, townsfolk and survivors who stay in sight of the site gain rows at about the rate of deaths and arrivals in view. An onlooker who sees every death and every arriving fighter (about 3.5 new things a second at this rate) would cross 2,048 in about 10 minutes. One who sees a sixth of them, as a look sees a sixth of the remains here, would cross in about an hour.
- **Not measured:** per-character counts at the end. The run's database was deleted at cleanup, and the counters give rates only. A 30-minute run reading `familiar` counts per actor before cleanup would settle it.

### C1: noticing reads in place (exact, no new state)

- **Change.** Noticing walks each chunk's cached structure list in place (`chunk_structures`). It tests distance and checks the seen set by id. It does not build the copied and sorted list.
- **When something is new.** Only then does it build the full list as now and redo the pass in its order. The lines, the joined tiles and the order of the `familiar` inserts are therefore the same.
- **Exact because:** the same structures (distance ≤ radius), the same seen-set calls per id (their effect does not depend on order), and the same `familiarity` calls in the same order.
- **Saves:** the copy and the sort, about 12.7 µs of the 62 µs a look (about 2 ms/s now). It grows with the remains as the rest does.
- **Keeps:** one hash lookup per structure in sight per look, which is most of the cost.
- **Other readers unchanged.** Cues, structure targets and region summaries still build the list when they read it.
- **Proof:** a `notice_inplace_check` law that runs both and compares the set of new ids and the lines, as `scene_lazy_check` does.

### C2: a look checks only what changed (incremental; needs a row and a decision)

**State.** One row per character a mind runs, `look`: where its last look stood, its radius, the highest structure id then, and when.

**A look:**
- No row, or the row is older than 45 s: a full look as now.
- Otherwise it walks the chunk lists of its sight disc in place. A structure gets the full check only if it is newer than the row's id, or was outside the last look's disc. That covers structures that came into view by moving, by the radius growing (light), or by being built.
- Every other structure in sight was handled at the last look and is skipped: no hash lookup, no row read.
- Each structure costs one or two float tests. When something is new, the full list is built as in C1.
- The row is then rewritten.

**Why a row, not module memory:**
- A tick that fails rolls back its `familiar` inserts. A cache in module memory would still say those structures were looked at.
- SpacetimeDB does not keep a module's memory between reducer calls ([reducers](https://spacetimedb.com/docs/functions/reducers/), "Global and Static Variables Are Undefined Behavior").
- Rewriting one small row per look is about 180–260 writes a second at 200 fighters, about 1–2 ms/s. That is the same order as `mind_state`'s rewrite (6 µs each).
- The table is private, indexed by its primary key only, and holds one row per character. Its row goes with the character (`forget_dead`).
- It is a new table, not a column on `mind_state`: a column append rewrites the table and disconnects every client on 2.14.1.

**Saves:** most of the stayers' checks.
- At this run's end, that is perhaps 8–10 ms/s of the 16.6.
- At an hour of remains, most of a projected ~115 ms/s.
- What is left is the new structures' rows and lines, which follow the death rate, not the pile.

**What it changes (not exact):**
- Skipped structures are not re-marked in the seen set every 45 s. A structure in view keeps an old mark, so after it leaves view and comes back its row is refreshed earlier than now. Pruning would also no longer spare it as "in the seen set".
- To keep "never forget what is in view", pruning would spare a structure within the last look's disc as well. That needs a lookup of the structure's position for each candidate, and pruning is rare: every 64 inserts.
- **Effect on the lines:** the same lines while a character holds fewer than 2,048 rows, which fighters never reach. Above that (long-lived onlookers of a long battle, above), which out-of-view row goes first can differ: the ordering of `last_ms` changes, while the rule "the oldest out-of-view first, never one in view" holds.
- That ordering is a memory bound, not a rule a player sees. **Whether it is acceptable is the general coordinator's call.**

**Proof:**
- A `notice_delta_check` law that runs the full pass next to the incremental one. It compares the set of structures each would send to the full check, and the lines.
- A verify-core case with a battle among remains, a walker crossing the site, and a fire built in view.

**Recommendation:**
- C1 is exact, but small today; it is worth building with E as one small exact branch.
- C2 is what an 8-hour battle needs, and waits on the decision above.

## Design note B: the `status_of` law in per-meter parts (not built; for the general coordinator)

**What it costs** (the profile above):
- The body's alarms (`brain.status`): 29.2 ms/s, 12% of the tick, over 633 calls a second.
- The character's cell answered 411 of these; 298 asked the law. Of those, the rules' memo answered 30 and 268 ran the script.
- About 6 ms/s of the 29 is this profile's own diagnostic (`status.diag`), so an ask costs about 75 µs.

**Why the memo misses:**
- Its key is every fact the law reads: `hunger`, `energy`, `share.health`, `hp_rate`, `night`, `kind`, `hurt_ago_s`, `stamina`. Any one changing makes a new key.
- Facts changed at an ask (`status:changed:*`): `stamina` at 74% of asks, `hurt_ago_s` 14% (it counts seconds up to 120 after a blow), health 6%, energy 4%, hunger 1%.
- 57% of asks changed exactly two facts: a meter and its share. Stamina is the usual one. Focus is the other; it changed at 17% of asks, but the law does not read it.
- Most asks therefore change the inputs of one part only. The counts do not say exactly how many; the check law's run would.

**The change** (a script-contract change):
- `skills.rhai` declares the law's parts: `fn status_parts() { ["hunger_status_of", "energy_status_of", …] }`. Each part takes the body (`a`) and returns its statuses: hunger, energy, health, freezing, in combat, out of breath, slowed, wasting or recovering, as `status_of` already builds them.
- The engine works out each part's read plan, as it does for skill checks, and memoizes each part on its own reads. The body's statuses are the parts' answers joined in the declared order.
- A change of stamina alone then re-asks one small part: out of breath, which reads `stamina`. Its context map holds that one fact, not the whole body.
- `status_of` stays as the reference: it calls the same parts in the same order. A `status_parts_check` law compares the joined parts with it at every ask, as `alarm_cells_check` does.
- **Exact when** the parts joined are `status_of`. The check law proves it for the script as written; a script whose parts differ from its `status_of` is caught by the check, not silently accepted.

**Saves:** an estimate, to be measured.
- If a one-part ask costs about 10–15 µs against the whole law's 75 µs, and most of the 268 runs a second (stamina alone is in 74% of them) become one part, they save about 60 µs each: about 10–16 ms/s, 4–6% of the tick.
- The cells' 411 answers are unchanged.

**What it costs to build:**
- A script API (`status_parts`) and its documentation in the script contract.
- Per-part plans and memo in `living_rules::script::body`, and the check law.
- A verify-core case covering each status, in and out of a fight.
- Every world script that defines `status_of` without parts keeps working as now.

**Decision for the general coordinator:** whether to extend the script contract for this; A waits.

## Exact paths E and C1 (`battle-exact-2`)

From the profile of combat resolution and woken evaluations (`battle-profile`, 2026-11-13): approved by the general coordinator as one exact branch. Each has a law (on) to roll it back and a `_check` law (a diagnostic) that also does the full computation and counts any difference.

- **E: the chronicle's repeat check reads its newest entries first** (`chronicle_recent`, `chronicle_recent_check`).
  - Each first blow and each killing writes a chronicle line (`common::chronicle`). To fold a repeat ("(×3)") it compares the newest 40 entries of the last two minutes. It used to read every entry of the two minutes to find them: about 2,300 rows at 19 lines a second, 0.95 ms a call, 7% of the tick at 200 fighters.
  - It now reads the last second, then 4 s, 16 s and the whole window, and stops at the first window that holds 40 entries from before this tick.
  - **Why "before this tick":** inside the tick's transaction a range read gives the rows written in it (this tick's entries and repeats, all at `now`) apart from the committed ones, not merged by `at_ms` (SpacetimeDB 2.14.1, found by the check law: verify-core `chronicle_recent`, one difference in 68 and in 460 compared, before this rule). Entries before `now` are committed, and a later start's committed rows are the tail of the whole window's. So a narrow read with 40 of them has the full read's last 40, wherever this tick's rows come.
  - **Note:** this also means "the newest 40" has always meant the newest 40 *committed* entries when 40 are in the window: a line repeated within the same tick is not folded into the entry written earlier in that tick. Unchanged here (exact), recorded for whoever revisits the chronicle.
  - **Proof:** verify-core `chronicle_recent` 5/5: 457 reads compared, none differed; the narrow read used 83 times and the whole 374; off, neither, and lines still written.
- **C1: noticing reads the structures in sight in place** (`notice_inplace`, `notice_inplace_check`).
  - A look walks the chunks' cached structure lists (`common::for_structures_near`, the order `structures_near` gathers in) and builds the copied, sorted list only when something in sight is new.
  - **The same calls in the same order where order matters:** a structure seen lately (its mark under `SEEN_MS`) is re-marked first; that changes no answer `prune_familiar` gives, which spares marks under `SEEN_MS` either way. Every other is marked and its familiarity asked nearest first, ties as in the full list (its sort is stable). Those calls insert rows and may prune, so they keep the full pass's order. A structure's seen key (`0x4000_0000 | id & 0x3fff_ffff`) is shared only by ids 2^30 apart.
  - **Saves** the copy and the sort: about 12.7 µs of the 62 µs a look at the end of the 8-minute profile (about 2 ms/s), growing with the remains. The per-structure check of the seen set stays (C2, not built, would remove most of it).
  - **Proof:** verify-core `notice_inplace` 6/6: 13,427 looks compared, none differed; the full list built for 159 of them; off, no in-place look, and new structures still noticed.
- **Their words** are `law_about(l, name)` entries (laws-about-list, aba5c876). The old `laws_about` map would have passed the engine's 6,144-byte string limit with these four, since the engine counts all the strings of a returned map together; laws-about-list reads one law's words at a time.

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
