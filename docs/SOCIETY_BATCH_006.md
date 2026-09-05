# Batch 006: committed tasks across urgent actions

The intent-resumption candidate finished 480.126 seconds with all four characters alive (Mira 34, Tovan 26, Iri 38, Renn 6 health). The progress-m1-14 repeat finished 480.073 seconds with three alive (74, 0, 40, 94). This is a promising bounded result, not stable long-term survival: the candidate left two characters near death and still showed unnecessary trips to an exhausted thicket.

The candidate made 60 journaled calls, with 1,015,432 reported tokens; one call was unfinished at the deadline. The comparator made 53 calls, with 897,831 reported tokens. Candidate authority rejections were one invalid shelter threshold and one oversized composite; comparator rejections were three invalid learning/tree operations. Both passed engine, scope and food-conservation checks.

## Material results

Iri contributed all 12 shelter units, benefiting every actor who returned to camp. Tovan transported food from the thicket and delivered **19 net units to camp** over the full run. His 110 deposits and 119 gathers were gross reuse counts, not new food production. Mira, Iri and Renn were net collectors at camp. Across event prefixes, at least 13 units collected there had to have been supplied by another character rather than camp's initial 18 units. This conservative bound accounts for each actor's own prior deposits; it proves collection, not consumption of individually identifiable food units.

Camp ended with 22 food; the main thicket was depleted; the unexplored northern site retained 30. Characters ate 42 units in total. Renn carried a large reserve, returned from the thicket and deposited 26 units, but later revisited the exhausted site and nearly died. Resource conservation holds despite this poor allocation.

## Execution and social evidence

In `sim-bevy-1788625068132`, Tovan's return journey was interrupted by an urgent rest at 67.514 seconds (events 3411–3412). Rest finished at cell 86 at 72.536 seconds (3802); movement then reached camp at 72.791 (3843), followed by a deposit at 73.037 (3864). This is an actual resumed delivery, backed by deterministic reload/preemption tests. The m1-15 `task_suspended` event was overbroad and also logged ordinary branch changes; this conclusion uses action outcomes instead. The next version narrows that diagnostic event.

Tovan's accepted learning cited Iri's perceived speech asking for gathering/help (source 1629), interpreted shared supplies as useful to the group, and increased trust by one. This provides an explicit speech-to-personal-state link; it does not establish that the speech alone caused later deliveries. Renn also accepted a speech-grounded reflection. Policies and deliberation remain authored by fresh Luna responses.

## Next controlled comparison

A separate deterministic test exposed an environmental action trap: damage every 2.5 seconds repeatedly canceled a rest interval of the same length. Starting rest between pulses restored zero energy over five seconds. Candidate m1-16 makes gradual weather/starvation damage non-interrupting while retaining health loss, sudden-damage interruptions and permanent death. The corrected test restores 24 energy, loses four health, and confirms no action progress after death. All 70 simulation and 37 bridge/host/compatibility tests pass.

Batch 007 repeats m1-15, compares m1-16 under identical supplied conditions, and runs m1-16 with empty food sites as a mortality control. Model, reasoning setting, food quantities in supplied runs and cold strength remain fixed. The society milestone is still under evaluation.
