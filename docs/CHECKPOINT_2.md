# Checkpoint 2: a valley that grows

Agreed with the user on 2026-09-26. The next commit/push point after the [living core](LIVING_CORE.md) baseline (`7b23fef` on `living-core`). It brings the [world roadmap](WORLD_ROADMAP.md)'s learning, renewal and multi-society stages into the living core at small scale, with a neutral valley seed (the faction world comes later on the same mechanics).

The problem it answers: the core works, but the world is thin. Once fed and warm, characters have nothing further to strive for, so staying clustered somewhere safe is the rational choice. Progression needs things to learn and pass on, pressure that rewards planning, and reasons to need other groups.

## Scope

1. **Know-how as world state.** Techniques must be known before they can be used: `fire`, `cooking`, `spear`, `shelter`, `storage`, `cloak`, `torch`, `planting`, `writing`. Know-how is practical capability (game state in SpacetimeDB), distinct from beliefs in the mind. It is gained by being taught (`teach`: the teacher spends time with the learner), by reading a tablet that describes the technique (requires `writing`, i.e. literacy), or by experimenting with materials (`experiment`: a chance to discover a technique whose prerequisites are met). It can be lost: if every knower dies and no tablet survives, it is gone. This first ladder is predefined data in the Rhai rules, the same mechanism later player-authored skills extend.
2. **Artifacts.** Tablets (carried, given, stored, taken) and signs (placed in the world), each with author, time and text written by the author's mind, optionally describing a technique the author knows. Reading is an experience the reader's mind weighs as testimony from its author.
3. **Seasons and uneven land.** An eight-day year; in winter plants do not regrow and nights are colder, so stored food and shared work matter. Richer resources in riskier places.
4. **Survival rebalance.** Warm cloaks (from deer hides) and torches make nights survivable and exploration possible; hunger and energy leave time for activity beyond recovery. Tuned by observation until characters take measured risks instead of hiding.
5. **Communities.** Three camps with different know-how, resources and temperaments (plus loners), so teaching, trade, gifts and rivalry have reasons to happen.
6. **Viewer toward the game** (in parallel): generated pixel art — textured terrain, readable character and creature sprites with simple animation, resource and structure sprites, seasons; know-how, tablets and seasons in the inspector.

## Evidence for the commit

Observed in a multi-hour live run (outcomes are observed, not scripted; failures are recorded as data):

- A technique spreads beyond the camp that started with it and is then used by the learner.
- A tablet changes what a reader does — ideally after its author died.
- A winter is survived through stored or preserved food, or its failure is understood.
- A child is born and taught a technique.
- Different camps meet and exchange something (teaching, gifts, trade) or come into understandable conflict.
- The authority benchmark stays within budget (216 and 2,000 characters, 60 Hz, no tick over 16.7 ms); LLM calls per minute and failures are reported.

## Out of scope for this checkpoint

Player-authored skills (Rhai authoring by characters with mastery, roadmap Stage 6), territorial and universal law editing (Stage 7), the faction seed (Stage 5), compute, and fabricated bodies.

## Evidence (2026-09-26)

**Deterministic mechanism checks** ([verify_mechanics.py](../living/tools/verify_mechanics.py), scripted graphs on a fresh database, real authority): all seven pass — a tablet written and handed over; reading it teaches its technique; the learner crafts with the learned technique; an atomic trade; teaching; planting; consensual conception beside a shelter.

**Live world `valley-5`** (12 people in three seeded communities plus two loners, 16 deer and 3 wolves, all with minds; Mistral Medium 3.5 / Mistral Small for people, `ministral-8b` feeling and `mistral-small` compiling for animals), observed through its first winter:

| Checkpoint question | Observed |
| --- | --- |
| A technique spreads beyond its camp and is used | Spread: Kael (Lake Folk) asked Nima (Ridge) and was taught torch-making. Not used: Kael starved before making one, and his know-how died with him. |
| A tablet changes what a reader does | Not autonomously: nobody wrote or visited the old sign during the run (the mechanism passes the deterministic check). |
| A winter survived through stores | All 11 remaining people survived winter (days 7–8) with seeded stores, fires and shelters; Kael had starved at the end of autumn after giving his food away (a legible choice he repeated for six decisions). Draws on stores are not recorded in the story feed, so reliance on stores is not measured. |
| A child is born and taught | Not autonomously (no couple chose it); the mechanism passes. |
| Camps meet and exchange | Yes: cross-camp teaching, gifts (Luma fed Iri repeatedly), a boundary ("Stay back, Kael. This is no place for outsiders"). |
| Authority within budget | 2,000 mind-controlled characters: p99 6.4 ms; 200-fighter battle: p99 6.4 ms, no tick over 16.7 ms. |

Understood causes and fixes made during the run: minds under constant survival pressure only talked logistics → seeded established camps, fire-shy wolves, gentler night cold, self-expressive speech; deer alarm spam fed a fear loop → signals follow novelty; animals were told people's names → animals perceive "a person"; small-model JSON slips → bounded repair; repeated identical lines and actions → suppressed or aggregated; a starving person beside a full store → a take-food reflex.

Open for later checkpoints: minds remain fear-dominated in a small world with few other stimuli; autonomous writing/reading, births and technique use did not occur within the observed days.
