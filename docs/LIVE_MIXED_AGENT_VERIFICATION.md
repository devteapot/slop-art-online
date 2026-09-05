# Live mixed internal/external agent session — 2026-09-05

A genuine mixed session was executed and is visible at [the Bevy client](http://127.0.0.1:18892). Run `sim-bevy-1788600396336` in isolated database `sim-bevy-db-1788600394809` is **paused at tick 7 of 24**. The bounded inference processes have finished; installed trees remain available for further operator stepping. Human participation remains available through the existing Bevy controls. The previous 18890 and 18891 sessions were preserved.

## What actually ran

Both participants requested and were served **gpt-5.6-luna** through the existing configured Carlid streaming Chat Completions route. All **10 genuine model calls** completed with HTTP 200, finish `stop` and stream DONE. These comprise six planned responsibility calls and four explicit fresh correction calls. The provider reported 66,028 total tokens across the ten responses, including reported input/output usage; this is not a billing estimate. The endpoint has no provider-enforced token cap. Each call had one attempt and a 300-second wall deadline. No authored policy, canned dialogue, mocked response or silently repaired model output was submitted.

- **Mira / internal NPC:** the production built-in `deliberate_once` harness, using only its authenticated `ParticipantService` view and reducer.
- **Tovan / external AI player:** a separately launched minimal Rust model-driven runtime, invoking the actual MCP stdio process with discovery, tool listing, observation and mutation calls. The runtime owns its model call and proposal interpretation. It reconnects with the same scoped participant session across bounded phases. It is a custom verification runtime, not evidence of Codex/Claude/Hermes or any other packaged client's compatibility.

Both runtimes receive only their own character's subjective context. The external MCP child does not inherit the provider credential. The authority, skills and ownership checks are shared. The phase launcher uses operator credentials only to start an isolated world and advance its clock; those capabilities are not supplied to either model.

The scenario starts the characters together and sets environmental hazards to zero, retaining shared gathering, food, energy, hunger and skill rules. This deliberately tests live integration and communication, not hazardous-world survival quality. Time was advanced in bounded controlled steps, not an unattended continuous session.

## Observed behavior

| Character | Actual skills through tick 7 | Independent learning |
|---|---|---|
| Mira | Gather at tick 2, eat at 3, move to 1 at 4 and 2 at 5, gather at 6, eat at 7. | Caution 65 → 64, trust toward Tovan +1, eastern-food belief grounded in own site perception #98, revised foraging goal. |
| Tovan | Gather at ticks 2 and 3, eat at 4–6, begin move toward 2 at 7; ends at position 1. | Caution 25 → 26, trust toward Mira +1, eastern-food belief based on hearing Mira #111, revised scouting goal. |

Both remain alive at health 100. Both policy revisions remain **1** while learning revisions independently advance **0 → 1**. Policy execution continued at ticks 6–7 after learning. The generated policies are not uniformly good: Tovan eats whenever it has food, consuming supplies after hunger is already low. This proof establishes accepted model decisions and shared execution, not robust or optimal autonomous behavior.

During the dialogue phase, the authority advanced ticks 2–4. Both model processes were still pending for the first two steps; the internal call remained pending for the third. The installed trees gathered and ate during those delays without waiting for dialogue generation. There was no tree replacement for speech.

At tick 5, after movement:

- Mira's speech **#110**, from position 2: “Tovan, there is food here. I also heard there may be more at the eastern clearing; stay alert while we forage.” Tovan heard it as **#111**.
- Tovan's speech **#113**, from position 0: “I found food here and have eaten. I’m heading east to check the reported clearing; stay alert.” Mira heard it as **#114**.

Both were within distance two. The human character also heard both. Learning events **#119** and **#121** cite retained own outcomes and those speech perceptions. Hearing alone did not copy beliefs; separate generated reflections changed each individual's state.

## Failures and corrections retained

1. Mira's first generated tree used `duration: 0`. The authority rejected it unchanged. The supplied schema exposed only an unsigned integer, omitting the existing authority bound. Added the schema range **1–5**, retained authority validation, and made the responsibility schema narrower. A fresh Mira generation was accepted.
2. Tovan's first behavior response included extra speech and learning operations. Its tree had already been submitted and accepted before the external runtime hit the invalid phase operation. The runtime now validates the whole proposal's responsibility before any submission. Both runtimes' generated schemas expose only the current responsibility's operations. The originally accepted tree was not rewritten or replaced.
3. Tovan's first independent speech selected expiry tick 2; the clock advanced before it arrived, so the authority rejected it. A fresh call from updated state chose expiry 10 and was accepted. The runtime did not silently extend the rejected utterance's expiry.
4. Both first learning batches were rejected atomically. Mira used cursor numbers in place of event source IDs; Tovan included its own speech emission, which is not an eligible observation/outcome. Grounded the model schema's source-ID enum in the same scoped observation and clarified trust requires a perceived counterpart. Both fresh learning calls were accepted. The failed batches changed no character state.

These are four authority rejections plus one external runtime phase error. They are preserved alongside the successful corrections; initial protocol success is not mislabeled as successful application behavior.

## Evidence and checks

Primary report: `output/mixed-live-luna-20260905/sim-bevy-1788600396336/verification.json`.

The same directory retains the resolved scenario, authority module, lockfile, full snapshot/audit, each actual request and response under `live-inference`, MCP discovery/results, model-reported usage, concurrent-step process status, and final runtime source/binary hashes. `scripts/summarize_mixed_live.py` checks ten completed genuine calls, actor scope, accepted trees/speech/learning, unchanged policy revisions, concurrent effects, final state and preserved services.

`cargo test -p simulation -p bridge -- --test-threads=1`: **66 passed** (35 simulation/projection, 30 bridge/provider/schema, one archive compatibility). One existing 300ms cancellation timing check failed during an earlier parallel run under load; its targeted rerun and the final full serial suite passed. New regression checks cover responsibility-restricted schemas, the authoritative duration range, and source IDs versus cursors/ineligible speech. Agent/host builds and Python syntax checks passed. Actual browser inspection confirmed live-model mode and final learned state at tick 7. Earlier native/WASM/legacy builds and participant access checks remain documented in [participant verification](PARTICIPANT_AGENT_VERIFICATION.md).

No commits, pushes, merges, proxy restart, production deployment or old-session replacement were performed.

## Bounded reproduction tooling

`scripts/run_mixed_live.py host` safely loads the existing credential and starts port 18892 with `SAO_HARNESS_MANUAL=1`: no automatic inference loop and no fixture installation. The `behavior`, `communication` and `learning` phases each launch distinct internal/external processes. `step --steps N` advances at most ten ticks per invocation. `--side internal|external --attempt 2` records an explicit correction in a separate directory; it is not an automatic retry. Existing phase directories are never overwritten. The script pins this proof's output directory and refuses to recreate it; use a separately named experiment directory/port when preparing a new experiment.

The development host now accepts `BEVY_DEV_OUTPUT`, `BEVY_DEV_SCENARIO`, `BEVY_DEV_MAX_TICKS` (1–300) and `SAO_HARNESS_MANUAL=1` for isolated bounded verification. The existing default host behavior remains available. Connecting an MCP server alone still does not schedule a full external agent; this proof's launcher explicitly scheduled the bounded external runtime phases.
