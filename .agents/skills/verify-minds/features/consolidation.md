# Consolidation without Neo4j

## Sub-features

- Authored bootstrap publishes persona, relations, judgments and places directly with no store, `living/mind/src/mind.rs:745`.
- Meaningful addressed speech triggers an actual experience consolidation, `living/mind/src/mind.rs:1038`.
- A momentous experience permits persona revision, `living/mind/src/mind.rs:1589`.
- `mind_consolidated` deletes consumed experiences and advances `mind_cursor`, `living/authority/src/mind.rs:408`.
- The consolidation reply requests relation, belief, judgment and place updates. Table comparisons expose whether the no-store path applies them, `living/mind/src/mind.rs:825`.
- With `LIVING_PROJECTS=1` and a store, a person's consolidation also shows and keeps projects (`projects` array); not reachable without a store: [projects.md](projects.md).

## How to get to it (user POV)

A character integrates what it experienced. Its identity can change after a meaningful event, and its consolidated experience inbox advances. Mind projections are visible in the authority's tables.

## Driving it with verify_minds.py

```bash
R=minds-memory-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case consolidation
```

The driver sets an authored background as setup. The real binary installs that sheet. It then hears four addressed player questions, each with salience 0.9. The fake returns a changed identity and a graph patch with distinct markers for every projection.

Compare `persona-before.json` with `persona-after.json`. Inspect the actual consolidation thought and its `experiences` list, the fake request and the journal. `cursor-after.json` must advance, and `integrated-experiences-after.json` must be empty for IDs at or below the cursor. Compare the other four `*-before.json` and `*-after.json` snapshots with the reply's markers. Persona revision, accepted consolidation and a strictly advancing cursor must pass. Missing patch markers produce XFAIL KNOWN ISSUE with per-projection booleans in `result.json`. If every patch marker reaches its table, this becomes XPASS and exits nonzero for review.

## Gotchas

- The no-store `project` branch currently sends empty relation, judgment and place vectors and `beliefs: None`. It does not project the parsed graph patch. This is XFAIL KNOWN ISSUE in [the handoff](../../../../docs/LIVING_HANDOFF.md), under "Still open". The patch loss is recorded even though persona and cursor updates pass.
- Background bootstrap is not experience consolidation. Match the distinct summary and experience IDs.
- The first consolidation has no minimum-gap delay. Later consolidations wait the real 90-second species gap. The driver waits up to 110 seconds and never edits tracked seeds.
- Persona changes normally wait eight minutes. Addressed speech supplies the momentous event that permits a change sooner.
- Projections WITH a store belong to `verify-knowledge`, which already proves them. This case checks no-store consumption and records its known patch-loss defect. It makes no verdict about stored projections.

## Whom one fights

`fight-field` (relation-fight, 2026-11-23; docs/WORLD_RULES.md "Whom one fights"), with the `relation_fight_on` law (on by default since 2026-11-26) set on explicitly before the service starts (off, the prompts carry no order and no field and a reply's `fight` is ignored; mind test `whom_one_fights_is_told_only_under_its_law` checks the shipped prompts carry them): the fake model's consolidation reply gives three relations with `fight`: `spare` for a resident, `"never"` for the player, `enemy` for id 999999. A player speaks to the mind's character to bring a consolidation. Passes when `relation_fight` holds exactly the resident's `spare` (by `mind`), the integration's thought notes say `fight: #<id> spare` and left out `"never"` and #999999, a consolidation or deliberation system prompt carries the gloss ("Whom your body counts as an enemy (relation: enemy)"), and a later prompt shows "fight: spare" beside the person. `mind.rs` `fights_of` and `fight`; the service subscribes `relation_fight` on its own (a module without it still starts). `mind_fight` refuses a character a person plays: verify-client's `PLAYED_REFUSED`.

