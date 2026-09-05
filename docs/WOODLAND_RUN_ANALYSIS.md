# Woodland run: what changed from the clearing

Analyzed `sim-bevy-1788616907633`, the completed five-minute run in `output/woodland-pathfinding-20260905/`, against `sim-bevy-1788614916089` in `output/living-clearing-20260905-connected/`.

Evidence: each run's final `snapshot.json`, controller journals and authoritative receipts, `pilot.json`, and `observations.jsonl`. Final states below come from snapshots, not the last periodic metrics sample. Event numbers are scoped to the woodland run unless stated otherwise.

The main result is better communication and accepted learning, with no successful long-distance navigation by either generated policy. The evidence separates a model's failure to apply a retained lesson from a runtime's failure to retain facts used by an installed guard.

## Comparison

| Measure | Earlier clearing | Woodland |
|---|---|---|
| World | One spatial axis, three sites | 24×16 surveyed grid, walls and gaps, six sites |
| Characters | Two LLM characters and an idle human | One host-managed LLM NPC and one external MCP player; no human |
| Surviving LLM characters | Mira only | Mira and Tovan, both health 100 |
| Final carried food / energy | Mira 26 / 3; Tovan died carrying 40 | Mira 4 / 37; Tovan 1 / 43 |
| Gathered food | 70 total: Mira 30, Tovan 40 | 13 total: Mira 8, Tovan 5 |
| Learning submissions | 0 of 3 accepted | 3 of 4 accepted |
| Communication | Three speeches, no relationship changes | Six speeches, all heard by the other character; trust changed in both directions |
| Model calls | Nine | 17: 12 host, five external |
| Accepted submitted operations | Six of nine | 13 of 14; additionally two malformed outputs never reached authority, and one valid no-op |
| Reported model tokens | 149,977 total | 282,227 total |
| Authority updates/sec | 14.23 | 14.55 |

This is not a controlled improvement score. Starting local food increased from six units at one shared site to eight at each of two neighboring sites. The hazardous site is elsewhere on the new map and neither character encountered it. The old false safety report about the hazardous east clearing was replaced with a shared unverified report about a safe remote food site. Controllers, scheduling, terrain, initial knowledge, character positions and population changed together. Both configurations used the same Luna provider configuration hash. Fresh model responses remain stochastic.

Survival improved, but neither new character demonstrated a better response to danger. The run simply did not expose them to damage. All four remote resource sites remained untouched; together the characters occupied only cells 147, 148 and 124.

## Mira: a valid policy lost the facts it needed

Mira installed her first policy at 30.120 seconds (#48). She gathered all eight units at cell 147, then completed the single-cell move to 148 at 38.174 seconds. Site perception #191 recorded eight food there. Her initial fallback then waited.

Her next behavior call read its context at 45.144 seconds. That context still contained #191 in the character's short memory and in the larger experience trace. The model authored a policy to gather at 148, eat when hungry, rest below 30 energy and otherwise wait. It was accepted at 73.658 seconds (#814).

By acceptance, repeated wait results and communication had displaced #191 from the 16-entry `player.memories` list. Event #820 records the new gathering branch evaluating false at 73.726 seconds. Its conditions were `at(148)` and `food_at(148, 1)`. The character was at 148 and seven food remained, but `food_at` reads only the short memory list. Textual beliefs and the 256-entry participant experience trace are separate inputs; they do not satisfy that guard. Standing at the site does not itself refresh its resource observation.

This explains why Mira could describe a food supply and install a sensible local gathering branch, yet never gather at 148. It is a general perception/working-memory contract problem, not proof that a model cannot recognize food. It is also distinct from the earlier reflection-citation expiry: this time the policy submission succeeded, but its runtime facts had disappeared.

Mira made two further behavior attempts from contexts at 88.686 and 122.326 seconds. Both replies were malformed JSON (an extra closing brace), despite HTTP 200 and normal `stop` finish reasons. Neither reached the authority. The provider configuration uses `prompt_json`, not provider-enforced JSON schema. There was no successful late policy repair.

Both attempted patches also targeted `root/1/guard`, the child inside the existing `energy < 30` rest guard, and inserted another guard with thresholds 45 or 60. **Counterfactual code inspection:** even with the JSON syntax corrected, the unchanged outer threshold would still prevent the intended earlier rest. These proposals should not be described as successful repairs that were lost only to transport.

She completed 98 waits and six eats, and finished at cell 148 with health 100, hunger 50, four food and 37 energy.

## Tovan: the correct lesson was retained but not applied

Tovan installed his first policy at 39.957 seconds (#209). A branch guarded by being at 148 gathered one food and started movement to cell 92. Movement reached 124 at 40.978 seconds (#254); at 41.042 seconds the guard failed and the route was abandoned (#259).

At 130.379 seconds, his learning batch was accepted (#1632). It explicitly diagnosed the problem: a branch guarded by being at the departure cell cannot sustain movement away from that cell. It also recognized that waiting did not advance scouting.

The next behavior call began from a context at 175.611 seconds. The original interruption #259 had left its retained trace, **but the accepted identity-change event #1632, including the full diagnosis, was still supplied in that prompt**. The goal also said to verify cell 92 without abandoning the approach. This particular recurrence cannot be attributed to losing the lesson before the next call.

The replacement policy was accepted at 228.613 seconds (#4165). It fixed the missing-food prerequisite for eating and added a return-to-provisions branch. That was a useful partial adaptation after 115 failed eating attempts with no carried food. However, the move-to-92 branch again required `at(148)`. Tovan repeatedly returned to 148, gathered, moved one cell north and stopped at 124. Later route interruptions are visible at #4281, #4460 and #5171.

He finished with health 100, hunger 50, one food and 43 energy. His behavior improved food recovery but did not implement the movement lesson. Acceptance of a reflection is therefore a weaker milestone than applying it in a later policy.

## Communication and individual change improved

All six speeches have matching listener perceptions: #19→#20, #127→#128, #392→#393, #606→#607, #1408→#1409, and #5140→#5141. Unlike the earlier clearing, both characters stayed within hearing range.

Mira's two accepted learning batches changed caution from 65 to 61 and trust in Tovan from absent to +2. Tovan's accepted batch changed caution from 25 to 27 and trust in Mira to +1. His reflection cited hearing Mira's provisioning advice (#607), and his later behavior proposal explicitly referred to the trusted supply at 148. This supports a communication → interpretation → later provisioning choice chain, although Tovan had also gathered there himself. It does not isolate speech as the sole cause or demonstrate joint exploration.

Tovan finally asked Mira for route advice at 283.731 seconds (#5140). Mira heard it, but her shared model-call budget was already exhausted. No subsequent answer was generated. His message was authored from an earlier context at 124 but delivered at 148; the text's location claim was already stale when spoken.

One of Mira's learning batches was rejected at 107.468 seconds (#1282) for `newer subjective evidence retained`. It cited site evidence #191 for location 148, while an existing belief for that location used source #192. That conflicting belief was already present in the supplied context: this was not a learning revision race caused by new damage during inference. The whole batch was rejected.

The belief store currently keeps one claim per location, so claims about food, a companion's presence and travel can overwrite one another merely because they mention the same cell. Mira's accepted second batch, for example, ended with the companion-presence claim for 148 rather than the earlier food claim in the same batch. This limits what the changed belief list can establish about durable knowledge. Also, the reflection `goal` field writes to the character's `motive`; Mira's original survival motive became a statement about updating assessments. These representation contracts deserve separate scrutiny before treating every identity change as useful development.

## The controllers were different, but this is not a fair ranking

Mira's host used independent behavior/communication/learning loops. Its 12-call allocation became four behavior calls, five communication calls and three learning calls. Only two behavior calls produced accepted policies; the other two failed JSON parsing. Her last call started at 122.326 seconds, so the controller had no further budget to reconsider or answer later messages.

Tovan's external runtime made five serial calls: behavior, communication, learning, behavior, communication. All five submitted operations were accepted. His second behavior call alone took about 53 simulation seconds, on top of the inter-role scheduling delays.

The host therefore considered behavior earlier and more frequently but consumed its entire budget early. The external path had better output validity in this sample but much slower behavior revision. Different prompts, personalities, schedules and sample counts prevent attributing this to the API transport or to one runtime's intelligence.

Reported usage was 187,476 tokens for Mira and 94,751 for Tovan, versus 149,977 across the previous run. Most growth was input: 266,480 prompt tokens and 15,747 completion tokens in the woodland run. Prompts rose from about 3,000–5,600 tokens initially to about 26,000–27,600 later. The terrain map itself was only 237 serialized JSON characters in Tovan's second behavior context; the experience list was 80,660 characters, dominated by repeated policy ticks, attempts and results. A larger terrain map is not the main explanation for this context expansion. These are provider-reported token counts, not a pricing estimate.

## Navigation and timing evidence

The independent real-authority check in `output/woodland-pathfinding-authority-check/` demonstrated both participants traversing a 26-step detour from 147 to 92, paying the same 26 energy and respecting walls. It used explicit fixture policies, not model-generated navigation. In the live run, no generated policy sustained travel long enough to exercise those corridors. Strategic route choice, alternate-route reasoning and exploration of unknown terrain remain untested; the map is explicitly surveyed and public.

The woodland authority advanced 300.005 simulation seconds in 4,364 updates with zero script errors. Average throughput was 14.55 updates/sec, compared with 14.23 before; sampled first/last-minute rates were approximately 17.57/13.13, versus 17.41/12.83. The same decline remains. The supervisor's 302.068 seconds includes shutdown and cleanup, so it is not a clean clock-drift measurement. Browser activity and the separate authority fixture also ran on the local service during the pilot. This is not evidence that grid navigation either caused or solved the throughput limitation.

## Next experiments without tailoring success to Luna

1. **Separate navigation from survival.** Give a bounded travel objective and compare model-authored policies across several maps and repeated samples. Measure arrival, interruption causes and route choice; keep the successful scripted route as a mechanical control, not as an NPC fallback.
2. **Probe observation lifetime.** Delay policy submission while repeated unrelated experiences accumulate. Check whether a still-local resource can remain available to guards, or whether the player has a way to refresh the observation. This should be a controller-independent contract.
3. **Measure applying a lesson.** Supply the same retained interruption diagnosis to fresh behavior calls, with different model/configuration variants. Record whether the resulting policy can leave its departure cell. Do not infer learning from good prose alone.
4. **Match the comparison conditions.** Match call opportunities or token budgets and rotate identities between host and external controller assignments. Keep prompt/context differences explicit. Examine role budget allocation separately from model quality.

These results justify clearer observation, authoring and controller contracts. They do not justify injecting a handcrafted survival strategy or claiming that the larger world already produces richer navigation.
