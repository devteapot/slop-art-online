# Stages: growing the living world

Decided with the user on 2026-09-26 after the large realm worlds collapsed (mass starvation, stillness, repetitive talk) in ways that made it unclear which layer had failed. The world now grows one layer at a time in small lab worlds. A stage passes only when its measured criteria hold, and only then does the next layer go on top. Work proceeds autonomously; evidence and every rule change are recorded here, and each passing stage is committed and pushed to `living-core`.

Principles that hold throughout: behavior belongs to the characters ([living core](LIVING_CORE.md#robustness-layers-found-necessary-in-live-runs)); mistakes get feedback, not injected corrections; world rules, balance and mechanics may change freely.

## Lab protocol

- Labs are small worlds built from `living/seeds/<scenario>.json` with `living/tools/lab.py`, each on its own database and mind service. Up to three run at once, each varying one factor from a baseline (food, predators, pace, group size).
- Lives last about 4 real hours in labs (a generation in about an hour); the play world keeps one game year per 15 real days.
- All minds use Mistral Small. No call budget.
- Every change keeps the whole living core compiling, observer included: `just living-check` (authority, mind, native and browser viewer, rules tests) runs before each commit.
- `living/tools/watch.py` reports every 10–15 minutes per lab (population by stage, births, deaths and causes, movement, time budget, speech and goal topics, flags, a model review). Stage criteria are computed from these reports and the databases.

## Stages

1. **Survival and life cycle, with communication.** One family or small band (about 8 people, all ages) in a small valley with deer and wolves. People eat, rest, keep warm, reproduce, raise their babies, age and die; animals graze or hunt, breed and die; people talk.
   - *Passes when*, over at least three generations in the baseline lab and in at least one variation: the population stays stable (neither dying out nor starving back from each surge); no one starves while food is within reach of their home range; infants are fed by someone; deer and wolves persist over generations (no extinction unless hunted out for an understandable reason); speech is proportionate (median under ~1 line per person per real minute, most exchanges ending in an outcome, few repeated lines); fewer than 5% of people stuck or flickering at a time.
2. **Know-how and making.** Fire, shelter, tools, planting and storage, taught to children.
   - *Passes when* techniques survive across generations (taught before their knowers die), food is stored for winter, and winter deaths fall compared with stage 1 conditions.
3. **From family to settlement.** Several families form a community: houses, shared stores, division of labor, rules (theft, gates, watch).
   - *Passes when* the settlement feeds itself across generations with roles that emerge (people repeatedly doing different work), and its rules are kept or changed by its members.
4. **Two settlements.** Travel, contact, trade or conflict over regional goods.
   - *Passes when* there is repeated exchange (goods, people, knowledge) or conflict with interpretable causes, sustained over generations.
5. **Several self-sufficient hubs** that communicate (roads, trade routes, alliances, feuds) on a larger map with about 150 people.
6. **Scale and players**: large worlds (2,000 characters) within the performance contract, and human players.

## Log

Evidence, rule changes and decisions per stage, newest last.

### Stage 1

- 2026-09-26 09:10 — Three labs started (baseline, scarce food, more wolves): one family of eight (elder, four adults, two children, a baby) in a 96×96 valley, lives of about 4 hours, seasons of 12 minutes, 16 deer and 3 (or 8) wolves.
- 09:40 — First review. Fixed at their causes: the baseline's mind service had exited and was never restarted (lab.py now supervises it); walks to where a body already stood never reported arrival and stayed "going" for up to 12 minutes; animals died of old age before their first spring because labs compress aging but not the calendar (mating no longer waits for a season). Seeded young had the elder as a parent (now the adults). All three labs restarted.
- 10:45 — Merged steering-based movement and situational recall with conversation pacing (both agent work, checked: mechanisms 10/10, steering 5/5, unit tests). Recall now brings cued knowledge (promises, dangers, memories) into each thought instead of recent feelings; talkativeness follows each person's temperament and agreements close exchanges. All three labs restarted on the combined code.
- 11:20 — Second review found the causes of the starving, still family and the dying wildlife:
  - **Home site.** The family had been seeded on the realm generator's "wild" site, in barren hills with no berries or grazing, contrary to the scenario's own setting. Stage 1 now uses the classic valley map, and bands on it settle where a family would: open grass with berries and fish in reach.
  - **Animal ways.** Animal minds rewrote their whole graph from each impulse and dropped mating (23 of 27 graphs had lost it), and animals born in the world would have kept their young "follow your parent" instinct for life. Grown deer and wolves now live by routines and weighted desires like people: stay safe, feed, rest, mate, keep with the herd or pack, roam. An impulse edits one routine or weight, and the young take on their species' ways when grown.
  - **Company.** "Alone" and "company" now count one's own kind.
  - **Self as target.** Targeting oneself (tending one's own wounds) resolved to a point and always failed; it now resolves to the character itself.

  Checks: mechanisms 10/10, steering 5/5, the repertoire test validates the animal routines against their bodies. All three labs restarted.
- 11:40 — Third review. Animals now breed: seven deer pairs and one wolf pair were expecting within 30 minutes, and the baby grew into a child. Findings:
  - **People could never conceive.** Conception needs a shelter nearby, and the family didn't know how to build one. By their history they have lived here for three generations, so stage 1 families now know shelters and start with a shelter and a campfire at their camp. Making things is stage 2's subject.
  - **Predators boomed.** With eight wolves, the pack grew to 16 and ate all but 3 deer: nothing but pregnancy limited breeding. Parents now raise their young for a species' interbirth interval before conceiving again (about a year for deer and wolves, two for people), in a new private `rearing` table (automatic migration: adding tables is allowed, <https://spacetimedb.com/docs/databases/automatic-migrations>). The failure reads "still raising your young".
  - **Viewer builds.** `just living-check` now keeps the observer compiling.
  - **lab.py cleanup.** A stopped lab now takes its mind and watcher down with it.

  All three labs restarted.
- 12:00 — Fourth review. All three labs have in-world births now (deer, wolves), but wolves take most fawns and old age thins the seeded herd; left to run longer. People stood still (7 of 7 in the baseline) at energy 0 and one starved: each thought replaced their whole top level with a flat, momentary plan ("go to family, else camp") that had no eating or sleeping, and when it completed they idled. Same failure as the animals, same answer: a reply's `intent` becomes the routine "current plan", weighed among the person's desires as "the plan" (needs keep their own pull, so a plan of 0.6 yields to strong hunger and resumes after); rewriting the top level stays possible but is for changing how one lives. A plan that has been carried out is done: it stops competing and the person thinks again ("I finished my plan"). Checks: mechanisms 10/10 (two flaky failures once under load), rules tests including the plan round trip. Labs restarted.
- 12:15 — The labs since 11:20 ran a stale mind service: `lab.py` rebuilt only the authority module, so the animal routine editing and the plan-as-desire format were not live (21 of 24 person replies still sent whole graphs). `lab.py` now builds the release mind as well. Labs restarted on the current code.
- 12:40 — With the current mind live, 17 of 20 people ran desires with a weighed plan, and none stood idle at hunger 100; but animal minds still sent a whole new top level with most impulses (35 of about 50 grown animals flat). Animal impulses now take the same path as a person's plan: an `intent` weighed among the animal's desires, the whole top level only when an impulse changes its entire way of living. Labs restarted.
- 13:10 — With animal impulses weighed too, nearly every grown character keeps its desires. The herds are growing (baseline 19 deer and 3 fawns; scarce 20 and 1), wolves and deer coexist in the wolves lab (9 wolves, 12 deer), and speech is 0.76–0.87 lines per person per minute. Two people starved beside food. Their minds had rewritten "eat" into routines that walk to a bush and stop, or wait without berries, and these reported success (332 successes, no failures) while hunger stayed at 100. One of them carried 11 fish, so being "very hungry" never prompted a thought (only an empty pack did). Feedback added, no rules:
  - **Starvation alert.** Starving (hunger 97 or more) is its own sensation and always prompts a thought.
  - **Needs in the repertoire.** The mind's repertoire shows beside each routine what it serves and how that need stands now, e.g. "eat (serves food: hunger 100/100) — done 332×".

  Lab modules were republished in place and their minds restarted.
- 13:40 — After an hour on the current code the herds grew (baseline 28 deer), but wolves died out in all three labs and no person was born in any lab.
  - **Wolves.** Many seeded wolves were past breeding age, and the rest courted without answer: conception needs both partners to choose each other within two minutes, and one wolf made 113 unanswered offers because nothing let a body notice being courted. Added the target `suitor` (whoever just offered to start a family with me, while in sight) and the desire signal `courted`; the animals' mate routines answer a suitor first, and courtship raises their wish for a mate.
  - **People.** The seed never told the family who is whose partner, child or parent, so every relation was a model-invented "family", and the people's starting ways had no family desire at all. Family history now seeds those relations, and people start with a "start a family" routine (answer a suitor, else approach one's partner) weighed as "a family"; like any habit it is theirs to change.

  Checks: mechanisms 10/10, rules tests 23. Labs restarted fresh.
