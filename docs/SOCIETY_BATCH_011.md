# Batch 011: teaching, archives and loss

Four concurrent fresh Luna-medium sessions ran for six minutes under frozen `m2-1-knowledge.1`, with a fifteen-second post-completion cadence and no call cap. [The manifest](../configs/experiments/campaign/011-knowledge.json) records the hypotheses and inputs. Initial survival policies were authored and revisable; teaching, preservation, consultation and exploration were model choices. Scheduled deaths and archive destruction were explicit authored disturbances.

## Results

| Variant | Seconds | Survivors | Final health by actor | Model calls | Reported tokens | New teaching / recording / consultation copies |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| Teaching two | 360.002 | 2/2 | 70, 46 | 23 | 448,227 | 1 / 0 / 0 |
| Archive four | 360.074 | 3/4 | 0, 100, 100, 100 | 37 | 665,706 | 1 / 1 / 2 |
| Archive loss four | 360.010 | 3/4 | 0, 40, 100, 78 | 38 | 706,069 | 3 / 1 / 0 |
| Distributed eight | 360.096 | 8/8 | 100, 50, 100, 70, 100, 100, 100, 100 | 105 | 1,974,917 | 1 / 1 / 2 |

The only deaths were the two scheduled author deaths. Travel outside shelter still incurred ordinary costs and cold damage. Surviving every person at full health was not this knowledge trial's criterion.

All runs had zero engine errors, scope violations, copy-audit violations and resource-conservation violations. Food reconciles as initial + actual production = final holdings/sites + meals: `24 + 23 = 31 + 16`, `30 + 27 = 31 + 26`, `30 + 24 = 28 + 26`, and `44 + 74 = 54 + 64`, respectively. Food stranded on dead actors remains in final accounting.

Gross operations substantially overstate transmission: teaching-two completed 13 teachings but only one new recipient copy; archive-four recorded six times but added one archive copy; distributed-eight recorded 25 times but added one copy. Repeated receipts cost ordinary resources and refresh citable evidence; they do not create new informed people. Models also authored five, six, four and eighteen new assertions, respectively. That count describes claims, not verified discoveries.

## Causal evidence

**A taught report changed an action.** In archive-loss-four (`sim-bevy-1788647097885`), Mira taught Tovan the private `route-cache` report: teaching event 1127 and recipient perception 1128 at 25.125 seconds. Tovan's accepted reflection 2408 at 56.819 seconds cited 1128, treated the report as unverified and added a belief about cell 56. The reflection incorrectly called the reporter Iri; the immutable report still identifies author 1. This is a model attribution error, not a changed provenance record.

At 121.846 seconds, command 4839 / decision 4840 replaced Tovan's camp-only reserve policy with travel and cache assessment. Move attempt 4848 completed at 123.148 seconds (result 4908, direct site perception 4907), followed by food collection at 123.486 seconds (resource event 4924, result 4927). This chain links supplied information, accepted interpretation, a selected behavior and an actual material result. It does not claim the report forced the choice or that every traveller completed its plan.

**An archive informed someone after the author died.** In archive-four (`sim-bevy-1788647096416`), the author died in event 4893 at 120.163 seconds. Iri later consulted archive 1 in event 10689 at 316.641 seconds, acquiring a new `route-cache` copy. This was a first formal copy for that actor, not repeated consultation. The physical archive remained intact; at completion all three survivors held the report and archive 1 retained it. The earlier consultation by Renn at 111.400 seconds occurred before the death and is reported separately.

**Archive destruction did not erase living copies.** In archive-loss-four, destruction event 7655 at 180.266 seconds removed the archive's one copy. Tovan, Iri and Renn still held personal copies. Tovan revisited the cache and collected food after destruction (for example results 7812 at 183.435 and 8020 at 187.581 seconds). This run establishes persistence through living carriers, not total loss. The deterministic last-copy tests cover complete in-world loss without seed/audit recovery.

**Greater population did not automatically spread knowledge.** In distributed-eight, actors 1–4 held the report and archive 1 retained it. Actors 5–8 at the second settlement did not acquire it, and archive 2 remained empty. No proximity-based or world-wide copying filled that gap. These differently configured two-, four- and eight-person samples are descriptive comparisons, not a controlled estimate of population-size effects.

## Defects and next decision

The authority rejected malformed subtree paths and invalid learning sources without granting effects. Finalization also rejected a command after a run stopped. Fresh model output remains fallible; the output-error totals are distinct from engine defects and accepted-action counts.

Live inspection exposed one bookkeeping defect: duplicate teaching refreshed `Holding.source`, so a later valid reflection citing an earlier received copy could update beliefs while leaving the report's personal interpretation empty. `m2-2-assessment.1` addresses this using the validated supplied perception, with separate ordering for assessments and receipt refreshes. It does not recover content through audit lookup. The first batch's artifacts remain unchanged.

Batch 012 repeats teaching on that fix and challenges archive use with readers initially at the other settlement. [Stage 2 acceptance](STAGE_2_EVIDENCE.md) is recorded after that verification. These trials do not establish practical skill mastery, population renewal or a broadly distributed culture.

Retained local evidence is under `output/society-lab/batches/011-knowledge`: immutable final snapshots, per-session `LIVE_RESULT.json`, `SOCIETY_RESULT.json`, `KNOWLEDGE_RESULT.json`, controller traces and batch `comparison.json`. The frozen implementation contains 367 hashed artifacts. Completed observer sessions remain available in the lab.
