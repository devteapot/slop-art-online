# Strangers: noticing a newcomer by personality and duty (design, 2026-11-11)

Status: **design and measurement plan, nothing built or run.** It is read from main `feb6a10c`. The ar2 figures come from the arrival batch on branch `trials-ar2` (docs/TRIALS.md, "Arrival batch ar2").

**The owner's decision.** Attention to newcomers is not a world rule. The arrival laws on `exp-arrive` (`newcomer_salience`, `newcomer_scene_min`, `newcomer_drive_s`) are rejected and are not on main. The target is a plausible spread by personality and duty, not a contact share:
- someone whose life includes watching who comes in asks a stranger their business;
- a sociable or curious person sometimes speaks;
- most people notice and carry on;
- some notice inwardly and do not show it.

## 1. Perception today

| Fact | Deliberation scene | Graph conditions |
|---|---|---|
| **I do not know this person's name** | **Yes.** Each person in sight carries `name` when known, else `who: "a stranger"` (`perceive.rs:431-436`). `community: "yours"` marks one's own community (`:437-438`). Both come from `perception::knows_name` (`perception.rs:315`): oneself, family, the same community, or someone who told you their name. | **No.** The filter `relation: "stranger"` (`graph.rs:412`) means "has no relation row, or a row whose label contains *stranger*" (`brain.rs:1385`). That is not the same fact. In Cullet each resident has relation rows for only 4–15 of the other 63 (the sheets), so the filter matches about 50 fellow residents. It stops matching a newcomer once a consolidation writes a relation such as "wary". The prompt still offers it as if it meant "someone I don't know" (`prompts.rs:343`). |
| **I have never seen this person** | Only as a one-time percept: "For the first time you see a stranger, 9 tiles west, wait." (salience 0.45, `brain.rs:1170`). In a crowd (more than 6 people in sight, `skills.rhai:11`), a person with no relation row is skipped (`brain.rs:1157`). A newcomer who arrives among a crowd gets no first-sight line, and no `familiar` row is written for them. | No. |

**For Cullet the name fact is enough.** "Everyone knows everyone by name and by face. A stranger has not been seen in living memory" (`bible.md:91`). All 64 residents are in one community, so the only person a resident's scene can call "a stranger" is the newcomer.

**On worlds with several settlements it is not enough.** There, "a stranger" also covers the people of another settlement whom one sees every day (ar2 finding 3). The smallest truthful fact for that case would be a scene key `seen` on unnamed people: `"never before"`, or `"before, N times"` from the `familiar` row. It costs one point lookup, `by_actor_thing`. It is specified here but not proposed now: Cullet cannot test it.

**No fact needs adding to the scene.** ar2's `known` arm added a "new to you" mark, and every measure stayed within control's spread. That fits the owner's decision: a fact changes nothing until a life gives a reason to act on it.

## 2. Duty in the seeded lives

No one in Cullet's cast keeps a gate, a quay or a door. The town is unwalled and has had no traffic since the Last Sail.
- **Where newcomers arrive.** They arrive on the only square, the Counting House yard (`plan.json` `square`, 30 × 14 m). That square is Aldous Quill's workplace, 9–15 and evenings. Beside it are the Fish Steps (Magda Tarn, Ingrid Morrow and the line fishers) and the Store (Davin Vane).
- **Lives that already give a spread without any change:**
  - Lark Morrow: curiosity 88; saw a sail.
  - Sabine Quill and Benedikt Orme: curiosity 95.
  - Greta Dunmore: sociability 85; "hears everything said at the wall".
  - Halvard Dunmore: judges everyone aloud, but sits at the Cone, 150 m away.
  - Anselm Faro: his vow is "until the ships came back", but he sleeps by day.

**Proposed for dev-box**, which owns Cullet's seed. These are two lives in the cast's own words, not a role type: no table, no engine duty. Only the text in bold is new.
- **Aldous Quill, `role`:** "tally keeper of the Counting House: keeps the ledger of the Store and of who owes whom, **and the ship-day book of arrivals, in which every master who came in gave his name and business at the Counting House door**; the best counters player in Cullet".
  - **New `ties` line:** "**keeps the custom that whoever comes in is asked their name and business at the Counting House and written in the book of arrivals, though nothing has been written there since the Last Sail**".
  - `wants`: unchanged.
- **Ingrid Morrow, `role`:** "net-mender on the Fish Steps, who moves her bench with the sun **and sees everyone who walks the quay**; a Strand elder".
  - **New `ties` line:** "**knows every back on the Strand from her bench, and says what she has seen to Magda Tarn before she says it to anyone else**".

Her traits are caution 78 and curiosity 30, so hers is the life of someone who notices and tells, not someone who asks. The Quill and Morrow sheets would then be redrafted, or their `narrative` and `goals` edited to agree, and `cullet.json` recompiled (docs/AUTHORED_WORLDS.md, "Cullet").

## 3. Routines a mind can write

A mind can already react at its next deliberation: the scene says "a stranger", and its persona decides. It cannot write a routine that reacts on sight, because no condition is true exactly when "a person I don't know is in sight".

- **What it can write today.** The closest expression is `{"sees": {"nearest": {"kind": "person", "relation": "stranger"}}}`. It is wrong in both directions, as shown in §1.
- **What else is close, and why it falls short:**
  - `relation: "outsider"` (not of my community, `brain.rs:1387`) matches the newcomer in Cullet. It stays true after they give their name, and in other worlds it means another settlement.
  - `hailed` and `speaker` need the stranger to act first.

**The one proposed change.** Make the selector's `"stranger"` mean what the scene's word means: `!perception::knows_name(me, them)`. The same rule names people in scenes, percepts, memory (`mind.rs:2231`) and the client.
- **Where it applies.** It serves every use of a creature filter: `sees`, `near`, `nearest` targets for `goto`, `follow`, `flee`, `say`, `give` or strike, `count` ("at most 0 strangers within 10"), and `health_of`.
- **What else changes:**
  - A relation labelled *stranger* no longer counts by its label.
  - The prompt's line `prompts.rs:343` changes to `stranger (someone whose name you do not know)`.
  - Nothing in the seeds uses `"stranger"` (`grep`: only `friend`, `enemy`, `family`, `partner` and `outsider`).
- **Cost.** Per candidate it takes about five indexed lookups instead of one: two membership rows by member, acquaintance by pair, and two parent ranges. They run only in graphs that use the filter. It adds no table, column, view, subscription or write.
- **Example.** A guard's routine written by his own mind:
  `{"if": {"sees": {"nearest": {"kind": "person", "relation": "stranger"}}}, "then": {"seq": [{"do": "goto", "target": {"nearest": {"kind": "person", "relation": "stranger"}}}, {"think": "someone I don't know at the Counting House door"}]}}`.
  The `think` asks his model, which decides the words, so it does not repeat a canned line. `think` is throttled: not within 45 s of a decision, then once per 90 s (`brain.rs:515-523`).

## 4. Inner reaction

This needs no change. The evidence path:
1. **The percept.** The first-sight line becomes an `experiences.jsonl` row. The inspector's "what they perceived" lists it.
2. **The deliberation.** The request's scene carries `who: "a stranger"`, and the reply's `thought` records the inner reaction. In ar2 `notice` r1, Oren thought "I'll keep my eyes on the newcomer but stay at my work". The inspector shows each exchange.
3. **Memory.** The consolidation patch keeps `person:<id>` named "a stranger" until the name is told (`name_people`, `mind.rs:2233`). It reaches Neo4j, and its journal exchange is in the inspector.

**Gap.** There is no measure of "noticed inwardly". §6 adds one to `arrive_spread.py`. The inspector is unchanged.

## 5. The client

Nothing new is needed. The client's `seen_characters` view (`perception.rs:972`) carries `name`, empty when the player's character does not know it, and `label` (`"a stranger"`, `"a child"`, `"an old stranger"`). The client draws `label` while `name == ""`. The proposed change touches no table or view. If the `seen` scene key of §1 is ever adopted, it is for minds only.

## 6. Measurement on Cullet with real minds

**Setup.**
- **World.** Seed `cullet`, `world.start_hour` 6.5, so minds live 3 game hours and can write routines before the arrival.
- **Player.** exp-arrive's `arrive` player, ported with `arrive_report.py` and `arrive_spread.py`. It joins at 360 s, about 09:30, when Aldous is at the Counting House.
  - Stand 1: 5 min silent at the arrival point, as at a gate. This needs a new script option, `stand_at: "arrival"`.
  - Stand 2: 5 min at the densest group.
- **Duration.** 20 min (10 game hours).
- **Switches.** Main's defaults: `LIVING_GREET=nearest`, `LIVING_PARK=concurrent`, the meters() alarms. No arrival laws. Every batch record states these switches.

**Arms** (same commit, 4 replicates each; the arms differ only as listed):

| Arm | Change | Question |
|---|---|---|
| **C** | none | The Cullet baseline. ar2's hamlet control is the reference shape only: a different world. |
| **S** | `stranger` selector (§3) | Guard: does the change alone shift anything? Expected not to, like ar2 `known`. |
| **L** | the two lives (§2) | Does the duty in a life make its owner ask, at his next deliberation? |
| **LS** | lives + selector | Does a routine the mind writes itself make the question come sooner? |

**Measures, per resident and per run** (arrive_spread's definitions, so they compare with ar2):
- **Each resident in range:** their duty (L arms), curiosity, sociability and caution; whether the first-sight percept arrived or the crowd rule dropped it.
- **Each resident's class:**
  - *asks*: a line to the newcomer, heard or not;
  - *approaches*: comes within 4 m with no line;
  - *inward*: a thought names the stranger, with no act toward them within 120 s;
  - *tells*: a line about the stranger to others;
  - *unaware*: in range, never in a thought.
- **Per run:**
  - time from the join to the first heard line, and who said it;
  - crowding (`converge_60s`, `together_4m`);
  - re-asks and unheard lines;
  - routines installed with `relation: "stranger"`;
  - the guards: false replies, repeated lines, and talk that led to something, net of placebo.

**The shape written down before running.** This is the owner's target as numbers, not a pass mark:
- in L/LS, Aldous asks during his hours in 3 or more of 4 runs;
- 3 or fewer other speakers a run, ranked toward high curiosity and sociability;
- *inward* outnumbers *asks*;
- `together_4m` is at most 2;
- the guards stay within C's spread.

The owner judges from the inspector pages, one per arm.

**Thinkers: all minds.** Each run thinks for all 63 residents (Dory, the infant, lives by her graph).
- **Why.** The question is a spread across personalities. Crowding and *tells* need the others to think. A resident run by a graph alone would count as "noticed nothing", a spread the experiment itself would cause.
- **The single-thinker stage.** A run with `minds.only` set to Aldous is the cheap stage before: it shows whether the life alone yields the question, and how soon, under L against LS.

**Stages and cost.** No paid call is made until the owner authorises it.
- **Rate.** ar2 measured $0.149–0.174 per resident-hour on the people mix (glm-5-3-flash and deepseek-v4-1-flash, concurrency 64). Cullet's scenes hold more people (48 m sight in a town), so this plan budgets $0.16–0.20.
- **Per run.** 63 thinkers for 20 min is 21 resident-hours: **$3.4–4.2** a run.

| Stage | What | Cost |
|---|---|---|
| 0 | `just living-check`; the fake model on `verify-core`/`verify-minds` scratch databases: the selector picks the newcomer, not an unrelated resident, and a written routine fires | free |
| 1 | single thinker (Aldous), L and LS, 4 replicates | about $0.5 |
| 2 | pilot: all minds, C, L and LS, 1 replicate | about $10–13 |
| 3 | full: C, S, L and LS, 4 replicates (16 runs) | about **$54–67** |

**Not covered:**
- a player who answers;
- other worlds, where the `seen` fact of §1 matters;
- nights, when Anselm wakes;
- whether contact lasts beyond 20 minutes.

The unheard-line problem of ar2 (a `say` beyond earshot) is not fixed on main and will recur. It is counted, not excluded.
