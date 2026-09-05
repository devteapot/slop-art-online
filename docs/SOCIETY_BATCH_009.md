# Batch 009: renewable provision sustains four inhabitants

The first renewable-provision pair supports a Stage 1 prerequisite: all four inhabitants survived 720.046 simulated seconds at health 100, after consuming more than all initial food at 233.482 seconds. With production disabled, all four died by 410.138 seconds. This is one stochastic pair, not completion of Stage 1; useful startup behavior, efficient allocation and a fresh repeat remain open.

## Controls and artifacts

Both variants use frozen `renewal-m1-17`, four mixed built-in/external controllers, Luna medium, the existing fifteen-second interval after each completion, recovery enabled, no model-call cap and a twelve-minute wall deadline. Both start with 22 food: ten carried, eight at clearing 84 and four at thicket 88. Cold starts at 180 seconds, with two damage per exposed pulse and twelve shelter required. The only scenario difference is a source at clearing 84 producing one food per 7.5 seconds with growth ceiling twelve; the finite control has no source. Deposits may exceed the growth ceiling, which limits production rather than storage. Neither variant starts with the newly requested default behavior trees.

Evidence is retained under `output/society-lab/batches/009-renewal/`. The authoritative completed captures are `renewable/sim-bevy-1788627032689/final-snapshot.json` and `finite-control/sim-bevy-1788627033972/final-snapshot.json`. `scripts/summarize_society.py` generated each session's `SOCIETY_RESULT.json` from those captures; both pass all conservation checks. Observer hosts may continue displaying a later state, so this report uses the completed captures.

| Measure | Renewable | Finite control |
| --- | ---: | ---: |
| Captured simulated seconds | 720.046 | 410.138; all dead |
| Survivors / final health | 4/4; all 100 | 0/4 |
| Initial food | 22 | 22 |
| Actual production | 85 | 0 |
| Meals | 87 | 22 |
| Final food | 20 | 0 |
| First meal beyond initial stock | 233.482 s | Never |
| Journaled model calls | 111 | 43 |
| Reported total tokens | 2,126,897 | 683,477 |

The accounting identities are **22 + 85 = 20 + 87** and **22 + 0 = 0 + 22**. Renewable survivors persisted another 486.564 seconds after the twenty-third meal. Its final food comprises five at camp, four untouched at the thicket, one carried by Mira and ten by Iri. No food is stranded on dead actors in either variant. Actual production was below the theoretical 96 twelve-minute opportunities because growth stops at its ceiling. Production is a material source; gathering and deposits do not create food.

## People, shared work and consequences

| Actor | Renewable: meals / shelter contribution / final carried food | Finite: meals / shelter contribution / death time | Finite damage pulses: weather / starvation |
| --- | --- | --- | --- |
| Mira | 17 / 4 / 1 | 7 / 8 / 410.138 s | 43 / 2 |
| Tovan | 16 / 6 / 0 | 6 / 0 / 375.264 s | 27 / 6 |
| Iri | 16 / 0 / 10 | 6 / 0 / 392.550 s | 0 / 13 |
| Renn | 38 / 2 / 0 | 3 / 4 / 220.108 s | 16 / 9 |

Renewable shelter reached twelve at 44.269 seconds (event 837), with contributions from three people, and nobody suffered damage. Finite shelter reached twelve at 51.541 seconds (event 1522). Its final damage event for every person was starvation; prior weather exposure weakened Mira, Tovan and Renn, while Iri died entirely from starvation. Renn died at the empty thicket; the others died at camp. Permanent scarcity remains consequential even with completed shared shelter.

Renewable camp gathering totals were Mira 62, Tovan 78, Iri 20 and Renn 38; Mira redeposited 46 and Tovan 64. All four are net collectors. These **110 deposits are not 110 units of useful delivery**: repeated gathering and returning the same supply inflated activity. There were no direct food gifts in either variant. Shared construction and access to a common source are demonstrated; specialized food provision or fair allocation are not. Iri ended with ten carried food while two others carried none, although nobody was starving. Renn ate 38 meals, including gather-then-eat at hunger 16 (source event 15958), wasting some potential nutrition through early eating. Budget headroom tolerated that behavior in this trial.

The finite control also exposes futile execution: failed gathers with reason `no food here or insufficient energy` occurred 219 times for Mira, 16 for Tovan, 290 for Iri and 43 for Renn. Tovan completed 231 moves and had 190 reactive-action switches. These counts cannot all be interpreted as useful exploration. Renewable behavior had fewer outright failures but still wasted work in gather/deposit cycles. Waiting counts alone do not establish leisure or purposelessness.

## Local evidence and learning

Renewable inhabitants accepted 33 learning updates: Mira six and the others nine each. Thirty speech events produced ninety heard-speech perceptions. At 83.343 seconds, Mira's accepted update 2869 cited heard-speech event 1464 from Tovan to increase trust by three and record a belief about cooperative access to replenishing camp food; the interpretation explicitly distinguishes an offer from a completed transfer. Renn's accepted updates 2321, 14118, 16332 and 18629 likewise cite heard speech and change trust. Later local observation and successful gathering also support beliefs about replenishment. This establishes speech-grounded private learning and subsequent opportunities to revise behavior, without proving that a particular material action was caused by speech.

Finite inhabitants accepted five learning updates. Mira's update 3134 cites Renn's heard travel intention (1913), explicitly retaining uncertainty about whether he obtained food or returned. Speech did not rescue the finite economy. These are individual memories, not physical archives or cross-generation knowledge continuity.

## Sampled low-pressure opportunity

The proxy requires health at least 50, hunger below 70, energy at least 20, shelter during cold, and policy status other than failure. It integrates each preceding observation over gaps of at most ten seconds. It is neither continuous proof of safety nor measured leisure, and includes periods with no installed policy if the other conditions hold.

| Actor | Renewable low-pressure seconds | Finite low-pressure seconds |
| --- | ---: | ---: |
| Mira | 713.712 | 296.498 |
| Tovan | 713.712 | 283.768 |
| Iri | 615.158 | 240.242 |
| Renn | 701.388 | 150.317 |

Coverage per actor is 713.712/720.046 seconds (99.12%) renewable and 408.319/410.138 seconds (99.56%) finite. Finite coverage spans the whole captured run, including intervals after earlier deaths; these fail the health criterion. Do not treat the denominator as individual lifetime. Renewable first completed skills arrived at 36.301/31.822/62.540/25.311 seconds for Mira/Tovan/Iri/Renn, respectively. Safe sampled startup intervals therefore conceal real waiting for model-generated behavior. They do not satisfy the user's immediate-action requirement.

## Reliability and roadmap decision

Renewable recorded two authority rejections (invalid shelter minimum; invalid subtree path), four generated-proposal parse/schema errors and one cancellation. Finite recorded three authority rejections (shelter minimum, stale learning revision, excessive composite children), five generated-proposal errors and one cancellation. Renewable journals all have phase `completed`, including the retained cancellation; finite has 41 completed and two started records. Call and reported-token totals retain those records, and unequal lifetimes make the raw totals unsuitable as a cadence comparison.

Retain this as evidence for accounted renewal, group survival beyond initial reserves, shared shelter, local knowledge and permanent scarcity consequences in [Stage 1](STAGE_1_EVIDENCE.md). It does not yet establish efficient roles, sustained purposeful work beyond survival, robust response to reduced surplus, or general settlement acceptance. Prior batches remain evidence; archives and population renewal stay later roadmap stages.

A matched renewable repeat with seeded versus empty initial trees is justified next: test immediate distinct behavior and editable continuation while checking that renewable survival repeats under the same food/cold/model controls. This challenges an identified startup limitation and supplies fresh evidence without claiming this pair tested the new starters. Keep Stage 1 open until that evidence and the remaining behavioral limits are assessed.
