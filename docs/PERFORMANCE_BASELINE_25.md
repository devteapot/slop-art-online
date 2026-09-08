# Short performance baseline (25)

Later review: [stack and architecture diagnosis](STACK_PERFORMANCE_REVIEW.md)
identified 245 full owner `sim_run` evaluations consuming 53.42 seconds in the
failed browser minute. The host launch used its SQL snapshot default, activating
a known expensive compatibility view. Original failure evidence is unchanged;
this is not a clean browser-renderer capacity result. The review evaluates 30 Hz
without changing the locked target.

2026-09-07. Short checks against the [locked contract](PERFORMANCE_CONTRACT.md).
No acceptance gate passes. The 30-minute and eight-hour runs are deliberately
excluded. Changes are diagnostic instrumentation, not authority rules or balance.

## Workload

Artifacts: `output/realtime/baseline-25/`, starting with `manifest.json`. Each
attempt retains its scenario, source, binaries, configuration, logs, metrics and
shutdown status. Successful runs also retain correlated client events, a paused
world export and the complete audit. Original failures remain separate.

The two latency runs each measure 60 seconds with 216 living characters, 215
native controllers, one automated human and one SDK observer. Nine occupied
cells initially hold 6–48 characters each. Normal render subscriptions are enabled;
the observer also inspects one character. Human input is about two actions/second,
including ordinary rest/eating. Seed policies include observation, waiting,
gathering, movement and infrastructure needs. No inference calls occur. Full
exports happen after pausing. Configured action interval is 16 ms (62.5 Hz), since
the integer-millisecond API cannot express exactly 60 Hz. Actual intervals are
compared with the 16.667 ms requirement.

Host: Ryzen AI MAX+ 395, 16 physical/32 logical cores, Radeon 8060S, about 62 GiB
RAM. Each service has a 6 GiB memory cap and 3 GiB page-pool bound. Load generation
shares the host; 16 backend vCPUs are not reserved. This is a diagnostic, not
certification of the 16-vCPU/64-GB resource envelope. Runtime 2.10.0, SDK/bindings
2.1.0, control CLI 2.7.1 and exact hashes are recorded.

## Input and physical timing

| Workload | Movement outcomes | Input → movement outcome p50 / p95 / p99 / max |
| --- | --- | --- |
| Loopback | 104 | 101 / 360 / 571 / 574 ms |
| Added 80 ms RTT | 104 | 194 / 396 / 518 / 647 ms |

Both runs sent 107 inputs: 104 moves, two rests and one eat. Every input received
a successful callback, accepted receipt and terminal outcome. Exact request →
command → attempt → result links are checked against the audit, including received
position versus actual result position. Intentional rests take about 2.6 seconds
and are reported separately. Movement alone fails **150 ms p95 / 250 ms p99** at
80 ms added RTT.

The TCP proxy adds 40 ms per direction, preserving byte order without an intentional
bandwidth throttle, loss or jitter. Four concurrent 256-KiB echo checks returned
identical bytes in 84.3–84.4 ms. During the workload, extra scheduling delay beyond
40 ms was about 1.54 ms p95 and at most 2.62 ms per chunk. One connection-close
error is retained; no measured input lacks an outcome. This is local propagation
emulation, not an Internet impairment suite.

On loopback both renderers observed all 2,641 update IDs, including the initial
frame. Logical physical-update intervals were 16 / 57 / 158 / 485 ms at
p50/p95/p99/max; 891 of 2,640 intervals exceeded 16.667 ms. The clock recorded
1,156 missed slots. Shared `sim_world_pulse` execution plus query work averaged
77.18 ms. These combined physical updates demonstrate gaps but do not establish
per-character 60 Hz combat cadence.

SDK timestamps distinguish send, server invocation, callback and terminal frame
receipt. Invocation is not network ingress; terminal receipt includes downstream
delivery after commit. Exact server-receipt → committed-outcome p95/p99 remains an
instrumentation gap. Mean reducer time and acknowledgements are not that metric.

## Capacity and combat startup

Actual 2,000-character creation fails. The original large scenario hits HTTP 413;
the compact, correctly named follow-up reaches the authority and returns
`scenario needs 1..256 players and 1..10000 ticks`. An intermediate namespace
error is retained separately. More duration cannot resolve admission failure.

The 200-character single-cell paired-attack scenario fails creation with
`target not perceived`. The recent-memory limit is 16, so early target sightings
have fallen out of memory when seed policies are installed. A follow-up enables
the existing lifecycle people catalog to retain local target knowledge. Creation
then fails with HTTP 402: service logs identify the node's execution-energy budget
being exceeded in `sim_create_client_world`. This is a runtime execution limit,
not a model-provider billing response. Neither attempt produces a timed battle.
No immunity, resurrection or larger execution budget was introduced.

Projectiles and dodges are absent from active foundation mechanics. Retired legacy
gameplay does not fill those acceptance gaps.

A separate 12-character, same-cell, paired-attack diagnostic completed ten seconds:
72 attempts, 54 damage events, six deaths. Deaths occurred at world times
3,217–3,457 ms. Later attacks against dead targets remain failures. Observer
physical-update intervals were 16 / 17 / 17 / 19 ms at p50/p95/p99/max. This
verifies ordinary attack execution and permanent death; it is not sustained
12-character combat, much less the required 200-character battle.

## Actual browser workload

The Bevy observer loaded successfully in Chromium 151 at 1440×757 CSS pixels,
device scale 1, using hardware WebGL2 through ANGLE/Vulkan/RADV Radeon 8060S.
The default world/session panel remained open, including its ordinary metadata
polling. The development host resumed the same run with background harness work
disabled. Browser enrollment preceded the measured minute. One SDK human and
215 controllers remained; this run had the browser observer instead of an SDK
observer. Initial screenshot and adapter logs verify the real client connection.

The workload **failed**: the UI reported `database SQL read exceeded its 30-second
deadline`; both probe pause acknowledgements timed out. Controller relays logged
timeouts and recoveries. Of 100 sent human inputs, capture retained 81 callbacks,
19 still pending callbacks, 79 rejected receipts and only one terminal outcome
(40,660 ms). Those failed-window numbers are not an accepted latency distribution.
The final export retains 216 living characters but only two physical updates;
clock counters including cleanup are not a successful active-window rate. The
wrapper subsequently paused/exported the world and both services stopped with
exit code 0. The original probe failure remains recorded.

During the declared minute, 3,600 `requestAnimationFrame` intervals averaged
59.97 Hz: p95 16.7 ms, p99 16.8 ms, maximum 33.4 ms. With floating-point tolerance,
95.42% were ≤16.7 ms; two exceeded 17 ms and none exceeded 50 ms. Browser timestamp
quantization matters near the threshold. These are callback gaps, not GPU-present
completion or input-to-photon measurements. A smooth callback loop coexisted with
a severely delayed authoritative world. This does not pass the 99%-within-16.7-ms
client requirement, and cannot establish minimum-hardware or combat acceptance.

## Resources and evidence

Loopback world/controller/relay peak RSS: about 1.25 / 0.76 / 0.42 GB, including
enrollment. Sampled CPU: 52.1 / 24.35 / 24.5 CPU-seconds. World WASM reported a peak
of about 148 MB. Allocator, pool, table and wire metrics remain in each run's
`summary.json`.

The human renderer received about 90.3 MB of serialized application frames; the
observer received about 242.2 MB including events. These are application payloads,
not compressed wire bytes. The exact audit has 129,178 events. Retained world /
controller WAL at the sampled end is about 545 / 759 MB, including setup, not
cumulative writes. Controller retention after cleanup records 131,200 archived
and 67,220 active journal records across 215 controllers. A minute cannot establish
bounded memory, sustainable storage or steady archive backlog.

## Correctness and client limitations

Kernel tests: 231 passed, one ignored. Bridge checks: 37 library, 14 development
host and two lab-host tests passed. The original bridge attempt failed because
`/tmp` exhausted its quota; rerunning with workspace `TMPDIR` passed. Both logs are
retained. Tests cover scoped evidence, control epochs, reconnect receipts,
interruptions, movement costs and slow-provider cancellation. The latter advances
the shared kernel while mock HTTP is delayed; it is not a loaded actual-authority
model workload.

The actual dual-service boundary probe passed all 16 checks: scoped/denied world
and mind access, observer inspection and revocation, incremental rendering,
delivery cursor bounds/recovery, both transport reconnects, retained policy and
in-flight completion without duplication. Its subscribed journal retained all
417 records with zero visible deletions while crossing an archive boundary.
These are bounded functional checks, not privacy-at-2,000 acceptance.

Restarting the retained, paused loopback service preserved the complete world
and all 129,178 audit events byte-for-byte (SHA-256
`3ef778cc2590495a150a9d8fb2edb5b54470e7d068cf9bf64bb6a41ec5b2ca8b`).
This restart is a separate recovery check after measurement; it does not hide
growth or convert a failed run into success. All seven experiment service pairs
stopped with exit code 0. Original development services were left untouched.
The ignored kernel test is an opt-in microbenchmark, not an ignored correctness
case. Probe/browser builds, Python compilation and `git diff --check` passed.

The client sends movement intent and smooths received authoritative positions;
local movement prediction is absent. There is no explicit configurable FPS cap
in the foundation client; Bevy window defaults apply. Higher-refresh acceptance,
input-to-photon latency and prediction-correction quality need further capability
and measurement. Headless timing cannot certify physical-display latency, and
minimum client hardware has not been defined.

## Contract disposition

| Requirement | Short baseline disposition |
| --- | --- |
| 60 Hz active physical execution | Fails crowded update timing; 200-character combat cannot start. Small combat is partial evidence only. |
| ≤50 ms p95 local feedback | Unverified input-to-photon; movement prediction is absent. |
| Server receipt → commit ≤50/100 ms | Exact endpoints not instrumented. Invocation, callback and delivery timestamps are retained without relabeling. |
| 80 ms RTT confirmation ≤150/250 ms | Fails: movement p95/p99 396/518 ms. |
| 60 FPS, 99% frames within ~16.7 ms | Headless callback diagnostic recorded; no minimum-hardware/combat acceptance. Browser authority flow also fails. |
| Configurable 120/144/165/240+ FPS | Explicit cap support absent; physical-display verification pending. |
| Slow systems do not block combat | Crowded maintenance averages 77.18 ms; timing requirement not met. Kernel deadline/cost checks pass. |
| Model latency independent of behavior | Unit cancellation/independence checks pass; no inference in measured authority workloads, so loaded model-workload acceptance remains open. |
| 2,000 active characters / 200 local combatants | Admission limit and combat creation failures established. |
| Backend envelope, bounded memory and backlog | Short CPU/RSS/WASM/pool/traffic/table/WAL evidence retained; shared host and short duration cannot certify the envelope or bounded growth. |
| 30-minute / eight-hour sustained gates | Deliberately not run, as requested. |

## Diagnostic implementation

The population probe now supports correlated direct actions with normal rendering,
terminal/render timestamps, a separately delayed human endpoint and a start gate
for browser enrollment. `summarize_performance_baseline.py` checks causal outcomes
and splits latency by skill. `delayed_tcp_proxy.py` records timing and byte counts
without payloads or credentials. Authority tables, reducers and generated bindings
are unchanged.

Official documentation consulted before probe changes:
[overview](https://spacetimedb.com/docs/),
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/),
[reducers](https://spacetimedb.com/docs/functions/reducers/) and
[performance](https://spacetimedb.com/docs/tables/performance/).
The pinned SDK event timestamp is invocation time. Subscription delivery and
reducer completion are distinct from physical outcome. Scoped views remain the
live read path; privileged complete exports are explicit paused diagnostics.
