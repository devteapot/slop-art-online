# Deferred initial definitions and action admission (45)

Local native transactions no longer decode an unused full population seed.
Action admission uses a private, versioned projection containing its map and rule
configuration. At 2,000 characters, normal-release participant REST admission
falls from 71.51 ms to 1.71 ms across five sequential samples per version.
The final build with separate bounded caches averages 1.76 ms for five further
samples. Complete world state and ordered audit match the frozen shared kernel.
These diagnostics do not establish the sustained performance gates.

## Documentation and storage boundary

Before designing the change, consulted the official
[SpacetimeDB documentation](https://spacetimedb.com/docs/),
[reducer transactions](https://spacetimedb.com/docs/functions/reducers/) and
[indexes](https://spacetimedb.com/docs/tables/indexes/). The export correction also
consulted [procedure transactions](https://spacetimedb.com/docs/functions/procedures/):
values serialized after `try_with_tx` must already own their database dependencies.
The authority remains on Rust SDK 2.1.0, CLI 2.7.1 and isolated service image
`b22dfaac6d46`; this uses existing tables and APIs, with no generated binding change.

The initial definition is 3,451,006 encoded bytes in the full-population world,
above the parse cache's 1 MiB retention bound. The first profile attributes
70.55 ms of mean participant command read time to its repeated decoding.
Deferring that read removes the cost from control changes, which never consume
the seed. It alone does not fix action admission: the second profile moves the
same roughly 71 ms into execution, where the kernel needs map and society rules.
The [three profiles](../output/realtime/scale-45/validation/profile-comparison.json)
retain this failed intermediate hypothesis and the resulting dependency change.

`initial_deferred` reads the definition version by primary key and creates a
transaction-local loader on a cache miss. First consumption fetches the body by
key, verifies its digest and decodes it. Unused bodies are neither fetched nor
validated; consumed corrupt or missing bodies fail. Missing legacy version rows
retain the full-body fallback. Only parsed, loader-free values can enter the
cache. Copy-on-write preserves isolation. Initial, admission and script values
have separate single-entry caches, each limited to 1 MiB of encoded input; this
bounds entry count independently of world population, not decoded heap size.
Separate slots prevent physics and local action admission evicting each other's
small-world definitions. Oversized definitions remain valid but uncached.

`action_admission_initial` uses the shared `Scenario` type and copies all fields
except initial players, knowledge and starting behaviors. Those three fields
account for nearly the entire large seed. The retained 36,269-byte projection
keeps map, society, laws and other configuration. It is used only by the existing
narrow start/cancel action and control paths, which execute the same shared
kernel. A single physical human input can use this path when it has no speech,
reflection or policy update; other human and participant requests retain their
wider context. Actor and explicit target rows retain their existing keyed reads.
No actor state or original seed is replaced by the projection in a commit.

One private `sim_native_definition` row (`admission_initial_v1`) and two existing
version-table rows hold the projection digest and canonical source digest.
Initialization and full saves maintain these atomically and skip unchanged
preparation. Existing native databases can explicitly prepare them through
`sim_migrate_native_state`, whose full-world migration cost is outside routine
local actions. Missing or stale projection metadata falls back to the canonical
seed. Invalid consumed projection contents fail digest validation. Bounded world
cancellation removes the projection and both version rows. These are constant
extra row counts per world; their body size follows rule/map configuration.
They have no new public subscription recipients. Existing actor publication,
receipts and audit remain durable and scoped by the existing authority.

Explicit owner exports and view snapshots materialize the complete original
initial definition inside the database transaction. Full exports remain costly
explicit diagnostics; they are not part of local command admission. Global
physical and maintenance paths retain their full logical dependencies.

## Correctness, variants and failures

The final [frozen implementation](../output/realtime/scale-45/implementation-cache-isolated/manifest.json)
passes [58 authority tests](../output/realtime/scale-45/validation/cache-isolation-tests.log)
and [253 kernel tests](../output/realtime/scale-45/validation/kernel-final-tests.log),
with one existing ignored kernel test. Tests cover unused oversized definitions,
first-use verification, loader lifetime, copy-on-write, separate cache slots,
legacy fallback and full-kernel parity for narrow control and human action paths.
The release WASM build succeeds with the existing warnings.

The final [actual authority comparison](../output/realtime/scale-45/definition-isolated-authority/result.json)
passes 71 complete world-and-audit checks, 16 access denials and three controller
modes. It covers repeated grants, handoffs, queued speech and lease invalidation,
human input, old/new module upgrade, idempotent projection preparation, private
row access and removal of unpublished projection state. Its service exits 0.

The initial compile/test failure removed an eager helper still used by rendering;
[the original compiler log](../output/realtime/scale-45/validation/unit-tests.log)
remains alongside the corrected build. More significantly, the first actual
candidate allowed a lazy seed to escape a procedure transaction. Owner export
then attempted a database read during serialization and panicked. Its
[failure](../output/realtime/scale-45/definition-parity-authority/failure.json)
and [service exit 1](../output/realtime/scale-45/definition-parity-authority/stop.json)
remain unchanged. This was not a graceful service stop. The owned-export
correction passes a separate full authority comparison before the final cache
isolation variant is tested again. No failed outcome is overwritten.

The preserved 2,000-character database is upgraded in place without resetting
its population or clock. Three diagnostic profiles, the normal before/after
release comparison and final isolated-cache build perform 69 recorded operations
in total: 36 control changes and 33 participant/human action admissions. The
[normal release replay](../output/realtime/scale-45/population-2000-definition-release/result.json)
compares all 57 preceding operations and 82 new audit events against the frozen
44 shared kernel. The [final build replay](../output/realtime/scale-45/population-2000-definition-isolated/result.json)
compares its further 12 operations and 20 audit events. Both complete 201 MB
worlds and ordered audit outputs match byte for byte. The
[retained Cargo checker](../output/realtime/scale-45/validation/replay-tool/manifest.json)
unifies JSON features and records its dependency lockfile. Final grants contain
only the original actor-2000 controller; all 2,000 characters remain at tick and
time zero. Every population diagnostic service stop exits 0.

## Sequential full-population measurements

The world has 200 colocated and 1,800 distributed characters on the existing
Ryzen AI MAX+ 395 host. The isolated service retains the same database, with a
6 GiB limit and 3 GiB page-pool budget. There is no active clock, model inference,
subscribed observer, rendered client or competing request stream in these
measurements. Exports and offline replay are outside the sampled call windows.
The participant API and human convenience reducer execute REST admissions;
these timings do not measure completed physical rest outcomes.

| Operation | Samples per version | Reference 44 mean | Normal candidate mean | Final isolated-cache mean (samples) |
| --- | ---: | ---: | ---: | ---: |
| Grant control | 5 | 70.74 ms | 1.25 ms | 1.99 ms (2) |
| Revoke control | 5 | 70.92 ms | 0.81 ms | 0.74 ms (2) |
| Participant REST admission | 5 | 71.51 ms | 1.71 ms | 1.76 ms (5) |
| Human REST input reducer | 3 | 71.07 ms | 1.09 ms | 1.15 ms (3) |

The [normal measurements](../output/realtime/scale-45/population-2000-definition-release/measurement-summary.json)
and [final measurements](../output/realtime/scale-45/population-2000-definition-isolated/measurement-summary.json)
retain every sample, WASM timing, HTTP wall time, 50 ms process samples and
resource endpoints. These are reducer-plus-query execution times, not queue
latency, end-to-end input latency or statistically established percentiles.
Final ranges are 0.72–3.26 ms for grants, 0.73–0.76 ms for revocations,
1.27–3.53 ms for participant admission and 1.05–1.27 ms for human input.

Final sampled service RSS peaks at 1,223,933,952 bytes with zero sampled swap.
WASM endpoint memory grows from 1,769,472 to 2,555,904 bytes during those calls.
Module publication resets its WASM instance, so comparison with prior samples
is not a controlled memory-saving claim. Allocator, pool, row-count and retained
WAL gauges do not refresh during this short final series: the retained log reads
655,826,079 bytes throughout. Their unchanged values do not establish zero
writes or growth, and allocator points do not represent process RSS. The raw
artifacts preserve these limitations. No long-duration resource bound is proven.

Inactive compiler caches were removed only after checking process use and link
ownership. Byte-identical retained checkpoint extents were shared with Linux
`FIDEDUPERANGE`, verifying complete hashes and file metadata unchanged. Cleanup
manifests are retained in the validation directory; failed artifacts and database
volumes remain. The active benchmark retains its 8 GiB disk and 3 GiB available
host-memory guards.

## Interrupted active combat diagnostics

Two separate attempts use the frozen final authority with the unchanged
iteration-41 controller module and population probe. Their
[combined manifest](../output/realtime/scale-45/combat-implementation/manifest.json)
records this provenance. The scenario starts 200 combatants at 100 health in one
cell, with 200 reference controllers, one compatibility-snapshot observer with open inspection,
60 Hz physical scheduling and a requested ten-second active window. There are no
human connections, rendered Bevy browser or model calls. Each isolated service
has a 6 GiB memory limit and 3 GiB page-pool budget. The ordinary development
service remains separate and running.

The [first run](../output/realtime/scale-45/combat-release/runner-result.json)
and [retry](../output/realtime/scale-45/combat-release-retry/runner-result.json)
both enroll all 200 characters and enter measurement, then hit the disk reserve
guard before completion. The harness sends SIGTERM to each probe (exit -15).
Both world and controller services in each attempt subsequently exit 0 with no
OOM kill. These are interrupted workloads, not graceful benchmark completions.
No committed final world or declared post-pause correctness checks are available.
Both summaries explicitly exclude them from performance comparisons.

After the first failure, exact sharing of
[identical retained data](../output/realtime/scale-45/validation/identical-data-dedupe.json)
raises free disk from 8,758,681,600 to 9,355,243,520 bytes, without changing file
hashes or metadata. The retry still breaches the fixed 8 GiB reserve. Its last
sample has 17,973,399,552 bytes of available host memory, so host memory is not
the triggering threshold. Raw service metrics and process samples are retained;
the existing harness does not record a disk gauge for each sample. Shared-host
disk changes and retained databases therefore cannot be attributed solely to
this workload. No guard is lowered and no experiment volume is deleted.

There is **no new valid live-cadence result** from this iteration. The previous
completed release still misses 45% of clock slots under the
[iteration-41 workload](SHARED_TARGET_SETS_41.md). Establish sufficient disk
reserve before repeating the complete active comparison. Physical-clock
read/save bursts and global maintenance dependencies remain the next performance
work, alongside sustained resource retention. The 216-character/30-minute and
2,000-character/8-hour gates, 60 Hz combat, client frame rate, full model workload
and autonomous outcomes remain open.
