# An island resident under the minds

Every person has a mind from the start (2026-11-11; the woken mechanism and `rules.minds = false` are gone). On the island a seeded resident is an AI character controlled by the world admin from world creation. This service sees it in `mine()` like any AI character and thinks, talks, acts and consolidates for it.

## Sub-features

- A resident keeping its post is `ai`, controller the world admin, before anyone engages it, and has given places (`place.given`: work, inn, square, evening).
- A player's `offer` asks its mind (`offers you` in its deliberation reason).
- The player's line to it while it deliberates is left to that deliberation (`talk.rs`), and the think step's `say` answers it: the player hears it as an experience.
- Later lines get talk turns, answered through `mind_say`.
- Its deliberation's acts accept the player's trade (a `trade` chronicle row) and teach the player a technique it knows and the player lacks (`know_how`).
- A consolidation runs. Then a `mind_update` sent as the service sends it with a store (`replace: true`, one new place) keeps its given places and adds the new one. Without Neo4j the service itself projects with `replace: false`.

## Driving it

```bash
R=minds-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case resident
```

The island module builds in `.local/living/target-resident-island`. `LIVING_SEED=island` and `LIVING_ONLY` names the resident, so the other 276 residents live on their starting ways with a deliberation pending. Admin scene calls: `place_near`, `grant_items` (wood for the trade) and the `mind_update` above.

## Gotchas

- Without Neo4j there is no store: the authored sheet's persona row is published directly. The store-backed install (world facts marked `world`, the sheet `authored`) is [lives-mind](lives-mind.md) and verify-knowledge's `facts_mind.py` ([facts minds](../../verify-knowledge/features/facts-minds.md)).
