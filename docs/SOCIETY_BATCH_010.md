# Batch 010: immediate seed habits and a renewable repeat

Both twelve-minute renewable settlements retained all four inhabitants after consuming more than their entire starting food supply. Seeded actors all finished at health 100 and acted at the first update, 52 milliseconds after startup. The empty-start repeat finished at health 98/2/20/100, with startup failures and unnecessary exposure causing lasting harm. Together with [009's renewable and finite-control pair](SOCIETY_BATCH_009.md), this supports bounded Stage 1 viability and the requested immediate-action mechanism. It does not prove indefinite stability or complete later roadmap stages.

## Controls and final captures

`starters-m1-18` runs the same four Luna medium controllers, fifteen-second post-completion interval, recovery setting, no model-call cap and twelve-minute wall deadline in both variants. Both start with 22 food, the same unfinished camp shelter and cold conditions, and a renewing source at clearing 84: one unit per 7.5 seconds, growth ceiling twelve. Only `starting_behaviors` differs. Initial roles are authored, revisable habits, not emergent specialization or scripted model choices.

The batch is retained at `output/society-lab/batches/010-seeded-starts/`. This report and each `SOCIETY_RESULT.json` use completed captures `seeded/sim-bevy-1788627890983/final-snapshot.json` and `empty-repeat/sim-bevy-1788627892470/final-snapshot.json`, not later observer state. Engine, scope and conservation checks report no violations. Model decisions remain stochastic; this is a controlled fresh comparison, not an identical model replay.

| Measure | Seeded | Empty repeat |
| --- | ---: | ---: |
| Captured simulated seconds | 720.306 | 720.114 |
| Survivors | 4/4 | 4/4 |
| Initial food | 22 | 22 |
| Actual production | 68 | 90 |
| Meals | 65 | 68 |
| Final food | 25 | 44 |
| First meal beyond initial stock | 270.174 s | 275.174 s |
| Journaled model calls | 114 | 88 |
| Reported total tokens | 2,165,050 | 1,627,366 |

Accounting holds: **22 + 68 = 25 + 65** and **22 + 90 = 44 + 68**. The full groups persisted for another 450.132 and 444.940 seconds after their twenty-third meals. Seeded final food is twelve at camp, four at the untouched thicket and nine carried; empty final food is seven at camp and 37 carried. Production differences reflect actual collection and time at the growth ceiling, not different source configurations. All carried food remains on living actors.

## Startup and evolving trees

| Actor / initial habit | Seeded first completed skill | Empty first completed skill | Seeded model evolution |
| --- | --- | --- | --- |
| Mira / builder | Build, 0.052 s | Build, 56.919 s | Retained until first patch at 365.623 s; further patch at 443.722 s; replaced at 656.919 s |
| Tovan / reserve keeper | Gather, 0.052 s | Gather, 24.509 s | Replaced at 29.223 s to add shelter construction |
| Iri / shared provider | Observe, 0.052 s | Eat, 124.771 s | Replaced at 19.024 s; five later accepted patches |
| Renn / cautious observer | Gather, 0.052 s | Gather, 32.249 s | Retained until reserve patch at 246.087 s; never fully replaced |

All four seed policies installed at time zero and completed their first action at update one, before their first model response or model-installed policy. For example, Renn's first external behavior call finished roughly 7.5 wall seconds after launch and explicitly chose to keep his working habit unchanged. Mira and Renn's unchanged-policy decisions are affirmative model choices recorded in their journals, not evidence that their controllers stopped. Empty first policy installations arrived at 56.808/24.445/124.580/32.183 seconds. Iri's invalid early proposals left six carried meals unused until she had suffered ten starvation pulses, permanently reducing health to twenty.

Replacement remains consequential. Iri's first generated tree inverted the shelter guard and produced 48 failed builds after shelter was complete. Three patches under `root/2/guard` retained contradictory enclosing conditions; replacing `root/2` at 387.210 seconds finally removed that structural mistake. Mira's first patch similarly put a hunger-55 guard inside the existing hunger-60 guard, so the intended earlier meal did not occur. Valid installation does not guarantee the model's intended semantic change. These ineffective patches are retained evidence, not silently repaired.

## Material work, survival and recurring behavior

| Actor | Seeded health / meals / shelter contribution / final carried food | Empty health / meals / shelter contribution / final carried food |
| --- | --- | --- |
| Mira | 100 / 16 / 11 / 2 | 98 / 16 / 3 / 8 |
| Tovan | 100 / 16 / 1 / 4 | 2 / 16 / 0 / 22 |
| Iri | 100 / 16 / 0 / 2 | 20 / 15 / 0 / 7 |
| Renn | 100 / 17 / 0 / 1 | 100 / 21 / 9 / 0 |

Seeded shelter reached twelve at 29.312 seconds (event 1521), compared with 64.976 seconds (2166) empty. Mira's starter built eleven units; Tovan's model replacement added the last unit. This is authored initial work followed by a model choosing additional shared work. All four benefited from the finished shelter, renewable food access and self-care. No seeded actor took damage. Empty Mira took one weather pulse, Tovan 49 weather pulses, Iri ten starvation pulses, and Renn none. No deaths occurred.

Seeded actors gathered 64 units total and made no deposits or direct gifts. The empty repeat recorded 91 Iri deposits and 26 Tovan deposits, but both were net collectors at camp; these are substantial recycling counts, not 117 units of net delivery. It also recorded 268 failed gathers (`no food here or insufficient energy`), 143 Tovan moves and 237 Iri observations. High counts alone are not useful progress. The seeded run avoids gather/deposit recycling, but does not establish a transport economy or equal allocation. Material transport and beneficiaries remain demonstrated by [006](SOCIETY_BATCH_006.md) and [007](SOCIETY_BATCH_007.md); every batch need not recreate that mechanism.

## Concrete learning, chosen waiting and speech effects

Renn's accepted learning 10464 at 220.839 seconds cites successful eating (9374), gathering (9445), renewal observation (9742) and Tovan's heard speech (9541). His next behavior journal, `live-inference/actor-4/10-behavior/external.json`, chooses to maintain the effective camp routine while raising his carried reserve from one to two. Accepted patch 11536 at 246.087 seconds replaces `root/3`. At 246.503 seconds it interrupts an ongoing wait and completes gather 11550, changing food from one to two at hunger 31. The trace proves that the starter is editable, prior learning is available for deliberation, and the selected revision changes actual action. It does not isolate speech as the cause of the reserve change.

Purposeful quiet time has stronger evidence than counters. Renn's behavior journals 07, 13 and 16 explicitly retain observing and waiting because camp is sheltered and replenishing, with existing guards for food and energy. Actual wait 11429 completes at 244.258 seconds with food one, energy 52 and hunger 29; he then changes the reserve target as described above. This is bounded monitoring and self-care opportunity under viable conditions.

Mira's accepted learning 18628 at 413.486 seconds cites camp renewal (17309), successful reserve refill (18057) and hunger rising during waiting (17778). Patch 19842 at 443.722 seconds explicitly replaces repetitive observation/waiting with longer waits while retaining self-care. Hunger interrupts that wait: eat 19890 completes at 445.228 seconds, gather 19950 restores two carried meals at 446.054, and longer wait 20341 completes at 456.957 with energy 52 and hunger 34. Iri makes a similar longer-wait revision at 462.771. These are chosen adjustments with subsequent execution, not claims of new research or open-ended projects.

Seeded inhabitants spoke 34 times, heard 102 speech perceptions and accepted thirty learning updates. A specific speech-to-choice trace appears in Renn's `08-communication/external.json`: its reported reason is to acknowledge Mira's coordination, followed by accepted speak command 9033 and speech at 189.175 seconds: “Understood. Camp stores are full and renewing; I’ll stay here, monitor supplies, and gather when the reserve drops.” His earlier learning 7216 explicitly cited Mira's heard report (5141) and increased trust. This supports chosen conversational response and speech-grounded private state; it does not prove that a later material transfer happened because of that speech. Empty inhabitants spoke ten times and accepted fifteen learning updates, with Iri accepting none. Prior speech and material-interaction evidence remains cumulative.

## Sampled opportunity and reliability

The low-pressure proxy requires health at least 50, hunger below 70, energy at least 20, shelter during cold, and policy status other than failure. It integrates the preceding observation over gaps no longer than ten seconds. It measures sampled opportunity, not continuous leisure, and can count startup intervals with no installed policy.

| Actor | Seeded low-pressure seconds | Empty low-pressure seconds |
| --- | ---: | ---: |
| Mira | 708.933 | 627.085 |
| Tovan | 712.864 | 467.772 |
| Iri | 712.864 | 61.472 |
| Renn | 712.864 | 705.855 |

Coverage is 712.864/720.306 seconds (98.97%) per seeded actor and 713.535/720.114 seconds (99.09%) per empty actor. Iri's low empty value primarily reflects permanent startup damage, despite later successful provision. Concrete waiting/response traces above supply the interpretation the proxy cannot provide by itself.

Seeded recorded one authority rejection (invalid subtree path), five generated-proposal parse errors and one cancellation. Empty recorded two authority rejections (mixed skill arguments; invalid subtree path), eighteen generated-proposal errors and two cancellations. All 114 seeded journal phases are `completed`, including the cancellation; empty has 87 completed and one started record. Totals retain partial/error records, and reported tokens exclude usage not returned by the provider. Higher seeded call count accompanies successful continuation into communication/learning; this pair does not isolate a scheduling change.

## Roadmap interpretation

This repeat strengthens the bounded viability result from 009 and demonstrates immediate, distinct, revisable habits without waiting for a model. Combined retained evidence now supports renewable survival beyond starting reserves, purposeful self-care and monitoring, shared construction and material interaction, local private learning, conversational influence, permanent scarcity consequences and inspectable isolated execution. The roadmap acceptance decision is recorded in [Stage 1 evidence](STAGE_1_EVIDENCE.md).

Poor patch choices, unnecessary exposure and unequal reserves remain real behavior limitations, but efficient specialization and equality are not additional Stage 1 requirements. Preserve those observations as future challenges. Authored starter roles do not prove emergent occupations, and successful twelve-minute runs do not establish unlimited population support, archives, dependent newcomers or later world stages.
