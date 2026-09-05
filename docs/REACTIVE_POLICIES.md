# Persistent reactive NPC policies

Rules `m1-4` accept model-generated `survivor-policy-v2` proposals. The LLM generates each individual's actual tree, conditions, priorities, actions and reflections. The simulation owns the vocabulary, validation, subjective condition evaluation, skill effects and durable runtime. No authored hazard/retreat tree is inserted into a generated proposal. Before the first valid policy, `authored_bootstrap` only eats carried food, rests when low on energy, or waits; it does not explore or navigate for the model.

The implementation is in [policy.rs](../simulation/src/policy.rs) and the shared [authoritative core](../simulation/src/lib.rs). The legacy Bevy/gameplay path is unchanged. `bonsai-bt` remains the legacy sequence representation; the foundation's new tagged policy vocabulary is simulation-owned and shares the same skill executor.

## Model contract and limits

A current model response contains `reason`, `policy` and `reflections`. The native [schema](../simulation/src/contract.rs) is derived from the authoritative `PolicyProposal`, node, condition, action and reflection types; the [reasoning service](../server/bridge/src/reasoning/mod.rs) supplies their operational descriptions and the frozen subjective context. Providers remain transport adapters. New model responses must contain a policy; historical sequence inputs are accepted separately by the authority and labeled `survivor-sequence-v1`.

| Node | Semantics |
|---|---|
| `priority {children}` | Revisit children from highest priority every tick; select the first non-failure. A changed branch interrupts the old skill and resets abandoned subtree cursors. |
| `sequence {children}` | Remember the running child across ticks. Advance only after success; failure ends/resets that subtree. Earlier completed children are not automatically rechecked. |
| `guard {condition, child}` | Recheck whenever visited. False fails and abandons the subtree; true ticks the child. Wrap a sequence to protect its whole ongoing execution. |
| `action {action}` | Run the shared authoritative move/gather/eat/rest/wait/speak/attack mechanism, including real prerequisites, costs, progress and effects. |
| `reconsider {reason}` | Ask for asynchronous revision when eligible; then succeed. Requests coalesce while one is already pending. |

The installed root repeats on subsequent ticks after success/failure. A terminal cycle does not uninstall the policy. This permits continuing behavior, but an unguarded speech/action can repeat: the model must choose appropriate guards. A preempted branch restarts on reentry; this version does not suspend/resume an interrupted physical action. Uninterrupted sequences preserve progress. At most **one skill step per character per tick** runs; control-only traversal is bounded separately.

Conditions are `all`, `any`, `not`, `at`, `danger`, `food_at`, and `resource` (health, hunger, energy, carried food, fear or failure count, compared using `below` or `at_least`). They evaluate a `Player`, never world sites or other minds. Danger reads a retained subjective belief at a fixed location or the current location; absence is false, not evidence of safety. Food reads the latest remembered observation for that location; absence is false and old observations can be wrong. Speech does not automatically write danger/food beliefs. Current resource values are the character's own accessible state.

Validation limits combined tree/condition depth to **8**, total nodes/conditions to **64**, composite width to **1–8**, and requires at least one skill action. Runtime traversal has a 128-node ceiling, with one skill step per tick. Locations are -10..10, resource thresholds 0..100, remembered-food minimum 1..100, and skill durations 1..5. Irrelevant skill arguments, unknown node/condition fields, unknown skills, unperceived explicit targets, invalid reflection sources and oversized input are rejected. Human and model reducer payload limits are both 50 KB; reflections remain limited to eight. The separate legacy sequence input retains its eight-action limit.

These are execution/schema limits, not a universal model budget. Current defaults/examples request 6,000 output tokens and native Ollama uses a 16,384-token context, instead of the original 1,200-output/8,192-context smoke settings, within the adapter's configurable 8,192 ceiling. The supplied proxy drops this field; do not treat it as a hard cap. Provider response/body limits remain explicit and unchanged.

## Time, damage and replacement

`Player.generation` now identifies the installed approach revision, not each damage event. Policy installation/replacement increments it; death invalidates it. Damage updates subjective experience, fear, caution and danger beliefs, and interrupts the current skill while retaining the installed policy and sequence state. On the next tick, reactive priority/guard nodes read the changed character state. A poorly chosen generated policy can still return to danger, repeat, fail or die; the executor does not manufacture sound judgment.

Pending reasoning uses its original frozen context. Damage alone does not discard that request. A response is accepted only for a current request, living AI-controlled actor, matching approach generation, unexpired 30-tick window and active run, with valid structure and permitted references. Current guard values and actual skill prerequisites determine effects after installation. An older-source reflection cannot overwrite a newer retained belief for the same location; `reflection_skipped` records that choice. This is structural/perceptual revalidation, not a guarantee that the model's old plan is sensible.

Replacement, controller mismatch, death, expiry and run stop invalidate pending work; the runner cancels the local HTTP wait and still records available outcomes. Cancellation does not prove remote processing stopped. Individual introspection intervals are retained and now also reconsider installed policies; speech, harm, policy failure and explicit reconsider nodes can request revision. New requests coalesce while one is pending. No model call pauses the authoritative tick.

## Persistence and audit

Execution retains the installed tree, sequence cursors, priority choices, active node path, action attempt/remaining duration and status (`running`, `success`, `failure`, `interrupted`) in the authoritative serialized world. SpacetimeDB reloads it for each reducer. Unit continuation checks compare both state and new causal events after serialize/restore. Conditions and effects use the same authoritative implementation in reducer tests and live runs.

Evidence includes `policy_installed`, `policy_replaced`, `guard_evaluated` with subjective sources, `branch_selected`, `policy_tick`, `action_interrupted`, ordinary skill lifecycle events, `rethinking`, `proposal_revalidated`, `reflection_skipped`, model outcomes and cancellation. Skill attempts link the relevant guard where present. The inspector shows the installed tree with stable node paths, selected priority children, sequence cursors, active path and generation; the full context and journals remain accessible separately.

Legacy archived files are not migrated or rewritten. Missing policy/runtime fields deserialize to legacy defaults and are omitted again when default. Old manifests remain inspectable and comparable with no credential. The current module refuses mutations of a saved world whose rules version differs; new experiments use fresh isolated databases. Legacy action-list proposals remain usable for human input and deterministic fixtures, explicitly distinct from the new model-output contract.

## Verification

Run the relevant checks after building the module and runner:

```bash
cargo test -p simulation -p bridge --lib --bins
python3 scripts/verify_reactive.py
python3 scripts/verify_m1.py
```

The reactive reducer check uses a visibly labeled deterministic conditional fixture. It proves runtime behavior, not model generation quality. The [reactive run verification](REACTIVE_POLICY_VERIFICATION.md) separately records real model attempts, the missing live branch proof, and the deterministic branch evidence, alongside limits and the [proxy investigation](PROXY_TOKEN_LIMIT_FINDING.md).

The model-facing schema excludes `reconsider` as the policy root because it cannot meet the executable-action requirement alone. Recursive nodes retain `reconsider` as a control leaf. The prompt states the required executable content before the vocabulary; the authority still validates that the complete tree contains a skill action. This constrains the contract, not the character’s chosen behavior.
