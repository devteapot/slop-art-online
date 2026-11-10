# Dealings: a mind sees and acts on a record

The world's records (docs/WORLD_RULES.md) reach a mind as perception and as its own dealings, never as table reads of other characters' records.

## Sub-features

- **Told and asked.** A demand on the mind's character is told to it (an experience of kind `record`), and the rules' `ask` requests a deliberation.
- **Shown.** The deliberation prompt has a dynamic section "Your dealings and your people's standing", worded by the script's `record_text` and named as the character knows the people in it (`mind/src/mind/dealings.rs`). The talk turn lists the same character's dealings with the other person among its "between" lines. Talk-marked acts the examples do not show (`offer_terms`, `demand`, `welcome`) are listed from the specs (`prompts::talk_acts`).
- **Acted on.** The fake model's deliberate reply carries `{"do": "give", ...}`. The act goes through `mind_act`; the rules' `on_give` counts it, the demand is `met`, the demander is told it was paid, and the demander's pack holds the stone.

## How to get to it

```bash
R=minds-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case dealings
```

The fake rule matches a deliberate request containing "demanded 1 stone of you", so the reply that pays is sent only when the prompt showed the demand. The demand itself is an admin `mind_act` of the second adult, as its own mind would decide.

## Gotchas

- `record` and `record_party` are subscribed whole by the mind service (as the owner, like `trade_offer`); a character is shown only the records it or its community is a party to.
- Regard shows in the same section on an island world (its seeded stances); the default world has none.
