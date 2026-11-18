# Seen structures and counted remains (R1 and R2)

*Design for the build, 2026-11-13. Approved by the general coordinator from the remains note (docs/BATTLE_SCALE.md, "Familiarity of remains"). Implementation on `battle-seen-ranges` is based on C2 as merged to main (`1cd32ab2`).*

## What stays as it is

- The world's remains stay individual: each body lies where its person fell, a structure of its own.
- Main limits the mind scene to the nearest ten structures. The bounded R1/R2 scene keeps that limit and distance order. Named and readable remains can appear individually. Other visible remains share one counted slot. The player still sees every body through the individual structure rows.
- A known person's remains keep their own first-sight line ("You notice a remains — the remains of Wren, 3 tiles north.").
- Players are not told noticing lines; they perceive by seeing (the general coordinator, 2026-11-13). The folded words are made in one place (`living_rules`), so a player would be told the same words if that ever changes.
- **What is new** is a structure id not seen before: a rebuilt structure, a ruin left by one destroyed, a new body. Noticing an absence (a structure gone) or a changed state (a fire out, a gate shut) is a separate, later decision. It belongs with known-ground's `remembered` table (what a character last saw of a thing that changes) and with talk-places' remembered resources that are gone when one was last there, so the two share one rule when it comes.

## R1: what a character has seen of structures, as id ranges

**Table** (private; a new table, a safe automatic migration: [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations), "Adding new tables"):

```rust
/// Which structures a character has seen in one 128 m block (8 × 8 chunks, as `known_ground`):
/// their ids as sorted, disjoint, inclusive ranges `[lo0, hi0, lo1, hi1, …]`. Ids are never
/// reused, so a structure seen once is in a range while it exists. Written by the character's
/// own looks, once per look that found something new there; gone at death.
#[spacetimedb::table(accessor = seen_structures,
    index(accessor = by_actor_block, btree(columns = [actor, block])))]
pub struct SeenStructures {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[index(btree)]
    pub actor: u32,
    pub block: u32,
    pub ranges: Vec<u64>,
}
```

It is keyed like `known_ground` (actor and 128 m block), so the two kinds of "I have been here" share one layout. A battle site lies in one or two blocks.

**Newness.** At a look, every structure C2 does not pass over is asked `seen(id)`: a binary search in its block's row, read once per block per look. If it is not seen, it is new: it is told (R2) and its id is added. A look adds all its new ids to each block's row at once, so one row is written per block touched.

**What leaves `familiar`:**
- Structures' `familiar` rows are no longer written. `familiar` keeps creatures and regions, and `FAMILIAR_LIMIT` bounds those.
- The seen set's structure marks and C1's ordering rule (which existed for `familiar`'s pruning) are not needed for structures.
- C2's prune protection of the last look's disc applies to legacy rows only.
- A structure is never forgotten while it exists; this is the documented difference (approved: "that's how a person remembers a place").

**Compaction.** When a row's ranges pass 64 pairs, they are rebuilt from the block's existing structures that are seen. Ids of structures gone drop out, and runs of consecutive seen ids merge. A battle's remains take nearly consecutive ids, so ranges stay few. The row is bounded by the structures that exist, and the remains' own hour bounds those.

**Migration.**
- Worlds already running hold `FAM_STRUCTURE` rows and no ranges. An entrant not in a range is asked of `familiar` as well.
- A legacy row found means seen: its id is added to the ranges and the legacy row deleted. So a world being updated is not flooded with "You notice" lines, and the legacy rows go as they are met.
- Legacy rows never met again are pruned by `familiar`'s own limit, as today.

**Laws.**
- `seen_ranges` (on): R1. Off: `familiar` as before.
- `seen_ranges_check` (a diagnostic): `familiar` rows are written and read as well. Each entrant's newness by ranges is compared with newness by `familiar`, counted and logged (`seen_ranges:differed`).
- The one expected difference is a structure whose `familiar` row was pruned. It is counted apart (`seen_ranges:kept`), not as a difference, because that is the approved change.
- `notice_delta_check` asks `seen(id)` of what C2 passes over.

**At death:** `forget_dead` deletes the character's rows.

**Bindings:** regenerated for the new table (`just living-generate`, through the trial container on the Spark).

## R2: one counted line for strangers' remains

**At a look:**
- **Remains whose person the observer knows by name** (`perception::knows_name`): each keeps its own line, in today's words, salience and wake.
- **Every other new remains of the same look** is counted into one line, grouped by how the observer refers to them, nearest first:
  - "You notice the remains of 12 strangers around you, the nearest 2 tiles east."
  - "You notice the remains of 12 strangers and 3 deer around you, the nearest 2 tiles east."
- **A look with one such remains** tells it in today's words: nothing changes below two.
- **The count is exact:** every new remains of the look is either on its own line or counted in the one line, none dropped.
- **A remains holding a tablet or sign** (which stays past `remains_h`) is told on its own line as now: it is a thing to read, not only a body.
- **The counted line's experience:**
  - kind `saw`, salience 0.8, as remains lines are now;
  - subject 0, object 0 (it names no one), placed at the nearest;
  - it wakes as a bystander, at most once per `witness_wake_ms`, as remains lines do.

**The words** are made in `living_rules::remains` (as `living_rules::fold` makes fight lines): `counted_line(groups: &[(label, n)], nearest: (dist, direction)) -> String`, with rules tests for one group, several, plurals ("2 deer", "3 strangers", "2 wolves") and the nearest.

**Players:** not told (as now). The verify-player case checks that a player's character at a field of remains gets no "You notice" lines, while its view lists every body.

## Proof

- **verify-core `seen_remains`:**
  - a field of 20 remains, two of them of people a newcomer knows by name;
  - a newcomer arrives with `seen_ranges_check` on. It is told two own lines and one counted line, "18 strangers", exact; newness agrees with `familiar` (none differed);
  - it walks off and back: nothing told again;
  - a new body falls in view: one new line;
  - a shelter put up in view: one new line (a new id);
  - with `seen_ranges` off: `familiar` as before, and the same lines.
- **Cargo:**
  - ranges insert, search and compaction (against a `BTreeSet`);
  - `counted_line`'s words;
  - migration: a legacy `familiar` row is taken into the ranges and deleted.
- **verify-minds:** a mind arriving at the field gets the counted line in its told experiences and its prompt, the known person's own line, and the ten-entry scene keeps the aggregate, named and readable remains, and other nearby structures.
- **verify-player:** as above.
- **Maintenance pass** on verify-core (battle.md, the README row, SKILL.md drive lines), verify-minds and verify-player for the new cases.

## Measurement

The same 30-minute 200-fighter run as `minds-fam30-041631` (`battle_diag.py --familiar`), with R1 and R2. At the 27-minute point (about 2,700 remains), compare:
- noticing ms/s (`brain.noticed`, `noticed.structures`);
- `familiar` rows and `seen_structures` rows;
- the table sizes;
- first-sight lines a second (`percept:saw`) and experiences a second;
- tick ms/s and ticks a second.

Then re-project to 8 hours (about 5,800 bodies at the site).

**Expected:**
- **Rows:** a newcomer's first look writes 1–2 rows instead of about 2,700 `familiar` rows and lines. A death deletes 1–2 instead of about 2,500.
- **Lines:** about 1.6 counted lines a second from arrivals, instead of 4,700.
- **Noticing:** down to the in-disc range lookups and the few lines. That is to be measured, not assumed.

## Implementation

The authority reads one indexed row for each actor and block touched by a look. It writes one row for each block with new or migrated IDs. Compaction reads the existing structure index for the block's 64 chunks and retains ranges for structures that are still present. The private table stays outside the game and mind subscription sets. The actor index makes death cleanup proportional to the blocks visited by that actor. With the diagnostic law off, a range hit needs no per-structure familiarity lookup. A range miss still checks the legacy index so that existing worlds preserve recognition.

The mind scene keeps up to ten entries, including one counted entry when unnamed remains are present. It uses the same indexed sight traversal and stable distance order as main. It walks the candidates once, counts by species and keeps only the closest individual candidates for serialization. Body species and readability are cached per structure ID, invalidated when writing moves and retired when a corpse expires. Known names use the same indexed family, acquaintance and membership rules as the player view. The first-sight line and scene entry share the group formatter. There are no schema changes in the bounded revision.

SpacetimeDB's [table](https://spacetimedb.com/docs/tables/), [index](https://spacetimedb.com/docs/tables/indexes/) and [performance](https://spacetimedb.com/docs/tables/performance/) guidance supports the focused private table, actor/block lookup, and grouped writes. The pinned 2.14.1 table API supports tuple B-tree filtering and actor-index deletion. [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/) permits adding the private table without rewriting an existing one. Legacy migration is an authority transaction when a structure is next checked.

## Unbounded scene prototype measurement

Both Spark trial runs used SpacetimeDB 2.14.1 on port 3320, with 200 fighter slots, 16 walkers and 310 seeded characters. Refills started about 30 m away with a 0.25 s minimum gap. The benchmark sampled each minute with `battle_diag.py --familiar --law profile_detail=true`, including SQL row counts, table metrics and per-actor familiarity reads. There was no game observer. `minds-seen-fake2-1118-210724` used one mind-service subscriber with a local fake provider. `minds-seen-match-1118-213921` used no mind service, matching archived `minds-fam30-041631`. Both runs finished before 22:12 CET on November 18. A comparable C2-only run was unavailable.

| At minute 27 | Archived fam30, pre-C2 | R1 + R2, matched no mind | R1 + R2, fake mind |
| --- | ---: | ---: | ---: |
| Remains within 30 m | 2,675 | 2,904 | 374 |
| Fighters assigned to battle / refilling | 170 / 29 | 111 / 73 | 198 / 2 |
| Live characters in world | 487 | 457 | 463 |
| `brain.noticed` ms/s | 277.60 | 93.92 | 7.93 |
| `noticed.structures` ms/s | — | 79.88 | 3.26 |
| `perceive.scene_json` ms/s | 34.31 | 575.37 | 1.58 |
| `familiar` rows | 465,100 | 43,046 | 74,360 |
| `seen_structures` rows | — | 696 | 1,305 |
| `familiar` pages / index keys, MB | ~69.8 combined estimate | 2.750 / 1.007 | 3.601 / 1.785 |
| `seen_structures` pages / index keys, MB | — | 0.842 / 0.014 | 0.411 / 0.026 |
| `percept:saw` /s | 5,261.2 | 186.5 | 1.1 |
| All experiences /s | 5,804.7 | 622.4 | 12.1 |
| Tick work ms/s | 682.47 | 898.92 | 165.51 |
| Ticks/s | 32.7 | 7.5 | 59.7 |

Row counts, sizes, total experiences and tick rates come from sample 28. Table sizes use the server's page and index-key gauges, in decimal MB. The baseline lacked those gauges. Its estimate uses its historical assumption of 150 bytes per familiarity row. Timing spans come from complete module log windows, about 20 s for the baseline and 30 s for each new run. Sight rates use the full intervals between diagnostic reports. This avoids truncation of the detailed CLI log tail and the extra seconds around the archive's diagnostic window. The original archive summary reported 275.47 ms/s of noticing and 4,713 sight events/s.

The matched replay spent 66% less time noticing and produced 96% fewer sight events. Its tick rate fell from 32.7 to 7.5 Hz. The former authority scene capped the whole structure list at ten. Returning each individual body now spends more time constructing and writing scenes when reasons update pending deliberations. Scene construction rose from 34 to 575 ms/s. Immediately after the matched sample, an 18.75 s unprofiled window ran at 9.0 ticks/s. The matched and archived runs refilled at 1.69 and 1.61 fighters/s between minutes 5 and 27. Their one-minute host loads were 8.9–10.1 and 4.8–4.3 in sample 28. The comparison includes C2 and these workload differences. The fake-model fight's refills tapered to nearly zero, so its lower timings describe a quieter fight.

### Eight-hour projection

An hour of retention at 1.6 deaths/s gives about 5,760 simultaneous bodies. The matched accrual of 1.72 remains/s would give about 6,200 if it persists. For 200 fighters whose field sight covers one or two blocks, local recognition occupies about 200–400 block rows, plus rows from other places. At 1.6 arrivals/s, one or two block writes for each first look at the field would be about 1.6–3.2 writes/s. Further looks can add more IDs. Each look emits at most one counted line, plus named and readable exceptions.

At fixed block count and linear payload growth, the measured 0.842 MB of range-table pages would reach about 1.7–1.8 MB. At fixed look and request rates with work growing linearly in the number of bodies, structure noticing would take approximately 160–170 ms/s and scene construction 1,140–1,230 ms/s. That estimate exceeds one second of reducer time per wall second for scene construction alone. Sight radius, queueing, action cadence, range fragmentation and exploration can change those results. An eight-hour run and the performance gate remain outstanding.

## Unbounded scene prototype verification

Core field 15/15, C2 module upgrade 6/6, mixed remains and tablet 6/6, mind prompt 5/5, player 3/3 and SDK privacy 3/3. The final core check logged 210 comparisons and 4,117 C2 checks with zero differences. The upgrade kept a live subscriber and migrated three legacy IDs. Cargo passed 41 authority, 329 rules, 124 mind and 128 game tests. `just living-check` and the fuel gate passed. Bindings were regenerated with the trial container's 2.14.1 CLI.

The first fake-model attempt was paused by the orphan guard when the build-slot wrapper exited. The completed run applied the slot around Cargo so the guard followed the long-lived driver. The aborted attempt and the full profiling windows are preserved in the evidence. The fake-model benchmark predates the final diagnostic-only correction and ran with the diagnostic off.
