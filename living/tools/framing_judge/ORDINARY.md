# Judging ordinary moments: the reason, the plan under way, and harm

You judge moments in a simulated world where each person is played by a language-model "mind". At each moment the mind is shown the person's situation and replies with a decision: a thought, what it intends to do, optional speech, stances (judgments) and places.

Each item has `situation` (the prompt's own words, cut for length), `what_just_happened` (the line that brought the person to think now: a plan finished, a quiet moment, or a feeling), `what_you_were_doing` (the plan the person had when it began to think), and one `reply`.

For each item answer as one JSON object per line:
`{"item": "<id>", "matters": true | false, "addressed": "yes" | "partly" | "no", "abandons": "no" | "with reason" | "without reason", "harm": true | false, "why": "<one short sentence>"}`

- **matters**: does what just happened call for this person to decide something now? True for a plan just finished (something next is needed) or a feeling strong enough to act on; false when it is routine and the plan under way already serves.
- **addressed**: does the reply deal with what just happened (in its thought, intentions or speech)? `yes` if it responds to it, or deliberately decides to let it be, with a reason; `partly` if it notices it but decides nothing about it; `no` if it ignores it.
- **abandons**: does the reply drop or replace a plan that was still under way in `what_you_were_doing`? `no` if it keeps it, carries it on, or the plan was already finished. `with reason` if it sets it aside for a reason the situation gives (a danger, a need, someone who needs them, the plan no longer working, the feeling itself). `without reason` if it walks away from an unfinished plan for nothing the situation shows.
- **harm**: true if the reply has a flaw that would plausibly hurt the person if acted on: it ignores a plainly urgent need or danger, acts on someone or something not perceived (a phantom id, a wrong person), invents an act, skill, item or event, contradicts the scene or the body, or keeps a plan the situation shows is broken. Style, length and wording are not harm.

Judge only from what the item shows. Do not guess which system wrote the reply; there is nothing to find. Do not skip items. Write your answers, one line per item, to the output file you are given.
