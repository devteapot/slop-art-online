# Stack and cadence iteration (26)

2026-09-08. Follow-up to [baseline 25](PERFORMANCE_BASELINE_25.md) and
[the stack review](STACK_PERFORMANCE_REVIEW.md). These are bounded actual-authority
diagnostics, not acceptance of the [performance contract](PERFORMANCE_CONTRACT.md).
The locked 60 Hz, latency, population and client-frame requirements are unchanged.
The 30-minute and eight-hour workloads remain excluded from this iteration.

## Changes and authority boundaries

The live development host now defaults to one-shot owner procedures. Resume checks
`sim_owned_run_ids()` instead of loading the whole owner World. Explicit SQL mode
and historical runner defaults remain available for declared diagnostics. The
original failed browser experiment remains unchanged.

Observer rendering now uses existing canonical typed components: a compact clock
header, actor rows, body support, site rows, scene metadata and event rows. The
normal closed-inspector path does not hydrate a World or load an arbitrary first
actor's mind. Bevy assembles the same presentation from its applied SDK cache.
An open inspector retains the existing rich selected-person projection; participant
rendering retains the existing personally scoped projection. The compatibility
render view remains available to older clients and explicit parity checks.

The optional personal combat view filters already-authorized durable experiences.
It creates no witnesses, memories or reactions. The reference controller continues
to consume the full ordered trace; other clients may choose their own behavior and
memory organization. Current target validation now checks the authoritative
visibility law independently of a 16-entry memory tail, while retaining the
existing ability to express intents about remembered targets. Physical range,
resource costs, interruptions and permanent death still determine actual effects.

Targeted native transactions point-read the named target's body, arena support
and numerical facts used by visibility laws, including adjacent cells. They do
not hydrate the target's history or change the actor-scoped write set. Custom-law
and full-kernel differential checks cover this dependency extension.

World construction no longer clones the complete initial event history for each
seeded decision. The unfinished World is discarded on any initialization error;
the constructor uses the same decision kernel within that existing atomic
boundary. Dynamic behavior installation retains its normal transactional wrapper.
State and event parity checks compare both installation paths.

## SpacetimeDB design basis

The implementation was checked against official
[views](https://spacetimedb.com/docs/functions/views/),
[subscriptions](https://spacetimedb.com/docs/clients/subscriptions/),
[indexes](https://spacetimedb.com/docs/tables/indexes/),
[performance guidance](https://spacetimedb.com/docs/tables/performance/),
[procedures](https://spacetimedb.com/docs/functions/procedures/),
[scheduled tables](https://spacetimedb.com/docs/tables/schedule-tables/) and
[event tables](https://spacetimedb.com/docs/tables/event-tables/).
The module and client SDK remain pinned to 2.1.0; the measured standalone service
is 2.10.0. Bindings were regenerated with CLI 2.1.0; publication/control uses 2.7.1.

Procedural views still reevaluate their declared read dependencies. Returning
typed rows removes World reconstruction and repeated whole-scene JSON transport;
it does not turn the observer's run-index scan into incremental query execution.
The pinned runtime's previously measured broad RawQuery invalidation remains a
reason to verify query-builder behavior before changing these access paths.

| Path | Reads and index | Writes / frequency | Delivery and retention |
| --- | --- | --- | --- |
| Host resume | Authenticated owner's run metadata, owner index | None, once per resume | Sorted owned run IDs; no live World view |
| Observer header | Sender grant, run render clock, optional inspector selection | None; physical clock/control changes | Small current header; explicit inspection still costs a rich projection |
| Observer actors / sites | Sender grant, canonical run indexes | Views write no game state; physical changes trigger evaluation | Incremental row deltas to authorized observers |
| Observer bodies / scene | Sender grant, support run index, initial-definition version, archive run index | None; support/configuration/archive changes | No per-frame map or all-player JSON replacement |
| Combat feed | Sender grant, personal `(run, actor)` experience index | None; personal experience changes | Combat subset of the latest 256 general experiences; no independent cursor acknowledgement |
| Target validation | Own scoped state plus explicit target primary keys | Existing actor-scoped command commit | No target-history publication or new memory copying |
| Exact Hz scheduler | Run deadline and rate primary keys | One rate row and one pending scheduled wake per run | No client subscription or new retained tick history |

Every observer component view verifies observer access on the authority. A spatial
or SQL filter is not its permission check. Combat data comes from the participant
trace, never the developer audit. Reconnect replays the retained combat subset;
clients deduplicate personal cursors and use the participant head to detect
retention gaps. A filtered stream must not be passed to the reference controller's
contiguous-cursor ingestion routine.

The exact-rate control uses an absolute microsecond grid:
`deadline(slot) = epoch + floor(slot * 1_000_000 / hz)`. A late callback advances
once using real elapsed time, records missed slots and arms the first future slot.
It does not replay an unbounded backlog. Pause/reconfiguration establishes a new
grid. Legacy integer-millisecond operation remains supported. Tests cover exact
30/60 Hz phase through eight hours, exact boundaries and long outages; these are
scheduler arithmetic tests, not an eight-hour runtime trial.

## Workload and reproducibility

Artifacts are under `output/realtime/stack-26/`. Each authority trial freezes its
source, WASM modules, probe and hashes. Browser trials additionally freeze the host
binary and browser distribution, Chrome arguments, initial/final screenshots,
console/errors and timestamped rAF gaps. Earlier agent-browser console captures
include its accumulated prior-session messages; the cached pair explicitly clears
that buffer on opening the new page. Final screenshots occur after driver shutdown
and can show the expected disconnected/host SQL error status. A paired 30 Hz run replays its 60 Hz run's
frozen authority/probe implementation.

Each browser comparison uses the same 216-character mixed scenario, 215 reference
controllers, one SDK human input client, one real Bevy observer, normal human and
observer subscriptions, and 60 seconds on loopback. Nine occupied cells initially
hold 6–48 characters each. The observer's world/session panel is open and its
inspector is closed. Automated input is approximately two actions per second,
including movement, eating and rest; seed policies retain their original ordinary
activities. There are no inference calls. Equal configuration does not imply an
identical asynchronous execution trace.

The host is the same Ryzen AI MAX+ 395, 16 physical/32 logical cores, Radeon 8060S
and roughly 62 GiB RAM used in baseline 25. Each isolated database service has a
6 GiB memory cap and 3 GiB page-pool bound. Backend vCPUs are not reserved; the
browser and load generation share the host. This does not certify the contract's
16-vCPU/64-GB envelope or minimum client hardware. The browser uses Chromium 151,
1440×757 CSS pixels and hardware WebGL2 through ANGLE/Vulkan/RADV.

Exports occur after pausing. Resource samples include enrollment for peak RSS and
use declared active windows for CPU and metric deltas. View times are accumulated
timings, not exclusive CPU attribution. Wire counters are actual WebSocket byte
sums; application JSON lengths are a different measurement. Clock counters are
captured after cleanup and are labeled accordingly. rAF gaps are callback timing,
not GPU presentation or input-to-photon measurements.

## First comparison: corrected host, compatibility rendering

The causal `browser-startup-16ms` minute uses the earlier 16 ms clock to isolate
the host fix. No `sim_run` view activation remains. All 107 inputs have callbacks
and terminal outcomes, and pause/export succeeds. It records 2,571 deadline wakes
and 1,179 missed slots. The original browser minute had only two physical updates
and failed pause acknowledgements. Repairing startup removes that severe failure
but does not establish acceptable real-time performance.

| Metric | Exact 30 Hz | Exact 60 Hz |
| --- | ---: | ---: |
| Deadline wakes / missed slots | 1,389 / 410 | 2,476 / 1,131 |
| Missed fraction of recorded slots | 22.8% | 31.4% |
| Input completion p95 / p99 | 208 / 403 ms | 252 / 401 ms |
| Inputs / callbacks / rejected | 107 / 107 / 0 | 107 / 107 / 1 |
| World CPU during sampled active window | 43.23 s | 50.41 s |
| World outgoing WebSocket bytes | 129.16 MB | 175.40 MB |
| Render-snapshot accumulated view time | 7.35 s | 12.67 s |
| rAF average / p99 gap | 59.47 Hz / 16.8 ms | 58.42 Hz / 33.3 ms |

These are `browser-30hz` and `browser-60hz`. The 60 Hz rejection is retained as
a missing terminal outcome, not dropped from the workload. Rest has a designed
duration; per-skill movement/outcome distributions are in `baseline-analysis.json`.
Thirty Hz reduces some work, but neither rate passes the quality limits. The
render-view cost motivates the component iteration.

## Component comparison and combat follow-up

The first typed-delivery pair (`components-60hz-b`, `components-30hz-b`) reduced
render-view work and wire traffic but regressed browser callback cadence. The
client rebuilt every presentation component whenever any subscribed component or
header changed. Repeatedly projecting unchanged sites and scene data erased part
of the server-side benefit. The follow-up caches presentation by applied SDK table
changes, updates the snapshot in place and preserves unchanged arrays. It still
projects all actor rows when the actor component changes; this is not a complete
per-entity Bevy/ECS migration.

| Metric, first typed pair | Exact 30 Hz | Exact 60 Hz |
| --- | ---: | ---: |
| Recorded missed slots | 21.1% | 28.3% |
| Input callback p95 / p99 | 221 / 324 ms | 264 / 310 ms |
| Movement terminal outcome p95 / p99 | 351 / 570 ms | 402 / 519 ms |
| Render-view accumulated time | 3.79 s | 6.41 s |
| World outgoing WebSocket bytes | 107.39 MB | 137.12 MB |
| rAF average / p99 gap | 55.12 Hz / 33.4 ms | 49.13 Hz / 33.4 ms |

Caching alone (`cached-30hz`, `cached-60hz`) recovered browser averages to
57.42 / 52.88 Hz respectively, but still regressed against compatibility rendering.
Actual 216-character post-pause checks passed initial/unchanged cache equality,
open-inspector transitions, compatibility parity, reconnect and revoked access.

A further client pass retains the closed-inspector navigation UI instead of
recreating every entity for physical snapshot changes. Its displayed clock text
updates independently; changes to navigation content still rebuild that UI, and
the open rich inspector retains its existing full update path. Terrain compares
existing state before allocating replacement geometry inputs. Actor interpolation
and physical state delivery remain at their existing per-frame/application rates.
Both final runs exercise opening and closing the browser inspector before the
closed-inspector measurement window.

The final runs are `retained-ui-30hz` and `retained-ui-60hz`. Their authority,
controller module and probe hashes match the cached pair; the rendering change
is in Bevy. Each paired workload still has 216 characters, 215 reference
controllers, one automated SDK human and one real Bevy observer for one minute.

| Final browser comparison | Exact 30 Hz | Exact 60 Hz |
| --- | ---: | ---: |
| rAF average / p99 gap | 59.99 Hz / 16.8 ms | 60.00 Hz / 16.8 ms |
| Maximum rAF gap | 33.3 ms | 16.8 ms |
| Deadline wakes / missed slots | 1,408 / 392 | 2,529 / 1,071 |
| Missed fraction of recorded slots | 21.8% | 29.8% |
| Input callback p95 / p99 | 214 / 336 ms | 241 / 372 ms |
| Movement terminal outcome p95 / p99 | 400 / 516 ms | 414 / 525 ms |
| Inputs / callbacks / rejected | 107 / 107 / 0 | 107 / 107 / 1 |
| Render-view accumulated time | 3.71 s | 6.42 s |
| World outgoing WebSocket bytes | 105.55 MB | 135.87 MB |
| World sampled active CPU | 39.08 s | 42.99 s |
| Backend CPU, world + controller + relay | 85.51 s | 89.05 s |
| World / controller / relay peak RSS | 1.17 / 0.78 / 0.40 GB | 1.18 / 0.77 / 0.40 GB |
| Deadline execution plus queries p95 histogram bucket | 50–100 ms | 25–50 ms |
| Deadline execution plus queries p99 histogram bucket | 100–250 ms | 100–250 ms |

Compared with the corrected-host compatibility pair, accumulated render-view work
falls 49.4% at 30 Hz and 49.3% at 60 Hz; outgoing world wire bytes fall 18.3% and
22.5%. World sampled CPU falls 9.6% and 14.7%. These are observed finite-run
comparisons on an unreserved host, not isolated attribution or steady-state
capacity estimates. Both new rates recover approximately 60 Hz browser callback
cadence. That does not establish GPU presentation, input-to-photon or the stricter
long-duration client-frame contract.

The 60 Hz input `raw-input-104` receives a `stale action revision` rejection and
has no terminal action outcome. It remains in the counts and artifacts. The 30 Hz
run records all 107 terminal outcomes. Neither callback nor movement completion
latency passes the locked quality limits. No `sim_run` owner view is activated in
either final timed window. Browser exception captures are empty; actual rich
inspection, component/cache parity, reconnect and revoked access checks pass.

Retained data also grows substantially during these minutes:

| Nearest sampled active-window change | Exact 30 Hz | Exact 60 Hz |
| --- | ---: | ---: |
| World retained WAL | +459.97 MB | +482.84 MB |
| Controller retained WAL | +957.98 MB | +695.71 MB |
| World table rows | +48,394 | +51,505 |
| Controller table rows | +108,121 | +106,943 |

These are retained-log and table-count changes, including durable evidence and
controller journals, not cumulative write throughput. The asynchronous controller
traces differ despite equal configuration. These short windows establish neither
bounded retention nor a valid eight-hour extrapolation. Per-service allocator,
page-pool and WASM peaks, table breakdowns and exact sample boundaries are retained
in each `stack-analysis.json`; `comparison.jsonl` contains the aggregate comparison.

The constructor fix enables both fresh 200-character trials to commit and enroll
all controllers. `combat-200-fixed-60hz` and `combat-200-fixed-30hz` replay the same
frozen implementation and catalog scenario, with 200 characters in one cell, 200
reference controllers and one SDK compatibility observer. The requested active
window is ten seconds, with no human input or inference. Timing through pause and
client shutdown is 16.806 / 17.718 seconds respectively; it is not ten seconds of
healthy real-time execution.

| Combat burst | Exact 30 Hz | Exact 60 Hz |
| --- | ---: | ---: |
| Final physical time / total updates | 8,934 ms / 10 | 8,920 ms / 10 |
| Deadline wakes / missed slots | 7 / 261 | 7 / 528 |
| Attack attempts / damage events | 500 / 500 | 500 / 500 |
| Permanent deaths / remaining alive | 100 / 100 | 100 / 100 |
| Deadline execution plus queries p95 histogram bucket | 500–1,000 ms | 500–1,000 ms |
| World sampled active CPU | 9.48 s | 9.47 s |
| World peak RSS, including enrollment | 1.36 GB | 1.38 GB |
| World WASM peak / retained WAL near pause | 160.10 MB / 150.26 MB | 160.10 MB / 150.26 MB |

World table counts near pause total 49,259 rows in each fresh service. These
retention and memory figures are finite-trial measurements; they do not establish
long-term bounded growth. WASM, service allocator memory and retained WAL are
different quantities, and retained WAL is not cumulative writes. Both run-level
counters include cleanup. The 60 Hz sampled deadline transaction
mean is 714 ms, and shared world maintenance averages 808 ms. These dominate the
16.7/33.3 ms budgets. Reducing the configured rate cannot repair these transaction
costs. All deaths occur near the final 8.9-second physical update; the trials do
not maintain 200 living combatants. Scoped combat-feed exact equality, reconnect,
ungranted/observer denial and revocation checks pass for all 200 participants in
both trials after pause. Both database services stop with exit code zero.

## Design decision and remaining work

Keep the startup fix, scoped typed delivery, presentation caching and separation
of current visibility from remembered history. Keep 60 Hz as the product target;
30 Hz is a measured diagnostic option, not an accepted replacement. Neither rate
has demonstrated the locked latency, client-frame or dense-combat quality.

The next authority work should split/measurably reduce large active-set physical
transactions and shared maintenance, while retaining one shared rules kernel and
exact causal traces. Remaining participant and open-inspector World projection,
observer run-index view scans and recent-audit event reads also warrant measured
replacement. On the client, use per-entity SDK changes in Bevy instead of rebuilding
all actor presentation and the open inspector for each snapshot. Exact ingress-to-commit,
input-to-photon, higher-refresh behavior, minimum client hardware, remote RTT on
the new paths, 2,000-character admission and the deferred long-duration gates
remain unverified. No short-run result changes those acceptance requirements.

## Correctness and retained failures

Simulation checks currently pass 235 tests with one opt-in microbenchmark ignored;
the authority module passes 31 tests. Bridge library checks pass 37 tests and the
development host passes 14. Rust client/bridge checks and the Bevy browser build
pass. Actual 12- and 200-character combat checks verify scoped combat delivery and exact
retained-row equality, reconnect and denied access. Actual component subscriptions
match the compatibility renderer in the 12- and 216-character worlds for participant,
closed/open observer inspection and reconnect; revocation clears observer rows.
The 216-character cache checks cover initial and unchanged state plus inspector
transitions. Both final Bevy runs visually verify opening/closing the inspector;
client checks and the final browser build pass, with no captured browser exceptions.

The first 200-character retry (`combat-200-60hz`) still exhausted constructor fuel
after the perception fix. Its stack trace identifies repeated World/event cloning
during seed installation. No World committed; the failed pause cleanup's missing-run
error and service shutdown records remain preserved.

The first component browser launch (`components-60hz`) failed because Chromium's
TMPDIR-derived Unix socket path exceeded the platform limit. The original wrapper
then incorrectly released its start gate during cleanup, producing an SDK-only
minute. `workload-caveats.json` excludes it from browser comparisons. The wrapper
now uses a short temporary path and a pre-start cancellation marker, and records
browser success/failure separately. Original evidence is unchanged.
