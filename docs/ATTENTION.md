# Attention cues: what a mind asks to be woken by (design, 2026-11-12)

Status: **design only, not built.** Read from main `b657a344`. Branch `attention-cues`.

**The gap** (docs/TRIALS.md, strangers stage 2). Aldous's life says arrivals are written in the book, yet he never thought with the newcomer in view. A first sight has salience 0.45. Even a percept at 0.6 or above only wakes the body's graph (`perceive.rs:49`). A thought is asked for only by fixed callers: being attacked, offers, bodily alarms, the plan ending, a quiet moment (`request_deliberation`). Nothing lets a mind say "this, when I see it, is worth a thought".

**The mechanism.** When a mind writes or revises a stance, goal or project, it may also write what in the world should make it think about it: typed **cues** over facts its perception already reports. The authority matches them by type. A match writes a percept and asks for a thought. We write no cue for anyone, and the prompt gives no example about strangers.

## Cue schema

Each cue has these fields. Every field present must hold for the same perceived thing.

| Field | Values | Matched against |
|---|---|---|
| `for` | a stance key, a project key, or one of the persona's goals | its lifetime; quoted in the reason |
| `who` | a person or creature id; `"unknown"` (a person whose name I do not know, `perception::knows_name`); a creature kind (`wolf`) | the scene's creatures, after `regard`: someone too far away to make out (`far`) matches nothing |
| `doing` | a skill or act name from the rules' catalogue (`strike`, `fish`, `bowshot`) | the perceived activity's skill (`perception::doing_of`'s source row) |
| `phase` | `winding up`, `releasing`, `recovering`, `holding` | the fighter row of COMBAT_MIND §3.2; refused until §3.2 is built |
| `thing` | a resource or structure kind (`fishing_spot`, `storage`) | the scene's resources and structures |
| `at` | one of the mind's own places, plus `within` (≤ 48 m, default 20) | the matched thing's position against that `place` row |
| `near_me` | metres (≤ sight) | the matched thing's distance |
| `why` | ≤ 120 characters, the mind's words | shown in the reason and the inspector |

- **Bounds.** At most one of `who`/`thing` per cue, and `doing` needs `who`. A character keeps at most 8 cues; a newer cue replaces its oldest.
- **Validation** happens in the reducer, as for graphs. Unknown kinds, skills or places, or ids of people never perceived, are refused. Refusals return to the next prompt.
- **Items carried by others** are not in the scene today, so they are not cue-able until perception reports them.
- **Examples:**
  - Aldous: `{"for": "arrivals_must_be_written", "who": "unknown", "at": "Counting House"}`;
  - a fisher: `{"for": "…", "thing": "fishing_spot", "near_me": 30}`;
  - a debtor: `{"for": "…", "who": 14}`;
  - a fighter: `{"who": 27, "doing": "firebolt"}`.

## Storage and write path

- **Memory is the source.** A cue is a property of the node it serves: the stance's `JUDGES` edge, the project node, or the goal. It lives, merges and fades with that node through consolidation and sleep. A stance the mind drops takes its cues with it.
- **The projection.** `project()` sends the full set as `MindUpdate.cues: Option<Vec<CueIn>>`, which replaces the set like `beliefs`. The private table is `cue`:
  - `id` (primary key, auto-increment) and `actor` (btree);
  - the typed fields above as plain columns;
  - `fired: Vec<Seen>` (subject and time, at most 8);
  - `fires`, `set_ms` and `thought_ref`.
- **Why a new table.** It is a new access pattern, read once per evaluation per character with cues. A new table is a safe automatic migration. No public or hot row changes, and the table is gone at death.

## Matching on the tick

- **When.** Matching runs in `Ev::noticed()` (`brain.rs`, from `after()`), on the character's own evaluations (its 1 Hz slot and wakes). It runs only for AI characters with the law on, at most once a second each.
- **What it reads.** One indexed range, `cue.actor`, which is empty for most characters. It matches over the scene the evaluation has already built (`self.scene()`): creatures, resources and structures. It does no text matching and no inference. Only `who: "unknown"` costs extra: `knows_name`, about 5 point lookups, for unnamed candidates only.
- **The bound.** At most 8 cues × the perceived set per check.
- **What it writes,** only on a fire:
  - the cue row's `fired`;
  - one `experience` row, kind `noticed`, salience 0.65, in the perceiver's own labels: "You notice a stranger (#77), 6 m east, near the Counting House: you meant to watch for this (arrivals must be written)";
  - one `request_deliberation` with that line as the reason.
- **When a cue fires.** A cue fires when a subject *begins* to match. A thread-local set of last-matched subjects gives the edge; the durable `fired` cooldown backs it up.
- **The rethink gate** treats a cue reason as decided by the mind itself and passes it. It is an entry in `rethink.json` `urgent`, so an arm can gate it instead.

## Guards and switch

- **Cooldown.** A cue fires at most once per subject per `cue_cooldown_s` (law, default 600). A character gets at most one cue-driven thought per `cue_gap_s` (default 60). Several subjects matching at once go in one line, so a crowd of strangers is one thought, not 30.
- **The law.** `cues_on` (default off) is switched at runtime by `set_world_law`, as `fov_on` is. While it is off, nothing is matched, the prompt omits cues, and stored cues stay inert. It is independent of `stranger_by_name`.
- **Visibility.** The inspector gets a per-character "Watches for" panel from the exported `cue` table. Each fire is a `noticed` experience, and each cue's exchange is the journaled thought that wrote it.
- **Fairness.** Matching uses only the character's perception: the scene, sight, `far` and names as the scene shows them. A cue can never detect what is out of sight or identify a figure too far away to make out. Players have no cues: their eyes are their own.

## What the prompt says

With the law on, the think and consolidate replies gain an optional `"notice": [ … ]` field. Its schema line reads: "what in the world should make you think about this stance, goal or project; you are brought to think once per thing per 10 minutes; at most 8 are kept". The examples given are a creature kind, a move and a person by id. A `# What you watch for` section lists the current cues and their fires, so a mind can keep, revise or drop them.

## Use by COMBAT_MIND 3.2 and 3.3

- **3.2.** Seeing what someone is doing gives `doing`/`phase` their facts: the same perceived fighter row the `doing` condition reads.
- **Too slow for timing.** A thought takes 5–40 s, so cues are not for timing a 350 ms windup. Timing stays with graph conditions.
- **What cues are for in a fight.** A cue makes the slow mind (or the §3.4 fast lane, once built) notice what it chose to look for, such as "the one who threw fire", and then prepare a routine.
- **3.3.** Movement intents consume no cues. A cue-driven thought may choose `keep_range` or `screen`, and `at` lets a watch be tied to a place: "keep watch at the ford".

## Verification and measure

- **verify-core** (scratch database):
  - an owner-written cue fires once on an unnamed person entering near the place, with a `noticed` row and a deliberation;
  - it does not fire for a `far` figure, a named neighbour, a second time within the cooldown, or with the law off;
  - bad cues are refused.
- **verify-minds** (fake model): a `notice` reply becomes `cue` rows.
- **verify-client:** the `cue` table is invisible to a player identity.
- **Skills.** `maintain-verification-skill` runs on core, minds and client.
- **Strangers stage 3** gets an arm L+cues. The question is whether Aldous writes a cue and asks, with the target spread unchanged.

SpacetimeDB docs (2.0.0; pinned 2.14.1) were consulted 2026-11-12:
- [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/): "Adding new tables" is always allowed, and a changed reducer needs regenerated bindings;
- [access permissions](https://spacetimedb.com/docs/tables/access-permissions/): tables are private by default;
- [indexes](https://spacetimedb.com/docs/tables/indexes/): btree equality lookups; "add based on actual query patterns";
- [performance](https://spacetimedb.com/docs/tables/performance/): "smaller, more focused tables".
