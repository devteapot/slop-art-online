# Deferred controller catalog reads (34)

2026-09-08. Continues the [world](WORLD_VISION.md) and
[simulation](SIMULATION_VISION.md) work after
[compact catalog storage](CONTROLLER_CATALOG_SCALING_33.md). The
[performance contract](PERFORMANCE_CONTRACT.md) remains unaccepted.

## Dependency change

Iteration 33's profile reads 28.71 MB of retained catalog bodies in 1,307 command
admissions and 4.46 MB in 322 inspector header evaluations. Neither operation
normally needs this historical controller field. The assembler nevertheless
loads and hashes it eagerly, and saving changed action metadata serializes and
hashes an unchanged catalog again. The release's command mean rises from
1.022 to 1.464 ms despite reduced physical-update catalog traffic.

The cold assembler now retains a transaction-local deferred catalog payload.
It validates controller run/key and reference syntax before constructing the
loader; an actual body read validates run, key, positive reference count and
content hash before exposing valid JSON. Referenced bodies are non-null by the
existing writer's format; a null referenced body fails on use. Legacy inline
JSON keeps its original decoding and optional-null semantics. Full eager exports
continue to resolve every referenced body. Cold serialization also forces reads
and returns load errors, so an incomplete world cannot serialize successfully.

Missing or corrupt unused cold bodies are not proactively read by an unrelated
command or inspector. This is the same dependency principle used by existing
cold evidence: when the catalog is compared, serialized or otherwise consumed,
validation runs and failures remain retained in that transaction. No load failure
becomes an empty catalog or successful physical effect.

Saving a changed controller can reuse its existing catalog reference only when
its payload is the exact immutable snapshot retained from that actor's load in
the same transaction. The current row must match run, actor, key and the current
reference format. Equal bytes in a separately constructed payload are not this
proof; that case takes the normal encode/intern path. Legacy inline rows still
migrate through normal serialization. Changed catalogs retain the existing
atomic reference accounting and last-reference deletion. No global cache,
new table, reducer interface or generated binding change is introduced.

This narrows both command work and inspector read dependencies. Physics still
compares the retained catalog when refreshing observed lifecycle facts. Personal
perception records, causal audit events, knowledge access, action admission and
actual physical outcomes retain their existing semantics.

## Documentation and validation

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance guidance](https://spacetimedb.com/docs/tables/performance/),
[views and read sets](https://spacetimedb.com/docs/functions/views/) and the
[pinned Rust SDK](https://docs.rs/spacetimedb/2.1.0/spacetimedb/). Procedural views
track accessed rows, so avoiding an irrelevant indexed fetch also avoids adding
that row to the view's dependencies. The implementation uses existing pinned
2.1.0 table/view APIs and transaction-local loaders; no current-docs-only query
builder or runtime cache API is assumed available.

Forty authority tests, 37 bridge tests and three focused immutable-payload tests
pass. New checks prove deferred first-use validation, one shared fetch, retained
missing/corrupt/null errors, scoped reference reuse, immutable detachment and
legacy fallback. Commands and inspection are checked with loaders that would
fail if called, while complete export must still fail without those bodies.
Existing full state/event parity checks run through repeated cold physics
reloads and the new deferred catalog path. The only simulation change exposes
the existing immutable snapshot identity predicate; its implementation is unchanged.

The profile logger records actual catalog body fetches separately from assembly.
An explicit deferred-assembly marker allows the summary to distinguish zero
fetches from missing instrumentation. The updated parser accepts the previous
profile format and does not claim zero deferred reads for older logs.

## Actual trials

The completed release is `output/realtime/scale-34/combat-deferred-catalogs`.
It uses the same 200 paired combatants in one cell, 200 reference controllers,
one component observer/open inspector, ten-second 60 Hz loopback interval,
no humans and no inference as iteration 33. Audit and catalog verification run
after pause. The host remains a Ryzen AI MAX+ 395, 16 physical/32 logical CPUs,
65,090,016 kB RAM; each database has a 6 GiB limit and 3 GiB pools. CPU is
unreserved, and relay/load generation shares the host. Probe/controller binaries
remain fixed. This is a short diagnostic, not a sustained population gate.

| Measurement | Iteration 33 release | Deferred catalogs |
|---|---:|---:|
| Physical elapsed | 10,081 ms | 10,087 ms |
| Probe elapsed including cleanup | 14,283 ms | 14,213 ms |
| Physical updates | 291 | 370 |
| Deadline wakes / missed slots | 288 / 316 | 367 / 238 |
| Missed-slot fraction | 52.3% | 39.3% |
| Deadline reducer + query mean / count | 12.693 ms / 284 | 9.027 ms / 367 |
| Deadline p95 / p99 buckets | 50–100 / 100–250 ms | 10–25 / 100–250 ms |
| Command reducer + query mean / count | 1.464 ms / 1,386 | 0.943 ms / 1,416 |
| Header processing / calls | 554.23 ms / 295 | 718.92 ms / 378 |
| World / controller / relay CPU | 7.54 / 3.64 / 4.65 s | 6.34 / 3.14 / 4.50 s |
| Total measured backend CPU | 15.83 s | 13.98 s |
| World outgoing wire bytes | 16.94 MB | 14.16 MB |
| Attacks: attempted / completed / failed | 933 / 718 / 215 | 918 / 695 / 223 |
| Site perceptions | 822 | 477 |
| Final alive / permanent deaths | 100 / 100 | 100 / 100 |

This run improves command mean and deadline cadence, but still fails 60 Hz and
contains a different asynchronous execution. Deaths occur in two waves (23 at
3,513 ms and 77 at 3,987 ms), versus five previously. There are fewer completed
attacks and site updates. These differences prevent attributing the entire
cadence/CPU change to deferred reads or claiming sustained capacity. Header
total cost rises with more evaluations; removing catalog reads does not establish
an overall inspector speedup.

All 200 feed checks pass for exact source evidence, reconnect, scope and
revocation. Component reconstruction, inspector transitions, reconnect and
grants pass. Owner diagnostics validate all 200 references, exact export values,
scoped content hashes, counts and no unreachable catalogs. Three bodies total
59,105 bytes, with 18,000 hot reference bytes and 3,497,351 equivalent repeated
catalog bytes. These are payload sizes, not total table allocation.

The audit retains 63,940 contiguous events, all 39,800 initial sightings and
14,950 death perceptions. All 223 failed attacks remain target-dead/out-of-range
failures, and 23 rejected commands retain their original outcomes. Observer
physical-gap p95/p99/max is 87/266/474 ms; delivery-gap p95/p99/max is
77/332/630 ms. These combined SDK delivery intervals do not measure Bevy frames,
per-character combat cadence or human input-to-photon latency.

Scheduled queue p95 is 0.1–0.5 ms and p99 is 50–100 ms. Three world-maintenance
samples average 88.98 ms including queries, still incompatible with timely
combat. World/controller/relay RSS peaks are 1.273/0.734/0.503 GB, with no
sampled swap. World WASM peaks at 158.66 MB; allocator allocated/resident peaks
are 560.14/1,111.37 MB, page/BSATN pools at 18.94/0.0415 MB. World and controller
WAL/row gauges remain unchanged across the selected endpoints (123.78 MB /
85,834 rows and 107.95 MB / 81,576 rows). Their unknown refresh timing does not
establish zero growth; retained WAL is not cumulative writes.

## Profile

`output/realtime/scale-34/combat-deferred-catalogs-profile` completes with
retained module logs, summaries and passing feed, reconstruction and catalog
checks. Actual deferred-body fetch counts are:

| Consumer | Assemblies | Catalog body reads | Body bytes |
|---|---:|---:|---:|
| Command admission | 1,646 | **0** | **0** |
| Inspector header | 306 | **0** | **0** |
| Local physical deadline | 293 | 43 | 892,947 |
| Full world maintenance | 3 | 3 | 55,791 |

These counters measure cold payload fetches when used. Reference-accounting
lookups on changed catalog saves remain separate; commands that retain an
unchanged reference generate no such accounting change. Physics loads the
catalogs needed by living recipients and skips untouched dead-character history.
Eager owner exports still validate all current references after pause.

| Profile phase mean | Iteration 33 | Deferred catalogs |
|---|---:|---:|
| Command row read | 0.0314 ms | 0.0301 ms |
| Command assembly | 0.2693 ms | 0.0274 ms |
| Command save | 0.3130 ms | 0.1016 ms |
| Nonempty local-domain read | 2.805 ms | 2.570 ms |
| Nonempty local-domain assembly | 1.839 ms | 1.376 ms |

The command comparison has 1,307 versus 1,646 samples. Nonempty local domains
have 19 versus 43 samples, each loading 200 bodies. Deferred work moves from
assembly into physical execution when consumed, so a lower assembly timer alone
would not prove less total work. The zero command/inspection fetch counters and
retained-reference checks directly establish the omitted dependency.

The largest physical kernel still takes 104.79 ms for 199 due actors and 7,963
events at 3,994 ms. Actor work is 92.82 ms and lifecycle observation 11.81 ms.
Another takes 90.09 ms for 147 due actors and 6,507 events. Local saves total
698.82 ms and peak at 96.50 ms. Full maintenance advances total 43.05 ms and
peak at 18.99 ms; saves total 26.60 ms and peak at 11.68 ms. Actor/evidence work,
persistence bursts and maintenance still exceed the budget.

The instrumented run performs different work: five death waves, 756 active
site-perception samples and 66,198 audit events. It misses 50.8% of deadline
slots and consumes 18.48 seconds of measured backend CPU. Its slower aggregate
outcome is retained and does not replace the uninstrumented release result.
All 200 references remain valid with six retained bodies totaling 118,570 bytes;
missing outcomes, audit gaps and unreachable catalogs are not accepted.

Both release and profile database pairs stop with code 0 and no OOM. No failed
trial or forced service stop occurs in this pass. Normal and profile WASM builds
pass, and rebuilding the normal module after profiling reproduces the frozen
release hash. Existing development services and older experiment artifacts are
preserved. No schema, bindings, client asset or gameplay-rule changes are made.

The next work is measuring and removing repeated participant evidence processing
inside actor execution and persistence, then separating remaining slow-system
work from combat deadlines. The immediate 216-character/30-minute and full
2,000-character/eight-hour gates, sustainable population, fresh inference,
projectiles/dodges and complete client frame/input verification remain open.
