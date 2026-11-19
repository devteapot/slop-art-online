# Making at a workplace that burns fuel

Rules: [docs/WORLD_RULES.md, "Goods, recipes and fuel" and "What a client shows (goods-2)"](../../../../docs/WORLD_RULES.md#what-a-client-shows-goods-2). Added 2026-11-11 on `goods-2`.

## Sub-features

- **The authority sees the fire.** A player's `human_act` toward a furnace (`{"do": {"skill": "make", "item": "glass", "target": {"nearest": "furnace"}}}`) is checked on the authority's facts of it: `lit` and `fuel` from `structure.lit_until_ms` (`act::target_facts`, `fire_state`).
- **Refusals with the rules' reasons**, in the player's own `my_experience`: out ("the furnace is out: feed it first"); fed but holding less than the recipe's heat ("has too little fuel left for it (it takes 1, it has 0.99): feed it first"). Nothing is taken from the pack.
- **Made once fed:** one ash and two sand become one glass; the furnace's `lit_until_ms` falls by one unit's burn (40 s on Cullet's day); "You did what you had decided: make glass → furnace (+1 glass)."
- **Seen at work** (`make_shows`, `feed_shows`): while the player feeds or makes, a `doing` row with the skill's `act_card` code stands at the furnace's position, and is gone when the work is done.

## How to get to it

```bash
P=player-$(date +%m%d-%H%M%S)
$V launch --run $P --seed cullet-laws && $V doctor --run $P
.agents/skills/verify-player/scripts/workplace.py --run $P   # writes $P/workplace.json
$V cleanup --run $P
```

The script joins the player if it has no living character. Admin reducers set the scene only: `grant_know_how` (fire, glassmaking), `grant_items` (1 ash, 2 sand, 6 peat), `place_structure` (the furnace, 0.8 m east of the player).

## Gotchas

- **No offered-acts list on the authority.** What the game client offers (its F list) comes from the rules' `_check` run on facts the client builds (`living/game/src/verbs.rs`). Today that client leaves a structure's `lit` and `fuel` at their defaults, so it never offers `make` at a fire that burns fuel; the authority accepts the act. What a client must pass is in docs/WORLD_RULES.md ("Make at a fuel-burning workplace").
- A feed lasts 1.5 s: the script polls `doing` every 50 ms over HTTP to catch it.
- A unit of fuel starts burning down at once: fed exactly one unit, the furnace holds 0.99 by the time the next act is checked, which is what the "too little fuel" refusal uses.

## Not covered

- The game client's own offering (that is `verify-ui`, after the client passes the facts).
- Other workplaces (hearth, oven, smokehouse) and recipes that `turns`: rules test `goods_are_data_matched_by_trait_and_fires_eat_fuel`.
