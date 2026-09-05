# Running the M1 simulation proof

M1 is a small survival simulation inside the existing SpacetimeDB module. [simulation/src/lib.rs](../simulation/src/lib.rs) owns the rules; [foundation.rs](../server/module/spacetimedb/src/foundation.rs) invokes them transactionally. The runner never steps a second local simulation. The Rust [sao-sim](../server/bridge/src/bin/sao-sim.rs) binary publishes unique local databases, calls reducers, performs asynchronous model requests, and exports evidence. Its HTML inspector is an operator tool, not a replacement for the Bevy game client.

This is the foundation path for future gameplay. The old voxel/3D client has been removed. Legacy `Player`/`Npc` server reducers have not been migrated; their respawn, skill and evaluator limitations still apply to that prototype. Use the commands below for headless M1 checks. `just client` now opens the supported 2D foundation client; the original bridge binary still targets legacy reducers.

The current module/SDK moved to 2.1.0 for the [browser Bevy client](BEVY_BROWSER_CLIENT.md). Historical verification reports retain their original 2.0.1 versions. Use a separate 2.1.0 data directory; do not point the new binary at retained 2.0.1 experiment storage.

## Start local services and build

Use a SpacetimeDB **2.1.0 server** matching the module/SDK. The runner uses CLI JSON SQL output, verified with **CLI 2.7.1**; generated Rust bindings still use the **2.1.0 CLI**. Versions can coexist; set `SPACETIME_CLI` to the desired CLI executable without changing your global default. The core uses serde, serde_json and bonsai-bt; the native reasoning service also enables Schemars to derive the provider output schema from authoritative types.

Start an isolated server in a terminal (use the installed 2.1.0 binary if your default differs):

```bash
mkdir -p output
# Example installed version path on macOS:
~/.local/share/spacetime/bin/2.1.0/spacetimedb-cli start \
  --listen-addr 127.0.0.1:3101 --data-dir output/m1-server-2-1
```

In another terminal, start `ollama serve` if it is not already running. `ollama list` shows installed models; the verified runs used `qwen2.5:7b`. A model must be installed before a live run. Then:

```bash
just sim-build
export SIM_SERVER=http://127.0.0.1:3101
just sim-run scenarios/survival.json output/my-first-run qwen2.5:7b 18877
```

Open [the loopback inspector](http://127.0.0.1:18877) while the command runs. Each output directory must be new. Each run creates a unique `sim-...` database and refuses to overwrite an existing run; it never publishes to `slop-art-online` or a remote server. Startup/model failures are reported, not silently treated as successful experiments. If a port is occupied, choose another; a failed startup can leave an initialized database and manifest for inspection/export.

The simulation advances at one logical tick per runner iteration, with a default 1000 ms delay plus command overhead. `SIM_TICK_MS=2000` gives a small local model more wall time between world steps. Model requests are asynchronous; behavior continues while inference is pending. HTTP requests time out after 90 seconds, and model proposals expire after 30 simulation ticks or an incompatible behavior generation change. Damage preserves installed reactive policies and pending requests; generation now identifies approach replacement. The reasoning service cancels local waits when a request becomes invalid or the run stops, then drains recorded outcomes before exiting. A provider may continue processing remotely; see the reasoning runbook.

## Select the NPC model backend

The local positional command above remains supported. For explicit per-run configuration, use `just sim-run-config scenarios/survival.json output/my-run configs/reasoning/ollama.json 18878`, or select `configs/reasoning/openrouter.json` after setting its credential environment variable. Generic Chat Completions endpoints use `configs/reasoning/openai-compatible.json`; the credential-free local compatibility example is `configs/reasoning/openai-compatible-local.json`. Read [NPC reasoning backends](NPC_REASONING.md) for explicit routing, capability validation, deadlines, journals, and archive compatibility.

## Developer inspection and human-intent testing

These browser controls are developer experiment tools. Product observation and human participation must be native to the Bevy client and are not yet wired to the foundation; see the [next integration slice](CURRENT_STATE.md#native-client-integration-remains-open).

The developer world map shows observer truth. Selecting a player shows their permitted decision context, including needs, personality, beliefs, remembered perceptions, relationships, and current sequence. The event filter exposes the same IDs as structured queries. Select an event and follow its parent buttons to inspect causal evidence.

Select **You · human**, expand **Participate as a human-controlled player**, choose a purpose and skill, and submit. Free-form speech uses your exact text. Submission is not success: inspect `human_input`, `decision` or `intent_rejected`, then `skill_attempt` and `skill_result`. Food, range, energy, progress and death rules are identical for AI and human controllers. The run operator controls its human character; multi-account gameplay authorization is outside this operator proof.

The operator endpoint is loopback-only, requires a custom request header, and rejects cross-origin mutations. Database state/audit tables are private; run mutations require the run creator's identity. Observer data is not fed back to model prompts: the kernel builds an explicit subjective-context allowlist.

## Parallel experiments and comparison

Run these in separate terminals against the isolated server:

```bash
SIM_TICK_MS=2000 just sim-run scenarios/survival.json output/baseline qwen2.5:7b 18877
SIM_TICK_MS=2000 just sim-run scenarios/scarcity.json output/scarcity qwen2.5:7b 18878
```

Then compare retained results:

```bash
cargo run -p bridge --bin sao-sim -- compare output/baseline output/scarcity > output/comparison.json
```

The comparison reports event counts, survival/resources, identity and belief differences, and identity event IDs for drill-down. These are descriptive outcomes, not proof of statistical significance or a preferred story. Concurrent databases and model responses remain run-scoped.

Each output directory contains `manifest.json` (resolved scenario, seed, model, clock delay, rules version, Git baseline, CLI version, module SHA-256), `module.wasm` (published executable for new runs), `model-catalog.json` when available (including installed model digests), `snapshot.json`, `events.jsonl`, and a final `summary.json`. Actual prompts, sampling settings, raw outputs, provider responses, failures and elapsed times are retained in audit events. Source is uncommitted during development; the executable hash is the exact implementation identity, not the Git baseline alone.

World rules currently make no random draws; the seed is retained and supplied to Ollama, not claimed as a guarantee of determinism. Fresh model calls can differ. Logical timing and actual decisions are recorded, and unit tests verify a bounded snapshot continuation. There is no general recorded-decision replay or cross-version state migration engine yet.

## Reopen history without a model or advancing time

```bash
just sim-inspect output/baseline 18877
```

The inspector labels this **archived · read-only**. It reads the retained files, needs neither Ollama nor an active DB, and disables character actions. To re-export from a still-available database using its saved manifest:

```bash
cargo run -p bridge --bin sao-sim -- export output/baseline
```

`sim_run` and `sim_audit` have no TTL or death cleanup. Exported history also outlives character memory, process shutdown, and the local service. Retention is explicit: keep the database data directory and output directory until intentionally removed. Files under `output/` are local artifacts, ignored by Git; back them up if a worktree will be removed.

## Validation

```bash
cargo test -p simulation --lib
python3 scripts/verify_m1.py
python3 scripts/verify_reactive.py
cargo check -p client
```

The integration script publishes two new local databases and verifies real reducers, auth/privacy, isolation, controller parity, sequences, failure, free speech interpretation, identity change, death and causal links. Its model decisions are explicitly labeled fixtures. Deterministic fixtures are now test-only; the live runner accepts real native Ollama, OpenRouter, or generic Chat Completions configurations. Neither fixtures nor mock HTTP adapters validate live intelligence. See [verification results](M1_VERIFICATION.md) for the separately recorded live-model proof and limitations.

Current LLM-generated policy semantics and persistence are documented in [Reactive policies](REACTIVE_POLICIES.md); legacy sequence archives remain read-only and unchanged.
