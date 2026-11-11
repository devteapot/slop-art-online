# Dealings: a mind sees and acts on a record

The world's records (docs/WORLD_RULES.md) reach a mind as perception and as its own dealings, never as table reads of other characters' records.

## Sub-features

- **Told and asked.** A demand on the mind's character is told to it (an experience of kind `record`), and the rules' `ask` requests a deliberation.
- **Shown.** The deliberation prompt has a dynamic section "Your dealings and your people's standing", worded by the script's `record_text` and named as the character knows the people in it (`mind/src/mind/dealings.rs`). The talk turn lists the same character's dealings with the other person among its "between" lines. Talk-marked acts the examples do not show (`offer_terms`, `demand`, `welcome`) are listed from the specs (`prompts::talk_acts`).
- **Acted on.** The fake model's deliberate reply carries `{"do": "give", ...}`. The act goes through `mind_act`; the rules' `on_give` counts it, the demand is `met`, the demander is told it was paid, and the demander's pack holds the stone.

- **Answers by id** (`answers` case; since `rules-offers-2`). The second adult proposes terms and offers a trade before the mind starts. The deliberation shows the trade's id in the scene's "asked of you" (`"offer": N`) and the proposal's id in its dealings ("accept or decline (toward them, record N)"); the fake rule matches that record text and replies with two acts, `{"do": "accept", "target": {"id": other}, "offer": N}` and `{"do": "decline", "target": {"id": other}, "record": M}`. The trade is taken (the wood arrives) though the terms stood, the record is `declined`, and the proposer is told "… declined your terms: …".

## How to get to it

```bash
R=minds-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case dealings
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R-a" --case answers
```

The fake rule matches a deliberate request containing "demanded 1 stone of you", so the reply that pays is sent only when the prompt showed the demand. The demand itself is an admin `mind_act` of the second adult, as its own mind would decide.

## Gotchas

- The rules' `ask` goes through the authority's thinking cadence (`perceive::request`: a person who deliberated within the species' `think_min_s` gets no new request unless it is urgent), as an offer's does. Right after the mind service starts, the ask is usually dropped. The case then requests the next thought itself (`asked_by_the_rules` in `result.json` says which), and that thought shows the demand among the character's dealings.
- The fake rule matches the dealing's own words, including the quoted reason between "stone" and "of you".
- Both adults are held (`wait`) before the demander is placed, as in `answers`: on the default world the first adult is a guard who walks to the north gate at the start, and an unheld demander wanders to the berry bushes while the mind service starts. A `demand` refused with "no #1 in sight" means the demander could not see the other when it acted (its experiences are kept as `demander-experiences.json`).
- Beside a guard standing in a gateway, `place_near`'s nearest free tile is diagonal, across the wall's end. Sight across one wall's corner is clear both ways since fix-dealings (2026-11-11, `Map::sight_walk`); before, the demander there could not see the guard although the guard saw it.

- `record` and `record_party` are subscribed whole by the mind service (as the owner, like `trade_offer`); a character is shown only the records it or its community is a party to.
- Regard shows in the same section on an island world (its seeded stances); the default world has none.
