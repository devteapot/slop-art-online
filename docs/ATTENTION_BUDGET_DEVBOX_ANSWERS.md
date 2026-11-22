# Attention budget: dev-box's answers to §12 (v2)

Status: design answers, updated 2026-11-22 for [ATTENTION_BUDGET.md](ATTENTION_BUDGET.md) v2 (`48ad5161c`, merged as `ca48edd56`). The first version answered v1 §3.5 from main `752f73d12`'s code and is in this branch's history at `8a9f8d6a2`.

This update adds:
- the coordinator's ruling on forced individuals;
- Q10 and Q11;
- E2's measurements, in place of the estimates Q2–Q4 had (docs/ATTENTION_E2_COST.md, on `attention-e2` and the docs-only `attention-e2-doc`).

The code read is main at `a6375a70e`. `frame.rs` and `perception.rs` are identical there to `752f73d12`. No code, schema or law changed on this branch. Paths are under `living/` unless they start with `docs/`.

## In short

**No question blocks the design. E2 changes its cost case.**

- **The ceiling is not set by the attended cost.** At 216 viewers and 60 Hz, a viewer with **nobody** attended already costs 4.3–5.0 ms/s, against a per-viewer budget of about 1.06 ms/s on dev-box (1.4–1.7 in v2, on the Spark's faster core). v2 §6's formula has no per-viewer constant, so no ceiling, 0 included, fits until that floor is cut (E2 §2.3, §4).
- **The attended cost, measured** (16 viewers, clean):
  - 67 ± 22 µs/s marginal per individual between ceilings 8 and 32;
  - 130–140 µs/s on average from none to 16, because the first attended are the near fighters, who cost about 190 µs/s each.
  - v2's `i + 10 µs` is roughly right for the marginal one, but not for the first eight.
- **Holds, not grace** (Q3). With `heed`'s holds (`attention-exp` `aa3d4d9e2`), a viewer at 216 sees 7–8 flip-backs a minute within 2 s. Without them it sees 378; a 1 s grace on an unheld instinct still leaves 115.
- **Q10:** the frames' changed marks are the right *test*, but not a per-tick *list*, and `moved` fires for nearly every fighter every tick. Hook the event re-rank on contact and aim (`fought`, `hurt`, `did` and `TARGETS`), for the target only. Everyone else waits for the 5 Hz sweep.
- **Q11:** a capacity drop mid-fight (16 → 6) causes no tick spike at 16 or 216 viewers. No frame-budget assumption breaks.

**Still wrong in the design as written** (carried from the first version, updated):
1. **Only players have a perceived set** (Q1). Minds need a new attended set in module memory, and every writer of what a mind learns must filter by it.
2. **i is not one constant** (Q2). It depends on density and on who is attended. See E2's tables.
3. **Crowd members leak through paths outside `perceived`**: the combat feed, `my_earshot` and the experience lines. E2 confirms it for the combat feed: 128,711 rows in one 16-viewer run, not trimmed by attention.
4. **Earshot would under-report** if it read the scene. It must read sight.
5. **On-stage detection would miss players in a mind's crowd** (`mind/src/mind.rs:1885-1897`).
6. **Forced individuals:** ruled (below). v1's `attend_engaged_max` cap is gone.
7. **`human_attend` as written does not compile** (Q9).

**Names.** Accepted (the Spark's points): the new names avoid gaze, cues and `crowd_*`. They are `heed` for the selector and `throng` for the many. Hover stays client-side; only pin, focus and target are sent, batched (Q9).

## The ruling on forced individuals (point 6)

The coordinator ruled on 2026-11-22:

> Forced individual, outside capacity and policy: whoever the viewer is acting on; whoever made contact with the viewer in the last few seconds: a blow landed, blocked or dodged. Not forced: someone winding up at me or closing on me stays with the policy; the starting instinct ranks them first. Consequence: a first blow from an untracked attacker is possible …; repeated invisible blows are not.

**What follows for the build:**
- **`Contact` needs blocks and dodges per viewer.** Today only `vitals.hurt_by` holds the last landed blow. Blocks and dodges are outcomes in the combat feed and the fold, not kept per defender. The build needs a small per-character "last contact by whom, when" in module memory, written where blocks and dodges are resolved. It does not need a table.
- **"Acting on" is already known:** `TARGETS` for moves and visible acts (`frame.rs:212`), and the talk addressee.
- **The forced set must be kept for every character, not only humans,** so `engaged_of`'s human filter (`frame.rs:728`) goes for this purpose (Q8).
- **How E2's arms compare:**
  - policies 0 and 1 forced every engaged creature (wider than the ruling);
  - policy 2 forced none (narrower);
  - `heed` (policies 3 and 4) forced `Acting` and `Contact` from the viewer's own last hurt only (slightly narrower: no blocks or dodges).
  - **The first-blow risk:** E2 did not measure first blows from unheeded attackers. The Spark's replay found 0 of 174 (437 windups aimed at subjects, all heeded at their start).

## Q1. Can "attended" simply be the perceived set?

**For players, yes.** E2 built exactly this.
- The attended set replaces `far_cap`'s trim at the same point in `perception::sweep_one`.
- Every copy, tier, cue and frame follows from `Viewer.scene` without a second set.
- With the laws off, the module is identical to main over 1,800 ticks and 113 tables (E2 §7).

**For minds, no.** No perceived set exists for them. A mind's attended set has to be new module memory, read by `Sensing`'s individual queries:
- graph `Sees`, `Count`, `Doing`, `Threatened` and the `Nearest`/`Id` targets (`brain.rs:1100-1115`, `1211`, `1284-1380`);
- cues and first sights (`brain.rs:1586-1680`, `1996-2096`);
- `scene_json` (`perceive.rs:824-1060`).

**Readers that treat `perceived` or `Viewer.scene` as "everyone in sight" and must move to a sight set:**

| Reader | Where | With crowds as written |
|---|---|---|
| Heard rows | `perception.rs:1336` | Crowd members become anonymous `heard_sounds` unless excluded as `far_cap`'s `capped` set excludes them. A decision is needed: the note wants crowd speech as "someone in the crowd". |
| Earshot | `frame.rs:1126-1149`, `earshot.rs:21-38` | Under-reports who hears the player |
| Keep margin on player acts | `act.rs:759`, `act.rs:1074` | Moot if aimed acts require "attended" |
| Cues | `frame.rs:911` | Only scene members get cues, so the forced set must always be in the scene |
| Engaged into the near tier | `frame.rs:777-807` | The same requirement |
| Test harnesses | `tools/battle_viewers.py:289-304`, `.agents/skills/verify-client/scripts/motion_tables.py:212-223`, `drive.py:836-837` | They need the crowd case. E2 did not run the privacy probe that compares tables and views with the laws on. |

**Readers that follow `perceived` and need nothing:**
- `look::reproject`;
- `health_moved`;
- `perception::gone` and `forget` (E2's `attend::clear` hooks `forget`);
- `kept_sweep` and `check_rows`;
- the determinism hash.

**Paths that never read `perceived`** (they must filter by attended for "learn only the attended"):
- speech hearers (`speech.rs:254`, `302`, `334`);
- fight folds (`fold.rs:51-82`);
- the combat feed (`combat.rs:139-187`, `632-651`);
- witness percepts (`perceive.rs:169`, `217-220`);
- the fast lane (`fast.rs:65`).

**Recommendation (unchanged):**
- Keep `perceived` as the attended set for players.
- Add a sight set in module memory (`Viewer.sight`) for earshot, heard exclusion and keep margins.
- For minds, add an attended set in module memory keyed by actor.
- No new table is needed for either.

## Q2. Is there a split of a pair's cost into near and far?

**Now measured, as cost by attended count rather than by tier** (E2 §2.1, 16 viewers on a 10 m ring, 110–128 in sight, two runs per arm):

| | ms/s per viewer |
|---|---:|
| Attention off (everyone, 128 in sight) | 11.08 |
| Nobody attended, nearest-first, no crowd: **the floor** | **4.26** |
| Nobody attended, `heed` pass and crowd rows | 5.00 |
| Ceiling 8 (my instinct) | 6.46 |
| Ceiling 16 (instinct / `heed` with holds / nearest-first) | 7.11 / 7.05 / 6.46 |
| Ceiling 24 / 32 (instinct) | 7.87 / 7.69 |

- **The marginal attended individual** costs 67 ± 22 µs/s between ceilings 8 and 32.
- **The first eight** cost about 190 µs/s each. They are the engaged and the nearest, so they are near-tier and fighting.
- **So the near/far split shows up as an order effect:** the first attended are near and expensive, the later ones far and cheaper.
- **At 216 viewers the host saturates in every arm** (16–36 ticks/s), so no per-attended cost is read from it. The floor per tick per viewer is about the same as at 16 viewers: 61 µs a tick against 71.

The older per-pair figures (docs/COMBAT_PHASE.md Part A; docs/BATTLE_LAWS.md §2(a)) are superseded for this purpose.

## Q3. Promotion and demotion: insert and delete, or a grace period?

**Insert and delete, with holds. E2 measured the alternatives** (216 viewers, ceiling 16, flip-backs per viewer-minute within 2 s; E2 §5):

| Selector | Flip-backs ≤ 2 s | Share of attended affected | Promotions per viewer-second |
|---|---:|---:|---:|
| Instinct, no grace | 612 | 59% | 13.4 |
| Instinct, 1 s grace | 115 | 25% | 9.5 |
| `heed` without holds | 378 | 47% | 10.9 |
| **`heed` with holds** (`aa3d4d9e2`) | **7.3–7.9** | **6%** | 5.2 |
| Nearest-first, 1 s grace | 20 | 10% | 5.2 |

- **Grace still delivers a dropped creature's position, and it hides the flips without stopping them.** Holds stop them at the source. With holds, grace is not needed.
- **Cost:** a promotion with its demotion costs about 25–30 µs (an estimate from a single run). At `heed`'s 6.7 promotions per viewer-second, that is about 0.2 ms/s per viewer.
- `sweep.project`'s share rises from 0.09 to 0.34 ms/s per viewer between ceilings 0 and 16 (L2).

## Q4. Should crowd rows share the frames' row budget?

**No. Give them their own budget, as before. E2 measured them:**
- **Volume:** 10–17 cells and 13–19 writes per viewer-second, at 6 m cells, 1 Hz and 0.5 m quantizing. A still crowd writes nothing.
- **Cost at 16 viewers:** about 0.04 ms/s per viewer in the pass, and about 0.08 ms/s with delivery. That is about 5 µs a write, as v2 assumed.
- **Cost at 216 viewers:** about 15–23 µs a write on a saturated host (an estimate). It may grow with the number of subscribers if each write is checked against every `viewer = :sender` filter.
  - That would hold for every copy table, and it argues for fewer, merged per-viewer tables.
  - E2 §3.3 proposes the measurement that would settle it.

## Q5. Is `seen_crowd`'s shape right?

**Yes. E2 built it as proposed with the changes:**
- a `u64` key, (viewer << 32) | level << 30 | cell, with a btree on `viewer`;
- an update in place;
- quantized values, written only on change;
- at most 48 cells, farther cells merged 2×2;
- a regular table, not an event table.

**Two further points:**
- **The quantized write works,** but moving crowds still rewrite most cells each second (writes exceed cells).
- **`moving` and `fallen`** were left at zero in E2. Computing them reads each member's body or nearby remains, which adds to the crowd's per-member cost. Keep them only if the client needs them.

**SpacetimeDB documentation** (read 2026-11-22; docs version 2.0.0; pinned 2.14.1):
- [event tables](https://spacetimedb.com/docs/tables/event-tables/): not cached, still logged;
- [performance](https://spacetimedb.com/docs/tables/performance/): keep tables focused and bounded;
- [indexes](https://spacetimedb.com/docs/tables/indexes/).

## Q6. Can the crowd table's access rule ride an existing disconnect window?

**Unchanged: yes, if it ships with the law, off, in a publish that already changes row-level security.**
- A publish that adds or changes a rule disconnects every client once. This is from the 2.14.1 source (`ensure_disconnect_all_users`; docs/BATTLE_VIEWERS.md), not the docs.
- A fresh world pays nothing, which is how E2 ran.
- [Row-level security](https://spacetimedb.com/docs/how-to/rls) is "experimental, unstable … use Views instead". [Views](https://spacetimedb.com/docs/functions/views/) "require separate computation for each subscriber". So the crowd stays a table.

## Q7. Will code break when crowd members have no projection?

**Nothing crashed or stalled in E2.** It ran 216 viewers with crowds and no projections for crowd members, and `forget` clears the attended state. No client-side or privacy check ran with the laws on. The silent changes listed in the first version still need handling:
- heard rows and earshot (Q1);
- the combat feed's id masking;
- mind on-stage detection;
- mind recall keys: keep crowds in their own array;
- mind prompt experience lines;
- the client's "Someone" default, which is right.

## Q8. Any objection to extending the engagement set to AI viewers?

**No objection. The ruling now defines what it is for.**
- **The forced set:** acting on (`TARGETS`) and contact in the last few seconds (a new per-character record; see the ruling).
- **The ranked-first set:** winding up at me and closing on me. These are the instinct's first rules, not forced.
- **Conditions, unchanged:**
  - `TARGETS` and `TARGET_DIRTY` must be kept while the attention law is on, whatever the delivery laws say (`frame.rs:689-695`);
  - `engaged_of` must run with every actor, not only humans;
  - "who aims at me" must come from `TARGETS`, because `fighter.target` has no index.
- **Cost:** not measured. E2 built human viewers only, and AI attention is E4. The map work is still an estimate at well under a millisecond a second.

## Q9. Is the proposed `human_attend` reducer shape right?

**Not as written. The Spark's points are accepted:**
- **Hover stays client-side.** Only pin, focus and target are sent, batched in one call with a `Vec`.
- **No tuples.** `spacetimedb-sats` 2.14.1 has no `SpacetimeType` for tuples (`typespace.rs`, lines 356–433; a source reading). Use a `#[derive(SpacetimeType)]` struct or plain `u32` lists.
- **No character argument.** The caller's own character comes from `ctx.sender` ([reducer context](https://spacetimedb.com/docs/functions/reducers/reducer-context)).
- **Spend from the shared input bucket** (`input_hz` 30, `input_burst` 15), not a gate of its own.
- **Derive focus where the authority already knows it:** aimed acts, `use_skill` targets and the talk addressee.

## Q10. Event-driven re-ranking in the tick: is the frames' changed-set the hook, and is it affordable?

**The changed marks are the right test, but not a list, and not all of them are events.**

- **What the frames have** (`frame.rs:199-215`, `328-360`): `MOVED`, `FOUGHT`, `HURT` and `DID` map each creature to the sequence number of its last change, for every creature in the world.
  - A viewer's frame asks, per scene member, "changed since my last frame?" (`changed`, `frame.rs:1031-1078`).
  - There is no per-tick list of what changed, and no inverse "who sees this creature" for creatures outside a viewer's near tier. `NEAR_OF` holds near-tier viewers only.
- **`moved` is not an event.** It marks every body row write, and in a battle almost every fighter's body is written every tick. Re-ranking on it would re-rank nearly every (viewer, creature in sight) pair every tick. That is 216 viewers × about 70 in sight × 60 Hz, about 900,000 evaluations a second, or about 0.6–0.9 s of database thread a second at E2's 0.65–1 µs an evaluation. That is not affordable.
- **The events worth an immediate re-rank** are the ones the ruling and the instinct care about: an aim at me (a `fought` or `did` write that changes `TARGETS`), contact (`hurt`, and blocks and dodges once they are kept), and being acted on.
  - **Admitting for the target only**, these are about one pair per event. In E2's battle, about 57 blows a second plus a similar number of windups is about 100–200 evaluations a second world-wide: under 0.2 ms/s in total.
  - **Checking every viewer that sees the creature** would cost much more. With a few events per creature a second, as v2 assumes, that is about 45,000 pair checks a second, about 30–45 ms/s in total: 0.14–0.21 ms/s per viewer, 13–20% of the 1.06 ms/s budget.
- **Recommendation:**
  - Hook the immediate re-rank on `TARGETS` changes and contact, for the aimed-at or struck character only.
  - Everything else (closing, fighting, salience) waits for the 5 Hz sweep, which already runs the selector, and the holds absorb the delay.
  - Keep `moved` out of the trigger.
  - This is what E2's `heed` arms did: forced places from contact and acting, and the rest at the sweep. They kept flicker at 7–8 a minute.

## Q11. Variable capacity: does a capacity that drops mid-fight break a frame-budget assumption?

**No. A capacity drop is a batch of demotions, measured** (E2 §6, `attend_burst_cap=6` flipped at 30 s):

| Arm | Viewers | Worst tick 1 s before → 1 s after (ms) | Missed slots |
|---|---:|---|---|
| Instinct | 16 | 15.1 → 13.4, 16.1 → 11.0 | 2 → 0, 1 → 0 |
| `heed` with holds | 16 | 12.0 → 12.4, 11.5 → 11.3 | 0 → 0 |
| Instinct (saturated) | 216 | 53 → 61, 60 → 60 | 44 → 39, 45 → 38 |
| `heed` with holds (saturated) | 216 | 52 → 51, 69 → 62 | 45 → 40, 45 → 41 |

- The second after the drop spends less in the tick, because fewer are attended.
- The frames' row budget is per tick across viewers, with a floor and a back-off (`frame.rs` `budget()`). Nothing assumes scenes change only with sight.
- **Visibly,** the drop with holds gives 12–13 flip-backs a minute, against 7–8 steady.
- **The opposite case was not measured:** a capacity rise is a batch of promotions with their copies, like newcomers to sight.

## Sources

- **Code:** main `a6375a70e`, and the prototype on `attention-e2`:
  - `b226aa8e0`, `5a81911a8`, `aeee62046`;
  - `heed` from `attention-exp` `aa3d4d9e2`.
- **Measurements:** docs/ATTENTION_E2_COST.md (`attention-e2-doc`), with its runs on the dev-box at `.local/e2/` in worktree `t3-b749c655`, archived at `~/archive/worktree-evidence-20261122/attention-e2.tar.zst`.
- **The Spark's replay:** `docs/ATTENTION_E3.md` on `attention-exp` (`67a68abd7`).
- **SpacetimeDB:** the official docs pages linked above, version 2.0.0 as read on 2026-11-22. Statements about 2.14.1 beyond them come from the crate source (`spacetimedb-sats-2.14.1`) and the project's earlier readings of the `v2.14.1` server source, and are marked.
