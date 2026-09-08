# Controller catalog storage scaling (33)

2026-09-08. Continues the [world](WORLD_VISION.md) and
[simulation](SIMULATION_VISION.md) work after
[encoded evidence](ENCODED_EVIDENCE_SCALING_32.md). The
[performance contract](PERFORMANCE_CONTRACT.md) remains unaccepted.

## Storage dependency and implementation

Iteration 32 shares controller catalog decoding only after every selected
controller row has crossed the database/WASM boundary. Its final 200-character
export contains 3,292,147 bytes of last-observed catalog JSON but only seven
distinct encodings, totaling 131,536 bytes. These are final-state payload sizes,
not measured wire traffic or a count of reads during the active interval.

The controller row now retains a compact versioned reference in its existing
`last_lifecycle` string. A new private `sim_native_controller_catalog` table
stores the exact JSON body, run, content identity and reference count. Identity
uses length-prefixed run, kind and body bytes plus the existing shared-scope
marker in the SHA-256 storage codec. Equal bodies in different runs have
different identities. Whitespace/key-order differences retain different bodies;
semantic comparison in the kernel continues to suppress equivalent observations.

The assembler validates each controller's run and actor key before resolving its
catalog. It checks the referenced row's key, run, positive reference count and
content hash. Selected controllers with the same reference share one read and
one decoded immutable payload within the transaction. Missing/corrupt references
fail; the cache never survives the transaction. Scoped participant reads fetch
only their referenced catalog by primary key. Full exports may read the run's
catalog set, as explicit diagnostics already read all relevant components.

Saves accumulate reference changes across the selected participants and update
each affected catalog once in the same reducer transaction as the controller
rows. The last released reference deletes the catalog. This bounds current
catalog rows by retained non-null controller references; it does not bound
catalog body size, character population, audit history or service memory. Dead
characters retain their last observed catalog, so their references remain valid.
The representation does not introduce a historical catalog archive.

Existing inline JSON remains readable and upgrades per changed controller on
save. JSON `null` retains the existing decoder's optional-value semantics.
Exports retain ordinary JSON values and require no reference knowledge. The
new schema is additive; old binaries cannot interpret new references, so a
binary rollback requires an appropriate data migration. No existing development
database is updated or reset in this iteration.

Personal perceptions, experience records, bootstrap data, action failures,
causal audit evidence, authentication and grant checks retain their existing
boundaries. Shared private storage does not make another character's knowledge
public. No gameplay rules, observation recipients, generated model decisions or
local-physics selection rules change.

## Documentation and version checks

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table design](https://spacetimedb.com/docs/tables/),
[performance guidance](https://spacetimedb.com/docs/tables/performance/),
[indexes](https://spacetimedb.com/docs/tables/indexes/) and
[pinned Rust SDK 2.1.0](https://docs.rs/spacetimedb/2.1.0/spacetimedb/).
Their access-pattern/table decomposition guidance supports keeping repeated
large immutable payloads outside mutable controller rows. The attempted separate
permissions-guide URL was unavailable; the official table guide explicitly
confirms that `pub` Rust visibility does not make a database table public.

Authority/SDK remain pinned to 2.1.0. CLI 2.1.0 regenerates bindings from the
compiled WASM into a temporary directory; comparison shows only the new private
row type and its generated module exports differ. Those generated files replace
the corresponding workspace files without hand edits. Actual isolated trials
use standalone 2.10.0 image `b22dfaac6d46` and control CLI 2.7.1.

## Validation and trial evidence

The final authority and bridge library suites pass 37 tests each. New checks
cover run/content identity, missing and corrupt bodies, reference underflow,
last-owner deletion, distinct encodings, complete exports, one read per distinct
selected reference, and full state/event/physical-outcome parity after repeated
cold storage reloads across scenario families. An initial test incorrectly
compares an in-memory `Some(null)` with the pre-existing JSON decoder's `None`;
the retained failed log identifies this. The corrected differential check uses
the old storage decoder as its reference and keeps exact serialized world and
audit comparisons. Normal and profile WASM builds pass. There are no simulation
source changes requiring a repeat of iteration 32's kernel suite.

`output/realtime/scale-33/catalog-upgrade-valid` publishes the old frozen module
to two fresh databases and creates identical four-character worlds. Updating
one database to the new module with `--delete-data=never` leaves its complete
snapshot unchanged. Eight subsequent steps match the old binary's complete
world and all 97 audit event strings exactly. All four controller rows migrate,
with one retained catalog and the exact reference count. This verifies the
additive schema and inline compatibility on the actual service, without updating
an existing development database.

The preceding `catalog-upgrade` setup attempt uses an invalid run ID without the
required `sim-` prefix and fails before world creation. It remains preserved.
Its service stops with exit code 1, not OOM; retained shutdown logs show a
cancelled-task panic while an initial snapshot is finishing. It is not described
as a successful or graceful stop. The corrected upgrade service and both pairs
of completed combat services stop with code 0 and no OOM. The failed setup runs
during profile enrollment; the successful upgrade starts after its timed window.
Neither overlaps the measured profile interval.

## Completed release comparison

`output/realtime/scale-33/combat-compact-catalogs` uses the same 200 paired
combatants in one cell, 200 reference controllers, one component observer/open
inspector, ten-second 60 Hz loopback window, no human input and no inference as
iteration 32. Audit and storage diagnostics run after pause. The Ryzen AI MAX+
395 host has 16 physical/32 logical CPUs and 65,090,016 kB RAM. Each isolated
service has a 6 GiB limit and 3 GiB pools; CPU is unreserved and the relay/load
generator shares the host. Probe and controller module binaries are held fixed.

| Measurement | Iteration 32 release | Compact catalogs |
|---|---:|---:|
| Physical elapsed | 10,001 ms | 10,081 ms |
| Probe elapsed including cleanup | 14,651 ms | 14,283 ms |
| Physical updates | 294 | 291 |
| Deadline wakes / missed slots | 294 / 306 | 288 / 316 |
| Missed-slot fraction | 51.0% | 52.3% |
| Deadline reducer + query mean / count | 14.910 ms / 293 | 12.693 ms / 284 |
| Deadline p95 / p99 buckets | 100–250 / 100–250 ms | 50–100 / 100–250 ms |
| Command reducer + query mean / count | 1.022 ms / 1,468 | 1.464 ms / 1,386 |
| Header processing / calls | 573.40 ms / 302 | 554.23 ms / 295 |
| World / controller / relay CPU | 8.23 / 4.16 / 5.59 s | 7.54 / 3.64 / 4.65 s |
| Total measured backend CPU | 17.98 s | 15.83 s |
| World outgoing wire bytes | 19.67 MB | 16.94 MB |
| Attacks: attempted / completed / failed | 1,016 / 806 / 210 | 933 / 718 / 215 |
| Final alive / permanent deaths | 100 / 100 | 100 / 100 |

This is **not an established end-to-end performance improvement**. Missed slots
worsen and command latency rises despite lower total CPU, a lower deadline mean
and a better p95 bucket. The asynchronous runs perform different work. Deaths
now arrive in five waves: 14 at 3,467 ms, 57 at 3,978 ms, 25 at 4,567 ms, one at
4,995 ms and three at 5,181 ms. The audit retains 64,671 contiguous events, all
14,950 death perceptions and 39,800 initial sightings. All 215 failed attacks
remain failures; 21 rejected commands report a dead character or stopped run.

All 200 combat-feed checks pass, including exact source evidence, reconnect,
scoped access and revocation. Component reconstruction, inspector transitions,
reconnect and grant checks pass. A separate anonymous SQL request for the new
table is denied. Paused owner diagnostics validate every controller reference,
exact export reconstruction, scoped hashes, reference counts and absence of
unreachable catalogs. Two hundred references occupy 18,000 bytes in controller
fields and retain six bodies totaling 101,885 bytes, instead of the equivalent
3,349,343 bytes repeated per controller. These are storage payload sizes, not a
claim about total table allocation or traffic.

Observer physical-gap p95/p99/max is 180/346/589 ms; delivery-gap p95/p99/max is
158/414/641 ms. These remain combined SDK delivery observations, not Bevy FPS or
human input-to-photon latency. Scheduled queue p95 is 10–50 ms and p99 is
100–500 ms. Three world-maintenance samples average 113.49 ms including queries.

World/controller/relay RSS peaks are 1.296/0.749/0.502 GB, with no sampled swap.
World WASM peaks at 158.66 MB; allocator allocated/resident peaks are
601.41/1,134.79 MB, with page/BSATN pools at 15.66/0.0415 MB. The sampled world
WAL and row gauges remain unchanged at 123.53 MB and 86,888 rows; unknown refresh
timing means this does **not** establish zero growth. Controller gauges change
by 13.74 MB WAL and 10,488 rows. Retained WAL is not cumulative writes.

## Profile and remaining dependencies

`output/realtime/scale-33/combat-compact-catalogs-profile` retains the opt-in
module logs and summaries. Across 315 deadline assemblies, 4,400 controller
references require 43 distinct body reads: 396,000 hot reference bytes plus
877,908 body bytes. No cache survives a transaction. Command admission still
performs 1,307 catalog body reads totaling 28.71 MB, and the inspector header
performs 322 reads totaling 4.46 MB. Those single-controller paths now pay an
additional indexed read and hash validation; they need further dependency work.

Among nonempty 200-body local action domains, read/assembly means are
2.805/1.839 ms over 19 domains, versus 3.492/4.906 ms over 52 domains in iteration
32's profile. The storage counters directly establish fewer repeated catalog
reads; differing domain counts and physical outcomes prevent treating total
profile differences as identical-work speedups.

The largest new local kernel still takes 96.42 ms for 162 due actors and 9,015
events, including 86.08 ms actor work and 10.16 ms lifecycle observation. Another
takes 79.67 ms for 153 due actors and 7,287 events. Local save peaks at
105.57 ms. Three full maintenance advances total 74.00 ms and peak at 56.48 ms;
their saves total 90.27 ms and peak at 76.97 ms. Site-perception construction
remains about 0.022 ms per sample; it is no longer the dominant phase.

The profile has only two death waves (47 and 53), 63,661 audit events and 253
active site-perception samples. Its missed-slot fraction is 47.3%, but it is an
instrumented, different execution and does not replace the release comparison.
Profile feed/reconstruction/retention checks also pass, retaining three catalog
bodies for 200 references. Failed attempts and shrinking population remain in
the original artifacts.

The next measured work is avoiding unchanged catalog materialization on command
and inspector paths, then addressing actor/evidence/save bursts and full
maintenance. Population admission and sustainability, geography, fresh model
workloads, current Bevy frame/input measurements, and the full 216-character /
30-minute and 2,000-character / eight-hour gates remain open. Normal release WASM
is rebuilt after profiling and matches the frozen release hash exactly.
