# Attention cues: what a mind asks to be woken by (2026-11-12)

Status: **on main since 2b163773, off by default (the `cues_on` law).** The design was approved by the general coordinator on 2026-11-12, who called "a cue match asks for a thought" the right single engine change. `cue-cache` (2026-11-12) shares each observer's answer about each target within a transaction and makes the check interval a law (`cue_check_s`). Its cost is measured below: the cache cuts the cues' own work by 16–35%, and at 216 characters with cues on 60 Hz still does not hold. The bar for default-on is in [Cost](#the-bar-for-default-on).

**The gap** (docs/TRIALS.md, strangers stage 2). Aldous's life says arrivals are written in the book, yet he never thought with the newcomer in view. A first sight has salience 0.45. Even a percept at 0.6 or above only wakes the body's graph (`perceive.rs`, `percept`). A thought is asked for only by fixed callers: being attacked, offers, bodily alarms, the plan ending, a quiet moment (`request_deliberation`). Nothing let a mind say "this, when I see it, is worth a thought".

**The mechanism.** When a mind writes or revises a stance, goal or project, it may also write what in the world should make it think about it: typed **cues** over facts its perception already reports. The authority matches them by type. A match asks for a thought and, once that request is taken, writes a percept quoting the mind's own reason. We write no cue for anyone, and the prompt's examples name no one, no duty and no situation.

## Cue schema

Every field present must hold for the same perceived thing.

| Field | Values | Matched against |
|---|---|---|
| `for` | a stance key, `project:<key>`, or `goal:<its words>` | its lifetime |
| `who` | a person or creature id; `"unknown"` (a person whose name I do not know, `perception::knows_name`); a creature kind (`wolf`, `person`) | the scene's creatures. Someone too far away to make out (`regard().far`) matches nothing, by id or by kind |
| `doing` | what they are visibly doing: a skill's name, its label, or a kind word (`melee`, `missile`) | `perception::visibly`, the row COMBAT_MIND 3.2's `doing` condition reads |
| `phase` | `living_rules::doing::Phase`'s words (`winding up`, `about to release`, `releasing`, …) | the same `visibly` |
| `thing` | a resource or structure kind (`fishing_spot`, `storage`; a structure also counts by its kind's `like`) | the scene's resources and structures |
| `at` | one of the mind's own places, with `within` (at most 48 m, default 20) | the matched thing's position |
| `near_me` | metres | the matched thing's distance |
| `why` | up to 160 characters, the mind's words | quoted in the line a match gives |

- **Bounds.** A cue has at most one of `who`/`thing`. `doing` and `phase` need `who`. A cue with only `at` fires when the character is at that place. A character keeps at most 8 cues: the newest 8 the projection sends.
- **Refusals.** `mind.rs` `cue_refusal` refuses:
  - a `for` that serves no stance, project or goal;
  - nothing to watch for;
  - a deed with no doer;
  - an id never met (no `familiar` or `relation` row, and the name unknown);
  - an unknown creature kind, thing kind, phase or place.

  A refused cue is kept as a row with its reason in `refused` and never matched. The next prompt lists it with the reason, and the inspector shows it.
- **`doing` is not checked against a list.** `visibly`'s `is` accepts a skill's name, its label or a kind word, as the graph's `doing` condition does.

## Storage and write path

- **Memory is the source.** A cue is a property of the concept it serves: `notice`, a JSON list on the stance's `stance:<key>`, the project's `project:<key>`, or a `goal:<key>` concept.
  - The cues a reply names for a concept replace that concept's cues. An entry naming only `for` clears them.
  - The cues live, merge and fade with their concept.
  - The compile step keeps the think decision's `notice`, with its thought, speech, stances and places (`mind.rs`, `keep`). The first build lost it there; the minds scene caught that.
- **The projection.** `Store::projection` returns:
  - a stance's cues while the stance is held;
  - a project's while it is pursued;
  - a goal's while the persona still has that goal (`memory::same_goal`: the same key, or one the start of the other).

  `Minds::project` sends the full set as `MindUpdate.cues: Option<Vec<CueIn>>`, which replaces the actor's set. Without a store, no cues are projected (`None`).
- **The private table `cue`** (`tables.rs`):
  - `id` (primary key, auto-increment) and `actor` (btree);
  - the typed fields as plain columns;
  - `refused`;
  - `fired: Vec<CueFire>` (subject and time, at most 8), `fires`, `set_ms`, `source`.

  An unchanged cue keeps its row, its fires and its cooldowns. The table is deleted at death (`act::die`).
- **Who keeps cues.** A character a person plays keeps none: `mind_update` writes an empty set for it, whoever calls. Its eyes are its player's. Player memory (`lived.rs`) drops a reply's `notice` too.
- **Why a new table.** It is a new access pattern, read once a second per character with the law on. A new table is a safe automatic migration. No public or hot row changes. Proved in place: main `49dfc2cd`'s module was published, then this branch's over it with data kept. The log said "Creating table `cue`"; characters, experiences and the clock went on.

## Matching on the tick

- **Where.** `brain.rs`, `Ev::cues`, called first in `noticed()`. It runs on the character's own evaluations (its 1 Hz slot, wakes, the fight cadence), and at most once a second per AI character, while the law holds.
- **What it reads:**
  - one indexed range, `cue.actor`;
  - the actor's `place` rows only if a cue has `at`;
  - the scene the evaluation builds anyway (creatures, resources, structures).

  For persons it reads `knows_name` and `regard` once per person a check, and only when a cue names a person. It reads `visibly` only when a cue has `doing` or `phase`. There is no text matching and no inference.
- **When a cue fires.** A cue fires when a thing *begins* to match. The edge is a thread-local set of the (cue, thing) pairs held since they fired. It is lost on a module update; the durable cooldown then holds.
- **What a fire does.**
  1. It asks the mind to think (`perceive::ask_to_think`), with the line as the reason.
  2. Only if that request is taken does it record the fire (`fired`, `fires`) and write one `experience` row, kind `noticed`, salience 0.65, in the observer's own labels, quoting the `why` verbatim: `You notice a stranger, 2 tiles southeast: you watch for this ("<why>").`
  3. A request refused within the species' `think_min_s` (20 s for people) is tried again at the next check. In the first build the fire was recorded without the thought; the minds scene caught that.
- **The rethink gate passes a cue's reason.** `living/configs/rethink.json` `urgent` holds `": you watch for this ("`. Removing that entry gates cues, for an arm.

## Laws

| Law | Default | Meaning |
|---|---|---|
| `cues_on` | `false` | Cues are matched, and minds are offered the `notice` field and `# What you watch for`. Off: nothing is matched, the prompt says nothing of cues, a reply's `notice` is not kept, and stored cues stay inert. Independent of `stranger_by_name`. |
| `cue_cooldown_s` | `600` (0–86,400) | A cue fires at most once per thing it matched within this many seconds. |
| `cue_gap_s` | `60` (0–3,600) | A character's cues bring it to think at most once in this many seconds. Things that begin to match together go in one line. |
| `cue_check_s` | `1.0` (0.1–60) | How often a character's cues are checked against what it perceives. A world may trade freshness for cost: a thing that begins to match is noticed up to this late. |
| `regard_cache` | `true` | What each observer makes of each target (name known, the `perceived_of` answer) is worked out once per transaction and shared by everyone who asks ([Shared answers](#shared-answers)). Off: each asker works it out afresh. The answers are the same either way; the switch exists to measure the cache. |
| `regard_cache_check` | `false` | Diagnostic: every shared answer is also worked out afresh and compared; a difference is logged and counted. It costs both, and is for verification only. |

The first-sight laws (`first_sight_thinks`, `first_sight_gap_s`) are a separate attention law: a first sight of someone one cannot place asks one thought ([First sight](FIRST_SIGHT.md)). A cue and a first sight of the same person in one look are one request.

All are script laws (`skills.rhai`, `script.rs` `Laws`), switched at runtime by `set_world_law`, and described by `law_about`.

## What the prompt says

With the law on (`prompts.rs`, `notice_field`):
- The think and consolidate replies gain an optional `"notice": [ … ]`. Its schema gives the fields, the phase words and the cooldown and gap in words. Its three examples are placeholders: a creature kind, a person id with a skill, a goal with a thing at a place.
- A unit test (`cue_examples_name_no_one`) fails if the field names a stranger, a newcomer, arrival, a visitor, a guard, a keeper, a gate, a door, a role, a duty, a ledger or a book, or if an example watches for people one does not know.
- The think prompt gains `# What you watch for` (`cue_line`). It lists each cue in the mind's words, how often it made the person think and when, or why the world does not watch for it.

## Use by COMBAT_MIND 3.2 and 3.3

- **3.2 (built, on main).** `doing` and `phase` read `perception::visibly`, the row the graph's `doing` condition reads, under the same sight. A thought takes 5–40 s, so cues are not for timing a windup: timing stays with graph conditions. A cue makes the slow mind (or the §3.4 fast lane, once built) notice what it chose to look for, for example "the one who throws fire, winding up", and then prepare a routine.
- **3.3.** Movement intents consume no cues. A cue-driven thought may choose them, and `at` ties a watch to a place.

## Shared answers

Cues, scene labels and the far label, far handles, first sights, graph filters and told lines all ask the same two questions about an observer and a target: does the observer know the target's name, and what does the `perceived_of` law let it make of them (its name, health, whether they are too far away to make out)? Since `cue-cache` each transaction answers each question once per observer and target and shares the answer (`perception.rs`, `with_answers`):

- **What is shared:** `knows_name` per pair; the observer's know-how as the law reads it; the law's answer per pair, distance in whole metres (when the law reads distance) and time. The distance is still read fresh each time (two body lookups), so a body that moved within a transaction gets the answer for where it is.
- **What empties it:** every write that can change an answer bumps a generation (`answers_changed`): an acquaintance, membership, know-how or reveal written or removed, a new character, new parents. A new transaction starts empty.
- **Exactness:** under `regard_cache_check` every shared answer is compared with a fresh one. `scenes.py regard_check` drives first sights in a crowd, the stranger filter and the far label, cues, told lines and an introduction during a fight, and requires at least 1,000 comparisons with none differing.
- **Not shared:** the far handle rows themselves (`far::handle_for` writes them); the handles take the shared "can I make them out" answer.

## Cost

### The bar for default-on

**Cues stay off by default.** To make them default-on, show the immediate gate of docs/PERFORMANCE_CONTRACT.md holding **with cues on**: 216 active characters for 30 minutes, 60 Hz with the crowded workload, within its latency and slow-system lines. Compare it with the same run with cues off, on the authority's own tick.
- The measurements below do not show the gate holding.
- At 2,000 characters, the first measurement's rate (about 220 ms/s of tick work) is not acceptable against the contract.
- The shared answers do not change that order of magnitude.

### With the shared answers (2026-11-12, `cue-cache`)

**How it was measured.**
- Tool: `living/tools/cue_cost.py`, on main `06be6921` merged into `cue-cache`, on the trial service (SpacetimeDB 2.14.1) on the DGX Spark (20 cores).
- Host load: the host was shared with other agents' builds and tests. Its 1-minute load is given per window, from 10 to 53.
- Arms: each arm is a world law switched in the same world (`cues_on`, `regard_cache`). With `regard_cache` off, every asker computes its answer afresh. That is the code path before the cache, plus one law lookup per answer.
- Order: the windows ran A B C D, then D C B A, so drift between the passes shows.
- Cues: every character holds the same 8 cues, two of them on `unknown` (the costly path). That is a deliberate upper bound; a real mind writes 0–3.

**Cullet** (`minds-costc-083416`, 120 s windows).
- World: seed `cullet`, 64 people.
- Minds: 63 on the fake model (think 5 s, compile and consolidation 4 s, talk 2 s), with Neo4j. Each mind's own think reply wrote its 8 cues: 472 rows, none refused.
- Its daily life: about 6–7 creatures in sight on average, and 0.1–0.6 deliberation requests a second.

| Window (order) | Arm | Ticks/s (samples) | Over 16.7 ms | Tick p50 / p95 / p99 / max (ms) | Tick work (ms/s) | Cue checks/s | Cue work (ms/s; p99 per check) | Shared answers: hits / computed | Fires | Load 1 min (start, end) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | cues off | 60.3 (7,205) | 0 | 0.711 / 2.695 / 4.371 / 14.055 | 60.07 | 0.0 | – | – | 0 | 52.8, 43.9 |
| 2 | cues off, cache on | 59.8 (7,195) | 1 | 0.707 / 2.499 / 4.311 / 24.745 | 59.13 | 0.0 | – | 946 / 5,339 | 0 | 50.2, 33.6 |
| 3 | cues on, before the cache | 59.8 (7,200) | 0 | 0.798 / 2.002 / 2.958 / 8.896 | 56.44 | 51.9 | 6.25 (0.544 ms) | – | 63 | 30.9, 20.2 |
| 4 | cues on, after the cache | 59.9 (7,205) | 0 | 0.723 / 1.795 / 2.487 / 7.623 | 51.14 | 52.4 | 4.93 (0.244 ms) | 38,479 / 65,422 | 26 | 18.7, 10.4 |
| 5 | cues on, after the cache | 60.4 (7,203) | 1 | 0.862 / 2.704 / 4.605 / 18.945 | 67.17 | 50.4 | 6.2 (1.268 ms) | 40,410 / 68,992 | 46 | 10.2, 30.4 |
| 6 | cues on, before the cache | 59.8 (7,199) | 0 | 0.821 / 2.044 / 3.307 / 9.09 | 57.91 | 52.0 | 6.61 (0.698 ms) | – | 64 | 28.4, 18.5 |
| 7 | cues off, cache on | 59.8 (7,192) | 1 | 0.7 / 1.758 / 3.239 / 27.755 | 50.87 | 0.0 | – | 1,408 / 5,413 | 0 | 18.2, 18.8 |
| 8 | cues off | 59.7 (7,189) | 1 | 0.676 / 1.788 / 3.223 / 18.684 | 49.74 | 0.0 | – | – | 0 | 20.0, 25.4 |

**216 characters** (`minds-c216m-110215`, `cue_cost.py crowd216 --mode mill`).
- World: seed `island`, with 310 ambient residents and animals on their own rules.
- Added: 216 minded people.
  - 100 are packed within 7 m of the arrival square's battle site. They stand among each other and now and then wave at the nearest. Each sees up to about 106 creatures.
  - 116 walk as foragers across the island.
- Cues: 1,728, none refused.
- No mind service: their requests to think stay pending, refreshed with their scene, as under a slow mind.
- No deaths in the run. Admin calls only set the scene.
- Windows: 150 s each, about 9,000 ticks, enough for a stable p99 and over-budget count; 20 minutes in all.

| Window (order) | Arm | Ticks/s (samples) | Over 16.7 ms | Tick p50 / p95 / p99 / max (ms) | Tick work (ms/s) | Cue checks/s | Cue work (ms/s; p99 per check) | Shared answers: hits / computed | Fires | Load 1 min (start, end) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | cues off | 59.7 (8,981) | 6 | 3.188 / 6.265 / 9.399 / 24.099 | 206.69 | 0.0 | – | – | 0 | 10.6, 15.4 |
| 2 | cues off, cache on | 60.3 (9,001) | 1 | 2.747 / 5.617 / 7.533 / 16.721 | 181.76 | 0.0 | – | 4,343 / 163,062 | 0 | 16.7, 12.3 |
| 3 | cues on, before the cache | 59.5 (8,949) | 23 | 2.909 / 6.643 / 10.321 / 94.105 | 202.45 | 296.4 | 68.05 (1.724 ms) | – | 325 | 11.7, 32.2 |
| 4 | cues on, after the cache | 59.8 (8,999) | 2 | 3.216 / 7.191 / 9.303 / 19.774 | 218.54 | 324.5 | 57.3 (1.291 ms) | 1,708,998 / 1,165,798 | 8926 | 32.5, 20.4 |
| 5 | cues on, after the cache | 57.5 (8,639) | 177 | 5.773 / 12.482 / 21.044 / 67.058 | 374.36 | 345.6 | 90.72 (2.209 ms) | 1,781,547 / 1,258,987 | 688 | 22.4, 46.2 |
| 6 | cues on, before the cache | 56.7 (8,565) | 278 | 5.816 / 14.595 / 23.879 / 89.584 | 385.87 | 325.4 | 139.37 (3.498 ms) | – | 334 | 45.3, 41.4 |
| 7 | cues off, cache on | 59.8 (8,999) | 2 | 2.146 / 4.181 / 6.316 / 29.044 | 140.96 | 0.0 | – | 698 / 3,207 | 0 | 39.6, 18.9 |
| 8 | cues off | 59.6 (8,961) | 8 | 3.071 / 6.159 / 8.88 / 150.013 | 200.82 | 0.0 | – | – | 0 | 19.5, 20.7 |

**Reading.**
- **Cue checks.** They run once a second per AI character with the law on. Here that is 296–346 checks a second: the 216, and the island's own residents, whose reads find no cues. Each check is one indexed range on `cue.actor`.
- **The shared answers cut the cues' own work by 16–35%** (each pass paired):

  | | Before | After |
  |---|---|---|
  | Cullet | 6.25 / 6.61 ms/s | 4.93 / 6.20 ms/s |
  | 216 | 68 / 139 ms/s | 57 / 91 ms/s |

  With cues on, 37% (Cullet) to 59% (216) of answers were shared hits. What remains is the matching itself: each check walks every creature in sight for each creature cue, and every resource and structure in sight for each thing cue.
- **With cues off, the cache shares almost nothing:** 3–20% hits, a few thousand answers a window. One observer seldom asks about the same target twice in one transaction.
  - The cues-off windows' tick work differs: 207 / 201 ms/s against 182 / 141 at 216, and 60 / 50 against 59 / 51 at Cullet.
  - Those differences follow how many were in sight (`seen_mean` 16.5 / 12.7 against 15.6 / 9.2) and the host's load, not the cache. They are within the noise.
- **At 216 with cues on, 60 Hz does not hold in the second pass:**
  - after the cache: 57.5 ticks/s, with 177 ticks over 16.7 ms in 150 s;
  - before the cache: 56.7 ticks/s, with 278 over;
  - with cues off: 59.6–60.3 ticks/s, with 1–8 over.

  The first pass held (59.8, 2 over). The cues' work in the second pass was 91–139 ms/s, half of the tick's 200 ms/s with cues off.
- **Scale.** After the cache, cues cost 0.26–0.42 ms of tick work per character-second at this density: about 530–840 ms/s at 2,000 characters. That is not acceptable. The next lever is the matching, not the answers, each option measured the same way:
  - check only on a scene change, or set `cue_check_s` to 2–5;
  - match only the kinds a cue names;
  - a smaller cap.

**A finding beside the bar: a lethal battle of 100 minded fighters runs away by itself.**
- The run: `cue_cost.py crowd216 --mode battle` (`minds-c216-090053`). The same 216, with the packed 100 fighting the nearest person, healing below half and replaced when they died.
- With cues off, it began at 18.5 ticks/s and fell to 2.9 by the last window, the same in every arm.
- Within 30 minutes, experiences went from 2.3k to about 40k a second, and `tick.wakes` from 510 to 850 ms/s, cues on or off. Witnessed blows wake every minded onlooker.
- That workload fails the gate first, not cues. It cannot compare arms and is kept as evidence (`cost.json`).

### First measurement, before the shared answers (2026-11-12, attention-cues)

**Setup.**
- A scratch world `verify-minds-cost-062824` on the trial service, seed `cullet`, built before main's merge (`592f9fe4`'s sources).
- All 63 minds on the fake model (think 5 s, compile and consolidation 4 s, talk 2 s), with Neo4j.
- Every mind wrote the same 8 cues, a deliberate upper bound: 2 on `unknown` (the costly path: name and `far` per person in sight), wolf, deer, storage within 5 m, fishing spot, a person visibly striking, a person within 1 m. That gave 464–504 rows, none refused.
- `living/tools/bench.py`, 120 s windows: law on, off, on again. Sight held 6.8 creatures on average (16 at most); 64 people, 60 ticks a second.

| Window | Tick p50 / p95 / p99 / max (ms) | Tick work (ms/s) | `tick.slots` (ms/s) | Cue checks (= `cue` reads) /s | `brain.cues` (ms/s; p50 / p99 per check) | Fires |
|---|---|---|---|---|---|---|
| on | 0.83 / 2.76 / 4.63 / 13.0 | 67.2 | 50.1 | 49.8 | 7.4 (0.10 / 1.35 ms) | 95 |
| off | 0.71 / 2.28 / 3.70 / 20.6 | 56.9 | 41.4 | 0 | – | 0 |
| on again | 0.82 / 2.17 / 3.46 / 17.1 | 60.0 | 39.0 | 52.0 | 6.7 (0.11 / 0.89 ms) | 58 |

- **Reading.** The check costs about 7 ms of work a second for 63 minds with 8 cues each: about 0.14 ms a check, 0.11 ms per character-second. The tick p50 rose by 0.11 ms.
- **At the gate.** At the 216-character gate that is about 24 ms/s. At the 2,000-character target it is about 220 ms/s, a fifth of a core.
- **Material.** This is material at scale, so nothing is tuned before the coordinator decides. The likely levers are:
  - caching name and `far` per observer and target for a tick (the `unknown` cues dominate);
  - checking on a scene change rather than every second;
  - a smaller per-character cap.
- **Not settled by these windows.** Deliberation requests stayed at 0.4–0.6 a second in both arms, but these were fixture cues; a real batch's fires decide the minds' cost.
- **Spans.** `brain.cues` included the scene build in this run when cues were the first to ask for it. The shipped code builds the scene first, which `noticed` needs anyway. Evidence: `.local/living/verify/minds-cost-062824/cost.json` and `bench-*.json`.

## Verification

- **verify-core:** `scenes.py cues`. With the law off, nothing. With it on:
  - one fire on a match, quoting the `why`, with a deliberation request;
  - the cooldown and the gap respected;
  - nothing for a figure too far away to make out (by kind or id);
  - refusals kept with their reasons;
  - a cue on a wolf visibly winding up a strike is accepted (its match is not driven; `doing`/`phase` share `visibly` with the `doing` condition, which `doing_seen` drives).
- **verify-core, shared answers:** `scenes.py regard_check`. Under `regard_cache_check`, every shared answer is compared with a fresh one. It drives first sights in a crowd, the stranger filter and the far label, cues, told lines (on an island run) and an introduction during a fight. At least 1,000 comparisons, none differing.
- **Unit tests:**
  - rules: `attention_cues_are_the_world_s_laws` (with `cue_check_s` and the cache laws);
  - mind: `cue_examples_name_no_one`, `notice_is_kept_on_what_it_serves`.
- **verify-minds:** `cues_mind.py` (Neo4j), with the real mind and the fake model:
  - a cue the reply writes is projected through `mind_update`;
  - a player W does not know walking up gives one `noticed` line;
  - the next think request carries it as its reason;
  - `# What you watch for` shows the cue as having made W think.
- **verify-client:**
  - `cue` is refused to anonymous and player identities;
  - `mind_update` (with cues) is refused for another's character;
  - a played character keeps no cues.
- **Trial report:** `arrive_spread.py --strangers` gives, for each asker and teller, the last cue that fired before their line, its words and the stance, project or goal it served. The trial runner's `final.json` keeps every `cue` row. The inspector puts each cue and its fires on the mind's timeline.

## SpacetimeDB documentation consulted (2026-11-12; docs 2.0.0, pinned 2.14.1)

- [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/): "Adding new tables" is always allowed. A changed reducer needs regenerated bindings (`MindUpdate` gained `cues`, so the verify drivers that call `mind_update` pass it).
- [Access permissions](https://spacetimedb.com/docs/tables/access-permissions/): tables are private by default and readable only by reducers and the owner.
- [Indexes](https://spacetimedb.com/docs/tables/indexes/): btree equality lookups; "add based on actual query patterns". The one read is `cue.actor`.
- [Performance](https://spacetimedb.com/docs/tables/performance/): "smaller, more focused tables". `cue` is written only by the projection and on a fire.
