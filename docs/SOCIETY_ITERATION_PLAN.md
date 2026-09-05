# First small-society iteration

The active objective is a small, inspectable group whose individual choices lead to useful interaction, resource use, recovery and meaningful consequences. This is an implementation-and-experiment loop, not a search for a scripted happy ending. The first integration target is 4–6 characters; two-character matrices remain the controlled diagnostic tool.

## Long-term objective and roadmap integration

User direction, 2026-09-05: continue the existing simulation/experiment loop toward the [world vision](WORLD_VISION.md), following the [world development roadmap](WORLD_ROADMAP.md). Integrate these with this plan rather than restarting experiments or discarding accepted evidence. The current small-society work is Stage 1 of that longer path.

The development sequence is viable settlement → knowledge transfer and archives → reproduction/fabrication and dependent newcomers → multiple societies → the four-faction world → research and skill invention → territorial editing and open-ended AGI ascension. These are engineering evidence gates, not milestones imposed on inhabitants. Advance through bounded experiments once the relevant mechanisms have evidence; do not treat completing a small society as completing the final vision.

Keep mechanics and balance reusable and separate from social-setting content. The first AI-lab setting is an authored world seed, not a reason to embed named-faction checks into resource costs, learning, skill requirements or population rules. Extend existing scenario machinery toward validated, versioned seed composition. A second full setting or general procedural generator is not an immediate prerequisite.

Preserve the core decisions: one entity shared by human/LLM controllers, including creatures; permanent initial death; renewal through reproduction and fabrication with care/learning; physical knowledge archives and genuine loss when all carriers disappear; material energy/compute infrastructure; emergent roles and politics. Gods are advanced players. Universal-editing access is the ascension capability, with no compulsory research route, victory screen or scripted dethroning. See the vision for agreed decisions versus proposals and unresolved requirements.

For the next planning pass, map retained batch evidence and open failures to Stage 1, identify the smallest missing mechanism, and record how each new experiment advances or challenges a roadmap gate. Preserve existing runtime/model choices and experiment controls. Do not expand the immediate run into all world features; stage knowledge continuity and population renewal after viable provision is demonstrated. Track roadmap progress with evidence links rather than marking future stages complete from scaffolding alone.

Starting-habit direction, 2026-09-05: normal settlement seeds provide visible, versioned initial behavior trees so people act before the first model response. Profiles can differ, but remain ordinary policies that the individual may keep, patch or replace. Preserve empty-start controls and distinguish authored habits from later learned behavior; never silently restore them after failure.

Current planning pass: [Stage 1 evidence mapping, mechanics/seed ownership and renewable budget](STAGE_1_EVIDENCE.md). Batches 001–010 remain retained evidence. The [bounded Stage 1 settlement is accepted](STAGE_1_EVIDENCE.md#acceptance-decision-bounded-stage-1-slice); knowledge continuity and later roadmap stages remain open.

## Loop and controls

1. State a hypothesis, the mechanism changed, expected observations and rejection criteria before running.
2. Freeze implementation artifacts, source/config inputs and client assets. Each variant runs its own authority database, host and scoped actor processes. Keep matrices inside each session.
3. Run a bounded paired batch with matched scenarios and controller opportunities. Retain all responses, errors, cancellations, resource effects and usage.
4. Analyze causal traces and invariant checks. Separate model validity, execution correctness, useful progress and social consequences. Record what supports or contradicts the hypothesis.
5. Keep useful changes, revise failed approaches, and replicate promising outcomes with swapped personas or changed resource conditions before claiming general improvement.

The user selected Luna throughout with no model-call/spending cap. Every batch still has a wall-time deadline and records actual call/token usage. A finite call allocation is available for controlled tests, but is disabled for the main iterative runs. Starting another batch requires a concrete reason recorded by the operator/agent; there is no blind endless launcher. Several candidates may run concurrently when their comparisons are interpretable; reconcile their findings before choosing the next change. Fresh model results are stochastic. Saving a build and seed enables inspection and controlled reruns, not exact model reproducibility.

## Milestone gates

- **Execution:** actions follow their declared semantics; resource transfers conserve quantities; interruption and resumption are explainable; impossible/unauthorized actions have no effects.
- **Individual intent:** each living character has an identifiable purpose and can revise a failed approach using its own experience. Useful waiting is distinguishable from loops without progress. Learning has a subsequent opportunity to change behavior.
- **Perception and memory:** local resource facts remain usable under an explicit observation contract; delayed deliberation can cite the evidence it actually received within a bounded lifetime; other minds and unseen events stay private.
- **Social effect:** free-form speech is heard and can influence a later choice; characters can carry out a material interaction such as giving resources or contributing to a shared need. The world does not force cooperation or copy beliefs automatically.
- **Consequences:** viable provision can sustain a group beyond its initial stock; scarcity or bad decisions can cause failure/death; death remains permanent. A shortage control must remain capable of failing.
- **Robustness and inspection:** at least two implementation variants can run concurrently without state/request/artifact mixing, completed histories remain inspectable, and model usage and throughput are reported. The accepted integration result must survive at least one fresh repeat or changed-condition challenge.

The initial society can use food, shelter and a small shared project; currency, families, institutions, large populations, public skill authoring and divine progression remain outside this first milestone unless later evidence or user direction changes scope. Mechanics stay in Rhai with validated engine capabilities, and all controllers use the same world rules.

## First hypotheses

1. Explicit resource-scale and execution semantics reduce inverted hunger guards and departure-condition mistakes without injecting a survival strategy.
2. Distinguishing significant experiences from routine tick noise, and pinning bounded read evidence for in-flight work, improves valid learning and lowers prompt/persistence overhead.
3. Reconsideration triggered by progress failure, social input and accepted learning is more useful than spending the budget on a fixed role rotation.
4. Conserved resource giving, perceptible shared work and renewable/limited supplies create opportunities for actual cooperation and competing interests beyond speech alone.

Start by making versioned paired execution concrete, then evaluate these hypotheses in that order where possible. Changes to underlying engine contracts get targeted deterministic checks before fresh-model evaluation. Generated mistakes remain evidence and are not silently corrected on submission.
