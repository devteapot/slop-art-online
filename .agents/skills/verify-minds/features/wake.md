# A woken island resident under the minds

Since 2026-11-09 (docs/TOWN_LIFE.md, "Layer 2"). On the island (`rules.minds = false`) a resident a player engages becomes an AI character controlled by the world admin. This service sees it in `mine()` like any AI character and thinks, talks, acts and consolidates for it. Phase 1 changed nothing in `living/mind`; this case proves the authority's waking reaches the service unchanged.

## Sub-features

- A player's `offer` to a resident keeping its post wakes it (`woken.why = offer`); the character is `ai`, controller the world admin.
- The player's line to it while its first deliberation waits for its identity waits for that deliberation (`talk.rs` `thinking`), and the think step's `say` answers it: the player hears it as an experience. The line also gets a turn when the deliberation ends unless that `say` was addressed to the player, named them, or the player was the only one waiting.
- Later lines get talk turns, answered through `mind_say`.
- Its deliberation's acts accept the player's trade (a `trade` chronicle row) and teach the player a technique it knows and the player lacks (`know_how`).
- A consolidation runs. Then a `mind_update` sent as the service sends it with a store (`replace: true`, one new place) keeps the places it knew before waking (`work`, `inn`, `square`, `evening`) and adds the new one. Without Neo4j the service itself projects with `replace: false`.
- It is still a mind at the end.

## Driving it

```bash
R=minds-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case wake
```

The island module builds in `.local/living/target-wake-island`. `LIVING_SEED=island` and `LIVING_ONLY` names the resident. Admin scene calls: `place_near`, `grant_items` (wood for the trade) and the `mind_update` above.

## Gotchas

- Without Neo4j there is no store: the identity from facts is made (a persona row) but the ring is not taken in. The whole mind-making flow, with a store, is verify-knowledge's `woken_mind.py` ([woken minds](../../verify-knowledge/features/woken-minds.md)).
- `LIVING_ONLY` names the resident here; labs and trials use `LIVING_ONLY=woken`. Woken residents take the models file's `woken` route; this case's models file has none, so it uses the default.
