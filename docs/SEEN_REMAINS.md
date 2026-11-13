# Seen structures as ranges, and one counted line for strangers' remains (R1, R2: design)

*Design for the build, 2026-11-13. Approved by the general coordinator from the remains note (docs/BATTLE_SCALE.md, "Familiarity of remains"). Nothing here is built yet. Branch `battle-seen-ranges`, after C2 (`battle-notice-delta`).*

## What stays as it is

- The world's remains stay individual: each body lies where its person fell, a structure of its own.
- The scene lists every body in sight, each as the observer knows who it was (a name if known, "a stranger" if not).
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
- **verify-minds:** a mind arriving at the field gets the counted line in its told experiences and its prompt, the known person's own line, and its scene lists every body.
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
