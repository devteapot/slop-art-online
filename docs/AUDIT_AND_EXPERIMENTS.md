# Audit and experiment contract

Requirements for the [simulation foundation](SIMULATION_VISION.md), maintained as mechanics evolve. The bounded M1 implementation and its acceptance evidence are recorded in [M1 verification](M1_VERIFICATION.md); this contract also applies to later extensions. See [implementation state](CURRENT_STATE.md) and the [work queue](TODO.md).

## One evidence model, two inspection interfaces

Provide Bevy in-game visual observation (primarily browser WASM, with shared native-target code) for the user and structured/queryable access with live traces for LLM-assisted development. An external browser inspector is an additional developer audit surface, not the product observer or human participant interface. Both read the same underlying records, with stable identifiers so a visual event can be retrieved through structured access and vice versa. A minimal observer view can show positions, selected-player state, current intention/activity, and a linked event timeline; rich presentation is later work.

The observer can compare world truth with each player's subjective understanding. This privileged view is not an input to the player's controller. Query permissions and context construction must preserve that boundary, including when a human observer also participates as a character.

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
