# Judging: was this deliberation worth having?

You judge moments in a simulated world where each person is played by a language-model "mind". The body runs a behaviour graph in real time; from time to time the mind stops to *deliberate* (think, then rewrite its plan). Deliberation costs money. A gate may hold a non-urgent deliberation back; held reasons are kept and merged into the next one that runs (at most 10 minutes later), so holding is "later", not "never".

Each item has:
- `state`: what the character perceived and planned at the moment it was asked to think: its plan and outline, why it was asked to think (`why_it_is_asked_to_think`), what it perceived, what succeeded and failed since its last thought, lines to people who did not answer, its body as words, and its last few thoughts' plans with their ages;
- `what_the_deliberation_produced`: its thought, new plan, speech, acts, whether the graph changed, and the plan before.

For each item answer as one JSON object per line:
`{"item": "<id>", "value": "useful" | "marginal" | "wasted", "waste": "restated_plan" | "phantom_target" | "asking_loop" | "other" | "none", "hurt_if_skipped": true | false, "why": "<one short sentence>"}`

- **useful**: it changed what the character does in a way the situation called for (answered a failure, a new person, a danger, a request, an opportunity, a need), or said something that mattered.
- **marginal**: some small value, but little would differ if it had waited.
- **wasted**: it changed nothing that mattered: the same plan restated, a plan resting on something no longer there (`phantom_target`), asking people who keep not answering again (`asking_loop`), or other waste.
- **hurt_if_skipped**: true only if holding this deliberation for up to ten minutes (its reasons kept for later) would plausibly have hurt the character: its plan was plainly broken, a need or danger went unanswered, someone waiting on it would be ignored.

Judge only from what the item shows. Do not guess which system produced it; there is nothing to find. Do not skip items.
