# Native clock research and revised decision

Research date: 2026-09-07. This revises the proposed implementation order in
[Native scale trials](NATIVE_SCALE_TRIALS.md). It changes no runtime, schema,
dependency version or experiment result.

Follow-up: [the first implementation pass](NATIVE_CLOCK_IMPLEMENTATION.md) records
the runtime comparison, phase measurements, history separation and script-cache
optimization. Indexed active/due/dirty clock execution remains future work.

## Decision

The earlier proposal is directionally sound, but an indexed deadline for every
actor is not established as optimal. Prefer a **hybrid clock**: compact batches for
continuously active mechanics, indexed deadlines for sparse delayed work, and
explicit wakeups for invalidated dependencies. Split frequently changing execution
state from histories before deciding how much work to put behind deadline indexes.

First profile the current boundary and compare server versions in isolation.
Official versioned source exposes a material alternative explanation for the
memory growth: the old runtime's instance pool. Application work remains expensive,
but attributing all service memory to world history would be premature.

## What the existing evidence establishes

The 72/144-actor trials ran for 180 wall seconds on the same 48-by-36 map, with one
persistent SDK connection per actor and simultaneous reads every 15 seconds.
They completed 3.13/0.56 updates per second. Clock WASM execution accounted for
approximately 141.4/157.7 seconds, versus 7.0/14.8 seconds for participant commands.
This identifies the dominant reducer, not its dominant internal phase.

Both population and local density increased; the older 36-actor run was shorter.
These runs therefore do not isolate population complexity, history growth or
connection concurrency. They contain no live model workload or active observer
subscription. The 144-actor trial failed its RSS bound during finalization despite
passing all reads. The full qualifications and immutable evidence locations remain
in [the trial report](NATIVE_SCALE_TRIALS.md).

Read-only inspection of retained final metrics found 73/145 module instances.
The old WASM gauge reported about 205/36 MB, while jemalloc resident memory was
about 1.11/1.24 GB. These are individual final samples, not synchronized peak
attribution, and do not explain the 5.91/11.82 GB whole-attempt RSS peaks.
Derived values are retained in `output/native-clock-research/memory-evidence.json`.
Do not multiply that WASM gauge by instance count: instances need not have equal
memory, and the old metric does not represent their aggregate.

## Official platform findings

The project's measured module/server/SDK baseline is 2.1.0; its control CLI is
separately versioned. Current documentation is useful design guidance but cannot
establish availability in that baseline.

- **Execution and instance pooling changed.** The
  [2.1.0 module host](https://github.com/clockworklabs/SpacetimeDB/blob/v2.1.0/crates/core/src/host/module_host.rs)
  uses a reusable pool that creates an instance when empty and returns healthy
  instances without a size cap or idle trimming. The
  [2.4.0 release](https://github.com/clockworklabs/SpacetimeDB/releases/tag/v2.4.0)
  introduced a dedicated synchronous WASM reducer lane, described in
  [PR 5095](https://github.com/clockworklabs/SpacetimeDB/pull/5095).
  The [2.10.0 host source](https://github.com/clockworklabs/SpacetimeDB/blob/v2.10.0/crates/core/src/host/module_host.rs)
  has one main WASM instance and a separate bounded procedure pool. This supports
  a version comparison; it does not establish how much RSS or execution time our
  workload would save. Procedure concurrency and large exports still matter.
- **The old memory metric is incomplete.**
  [2.5.0](https://github.com/clockworklabs/SpacetimeDB/releases/tag/v2.5.0) changed
  `wasm_memory_bytes` to account for all Wasmtime instances. This is an accounting
  correction, not itself a memory optimization. Raw old/new gauge values are not
  directly comparable.
- **Schedules do not create CPU capacity.** The
  [2.1.0 scheduler](https://github.com/clockworklabs/SpacetimeDB/blob/v2.1.0/crates/core/src/host/scheduler.rs)
  re-inserts interval work relative to completion. A 50 ms interval cannot deliver
  20 completed updates/s when each update takes substantial time. Absolute
  deadlines require explicit lateness and catch-up rules.
- **Access patterns should determine tables and indexes.** Official
  [table performance](https://spacetimedb.com/docs/tables/performance/) and
  [index guidance](https://spacetimedb.com/docs/tables/indexes/) support selective
  reads and compact rows. They do not establish that an index wins when nearly
  every row is due. Every additional index also has maintenance cost.
- **More reducers in one database do not imply parallel simulation.** The official
  [scaling explanation](https://spacetimedb.com/blog/how-does-spacetime-scale)
  describes serialized database execution and regional databases for BitCraft.
  Regional authority is a possible later step, with explicit cross-region
  semantics. Announced future storage/execution features are not available merely
  because they appear in the roadmap.

The latest release checked was 2.10.0, published 2026-09-04. No upgrade was applied.
A comparison must verify module ABI, Rust SDK protocol, views, procedures,
subscriptions, migration and recovery behavior before interpreting performance.

## What the production game example actually does

Clockwork Labs' public BitCraft implementation mixes subsystem timers with narrow
table scans. At commit `a648d1a71ce71b99c3a06919d7a23b661d129c9c`,
[player regeneration](https://github.com/clockworklabs/BitCraftPublic/blob/a648d1a71ce71b99c3a06919d7a23b661d129c9c/BitCraftServer/packages/game/src/agents/player_regen_agent.rs)
scans signed-in players and loads relevant stats,
[growth](https://github.com/clockworklabs/BitCraftPublic/blob/a648d1a71ce71b99c3a06919d7a23b661d129c9c/BitCraftServer/packages/game/src/agents/growth_agent.rs)
scans growth records and checks completion times, and
[NPC AI](https://github.com/clockworklabs/BitCraftPublic/blob/a648d1a71ce71b99c3a06919d7a23b661d129c9c/BitCraftServer/packages/game/src/agents/npc_ai_agent.rs)
checks action timestamps during a periodic scan.

This is evidence that useful SpacetimeDB designs can combine timers and scans.
It is not a benchmark of our mechanics, proof of optimality, or justification for
retaining whole-World hydration.

## Alternatives and affected data paths

| Approach | Reads/writes and frequency | Expected use and limitation |
| --- | --- | --- |
| Existing whole-World clock | All mutable components and reconciliation each update | Correctness reference; work includes unrelated state and growing histories. |
| Compact active batches | Active execution/body rows plus actual targets each physical update | Strong candidate when most selected actors are active; still needs narrow dependency loading. |
| Indexed due work | Range lookup by run/deadline; update deadlines only when changed | Strong candidate for sleeping actors, facility completions and delayed speech; dense due sets may erase the saving. |
| One scheduled reducer per actor | Separate transaction and schedule-row changes per actor wake | May suit isolated rare work; adds transaction overhead and complicates contested action ordering. Not the default. |
| Hybrid clock | Active batch plus due ranges and deduplicated dirty wakeups | Recommended candidate; needs explicit ownership of each mechanic to prevent double execution. |
| Regional databases | Region-local rows and explicit cross-region transfers | Enables parallel authority; significantly changes cross-boundary effects, perception and evidence. Defer until justified. |

Current `SimNativeMind` bundles execution/generation/failure fields with memories,
knowledge and site observations. `SimNativeParticipant` bundles cursors and activity
with experience history. Even a selected actor can therefore require parsing and
rewriting substantial history. Separate small execution/physiology rows from
individually addressable history records, using shared mechanics rather than an
approximate replacement simulator.

For an implementation, define indexes for `(run, actor)` history access and
`(run, next_due_ms)` sparse work, retaining deterministic phase/actor order after
selection. Keep active membership and dirty reasons durable for recovery. Store
one current wakeup per relevant entity/reason, updating it only when needed;
otherwise the scheduler itself can create unbounded retained work or needless
50 ms writes. History append/eviction must preserve evidence leases and durable
audit independently.

Subscriptions should expose only the affected authorized participant or observer
projection, with compact head changes separate from requested history. Measure
view invalidation and resulting bytes as well as row writes. Due queues and private
memories stay authority-private; spatial selection does not enforce permissions.
Use explicit checkpoints for full exports and measure their transient memory.

Lazy elapsed-time accumulation is valid only where it preserves thresholds and
causal ordering. Settle hunger, hazard and compute effects before dependent reads
or actions and at relevant law boundaries. Do not skip intermediate deaths or
resource contention. Preserve birth's physiological clock. Authored perception,
remote ownership and law dependencies prevent assuming a universal local radius.

## Revised implementation and verification order

1. **Attribute cost and compare runtimes.** Profile hydration, cloning, mechanics,
   reconciliation/encoding, view work and export separately. Compare the existing
   2.1.0 baseline with a verified compatible 2.10.0 candidate on isolated copies.
   First try the identical WASM/SDK where supported; record any required changes
   as separate experimental factors. Measure instance counts, aggregate WASM
   memory where valid, service RSS, allocator/pool metrics and table growth.
2. **Split hot state from history.** Remove routine history parsing and rewriting
   from execution updates. Keep the same scheduling algorithm initially so the
   effect can be isolated. Make history retention explicit without deleting the
   historical experiment evidence.
3. **Extract phase dependencies and implement the hybrid candidate.** Preserve
   activation, ecology/infrastructure, actor effects, lifecycle and queued-speech
   ordering. Share the same skills, costs, law checks and physical outcomes.
   Compare compact scanning against indexed selection at different active fractions.
4. **Test causal equivalence before cadence changes.** Differentially compare full
   states, failed attempts, receipts and event order at identical supplied times
   and inputs. Cover simultaneous contested actions, law activation, movement,
   remote facilities, birth/death, lease expiry, pause/restart and reconnect.
   Changing timestep/catch-up semantics requires its own acceptance decision;
   equal seeds alone do not establish equal fresh model inference.
5. **Measure scheduling and sustainable capacity.** Compare completion-relative
   intervals with absolute deadlines only after batches fit the time budget.
   Bound catch-up and report lateness/backlog without silently discarding effects.
   Proceed to regional design only if measured local work cannot meet the target.

Use staged matched comparisons, not one giant matrix: first fixed 72 actors,
180 seconds, identical fixture/history, density, subscriptions and read bursts on
each runtime. Separately compare clock-only, connected-idle, reads-only and
clock-plus-reads to distinguish pool/concurrency effects. Then compare history
splitting and scan/deadline selection with sleeping, mixed and fully active
populations. Vary density independently from population, and repeat promising
variants before longer soak tests. Add live models and observer/export load as
declared separate workloads.

Record reducer execution and queue time, completed cadence and lateness, read
latency/acceptance, rows and bytes read/written, subscription bytes, table/history
growth, WASM/allocator/pool memory and isolated service RSS. Distinguish retained
WAL size from cumulative writes. Keep declared resource stops and original failed
outcomes; no restarts to conceal growth. Thousands of players and sustained 20 Hz
remain targets until these workloads demonstrate them.
