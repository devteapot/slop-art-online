# Attention cues: what a mind asks to be woken by (2026-11-12)

Status: **built on branch `attention-cues`, off by default (the `cues_on` law).** The design was approved by the general coordinator on 2026-11-12, who called "a cue match asks for a thought" the right single engine change. Main had moved to `49dfc2cd` (COMBAT_MIND 3.2 included) when this was merged in. The cost of the one-second check is measured below. It is material, and it is left untuned until the coordinator decides.

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

All are script laws (`skills.rhai`, `script.rs` `Laws`), switched at runtime by `set_world_law`, and described by `laws_about`.

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

## Cost (2026-11-12, all of Cullet's minds)

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
- **Unit tests:**
  - rules: `attention_cues_are_the_world_s_laws`;
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
