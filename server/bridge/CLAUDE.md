# LLM bridge guidance

The Rust bridge connects pending SpacetimeDB decisions to model reasoning above real-time behavior execution. Read the [simulation vision](../../docs/SIMULATION_VISION.md), [audit/experiment contract](../../docs/AUDIT_AND_EXPERIMENTS.md), and [verified gaps](../../docs/CURRENT_STATE.md). [ADR 005](../../docs/adr/005-npc-architecture-v2.md) retains the old design rationale; its template-first conversation and fixed call quotas are superseded.

## M1 operator and model runner

[sao-sim.rs](src/bin/sao-sim.rs) drives isolated SpacetimeDB foundation runs and async NPC reasoning through [reasoning/mod.rs](src/reasoning/mod.rs). Typed native Ollama, OpenRouter, and generic Chat Completions adapters own provider protocols; the simulation remains authoritative. See [backend configuration and evidence](../../docs/NPC_REASONING.md). It never runs a second local world. [inspector.html](inspector.html) renders exported common evidence and supports the run operator’s human input. Follow the [runbook](../../docs/M1_RUNBOOK.md) for commands and [verification](../../docs/M1_VERIFICATION.md) for results. `cargo run -p bridge` still selects the original bridge by default.

## Legacy bridge source structure

| Source | Responsibility |
|---|---|
| [main.rs](src/main.rs) | Subscribes to `NpcPendingDecision`; queues and handles requests, calls submission reducers |
| [llm.rs](src/llm.rs) | Ollama HTTP requests and response parsing |
| [prompt.rs](src/prompt.rs) | Prompt construction |
| [tools.rs](src/tools.rs) | Tool definitions, currently unused/reserved |

| Routed type | Handler | Submission reducer |
|---|---|---|
| `tree_generation` | `generate_tree` | `submit_npc_tree` |
| `experience` | `generate_experience_eval` | `submit_npc_identity_update` |
| `conversation` | `generate_conversation` | `submit_npc_speech` |

These routes exist; they do not certify every trigger or resulting behavior. Today's bridge processes its queue sequentially. Multi-worker claim/lease coordination and cloud backend routing are not implemented by these files.

Current failure submissions are an empty tree string, `{}` for identity, or “Hmm...” for speech. An invalid tree keeps the current tree and clears the pending row; the tick uses a role default if no parseable tree is available. This is source behavior, not evidence of complete retry/recovery or meaningful conversation during outages.

## Configuration and local use

`HOST` (`http://localhost:3000`) and `DB_NAME` (`slop-art-online`) are constants in `main.rs`, not environment overrides. `llm.rs` reads `OLLAMA_URL` (default `http://localhost:11434`) and `OLLAMA_MODEL` (default `qwen2.5:7b`). Run `cargo run -p bridge` after publishing a matching module. See [README](../../README.md#quick-start) for setup.

Scenario tooling needs configurable isolated destinations and request/output routing before concurrent runs are accepted. Do not assume multiple bridge processes pointed at the same pending table are safely coordinated.

## Target reasoning and evidence contract

Free-form communication is required from the first slice. Preserve full expressive text within validated speech actions; do not gate novel phrasing behind template failure, “important NPC” tiers, or a fixed percentage of exchanges. The behavior layer can manage timing/reactivity while model reasoning interprets experiences and revises approaches.

Support reconsideration driven by lack of progress and individual introspection as well as external experiences. The exact trait/scheduling link remains open. Fixed call budgets are tuning choices to evaluate after the small proof, not substitutes for required behavior.

Build model context from authorized character perceptions and relevant subjective state. Observer world truth and external audit history are not unrestricted character memory. Retain the actual supplied prompt/context, returned output, parsed decision, concise reported explanation where provided, model/config/prompt/behavior versions, and request/result links. Explanations are not hidden chain-of-thought or proof of world causation.

The authority owns accepted state changes. Parsing is not enough: correlate requests and versions, reject stale/unauthorized responses, validate skills and references, and record errors/fallbacks distinctly. Replaying recorded decisions is different from fresh model calls; the same seed does not guarantee identical output.

Keep game state in SpacetimeDB and the bridge focused on model transport/routing. Add durable evidence and run isolation with the core/tooling contract rather than embedding a separate simulator in this service.
