# Actor-scoped control changes (44)

Grants and revocations now use the existing actor transaction for native
participant worlds. At 2,000 characters, five measured grants average 71.21 ms,
down from 1,420.74 ms; five revocations average 68.00 ms, down from 1,404.78 ms.
Complete authority state and ordered control audit match the shared full kernel.
This improves access operations but does not pass the
[latency or sustained population gates](PERFORMANCE_CONTRACT.md).

## Design and documentation

Before selecting this boundary, consulted the official
[SpacetimeDB documentation](https://spacetimedb.com/docs/),
[reducer transactions](https://spacetimedb.com/docs/functions/reducers/), and
[indexes](https://spacetimedb.com/docs/tables/indexes/).
The authority still uses Rust SDK 2.1.0, control CLI 2.7.1, and isolated service
image `b22dfaac6d46`. No table or public API changes require binding regeneration.

`GrantWorld` reads the run and native head by primary key, validates the current
rules and operator, and checks eligibility through the addressed actor key.
The existing `(run, actor)` access index enforces exclusive control. Observer
and identical-grant operations need no world hydration or simulation save.
Legacy normalized archives keep their existing full-world adapter.

A native control change calls `World::change_control` through
`ParticipantTransaction`. Its dependencies are the actor's body, mind, support,
participant/controller metadata, leases, lazy own evidence and shared
definitions. There is no peer-body, other-mind or station scan. The existing
actor commit updates the epoch, lease retention, personal evidence, scoped
publication and ordered audit. It recomputes that actor's clock hint, including
queued-speech cancellation. It does not increment the full-world transaction
counter or republish the global render clock merely because access changed.
Global maintenance deadlines and physical state are unchanged by this operation.

A same-world handoff applies both actor changes in order. A cross-world handoff
validates each operator and applies both storage adapters inside the same reducer;
any error rolls back the transaction. The shared kernel invalidates slow work
and evidence leases, cancels queued speech, and preserves installed physical
behavior. Existing observer semantics are retained: changing a grant to observer
for the same run and actor does not itself advance the epoch. Reclaiming control
from that observer does advance it. This is compatibility evidence, not a new
permission policy.

The actor transaction still reads the complete initial definition. The 2,000-person
seed exceeds the definition cache's 1 MiB retention bound, so it is decoded again
on each such read. Removing this unnecessary dependency where the kernel does
not consume it is the next candidate; this experiment does not attribute the
entire remaining latency to that read.

## Correctness and retained failures

The [frozen source and release module](../output/realtime/scale-44/implementation/manifest.json)
record the tested implementation. The [authority tests](../output/realtime/scale-44/validation/unit-tests-corrected.log)
pass all 54 tests; the [kernel suite](../output/realtime/scale-44/validation/kernel-tests.log)
passes 253 with one existing ignored test. The new differential check covers
participant and client modes across five world scenarios, comparing complete
state, ordered audit and actor clock hints after repeated control changes with
live behavior, captured evidence and queued speech.

The initial test fixture submitted a client-only start-action command to ordinary
participant mode. Its [failure](../output/realtime/scale-44/validation/unit-tests.log)
and [diagnosis](../output/realtime/scale-44/validation/control-test-diagnostic.log)
remain; the corrected fixture uses the mode's existing command API.

The [actual old/new authority comparison](../output/realtime/scale-44/grant-parity-authority/result.json)
performs 66 complete world-and-audit checks across ordinary, participant and
client worlds. It covers grants, identical retries, same-actor observer changes,
reclaiming control, actor/world handoffs, stale requests, revocation and actor-zero
observers. Sixteen denials cover collisions, invalid eligibility, foreign
operators, cross-owner replacement and foreign revocation. Grant rows match
between implementations; failed operations preserve them. The service exits 0.

The full-population diagnostic reopens the preserved database from
[initialization 43](STAGED_WORLD_INITIALIZATION_43.md), exports its exact starting
state, measures five grant/revoke cycles on actor 1999, upgrades the module, and
repeats five cycles. It also measures one identical retry and observer grant/revoke
per version. The final complete world and all 20 new ordered audit events match
replay through the frozen 43 shared kernel **byte for byte**.

Its original [checker failure](../output/realtime/scale-44/population-2000-grant-authority/failure.json)
is retained: a standalone `rustc` invocation linked incompatible `serde_json`
feature sets, incorrectly wrapping generic numbers in the expected world.
The audit already matched. A separate Cargo checker unifies JSON features;
its [source, dependency versions and exact result](../output/realtime/scale-44/population-2000-grant-authority/corrected-checker.json)
are retained alongside the malformed output. Only the offline checker reran.
A [read-only restart](../output/realtime/scale-44/population-2000-grant-recovery/result.json)
confirms epoch 20, the original actor-2000 grant and accepted request, all 2,000
characters and tick/time zero. Both diagnostic service stops exit 0. The original
failed run is not relabeled as an uninterrupted successful run.

## Actual authority measurements and limits

[Measurements and resource points](../output/realtime/scale-44/population-2000-grant-authority/measurement-summary.json)
use the same preserved world: 2,000 characters, 200 colocated and 1,800 distributed,
on the existing Ryzen AI MAX+ 395 host. The isolated service has a 6 GiB limit and
3 GiB pool budget. There is no physical clock, inference, subscribed observer,
active controller population or competing request stream. Requests are sequential;
exports and offline replay are excluded from reducer measurements. There is no
sustained workload duration or action-rate claim.

| Operation | Samples per version | Reference mean | Candidate mean | Candidate range |
| --- | ---: | ---: | ---: | ---: |
| Grant control | 5 | 1,420.74 ms | 71.21 ms | 68.28–76.92 ms |
| Revoke control | 5 | 1,404.78 ms | 68.00 ms | 67.21–69.25 ms |
| Identical grant | 1 | 1,395.30 ms | 0.107 ms | single sample |
| Observer grant | 1 | 1,385.17 ms | 0.079 ms | single sample |
| Observer revoke | 1 | 1,349.14 ms | 0.088 ms | single sample |

These are reducer-plus-query execution times, not queue/network latency or a
population percentile. New control changes are approximately 20 times faster;
their remaining cost still exceeds the 50 ms latency threshold.

Process samples every 50 ms during measured calls peak at 2,561,703,936 bytes
before upgrade and 1,252,188,160 bytes afterward, with zero sampled swap. The
upgrade replaces the module instance, so these are not a controlled proof of
memory savings. Point measurements show WASM memory moving from 1,141,571,584 to
1,747,714,048 bytes during the old series, then 1,769,472 to 17,629,184 after the
upgrade. Service allocator resident bytes rise from 706,600,960 to 1,260,920,832
during the candidate series. Resource points are not continuous peaks and exports
are outside the sampled call intervals.

The retained message-log gauge is 510,024,585 bytes before the reference series
and 510,062,620 afterward; it remains at that sampled value during the short
candidate series. This gauge does not measure cumulative writes or prove zero
candidate writes. No sustained table-growth, subscription-volume or queueing
acceptance is established. Completed compiler cache cleanup is recorded separately;
no experiment volume or failed artifact is deleted.

The 216-character/30-minute and 2,000-character/8-hour gates, 60 Hz combat,
client frame rate, sustainable population and full model workload remain open.
