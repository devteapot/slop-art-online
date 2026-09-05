# Simulation roadmap and work queue

Long-horizon development order: [from first society to living world](WORLD_ROADMAP.md), based on the [world vision](WORLD_VISION.md). Its seven stages refine the broad later-stage headings below without resetting accepted M1 work. The [small-society iteration plan](SOCIETY_ITERATION_PLAN.md) remains the immediate experiment scope; [Stage 1 settlement](STAGE_1_EVIDENCE.md), [Stage 2 teaching/archives](STAGE_2_EVIDENCE.md) and [Stage 3 creation/care/capability](STAGE_3_EVIDENCE.md) have bounded acceptance evidence with explicit live limitations. Multiple societies and faction-world integration follow.

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
- [ ] Before public player authoring, add aggregate allocation/work accounting and capability/progression policies that enforce composition costs against untrusted definitions.
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

- [ ] As mechanics evolve, provide reusable component experiment tooling for use-case-generated skill, belief and other mechanic investigations, using production implementations and traceable inputs/outputs. Preserve end-to-end verification and focused contract regressions; see [component experiments](AUDIT_AND_EXPERIMENTS.md#component-experiments). Deferred tooling direction, not an immediate framework build.
- [ ] Use existing NPC event/memory indexes in hot queries where appropriate; do not duplicate existing schema indexes.
- [ ] Measure spatial query cost before choosing an index/partitioning strategy. Population scale is not the current success criterion.
- [ ] Extract tick/action/controller responsibilities from large `lib.rs` and `npc_ai.rs` as the relevant contracts are implemented; avoid unrelated rewrites.
- [ ] Keep scenario schemas, trace records, model/behavior/skill versions, and comparison readers aligned with mechanic changes.

## Completion discipline

Unchecked means not accepted, even if part of the machinery exists. Link source changes and relevant recorded runs when completing an item. Update [CURRENT_STATE.md](CURRENT_STATE.md) with verified status and any limitations. Resolve the [open questions](SIMULATION_VISION.md#open-design-decisions) only as far as needed for the next bounded slice, recording material architectural decisions in an ADR.
