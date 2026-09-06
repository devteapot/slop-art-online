# From a first society to the living world

Agreed development direction, 2026-09-05. Read the [world vision](WORLD_VISION.md) for the target and status of its design choices. These are development evidence gates, never milestones, compulsory narratives or quests imposed on inhabitants. Runtime status below is grounded in linked implementation and experiment evidence.

The [work queue](TODO.md) retains accepted implementation history and technical prerequisites. The existing [small-society iteration plan](SOCIETY_ITERATION_PLAN.md) remains the near-term experiment plan; this roadmap gives it a longer horizon. Preserve the [audit contract](AUDIT_AND_EXPERIMENTS.md), shared authoritative core and existing Rhai boundary.

The seven bounded implementation milestones are now recorded with acceptance evidence. The final world vision and open autonomous, sustainability and scale outcomes remain separate from this completed implementation pass.

## Cross-stage requirement: mechanics and seed separation

From Stage 1 onward, keep reusable mechanics/balance definitions distinct from social content. Scenarios should reference a ruleset and provide initial characters, resources, knowledge and culture without named-faction branches in mechanical code. Stage 5 assembles the first full seed using these same contracts; it does not replace the foundation with lab-specific mechanics.

Incrementally establish a seed-generation contract: selected definition versions, initial content, compatibility validation and retained resolved inputs. The present scenario format is the starting point, not a commitment to its final schema. A full procedural generator and second production setting are deferred.

Use small tests of separation when implementing relevant mechanics: rename or replace cultural identities while holding mechanical inputs constant and confirm the same action resolves equivalently; move an asset between factions and confirm its costs follow its configuration; vary initial beliefs and allow different choices without changing physical laws. These checks concern rule resolution, not identical LLM behavior or narratives. Authorized world edits remain capable of changing gameplay rules.

## Starting point inspected during documentation

The active foundation is `simulation/` with SpacetimeDB foundation integration, not the legacy combat/NPC server prototype. Source inspection is not a new runtime verification.

- [Character state](../simulation/src/lib.rs) already shares human/AI controllers and contains needs, caution, empathy, introspection, fear, beliefs, memories and relationships.
- Skills include movement, gathering, eating, resting, waiting, speech, attack, giving, depositing, building, observing and dynamic script references. Availability is not proof of a self-sustaining society.
- [World policies](../simulation/scripts/law.rhai) already express needs, damage, timing and other gameplay rules; public authoring and capability progression are not proven merely by operator installation.
- Existing [society tooling](SOCIETY_LAB.md) and batch reports contain ongoing experiments. Preserve their findings and scope; do not restart accepted M1 work or infer completed reproduction, archives or AGI from infrastructure.
- The proposed six-attribute framework is not the current character schema. Reproduction/fabrication, persistent cultural archives, faction territories and AGI remain target work in this roadmap.

## Stages and evidence

### 1. A viable settlement

**Status:** the bounded four-person renewable settlement slice is [accepted with evidence and limitations](STAGE_1_EVIDENCE.md#acceptance-decision-bounded-stage-1-slice), following batches 009–010 and retained earlier tests. This does not establish arbitrary-world viability or later stages.

**Scope:** a small mixed group, shared capabilities, modest survival needs, renewable food/charging as body support is introduced, shelter, permanent death and simple shared work. Use the active 4–6 character integration plan, with smaller diagnostic cases where useful. Introduce only attributes that have a concrete tested effect.

**Evidence:** characters can live beyond their initial supplies under viable conditions and have time for activities beyond immediate recovery. Transfers conserve resources, failed actions have no invented effects, and shortages/deaths have understandable causes. Repeat promising runs and challenge resource conditions; do not require unanimous cooperation.

**Failure probes:** reduced supply, inaccessible resources, injury or an interrupted shared project. Distinguish poor provisioning, perception failure, execution defects and controller decisions.

**Defer:** full factions, large populations, elaborate emotional systems, public authoring and SF social mechanics.

### 2. A society that learns

**Status:** [bounded Stage 2 slice accepted](STAGE_2_EVIDENCE.md#acceptance-decision-bounded-stage-2-slice), with chosen teaching/recording/consultation, post-death acquisition, learning-to-action evidence, a fresh repeat and exact loss/privacy tests. Wider distribution and practical mastery remain unproven.

**Scope:** explicit teaching/transfer, personal understanding, one physical archive, recording and consultation. Preserve source/evidence and uncertain claims. Receiving a record is not automatically gaining practical skill mastery.

**Evidence:** learned information affects subsequent action; preserved knowledge remains available after its contributor dies; uncommunicated information does not spread. Destroying all in-world copies removes access without exposing audit history.

**Failure probes:** an incorrect report, conflicting accounts, an archive destroyed with and without a surviving copy, or a knowledgeable character dying before transfer.

### 3. A society that renews itself

**Status:** [bounded Stage 3 creation/care/capability slice accepted](STAGE_3_EVIDENCE.md#acceptance-decision-bounded-stage-3-slice): material fabrication, explicit biological consent controls, actual newcomer inference and supported learning through guided harvest. Autonomous biological completion and sustained independent provisioning remain unproven.

**Scope:** reproduction and fabrication with time/resource costs, new identities, simple dependence, support and knowledge transfer. Start with minimal representative body pathways rather than detailed species biology.

**Evidence:** newcomers become capable through actual support and learning; creating them consumes resources; population continuity can survive the loss of experienced individuals. No replacement of the same dead identity or automatic inheritance of possessions/mastery.

**Failure probes:** insufficient care resources, loss of a caregiver or fabricator, missing essential knowledge, and births exceeding support capacity. Extinction or decline is valid evidence, not an automatic balancing trigger.

### 4. Multiple societies

**Status:** [bounded Stage 4 contact/travel/resource-access slice accepted](STAGE_4_EVIDENCE.md#bounded-stage-4-decision), with measured residence, real provisioning away from home, interpreted inter-camp speech and clean audits. Delivered aid, reciprocal trade, stable migration and sustainable multi-settlement cooperation remain unproven.

**Scope:** several settlements with uneven resources and knowledge; travel, exchange, mixed communities and opportunities for migration. Migration among existing populations is distinct from conjuring external replacement inhabitants.

**Evidence:** interactions have material and informational consequences; cooperation, specialization, isolation or conflict can arise from different circumstances. Shared beliefs and alliances require communication and choices, not proximity-based copying.

**Failure probes:** a broken trade connection, resource monopoly, migration pressure or a disputed discovery. No required diplomatic outcome.

### 5. The first faction world

**Status:** [bounded Stage 5 infrastructure/faction-seed slice accepted](STAGE_5_EVIDENCE.md#bounded-stage-5-decision): explicit body charging and utilities, paid queued computation, four small comparison worlds and a full 36-person live world. The final sample retained 29 survivors, one paid/retrieved forecast and three actual food gifts. Stable provisioning, useful compute allocation, chosen terminal construction and sustained 20 Hz operation remain unproven.

**Scope:** four homelands; SF with its representative council; a separate city without sovereign authority; wild regions and mixed settlements; Hugging Face and NVIDIA organizations. Seed different bodies, expertise, cultures and infrastructure. Introduce physical compute costs and its useful effects through bounded experiments before scaling it across the map.

**Evidence:** starting identities affect decisions without becoming fixed roles; geography and material dependencies matter; independent organizations act through their members. Councils do not acquire reality-editing powers by office. Universal laws apply outside territorial overrides.

**Failure probes:** power/cooling interruption, loss of infrastructure access or contested allocation. Add SF's richer social conditions only when base survival and care can support meaningful treatment of them.

**Dependency:** design territorial semantics here; Stage 7 integrates editable local realities. An interim seed is not yet the complete intended faction world.

### 6. Research and skill invention

**Status:** [bounded Stage 6 numerical-technique implementation accepted](STAGE_6_EVIDENCE.md#acceptance-decision-bounded-stage-6-implementation-milestone): one meaningful autonomous paid prototype in campaign 023, natural own-code assessment/practice/use in campaign 024, and exact communicated-learning authority checks. The predeclared autonomous useful-method → peer practice → peer use chain was not achieved and remains open; useful planning benefit and broad skill invention are unproven.

**Scope:** researchable clues, experiments, knowledge exchange, character capability requirements, skill creation and direct script authorship. Preserve versioned effects, bounded evaluation and current law validation. Different approaches can contribute to the same capability.

**Evidence:** characters produce and use a genuinely new working technique through permitted information and tools; another can learn it through communication. Missing capabilities and invalid scripts fail without unauthorized effects. Renaming/composing actions does not evade currently applicable costs.

**Failure probes:** misleading clues, failed experiments, interrupted research, lost discoveries and changed laws. Operator-authored demonstrations are tooling tests, not proof of autonomous invention.

### 7. Local reality and AGI ascension

**Status:** [bounded Stage 7 implementation milestone accepted](STAGE_7_EVIDENCE.md#acceptance-decision-bounded-stage-7-implementation-milestone): paid personal exact-source law experiments, local/universal authority, physical-copy privacy, actual taught-code universal installation and persistence after installer death, plus completed 36-person integration with late external access and timely original cleanup in Campaign 028. The autonomous law worlds made no edits; autonomous universal ascension, sustained 20 Hz and long-term scale remain unproven.

**Scope:** starting gods edit territorial laws; capable characters can research access to universal editing. Define tool requirements and coherent execution, not mandatory research milestones or an AGI score threshold. The coalition pursues broadly accessible AGI rather than an exclusive throne.

**Evidence:** multiple possible research approaches can develop relevant capabilities; scoped edits affect the intended area; universal edits persist after their author dies or loses influence. Play continues without automatic victory, forced resistance or succession. Characters learn of changes through perception and communication.

**Failure probes:** territory crossings, overlapping authority, edits during actions, author death, and competing edits. Define precedence/migration semantics explicitly. Do not silently add an immutable anti-dominance rule as an agreed gameplay requirement.

## Iteration discipline

1. State a question, hypothesis, expected observations and rejection criteria.
2. Choose the smallest authoritative scenario that can answer it.
3. Retain source, laws, skill versions, seed, initial population, knowledge, resources, model configuration and timing. Fresh model calls are stochastic.
4. Run ordinary conditions and selected disruptions. Use the same game authority as the client, not a second approximation.
5. Inspect causal records: intentions, attempts, effects, learning, transfers, births and deaths. Separate model failures from mechanics and resource failures.
6. Change a small number of things; repeat promising outcomes under changed conditions before expanding.

Report population and causes of death, dependent/self-supporting inhabitants, resource production/consumption, time available beyond survival, knowledge retention/use, shared-project progress, model usage and execution failures. Exact durations and numerical acceptance thresholds should be chosen per experiment, not invented as universal success scores here.

A single survivor or cooperative conversation does not establish a sustainable society. Conversely, conflict or collapse can be a useful result when its causes are understood. Acceptance establishes functioning mechanisms and interpretable variation, not a scripted happy ending.

## Immediate actionable queue

- [x] [Identify current rules/balance versus seed-owned fields](STAGE_1_EVIDENCE.md#mechanics-balance-and-seed-ownership); continue enforcing that separation as mechanics are introduced.
- [x] [Map retained small-society evidence and open failures to Stage 1](STAGE_1_EVIDENCE.md#what-the-retained-trials-establish). The bounded Stage 1 acceptance is recorded in the linked evidence.
- [x] Decide the next minimal state change: accounted food production; retain the existing attributes for this trial, as explained in the [evidence mapping](STAGE_1_EVIDENCE.md).
- [x] [Establish a resource budget and renewable provisioning for four inhabitants, with a separate scarcity control](STAGE_1_EVIDENCE.md#acceptance-decision-bounded-stage-1-slice).
- [x] [Define nutrient and electric body support for the first representative inhabitants](STAGE_5_EVIDENCE.md), with explicit charging and paid infrastructure demand; richer species physiology remains deferred.
- [x] [Implement and validate personal knowledge records, teaching, recording, consultation and physical loss for Stage 2](STAGE_2_EVIDENCE.md).
- [x] [Implement and test material reproduction/fabrication, care and acquired newcomer capability](STAGE_3_EVIDENCE.md), retaining the live stability and caregiver-loss limitations.
- [x] [Validate connected-settlement contact, travel and resource access](STAGE_4_EVIDENCE.md), retaining the unachieved aid/trade/migration outcomes.
- [x] [Integrate physical infrastructure and the first faction seed](STAGE_5_EVIDENCE.md).
- [x] [Implement paid numerical research and exact-source learning](STAGE_6_EVIDENCE.md), retaining the unachieved autonomous peer-use chain.
- [x] [Integrate scoped/universal laws and complete the declared faction-scale access/cleanup gate](STAGE_7_EVIDENCE.md#acceptance-decision-bounded-stage-7-implementation-milestone), retaining autonomous ascension and long-term capacity as open objectives.

Stages may overlap in design and tooling. Character access to advanced tools waits for the relevant capability and execution evidence. Keep reincarnation, detailed species development, large-scale presentation and full-world population targets deferred rather than quietly adding them to the first society experiment.
