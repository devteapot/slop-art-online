# Transaction-local catalog identities (47)

Controller catalog saves reuse the content identity of identical catalog bytes
within one transaction and one world. A crowd observing the same catalog no
longer hashes its complete body separately for every changed controller.
Correctness and measured performance are reported separately below.

## Cause and boundary

The previous [append/prune change](APPEND_TRACE_SCALING_46.md) narrows trace-page
persistence. The remaining sampled controller-save span reaches 0.362 ms per
sampled actor, with a 0.231 ms p95. Source inspection shows `Writes::replace`
hashes each non-null catalog before its existing body map deduplicates storage.
The live catalogs represent roughly 3.4 MB of logical catalog bytes across 200
controllers, though only a few distinct bodies are retained. This identifies
redundant work; the complete span also includes serialization and controller rows.

Consulted the official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[performance guidance](https://spacetimedb.com/docs/tables/performance/) and
[indexes](https://spacetimedb.com/docs/tables/indexes/) before designing the change.
Rust SDK 2.1.0, CLI 2.7.1 and service 2.10.0 remain fixed. Private immutable catalog
rows and their existing primary-key reconciliation remain unchanged. No schema,
public interface or binding generation changes are required.

The accumulator maps each world and exact non-null body string to its existing
content identity. Equal bytes in another world receive that world's identity;
JSON whitespace or other byte differences remain distinct. The memo and the
existing pending-body map share one immutable allocation per distinct catalog.
Repeated input strings are released after lookup. All memo state is owned by the
transaction's write accumulator and drops after commit preparation, with no
cross-transaction cache or extra persistent rows.

Reference deltas still accumulate per content identity. Reconciliation still
reads the current catalog by primary key, validates its full identity and body,
checks reference arithmetic, and inserts, updates or removes the same row.
Untouched controller catalogs retain their existing snapshot proof. Null catalogs,
legacy inline migration, scoped lazy reads and captured personal evidence keep
their existing behavior. This does not add recipients, expose another actor's
knowledge or skip validation of a stored row.

Opt-in profiles count non-null replacements, fresh identity hashes, input bytes
and hashed bytes once per complete write batch. Stored-row validation hashes are
separate. These counters establish executed reuse, not end-to-end capacity or a
change in subscription delivery. Normal builds omit the counters and logging.

## Verification

The [authority suite](../output/realtime/scale-47/validation/authority-tests.log)
passes 62 tests and the [storage integration suite](../output/realtime/scale-47/validation/storage-tests.log)
passes 39 tests. The new repeated-replacement check covers two worlds, exact byte
distinctions, null transitions, independent final-owner counts and shared
allocation. The kernel is unchanged from the previous 256-test pass; that
historical pass is not counted as a newly executed suite here.

The [normal implementation](../output/realtime/scale-47/implementation/manifest.json)
and [profiling implementation](../output/realtime/scale-47/profile-implementation/manifest.json)
freeze source and WASM hashes. Both builds succeed with the existing 20 warnings.
The unchanged iteration-41 controller module and SDK probe are recorded separately
from the authority change.

The [paired actual-authority comparison](../output/realtime/scale-47/catalog-combat-paired-authority/result.json)
publishes reference 46 and candidate 47 into two fresh databases before any
setup. Each retains one warmup and two measured worlds, each with 200 colocated
characters at 20 health, no disturbances or starting behaviors, and one authorized
paired attack installed per actor. One sequential participant identity moves its
grant between actors. The measured work is two 2,500 ms owner advances per world,
with database order alternating by step and repetition. There is no physical
scheduler, controller population, observer, human input or inference in this
comparison; all six worlds remain in one isolated service with a 6 GiB memory
limit and 3 GiB page-pool budget.

Corresponding initial and advanced complete worlds and ordered audit match
exactly. Each world records 100 deaths, 100 damage events and 14,950 death
observations. Captured evidence survives 260 rejected requests that evict the
original record and remove its last current body reference. Trace reconstruction,
body counts, denial of the four private trace/body tables and a scoped public
head pass. Publishing candidate 47 over the reference preserves all three
reference worlds. The service exits 0 without an OOM kill.

| Four measured owner advances, warmup excluded | Reference 46 | Candidate 47 |
| --- | ---: | ---: |
| Reducer plus queries, total | 1,442.76 ms | 1,422.40 ms |
| WASM execution, total | 1,368.08 ms | 1,347.18 ms |
| CLI wall time, total | 1,524.59 ms | 1,492.85 ms |

The [measured reducer-plus-query total](../output/realtime/scale-47/catalog-combat-paired-authority/measurement-summary.json)
is 1.4% lower. This small two-repetition comparison preserves identical physical
work, but does not establish a stable general speedup or live cadence. Service
memory covers all six retained worlds; no per-world memory claim is derived.

## Live workload

The live workload starts 200 colocated characters at 100 health, with 200 reference
controllers and one SDK component observer with open inspection. It requests a
ten-second active interval at 60 Hz, with no human input, model inference or
rendered Bevy client. World and controller services each have a 6 GiB memory
limit and 3 GiB page-pool budget. Ordinary permanent deaths reduce the population
to 100; this cannot establish sustained population.

The [candidate profile](../output/realtime/scale-47/combat-catalog-profile/clock-profile-summary.json)
records 406 non-null replacements across the active deadline transactions,
with three fresh identities: 7,519,447 input bytes require 50,289 hashed bytes.
A single transaction replaces as many as 197 controller catalogs while hashing
one distinct body. The complete batches include zero-change records. Stored-row
validation hashes are separate and still execute as before.

| Instrumented deadline phase | Reference 46 | Candidate 47 |
| --- | ---: | ---: |
| Sampled controller-save mean | 0.0340 ms | 0.0196 ms |
| Sampled controller-save p95 | 0.2316 ms | 0.0330 ms |
| Sampled controller-save maximum | 0.3621 ms | 0.2636 ms |
| Participant save total / maximum | 211.91 / 60.12 ms | 171.51 / 35.35 ms |
| Complete save total / maximum | 354.44 / 66.77 ms | 318.55 / 40.90 ms |
| Physical execution total / maximum | 724.25 / 97.47 ms | 716.35 / 103.84 ms |

The [reference profile](../output/realtime/scale-46/combat-append-profile/clock-profile-summary.json)
and candidate perform 337 and 331 local physical saves, respectively. Their
asynchronous requests, death timing and sampled work differ; spans are nested,
and maxima need not describe the same transaction. Timers perturb both runs.
The fresh-hash counts prove executed reuse; the phase comparisons identify a
narrower save benefit, without proving overall capacity. Actor execution remains
above 100 ms at its largest burst. The separate audit-append phase reaches
42.37 ms; it includes event serialization, durable inserts and retention tracking. All declared paused audit, trace, catalog,
component-render and combat-feed/reconnect checks pass; both services exit 0.

The [normal candidate run](../output/realtime/scale-47/combat-catalog-release/stack-analysis.json)
completes the same declared component workload as the retained
[reference 46 release](../output/realtime/scale-46/combat-append-release-retry/stack-analysis.json).

| Normal release diagnostic | Reference 46 | Candidate 47 |
| --- | ---: | ---: |
| Clock wakes / missed slots | 322 / 278 | 326 / 274 |
| Missed-slot fraction | 46.3% | 45.7% |
| Deadline execution plus queries p95 bucket | 50–100 ms | 50–100 ms |
| Deadline execution plus queries p99 bucket | 250–500 ms | 100–250 ms |
| Scheduled queue p95 / p99 buckets | 10–50 / 50–100 ms | 5–10 / 50–100 ms |
| Sampled backend CPU | 17.36 s | 16.88 s |
| World outgoing wire bytes | 17,698,828 | 18,441,970 |

All declared paused checks pass. The normal run ends at 10,001 simulated
milliseconds with 100 survivors and 65,470 verified audit events. Both services
exit 0 without OOM. The observer misses no physical update IDs; its delivery
interval p99 is 316 ms and maximum is 524 ms. This is SDK delivery, not FPS.
The clock still fails the active-combat requirement. Counters include
setup/cleanup, and nearest one-second samples bound metrics. Different
asynchronous requests and outcomes produce 10,000 action-actor loads here versus
10,600 before. The small cadence difference does not establish a stable general
speedup, and wire volume increases.

Normal peak RSS is 1,311,420,416 bytes for the world, 770,719,744 for the controller
and 508,850,176 for the relay, including enrollment, with no sampled swap.
The world worker WASM gauge reaches 238,616,576 bytes. World allocator
allocated/resident peaks are 566,812,672 / 1,099,010,048 bytes and its page-pool
peak is 10,420,752 bytes. Controller allocator allocated/resident peaks are
281,951,312 / 687,411,200 bytes. Gauges refresh independently and are not added to
RSS. These isolated services do not establish a long-duration memory plateau.

Sampled retained WAL endpoints are 104,066,632 → 148,612,257 bytes for the world
and 96,509,598 → 368,113,981 for the controller. These are retained sizes, not
cumulative writes. Table gauges lag and are not exact retention counts. The
paused diagnostic reconstructs 50,609 experiences across 1,761 pages and 2,330
bodies, with 20,172,508 logical body bytes occupying 801,740 stored bytes.
Five catalogs occupy 94,811 bytes for 200 references; there are no unreachable
current catalogs/bodies, legacy indexes or payload rows.

## Resource discipline

Before measured workloads, completed compiler-library cache cleanup raises free
disk from 11,677,061,120 to 12,403,843,072 bytes. Only unmapped single-link native
compiler libraries are removed; source, executables, frozen evidence and database
volumes remain. No compiler or test process is active during cleanup.

After the profile finishes, [block sharing](../output/realtime/scale-47/validation/completed-block-dedupe-result.json)
processes 441 completed snapshot, audit and metrics files, registering 45
previously processed files without repeating their deduplication. Full SHA-256,
size, modification time, permissions and ownership remain unchanged. Free disk
rises from 9,521,483,776 to 10,548,994,048 bytes. No retained file or volume is
deleted. The original 8 GiB disk and 3 GiB free-memory guards remain unchanged;
no cleanup, block sharing or compilation overlaps measured authority work.

The final [correctness summary](../output/realtime/scale-47/validation/correctness-summary.json)
and [documentation/source checks](../output/realtime/scale-47/validation/documentation-check.json)
verify four frozen source/binary manifests, both paired module hashes, the
workspace's normal source/build match and all five service shutdowns. Every
experiment service exits 0 without OOM; existing development services remain
untouched. Earlier excluded runs and nonzero shutdowns remain in their original
iteration-46 records.

The 216-character/30-minute and 2,000-character/8-hour gates, human and full model
workloads, movement/combat mechanics, client pacing and autonomous outcomes remain
open. These reference-controller diagnostics do not satisfy the product target.
