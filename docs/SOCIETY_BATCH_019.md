# Batch 019: sustained history growth exposed a second capacity limit

The 36-person `faction-world-m5-4` sample was deliberately interrupted after update cadence deteriorated and external clients repeatedly failed to establish their participant subscriptions. It did not complete the planned twelve minutes. The final authority retained 259.291 simulation seconds, 324 updates and 46,972 events. Thirty-four actors remained alive. This sample establishes a sustained-load failure beyond the short successful batch 018 read diagnostic; it does not establish stable 36-person society behavior.

The frozen authority was `m5-4-scaled-publication.1`, with the same scenario and controller inputs used in the preceding capacity work. All 36 controllers used Luna with requested medium effort, independent fifteen-second post-completion schedules, and no model-call cap. The observer was on port 18984, run `sim-bevy-1788656469914`.

## The measured deterioration

The host's local exports and journals were read without adding participant requests or changing the world. [MONITOR.jsonl](../output/society-lab/batches/019-faction-world-scaled/MONITOR.jsonl) retains the measurements and export ages.

| Sample wall seconds | Export simulation seconds | Authority updates | Compact world MB | Export age seconds |
| ---: | ---: | ---: | ---: | ---: |
| 60.9 | 52.049 | 239 | 7.84 | 6.7 |
| 124.0 | 116.461 | 289 | 13.27 | 2.2 |
| 196.3 | 184.973 | 305 | 15.21 | 4.3 |

Between the first two samples, only fifty additional updates occurred over 63.1 wall seconds, approximately 0.79 Hz. The next interval delivered sixteen updates over 72.3 wall seconds, approximately 0.22 Hz. These are intervals between asynchronous local exports, with their ages shown above. Elapsed simulation remained close to elapsed wall time because updates account for elapsed time; this does not preserve frequent action opportunities. A 50 ms configured clock did not produce a sustained twenty-Hz action cadence.

Thirty-seven external process logs report `no participant grant or subscription not ready` before model invocation. The first affected recorded attempt was actor 18's fourth call, starting 106.1 seconds after the pilot began. This error identifies failure to establish a ready subscription within the client's deadline; it does not prove that the authority revoked the actor's grant. Some actors recovered on later attempts. There were no recorded `receipt timeout` errors. Built-in controllers continued creating journals, so the failure differs from batch 017's permanent post-restart disconnection. No server restart was used during this run or its cleanup.

There were 138 external process attempts: 76 completed, 56 failed and six were interrupted. Actual retained built-in and external model journals total 262: 259 completed entries with HTTP 200 replies and three started entries. They report 6,601,109 tokens. Forty-five journals contain processing errors: 36 malformed proposals, eight cancellations and one `this identity has no run access` during shutdown. The thirty-seven pre-inference subscription failures are separate from that journal error count. Neither a failed process launch nor an HTTP 200 reply is evidence of an accepted world action.

## Where the serialized state grew

A live snapshot retained at 242.122 simulation seconds contains 15.753 MB of compact UTF-8 world JSON, of which 15.175 MB is participant state. [PARTICIPANT_PROFILE_SIZE_DIAGNOSTIC.json](../output/society-lab/batches/019-faction-world-scaled/faction-world/PARTICIPANT_PROFILE_SIZE_DIAGNOSTIC.json) provides per-actor measurements and the hash of the preserved profile snapshot.

| Participant content | Total MB | Mean per actor KB | Largest actor KB |
| --- | ---: | ---: | ---: |
| Complete participant state | 15.175 | 421.5 | 505.9, actor 9 |
| Retained lease observations | 4.529 | 125.8 | 142.5, actor 9 |
| Context within those observations | 4.143 | 115.1 | 129.8, actor 9 |
| Retained lease experience lists | 6.906 | 191.8 | 239.7, actor 11 |
| Current experience queues | 3.594 | 99.8 | 119.8, actor 9 |

The context row is a subset of observations. Lease fields total 11.451 MB, including small metadata. Receipts total only 73.6 KB. Every actor had the bounded four leases; bounded count alone did not prevent expensive repeated data bodies.

Current queues and retained leases held 26,487 experience entries representing 11,852 distinct actor/cursor pairs. Deduplicating those entries within each actor would remove approximately 5.893 MB of repeated serialized entry bodies, excluding list punctuation. This is a representation estimate, not permission to discard evidence: older leased events may no longer be in the current queue and must remain available until the lease expires. The separate private participant status cache contains additional response copies and is not counted inside the World JSON.

The existing immutable observation representation reduced some work, but participant cloning and experience JSON parsing/serialization still amplified history costs. The next implementation targets those representations; no physical resource rates or policies were changed inside batch 019.

## Physical effects before interruption

The [cleanup infrastructure audit](../output/society-lab/batches/019-faction-world-scaled/faction-world/CLEANUP_INFRASTRUCTURE_AUDIT.json) balances all material accounts. Electricity: 1,710 initial + 2,020 generated = 1,899 retained + 1,831 body use. Water remained 396, and parts remained 229, including embodied module parts. Seventy actual body-charging actions occurred. No compute submission, completion, retrieval, terminal construction, repair, grant or support charge occurred. HF member Felix 34 explicitly said he was not starting construction or computation in speech event 19666 at 53.537s; facility 8 remained without a terminal.

Food also balances: 90 initial + 108 produced = 111 retained + 87 eaten. No food transfer or deposit occurred. Knowledge-copy and fixed-population event audits report no violations; 56 records were initially seeded and 79 assertions were authored, with no teaching, archive copying or compute reports. The separate `CLEANUP_KNOWLEDGE_AUDIT.json` and `CLEANUP_MULTISOCIETY_AUDIT.json` explicitly identify this as an interrupted diagnostic.

Mara 23 and Sol 24 moved from their adjacent initial cells into shared SF shelter in their first update: completed movement events 906 and 925 at 0.136s. Mara later died of starvation at 220.857s, event 42471 after damage 42467. Sol remained alive at health 100. These are physical neighbor outcomes, not evidence that the fictional dependency biography implements withdrawal or treatment physiology.

Juno 11 died of power depletion at 234.831s, event 43577 after damage 43573. His accepted command 4752 at 12.094s replaced `root/0`, the initial charging branch, with food gathering, while its explanation claimed to preserve existing charging. He never successfully charged. Speech 32124 at 119.650s recognized falling body charge despite a full station; speech 42680 at 220.857s requested explicit charging after damage began. No supporting charge followed. This authored policy error is real evidence; the degraded action cadence and intermittent model access prevent attributing the whole outcome solely to resource balance or solely to infrastructure performance.

NVIDIA members Niko 35 and Veda 36 spoke about their own facility and intermittent SF food supply. Veda proposed coordinating a compute task if a concrete shared question were requested; no job followed. Their statements establish individual communication, not institutional decisions. Veda ended at health 52; Niko at 100. Actors 4, 8 and 28 also ended at health 52. No council allocation, inter-person supply delivery or numerically informed compute decision was established.

## Interruption provenance and the supervisor correction

The verified pilot PID 959518 received SIGINT after the capacity failure was reviewed. Its pause, grant revocation and final export succeeded. However, the old supervisor unconditionally marked the run `completed` after leaving its loop, even when a signal had caused the exit. The batch accepted exit code zero and generated `LIVE_RESULT.json`. That label was incorrect: the pilot ended after about 285 wall seconds, not 720.

The exact original supervisor and batch results are retained as `pilot-supervisor-original.json` and `batch-supervisor-original.json`. Working pilot and batch metadata now say `failed` with explicit controlled-interruption provenance. The automatically generated `LIVE_RESULT.json` remains original evidence of that reporting defect; its `completed` label must not be treated as experimental acceptance. Diagnostic audits use the final authority directly and keep their interrupted scope explicit.

[cleanup-confirmation.json](../output/society-lab/batches/019-faction-world-scaled/faction-world/cleanup-confirmation.json) confirms the clock paused, stable authority matching the supervisor export, host 959585 stopped, and zero participant grants remaining. The supervisor had already revoked all 36 grants before exporting, which also cleared retained leases. Thus the final compact world is only 4.396 MB; it must not replace the live profile when assessing peak serialization cost. No other database or server was changed.

The supervisor now records the termination signal, a completion reason and active monotonic duration before draining workers or exporting. Signals during the run or cleanup keep failed status. The batch requires the planned duration or an authority-proven stopped/dead population, plus matching final run, time, path and SHA-256. Cleanup time cannot satisfy a minimum sample duration, and exit code zero alone cannot establish completion. Twenty-two focused supervisor/coordinator tests pass, including eight new interruption, timing and provenance regressions.

Final authority SHA-256: `cd435bba625250e1dd91980e5a3f25e74a58ceebf4684c7143c6fd5a14a1b7e7`. Preserved live profile SHA-256: `fdf60c7704987333f6aa11dc3ac6ca97c5fd056f6a10f7d2ec7e4ad82eb04489`.
