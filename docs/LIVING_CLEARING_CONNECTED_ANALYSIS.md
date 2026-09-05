# Connected five-minute pilot analysis

The run displayed after the browser connection repair was `sim-bevy-1788614916089`, in `output/living-clearing-20260905-connected/`. This report analyzes that run. The earlier attempt in `output/living-clearing-20260905-second/` is a distinct experiment and is not combined with it.

Evidence: `pilot.json` for call timing; the run's `snapshot.json` for the complete 5,800-event archive and final world; `live-inference/` for supplied contexts, model proposals and authoritative receipts; `observations.jsonl` for sampled progression. `metrics.json` is the last periodic sample, approximately 2.5 seconds before completion, rather than the final state. The archived authority used `m1-7-time.1`.

## What happened

| Simulation time | Outcome and evidence |
|---|---|
| 31.4 s | Tovan installed an eating/resting/foraging policy (#58). He gathered all six camp food units, then reached the eastern clearing at 37.7 s. His tree had no escape branch for danger or low health. |
| 37.7 s | Tovan announced his scouting plan (#214). Mira and the human heard him. |
| 40.0 s onward | The clearing inflicted three damage every 2.5 seconds. Scripted damage reactions corrected Tovan's belief to dangerous and increased caution, but his installed tree continued gathering and resting there. |
| 48.9–52.4 s | Mira installed her first tree (#412), initially attempted gathering from a stale camp observation, then moved one cell west (#667). Her movement guard required being at camp; after reaching -1, that guard became false and the fallback selected waiting. |
| 60.0 s | Mira spoke to Tovan about going west (#843). He was three cells away, beyond hearing range; the human heard her. |
| 110.9 / 118.1 s | Tovan's and Mira's first learning submissions were rejected (#1858, #2017). |
| 122.6 s | Tovan died from the eastern hazard (#2120), carrying 40 food. His caution had risen from 25 to 93. He never installed another behavior tree. |
| 155.0 s | The human character died from starvation (#2460), still carrying two food. No human skills executed in this run. |
| 173.3 s | Mira's model patched the fallback from waiting to moving west (#2625). She reached -2, gathered, ate and recovered from her prolonged stall. This was a successful model-authored repair while the world continued running. |
| 228.4 s | Mira announced her discovery (#3829). Both other characters were already dead, so this produced no listener perception. |
| 255.5 s onward | Mira exhausted the 30 western food units. Her return branch required being at -2; at -1 it became false and the patched fallback sent her west again. She oscillated between -2 and -1, with energy recovery and eating interrupting the loop. |
| 291.0 s | Mira's second learning batch was rejected (#5551), although its explanation correctly described oscillation and interrupted recovery. |
| 300.061 s | The configured cap stopped the world (#5797). Mira remained alive: health 100, hunger 50, energy 3, food 26, position -1. |

Mira completed 30 gathers and six eats, but also recorded 102 failed skill results with the combined reason `no food here or insufficient energy`. This is survival with an inefficient policy, not a reliable foraging loop. No relationships changed. Three speeches and scripted danger learning do not establish effective cooperation or accepted model-authored reflection.

## Learning contract failures

All nine controller processes completed successfully, but only six of their nine submitted operations were accepted: two tree installations, one patch and three speeches. All three reflection operations were rejected. Process completion and a model's reported explanation must not be counted as successful state changes.

Mira's first reflection cited source #416, supplied at experience cursor 10 in a context taken at 105.195 seconds. At submission, her cursor had advanced to 278 and the 256-entry trace retained only cursors 23–278. The source had expired during reasoning. Her second context ended at cursor 1631; at submission the retained window was 1583–1838, again excluding several supplied citations. These were real, supplied sources, not invented IDs. The current validator requires sources to remain in the live trace when the answer arrives.

Tovan began learning at 83.031 seconds with learning revision 18 and health 46. Damage continued updating his identity during the roughly 28-second call. By submission, the revision was 29, so the revision-18 proposal was rejected. The protection against overwriting newer state worked, but there was no successful refresh/reconciliation afterward.

The next contract should preserve scoped evidence references for an in-flight request independently of the short display trace. It should also define how delayed reflections reconcile with newer automatic state changes, retaining source authorization, duplicate protection and conflict checks. Increasing the trace limit alone would postpone this failure rather than define that contract.

## Controller and behavior boundaries

The pilot worker performs initial behavior, then rotates communication, learning and behavior with a 45-second wait after each role. It does not prioritize fresh injury or a stalled policy. Tovan died before his next behavior turn; Mira remained between sites for roughly two minutes before a patch arrived. This schedule is a pilot orchestration choice, not a world timing requirement.

Reactive guards are continuously rechecked. A condition describing where an action starts is often unsuitable as a condition for continuing it. Both of Mira's movement problems expose this authoring distinction. The engine should keep executing the submitted semantics; authoring diagnostics and explicit entry/continuation conditions should make these consequences inspectable. A focused movement use case should demonstrate reaching a multi-cell destination while still allowing a higher-priority emergency to interrupt it.

Tovan's injury changed his beliefs, but his policy never consulted danger. This shows that subjective state and action execution are connected only where the authored policy or a later controller update makes that connection. Event-triggered, bounded reconsideration and authored local danger responses are candidates to evaluate without pausing the world or silently repairing a model's choices.

## Runtime evidence and limits

The world advanced 300.061 simulation seconds over 300.225 seconds from supervisor start to completion. It did not wait for model replies. Initial policies arrived after roughly 31 and 49 seconds, and the needs clock continued throughout that delay.

The authority recorded 4,270 updates: **14.23 updates/sec** averaged over simulation time, against the native 50 ms / 20 Hz scheduling target. Observation samples measured about 17.4 updates/sec in the first minute and 12.8 in the last. There were no recorded script errors or failed script updates. Correct elapsed time does not establish the target update throughput.

The decline warrants profiling reducer evaluation, archive growth, serialized-world persistence and observer projection. This run does not isolate which cost caused it, and three characters cannot establish scalability. The label rendering fix was verified separately and should not be credited with changing this completed run's measurements.

Before extending duration or population, prioritize: (1) usable evidence and revision semantics across asynchronous learning; (2) behavior authoring checks for interrupted movement and depleted destinations; (3) controller wakeups driven by consequential experiences within an explicit budget; (4) profiling the update-rate decline. A focused repeat should observe an accepted delayed reflection, a completed multi-cell trip and a policy response to newly perceived damage while simulation time continues independently.
