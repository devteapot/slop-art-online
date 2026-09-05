# Scripted gameplay foundation

Rules version `m1-6-rhai`, implemented 2026-09-05 under [ADR 016](adr/016-scripted-gameplay-rhai.md). The current foundation game executes Rhai inside the authoritative SpacetimeDB module. This migrates the active survival/participant game, not the retired server prototype.

## Ownership

| Layer | Current responsibility |
|---|---|
| [Bundled skills](../simulation/scripts/) | Movement, gathering, eating, resting, waiting, speaking and attacking; their parameter validation, costs, formulas, effects and continuation behavior. Queued dialogue invokes the same speaking definition as behavior trees. |
| [World laws](../simulation/scripts/law.rhai) | Metabolism, starvation/hazard consequences, damage response, reflection formulas, visibility, observation content, memory retention, reconsideration interval, bootstrap choice, subjective guard evaluation, condition ranges, dialogue expiry and edit/effect authorization. |
| [Rhai registry](../simulation/src/scripting.rs) | Versioned source, dependencies, active definitions, bounded interpretation, plain-data conversion and disposable compiled caches. |
| [Engine adapters](../simulation/src/scripted_world.rs) | Scoped facts/effect capabilities, authoritative validation and atomic commit, failure records and activation boundaries. Rust still owns identities, storage, scheduling, tree traversal and typed state/effect representations. |
| Client and controllers | Submit intentions and display authoritative results. Human input, built-in agents and external participants use the same actions. Prompts receive the active catalog and law description; their schema no longer fixes a gameplay duration range. |

The first capability vocabulary retains the existing game's positions, resources, damage, observations, speech and beliefs. It is intentionally bounded. Adding a new state/effect primitive still requires engine work; changing the existing skills and policy formulas does not. Scenario initialization retains the bounded fixture schema. This is not an arbitrary component engine or a migration of every historical reducer.

## Definition and invocation contract

Each installed definition has `id`, monotonically increasing `revision`, `source`, `description`, and pinned `dependencies: [{id, revision}]`. `law` is the active world policy bundle; other definitions are skills with `validate(context)` and `step(context)` entry points. The catalog exposes an invocation value, such as `{"script":"stride"}`, alongside its revision and authored description. Original skill strings remain compatible aliases into the same registry.

Scripts are function-only modules. Top-level statements are discarded and never executed; put reusable values inside functions. Declared dependencies are exposed as static namespaces (`move::step(...)`). Imports, runtime evaluation, ambient time, I/O, printing and uncontrolled randomness are unavailable. All script numbers are signed 64-bit integers; host fields retain their declared types. The adapter explicitly converts JSON values, including when bridge dependencies enable `serde_json/arbitrary_precision`.

`validate` returns an empty string for acceptance or a rejection reason. At execution, `step` receives the actor's mechanical facts, action arguments, current site's food, requested target's physical facts, explicit continuation state, remaining duration and the speech scheduler flag. Other characters' minds and observer history are absent. These are authority-owned definitions; this physical execution context is **not** a public player-authoring capability grant.

`step` returns plain data with:

```text
status: "running" | "success" | "failure"
reason: string
remaining: unsigned integer
state: serializable data
effects: array
progress: serializable data
```

Effects currently support actor `position`/`energy`/`food`/`hunger` patches, current-site food, observation, speech, and damage to the requested target. Engine checks prevent writes to another actor's private state or outside the granted target capability. Active `authorize_effect` runs before each effect against the preceding staged changes. A later rejection discards the entire invocation, including earlier changes and their tentative events. Failed results cannot carry effects. The engine records a failure the character can perceive.

Bundled definitions and the current law are operator-controlled. The initial `authorize_effect` permits effects from those installed definitions; it is **not** a complete cost/progression policy for hostile player-authored code. Public authoring must add scoped grants and law-enforced composition costs before that boundary is exposed.

## Editing a live run

The owner-authenticated reducer is `sim_stage_scripts(run, update_json_string)`. Its update payload is:

```json
{
  "api_version": 1,
  "expected_revision": 1,
  "definitions": [{
    "id": "move",
    "revision": 2,
    "source": "...complete revised Rhai module...",
    "description": "Updated authored behavior and requirements",
    "dependencies": []
  }]
}
```

Use the private operator CLI configuration described in the [browser runbook](BEVY_BROWSER_CLIENT.md). A safe way to submit a file without manually escaping its source is:

```python
import json, os, subprocess
from pathlib import Path
subprocess.run([
    os.environ["SPACETIME_CONTROL_CLI"],
    "--config-path", os.environ["SPACETIME_CONFIG_PATH"],
    "call", database, "sim_stage_scripts", json.dumps(run),
    json.dumps(Path("update.json").read_text()),
    "--server", "http://127.0.0.1:3101", "--no-config", "-y",
], check=True)
```

Validation uses the currently active law's edit policy; proposed rules cannot authorize themselves. Unknown APIs, stale revisions, concurrent pending updates, invalid entry points, missing/conflicting dependencies, cycles and storage limits reject the proposal. Authenticated content rejection is recorded as `script_update_rejected`; the reducer commits that receipt, so CLI success alone does not mean the definition was accepted. Check the audit and `scripts.pending`. Unauthorized callers receive a reducer error before any mutation.

Accepted changes activate together at the next tick. Every action pins its skill and dependency revisions at its first attempt, and reevaluates its next step under active laws. Explicit `state` and `remaining` survive database reloads; queued dialogue has independent continuation without replacing movement or its behavior policy. Completed consequences stay historical facts. A periodic-law exception rolls back the whole tick and clears the failed pending activation, retaining the old active registry. Action exceptions roll back their individual invocation and produce failure evidence.

Changing bundled files changes **new worlds** after rebuilding the module. Existing worlds retain their stored source; use the reducer to update them. Prior definitions are retained, not silently replaced or garbage-collected. Compiled ASTs are caches only. The existing whole-world row remains the storage adapter. Old rules versions are rejected for execution and remain inspectable as archives; no implicit `m1-5` migration is performed.

## Limits and next work

Each invocation allows 50,000 interpreter operations, 24 call levels, bounded expression depth, 8 KiB strings, 512-element arrays/maps and 128 variables. Input/output are capped at 64 KiB; output additionally has depth/node limits. Each action returns at most 32 effects and remaining duration at most 10,000. Definitions are at most 32 KiB; updates contain at most 32 definitions, with at most eight direct dependencies. The registry permits 64 active IDs and 256 retained revisions within a 1 MiB serialized budget. Exceeding a history limit rejects edits instead of deleting referenced content.

These limits support the current operator-authored slice. Aggregate interpreter allocations, total work across nested invocations, large populations and long-lived source history still need measurement and stronger accounting before public untrusted authoring. Cloning the bounded world for atomic evaluation and serializing its source registry are deliberate current costs. Language/runtime pins, source revisions and explicit state support reconstruction; universal cross-version replay is not claimed.

Player editors, authoring progression, divine authority, territorial rule composition and learning a new technique through communication remain future gameplay. This integration establishes the execution foundation they can use.

## Executed verification

- `cargo test -p simulation -p bridge -- --test-threads=1`: 45 simulation tests, 30 bridge tests, one archive test and four developer-host tests passed. The ten added scripting tests cover revised laws, pinned actions/dependencies, serializable composition state, active condition ranges, queued dialogue, private context, stale/cyclic edits and atomic failures/budgets.
- Actual `server_module` built for `wasm32-unknown-unknown`; Rust bindings regenerated for the new reducer. Native client check and Bevy WASM/Trunk build passed.
- [Real authority verifier](../scripts/verify_scripted_gameplay.py) exercised authenticated human/AI parity, denied participant installation, next-tick law activation, per-reducer reloads, new skill revisions, composed movement, queued speech and atomic effect rejection. Inputs were explicit fixtures, not fresh model inference.
- Actual browser input moved You from position 0 to 1 at tick 2; the saved energy changed from 65 to 64. Keyboard speech `Hi` appeared at tick 3. The linked audit records identify `move@1`, `speak@1` and speech event 77 in `sim-bevy-1788609676864`. Bevy rendered the authoritative result without browser errors. After the final client/module rebuild, another keyboard move was accepted at tick 4 and completed at tick 5 (position 2, energy 63), confirming the final bundle.

Local evidence is retained under `output/scripted-gameplay-authority/`, `output/scripted-gameplay-authority-final/` and `output/scripted-gameplay-dev/`. The earlier isolated language comparison remains in [embedding verification](SCRIPTING_VERIFICATION.md). To repeat the authority check, publish a fresh current module, then run:

```sh
SPACETIME_CONTROL_CLI="$HOME/.local/share/spacetime/bin/2.7.1/spacetimedb-cli" \
SPACETIME_CONFIG_PATH="$PWD/.local/credentials/bevy-cli.toml" \
python3 scripts/verify_scripted_gameplay.py --database "$DB"
```

The verifier creates a unique run and fresh participant identities; it never resets a database or prints tokens.
