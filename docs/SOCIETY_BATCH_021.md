# Batch 021: completed faction sample with paid computation and local aid

The 36-person faction world completed its twelve-minute sample on frozen `faction-world-m5-5`, with the retained authority version `m5-4-scaled-publication.1`. It retained 720.675 simulation seconds, 856 updates and 172,892 audit events. Twenty-nine people survived. NVIDIA member Niko chose, paid for and retrieved one conditional forecast; three people later gave food to Dai at SF; OpenAI residents exchanged two local knowledge records through an archive and teaching. All material, knowledge-copy, population, engine and scope audits passed.

The sustained service result remains limited. The authority averaged 1.156 updates per active wall second, and external controllers experienced 36 failed subscription setups and some long gaps between model observations. This is a completed integration sample with actual effects, not evidence of twenty-Hz operation, uninterrupted reasoning by all 36 controllers, sustained provisioning or successful inter-settlement coordination.

The [campaign](../configs/experiments/campaign/021-faction-world-history.json) kept the preceding faction seed and Luna-medium controller configurations. The new implementation shares participant state until mutation and retains experience bodies as immutable JSON, reducing repeated history parsing, cloning and serialization. No scenario intervention or policy repair was injected during the sample. The run was `sim-bevy-1788657150824` on port 18990.

## Duration and controller continuity

The corrected supervisor recorded `duration_elapsed`, requested duration 720 seconds, and active monotonic duration 740.323 seconds. Reading the large observer export delayed handling of the deadline; worker drain and final export followed that measured interval. Final simulation time was 720.675 seconds. The batch independently validated the completion protocol and the final run, time, path and SHA-256. Cleanup had no pause error. The completed observer was subsequently replaced with an archive viewer on the same port; that happened after the sample and did not change its final snapshot.

| Controller runtime | Retained model journals | HTTP 200 replies | Reported tokens |
| --- | ---: | ---: | ---: |
| Built-in | 402 | 400 | 11,380,020 |
| External | 200 | 200 | 5,997,188 |
| Total | 602 | 600 | 17,377,208 |

All 602 journals reached completed phase, including error completions. Seventy-eight have processing errors: 73 invalid generated proposals and five cancellations. The external supervisor also recorded 249 process attempts: 168 completed, 76 failed and five interrupted. Thirty-six process logs failed with `no participant grant or subscription not ready` before inference. Those failures are additional to the model journal errors; process attempts do not equal model calls.

There were no recorded receipt timeouts and no new server restart. The shared server remained on its original post-batch-017 start time, with restart count one and `OOMKilled=false`. Failed new external subscriptions frequently recovered on later attempts. They do not prove lost grants or an unobserved server restart. Built-in persistent connections continued producing journals through the sample.

The [continuity analysis](../output/batches/021-faction-world-history/faction-world/MODEL_CONTINUITY.json) uses each model journal's actual observation time, and censors dead actors at death. Surviving built-in actors had at most 54.365 seconds between observations. Surviving external actors had materially larger gaps: Inez 22 reached 198.997 seconds with six setup failures, Xeno-Prime 10 reached 160.045 seconds, and Sol 24 reached 149.396 seconds. A later successful call does not erase those gaps. The final observation times and per-actor errors are retained in that artifact.

| Wall seconds at monitor read | Export simulation seconds | Updates | Compact world MB | Export age seconds |
| ---: | ---: | ---: | ---: | ---: |
| 54.7 | 49.450 | 253 | 7.14 | 3.0 |
| 114.7 | 103.916 | 360 | 12.72 | 0.9 |
| 221.9 | 203.915 | 465 | 15.74 | 6.3 |
| 386.8 | 372.485 | 603 | 16.52 | 1.9 |
| 554.7 | 524.518 | 725 | 17.12 | 13.0 |
| 660.4 | 626.178 | 800 | 17.64 | 12.5 |

The late measured interval was approximately 0.71 updates per wall second. Four retained leases per actor bounded their count, while growing histories still enlarged their bodies. Full observer exports, including accumulated audit events, reached approximately 76 MB in the final live monitoring sample. [MONITOR.jsonl](../output/batches/021-faction-world-history/MONITOR.jsonl) retains these asynchronous measurements. Near-real-time elapsed simulation, 0.973 simulation seconds per measured active wall second overall, did not preserve the configured 50 ms action cadence.

## Niko's chosen computation

Niko 35 replaced his own behavior in command 38029 at 109.745s to submit a single bounded forecast and explicitly retrieve the result while retaining survival actions. The initial seed did not contain that submission. At station 9 he submitted stock 88, inflow 48/min, demand 24/min and a two-minute horizon, citing his personal `facility-9-planning` account and owned `assertion-35-24114`.

| Event | Authority evidence |
| --- | --- |
| Submission | 38488 at 110.407s |
| Completion | 39324 at 113.699s, after three paid quanta |
| Explicit retrieval | 39431 at 113.699s |
| Personal record | `compute-1-39324-0`, received in perception 39432 |

The job consumed six station electricity, three cooling water and three integrity. Station 9 ended at integrity 97. The result is correct conditional arithmetic: `88 + (48 − 24) × 2 = 136`, with no modeled shortfall. It does not include the finite 100-unit station cap or all possible additional consumption. The cited assertion records a prior local station reading of 66 electricity, while the submitted 88 is a later supplied assumption. Source ownership and arithmetic validity are distinct from semantic adequacy or forecast accuracy.

Niko publicly described the exact result and its assumptions in speech 45710 at 133.693s. His reflection 55795 at 171.145s treated that communication as conditional rather than a guarantee. It also interpreted repeated `retrieve_ready` failures after the report had already been collected. Patch 64426 at 203.915s removed that failed polling loop. The strict report-receipt interpretation audit remains zero: that reflection cites his speech and operation feedback, not the report receipt itself.

No later material decision is established as a consequence of the number 136. Niko's subsequent charging changes cite repeated interruptions; his gathering changes cite observed fluctuating food and stale observations. His eventual gift to Dai explicitly cites the currently observed recipient and carried food. These are authored adaptations, but the evidence does not attribute them to the numerical forecast.

Other attempted forecasts produced 268 source/assumption-validation failures and no valid additional jobs. There were ninety attempts to retrieve without an own completed report. HF member Felix 34 recognized station 8's missing terminal and discussed its five-part construction cost, but never chose a build action. No terminal construction, repair, station grant, material transfer or support charging occurred.

## Food, neighbors and actual aid

Three one-unit gifts reached Dai 20 at SF cell 888:

| Donor | Accepted policy choice | Actual transfer |
| --- | --- | --- |
| Amara 17 | 138424 at 524.518s, directly observed hungry Dai | 138629 at 528.644s |
| Rowan 21 | 141953 at 543.416s, observed Dai and own carried food | 142154 at 545.689s |
| Niko 35 | 157626 at 626.178s, observed Dai and own carried food | 158033 at 634.874s |

Each gift changed the donor and recipient inventories. Dai subsequently ate and finished alive at health 44 with one food. His last starvation damage preceded these gifts. This establishes delivered aid and later consumption; it does not prove that each gifted unit was necessary for survival or that a lasting supply agreement formed. Earlier Fenn 25 gift attempts failed after Tern 28 was already dead; the final trace contains 211 `recipient dead or not at this cell` failures.

Real deposits also occurred. Olin 18 gathered 69 food and deposited 58; Nima 5 gathered 32 and deposited 31; Rowan gathered 21 and deposited eleven. Fenn and Xara 19 each deposited one. Every site still had no net provider over the whole run: those depositors collected more from its stock than they returned. Some circulation may help timing, but repeated gathering and returning the same stock is not sustained net provisioning. Olin eventually died of starvation.

Food conserved exactly: 90 initial + 324 produced = 187 retained + 227 eaten. The final retained food was unevenly distributed: electric bodies held 125, nutrient bodies held nineteen, and sites held 43. Electric bodies do not metabolize those carried meals. Seven starvation deaths therefore do not establish a global absence of food. Individual policy, allocation, depleted local stocks and degraded action opportunities all matter.

| Person | Death simulation seconds | Death event |
| --- | ---: | ---: |
| Soren 4 | 305.051 | 89169 |
| Tern 28 | 305.051 | 89503 |
| Mei 32 | 305.051 | 89562 |
| Veda 36 | 437.704 | 120116 |
| Mara 23 | 480.878 | 129912 |
| Kiri 16 | 700.948 | 169128 |
| Olin 18 | 700.948 | 169154 |

Every listed death followed recorded starvation damage. Tavi 12 survived at health 68, Dai at 44 and Uma 27 at 76; the other 26 survivors were at 100. There were no electric-body deaths. Mara and Sol 24 both moved from their adjacent initial cells to SF in the first update, at 0.170s; Mara later died and Sol survived. Their fictional housing/dependency biographies do not implement detailed substance physiology. No one subsequently traveled between settlements.

## Local knowledge and institutional limits

Pax 7 recorded `assertion-7-58454` in OpenAI archive 2 at event 91931, 314.916s. The record describes his observed local charging access as time-sensitive, not general permission. Leto 8 acquired an actual copy through consultation 106447 at 380.813s, and Nima 5 through consultation 170359 at 708.962s. Nima then taught Pax her own food-fluctuation assertion, `assertion-5-164013`, in event 170696 at 712.063s. These four new-copy operations reconcile with final holdings.

The sample contains 56 seeded records and 240 authored assertions, one completed compute report and its explicit retrieval, one archive write, two consultations and one teaching event. No explicit recipient interpretation or useful subsequent material decision from those copied local records is established by the strict knowledge-use audit. All copies and food transfers remained within their initial settlement. The council seats, faction affiliations, prophet/deity distinction and territorial designations remained metadata and attributed identities; individual speech and aid do not establish a council decision, territorial editing, an alliance or inter-settlement delivery.

## Accounts and retained evidence

| Account | Conservation identity |
| --- | --- |
| Electricity | 1,710 initial + 5,391 generated = 1,914 retained + 5,181 body use + 6 compute use |
| Water | 396 initial = 393 retained + 3 cooling use |
| Parts | 229 initial = 229 retained + 0 repair use |
| Food | 90 initial + 324 produced = 187 retained + 227 eaten |

There were 234 body-charging actions. Parts include endowed modules and carried inventory. Production totals use actual output under caps rather than nominal rates extrapolated over the duration. Dead-body stocks remain conserved even when unavailable for ordinary use.

Completed reports are [INFRASTRUCTURE_RESULT.json](../output/batches/021-faction-world-history/faction-world/INFRASTRUCTURE_RESULT.json), [KNOWLEDGE_RESULT.json](../output/batches/021-faction-world-history/faction-world/KNOWLEDGE_RESULT.json), [SOCIETY_RESULT.json](../output/batches/021-faction-world-history/faction-world/SOCIETY_RESULT.json), and [MULTISOCIETY_RESULT.json](../output/batches/021-faction-world-history/faction-world/MULTISOCIETY_RESULT.json). Reproduce them with `scripts/summarize_infrastructure.py` and `scripts/summarize_multisociety.py` on the run output directory. Their audits pass without violations; the measured service, causal-use and provisioning limitations remain separate findings.

Final authority SHA-256: `6e1ef582b8c778f2079723a82f281c95a4695153444fcc1dfaadbf00b80d37c1`.
