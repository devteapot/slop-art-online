# Paged personal traces and shared stored evidence (37)

2026-09-08. Continues [shared witness payloads](SHARED_WITNESS_SCALING_36.md)
toward the [world](WORLD_VISION.md) and [simulation](SIMULATION_VISION.md)
visions. The [performance contract](PERFORMANCE_CONTRACT.md) remains unaccepted.

## Storage change

Iteration 36 reuses identical witness payload encoding in memory but still stores
one full payload per recipient and rewrites each changed actor's complete trace
index. The new private format separates ordered personal metadata from immutable
JSON bodies. Each actor has a small head and pages of at most 32 cursor values.
Only changed pages are written. In an ordinary retained trace of cursors 1–256,
appending 257 and pruning 1 changes the two edge pages and preserves seven pages.
Arbitrary retained ordering and cursor gaps remain supported: a bucket transition
starts a new page, and decoding preserves the head's explicit order.

Bodies share storage only when their exact encoded JSON and run agree. Personal
cursor, source event, tick, location, kind and parents remain per-recipient page
entries. A run-scoped SHA-256 digest identifies content; readers validate identity,
run, digest and JSON. Internal auto-increment body IDs have no gameplay meaning
and need not be contiguous. Hash matches also require exact content equality on
write. This does not grant a character access to another's perception or knowledge.

Reference counts use a separate private table, so retaining an existing body does
not update its content row or invalidate other readers of that immutable body.
The transaction accumulates reference changes across affected participants and
deletes a body after its last current trace reference disappears. Captured evidence
leases retain their existing self-contained data and lifetime. Lease writes finish
before body deletion, preserving lazy source reads even when a trace evicts them.
Durable audit and permanent identity history retain their existing policies.

The participant's storage marker selects the format. Existing inline and earlier
split formats remain readable; an actor upgrades atomically when its trace changes.
Publishing the module does not eagerly rewrite existing Worlds. Cold kernel loads
read actor-scoped metadata pages and defer bodies until needed. Changed traces
still walk their retained entries and compare pages; this is not a fully constant
cost append implementation. Explicit full exports reconstruct the exact World.

Controller views reconstruct the same existing experience row shape after grant,
epoch and cursor checks. Acknowledged cursor buckets are excluded before page
reads, then individual entries are filtered by cursor. Body reads are cached
within each view invocation. Combat views can request the retained history from
cursor zero. New storage tables remain private; content sharing does not expose
body IDs through a new public API.

## Documentation and version checks

Consulted official [documentation](https://spacetimedb.com/docs/),
[table performance](https://spacetimedb.com/docs/tables/performance/),
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and
[views](https://spacetimedb.com/docs/functions/views/) before designing the change.
The access pattern follows typed private tables, actor indexes and primary-key
reads with narrow procedural-view dependencies. Schema/API availability was
checked against pinned Rust SDK 2.1.0. Control CLI 2.7.1 and standalone service
2.10.0 (`b22dfaac6d46`) remain fixed. Bindings for four new private tables and their
nested entry type were regenerated with CLI 2.1.0, including the module exports.
Existing public experience types are preserved.

| Data | Read/write scope | Retention and recipients |
|---|---|---|
| Trace head | Actor primary key; page order updated when changed | One per participant; private |
| Trace pages | `(run, actor)` index for full actor reads; primary keys for unread pages | Current trace entries only; private |
| Immutable body | Digest lookup on new content; ID reads for needed entries | One per identical JSON/run while referenced; private |
| Body retention | ID update after aggregate transaction deltas | Removed with last current reference; private |
| Controller experience view | Authenticated actor's unread pages and referenced bodies | Existing authorized subscribers and wire shape |
| Audit and captured leases | Existing authority paths | Existing durable evidence and recovery contracts |

Common witness content reduces stored payload duplication, not the number of
personal evidence records or the bytes that each authorized subscriber needs.
Distinct bodies, page metadata, leases and audit still consume resources.
Short retained-row checks do not establish bounded long-term service memory.

## Correctness and migration

All 46 authority tests pass. An initial fixture edit failed compilation; the
syntax was corrected before these checks. The original failure and subsequent
build/test logs are retained under `output/realtime/scale-37/validation`.
New checks cover page edge updates, arbitrary order,
gaps, missing/repeated/foreign pages, malformed body identity and JSON, reference
underflow/overflow, last-reference deletion, eager World reconstruction and
acknowledged-page filtering at bucket boundaries and maximum cursor values.
Existing cold-load, command, rendering and full-kernel parity fixtures now exercise
the paged format. All 37 bridge tests pass with regenerated bindings. Simulation
code is unchanged from iteration 36's 246 passing tests and one ignored test.

`output/realtime/scale-37/paged-paired-authority` compares two actual authority
databases with 200 actors, no starting habits and 64 authored damage interventions
at 2,500 ms. Both start with the old binary; one receives the new module without
data deletion. Publication preserves the exact full World. Two owner-driven
2,500 ms steps produce identical Worlds, including 64 deaths and 10,720 distinct
death-witness perceptions. This uses the shared kernel and actual persistence.

Afterward both versions capture one unique rejected-command evidence record in a
lease. Another 260 rejected requests evict it from the current trace. The new
storage deletes that body's last current reference, while the lease still returns
the exact captured record. Full Worlds and all 51,984 audit events match across
the comparison. A separate participant identity can read its granted public head
but cannot query any of the four private tables. This privacy probe runs after
canonical comparison and is recorded as a separate mutation. The service exits 0.

| Actual-authority reducer | Old format | New format |
|---|---:|---:|
| First step execution + query | 462.925 ms | 537.059 ms |
| First step WASM | 410.313 ms | 459.223 ms |
| Second step execution + query | 298.625 ms | 260.716 ms |
| Second step WASM | 297.185 ms | 259.421 ms |

The first new step includes migration of legacy traces and is slower. The second
is about 12.7% lower in execution plus query time in this single comparison.
Invocation order alternates. These two coarse owner steps do not establish steady
60 Hz scheduling or a statistical speedup. No relay, model, human or observer is
connected. Both databases share one service; its memory is not a single World's
footprint. The paired binary precedes the final selective view-read optimization;
that optimization changes view reads, not the compared persistence operations.

## Live workload and preliminary regression

The release workload is 200 same-cell paired combatants, 200 reference controllers,
one component observer with inspector, no human or inference, and a ten-second
60 Hz loopback interval. The host remains Ryzen AI MAX+ 395, 16 physical/32 logical
CPUs, 65,090,016 kB RAM, unreserved CPU and shared relay/load generation. Each
service has a 6 GiB limit and 3 GiB pools. Controller/probe binaries are fixed.

The preliminary `combat-paged-traces` artifact passes paused correctness checks
but overlaps a corrective build during measurement. Its explicit caveat excludes
performance comparison; its original evidence and volume remain intact.

The subsequent `combat-paged-traces-final` release has 200 heads, 1,761 pages,
2,426 bodies and 50,642 personal entries. Their logical payloads total 20,787,580 B;
the distinct stored bodies total 836,304 B. There are no extra body references or
legacy experience/index rows. This comparison counts JSON payload bytes, excluding
metadata, table/index overhead, retained WAL and allocator memory.

That release passes audit, trace retention, catalogs, rendering, combat feed,
reconnect and access checks, with both services exiting 0. However, it misses
53.8% of clock slots and has a 17.178 ms deadline execution/query mean, compared
with 46.5% and 13.000 ms in iteration 36. Its experience view spends 1,253.276 ms
in WASM across 4,310 calls, versus 526.234 ms across 4,609 calls previously.
Reading all metadata pages on every acknowledgement causes an avoidable regression.
The final implementation therefore skips fully acknowledged cursor buckets before
reading pages. The following live measurements evaluate that correction.

## Final selective-page release

`output/realtime/scale-37/combat-selective-pages` passes every declared paused
check, including exact trace reconstruction and reference retention. It retains
200 heads, 1,758 pages, 2,078 bodies and 50,498 personal entries. Logical body
content totals 16,350,801 B; stored bodies total 699,822 B (95.7% fewer payload
bytes), with no legacy rows or unreachable current bodies. Both services exit 0.
The measurement has no overlapping build.

| Release measurement | Iteration 36 | Paged traces, all pages | Paged traces, unread pages |
|---|---:|---:|---:|
| Physical elapsed | 10,002 ms | 10,000 ms | 10,002 ms |
| Probe elapsed including cleanup | 14,907 ms | 15,574 ms | 15,535 ms |
| Physical updates / survivors | 322 / 100 | 278 / 100 | 354 / 100 |
| Attack attempts / damage events | 1,028 / 825 | 1,040 / 828 | 895 / 688 |
| Deadline wakes / missed slots | 321 / 279 | 277 / 323 | 353 / 247 |
| Deadline execution + query mean | 13.000 ms | 17.178 ms | 11.520 ms |
| Deadline p95 / p99 buckets | (50, 100] / (100, 250] ms | (50, 100] / (250, 500] ms | (25, 50] / (100, 250] ms |
| Scheduled queue p95 bucket | (5, 10] ms | (10, 50] ms | (1, 5] ms |
| Action admission execution + query mean | 0.891 ms | 1.023 ms | 0.924 ms |
| Observer physical gap p95 / maximum | 109 / 423 ms | 143 / 606 ms | 96 / 528 ms |
| Experience view calls / WASM | 4,609 / 526.234 ms | 4,310 / 1,253.276 ms | 3,761 / 735.031 ms |
| Backend CPU | 17.10 s | 16.59 s | 14.23 s |
| World outgoing WebSocket bytes | 19,203,245 | 17,498,693 | 14,713,502 |
| World peak RSS | 1,342,320,640 B | 1,252,679,680 B | 1,203,535,872 B |
| World WASM peak | 158,662,656 B | 158,662,656 B | 158,662,656 B |
| World jemalloc allocated peak | 581,522,968 B | 566,015,960 B | 537,125,432 B |
| World jemalloc resident peak | 1,109,688,320 B | 1,122,201,600 B | 1,031,081,984 B |

These asynchronous runs contain different action/death timing and amounts of work.
The final release has fewer attacks and damage events. It misses 41.2% of clock
slots, and the experience-view WASM cost per call remains above iteration 36.
The table supports continued investigation, not a controlled end-to-end speedup
claim. Observer gaps are authoritative update intervals, not rendered FPS or
per-actor cadence. Service gauges are sampled; retained WAL is not cumulative
writes. Each live world has its own isolated service/database. No swap is observed.

## Profile and remaining work

`output/realtime/scale-37/combat-selective-pages-profile` passes all declared
checks and both services exit 0. It reaches 10,001 physical milliseconds with
100 survivors, 971 attack attempts and 769 damage events, recording 312 wakes
and 288 missed slots (48%). The trace verifier matches 50,608 entries to 1,763
pages and 2,253 bodies without extra rows. Instrumentation changes scheduling;
this is diagnostic evidence, not the release acceptance measurement.

| Instrumented phase | Iteration 36 | Paged traces with selective reads |
|---|---:|---:|
| Death-witness total / count | 136.24 ms / 100 | 93.81 ms / 100 |
| Actor kernel total / count | 607.99 ms / 280 | 544.93 ms / 311 |
| Action execution total / count | 822.10 ms / 277 | 744.98 ms / 308 |
| Action save total / count | 790.08 ms / 277 | 606.04 ms / 308 |
| First-use evidence sample mean | 0.063261 ms | 0.065973 ms |
| Already-loaded evidence sample mean | 0.001988 ms | 0.001849 ms |
| Trace diff sample mean | 0.008773 ms | 0.063786 ms |
| Payload resolution/row sample mean | 0.055563 ms | 0.078978 ms |
| Index/page save sample mean | 0.105339 ms | 0.057567 ms |

New trace-diff and payload phases perform different work: reading/validating
pages and resolving immutable identities replace the old flat-index/payload
operations. Lower page-write timing alone does not prove lower total trace-save
cost. The new profile has 2,067 eligible first-use evidence calls (314 sampled)
and 17,823 already-loaded calls (287 sampled), compared with 2,615 and 17,943
previously. It selects 148 of 2,162 changed participant saves; 138 have changed
traces. The previous profile selected 185 of 2,776, with 172 changed traces.
These systematic sample means are not unbiased population estimates. Work and
sampling counts differ. Parent/child spans overlap and must not be summed.

Aggregate body-reference finalization takes 2.883 ms across 1,888 profiled calls,
including empty calls. The largest action domain still loads all 200 actors,
with 199 alive/due inputs, and emits 12,593 events at 4,106 ms. Actor execution
alone takes 100.50 ms and complete action execution 109.34 ms. The maximum action
save span is 85.62 ms. Dense evidence bursts still exceed the 16.67 ms budget by
large margins. Cold trace metadata reads, per-recipient parent/evidence work,
trace comparisons and subscription rendering remain relevant costs. Shared body
storage addresses duplication; it does not make those operations disappear.

The normal module was rebuilt after profiling and matches the frozen selective
release WASM SHA-256 exactly. Documentation links and `git diff --check` pass.
Inactive reproducible build caches were reclaimed after checking running
executables and hard links; all experiment outputs and volumes were retained.
No development database was modified.

The 216-character/30-minute gate, 2,000-character/eight-hour target, rendered frame
rate and full model-workload acceptance remain open. The wider world vision,
including autonomous invention/ascension and sustainable long-lived populations,
is not established by this storage pass. Further work must reduce burst execution
and persistence cost while preserving exact physical outcomes, distinct personal
provenance, private access, durable audit and lease/reconnect recovery.
