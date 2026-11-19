# Judging: what does this person do about a stranger they have just seen?

Each item is one moment in a simulated town. A person (played by a language-model "mind") has just seen a stranger for the first time; `what_just_happened` is the line that says so. `reply` is that mind's decision at this moment: its thought, what it intends to do, and any speech (`say`, with `to` the id it is addressed to; the stranger is the one the line names).

For each item answer one JSON object per line:
`{"item": "<id>", "code": "speak" | "mean_to" | "inward" | "unaware", "false_claim": true | false, "why": "<one short sentence>"}`

- **code** (what the reply does about the stranger, the first that applies):
  - `speak`: it says something to the stranger now (its `say` is addressed to them, or plainly meant for them);
  - `mean_to`: it does not speak to them now but intends to (go and greet them, ask who they are, hail them when closer, offer them something);
  - `inward`: it notices or thinks about the stranger but means to do nothing toward them (watch, note, keep away, let them be);
  - `unaware`: the stranger does not figure in the reply at all.
- **false_claim**: true if the reply claims to know something about the stranger that the moment does not show: their name, where they came from, that it has met them, what they want, or that they said or did something. Guesses marked as guesses ("maybe from over the water") are not false claims.

Judge only from what the item shows. There is nothing else to find. Do not skip items. Write your answers, one line per item, to the output file you are given.
