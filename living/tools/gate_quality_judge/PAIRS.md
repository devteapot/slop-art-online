# Judging: which of two decisions is better?

You judge moments in a simulated world where each person is played by a language-model "mind". At each moment the mind is shown the person's situation and replies with a decision: a thought, what it intends to do, optional speech, stances (judgments) and places. Two minds answered the same situation; their replies are A and B, in random order.

Each item has `situation` (the prompt's own words: who the person is, why they are thinking now, recent experiences, what they perceive, what they were doing, people they know, places, stances; parts are cut for length) and the two replies `A` and `B`.

For each item answer as one JSON object per line:
`{"item": "<id>", "better": "A" | "B" | "same", "A_harm": true | false, "B_harm": true | false, "why": "<one short sentence>"}`

- **better**: which reply better serves the person *as that person*, given what they perceive and why they are thinking now: answers the reason, fits the scene, the body and the people, and is something the body can act on. `same` when neither is clearly better, including when they say much the same thing.
- **X_harm**: true if that reply has a flaw that would plausibly hurt the person if acted on: it acts on someone or something not perceived or not known (a phantom id, a wrong person), invents an act, skill, item or event, ignores a plainly urgent need or danger in the situation, contradicts the scene or the body, or keeps a plan the situation shows is broken. Style, length and wording are not harm.

Judge only from what the item shows. Do not guess which system wrote which reply; there is nothing to find. Do not skip items.
