# Looks: a world's look data

Since `look-1-auth` (2026-11-12, docs/LOOK.md §4-§5). A seed may carry `looks: { generation, people: { lp: { band: lk } }, words: { lk: LookWords }, pool: [lp] }` (bands `"0"`..`"4"` or `"infant"`..`"elder"`), and each seeded resident `look: "lp_…"`. `floor::check` refuses, before anything is written, looks that do not resolve: a key of the wrong shape, a band that is not one, a line without words (or words with girth or height past 2, or a field `LookWords` lacks, such as `colour`), a pool entry missing any band, a resident wearing an entry not among `people`, or one with no line for its band at its seeded age or for a band after it (`look::check`). Genesis (`init`, `create_floor`, staged `genesis`'s people step) writes the `look_line` rows and `world.look_book` before anyone is made, then gives every person a look: the pool's (`pool_pick`) as they are made, an authored resident its own entry right after.

Cullet's data is char-4's (`living/seeds/worlds/cullet/looks.json`, written by `living/tools/characters/look_lines.py`, generation `c4-aa393793`: 192 person entries, 791 lines, a pool of 128, the 64 residents' keys); `author_world.py cullet --compile-only` writes the residents' `look` and the seed's `looks` into `cullet.json`, and `cullet_plan.py` keeps them when it rewrites the rest. `plan-test` carries a small fixture (`fixture-1`: its 5 residents and a pool of 3). Since `look-1-island` the island carries the pool alone ([LOOK.md](../../../../docs/LOOK.md) §9: `living/tools/pool_looks.py island --into island`, Cullet's pool at `c4-aa393793`), and no resident names a look, so all 277 wear a pool entry.

## Sub-features

- With looks: the world wears the seed's generation; `look_line` holds exactly each (person, band, line) of the data, with its words; every living person has a look row whose line resolves for its person and band; no animal or dead character has one; each seeded resident wears its own entry and everyone else a pool entry; every key is `lk_` and 16 hex digits.
- With char-4's cases (`living/seeds/worlds/<run>/look-cases.json`, Cullet): the cases are of the world's generation; the key rule (`lk_` + 16 hex digits of SHA-256 over the canonical JSON of the drawn fields `type`, `height`, `proportions`, `identity`, `colors`, `styles`, `belly`, `grey`; `name` and `seed` left out) gives each hash case's key; each band case's resident (Dory 1, infant; Edda 12, youth; Col 15, stage 2 and still a youth; Roos 18, adult; Vessa 61, elder; and six more) wears its entry, in its band, with its line, at its stage.
- A seed that names no one (the island): "each seeded resident wears its own entry (none: …)" passes, and every person's entry is the one `pool_pick(world seed, id, pool length)` names, recomputed in Python (splitmix64).
- With the client's book (`LIVING_LOOK_BOOK`, else `living/game/assets/characters/looks.json`; git-ignored, in char-4's bundles under `~/archive/deliverables/`): every look row's line is in the book, and the seed's generation is among the book's. Without a book the check says it was not run.
- Without looks: no look rows, no look lines, an empty `look_book`.
- A runtime floor seed with looks (`plan-test-floor`: plan-test given to a floor module by `create_floor`): refused when a resident wears an unknown entry or a line has no words, accepted whole, a second `create_floor` refused; then the same checks.

## Driving it

```bash
.agents/skills/verify-generation/scripts/generation.py --run generation-looks-$(date +%Y%m%d-%H%M%S) --feature worlds --seeds plan-test,plan-test-floor,cullet
```

`check_looks` runs on every world the suite makes (`checks.json`: the rows above); `create_floor_looks` drives the floor's refusals (`create-floor-*.log`). Cargo: `look::tests::` in living-authority (the fixture's refusals, Cullet's looks and band cases) and `cullet_check::tests::cullet_s_band_cases_hold`, `look::tests::` in living-rules.

## Gotchas

- The island's `pack the wolves of the low hills starts near deer` fails on main too (the same wolves at the same spots, about 816 m from the nearest deer): it is not a look check.
- The suite's last check, "original seeds unchanged", compares `living/seeds` before and after: merging main during a run fails it.
- SQL's JSON gives the `words` struct column as its fields in order; `check_looks` reads it so.
