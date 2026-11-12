# Strangers: noticing a newcomer by personality and duty (design, 2026-11-11)

Status: **design approved 2026-11-12 with the decisions at the end; nothing built or run yet.** It is read from main `feb6a10c`. The ar2 figures come from the arrival batch on branch `trials-ar2` (docs/TRIALS.md, "Arrival batch ar2").

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

**For Cullet the name fact is enough, but the scene's word was not (corrected 2026-11-12, `far-label`).** "Everyone knows everyone by name and by face. A stranger has not been seen in living memory" (`bible.md:91`). All 64 residents are in one community, so `knows_name` is false only for the newcomer.

This section first said that the only person a resident's scene could call "a stranger" was the newcomer. That was wrong.
- **The cause.** Cullet's `perceived_of` law gives a name only within 24 m (`known_within`). Past it, a neighbour was labelled "a stranger" too, and still carried `"community": "yours"`.
- **The effect in stage 1** (docs/TRIALS.md, st1):
  - Aldous thought of far neighbours as "the west strangers carrying fish" and told Neve Calloway about them.
  - His mind wrote a relation "Tobiah Dunmore: stranger" from a far first sight ("A stranger (#19) came in from the west").
- **The fix.** The law now marks such a sighting `far`. Someone too far away to make out is "someone too far away to make out", known or not:
  - in the scene, with their `id` and with no `name` and no `community`;
  - in percepts and in players' `seen_*` labels.
  Nobody is told a first sight of them until they can be made out. A relation labelled "stranger" about someone whose name one knows is not written. Within 24 m an unknown person is "a stranger" and a known one is named, as before.

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

## Decisions (2026-11-12)

The general coordinator approved this design with the decisions below. Where they differ from §1–§6, they replace them.

1. **The filter fix is built behind a law switch.** With the switch on, `relation: "stranger"` means "I don't know their name", the scene's rule (`perception::knows_name`, §3). It is off by default and in arms C and L, and on in S and LS. Whether it becomes the default is decided from the results, and that decision goes back to the general coordinator, because it changes what existing graphs match.
2. **The two lives (§2) went to dev-box,** which owns Cullet's cast. dev-box may adjust the wording and will send the commit. Once the lives are on main, arms C and S run with Aldous Quill's and Ingrid Morrow's earlier text, so the arms still differ only as the table in §6 lists. The stage 2 runner must provide that override.
3. **The crowd first-sight gap is fixed now, for every arm.** The owner ruled against attention caps on 2026-11-10: everything in sight is perceived. Skipping the first-sight line for unrelated people when more than 6 are in sight (`brain.rs:1157`) is such a cap.
   - Several first sights may be batched into one line, but nobody seen for the first time goes unmentioned, and each gets its `familiar` row.
   - The fix merges before stage 2. It is therefore part of the Cullet baseline, not an arm.
4. **Runs:**
   - Stages 0–1 go now.
   - Stage 2 (about $10–13) is approved once four conditions hold: stage 1 looks sane, and speech-truth, the crowd fix and the two lives are all on main.
   - Stage 3 waits on stage 2's result.
5. **The target spread** is fixed below, before any run. It replaces §6's "shape written down before running".

### Target spread (fixed before any run)

The target is for the 63-mind Cullet world under §6's script.
- **Who is counted.** "In range" means within 12 m of the newcomer during a stand. About 10–16 residents are expected in range at 09:30 on the yard and the Fish Steps.
- **The four exclusive classes.** Each resident in range has exactly one, taken in this order of precedence by the end of the run:
  - *asks*: a line to the newcomer, heard or not;
  - *approaches silently*: comes within 4 m with no line;
  - *notices inwardly*: a thought names the stranger, with no act toward them;
  - *unaware*: none of these.
- ***Tells others*** is counted separately, over all 63 residents: a line about the stranger to someone else. A teller may be in another class, or out of range.

Bands for one run, in the arms with the lives (L, LS):

| Class | Count per run | Share of those in range | Who |
|---|---|---|---|
| Asks | 1–3 | about 10–25% | Aldous during his hours (9–15), plus at most 2 others. Most of the others have curiosity or sociability of 70 or more. |
| Approaches silently | 0–2 | 0–15% | anyone |
| Notices inwardly | 3–8 | 25–60% | at least as many as asks and approaches together |
| Unaware | at most 6 | at most 40% | every one of them still got a first-sight line (decision 3) |
| Tells others (all 63) | 1–4 | — | at least one teller out of range when the stranger arrived. Ingrid is a teller in 2 or more of 4 runs. |

**Also in L and LS:**
- the first line the newcomer hears comes within 5 minutes of the join in 3 or more of 4 runs, sooner in LS than in L if the routine matters;
- `converge_60s` is at most 3;
- `together_4m` is at most 2;
- the guards (false replies, repeated lines, and talk that led to something, net of placebo) stay within C's spread.

**In C and S** the same bands hold, except that asks may be 0–2 and nobody is required to ask. S is expected to match C.

**Out of shape, whatever the arm:**
- 5 or more askers in a run, the newcomer-law pattern from ar2;
- no asker in L or LS across 2 or more runs: the life does not lead to asking;
- unaware above 60% of those in range;
- 3 or more residents within 4 m at once.

**How the bands are read:**
- An arm is in shape in stage 3 when 3 or more of its 4 runs fall within every band.
- Stage 2 has one replicate per arm, so it is read against the bands as indicative only.
- These are the owner's target written as numbers, not a pass mark. The owner judges from the inspector pages, one per arm.

## Proposal: appearance as an authority fact (2026-11-12; not built)

Status: proposal only. It needs dev-box, which owns the character generator, and comes after play-test 6.

**The gap.** A player sees "a stranger in green and dark grey": the game names an unnamed person by the colours it draws (`living/game/src/looks.rs`). A resident sees the same person as "a stranger", and in its memory as "a stranger #77" (`fix-stranger-merge`). Two strangers in one scene are told apart by a player by their clothes, and by a mind only by an id it must never say aloud. The two controllers do not perceive the same thing.

**Where the looks come from today.** Only the client has them.
- `live::recipe_for` seeds `characters::Recipe::random_in(land_seed * k + id, folk, style)`. `folk` and `style` come from the authority's projection (`seen_characters`).
- The draw reads ranges, palettes and style presets from the git-ignored `assets/characters/recipes.json` (`just living-game-assets`).
- It yields:
  - `Colors`: hair, skin, eyes, top, bottom, shoes, accent, and per-piece outfit colours;
  - `Proportions`: legs, arms, torso, neck, head, shoulders, hips, build, hands, feet;
  - a height and a base model.
- `looks::colour_name` turns a colour into a plain word. The authority never sees any of this.

**Which fields.** Only what someone notices at a glance and could say:
- the top and bottom colour words (`colour_name`'s words);
- the hair colour word;
- a build band from `Proportions.build` and the height: slight, medium, heavy-set, tall, short.

Skin and eye colours, pieces and exact numbers are left out.

**How it would become an authority fact.**
1. **One generator.** The recipe draw (palettes, ranges, the seeded RNG) moves into `living_rules` (a `looks` module), with its data in the seed or a rules data file instead of a client asset. The client and the authority then draw the same person from the same inputs. This is dev-box's part: the generator and its data.
2. **One row per character, written once.** At birth or spawn, the authority writes a private `appearance` table: `id` as primary key, and the four words. It changes only when dress changes, which is not modelled. It is never written per tick, and it costs 64 rows in Cullet.
3. **Perceived through the projection law.** `appearance` becomes an input of `perceived_of` (`skills.rhai`, docs/PERCEPTION.md), like `band`. The law decides which words reach which observer:
   - the colours within sight by day;
   - only light or dark at night or past a distance;
   - the build always.
   The `seen_characters` projection carries it, so the client draws its label from the authority's words and not from its own draw. The mind's scene carries it the same way.
4. **Only for unnamed people.** `perception::label` becomes "a stranger in green and dark grey" when the name is not known. It is used in scenes, percepts ("For the first time you see a stranger in green and dark grey, 9 tiles west, wait."), memory names and the client. Named people keep their names. The #id stays for acts and memory and is never said.

**Cost.**
- About 8–12 tokens per unnamed person in a scene line or a first-sight line ("in green and dark grey, dark-haired, heavy-set").
- In Cullet only the newcomer is unnamed, so about 10 tokens a scene.
- On a world with several settlements, about 100–250 tokens a scene with 10–20 unnamed people in sight.
- Authority cost: one extra point lookup per perceived person when a projection is rebuilt, and no new subscription.

## Stage 2b (prepared 2026-11-12; not run)

One replicate of each of four arms, about $10. It runs only after fix-far-silence, far-handle and attention-cues are on main.
- **The arms:** C (`strangers-2b-c`), L and LS (`strangers-2b`, control and filter), and LS + cues (variant `strangers-filter-cues`: `stranger_by_name` and `cues_on` on).
- **The newcomer's walk.** It is player behaviour, not a fixture: after the stand at the arrival point, the newcomer walks the Strand (`walk_route`, a `goto` to each point as a player clicks along a street). It goes down from the Counting House yard to the quay and west along it, past the Fish Steps, where Ingrid Morrow mends, about 6 m off. Then it stands at the densest group as before.
- **Silent approaches** count only a `goto` or `follow` aimed at the newcomer, a wave or nod at them, or a path that bent toward them and stayed within 4 m for 6 s (`arrive_spread.py` `bent_toward`). Turning to face them is not one. A resident whose own routine only passes within 4 m is counted as `passed_by`.
  - Recomputed on stage 2's runs: approaches C 6→2, L 13→1, LS 6→2; passed by 4, 12, 3.
- **The cues arm** is a stub until attention-cues lands: today `set_world_law cues_on` is refused ("`cues_on` is not a law of this world") and the instance does not start.
- **Fake 5-minute pass** (`st2bf`, main `49dfc2cd` plus this branch):
  - C, L and LS ran to duration; the walk took about 35 s.
  - Ingrid got a first-sight line for the newcomer in all three ("For the first time you see a stranger, 8 tiles east, goto → (490,779)."), closest 0.6–3.5 m.
  - The cues arm was refused as above.

## Far handles (far-handle, 2026-11-12; built)

Stage 2 showed that the far label alone did not stop a mind from naming far figures (docs/TRIALS.md, "Strangers stage 2"):
- the far entry kept the person's id;
- the same prompt maps ids to names, in the community line ("Thessaly Marl (#15)") and the relations list.

The general coordinator decided on a handle of the sighting.

**The handle.**
- A person the `perceived_of` law marks `far` is named in a mind's scene and experiences by a handle: `1000000000 + n`, from the private table `far_handle` (`living/authority/src/far.rs`).
- It is never the person's id, so no other prompt line ties it to a name: not the relations, the community line, recall, a conversation or a plan.
- A figure out of the observer's sight for 60 s is a new sighting with a new handle.

**Acting on it.**
- Acts and graph targets that name the handle (`{"id": handle}`) reach the person (`brain.rs` `Target::Id`, `far::resolve`), and so does speech (`speech::speak`).
- `{"named": "..."}` finds only someone whose name the character perceives now, so a name cannot be tried on a figure.

**When they are made out.**
- When the character can make them out, the authority writes a `made_out` experience: "Bram is the one you saw too far away to make out." Its subject is the person and its object the handle.
- The mind's consolidation then merges `person:<handle>` into `person:<id>` (`MERGED_INTO`; `made_out_merges`). What it remembered of the figure carries over.
- Later far sightings get new handles, so nothing is renamed back.

**Other places checked.**
- Experience tags show the handle (`{someone too far away to make out=#handle}`).
- The speaker's "heard by" list (`line_heard`) names a far hearer by its handle.
- A far speaker cannot start a conversation (`talk.rs` `on_speech` needs a character).
- A relation cannot be written about a handle (`mind_update` needs a character).
- Players' rows keep real ids: their client draws by id. This change concerns minds.

**The check.** verify-minds `far-figure`:
- M's neighbour F is in M's relations, 5 m off under an overlay that makes everyone past 4 m far, and says a line.
- The prompt shows a far figure under a handle, the line tagged with that handle, and no line tying the handle to F's name or id.
- A wave at the handle reaches F.
- Brought within 2 m, F is made out (the handle is joined to F's id), and the scene names F.

**Measure change (2026-11-12, st2b analysis).**
- "In range" now includes the newcomer's walks (`human_route`), not only its stands. Anyone it passes within 12 m on the Strand is classed (`arrive_report.WALKS`; `arrive_spread.py --stands-only` gives the old measure).
- The target's "about 10–16 in range" was written for the stands. Re-scored, st2b has 18–24 in range.
