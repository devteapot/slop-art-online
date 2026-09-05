# Batch 007: gradual exposure and mortality control

The m1-16 exposure candidate finished eight minutes with **4/4 alive**, at health 70/42/2/12. All were at the completed shared shelter and had remained stable there for the last several minutes. The m1-15 repeat finished with only Renn alive (66 health), confirming that the earlier four-survivor result alone was insufficient. The m1-16 food-shortage control lost all four by 307.667 seconds.

| Variant | Calls | Reported tokens | Survival | Engine/scope/conservation violations |
| --- | ---: | ---: | --- | --- |
| intents repeat | 39 | 642,929 | 1/4 at 480.064 s | 0 |
| exposure | 65 | 1,143,037 | 4/4 at 480.179 s | 0 |
| shortage | 26 | 387,279 | 0/4 at 307.667 s | 0 |

These call counts include one unfinished call per run at shutdown. Reported tokens exclude usage that the provider did not return. The candidate had one authority rejection for a stale learning revision; parser/provider/unfinished-call errors remain separately recorded. In particular, Tovan's first three generated proposals were malformed. His fourth decision recovered, but he had already lost health; the output was never silently repaired.

## Mechanism and actual interaction

Cold still reduced health every 2.5 seconds. Successful exposed rests are recorded in `sim-bevy-1788625595746`: Iri at cell 87 at 205.933 s (event 11636), and Renn at cells 87/85/87 at 216.516, 233.132 and 251.038 s (12394, 13752, 15095). They recovered energy while still exposed. This supports the deterministic regression: damage no longer erases every partial rest interval. Both survived long enough to return to shelter, although their final health was very low.

Iri built eight shelter units and Renn four. Camp ended with 61 food, versus 18 initially. Net deliveries after each actor's own camp withdrawals were Mira +1, Iri +17, Renn +29 and Tovan -4. All actors used food and shelter, the main thicket's 80 units were exhausted, and the unexplored northern site retained 30. The group ate 46 food units; final world food plus consumption equals the initial 138 units. No food regeneration or survival policy was added.

Tovan accepted Mira's perceived warning about cold at the thicket (source 18638), formed a corresponding belief, and increased trust. Renn accepted Iri's shelter request (625) as credible because it agreed with observed work. Subsequent policies and contexts are retained for inspection; speech is neither automatically believed nor an engine command.

The shortage group also built shelter and pooled starting inventory. It consumed all ten initial carried units and then died. Shelter did not manufacture food or suppress starvation. This is a successful scarcity control, not a failed infrastructure run.

## Remaining uncertainty and validation

The candidate recovered from inefficient trips and repeated actions, but two survivors were close to death. One successful run does not prove reliable planning. Batch 008 repeats the exact candidate/world/model at the same 15-second post-completion cadence, alongside the same candidate with a 5-second cadence. That comparison changes controller opportunities only, keeps internal and external controllers matched within each variant, and records the effective interval in each manifest and pilot. The milestone remains under evaluation until that repeat is reviewed.
