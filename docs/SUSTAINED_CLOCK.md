# Sustained authoritative clock work

This follows the completed [hybrid scheduler](HYBRID_CLOCK.md). The requested order
is: matched runtime comparison; measured execution/storage cost reduction; bounded
active evidence with durable history; deadline scheduling; progressive population,
density and mixed-controller workloads. Completion of one finite trial does not
establish sustained 20 Hz or thousand-player capacity.

## Experiment contract

The baseline is commit `7ce2a31`, using the frozen default hybrid WASM with SHA-256
`ce778c25ffad1c84800817536b4ec01f25940521135833e52fba962d1b6fa0b6`.
Two fresh isolated services run that identical module and SDK probe on 2.1.0 and
2.10.0. Both use 72 actors, initial local density 16, the same authored policies,
180 seconds, 72 persistent participant connections and twelve 72-read bursts at
seconds 5, 20, …, 170. There are no models or observers; exports occur at paused
boundaries. Builds do not run during measurements. Results and original failures
are retained under `output/sustained-clock/`.

The 8 GiB free-disk reserve, 3 GiB available-memory floor, 11 GiB service RSS bound,
12 GiB cgroup limit with no extra swap and 4 GiB retained-WAL bound remain enabled.
An interrupted or resource-aborted run is not capacity evidence. Existing databases
and evidence remain intact. Later workloads will declare their resource limits,
inputs and acceptance conditions before launch.

Official [table performance](https://spacetimedb.com/docs/tables/performance/),
[indexes](https://spacetimedb.com/docs/tables/indexes/) and
[scheduling](https://spacetimedb.com/docs/tables/schedule-tables/) were rechecked
before work. Module and client dependencies remain pinned to 2.1.0 until a separate
compatibility decision; the runtime comparison does not upgrade the development
service. Local indexed operations and compact state are the intended data paths.
Any timing change must retain elapsed simulation time, explicit long-gap recovery,
ordered physical effects and visible lateness.

## Stage status

1. Matched runtime comparison: passed; 2.10.0 selected for isolated follow-up trials.
2. Measured clock costs: immutable configuration and lazy trace metadata validated.
3. Bounded active audit evidence and durable archival/recovery: passed the initial live/restart trial.
4. Deadline scheduling: passed bounded cadence/control/restart/outage validation; sustained 20 Hz failed.
5. Progressive population/density and mixed-controller trials: completed. The 600-second soak completed its window but failed the all-reads-success gate after permanent deaths; sustained 20 Hz and population capacity remain unaccepted.

## Matched runtime result

Both 180-second trials passed all 864 reads. The identical production module
completed 9.39 updates/s on 2.1.0 and 12.96 on 2.10.0. Active service peak RSS was
2.86/1.33 GB; read p95 was 788/722 ms and maximum 1,009/849 ms. Retained WAL at pause
was 1.21/2.12 GB, and audit counts were 216,355/228,549. No resource guard aborted.
Both services required forced shutdown (exit 137), which remains distinct from
successful workload completion. These are single trials on a shared host; the user
freed unrelated disk space during the second trial. They do not isolate every
runtime mechanism or establish long-duration capacity.

## First cost reduction

The prior diagnostic attributes most advancement time to actor execution. Skill
transactions clone the complete scenario and script registry even when neither
changes. Share those immutable values across candidates using the existing typed
copy-on-write wrapper; mutation must detach and serialization remains ordinary
JSON. Retain exact rollback, law activation and full-state differential checks.
The follow-up measurement will use the same 72-actor, 60-second diagnostic as the
hybrid report before progressing to storage retention.

The first diagnostic passed all 288 reads at 16.38 updates/s. Mean load/advance/save
was 7.15/10.06/3.79 ms, compared with 7.25/10.93/4.80 ms in the earlier matching
hybrid diagnostic. This is a modest measured gain, not a 20 Hz result.

Deferring the entire trace metadata vector initially moved cost: load fell to
4.18 ms but save rose to 6.71 ms, with 16.27 updates/s. Participant-head publication
still read every trace's first entry on save. The subsequent correction reuses
`oldest_cursor` only when the stored head matches the actor/run/current cursor and
the exact immutable trace snapshot is retained. Changed traces still compute their
own first cursor. The original intermediate measurement is retained.

The corrected trace/header diagnostic passed all 288 reads plus privacy, lease
expiry and reconnect checks at 16.52 updates/s. Mean load/advance/save was
4.39/10.19/2.85 ms. Cumulative correctness checks passed 213 kernel tests, 19 module
checks, 39 codec checks and two delivery checks. Remaining execution and hot-state
scans still matter; these changes do not establish thousand-player capacity.

## Lossless audit retention

Audit archival is explicitly enabled per run by its owner. It preserves the
private `sim_audit` table as a recent tail and atomically moves complete groups of
128 old events to immutable private `sim_audit_block` rows. At steady state the
recent tail contains 2,048–2,175 events. Compaction work per append is proportional
to incoming events plus one old block; enabling archival on an existing large
history exposes a backlog that can be drained with bounded owner maintenance.
It does not perform a whole-history scan inside a routine update.

Each block contains the original JSON strings, bounded zlib encoding and a SHA-256
integrity hash. Identity, contiguous IDs, block range, count, size and hash are
checked during recovery. Compression failure keeps the source rows and records a
blocked state; the implementation does not silently discard evidence or turn that
failure into a gameplay effect. The encoding budget is 32 MiB per block.

The owner-only `sim_export_owned_audit` procedure reads at most 4,096 requested
events using block primary keys and the live `(run,event_id)` index. Ownership is
checked before reading either path. A coherent page is captured transactionally;
decompression then occurs outside the transaction. It rejects missing or corrupt
history. The archive tables have no participant subscriptions. This follows the
[procedure transaction guidance](https://spacetimedb.com/docs/functions/procedures/)
while using the pinned 2.1.0 API, rather than treating transient
[event delivery](https://spacetimedb.com/docs/tables/event-tables/) as durable history.

The development host and pilot finalization have an explicit archive mode that
uses this API. Historical SQL-only tooling retains its original default; raw
`sim_audit` SQL contains only recent history after archival is enabled. Full owner
exports must use the merged API in that mode. No existing experiment database is
converted automatically. Disabling further compaction preserves existing blocks.

This bounds the active audit index, not all durable history or character knowledge.
Archive storage still grows with genuine events. Compression ratio, retained WAL,
execution cost and exact recovery after service restart will be measured before
moving to deadline scheduling.

The first live archival attempt stopped before resume because the diagnostic
`COUNT(*)` expression lacked the alias required by SQL. It remains recorded as a
failed attempt. After correcting the query, all 288 reads passed at 16.25 updates/s;
mean load/advance/save was 4.33/10.67/3.53 ms. Active service peak RSS was 975 MB and
retained WAL at pause was 277 MB. The final measured snapshot retained 2,082 live
rows and 44,800 archived events: 31.58 MB of encoded original event strings in
4.69 MB compressed blocks. Owner recovery after service restart matched the exact
World and all 46,954 audit strings captured after cleanup, then advanced normally.
Access, privacy, lease expiry and reconnect checks passed. Both restart and final
shutdown required SIGKILL; this establishes recovery from forced stop, not graceful
shutdown. Raw artifacts are in `output/sustained-clock/archive-profile-72-60s-fixed-query`.

## Absolute deadline mode

`sim_configure_deadline_clock(run, enabled)` is owner-only and requires a paused
clock. The original control table remains compatible; in deadline mode its
interval callback is a cheap minute heartbeat. A private per-run cadence row holds
the period, pending wake ID, deadline and cumulative wake/lateness/missed-slot
counters. A separate private one-shot table has at most one pending wake per run.
No participant receives either table. Routine work uses primary/unique lookups,
not clock scans. Pause cancels the wake; resume and explicit period changes start
a new grid alongside the existing elapsed-time baseline reset.

The [pinned 2.1.0 scheduler source](https://github.com/clockworklabs/SpacetimeDB/blob/v2.1.0/crates/core/src/host/scheduler.rs)
shows that interval rescheduling happens after execution and one-shot rows are
deleted after callbacks. Therefore every next wake receives a new ID. The callback
checks that ID against the current cadence row and targets the first point on its
existing period grid strictly after the authoritative callback timestamp. A late
callback counts missed slots and advances actual elapsed time once through the
same kernel and storage path. It does not fabricate 50 ms time or replay unlimited
actions. Execution time comes from the shared elapsed-time rules, not profiling
timers. The existing greater-than-60-second recovery pause is preserved.

`--deadline-clock` enables this mode in the authority benchmark and pilot;
`SAO_DEADLINE_CLOCK=1` enables it for newly created development-host runs. Both
remain opt-in until representative workloads establish suitability. The first
comparison retains the same population, actions, subscriptions and archive mode.

The first deadline diagnostic passed all 288 reads at 17.62 updates/s, versus
16.25 with interval scheduling. Mean load/advance/save was 4.15/9.90/3.30 ms; 143
slots were missed, with 619 ms maximum lateness. All pause/cancellation/resume,
interval fallback and exact restart checks passed. A separate 62-second service
freeze triggered one `clock_recovery_required` event (62,171 ms), paused with no
pending wake and did not replay the gap. Explicit resume then advanced 551 ms.
This validates the recovery contract but does not establish sustained 20 Hz.

## Progressive workload contract

The frozen default production WASM, shared SDK 2.1.0 probe and isolated server
2.10.0 are used for 72 actors/180 seconds, then 144 and 216 actors/60 seconds each.
The initial colocations are 16, 32 and 48 respectively, with unchanged map and
supplies. The 216 case stays within the existing 256-actor kernel ceiling. All
actors remain connected and each sends a read every 15 seconds in synchronized
bursts. A separate 72-actor/60-second case changes only initial positions (one
actor per selected cell, four-tile spacing); it changes travel distances and can
regroup during play, so it is not a constant-density capacity claim.

The mixed pilot uses 72 actors: real `gpt-5.6-luna` controllers for actors 1 and 2,
one human-controlled actor receiving automated client input, and 69 others with
seeded behaviors. It runs 120 seconds with at most three calls per model actor,
persistent external MCP and eight external RPC admission slots. A separate SDK
developer observer subscribes for approximately 40 seconds; production owner
exports run throughout. The human client sends four wait intentions, disconnects
and reconnects with the same identity, then checks exact read recovery and receipt
idempotency. This is automated human-interface coverage, not a claim that a person
played the session. Observer truth is never passed to either participant/model.

Finally, the 72-actor read workload was scheduled for 600 seconds with 40 bursts under
the same resource guards. A guard abort remains a failed soak; it must not be
relabelled as a completed shorter trial. Durable audit compression does not bound
WAL or all character state, and those growth rates decide whether longer runs fit.

The 72-actor default production run passed all 864 reads at 17.38 updates/s versus
12.96 for the original production module on the same 2.10 runtime. Active peak RSS
was 1.09 GB, retained WAL at pause 1.58 GB and read p95/max 679/749 ms. The audit
contained 235,305 events: 233,216 archived plus 2,089 live. Encoded archived bytes
were 116.85 MB, compressed to 13.43 MB. The deadline counted 471 missed slots and
656 ms maximum lateness. Access and clock control checks passed. This is a finite
three-minute improvement, with unbounded durable growth and missed deadlines still
visible. Original evidence: `output/sustained-clock/production-72-180s`.

### Density exposed a guard-input correctness failure

The first 144- and 216-actor trials passed all 576/864 reads but reached only
11.88/4.28 updates/s. The spread-out 72-actor trial passed all reads but failed the
engine-error gate: 982 `script_error` events affected nine actors, starting at
21,330 ms. These are retained as original failures, not valid capacity results.

The error is Rhai's recursive map-entry budget. Guard input contained full
subjective memory/observation collections even for a position or resource check;
one affected actor ended with 35 site observations and 16 memories. The
[Rhai map-limit contract](https://rhai.rs/book/safety/max-map-size.html) and pinned
1.26.0 `eval/data_check.rs` both confirm that nested entries count toward the 512
limit. The limit remains unchanged.

The correction projects only the dependencies of the requested condition when
both the active law source and a pinned bundled-source SHA-256 match the reviewed
contract (`593033f72233dca88d901e271485cd6df5212275519f2d2056111dad85ca4fce`).
Custom or future changed laws fall back to the full existing input. Guard logic
still executes in Rhai. Selection preserves first belief/holding matches, last
site matches, newest care evidence and recursive source ordering, including
repeated sources. No memories are discarded and no foreign evidence is added.
Resource/position conditions avoid loading unrelated deferred private history.

All 216 kernel and 21 module tests passed after this correction, including exact
condition/result/provenance comparisons, a 49-location guard and custom-source
fallback. A test-fixture type mismatch in the initial test build was corrected;
that compile failure is retained. Production measurements must be repeated for
this new candidate before drawing final population/density conclusions.

The pilot now accepts an explicit fixed model subset, requiring a matching
controller manifest; unselected actors retain their existing authored/human
controllers. Its report separates full population from model actors and budgets
calls against the selected runtime population. A resumed development host also
preserves archive/deadline flags from its saved active-run descriptor, so restarting
without the original environment cannot select incomplete raw-audit SQL export.

### Final guarded population and density results

The corrected production module passed every access/correctness gate below,
including zero engine errors and zero remaining participant grants. All four
failed the separate sustained-20-Hz gate. Initial density is 16 in the population
series; the spread case changes positions only and is reported separately.

| Population / placement | Seconds | Updates/s | Reads | Read p95 / max ms | Active RSS GB | Retained WAL GB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 72 / original | 180 | 18.66 | 864/864 | 677 / 1,074 | 1.13 | 2.37 |
| 144 / scaled | 60 | 14.57 | 576/576 | 1,176 / 1,289 | 1.22 | 0.82 |
| 216 / scaled | 60 | 7.02 | 864/864 | 2,862 / 3,251 | 1.43 | 1.02 |
| 72 / spread | 60 | 14.83 | 288/288 | 1,226 / 1,370 | 1.41 | 1.66 |

Values use decimal GB. Evidence directories are `guard-72-180s`, `guard-144-60s`,
`guard-216-60s` and `guard-72-spread-60s` under `output/sustained-clock/`.
Their manifests freeze inputs and binaries; summaries retain reducer execution,
queue, WASM, allocator/pool, subscription and history measurements. The production
72 result improves on 12.96 updates/s for the original module on 2.10, while WAL
is worse (2.37 versus 2.12 GB); the improvement is not a storage-capacity solution.

Mean deadline WASM execution was approximately 20.6/37.0/107.7 ms for 72/144/216
actors. Mean participant reducer queue waits were 303/588/1,320 ms during the
synchronized read bursts. At 216 actors the physical clock preserved 99.5% of
elapsed wall time, but counted 773 missed slots and 4.03 s maximum lateness.
Preserving elapsed time is distinct from frequent delivery. Active WASM memory
peaked at 71/127/204 MB, while allocator resident memory reached 1.06/1.13/1.26 GB.
These are fresh single-database services, not RSS attributed from a shared service.
All four required forced service stops (exit 137); workload success does not imply
graceful shutdown. No service was restarted to conceal active growth.

Large pilot creation also needed an authenticated HTTP setup path because Linux
limits individual command arguments. Above 120 KiB the host uses the official CLI
2.7.1 JSON-array reducer HTTP contract with its configured owner credential and a
30-second timeout. It does not retry an ambiguous outcome. Routine commands retain
the existing path. Fourteen host tests pass, including exact model-subset coverage,
credential parsing, setup threshold and resumed archive/deadline modes.

### Mixed-model, human-client and observer result

`output/sustained-clock/mixed-72-120s` passed its declared mixed-workload gate.
Five of six attempted model calls completed with five accepted operations across
both actors: three built-in and two external. The external learning call was
interrupted at shutdown; its partial exchange and unknown delivery/cost warning
remain in the journal. This does not establish six completed calls or sustained
model access at larger populations.

All four automated human wait intentions were accepted in 249–496 ms. The same
identity reconnected, recovered exact participant reads and passed receipt
idempotency. The separate developer observer received 193 updates with 656.83 MB
of JSON bodies during the client's 43.209-second interval, excluding network
framing. Full production owner exports also ran; neither source fed audit truth
to a model. The run reached 1,618 physics updates in 120 seconds (13.48/s), with
120,004 ms simulated. The mixed change cannot isolate one cause of the slowdown.

Final history contains 130,666 contiguous events, no engine errors and no remaining
grants after cleanup. Active service RSS peaked at 0.97 GB and retained WAL at
0.90 GB. The host stopped before final capture; the authority service subsequently
required forced shutdown (137). The human interface was exercised by a scripted
client, not a person. Cadence and observer bandwidth remain failed scale targets.

### Ten-minute soak: completed duration, failed living-population gate

`output/sustained-clock/guard-72-600s` completed the full 600-second window with
72 persistent connections and 40 read bursts, without a resource abort or restart.
It remains an **overall failed trial**: 2,124 reads succeeded and 756 received the
expected dead-character refusal. All rejected receipts match the client exactly,
and each affected actor's death precedes its refusal in the authority history.
Deaths began at 232,511 ms; 36 actors died by 480,001 ms. No characters were revived
and the fixture was not changed to conceal this outcome.

The clock performed 11,325 updates (18.875/s), simulating 600,002 ms with 675 missed
slots and 631 ms maximum lateness. This also fails 20 Hz, and the reduced living
population makes the latter portion unsuitable as capacity evidence for 72 living
actors. Read receipt latency, including refusals, was p95 654 ms and maximum 779 ms.
There were no script errors, all clients disconnected, the clock paused in 247 ms,
and cleanup verified zero remaining grants. Optional post-trial clock-control
checks were correctly skipped after the failed workload gate; earlier dedicated
control/outage tests remain separate evidence.

Active RSS peaked at 1.25 GB (1.42 GB including finalization). Retained WAL peaked
at 3.79 GB and ended near 2.82 GB; it fell during the uninterrupted run, so the
retained-size gauge must not be interpreted as cumulative writes. The complete
history contains 649,770 contiguous events, with 647,680 archived and 2,090 live.
Archived encoded content was 310.13 MB, compressed to 32.96 MB. This verifies the
active-tail bound for this finite run, not a bound on total durable history or
personal evidence. The retained final snapshot preserves the deaths and failures.
Service shutdown still required exit 137.

A later sustained-population test needs an explicitly declared provisioning
workload that keeps its intended living population, while retaining any failure
as a real outcome. This run must not be relabelled as successful 72-actor capacity
or silently substituted with a fixture that disables mortality.

### Regional-processing decision (superseded priority)

The user subsequently prioritized the [client/authority boundary](CLIENT_AUTHORITY_BOUNDARY.md)
and deferred regional processing on the current 48×36 maps. The following proposal
is retained as historical analysis, not the current next implementation.

Proceed with a bounded regional-work prototype as the next scale slice. The
216-actor deadline reducer already averages more than twice the 50 ms budget,
and the spread workload performs worse despite lower initial density. Increasing
the actor cap or subdividing subscriptions alone cannot resolve that evidence.
This is a decision to measure a regional implementation, not evidence that a
particular partition size or multi-database topology will meet the target.

Keep the first prototype in one authority and reuse the exact shared kernel.
Index hot actors, due work and spatial interactions by region; load the affected
regions and an explicit interaction boundary, and measure cross-boundary travel,
communication, combat, perception and resource effects. Preserve one ordered
causal history, pending law activation and actor identity across region changes.
Differential tests must compare the same actions and final state against the
existing whole-world authority. A region subscription must never grant access to
unperceived actors or their private history.

Measure actor execution, neighbor-query work, region crossings, write amplification
and observer delivery separately before selecting a region size. Within one
database this reduces transaction work but does not demonstrate parallel write
capacity. Multi-database ownership transfer requires a separate protocol and
failure/recovery design; this experiment does not authorize silently splitting
physical rules or replacing them with another simulator. Independently address
WAL retention and growing character evidence: compact active audit tables alone
do not bound durable storage. A thin incremental developer observer also needs a
separate delivery path before larger mixed workloads.

## Final validation and scope

The completed focused checks include 216 kernel tests (one existing ignored),
21 authority module tests, 39 storage-codec checks, bridge library/export checks,
and 14 development-host tests. Final Python checks passed six cleanup tests,
six owner-snapshot tests and two audit-archive tests. Changed Python files parse,
local documentation targets exist and `git diff --check` passes. Generated bindings
cover the new authority archive/deadline interfaces; no client presentation change
was needed. Live access, restart, outage, mixed-controller and population evidence
are reported separately above rather than inferred from unit tests.

All five requested stages received their ordered implementation/measurement pass.
The resulting source remains a bounded improvement, not an accepted 20 Hz or
thousand-player system. All experiment services are stopped, retained volumes and
original failed artifacts remain available, and the existing development service
was not upgraded or reset.
