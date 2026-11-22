# Attention budget: each character keeps track of at most N others (design note)

Status: **design only**, 2026-11-22, branch `attention-budget` (Spark), from `origin/main` `8384dc77`. Nothing is built: no law, table, reducer, view, prompt or default changes. The only file beside this note is a read-only analysis script, [`living/tools/attention_density.py`](../living/tools/attention_density.py), which the numbers below come from.

**The owner's idea** (2026-11-22, on the battle cap): "could a dynamic attention system work? there is a cap but the mind decides who to keep track of. we do kind of the same thing as players no?" This note designs it as a **perception law that is the same for players and minds**: each character perceives at most N others as individuals; *who* fills those places is partly the character's own choice; everyone else in sight is perceived as a crowd.

**What it would replace.**
- **The owner's 2026-11-10 ruling against attention caps** (docs/STRANGERS.md, Decisions 3; docs/BATTLE_SCALE.md: "everything within vision at full detail"). That is the owner's decision to revisit; nothing here assumes it.
- **`far_cap`** (docs/BATTLE_LAWS.md (a)). It caps only players' sight, so players and minds perceive differently.
- **A cap minds already have.** A mind's scene lists only the 14 nearest creatures ([`perceive.rs`](../living/authority/src/perceive.rs), `scene_json`: `if creatures.len() >= 14 { break }`). In the 200-mind battle, 14 is the p90 of what the think prompts listed (§3.3). So minds already have a distance-only cap in their prompts, while their graphs and players see everyone. The law would replace that hidden 14 with the same N for everyone.

## 0. In short

- **The rule.** Each character, player or mind, perceives at most **N = 16** others as individuals. The places fill in this order:
  - **(a) always in:** whoever is attacking or winding up at me, whomever I am acting on, whoever is addressing me, then the nearest within 8 m (the near tier);
  - **(b) chosen:** for a player, their target, focus, hover, pins and community; for a mind, its cues and the people its relations, family, community and projects name;
  - **(c) the rest,** by salience and distance.

  Everyone else in sight is a **crowd**. To a mind, a crowd is a scene line: count, direction, rough area, what is visibly going on. To a player it is crowd rows per 6 m cell, drawn as an impostor crowd.
- **Threats never wait on a mind.** (a) is computed by the authority every tick from engagement. The slow mind (5–40 s) and Jev (1–3 s) only shape (b), which is standing interest.
- **Cost.** With crowds, a viewer's cost goes from about C × 130 µs/s (C creatures in sight) to about **N × (i + 10) + (C − N) × 2 + K × 5 µs/s**. Here i is the per-individual delivery cost and K the number of crowd cells. The contract leaves about **1.4–1.7 ms/s per viewer** at 216 viewers. In the worst case (C ≈ 200 in sight) that fits at **N = 16 only once the planned exact view and sweep steps bring i down to about 30–40 µs/s**. At today's i (about 120) no N fits; at N = 24 it is marginal; at N = 32 it fails (§3.2). An attention budget is necessary but not sufficient.
- **Minds learn only the individuals they attended to,** plus crowd-level facts. That is a narrowing of perception, never an addition, so "minds know only what they perceive" holds. It makes ambushes, crowds as cover and distraction work by the same law for everyone (§4).
- **Jev as the mind's attention layer** (§7): one TypeSafe request per mind per 1–3 s, only while more than N are in sight. One state (what that mind perceives now), several questions from the mind's own cues, relations and projects. The answers are cached rows that fill (b) and are never waited on.
  - **Load:** about 2,700 input tokens a request and 20–60 calls a fighter-minute in a battle. In a town it is about zero: off stage nobody calls, and on stage C rarely exceeds N.
  - **Scale:** a 200-fighter battle-hour is about **5–14 times** the rethink gate's Jev use for 2,000 people for an hour (costs in relative terms; price only in the local prices file).
  - **Baseline:** the plain rule (cues and named people) is what Jev must beat, in replay first.
- **Default:** off (N = 0 means everyone in sight is an individual, today's rule). **Recommended N: 16,** with 6 m crowd cells refreshed at 1 Hz and at most 48 cells per viewer. Before the owner decides: the stills at N = 16 and N = 32, and one fake-model battle.

## 1. The rule

### 1.1 Two grains of perception

Sight is unchanged: the same `sight::sees` test (range, field, light, cover, a clear line) decides who is in sight, for players' sweeps, minds' scenes and graphs alike (docs/PERCEPTION.md, "Minds see what their character sees"). The new law decides **at which grain** each creature in sight is perceived:

| Grain | Who | What is perceived |
|---|---|---|
| **Individual** | the attended, at most N (plus engaged overflow, §1.2) | everything perceived today: the projection (name or label, band, look), motion, what they are visibly doing and at whom, speech as speech |
| **Crowd** | everyone else in sight | per area: count, where, how spread, which way it moves, what is visibly going on (how many fighting, fallen, the kinds present). No identity, health, name or exact pose |

The law is a **world law**, value-only, like the battle laws (docs/LAW_OVERRIDE.md). It changes delivery, scenes, graphs and memory for both controllers at once. `attend_n = 0` switches it off and is exactly today's behaviour; the hidden 14 in minds' scenes stays as it is while the law is off.

### 1.2 Filling the places, in order

Each character's attended set is refilled at its own cadence (§1.3), in this order. A place taken by a higher class is never given to a lower one.

**(a) Always in.**
1. **Engaged with me:** anyone whose unexpired move or visible act (a windup, a release, a shot) is aimed at me, and anyone mine is aimed at. This is `frame::engaged_of`, which today is computed only for players. Here it is extended to every character with the law on. An archer winding up at me from 20 m is attended in the tick its aim is seen, as the near tier already does (docs/PERCEPTION.md, "Cues and tiers").
2. **Addressing me:** a line spoken to me, or an offer, trade or request to me, within its window (the scene's "asked of you").
3. **The near tier:** the nearest within 8 m (9 m to drop), one already attended counting half a metre nearer, in the places that (b) leaves (below).

The engaged may exceed N. They are few by the fight's physics: in the 200-mind battle the open attacks aimed at one fighter were p50 0, p90 1, at most 3 (§3.3). Overflow is counted and bounded by `attend_engaged_max` (8) so no fixture can fan it out.

**(b) Chosen,** up to `attend_chosen_max` (4) places, reserved only while something chosen is in sight and can be made out. Unused places go back to the near tier and (c).

| Source | Player | Mind |
|---|---|---|
| The controller's explicit picks | target or focus (locked), hover held 300 ms, up to 4 pins, through one new reducer `human_attend` | its **cues** that match now (docs/ATTENTION.md: `who` by id or kind, `doing`, `phase`) and, with Jev on, Jev's picks (§7) |
| The character's own ties (authority facts, the same for both) | family (parents, children, the other parent), the character's community (the game has no party; its community stands in), people it pinned | family, community, people its `relation` rows name (strongest feeling first) and people its projects name |

- **Recognition is the authority's, and only where the character can make someone out.** A person under the far label ("someone too far away to make out", `regard().far`) cannot be picked by id, exactly as a cue cannot match them (docs/ATTENTION.md). A kind or `doing` cue can still pick a crowd member it describes ("a wolf", "someone throwing fire").
- **Promotion is visible.** A chosen creature that was crowd becomes attended with a told reason (§2.3).

**(c) The rest,** up to N, by **salience, then distance**. Salience is a Rust primitive with world-law weights; Rhai is never run per candidate (docs/CAMERA.md, "Proposed cadence"). Its terms are things visible to anyone:
- acting on someone I attend (striking my partner, giving to my child);
- closing on me (approach speed toward me);
- visibly fighting, fallen, or carrying a light at night;
- kind (a wolf before a deer);
- novelty: in sight for under 5 s.

No term reads a role, a duty, a side or a name list we wrote. A seed can weight the terms; it cannot name people.

**Hysteresis.** An attended creature keeps its place for at least `attend_hold_ms` (1,000) unless (a) needs the place. This damps the edge blinking BATTLE_LAWS noted for `far_cap`.

**Where N = 16 goes in a dense melee:** engaged (0–3) first, up to 4 chosen, the near tier, then salience. When more than about 12 stand within 8 m, the farther of them are crowd. That is the law's visible consequence at the recommended N.

### 1.3 Timing: who re-picks how fast

| Class | Computed | Lag after the cause |
|---|---|---|
| (a) engaged, addressing | every tick, from the engagement set the frames already keep | none: the tick the windup, blow or line is committed |
| (a) near tier | at each sweep (players, 200 ms) or evaluation slot (AI, 1 Hz and its wakes and fight cadence) | ≤ 200 ms (player), ≤ 67 ms in a fight (AI at 15 Hz) |
| (b) from cues, ties, player input | at the same sweep or slot, from indexed rows | ≤ 200 ms after the input or the creature coming into sight |
| (b) what to choose, for a mind | when the slow mind writes cues or relations (5–40 s a thought; up to ~35 s stale under load, docs/FAST_LANE_FRAME.md on `battle-frame`), or Jev every 1–3 s | seconds to tens of seconds |
| (c) salience | at the sweep or slot | ≤ 200 ms (player), ≤ 1 s (AI) |
| Crowd membership and cells | 1 Hz, staggered | ≤ 1 s |

**The slow mind's lag is why (a) must carry every threat.** A mind cannot think "watch the archer" in time to see the arrow. The authority puts anyone aiming at it in (a) in the same tick, whatever the mind chose. (b) is standing interest: who the character cares about or is looking for. A stale (b) costs at most 4 places, never a threat.

### 1.4 What attention changes elsewhere (both controllers)

| Path | Today | With the law on |
|---|---|---|
| A player's copies (`seen_body_copy`, `seen_character_copy`, `seen_fighter_copy`, doing, cues) | everyone in sight (`perceived`) | the attended only. Crowd members get crowd rows (§2.2) |
| A mind's scene (`scene_json`) | the 14 nearest | the attended (≤ N), each as today, plus crowd lines |
| Behaviour graphs (`sees`, `nearest`, a target) | everyone in sight | individuals: the attended. **Counts** (`count … within`) count the attended and the crowd, since a crowd's numbers are perceived. `nearest` and `attacker` are always in (a) |
| Aimed acts by id (player and mind) | the target must be in sight | the target must be attended. A player clicking a crowd figure promotes it first (§2.3) |
| Witnessed events, fight folds (`fold::flush`), first sights | named per creature in sight | named per attended creature. Crowd members' deeds fold into crowd lines ("in the crowd to the north, two fell"). `familiar` rows and first sights only for the attended (a crowd first sight stays one line: "You are among a crowd of about 121 people", `brain.rs` today) |
| Hearing | a line within earshot is heard from its speaker | a line addressed to me promotes its speaker ((a) 2). Others' lines from crowd members are heard as a crowd member speaking ("someone in the crowd to the east says …"), with no handle |
| Cues | matched against the scene's creatures | matched against everyone in sight (as now); a match promotes ((b)) |

The fold's naming cost falls with it: `fold.labels`, 43–51 ms/s at 200 fighters, is each onlooker's labels for everyone in its line (docs/BATTLE_SCALE.md, Fix 4).

### 1.5 Laws (value-only, off by default)

| Law | Default | Meaning |
|---|---|---|
| `attend_n` | 0 (off) | individuals per character; 0 is today's rule |
| `attend_chosen_max` | 4 | places (b) may reserve |
| `attend_engaged_max` | 8 | engaged overflow beyond N |
| `attend_hold_ms` | 1,000 | minimum hold of a place |
| `crowd_cell_m` | 6 | crowd cell size (world-aligned squares) |
| `crowd_hz` | 1 | crowd membership and rows refresh |
| `crowd_cells_max` | 48 | crowd rows per viewer. Beyond it, the farthest cells merge 2×2 |
| salience weights | seed data | (c)'s terms |

`far_cap` would be retired once this is built, since it is the player-only special case of this law with (b) and crowds missing.

## 2. What a crowd is

### 2.1 To a mind: scene lines

Each mind's scene gains `crowds`: one entry per compass direction and distance band (within reach, close, a stone's throw, far) that holds crowd members, built from the same cells as the player's rows:

```json
"crowds": [
  {"dir": "northeast", "dist": "a stone's throw", "about": 40, "across": "about 20 m",
   "moving": "toward you", "visibly": "most fighting; 3 fallen", "kinds": "people"}
]
```

- **Counts are rounded** ("about 40") as the existing crowd percept is, and the far label rule applies: a crowd says nothing a far figure would not.
- **No ids.** A crowd member has no handle until it is attended. A mind can still act on the crowd as a crowd: move away from it, toward it, or watch for a kind or deed in it through a cue.

### 2.2 To a player: crowd rows drawn as an impostor crowd

This is docs/BATTLE_LAWS.md (a)'s "aggregated far crowd", made general. It uses one new public table with the copy tables' row-level security.

| Column | Type | Note |
|---|---|---|
| `id` | `u64`, primary key | `key(viewer character, cell)`, so a change is one in-place update (`seen_fighter_copy`'s lesson: a keyless table cost 24–43 ms/s more) |
| `viewer` | `Identity`, btree | the RLS column, `SELECT * FROM seen_crowd WHERE viewer = :sender` |
| `cx`, `cy` | `i16` | cell index (world-aligned, `crowd_cell_m`) |
| `count` | `u16` | members in sight in the cell |
| `x`, `y`, `spread` | `f32` | centroid and spread (the renderer scatters figures in that ellipse) |
| `heading`, `moving` | `u8`, `u8` | dominant heading (16ths) and the moving share |
| `fighting`, `fallen` | `u16`, `u16` | members visibly in a fight move; remains in the cell |
| `kinds` | `u8` | a bitmask of the kinds present |

About 70 bytes a row; the identity is 32 of them, as Addendum 2 of docs/BATTLE_VIEWERS.md explains. The laptop's client draws each row as `count` generic, non-interactive figures without nameplates, animated locally (fighting or walking by the row's shares), placed by the centroid and spread. Hovering or clicking one is a request to attend (§2.3).

### 2.3 Promotion: a place and a visible reason

A creature moves from crowd to individual only by taking a place, and the reason is told:

- **A mind:** a `noticed` line in its own labels, as cues already write: "You pick out a stranger in the crowd to the north, striking someone you know." For (a), the reason is the engagement or address itself, already told by the blow, windup or line.
- **A player:** the client's crowd figure turns into the individual, with a short marker saying why (`attacking you`, `your pin`, `your community`, `you looked`), from a reason code on the copy. `human_attend(point)` on a crowd figure promotes the crowd member nearest that point in that cell, within the (b) quota. The reply is the next frame: about one frame interval plus the round trip.
- **Demotion** is silent, as leaving sight is today. The creature becomes part of its cell's count.

## 3. Delivery cost

### 3.1 The budget, and today's cost

From docs/COMBAT_PHASE.md ("Budget"):
- the whole tick call should stay at or below about 600 ms/s;
- the AI tick body at a sustained 200 fighters is about 300 ms/s, and about 240 after the exact trims;
- that leaves **300–360 ms/s for everything per viewer**: **1.4–1.7 ms/s per viewer** at 216, or about 7–10 µs/s per (viewer, creature in sight) pair at 160–200 in sight.

Today a pair costs about 130 µs/s, with the copy tables on. That is at 16 viewers on the 10 m ring, where each viewer adds about 12.4 ms/s: views 6.7, call remainder 2.2, sweeps 1.7, frames 1.6, cues 0.2.

### 3.2 The model with attention

Per viewer and second, with C creatures in sight, N attended and K crowd cells:

**cost ≈ N × (i + s₅) + (C − N) × s₁ + K × k**

| Term | Value used | Source |
|---|---|---|
| s₅: sight for an attended creature, swept at 5 Hz | about 10 µs/s | a sweep costs 339–378 µs at about 90 in sight (16 viewers), about half of it projection, so about 2 µs per creature a sweep |
| s₁: sight for a crowd member, at the crowd's 1 Hz | about 2 µs/s | the same test, a fifth as often. Crowd members get no projection, copy or frame |
| i: delivering one individual (copies, frames, cues, projection, its share of views and commit) | **today about 120 µs/s** (the pair average less sight); **about 30–40 after the planned exact steps** | COMBAT_PHASE: converting the remaining views and the exact sweep work "might reach 3–4×". BATTLE_LAWS (a)'s far-cap runs give a marginal 16–40 µs/s per dropped *far* pair (one run each), so far places may already cost less than the average |
| k: one crowd row, refreshed at 1 Hz with about half the cells changing | about 5 µs/s (assumed) | a primary-key update in place plus about 1 µs of RLS evaluation (the cue and copy tables), as for `seen_fighter_copy` and `combat_feed` (3.3 µs of WASM per event insert) |

**Per viewer (ms/s), against a budget of 1.4–1.7:**

| | C ≈ 200 in sight (in the battle), K = 48 | | C ≈ 60 (the edge, the 26–32 m ring), K ≈ 15 | |
|---|---|---|---|---|
| | i today (120) | i planned (30–40) | i today | i planned |
| Off (everyone individual) | 26 | 8.0–10 | 7.8 | 2.4–3.0 |
| N = 12 | 2.2 | 1.1–1.2 | 1.7 | 0.7–0.8 |
| **N = 16** | **2.7** | **1.3–1.4** | 2.2 | 0.8–1.0 |
| N = 24 | 3.7 | 1.6–1.8 | 3.3 | 1.1–1.4 |
| N = 32 | 4.7 | 1.9–2.2 | 4.3 | 1.4–1.7 |

**Reading.**
- **At today's i, no N fits the worst case.** Attention alone is not enough; the per-individual exact work (the remaining views onto tables, the sweep's exact items, docs/COMBAT_PHASE.md "Next") must land too.
- **With it, N = 16 fits** at C ≈ 200 with a little margin, N = 24 is at or just over the line, and N = 32 fails.
- **At the edge** (C ≈ 60) every N up to 24 fits once i is down.
- **The crowd's own cost is small.** Rows: 48 cells × 5 µs/s ≈ 0.24 ms/s per viewer, about 52 ms/s at 216. Sight: 0.4 ms/s per viewer at C = 200, because crowd sight runs at 1 Hz. Crowd sight at 5 Hz would cost 2 ms/s per viewer alone, more than the whole budget.

The model is an estimate, not a measurement. The fake-model battle (§5.2) measures i, s and k directly, and N follows from them: **N ≈ (1.5 ms/s − C × s₁ − K × k) / (i + s₅)**.

**Cell size.** Crowd rows per viewer in the 200-mind battle (below), beyond the N nearest within 48 m:

| Cell | N = 16: p50 / p90 / max | N = 24: p50 / p90 / max |
|---|---|---|
| 4 m | 29 / 70 / 83 | 24 / 68 / 80 |
| **6 m** | **24 / 50 / 63** | **19 / 49 / 60** |
| 8 m | 20 / 40 / 50 | 17 / 39 / 50 |

These counts are distance only, with no facing or cover, so they are upper bounds: the laptop's still at the battle's edge saw about 50 of 200. **6 m** keeps p90 near the 48-row cap with 2×2 merging beyond it. 4 m would show the crowd's shape better at about 40% more rows. The stills decide between them by eye (§5.1).

### 3.3 What the saved battles show

`attention_density.py` read the act trial's real-mind battle, read-only (`act-trial-20261121.tar.zst`, run `minds-atb1-off-055246`):
- 200 real minds, minutes 2–8;
- 84 one-second samples, 16,277 fighter-samples;
- positions replayed along each segment.

| Measure | p10 | p50 | p90 | max |
|---|---:|---:|---:|---:|
| Others within 3 m | 0 | 1 | 7 | 24 |
| Others within 8 m (the near tier's reach) | 1 | 4 | 34 | 89 |
| Others within 20 m | 2 | 14 | 111 | 174 |
| Others within 48 m (Cullet's day sight) | 10 | 57 | 169 | 196 |
| Open attacks aimed at one fighter | 0 | 0 | 1 | 3 |
| Creatures a think prompt listed (capped at 14) | 1 | 6 | 14 | 14 |
| Think prompt tokens | 4,363 | 4,733 | 6,106 | 11,210 |

- **The real-mind battle spreads out:** minds disengage (docs/FAST_LANE_WHY.md). The AI-graph fixture (`spawn_battle`, 200 within 7 m) is denser: about 90 in sight on the 10 m ring and about 160 for 216 viewers at 10 m (docs/BATTLE_LAWS.md, docs/COMBAT_PHASE.md).
- **Engagement overflow is small:** at most 3 attacks aimed at one fighter at once.

### 3.4 Data paths (AGENTS.md)

| Path | Rows read and written, indexes | Recipients | Frequency | Retained, growth |
|---|---|---|---|---|
| Attended set per character | module memory (`ATTENDING`, as the near tier's `Viewer::near`); reads the engagement set, `cue.actor`, `relation` by actor, family and membership by key, `attend_choice.actor` | none (authority working state) | players: each sweep (200 ms); AI: each evaluation slot (1 Hz, wakes, fight cadence) | none. A fresh instance recomputes it at the next sweep or slot (places reshuffle once; hold times are lost). It decides who is delivered, never what a copy holds, the frames' existing rule (docs/PERCEPTION.md, "Module memory") |
| `attend_choice` (new, private) | `id` pk, `actor` btree, `target` (0 for a kind), `kind`, `source` (player input, pin, Jev), `weight`, `until_ms`; at most 8 a character | owner only | player: on input (rate-limited like `human_gaze`, one change per 250 ms); mind: each Jev refresh (1–3 s) | ≤ 8 × characters; expired rows deleted by an `until_ms` range once a second, as `reveal` is |
| `seen_crowd` (new, public, RLS) | pk update in place; `viewer` btree | the one viewer | 1 Hz per viewer, changed cells only | ≤ 48 × viewers. Commitlog about 70–100 B a written row: at 216 viewers × about 24 changed cells a second, about 0.5 MB/s, against about 8.4 MB/s for the battle's base commitlog at 216 (docs/BATTLE_VIEWERS.md, commitlog growth). The copies it replaces write far more |
| Copies of crowd members | none: dropped from `perceived`, motion, fighter, doing and projection | – | – | fewer rows than today |
| A mind's scene | the attended plus crowd lines, built where `scene_json` is today | the mind service, as today | per deliberation request | no change |
| Jev state for a mind (§7) | a new **procedure** `mind_attention_state(actor)` returns it to the controller alone and writes nothing, like `mind_reach` | the calling mind service | 1–3 s per mind, only while C > N | none (a procedure's answer is not broadcast) |

**SpacetimeDB documentation consulted** (2026-11-22; every page shows version 2.0.0; the pinned server and crates are 2.14.1; the versioned-source readings are those of docs/BATTLE_VIEWERS.md at `v2.14.1` `a0bf6be`):
- [Row-level security](https://spacetimedb.com/docs/how-to/rls). "Row Level Security is an experimental, unstable feature … use Views instead." A `:sender` filter is bound to the requesting identity; RLS applies to event tables too; module owners bypass it. No per-row cost is stated. The project accepted RLS conditionally for the copy tables (gate case, kill switch, isolation proofs). `seen_crowd` takes the same safeguards (§5.3). In 2.14.1 a `viewer = :sender` equality is a search argument with delta-index pruning (about 1 µs a row, measured).
- [Views](https://spacetimedb.com/docs/functions/views/). "Per-user views require separate computation for each subscriber." That cost is why crowds are a table, not a view.
- [Event tables](https://spacetimedb.com/docs/tables/event-tables/). Rows are never kept in the client cache, and their inserts are still written to the commitlog. A crowd row is current state the client must have after a reconnect, so it is a regular table.
- [Performance](https://spacetimedb.com/docs/tables/performance/): "prefer indexed lookups over full table scans"; small, focused tables; private tables avoid synchronization. Hence `attend_choice` is private and narrow, and every read is by `actor` or primary key.
- [Indexes](https://spacetimedb.com/docs/tables/indexes/): B-tree, multi-column; a point lookup by value. Every new read is a single-column point or range read.
- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): initial rows, then updates; unsubscribing is asynchronous. The client switch is make-before-break, as for the copy tables.
- **Rollout.** Adding a table does not disconnect clients, but publishing a new RLS rule disconnects every client once (`ensure_disconnect_all_users`, BATTLE_VIEWERS Addendum 1). `seen_crowd` therefore goes in a play-test-free window, with a mind restart.

### 3.5 Questions for dev-box

dev-box owns the per-viewer views and copy tables. Each question states the assumption this note makes until it is answered.

1. **`perceived` as the attended set.** Can "attended" simply be `perceived` (crowd members get no `perceived` row), so that every copy, tier, cue and frame follows without a second set? Which readers assume `perceived` means everyone in sight: `look.rs`'s relook, offers, aimed-act checks, `heard`, `kept_sweep`? *Assumed: yes, with those readers moved to the sight set where they need it.*
2. **The cost of one individual today and after the planned steps.** Do you have the L2 split of a pair's cost into near-tier and far-tier pairs at 16 viewers? The far-cap runs suggest a dropped far pair saves 16–40 µs/s against the 130 average. *Assumed: i = 120 today and 30–40 after the remaining views move to tables (§3.2). The far split would raise the usable N.*
3. **Promotion and demotion churn.** A promotion inserts 3–5 copies; a demotion deletes them. Is it cheaper to keep a demoted creature's copies through a grace period, hidden by a flag, than to re-insert them? Is a tier flip's measured cost a fair proxy? *Assumed: insert and delete, with `attend_hold_ms` 1,000 damping churn to a few changes per viewer a second in a battle.*
4. **Budgets.** Should crowd rows share the frames' scene-row budget (`SCENE_ROWS_PER_S`, the 250-row floor) and the cue row cap, or have their own? *Assumed: their own small budget (48 rows per viewer per second at most), outside the frames'.*
5. **`seen_crowd`'s shape.** Is the primary key `key(viewer character, cell)` with in-place update the right choice (the `seen_fighter_copy` lesson)? Is about 70 B a row acceptable to the laptop, or should centroid and spread be quantized to `i16`? *Assumed: pk update, `f32` positions.*
6. **The RLS publish.** Can `seen_crowd`'s rule ride the next planned disconnect window, with other rule changes, rather than cost its own? *Assumed: its own window, before any play-test with the law on.*
7. **Projection for crowd members.** Are there paths that iterate `projected` by body and would break when crowd members have no projection, for example `look.rs` relooking every viewer's row of one body? *Assumed: none that cannot read the sight set.*
8. **The engagement set for AI viewers.** `frame::engaged_of` is computed for humans only. Extending it to every character with the law on means the TARGETS map serves AI too. Any objection on cost at 200 fighters? *Assumed: cheap, since it is already maintained per actor and the change is who it reports to.*
9. **`human_attend`.** Shape `human_attend(targets: Vec<u32>, point: Option<(f32, f32)>)`, at most 4 pins plus one focus, one change per 250 ms like `human_gaze`, refused for another's character. Does that fit the client's input path? *Assumed: yes.*

## 4. Minds' prompts and memory

**They learn only the individuals they attended to.** A mind's scene lists the attended; its experiences name the attended; its memory graph gets nodes only for them. Everything else reaches it as crowd facts: counts, directions, deeds by number.

**Is that consistent with "minds know only what they perceive"?** Yes, and stricter than today.
- **Attention narrows perception; it never adds to it.** Every attended creature is in sight by the existing sight rule, and so is every crowd member. Nothing reaches a mind that its character could not perceive.
- **Recognising someone in a crowd is perception, done by the law.** It happens only where the character can make the person out, and its result is told as a reason ("you pick out …"). Today the mind would have been told about that person anyway, because today everyone in sight is an individual.
- **The Jev attention layer sees the character's current field** (§7). That field holds the attended, a few unattended candidates the character can make out, and the crowds. Its answers only choose places. Its state never enters a prompt or memory: only the picks do, and a pick is just "this one is attended".
- **The same holds for players.** Their screen shows the attended and the impostor crowd; their character's lived memory (`mind/lived.rs`) is built from the same experience lines.

**Today's asymmetry goes away.** A mind's prompt already lists only the 14 nearest, while its graph and its experiences cover everyone in sight. The prompt, the graph and memory would now agree on one attended set, the same for a player's character.

**Prompt cost.** At N = 16 a crowded scene lists 16 instead of 14 creatures: about +2 × 85 tokens on a 4,700-token think prompt (+4%). The crowd lines add about 30–60 tokens each, a few per scene. At N = 24 it would be about +850 tokens (+18%) in crowds.

**Emergent consequences** (none scripted; each follows from the law being the same for everyone):
- **Ambush and flanking.** While a fighter's places are full of the fight in front, someone walking round the edge is crowd until they wind up at it, and from that tick they are attended ((a)). An attacker who gets close before striking is noticed late by a character whose attention was elsewhere. A character who keeps a place free (a cue on "someone behind me", a player's pin) is harder to surprise.
- **Crowds as cover.** A thief in a market crowd is one of "about 40 people" to everyone who has not picked them out. Whoever watches for them (a cue on the person, a stance about thieves with a kind-and-deed cue, a guard's pin) picks them out.
- **Distraction.** A loud fight draws salience ((c): fighting, fallen). Something quieter elsewhere goes to the crowd.
- **Being known.** People who matter to many (family, those with strong feelings attached) are attended by many and remembered individually. Strangers in a battle are remembered as "the battle at the ford: about 120 fought, many fell", which also compresses memory.
- **Searching.** A parent looking for a child (family, (b)) picks them out of a crowd as soon as they can be made out. A stranger looking for "the one with the red cloak" can only search by moving closer, unless their cue describes something visible.
- **Fairness to players.** A player's character is subject to the same law: an AI ambusher can hide in a crowd from the player, and a player can hide from AI minds the same way.

## 5. Tests

### 5.1 Stills for the owner (the laptop renders)

The question for the owner: does a 200-fighter battle still read as a battle at N individuals plus an impostor crowd? Nothing is built, so the stills use a mock: `far_cap` = N for the individuals (it keeps the engaged and then the nearest, which is (a) and (c) by distance without (b)), and a client-side crowd from an owner SQL read.

**One shot per cell:**

| | everyone individual (law off) | N = 32 + crowd | N = 16 + crowd | N = 16, no crowd |
|---|---|---|---|---|
| **Middle band, at the edge** (26 m south, facing north) | 1 | 2 | 3 | 4 |
| **Far band, at the edge** | 5 | 6 | 7 | 8 |
| **Middle band, inside** (10 m ring, the fight round the player) | 9 | 10 | 11 | – |

- **World:** Cullet (`LIVING_SEED=cullet`), a fresh world from current main with all battle laws off except `far_cap`, by the world's day (shots between 10:00 and 15:00 world time).
- **Staging:**

  ```
  battle_viewers.py --viewers 1 --fighters 200 --sides 2 --ring 26,26
    --paused-placement --battle-after-placing --keep-alive 0.5
    --seconds 600 --law far_cap=N
  ```

  - Use `--ring 10,10` for the "inside" row. Leave the law out for "off".
  - `--sides 2` keeps residents alive (docs/BATTLE_LAWS.md §1).
  - The one viewer is the game client's own player with its own identity, joined, then `place_at` the battle's centre (the arrival less 20 m, as `spawn_battle` takes it) plus 26 m (or 10 m) due south, facing north.
- **Camera:** north-up (the default bearing), the play camera's own Middle and Far zoom bands (docs/CAMERA.md), no free camera, the battle's centre on the screen's vertical middle.
- **Timing:** 20 s after `spawn_battle` (about 180 alive), paused for the shot (`set_paused true`). Each arm is its own run at the same moment of its own run, as BATTLE_LAWS' stills were.
- **The mock crowd** (shots 2, 3, 6, 7, 10, 11):
  - **Who:** while paused, read `body` positions as the owner and take every creature within the viewer's sight radius and field (from its `my_senses` row) that is not in `seen_bodies`. Cover is ignored in the mock; the JSON says so.
  - **Cells:** bin them into **6 m** world-aligned cells, with each cell's count, centroid and spread.
  - **How it is drawn:** `count` generic figures per cell, no nameplates, scattered in the cell's spread ellipse round its centroid, in a fighting idle when the cell's members are within 2 m of another fighter, else standing.
  - **Second variant:** each cell as one translucent disc sized by count (BATTLE_LAWS' mock), as `-discs`, to judge which reads better.
  - **Cell size:** additionally shot 3 at 4 m and 8 m cells (3a, 3b), to judge cell size by eye.
- **Output:** 1920×1080 PNG, UI hidden except nameplates, named `attention-<middle|far|inside>-n<off|32|16>-<crowd|discs|nocrowd>[-4m|-8m].png`. Beside each, a JSON with:
  - the world time, the fighters alive;
  - `seen_bodies` count (individuals drawn);
  - the crowd members and cells drawn, and the cell size;
  - the `far_cap` value;
  - the commit and module hash.
- **What the owner judges:**
  - **At Middle:** is one's own fight whole at 16, and does the crowd read as the rest of the battle?
  - **At Far:** does the battle still look like 200 at 16 and 32, and do the figures or the discs read better?
  - **Inside:** is a 16-place melee enough, with the rest as crowd figures within a few metres?

### 5.2 One fake-model battle: tick and delivery (once built)

On the Spark, after the law and `seen_crowd` are built behind the law (off by default):

- **Server and lock.** Its own private SpacetimeDB 2.14.1 container, pinned to the X925 cores (5–9, 15–19), with `battle.lock` held: measurements keep the lock. Quiet start, and a redo only if the load exceeds 8.
- **Fixture.** `battle_viewers.py` with 200 fighters in 2 sides, `--keep-fighters 1` (a sustained 200), the keep-alive, paused placement, the battle after placing, the copy tables on (the shipped defaults).
- **Minds.** The fighters' minds on the mind service with verify-llm's fake model, including a fake Jev endpoint that answers attention questions. This needs a `--minds fake` option in `battle_viewers.py`, or `battle_diag.py`'s minded fighters with viewers added; whichever is smaller to build.
- **Viewers:** 216 `gate-load` players on the 26–32 m ring, and 16 on the 10 m ring, subscribed to `seen_crowd` with the law on.
- **Arms** (each a `law_override`, no reinstall): `attend_n` 0 (today), 16, 24, with 6 m cells, the crowd at 1 Hz and Jev attention off. One more arm: 16 with fake Jev on.
- **Runs:** two per arm, interleaved; 20 s warm-up, a 60 s window; L0 and one L1 run of each.
- **Measured:**
  - ticks/s, late slots, the tick's p50/p99;
  - database-thread CPU, views and subscription-evaluation CPU;
  - **per viewer and per attended individual** (the 0-viewer arm subtracted): this gives i, s₁ and k for §3.2's formula;
  - rows/s and kB/s per player by table, `seen_crowd` included;
  - commitlog MB/s;
  - near and far freshness (p50/p90/p95);
  - promotions and demotions per viewer-second;
  - **(a) latency:** from a windup aimed at a viewer to the attacker's first copy row (should be the same tick);
  - WASM memory;
  - the minds' prompt tokens (from the fake journals);
  - fake Jev calls/s and in-flight count.
- **Pass:** at 216 on the 26–32 m ring, 60 ticks/s with the whole tick call ≤ 600 ms/s at the chosen N; at 16 on the 10 m ring, no regression against `attend_n` 0. If it fails, the measured i says which N would pass.

### 5.3 Verification plan

Run the surfaces the change touches, and `maintain-verification-skill` on each in the same change, because tables, reducers, the mind protocol and UI controls change shape. Free tiers only.

| Surface | What it drives | New scenes or cases |
|---|---|---|
| verify-core | the law on a scratch world | `attention_slots`: engaged and addressing always in, past N; the near tier; (b) by a cue, a relation, family and a pin, with its line; (c) by salience; the hold time; `attend_n` 0 identical to main tick by tick (`det_compare`). `attention_ambush`: a fighter in a crowd winds up at a character whose places are full, and is attended in the same tick. `attention_fold`: crowd deeds fold into crowd lines, and the attended are named. Graphs: `count` counts the crowd, `nearest` stays attended |
| verify-client | `seen_crowd`'s isolation | `crowd_tables.py`, on `cues.py` and `motion_tables.py`'s harness: A, B, C and anonymous; subscribe by name, subscribe-all, `SELECT * FROM *`, peeking by identity; the kill switch (law off: every crowd row gone in one tick). A negative build without the rule must fail. The gate case `crowd_tables`; `RLS_TABLES` and the owner guard in `drive.py`; `copy_privacy` at battle density with `--crowd` |
| verify-player | `human_attend` | permissions (only one's own character), bounds (4 pins), rate limit, a pin promotes and a crowd click promotes, an aimed act at an unattended id refused with its reason |
| verify-minds | the mind with the fake model | `attention-scene`: the scene lists the attended and crowd lines, and the prompt has no crowd ids. `attention-jev`: one request per mind with one state and its own questions, picks written through `mind_attend`, the authority not waiting (a slow fake Jev leaves the plain rule in force), no calls off stage or while C ≤ N |
| verify-llm | the fake Jev endpoint | the attention purpose journaled, `cost_usd` null without a prices file, a timeout taking the fallback |
| verify-knowledge | memory | a crowd member never becomes a person node; a promoted one does, from that line on; a crowd's deaths are recalled as crowd events |
| verify-ui (laptop) | the client | the impostor crowd drawn from `seen_crowd`, click to promote, the reason marker, make-before-break when the law flips |

## 6. Default, risks and the recommended N

**Default: off** (`attend_n` 0). It goes on per world by its `law_override` row, first in a battle world after §5.2 passes, then in Cullet after a play-test. A new perception law in play is the owner's call.

**Recommended: N = 16,** with `attend_chosen_max` 4, 6 m crowd cells at 1 Hz, at most 48 cells.
- **Cost:** it is the only N in §3.2 that fits the per-viewer budget in the worst case (C ≈ 200 in sight), and then only after the planned exact steps.
- **Prompts:** it keeps minds' prompts near today's 14.
- **Melee:** it holds the engaged, up to 4 chosen, and about the 12 nearest in a melee.
- **If §5.2 measures i at 30 µs/s or less,** 24 becomes affordable, and the stills say whether it is worth it.

**Risks.**
- **The cost model is an estimate.** If i stays near today's 120 µs/s, attention alone does not reach the contract at any N worth playing. The exact steps are a precondition, not an option.
- **Players see fewer individuals.** Far individuals become crowd figures: no names, health or exact poses beyond N. A newcomer sees a battle as a crowd until they pick people out. The stills are there to judge this.
- **A reversed ruling.** It reverses the owner's 2026-11-10 rule: crowd members get no first sights, no `familiar` rows and no named fight lines. Trials that counted first sights (docs/STRANGERS.md) are not comparable across the switch; every batch record must state it (as other switches are).
- **Places churn.** Changes cost copies. The 1 s hold damps it; §5.2 counts it.
- **RLS is experimental.** One more RLS table, with the copy tables' safeguards and a disconnect at publish.
- **Behaviour changes for AI graphs.** `sees` and targets read only the attended. A graph that hunted the nearest wolf at 40 m with 30 people around would not see it unless it is salient (a wolf is) or chosen (a cue). `det_compare` proves "off equals main", not that every graph still does what its author meant; verify-core's scenes cover the common conditions.
- **The Jev layer's load** (§7) is large in battles. It stays a separate switch, and the law works without it.

## 7. Jev as the mind's attention layer

The owner (2026-11-22): "this might be an interesting use of the decision models, you can put many queries in them to run in parallel on the same input that in this case would be what's visible to the player. we could extend the same to a more generalized layer of perception in the mind about attention. worth exploring imo". Design only.

### 7.1 Shape

**One TypeSafe `systemone` request per mind, never mixing minds.** It is MIND_HARNESS §6's batching: one state, many questions, requests concurrent, one in flight per mind, a newer state coalescing an unsent one.

```json
{"model": "jev-1.14.0",
 "state": {
   "note": "Everything here is this character's own perception, ties and concerns.",
   "you": {"doing": "fighting", "body": "hurt", "facing": "north"},
   "your_people": [{"h": "c3", "tie": "your partner"}],
   "your_concerns": ["the one who took my fish (watch: 'him, if he comes back')", "project: get the boat built"],
   "attended": [{"h": "c1", "who": "a stranger", "form": "man", "dir": "north", "dist": "within reach", "visibly": "strike at you, recovering"}, "…"],
   "also_in_sight": [{"h": "c17", "who": "Bram", "dir": "east", "dist": "a stone's throw", "visibly": "strike at c3, winding up"}, "…"],
   "crowds": [{"dir": "northeast", "dist": "far", "about": 40, "visibly": "most fighting"}]
 },
 "questions": {
   "q_cue_1": {"type": "choice", "instructions": "Who here, if anyone, is what you watch for: 'him, if he comes back'?", "options": ["c1", "…", "c22", "no one"]},
   "q_people": {"type": "choice", "instructions": "Is anyone here acting on someone in `your_people`? Who?", "options": ["…", "no one"]},
   "q_matter": {"type": "choice", "instructions": "Who here is about to matter to you?", "options": ["…", "no one"]}
 }}
```

- **The state is what this mind's character perceives now, and nothing else.**
  - It comes from a new procedure `mind_attention_state(actor)`: returned to the controller alone and written nowhere, like `mind_reach`.
  - It holds: the attended (≤ N); up to 8–14 unattended candidates it can make out, chosen by salience; its crowds; and its own ties and concerns, which the authority already holds (cues with their `why`, relations, family, community, projects as projected).
  - Distances and counts are words, because Jev is weak at numbers (docs.typesafe.ai "model jaggedness"; MIND_HARNESS §6).
  - About 30 creatures at most. Handles (`c1`…) are per request and are not ids the mind keeps.
- **Questions are `choice` over the state's handles plus "no one".** The answer is a distribution. Picks are the handles at or above `jev.pick_above` (to be tuned in replay), up to the (b) quota.

### 7.2 Where the questions come from

**The mind's own content, in one neutral frame.** We write no tactic or role question.
- **Each cue's `why`** (the mind's words, ≤ 160 characters; docs/ATTENTION.md). Wrapped as "Who here, if anyone, is what you watch for: '<why>'?". This extends cues past their typed fields: "someone carrying fish" cannot be typed, but Jev can read it against what is visibly going on. A cue's typed match stays the authority's exact rule and is not re-asked.
- **Relations and family:** "Is anyone here acting on someone in `your_people`? Who?". It is a question about the character's own ties, and it names no deed to look for.
- **Stances and projects, by their own text:** "Who here, if anyone, bears on this: '<the stance or project in the mind's words>'?". At most 3, the newest.
- **One general question the rules cannot answer by distance:** "Who here is about to matter to you?". Novelty, approach and fighting are already (c)'s, so no general question repeats them.

**What earlier work settled and this keeps.**
- **docs/ATTENTION.md:**
  - cues are typed, at most 8, each serving a stance, project or goal;
  - the prompt's examples name no one, tested by `cue_examples_name_no_one`;
  - a cue's `why` is quoted verbatim;
  - a played character keeps no cues.

  Jev questions inherit all of it: they exist only where a mind wrote a concern, and a played character gets none.
- **docs/JEV_BEHAVIOR_RESEARCH.md:**
  - questions stay tied to the character's goals and experience, so actors do not become one prescribed fighter;
  - no waiting inside a guard;
  - one shared context per actor, never several actors in one prompt;
  - pending, valid, expired and failed are distinct states;
  - answers bind to actor, revision and snapshot time, and stale or out-of-order answers are rejected;
  - one active batch per actor, with newer snapshots coalesced;
  - no claimed joint probabilities.

  Here: choice questions are independent, and their picks fill places; they are not multiplied into anything.

### 7.3 What the answers do

- **They fill slot class (b) for minds as cached rows, never waited on.**
  - The mind writes picks through a new reducer `mind_attend(actor, picks)`, only the controller may call it, as `mind_judged`.
  - The picks become `attend_choice` rows with source Jev, the answer's probability as weight, and `until_ms` = the snapshot time + 5 s.
  - At each slot the authority reads them by `actor` with the plain rule's (b): exact cue matches first, then Jev picks by weight, then ties.
  - Expired, missing or failed answers leave the plain rule in force. The tick never waits for Jev; nothing is asked from inside a reducer.
- **Beyond battle (design only):**
  - **Which percepts are worth a thought.** A percept involving a Jev pick passes the rethink gate as cues' reasons do (`rethink.json` `urgent`), so attention and the gate agree on what matters. That reuses the gate's state and adds no question.
  - **Memory salience.** Experiences involving people a mind attended by choice ((b), not just (a) or (c)) are weighted up at consolidation. A consolidation-time question ("which of these will you remember") would be a separate experiment.

### 7.4 It stays within the 2026-11-09 rule

The owner decided on 2026-11-09 that Jev is not real-time and never drives moment-to-moment choices (MIND_HARNESS §6). Attention stays inside that rule:
- **The cadence is slow.** It refreshes every 1–3 s, not per tick.
- **It shapes only who is perceived as an individual, never what is done.** It picks no act, branch, target or timing.
- **Every threat is outside its reach.** Threats, address and the near tier are the authority's (a), the same tick.
- **The one indirect effect is bounded and the same for players.** A graph can only target the attended, so Jev can change which *far* individual a graph could take, through at most the (b) quota. A player's attention picks do the same for a player's command graph.

### 7.5 Cost and load

| | Town (Cullet, a mind on stage) | 200-fighter battle |
|---|---|---|
| Creatures in sight | about 6–7 mean, 16 max (docs/ATTENTION.md, Cullet's daily life) | p50 57, p90 169 within 48 m (§3.3, distance only) |
| When it calls | only while C > N (markets, gatherings), on a change of candidates, at most every 3 s, and at least every 30 s while it lasts | while C > N (most fighters), every 1–3 s |
| Off stage (LOD: no player in the scene, docs/MIND_HARNESS.md §1) | 0 | 0 (a battle with players is on stage) |
| Calls per character-minute | ≈ 0 on most days, ≤ 2 in a crowd | 20–60 |
| Input tokens per request | about 2,400–2,700 (2,700 used for sizing): a 30-creature state at about 120 characters an entry (`attention_density.py`: p50 117, p90 144 over 19,524 battle-scene entries), about 1,500 characters of self, ties, concerns and crowds, and 4–6 questions of about 400 characters, at about 0.33–0.4 tokens a character (the gate's replay journals: tokens ≈ 0.33 × state characters plus the questions, so the state is counted once a request, not once a question) | the same |
| Input tokens per character-hour | ≈ 0 – 0.3 M | 3.2–9.7 M |
| Against the rethink gate (about 47 calls × 1,500 tokens ≈ 70k tokens per person-hour, MIND_HARNESS §6) | ≤ 5× | 45–140× per character |
| A whole battle-hour | – | 0.65–1.9 G tokens: **about 5–14 times the rethink gate for 2,000 people for an hour** |
| Requests a second, 200 characters | ≈ 0 | 67–200 |
| Latency (p50 / p95) | 136–174 / 174–240 ms (dev-box, `judged_fight.py`); 135 / 171 ms (rethink replay); 138 / 202 ms (gate-quality replay, read here) | the same; the answer's age when used is latency plus half the period, about 0.6–1.7 s, well inside its 5 s life |

- **Price.** Jev bills input tokens only. Its price is not committed; multiply these token counts by the price in the local prices file (`LIVING_PRICES`, `living/configs/prices.local.json` or `~/.config/slop-living/prices.local.json`; shape in `living/configs/prices.example.json`). Journals record `cost_usd` from it, or null without it.
- **Throughput.** TypeSafe's rate and concurrency limits are not recorded in this repository. MIND_HARNESS §6 sized the gate at 2,000 people as 26 requests a second "on TypeSafe's rate limits"; one battle with attention is 67–200. In-flight load is modest: at about 150 ms a call and a period of 1 s or more, 200 minds need about 30 requests in flight. Before any live battle with Jev attention, ask the provider for the limits, and size the cadence to them (3 s halves the load against 1.5 s).
- **Levers, in order:** call only while C > N; skip a refresh when the candidates did not change; a longer period; fewer candidates in the state (8 instead of 14 saves about 10% of the tokens).

### 7.6 Players

A player's (b) comes from the player's own input: target, focus, hover, pins and the client's crowd clicks, through `human_attend`. **Never from a model.** It is the same rule with a different controller, as cues are for minds and not for played characters.

### 7.7 Test: replay first, then a small paid trial

Use the `rethink-replay` pattern (`living-mind rethink-replay`, MIND_HARNESS §6), as `fast-replay` did on `battle-frame`.

1. **`living-mind attention-replay --arm rule|jev --n 16 --out FILE RUN_DIR…`** rebuilds each mind's field at 1 Hz from saved runs:
   - positions from `combat-samples.jsonl.gz` (sight approximated by distance and facing; cover ignored, and said so);
   - ties from `mind_rows`;
   - cues from the saved `cue` rows.

   Inputs: the act trial's battle (`minds-atb1-off/on`, 200 real minds), and a town run with a crowd (a market or arrival scene from the strangers trials).
2. **Three pickers on the same fields:**
   - **distance:** (a) and nearest, `far_cap`'s rule;
   - **rule:** (a), cues and named people, then salience;
   - **Jev:** the rule, with Jev's picks in (b).
3. **Scored against what the mind actually acted on:** the creatures named by its acts (`act_attempts.jsonl`), its skill uses (`skill-uses.json`), its speech and its compiled graphs' targets within the next 10–30 s. Reported:
   - the share of those already attended at decision time (recall at N);
   - how much (b) changed it;
   - churn per minute.

   A blind check on a sample: is the pick "someone this character would plausibly keep track of", given its ties and concerns?
4. **Free first:** prompts only (token counts per request, the state's size at 30 creatures), and the fake Jev through the call path.
5. **The paid part only after the general coordinator approves:** a few hundred states (for example 300 from the battle and 200 from the town), each journaled, with a spend watcher. **The plain rule is the baseline Jev must beat** on recall at N with no more churn. If it does not, attention stays on the plain rule, and Jev keeps its place at the rethink gate.

## 8. Open decisions for the owner

1. **Replace the 2026-11-10 "no attention cap" ruling with this law** (the same for players and minds), and retire `far_cap`?
2. **N:** recommended 16, judged on the stills (§5.1) and the fake-model battle (§5.2); 24 if the measured cost allows.
3. **The crowd's look:** impostor figures or discs; 6 m or 4 m cells.
4. **Memory semantics:** crowd members get no first sight, no `familiar` row and no named fight line, only crowd lines. Accept this, given that trials across the switch are not comparable?
5. **Players' choice:** clicking a crowd figure promotes it, pins (up to 4) stand in for a mind's relations, and the community stands in for a party. Is that the player's side of (b)?
6. **Jev attention:** explore it through replay (free), then a small paid replay after the coordinator's approval. Any live battle use waits on the provider's limits and the owner's word on spend at scale.

## Evidence

- `living/tools/attention_density.py` (this branch) on `act-trial-20261121.tar.zst`, run `minds-atb1-off-055246` (copied out of `~/slop-evidence` to the scratchpad; read-only, pinned to CPUs 0–4 and 10–14): every density, cell and scene figure in §3.2–§3.3 and §7.5.
- `~/slop-evidence/gate-quality-20261112/out/replay-*-jev.journal` (read-only): Jev tokens against state size (1,198 rethink requests: tokens ≈ 0.33 × state characters + a constant; p50 1,555 tokens; latency p50 138 ms, p95 202 ms).
- Measured costs quoted from docs/COMBAT_PHASE.md, docs/BATTLE_LAWS.md, docs/BATTLE_VIEWERS.md, docs/ATTENTION.md, docs/MIND_HARNESS.md; code read at `origin/main` `8384dc77` (`perception.rs` `sweep_one` and `far_cap`, `frame.rs` `NEAR_MAX` and `engaged_of`, `perceive.rs` `scene_json`, `brain.rs` `noticed`, `attention.rs`, `mind.rs` `mind_reach`).
