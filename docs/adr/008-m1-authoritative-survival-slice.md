# ADR 008: A bounded authoritative survival slice

**Status:** Implemented M1 defaults, 2026-09-04. These are revisable implementation choices, not previously fixed product requirements. See [runbook](../M1_RUNBOOK.md) and [verification](../M1_VERIFICATION.md).

## Decision

Keep one authoritative Rust rule kernel in the `simulation` workspace crate, invoked by dedicated `sim_*` reducers in the existing SpacetimeDB module. The scenario runner calls those real reducers; only unit tests call the kernel directly. Existing gameplay remains a legacy prototype until its presentation/controllers are connected to the foundation. This avoids rewriting Bevy or changing the server stack while keeping the first proof bounded.

Persist one serialized run snapshot and append-only causal rows in private SpacetimeDB tables. A unique database per experiment isolates state, operator identity, requests and outputs. The Rust bridge's new `sao-sim` binary provides local orchestration/model transport and exports common evidence for an HTML operator inspector and structured consumers. Bevy remains the game client. This deliberately simple storage/query strategy targets a few individuals, not scale.

The behavior layer uses `bonsai-bt` sequence data with a persisted cursor, active attempt and remaining duration. Model output supplies at most eight skill actions, compiled into this restricted sequence. It does not accept arbitrary nested trees yet. Each action must complete before the next begins; failures stop the sequence; damage or an accepted new approach interrupts it. An authored reactive/survival policy continues when no model approach is available and uses only subjective state. The old `npc_ai.rs` evaluator is not used in foundation runs.

## Selected first defaults

- Three initial players: two AI controllers and one optional human controller; up to sixteen supported by scenario validation. Roles and motives are separate fields. The operator owns the run and its human participation input.
- A one-dimensional world from -10 to 10, with configured food sites and danger. Movement takes one cell per tick; observation sees food at the current location and nearby players within one cell. Speech is heard within two cells; witnessed death within one. Initial reports can be wrong.
- Shared `move`, `gather`, `eat`, `rest`, `wait`, `speak`, and `attack` skills. Gathering costs four energy; attacking costs eight and inflicts twenty damage; eating consumes one food and reduces hunger by thirty-five. Rest recovers twelve energy per tick for one to five ticks. Hunger rises by two per tick, with starvation damage only after an opportunity to act. Hazard damage is scenario-defined. These values are tuning defaults.
- Character memories retain sixteen perceived events; audit history has no automatic expiry. Authored prior reports receive their own subjective perception IDs rather than pointing into omniscient initialization data.
- Caution, empathy, introspection, fear, relationships and beliefs enter model context. Experienced harm changes caution according to individual introspection and produces source-linked subjective consequences. Starvation is distinguished from environmental danger. Model interpretation can propose bounded caution/trust and belief changes tied to supplied perceptions. Natural-language belief text is subjective, not verified world fact.
- Reconsideration after failed/no-progress approaches varies from four to fourteen ticks with introspection. Initial reasoning and heard speech can also request interpretation. Inputs are captured at request time; reflection evidence is validated against that exact supplied context even if short-term memory changes during inference. Behavior-generation changes, dead actors, stopped runs, unknown requests and unsupported output remain rejection boundaries.
- The local inspector can expose world truth and history; model context is explicitly constructed from the individual. The loopback operator UI is not an in-world source of information.

## Consequences and limits

The slice is executable, inspectable, and testable without the visual client. Shared controller semantics apply to foundation characters; legacy combat skills, respawn and automatic belief propagation are not silently declared migrated. Models can still make bad choices, invent an invalid source, repeat failed approaches, or contradict their own wording; those failures remain visible in evidence rather than being accepted as mechanical truth.

Seeds, resolved configuration, actual model requests/outputs, logical time and versions are retained. World rules currently use no random draws. A seed does not guarantee fresh model output; a general replay engine, broad tree representations, large-scale storage, sophisticated attention/memory and multi-account gameplay integration remain later work. Each new mechanic must preserve scenario, evidence and query support.
