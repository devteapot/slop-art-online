# Society experiment lab

The local dashboard runs at `http://127.0.0.1:18930`. It groups running and completed experiments, shows actual journaled model calls, and opens one map or two maps side by side. Floating labels are off by default. The full map view can inspect individual motives, current goals, policies, beliefs and recent activity.

This campaign is Luna-only, with no model-call cap. Each batch has a finite wall-time deadline. A new hypothesis is recorded before launching; runs are reviewed before the next batch. The [bounded four-person Stage 1 settlement is accepted](STAGE_1_EVIDENCE.md#acceptance-decision-bounded-stage-1-slice), combining renewable/finite controls, a fresh repeat and startup challenge with retained material and learning/action evidence. This does not establish indefinite or arbitrary-world viability. See [the milestone plan](SOCIETY_ITERATION_PLAN.md) and batch reports 001–010.

## Launch and inspect

Build the authoritative module, host/MCP/participant agent binaries, and foundation client before freezing an implementation. `scripts/experiment_artifacts.py freeze output/society-lab/implementations/<new-id> --label <new-id>` copies source, configs, executable artifacts and viewer assets, with file hashes. Bundles include uncommitted working-tree changes; a base Git commit alone is not their identity. Existing bundles cannot be overwritten by this command.

`scripts/run_experiment_batch.py configs/experiments/campaign/<manifest>.json --output output/society-lab/batches/<new-id>` starts one to four isolated authority databases and hosts, waits for readiness, then releases their clocks together. The manifest pins implementation, scenario, controller configuration, hypothesis and evaluation criteria. `calls_per_actor: 0` disables the call cap. A supplied `recovery: true` enables controller feedback and behavior reconsideration in implementations that support it. A variant's `serial_ms` overrides the batch's post-completion interval (minimum 1000 ms); it applies equally to its built-in and external actors and is recorded explicitly.

`cargo run -p bridge --bin sao-experiment-lab` opens the dashboard. Its map URLs proxy registered local hosts; the dashboard itself never steps worlds or controls NPCs. Dashboard frames use the current common viewer; direct host URLs retain each experiment's frozen viewer until replaced with an archive viewer.

At completion the supervisor pauses the authority, stops external workers, revokes built-in controller grants and captures `final-snapshot.json` directly from the database. Original periodic exports remain available, but comparisons prefer this stable final capture. `scripts/summarize_society.py <session-output>` checks food conservation and reports actual social effects, model usage and provenance. Gross gather/deposit totals include reuse and must not be treated as production. `scripts/park_completed_hosts.py` converts completed local hosts to lightweight archive viewers, preserving the original authority module/database and snapshot hashes.

## Shared simulation contract

All actors use the same Rhai skills and authoritative effects. Giving and public deposits conserve food. Shelter construction costs energy, helps all occupants, improves rest, and can protect against forecast cold. Death is permanent. Eating carried food and resting are allowed away from camp. In m1-18, normal settlement seeds include explicit, versioned starting habits. These are ordinary validated participant policies: they act immediately, incur the same costs for human and AI controllers, and can be kept, patched or replaced through the normal API. An empty-policy control remains available; the engine never reinstalls a starter after a policy fails. Earlier unseeded trials retain their original inputs.

In m1-17, configured food sources produce through an elapsed-time Rhai law. Production is recorded separately from conserved transfers; occupants perceive growth locally. Green bars below source tiles distinguish renewable sites, while shelter appears above tiles.

In m1-16, gradual cold and starvation reduce health without resetting action progress. Sudden attacks/site hazards still interrupt, and death stops action. Earlier frozen implementations preserve the former all-damage interruption rule.

Each character retains direct local observations independently of short recent memories. Atomic reads capture private context and trace together, retaining bounded evidence for slow deliberation. Learning still checks ownership, revision, source provenance, duplicates and newer conflicting observations. Mechanical damage can currently invalidate an in-flight learning revision; this limitation is recorded in trial evidence.

`guard` checks an ongoing condition. Current `when` semantics commit on entry. In `m1-15-intents.1`, priority preemption suspends lower sequences and their entry commitments; they resume afterward. False continuous guards and failed sequences still cancel their branches. Earlier frozen implementations retain their earlier interruption semantics.

Controller feedback contains the unchanged failed model output and precise error, separate from world experiences. Recovery schedules a fresh model decision; it does not repair a tree or silently refresh a stale proposal. Recent activity summarizes only that actor's own outcomes and net local food changes. The character chooses what those observations mean and what to do next.

## Starting habits

`python3 scripts/prepare_settlement_scenario.py` resolves four reusable profiles for the settlement home: builder, reserve keeper, shared provider and cautious observer. Definitions live in `scripts/starting_behavior_presets.py` and the generated catalog `configs/behaviors/settlement-starters-v1.json`. Scenario `starting_behaviors` maps actor IDs explicitly to `{id, revision, description, tree}`; names, motives and controller types never select a hidden engine role. The renewable and finite seeds include those habits; `settlement-renewable-empty.json` is the matched empty-policy control.

Starter provenance appears in the owner’s context and experience trace, and in the observer inspector. It describes where the policy began, not what the person must continue doing. Tree shape, condition limits, destinations and actor scope pass the same validation as later participant decisions. Invalid seeds reject initialization. Seeded construction or reserve keeping is evidence of execution, not spontaneous model invention or emergent specialization.

The m1-18 validation run passed 120 tests: 81 authoritative simulation, 31 bridge/provider, five host boundary, one archive compatibility and two client checks. The seven startup tests cover first-update execution (including the real settlement seed), human/AI cost parity, private provenance across server-style reload, invalid actor/tree/destination and arena scope rejection, and durable participant replacement/patching. Authority release WASM, host/MCP/external agent and browser client builds passed. Live starter behavior and model evolution are evaluated separately in batch 010.

Patch-path caveat found in batch 010: `/guard` selects a guard’s child, and `/when` selects a when-node’s child. Replacing a condition requires replacing the containing guard/when node. A valid nested patch can leave the original condition in force, so an accepted receipt is not proof that the stated behavioral change happened. Inspect the resulting tree and subsequent actions.

After completion, the checked-in 009/010 manifests reference their frozen scenario/controller files for future fresh-model repeats; their original batch manifests and resolved input hashes remain untouched. Choose a new output directory for a repeat. The common dashboard viewer also has a presentation-only correction replacing old fixed six-arena labels with generic world-area labels; frozen trial bundles retain their original viewer assets.
