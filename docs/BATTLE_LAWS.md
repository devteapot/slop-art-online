# Battle laws: the owner's options for a battle watched by many players

Status: prototypes, measured once each, 2026-11-20. Branch `battle-laws` (dev-box), from `origin/main` `3c64dcac6`. Every option below is a law, **off in play**; nothing here changes the game until the owner chooses. The Spark adds its parts (§4: the tick body and module memory across transactions). The GC takes the whole document to the owner.

**Why this document.** The performance contract asks for 200 fighters at 60 Hz with players watching (docs/PERFORMANCE_CONTRACT.md; the immediate gate is 216 characters for 30 minutes). After the views track and the exact sweep work, a player watching a dense battle still costs about 85–105 µs a second for each creature it sees. The contract's budget is about 7–10 µs. That breakdown is in docs/BATTLE_VIEWERS.md, the addendum of views step 3, and in docs/COMBAT_PHASE.md. The rest of the gap is each player's own rows: its sweeps, its frames' writes, and each transaction's commit and subscription work. Exact work cannot remove those; only fewer pairs (fewer creatures each player is told about) or fewer refreshes can. Each of those changes what a player perceives, or when, so each is the owner's call.

## 1. How the options were measured

**Fixture.**
- Host and server: dev-box, its own server `sg-stdb` (SpacetimeDB 2.14.1), one core type, no pinning.
- Module: Cullet, built from this branch (`bl-cullet`).
- `living/tools/battle_viewers.py`: 200 AI fighters, the viewers placed while paused with the battle spawned after placing, and a keep-alive every 0.5 s so no viewer dies.
- The viewers: `gate-load` players on the tiers, the cues and both copy tables (the defaults since bv-defaults-on), walking small circles.
- Two densities:
  - **16 viewers on the 10 m ring**: about 90 creatures in each one's sight, so about 1,440 viewer–creature pairs;
  - **216 viewers on the 26–32 m ring**: about 59 each, about 12,700 pairs.
- 20 s warm-up, 60 s window, server metrics only (L0, no spans).
- The 1-minute load was below 4 at every start. No viewer died in any window.

**One run per arm.** Two base runs of the same fixture varied by ±15–20 ms/s at 16 viewers, so a difference smaller than that is not a result. The repeats (two more runs per arm, at both densities, interleaved) are for Sol after the 25th.

**Per pair** is the change in the database thread's CPU over the base's pairs. At 216 the database thread is saturated (about 790 ms of 1,000 a second), so the tick rate is the clearer result there: it goes up as the thread frees.

**Freshness** is `gate-load`'s sample (every third viewer) of how late a creature's new motion segment reached the client (ms, p50 / p90 / p95, all creatures in sight). It shows what a law does to what a player sees in time.

## 2. The options

### (a) A bounded far tier: at most N creatures seen at once (`far_cap`)

**What it does.** A player's sweep keeps at most N of the creatures in sight: first whoever is engaged with it (fighting it, aimed at it), then the nearest. The rest are neither seen nor heard by that player until they come within the N nearest. Prototype value: N = 40.

**What changes for a player.** In a crowd larger than N, the farther ones are not drawn at all. A player in a 200-fighter battle sees the 40 nearest (and anyone attacking it), and the far edge of the battle is empty ground. Its own fight, and those near it, are unchanged and fresher than before (below). The AI is untouched: a mind's scene, its sight and its memories are unchanged. That asymmetry is a rules question: the same rules for players and AI. The aggregated alternative below would keep a far crowd visible.

**Stills.** Not taken yet; they are the laptop's (verify-ui, the Bevy client).
- Two views of a far crowd at Middle and at Far (docs/CAMERA.md bands), law off and on (N = 40), from a player 26 m from the 200-fighter battle.
- Taken with `verify-ui`'s camera scenario on a world staged by `battle_viewers.py` (`--viewers 1 --ring 26,32 --law far_cap=40`), the game client joined as that viewer.

**Measured.**

| | 16 viewers, 10 m ring | 216 viewers, 26–32 m ring |
|---|---|---|
| Database thread, ms/s (base → law) | 465 → 442 (−23) | 789 → 722 (−67) |
| Per pair (µs/s, over the base's pairs) | about −16 | about −5 (at 23–28 ticks/s) |
| Ticks/s | 58.9 → 58.9 | 23.2 → 28.4 (+22%) |
| Freshness p50/p90/p95 (ms) | 35/100/149 → 25/44/52 | 72/440/801 → 53/110/351 |

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

**Measured.** No change measurable at one run: 465 → 481 ms/s at 16 viewers and 789 → 808 at 216, both within the runs' spread. Ticks/s at 216: 23.2 → 23.1. The Spark's diagnosis estimated about −23 ms/s at a sustained 200 fighters (`wake.eval.fight`). This fixture's fight thins over the window, and its bystander wakes are few. The repeat runs, with the Spark's spans, will tell.

**Risk.** Low. AI fighters' reactions to bystander events are a little later.

### (d) The combat cadence itself (the Spark's)

The Spark's part (docs/COMBAT_PHASE.md): the 15 Hz cadence at 10 Hz is about −45 ms/s and changes fighters' reaction timing. To be added by the Spark with its measurement.

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

*To be added by the Spark:*
- the AI-trims results and what remains of the tick body at a sustained 200 fighters;
- module memory across transactions (each viewer's `heard` rows and health readings kept between ticks, the `KEPT` pattern) with its bounded imprecision and expected gain;
- the combat cadence (d).

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
