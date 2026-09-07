# Native scale trials and clock follow-up

Later evidence: [clock implementation and profiling](NATIVE_CLOCK_IMPLEMENTATION.md)
records an isolated runtime comparison and subsequent history/cache optimizations.
The measurements below retain their original implementation and outcomes.

This follow-up tests the verified native-state implementation at 72 and 144 initial
actors. It does not change the gameplay module or clock algorithm. The question is
whether the faster local transaction path remains responsive under larger, longer
loads, and which limits should govern the next clock refactor.

## Prospective workload

- Three wall-clock minutes per run; scheduled clock interval remains 50 ms.
- Persistent authenticated SDK connections: one per initial actor.
- Twelve simultaneous read rounds at 5, 20, ..., 170 seconds; 128 experiences per
  observation, ten-second deadline, no retry. This preserves the prior per-actor
  request rate while extending duration. Maximum requests: 864 / 1,728.
- Same 48-by-36 map, facilities, site food, generation and weather as the original
  faction seed. Initial actor templates, starting behavior, body/material config
  and initial knowledge seeds are duplicated with unique actor/record identities.
  Arena membership extends to the new actors. Territorial grants, organization
  memberships and office holders remain unchanged. No runtime character history,
  learned evidence or completed jobs are copied.
- Maximum initial co-location rises from 8 to 16 / 32. This is a density and
  resource-contention trial, not a constant-density population comparison.
- No models, observer subscription or exports during the active window. Mandatory
  owner exports and audit reconciliation occur at paused boundaries. No build
  runs concurrently with the workload.
- Fresh isolated service, database and volume on localhost:3103 per attempt.
  Existing archives and services are untouched. Module/client SDK remains 2.1.0;
  the exact previously verified WASM is reused.

The existing runner now accepts explicit population, duration and read rounds;
its default 36-actor/60-second workload is unchanged. The fixtures are generated
by `scripts/prepare_native_scale_fixture.py` and validated by `World::new` through
the native probe's `--check-fixture` mode. Larger scenario creation uses the
same authenticated HTTP reducer endpoint as the official CLI, avoiding Linux's
per-argument size limit. Read operations still use the real persistent SDK clients.

## Limits and evidence

The service has a 12 GiB memory limit and no extra swap. One-second telemetry
stops the owned service if RSS exceeds 11 GiB, host available memory falls below
3 GiB, host free disk falls below 8 GiB, or retained log size exceeds 4 GiB. A
resource abort is a failed trial, not a successful shorter run. Read acceptance
requires every scheduled request to complete within ten seconds with its own
observation and corresponding authoritative receipt. Clock progress and the 20 Hz
target are reported separately; passing reads does not certify clock capacity.

The 144-actor run follows only after the 72-actor run's cleanup is resolved and
resource bounds are assessed. Each result retains manifests, fixture hashes,
telemetry, read outcomes, audit reconciliation, pause/revocation/disconnection and
service-stop evidence. Summaries use `scripts/summarize_native_scale.py`; percentile
latencies use nearest ranks and metric deltas use the nearest one-second samples.
Retained WAL size is not cumulative bytes written. Service RSS includes the
isolated database host and connection/module instances, not just character rows.

The first setup attempt (`pop72-180s`) never created a world: its CLI argument was
too large. The first offline fixture also exposed duplicate seeded record IDs.
Both are preserved. Version-2 fixtures assign unique seed record IDs, both pass
`World::new`, and subsequent attempts use HTTP creation. These are setup failures,
not population-performance measurements.

## Results

| Three-minute density trial | 72 actors | 144 actors |
| --- | ---: | ---: |
| Timely, reconciled reads | 864 / 864 | 1,728 / 1,728 |
| Median read latency | 549 ms | 1,675 ms |
| p95 read latency | 1,553 ms | 5,939 ms |
| Maximum read latency | 1,745 ms | 6,794 ms |
| Simulation updates | 563 | 101 |
| Updates per wall second | 3.13 | 0.56 |
| Simulated elapsed time | 179,928 ms | 179,221 ms |
| Active-window peak service RSS | 5,690,007,552 B | 9,197,785,088 B |
| Whole-attempt sampled peak service RSS | 5,911,625,728 B | 11,816,038,400 B |
| Retained log sampled near pause | 1,828,698,109 B | 2,149,636,984 B |
| Subscription body bytes | 131,878,965 B | 213,244,696 B |
| Audit events in final export | 143,146 | 177,293 |
| Living actors at the end | 72 | 144 |
| Pause acknowledgement | 140 ms | 20 ms |
| Resource/read trial | Pass | **Fail: RSS guard during finalization** |
| Sustained 20 Hz capacity target | Fail | Fail |

The 144-actor attempt completed the full active window and every read, then
crossed the declared 11 GiB RSS guard during post-pause finalization. The guard
sample was 11,816,038,400 bytes, just above the 11,811,160,064-byte threshold.
Its overall result is a failure even though protocol reconciliation and cleanup
passed. It was not restarted to finish the trial or hide the peak. Neither run
had a service OOM or service swap. Both have zero engine errors and zero dropped
subscription samples. All measured actors survived; no population reduction
explains the lower update cadence.

The clock used approximately 141.4 / 157.7 seconds of WASM execution for 72 / 144
actors, versus 7.0 / 14.8 seconds for all participant commands. These are nearest
one-second metric deltas, not per-phase profiles. The global clock is the largest
measured execution cost, but these counters do not separate hydration, gameplay
phases and serialization within it. Simulation elapsed time roughly kept pace
because the existing kernel consumes actual elapsed milliseconds; physical
updates became much less frequent. Timely reads therefore do not establish
responsive gameplay.

RSS continued growing during both active windows. For 144 actors it rose from
about 0.59 GB at resume to 9.20 GB near pause; finalization added further growth.
This observation does not establish whether memory would eventually plateau or
whether the cause is a leak. Likewise, log size fluctuates as retained storage
changes; it is not a monotonic measure of cumulative writes. The initial
36-actor evidence used only 60 seconds, so differences from that run combine
population, density, elapsed duration and resulting world history.

Evidence: `output/native-scale/pop72-180s-v2/` and `pop144-180s/`, with frozen
measurement scripts/probe/module hashes in `artifacts-v2/`, declared fixture
transformations in `fixture72-v2/` and `fixture144-v2/`, and offline strict receipt
reconciliation in `reconciliation-check.json`. The latter also verifies that an
altered client receipt cannot pass authority reconciliation. The runner now
performs automatic kernel fixture preflight before creating a service and checks
exact receipt/event matching. These final harness checks were verified offline
against the retained trials; their original artifacts remain unchanged.

Both worlds were authoritatively paused, every grant revoked and all participant
connections disconnected. Both owned services are stopped, with exit 137 after
Podman's stop timeout; this is not graceful shutdown. No existing experiment
archive was modified. The failed initial setup service is also stopped and has
no grants. No model calls were made in any attempt.

## How to remove the global clock scan

The sequence below records the initial post-trial proposal. Subsequent
[official-source research](NATIVE_CLOCK_RESEARCH.md) revises its priority:
profile and compare runtime versions first, separate execution state from history,
then test a hybrid of compact active batches, sparse indexed deadlines and explicit
wakeups. An indexed deadline for every actor is not yet established as optimal.

Official [performance](https://spacetimedb.com/docs/tables/performance/),
[index](https://spacetimedb.com/docs/tables/indexes/) and
[schedule-table](https://spacetimedb.com/docs/tables/schedule-tables/) guidance was
consulted before this analysis. The pinned
[2.1.0 scheduler implementation](https://github.com/clockworklabs/SpacetimeDB/blob/v2.1.0/crates/core/src/host/scheduler.rs)
re-inserts interval work after completion. A configured 50 ms interval therefore
does not guarantee 20 completed updates/s when each update does substantial work.
Increasing timer frequency alone would consume more resources without fixing the
read/write set.

The current kernel already has `action_ready_ms`, `dialogue_ready_ms`, script
wake times and dirty flags. However, the database still hydrates all mutable
components, `step_inner` checks every living actor, and the save boundary reconciles
the run. Splitting that same scan among many reducers would preserve the cost and
could change action ordering.

The initial proposed implementation order was:

1. **Expose the existing phase dependencies.** Separate due-work selection from
   the shared mechanics, preserving the current ordering: activation, ecology and
   infrastructure, actor needs/actions/consequences, lifecycle, then queued speech.
   Differential tests must compare full state, failures and exact causal events.
2. **Persist due work and explicit wakeups.** Index actors and facilities by
   `(run, next_due_ms)`, with dirty actors scheduled immediately. Store last-applied
   simulation time so hunger, hazards, generation and compute quanta accrue
   exactly once even when nothing polls them. Policy changes, movement, resource
   changes, death and applicable law activation must update the dependencies they
   invalidate. Birth needs its own physiological clock, as it does today.
3. **Load and commit only the selected dependencies.** An action can affect a
   target, site, workshop or remote owned facility. Reuse the shared skill/law
   implementation and preserve deterministic actor ordering within each phase.
   Keep one coherent event cursor and explicit transaction rollback. Do not assume
   a fixed sight radius: authored perception laws can alter dependencies.
4. **Split frequently changed state from histories.** Needs, execution cursors and
   due timestamps should not cause serialization of a character's complete memory
   or participant trace. Store append/eviction changes separately, while preserving
   evidence leases and the independent durable audit. This addresses write growth
   as well as clock cost.
5. **Validate cadence and overload behavior.** Once batches fit the time budget,
   compare absolute scheduled deadlines with completion-relative intervals under
   the pinned server. Missed work must have explicit catch-up semantics, not an
   unbounded backlog or silent loss of elapsed time. Verify restart/pause/reconnect,
   simultaneous contested actions, law changes, newborns and lease expiry before
   claiming sustained 20 Hz.

Regional partitioning can follow if one database's serialized workload remains
insufficient. It requires an explicit contract for cross-region movement, effects
and evidence; it is not a transparent configuration change. No such partitioning
or due-work clock has been implemented by these measurement changes.
