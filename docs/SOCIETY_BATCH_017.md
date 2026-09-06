# Batch 017: chosen computation completed, with a server-restart limitation

Four fresh eight-minute samples used [campaign 017](../configs/experiments/campaign/017-infrastructure-repeat.json), frozen as `infrastructure-m5-2` with authority `m5-2-deliberate-compute.1`. Scenario and controller JSON matched the frozen batch 016 inputs exactly. The runtime added persistent `once` behavior and `retrieve_ready`, which selects the caller's oldest completed uncollected job. Neither operation was placed into a starting policy. Model participants chose their own changes.

Baseline participants submitted, paid for, completed and retrieved two forecasts. Dara personally interpreted her retrieved report as conditional arithmetic. No later material decision is established as a consequence of either numerical result. The other three samples submitted no valid jobs. All four were also affected by a shared server panic at about three minutes: existing policies continued, but the eight built-in controllers never reconnected. This limits conclusions about subsequent reasoning, repair, rescue and policy adaptation.

| Variant | Simulation seconds | Final living / retained | Charging actions | Submitted / completed / retrieved jobs |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 480.162 | 4 / 4 | 16 | 2 / 2 / 2 |
| Power | 480.124 | 3 / 4 | 11 | 0 / 0 / 0 |
| Cooling | 480.031 | 4 / 4 | 18 | 0 / 0 / 0 |
| Access | 480.148 | 3 / 4 | 9 | 0 / 0 / 0 |

Power Cato 3 died at 382.663s, event 26773, after damage 26769 (`power_depletion`). His three charges occurred at 77.535s, 127.602s and 225.022s; the generation rate could not indefinitely support both electric bodies. Access Cato 3 died at 232.579s, event 12232, after damage 12228 with the same cause. His accepted command 4374 at 97.550s removed unauthorized charging and chose local gathering. No owner grant or support charge followed. Both deaths occurred after the built-in sessions stopped reasoning.

## From a chosen task to a private physical report

Baseline Ari 1 authored a `once` submission and retrieval policy in command 1017 at 24.131s. Cato 3 independently authored a similar task in command 889 at 22.682s. Both initially supplied descriptive strings as sources rather than personally held record IDs; those attempts failed before creating jobs or spending compute resources.

Ari then corrected the source himself in command 9546 at 108.221s, preserving the unfinished `once` task and citing his owned `assertion-1-7140`. Dara 4 authored her own guarded `once` submission and retrieval in command 10007 at 114.763s, citing her owned `assertion-4-4988`.

| Caller / job | Submitted | Completed | Retrieved | Private record |
| --- | --- | --- | --- | --- |
| Ari 1 / job 1 | 108.568s, event 9554 | 111.614s, event 9754 | 111.826s, event 9774 | `compute-1-9754-0` |
| Dara 4 / job 2 | 115.156s, event 10046 | 118.371s, event 10353 | 118.596s, event 10399 | `compute-2-10353-0` |

Each job advanced through three one-second quanta and consumed six electricity, three water and three integrity. Six quanta therefore consumed twelve electricity and six cooling water; station integrity ended at 94. Completion alone did not place a record into personal knowledge: the explicit retrieval events created the two personal copies.

Ari submitted stock 78, inflow 72/min, demand 24/min and a two-minute horizon, producing projected stock 174. Dara submitted stock 100, inflow 3/min, demand 1/min and a one-minute horizon, producing 102. These are correct arithmetic for their supplied assumptions. Ari's demand counts one electric body and omits the finite buffer cap; his source assertion concerns valid forecast source IDs, not numeric stock/generation observations. Dara's source assertion concerns food rather than the station values used in her calculation. Owned citations establish provenance and authority, not the semantic adequacy of assumptions or prediction accuracy.

Dara's accepted reflection command 14029 at 166.347s cites the ready perception 10354 and retrieved-report perception 10400. She explicitly treats the output as conditional on supplied assumptions and as unable to verify future production, geography, access or intentions. Her later surviving external controller chose to retain the two-meal reserve policy, rather than recording a numeric forecast-driven material change. Ari's reflection 13356 at 156.872s instead interprets repeated retrieval failures as an already-collected-report problem. His next Behavior call was cancelled by the server restart before it could repair that loop.

Cato received one actual copy of Bryn's `camp-equipment-maintenance` record through teaching event 8353 at 92.028s. That copy did not result in a completed Cato job. A physical knowledge transfer and successful computation should therefore be counted separately.

## What the controls did not establish

No module construction, repair, station grant, water/part transfer or support charge occurred. Power, cooling and access participants chose some typed compute policies, but no valid submission reached a queue. Cooling still held its one initial station water at the end, so the run never tested a paid job stalling for insufficient cooling.

Failed primitive counts retain the cost of unsuccessful behavior without inventing successful work: baseline had 426 source-validation failures and 969 attempts to retrieve without an own completed report; power had 216 source-validation and 1,203 charging failures; cooling had 1,148 source-validation failures; access had 271 source-validation failures and 48 permission denials. Some loops continued after the model connections were lost. These are gameplay rejection events, distinct from malformed model proposals and server failures.

Cooling Dara deposited nine food units and access Dara deposited 34. Both gathered more than they deposited and remained net collectors over the sample. No actor was a net food provider. Baseline and power had no food deposits. Actual food circulation does not establish a maintained provisioning agreement or a forecast-driven allocation.

## Shared server panic and unrecovered controllers

At UTC 2026-09-06 00:24:37, the shared `clockworklabs/spacetime:v2.1.0` container exited with code 1 after a `tokio-runtime-worker` panic at `crates/client-api/src/routes/subscribe.rs:1366:48`: `buffer should be unique`. It restarted at 00:24:38.161. Podman recorded one restart and `OOMKilled=false`; this was not evidence of an out-of-memory kill or an authored world action. The compact diagnostic is [SERVER_INCIDENT.json](../output/society-lab/batches/017-infrastructure-repeat/SERVER_INCIDENT.json).

All eight built-in actors (1 and 3 in each sample) lost their persistent participant connections. Their final journal counts were baseline 7/7, power 6/6, cooling 6/7 and access 7/7. Four in-flight Behavior calls were cancelled around 00:24:37.8; others were between requests. Every host log then repeatedly reported `participant connection disconnected; reconnect with same session file`. There were no later built-in model journals. Control epochs remained 1, identities stayed in the world, and already-installed behavior trees continued. External actors 2 and 4 used fresh per-call connections and continued producing proposals.

The two completed baseline jobs and Dara's initial interpretation preceded this incident. It does not invalidate their authority events, but it prevents treating the remainder as eight minutes of uninterrupted reasoning by every actor. Final gameplay audits report no engine or scope violations; that does not negate the independently observed host/server continuity failure. The subsequent host should reconnect with the same saved identity and control epoch before the larger integration sample. No repair or reconnection was injected into batch 017.

## Accounts and model records

| Variant | Initial electricity + produced = final + body use + compute use | Initial water = final + cooling use | Initial food + produced = final + eaten |
| --- | --- | --- | --- |
| Baseline | 190 + 385 = 179 + 384 + 12 | 32 = 26 + 6 | 10 + 29 = 19 + 20 |
| Power | 190 + 192 = 50 + 332 + 0 | 32 = 32 + 0 | 10 + 32 = 21 + 21 |
| Cooling | 190 + 393 = 199 + 384 + 0 | 13 = 13 + 0 | 10 + 30 = 20 + 20 |
| Access | 190 + 233 = 151 + 272 + 0 | 32 = 32 + 0 | 10 + 32 = 22 + 20 |

Every sample retained 26 parts, including fourteen endowed module parts and twelve carried parts; no repair consumed any. Electricity combines body and station stocks. Production is actual output after caps, not nominal output extrapolated over time. Pulse events may report zero use or multiple units after elapsed-time recovery, so event counts need not equal consumed units. Dead-body inventories remain in the food and material accounts.

| Variant | Recorded calls | Completed journal entries / HTTP 200 | Entries with output/processing errors | Reported tokens |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 49 | 48 / 48 | 5 | 1,357,321 |
| Power | 48 | 48 / 48 | 8 | 1,355,893 |
| Cooling | 49 | 48 / 48 | 10 | 1,336,027 |
| Access | 49 | 48 / 48 | 7 | 1,310,425 |

There were 195 recorded model calls and 5,359,666 reported tokens. Three final entries remained in `started` phase. Thirty entries carry errors: 26 invalid generated/participant proposals and four cancellations. These counts do not include the continuing attempts to use already-disconnected built-in sessions, which failed before a new model journal. HTTP success and absence of an engine invariant failure are insufficient evidence of controller continuity.

## Reproducing the reports

Each output directory contains `INFRASTRUCTURE_RESULT.json`, `KNOWLEDGE_RESULT.json`, `SOCIETY_RESULT.json`, `LIVE_RESULT.json`, final authority evidence and controller journals. Run `python3 scripts/summarize_infrastructure.py output/society-lab/batches/017-infrastructure-repeat/<variant>` to rebuild the reports. All four completed infrastructure, food-conservation and knowledge-copy audits passed without violations. The server incident and limited forecast usefulness remain separate findings.

Final authority snapshot SHA-256 values:

| Variant | SHA-256 |
| --- | --- |
| Baseline | `d430910ca4aafeb656a94a42e3cbd770901f3c201edb45d2db357dbdf3aab24f` |
| Power | `a9beb777b91cbd002867f91d7f64ea1c16472b6fb314f40c8928620a445229ad` |
| Cooling | `835b98e2501dda91d6f24263b62894e43560088cd02f32da9dbdd50d6a4dace4` |
| Access | `09a5da04b1991de63e0648805babd3953517bfdaf0e785df6569f31c72106588` |
