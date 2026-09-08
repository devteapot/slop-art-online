# World initialization and prototype limits (42)

2026-09-08. Continues [shared remembered-target sets](SHARED_TARGET_SETS_41.md)
toward the [world vision](WORLD_VISION.md), [simulation vision](SIMULATION_VISION.md)
and [performance contract](PERFORMANCE_CONTRACT.md). Retained: exact creation
parity and cheaper 200-character initialization. Full 2,000-character finalization
still fails the authority's energy budget; no capacity gate is accepted.

## Boundary being changed

The client-world reducer previously created and saved an ordinary World, loaded
it to enable participant state, saved it again, loaded it again to enable client
controllers, and saved a third time. The middle phase scanned and parsed the
newly written audit to recover permitted initial personal evidence. Every stage
ran inside the same authority transaction, so these intermediate storage states
were never useful independently to subscribers.

The shared kernel now composes these phases through `World::new_participant`
and `World::new_client`. Participant creation imports the same permitted initial
event kinds, preserving their order, while retaining the complete original audit
for its single append. Initial seed truth remains outside character evidence.
The authority validates the run name, uniqueness and input size, constructs the
requested initial mode, and publishes the completed World once. All existing
creation reducers and their argument shapes remain available.

The kernel no longer imposes a global 256-character ceiling or a 10,000-tick
horizon ceiling. Society membership is checked against actual initial identities.
Population renewal still obeys the seed's explicit `max_total` and ordinary
requirements, costs, dependence and new-identity rules. That existing seed field
continues to count retained identities, including dead characters; this change
does not silently redefine it as an active-population limit. A positive tick
horizon and overflow-checked conversion to physical time remain required.
Existing finite seeds keep their original stopping and capacity behavior.

Removing those global constants is admission work, not evidence of sustainable
capacity. The full initialization algorithm still uses the complete seed once,
including cross-character reference checks and initial perception. Subsequent
work may need incremental provisioning if representative creation exceeds the
resource envelope. Routine actions do not use this explicit provisioning path.

## Official documentation and access patterns

Consulted the official [SpacetimeDB documentation](https://spacetimedb.com/docs/),
[table performance guidance](https://spacetimedb.com/docs/tables/performance/)
and [indexes](https://spacetimedb.com/docs/tables/indexes/) before designing the
change, followed by the [reducer transaction contract](https://spacetimedb.com/docs/functions/reducers/)
before adding chunked provisioning. The relevant principle is to avoid unnecessary repeated storage work
and keep typed state grouped by access pattern. The SDK remains pinned at 2.1.0;
the control CLI is 2.7.1 and measured service image is 2.10.0 (`b22dfaac6d46`).

Creation remains an atomic explicit operation. Run uniqueness uses its primary
key. The new path writes the same final typed actor, participant, controller,
definition, perception and audit state, with one final delivery publication.
It eliminates the two whole-World reloads, repeated intermediate row writes and
the audit range scan from client-world creation. Row IDs used only for private
storage internals need not be identical; canonical state and ordered audit do.
Existing worlds and routine command/clock storage are unchanged.

Direct creation retains its 2 MiB scenario-text limit, and the service HTTP
request limit still applies independently. Definitions, per-character initial
context and audit size still grow with the authored seed.

## Chunked seed transport

The 2,000-character seed with its authored starting behaviors is 3,451,006 UTF-8
bytes. Passing the kernel's count validation therefore does not make a direct
HTTP request viable. Four additional reducers provide private upload transport:
`sim_begin_world_upload`, `sim_append_world_upload`, `sim_finish_world_upload`
and `sim_cancel_world_upload`. Existing creation reducer signatures are unchanged.

A private header reserves a run ID, records the authenticated owner, mode,
declared byte count, SHA-256 digest and progress. Its unique owner index permits
one pending upload per identity. Private chunks use run/ordinal keys. Limits are
8 MiB per pending seed, 128 KiB per chunk and 128 chunks; these bound transport
storage and row overhead independently of character count. No partial World or
participant state is published. An owner-only view exposes progress without
exposing chunk contents. Interrupted uploads persist for retry or cancellation.

Appending reads the header and writes one chunk plus its updated header. Exact
retries are idempotent; changed retries and out-of-order chunks fail. Finishing
point-reads the declared ordinal range, verifies complete length and digest,
constructs the shared kernel World, then publishes it and removes staging rows
in the same transaction. Validation or commit failure retains the pending upload
and leaves no partial World. Cancellation removes only that owner's staging
rows. A direct creation cannot take over a reserved run ID.

Generated Rust bindings add only the four reducers, progress view and its new
types. Both the shared SDK crate and bridge are compiled against the result.
No existing native actor, controller, evidence, definition or clock table changes.

The reusable [upload helper](../scripts/world_seed_upload.py) preserves UTF-8
boundaries, CRLF bytes and the digest. Supply the selected server, database and
an existing private operator credential file explicitly:

```bash
python3 scripts/world_seed_upload.py --server http://127.0.0.1:3101 \
  --database YOUR_DATABASE --config .local/credentials/bevy-cli.toml \
  --run sim-example-world --mode client --scenario YOUR_SCENARIO.json
```

Rerunning an interrupted upload with identical bytes resumes through idempotent
chunk checks. A failed finalization remains available for diagnosis and explicit
cancellation; this helper never deletes a completed run.

## Resource preparation

The root filesystem had less than the benchmark's 8 GiB reserve. Before any
build or measurement, identical retained executable artifacts were grouped by
size and SHA-256, then deduplicated using XFS's content-checked extent-sharing
operation. Every destination and source was hashed again; paths, file sizes and
modification times were preserved. All 251 operations passed and free space
increased by 1,113,804,800 bytes. The per-file manifest is retained in
`output/realtime/scale-42/validation/artifact-extent-deduplication.json`.
No experiment contents or database volumes were deleted or rewritten.

After the builds and tests finished, 3,096,150,665 bytes of inactive compiler
libraries/macros and completed test executables were unlinked. Runtime paths,
the frozen implementation, all original outputs and database volumes remain
retained. The cleanup manifest is in `validation/`; no cleanup or build overlaps
the authority measurements.

## Correctness and controlled creation

The kernel passes 251 tests with one existing ignored test, including exact
World/audit comparisons between composed initialization and the former persisted
phases across four world families. A 2,000-character kernel case includes an
organization containing every actor and a horizon exceeding eight hours.
Material fabrication creates identity 257 with ordinary costs and dependence,
then respects the seed's declared capacity. The existing test that dead actors
still consume retained capacity also passes. These are correctness checks, not
soak evidence.

All 39 storage tests and 53 authority tests pass. Generated bindings, the shared
SDK crate and bridge compile. The first bridge check encountered the system
temporary-directory quota; using the task's explicit temporary directory passes.
Original failed checks and corrected logs remain in `validation/`.

`initialization-paired-authority/` publishes the frozen previous and current
modules into two databases before setup. Three small warmups verify ordinary,
participant and client creation separately, each with three actors and 16 exact
audit events. Two measured fresh 200-character dense worlds per module then use
alternating execution order. Every complete World and all 40,801 ordered audit
events match in both pairs. Setup, exports and protocol checks are outside the
creation measurements. All worlds remain retained; service memory spans them.

| Two measured 200-character creations | Previous | New | Change |
|---|---:|---:|---:|
| Execution plus queries | 5,979.579 ms | 5,291.471 ms | −11.51% |
| WASM | 5,809.174 ms | 5,120.243 ms | −11.86% |
| HTTP wall time | 5,983.706 ms | 5,296.520 ms | −11.48% |

Both individual creations improve: 2,999.958 → 2,649.574 ms and
2,979.621 → 2,641.897 ms for execution plus queries. This supports the explicit
initialization change; it says nothing about physical cadence or sustained
population. No world clock, model, controller population or observer is active.

Real upload checks use an uploader and outsider distinct from the database
publisher. Both are denied private table access; only the uploader sees progress
and can append, finish or cancel. Checks cover foreign operations, direct-create
reservation conflicts, a second pending upload, wrong order, identical and changed
retries, incomplete finalization, invalid JSON, bad digests and oversized/invalid
manifests. Unicode plus CRLF input produces the exact same World and audit as the
old direct path. Failed finalizations preserve progress without creating a World;
success and cancellation remove staging rows. Five reference worlds also remain
unchanged after upgrading their database to the new module. The service exits 0.

## Full seed: transport passes, authority finalization fails

The resolved `inputs/population-2000.json` extends the retained faction-world
admission seed, assigns all actors to its existing connected arena, places 200
at SF and spreads the remaining 1,800 across valid cells. Existing behavior
templates are assigned to their corresponding initial actor templates. The
manifest records these changes, the original source hash, and its ten-hour
authored horizon. Existing definitions, knowledge, infrastructure, society,
resources and physical rules remain. This seed is for admission; it does not
claim a sustainable population or ten hours of execution.

The [kernel initializer](../simulation/examples/initialize_world.rs) produces
the complete expected initial World and 61,232 ordered events. Its debug-build
construction takes 13,369 ms, excluding parsing and export. The retained World
JSON is 201,084,785 bytes and audit JSONL is 157,142,799 bytes. Those sizes expose
the substantial initial personal-context and evidence cost.

`population-2000-authority/` uses a separate service with the fixed 6 GiB memory
and 3 GiB page-pool limits. All 27 chunks upload. Atomic finalization then returns
HTTP 402, `Module energy budget exhausted`, after 8,548.648 ms. The WASM stack
is serializing `controller::Bootstrap` through `save_participant_state`; the
kernel constructor has completed, but persistence has not. Sampled peak service
RSS is 1,877,929,984 bytes. There is no OOM or forced stop; the service exits 0.
WASM/allocator peaks for this failed transaction were not captured, so RSS alone
does not establish its complete memory footprint.

The original failed attempt, input, implementation, process samples, logs and
database volume remain retained. Separately recorded read-only recovery checks
restart that same database to verify rollback and exact staged bytes, without
retrying finalization, changing its schema or starting a world clock. The first
readback query required a SQL aggregate alias and is retained as a failed check;
the corrected check is separate. These restarts are recovery diagnostics and
cannot support a memory-stability or performance claim.

The corrected readback passes: zero run, native head, actor, mind, participant,
controller, bootstrap and audit rows exist for the failed World. Its one upload
header and all 27 chunks retain the exact 3,451,006 bytes and digest
`a74fc3a13e567f30795c99a0df60d06c8f9bd949abb07f8425a03b5621a7fcf0`.
Both readback stops exit 0. This establishes rollback and recoverable seed data,
not successful world admission.

## Next boundary

Chunked transport and one final save do not make the initialization transaction
bounded enough. Next split shared initialization and storage into resumable
stages, with durable progress and bounded actor/evidence batches. Preserve the
current initialization order and original audit IDs across observations,
knowledge, starting behaviors, personal evidence and controller bootstraps.
Partial state must stay unavailable to ordinary grants, exports and clocks until
one final activation commit. Cancellation must also clean staged state in bounded
work without deleting an existing World.

Do not solve this by increasing the energy budget or reconstructing the complete
World for every small batch. The failed stack identifies bootstrap serialization
as the observed exhaustion point, and the next profile must distinguish kernel
construction, per-actor persistence and final activation. The 2,000-character
authority comparison remains incomplete. The prior live release's 45% missed
clock slots, long-duration gates, client verification and autonomous outcomes
also remain unresolved.
