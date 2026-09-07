# Client controller and physical authority boundary

The user clarified and authorized this boundary on 2026-09-07. Earlier participant
runs executed installed behavior trees and subjective updates inside the world
clock. That remains the explicitly legacy execution contract for old recordings;
it is not the target architecture. The current work moves those responsibilities
to the participant runtime before pursuing larger maps or regional processing.

## Ownership

The client owns behavior trees, branch/guard evaluation, interpretation, beliefs,
memory organization, goals and its decision journal. A hosted Rust agent is a
client just as Bevy is; asynchronous inference and the fast reactive loop share
that client's permitted observations. Neither has operator credentials.

The authority owns physical state, action admission, progress, timing, costs,
interruption, shared capabilities, ownership, physical knowledge/proof records,
visibility/hearing and accepted/rejected request receipts. A client cannot submit
effects or grant itself knowledge/mastery by changing its own memory. Rhai laws
and skill effects continue through the existing shared physical kernel.

Action requests start one finite skill and refer to the currently observed action
revision. Cancellation is separately revision checked. The clock progresses the
accepted skill; a client need not send one command per physics update. Policy
replacement and reflection become local controller operations, with their own
revisions and explicitly client-reported receipts. They are not authority commits.

Private reflection retains optional knowledge drafts in the controller. An
explicit `publish_knowledge` command submits only a cited interpretation and
optional assertion to the authority, which checks personally retained evidence
and the exact currently held source using the shared knowledge implementation.
This preserves research assessment prerequisites without copying private goals,
beliefs or policy state. Publication cannot create experimental proof or executable
source from an assertion. A source no longer retained by the world must be rejected;
a client journal is not authority evidence.

Server-scoped observations are a durable delivery stream with ordered cursors and
explicit gaps, not authoritative interpretations. Current physical facts, initial
private controller seed, event rows and command receipts have separate access
patterns. The client persists its cursor, controller state, outstanding command
and journal before/after dispatch. Reconnect reconciles an uncertain command;
neither receipt timeout nor restart silently repeats an action. A disconnected
controller does not keep choosing new actions inside the authority. Already
accepted physical actions remain subject to authority timing and interruption.

## Storage and compatibility constraints

New authority metadata and immutable per-actor bootstrap rows are private and
indexed by run/actor. Sender-authenticated views check the current grant before
returning a participant's rows. Routine controller reads use local subscriptions;
no whole-world export or owner snapshot enters a controller. Existing durable
scoped experience rows provide reconnect delivery; subjective history lives in
the client's own checkpoint and journal. Server outcome events and client decision
events retain distinct provenance and can be joined using request/event IDs.

Existing recordings and databases are not reset, converted or rewritten. The new
creation route and updated development host select client execution explicitly.
Legacy creation remains available for old-contract regression comparisons.

The official [tables](https://spacetimedb.com/docs/tables/),
[indexes](https://spacetimedb.com/docs/tables/indexes/),
[performance](https://spacetimedb.com/docs/tables/performance/),
[views](https://spacetimedb.com/docs/functions/views/),
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) and
[event tables](https://spacetimedb.com/docs/tables/event-tables/) documentation was
consulted before this design. Group rows by access/update pattern and use indexed
local operations. Spatial filters alone are not permissions. Transient events
alone cannot satisfy durable delivery, replay or reconnect recovery. Module/SDK
APIs remain pinned to 2.1.0; experiments use the previously verified isolated
2.10.0 runtime without upgrading the development service.

## Acceptance

Verify client branch/once/sequence/preemption semantics; authority action parity,
failed costs, interruption, death and changed laws; scoped event delivery and
denied foreign access; local reflection without authority mutation; stale revision
and duplicate-command handling; checkpoint restart and disconnect behavior; real
model operations through built-in and external clients; and human action parity.
Measure the crowded 72/216-actor workload with actual connected controllers,
declared input rate and retained client/server evidence. Shifted client CPU/network
cost must be reported alongside authoritative cadence. No capacity claim follows
from an idle server, dropped clients, disabled mortality or removed physical rules.

The boundary is implemented. Protocol, kernel and browser checks are recorded
below; successful fresh inference and the 20 Hz scale target remain open.

## Native controller service (2026-09-07 direction)

Native players use a separate controller database as the canonical client
implementation. Its private actor rows own policy execution and subjective
state. A Rust relay subscribes to the world with each actor's ordinary grant,
forwards scoped inputs, dispatches queued physical commands, and returns receipts.
Model inference remains in Rust workers. Reducers have no external network I/O
([official reducer documentation](https://spacetimedb.com/docs/functions/reducers/)).

The evaluator stays transport-independent. External controllers may implement
entirely different internal logic while consuming the same world protocol. No
world reducer reads the controller database; no shared controller database grants
characters access to other minds. Controller groups can be distributed separately
from physical world zones. Actual process/resource isolation requires separate
service instances; another database name alone is not a dedicated CPU allocation.

Cross-database delivery is asynchronous: retain ordered input cursors, one pending
physical command per actor, request IDs and receipts, and an exclusive relay
ownership epoch. There is no atomic transaction spanning the two databases.
Measure both services and the relay, including extra latency and retained data.

The first 72-controller, 60-second trial exposed repeated context/history writes
in controller checkpoints. The controller storage now separates model context
(one private row, updated when context changes) and immutable scoped inputs
(owner/cursor index, latest 256 rows) from policy execution state. Only observation
and reflection commands load the retained input window; policy ticks use the
controller's current subjective state and physical frame. Personal memories,
remembered sites, beliefs, relationships and knowledge use a separate private
history row, with deferred field decoding and updates only when contents change.
These are controller-local point accesses, not world reads or all-mind scans.
Every newly ingested scoped input is also appended once to the private journal.
Explicit read leases
and the decision journal preserve their separate evidence contracts. This follows
the indexed access patterns in the official table guidance above. The original
trial is retained; a new trial must establish the cost of this revision.

## Finite controller measurements

All three initial trials used 72 living characters, the unchanged crowded 48×36
scenario, one connected canonical controller per character and a 60-second window.
No model calls, human inputs or observer exports ran during measurement. Each
actor held seven sender-scoped world-view subscriptions and four controller-view
subscriptions; action traffic came from its unchanged seed policy. The 72/216
seeds begin on nine cells (maximum initial occupancy 16/48). Each
trial used fresh world/controller service processes (2.10.0), each limited to
6 GiB with a 3 GiB page pool, plus a separate Rust relay process. The scenario's
starting policies and physical rules were retained. Full exports occurred after
pause. All 72 characters were alive at the end.

| Controller storage | World updates/s | Controller retained WAL at end | Evidence |
| --- | ---: | ---: | --- |
| Whole checkpoint | 17.98 | 2,297 MiB | `output/client-boundary/pop72-60s/` |
| Separate context and input rows | 18.15 | 690 MiB | `output/client-boundary/pop72-split-60s/` |
| Separate personal history as well | 18.23 | 231 MiB | `output/client-boundary/pop72-mind-60s/` |

The final row consumed approximately 25.06 world CPU seconds, 8.65 controller CPU
seconds and 10.84 relay CPU seconds during the sampled active window. Peak RSS,
including enrollment, was 837 MiB world, 593 MiB controller and 260 MiB relay.
These figures show reduced repeated controller writes, not sustained 20 Hz or
large-population capacity. The first trial's CPU/metric window included enrollment
because its probe lacked wall markers; do not compare its CPU total directly.
Retained WAL is not cumulative writes. Per-service table, subscription, queue,
allocator/pool and WASM metrics and exact source/module/probe hashes are retained.

The first measurement runner used an unsupported shutdown flag; separate recorded
SIGINT cleanup exited both services with code zero. The corrected later runners
exited both services with code zero. Earlier smoke-test shutdown code 137 remains
recorded as forced, not graceful. No development database was changed.

The first 216-character trial of this layout completed with all 216 alive but
only 4.17 updates/s (`output/client-boundary/pop216-mind-60s/`). This is a recorded
regression, not acceptance. World action commands still eagerly loaded bootstrap
and retained evidence, and the procedural event view repeatedly materialized its
retained rows. The live-facts view also read physical execution counters that
changed on every update.

**Later correction:** the [real-time investigation](REALTIME_PERFORMANCE.md#version-specific-view-invalidation)
found whole-table invalidation in the pinned 2.10.0 query-view implementation.
The incremental-evaluation expectation below was not borne out; retain the trial
results as recorded and use the later versioned-source finding for new work.

The next revision uses the existing deferred native reader for participant
transactions, a separate per-actor published-facts row updated only when visible
contents change, and a query-builder event view. The view authenticates the grant
and client bootstrap before returning a `(run, actor)`-filtered query; grant
changes invalidate the scope, while new experience rows are evaluated
incrementally. The pinned 2.1.0 Rust crate exposes `ViewContext::from` and `Query`,
and the resulting view was published and tested on 2.10.0. The official
[view performance guidance](https://spacetimedb.com/docs/functions/views/#performance-considerations)
explains the distinction between procedural read-set invalidation and incremental
query evaluation. This revision's live protocol check passed foreign/private
access denial, revocation, both transport reconnects and completion of an in-flight
action without duplicate dispatch (`output/client-boundary/functional-01/probe-02-result.json`).
Its population cost must be measured separately from the failed 216-character trial.


The first query-builder trial, `output/client-boundary/pop216-incremental-60s/`,
failed its 30-second pause acknowledgement deadline and later logged relay receipt
timeouts. Cleanup obtained pause and a final export with all 216 alive; both
services exited zero. Its 83 final updates include cleanup and must not be divided
by the requested 60 seconds to claim cadence. The original result, metrics and
failed summarizer invocation are retained.

The 2.10.0 [query planner source](https://github.com/clockworklabs/SpacetimeDB/blob/v2.10.0/crates/physical-plan/src/rules.rs#L429)
requires equality predicates for every index column in `IxScanFromPredicates`.
The view filters `(run, actor)`, while the pre-existing native reducer index is
`(run, actor, cursor)`. A separate two-column `controller_scope` index now matches
the view exactly. The three-column index remains necessary for ordered reducer
reads and retention. This adds one B-tree entry per retained experience, with the
same 256-row-per-actor retention; it adds no recipients or payload copies. Generic
prefix-scan support in the table API does not establish this SQL optimizer path.

## Functional verification

`output/client-boundary/functional-01/probe-02-result.json` records ten passing
live checks: ungranted and foreign access, denial of raw private controller tables,
a finite action, both transport reconnects, retained policy, in-flight completion
without duplicate dispatch, and revocation. The earlier probe's immediate
post-disconnect assertion failed because SDK disconnection is asynchronous; the
corrected probe waits for disconnection. Both original outcomes are retained.

Final kernel tests passed: 223 simulation tests (one ignored), 37 bridge library
tests, 14 host tests and two live-agent payload tests. Seven controller kernel
tests cover policy semantics, authority validation, private reflection, paid
human/action parity and permanent death. Eight native storage tests cover
actor-scoped transaction parity. The browser WASM build passed.

The actual built-in harness and persistent external MCP worker each attempted
behavior, communication and learning with the configured `gpt-5.6-luna` streaming
profile, one attempt and a 300-second request deadline. All six requests returned
provider HTTP 530; no model substitution or automatic retry was made. The world
stopped after approximately 130 simulated seconds when the unprovisioned actors
died. Requests, response bodies, controller records, final world and revoked grants
are retained in `output/client-boundary/model-browser-02/`. This verifies failure
reporting and access through both routes, not successful new model-generated
policy, learning or communication. The earlier unlaunched supervisor failure
(`arenas` absent in the ordinary scenario) is retained separately; the supervisor
now treats that optional matrix metadata as optional.

Actual Bevy/Chromium verification passed page rendering, participant/observer
switching, movement from 149 to 150 and free-form `hi` speech. In the separate
no-inference world `sim-bevy-1788778159831`, speech #216 follows skill attempt #215
and completed result #218; the world was paused before stopping the host.
`output/client-boundary/browser-human-01/browser-verification.json` and browser
screenshots retain the evidence. Chromium required a short, writable temporary
directory; earlier browser-launch failures are retained. No page errors occurred.
The earlier model-world speech attempt happened after death and is not counted as
successful speech.


## Final 216-controller result and remaining work

`output/client-boundary/pop216-scope-index-60s/` completed its controller workload:
265 updates over 61.426 seconds including pause acknowledgement, **4.31 updates/s**,
60.628 simulated seconds, all 216 alive and zero sampled controller faults. The
active metric window contains 4,551 participant commands (approximately 75/s).
Mean world pulse execution plus query time was 118.90 ms; participant commands
averaged 5.47 ms. The matching index removed the preceding timeout failure in this
trial, but the result remains below the earlier 7.02 updates/s authority-policy
baseline and far below 20 Hz. Those architectures generate different dispatch and
perception schedules, so this is a workload comparison, not an isolated speedup.

World/controller/relay active CPU totals were 57.73/22.19/33.18 seconds. Their peak
RSS values, including enrollment, were 1,090/785/488 MiB, with no sampled swap.
Retained WAL at the measurement endpoint was approximately 310 MiB world and
650 MiB controller. Controller ticks averaged 0.53 ms and scoped-input ingestion
0.42 ms; world pulse and action processing still dominate the serialized world
work. Full resource/subscription/table/queue metrics are retained in `summary.json`
and the original metric samples. This finite run does not establish sustainable
retention or thousand-player capacity.

After the probe exited successfully and paused, the measurement wrapper raced
reading `/proc` and failed on missing `VmRSS`. Both services stopped with exit zero.
The retained paused world service was restarted only to recover the final owner
export, then stopped again with exit zero. Original measurement metrics precede
that restart; `runner-result.json`, `export-recovery.json` and recovery shutdown
records explicitly preserve the wrapper failure. The wrapper now handles an exited
probe without losing its exit status or skipping normal finalization. This is a
completed workload with separately recovered export, not a clean original wrapper
run. Probe timing markers are now written before pause so a future pause timeout
cannot erase measurement boundaries.

Remaining acceptance work is successful fresh model operations once the provider
is available, lower world pulse/dispatch costs under living-controller load, and
long-duration resource measurements. Larger maps/regions remain deferred; splitting
the controller service alone has not solved the crowded-world bottleneck.


## Recoverable dispatch and relay supervision

The world now exposes `sim_dispatch_controller_action(sequence, request)` and
`sim_my_controller_dispatch`. The request is still the ordinary finite
`StartAction`/`CancelAction` request with its action revision and control epoch.
A private `(run, actor)` mailbox stores one sequence, canonical request and exact
receipt. Action execution/admission and mailbox persistence happen in one reducer
transaction. Equal sequences require identical requests; lower sequences are
rejected; a higher sequence replaces the previous result. Ownership epoch changes
require explicit handoff. This provides bounded retry protection after general
participant receipts rotate out, including rejected physical commands.

The canonical outbox persists its sequence before dispatch. The old `claimed`
flag remains inspectable, but no longer prevents recovery: a pending request can
be retried with the same sequence and payload. General reads never overwrite the
dispatch mailbox. The controller retains one last acknowledgement per identity so
an acknowledgement retry cannot clear a subsequent outbox or repeat journal work.
Neither service grants the relay operator access. The world mailbox is available
to any authenticated participant using this protocol, not only the native client.

This follows the official [reducer transaction contract](https://spacetimedb.com/docs/functions/reducers/#transactional-execution)
and [subscription model](https://spacetimedb.com/docs/clients/subscriptions/).
The new world read/write path uses grant, head, bootstrap and mailbox point lookups,
then the existing actor-scoped physical command transaction; it introduces no
world export or all-player scan. Storage adds one mailbox per actor and one last
acknowledgement per controller identity. Native connections add one sender-scoped
world view (eight total), while controller subscriptions remain four. Old frozen
modules/databases are retained unchanged; the new controller outbox schema and
world endpoint require matching regenerated bindings and module deployment.

Transient relay transport errors now retry the pending operation with bounded
backoff, reporting the fault until recovery. A finished relay task is detected
independently of transport health by `reconnect_if_needed`. Resident native
controllers have a host supervisor even when no model worker is active; teardown
aborts and awaits those owned tasks. Epoch changes and experience gaps remain
explicit errors, not silent reseeding or lost-history recovery.

`output/client-boundary/recovery-01/result.json` records actual SIGKILL of a
separate relay process after queuing, after claiming, after authority commit and
after controller acknowledgement. All four cases resumed the same private
identities and completed exactly the same action at revision one. The committed
case first issued 70 observation reads, verified eviction of the ordinary receipt,
and recovered the exact original result from the durable dispatch mailbox. Each
case also restarted an interrupted relay with healthy transports, rejected changed
content at the same sequence, and rejected a superseded sequence. The broader
10-check access/reconnect protocol passed against these modules; revocation also
removed the new dispatch view. Test runs were paused, grants revoked and both
services stopped with exit code zero. These checks do not establish automatic
recovery from long event gaps, controller-service failover, or all possible timeout
and concurrent-writer schedules. The additional timeout check below narrows that gap.


`output/client-boundary/recovery-timeout-01/` adds an actual timeout-after-commit
case using `scripts/recovery_response_proxy.py`: requests reach the authority,
while responses are held without closing the socket. The client observed its
10-second timeout with an active connection. After SIGKILL, the resumed identity
verified that the original dispatch had committed, recovered the original result,
and completed at revision one. The same changed-content, superseded-sequence and
healthy-transport task-restart assertions passed. Owner cleanup bypassed the proxy;
the run was paused, grants revoked, the proxy terminated, and both retained
services stopped with exit code zero. This tests ambiguous delivery plus process
recovery; it does not independently certify every background-backoff schedule.

### Recovery-pass profile and regression checks

The opt-in instrumented 216-actor, 20-second diagnostic is retained at
`output/client-boundary/recovery-pop216-profile-20s/`. It used the same crowded
48×36 scenario and separate world/controller services as the preceding finite
trial, with 216 persistent relay connections to each service, eight scoped world
views and four controller views per identity, seeded local policies, no inference,
no human input, and no observer/export load during measurement. Exports occurred
after pause. All 216 actors survived and no controller faults were sampled.

Across 115 profiled pulses, mean clock load/advance/save time was
7.56/38.13/13.81 ms. Actor processing accounted for 4.365 of 4.385 seconds of kernel
advance time; its worst pulse took 1.643 seconds. Participant delivery averaged
1.79 ms per pulse, so the proposed receipt-publication optimization was not
selected as the main fix. This profile localizes the remaining clock bottleneck
to actor work, but does not yet separate physiology, action execution and script
costs inside that loop. The world also processed 1,818 dispatches at a mean
4.46 ms including query work (approximately 84/s over the measured window).
Clock and command costs both matter; optimizing only controller storage cannot
remove the world bottleneck. Instrumented timings are diagnostic, not a capacity
claim. Raw spans, reducer/queue metrics, resource gauges, table counts, network
counters and exact implementation artifacts are retained.

The normal world WASM and release relay probe were rebuilt after profiling.
Regression checks passed: 223 simulation tests (one existing ignored test), 37
bridge library tests, 14 development-host tests and two snapshot compatibility
tests. The first bridge run failed because `/tmp` returned `EDQUOT` on writes;
a writable `TMPDIR` cleared the audit failures. One short-deadline streaming test
then failed under parallel load; the full bridge suite passed serially with its
original timeout unchanged. All attempts are retained in
`output/recovery-final-*-tests*.log`. Python syntax and `git diff --check` passed.


### Uninstrumented finite load after recovery changes

`output/client-boundary/recovery-pop216-60s/` retains the matching normal build,
source hashes and final successful run. The declared active duration was 60 seconds;
the measured start-through-pause acknowledgement interval was 61.350 seconds,
with 273 updates and all 216 actors alive: **4.45 updates/s**, compared with the
preceding 4.31. This single pair does not establish a repeatable speed improvement,
and remains far below the 20 Hz target. No controller faults were sampled. The
workload had the same density, subscriptions, seed-policy and observer/inference
conditions as the diagnostic above. It processed 4,959 sequenced world dispatches
in the nearest-sample metrics window (approximately 81/s, 0.37 per actor/s).

| Metric | World service | Controller service | Native relay process |
| --- | ---: | ---: | ---: |
| Peak RSS, including enrollment (MiB) | 1,092.2 | 776.7 | 500.2 |
| Active CPU seconds | 57.62 | 21.10 | 33.70 |
| Active WASM memory gauge peak (MiB) | 141.75 | 2.44 | n/a |
| Retained WAL at end (MiB) | 321.67 | 691.80 | n/a |
| WebSocket bytes sent, sample-window delta (MiB) | 23.08 | 7.10 | not separately metered |
| Scheduled-reducer aggregate wait (seconds) | 24.74 | 3.70 | n/a |

Mean reducer execution plus query time was 114.16 ms for world clock pulses and
5.06 ms for dispatches; controller tick/ingest/ack means were 0.483/0.405/0.213 ms.
Removing the claim round trip left no `brain_claim` calls in the measured run.
The final sampled bounded recovery tables each contained 216 rows
(`sim_controller_dispatch` and `brain_last_ack`). Durable evidence still grew to
51,900 world experiences and 155,973 controller journal rows. Forty-five outboxes
were pending at the final sample; the benchmark pauses and revokes rather than
claiming that every queued action drained. Full table inventories and allocator,
pool, queue, network and memory metrics remain in `summary.json` and raw samples.
WAL figures are retained size, not cumulative write volume; service RSS includes
allocator retention, not only live world rows. This is a finite trial, with no
long-term storage bound or service-failover acceptance. Both isolated services
stopped with exit code zero; the development service on port 3101 was untouched.

Next performance work should split actor-loop profiling into physiological,
script and physical-action costs, then measure a targeted change under living
controllers. Long-lived controller evidence retention, recovery across expired
experience windows, successful fresh model operations, sustained cadence and
thousand-player capacity remain open. The bounded retry/supervision pass does not
resolve those separate acceptance requirements.
