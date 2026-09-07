# Independent action and world maintenance clocks

User direction, 2026-09-07: support responsive movement/combat alongside slower
world updates, in the existing small world. Rendering remains deferred. A 20 Hz
whole-world average is a performance checkpoint, not a combat acceptance metric.

## Implemented boundary

The owner can enable `sim_configure_physical_clock(run, true)` while paused on a
native client-controller world. `sim_operator_clock` accepts action periods from
10 to 60,000 ms; that range is configuration, not a measured capacity claim.
The existing absolute deadline clock supplies action opportunities. A separate
one-shot `sim_world_wake` supplies the next maintenance deadline. Both callbacks
use the same transactional authority and shared simulation; independent scheduling
does not claim parallel execution on CPU cores.

`sim_physical_clock.next_world_ms` is a durable barrier calculated after full-world
commits. Before a local action opportunity, the authority compares the current
elapsed time with that barrier. Due maintenance uses the complete shared kernel,
including due actions in original actor order. Its existing ordering remains:
food/disturbances/infrastructure, then each actor's needs/action/hazard phase,
then lifecycle and speech. A delayed callback cannot cause already-due food,
energy, damage or law work to be skipped. Stale wake IDs are ignored; pause cancels
maintenance wakes and resume re-establishes their wall-clock mapping. The existing
60-second outage rule remains explicit recovery rather than discarded time.

Between those deadlines, the action path queries active/due actor indexes and
loads their local physical dependencies through location indexes. It invokes the
same action, perception and lifecycle-tail implementation. It saves only loaded
actors/recipients and affected sites, preserving original ordinals, evidence IDs,
permissions, histories and delivery cursors. It does not reconcile the population,
advance food/station remainders, or regenerate all participant statuses. An alive
count prevents an incomplete local domain from incorrectly stopping the whole run.

`Timing.maintenance_ms` records the settlement origin of slow-system remainders.
Fast transactions advance authoritative time while leaving those remainders
unchanged. The next full phase accounts for all elapsed time since their origin.
This state survives native storage, owner export and reload; disabling the mode
also preserves the unsettled elapsed interval.

The initial local dependency contract covers the bundled move, attack, gather,
eat, rest, wait, speak, give, deposit, build and observe skills under the bundled
base law. A radius-three query includes one movement step and its observers,
speech recipients and local catalogs. Explicit targets and station-owner arena
metadata are additional dependencies. Custom laws, modified skill implementations,
population creation and infrastructure/research/knowledge actions retain a full
shared-kernel fallback. These remaining broad transactions are explicit limits,
not evidence of thousand-player scalability. Global maintenance also still loads
all hot world state when due.

## Forensic maintenance

Physical commits retain original audit rows and update the contiguous cursor.
They enqueue at most one `sim_audit_wake` per run; compression happens in a separate
transaction, one existing 128-event block at a time. Block insertion and original
row deletion remain atomic. Existing block encoding, digest validation, complete
owner export and recipient recovery are unchanged. A backlog remains original,
exportable rows; encoder failures retain them and expose the blocked state. This
bounds work by block, not a guaranteed wall-time budget. Existing per-block byte
limits and total archive growth still require monitoring.

## Documentation and validation

Consulted official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[schedule tables](https://spacetimedb.com/docs/tables/schedule-tables/),
[performance guidance](https://spacetimedb.com/docs/tables/performance/) and
[indexes](https://spacetimedb.com/docs/tables/indexes/) before implementation.
The Rust scheduled-table pattern, transactional row writes and indexed ranges use
the pinned 2.1.0 SDK; isolated service verification uses 2.10.0. No dependency
upgrade or scheduled-procedure feature is required. Relevant Rust bindings are
regenerated with CLI 2.1.0 from the built authority WASM.

The full simulation library suite passes 231 tests, with one existing ignored
case; all 29 authority library tests and 37 bridge library tests pass. The first
bridge run failed with `/tmp` quota exhaustion (confirmed `QuotaExceeded`); rerunning
with a dedicated workspace `TMPDIR` passed without code changes. Two Python audit
export tests, Python compilation, local documentation links and `git diff --check`
also pass. New differential checks compare physical state and ordered evidence across
split/full updates, reload, food and lethal damage at an action deadline, and
custom-source fallbacks. Native projection checks cover attacks/death witnesses,
movement, speech and resources with a distant actor omitted. All 16 actual-service
functional checks pass. A 216-controller, 60-second workload used 990 local action
transactions and 72 full physical updates. A separate 215-controller/one automated
human trial at a configured 33 ms interval delivered 1,503 action-only transactions
over 60.448 seconds. All actors survived and all 107 inputs obtained execution
evidence, but p95 input-to-reducer latency was 165 ms and input-to-execution notice
was 331 ms. This does not establish smooth combat or sustained 30 Hz.

The paused world and all 129,293 exact audit event strings match after restarting
the retained service, including the maintenance origin (60,002 ms) behind current
world time (60,108 ms). Thus the unconsumed 106 ms is retained. Original workload
metrics are preserved separately from restart evidence. Both initial services and
the recovery service stopped with exit 0. Full workload, queue, subscriptions,
memory and remaining capacity limits are recorded in the
[performance report](REALTIME_PERFORMANCE.md#independent-physical-clocks-24).

The benchmark supports `--physical-clock`, `--action-period-ms`, and `--no-render`.
With a human actor and no rendering, it sends explicit participant StartAction
requests with stable IDs and records both reducer completion and the first scoped
frame showing execution. These are automated inputs; no browser smoothness or
successful model-inference claim follows. Mixed action/world update counts must
not be reported as one whole-world tick rate.
