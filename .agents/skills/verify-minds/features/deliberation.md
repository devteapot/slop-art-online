# Deliberation and deliberate acts

## Sub-features

- `mind-request`: an AI adult controlled by `world.admin` receives a real `deliberation` row through `perceive::request_deliberation`, `living/authority/src/perceive.rs:214`.
- `mind-think`: the think reply supplies intention and speech; the compiler receives the decision, `living/mind/src/mind.rs:1254`.
- `mind-install`: `mind_install` installs a graph with source `mind`, increases revision, logs a thought, clears the request and speaks, `living/authority/src/mind.rs:331`.
- `mind-routines`: the reply's intent becomes the `current plan` routine through `mind_routines`, `living/mind/src/mind.rs:326`.
- `mind-activity`: the authority starts a wait from the installed plan.
- `mind-act`: one reply queues give, offer and an impossible give through `mind_act`, `living/authority/src/mind.rs:380`. Recipient inventory, `trade_offer`, and failure experience prove the outcomes.

## How to get to it (user POV)

A running mind handles a character's pending reasons for reconsidering. It chooses what to do, installs the continuous behavior and submits one-off interactions. Speech appears in the world's chronicle.

## Driving it with verify_minds.py

```bash
R=minds-deliberation-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case roundtrip --case acts
```

`roundtrip` saves the pending request before starting the mind. Compare `brain-before.json` with `brain-after.json`, then inspect `routines-after.json`, `activity-after.json`, `thoughts.json`, `pending-after.json` and `speech-after.json`. The fake think speech must survive compilation. The thought records the reply, model, tokens and reference.

`acts` joins a player through the shared harness, places the AI beside it and grants three stones as setup. The fake submits its act list once. `receiver-inventory-before.json` and `receiver-inventory-after.json` prove one stone arrived. `offers-after.json` proves the offer, and `act-experiences.json` records the failed give. Check the exact reply in `fake-requests.jsonl` and `journal/`.

## Gotchas

- A think node waits 45 seconds after the last deliberation, `living/authority/src/brain.rs:424`. The driver waits the real interval.
- A decision may run again if a pending request changes during bootstrap. The act reply applies only once in the fake script.
- Needs remain in the graph. The fixture weights its waiting intent at 1.5, above ordinary needs in this scene.
- `mind_act` acceptance alone does not prove a completed interaction. Check the effect or its failure experience.
- A thought is an audit record of reported model output. It is not hidden chain-of-thought or proof of autonomous reasoning.
