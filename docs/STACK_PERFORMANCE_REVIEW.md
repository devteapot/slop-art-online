# Stack and architecture review against baseline 25

2026-09-07. The user asked whether the implementation is using the selected stack
incorrectly and whether 30 Hz should replace an unreasonable 60 Hz target. This
review interprets “6 Hz” as 60 Hz from the preceding contract. It evaluates 30 Hz;
it does not change the agreed target or claim that either rate is achieved.

The evidence points to substantial application and integration problems before
it establishes a platform ceiling. Keep Rust, SpacetimeDB and Bevy for the next
bounded comparisons. Fix the expensive data paths, then compare 30 and 60 Hz on
the same actual-authority workload. A larger machine or a lower timer frequency
will not repair the current admission and perception failures.

## What must work

The [contract](PERFORMANCE_CONTRACT.md) targets 2,000 active characters, including
200 interacting combatants in one locality, within 16 backend vCPUs and 64 GB RAM.
Human and AI characters share physical rules, costs, death and authority. Installed
behavior must continue while external inference is slow. The intended experience
requires ≤50 ms p95 local feedback, ≤50/100 ms p95/p99 server response, and
≤150/250 ms confirmation at 80 ms RTT. Rendering should provide stable 60 FPS and
higher rates when supported, independently of authoritative step rate.

The [baseline](PERFORMANCE_BASELINE_25.md) measures a smaller and simpler workload:
216 characters, no model inference, simple movement/needs/policies, one human and
one observer. Missing projectiles and dodges mean even a pass would be partial.
The immediate 30-minute and full eight-hour durations remain untested by request.

## New finding: the browser trial activated the wrong owner read path

Retrospective analysis of the original browser trial's metric files found:

| View, same measured minute | Calls | Accumulated view time |
| --- | --- | --- |
| Full owner `sim_run` compatibility view | 245 | 53,419.495 ms |
| Browser/human `sim_my_render_snapshot` view | 35 | 74.675 ms |

Metric boundaries are `1788805242746.prom` and `1788805302752.prom`.
Derived data is retained as
`output/realtime/baseline-25/browser-216/review-failed-window-metrics.json`.
These are accumulated view timings, not a claim about exclusive CPU attribution
or a successful workload. The loopback SDK-only minute had no `sim_run` view work.

The source explains a concrete activation path:

1. Development-host resume calls `state()` to validate the existing run.
2. `SnapshotApi` defaults to SQL. The baseline launch did not select
   `SAO_OWNER_SNAPSHOT_API=procedure`.
3. `world_json()` executes `SELECT state FROM sim_run ...`.
4. `storage::sim_run` hydrates and serializes the complete World for owned runs.
   Its read dependencies are much broader than the final SQL projection suggests.

This retained-view hazard was already documented in
[the owner snapshot contract](OWNER_SNAPSHOT_API.md): a one-off SQL query can
materialize a view that continues refreshing on relevant writes without an active
subscriber. The existing one-shot procedure avoids registering that view.
`BEVY_DEV_ARCHIVE_ONLY=1` disables background harness work; it does not change the
owner snapshot transport.

The baseline therefore exposed a real unsafe default in the development host,
and the benchmark launch repeated a known configuration mistake. It is not a
clean measurement of the incremental browser renderer's capacity. The observed
timeouts remain valid failures, but attributing them to Bevy or ordinary browser
subscriptions would be unsupported. The session-list SQL timeout may be a victim
of this work, rather than its original cause.

First corrective comparison: identical fresh browser workload, explicitly using
the existing procedure mode, with zero owner `sim_run` evaluations throughout the
active window. Require that counter condition before interpreting the result.
No such corrected trial has been run in this review. Longer term, ordinary startup
should validate ownership/run metadata through small rows, and full exports should
remain explicit checkpoints. Eliminate accidental activation of the compatibility
view from the live host; closing a browser is not a reliable remedy once it exists.

Relevant code: [host resume and world reads](../server/bridge/src/bin/sao-dev-client.rs),
[transport default](../server/bridge/src/owner_snapshot.rs),
[owner view and export procedures](../server/module/spacetimedb/src/foundation/storage.rs).

## What the stack supplies, and where our approach fights it

| Component | Verified capability or constraint | Implication for this game |
| --- | --- | --- |
| SpacetimeDB tables and subscriptions | Typed rows, indexes, transactional mutation and incremental SQL subscription evaluation | Store/update the affected physical rows; deliver changed authorized entities rather than repeatedly replacing a large JSON world projection. |
| Procedural views | Arbitrary Rust code with tracked read dependencies; invalidation reruns the view body | A function that reconstructs a World is not automatically optimized into small incremental entity updates. Keep live view dependencies and outputs narrow. |
| Query-builder views | `Query`, `RawQuery` and `ViewContext.from` are present in pinned Rust SDK 2.1.0 | Declarative filters/joins can use the query engine. This is an available option, not an assumed future upgrade; actual schema/access queries still need verification. |
| Transactions and scheduling | Atomic reducers, one-shot/interval scheduling; the examined 2.10.0 locking datastore acquires an exclusive database write lock for mutable transactions | Separate timers do not give independent mutation lanes. Long maintenance and view work can delay actions in the same database. More host cores do not automatically parallelize that lane. |
| Separate Rust controllers and bridge | Existing private controller runtime, durable commands/receipts and asynchronous external inference | Preserve the controller/authority separation. Reduce unnecessary wakes, ingestion and repeated serialization without moving model reasoning into authority reducers. |
| Bevy 0.18.1 | Separate fixed-update and per-render-frame schedules | Server rate and client FPS can differ. Prediction/interpolation and frame pacing remain application work; they are not provided merely by selecting Bevy. |
| Shared Rust/Rhai rules | Same authoritative mechanics, mutable scoped laws and explicit fallback paths | Reuse those semantics through local storage adapters. Do not trade correctness for a second approximate simulator or hard-code away user-editable laws. |

Official basis: [table design/performance](https://spacetimedb.com/docs/tables/performance/),
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/),
[procedural versus query views](https://spacetimedb.com/docs/functions/views/),
[2.1.0 bindings source](https://github.com/clockworklabs/SpacetimeDB/blob/v2.1.0/crates/bindings/src/lib.rs),
[2.10.0 transaction locking implementation](https://github.com/clockworklabs/SpacetimeDB/blob/v2.10.0/crates/datastore/src/locking_tx_datastore/datastore.rs),
[scheduled tables](https://spacetimedb.com/docs/tables/schedule-tables/), and
[Bevy 0.18.1 FixedUpdate](https://docs.rs/bevy/0.18.1/bevy/app/struct.FixedUpdate.html).
The locking-source finding is version-specific, not a claim that every SpacetimeDB
subsystem is single-threaded. Current documentation reserves the possibility of
concurrent reducer execution; that is not a capacity guarantee for this deployment.

## Other established problems and the next discriminating checks

| Finding | Classification | What should change or be measured |
| --- | --- | --- |
| Shared maintenance averages 77.18 ms execution plus query work at 216 characters | Measured over-budget transaction; whole-world dependency barrier confirmed in code | Split work by due subsystem and affected entities while settling dependencies before actions. Measure queue, load, rules, save, view, commit and delivery separately. Another scheduled callback alone is insufficient. |
| Two renderers generate 5,480 render-view calls and 16.11 seconds of view work in the healthy loopback minute | Measured presentation amplification | Separate frequently changing position/action/health rows from static map, definitions and inspector/history data. Compare equal recipients and effects; record bytes and view work per action. |
| Human render payload is 90.3 MB/minute; observer 242.2 MB/minute | Measured application payloads, not compressed wire bytes | These are roughly 1.5 and 4 MB/s for this trial. Do not extrapolate a full observer to every player. Measure delta delivery and local-density scaling for ordinary clients. |
| 24,000 `brain_tick` transactions, 16,472 ingests and 4,501 acknowledgements in the loopback minute | Measured controller amplification; not proof that all wakes are waste | Profile wakes with/without changed input and useful dispatch. Schedule relevant deadlines and changes; consider bounded batching while retaining identity, fairness and exact receipts. Controllers already use conditional wakes, so replacing a nonexistent unconditional loop is not the answer. |
| 2,000-character create fails at 256 | Application guard, not a SpacetimeDB actor limit | Design bounded population admission/bootstrap and growth accounting. Raising the constant alone would leave larger transactions and memory liabilities. |
| 200 paired attackers fail target validation with only 16 recent memories | Current perception is coupled to a short memory list during seed installation | Maintain authoritative current target availability separately from remembered experience. Preserve occlusion, scope, loss of sight and personal knowledge semantics; do not expose audit truth. |
| Enabling the lifecycle people catalog then exceeds creation energy budget | Measured startup failure; exact expensive phases not yet isolated | Profile creation separately from combat. Avoid repeatedly constructing the crowd catalog and all seed decision contexts in one unbounded operation. Transactional bootstrap stages need an explicit incomplete/not-playable state. |
| Custom laws and several skill categories fall back to the full shared World | Confirmed design limitation | Define verifiable dependency scopes and local execution for those operations. Measure exceptional global operations explicitly; custom gameplay cannot silently make every routine action global. |
| Movement waits for authoritative updates; no local prediction | Missing client capability | Prediction with reconciliation can improve local feel at either rate. It cannot make late server hits timely or change authoritative costs. |

The atomic audit/delivery facts remain necessary. Repeated unchanged observations,
presentation snapshots and controller journals are not all the same requirement.
Retain exact causal outcomes while measuring records/bytes per cause and recipient.
Archive compression is already in separate transactions; the next proposal must
not describe moving it there as new work. Retained WAL is not cumulative write
throughput, and a one-minute memory peak is not a bounded-growth proof.

## 30 Hz versus 60 Hz

| Authoritative rate | Step budget | Ideal mean wait until next step* |
| --- | --- | --- |
| 60 Hz | 16.667 ms | 8.333 ms |
| 30 Hz | 33.333 ms | 16.667 ms |

\*Uniform input arrival, one relevant next step, no backlog. These are arithmetic
examples, not measurements of this application. Several scheduled handoffs can
add separate waits; existing 50 ms controller scheduling deserves its own analysis.

30 Hz doubles the per-step budget and can reduce work that is actually performed
once per step. It does not halve all input, view, audit, controller or maintenance
costs. In the ideal example it adds only 8.333 ms average scheduling wait relative
to 60 Hz; our 396 ms p95 confirmation at 80 ms RTT is much larger. A 77 ms mutation
is still too long for either cadence, although less frequent scheduling may reduce
some queue pressure. Neither the 256-character guard nor failed creation depends
on choosing 30 instead of 60 Hz.

30 Hz is a reasonable candidate for this action-RPG experience with responsive
local prediction and interpolation. It must be playtested for attack timing,
projectile crossings, dodges and corrections as those mechanics exist. Keep the
same population, resource envelope, latency limits and independent 60+ FPS client
requirements when comparing it. Do not confuse a 30 Hz server with a 30 FPS client.

There is insufficient evidence to promise 2,000/200 at 60 Hz on one database, but
also insufficient evidence to reject 60 Hz for this stack. The small combat trial
shows short intervals are possible; it does not bound a crowded battle's cost.
Only after local work, subscriptions and diagnostics are controlled can the
remaining transaction budget reveal a genuine topology limit.

## Decision order

1. Correct the host read path and repeat the browser condition at the same rate.
   Verify zero owner-view work and retain the original failed trial.
2. Instrument the missing ingress/execution/commit/delivery intervals. Define
   representative sustained combat before calling a latency or cadence gate met.
3. Replace broad maintenance, render reconstruction and perception churn with
   local, typed, dependency-correct work. Report before/after amplification per
   physical action, including dense and sparse populations.
4. Compare 30/60 Hz at 216 characters and then higher populations with the same
   controller, client and battle conditions. Prefer the rate that meets the
   experience contract with useful headroom; one just-at-budget average is not
   headroom. The specific 200-character admission/initialization failures must be
   resolved before battle comparison.
5. If optimized representative mutation work still cannot fit, reconsider the
   execution topology. Separate authority partitions can use multiple database
   write lanes, but cross-boundary combat, transfer, laws and evidence require an
   explicit consistency design. Splitting the quiet world will not fix a single
   200-character hotspot. Moving authority outside SpacetimeDB would be a larger
   product/architecture decision, not an incidental performance tweak.

Recommendation: use 30 Hz as a comparison candidate and potentially the first
playable performance milestone; retain 60 Hz as the current target until the
corrected, representative evidence supports an explicit change. The immediate
priority is removing the established amplification, not lowering the timer to
make the current architecture appear acceptable.
