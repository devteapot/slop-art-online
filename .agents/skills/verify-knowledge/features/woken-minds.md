# Woken residents' minds

Since 2026-11-09 (docs/TOWN_LIFE.md, "Layer 2"). On an island world (`rules.minds = false`) a resident a player engages is handed to the mind service (`woken` row). Before its first thought the service makes its mind once (`living/mind/src/mind/woken.rs`): an identity written from the world's facts, then its ring of perceptions from before it woke (`prior`), taken in through player memory's integration path (`lived.rs`, `Source::Ring`).

## Sub-features

- A resident in earshot of a line spoken to another keeps it in its ring and stays instinct only.
- Spoken to, it wakes (`why = speech`); its thoughts come in order: `awaken`, `internalize`, `deliberate`.
- The identity request (purpose `consolidate`) carries the facts (`occupation`, `household`, `places` with `work`, `settlement`) and no perception; the ring request (purpose `internalize`) carries the overheard line and nothing said after waking.
- The graph: facts marked `world`, the ring's memories and beliefs `instinct`, the identity version `written_by: model` with `from_facts`; `self.woken_upto` set.
- It answers the newcomer (its first thought's `say`); a later line takes a talk turn on the woken route's talk model (`woken` in the models file → the mix's `talk`).
- Its deliberation's acts give the newcomer food, teach it a technique whose prerequisites it has (from the rules' `requires`), and `host` it (`guest` row, `lodging` place).
- Waking one more resident of the settlement than the `woken_stage("cap")` law: the cap binds, logged (`stage cap … binds`) and journaled (`purpose: stage_cap`).
- Woken residents stay minds.

## Driving it

```bash
.agents/skills/verify-knowledge/scripts/woken_mind.py run --run knowledge-woken-<name>
```

The island module builds in `.local/living/target-woken-island`, the mind in `.local/living/verify/build-knowledge`. Scratch Neo4j on 127.0.0.1:7691. `LIVING_ONLY=woken`, `LIVING_LOD=1`. The fake model tells purposes apart by each profile's `reasoning_effort` map; one `consolidate` reply carries both the identity's and a consolidation's fields. Admin scene calls: `set_weather`, `place_at`, `grant_items`. Evidence: `results.json`, `requests.jsonl`, `thoughts-all.json`, the Cypher outputs, `mind.log`, the copied journal.

Paid tier: `woken_real.py --allow-live --run knowledge-woken-real-<name>` (a scripted newcomer asks three Brackenford residents for food, a bed and a lesson; `report.md`, `rows.json`, `cost.json`).

## Gotchas

- The island's residents are authored since 2026-11-10 ([seeded lives](../../../../docs/SEEDED_LIVES.md)): an authored resident wakes as its sheet says, installed without a model call (`verify-minds` `lives_wake.py` proves that path). This driver proves the other one, so it takes the chosen resident's sheet out of its background with `set_background` before waking it.

- `player_session.py` reads the player's characters through `my_characters` (`character` is private in the scoped default).
- A lesson whose prerequisite the newcomer lacks is refused by the rules; that is not a mind failure.
- The cap counts residents on stage, which needs contact with a player within `LIVING_LOD_STICKY_S`; the driver speaks to each resident it wakes.
