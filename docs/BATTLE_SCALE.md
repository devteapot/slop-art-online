# Battle scale: why a battle of minded fighters collapses (diagnosis and fix design, 2026-11-12)

Status: **fixes 1–3 built on branch `battle-scale` (2026-11-12); fix 4 (folding) held**, to be built only if 1–3 do not reach the bar. The diagnosis below was measured on `battle-diagnosis` (from main `b36a938c`). Its only code change was diagnostics: profiling-only counters (`common::diag`, one `diag:` log line a second while `set_profile` is on, nothing otherwise), spans on `brain.noticed`, `brain.graph`, `brain.after` and `perceive.scene_json`, and the measurement tool `living/tools/battle_diag.py`. The target is the performance contract's 200-character local battle (docs/PERFORMANCE_CONTRACT.md) under the owner's rule: **no attention cap; everything within vision at full detail.**

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

## Fix design (fixes 1–3 now built, fix 4 held)

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
- Versioned source: `crates/durability/src/imp/local.rs:358`, where the delete-time panic is.
