# Attention E2: the real cost of attending, and the ceiling at 216 viewers

Status: **measurement**, 2026-11-22, dev-box. This answers [ATTENTION_BUDGET.md](ATTENTION_BUDGET.md) v2's E2 (§8): the per-individual cost i, the crowd row cost, and the ceiling from §6's formula. It also covers churn, the visible flicker, a capacity burst and a breakdown of the per-viewer floor.

The prototype lives on branch `attention-e2` only and never goes to main. This note goes to main alone, on the docs-only branch `attention-e2-doc`. Code paths below are on `attention-e2` unless they name main. The design is [ATTENTION_BUDGET.md](ATTENTION_BUDGET.md) v2 (`ca48edd56`, branch `attention-budget-v2` at `48ad5161c`). dev-box's answers to its questions are `docs/ATTENTION_BUDGET_DEVBOX_ANSWERS.md` on branch `attention-budget-devbox`.

## 0. In short

- **No attention ceiling fits 60 Hz at 216 viewers on this fixture and host, not even 0.**
  - The per-viewer budget is about **1.06 ms/s** (17.7 µs a tick): 600 ms/s for the whole tick, less this host's 371 ms/s with no viewers, over 216. v2 used 1.4–1.7 from the Spark's faster core.
  - The per-viewer **floor**, with nobody attended, measures **4.3–5.0 ms/s** at 16 viewers. That is 4.0–4.7× the budget (2.8–3.3× v2's 1.5).
  - Attending 16 adds **2.0–2.2 ms/s** on top.
- **The missing term in v2 §6 is that floor.** v2's formula has no per-viewer constant. The measured one is larger than the whole budget, and most of it is not attention's to cut (§4).
- **The per-individual cost** (16 viewers, 10 m ring, clean at 58–60 ticks/s):
  - **marginal** across ceilings 8–32: **67 ± 22 µs/s** per attended individual (the slope over 8 runs; the standard error is from the run-to-run spread);
  - **average** from none to 16 attended: **130–140 µs/s** per individual. The first few attended are the near, fighting ones and cost about three times the later ones.
  - **This corrects my interim figures.** The "about 35 µs/s" and "floor about 6.2 ms/s" I reported earlier came from one run per arm. 6.0–6.2 is where the 8–32 line meets zero attended, not the floor; the measured floor is 4.3–5.0.
- **Attention still pays.** At 16 viewers it cuts the per-viewer cost from 11.1 ms/s (128 in sight) to 6.5–7.3 at a ceiling of 16. At 216 viewers (a **saturated host**) it lifts the tick rate from 16.5 to 21–27 at a ceiling of 16, and to 36 with nothing attended.
- **Holds are what stop flicker.** With the shared selector `heed` (Spark, `attention-exp` `aa3d4d9e2`) and its holds, at 216 viewers and a ceiling of 16, a viewer sees **7–8 flip-backs a minute within 2 s**, 6% of attended creatures affected. Without holds it is 378, and my own instinct with no grace gives 612. This matches the Spark's replay (3.4 with holds, 169 without).
- **A capacity drop mid-fight (16 → 6) causes no tick spike** at 16 or 216 viewers (Q11).
- **The crowd rows are cheap at 16 viewers** (about 0.08 ms/s per viewer, 13–19 writes per viewer-second). At 216 the crowd's share grows with the viewer count; see §3.3.
- **Throng sight at 1 Hz saves nothing.** Sight is only about 0.24 ms/s per viewer, and the cached throng costs more than it saves.
- **Off is off.** With every law off, both measured modules are byte-identical in behaviour to main `a6375a70e`: 1,800 ticks, 113 tables, 47,627 rows. With `attend_on`, the run differs from tick 2.

## 1. Method

### 1.1 The fixture

- **The battle:** `living/tools/battle_viewers.py` on Cullet, as docs/COMBAT_PHASE.md's series.
  - 200 AI fighters (`spawn_battle`), kept at 200 (`--keep-fighters 1`, refill when below);
  - SDK viewers as player characters, `--keep-alive 0.5`;
  - `--paused-placement --battle-after-placing`;
  - the shipped delivery defaults: tiers, cues and every copy table;
  - L1 profiling (`--detail --full-log`). The L2 runs add `profile_detail=true` (§4.2);
  - 20 s warm-up, then a 60 s window.
- **Viewers:**
  - **16 viewers on a 10 m ring** (110–128 in sight): the clean set, at 58–60 ticks/s;
  - **216 viewers on a 26–32 m ring** (about 70 in sight): a **saturated host**, at 16–36 ticks/s.
- **The reference:** 0 viewers, 60 ticks/s, database thread 371.5 ms/s, tick 365 ms/s, 6.2 ms a tick.
- **Cost per viewer:**
  - at 16 viewers, the database thread's ms/s, less the reference, over the viewers;
  - at 216 viewers, ms a tick, less the reference's 6.19, over 216, in µs a tick.
- **The battle stays live in every arm:** 55–61 blows a second, 123–153 fallen in the window, 97–100% of the 200 alive at the end. `--sides` was not used: the keeper counts only names that start with "Fighter".
- **Runs:**
  - two runs per arm, interleaved by set, unless marked "1 run";
  - the run-to-run spread at 16 viewers is about ±0.5 ms/s per viewer, so differences under about 0.5 are within noise.

### 1.2 The host

- **The host:** dev-box, the scratch server `e2-stdb` (SpacetimeDB 2.14.1), started through `systemd-run --user --scope` with `LimitNOFILE=524288`.
- **Load and processes:** recorded for each run in `procs-*.txt` and `load1`.
- **The gate lock:** my builds did not pause for it, because nobody held it.
- **Noise from the runner services:** the crash-looping `github-actions-runner@tb-*` services, not ours, cost about one core intermittently from about 01:44 UTC. Every run from `a-off-r2` on was made with them running. They were reported to the coordinator.
- **Replicas:** SpacetimeDB 2.14.1 keeps a deleted database's replica directory. Those replicas were cleared between runs in `vis.sh`, `d.sh` and `e.sh` to keep the disk at or above 45 GB free.

### 1.3 The prototype (branch `attention-e2`)

`living/authority/src/attend.rs` is wired into `perception::sweep_one` after `far_cap`. It applies only to human players' perceived sets, the only sets that exist (answers Q1). Its laws are value-only and off by default:

| Law | Meaning |
|---|---|
| `attend_on` | the switch (false) |
| `attend_ceiling` | capacity (16) |
| `attend_burst_cap` | a lower capacity flipped mid-run (0 = none) |
| `attend_policy` | who is attended: 0 the engaged (past capacity), then the nearest; 1 the engaged, then a random rank redrawn every `attend_reorder_ms` (a high-churn stand-in); 2 my reading of v2's person instinct (§2.4), bounded by capacity; 3 the shared `heed::select` with holds; 4 `heed` without holds |
| `attend_grace_ms` | a dropped creature stays delivered this long (0) |
| `attend_crowd_on` | `seen_crowd` rows: 6 m cells at 1 Hz, at most 48, farther cells merged 2×2, written only when the content changes after 0.5 m quantizing; `viewer = :sender` row-level security |
| `attend_vis_on` | the visible-churn counters (§5) |
| `attend_throng_sight_ms` | throng members' sight cached for this long (0) |

**Which selector each arm ran:**
- **Policies 0–2** were measured on module `e2-cullet` (`d50674e0377e`, commit `b226aa8e0`, without `heed`). Sets A, B, C and D used it.
- **The visibility runs** (`vis-c-*`) used `e2-vis-cullet` (`493dcd2f8c11`). It was built from `b226aa8e0` plus the visibility counters before they were committed, so it matches no commit exactly. Costs are not read from these runs.
- **Policies 3 and 4** used `e2-heeds-cullet` (`575bd6a4eaac`), commit `aeee62046`, with `living/rules/src/heed.rs` and `seeds/heed.json` from `attention-exp` **`aa3d4d9e2`**: smoothed closing over 1 s and incumbent wins ties. There is one `ClosingTracker` per observer. Set E, the L2 set and the `h`/`hb` arms used it.
  - **A name to watch:** in set E, `e-p2n*` and `el2-p2n*` ran **policy 3**. The `p2` in their names is a leftover; the laws in each run's `battle-viewers.json` are the record.
  - The earlier `heed` at `c18ca061` (module `e2-heed-cullet`) was built but never used for an arm.

**How the arms differ from the owner's ruling on forced individuals** (the coordinator, 2026-11-22: forced is whoever the viewer acts on and whoever made contact in the last few seconds; someone winding up at me or closing on me is ranked first, not forced):
- **Policies 0 and 1 force every engaged creature past capacity.** That is wider than the ruling.
- **Policy 2 forces nothing.** The engaged rank first within capacity, which is narrower than the ruling.
- **Policies 3 and 4 force `Acting` and `Contact` as `heed` does.** Contact comes only from the viewer's own last hurt, because blocks and dodges are not kept per viewer. So these are slightly narrower than the ruling.

**The fixture's limits:**
- nobody speaks, is cued, chosen, kin or fallen-and-watched, so those rules never fire;
- `threatening` is a move aimed at me;
- the own state is a rested, unhurt adult's.

**Not built:**
- capacity as a Rhai law (the ceiling is used directly);
- AI characters' attended sets;
- `human_attend`;
- the crowd's `moving` and `fallen` fields (written as zero).

### 1.4 SpacetimeDB documentation and what it implies

Read for this work (pages show docs version 2.0.0; the pinned server and crates are 2.14.1). Statements about 2.14.1 beyond them come from the versioned source and are marked.

- **[Row-level security](https://spacetimedb.com/docs/how-to/rls):** "an experimental, unstable feature … use Views instead". `seen_crowd` uses `client_visibility_filter` like the copy tables.
  - From the 2.14.1 source, not the docs: a publish that adds a rule disconnects every client (`ensure_disconnect_all_users`; docs/BATTLE_VIEWERS.md). The prototype runs only on fresh scratch worlds, so it paid none.
  - Shipping `seen_crowd` needs a merge window (answers Q6).
- **[Views](https://spacetimedb.com/docs/functions/views/):** "Per-user views require separate computation for each subscriber". That is why the crowd is a table. It is also why the views' 0.5 ms/s per viewer (§4) is a per-viewer constant.
- **[Event tables](https://spacetimedb.com/docs/tables/event-tables/):** rows are not cached by clients but are still logged. The crowd is state a client needs after reconnecting, so it stays a regular table.
- **[Table performance](https://spacetimedb.com/docs/tables/performance/) and [indexes](https://spacetimedb.com/docs/tables/indexes/):** `seen_crowd` has a `u64` primary key, (viewer << 32) | level << 30 | cell, plus a btree on `viewer`. A change is one update in place. Its size is bounded by 48 cells × viewers.
- **[Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/):** `gate_load` subscribes `seen_crowd` beside the copies. The 216-viewer crowd figures (§3.3) suggest each crowd write costs more as viewers grow. Why it does is not established here.

## 2. Cost against the ceiling

### 2.1 Sixteen viewers (clean)

Per viewer, reference subtracted. Delivery and churn are per viewer-second.

| Arm (runs) | Policy | Ceiling | Ticks/s | ms/s per viewer | µs a tick | Attended | In sight | kB/s | Rows/s | Promoted/s | Demoted/s |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `b-off` (2) | off | – | 58.3 | **11.08** | 190 | 128 | 128 | 82.8 | 840 | – | – |
| `db-p0n0nocrowd` (2) | 0, no crowd | 0 | 59.7 | **4.26** | 71 | 0.4 | 117 | 12.3 | 99 | 0.5 | 0.5 |
| `db-p2n0nocrowd` (2) | 2, no crowd | 0 | 59.7 | 4.89 | 82 | 0 | 124 | 12.7 | 101 | 0 | 0 |
| `db-p2n0` (2) | 2 | 0 | 59.7 | 4.97 | 83 | 0 | 115 | 13.5 | 119 | 0 | 0 |
| `e-p2n0` (2) | **3** (heed) | 0 | 59.8 | **5.00** | 84 | 0.3 | 110 | 13.5 | 120 | 0.3 | 0.1 |
| `b-p2n8` (2) | 2 | 8 | 59.4 | 6.46 | 109 | 7.9 | 122 | 23.0 | 214 | 8.7 | 7.9 |
| `b-p2n16` (2) | 2 | 16 | 59.0 | 7.11 | 120 | 15.1 | 111 | 29.9 | 287 | 18.5 | 16.0 |
| `b-p2n24` (2) | 2 | 24 | 59.2 | 7.87 | 133 | 22.9 | 120 | 39.0 | 380 | 27.8 | 24.6 |
| `b-p2n32` (2) | 2 | 32 | 59.2 | 7.69 | 130 | 28.1 | 113 | 44.1 | 430 | 33.5 | 28.6 |
| `db-p0n16` (2) | 0 | 16 | 59.4 | 6.46 | 109 | 15.6 | 124 | 27.7 | 264 | 10.4 | 7.8 |
| `hb-p3n16` (2) | 3 (heed, holds) | 16 | 59.5 | **7.05** | 119 | 15.6 | 124 | 25.0 | 238 | 6.7 | 0.6 |
| `e-p2n16` (2) | 3 (heed, holds) | 16 | 59.3 | 7.16 | 121 | 16.0 | 127 | 25.5 | 244 | 6.8 | 0.6 |
| `hb-p4n16` (1) | 4 (heed, no holds) | 16 | 59.4 | 7.32 | 123 | 15.5 | 124 | 29.6 | 280 | 16.2 | 13.8 |

Unless marked "no crowd", every arm writes crowd rows. "µs a tick" is ms/s per viewer over ticks/s.

**Reading:**
- **Marginal per attended individual** (policy 2, 8 runs at ceilings 8–32, regressed on the measured attended count): **67 ± 22 µs/s**. The line's intercept is 6.0 ms/s. Pairs of runs give 40–95 µs/s. Ceiling 32 attends 28 on average, and the 24 and 32 arms overlap within noise.
- **Average from none to 16:** 2.12–2.14 ms/s for about 15.5 attended. That is 136 (nearest-first), 132 (heed) and 142 (instinct) µs/s each. The first 8 cost about 190 µs/s each and the next ones about 60–70.
  - The first ones are the engaged and nearest, who fight and move most. Rows delivered per attended fall from about 14 a second for the first 8 to about 10–12 after.
  - The attended cost is therefore not one i. It depends on who is attended, and that follows the policy.
- **The policies at 16:**
  - nearest-first (0) costs about 0.6 ms/s less than the instinct (2) and the heed (3/4) at the same capacity: fewer promotions, no feature pass;
  - heed with holds equals the instinct in cost, with about a third of the promotions;
  - heed without holds costs about 0.27 ms/s more than with them, for about 9.5 more promotions and 13 more demotions a second. That is about **25–30 µs a promotion with its demotion** (an estimate from a single run).
- **The selection pass** over everyone in sight at 5 Hz, with nothing attended, costs about 0.6–0.7 ms/s per viewer over nearest-first (`db-p2n0nocrowd`, `e-p2n0` against `db-p0n0nocrowd`; the margin is near noise). The L2 spans put the feature and rule pass at 0.39 ms/s for about 119 in sight. That is about **3.2 µs/s per creature in sight, or 0.65 µs an evaluation** at 5 Hz. v2 assumed 3 µs/s.

### 2.2 216 viewers (saturated host)

**Saturated host.** At no ceiling does the database thread keep 60 ticks/s, so per-second costs are not comparable, and the cost per attended individual is **not** read from these arms. Shown are the ticks/s achieved and the per-viewer µs a tick ((ms a tick − 6.19) / 216).

| Arm (runs) | Policy | Ceiling | Ticks/s | ms a tick | µs a tick per viewer | Body p99 ms | Attended | In sight | kB/s per viewer | Promoted/s |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `a-off` (2) | off | – | 16.5 | 52.7 | 215 | 109 | 74 | 74 | 26.3 | – |
| `da-p0n0nocrowd` (2) | 0, no crowd | 0 | **36.2** | 19.4 | **61** | 33 | 0 | 71 | 5.1 | 0 |
| `da-p2n0nocrowd` (2) | 2, no crowd | 0 | 33.6 | 21.2 | 70 | 37 | 0 | 70 | 5.0 | 0 |
| `da-p2n0` (2) | 2 | 0 | 30.3 | 24.3 | 84 | 43 | 0 | 71 | 6.7 | 0 |
| `a-p2n8` (2) | 2 | 8 | 25.0 | 31.5 | 117 | 49 | 7.6 | 71 | 10.6 | 5.8 |
| `a-p2n16` (2) | 2 | 16 | 21.2 | 38.9 | 151 | 63 | 14.5 | 72 | 15.2 | 13.3 |
| `a-p2n16nocrowd` (2) | 2, no crowd | 16 | 22.4 | 36.4 | 140 | 57 | 14.3 | 71 | 13.7 | 13.3 |
| `a-p2n24` (2) | 2 | 24 | 20.1 | 41.3 | 163 | 80 | 19.8 | 69 | 17.7 | 17.8 |
| `a-p2n32` (2) | 2 | 32 | 17.2 | 49.9 | 202 | 89 | 24.9 | 74 | 21.1 | 22.6 |
| `a-p0n16` (2) | 0 | 16 | 27.2 | 27.7 | 99 | 39 | 14.4 | 71 | 11.4 | 5.9 |
| `h-p3n16vis` (2) | 3 (heed, holds) | 16 | 23.3 | 34.4 | 130 | 55 | 14.4 | 71 | 10.6 | 5.2 |
| `h-p4n16vis` (1) | 4 (heed, no holds) | 16 | 21.2 | 38.4 | 149 | 65 | 14.4 | 69 | 13.4 | 10.9 |

- **The per-viewer floor per tick matches at both sizes.** It is 61 µs a tick at 216 (`da-p0n0nocrowd`), against 71 at 16 viewers, so the floor scales about linearly with viewers. The budget is 17.7.
- **The order of the arms holds at 216:** nearest-first is cheapest, heed with holds comes next, and the instinct and heed without holds cost the most.

### 2.3 The ceiling the contract allows at 216

v2 §6's formula, `attend_ceiling ≈ floor((B − (C − c) × 3 µs − K × 5 µs) / (i + 10 µs))`, has no per-viewer constant. With the measured floor F (4.3–5.0 ms/s) added to the left side, it has no solution: F > B on either budget.

What would have to change, using the 16-viewer figures (marked **estimates**; attended cost A(c) as measured from none to c):

| Budget B (ms/s per viewer) | Floor F | Ceiling that fits with today's A(c) | A(16) needed for a ceiling of 16 |
|---|---|---|---|
| 1.06 (this host: 600 − 371 over 216) | 4.3–5.0 (today) | **none** | – |
| 1.06 | 0.5 | about 3 | ≤ 0.56 ms/s (about 35 µs/s each, a 3.8× cut) |
| 1.06 | 0 | about 5–6 | ≤ 1.06 ms/s (about 66 µs/s each, a 2× cut) |
| 1.5 (v2's, the Spark's core) | 0.5 | about 5–6 | ≤ 1.0 ms/s (about 63 µs/s each, a 2.1× cut) |
| 1.5 | 0 | about 8 | ≤ 1.5 ms/s (about 94 µs/s each, a 1.4× cut) |

**So the provisional ceiling of 16 is not justified by cost.** At 216 viewers and 60 Hz, cost allows a ceiling of about 5–8 only if the per-viewer floor is removed almost entirely. A ceiling of 16 needs both the floor near zero and the attended cost halved. §4 shows how much of the floor can plausibly go. The cost-only number matters less than the floor: a ceiling of 8 against 16 is a difference of about 0.6 ms/s, while the floor is 4.3–5.0.

## 3. The crowd rows

### 3.1 What is written

- **Cells:** 10–17 per viewer.
- **Writes:** 13–19 per viewer-second, at both 16 and 216 viewers. Writes exceed cells because moving cells change after quantizing. A still crowd writes nothing.
- **Delivery:** about 0.8–1.5 kB/s per viewer (the no-crowd arm against the crowd arm: `db-p2n0` and `db-p2n0nocrowd`, `a-p2n16` and its no-crowd arm).

### 3.2 Cost at 16 viewers

- The L2 crowd pass (`attend.crowd`) costs 0.04 ms/s per viewer, about 2.6 µs a write.
- The whole difference, crowd on against off, is about 0.08 ms/s per viewer, about 5 µs a write with its delivery. That is within noise, but it matches v2's assumed 5 µs a row.

### 3.3 Cost at 216 viewers (saturated, an estimate)

- **On against off:** 84 against 70 µs a tick per viewer at ceiling 0, and 151 against 140 at ceiling 16.
- **Per write** (crowd writes a tick across all viewers): about 15–23 µs a write, three to four times the 16-viewer figure.
- **A hypothesis, not tested:** each write is evaluated against every subscriber's `viewer = :sender` filter, so a write's cost grows with the viewer count. If that holds, it applies equally to every copy table and to "outside the tick" in §4.
- **The measurement that would settle it:** one crowd row written per tick at 16, 64 and 216 idle viewers, with no battle.

## 4. The floor: what a viewer costs with nobody attended

### 4.1 The parts (16 viewers, L1, two runs, ms/s per viewer, reference subtracted)

| Part | Off (128 in sight) | Floor: policy 0, ceiling 0, no crowd | Policy 2, ceiling 16 | Scales with |
|---|---:|---:|---:|---|
| Sweep (`tick.perception`) | 2.95 | **1.11** | 2.41 | viewers; plus in sight (sight, selection) and attended (projection) |
| Frames (`tick.frames`) | 2.75 | **0.62** | 0.95 | viewers (constant about 10 µs a tick each); plus about 15 µs/s per attended |
| Views (`view_total_time_usec`) | 0.64 | **0.49** | 0.50 | viewers (per-user views recomputed per subscriber) |
| Database thread outside the tick (subscription evaluation, commit, other reducers) | 0.93 | **0.48** | 0.71 | viewers; plus delivered rows |
| Fight folds (`tick.fold`) | 0.47 | 0.35 | 0.36 | characters: a viewer is one |
| Activity (`tick.activity`) | 0.66 | 0.41 | 0.44 | characters |
| Combat incl. the combat feed (`tick.combat`) | 0.80 | 0.41 | 0.64 | blows in sight; the feed is **not** trimmed by attention |
| Motion, cues | 0.39 | 0.14 | 0.31 | characters; cues per attended |
| Tick, unspanned remainder (includes the views above, evaluated at commit, and the commit itself; an estimate) | 2.14 | 0.74 | 1.28 | viewers; plus delivered rows |
| **Database thread, total** (the views are inside the remainder, not added again) | **11.08** | **4.26** | **7.11** | |

### 4.2 Inside the sweep (L2, one run each, ms/s per viewer)

These are profiling spans, so the absolute values are inflated. Use them for shares.

| Span | Off | Policy 0, ceiling 0, no crowd | Heed, ceiling 0 | Heed, 16 | Heed, 16, throng sight 1 Hz |
|---|---:|---:|---:|---:|---:|
| `sweep.one` (whole) | 3.10 | 1.18 | 1.64 | 2.37 | 2.67 |
| `sweep.hear` | 0.49 | **0.58** | 0.58 | 0.55 | 0.54 |
| `sight.player_candidates` | 0.26 | **0.24** | 0.25 | 0.25 | 0.39 |
| `sweep.project` | 1.41 | 0.09 | 0.09 | 0.34 | 0.35 |
| `attend.features` | – | – | 0.38 | 0.67 | 0.74 |
| `attend.rules` | – | – | 0.005 | 0.26 | 0.30 |
| `attend.crowd` | – | – | 0.04 | 0.04 | 0.04 |
| `tick.frames` | 2.82 | 0.73 | 0.74 | 1.13 | 1.08 |

- **In the floor's sweep:** hearing is about half, sight about a fifth, and the change test and vitals reads make up most of the rest. Projection is near zero with nobody attended.
- **Throng sight at 1 Hz** (`e-*throng`) cached throng members' sight for up to 1 s:
  - in sight rose (110 → 149), as departed creatures stayed cached;
  - crowd writes rose (15.6 → 19.4 a second);
  - cost rose: 5.00 → 5.52 at ceiling 0, and 7.16 → 7.29 at 16.
  - Sight is too small to be worth caching. v2's "crowd sight at 1 Hz" can be dropped.

### 4.3 What could reach the budget (estimates, none measured)

Against 1.06 ms/s per viewer:

| Part | Today | Possible change | Rough target |
|---|---:|---|---:|
| Hearing | 0.55 | Event-driven: hear when a sound is made, not each sweep; module memory for `heard` (docs/COMBAT_PHASE.md Part C saved 25–35 µs of a 340–380 µs sweep) | 0.1–0.2 |
| Frames' per-viewer constant | 0.62 | Skip viewers whose scene has no changed creature this tick (the frames' changed-set already exists per scene) | 0.1 |
| Views | 0.49 | Move the remaining per-user views to keyed tables, or recompute only on the owner's own rows | 0.1–0.2 |
| Outside the tick | 0.48 | Fewer subscribed tables per viewer (one merged copy table), if per-subscriber evaluation is the cost (§3.3) | 0.2–0.3 |
| Sweep's change test and vitals | about 0.26 | Module memory (Part C) | 0.1 |
| Sight | 0.24 | Keep | 0.24 |
| Combat feed | about 0.2–0.4 | Trim to the attended (also a leak, §7) | 0.05–0.1 |
| Fold, activity, motion | 0.85 | Not delivery: a viewer's cost as a character. It belongs to the character budget (the contract's 2,000 characters), not the viewer's | – |
| **Delivery floor** | **about 3.4** | | **about 0.9–1.3** |

- **Even with all of these, the floor stays near the whole 1.06 budget.** A ceiling of 8–16 then needs the per-attended cost cut about 2–4× (§2.3); that is v2's "planned per-individual work".
- **On this host, 216 viewers at 60 Hz therefore needs one of three things:**
  - the faster core v2 assumed;
  - moving per-viewer work off the database thread (delivery outside the tick);
  - a lower rate for everything the floor holds that does not have to run at 60 Hz: hearing, views, and the frames of unchanged scenes.

## 5. Churn and visible flicker

### 5.1 Measures

- **Promotions and demotions:** per viewer-second (§2).
- **Visible churn** (`attend_vis_on`): per viewer, a creature in sight that goes from individual to crowd and back, or the other way, within 2 s and within 5 s. That is a figure a viewer would see flip.
  - Counted at every sweep (5 Hz) and logged per 10 s bucket per viewer.
  - Reported per viewer-minute, with the share of attended creatures affected and the worst viewer.
  - Unit test: `flip_backs_are_counted_within_2_and_5_seconds`.

### 5.2 Results (ceiling 16, 216 viewers unless marked)

| Arm | Selector | Flip-backs ≤ 2 s per viewer-minute | ≤ 5 s | Share of attended affected | Worst viewer ≤ 2 s (≤ 5 s) | Promoted/s |
|---|---|---:|---:|---:|---:|---:|
| `vis-c-p2g0` | my instinct (2), no grace | 612 | 660 | 59% | 1,745 (1,830) | 13.4 |
| `vis-c-p2g1000` | my instinct, 1 s grace | 115 | 166 | 25% | 227 (448) | 9.5 |
| `vis-c-p1g0` | redraw each second (1), no grace | 455 | 512 | 44% | 835 (899) | 15.3 |
| `vis-c-p1g1000` | redraw each second, 1 s grace | 99 | 186 | 19% | 262 (506) | 13.1 |
| `vis-c-p0g1000` | nearest-first (0), 1 s grace | 20 | 30 | 10% | 49 (113) | 5.2 |
| `vis-c-burst` | instinct, 16 → 6 at 30 s | 355 | 389 | 60% | 1,006 (1,058) | 8.2 |
| `vis-c-burstg1000` | instinct, burst, 1 s grace | 83 | 125 | 29% | 295 (413) | 6.1 |
| **`h-p3n16vis`** (2 runs) | **heed with holds** (`aa3d4d9e2`) | **7.9 / 7.3** | **20 / 18** | **6%** | 29–30 (92–108) | 5.2 |
| `h-p4n16vis` | heed without holds | 378 | 427 | 47% | 1,232 (1,355) | 10.9 |
| `h-burst` (2 runs) | heed with holds, 16 → 6 | 12.4 / 12.7 | 24 / 25 | 12% | 14–18 (90–92) | 3.4 |
| `hb-p3n16vis` (16 viewers) | heed with holds | 8.5 | 32 | 7% | 17 (50) | 7.1 |

The `vis-c-*` arms ran once each, on the visibility build.

### 5.3 The Spark's replay beside these

From `docs/ATTENTION_E3.md` on `attention-exp` (`67a68abd7`), on Cullet recordings with a fake model at 0.5 s steps. Its "flicker" is a stint shorter than 3 s between individual and throng, per subject-minute, so it is a lower bound and not the same unit as above.

| Spark arm (battle) | Flicker /min | Figures flickering | Live arm here | ≤ 2 s / ≤ 5 s per viewer-minute | Share |
|---|---:|---:|---|---:|---:|
| smoothed closing, holds on | 3.4 | 5.5% | heed with holds | 7.6 / 19 | 6% |
| smoothed closing, holds off | 169 | 75% | heed without holds | 378 / 427 | 47% |
| two-pass closing (E2's), holds off | 222 | 80% | my instinct, no grace | 612 / 660 | 59% |

### 5.4 Reading

- **The two measures agree on the order and the size of the effect.** Holds cut flips by about 98% here, as in the replay. The live counts are about 2.2× the replay's in both arms. The measures differ: the live runs sample at 5 Hz with 2 s and 5 s windows, against the replay's 0.5 s steps and 3 s stints, and the live battle has 216 observers in place of recorded subjects.
- **Grace hides the flips the policy makes, but does not stop it making them.** A 1 s grace cuts my instinct's flips by 80%, but leaves 115 a minute and 25% of attended creatures affected. It also delivers a dropped creature for 1 s more, which is perception the character no longer has (answers Q3). Holds are the right damper; grace is not needed with them.
- **Does my instinct need hysteresis? Yes.** Its ranking is redrawn on unsmoothed features every sweep, and it is the worst arm. The heed selector with its holds and smoothed closing is that hysteresis, at the same cost (§2.1).
- **The burst with holds** leaves 12–13 flips a minute, about 1.6× steady holds. A demotion on the drop counts only if the creature comes back within the window.

## 6. The burst: capacity 16 → 6 mid-fight (Q11)

`--flip-law attend_burst_cap=6 --flip-at 30` sets capacity 6 at 30 s, in the middle of the window. Tick bodies are shown 1 s before and 1 s after.

| Arm | Viewers | Worst tick before → after (ms) | Missed slots before → after | Tick body sum (ms) before → after |
|---|---:|---|---|---|
| `db-burst` r1 / r2 (instinct) | 16 | 15.1 → 13.4 / 16.1 → 11.0 | 2 → 0 / 1 → 0 | 463 → 430 / 435 → 413 |
| `hb-burst` r1 / r2 (heed) | 16 | 12.0 → 12.4 / 11.5 → 11.3 | 0 → 0 / 0 → 0 | 442 → 393 / 439 → 410 |
| `c-burst` r1 / r2 (instinct, saturated) | 216 | 53 → 61 / 60 → 60 | 44 → 39 / 45 → 38 | 734 → 668 / 736 → 656 |
| `h-burst` r1 / r2 (heed, saturated) | 216 | 52 → 51 / 69 → 62 | 45 → 40 / 45 → 41 | 785 → 702 / 745 → 728 |

**A capacity drop is a batch of demotions, and nothing in the frame budget breaks.**
- The worst tick after the drop is within the run's ordinary spread.
- The second after spends less in the tick, because fewer creatures are attended.
- Missed slots do not rise.
- From the code: the frames' row budget (`FRAME_ROWS_PER_TICK`, its floor and back-off) is per tick across viewers and does not assume scenes change only with sight.

## 7. Off-identity, memory and side findings

- **Off is off.** `det_compare.py` ran 1,800 ticks, 16 viewers on a 10 m ring and 200 fighters, comparing every tick and every table (113 tables, 47,627 rows) on the dedicated server `e2-deta`:
  - main `a6375a70e` (`main-cullet`) against `e2-cullet` (laws off): **identical**;
  - main against `e2-heeds-cullet` (laws off): **identical**;
  - the negative control, `e2-cullet` with `attend_on=true`, differs from tick 2.
- **WASM memory:** 185.5–185.6 MB in every arm, flat over the window.
- **The combat feed is not trimmed by attention:** 128,711 rows in one 16-viewer run. It names actors and targets the viewer does not attend. That is a leak in the design's terms, and part of the floor (answers, summary item 3).
- **Queue wait** for player reducers: 0.05–0.10 ms at 16 viewers, and 0.3–1.8 ms at 216 (saturated).

## 8. What was not measured

- **RSS per world.** Only the service's RSS after each run was recorded. VmHWM is cumulative across runs on one server, so no per-world footprint is claimed.
- **Blows, blocks and misses are counted together** in "blows a second". The fixture check needed only that the battle was live.
- **The L2 figures are single runs,** and so are `hb-p4n16`, `h-p4n16vis`, `hb-p3n16vis` and the `vis-c-*` arms.
- **AI characters' attention** was not built, so v2 §6's "200 fighters × 200 in sight × 1 µs ≈ 40 ms/s" and the fold's saving are not measured (E4).
- **A capacity law in Rhai, `human_attend`, pins and the client's crowd drawing** were not built.
- **The crowd's `moving` and `fallen` fields** were written as zero. Computing them adds per-member reads to the crowd's cost.
- **My instinct (policy 2) uses unsmoothed closing.** Its churn is an upper bound for a design that smooths. The heed arms are the representative ones.
- **The 216-viewer per-write crowd cost** (§3.3) comes from a saturated host. The cause is a hypothesis.
- **The runner services' noise** (§1.2) affected the runs from `a-off-r2` on. The 16-viewer spread (±0.5 ms/s per viewer) includes it.
- **The `abc` series ran with uncommitted changes in the worktree** (the series log shows `dirty=4`). Its module `e2-cullet` (`d50674e0377e`) was built from `b226aa8e0` before those edits, so the module is exact. The `d` and `e` series logged `dirty=0`.
- **No 60 Hz run at 216 viewers exists,** so the latency from a windup to the attacker's first copy row at 216 was not measured.

## Evidence

- **Code:** branch `attention-e2`:
  - `b226aa8e0`: the prototype and policies 0–2;
  - `5a81911a8`: visible churn, throng sight and the selector, measuring only;
  - `aeee62046`: `heed` at `attention-exp` `aa3d4d9e2`;
  - the commit that adds this note.
- **Tools on the same branch:**
  - `living/tools/e2_report.py` (per-run figures; known-answer self-test, 22/22);
  - `battle_viewers.py`'s `--crowd`, `--flip-law` and `--flip-at`;
  - `gate_load`'s `seen_crowd` subscription.
- **Runs:** on the dev-box, worktree `t3-b749c655` at `.local/e2/`:
  - `runs/<arm>-r<n>/`: `battle-viewers.json`, `v<n>/metrics.json`, the full logs, `procs-*.txt` and `rss.json`;
  - `runs/series.log`, holding each set's module hash, commit and dirty count;
  - the scripts `series.sh`, `vis.sh`, `d.sh`, `e.sh`, `chain.sh` and `det*.sh`;
  - `tables.py`, which writes `tables.json` (every figure above);
  - `el2-*-spans.json`;
  - `det-off`, `det-off-final`, `det-off-heeds` and `det-negative`;
  - the modules in `wasm/`.
- **Archived** on the dev-box at `~/archive/worktree-evidence-20261122/attention-e2.tar.zst` (sha256 `889fe4fe68010521…`, 629 MB; build targets excluded).
- **The scratch server's volume** `e2-stdb-data` was kept until this note was written.
- **Related:**
  - docs/COMBAT_PHASE.md (Budget; Part C);
  - [PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md);
  - `docs/ATTENTION_E3.md` on `attention-exp` (`67a68abd7`);
  - dev-box's answers on `attention-budget-devbox`.
