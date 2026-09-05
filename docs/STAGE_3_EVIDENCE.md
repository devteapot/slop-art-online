# Stage 3 evidence: population renewal

The [roadmap's third stage](WORLD_ROADMAP.md#3-a-society-that-renews-itself) is accepted for the bounded creation, care and acquired-capability slice described below. Final gameplay implementation is `m3-2-perceived-care.1`. Live outcomes remain variable; long-term population stability is not established.

## Mechanism and scope

Biological reproduction requires two living, independent, colocated people to make matching explicit offers. Offers quote each person's food and energy commitment, expire after 90 seconds and can be withdrawn. A reproduction attempt takes 30 seconds and binds the exact offers; departure, death, withdrawal, replacement, expiry or inadequate resources prevents completion. Both parties pay two food and ten energy only on successful creation. Concurrent attempts cannot consume the same offers twice.

Fabrication takes 45 seconds at a configured workshop and consumes six food as construction nutrients and thirty energy. It creates an artificial individual with its own identity and controller. This representative artificial body uses nutrient support; electrical charging and compute infrastructure belong to the next stage of body/economy development. Fabrication grants no ownership or obedience.

Each newcomer starts with a new monotonically allocated ID, no possessions or private reports, and an ordinary revisable survival habit from the seed. It neither restores a dead identity nor inherits the creator's memories, mastery, controller credentials or installed policy. Controller enrollment discovers authoritative creation and assigns the configured newcomer profile through normal participant authority. Both builtin and external profiles are supported. A retained actor limit bounds this implementation's records, including dead individuals; it is not an ecological support estimate.

A dependent can move, communicate, observe, rest, eat supplied food and learn. Independent gathering, building and creation require development. Care is a three-second action that spends one real caregiver meal and two energy, reducing a hungry dependent's need by 35. It records actual support. Guided practice takes five seconds and four energy, requires a living local prior caregiver and a personally interpreted report about the current site, and gathers one food that must actually exist there. Default self-support requires at least sixty seconds of age, two care meals and one such practice. Age, a received report, an asserted interpretation or care alone cannot substitute for doing the work.

These costs and development conditions are Rhai laws. Seed-owned names, motives, workshop locations, capacity and newcomer habits remain separate. Public local observations show body/dependence and care needs; they do not expose others' private understanding. Offers appear to their author and addressed partner. The Life panel submits human actions through the same authority used by AI participants.

## Verification and live plan

All 165 Rust tests pass: 122 simulation, 32 bridge, eight development-host, one compatibility and two client tests. The simulation total includes sixteen lifecycle tests. Twenty-one focused Python tests cover batch orchestration, enrollment shutdown and population reporting. Native binaries, authoritative WASM and the browser client build successfully. The live dashboard and Life panel rendered without browser errors.

Deterministic tests cover consent withdrawal, replacement, expiry and partner death; exact completion costs and transaction rollback; unique identities and arena scope; starter provenance and reload; human/AI fabrication parity; insufficient care and practice resources; practical learning and independent-action gates; and newborn timing. Host tests cover dynamic enrollment and stopping without leaving late newborn grants active. Reporting treats creation costs, care meals and actual practice harvests explicitly in food conservation.

[Campaign 013](../configs/experiments/campaign/013-population.json) runs four concurrent eight-minute sessions with fresh Luna medium controllers, a fifteen-second post-completion cadence and no call cap. Four initial people share a sheltered camp. Initial and newborn habits contain no reproduction, fabrication, care, teaching or practice. Motives make these opportunities relevant while actions remain model choices.

The reproduction and fabrication variants permit one newcomer. The loss variant schedules lethal damage to actor 1 at 300 seconds; whether a child exists and whether that person actually provided care must be read from the events. The pressure variant permits further creation while reducing nominal food production from eight to six per minute. Current metabolism requires approximately 5.486 meals/minute for four people or 6.857 for five, before waste or creation costs. Initial stocks temporarily buffer shortages. Report measured production and consumption separately from those reference rates.

Look for completed creation, newcomer model calls, actual care, report acquisition and interpretation, guided harvest, subsequent independent work, and continuity after actual caregiver loss. Also retain refusals, absent creation, failed plans, unmet care and deaths. One sample of each condition establishes neither reproducibility nor universal population stability.

[Batch 013](SOCIETY_BATCH_013.md) established fabrication, actual newcomer inference, material care and an interrupted biological creation, but no self-supporting newcomer. The next [twelve-minute repeats](../configs/experiments/campaign/014-population-repeat.json) use `m3-2-perceived-care.1`: retained local observations remain valid target evidence, patch paths are explicit, and failed behavior retries no longer consume communication or learning slots.


## Acceptance decision: bounded Stage 3 slice

Accepted on 2026-09-06 using [batch 013](SOCIETY_BATCH_013.md), [batch 014](SOCIETY_BATCH_014.md) and the exact authority controls.

| Required evidence | Result |
| --- | --- |
| Material creation and distinct identity | Three chosen fabrications across fresh sessions; exact food/energy costs, new actor 5, empty knowledge/inventory and actual separately enrolled model calls |
| Both representative pathways | Fabrication completed live; biological completion, mutual consent, atomic costs and controller parity pass deterministic tests; live mutual creation fails correctly after a parent's death |
| Support and learning develop capability | Actual meals, communicated guidance, personally interpreted typed account, guided harvest, self-support event and consumption of the harvested food in 014 |
| Continuity after experienced individual loss | A newcomer remains healthy and develops after the initial report holder dies, supported by surviving residents; that deceased person was not an actual caregiver in this sample |
| No automatic inheritance or knowledge access | Creation/reload/arena/privacy tests; newcomer learns through its own receipts and interpretation, without copying a dead person's private state |
| Coherent failure and scope | Expired/withdrawn/replaced consent, insufficient resources, unavailable guidance, missing understanding, death and transaction rollback controls; clean live conservation, copy and scope audits |
| Mechanics separate from seed identity | Matching creation outcomes after changing cultural names, motives and Human/AI controllers with physical inputs held constant |

The accepted evidence is a working population-development mechanism and one complete supported learning-to-capability chain. It is not autonomous biological reproduction, loss of an established primary caregiver in a live run, sustained independent provisioning, reliable model syntax, charging physiology or a stable population across generations. The successful learner's final ordinary-gather policy update was still pending at the endpoint; its earlier guided harvest and meal were real, but a status transition must not be reported as a demonstrated long-term habit. Those integration limits remain explicit when later seeds add population renewal.

The next milestone tests travel, exchange and information among existing settlements. It uses fixed populations so migration cannot be confused with new creation. Later faction-world integration must continue watching actual newcomer provisioning and caregiver loss alongside the new body/infrastructure economy.
