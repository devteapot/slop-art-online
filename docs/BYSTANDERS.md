# Bystander reactions in Brackenford

Play-test 8 had 17 minds. The owner reported that residents seemed to carry on while fights happened around them. This diagnosis follows an event from a character's senses through graph evaluation, model request, decision and physical outcome.

## Where the code path stops

| Layer | What the authority and mind service do |
| --- | --- |
| Perception | The 200 ms sweep serves player projections. A melee blow instead tests witnesses against live position, facing and sight at impact. `fold::blow` records the onlooker IDs in private `fight_seen` rows. The default two-second fold writes each witness a bounded `experience` line and deletes the raw rows. For an awake resident behind the sight boundary, the impact-noise path does not write a fight percept. It handles waking sleepers within the sound threshold and reach. |
| Salience | For the first landed blow, a visible bystander enters the behavior-graph wake path. The default 500 ms window coalesces these graph wakes. The folded line carries salience 0.7 when the fold is salient, otherwise 0.5. That line is written quietly. Graph evaluation can therefore precede the folded experience. |
| Thought | The first-blow caller asks the victim's mind directly. Fight reports are participant calls. The awake witness's graph wake queues an evaluation. It supplies no bystander deliberation reason. A separate eligible caller can still ask on the same tick or later, for example a cue, first sight, an alarm or a finished plan. The two attention laws were off in play8. |
| Decision | A person's `think` request includes its reason, a scene snapshot, and up to 16 recent experiences through the scene timestamp. A thought whose snapshot precedes the fold cannot get that fold from the experience list. Active combat can appear as a creature's visible activity. The scene has separate caps of 14 creatures and 10 structures. The structure cap cannot clip the fight line. |
| Action | The graph can execute an already-authored action on evaluation. A model intention is only a decision. `act_outcome`, `skill_use`, and the relevant physical state show the attempt, acceptance and effect. |

The code predicts **layer 3 for an awake sighted bystander** and **layer 1 for an awake earshot-only bystander** as far as the noise of an impact is concerned. Loud speech and a sleeper waking to a noise are separate paths. First sight is a useful positive control for a nearby stranger, and cues can match perceived activity when a resident has chosen a matching cue. Neither is a general fight-event trigger.

Sources in the runtime tree include `living/authority/src/act.rs` (impact, damage and victim request), `fold.rs` (witness selection and folding), `perceive.rs` (noise, scene and request), `tick.rs` and `common.rs` (graph wake), and `living/mind/src/mind.rs` (prompt assembly). See also [Perception](PERCEPTION.md), [Battle scale](BATTLE_SCALE.md), [Mind harness](MIND_HARNESS.md), [First sight](FIRST_SIGHT.md), and [Attention](ATTENTION.md).

The documentation for [SpacetimeDB tables](https://spacetimedb.com/docs/tables/) and [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) explains why owner reads can establish recorded truth while each client receives only matching rows it may access. The repository pins 2.14.1. This diagnosis uses the existing private tables and indexes and adds no subscription or durable state. A future request should use each witness's own evidence, read via the actor or observer key, through the existing private deliberation path. The current combat fold retains raw evidence for seconds and the experience inbox is bounded per character.

## Recommendation

If a sighted play8 witness has a fight percept and no request, trial an off-by-default, event-triggered attention rule. A sudden salient event that the character actually perceived can ask one thought. Use the observer's version in the reason, merge with an existing request when possible, and coalesce repeats of the same episode. For blows, ask after the folded experience is available, or carry the witnessed event into the request directly. A generic sound can identify only what the listener heard. Extending the rule to awake listeners of an impact requires an audible percept first.

Apply identical sensing to people and minds. Only the mind controller gets a model request. Its persona, role and ties can lead it to continue its plan, investigate or act. Start with a resident-wide five-minute gap for measurement. Count eligible episodes, merged or suppressed asks, fresh requests, actual prompt entries, decisions and physical outcomes per resident-hour.

A scenario of one to four eligible episodes per resident-hour would add at most one to four deliberations per resident-hour before merges. At the historical all-in rate of $0.0063–$0.0065 per deliberation from [First sight](FIRST_SIGHT.md), that is about $0.006–$0.026 per resident-hour under that assumption. A five-minute gap caps the long-run rate at 12 per hour, about $0.078 per resident-hour at the high rate. Neither the episode rate nor cost for this candidate was measured in play8.

## Play8 evidence

The paused session used build `95d11f43`, island seed 7, and 17 resident minds. The archived script has `first_sight_thinks=false`, `cues_on=false`, a two-second fight fold and a 500 ms behavior-graph wake window. The archive records $0.1799 for 128 calls across the entire play-test. That total includes other activity. The 17 resident journals contain 22 think, 21 compile, 30 talk and 46 consolidation replies. Over the 278 s unpaused interval, 22 think calls amount to about 16.8 per resident-hour during this short session. This is an exposure-normalized rate for that session.

### 1. Seeing to thinking

The archived `fight_seen` transactions recovered 36 rows. Counts below are firsthand rows, with the shooter-visibility flag masked off to recover the witness ID. A direct ask means a model prompt whose request reason named the attack on that character or explicitly reported a fight. Later calls carrying a fight percept are reported separately.

| Encounter (UTC) | Raw rows | Resident witnesses | Direct fight asks in witness prompts | Party response |
| --- | ---: | ---: | ---: | --- |
| Aldric, 21:43:14.091–21:44:41.809 | 23 | 11 | 0 | Aldric had six combat-related think replies, including one that returned after he died. The first think reply returned 5.612 s after the blow. He struck back after 1.216 s, before that reply. |
| Sissly, 21:45:02.826 | 1 | 9 | 0 | Her shot-triggered think reply returned after 2.975 s. She called at +9.974 s and ran to Agnes, completing `goto` at +11.735 s. |
| Cuth, 21:45:08.227–21:45:33.894 | 12 | 9 | 0 | Cuth struck back, called, dodged and yielded. Her later compilation returned after death. Her first think reply returned 4.926 s after her own first hit. Its scene shows the stranger releasing a firebolt at her and the experience separately names the bolt that hit Sissly. |

Cuth's first attack prompt held 10 creatures and 10 structures. It identified Diego by perceived handle #26, 1.5 m away, with `visibly` set to a firebolt releasing at her. Linnet's quiet-moment prompt also had 10 creatures and 10 structures. It held Cuth, Sissly and the stranger, alongside earlier fight experience. Cuth was facing Mercy by that snapshot. Aldith's and Agnes's later prompts each had nine creatures and ten structures. Their attacker entry had no active windup. These snapshots show the distinction between evidence of what happened and visible activity at request time.

Several witnesses reacted socially. Maud's first combat-aware conversation response came back 12.094 s after Aldric's first blow and her call reached the world at +16.766 s. Bram's warning came at +42.620 s. Linnet's own quiet-moment think response came back 19.977 s into Cuth's fight. She called at +25.132 s and completed a run to Mercy at +29.100 s. Agnes and Aldith had quiet-moment think replies 40.913 and 41.485 s after Cuth's first blow. These are observed response or effect times, rather than authority dispatch timestamps. The archive has no evaluation-by-evaluation graph trace.

Wat, Tobin, and Gareth were 109.1–112.5 m away at their closest during Aldric's encounter, 111.5–114.9 m at Sissly's and 101.0–104.4 m at their closest during Cuth's. Aldric's four recorded calls were 110.9–126.3 m from the gate group, measured from the call positions and the guards' stationary body positions. These ranges exceed play8's 48 m daylight sight and 30 m spoken call reach. The archive gives no firsthand fight rows or listener evidence of Aldric's calls for the gate group. Wenna approached from 104.6 m to 39.3 m and became a late Aldric witness, with her first blow 22.934 s into that encounter.

### 2. Saying without doing

Maud's actual 21:43:26.185 talk frame opens with “This is your turn in a conversation. Talk as yourself, in your own voice, usually a sentence or two”. Her user frame includes her relationship to Aldric, recent folded blows under “Lately, involving Aldric Marrow”, and his call under “What you are answering”. The fight was in the prompt. It did not need a structure slot.

The reply fields in that frame are `thought`, `say`, `to`, `way`, `acts`, `settled`, `until`, and `end`. The exact schema clause is “\"acts\": [] or deliberate acts you carry out now”, followed by examples for conceive, accept, decline, give, offer, teach and host. The frame says “words change nothing in the world by themselves: what you agree to do now, do here; you will learn how it went”. The mind service dispatches `say` and `acts` separately. A spoken line, a private thought, and a settlement do not execute movement or treatment.

Maud's first two replies told her father to get or sit behind her and returned `acts: []`. Her third declared a settlement that she stood between him and the attacker and tended him, again with an empty array. Agnes's 21:45:39.198 reply specified a trip home and tending Sissly's burn in `settled`, with no act. No completed tend was found for either episode. Linnet and Sissly eventually did submit valid `goto` acts through deliberation and the authority recorded their completion.

A framing test should make the independent choices to speak and act equally visible, use an example that contains both, and keep settlements in the language of agreement or intention until the authority confirms an effect. If a choice requires an ongoing graph rather than a one-off act, carry the decision into deliberation without making the model re-infer it. Compare this separately from changes to request timing.

### 3. Wrong act name and no repair

Both refusals followed a talk reply that specified an act. Sissly submitted `{"do":"go","target":{"place":"home"}}`; Bram submitted `{"do":"go","target":{"id":"Agnes Fenner"}}`. Their acts were rejected at 21:45:38.318 (XP 1963) and 21:46:01.572 (XP 2090). The actor's experience read “You could not act on what you decided (…)” followed by “graph.do: unknown skill `go`; skills are goto, wander, …”. The real feedback includes the full canonical list, which also contains skills inappropriate for a one-off act. Bram's target would also need repair to a numeric perceived ID.

The actual talk system and user messages for these replies have no `goto` example. The actual deliberation compiler prompt for Sissly's earlier successful walk names it both in the skill list and as a one-off act, `{"do":"goto","target":T}`. Talk's displayed catalogue is drawn from skills tagged for talk, while its submission path accepts other legal one-off acts. The parser records `unreadable` and sends the experience with `think=false`. The reducer itself returns successfully. Existing retries cover malformed model replies and some transport or speech errors. These submitted acts got no repair in the same turn and no corrected retry was found before play8 ended.

Propose a bounded repair in the mind service with structured per-act authority feedback, the current admissible catalogue, and explicit target examples. The repair should resubmit only the rejected act, at most once, and preserve the already recorded refusal. Any earlier successful act or speech must not be repeated. Keep the authoritative skill names exact.

### Yield and killing after yielding

Aldric's second yield at 21:44:30.676 was followed by a blow at 21:44:33.925 and death at 21:44:41.809. Cuth yielded at 21:45:26.660, took a blow at 21:45:29.826, and died at 21:45:33.894. Three different percepts carry the fact: a yield with guard down (0.6), the first strike after the yield (0.95), and a death line that explicitly says “after yielding” (1.0). The explicit death line preserves meaning even if a witness missed the yield itself.

| Resident | Aldric / Sissly / Cuth firsthand rows | Aldric yield / strike after yield / death | Cuth yield / strike after yield / death | Verified response or outcome |
| --- | --- | --- | --- | --- |
| Aldric #1 | party / 0 / 0 | party | — | Struck back, called, yielded twice and died. |
| Cuth #2 | 23 / 1 / party | Y/Y/Y | party | Referred to Aldric's killing after yield in an audible warning, then fought, yielded and died. |
| Maud #3 | 23 / 1 / 12 | Y/Y/Y | Y/Y/Y | Warned Aldric before his death. No follow-up act observed. |
| Wenna #4 | 6 / 0 / 0 | — | — | No verified death response. |
| Tobin #5 | 0 / 0 / 0 | — | — | Gate group. |
| Mercy #6 | 23 / 1 / 12 | Y/Y/Y | Y/Y/Y | Warned Linnet to stay behind her and spoke about denying trade and shelter. No executed sanction established. |
| Osric #7 | 0 / 0 / 0 | — | — | No verified response. |
| Linnet #8 | 18 / 1 / 12 | N/N/Y | Y/Y/Y | Called and completed her run to Mercy. The run was decided before Cuth died. |
| Agnes #9 | 23 / 1 / 12 | Y/Y/Y | Y/Y/Y | Answered Sissly, later issued warnings. No completed tend or protective walk verified. |
| Wat #10 | 0 / 0 / 0 | — | — | Gate group. |
| Bram #11 | 23 / 1 / 12 | Y/Y/Y | Y/Y/Y | Warned during Aldric's fight; later tried to go to Agnes. The attempt was refused. |
| Sissly #12 | 23 / party / 12 | Y/Y/Y | Y/Y/Y | Described Aldric's fall after a question. After her own injury, called and ran to Agnes. Later retreat attempt refused. |
| Baldwin #13 | 23 / 1 / 12 | Y/Y/Y | Y/Y/Y | Movement toward the square was observed. No fight-caused act verified. |
| Petra #14 | 23 / 1 / 12 | Y/Y/Y | Y/Y/Y | Continued teaching during Aldric's fight. No verified death response. |
| Gareth #15 | 0 / 0 / 0 | — | — | Gate group. |
| Aldith #16 | 23 / 1 / 12 | Y/Y/Y | Y/Y/Y | Publicly named the killings after yield. First call after Cuth fell was at +20.623 s. |
| Leofwine #17 | 0 / 0 / 0 | — | — | No verified response. |

As a replay estimate, ten resident IDs received a recorded episode-related fight or death line at salience 0.7 or higher, or an audible call from a participant, using the capture's actual recipients. Applying one fresh thought each to that set over play8's 278 s would add about 7.6 per resident-hour and $0.063–$0.065 to that session at the historical all-in rate. This is a counterfactual estimate from the recorded sight and speech paths. It omits the new awake impact sounds and any prior event that would consume a resident's gap. The short and unusually violent session is not a steady-state forecast.

Ten resident witnesses got the Aldric death line and nine got the Cuth death line. None got a direct bystander request about the death. The audit distinguishes actions during an encounter from reactions demonstrably caused by the death. Mere location change and later claims about others are insufficient to establish causation.

## Measurement-only law and trial

The branch contains `trial_salient_events_think`, off by default. It can ask an awake resident mind to think on what the authority actually wrote for that resident. It uses the recipient's own percept text and gates by a five-minute per-resident gap and the existing request path. Qualifying firsthand lines are non-party witnessed events at salience 0.7 or higher. Loud speech uses the existing set of listeners. Audible impacts use the existing loudness and reach with each listener's hearing. The prototype writes only a bearing and description for an impact sound, with no attacker or victim identity. Hearing uses the same path for player and AI characters. The AI controller alone can get a model request.

The gap is held in module memory and is scoped to this trial. It did not add tables, subscriptions, or schema migrations. In particular, an initial impact sound can spend the gap before the visual fold arrives, and a subsequent fall can be suppressed by it. Both possibilities matter when interpreting whether a thought actually saw the most salient part of the encounter. A production design should assess merging fresher observed evidence into a pending moment and whether a genuinely new escalation can reopen it. It needs load and memory bounds under sustained crowds.

The comparison uses the archived play8 laws, the island seed, a player-identity strike against Aldric on the Brackenford road, and four nearby authored residents. Cuth and Maud are his family. Agnes and Bram were staged farther out. Aldric is held on a scripted graph and yields after the first strike. An admin health adjustment makes the next ordinary player strike lethal. That adjustment is setup, while the skill ledger and chronicle must prove that a player blow killed him during the yield. The diagnostic first-sight arm enables that existing law and sets its gap to zero to remove an unrelated opening first-sight cooldown. The free model deliberately holds its plan. The paid arms use the two play8 provider models and leave the observed residents' decisions to their authored personas and ties.

The watcher admits at most 24 requests total across both paid arms, each at most 64 KiB and 8,192 output tokens, charging a conservative $0.10 reservation per admission before forwarding. It records usage and computes the estimated actual cost with the trial runner's pricing. The admission cap reserves at most $2.40, and the 25th request is refused locally. The checked rates are published by [Mistral](https://docs.mistral.ai/inference/pricing?currency=usd). The provider key stays in memory on the trial host.

The Spark build gate passed after adding the law's required description. The spend watcher's mock check admitted 24 requests, refused the 25th without forwarding, and reserved a maximum of $2.40. The free scratch arms completed and were paused and deleted. The first paid attempt stopped in both arms at verify startup. Its startup check expected a concrete default profile instead of the play8 routing mix. It sent no provider requests. Both scratch worlds were paused and deleted. The retry gives the helper a concrete fallback and assigns the play8 mix to the study residents.


### Free comparison results

The baseline and event-law arms used identical positions for the six staged characters. An unheld body's occupancy put Aldric on the adjacent south tile in the first-sight arm. Both ordinary strikes were accepted in all three arms, dealt damage and resolved physically. The first one dealt 8–10 damage, Aldric yielded, and the second killed him 5.40–5.48 s after the first in the baseline and candidate. All four monitored residents saw both blows in every arm. Each received a first-blow line at 0.7, a yield at 0.6, a strike after yield at 0.95, a death at 1.0, and a final folded fight line at 0.7. The baseline's first fold arrived 50–1,733 ms after the initial impact.

| Free arm | Four residents' think replies in the 34 s fight window | Trigger | Installed decision and effect |
| --- | ---: | --- | --- |
| Play8 baseline | 0 | No witness request from combat | No model-driven reaction in the window |
| First sight on | 3 | First sight of passing children in all three replies | Fixture kept its plan, with no fight-triggered request |
| Salient event on | 4 | Two heard the impact and two were prompted by the folded sight | Fixture kept its plan for all four, with no new physical action |

The fight was also visible to unmonitored people in the full island world. The model service was restricted to the named four, so these thought counts and normalized rates apply to those four. The two combat rows include each first-blow witness. Source code shows that the first row's qualifying witnesses enter the graph-wake path. The saved profiling tail is too short to identify each wake execution independently.

| Witness | Baseline fight requests | Candidate request from first hit | Fake think reply from first hit | What its candidate frame held |
| --- | ---: | ---: | ---: | --- |
| Cuth #2 | 0 | +0 ms | +1,651 ms | Bearing of the impact. The scene shows a strike releasing at her partner. |
| Maud #3 | 0 | +0 ms | +1,598 ms | Bearing of the impact. The scene shows a strike releasing at her father. |
| Agnes #9 | 0 | +117 ms | +1,377 ms | Folded first blow, plus the strike release in her scene. |
| Bram #11 | 0 | +584 ms | +1,488 ms | Folded first blow. The participants remained in view, with no active windup in the scene. |

Each candidate frame was at both scene caps, 14 creatures and 10 structures. The participants and the event reason reached the prompts. The prompt of each request preceded the yield. Each resident got one eligible request within the event and the death generated no second request under the prototype's cooldown. At this staged encounter rate the normalized model think rates were 0, 78.8 and 106.2 per resident-hour across the three arms. These short-window figures measure the trial workload. One sustained qualifying episode per resident within a five-minute gap would instead be at most 12 fresh requests per resident-hour.

After the baseline window, an unrelated graph request deliberately opened one prompt per resident. All four frames then carried the yield and killing, showing that this evidence survived to a later eligible request. The fake compiler submitted an invalid `go` act for each resident. All four refusals surfaced in subsequent consolidation prompts with `goto` in the skill list. No automatic retry or physical effect followed. The free provider cost was $0.

### Paid comparison results

Runs `minds-bystanders-1-live-base` and `minds-bystanders-1-live-event` finished at 00:51 CET on November 19. The six staged bodies started at identical coordinates. Both arms recorded two accepted and released player strikes. The first did 7 damage in baseline and 6 in treatment. The second killed Aldric after he yielded, at +5.468 s and +5.617 s respectively. All four residents saw both strikes and received the yield, the explicit strike after yield, and the death line. The baseline had no resident fight thought, speech, deliberate movement or position change in its 34.049 s window.

Times below are relative to the first landed blow in the candidate arm. Request times are the authority's, think reply times are the journal's, and effects come from the chronicle, experience and body snapshots.

| Witness | Request | Think reply | Decision | Verified physical or spoken effect |
| --- | ---: | ---: | --- | --- |
| Cuth #2 | +0.000 s, heard | +4.185 s | Call for the attacker to stop and approach her husband to tend him | Call at +8.112 s. No completed approach or tend. |
| Maud #3 | +0.000 s, heard | +15.644 s | Rouse the town and interpose for her father | Call at +17.708 s. No completed interposition. |
| Agnes #9 | +0.867 s, saw | +4.334 s | Call for help and move closer | Call at +8.160 s. `goto` completed at +10.234 s. Final position was 8 m closer along the road. |
| Bram #11 | +1.350 s, saw | +4.052 s | Alert the guards and keep back | Call at +7.179 s. A separate `do: "call"` act was refused as an unknown skill at +7.193 s. His `goto` completed at +14.817 s. |

Four thoughts and four compilations led to four verified calls and two completed walks. The role-specific intentions were the models' replies. No intervention occurred before the killing and no completed protection or treatment was recorded. The candidate did not ask again on the yield or death. Its initial prompts described an attack in progress and did not have those later lines. Some warnings were already stale by the time they were spoken. Prompt opportunity improved and end-to-end response latency remained a separate limit. Bram's `call` refusal also reproduced the general skill-name failure with another word. The valid spoken call had already gone out through the separate speech path; resubmitting it during act repair would duplicate it.

The 34.268 s candidate window produced 4 versus 0 resident think replies, or a short-window normalized rate of 105.1 versus 0 per resident-hour. One extra thought per resident in a staged episode is the interpretable exposure result. The spend watcher recorded 18 successful upstream calls. Baseline used 4 consolidation calls ($0.00560). The candidate used 4 consolidation, 4 think, 4 compile, and 2 talk calls ($0.02822). The total was $0.03382 and the difference was $0.02263, about $0.00566 per extra thought including associated calls and background cost variation. That gives about $0.006–$0.023 per resident-hour if one to four eligible episodes each add one thought. This estimate comes from one staged episode and four residents.

### Coverage and recommendation to the coordinators

The free tests reproduced the missing request with the existing laws and opened the path with a general event trigger. The paid comparison showed the model could choose speech and concrete acts from the witnessed scene. The imposed fight was short, the cast was small, and nobody had been assigned a prescribed response. The test covered four resident minds with sight of the same short encounter. Steady-state cost, crowd load, an occluded earshot-only listener, and longer fights remain open. The first paid attempt failed at local startup and spent $0. The corrected run finished both arms with no provider errors. All scratch databases were paused and deleted. The trial server did not restart.

Keep the three production decisions separate. Start by testing timely requests on the recipient's own evidence, then test a way to carry an observed escalation into an in-flight or follow-up prompt without flooding the service. Independently test talk framing with speech and action shown as separate choices, and same-turn repair of rejected acts without replaying successful work. The measurement law remains off by default. Production implementation is pending the coordinators' decision.

The replay extracts, free and paid runs, model journals, spend log and build evidence are archived on Spark in `~/slop-evidence/bystanders-1-2026-11-19.tar.zst` with a matching `.sha256`.
