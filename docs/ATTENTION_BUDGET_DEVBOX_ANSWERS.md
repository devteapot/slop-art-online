# Attention budget: dev-box's answers to §3.5

Status: design answers only, 2026-11-22, branch `attention-budget-devbox` from `origin/attention-budget` (112a42bfe). The code read is main's at `752f73d12`; `living/authority`, `living/game`, `living/mind` and `living/viewer` are identical there to the note's base `8384dc77`. No code, schema or law changed, and nothing was run beyond reading. Questions are those of [ATTENTION_BUDGET.md §3.5](ATTENTION_BUDGET.md#35-questions-for-dev-box). Paths below are under `living/` unless they start with `docs/` or `.agents/`.

## In short: blockers and objections

No question blocks the design. Seven things in it are wrong as written:

1. **Only players have a perceived set** (Q1). `perceived`, `projected` and the copies exist only for human players (`perception::sweep`, `authority/src/perception.rs:1127-1165`; `combat::humans`, `combat.rs:47-70`). AI characters, and every rule check, call the sight rule afresh through `perception::Sensing` (`brain.rs:348-360`, `perception.rs:309-449`). So "attended = `perceived`" works for players only. Minds need a new attended set in module memory, and every writer of what a mind learns would have to filter by it. Most of those writers call `in_sight` directly, not `perceived`: hearing, fight folds, witness percepts, the combat feed, first sights, cues and graph conditions. The authority-side scope is larger than §1.4's table suggests.
2. **The cost model's i is not a constant.** 120 µs/s is the 16-viewer pair average near 60 Hz (2.2 µs a tick). At 216 viewers the measured cost per pair per tick is 1.9–2.3 µs with about 58 in sight, but 10.6 µs with about 166 in sight (docs/COMBAT_PHASE.md, "Part A"). The per-pair cost grows with density. That helps a cap, but it makes §3.2's table an extrapolation from one density. No near/far split of a pair's cost exists, no tier flip has been costed, and "16–40 µs/s per far pair" cannot be rebuilt beyond about 16 and 29 from the single runs it rests on. A small `far_cap` sweep would measure all of it (Q2).
3. **Crowd members would leak handles through paths outside `perceived`.**
   - The combat feed masks actor and target only by sight (`combat.rs:139-187`).
   - `my_earshot` and the experience lines name individuals by sight.
   - A crowd member must stay anonymous on every path, not only in the copies.
4. **Earshot would under-report.** `show_earshot` decides who hears the player from the scene (`frame.rs:1141`). With crowds it would tell a player that fewer people hear them than do. This is a consent issue for speech, so it must read sight.
5. **On-stage detection would miss players in a mind's crowd.** The mind service marks a mind on stage when its scene lists a player (`mind/src/mind.rs:1885-1897`). A player who is crowd to that mind would no longer count, and the level of detail and the rethink gate would treat it as off stage.
6. **An engaged creature must never be crowd** (Q8). The proposed `attend_engaged_max` (8) can leave an attacker unattended. That attacker then gets no cue, copy or projection, which means an invisible blow. If the cap stays, the overflow must still get copies.
7. **`human_attend` as written does not compile** (Q9). `spacetimedb-sats` 2.14.1 has no `SpacetimeType` for tuples, and a reducer call per held hover is a transaction for every change.

**Names.** "Attention" is already taken twice: the gaze-band table and module (`authority/src/attention.rs`, `human_gaze`) and the cue design (docs/ATTENTION.md). `crowd` is taken by the `crowd_sweep_n` and `crowd_frame_max_ms` laws. New names should avoid both.

## Q1. Can "attended" simply be the perceived set?

**For players, yes.** `far_cap` already does exactly this (`perception.rs:1308-1323`):
- It trims the seen set to N, engaged creatures first (`frame::engaged_with`), then the nearest.
- Trimmed creatures get no `perceived`, `projected`, copy or cue rows. Through its `capped` set they get no `heard` row either (`perception.rs:1336`).

The attended set can replace that trim at the same point in `sweep_one`, and every copy, tier, cue and frame follows from `Viewer.scene` (`frame.rs:149-191`, `376`) without a second set.

**For minds, no.** No perceived set exists for them (summary, item 1). A mind's attended set has to be new module memory. Every `Sensing` reader that should see individuals would consult it: graph `Sees`, `Count`, `Doing`, `Threatened` and the `Nearest`/`Id` targets (`brain.rs:1100-1115`, `1211`, `1284-1380`), cues and first sights (`brain.rs:1586-1680`, `1996-2096`), and `scene_json` (`perceive.rs:824-1060`).

**Readers that treat `perceived` or `Viewer.scene` as "everyone in sight", and must move to a sight set:**

| Reader | Where | With crowds as written |
|---|---|---|
| Heard rows | `perception.rs:1336` | In-sight crowd members become anonymous `heard_sounds` unless they are excluded the way `far_cap`'s `capped` excludes them. This is a decision: the note wants crowd speech as "someone in the crowd". |
| Earshot | `frame.rs:1126-1149`, `earshot.rs:21-38` | Under-reports who hears the player (summary, item 4) |
| Keep margin on player acts | `act.rs:759`, `act.rs:1074` | Uses `perceived` only to grant the 1 m and field-angle keep margin (`rules/src/sight.rs:121-135`). Moot if aimed acts require "attended", as §1.4 proposes. |
| Cues | `frame.rs:911` | Only scene members get cues. Engaged creatures must therefore always be in the scene (Q8). |
| Engaged into the near tier | `frame.rs:777-807` (`scene.contains`, 783) | Same requirement |
| Test harnesses | `tools/battle_viewers.py:289-304`, `.agents/skills/verify-client/scripts/motion_tables.py:212-223`, `drive.py:836-837` | They assert that tables equal views and that `my_earshot ⊆ seen_characters`. They need the crowd case. |

**Readers that follow `perceived` and need nothing:**
- `look::reproject` (Q7).
- `health_moved`, which reads only the own row (`perception.rs:2152`).
- `perception::gone` and `forget` (`perception.rs:2172-2234`).
- `kept_sweep` and `check_rows` (`perception.rs:1735-1920`).
- The determinism hash (`det.rs:229-236`).

**Paths that never read `perceived`** (they call `in_sight` or `sees_creature`, so they must be changed to filter by attended if minds and players are to "learn only the attended"):
- speech hearers (`speech.rs:254`, `302`, `334`);
- fight folds (`fold.rs:51-82`);
- the combat feed (`combat.rs:139-187`, `632-651`);
- witness percepts (`perceive.rs:169`, `217-220`);
- the fast lane (`fast.rs:65`).

The game client draws, picks, names and targets only from `Scene.shown`, which holds creatures with a motion row (`game/src/bodies.rs:360-389`). It never panics on a missing row (`net.rs:1293-1444`). So a crowd member is simply not drawn, and the impostor crowd must come from the new rows. The observers read truth tables (`viewer/src/net.rs:13-39`) and are unaffected.

**Recommendation.** Keep `perceived` as the attended set for players. Add a sight set in module memory (`Viewer.sight` beside `Viewer.scene`) for earshot, heard exclusion and keep margins. For minds, add an attended set in module memory keyed by actor, read by `Sensing`'s individual queries. No new table is needed for either.

## Q2. Is there a split of a pair's cost into near and far?

**No measurement exists.**
- There is no near/far split of a pair's cost.
- No tier flip has been costed.
- No per-viewer cost by tier exists, only per view call (docs/COMBAT_PHASE.md lines 206-211 and 300-306: `seen_bodies_far` 83–176 µs a call against `seen_bodies_near` 42–46, and most of those views have since moved to tables).

**What is measured** (docs/COMBAT_PHASE.md, "Part A: the per-pair series on main", Spark, two runs per arm, L1, copy tables on):

| Arm | In sight | Ticks/s | Pair µs/s | Pair µs a tick |
|---|---:|---:|---:|---:|
| 16 viewers, 10 m ring | 81–93 | 59.7–59.9 | 119–144 (130 at low load) | 2.0–2.5 |
| 216 viewers, 26–32 m ring | 57–61 | 23.7–28.1 | 42.5–44.2 | 1.9–2.3 |
| 216 viewers, 10 m ring | 166–167 | 2.4–2.5 | 19.4–20.3 | 10.6–10.7 |

- **Per second, the 216-viewer arms are not comparable.** The thread is saturated, as COMBAT_PHASE itself notes. Per tick they are.
- At about 58 in sight, a pair costs what it does at 16 viewers (about 2 µs a tick, or about 120–140 µs/s at 60 Hz). So the note's i = 120 is right for that density.
- At about 166 in sight it costs about 5 times more a tick. Cost per pair grows with C. That favours a cap, but §3.2 should not apply one i to C = 60 and C = 200 alike.

**The 16–40 µs/s figure** (docs/BATTLE_LAWS.md §2(a)) rests on one run per arm:
- The raw files are on dev-box, `.local/bl/runs/` in worktree `t3-b749c655`, with `series.log`; `threads.json` reads 465.3 → 441.8 and 789.4 → 722.1 ms/s.
- The two base runs at 16 viewers differed by ±15–20 ms/s, and the cap saved 23. So that arm is near noise.
- From those numbers I get about 29 µs/s per dropped pair at 16 viewers and about 16 at 216. At 216 the tick rate also changed, which confounds it. I cannot rebuild 40.
- Since the cap of 40 exceeds `NEAR_MAX` (32, `frame.rs:130`), the dropped pairs were all far-tier.

**A cheap measurement** (one host, about 30 minutes, no viewers beyond what is listed):
- **Fixture:** `battle_viewers.py`, 16 viewers, 10 m ring, `--tiers --cues --paused-placement --keep-alive 0.5`, L1 (`--full-log`, which the per-pair method needs for `sweep:seen`), 20 s warm-up, 60 s window.
- **Arms:** `far_cap` 0, 48, 32, 16 and 8 through `law_override`, two interleaved runs each, plus a 0-viewer reference.
- **Reading:** the trim keeps engaged creatures and then the nearest, and the near tier is at most 32 within 8 m. So arms 0 → 32 drop only far pairs, and 32 → 8 drops near pairs.
  - The slope of database-thread ms/s against kept pairs in each range is the far and near marginal cost. The `far_cap:dropped` and `sweep:seen` counters give the pairs.
  - A repeat of the 0 and 16 arms at 216 viewers on the 26–32 m ring gives the same slopes per tick at high viewer counts.
  - That is i_far, i_near and their dependence on C, which is what §3.2 needs.

## Q3. Promotion and demotion: insert and delete, or a grace period?

**Insert and delete, with the hold.** Today a creature leaving the scene is deleted in the same sweep (`perception.rs:1354-1359`, `frame::drop_copies` at `frame.rs:1367-1383`). Its projection goes through `proj_delete` (`perception.rs:1434-1437`, `1780-1785`). There is no time-based grace. The only hysteresis is spatial:
- the keep margin (1 m plus the field angle);
- the near tier's 8 m in and 9 m out, with a half-metre bonus (`frame.rs:114-117`, `469`).

**Against hidden copies.** A copy hidden by a flag is still a row the client receives, and keeping it current costs what an attended creature costs. It would deliver a demoted creature's position to the client, which is perception the law says the character no longer has. It saves nothing and breaks the rule. A hold on the place (`attend_hold_ms`) is the right damper.

**A tier flip is only a partial proxy.**
- A flip rewrites copies between tiers (`frame::scene`, `frame.rs:366-412`). A promotion inserts a projection and copies, and a demotion deletes them.
- The closest measured numbers are for entering and leaving sight (docs/COMBAT_PHASE.md lines 191, 224, 413):
  - `sweep.rows` is 113–115 µs a sweep at 216 viewers on the 10 m ring, with about 23 enters and 23 leaves a sweep. That works out to about 2.6–3.8 µs an event; this is my arithmetic, not measured per event.
  - `project.show` (copies for newcomers) adds 59–66 µs a sweep (lines 633, 644).
- So a promotion plus a demotion costs a few µs plus the newcomer's copies, and churn of a few changes per viewer a second costs tens of µs/s per viewer. That is a derived estimate. §5.2 should count promotions per viewer-second and read the `sweep.rows` and `project.show` spans, to settle it.

## Q4. Should crowd rows share the frames' row budget?

**Give them their own budget, slowed by the frames' overload signal.** The frames' budgets are per tick, across viewers (`frame.rs`):
- `FRAME_ROWS_PER_TICK` is 2,500, with a floor `FRAME_ROWS_MIN` of 250. It shrinks by 1/8 after a late tick and grows by 2 otherwise (`budget()`, `frame.rs:251-264`).
- `SCENE_ROWS_PER_S` (2,000) is not a row budget. It sets one viewer's frame interval from its far-tier size, between 33 and 100 ms (`frame.rs:82`, `539-541`).
- Cues have `CUE_ROWS_PER_TICK` 3,000 with a floor of 300, and engaged pairs are never deferred (`frame.rs:135-136`, `946-965`).

At 216 viewers, 48 cells refreshed at 1 Hz is up to 10,368 rows a second, about 173 a tick at 60 Hz. Sharing the frames' budget would let crowd rows take most of the 250-row floor under overload, exactly when individuals' motion matters most.

**Recommendation:**
- A separate cap (≤ `crowd_cells_max` rows a viewer a second), staggered over ticks as sweeps are (`SWEEP_GROUPS`).
- Rewrite a cell only when its quantized content changed (Q5).
- Stretch the refresh (1 Hz toward 0.5 Hz) while the frame budget sits at its floor. The crowd is the least urgent delivery.

## Q5. Is `seen_crowd`'s shape right?

**Yes, with three changes.**

- **The primary key and in-place update are right.** A keyless table writes every change as an insert plus a delete: `seen_body_copy` still has no key, and the client sees insert and delete pairs (`game/src/net.rs:507-532`). The fighter copy's keyed version (docs/BATTLE_VIEWERS.md Addendum 5) is the lesson. Its "24–43 ms/s" figure comes from the validation record `.agents/skills/verify-client/references/validation/2026-11-20-0930-fighter-tables.md`, which states neither run count nor baseline, so treat it as an indication.
  - The key (`viewer` character id in the high 32 bits, cell in the low 32) is a sound `u64`.
- **About 70 B is fine; the number of writes is what to cut.** One individual today costs a viewer about 98 + 87 + 79 B plus strings across three copy rows (bindings `seen_body_copy_type.rs`, `seen_fighter_copy_type.rs`, `seen_character_copy_type.rs`). A crowd row replacing several individuals is cheaper on any reading.
  - The cost lies in rewrites. A moving crowd's `f32` centroid changes every second, so every cell would be rewritten at every refresh. Make the update conditional on quantized values: centroid and spread to 0.5 m, cell-relative, as `i16` or `u8`, and counts as they are. Then a still crowd writes nothing. That saves more than shrinking the row.
  - Moving to `i16` saves about 8 B a row. That is worth having, but secondary.
- **Change `kinds` (`u8`).** Check it against the number of creature kinds the seeds use (`seeds/repertoire.json`'s species plus `person`). Use `u16` if they exceed 8.
- **Keep it a regular table, not an event table** (verified, below): a crowd is state the client needs after reconnecting.

**SpacetimeDB documentation** (read 2026-11-22; every page shows version 2.0.0; the pinned server and crates are 2.14.1):
- [Event tables](https://spacetimedb.com/docs/tables/event-tables/): "Once subscribed, event table rows are never stored in the client cache"; "The inserts are still recorded in the commitlog". That is verified for 2.0.0 docs. That it holds in 2.14.1 is assumed, though consistent with the project's `combat_feed` measurements (docs/BATTLE_VIEWERS.md).
- [Performance](https://spacetimedb.com/docs/tables/performance/): "Keep Tables Focused … touching fewer rows", "Be mindful of unbounded table growth". `seen_crowd` is bounded at ≤ `crowd_cells_max` × viewers.

## Q6. Can the crowd table's access rule ride an existing disconnect window?

**Yes, if it is published with the law, off by default, in a publish that already changes row-level security.**
- A publish that adds or changes a row-level security rule disconnects every client once. This is from the 2.14.1 source, not the docs: `ensure_disconnect_all_users`, docs/BATTLE_VIEWERS.md line 84 and docs/TICK_RATE.md line 458 (`auto_migrate.rs` 1315–1337).
- Two rules in one publish cost one disconnect (docs/BATTLE_VIEWERS.md line 166).
- A fresh world's genesis disconnects nobody (lines 321–327).
- The project's policy is a merge window with a mind restart, never during an owner play-test (docs/TICK_RATE.md lines 468, 474).

**No next window is scheduled in any doc.** The disconnect is paid at publish, not when the law is turned on. So the table and its `client_visibility_filter` should ship in the build that adds the law, off by default, merged in a window. If another row-level security change is pending then (any of the seven rules in `frame.rs:1563-1581`), put them in the same publish. Battle and test worlds made fresh pay nothing.

**The documentation does not cover this** ([Row-level security](https://spacetimedb.com/docs/how-to/rls)):
- It calls the feature "an experimental, unstable feature … use Views instead". That is verified for the 2.0.0 docs.
- It says nothing about disconnecting at publish, so that part rests on the versioned source the project read, not the docs.
- [Views](https://spacetimedb.com/docs/functions/views/): "Per-user views require separate computation for each subscriber", which is why copies and crowds are tables. Verified for 2.0.0.

## Q7. Will code break when crowd members have no projection?

**Nothing breaks; several things silently change.**

**Safe:**
- `look::reproject` (`look.rs:363-370`, reached from `relook` at 386) iterates `projected.body(id)`. A crowd member has no rows, so nothing is rewritten. A promotion inserts the projection fresh with the current look line (`proj_insert`, `perception.rs:2648-2664`).
- `health_moved` reads only the own row.
- `perceived_band` / `show_band` fall back and do not write (`frame.rs:1585-1609`).
- `perception::gone` iterates `projected.body` to drop copies. That stays correct as long as the invariant "copies exist only with a projected row" holds, and crowds have neither.

**Changes to handle:**
- Heard rows and earshot (Q1).
- The combat feed's id masking (summary, item 3).
- Mind on-stage detection (summary, item 5).
- **Mind recall:** `recall::scene_cues` builds `person:{id}` keys from scene creatures (`mind/src/mind/recall.rs:146-156`). If a crowd member were ever listed among `creatures` without an id, the key would be `person:null`. Keep crowds in their own `crowds` array, as §2.1 has them, and the risk is gone.
- **Mind prompts:** experience lines resolve ids against the truth `character` table (`mind/src/mind.rs:1006-1034`), so a line naming a crowd member would show an id the scene does not list. The writers must name crowd members as crowd (Q1's list), or the prompt contradicts itself.
- **Client:** speech bubbles, nameplates and the talk addressee skip a missing row (`game/src/ui/live.rs:209-210`, `287-288`; `game/src/talk.rs:262-299`). A crowd member's line shows in the log as "Someone" (`ui/live.rs:187`). That is the right default.

## Q8. Any objection to extending the engagement set to AI viewers?

**No objection on cost. The cost is an estimate, not a measurement.**
- `TARGETS` already holds every actor's current move and visible act target (`frame.rs:212`, `720-724`).
- `engaged_of` keeps only pairs that involve a human (`human.contains`, `frame.rs:746-751`).
- For every character, that filter goes, and the reverse map holds one entry per live aimed move or act: at most a few hundred at 200 fighters (§3.3: p90 1, at most 3 aimed at one fighter). That is hash-map work per tick, well under a millisecond a second.

**Three conditions:**
- **`TARGET_DIRTY` is filled only while a delivery law is on**, and both maps are cleared when `cue_transport_on` and `near_tier_on` are off (`frame.rs:689-695`). With the attention law on, they must be kept whatever the delivery laws say, and `engaged_of` must run in `deliver` with every actor, not only humans.
- **`TARGETS` is the right source.** The `fighter` table has no index on `target` (`tables.rs:1705-1720`), so "who aims at me" from rows would be a scan.
- **Engagement must outrank the cap** (summary, item 6). The near tier already never defers engaged pairs (`frame.rs:946-965`). The attended set should do the same and count, not drop, any overflow.

AI graphs already have their own notions of engagement: `Target::Attacker` from `vitals.hurt_by` within 60 s (`brain.rs:1027`), and `Threatened` through `Sensing`. These should resolve through the same set, so a mind and a player are attacked "visibly" by the same rule.

## Q9. Is the proposed `human_attend` reducer shape right?

**Not as written.**

- **Tuples are not reducer argument types in 2.14.1.**
  - `spacetimedb-sats` 2.14.1 implements `SpacetimeType` for `()`, slices, `Vec`, `Option`, `Result` and smart pointers. It has no tuple implementation (`typespace.rs`, lines 356–433 of the crate source). This is a source reading; I did not compile a test.
  - `Option<(f32, f32)>` therefore needs a `#[derive(SpacetimeType)] struct Point { x: f32, y: f32 }` (`Option<Point>`), or two `f32` arguments with "none" encoded. `Vec<u32>` is fine.
- **No character argument.** "Refused for another's character" is automatic: the `human_*` reducers resolve the caller's own character from `ctx.sender` (`my_character`, `lib.rs`; [reducer context](https://spacetimedb.com/docs/functions/reducers/reducer-context): "Every reducer invocation has an associated caller identity").
- **Rate limit through the input bucket, not a gate of its own.**
  - `human_gaze`'s 250 ms limit is a separate per-character gate (`attention.rs:18-41`), and it spends no input token.
  - `human_face` and `human_act` spend from the shared bucket (`input_hz` 30, `input_burst` 15; `motion.rs:1389-1401`, `acts.rs:34-40`).
  - Pins should spend a token too, so a client cannot raise its input rate by alternating reducers.
- **Keep hover and focus off the wire where the authority already knows them.**
  - The client has no pin or focus concept today. Its combat target is recomputed every frame from the pick (`game/src/combat.rs:118-119`, `478-492`). Only the talk window pins an addressee (`talk.rs:97-99`).
  - A reducer call per held hover is a transaction per change: 216 players hovering around would be hundreds of calls a second.
  - The authority already sees the player's aimed acts, `use_skill` targets and the talk addressee. Derive "focus" from those, and send `human_attend` only for explicit pins and a deliberate "look at that one" click.
  - Hover held 300 ms could stay client-side (a predicted highlight) until the click.
- **The client's input path:** these calls sit beside `human_gaze` in `game/src/net.rs:1607-1654` (one call in flight, a gap between changes) and `game/src/controls.rs`. Promotion by clicking a crowd figure belongs in `pick.rs`, which today picks only from `scene.shown` (`pick.rs:114-127`).

## Sources

- **Code:** main at `752f73d12`, as named above.
- **Measurements:**
  - docs/COMBAT_PHASE.md, "battle-laws … Part A" (Spark, raw runs `~/slop-evidence/battle-laws-20261120.tar.zst` on the Spark);
  - docs/BATTLE_LAWS.md §2(a) (dev-box, raw runs `.local/bl/runs/` in worktree `t3-b749c655` and `~/archive/worktree-evidence-20261120/battle-laws-local.tar.gz`);
  - docs/BATTLE_VIEWERS.md (Addenda; `ensure_disconnect_all_users`; commitlog).
- **SpacetimeDB:** the official docs pages linked above, all version 2.0.0 on 2026-11-22. Statements about 2.14.1 beyond them come from the crate source in `~/.cargo/registry` (`spacetimedb-sats-2.14.1`) and the project's earlier readings of the `v2.14.1` server source, and are marked as such.
