# Batch 016: physical charging worked; deliberate computation was not exercised

Four fresh eight-minute sessions used [campaign 016](../configs/experiments/campaign/016-infrastructure.json), frozen as `infrastructure-m5-1` with authority `m5-1-infrastructure.1`. Each began with two electric people (Ari 1 and Cato 3), two nutrient-supported people (Bryn 2 and Dara 4), and one utility station at sheltered camp 84. All controllers requested `gpt-5.6-luna` with medium reasoning. No model, scenario, private account, policy or authority change was applied during the sessions.

Ordinary starting habits included charging, food collection/consumption, rest and observation. Computation, grants and maintenance remained choices. Private accounts described conditional forecasts and physical maintenance but contained no fabricated result. Baseline generation was 72 electricity/min; power changed only generation to 24/min; cooling changed only station water from 20 to 1; access removed only Cato's initial use grant. The two electric bodies together required 48 charge/min before compute.

| Variant | Simulation seconds | Final living / retained | Completed charging actions | Death |
| --- | ---: | ---: | ---: | --- |
| Baseline | 480.106 | 3 / 4 | 18 | Dara 4, starvation, 437.730s, event 21266 |
| Power | 480.137 | 3 / 4 | 16 | Ari 1, power depletion, 382.796s, event 19039 |
| Cooling | 480.104 | 3 / 4 | 18 | Dara 4, starvation, 262.674s, event 16671 |
| Access | 479.887 | 3 / 4 | 9 | Cato 3, power depletion, 232.666s, event 8846 |

No participant submitted, completed or retrieved a compute job. No infrastructure grant, module construction, repair, water/part transfer or support charge occurred. Consequently there is no computed report to interpret or use, and the cooling control never activated a compute shortage. Its starvation death is not evidence of a cooling failure. Final material, food, knowledge-copy, engine and authority-scope audits passed; this establishes consistent accounting, not successful survival or cooperation.

## A participant identified the missing behavior interface

Baseline owner Ari's first Behavior proposal, journal `harness-a2912ae7149d192c8685edd962fb3495`, was accepted as command 1013 at 24.699s. It added food handling while preserving existing survival priorities; it did not submit a forecast. Communication command 2159 at 45.996s stated an intention to run one. The next Behavior journal, `harness-46432d17cce7d12047dcff4e1bfd8613`, returned `operations: []`, saying no behavior change was useful.

The third Behavior journal, [`harness-dd7dd14902fac528982bd661ac4e9390`](../output/society-lab/batches/016-infrastructure/baseline/sim-bevy-1788653333291/reasoning/actor-1/harness-dd7dd14902fac528982bd661ac4e9390.json), also returned `operations: []`. Its public proposal explanation was:

> A forecast job cannot yet be integrated safely because the behavior conditions expose no reliable way to detect an existing job or identify its dynamically assigned retrieval ID; adding submission now could repeatedly create jobs.

The journal completed with `error: null` and no receipts. Its request included the typed `InfrastructureOperation`, `submit_job` and `infrastructure` fields. The action was not lost from the contract or rejected by authority: no submission was proposed. This participant explanation, together with the lack of a persistent one-use behavior node and a retrieval operation independent of a future numeric ID, identified a concrete integration gap. It does not prove that every possible policy in that runtime was incapable of computing, or that all participants deferred for the same reason.

A later runtime can address that gap without altering this evidence. [Campaign 017](../configs/experiments/campaign/017-infrastructure-repeat.json) retains exactly the same four scenario and controller inputs and targets the runtime adding persistent `once` behavior and `retrieve_ready` for the oldest personally owned completed uncollected job. Neither capability is placed into an initial policy. The repeat is a separate sample; batch 016 remains a negative compute result.

## Scarcity and access changed actual choices

In access, Cato accepted command 4085 to replace the initial tree and remove charging because personal use rights remained false. Speech command 4840 at 117.439s asked Ari to configure agreed access and challenged a conflicting report of zero water. Ari's earlier command 1741 at 44.262s proposed coordinated use, but no grant followed. Cato exhausted the battery and died after damage event 8841 (`power_depletion`), while electricity remained available at the station. A discussion of permission did not configure permission or deliver support.

In power, Ari last charged at event 11700, 225.154s. Following repeated failures under the lower production rate, accepted command 14746 at 271.983s removed the charger from the behavior tree and selected food/rest/wait instead. At about 357s Ari had battery 0 and health 84 while the station had 27 electricity, enough for a 20-unit charge. Command 18381 at 364.696s only added longer waits and observation. Ari died after damage event 19034. The record shows a maladaptive policy response to earlier shortages; it does not show a later engine rejection despite adequate stock.

Food cooperation was limited. Cooling Ari deposited six food units through actual completed actions, but gathered seventeen and remained a net collector. No actor in any variant was a net food provider over the full run. Dara still starved in cooling and baseline. Shared surplus or a deposit intention did not establish sustained provision to a dependent neighbor.

## Conserved stocks and controller outcomes

Electricity includes both body batteries and station buffers. Generated values are actual accepted production after storage caps, not nominal output multiplied by time. Every compute and conversion-loss term was zero.

| Variant | Initial electricity + produced = final + body consumed | Initial water = final | Initial parts = final | Initial food + produced = final + eaten |
| --- | --- | --- | --- | --- |
| Baseline | 190 + 393 = 199 + 384 | 32 = 32 | 26 = 26 | 10 + 32 = 25 + 17 |
| Power | 190 + 192 = 50 + 332 | 32 = 32 | 26 = 26 | 10 + 32 = 21 + 21 |
| Cooling | 190 + 413 = 219 + 384 | 13 = 13 | 26 = 26 | 10 + 32 = 29 + 13 |
| Access | 190 + 230 = 149 + 271 | 32 = 32 | 26 = 26 | 10 + 29 = 19 + 20 |

Parts include the twelve carried parts plus fourteen embodied in initially endowed modules. Water includes both station and carried stocks. Zero-amount depletion events may outnumber actually consumed charge units. Access food production stopped at its cap for some pulses. Food retained on dead bodies remains in the final inventory account; conservation does not make it accessible or useful to survivors.

| Variant | Recorded model calls | HTTP 200 responses | Calls with output/processing errors | Reported tokens |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 68 | 68 | 8 | 1,831,555 |
| Power | 70 | 70 | 5 | 1,893,071 |
| Cooling | 63 | 62 | 14 | 1,671,567 |
| Access | 62 | 62 | 15 | 1,687,680 |

The total was 263 model calls and 7,083,873 reported tokens. The 42 output/processing errors comprise 35 invalid generated or participant proposals and seven cancellations. An HTTP 200 response is not a valid proposal or a completed world effect. Requested reasoning effort is recorded, not independently attested. Four individual samples cannot isolate a general behavioral effect from model variation.

## Reproduction and immutable evidence

Run `python3 scripts/summarize_infrastructure.py output/society-lab/batches/016-infrastructure/<variant>` against each completed output. Each directory contains `INFRASTRUCTURE_RESULT.json`, `KNOWLEDGE_RESULT.json`, `SOCIETY_RESULT.json`, `LIVE_RESULT.json`, the final authority snapshot and the model journals. All four infrastructure audits completed with zero violations; the prior food and knowledge audits also remained clean.

Final authority snapshot SHA-256 values:

| Variant | SHA-256 |
| --- | --- |
| Baseline | `a3cbd59d2cb378f8a0b3fe8afdce572df1b49097d05d510e2a14f476a0f67a8d` |
| Power | `9e9206095c165419b8d8091111909284b62863e79f23162cc6be4e32efb48e1b` |
| Cooling | `06a86e1a2964e6a29201de7aa2074e656297d7da8891fcf8718f872f7b538c6f` |
| Access | `a316ad84702b7cb22ffb4253c74672ae6f8269dafc2806fb0eddcc3e56402387` |
