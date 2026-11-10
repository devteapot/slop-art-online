# Dealings: a player's agreements and the demands on them

A player makes agreements and is told how they end through the same act path as minds (docs/WORLD_RULES.md). The rules' records are private; the player reads their own through `my_records` and what the rules told them through `my_experience`.

## Sub-features

- **Proposing.** `human_act` takes the node the client's verbs build for terms: `{"do": "offer_terms", "target": {"id": W}, "item": "berries", "qty": 1, "want": "wood", "want_qty": 1}` (the verbs test `to_a_person_i_offer_terms_and_make_demands`; the scene asks 2 wood). The act's outcome is the rules' own words ("Proposed to a stranger: you give 1 berries, they give 2 wood").
- **Reading the record.** The player reads the offered agreement in `my_records`, with role `from` and `to=W` among the others.
- **Accepted and owed.** The other side accepts and delivers. The player is told "accepted your terms", then "You owe them 1 berries by dusk".
- **Paying.** A `human_act` give pays. The player is told the agreement is kept on both sides, and `my_records` shows it `kept`.
- **Privacy.** `record` and `record_party` are private to the player and to an anonymous client.
- **A demand on the player.** The player is told of it. Unpaid, it falls due after 3 world hours under the world's own rules (90 s at the default day), and the player is told "You did not pay".

## How to get to it

```bash
$V launch --run player-deal-$S && $V doctor --run player-deal-$S
python3 .agents/skills/verify-player/scripts/deal.py --run player-deal-$S
$V cleanup --run player-deal-$S
```

Any seed works. The other side is a `spawn_crowd` walker driven by admin `mind_act` (as a mind would decide). The script joins a player if the run has none, places the walker beside it (`place_near`), grants berries and wood, and holds both on a `wait` graph (`set_behavior`). Name those admin calls in the report. Results: `RUN/deal.json`.

## Gotchas

- The demand's wait follows the world's `day_ms`; the script reads it and waits 3 world hours plus 15 s.
- A walker has no home, so the player's store deliveries are not driven here (verify-core `dealings` and Cargo cover a household's store).
