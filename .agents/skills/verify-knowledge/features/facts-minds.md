# A resident's mind from the world's facts

Every person has a mind from the start (2026-11-11; the woken mechanism and its ring are gone). Before a resident's first thought the mind service makes its first identity once (`living/mind/src/mind/facts.rs`): its world facts as given (marked `world`), then its authored sheet if it has one (marked `authored`, no model call; `verify-minds` `lives_mind.py`), otherwise one identity call written from those facts only (the model's part marked `ai`). This runner proves the second path.

## Sub-features

- With the chosen resident's sheet taken out of its background before the mind starts, the service's first identity for it is an identity call (purpose `consolidate`) whose request carries the facts (`occupation`, `household`, `places` with `work`, `settlement`) and no perception or sheet; its thought ("Who I am, from what the world holds about me.") comes before its first deliberation.
- The graph: facts marked `world` (its given `work` place among them), the identity version `written_by: model` with `from_facts`.
- It answers the newcomer (its first thought's `say`); a later line takes a talk turn on the default route's talk model (`people` mix → its `talk` profile).
- Its deliberation's acts give the newcomer food, teach it a technique whose prerequisites it has (from the rules' `requires`), and `host` it (`guest` row, `lodging` place).
- The newcomer never says its name, and nothing the resident's model is sent names it.

## Driving it

```bash
.agents/skills/verify-knowledge/scripts/facts_mind.py run --run knowledge-facts-<name>
```

The island module builds in `.local/living/target-facts-island`, the mind in `.local/living/verify/build-knowledge`. Scratch Neo4j on 127.0.0.1:7691. `LIVING_ONLY` names the resident, `LIVING_LOD=0`. The fake model tells purposes apart by each profile's `reasoning_effort` map; one `consolidate` reply carries both the identity's and a consolidation's fields. Admin scene calls: `set_weather`, `place_at`, `grant_items`, `set_background`. Evidence: `results.json`, `requests.jsonl`, `thoughts-all.json`, the Cypher outputs, `mind.log`, the copied journal.

Paid tier: `residents_real.py --allow-live --run knowledge-residents-real-<name>` (a scripted newcomer asks three Brackenford residents for food, a bed and a lesson; `LIVING_ONLY` names Brackenford's residents; `report.md`, `rows.json`, `cost.json`).

## Gotchas

- The island's residents are authored ([seeded lives](../../../../docs/SEEDED_LIVES.md)): an authored resident's mind starts as its sheet says. The fixture takes the chosen resident's sheet out of its background with `set_background` before the mind starts, since the identity is made at the service's start.
- `player_session.py` reads the player's characters through `my_characters` (`character` is private in the scoped default).
- A lesson whose prerequisite the newcomer lacks is refused by the rules; that is not a mind failure.

## Someone born in the world whose mind starts when grown (since 2026-11-12, `self-body`)

The other facts path: a character born in the run (parents on its `character` row, no background, not in the seed) whose mind first starts once it is past childhood, as in a capped trial (`Origin::Grown`, `facts.rs` `grown_identity`). Its first identity comes from facts with no model call: its parents, siblings, children and settlement in a plain narrative ("I am Vale, child of Brisk Marrow and Edda Marrow. My home is in Millbrook."), its inborn temperament, and no values, goals, pastimes, calling or mood. Its mind gets `CHILD_OF` edges from `self` to both parents and the `parent` relation (trust 70, affinity 80, as a newborn's mind starts with), written `lived_under = world`; the identity version is `written_by: facts` with `from_facts`. Before this such a mind had "(no persona yet)" and no parents.

The proof is verify-minds' `body` case run with `LIVING_PRIVACY_NEO4J` and `LIVING_PRIVACY_NEO4J_ENV` set ([self-body.md](../../verify-minds/features/self-body.md)): it reads the `CHILD_OF` edges with Cypher (`grown-child-of.txt`) and the projected `parent` relation rows, then deletes the run's nodes.
