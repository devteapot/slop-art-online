# Resumable world initialization (43)

This replaces the all-at-once persistence boundary that exhausted reducer fuel
for the full 2,000-character seed in [iteration 42](WORLD_INITIALIZATION_SCALING_42.md).
It does not change perception, personal evidence, habits, controller authority,
or physical rules. Initialization admission is separate from the locked
[performance and population acceptance gates](PERFORMANCE_CONTRACT.md).

## Design and official documentation

Before selecting the transaction boundary, consulted the official
[SpacetimeDB documentation](https://spacetimedb.com/docs/),
[reducer transaction guidance](https://spacetimedb.com/docs/functions/reducers/),
and [indexes](https://spacetimedb.com/docs/tables/indexes/).
The implementation uses the pinned Rust SDK 2.1.0, generation CLI 2.1.0,
control CLI 2.7.1, and the existing service image `b22dfaac6d46`.

A reducer failure rolls back that batch's state, audit, and progress together.
Earlier completed batches stay durable. The private upload reserves the run;
`sim_run_store` remains absent until activation. Existing owner checks reject
exports, grants, clock configuration, and gameplay against an unfinished run.
Private component and delivery tables remain inaccessible to ordinary clients.
The caller sees only its own upload and build progress through authenticated
views. No timer or audit archive job is armed for an unfinished build.

The shared kernel exposes unpublished construction and ordered batches. Ordinary
`World::new` runs those same batches to completion. Observations follow the
original player-vector order; knowledge and habits follow their original ordered
actor maps. Initialization evidence retains its global event IDs and ordering.
The cursor lives outside `World`, so active-world serialization is unchanged.

A private `sim_world_build` row records the owner, phase, ordinal, step, and
serialized kernel progress. A separate private `sim_world_build_event` table
holds only references to the three safe initial-event kinds used by the original
participant constructor. Bodies remain in the canonical audit. Import uses
explicit audit-ID point reads; it does not rely on database iterator ordering.
Neither the omniscient initialization event nor arbitrary audit history becomes
a character's knowledge.

Each batch performs at most 16 actors in an actor phase or 128 audit IDs during
personal evidence import. The phases are:

1. Shared kernel observations, knowledge validation and seeding, then habits.
2. Enable participant mode without replaying the initialization payload.
3. Import the original safe personal evidence in audit order.
4. Construct client bootstraps in authored actor order, when requested.
5. Prepare private delivery rows in actor batches.
6. Atomically activate by creating the run row at the activation timestamp.

The cold native loader reads physical and hot metadata for the run, plus global
rules and seed definitions. Histories and bootstraps remain deferred until used;
unchanged snapshots avoid repeated serialization. This is still a whole-run
metadata read/reconciliation per initialization batch, explicitly limited to
provisioning. It is not a new pattern for local gameplay. Validation of the seed,
lifecycle and infrastructure setup, and base-row persistence remain one initial
transaction; bounded transport alone does not guarantee arbitrary seeds fit.

The final activation does not serialize the complete world again. Its row
establishes the world wall-clock origin, avoiding elapsed-time debt from the
provisioning interval. A failed or interrupted batch leaves an owned, unpublished
build. Passing an already committed `expected_step` is an acknowledgement retry;
a future step is rejected. A cancelling build cannot advance or activate.

## API and cancellation

The existing atomic upload finalizer remains available for small worlds. To use
staged construction, complete the same private seed upload, call
`sim_prepare_world_build(run)`, read `sim_my_world_build`, and call
`sim_advance_world_build(run, expected_step)` until its phase is `ready`.
Then call `sim_finish_world_upload(run)` to activate.

The [upload helper](../scripts/world_seed_upload.py) exposes this as `--staged`.
Rerunning with identical bytes resumes a pending upload/build. It does not retry
failed transactions silently or cancel partial work automatically. The existing
8 MiB seed, 128 KiB chunk, 128-chunk and one-pending-upload-per-owner bounds remain.

`sim_cancel_world_upload(run)` also cancels a staged build. Repeat until the
owner's upload view is empty. Each call first locks the build in cancellation,
then removes at most 128 event references, audit rows, or native component rows
in that pass. Removing actor addressing rows also removes their bounded initial
delivery headers. Constant-sized run/definition headers are removed at the end.
Only initialization can create these rows; no gameplay receipts or leases can
accumulate before admission. The reservation survives until cleanup finishes.
All evidence-body identities are run-scoped; deleting unpublished rows cannot
remove another world's data. Completed worlds cannot enter this path.

## Validation and retained artifacts

The frozen [implementation](../output/realtime/scale-43/implementation/manifest.json)
records source hashes and the release module. Tests and build logs are retained
under [validation](../output/realtime/scale-43/validation/unit-tests.log).

- 253 kernel tests pass, with one existing ignored test. New checks serialize and
  recover state and progress between differently sized batches in all three
  modes, preserving complete world JSON and ordered audits. Invalid batches and
  already-started worlds cannot advance initialization.
- 39 storage and 53 authority tests pass. Generated bindings and bridge compile.
- The [actual authority fixture](../output/realtime/scale-43/staged-initialization-authority/result.json)
  compares frozen 42 with staged 43 in world, participant, and client modes.
  All three 36-character worlds and all 472 audit events per world match exactly.
- Twenty rejected access/sequence operations cover private tables, foreign
  mutations, premature export/grant/finalization, future steps, and cancelled
  builds. Repeating committed steps preserves progress and final exact results.
- Cancellation from kernel, experience, publication, and ready phases removes
  every staged table row checked by the fixture. A completed prior world remains
  exact after module upgrade. The isolated service exits normally with code 0.

## Full 2,000-character authority result

The exact 3,451,006-byte [seed from 42](../output/realtime/scale-42/inputs/population-2000.json)
contains 2,000 characters, 200 colocated and 1,800 distributed, with the original
habits and world content retained. All 27 uploaded chunks survive an actual
42-to-43 upgrade before construction begins. The authority activates the world;
its [complete export and all 61,232 audit events](../output/realtime/scale-43/population-2000-staged-authority/canonical-verification.json)
match the frozen 42 shared-kernel output **byte for byte**.

The [batch summary](../output/realtime/scale-43/population-2000-staged-authority/build-summary.json)
records 995 transactions over 274.223 seconds, including progress queries between
calls. Aggregate reducer-plus-query execution is 199.016 seconds and WASM runtime
198.153 seconds. The largest individual batch HTTP time is 326.321 ms. Base-state
preparation takes 288.137 ms over HTTP (286.568 ms reducer-plus-query); final
activation takes 2.255 ms over HTTP (0.641 ms reducer-plus-query). These are
provisioning measurements, not responsive gameplay timings or a throughput gain
against the earlier failed all-at-once operation.

| Phase | Batches | Mean HTTP time | Maximum HTTP time |
| --- | ---: | ---: | ---: |
| Kernel initialization | 265 | 212.35 ms | 326.32 ms |
| Participant setup | 1 | 215.10 ms | 215.10 ms |
| Personal evidence import | 479 | 211.55 ms | 221.76 ms |
| Controller bootstraps | 125 | 198.82 ms | 232.17 ms |
| Private delivery preparation | 125 | 141.77 ms | 152.96 ms |

The initialized database has 2,000 actors, participants, controllers, bootstraps,
and trace heads; 3,224 trace pages and 3,927 evidence bodies with corresponding
retention rows. Process sampling every 50 ms during batches reports a maximum
RSS of 1,444,761,600 bytes and zero swap. This is one isolated service/database,
including retained service allocator/pool memory and the module upgrade; it is
not a separable world's memory requirement. WASM and allocator snapshots are
retained as [resource points](../output/realtime/scale-43/population-2000-staged-authority/resource-points.json),
not claimed as continuous peaks. The retained message-log gauge grows from
16,099,395 to 509,583,111 bytes across the batch interval; this is retained log
size, not cumulative writes. No active clock, observer, model work or live
controller population ran. Startup, transport, export and later command checks
are outside the batch timing interval.

The original diagnostic ends with a retained [client encoding failure](../output/realtime/scale-43/population-2000-staged-authority/failure.json)
after exact admission verification: a raw HTTP identity string is not the
Identity SATS tuple. A separate diagnostic restarts the preserved service and
uses the established CLI Identity conversion. The actor-2000 grant commits in
1,483.333 ms reducer-plus-query time, and a scoped rest-action request is
[accepted and installed](../output/realtime/scale-43/population-2000-command-check/command-verification.json)
in 71.706 ms. This is one sample, not a percentile or physical rest outcome.
A validly encoded premature grant is rejected with `run not found`; this
corrects the first small fixture's syntactic rather than semantic grant rejection.

That follow-up retains a separate [invalid SQL literal failure](../output/realtime/scale-43/population-2000-command-check/failure.json)
after the successful command and denial checks. The [corrected readback](../output/realtime/scale-43/population-2000-command-recovery/result.json)
verifies the grant and accepted receipt survive restart, removes the temporary
unpublished test build, and confirms all 2,000 actors remain at tick/time zero.
Neither diagnostic repeats initialization, resets data, retries the action, or
claims uninterrupted stability. All service stops are normal, exit code 0.
Original failures and artifacts remain intact.

The [actual helper CLI check](../output/realtime/scale-43/staged-upload-cli-authority/result.json)
resumes an already partially initialized world using `--staged`, activates it,
and matches the old constructor's complete world and audit. The generated six
interface files are produced by the pinned generator; none is handwritten.

## Remaining gate

Full-seed authority admission is now verified. The 995 batches still repeatedly
read/reconcile the world's hot metadata, and grant/command costs show additional
work on access and local transaction dependencies is necessary. Provisioning
transactions can also contend with active work in the same database; this trial
did not test that concurrent workload.

The prior release's 45% missed clock slots remains the latest live cadence
failure. No new movement/combat cadence, model-workload access, sustainable
population, client frame rate, 216-character 30-minute gate, or 2,000-character
eight-hour gate is established here. Next address access/command dependencies,
action execution/save bursts and world maintenance before sustained acceptance.
