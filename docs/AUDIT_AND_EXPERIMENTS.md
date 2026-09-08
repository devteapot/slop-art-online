# Audit and experiment contract

Work is paused at [script invocation boundary (49)](SCRIPT_BOUNDARY_SCALING_49.md).
Its shared-definition candidate passes 360 focused tests and builds successfully;
candidate performance measurements have not run. Iteration 48 remains the latest
measured normal release, and all performance gates remain open.

The latest [compressed audit digest change (48)](AUDIT_DIGEST_SCALING_48.md)
preserves all exact event strings, complete worlds, leases and private access.
All 102 relevant authority/storage tests pass. Six real archives, 12 independently
verified blocks, mixed-format upgrade and explicit persistence restart pass.
The original checker failure on valid SATS optional encoding and a partial
physical block-sharing failure remain preserved. Identical archive work uses
35.8% less WASM time but 23.3% more wall time; normal combat misses 48.3% of clock
slots versus 45.7% before. Recovery restarts are outside measurements and do not
establish sustained resource acceptance.

[Deferred definitions (45)](DEFERRED_DEFINITION_SCALING_45.md) retain exact
2,000-character world/audit parity and sequential admission timing evidence.
The failed export and both interrupted combat attempts remain preserved.

[Staged initialization (43)](STAGED_WORLD_INITIALIZATION_43.md) preserves exact
2,000-character admission, private staging and recovery evidence.

The [deferred-catalog iteration (34)](DEFERRED_CATALOG_SCALING_34.md) verifies
first-use identity validation, retained failures, scoped immutable reference
reuse and complete export requirements. Actual profiles show zero command and
inspection catalog fetches. Different death waves, greater profile work and
remaining latency failures are retained alongside the improved release result.

The [controller-catalog iteration (33)](CONTROLLER_CATALOG_SCALING_33.md) verifies
content identity, scoped reads, reference retention, exact exports and actual
old/new module world-and-audit parity after upgrade. It preserves a failed setup
and nonzero service shutdown. Completed trials retain worse release cadence and
higher command cost alongside fewer physics catalog reads; phase improvements
do not imply performance acceptance.

The [encoded-evidence iteration (32)](ENCODED_EVIDENCE_SCALING_32.md) checks exact
event JSON, immutable source redaction, separate recipient records and loaded-row
scope. It preserves a disk-guard-aborted trial with its forced probe stop. The
completed comparison and profile retain greater work, worse cadence and higher
aggregate costs alongside cheaper site-perception construction; no acceptance
is inferred from isolated phase improvements.

The [action-admission iteration (31)](ACTION_ADMISSION_SCALING_31.md) compares
complete authority state, event ordering, receipts and clock hints against the
full kernel for narrowed command reads. Actual profiling confirms actor/target
dependencies; live combat, reconstruction, reconnect and access checks pass.
Greater attack counts, CPU/wire increases and permanent-death shrinkage prevent
treating the short comparison as sustained capacity evidence.

The [component-inspection iteration (30)](COMPONENT_INSPECTION_SCALING_30.md)
retains before/after trials using the current client's exact component query set,
with open inspection. Actual component equality, reconnect, access/revocation
and 200 personal combat feeds pass. The separate profile, original failures,
death-driven workload shrinkage and stale-gauge limitations remain explicit;
no sustained-performance claim follows from these ten-second executions.

The [personal-evidence iteration (29)](PERSONAL_EVIDENCE_SCALING_29.md) verifies
snapshot isolation under every metadata edit and compares complete state/events
against full visibility evaluation. Its retained setup failure is distinct from
the actual workload trials; optimized execution still preserves original evidence.

The [action-domain iteration (28)](ACTION_DOMAIN_SCALING_28.md) separates crowded
transaction profiles from quiet updates after deaths. It retains original
intermediate failures, verifies exact witness state/events and scoped combat-feed
recovery, and identifies retention gauges that cannot establish active growth.

The [crowd lifecycle iteration (27)](CROWD_LIFECYCLE_SCALING_27.md) retains the original
and intermediate failed combat runs. It distinguishes unchanged catalog-computation
semantics from the deliberate removal of redundant automatic peer sightings;
actual witness evidence and explicit observation remain separately verified.

The [stack iteration (26)](PERFORMANCE_ITERATION_26.md) adds scoped component
rendering, a personal combat feed and exact 30/60 Hz comparisons. Its bounded
browser and combat trials retain original failures and leave all long-duration
performance gates open.

The [short performance baseline (25)](PERFORMANCE_BASELINE_25.md) records current
contract checks, original failed trials and explicit measurement gaps. It does
not substitute for the deferred 30-minute and eight-hour acceptance workloads.

Requirements for the [simulation foundation](SIMULATION_VISION.md), maintained as mechanics evolve. The bounded M1 implementation and its acceptance evidence are recorded in [M1 verification](M1_VERIFICATION.md); this contract also applies to later extensions. See [implementation state](CURRENT_STATE.md) and the [work queue](TODO.md).

## One evidence model, two inspection interfaces

Provide Bevy in-game visual observation (primarily browser WASM, with shared native-target code) for the user and structured/queryable access with live traces for LLM-assisted development. An external browser inspector is an additional developer audit surface, not the product observer or human participant interface. Both read the same underlying records, with stable identifiers so a visual event can be retrieved through structured access and vice versa. A minimal observer view can show positions, selected-player state, current intention/activity, and a linked event timeline; rich presentation is later work.

The observer can compare world truth with each player's subjective understanding. This privileged view is not an input to the player's controller. Query permissions and context construction must preserve that boundary, including when a human observer also participates as a character.

The [sustained clock archive contract](SUSTAINED_CLOCK.md#lossless-audit-retention)
can move old owner-audit events atomically into private compressed blocks while
retaining their exact JSON, IDs and ordering. Enabled runs require the merged
owner export API; raw audit-table SQL is a recent tail. Bounding that active index
does not bound all durable history or permit restoring lost character knowledge.

## Component experiments

Support independent, deep inspection of a component as well as integrated runs. A focused experiment should invoke the production implementation through its normal contract, with explicit supplied dependencies and state. It should need only the surrounding systems relevant to the question. A skill evaluator can be exercised with selected facts and law definitions; a belief update can be exercised with selected prior beliefs, perceptions and interpretations. Database commit semantics and interactions between components still require integration checks against the real authority.

Build reusable experiment tooling around concrete questions: what changes when a law changes, which evidence caused a belief revision, or where an invocation spends its time. Cases and variants may be authored or generated for the use case. Each experiment should record its question, resolved inputs, component and definition versions, supplied versus live dependencies, relevant before/after state, intermediate decisions or effects, failures and applicable measurements. Use compatible trace identifiers so a case encountered in an integrated run can be isolated and its component findings connected back to that run.

Separate exploration from pass/fail assertions. Generated cases need a stated property or comparison when used as tests; generated expected answers alone do not establish correctness. Keep focused deterministic checks for contracts such as scope, provenance and atomicity, and for reproduced bugs. Avoid accumulating fixed narrative expectations merely to increase test count. Preserve useful generated inputs and failures for later reproduction, and distinguish recorded inputs from fresh model calls using the replay rules below.

This is a tooling direction, not a requirement to build a new framework now. Independent inspection must reuse the actual game components rather than introduce an approximate second simulator.

## Causal record contract

Concrete storage schemas are open. The following information and links are required; records can be multiple linked types rather than one large row.

| Evidence | Required meaning |
|---|---|
| Run and ordering | Run ID, simulation time, stable event IDs, ordering information, and parent/correlation links. Wall time may supplement simulation time. |
| World event | What occurred, participants/locations, validated effects, and the authoritative execution that produced it. |
| Perception | Who perceived what, from which event/source, under what visibility/hearing/attention conditions; omissions or filtering where relevant. |
| Subjective context | Relevant pre-decision beliefs, goals, needs, relationships, emotions, personality, memory and capability context, as snapshots or reconstructible version references. |
| Decision | Intention, selected approach, trigger (including introspection), expected outcome if supplied, relevant context/version links, and controller type. Do not fabricate human rationales. |
| Model exchange | Actual supplied prompts/context, returned output and parsed decision, model/backend identity and available revision, prompt/config versions and sampling settings; errors, retries, and fallbacks. Exclude credentials. |
| Behavior execution | Behavior version, selected branch/node, progress and transitions, completion/failure/interruption, and links to the decision and attempts. |
| Skill attempt | Actor, skill/version, parameters, prerequisites checked, acceptance/rejection reason, start/progress/end, resources and target context. |
| Actual result | Validated effects or lack of effect, affected state, failure/interruption reasons, linked to the attempt. |
| Later changes | Before/after values or reconstructible versions for beliefs, knowledge, relationships, goals, emotions, personality, and memory, linked to perceived experiences and updates. |

Every selected action need not create a fresh LLM call. Routine graph activity still needs enough execution evidence to explain what happened. Record unavailable evidence explicitly; do not infer that an absent effect proves no attempt occurred. Long waits or ongoing skills should have inspectable status without requiring unbounded duplicate records each tick.

Retain concise decision explanations when provided, labeled as **reported explanations**. Do not request or promise hidden model chain-of-thought. A plausible model explanation is not proof of what caused an outcome. World execution and state-transition records establish actual effects; model output establishes what the model returned.

## Historical durability

Character memory may be lossy, revised, or forgotten. Audit history must remain inspectable independently, including after a character dies. Preserve stable references to dead characters and their relevant history; deletion of live state must not destroy the evidence chain.

The five-minute `NpcEventLog` is a current short-term context buffer, not sufficient lasting audit history. Choose explicit retention/export and snapshot policies before declaring the first milestone complete. For that milestone, completed runs and their causal histories must survive process shutdown and live-state cleanup and remain available for comparison until explicitly removed. A chosen retention policy must make gaps visible; it must not silently claim full history after discarding evidence.

## Reusable scenarios and isolated runs

A modest first runner must initialize defined starting environments, run the authoritative SpacetimeDB simulation without the visual client, and launch multiple isolated simulations in parallel. Separate databases are one candidate, not a settled deployment requirement. Isolation includes simulation state, bridge requests/responses, output files, and run configuration. Do not reset a user's ordinary development database to start an experiment.

Scenario definitions should specify initial environment and resources, population and baseline attributes/capabilities, subjective knowledge/beliefs, and run limits. Proposed additional fields include goals, starting relationships, controlled disturbances, clock settings, and expected invariants. Exact format is open. Record the resolved configuration, not just a preset name whose contents can change.

For each run retain:

- Scenario definition/version and resolved initial state, run ID, seed(s), start/stop conditions, and outcome/status.
- Simulation source/build/schema version, skill and behavior versions, prompt and model/config versions, and relevant clock/execution settings.
- Actual external inputs (including human actions or injected scenario events), their ordering/timing, and actual model outputs/decisions, with rejected or failed exchanges.
- The audit record stream and enough snapshots/state to inspect and compare results.

Tooling is part of the mechanic: adding a skill or changing a perception rule must also update scenario initialization, trace semantics, queries, and comparison support as needed. This is not a separate large infrastructure program; begin with local runs, simple durable records, and focused comparisons.

## Fresh experiments versus recorded-decision replay

A **fresh experiment** invokes models again. Reusing the initial seed does not guarantee identical model outputs, scheduling, or outcomes. Compare repeated runs and variants as experiments and retain the actual decisions that occurred.

A **recorded-decision replay** supplies recorded decisions instead of fresh model calls, with recorded external inputs at their original simulation boundaries. Reproducing world outcomes also requires compatible simulation, schema, skill and behavior versions, initial state, RNG state/seed handling, clock and input ordering, and deterministic execution. Verify those assumptions; report the earliest mismatch rather than claiming universal determinism. An incompatible replay should be labeled or rejected explicitly.

For the first milestone, preserve the material needed for replay and document the supported reproducibility limits. A bounded replay check under a pinned compatible setup is a recommended follow-up to the runner, not a requirement for a general replay engine in the first slice. Cross-version replay, a distributed experiment service, and exhaustive determinism guarantees are deferred.

## Acceptance checks

Performance acceptance follows the agreed [performance contract](PERFORMANCE_CONTRACT.md).
Freeze population, local combat load, controller mix, subscriptions, hardware and
network conditions before a run. Separate input acceptance, execution, committed
outcome and delivery; report tail latency, frame pacing, deadline misses and resource
growth. Preserve failed outcomes. Historical update-count improvements cannot pass
the current contract or justify silently relaxing its requirements.

Each check requires inspectable evidence without prescribing one narrative. [M1 verification](M1_VERIFICATION.md) maps these checks to executed tests and retained runs.

| Check | Required evidence |
|---|---|
| Connected cycle | Follow a world event through a player's perception, subjective context, decision, execution, skill attempt, result, and subsequent change. Both interfaces retrieve the same IDs. |
| Failure and interruption | An unavailable resource/target or interruption yields a distinct attempt/result record, not a fabricated success; show how continued activity or reconsideration follows. |
| Imperfect knowledge | Two players can have different or wrong understandings of one situation. Inspect the source of each and confirm the model input does not contain privileged truth. |
| Speech has consequences | Free-form content outside an authored template is emitted, perceived, interpreted, and can change a later choice; a false claim does not directly rewrite world facts. |
| Individual development | Trace differing interpretations or responses to experience and a persistent identity change that influences a later decision. Avoid requiring every run to produce the same divergence. |
| Introspection | Repeated failure or lack of progress can prompt reconsideration without a dramatic external event; compare configured individual propensities and inspect triggers. |
| Mortality and history | A dead character cannot continue acting or respawn. A survivor without evidence can remain unaware. History is still queryable after cleanup and run restart. |
| Multiple runs | Start at least two isolated runs concurrently from reusable scenarios; demonstrate no cross-run state, request, or output mixing. |
| Comparison | Compare a baseline and variant/repeat for rule correctness and behavioral differences, linking aggregates back to events. |
| Reproducibility evidence | Actual model decisions, external inputs, initial state, timing/order, and relevant versions are retained. Fresh calls are labeled stochastic; any supported replay claim names its tested compatibility conditions and limitations. |
| Model failure | Failure/fallback, rejected and stale responses are visible and cannot invent effects. |

Candidate comparison measures include survival and resource use, attempted/successful/interrupted skills, approaches abandoned, belief changes and their sources, communication effects, identity trajectories, and model latency/cost. Use them to explain behavior and assess invariants, not to force cooperation, conflict, or any other preferred story.
