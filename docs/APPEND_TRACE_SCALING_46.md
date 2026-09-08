# Append/prune trace persistence (46)

Personal traces now carry a transaction-local append/prune journal. A native
writer can use that proof to read and update the affected boundary pages, without
reconciling every retained page. General edits retain the complete writer.
Complete actual-authority worlds, ordered audit, leases and reference counts
match the reference. This does not establish the sustained performance gates.

## Constraint and design

The completed iteration-45 implementation, measured with component subscriptions,
misses 49.2% of clock slots in the short 200-character combat diagnostic. A new
profile separates physical save phases: personal evidence persistence reaches
75.85 ms, the complete save reaches 82.58 ms, and the actor/body/hint loop reaches
9.47 ms. These maxima need not occur in the same transaction. The writer fetches
all of a changed actor's pages, builds maps of old and current metadata, and
compares retained entries even for one appended experience and one pruned record.

Consulted the official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance guidance](https://spacetimedb.com/docs/tables/performance/) and
[indexes](https://spacetimedb.com/docs/tables/indexes/) before the change. Rust SDK
2.1.0, CLI 2.7.1 and service 2.10.0 (`b22dfaac6d46`) remain fixed. This uses existing
private tables and primary-key accessors; table schemas and public JSON do not
change, so bindings are not regenerated.

The shared kernel's `Trace` retains its ordinary ordered array and deferred
payloads. Its specialized append operation preserves the exact historical rule:
append one record, then remove one oldest record if over the limit. Oversized
imported traces keep that same rule. A small journal holds the strongly owned
original snapshot and the number of original prefix entries removed. The appended
suffix remains in the current array; no second list of new records is retained.
Repeated appends share one original snapshot, not a growing chain of snapshots.
General mutable access clears the journal before exposing the records. A
serialized/reloaded trace has no journal. The proof is never a durable identifier.

The writer accepts the journal only relative to its retained kernel snapshot from
the current transaction. The previous trace's metadata was validated when loaded.
The addressed head must still match its page layout; appended cursors must follow
all previous cursors strictly. Unusual cursor order, general edits and legacy
formats use full reconciliation. The fast path reads removed prefix pages and an
existing tail page only when a new entry shares its cursor bucket. It validates
every touched row, writes changed/new pages and the changed head, and applies net
body-reference changes in the existing atomic transaction. Bodies with no current
reference are removed through the existing retention pass; captured leases keep
their exact independent evidence.

A one-record append/prune over 256 records reads two boundary pages in the focused
fixture. Appending at a fresh cursor bucket with no pruning reads no old page in
the writer. This is not a claim of zero kernel trace reads: the kernel still loads
metadata when it needs parents or other personal evidence. Eligibility also scans
the retained in-memory metadata. Work depends on the actor's retained trace and
actual changes, not a scan of other players.

The original selective writer already omitted unchanged page updates. The new
boundary reduces redundant reads and comparisons; it does not promise fewer
subscription invalidations or a different persisted format. There are no new
public recipients, added database rows or changed learning rules. Current
perception, remembered evidence and owner audit remain separate.

## Validation and identical-work comparison

The [normal frozen implementation](../output/realtime/scale-46/implementation/manifest.json)
and [profile variant](../output/realtime/scale-46/profile-append-implementation/manifest.json)
include exact source and module hashes. The final code passes
[256 kernel tests](../output/realtime/scale-46/validation/kernel-append-tests.log),
[61 authority tests](../output/realtime/scale-46/validation/authority-append-tests-workspace-tmp.log)
and [39 storage integration tests](../output/realtime/scale-46/validation/storage-append-tests.log),
with one existing ignored kernel test. The bridge passes its release compile
check against the changed internal Rust trace type. Normal and profiling WASM
builds succeed with the existing warnings.

New checks compare exact arrays and immutable snapshots through repeated
append/prune operations, over-limit imports, general edits, serialization and
reader release. Page plans match complete materialization and independent body
multiset counts across boundary crossings, gaps, arbitrary retained order and
multiple appends. Historical payload loaders deliberately fail if planning reads
them. Touched missing/foreign pages fail; unsupported append order falls back.

The initial authority compilation exhausts the separate `/tmp` quota while
assembling a dependency. Its [original log](../output/realtime/scale-46/validation/authority-append-tests.log)
remains. Rebuilding with the workspace's declared temporary directory succeeds;
this was a compiler temporary-storage failure, not a passed test or reducer error.

The [actual paired comparison](../output/realtime/scale-46/append-combat-paired-authority/result.json)
publishes both normal modules before setup, retains one warmup and two fresh
measured worlds per module, and alternates database order for two 2,500 ms owner
advances per world. Each world starts with 200 colocated characters at 20 health,
no disturbances or starting behaviors, and one authorized paired attack installed
per actor. A sequential participant identity moves its grant between actors;
there is no physical scheduler, active controller population, observer, human
input or inference during these measured owner steps. All six worlds remain in
one isolated service with its 6 GiB memory limit and 3 GiB page-pool budget.

Every corresponding initial and advanced World and ordered audit matches exactly.
Each world has 100 deaths, 100 damage events and 14,950 death observations. An
additional 260 rejected requests evict a selected record and remove its last
current body reference while a pinned lease preserves the exact captured record.
Private-table denial, scoped public access, trace reconstruction and body counts
pass. Publishing the candidate over the reference preserves all three reference
worlds. The service exits 0 without an OOM kill.

| Four measured owner advances, excluding warmup | Reference 45 | Append/prune candidate |
| --- | ---: | ---: |
| Reducer plus queries, total | 1,407.40 ms | 1,431.67 ms |
| WASM execution, total | 1,335.61 ms | 1,359.14 ms |
| CLI wall time, total | 1,483.90 ms | 1,511.23 ms |

The [recorded comparison](../output/realtime/scale-46/append-combat-paired-authority/measurement-summary.json)
is **1.7% slower overall**, with no speedup established for this coarse workload.
Large single-step death waves replace much of each trace, reducing the benefit
of boundary-only work. The new journal also adds kernel bookkeeping. These
measurements are retained alongside the narrower live profile improvement.

## Live profiles and workload distinctions

Both component profiles start 200 characters at 100 health in one cell, with
200 reference controllers, one component observer with open inspection, 60 Hz
physical scheduling and a declared ten-second active window. No human connections,
model inference or rendered Bevy client are present. The controller module and
probe remain the unchanged iteration-41 binaries. Each service has a 6 GiB memory
limit and 3 GiB page-pool budget. Population falls to 100 through ordinary permanent
deaths, so this is not a sustained-population trial.

The [before profile](../output/realtime/scale-46/combat-components-profile/clock-profile-summary.json)
and [append profile](../output/realtime/scale-46/combat-append-profile/clock-profile-summary.json)
retain all host spans and their sampling rules. On the append profile, all 133
sampled trace saves use the append journal, with 170 old-page reads in the writer,
a maximum of four per sampled save, and no sampled full reconciliation. The
kernel's metadata loading is counted separately. Sampled diff time averages
0.00417 ms versus 0.05272 ms before; nested spans are not added to their parents.

| Profile phase | Before total / maximum | Append total / maximum |
| --- | ---: | ---: |
| Physical execution | 721.48 / 82.98 ms | 724.25 / 97.47 ms |
| Physical save | 568.92 / 82.58 ms | 354.44 / 66.77 ms |
| Participant persistence within save | 411.69 / 75.85 ms | 211.91 / 60.12 ms |

The profiles execute different numbers and timings of transactions: 295 local
physical saves before and 337 afterward. Death waves and asynchronous controller
requests differ, and timers perturb both runs. The lower save totals and sampled
page counts identify the narrower writer benefit; they do not isolate an overall
speedup or resolve the remaining physical execution bursts. All declared paused
audit, trace, catalog, component-render and combat-feed scope/reconnect checks
pass for both profiles, and all four services exit 0.

The completed [normal reference](../output/realtime/scale-46/combat-components-before/stack-analysis.json)
and [normal append retry](../output/realtime/scale-46/combat-append-release-retry/stack-analysis.json)
use that same declared component workload without profile instrumentation:

| Normal release diagnostic | Reference 45 | Append/prune 46 |
| --- | ---: | ---: |
| Clock wakes / missed slots | 305 / 295 | 322 / 278 |
| Missed-slot fraction | 49.2% | 46.3% |
| Deadline execution plus queries p95 bucket | 50–100 ms | 50–100 ms |
| Deadline execution plus queries p99 bucket | 100–250 ms | 250–500 ms |
| Scheduled queue p95 / p99 buckets | 10–50 / 50–100 ms | 10–50 / 50–100 ms |
| Sampled backend CPU | 16.68 s | 17.36 s |
| World outgoing wire bytes | 19,219,960 | 17,698,828 |

The retry completes all declared checks and both services exit 0 without OOM.
It ends at 10,002 simulated milliseconds with 100 survivors, 65,953 verified
audit events and no inference or human input. The component observer has no
missing physical update IDs; delivery intervals reach 352 ms at p99 and 550 ms
at maximum. These are SDK delivery intervals, not rendered frame times.
The asynchronous runs perform different work: 9,600 versus 10,600 action-actor
loads, and differing controller requests, observations and retention timing.
Clock counters include setup/cleanup; metrics use nearest one-second samples.
The smaller missed-slot fraction does not establish a general speedup, and the
worse p99 bucket and greater CPU use remain explicit. Active combat still fails.

Retry peak RSS is 1,343,209,472 bytes for the world service, 799,690,752 for the
controller service and 559,812,608 for the relay, with no sampled swap. These
per-process peaks include enrollment. The world worker WASM gauge reaches
238,944,256 bytes; sampled world allocator allocated/resident peaks are
535,411,128 / 1,092,591,616 bytes, with a 1,704,464-byte page-pool peak.
Controller allocator allocated/resident peaks are 372,369,088 / 835,391,488 bytes.
Each service is isolated for this run; allocator gauges have independent refresh
boundaries and are not added to RSS. These short measurements establish no
long-duration memory plateau.

Sampled retained WAL endpoints are 105,281,821 → 115,190,698 bytes for the world
and 93,044,599 → 247,681,868 for the controller. WAL size is not cumulative writes.
Table gauges lag: the final sampled trace-page gauge is 1,400 while the paused
exact diagnostic counts 1,766, so sampled row changes are not treated as exact
retention growth. Paused verification reconstructs 50,667 retained experiences,
2,461 bodies and 200 heads; 17,797,152 logical body bytes occupy 836,050 stored
body bytes. Five current catalogs occupy 87,064 bytes for 200 references.
No unreachable current bodies/catalogs, legacy indexes or payload rows remain.
The original failed release attempt is documented below and stays excluded.

An earlier [completed compatibility-observer run](../output/realtime/scale-46/combat-before/invocation.json)
uses the command's default compatibility snapshot, misses 50.2% of slots and runs
only the requested audit/combat-feed checks. It remains a separate workload; it
is not compared as the same observer setup as iteration 41. The two interrupted
iteration-45 attempts also used compatibility snapshots, and their document's
observer description is corrected from the retained invocations. Original raw
invocations and failed results remain unchanged.

The first summary command redirected stdout into the summarizer's own output
path, corrupting that derived summary. Its
[original text and correction](../output/realtime/scale-46/validation/summary-correction.json)
remain; regeneration uses unchanged raw artifacts and a separate stdout file.
No authority workload or physical outcome was rerun for that correction.

## Storage reserve and remaining acceptance

The preceding combat attempts hit the fixed 8 GiB disk reserve. Sharing identical
4 KiB blocks within and between retained JSON snapshots raises measured free disk
from 8,551,878,656 to 15,814,254,592 bytes on the shared filesystem. The
[retained driver and result](../output/realtime/scale-46/validation/block-dedupe-result.json)
cover 174 files, with complete SHA-256, size, modification time, permissions and
ownership verified unchanged. No file path, original evidence or database volume
is deleted. Completed compiler-cache cleanup is recorded separately.

The first [normal append release attempt](../output/realtime/scale-46/combat-append-release/runner-result.json)
also reaches the disk guard after enrollment and the start of measurement. Its
[guard record](../output/realtime/scale-46/combat-append-release/resource-guard.json)
reports 8,573,276,160 free disk bytes, below the 8,589,934,592-byte threshold;
free RAM remains above its threshold. The probe is terminated with signal 15.
The controller service exits 0; the world service exits 1 without an OOM kill.
The retained shutdown log does not establish the cause of that nonzero exit.
This attempt has no completed final-world checks or accepted cadence result and
remains excluded. A later successful attempt does not replace it.

[Expanded block sharing](../output/realtime/scale-46/validation/expanded-block-dedupe-result.json)
then processes 27,846 completed JSON, JSONL and metrics files, verifying full
SHA-256 and file metadata unchanged. Free disk rises from 8,551,403,520 to
13,944,733,696 bytes. Already processed JSON blocks are registered for matching
without repeating their deduplication. This changes physical allocation only;
all original evidence and retained database volumes remain. No cleanup or block
sharing runs concurrently with measured workloads.

The harness now records free disk with its one-second memory/process samples and
writes actual values plus thresholds if a guard triggers. The disk and memory
thresholds remain 8 GiB and 3 GiB respectively. This improves failure evidence;
it does not relax the resource envelope.

The final [correctness summary](../output/realtime/scale-46/validation/correctness-summary.json)
and [documentation/source checks](../output/realtime/scale-46/validation/documentation-check.json)
retain all 13 stopped-service outcomes, nine frozen source/binary manifests,
workspace-to-normal-build verification and the separate failed outcomes.
Twelve services exit 0; the original guarded release world exits 1. None remains
running or reports an OOM kill. Existing development services are untouched.

The 216-character/30-minute and 2,000-character/8-hour gates, 60 Hz active combat,
client frame rate and latency, sustainable population, full model workload and
autonomous outcomes remain open. These short reference-controller runs do not
satisfy the full acceptance workload.
