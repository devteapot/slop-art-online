# Shared remembered-target sets (41)

2026-09-08. Continues [shared trace loaders](SHARED_TRACE_LOADERS_40.md) toward
the [world](WORLD_VISION.md), [simulation](SIMULATION_VISION.md) and
[performance contract](PERFORMANCE_CONTRACT.md) objectives. Retained: exact
combat comparisons show lower repeated-copy cost, while live cadence still
fails the contract.

## Constraint and change

Iteration 40 still reaches 116.82 ms in actor execution and 126.37 ms in complete
action execution during a dense witness burst. Every scripted action stages a
candidate World so a failed invocation can roll back all its effects. Mutating
a witness participant detaches that participant's retained state. Its controller
previously deep-cloned the complete remembered-target BTreeSet, even when the
event merely named a target it already knew. A sequence of deaths can repeat
this copying for the same surviving witnesses across candidate actions.

The controller now keeps that set in the existing copy-on-write Deferred
container. Recording a known identity checks membership through the immutable
view first; duplicate insertions do not invoke mutable access and therefore do
not detach the set. A newly remembered identity still detaches before insertion.
General mutable operations retain the container's ordinary isolation semantics.

Each character preserves its exact remembered identities. Nothing is forgotten,
learned from an unauthorized source, filtered differently or inherited by a new
identity. Physical perception and target checks remain unchanged. Only retained
snapshots of the same state share storage; this is not a proximity-learning
mechanism or a cross-transaction cache.

## Documentation and data access

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance](https://spacetimedb.com/docs/tables/performance/) and
[indexes](https://spacetimedb.com/docs/tables/indexes/) before the change. The
authority still reads and writes the same actor-scoped controller rows, including
their typed target vectors. Assembly collects those vectors into the kernel's
set and saving preserves their ordered values. This change promises no reduction
in database reads, row writes, subscription recipients or retained data.

The World JSON and stored table/interface shapes remain unchanged, so generated
bindings are retained. SDK 2.1.0, control CLI 2.7.1 and service 2.10.0
(`b22dfaac6d46`) remain fixed. Normal builds contain no profiling timers.

## Correctness checks

The kernel suite passes 248 tests with one existing ignored test. New checks
prove that 200 duplicate observations retain the original target-set snapshot,
adding a new maximum-u32 identity detaches it, ordinary clearing cannot alter
another snapshot, and legacy JSON arrays preserve set ordering/deduplication.
A real dense death-witness sequence produces every expected witness while
keeping the unchanged remembered-target sets shared with the pre-action World.

All 39 storage-codec integration tests and 52 authority tests pass, including
cold physical execution, commands, scope, leases and reconstruction. The bridge
passes its release compile check against the changed public Rust field type.
The generated/wire interfaces and bridge logic are unchanged.

## Live release diagnostic

`output/realtime/scale-41/combat-shared-target-sets/` freezes the normal module,
source, controller module and probe. It uses the same scenario as iteration 40:
200 combatants initially at 100 health in one cell, 200 reference controllers,
one component observer with open inspection, 60 Hz physical scheduling and a
declared ten-second active window. No human connections or model calls are
present. Both services have 6 GiB memory and 3 GiB page-pool limits. Builds and
cache cleanup do not overlap the measured interval.

All declared post-pause checks pass: exact ordered audit export, trace/body
retention, catalog reconstruction, combat-feed scope/reconnect, and component
render equivalence. Both services exit 0. The trace has 200 heads, 1,762 pages,
2,480 bodies and 50,635 current references, with no legacy or extra current rows.
Payload sizes are 15,277,825 logical bytes and 824,081 stored bytes. These reflect
the actual trace and existing body sharing, not a new storage-format reduction.

| Live diagnostic | Iteration 40 | Shared target sets |
|---|---:|---:|
| Probe wall duration | 15,191 ms | 15,451 ms |
| Physical elapsed / survivors | 10,001 ms / 100 | 10,001 ms / 100 |
| Attack attempts / damage events | 1,104 / 856 | 1,086 / 840 |
| Deadline wakes / missed slots | 278 / 322 | 330 / 270 |
| Deadline execution plus query mean | 15.532 ms | 12.436 ms |
| Deadline p95 / p99 buckets | (50, 100] / (250, 500] ms | (50, 100] / (100, 250] ms |
| Scheduled queue p95 / p99 buckets | (10, 50] / (50, 100] ms | (10, 50] / (50, 100] ms |
| Action admission execution plus query mean | 0.992 ms | 0.982 ms |
| Observer physical gap p95 / maximum | 156 / 549 ms | 106 / 519 ms |
| Experience view calls / WASM total | 4,881 / 1,194.461 ms | 4,441 / 815.981 ms |
| Backend CPU | 17.79 s | 15.60 s |
| World outgoing WebSocket bytes | 18,007,913 B | 15,345,503 B |
| World peak RSS | 1,252,245,504 B | 1,188,442,112 B |
| World WASM peak | 158,990,336 B | 158,662,656 B |
| World jemalloc allocated peak | 493,229,992 B | 455,083,304 B |
| World jemalloc resident peak | 1,043,771,392 B | 967,057,408 B |

Observed missed slots fall from 53.7% to 45%, but the new run performs slightly
fewer attacks and damage events. One maintenance transaction falls in its sampled
interval versus two previously. These asynchronous runs do not isolate the
target-set change. Observer gaps combine physical update types and do not
establish per-actor combat cadence or rendered FPS. No acceptance gate passes.

Resource gauges are sampled and no swap is observed. Retained WAL changes from
104,953,021 to 174,240,313 bytes for the world and 101,489,580 to 336,596,089
bytes for controllers. Unknown gauge refresh times prevent treating these as
cumulative writes or steady-state growth rates. All original outputs and
volumes remain retained.

## Controlled combat comparison

`output/realtime/scale-41/targets-combat-paired-authority/` compares the frozen
normal modules from iterations 40 and 41 on the actual SpacetimeDB authority.
Both databases are published before setup. One warmup and two measured fresh
worlds per database remain retained throughout; each world advances through two
2,500 ms owner steps, alternating module order by step and repetition. These
coarse explicit advances isolate implementation cost, not real-time scheduling.

Each world contains 200 colocated characters initially at 20 health, with no
starting behaviors or disturbances. Before timing, an authorized participant
installs one attack per actor against its adjacent paired actor. The ordinary
grant and participant command paths validate ownership, epoch and revision;
every successful receipt and installed action is checked. Moving the grant
preserves the previously installed physical behavior. This setup uses one
sequential participant identity per world and no live controller, relay, model,
human or observer connections. Setup, exports and grants are outside timing.

The driver compares complete canonical World state initially and after every
advance, then every ordered audit event. Each final world must contain exactly
100 deaths, 100 damage events and 14,950 death observations. The first step
contains the combat burst; the second covers subsequent settling. Reporting
these separately avoids attributing unrelated maintenance cost to target sets.

After timing, the driver checks exact leased evidence after 260 trace evictions
and deletion of its final current body reference, private-table denial for a
scoped outsider, native trace reconstruction, and publication of the new module
over the reference database without changing any of its three retained worlds.
The service's memory spans six worlds and is not a single-world estimate.

All comparisons and post-measurement checks pass, including 56,950 identical
ordered audit events per world before the lease checks. The service exits 0.

| Measured authority work | Iteration 40 | Shared target sets | Change |
|---|---:|---:|---:|
| Two combat bursts: execution plus queries | 981.324 ms | 930.093 ms | −5.22% |
| Two combat bursts: WASM | 906.148 ms | 856.137 ms | −5.52% |
| Two settling steps: execution plus queries | 523.111 ms | 518.648 ms | −0.85% |
| All four advances: execution plus queries | 1,504.435 ms | 1,448.741 ms | −3.70% |
| All four advances: WASM | 1,426.654 ms | 1,372.065 ms | −3.83% |
| All four advances: CLI wall time | 1,582.046 ms | 1,523.823 ms | −3.68% |

Both measured bursts improve individually (494.725 to 465.192 ms and 486.599
to 464.902 ms). This supports retaining the allocation change for this exact
workload. Two measured repetitions do not establish a general speedup or a
sustained capacity result. Each coarse step includes the unchanged maintenance
and persistence work; its duration is not a 60 Hz transaction measurement.

## Instrumented live diagnostic and remaining work

The separate `combat-shared-target-sets-profile/` run retains the same declared
live scenario and all profiling logs. All five post-pause checks pass, with
65,701 contiguous audit events and both services exiting 0. Its 15,766 ms probe
covers 10,113 ms of physical time, 298 combined updates and 100 survivors.
It performs 1,001 attacks and 780 damage events, versus 956/754 in the previous
profile and 1,086/840 in this iteration's release trial.
Durable counters record 295 wakes and 311 missed slots (51.3%); the measured
deadline p95/p99 execution-plus-query buckets are (50, 100] and (250, 500] ms.
Queue p95/p99 are (5, 10] and (50, 100] ms. This is an instrumented diagnostic,
not a replacement for the normal release result or a sustained gate.

| Instrumented deadline phase | Total | Samples | Maximum |
|---|---:|---:|---:|
| Actor execution | 453.901 ms | 293 | 62.244 ms |
| Complete action execution | 693.085 ms | 292 | 69.760 ms |
| Action save | 569.348 ms | 292 | 83.514 ms |
| Death-witness work | 77.046 ms | 100 | 9.918 ms |

Nested timers overlap and must not be summed. The largest execution span loads
200 actors with 174 alive and due, producing 10,020 events at physical time
4,703 ms. The previous profile's largest span had 198 due actors and 15,531
events, so its 126.37 ms maximum cannot serve as an equivalent-work comparison.
Two maintenance transactions also fall in the new measured window. Save and
delivery stalls remain substantial despite the controlled allocation improvement.

This profile retains 200 trace heads, 1,764 pages, 2,306 bodies and 50,654 current
references; exact reconstruction verifies 22,460,467 logical payload bytes from
810,925 stored bytes, with no legacy/extra rows. Peak world RSS is 1,268,342,784 B,
WASM 158,990,336 B, allocated memory 461,725,312 B and resident allocator memory
1,023,758,336 B. No swap is sampled. Backend CPU is 16.64 s and outgoing world
WebSocket traffic is 18,114,358 B. Retained world/controller WAL endpoints are
107,066,230 → 184,222,232 B and 102,009,615 → 383,199,445 B respectively; these
sampled gauges do not measure cumulative writes.

The normal module is rebuilt after profiling and verified byte-identical to the
frozen release module. Validation logs and hashes are retained in `validation/`.
Completed native compiler caches and test binaries were reclaimed outside all
measurement intervals, with per-file manifests. All experiment artifacts and
database volumes remain retained; the development service is unchanged.

Retain shared target sets for the exact controlled improvement and snapshot
isolation evidence. Next work must address the remaining execution/save/delivery
critical path, whole-world maintenance and the 256-character initialization
boundary. This pass does not establish sustained 216-character or 2,000-character
capacity, population sustainability, client FPS or autonomous world outcomes.
