# Stages: growing the living world

Decided with the user on 2026-09-26 after the large realm worlds collapsed (mass starvation, stillness, repetitive talk) in ways that made it unclear which layer had failed. The world now grows one layer at a time in small lab worlds. A stage passes only when its measured criteria hold, and only then does the next layer go on top. Work proceeds autonomously; evidence and every rule change are recorded here, and each passing stage is committed and pushed to `living-core`.

Principles that hold throughout: behavior belongs to the characters ([living core](LIVING_CORE.md#robustness-layers-found-necessary-in-live-runs)); mistakes get feedback, not injected corrections; world rules, balance and mechanics may change freely.

## Lab protocol

- Labs are small worlds built from `living/seeds/<scenario>.json` with `living/tools/lab.py`, each on its own database and mind service. Up to three run at once, each varying one factor from a baseline (food, predators, pace, group size).
- Lives last about 4 real hours in labs (a generation in about an hour); the play world keeps one game year per 15 real days.
- All minds use Mistral Small. No call budget.
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
