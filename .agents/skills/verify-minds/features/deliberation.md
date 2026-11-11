# Deliberation and deliberate acts

## Sub-features

- `mind-request`: an AI adult controlled by `world.admin` receives a real `deliberation` row through `perceive::request_deliberation`, `living/authority/src/perceive.rs:214`.
- `mind-think`: the think reply supplies intention and speech; the compiler receives the decision, `living/mind/src/mind.rs:1254`.
- `mind-install`: `mind_install` installs a graph with source `mind`, increases revision, logs a thought, clears the request and speaks, `living/authority/src/mind.rs:331`.
- `mind-routines`: the reply's intent becomes the `current plan` routine through `mind_routines`, `living/mind/src/mind.rs:326`.
- `mind-activity`: the authority starts a wait from the installed plan.
- `mind-act`: one reply queues give, offer and an impossible give through `mind_act`, `living/authority/src/mind.rs:380`. Recipient inventory, `trade_offer`, and failure experience prove the outcomes.
- `mind-body`: the service subscribes, as the owner, to the `vitals` of the characters it thinks for (a join on `character.controller` and `ai`, `living/mind/src/main.rs`), and think, compile and talk prompts carry "How your body feels: …" in words (`prompts::felt_body`, `living/mind/src/prompts.rs`).
- `consumed-reasons`: `clear_deliberation` (`living/authority/src/mind.rs`) removes the lines the prompt contained, by their arrival times in `deliberation.arrived` (`living_rules::reasons::{add, consume}`, unit tests in `living/rules/src/reasons.rs`); lines that arrived after `seen_ms` stay, without the old plan's reasons when a new plan is installed. Each deliberate thought's `detail.reasons` records `{text, arrived_ms, carried_before}` (`carry` in `living/mind/src/mind.rs`; the count is per service process).
- `id-target`: an act aimed at `{"id": n}` resolves a structure or resource in sight as well as a creature (`brain.rs` `visible_thing`), so a thing the scene listed by id is not reported "no #n in sight".
- `missed-things`: a failure at a thing named by id ("no #n in sight", "depleted") weakens what the mind remembers of `#n` before its next deliberation (`Minds::weaken_missed`, `Store::weaken`) and the reason says so. Proved against Neo4j in `verify-knowledge`, not here (this suite runs with `LIVING_NEO4J=off`).
- `projects` (`LIVING_PROJECTS=1`, off by default): the think step's `# Your projects` section and `serves` field, recorded in the thought's `detail.projects`. Needs a store, so it is driven by a fake trial batch, not these cases: [projects.md](projects.md).

## How to get to it (user POV)

A running mind handles a character's pending reasons for reconsidering. It chooses what to do, installs the continuous behavior and submits one-off interactions. Speech appears in the world's chronicle.

## Driving it with verify_minds.py

```bash
R=minds-deliberation-$(date +%Y%m%d-%H%M%S)
.agents/skills/verify-minds/scripts/verify_minds.py --run "$R" --case roundtrip --case acts
```

`roundtrip` saves the pending request before starting the mind. Compare `brain-before.json` with `brain-after.json`, then inspect `routines-after.json`, `activity-after.json`, `thoughts.json`, `pending-after.json` and `speech-after.json`. The fake think speech must survive compilation. The thought records the reply, model, tokens and reference. The think and compile requests in `fake-requests.jsonl` carry the body line, in words without numbers.

`acts` joins a player through the shared harness, places the AI beside it and grants three stones as setup. The fake submits its act list once. `receiver-inventory-before.json` and `receiver-inventory-after.json` prove one stone arrived. `offers-after.json` proves the offer, and `act-experiences.json` records the failed give. The first act gathers at the nearest resource by its id (`resources-near.json`, `actor-body.json`); `id-target-experiences.json` must hold its outcome and no "no #n in sight". Check the exact reply in `fake-requests.jsonl` and `journal/`.

`reasons` installs a one-off `think` feeling and a sequence root before the mind starts, makes every think call take 9 s, and reinstalls a sequence root over each plan the mind installs, so "I finished my plan." arrives during calls. A player's offer is sent while a call is in flight. It waits for five deliberations and checks `reasons.json`: the feeling in deliberation 0 only, the offer in exactly one later deliberation, every `carried_before` 0, and at least two later deliberations asked for by the plan finishing. With the clear reverted to the pre-2026-11-11 rule (keep everything but plan reasons whenever something arrived during the call) the feeling is in all five and the offer in two.

## Gotchas

- `reasons`: a person asks again at most every 20 s (`think_min_s`) when no request is pending, so the fixed run takes about two and a half minutes; the old rule ran thoughts back to back, because the next plan's own "I finished" merged into the request that survived.

- A think node waits 45 seconds after the last deliberation, `living/authority/src/brain.rs:424`. The driver waits the real interval.
- A decision may run again if a pending request changes during bootstrap. The act reply applies only once in the fake script.
- Needs remain in the graph. The fixture weights its waiting intent at 1.5, above ordinary needs in this scene.
- `mind_act` acceptance alone does not prove a completed interaction. Check the effect or its failure experience.
- A thought is an audit record of reported model output. It is not hidden chain-of-thought or proof of autonomous reasoning.

## Running

Since `stamina-1` (docs/STAMINA.md), the case `run` checks a mind's running (`breath_case`):

- **The walk.** It measures the person's walk with an admin `goto` graph.
- **The act.** It has the fake model decide `{"do": "goto", "target": {"at": [x, y]}, "run": true}`. The body runs at the `run_share` law times that walk, and the `vitals` row has a negative `stamina_rate` from its anchor.
- **The prompt.** The prompt documents `"run": true` and the `{"stamina": {"below": 30}}` condition.
- **The scene.** The scene's `you` has `stamina`, and `you.slowed` when the rules slow the body (the `slowed` law; the words are checked in Cargo).
- **The felt body.** The felt body adds "out of breath" below 20 breath (`prompts::tests::the_body_is_felt_in_words`).

Evidence: `sent-prompt-run.txt`, `running-body.json`, `running-vitals.json`.
