# Hybrid authoritative clock

The native scheduled clock now uses indexed due work, a compact active set and
transaction-local loading of private histories. Both paths execute the same
`World` mechanics. The original full actor scan remains the reference for
operator stepping, differential tests and an explicit diagnostic build.

This completes the scheduler implementation deferred by the
[first clock optimization pass](NATIVE_CLOCK_IMPLEMENTATION.md). It does not
establish thousand-player capacity or sustained 20 Hz. Body, world configuration,
site, station, archive and global subsystem scans still exist; the new path avoids
eagerly hydrating every private mind, trace payload and leased evidence body.

## Selection and ordering

Private `SimNativeClockActor` records have one primary key per run/actor and
indexes on `(run, active)` and `(run, due_ms)`. The clock unions active actors with
the due range up to the incoming simulation time, deduplicates them and keeps
the original **world actor order**. It does not run a separate reducer per actor.
`SimNativeClockState` records the index version, script revision and ordered actor
membership. A missing or incompatible index uses the full shared-kernel update
and rebuilds the index atomically when saving.

Hints include action/dialogue continuations, physiology boundaries and applicable
legacy reconsideration. Queued speech includes first-continuation initialization
and expiry; initialization is observable even when an earlier utterance still
owns the cooldown. Invalid law hooks keep an actor active so the normal update
reports its original failure. Participant mode still validates the reconsideration
hook, whose request effect is otherwise a no-op. Hints never apply gameplay effects.

Every participant commit publishes its actor's new hint. Global saves update
changed, active, due and dirty actors; revision/membership changes rebuild the
derived index. There is no growing queue of completed wakeups. The existing dirty
flag remains durable. Within an update, the kernel also notices actors changed
or woken by earlier actors, so a recipient can react in the same update without
reordering a contested resource operation. An actor already processed is not
executed a second time because a later actor wakes it.

Activation, ecology, infrastructure, ordered actor effects, lifecycle, lifecycle
observations, speech and request handling keep their original phase order.
Newborn physiological remainders advance exactly even on a skipped actor update.
Global phases continue using the shared implementation; arbitrary laws and remote
ownership are not assumed to have a fixed spatial dependency radius.

The host interval, elapsed-time accounting, maximum 60-second update and explicit
long-gap recovery remain unchanged. There is no timestep change, hidden catch-up,
discarded physical time or asynchronous model work inside the authority.

## Private data access and retention

`Deferred<T>` supplies a typed, transaction-local value through an exact storage
loader. Cloning shares the original value; mutation resolves and detaches it.
Serialization produces the same ordinary JSON shape and refuses missing data.
Storage-backed values are not retained across reducers or used as durable cache
identities. The simulation crate contains no database or network implementation.

| Data | Routine clock access | Index / growth |
| --- | --- | --- |
| Mind histories | First actual read or mutation loads that actor's history row once; individual fields decode when needed | Primary run/actor key; one history row per retained actor |
| Personal trace | Small ordered metadata stays with the participant; historical payloads load only when inspected | Primary run/actor/cursor key; existing 256-entry trace limit |
| Leased evidence | Clock retains lease metadata and stable references; unchanged leases avoid evidence reads and writes | New private `SimNativeLeaseEvidence`, primary lease ID; existing four-lease limit |
| Captured contexts | Continue using deferred immutable captures during clock updates | Existing lease ID; explicit exports materialize captures |
| Scheduler | Active batch plus due range; rewrite only changed derived hints | One actor row and one run index-state row |

The trace header duplicates compact metadata, not its large JSON payloads. First
payload access verifies run, actor, cursor and all referenced metadata against the
stored row. Cold mind/lease lookups also verify scope. No missing history is
substituted with an empty value. Idle updates can complete with zero cold reads.
Explicit full exports still load all referenced data and validate completeness.

The new tables are private. Participant subscriptions remain sender-authenticated
head/read/receipt projections. Spatial selection is not authorization. Existing
lease expiry, revocation, request-ID reuse and reconnect behavior are preserved.
Evicting a lease deletes its separate evidence row; trace eviction deletes its
payload row. Durable knowledge and causal audit retain their existing semantics
and still require a longer-term growth policy.

## Compatibility and documentation checks

Module and SDK versions remain pinned to 2.1.0. Bindings were regenerated with
CLI 2.1.0; only the three new private types and generated exports changed. The
existing development service was not upgraded or reset.

Old inline histories, cursor-only trace references and inline lease evidence remain
readable. Owner migration materializes complete captures, converts storage and
builds the schedule without advancing simulation time. Ordinary writes can also
convert affected rows. Older modules cannot interpret the new trace/lease markers;
rollback requires a compatible module or an explicit export migration.

Official [indexes](https://spacetimedb.com/docs/tables/indexes/),
[performance](https://spacetimedb.com/docs/tables/performance/),
[schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/) and
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) were consulted
before implementation. The design uses integer simulation deadlines, existing
native scheduling, bounded derived rows and local indexed history fetches. Owned
index handles and prefix/range operations were checked against the pinned 2.1.0
SDK/macro source and compiled in WASM. The current permissions page was unavailable;
private-by-default behavior was checked with the pinned macro and denied live
subscriptions, including all three new tables.

## Verification and retained evidence

Evidence is under `output/hybrid-clock/`: prospective plans, frozen artifacts and
hashes, test/build logs, metrics, module/service logs, exact exports, read receipts
and cleanup outcomes. Earlier experiment failures and volumes remain unchanged.

The selected clock is compared with the original full scan at identical supplied
times and inputs, using complete authoritative state and ordered events. Coverage
includes five world families in participant and legacy modes, reload, contested
resource failure, same-update wakeups, script activation failure, long gaps,
queued-speech initialization/expiry, birth-relative physiology, permanent death
paid scoped-law activation and author death,
and remote computation after owner death. Storage comparisons repeat the selected
clock after cold reloads and verify that idle physics reads no private payloads.

A focused speech test first failed: skipping a not-yet-ready utterance also
skipped creation of its continuation. The initialization wakeup fixed the exact
state difference; the original failed log is retained. Final tests passed:
213 kernel tests (one existing ignored benchmark), 19 module tests, 39 legacy
codec tests, two delivery tests and 36 serial bridge library tests. The native
client check and production WASM build also passed with existing warnings.

The initial 72-actor, 60-second diagnostic on isolated 2.10.0 passed all 288 reads,
private-table/reconnect/expiry checks, and exact/idempotent world-and-audit migration
from the previous module. It observed 15.67 updates/s, mean load/advance/save spans
of 12.34/11.38/4.89 ms, and mean cold reads of 6.06 mind rows, 0.02 trace payload
rows and zero leased-evidence rows per clock update. That diagnostic preceded the
speech fix and removal of redundant metadata decoding; it is not final capacity
evidence. Nested spans overlap and must not be summed with their children.

## Production measurement

The final default build ran on an isolated **2.1.0** service for 180 seconds with
72 actors, initial local density 16, 72 participant connections and twelve
72-read bursts at seconds 5, 20, …, 170 (4.8 reads/s averaged over the window).
Starting policies were the same authored fixture as the previous clock trial.
There were no model calls or observers; full exports occurred at paused boundaries.
The existing development database was untouched.

| Measurement | Previous clock | Hybrid clock |
| --- | ---: | ---: |
| Updates/s | 4.79 | 9.44 |
| Successful reads | 864/864 | 864/864 |
| Read p95 / maximum | 903 / 1,050 ms | 806 / 887 ms |
| Active-window peak service RSS | 5.43 GB | 2.80 GB |
| Retained WAL at pause | 0.823 GB | 1.194 GB |
| Retained audit events | 166,311 | 214,963 |

The hybrid run completed 1,699 updates and advanced 179,933 ms of simulation time.
Its privacy/reconnect/lease checks and exact, idempotent migration from the prior
module passed. The new tables denied participant subscriptions. These finite
runs demonstrate improved cadence and lower active service RSS for this workload;
they do **not** establish 20 Hz, thousand-player capacity or bounded long-term
storage. Retained WAL increased alongside additional updates and causal events.
A retained WAL gauge is not cumulative write volume.

Near the end of the active window, clock reducer/query time averaged approximately
50.3 ms across 1,703 boundary-sampled calls. Participant commands averaged 8.8 ms
of execution/query time and 362.4 ms of recorded queue wait across 864 calls.
Clock queue metrics were not exposed in that sample. Subscription body samples
totalled 131.4 MB, excluding transport framing. Whole-trial peak RSS was 4.60 GB,
including the additional access and migration checks after the measured window;
it is distinct from active-window RSS. At the final metric boundary jemalloc
reported 729.0 MB allocated, 760.7 MB active and 1,038.3 MB resident, with 2.95 MB
in the page pool and 0.041 MB in the row-list pool. These allocator gauges do not
account for all service RSS. Module linear WASM memory was 28.64 MB. The same
boundary retained 72 actor hints, one clock-state row, 72 mind histories, 18,432
trace rows (72 × 256), and 288 each of leases, captures and lease-evidence rows
(72 × 4). The bounded scheduler/trace/lease counts do not bound durable audit or
knowledge growth.

## Controlled actor-selection diagnostics

Four fresh 60-second diagnostics on isolated **2.10.0** compare indexed selection
with full actor scanning while keeping identical deferred storage and hint
maintenance. Each uses 72 actors/connections, initial density 16 and 72-read bursts
at seconds 5, 20, 35 and 50 (288 reads, 4.8 reads/s). The mixed fixture starts
72 authored policies; the idle fixture clears only those starting policies.
There are no models or observers and exports occur at paused boundaries.


| Fixture / selection | Updates/s | Load ms | Advance ms | Save ms | Active RSS GB | Retained WAL MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mixed-scan | 16.07 | 7.01 | 12.05 | 4.79 | 1.02 | 239.42 |
| mixed-indexed | 16.02 | 7.25 | 10.93 | 4.80 | 1.04 | 255.52 |
| idle-scan | 19.70 | 2.29 | 2.29 | 1.82 | 0.83 | 77.24 |
| idle-indexed | 19.72 | 2.36 | 0.39 | 1.85 | 0.85 | 77.13 |

All four runs passed all 288 reads. Indexed selection reduced mean advancement
cost, but these trials show little overall cadence difference: the mixed fixture
remains around 16 updates/s and the idle fixture around 19.7. The cold-storage
path is shared by both variants, so the full production improvement cannot be
attributed to selection alone. Actual elapsed update times and resulting event
trajectories differ between live runs; exact semantic equivalence is established
by the supplied-time differential tests above.

Mixed scan/indexed updates averaged 5.90 mind-row fetches, about 124 KB of mind
bodies, 0.019 historical trace fetches and zero lease-evidence fetches. Both idle
variants recorded zero cold mind, trace and lease-evidence fetches. These counters
include saving but exclude compact hot rows, metadata, keys and transport framing.
The means are diagnostic spans, not standalone capacity guarantees.

The prospective resource guards stayed enabled: 11 GiB service RSS, 12 GiB cgroup
memory, 4 GiB retained WAL, no added swap, at least 3 GiB host available memory and
8 GiB free disk. No guard aborted a run. Each isolated service was stopped after
exports; cleanup required forced termination (exit 137), **not graceful shutdown**.
Volumes and original failure evidence were retained. Only the original development
service remains running.
