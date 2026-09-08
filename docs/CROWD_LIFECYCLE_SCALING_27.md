# Crowd lifecycle scaling (27)

2026-09-08. Work toward the [world](WORLD_VISION.md) and
[simulation](SIMULATION_VISION.md) visions, following
[stack iteration 26](PERFORMANCE_ITERATION_26.md). The locked
[performance contract](PERFORMANCE_CONTRACT.md) remains the acceptance criterion.
These short diagnostics do not establish the 216-character/30-minute gate,
2,000-character admission, a sustained 200-character battle or eight-hour capacity.

## Cause and change

A fresh, instrumented 200-character actual-authority combat trial identifies
lifecycle observation as the dominant shared-kernel cost. Across three complete
shared updates in the declared ten-second window, the lifecycle-observation phase
averages 555.55 ms; the complete kernel advance averages 613.86 ms. Action-only
kernel execution averages 578.18 ms across six measured calls. These nested spans
must not be added together. Diagnostic logging perturbs execution; uninstrumented
measurements are needed for capacity comparisons.

Every character previously rebuilt the local people catalog, invoking the same
`needs_care` law for every living person in that cell and arena, even when nothing
observable had changed. A 200-person crowd therefore repeated roughly 40,000 care
law evaluations per refresh. This is application work, not evidence of a platform
capacity ceiling.

The shared kernel now computes each person's public lifecycle facts once per
refresh under the exact bundled laws and groups them by location and arena. The
same Rhai law supplies the care result; no gameplay formula moves into Rust.
Reproduction offers and the comparison with remembered observations remain
personal. The first iteration kept the original site and sight observation path
and verified exact state/event parity. Its failed release comparison exposed the
next amplification: a changed lifecycle catalog caused each recipient to observe
every unchanged peer again. The deadline transaction p99 reached the 2.5–5 second
histogram bucket. That intermediate implementation and failure remain frozen.

The second iteration treats a lifecycle change as a site-fact update, like the
existing food-renewal path. It emits each recipient's changed catalog with normal
causal links, memory and wake effects, using the already computed payload. It
does not manufacture new `seen_player` events for unchanged peers. Actual death
witnesses still execute the visibility law and receive their death perceptions;
explicit Observe and ordinary sight-producing actions retain their existing paths.
This is a deliberate change to the automatic observation trigger, not removal of
historical evidence. It also prevents repeated sightings from evicting a just-seen
death from a character's bounded memory.

That release still has a 2.5–5 second p99 deadline bucket. Removing duplicate
sight events alone is insufficient. A third iteration retains controller lifecycle
observations using the existing immutable `ExperienceData` JSON representation.
Candidate action snapshots share that payload, and native loading/serialization
can retain its encoded form. Equality first checks canonical JSON; differing
whitespace/key order falls back to parsed-value equality. This preserves the
existing stored JSON/API shape and avoids treating formatting as changed knowledge.
It introduces no new record retention policy or shared character interpretation.

The cache exists only within this completed action/maintenance refresh. It cannot
survive movement, birth, death, care, offer expiry, a reload or law activation.
Custom laws, overlays and pending law changes retain the existing evaluation path,
including failure/fallback invocation order. Arena-less actors in an arena-enabled
world do not acquire a shared visibility domain. No shared private memory,
controller interpretation or in-world archive is introduced.

The profile summarizer now includes `sim_world_pulse`, which independently executes
shared maintenance. Omitting that reducer previously excluded relevant clock spans.
The original first summary remains preserved; `clock-profile-all-clocks.json`
contains the corrected diagnostic for the before trial.

## Storage and documentation basis

Consulted official [documentation](https://spacetimedb.com/docs/),
[performance guidance](https://spacetimedb.com/docs/tables/performance/),
[indexes](https://spacetimedb.com/docs/tables/indexes/),
[views](https://spacetimedb.com/docs/functions/views/),
[scheduled tables](https://spacetimedb.com/docs/tables/schedule-tables/) and
[pinned Rust SDK 2.1.0](https://docs.rs/spacetimedb/2.1.0/spacetimedb/).
The module/client remain pinned to 2.1.0. The isolated trials use the existing
standalone 2.10.0 image `b22dfaac6d46` and control CLI 2.7.1.

This change reduces repeated computation inside the existing authority transaction;
it introduces no table, index, subscription or generated-interface change. Local
action loading still uses active/due actor and location indexes and loads neighboring
physical/controller dependencies. Global maintenance still loads the hot world.
Writes, authorized recipients, retained evidence and reconnect behavior remain on
their existing paths; the final iteration produces fewer redundant sight events.
Repeated catalog serialization, stored per-character catalog
copies, broad local loading and large changed-observation bursts remain costs to
measure and reduce. This is not yet incremental per-entity maintenance.

## Validation and measurements

Shared-kernel tests compare complete serialized state **and the separately retained
ordered event vector** between shared and unshared catalog computation. Cases cover unchanged state,
care facts, personal reproduction offers, expiry, movement, death, reload,
overlapping cells in separate arenas, both controller representations and custom
law quarantine evidence. A 24-character regression separately verifies exact death
witness counts, one changed site catalog per survivor, exclusion of the dead body
from the current catalog, retention of actual death memory and unchanged explicit
sight behavior for both controller representations. An immutable-payload regression
verifies shared ownership, unchanged canonical comparisons without parsing,
noncanonical equality, changed-value detection and preservation of the original
JSON through serialization. Simulation checks pass 240 tests with one opt-in
microbenchmark ignored.

Artifacts are retained under `output/realtime/scale-27/`. Each actual-authority
trial freezes the source, WASM, probe, scenario and invocation and preserves its
service volumes, metrics, audit export and shutdown outcome. The first trial is
`combat-profile-before`; the first comparison is `combat-profile-shared-catalog`.
The release comparisons are `combat-release-shared-catalog` and
`combat-release-lifecycle-facts`, followed by `combat-release-immutable-catalog`.
Controller-module and probe binaries are held fixed across these conditions;
the authority module is rebuilt for each implementation. The snapshots contain
current source and exact artifact hashes; controller/probe binaries are reused
from the preceding implementation rather than rebuilt for authority-only changes.

| Instrumented shared-update phase | Before | Shared catalog |
| --- | ---: | ---: |
| Lifecycle refresh mean, 3 samples each | 555.55 ms | 46.93 ms |
| Complete kernel advance mean, 3 samples each | 613.86 ms | 81.55 ms |
| Hot-world load mean, 3 samples each | 39.72 ms | 36.92 ms |
| Save mean, 3 samples each | 63.95 ms | 43.27 ms |

The reduction in repeated care-law evaluation is material, but these remaining
transactions still exceed the 16.667 ms budget. The first optimized profile's
97 action-only samples include many nearly empty updates; their 22.89 ms mean
must not be presented as dense-combat capacity. The worst action-only execution
took 1,702.50 ms. The baseline contains only six such samples, so the two overall
means describe different executed work mixtures. Asynchronous controller traces
and permanent deaths differ despite identical initial scenarios.

## Release workload and results

Each release trial requests ten seconds with 200 initial characters in one cell,
200 reference-controller connections and one SDK compatibility observer. The
catalog scenario is identical to the retained iteration-26 combat trial. Controllers
choose paired attacks under the ordinary 750 ms attack interval, energy costs,
interruptions and permanent death; there is no immunity, replacement spawning,
human input, browser or model inference. Actual attempt counts and deaths below
describe the resulting asynchronous work, not a fixed request-rate generator.
Exports and combat-feed verification occur after pausing. No full-owner `sim_run`
view is active in the measured final trial.

The host is an AMD Ryzen AI MAX+ 395 with 16 physical/32 logical CPUs and about
62 GiB RAM. Each fresh standalone service uses the existing 6 GiB memory cap and
3 GiB page-pool bound. CPU allocation is not reserved and load generation shares
the host; these trials do not certify the combined 16-vCPU reference budget.
Connections use loopback without the contract's 80 ms RTT. Resource/metric samples
are approximately one second apart, so nearest endpoint samples can include
boundary cleanup. Retained clock counters are captured after cleanup. WASM memory,
service RSS and allocator/pool figures are separate measurements.

| Release diagnostic | Shared catalog only | Lifecycle facts | Immutable catalog (final) |
| --- | ---: | ---: | ---: |
| Recorded deadline wakes / missed slots | 75 / 433 | 73 / 547 | 219 / 381 |
| Missed fraction of recorded slots | 85.2% | 88.2% | 63.5% |
| Sampled deadline transaction count | 75 | 72 | 201 |
| Deadline execution plus queries mean | 88.75 ms | 86.09 ms | 24.47 ms |
| Deadline p95 histogram bucket | 250–500 ms | 250–500 ms | 100–250 ms |
| Deadline p99 histogram bucket | 2,500–5,000 ms | 2,500–5,000 ms | 100–250 ms |
| Physical time / total updates after pause | 8,476 ms / 76 | 10,343 ms / 76 | 10,002 ms / 220 |
| Attack attempts / damage events | 593 / 593 | 680 / 580 | 894 / 694 |
| Permanent deaths / remaining alive | 33 / 167 | 100 / 100 | 100 / 100 |
| World sampled active CPU | 9.43 s | 9.52 s | 8.09 s |
| World peak RSS, including enrollment | 1.445 GB | 1.306 GB | 1.358 GB |
| World peak WASM memory | 164.95 MB | 160.63 MB | 160.76 MB |
| World retained WAL near pause | 126.90 MB | 134.51 MB | 298.09 MB |

The final histogram still contains one 500–1,000 ms transaction and one
1,000–2,500 ms transaction. Most samples are short updates after actions have
settled. Neither the mean nor the p99 describes a sustained 200-person battle.
The 100 deaths occur at physical times 3,662 and 5,011 ms in the final run; the
later clock operates with only 100 survivors. Forty-seven participant requests
are rejected because the character is dead or the run stopped. Their original
requests/rejections remain in the audit. The 200 failed attack attempts produce
normal terminal skill results; accepted intentions are not counted as damage.

Final controller/relay peak RSS is 0.718/0.475 GB; sampled active CPU across world,
controller and relay totals 14.70 seconds. World outgoing WebSocket traffic is
13.50 MB. Near the sampled active boundaries, retained WAL increases by 170.69 MB
in the world service and 182.92 MB in the controller service. Reported table/view
row counts increase by 4,907 and 37,022 respectively; materialized view rows are
included in those counters. The complete allocator, page-pool, WASM and per-table
breakdown is in `stack-analysis.json`. These figures do not establish bounded
growth and retained WAL is not cumulative writes. More completed work can increase
retained storage even when an individual operation becomes cheaper.

All 200 participants pass exact retained combat-feed equality, reconnect and
revocation checks in each optimized trial; ungranted identities and observers
receive no personal combat rows. Final exports succeed, and every trial-owned
world/controller service stops with exit code zero. The final simulation suite
passes 240 tests (one opt-in benchmark ignored), authority 31 and bridge 37.
The release WASM build, documentation links and `git diff --check` pass. Existing
unrelated workspace changes and all original/intermediate experiment artifacts
remain intact. No client code or generated bindings changed in this iteration.

## Remaining scaling work

The next transaction work should target stored catalog duplication and dependency
loading, repeated unchanged catalog construction, witness bursts and shared
maintenance. The intermediate shared-catalog export contains 200 stored lifecycle
observations totaling 4.26 MB of canonical JSON with only three distinct payloads.
The immutable representation removes repeated in-memory cloning but does not
deduplicate those database rows. Any storage replacement must retain scoped
access, exact observation versions and reconnect recovery.

All performance gates remain open. The final run misses 63.5% of recorded slots,
has over-budget transaction tails and loses half its active population. It does
not verify server ingress-to-commit latency, networked outcomes at 80 ms RTT,
client frame pacing, projectiles/dodges, 2,000-character admission, sustainable
provisioning, fresh inference or either required soak duration. The world and
simulation visions remain the goal; these are measured implementation steps.
