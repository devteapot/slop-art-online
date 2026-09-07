# Authority execution and experience design review

User direction, 2026-09-07: investigate raw authority performance and possible
core-system design errors in time progression and experience generation. Defer
client/rendering work; retain the existing small world and the agreed separate
agent implementation. This supersedes further incremental render tuning as the
next optimization priority. The 216-actor responsiveness/capacity target remains
unmet; changing the scheduling model must not silently weaken it.

## What time progression currently does

`foundation/deadline_clock.rs::sim_deadline_pulse` wakes one global run on an
absolute 50 ms grid and calls `client_access::advance_pulse`. That loads a clock
World, selects due actors, advances the shared kernel and saves the run.
`World::step_inner` advances food growth, disturbances/weather effects,
infrastructure, finite physical actions, needs/hazards, lifecycle and queued
speech. Client-mode behavior trees and mental interpretation are elsewhere.

Authoritative elapsed time and autonomous future work are required. A global
whole-World update at 20 Hz is an implementation choice, not a requirement of
SpacetimeDB or of all these mechanics. Official
[schedule-table documentation](https://spacetimedb.com/docs/tables/schedule-tables/)
explicitly supports both one-shot deadlines and recurring game ticks, including
a 50 ms Rust example. The scheduling API itself is appropriate. The transaction
work attached to a wake needs redesign. Pinned module SDK remains 2.1.0 and the
isolated measured runtime remains 2.10.0; no version change is proposed here.

Potential design: indexed due physical actions and explicit deadlines for slower
systems, with timestamp-based elapsed accounting. Keep idle actors out of hot
transactions. Before implementation specify action ordering, simultaneous effects,
interruption, death while disconnected, newborn time origins, law activation,
outage recovery and cross-entity dependencies. Merely creating one 20 Hz timer per
actor would multiply scheduling overhead without solving the underlying work.

## Evidence is three separate responsibilities

1. World physical facts and authorized delivery: action outcomes, perception
   authorization, ordered recipient cursors, reconnect recovery and evidence
   needed for authority-side proof checks. These cannot be accepted solely from
   a client assertion.
2. Client experience interpretation: personal memory, beliefs, goals, behavioral
   evaluation and decision journal. The separate controller instance already owns
   these. `brain_ingest` applies delivered experiences to that private runtime.
3. Developer forensic audit: full world event history, lossless compression and
   diagnostic exports. The current world save still appends and compresses this
   inside the physical transaction. The controller journal does not replace it:
   each controller can see only its own authorized inputs.

The world currently retains recipient `sim_native_experience` rows (up to 256 per
actor) as well as full `sim_audit` history, while the controller persists received
inputs and its decision journal. Some duplication serves different contracts,
but those contracts do not require the current payload size, generation frequency
or synchronous archive cost. Review each field against delivery, gameplay proof
or diagnostics before retaining it on the world. Event-only transient delivery
cannot replace reconnect recovery; see official
[event table guidance](https://spacetimedb.com/docs/tables/event-tables/).

## Confirmed core-design amplification

Before the change below, `simulation/src/ecology.rs::renew_food` emitted local
`food_growth` and then called
`observe_site` for every living actor at that site. `observe_site` reconstructs a
site/catalog observation and evaluates nearby people, emitting a new
`seen_player` perception for each visible peer. `World::event` also calls
`record_experience`, which projects the recipient record and updates retained
history. Save then persists recipient rows and the global audit; controller
subscriptions deliver inputs to the other instance for interpretation/storage.

Thus a changed food amount triggers more than a food update: in a mutually
visible crowd of n actors it can cause O(n²) peer observation records. The existing
visibility candidate filter reduces distant work but does not remove this dense
local amplification. This is a code-established design concern, not yet a measured
claim that it accounts for all remaining latency.

Review change-driven perception: a food change should update food facts for
eligible recipients; movement/visibility changes should update perceived people.
Preserve explicit observation actions, disappearance/occlusion, provenance,
authoritative access and legitimate knowledge freshness. Do not simply drop
records after generation or delete old evidence. Changing observation triggers
requires explicit semantic acceptance tests, including custom visibility laws.

## Next validation and implementation order

- Establish an authority-only baseline with real agent controllers, no render
  subscriptions and no exports during the active window. Declare controller count,
  action rate, local density and duration. Report controller/relay costs separately.
- Measure records per physical cause and recipient, repeated unchanged perceptions,
  rows read/written per wake and deadline lateness. Use the actual shared kernel
  and actual authority; synthetic connection capacity is a separate experiment.
- Implement cause-specific perception and local due-work transaction boundaries,
  preserving causal/permission/physical semantics. Evaluate audit maintenance
  separately from necessary atomic outcome/delivery writes.
- Compare sparse and crowded populations in this same world before proposing
  shards. Judge active-action cadence, input latency and timely autonomous effects;
  an event-driven idle world need not manufacture 20 empty commits per second.

The first cause-specific change is implemented below. The subsequent
[independent physical clock](INDEPENDENT_PHYSICAL_CLOCK.md) implements opt-in
local action transactions, maintenance deadlines with a causal barrier, and
separate archive transactions. General local execution for arbitrary laws and
skills, long-duration responsiveness and population capacity remain unverified.


## First implementation: food renewal refreshes site facts

Food renewal now calls `observe_site_facts`, preserving the active observation
law, local catalogs, `food_growth`, world observation and recipient site evidence.
It no longer initiates peer visibility evaluation or generates fresh `seen_player`
records. Explicit observation still refreshes both site facts and visible people.
This deliberately removes food renewal as an implicit trigger for person sightings;
movement and explicit observation retain their existing triggers. It does not
implement general change-driven visibility invalidation for arbitrary custom laws.

For one growth event in a mutually visible crowd of n living actors, the isolated
kernel test asserts exactly 1 + 3n events, instead of the previous additional
n(n-1) peer perceptions. It covers 2, 8 and 32 actors in both controller modes,
client ingestion and checkpoint recovery with original provenance, and explicit
observation retaining n-1 sightings. A custom observation-law test checks that
projected food still follows the law. The simulation library suite passes
228 tests with one existing ignored test. Both WASM modules and both authority
probe binaries build successfully.

The change retains the current indexed recipient delivery/storage paths and
subscriptions; there is no schema or generated-binding change. It reduces records
at their physical trigger rather than discarding accepted evidence. Existing
whole-World loads and synchronous audit compression remained at that pass. Actual-authority
functional and throughput validation is recorded in `REALTIME_PERFORMANCE.md`.
