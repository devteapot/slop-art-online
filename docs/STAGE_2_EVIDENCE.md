# Stage 2 evidence: teaching and physical archives

The [roadmap’s second stage](WORLD_ROADMAP.md#2-a-society-that-learns) is accepted for this bounded slice, with final implementation `m2-3-catalog-bounds.1`. Batches 011–012 demonstrate chosen use and variation; deterministic tests establish the exact privacy, loss, timing and failure boundaries.

## Mechanism and scope

A personal record is an immutable attributed assertion with an ID, topic, text, optional reported location, author, origin citation and stated confidence. A holder separately retains acquisition evidence and a personal interpretation. Reports may conflict with one another and with reality. Teaching or consultation copies a report; neither grants truth, a resource, an observed site nor practical mastery. A character can interpret its own evidence and formulate a new attributed assertion.

`teach`, `record`, `consult` and `destroy_archive` use the shared timed skill executor. Their current Rhai definitions take 2, 2.5, 1.5 and 5 seconds, respectively, and cost 2, 4, 1 and 8 energy upon successful completion. Preconditions are checked again when effects commit. Teaching needs another living character at the same location; recording needs a held record and a local intact archive; consultation needs an actual local physical copy. Failed or interrupted actions do not invent transfers. The same rules apply to human and AI controllers.

Archives are finite physical assets. The local catalog exposes record identifiers, topics and authors, while consultation obtains the text. Destruction removes that archive's copies; surviving personal or other archive copies remain usable. Seed knowledge and external audit history never serve as runtime retrieval stores. New claim creation cites owned evidence but is not verification of the claim's contents. Initial knowledge and archive placement belong to the world seed; no faction names occur in these mechanics.

Personal and archive capacities are bounded at 32 records, with bounded identifiers and text. Repeated transmission refreshes acquisition evidence without replacing the immutable payload or a holder's interpretation; evidence distinguishes a repeated receipt from a new copy. A destroyed archive's catalog can remain in an absent character's stale observations until new perception corrects it.

The client exposes personal reports and remembered local catalogs in a Knowledge panel, with human actions submitted through ordinary authority. Observer inspection remains explicitly privileged. The model receives its own holdings and perceptions, not the world's archives or other characters' private records.

## Deterministic verification

All 145 Rust tests pass on final `m2-3-catalog-bounds.1`: 106 simulation, 31 bridge, five development-host, one compatibility and two client tests. The simulation total includes 19 knowledge tests and six disturbance tests. Native host/MCP/participant binaries, authoritative WASM and the browser client built successfully. The live dashboard and Knowledge panel rendered without browser errors.

Knowledge tests cover timed human/AI parity; an incoming report changing an already installed conditional action; source and location scoping; unconsulted-content privacy; disagreement without forced agreement or mastery; author death followed by consultation; archive destruction with a surviving personal copy; loss of every physical and living copy without recovery from seed/audit; departed or dead recipients; invalid references; capacity and immutable-payload collisions; maximum Unicode payloads under the behavior interpreter's input budget; and refreshing duplicate evidence without losing interpretation.

Scheduled disturbances are explicit authored experiment inputs, not character choices. They use ordinary damage or archive-destruction mechanisms, apply once in deterministic input order, survive reload and remain part of the transactional update. Tests cover scoping, validation and rollback. They let the experiment examine death and loss without requiring a model to choose a particular destructive narrative.

## Live experiment plan

[Campaign 011](../configs/experiments/campaign/011-knowledge.json) retains four concurrent six-minute sessions on a frozen implementation, with fresh Luna medium controllers, a fifteen-second post-completion cadence and no call cap. All use ordinary revisable survival habits; those habits contain no authored teaching, consultation, recording or speech actions.

- Two people: private initial report, direct teaching opportunity, no archive or scheduled death.
- Four people: one archive and scheduled author death at 120 seconds.
- Matched four-person loss probe: the same inputs plus archive destruction at 180 seconds.
- Eight people: two supplied sheltered settlements and two archives, examining distribution at greater population and distance.

Only the initial author has the private report describing a cache. Other motives express interest in useful information without disclosing that cache. Sources supply 8 food/minute for the smaller sessions and 16 across the two larger settlements, against approximately 1.371 food/minute/person upkeep. These trials focus on knowledge rather than proving the already accepted survival budget again.

Inspect actual transfers, unique surviving copies, interpretations and later actions, distinguishing direct observation or speech from formal transmission. Archive destruction alone is not total knowledge loss. A repeated consultation by an existing holder is not a newly informed inhabitant. Author death is not evidence that an unrecorded contribution survives. Exact total-loss controls remain deterministic tests; stochastic runs are assessed for what actually happens.


[Batch 011](SOCIETY_BATCH_011.md) completed with actual chosen teaching, recording, consultation after author death, and a taught report leading to cache collection. All four sessions passed their copy, scope, engine and conservation checks. The report documents duplicate-operation counts, limited distribution at eight people and the receipt-assessment bookkeeping fix. [Campaign 012](../configs/experiments/campaign/012-knowledge-repeat.json) repeats teaching on that fix and challenges archive use by initially separated readers.


## Acceptance decision: bounded Stage 2 slice

Accepted on 2026-09-06, combining [batch 011](SOCIETY_BATCH_011.md), [batch 012](SOCIETY_BATCH_012.md) and deterministic authority tests.

| Required evidence | Result |
| --- | --- |
| Learned information affects action | Cited teaching → accepted belief → model-selected cache travel → actual collection in 011; a fresh learner in 012 visits an already exhausted cache |
| Preservation after contributor death | New archive acquisition at 316.641s after author death at 120.163s in 011; archive is the sole accessible copy in the separated-reader challenge |
| No uncommunicated automatic spread | Initially private records; no copies transferred to the second eight-person settlement or the separated readers without chosen operations; scope tests |
| Complete in-world loss | Exact last-archive/last-living-carrier destruction tests reject recovery from initial seed or audit; a surviving-copy probe remains usable |
| Uncertain personal understanding | Distinct conflicting immutable assertions, evidence-linked interpretation, no automatic truth or mastery; delayed receipt assessment fixed and repeated live |
| Shared coherent execution | Timed human/AI parity, invalid/interrupted action rollback, maximum-capacity/Unicode guard checks and zero live invariants violated |

This is not universal reliability, practical mastery, autonomous research or widely distributed culture. Repeated transmission wastes resources; models can misattribute names, submit invalid operations, remain isolated or fail to exploit a preserved opportunity. Those outcomes are retained. Capacity is explicitly finite. Full in-world copying loss is established by controlled authority tests, not falsely attributed to an archive destroyed while learners survived.

The next milestone is population renewal: actual new identities with resource/time costs, dependence, support and learning, plus dynamically provisioned controllers and population-aware accounting. No newborn mechanism is claimed by this milestone.
