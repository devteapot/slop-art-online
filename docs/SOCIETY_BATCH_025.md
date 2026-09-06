# Batch 025: the 36-person reality run failed service continuity

The fresh faction-world run reached its twelve-minute wall deadline, but it did not produce a confirmed final authority export. The supervisor records `duration_elapsed` after 721.928 active wall seconds, then fails because its final `sim_operator_pause` command exceeds the thirty-second deadline. The batch and pilot are both `failed`. This is an incomplete service-capacity sample, not a completed twelve-minute society or evidence that people autonomously declined law editing.

The retained owner export ends at 134.596 simulation seconds, 22 updates and event 9469. Later model contexts reach 203.308 seconds, so that export is demonstrably behind authority activity. Its thirty-six health values of 100 and absence of damage apply only to the retained prefix. The original supervisor evidence supplies no confirmed final population, simulation duration, update rate or law registry. A later, separately labeled recovery reads the paused authority at 361.416 simulation seconds; it does not repair the original completion failure.

## Fixed inputs

The [campaign](../configs/experiments/campaign/025-faction-reality.json) uses frozen `reality-m7-1`, manifest SHA-256 `a89660bf0907234f3bd64687ffb2367f6cba5d471b1806bfacba9c6b0d421350`. It fixes thirty-six Luna-medium controllers, serial behavior/communication/learning, fifteen seconds after each responsibility, no call cap and a twelve-minute duration. Eighteen controllers use the built-in host route and eighteen the external participant route.

Relative to the earlier faction-world scenario, only the display name and four obsolete motive sentences change. Physical stocks, geography, initial knowledge, survival habits, offices, organizations and controller settings retain the prior seed. The existing homeland grants belong to actors 2, 6, 10 and 14; civic office conveys no editing privilege, and SF, the independent city and wild regions have no initial editor. No law source, experimental cases, successful proof or required action is seeded. The four initial grantees use the external controller route and have ordinary organic bodies.

[Preflight evidence](../output/batches/025-faction-reality/MONITOR_PREFLIGHT.json) records the exact input comparison. The actual initial request checks cover all thirty-six people. Initial request contents establish available controls at that point; they do not establish continued subscription readiness, later effective commands or successful research.

## Observed service failure

[Live monitoring](../output/batches/025-faction-reality/MONITOR.jsonl) contains eighteen running samples, from 29.6 to 718.7 wall seconds, followed by a failed-state sample. At 29.6 wall seconds the export contains 21.386 simulation seconds and twelve updates. At 150.5 wall seconds it contains the last retained 134.596-second state. It does not advance in any later sample. Its age reaches 574.9 seconds at the last running sample and 615.5 seconds in the failed-state sample. These are sampled export observations, not measurements of every authority update.

The [service review](../output/batches/025-faction-reality/faction-world-reality/SERVICE_CONTINUITY_REVIEW.json) records 467 process setup failures with `no participant grant or subscription not ready`, affecting all eighteen external actors. The first failure is actor 6's second call, a communication call beginning 26.945 wall seconds after start and failing after 5.991 seconds. That process never reaches a model journal. The error combines missing grant and subscription readiness; it does not itself prove a grant was revoked.

Eleven external actors retain only their initial 4.808-second context. Four reach 34.384 seconds, and three reach 140.010 seconds after earlier setup failures. Built-in actors retain between three and five model journals each. Actor 35 has the latest context, at 203.308 seconds. These observations show partial later access while the owner export is stale; they cannot supply a final-state observation gap or completed-run cadence.

| Retained model evidence | Built-in | External | Total |
| --- | ---: | ---: | ---: |
| Completed journals / HTTP 200 | 70 / 70 | 28 / 28 | 98 / 98 |
| Reported tokens | 3,202,789 | 1,351,006 | 4,553,795 |

The external supervisor records 26 completed processes, 469 failed and one interrupted. A process status is a different measure from model HTTP success or command application. Twenty-four model journals contain receipt-timeout errors, including errors nested inside result receipts. Such a timeout means the waiting client does not know the command's outcome. It must not be counted automatically as an authority rejection.

The [independent receipt correlation](../output/batches/025-faction-reality/source-receipt-correlation.json) identifies twelve timeout journals with committed participant-command evidence in the retained prefix: seven speeches are delivered and five expire. Five speeches queued at 34.384 seconds/update 16 subsequently expire at 65.591 seconds/update 17. Command acceptance, speech delivery and receipt availability are distinct outcomes. Later journal feedback also acknowledges Niko's command 9470, beyond the prefix's last event; this establishes policy acceptance through that feedback, not a third completed forecast.

## Physical work and law absence in the retained prefix

The [immutable prefix](../output/batches/025-faction-reality/faction-world-reality/INTERRUPTED_AUTHORITY_PREFIX.json) has SHA-256 `236592931206008b7c45a08b4e4ec53bcb9bddccb93e602192b5951a265ee537`. Its [metadata](../output/batches/025-faction-reality/faction-world-reality/INTERRUPTED_AUTHORITY_PREFIX_METADATA.json) states explicitly that it is not final authority. The [prefix audit](../output/batches/025-faction-reality/faction-world-reality/PREFIX_AUDIT.json) calls the existing pure analyzers on those bytes; it does not bypass the normal reporters' completed-pilot requirement.

The prefix contains no law draft submission, experiment, installation, activation, border crossing or author-death persistence condition. [Independent review](../output/batches/025-faction-reality/source-causal-findings.md) of all ninety-eight retained raw model replies, including malformed proposals, finds no law attempt. It classifies 39 replies with accepted receipts, 23 valid no-operations, eleven malformed replies, one parsed validation error and 24 receipt timeouts. Each initial grantee has only one model journal, an initial maintenance no-operation. Missing law activity remains confounded by lost service continuity and the incomplete authority record. It cannot be interpreted like the completed four-world batch 022.

Vela (3) submits a built-in forecast at station 1 in event 4913 at 32.089 seconds. Juno (11) submits another at station 3 in event 5556 at 34.384 seconds. Both complete and are retrieved at 65.591 seconds. The two jobs consume six paid quanta, twelve electricity and six water. They use an existing calculator; neither is participant-authored numeric or law source.

Later accepted replies end those retrieval loops. Vela installs a survival policy including eating; Juno installs charge/gather/observe/rest priorities with no eating action. The prefix does not establish downstream harm from either choice. No inter-origin material transfer, damage or death appears in it.

| Retained-prefix account | Balance |
| --- | --- |
| Food | 90 initial + 54 produced = 108 retained + 36 eaten |
| Electricity | 1,710 initial + 1,082 produced = 1,826 retained + 954 body use + 12 compute |
| Water | 396 initial = 390 retained + 6 cooling |
| Parts | 229 initial = 229 retained; no repair consumption |

The prefix law, research, infrastructure, physical-copy and multisociety analyzers report no violations. These balances and checks establish internal consistency of that prefix. They do not certify a final world or sustained provisioning.

## Exact physical WAL and shared load

The [baseline](../output/batches/025-faction-reality/WAL_BASELINE.json) captures 107 pre-existing replica directories before exclusive publication. At readiness exactly one new replica, `8000051`, appears for database `sim-bevy-db-1788671547748-2239983` and run `sim-bevy-1788671548228`. The sampler freezes that mapping and never adds unrelated replicas.

[WAL_RESULT](../output/batches/025-faction-reality/WAL_RESULT.json) retains twenty-nine samples and ends automatically on batch failure. Over 780.714 baseline-to-terminal seconds, including publication/setup and failed cleanup, logical file growth is 339.200 MiB and allocated growth is 335.328 MiB. This remains actual measured WAL growth even though the owner snapshot stops refreshing. It is not a measure of useful simulation progress. Preallocation and writes within already allocated space limit what file-size sampling reveals; this is not a sum of compact database rows.

The coordinator's 770 disk samples remain above its 3 GiB reserve, declining from 14.657 to 14.142 GiB. The capacity failure is not a measured disk-reserve exhaustion. Shared-disk changes also include exported evidence and unrelated files.

The separate [read-only service diagnosis](../output/society-lab/reality-m7-build-verification/025-service-route-diagnosis.md) measures unnecessary work from eight retained, paused observer hosts. In a ten-second sample they consume a combined 35.7% of one CPU and substantial socket/pipe traffic. The current runner consumes 95.89% CPU while repeatedly decoding the unchanged 31.5 MB snapshot for actor-alive checks; SpacetimeDB consumes 118.39%, with a separate sample finding one busy worker at 98.14%.

Code inspection explains that paused observer hosts still request the hydrated full-world owner view every 600 ms, before unchanged-export suppression. This establishes redundant load and a plausible contention factor. It does not isolate the dominant reducer/view function, prove that the retained hosts caused this failure, or establish a Stage 7 regression. Earlier thirty-six-person runs already exhibited readiness failures. A fresh comparison after parking completed hosts must be reported separately; it cannot repair this sample or fill its missing final authority record.

A subsequent [offline native replay](../output/society-lab/reality-m7-build-verification/025-native-profile/README.md), performed after the active run ended, separately measures a copy of the retained World. Two `advance_ms(50)` calls take 540 and 518 ms; two `advance_ms(9282)` calls take 690 and 591 ms. Each starts from an independent copy, advances one update and produces no engine fault. This establishes material stepping cost in a native debug build before WASM/storage/subscription overhead. One state and two repetitions do not identify the hottest function or explain the full live stall; they are diagnostic fixtures, not continuation of the society.

A complementary [native participant-status profile](../output/society-lab/reality-m7-build-verification/025-status-profile/README.md) reads the recovered World without advancing it. Full status for all thirty-six people totals 16.93 MB, versus 0.119 MB for status headers; retained-read contents account for 99.30% of the full payload. Native reconstruction and frozen memory-fragment expansion are measured separately. This identifies substantial repeated status payload and processing work, but does not measure network/WASM cost or establish an optimization speedup.

## Separate recovery after the failed run

After the run failed, the operator parked eight completed batch-022/024 observer hosts and retained their archive access. A cheap read of the owned 025 clock then returned `paused=true` in 0.017 seconds. The [recovery record](../output/batches/025-faction-reality/faction-world-reality/POST_RUN_RECOVERY.json) measures the full-world read at 0.418 seconds and the whole capture at 0.910 seconds. These are post-run observations following a change in shared load, not a controlled replay of the earlier stall.

The [recovered snapshot](../output/batches/025-faction-reality/faction-world-reality/POST_RUN_RECOVERED_SNAPSHOT.json), SHA-256 `e92844aff98575ca5bc728b93e176a720ed42f9f0c169b7439f8c2ecfbf736c1`, contains 361.416 simulation seconds, 29 updates and 14,279 contiguous events. Event 14027 records `clock_recovery_required` at update 29 after 60,542 ms of elapsed wall time. The clock had paused after exceeding its recovery threshold. The failed pilot, missing original final export and immutable 134.596-second prefix remain unchanged.

The [recovery audit](../output/batches/025-faction-reality/faction-world-reality/POST_RUN_RECOVERY_AUDIT.json) finds all thirty-six people alive, with actor 33 at health 28 and everyone else at 100. Damage event 12483 applies 72 power-depletion damage to actor 33 at 274.485 seconds/update 27, under the ordinary law with no overlay. There is still no law experiment, activation, crossing or inter-origin material transfer. This is the recovered paused state, not twelve simulation minutes of sustained survival.

[The recovered causal supplement](../output/batches/025-faction-reality/source-recovered-supplement.md) resolves all twenty-four timeout request IDs: seventeen speeches (ten delivered, seven expired), four reflections and three policy patches. The additional three forecasts have no retained personal interpretation.

Hana (33) provides a concrete interaction between an earlier accepted policy and delayed updates. Her 98.109-second policy places gathering until five carried food above charging below fifty. She continues gathering as charge falls, takes her fifth food at 243.773 seconds with charge three while her perceived station is enabled, authorized and holds 100 electricity, and reaches the next needs batch with insufficient power. At 274.485 seconds support requires twelve charge but pays three, leaving nine unpaid pulses in event 12472. Charging subsequently adds twenty in 12477, but the accumulated deficit still produces 72 damage in 12483. This supports delayed charging under that policy combined with large elapsed needs batches. It does not establish a new decision after service access was lost or intentional self-harm.

Recovered events establish additional computation beyond the stale prefix: Niko's forecast is submitted in 9862 at 140.010 seconds, completes in 9969 at 159.813 and is retrieved in 10547. Actor 5's forecast also completes and is retrieved; actor 17's completes but remains unclaimed. Totals are five submitted/completed built-in forecasts, four retrievals and fifteen paid quanta. These recovered physical outcomes resolve uncertainty that the original prefix alone could not resolve.

Recovered balances pass separately: food `90 + 162 = 135 retained + 117 eaten`; electricity `1710 + 2520 = 1617 retained + 2583 body use + 30 compute`; water `396 = 381 retained + 15 cooling`; parts remain 229. The pure recovery analyzers report no law, research, infrastructure, physical-copy or multisociety violations. These checks cover the recovered paused authority; completion-gated campaign acceptance remains failed.
