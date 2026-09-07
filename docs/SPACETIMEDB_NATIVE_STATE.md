# Native authority state

New foundation runs store canonical state in private SpacetimeDB tables grouped
by access pattern. Participant commands and participant Bevy input use indexed,
actor-scoped transactions through the existing simulation kernel. They no longer
hydrate, clone or serialize the whole World. The global clock still executes the
shared deterministic World kernel; this refactor does not establish thousand-player
capacity or sustained 20 Hz.

## Design and version evidence

Official guidance consulted:

- [Table design](https://spacetimedb.com/docs/tables/) and
  [indexes](https://spacetimedb.com/docs/tables/indexes/): independently accessed
  state belongs in separate rows, with entity and location indexes.
- [Views](https://spacetimedb.com/docs/functions/views/) and
  [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/): procedural
  view dependencies affect recomputation. A changing header must not read or
  retransmit retained observations. Subscription filters are not authorization.
- [Performance](https://spacetimedb.com/docs/tables/performance/): measure real
  transactions, fan-out and retention. Pool capacity is not resident memory.
- [Pinned Rust API](https://docs.rs/spacetimedb/2.1.0/spacetimedb/): module and
  native client dependencies remain at 2.1.0; bindings use CLI 2.1.0. No SDK upgrade
  or reliance on announced storage features is part of this change.

## Storage and execution

| State | Access pattern |
| --- | --- |
| Run head | Small typed clock, event cursor and runtime counters |
| Actor bodies | Typed identity, position and physical state; `(run, position)` index |
| Private minds | Execution and frequently updated fields, with separate private mind-history rows |
| Participant state | Revisions, speech queue and learning state; ordered references to individual private experience rows |
| Leases / captures | Bounded evidence metadata and separate immutable captured context |
| Sites / stations / archives | Separate entities; location indexes for local dependencies |
| Definitions | Shared configuration, scripts, law revisions and balance |
| Audit | Existing append-only causal events, preserved independently of character memory |

Nested mind histories and authored programs remain serialized within their
component rows; participant experiences are individually addressable. This is
not a fully relational representation of every memory or program. The later
[clock optimization pass](NATIVE_CLOCK_IMPLEMENTATION.md) records history
separation, migration compatibility and measured runtime/cache effects.
The old compact root/blob schema remains readable for explicit migration; new
runs have no canonical World JSON root or `sim_world_blob` payloads.

`ParticipantTransaction` calls the same `World` participant methods as the full
kernel. Its dependencies are the authenticated actor's body and private state,
co-located public bodies/lifecycle, local stations, station-owner arena membership,
actor support/materials, shared rules and surveyed configuration. It can commit
only the actor, participant state, wake flag, event cursor, audit events and law
faults. It cannot advance physics. Policy/manual input and speech enqueueing use
this boundary; their physical effects still execute under the scheduled clock.

The participant Bevy snapshot loads the same scoped dependencies. The actor-3
human-controller availability flag uses a separate point lookup. Observer views
and owner exports intentionally load full state. Bevy retains its existing JSON
presentation contract, so its snapshot is not as incremental as the agent path.

The global clock loads mutable components, preserves deterministic movement,
perception, speech, ecology, population and law ordering, then updates changed
rows. It skips captured observation bodies. Explicit exports materialize those
bodies and fail if any are missing. Copy-on-write character/participant state
avoids deep-cloning every mind for each candidate action, while retaining rollback.
Unchanged participant state avoids lease serialization and receipt/read scans.

## Incremental delivery and authority

Agents subscribe to three sender-authenticated views: participant head, receipts
and immutable reads. Receipt/read lookups use `(run, actor)` indexes. Receipt
completion is correlated by request ID; observation responses are read directly
from their immutable row. A captured read's identity is its lease ID, because a
request ID may be reused after receipt eviction. Header changes do not republish
captured contexts. The legacy status view assembles the previous response shape
for compatible clients after delivery rows have been populated.

Controller changes clear leases; revocation/reassignment changes the authenticated
view scope. Expired responses leave delivery at the existing simulation-time
boundary. Character trace and lease retention follow the existing limits (256
trace entries, 64 receipts, four leases, 330,000 ms lease lifetime). None of these
operations deletes the separate developer audit. Nested durable learned state and
audit history still need a long-term retention/storage design.

## Verification and measured result

The final candidate passed 16 module tests, 202 kernel tests (one existing ignored
test), 39 legacy-codec tests and two delivery tests. Differential checks compare
complete authoritative state and exact events across five scenario families,
including accepted/rejected participant commands, learning, idempotency, death,
Bevy input and scoped presentation. Deferred-capture checks verify physics parity
and refuse incomplete exports. Client compilation and all 36 bridge library tests
passed. The first bridge run failed audit writes under `/tmp`; rerunning with a
fresh disk-backed `TMPDIR` passed. Both logs are retained.

Live SDK checks passed for ungranted/observer isolation, private-table denial,
owner-operation denial, Bevy snapshot/input, old/new status parity, reconnect,
request-ID reuse, exact expiry, revocation, stale epochs and cross-run reassignment.
A separate fresh database was published with the old module, populated with a
captured read and queued speech, then upgraded. Migration preserved the exact
World and audit, collected legacy blobs, was idempotent, and subsequently executed
the queued speech through the real clock kernel.

The same original 36-person faction scenario ran for 60 wall-clock seconds, with
36 persistent connections and four simultaneous rounds of 36 observations. Every
one of the 144 reads passed the unchanged ten-second deadline and authority
reconciliation. No model calls, observer subscription or concurrent build occurred;
owner exports were at paused boundaries. Each performance run used a fresh service,
volume and database, a 12 GiB service limit with no extra swap, and the same 8 GiB
page-pool maximum. Access/migration fixtures ran after performance sampling stopped.

| Measurement | Original | Final native state |
| --- | ---: | ---: |
| Successful, reconciled reads | 144 | 144 |
| Maximum read completion | 9,822 ms | 430 ms |
| Simulation updates in 60 s | 104 | 563 |
| Simulation elapsed | 59,783 ms | 59,933 ms |
| Subscription bodies within fixed window | 321,288,418 B | 23,607,476 B |
| Isolated service peak RSS | 2,397,294,592 B | 1,720,967,168 B |
| Peak RSS during active window | 2,259,480,576 B | 1,644,773,376 B |
| Pause acknowledgement | 749 ms | 42 ms |
| Participant reducer WASM execution, approximate window total | 24.845 s | 0.889 s |
| Participant queue wait, summed across 144 requests | 450.396 s | 22.982 s |
| Retained message-log size, last telemetry sample | 146,770,500 B | 514,438,555 B |

Original body samples count JSON; new samples count BSATN rows. These are payload
measures, not complete network frames. Earlier intermediate notes counted all
samples; the table above consistently uses the declared fixed window. Reducer
counter deltas use the nearest one-second telemetry samples. These are single
finite runs, not statistical benchmarks. The faster clock performs more updates
and produces more audit events; equal wall duration does not mean identical work.

Retained log size increased, so this is not evidence of reduced disk growth. The
last native sample contains 36 body/mind/participant rows, 144 leases/captures/read
rows, 144 receipts, 17,983 audit events and zero legacy blobs. Telemetry is sampled
and may precede cleanup; explicit cleanup queries are authoritative for final grants.
The observed page pool was only about 2.8 MB. Final sampled jemalloc resident memory
was about 538 MB, and the per-database WASM gauge about 101 MB with 37 live instances.
The gauge does not provide the summed memory of those instances; multiplying it
by the instance count would not establish attribution of service RSS.

Evidence is under `output/native-state/final-default-pool/`, with source/WASM/probe
artifacts in `final-artifacts/`, test logs beside them, and derived comparisons in
`comparison.json` (generated by retained `summarize.py`). Earlier baseline and
intermediate directories are preserved. All fixture grants were revoked, measured
worlds paused, connections closed and the owned service stopped. Podman returned
exit 137 after its stop timeout; this was not a graceful database shutdown. Existing
experiment archives and their services were not migrated or reset.

## Existing-run migration

New runs use native storage automatically. For an existing run, pause it with the
old module and capture an owner export/audit checkpoint. Publish the new module to
the explicitly selected database, then call `sim_migrate_native_state` with that
run ID as its owner before resuming clients. The reducer compares the full restored
World inside the transaction and rolls back on mismatch. It preserves controller
state, receipts, evidence and audit; only obsolete representation rows are removed.
The run-level migration is explicit, not an automatic sweep over archived runs.
Old active subscriptions should reconnect after the schema update/migration.

The benchmark's `--migration-baseline-wasm` option reproduces the verified upgrade
on a separate fresh database. `--access-probe` runs the live authorization suite.
Neither option touches an existing archive.

## Remaining scale work

The global clock still scans the run and performs broad physics/perception work.
It reached about 9.38 updates/s here, below sustained 20 Hz. Native local commands
remove an important bottleneck but do not remove global event-head contention,
all-world clock execution, growing audit/log storage, or the existing actor cap.
Shared law and survey definitions also grow with world complexity. Narrowing
clock execution requires an explicit dependency/scheduling design that preserves
remote infrastructure, arbitrary applicable perception laws and causal ordering.
Longer runs, larger populations, dense local populations, model traffic and observer
load remain unverified. No thousand-player or production-capacity claim follows
from this 36-actor result.

The subsequent [72/144-actor density trials](NATIVE_SCALE_TRIALS.md) extend this
one-minute evidence. They expose much lower clock cadence and a 144-actor memory
guard failure during finalization; use those findings for further scale decisions.
