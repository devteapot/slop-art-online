# Luna matrix: run analysis

Analyzed `sim-bevy-1788618753300`, recorded in `output/luna-matrix-20260905/`. Sources are the final authority snapshot and events, all 66 actor inference journals, supervisor receipts/cancellations, and sampled observations. Event numbers below refer to this run. No simulation or model calls were performed for this analysis.

The strongest result is a recurring policy-authoring failure: four external characters starved while carrying food because they used inverted hunger conditions. Medium/corridors also contains a positive case of repairing a failed navigation policy. This run does not establish a winning reasoning level or runtime.

## Outcomes

Each internal character is Mira; each external character is Tovan. All seven survivors finished with 100 HP. Deaths were all starvation; there were 65 starvation damage events and no combat or environmental damage.

| Environment / requested effort | Internal | External | External food at end/death | Confirmed remote-food arrival |
|---|---|---|---:|---|
| Open / low | Survived | Died at 167.708 s | 12 | External at 62.181 s |
| Open / medium | Survived | Died at 130.075 s | 38 | External at 29.845 s |
| Open / high | Survived | Died at 130.075 s | 14 | External at 68.423 s |
| Corridors / low | Survived | Died at 262.622 s | 0 | Neither |
| Corridors / medium | Survived | Survived | 4 | Internal at 127.993 s |
| Corridors / high | Survived | Died at 130.075 s | 25 | External at 72.833 s |

Arrival means an actual `site` perception at the reported location, not the initial report or a successful same-cell move. Arrival events: #5593, #1821, #6561, #14622, #7195 respectively.

Five internal characters gathered exactly the eight food at their starting site, ate six times, and finished carrying four. Their policies spent much of the remaining run waiting/resting or stalled after a short move. Medium/corridors Mira gathered 43 in total: eight local plus all 35 at the remote source, and finished carrying 39. Survival alone therefore gives limited information about exploration or adaptability in this five-minute setup.

## Four deaths despite carrying food

The game uses hunger as deprivation: it rises over time, and eating reduces it by 35. The supplied skill description explicitly says this. Four external policies used the opposite condition:

- **Open/low, actor 2:** `hunger < 35` → eat. He initially ate twice while hunger was low, then accumulated 138 `no carried food` failures. Once hunger exceeded that threshold, eating stopped being eligible. He later gathered 12 at the remote source but died holding all 12. The later behavior patch retained the wrong eat guard. Initial policy #224; patch #8485; death #17472.
- **Open/medium, actor 4:** `hunger < 30` → eat. The first policy was installed at 24.302 s, after live hunger had already exceeded the threshold. He gathered 36 food and never ate. His second proposal read hunger 88 at 86.900 s, described eating as urgent, but authored `hunger < 90`. It arrived at 110.538 s, when hunger was already 100, so it still never ate. Death #14812, carrying 38. This combines an inverted comparison with a proposal that had become stale during inference.
- **Open/high, actor 6:** `hunger < 15 && food >= 1` → eat. Starting hunger was already 20 and only increased. The decision explanation even said to eat when hunger was low. He gathered 12, never ate, and died carrying 14 (#14834). A second behavior call began at 125.882 s with hunger 100 and was interrupted by death.
- **Corridors/high, actor 12:** `hunger < 40 && food >= 1` → eat. Its initial context was from the start, but the policy did not arrive until 56.311 s, after hunger had crossed 40. He gathered all eight local food, completed the corridor journey and gathered another 15, yet never ate. Death #14879, carrying 25.

These are neither resource scarcity nor pathfinding failures. The mechanics and generated predicates explain the outcome. The external prompt includes the correct eat description; this analysis found no instruction that explicitly reverses the scale. A shared misunderstanding across these responses does not establish why the external path was more susceptible: its prompt, MCP schema overhead and character persona differ from the internal path.

Corridors/low actor 8 died for a different reason. His first travel sequence was wrapped in an `at(start)` guard, so moving one cell made the whole branch false (#373 at 15.758 s). The replacement at 83.209 s correctly ate at high hunger but contained only eat/rest/wait, with no food acquisition or return branch. He consumed his initial two plus one gathered food, accumulated 200 empty-inventory eating failures, and starved at 262.622 s (#25949). A reflection saying to use a known food site did not add that action to the policy.

## Navigation improved in one meaningful case

The previous woodland run never reached a remote source. This matrix produced five actual arrivals, including two routes through corridors. That is live model-authored navigation evidence, beyond the separate scripted route verification.

Medium/corridors Mira provides the clearest adaptation:

1. First policy #1308 guarded its outgoing move with `at(1853)`. It moved one cell and abandoned the branch (#2320 at 34.326 s).
2. Accepted learning #7281 at 73.696 s referred to the interrupted journey and unproductive waiting. The next behavior prompt retained both that learning event and the original interruption.
3. Replacement #13275 at 117.161 s used `not at(1642)` to keep travel eligible throughout the journey, with independent hunger and energy safeguards.
4. She arrived at 127.993 s (#14622) and collected all 35 remote food.

This is a traceable experience → later policy revision → changed behavior chain. The reflection itself did not precisely diagnose the guard semantics, so it would overstate the evidence to attribute the fix solely to that reflection rather than the whole supplied context.

The same departure-guard problem remained in open/medium Mira and open/high Mira. They left their starting cell and then stalled (#13954/#14044 and #4027). Higher requested effort did not consistently avoid this mistake.

The surviving external character, medium/corridors Tovan, made a useful return-to-food patch at 143.217 s (#15603) after becoming stranded partway to the remote source. He gathered the remaining local food and survived. But the patched sequence repeatedly called move-to-1854 while already there: 556 completed move results across the run, mostly no displacement. At 188.656 s his accepted reflection correctly recognized that completion did not mean progress (#19105). That was his sixth/final call; no later behavior turn was available to apply the lesson. Do not interpret those 556 results as extensive exploration.

## What the reasoning settings changed

Across the four initial behavior calls at each requested setting:

| Requested effort | Median first-policy installation time | Median provider-reported reasoning tokens |
|---|---:|---:|
| Low | 11.869 s | 230 |
| Medium | 25.209 s | 842 |
| High | 55.318 s | 2,588 |

Initial requests were released together near simulation start. These times include provider/model and runtime/authority delays; they are not isolated model compute benchmarks. For example, medium/corridors external took 54.115 s while the other medium first policies arrived at 21.562–26.116 s.

The response metadata shows substantially greater reasoning-token use at higher requested effort, consistent with the configuration having an effect. The endpoint still does not attest to the effective upstream setting. More reasoning did not reliably fix inverted hunger comparisons, departure guards or malformed JSON in this sample.

All completed calls together reported 1,205,028 tokens: 456,568 low, 414,297 medium and 334,163 high. These totals are not a cost/efficiency ranking: low made 24 calls, medium 23 including one interrupted journal, and high 19 including one interrupted journal. Character death and provider latency changed how many turns fit inside the run. Initial external prompts were approximately 5,587–5,728 tokens versus 3,010–3,151 internally because the external path also carries MCP contracts.

## Output validity and learning retention

There were 66 started calls, 64 completed journals and two incomplete journals associated with interrupted external work. Of completed responses, three internal second-behavior outputs had malformed JSON: actors 7, 5 and 11. They had normal provider `stop` finishes but were rejected before any authority operation. The existing policy continued. No response was silently repaired.

The remaining 61 proposed operations produced 56 accepted operations and five authority rejections:

- 19 accepted behavior operations: 17 replacements and two patches.
- 21 accepted speech operations.
- 16 accepted learning batches out of 21 attempted learning batches.

Three learning rejections were retention failures, not fabricated references: actor 2 twice (#4754, #14677) and actor 7 (#15202). **Every cited source in those batches was present in the actual model input.** The bounded live trace had changed by submission. The respective read→submission intervals were approximately 8.1, 9.8 and 23.7 seconds. This is the existing asynchronous evidence-lifetime problem, amplified by dense event streams.

Actor 6's learning failed with `stale learning revision` (#12436): it read before starvation damage began and returned after damage had changed the character's learning revision. Actor 12's learning arrived after death (#14910). Those are real state changes during inference, distinct from source expiration.

The 81 `identity_change` events must not be counted as 81 successful model learning batches: 65 accompanied starvation damage, and 16 were accepted reflection batches. Rising caution in dying characters is therefore largely mechanical damage response.

## Communication and simulation health

There were 21 speeches but only seven matching listener perceptions, compared with six of six heard in the prior woodland run. Pairs often separated spatially; walls do not expand hearing range. Some accepted learning referred to heard speech, including medium/corridors Tovan's interpretation of Mira's meeting-place message, but this run does not demonstrate coordinated joint exploration. Food-sharing language also does not itself transfer inventory; there is no give-food skill in the supplied catalog.

The run advanced 300.05 authoritative seconds in 1,692 updates: 5.64 updates/sec on average against a 20 Hz scheduling target. Sampled throughput declined from roughly 10.76 in the first minute to 4.04 in the last minute. The previous two-character woodland run averaged 14.55. With twelve actors, dense audit/subscription traffic, model processes and browser/test activity, this deserves profiling; the data does not isolate one cause. All cells share the same elapsed-time clock, so fewer updates do not mean metabolism simply paused, but contention and delayed decisions are comparison confounds.

No script errors or detected cross-arena context/movement violations occurred. All six hazardous sites remained untouched, as did the other two unreported remote food sites per arena. This tests surveyed navigation and survival more than hazard learning or broad exploration.

## Most useful next experiments

1. Test shared resource semantics explicitly: expose the scale endpoints and effects clearly, then measure whether fresh policies implement the intended hunger condition. Apply the same contract to both runtimes; do not inject a fixed survival policy.
2. Use a small travel task with several layouts to test whether generated policies can leave a starting cell, survive a higher-priority interruption and resume. Measure actual displacement/arrival, not successful move counts.
3. Give each accepted learning batch a subsequent behavior opportunity, and address the evidence-retention window for asynchronous submissions. Preserve stale-state checks while separating missing provenance from evidence that expired during a call.
4. Repeat cells, rotate personas between runtimes, and compare equivalent prompts/call opportunities. Profile the authority under twelve actors before attributing latency differences entirely to reasoning effort.

Medium/corridors was the strongest observed cell for this run: both survived and one successfully repaired its journey. That is a promising case to replicate, not an established optimum.
