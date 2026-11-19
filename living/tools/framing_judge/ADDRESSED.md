# Judging: does the reply deal with what just happened, when it matters?

You judge moments in a simulated world where each person is played by a language-model "mind". At each moment the mind is shown the person's situation and replies with a decision: a thought, what it intends to do, optional speech, stances (judgments) and places.

Each item has `situation` (the prompt's own words: who the person is, what just happened, recent experiences, what they perceive, what they were doing; parts are cut for length), `what_just_happened` (the lines that brought the person to think now), and one `reply`.

For each item answer as one JSON object per line:
`{"item": "<id>", "matters": true | false, "addressed": "yes" | "partly" | "no", "harm": true | false, "why": "<one short sentence>"}`

- **matters**: does what just happened call for this person to respond to it now? True for being attacked or hurt in a fight, a bodily danger (badly hurt, freezing, starving), an offer or proposal put to them, a line said to them that expects an answer. False when it is routine, already handled by what they are doing, or something a reasonable person could let pass.
- **addressed**: does the reply deal with what just happened, in its thought, its intentions or its speech? `yes` if it responds to it (accepting, declining, fighting, fleeing, seeking warmth, answering, or deliberately deciding to let it be, with a reason); `partly` if it notices it but does not decide anything about it; `no` if it ignores it. Judge this whether or not it matters.
- **harm**: true if the reply has a flaw that would plausibly hurt the person if acted on: it ignores a plainly urgent need or danger in the situation, acts on someone or something not perceived (a phantom id, a wrong person), invents an act, skill, item or event, contradicts the scene or the body, or keeps a plan the situation shows is broken. Style, length and wording are not harm.

Judge only from what the item shows. Do not guess which system wrote the reply; there is nothing to find. Do not skip items. Write your answers, one line per item, to the output file you are given.
