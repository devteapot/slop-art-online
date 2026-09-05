# Batch 014: supported learning and population choices

Four fresh twelve-minute sessions ran frozen `population-m3-2` (`m3-2-perceived-care.1`) under [campaign 014](../configs/experiments/campaign/014-population-repeat.json). The implementation fixes retained-observation target validation and preserves behavior, communication and learning schedules under controller errors. It also clarifies canonical policy-patch paths. Creation costs, care, development and ordinary survival habits remain unchanged.

## Outcomes

| Variant | Final living / retained | Creation and development |
| --- | --- | --- |
| Reproduction repeat | 4 / 4 | No offers or birth; discussion and delay |
| Extra parental reserves | 4 / 4 | No offers or birth; one other resident lost 16 health to starvation |
| Fabrication repeat | 5 / 5 | Newcomer at 281.742s; health 100, eleven care meals, still dependent |
| Fabrication with scheduled actor 3 loss | 4 / 5 | Newcomer at 66.724s; health 100, fourteen care meals, guided practice and self-support at 640.936s |

All variants reached about 720 simulation seconds in 722–726 wall seconds. Engine, authority scope, knowledge-copy and food conservation checks were clean. Fresh model outputs remained fallible. No condition forced a family, caregiver, teaching event or successful policy.

Extra reserves increased only actors 1 and 2's initial carried food from four to six each relative to the reproduction repeat. Neither reproduction sample completed offers. Recorded speech explicitly distinguished discussion from consent, and participants continued considering reserves and care arrangements. Those decisions are not evidence of a rejected mechanical attempt. The earlier interrupted biological creation and deterministic completion/consent controls remain the evidence for that pathway.

## Actual learning chain

In the scheduled-loss variant, actor 2 provided meals at 88.035s and 94.961s. Actor 1 later provided eleven meals and actor 4 one. These were real consumed food units, and the newcomer avoided starvation damage.

At 106.413s, Tovan's guidance speech event 5417 produced the newcomer's perception 5421. At 134.946s, the newcomer personally interpreted that experience and created `assertion-5-6918`, a typed report about cell 84, in event 6918 with its own receipt 6919. It also formed other personal accounts. This is learning from communicated guidance and personal interpretation, not inherited knowledge or a forced transfer of the initial teacher's report.

Several proposed practice trees were malformed JSON. Independent comparison of the retained SSE content and saved model output showed matching text, completed streams and no truncation: the errors were generated punctuation or proposal structure, not transport escaping. They were rejected unchanged. Scheduled communication and learning still ran between failed behavior calls. This is a live check that the recovery scheduler no longer consumes those opportunities.

A valid practice policy was finally accepted in event 32373. At 640.936s, event 32547 removed one real site food; practice event 32548 cited the interpreted report and guide 2. Event 32559 then recorded self-support, citing the actual care and practice evidence. The newcomer had age 574.212s, fourteen care meals and one completed practice. It ate that gathered food at 661.793s, event 33368. The chain therefore includes a material result used for its own body support, beyond a claim or status flag.

Actor 3 died at 500.031s, event 27361, before this development. It held the original camp report but had supplied no actual care in this repeat; other caregivers completed meals first. This is continuity after an experienced resident/report holder's death. It is not a demonstrated loss of the newcomer's established primary caregiver, and no automatic transfer of actor 3's private report occurred.

After gaining capability, the existing practice branch was no longer applicable and failed 128 times. A later learning call acknowledged that change and created report 34905. The next behavior call began at 713.086s but was incomplete when the experiment ended. The newcomer finished healthy with food zero and hunger 47. No ordinary independent `gather` was observed afterward. This establishes acquired capability, actual guided food production and consumption; it does not establish a reliable autonomous provisioning habit or long-term population stability.

The other fabricated newcomer received eleven meals from creator 1 and stayed healthy. It acquired a personally interpreted account of guidance late, but completed no practice before the endpoint. That difference remains a result rather than an assumed success.

## Accounting and inference

| Variant | Initial + produced food | Final + eaten + lifecycle costs | Model calls |
| --- | --- | --- | --- |
| Reproduction repeat | 24 + 71 | 30 + 65 + 0 | 109 |
| Extra parental reserves | 28 + 66 | 29 + 65 + 0 | 113 |
| Fabrication repeat | 28 + 82 | 27 + 66 + 17 | 116 |
| Scheduled actor 3 loss | 28 + 82 | 29 + 61 + 20 | 119 |

Fabrication costs six food in each creation; remaining lifecycle consumption is care. The practice harvest moves food from site to inventory, then ordinary eating consumes it; it is not extra production. Actual regrowth differs from nominal capacity because full sites discard growth opportunities.

The fabrication-repeat newcomer made sixteen model attempts, fifteen HTTP-successful calls, and eleven calls without a top-level error, reporting 377,551 tokens. The scheduled-loss newcomer made twenty-two attempts, twenty-one HTTP-successful calls and fifteen without a top-level error, reporting 564,839 tokens. These totals do not imply accepted commands: report fields separately retain command receipts, rejected operations, malformed proposals and the final incomplete calls.

## Retained evidence

Evidence is under `output/society-lab/batches/014-population-repeat/`, including complete authority snapshots, model journals, and the population, knowledge, society and scope reports. The manifest retains frozen implementation/input hashes. Final snapshot SHA-256 values:

| Variant | SHA-256 |
| --- | --- |
| Reproduction repeat | `088cffb8e13aa26bfdfcf924526d9369a4774dd5abf06660fc85548af0a49286` |
| Extra parental reserves | `6038dbe1b8a4a991820126862825e257aaf8381439f20e61e126c84736c4680e` |
| Fabrication repeat | `d3dac2eb4515be843368ba2864190998b938d205f1835cc04544255231ae27fe` |
| Scheduled loss | `d111b580e0645a1f3dad835094681a0e328f0ff129fa5259dfab94535dfeb1b4` |
