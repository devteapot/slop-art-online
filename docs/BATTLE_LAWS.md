# Battle laws: the owner's options for a battle watched by many players

Status: prototypes, measured once each, 2026-11-20. Branch `battle-laws` (dev-box), from `origin/main` `3c64dcac6`. Every option below is a law, **off in play**; nothing here changes the game until the owner chooses. The Spark adds its parts (§4: the tick body and module memory across transactions). The GC takes the whole document to the owner.

**Why this document.** The performance contract asks for 200 fighters at 60 Hz with players watching (docs/PERFORMANCE_CONTRACT.md; the immediate gate is 216 characters for 30 minutes). After the views track and the exact sweep work, a player watching a dense battle still costs about 85–105 µs a second for each creature it sees. The contract's budget is about 7–10 µs. That breakdown is in docs/BATTLE_VIEWERS.md, the addendum of views step 3, and in docs/COMBAT_PHASE.md. The rest of the gap is each player's own rows: its sweeps, its frames' writes, and each transaction's commit and subscription work. Exact work cannot remove those; only fewer pairs (fewer creatures each player is told about) or fewer refreshes can. Each of those changes what a player perceives, or when, so each is the owner's call.

## 1. How the options were measured

**Fixture.**
- Battle: `spawn_battle`'s fighters attack the nearest person, residents included (the laptop's stills lost 36 residents in one run). For stills and any run where bystanders should live, `battle_viewers.py --sides N` uses the new fixture reducer `spawn_battle_sides(n, sides)`: the fighters are in N sides (communities `Side A`, `Side B`, …, names `A12`, `B7`) with an "enemy" stance record each way between sides, and target the nearest person of an enemy side.
  - Proved on a Cullet world, 200 fighters in 2 sides for 60 s: 671 skill uses, none at a resident or at the fighter's own side, and none of the 64 residents died.
  - The side is the fighter's membership, so a client can tint by side.
  - The measurements below used `spawn_battle` (bystanders could be attacked).
- Host and server: dev-box, its own server `sg-stdb` (SpacetimeDB 2.14.1), one core type, no pinning.
- Module: Cullet, built from this branch (`bl-cullet`).
- `living/tools/battle_viewers.py`: 200 AI fighters, the viewers placed while paused with the battle spawned after placing, and a keep-alive every 0.5 s so no viewer dies.
- The viewers: `gate-load` players on the tiers, the cues and both copy tables (the defaults since bv-defaults-on), walking small circles.
- Two densities:
  - **16 viewers on the 10 m ring**: about 90 creatures in each one's sight, so about 1,440 viewer–creature pairs;
  - **216 viewers on the 26–32 m ring**: about 59 each, about 12,700 pairs.
- 20 s warm-up, 60 s window, server metrics only (L0, no spans).
- The 1-minute load was below 4 at every start. No viewer died in any window.

**Sight is play's.** The fixture's module has the Cullet seed compiled in, and Cullet's own laws turn on everything play uses (`living/seeds/worlds/cullet/laws.rhai`): facing sight (`fov_on`), cover (`cover_sight_on`) and gaze (`gaze_on`). A viewer that sends no gaze is at Middle (no `applied_gaze` row), as `gate-load`'s viewers are. So the counts below are play's sight.

They differ from a still by placement:
- **The 16 viewers on the 10 m ring** stand inside the battle's edge on open ground, with fighters all round. About 90 creatures are in sight each.
- **The 216 viewers on the 26–32 m ring** see about 59 each.
- **The laptop's stills** (`battle-stills` `718ebcf4b`): a still player at the battle's edge, facing it, perceived about 50 of 200 with the cap off. A terrace wall and its facing cut the rest.

So the 216 ring is the "player at the edge" case, and the 10 m ring a player in the battle. Per-pair figures below are over each ring's own pairs.

**One run per arm.** Two base runs of the same fixture varied by ±15–20 ms/s at 16 viewers, so a difference smaller than that is not a result. The repeats (two more runs per arm, at both densities, interleaved) are for Sol after the 25th.

**Per pair** is the change in the database thread's CPU over the base's pairs. At 216 the database thread is saturated (about 790 ms of 1,000 a second), so the tick rate is the clearer result there: it goes up as the thread frees.

**Freshness** is `gate-load`'s sample (every third viewer) of how late a creature's new motion segment reached the client (ms, p50 / p90 / p95, all creatures in sight). It shows what a law does to what a player sees in time.

## 2. The options

### (a) A bounded far tier: at most N creatures seen at once (`far_cap`)

**What it does.** A player's sweep keeps at most N of the creatures in sight: first whoever is engaged with it (fighting it, aimed at it), then the nearest. The rest are neither seen nor heard by that player until they come within the N nearest. Prototype value: N = 40. The cap is exact: a player never perceives more than N (the laptop's stills: 40 of about 50 at cap 40, 25 at cap 25).

**What it counts: every creature in sight,** fighters and bystanders alike (residents, animals). That is the decision here, not "fighters first":
- the cost follows every perceived pair, whoever they are;
- a crowd of onlookers costs what a crowd of fighters does;
- fighters first would need a ranking rule (who is a fighter now) in the sweep.

The laptop saw what it means: at its spot, cap 40 gave 39 fighters (one resident in sight took a place), and cap 25 gave 24. If the owner wants fighters ranked first after the nearest engaged ones, that is a small change to the sweep's order, not to the cap.

**What changes for a player.** In a crowd larger than N, the farther ones are not drawn at all. A player in a 200-fighter battle sees the 40 nearest (and anyone attacking it), and the far edge of the battle is empty ground. Its own fight, and those near it, are unchanged and fresher than before (below). The AI is untouched: a mind's scene, its sight and its memories are unchanged. That asymmetry is a rules question: the same rules for players and AI. The aggregated alternative below would keep a far crowd visible.

**Stills: the spec for the laptop** (verify-ui and the Bevy client; the GC's brief, 2026-11-20). They let the owner judge (a) by eye. One shot per cell of this grid:

| | `far_cap` off | `far_cap` 40 | `far_cap` 30 | `far_cap` 20 | aggregated crowd (mock, if cheap) |
|---|---|---|---|---|---|
| Middle band | 1 | 2 | 3 | 4 | 5 |
| Far band | 6 | 7 | 8 | 9 | 10 |

- **World:** Cullet (`LIVING_SEED=cullet`), a fresh world from the build under test (all battle laws off but `far_cap`), by day (the world's own day: the shots between 10:00 and 15:00 world time).
- **Staging:** `living/tools/battle_viewers.py --viewers 1 --fighters 200 --ring 26,26 --paused-placement --battle-after-placing --keep-alive 0.5 --law far_cap=N` (the law left out for "off"), with `--seconds 600` so the world stays up. The one viewer is the game client's own player, joined with its own identity in place of `gate-load`'s: join it, then `place_at` it at the battle's centre plus 26 m due south of it (centre: the arrival less 20 m, as `spawn_battle` takes it), facing north.
- **Camera:** north-up (the default bearing), the play camera's own Middle and Far zoom bands (docs/CAMERA.md), no free camera. The fight in frame: the battle's centre on the screen's vertical middle.
- **Timing:** 20 s after `spawn_battle` (the fight under way; about 180 fighters alive), the world paused for the shot (`set_paused true`), so the five arms show the same moment of their own run.
- **Output:** 1920×1080 PNG, UI hidden but the nameplates, named `battle-laws-<band>-cap<N|off|crowd>.png`, beside a JSON per shot with the world time, the fighters alive, the creatures the viewer sees (`seen_bodies` count) and the law's value.
- **The aggregated crowd (5, 10), only if cheap:** the cap-30 view plus, for the capped creatures, one translucent disc per 4 m cell where they stand, its size by their count (a client-side mock from an owner SQL read of `body` positions; no table yet).
- **What the owner should be able to see:** at Middle, whether the nearer fighters are all there and the far edge's absence is noticeable; at Far, how much of the battle is gone at 40, 30 and 20, and whether the crowd discs read as "a big fight over there".

**Measured.**

| | 16 viewers, 10 m ring | 216 viewers, 26–32 m ring |
|---|---|---|
| Database thread, ms/s (base → law) | 465 → 442 (−23) | 789 → 722 (−67) |
| Per pair (µs/s, over the base's pairs) | about −16 | about −5 (at 23–28 ticks/s) |
| Ticks/s | 58.9 → 58.9 | 23.2 → 28.4 (+22%) |
| Freshness p50/p90/p95 (ms) | 35/100/149 → 25/44/52 | 72/440/801 → 53/110/351 |

**Live-tunable.** Every prototype law is value-only (`law_override`, docs/LAW_OVERRIDE.md), like the delivery laws: `set_world_law far_cap 30` takes effect at the next tick with no install (the stills' first runs took a full install, about 5 s, each). Tested in `law_override_check::the_battle_laws_are_value_only`.

**Risk.**
- The far edge of a battle disappears for players. A player can no longer judge a big fight's size from afar, and a newcomer walking in sees the crowd fill in as it nears.
- A creature dropped by the cap is also unheard by the player.
- The cap applies per sweep, so a creature at the edge can blink in and out as the order changes. A margin (keep a capped one for a second) would damp it.
- Players and AI perceive differently.

**Its better form: aggregated far crowds (not built).** The capped creatures could be sent as a few crowd rows per player: one per cell of the far crowd, with a count and the cell's centre and spread. The client would draw them as an impostor crowd. A player would still see that a big fight is there and roughly where, without its individuals. The cost per player becomes about N + cells instead of every creature. This needs a new table with row-level security (as the copy tables), a crowd renderer in the client (the laptop's), and the stills to judge the look. Expected: close to (a)'s gain, with the far battle still visible.

### (b) A density-following sweep and frame cadence (`crowd_sweep_n`, `crowd_frame_max_ms`)

**What it does.**
- A player's sweep (what it sees and hears) normally comes every 200 ms. Above n creatures in sight it comes less often, in proportion to the count, up to 3× (600 ms).
- Its far frames' longest interval (normally 100 ms) is raised in a crowd.
- Prototype values: n = 30, 250 ms.

**What changes for a player.** In a crowd, a creature that comes into sight appears up to 0.4 s later, and one leaving lingers as long. Its health band and name follow at that pace. Far creatures' motion still extrapolates on the client between updates, but a far creature's new path reaches the client up to 150 ms later. Near creatures and the player's own fight are unchanged: cues carry them at once.

**Measured.**

| | 16 viewers, 10 m ring | 216 viewers, 26–32 m ring |
|---|---|---|
| Database thread, ms/s | 465 → 455 (−10, within noise) | 789 → 744 (−45) |
| Per pair (µs/s) | about −7 (not a result at one run) | about −3.5 |
| Ticks/s | 58.9 → 58.8 | 23.2 → 27.8 (+20%) |
| Freshness p50/p90/p95 (ms) | 35/100/149 → 33/82/117 | 72/440/801 → 61/431/840 |

**Risk.** Perception in a crowd is later. That is felt as slower reactions to far events, and as creatures popping in late at the edge of sight. Freshness of far motion is about unchanged at these values, because the frames' row budget, not their interval, bounds it at 216.

### (c) Fighters on the combat cadence skip bystander wakes (`fighter_bystander_wakes` off)

**What it does.** A fighter already evaluated about 15 times a second (the combat cadence) is not woken again by what it sees as a bystander. Its next cadence evaluation, within 4 ticks (about 67 ms), sees it.

**What changes for a player.** Nothing directly. AI fighters react to things around them (not aimed at them) up to about 67 ms later.

**Measured.** No change measurable at one run: 465 → 481 ms/s at 16 viewers and 789 → 808 at 216, both within the runs' spread. Ticks/s at 216: 23.2 → 23.1. The Spark's diagnosis estimated about −23 ms/s at a sustained 200 fighters (`wake.eval.fight`). This fixture's fight thins over the window, and its bystander wakes are few. The repeat runs, with the Spark's spans, will tell. Measured by the Spark at a sustained 200: §4.1, −11 ms/s at 0 viewers.

**Risk.** Low. AI fighters' reactions to bystander events are a little later.

### (d) The combat cadence itself (the Spark's)

The Spark's part (docs/COMBAT_PHASE.md): the 15 Hz cadence at 10 Hz is about −45 ms/s and changes fighters' reaction timing. To be added by the Spark with its measurement. Measured: §4.2, `combat_eval_hz`.

### (e) Other candidates

**(e1) A tolerance on far motion copies (`far_motion_tol_m`).**
- What it does: a far creature's motion copy is rewritten only when the client's extrapolation of the old copy would be more than the tolerance off, at now, in 250 and 500 ms, and at the segment's end (2 s at most). Prototype value: 0.5 m.
- What changes for a player: a far creature's drawn path may be up to 0.5 m off its true path.
- Measured, a loss: 465 → 477 ms/s at 16 viewers (noise), 789 → 827 at 216, with ticks/s falling 23.2 → 19.8.
- Why: in this battle, far creatures' segments change because they really change course, so few writes are kept. The four extrapolations per check cost more than the writes saved. Freshness worsened at p50 (72 → 89 ms).
- **Not recommended**, unless a fixture with long straight walks (a crowd crossing a square) shows otherwise.

**(e2) The per-transaction remainder.** Each tick's commit, read sets and subscription evaluation are about 21 µs/s a pair at 16 viewers. That is SpacetimeDB's own work per transaction. It scales with the rows a tick writes and the subscriptions they touch, so it falls with (a) and (b). A host-side profile of the database thread (`perf`, our own container) would split it. No law of ours changes it directly.

## 3. What the views track and the exact work already did

From docs/BATTLE_VIEWERS.md (addenda 3–5) and docs/COMBAT_PHASE.md, per pair at 16 viewers on the 10 m ring:

| After | µs/s a pair |
|---|---:|
| The diagnosis (before step 1) | about 130 |
| Steps 1 and 2 (copy tables, `combat_feed`) | about 105 |
| Step 3 (fighter copies) and the exact items | about 88–92 expected (step 3 measured −12) |

## 4. The tick body and module memory across transactions (the Spark's part)

Measured on the Spark (docs/COMBAT_PHASE.md, "battle-laws", is the detailed source: every run, its load and placement). The fixture differs from §1's in four ways. First, the Spark's own server is pinned to its fast cores (X925; unpinned Spark ticks swing 40–50%). Second, L1: profiling on, so the tick's phases and the creatures in sight are counted, which costs a few percent. Third, two runs per arm, interleaved. Fourth, for (c) and (d), **a sustained battle**: `battle_viewers.py --keep-fighters 1` counts the fighters alive every second and replaces the dead one for one with `spawn_battle`, the same profile within the site's 7 m. That is about 2.0–2.6 refills a second, and 191–200 fighters alive at every count (§1's battle thins from about 180 to about 90 engaged over its window). This is a respawn the game does not have, as `battle_diag.py`'s refills are; it keeps deaths and their witnessed events, which reduced damage would not. The rings are §1's: 16 viewers on the 10 m ring, 216 on the 26–32 m ring, copy tables on. Per pair is as in §1, against the same law state's 0-viewer arm. At 216 it is per pair per tick, since the thread is saturated. Compare per-pair figures within one host only: the Spark's L1 runs and §1's dev-box L0 runs measure the same thing at different scales.

**Where the tick body stands.** After the exact AI trims (docs/COMBAT_PHASE.md, step 3: −9..−13% of the AI-only tick, an evaluation 69.5 → 61 µs, exact by tick-by-tick comparison), a sustained 200-fighter battle with no viewer costs **321 ms/s** of the database thread's 1,000 (L1, two runs, 321.0 both). The parts:
- the fighters' 15 Hz cadence evaluations, 161 ms/s (about 3,100 a second at about 52 µs);
- wakes, 49 ms/s (about 340 woken evaluations of fighters a second, most of them as a party: the target of a windup);
- the rest (blows, deaths, folded onlooker lines, residents' slots, motion) about 110 ms/s.

So at 60 Hz the battle alone leaves about 280–380 ms/s for every viewer cost, before the headroom for spikes. The options below take from the battle's share; none of them changes a viewer's own cost (per pair), which is what §2's (a) and (b) do.

### 4.1 (c) at a sustained 200: fighters' bystander wakes (`fighter_bystander_wakes`, on as shipped)

**What it does.** Off, a creature on the combat cadence is not woken as a bystander, neither at once nor when a held-back wake (`witness_wake_ms`) falls due. Its next cadence evaluation sees what happened. That evaluation comes within 4 ticks at 15 Hz; the law only applies while the fight's cadence is sure to reach it (`mind_state.fast_until` at least one cadence ahead). A party (the one a blow is aimed at, the one striking) is woken at once either way, and the percept is written at once in full either way. The Spark's build is the rule of this branch's prototype under the same name, plus the held-back wakes and the cadence guarantee (branch `battle-laws`, Spark). One of the two goes in at merge.

**What changes for a player.** Nothing a player does. AI bystanders in a fight turn to what others do near them (an ally struck, a death seen) at their next beat, up to about 67 ms later. A player's own character in a fight runs only its command or waiting graph on the cadence, and its skills start when the player asks.

**Measured** (sustained 200):

| | 0 viewers | 16 viewers, 10 m ring | 216 viewers, 26–32 m ring |
|---|---|---|---|
| Database thread, ms/s (on → off) | 338 → 326 (**−11**) | 544 → 547 (within the spread) | 859 → 887 (within the spread) |
| Tick WASM, ms/s | 321 → 310 (−3.5%) | 410 → 409 | 580 → 598 |
| Per pair | – | 101 (89–112) → 118 (114–122) µs/s, within the spread | 3.25 → 3.24 µs per pair-tick |
| Ticks/s | 60 → 60 | 57.6 → 57.8 | 15.1 → 15.2 |
| Bystander wakes left to the cadence | 283–309 a second | 553–644 | 630–697 |

**Correcting the diagnosis.** The diagnosis's −23 ms/s counted every woken evaluation of a fighter (`wake.eval.fight`), and most of those are wakes as a party, which this law keeps. At a sustained 200 the gain is −11 ms/s: `tick.wakes` −5.8 ms/s, and the fighters' woken evaluations 341 → 310 a second.

**Behaviour** (three matched battles, stepped deterministically, AI only). Reaction to an attack aimed at a fighter is unchanged: p50 17 ms; 64.0% of attacks are met by a block or dodge before they resolve, against 63.6%. Blows landed, blocked and dodged, hits taken, deaths and engagement length are within the spread between battles.

**Exactness.** On as shipped is identical to main tick by tick (`det_compare`, with 16 players and without). Off changes AI timing by design.

**Risk.** Low: one value, live-tunable (value-only). In this fight graph its effect could not be seen; a graph that reacts to others' acts would react later.

### 4.2 (d) at a sustained 200: the combat cadence (`combat_eval_hz`, 15 as shipped)

**What it does.** Creatures in a fight are evaluated every `round(60 / combat_eval_hz)` ticks, staggered by id: 15 Hz is every 4th tick (as today), 10 Hz every 6th, 7.5 Hz every 8th. Wakes are untouched, so a threat still wakes its target at once.

**What changes for a player and for fighters.** A fighter's reaction to an attack aimed at it does not change: the attack's windup wakes its target, which decides in the next tick (p50 17 ms at every value). What slows is everything a fighter does between threats: choosing and closing on a target, turning to face it, the next attack once recovered. A player fighting AI meets opponents that re-plan every 100 ms (10 Hz) or 133 ms (7.5 Hz) instead of every 67. A player's own command graph in a fight (approach and strike) re-plans at the same pace. A player's skills are not affected.

**Measured** (sustained 200; 10 Hz / 7.5 Hz against 15):

| | 0 viewers | 16 viewers, 10 m ring | 216 viewers, 26–32 m ring |
|---|---|---|---|
| Database thread, ms/s | 338 → 283 / 272 (**−55 / −66**) | 544 → 526 / 483 (−18 / −60) | 859 → 877 / 879 (saturated) |
| Tick WASM, ms/s | 321 → 266 / 256 (**−17% / −20%**) | 410 → 378 / 340 | 580 → 590 / 588 |
| Cadence evaluations' cost (`tick.combat`), ms/s | 161 → 119 / 100 | 162 → 123 / 97 | 56 → 49 / 39 |
| Per pair | – | 101 → 118 / 108 µs/s (within the spread) | 3.25 → 3.17 / 3.01 µs per pair-tick |
| Ticks/s | 60 | 57.6 → 58.4 / 58.6 | 15.1 → 16.1 / 16.2 (+7%) |

**Behaviour** (three matched battles, AI only; 15 → 10 / 7.5 Hz):
- attacks met by a block or dodge: 63.6% → 64.0 / 63.3%;
- blows that miss: 4.8% → 5.7 / 5.1%;
- blocked: 32.0% → 31.2 / 30.6%;
- the slow tail between a fighter's moves, p90 from a move's end to its next decision: 1,300–1,450 ms → 1,350–1,433 / 1,517–1,566 (7.5 Hz about +11%);
- deaths, hits taken and engagement length: within the spread between battles.

**Exactness.** 15 is identical to main tick by tick. Other values change AI timing by design.

**Risk.** Low to implement (one value, value-only). It is the largest AI-side lever measured, but it makes AI fighters a little slower to follow a fight, which a player who fights them might feel. The diagnosis's advice stands: use it only if the budget still fails after the rest. If so, 10 Hz costs the least behaviour for about −55 ms/s at a sustained 200.

### 4.3 (f) Module memory across transactions: each viewer's heard rows and the health readings kept between ticks (`sweep_keep_memory`, a diagnostic, off)

**What it does.** A player's sweep keeps its `heard` rows (what it hears and does not see) and the creatures' `vitals` rows in the module's memory from one tick to the next, instead of reading them each sweep. This is `KEPT`'s pattern: memory that only stands in for a read. It is cleared whenever this instance skipped or repeated a tick (another instance ran one, or one rolled back), dropped for a player outside the tick (a join, a death), and read afresh every 150 sweeps (heard) or 60 ticks (health). A blow, a heal or a band change (`health_moved`) drops a creature's kept health. `sweep_keep_check` compares each kept value with the table.

**Why it is not exact.** SpacetimeDB does not keep module memory across reducer calls: "Relying on global variables, static variables, or module-level state to persist across reducer calls is undefined behavior", and a rolled-back transaction's changes to it "may remain" (docs: reducers, 2.0.0; the server is 2.14.1). The heard keep is exact in practice, because only the sweep and a death write those rows. The health keep is not: most writes to `vitals` (needs settled at each evaluation, breath, eating) do not mark it.

**What changes for a player.** Nothing measured. A revealed exact health (one's own is written at once anyway) could lag by up to a second between blows.

**Measured** (the thinning fixture of COMBAT_PHASE.md; L2 for the sweep's parts, L1 for the totals; two runs each):

| | 16 viewers, 10 m ring | 216 viewers, 26–32 m ring | 216 viewers, 10 m ring |
|---|---|---|---|
| A sweep, µs (off → on) | 339–378 → 346–353; its heard read 17 → 1, its health test 63–73 → 54 | 239–247 → 226–232; heard read 7 → 0.6, health test 26–28 → 22–24 | 654–666 → 680–701 (nothing measurable) |
| Database thread | about −2..−3 ms/s | about −6..−22 ms/s | – |
| Per pair | about −1.5..−2 of about 130 µs/s | about −1..−3% per pair-tick | – |
| Kept against the table (`sweep_keep_check`, one run each) | heard: 0 of 6,862 lists differed; health: raw value 13% of 348,503, band 0 | – | heard: 0 of 24,451; health: raw 14% of 43,652, band 0 |

**Risk.** Medium for little: memory that a missed mark makes stale, against a few percent of a sweep. The heard half could be made a permanent exact path at low risk (its only writers are known). The health half needs a mark at every `vitals` write before it could be.

**Recommendation.** Not for play as it stands. What remains of a viewer's cost is row writes, views and each transaction's commit, which this does not touch.

### 4.4 Other items in the tick body (exact; docs/COMBAT_PHASE.md "Next", rows 3, 4, 5, 10)

| Item | Expected gain | Exactness | Risk |
|---|---|---|---|
| The viewer's own `perceived` rows kept as heard rows are (each sweep reads all of them) | about −10..−16 ms/s at 216 on the 10 m ring, −1.5 at 16 (estimated) | exact while every writer marks it | medium: joins, deaths and `sweep_now` write them too |
| Frames take the sweep's band and health instead of reading them again (dev-box's `frame.rs`) | part of 25–34 ms/s of frames at 16 viewers | exact | low |
| The skill script's breath test run natively before the script, for the about 570 "out of breath" refusals a second | up to about −12 ms/s at 200 fighters | exact only checked against the script (a `_check` law) | medium: the script is the world's |
| Each transaction's commit and subscription work (§2 (e2)) | unknown until a host profile splits it | – | – |

Together the exact items might take 30–50 ms/s at 216 viewers and 15–20 at 16, a third of it the breath test, which does not grow with viewers. None of them closes the per-pair gap.

### 4.5 What §4 adds to §5

At a sustained 200 fighters the battle itself takes about 320 ms/s. (d) at 10 Hz frees about 55 of it, (c) about 11, the exact items perhaps 30–50 at 216 viewers. That raises the tick rate at 216 by a few percent (+7% measured for (d)), but the per-pair cost, about 100–130 µs/s at 16 viewers against a budget of 7–10, is untouched. The per-pair gap is (a)'s and (b)'s.

## 5. A recommended combination (preliminary, one run each)

At 216 viewers on the 26–32 m ring, (a) and (b) each free about 45–67 ms/s of the database thread and raise the tick rate by about 20%. (c) and (e1) show nothing measurable, (e1) a loss.

- **Recommended to try together:** (a) with the aggregated far crowd (so the far battle stays visible), plus (b). Their effects should add, since (a) cuts pairs and (b) cuts how often the remaining pairs refresh.
  - A rough estimate, to be measured as one arm: −90 to −110 ms/s at 216, tick rate about 30.
- **How far that gets.** At 216 viewers on the 26–32 m ring the base runs at 23 ticks/s with the database thread saturated. Reaching 60 Hz needs the thread at about 600 ms/s or less with ticks three times as often. Every tick-bound cost then triples, so about a 3–4× cut of the per-pair cost at 60 Hz.
  - (a) at N = 40 with crowd rows cuts pairs by about 1.5× at this ring (59 → 40 seen) and about 2.2× at the 10 m ring (90 → 40). At N = 20 it would cut them 3–4.5×.
  - (b) cuts the sweeps' share (about a quarter of the per-pair cost) by up to 3×.
  - Together, with the Spark's tick-body trims, the contract looks reachable only with a far cap of about 20–30 and crowd rows: a large change to what a player sees of a big battle.
- **The owner's question is therefore:** how much of a distant battle must a player see individually? The cost follows that number almost linearly.

The repeats (Sol, after the 25th), the combined arm, the aggregated crowd prototype and the stills come before any of this is proposed for play.

## Evidence

`.local/bl/runs/` on the dev-box (worktree; archived with the branch): each arm's `battle-viewers.json`, `metrics.json`, `threads.json`, `load.log`, `events-*.jsonl`; `series.log` with the module's hash and the load at each start.
