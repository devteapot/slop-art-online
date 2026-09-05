# Living clearing pilot

First run, September 5, 2026: two genuine hosted AI participants, differing motives and incomplete knowledge, finite shared food, mild eastern hazard, and a human character. The existing Rust bridge and external MCP participant use the same authoritative Rhai skills. No fixture policy or model-readiness pause is inserted.

The requested observation cap was shortened from 20 minutes to **five minutes total** during the run. The world ended earlier: all characters were dead after **217.546 simulation seconds**, with the supervisor finishing after **218.985 wall seconds**. Permanent death is an outcome, not a reason to restart or silently improve a policy.

The retained Bevy client is at **http://127.0.0.1:18908/**. It displays the finished, paused run; it is no longer a live advancing simulation. Use **Inspect [I]** to examine the selected character's policy and history. This is a local service, not a published internet deployment.

## Observed results

| Character | Observed outcome |
|---|---|
| Mira | First policy accepted at 67.388 simulation seconds. Its westward movement branch required `at(0)` continuously; after moving to -1 the guard became false. She waited between sites and died from starvation at 217.546 seconds. A later behavior revision was still pending when she died. |
| Tovan | First policy accepted at 37.199 seconds. Reached eastern food, gathered and spoke, but had no hazard-escape branch. Environmental damage killed him at 127.541 seconds. |
| You | Uncontrolled during this observation; no survival immunity or hidden policy. Died from starvation at 155.018 seconds. |

Both initial generated policies were accepted and executed. Seven participant calls started: five processes succeeded; one learning call was terminated after death, and Mira's final behavior call returned a cancellation error when the character stopped. The journals preserve partial responses. The run recorded two speeches, 61 identity-change events, 102 skill-result events, no participant-command rejections, no script errors and no failed script updates. Identity-change counts include scripted responses to damage; they are not a count of model-authored reflections.

These findings establish live integration, not successful adaptive survival. Next use-case experiments should probe guards that stay valid during multi-step movement and reaction to newly learned hazards. Guard persistence must be taught or made explicit in the behavior-authoring interface; the authority must not silently rewrite a model's chosen tree to make an experiment succeed.

## Timing evidence

The authority used SpacetimeDB's native 50 ms interval schedule and an optimized WASM module. The release preflight measured **18.606 updates/sec** and a simulation/wall-time ratio of **0.997**. Across pilot observation samples, with actual model calls and a browser observer, the measured rate was **15.576 updates/sec**, while simulation time tracked wall time at **0.995**. The 20 Hz setting is a target; sustained 20 Hz under observer load is not established. The simulation never waited for model output or changed speed to accommodate it.

This is a three-character bounded run using the current serialized-world adapter. The measured throughput gap warrants profiling reducer evaluation and observer projection/persistence before a larger population. See the [timing contract](SIMULATION_TIMING.md) and its official SpacetimeDB references.

The pilot's immutable module and initial definitions identify **`m1-7-time`**. Subsequent source **`m1-7-time.1`** separates continuation wakeups from committed cooldowns, so cancelled rest does not block movement and completed rest/wait adds no extra duration. It also wakes behavior after accepted participant edits. This correction is verified separately; it was not silently injected into the finished pilot. The archived module remains the authority for explaining that run.

## Retained artifacts and repeat runs

Local evidence directory: `output/living-clearing-20260905/`.

- `pilot.json`: original plan, actual calls, revised duration and final status.
- `stop-request.json`: the user's five-minute cap and its absolute deadline.
- `observations.jsonl`: sampled time, update count, character state and event counts.
- `sim-bevy-1788613563373/`: actual scenario, module, lockfile, final snapshot, audit and model journals.
- `browser-finished.png`: verified Bevy view of the finished run.

Database: `sim-bevy-db-1788613563147`; run: `sim-bevy-1788613563373`. Private controller session files and the provider key remain under the ignored `.local/credentials/`, outside run evidence.

For another pilot, choose a fresh directory and available port. The default observation cap is now five minutes; `--minutes 20` explicitly requests a longer experiment. Runs also stop when both AI characters have died. Build current source first:

```sh
cargo build --locked --release -p server_module --target wasm32-unknown-unknown
cargo build --locked -p bridge --bin sao-dev-client --bin sao-agent-mcp --example participant_live_agent
cd client
env -u NO_COLOR trunk build --cargo-profile wasm-dev --dist dist-participant
cd ..
python3 scripts/run_living_clearing.py --output output/living-clearing-next --port 18909 --minutes 5
```

The launcher uses the existing credential loader and explicitly selects/archives the release module. It limits the run to 36 provider calls by default, one attempt each, with a 300-second per-call deadline and no provider output-token cap. This bounds observation cost, not character powers or world time. The host stays available after the supervisor pauses the run.
