# Simulation roadmap and work queue

Work is paused at [script invocation boundary (49)](SCRIPT_BOUNDARY_SCALING_49.md).
Its shared-definition candidate passes 360 focused tests and builds successfully;
candidate performance measurements have not run. Iteration 48 remains the latest
measured normal release, and all performance gates remain open.

The latest [compressed audit digest change (48)](AUDIT_DIGEST_SCALING_48.md)
reduces WASM cost for identical archive work by 35.8%; wall catch-up takes 23.3%
longer. All 102 relevant tests and actual-authority recovery checks pass. Profiled
archive encoder maximum falls from 85.01 to 37.39 ms; physical execution still
reaches 78.85 ms and audit append 27.72 ms. Next reduce the remaining physical
and maintenance bursts while preserving exact evidence. Normal combat misses
48.3% of clock slots versus 45.7% before, with worse tail latency. Sustained
cadence, population, full model workloads and client gates remain open.

[Deferred definitions (45)](DEFERRED_DEFINITION_SCALING_45.md) retain the
2,000-character local REST admission improvement from 71.51 ms to 1.76 ms.
All disk-guard interruptions remain preserved and excluded from timing claims.

[Staged initialization (43)](STAGED_WORLD_INITIALIZATION_43.md) completes exact
authority admission through private resumable batches and atomic activation.

Earlier [parent lookup experiments (38)](INDEXED_PARENT_SCALING_38.md) rejected
both candidates. The writer retains the [paged trace format (37)](PAGED_TRACE_SCALING_37.md),
which supersedes [typed personal trace indexes (35)](TYPED_TRACE_SCALING_35.md).

The [deferred-catalog iteration (34)](DEFERRED_CATALOG_SCALING_34.md) verifies
zero catalog body fetches during command admission and inspection. Next measure
repeated participant evidence work inside actor execution and saves, and separate
slow maintenance from combat deadlines. Release missed slots improve to 39.3%;
all sustained population, client and complete combat gates remain open.

The [controller-catalog iteration (33)](CONTROLLER_CATALOG_SCALING_33.md) removes
repeated catalog bodies from mutable controller rows, with exact reconstruction
and bounded current-reference retention. Next remove unnecessary catalog loads
from commands/inspection, then address actor/evidence/save bursts and full
maintenance. Release cadence still fails at 52.3% missed slots; sustainable
population and both locked scale gates remain open.

The [encoded-evidence iteration (32)](ENCODED_EVIDENCE_SCALING_32.md) reduces
site-perception construction while preserving distinct recipient evidence.
Release cadence still fails and worsens in the different asynchronous workload.
Next investigate large controller/catalog/trace metadata loads during active
local physics; sharing after loading does not remove storage/ABI costs. Any new
boundary must retain authoritative visibility, atomic effects and reconnectable
personal evidence, with bounded active-data retention.

The [action-admission iteration (31)](ACTION_ADMISSION_SCALING_31.md) removes
unrelated crowd/station reads from finite action start/cancel while preserving
full shared-kernel parity, visibility laws and captured leases. Actual attack
admissions load two bodies. Next investigate physical-update bursts, lifecycle
catalog persistence and shared maintenance; the changed release still misses
46.8% of clock slots and does not sustain its starting population.

The [component-inspection iteration (30)](COMPONENT_INSPECTION_SCALING_30.md)
removes full-world inspection snapshots and shares exact bundled care checks.
The component workload still fails cadence and long-tail limits. Iteration 31
addresses its excessive action-admission crowd reads while preserving target
perception, shared rules and custom-law behavior; sustainable population,
retention and full performance acceptance remain open.

The [personal-evidence iteration (29)](PERSONAL_EVIDENCE_SCALING_29.md) reduces
candidate-record copying and repeated witness-law evaluation. Next, reduce changed
catalog materialization/persistence and broad maintenance dependencies, then verify
representative living populations and the current client delivery path. The locked
population, latency and duration gates remain unchecked.

The [action-domain iteration (28)](ACTION_DOMAIN_SCALING_28.md) reduces repeated
catalog encoding and witness-input construction. Next, reduce changed-catalog
serialization/persistence, candidate-state copying and real witness bursts; retain
exact personal evidence and custom-law behavior. Short-run retention gauges also
need confirmed refresh boundaries before storage-growth claims are possible.

The [crowd lifecycle iteration (27)](CROWD_LIFECYCLE_SCALING_27.md) reduces redundant
care-law evaluation, lifecycle-triggered sight events and candidate-action copying.
Next, reduce repeated
per-character catalog storage/loading, large physical transaction dependencies and
real witness-delivery bursts without losing causality, privacy or personal memory.
The 60 Hz and sustained-population gates remain unchecked.

The [stack iteration (26)](PERFORMANCE_ITERATION_26.md) implements the owner-read fix,
scoped typed observer delivery, exact 30/60 Hz scheduling and a personal combat
view. It preserves [baseline 25](PERFORMANCE_BASELINE_25.md) and its failures.
Next work must reduce deadline transaction tails, global maintenance and remaining
participant/inspection projection costs, then verify client presentation and exact
latency boundaries. Combat startup now succeeds, but crowded battle cadence and
2,000-character admission remain unresolved. Long acceptance runs remain pending;
a completed diagnostic is not a passed performance gate.

The [seven-stage living-world roadmap](WORLD_ROADMAP.md) has completed its bounded implementation pass: [settlement](STAGE_1_EVIDENCE.md), [teaching/archives](STAGE_2_EVIDENCE.md), [population renewal](STAGE_3_EVIDENCE.md), [connected settlements](STAGE_4_EVIDENCE.md), [physical infrastructure/faction seed](STAGE_5_EVIDENCE.md), [numerical research](STAGE_6_EVIDENCE.md) and [scoped/universal laws](STAGE_7_EVIDENCE.md#acceptance-decision-bounded-stage-7-implementation-milestone). [Campaign 028](SOCIETY_BATCH_028.md) supplies completed 36-person integration with the declared persistent/admission/finalization modes, late external access, timely original cleanup and passing final audits. Campaigns 025/026 and earlier fixture failures retain their failed outcomes; 027 remains unlaunched.

Open research objectives include autonomous useful-code transfer and peer use, autonomous law discovery/universal ascension, sustained provisioning, delivered inter-settlement aid, stable migration and useful compute allocation. Scale work must meet the locked [performance contract](PERFORMANCE_CONTRACT.md), including 60 Hz active movement/combat, latency limits, long-term memory/WAL capacity and graceful shutdown. These are not claimed complete by the bounded milestones. The broader work queue below retains its own unchecked requirements and deferred scope.

Current participant iteration: [participant agent runtimes](PARTICIPANT_AGENTS.md) and [ADR 013](adr/013-participant-agent-runtimes.md). Rules `m1-5` use one scoped API for the built-in harness and external MCP runtimes, with independent tree, speech and learning operations. Earlier evidence and legacy runner descriptions below retain their historical scope.

Read the [authoritative vision](SIMULATION_VISION.md) first, then [source-backed gaps](CURRENT_STATE.md) and the [audit/experiment contract](AUDIT_AND_EXPERIMENTS.md). This replaces the former v1 → v2 “COMPLETE” checklist as the active roadmap. Historical migration rationale remains in [ADR 005](adr/005-npc-architecture-v2.md); existing tables and routes are reusable scaffolding, not completion of this milestone.

Reactive-policy follow-up: [runtime contract](REACTIVE_POLICIES.md), [ADR 011](adr/011-persistent-reactive-policies.md), and [current verification](REACTIVE_POLICY_VERIFICATION.md) distinguish implemented persistent trees from live-generation evidence.

Transport follow-up: [Carlid streaming verification](CARLID_STREAMING_VERIFICATION.md) records a completed Luna stream and correct rejection of an overwide generated tree. Transport is repaired; generated policy compliance and adaptive execution remain separate from the completed browser Bevy integration below.

## M1 — Inspectable survival and individual change

The first proof is a small population pursuing basic survival, communicating freely, holding imperfect beliefs, and changing through experience. The implemented slice uses three survivors, food, rest, and danger, with the bounded defaults in [ADR 008](adr/008-m1-authoritative-survival-slice.md). Rich game presentation, large population targets, work/family simulation, and complex society are outside this milestone.

**The headless/developer M1 foundation was accepted on 2026-09-04; browser-hosted Bevy observation and participation are now implemented and verified for the bounded slice.** See the [verification report](M1_VERIFICATION.md) for exact run IDs, acceptance evidence, and model-quality limitations, and the [runbook](M1_RUNBOOK.md) to exercise it. The voxel/3D client is retired. Legacy server reducers remain outside this foundation; M1 runs through the authoritative SpacetimeDB foundation reducers.

The following were implemented in dependency order, iterating through a thin connected cycle early. Audit records and scenario support accompany each mechanic from its first implementation; they are not a cleanup phase.

### 1. Contracts and the first runnable scenario

- [x] Choose the minimal survival scenario and explicit run limits; define baseline identities, capabilities, resources, and initial subjective knowledge.
- [x] Specify common character/controller boundaries and a skill attempt/result lifecycle. Map existing separate code paths to it (G1).
- [x] Specify perception, subjective state, stable causal IDs, model request correlation, and durable audit retention/export (G5, G7, G8).
- [x] Establish a local headless runner against the real SpacetimeDB core, resolved scenario/run manifests, and isolated state/bridge/output destinations (G9). Prove parallel isolation early.

Exit evidence: a defined starting environment can be initialized reproducibly under documented constraints, observed through structured records, and run independently of the Bevy client. This is a prerequisite, not the whole proof.

### 2. Intentions, execution, shared skills, and mortality

- [x] Correct sequence progress/completion and interruption semantics; capture selected behavior, attempts, and actual outcomes (G2).
- [x] Implement the chosen survival, movement/wait/rest, and danger-response skills through common authoritative requirements and effects for either controller (G1).
- [x] Make activity purpose and reconsideration conditions inspectable, including deliberate waiting (G6).
- [x] Implement shared permanent death semantics and history retention, with survivor knowledge gated by perception or later reports (G4, G5).
- [x] Verify capability/rule parity through equivalent human-controller requests and AI-controller requests; a full participation UI is not required for this check.

Exit evidence: valid, rejected, and interrupted attempts are distinguishable; changes match validated outcomes. No character automatically respawns in this milestone's mortality model.

### 3. Subjective experience, free-form communication, and development

- [x] Build explicit perception → interpretation → belief/knowledge/memory links; remove silent proximity-based belief copying as a substitute for communication (G3, G7).
- [x] Support chosen free-form speech and responses from the first integrated slice, tied to intentions and affecting later decisions. Do not make templates a gate (G3).
- [x] Connect relevant needs, motives, goals, personality, emotions, relationships, and subjective knowledge to decision context and behavior (G7).
- [x] Record experience-linked before/after identity changes and demonstrate influence on subsequent choices, including different interpretations across individuals.
- [x] Add failure/progress-driven and self-initiated reconsideration, with individual variation; evaluate candidate trait linkages rather than imposing a universal schedule (G6).
- [x] Validate and correlate returned model decisions; handle unavailable models, stale responses, failure, and fallback as explicit evidence (G8).

Exit evidence: the whole experience → decision → consequences → development loop is visible. Free-form conversation and individual change are required now, not deferred “emergence” extras.

### 4. Integrated inspection and experiment proof

- [x] Deliver a developer audit inspector and structured/queryable live traces using the same records and IDs, including world truth versus player understanding.
- [x] Deliver observer and human participant modes in the existing Bevy client compiled to browser WASM; actual Bevy rendering/input is verified in [the client report](BEVY_BROWSER_CLIENT.md).
- [x] Run multiple isolated scenarios concurrently, retain resolved configurations/versions/seeds/actual LLM exchanges, and inspect completed runs after shutdown/cleanup.
- [x] Compare repeated runs and variants for correctness and behavioral differences, with metrics linked back to evidence rather than a prescribed narrative.
- [x] Retain recorded decisions and external inputs with timing/order and versions; document reproducibility limits separately from fresh stochastic runs. A bounded replay check is a recommended follow-up, not a general replay-engine prerequisite.
- [x] Complete every [audit acceptance check](AUDIT_AND_EXPERIMENTS.md#acceptance-checks) and attach run IDs/artifact references here when marking work complete.

M1 is complete only when the integrated proof passes, not when its component tables exist. Keep illustrative scenes flexible; an experiment need not yield the same story every time.

## Browser foundation client — delivered bounded slice

- [x] Authenticated caller-specific read projection, observer privilege and exclusive human ownership without public private-state tables.
- [x] Actual Bevy WASM world rendering, selection, mind/policy/history panels and shared native-target code.
- [x] Owned human skill and free-form keyboard speech input through the shared authoritative executor, with trace-linked outcomes.
- [x] Real browser observer/participant checks plus separate-identity access tests; live fixture and recorded model evidence distinguished.
- [x] Top-down 2D observation with pan/zoom camera, optional overlays, detached inspection and independent hosted session focus; see [scope and verification](WORLD_OBSERVER.md).
- [ ] Production authenticated role provisioning, broader browser/accessibility/IME coverage, richer scene presentation and multiple human assignments.
- [ ] Demonstrate a fresh generated policy that complies with limits and changes branches meaningfully; transport success is already separate evidence.

See [verification and reproduction](BEVY_BROWSER_CLIENT.md). This is a local development client; the external HTML inspector remains supporting audit tooling.

## Scripted gameplay foundation: next gate

[ADR 016](adr/016-scripted-gameplay-rhai.md) selects Rhai and fixes the engine/gameplay boundary. Introduce this foundation before expanding the action vocabulary or broader world mechanics. This gate supersedes treating scripting as optional later extensibility.

- [x] Select the language using executable native and SpacetimeDB WASM embedding evidence; see [verification](SCRIPTING_VERIFICATION.md).
- [x] Integrate Rhai into the actual simulation with transactional effects, explicit continuation, bounded interpreter calls and scoped host capabilities. [Executed integration](SCRIPTED_GAMEPLAY.md).
- [x] Introduce source/version history and an authoritative registry, next-tick law activation, action/dependency pinning, current-law validation, operator authentication and audit rejection.
- [x] Migrate all seven active foundation skills (including queued speech), world policy formulas and subjective guard evaluation. Keep one execution path with dynamic skill references and current catalog descriptions for controllers.
- [x] Verify composed movement and law changes in a real database, failure/rollback and existing Bevy movement/speech. Retain source/state and reject incompatible old rule versions.
- [x] [Add physical terminal work accounting and exact-source capability policies](STAGE_6_EVIDENCE.md) for bounded participant-authored numerical techniques; ordinary executions remain subject to current costs and law. This is not unrestricted arbitrary-skill authoring.
- [ ] Prove player discovery, authoring and communicated learning of a new technique, with a law change during execution and visible character response. Operator-authored fixtures do not prove this experience.
- [ ] Measure parsing/evaluation, transactional cloning and persistence cost; design history retention and explicit migration before expanding population or content volume.

## Later stages

These are staged growth areas after the foundation; richer presentation can develop alongside broader mechanics rather than waiting for all society or scaling work to finish.

| Stage | Focus | Gate |
|---|---|---|
| M2 — Participation and broader daily life | Build on browser-hosted Bevy observation and human participation; extend reusable skills toward work, trade, and richer relationships as evidence supports them. | Preserve shared rules, subjective boundaries, and M1 audit/scenario checks. |
| M3 — Society and scale | Explore cooperation, conflict, economy and social structures; optimize measured bottlenecks, model budgets, and populations. | Explain individual and collective outcomes with causal history; maintain tooling as mechanics evolve. |
| M4 — Optional 2.5D/3D presentation | Reconsider the official visual interface after the 2D behavior/mechanics foundation is solid. | No second simulation authority; rendering and content must integrate with skills and perception. |

Reincarnation/souls are explicitly deferred, with no implementation commitment. Animals and monsters use the shared player entity with initially simpler LLM controllers; detailed species and cognitive progression remain design questions. [ADR 006](adr/006-hy-world-2-integration-assessment.md) is deferred world-generation research, not a required dependency or current product recommendation.

## Supporting technical debt

- [x] Implement and differentially verify the [native hybrid clock](HYBRID_CLOCK.md): indexed active/due work, durable wakeups and on-demand private-history loading through the shared kernel.
- [x] Complete the [matched 2.1/2.10 runtime comparison and bounded clock/storage implementation](SUSTAINED_CLOCK.md): immutable configuration, selective bundled-guard evidence, lossless active-audit retention, exact restart recovery and explicit deadline/outage controls.
- [ ] Establish sustained cadence and thousand-player capacity with representative longer workloads; reduce remaining global scans and bound long-term evidence/storage growth without erasing historical audit evidence.

- [ ] As mechanics evolve, provide reusable component experiment tooling for use-case-generated skill, belief and other mechanic investigations, using production implementations and traceable inputs/outputs. Preserve end-to-end verification and focused contract regressions; see [component experiments](AUDIT_AND_EXPERIMENTS.md#component-experiments). Deferred tooling direction, not an immediate framework build.
- [ ] Use existing NPC event/memory indexes in hot queries where appropriate; do not duplicate existing schema indexes.
- [x] Measure the [72/144/216-actor population series, separate density case and mixed model/human/observer workload](SUSTAINED_CLOCK.md). These finite trials failed the separate 20 Hz target; the subsequent user direction prioritizes client/authority separation before regional work.
- [x] Implement the [client/authority boundary](CLIENT_AUTHORITY_BOUNDARY.md): separate native controller database, ordinary scoped world protocol, finite shared actions, durable private mental evidence, reconnect/privacy checks and actual Bevy human movement/speech. Both-service/relay costs and failed trials are retained.
- [x] Add bounded durable dispatch recovery and native relay supervision: four real process-kill boundaries, ordinary-receipt eviction, timeout after authority commit, and healthy-transport relay restart passed; see [recovery evidence](CLIENT_AUTHORITY_BOUNDARY.md#recoverable-dispatch-and-relay-supervision).
- [x] Separate [local action opportunities, world maintenance and audit compression](INDEPENDENT_PHYSICAL_CLOCK.md), preserving shared physical rules and due-maintenance ordering. The initial physical mode is opt-in and retains full-world fallback for unsupported dependencies.
- [ ] Meet the immediate [performance contract](PERFORMANCE_CONTRACT.md) gate: 216 active characters for 30 minutes, 60 Hz active movement/combat, server receipt-to-outcome ≤50/100 ms p95/p99, network input-to-outcome ≤150/250 ms p95/p99 at 80 ms RTT, normal subscriptions and observer load, stable queues and bounded active memory. Short controller-only improvements do not pass this gate.
- [ ] Verify the eventual gameplay client against the same contract: stable 60 FPS with 99% of frames within approximately 16.7 ms, high-refresh rendering/input support, prediction/interpolation and actual combat feel. Current client polish remains deferred; missing client evidence keeps product acceptance open.
- [ ] Meet the full contract: 2,000 active characters including a 200-character local battle for 8 hours within the combined 16-vCPU/64-GB backend budget, without relaxing responsiveness or correctness. Freeze hardware and representative workload details before acceptance runs.
- [ ] Complete successful fresh model operations through the migrated built-in and external paths; the latest six provider requests all returned HTTP 530. Meet the performance contract under declared controller/inference load before claiming full workload acceptance.
- [ ] Reassess bounded regional execution after the boundary measurements; current 48×36 maps do not justify a premature region-size decision. Thousands of players remain the target.
- [ ] Extract tick/action/controller responsibilities from large `lib.rs` and `npc_ai.rs` as the relevant contracts are implemented; avoid unrelated rewrites.
- [ ] Keep scenario schemas, trace records, model/behavior/skill versions, and comparison readers aligned with mechanic changes.

## Completion discipline

Unchecked means not accepted, even if part of the machinery exists. Link source changes and relevant recorded runs when completing an item. Update [CURRENT_STATE.md](CURRENT_STATE.md) with verified status and any limitations. Resolve the [open questions](SIMULATION_VISION.md#open-design-decisions) only as far as needed for the next bounded slice, recording material architectural decisions in an ADR.
