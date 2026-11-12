# Mind research ideas, ranked by evidence to effort (2026-11-12)

A research list, not a build. Branch `research-ideas`, from origin/main `dfbb3ae1`. Nothing here was run: it was written by reading the docs, trial records and code. No build, model call or database was touched. Three tracks already run in parallel: movement and navigation, wolf packs against people, and local models on the GPU. This list covers the other mind research worth doing, beside those three.

**How the ranking works.** Evidence is what the trial records already show: a measured gap, and whether the machinery to test it exists. Effort is engine work plus paid spend. An idea ranks high when the gap is measured and the test needs little or no new code. Every idea keeps the owner's standing rules:

- emergent, not hard-coded;
- the same rules and physical limits for minds and players;
- minds know only what they perceived or remember;
- no silent proximity-based knowledge copying;
- architecture changes only where general and shown necessary by measurement;
- arenas measure; they never train or install behaviour.

**Cost figures used** (hosted models: glm-flash with the deepseek-flash fallback):

| Unit | Figure | Source |
|---|---|---|
| One deliberation (think + compile) | about $0.0063 | coordinator's current figure |
| One thinking resident-hour, hamlet | $0.13 (about $1.5–1.9 per world-hour with 11–12 thinkers) | [bi1](TRIALS.md#mind-cost), [ar2](TRIALS.md#thinking-and-money-baseline-for-the-meters-alarm-level-change) |
| One Cullet arm, 63 minds, 20 minutes | about $2.5 | [st2](TRIALS.md#strangers-stage-2-2026-11-12-st2), [st2b](TRIALS.md#results-batch-st2b-2026-11-12-08330854) |
| One 10-minute arena fight | $0.026–0.053 | [r2b–r2d](TRIALS.md#arenas-r2-against-scripted-opponents-2026-11-12) |
| One newcomer life, single mind | $0.12–0.19 an hour | [l7, i11](TRIALS.md#baseline-on-main-cb5214b7-b6-b6b-s12-s12b-l7-2026-11-11) |

**Every batch below states its switches** (greet, park, timings, `force_outcomes`, `cues_on`, `first_sight_thinks`, `fast_lane_on`, `LIVING_*`) and runs 3–4 replicates. An arm is read beside its guards: false replies, repeated lines, and talk that led to something net of placebo ([feel-score caveats](TRIALS.md#owner-tuned-player-score)).

## The ranked list

| # | Idea | Engine change | Free work | Paid estimate |
|---|---|---|---|---|
| 1 | Projects across days: does a held aim turn into acts? | none (built, off) | fake proof, measure check | about $21 |
| 2 | Learning between fights by watching | trial files first; perception change only if the baseline shows the gap | fixtures, fake proof | about $2.5 |
| 3 | The rethink gate's quality cost in a world of minds | none (built, off) | replay on new evidence | about $16 |
| 4 | Speaking within earshot | small perception fact in the scene | scene check, fake proof | about $4 |
| 5 | Confabulation about one's own deeds | measure first; lever is mind-side | read-only measure over existing journals | about $10 |
| 6 | Why the run-born do not pair | none | read-only reading of bi1 | $0 extra (rides births 2) |
| 7 | Who lives where: finding people one knows | probably none | read-only audit | about $5 |
| 8 | Working together (carrying, building) | a general law, the owner's design call | count of joint work in existing runs | about $20, after a build |

Teaching by showing is under idea 2: it is the same perception gap applied to crafts.

## 1. Projects across days: does a held aim turn into acts?

**Why it matters.** The vision asks for "ends, goals, and chosen approaches" and for individuals who "become different through living" ([SIMULATION_VISION](SIMULATION_VISION.md#individuals-become-different-through-living)). The owner's play-test found that characters "feel like NPCs and that survival is too central" ([player-likeness](TRIALS.md#player-likeness-measures-2026-11-11)). The general coordinator's candidate "a mind's sense of time and plans across days" is this idea.

**Evidence.**
- Survival fills the plans: 3–28% of plans are about neither food nor warmth in every arm, and 6% in the valley lives that reached old age ([player-likeness](TRIALS.md#player-likeness-measures-2026-11-11), reading 1).
- Aims are held but never reached: lives hold 2–8 goals for a game day or more, yet on the island 0–0.5 per run reach an outcome in rows (reading 5). "Someday, a family of my own" was held 15–29 game days with no path.
- Promises fade: 15 residents planned to help the newcomer, and 4 ever decided an act toward it ([ls1/ls2 diagnosis](TRIALS.md#why-the-newcomer-got-so-little-diagnosis-from-ls1ls2-journals-and-rows)).
- Default-effort GLM "stalled in its head": "the vow is settled in my head and still breaks in my hands" ([life runs](TRIALS.md#what-kind-of-life-emerged)).
- The machinery is built and off: `LIVING_PROJECTS=1` ([LIVING_CORE, Projects](LIVING_CORE.md#projects-experiment-2026-11-11); [projects.rs](../living/mind/src/mind/projects.rs)). A `projects` variant exists in [variants.json](../living/trials/variants.json). **No paid run has measured it.**

**What is missing in the engine.** Nothing. The prompts suggest no aims; survival stays the body's business. The sense of time it needs is already in the edge (`since`, `progress`, `next_step`, fading at 40 min) and in agreements' `until`.

**What it measures.** The hamlet (`hamlet` × `default`, `projects`; Cullet's 48-minute day, so 2 hours is 2.5 game days) and the newcomer `life`. 3 replicates per arm, 2 hours.
- Primary: `life_feel.py` `own_project`, `project_acts` and `project_progress`; `goals_reached`; `plans_other`; `self_started`. Also `detail.projects.serves` per deliberation: the share of decisions that serve an open project.
- Horizon: projects held across a night and still served the next day. Ended `done` against `dropped`.
- Guards: starved; hunger peaks; the three talk guards; deliberations per resident-hour.
- Pass reading: `goals_reached` and `project_acts` above control's spread, with no guard worse. The measures are keyword heuristics, so the owner rates excerpts of both arms blind.

**Cost.**
- Free: a fake proof (`--fake`, both arms, 10 minutes) to confirm `# Your projects` reaches think prompts, and a check that `own_project` reads the `serves` field.
- Paid: hamlet, 6 runs × 2 h × 12 thinkers × $0.13 ≈ **$19**. Newcomer `life`, 6 runs × 2 h × about $0.14 ≈ **$1.7**. Total **about $21**.

**Risks against the rules.**
- A project section could become a goal list handed out. The tests pin that the prompt names no aim (`projects_into`). Keep it so, and do not seed projects in sheets for this trial.
- A project can harden into enforcement, like the stage-log reading about stances. Read the `ended` reasons and the stances beside them.

## 2. Learning between fights by watching (and teaching by showing)

**Why it matters.** It is the owner's earlier wish. [COMBAT_MIND §8 Q4](COMBAT_MIND.md#8-open-questions-for-the-owner), with the coordinator's recommendation: "a character learns from a fight it watches, under the sight rules, more weakly than from fighting it and more strongly than from being told". The world vision: "Research, observation, experiments, teaching … can develop understanding and capabilities" ([WORLD_VISION](WORLD_VISION.md#gods-skills-and-agi--agreed)). The owner wants the second fight to be "much easier" ([COMBAT_MIND rule](COMBAT_MIND.md#the-rule-this-design-follows)).

**Evidence.**
- Minds name a pattern from their own fights by the 3rd or 4th exposure, but the body's answer comes late or never: the heavy blow was answered 7 of 36 times (r2b+r2c) and 1 of 32 (r2d). The kiter was answered 17 of 132 times, 15 of those in one fight ([r2d](TRIALS.md#r2-again-with-what-a-character-is-told-fixed-r2d-10-fights-030)). A mind that arrived having watched the pattern could start where these end.
- **The gap is in perception, and only for minds.** A mind onlooker is told only the first blow of a fight: "{a} attacked {b}" at salience 0.7 ([act.rs](../living/authority/src/act.rs), the `first_blow` branch of the damage path). Later blows, dodges and blocks reach a mind only as fighter (`fight_report`, for the two who fight) or through the scene's `doing` field when it next deliberates. A human onlooker gets every release, hit, miss, block and dodge in sight through `combat_seen` ([COMBAT.md](COMBAT.md)): "Minds still perceive fights through `experience`, unchanged." The same sight rule therefore gives a player more than a mind.
- Crafts are the same: an onlooker gets one "{a} made a cloak" line at 0.3 ([act.rs](../living/authority/src/act.rs), `witnessed(... "craft" ...)`). Every technique newcomers learned came from experimenting: 36 of 36 in `la1`, 13 of 13 in the life runs. Teaching was decided 1–17 times per valley life and landed twice ([l7](TRIALS.md#baseline-on-main-cb5214b7-b6-b6b-s12-s12b-l7-2026-11-11)). The scripted teacher's cloak lesson failed when a slow GLM mind wandered off ([b4](TRIALS.md#what-the-minds-did)).
- R3 (the veteran against the fresh) is designed and not run ([COMBAT_MIND §5](COMBAT_MIND.md#5-runs-to-schedule)). The heavy fixture now approaches and lasts ([arena-heavy-fix](TRIALS.md#r2-results-r2b-10-fights-040)).

**What is missing in the engine.** First nothing: measure the watcher on today's perception. Then, only if the watcher shows nothing the fresh character lacks, one general perception change. A mind onlooker would get a per-fight account of what it saw, in the shape `fight_report` gives the fighters ("Grim struck Lio four times, each after a long windup; Lio dodged once"), written at most every few seconds per onlooker and asking for no thought. The same applies to a watched craft: a line for each making seen. This gives minds what a player's screen already gives the player.

Teaching by showing then needs no new act. Let a watched making raise the odds of the watcher's own later `experiment` with that material, as a Rhai law over what the watcher's experiences hold. The learner still spends the material, takes the 10 s and may fail. The teacher chooses to make the thing in front of them, or the learner watches unasked.

**What it measures.** R3 with a fourth arm. Arms, 4 replicates, 60 minutes, `arena-heavy`:
- veteran: fights A four times, with sleep between;
- fresh;
- **watcher**: sees A fight a scripted dummy four times from 8 m, then meets B with A's pattern;
- watcher-lookalike: as watcher, but B has a different pattern, to check that the lesson is not applied blindly.

Measures are [Measure 2](COMBAT_MIND.md#43-measure-2-across-fights-and-transfer): K against B, damage taken, outcome, the first thought that links B to what was watched, and routines ready at the start. For crafts: a hamlet arm where a resident crafts a cloak beside a newcomer that lacks it, against one where the newcomer only hears that cloaks exist. Measure experiments tried with hide and fiber, time to `cloak` known, and the source of the know-how row.

**Cost.**
- Free: the watcher fixture (trial files: a scripted dummy for A to fight), a fake proof of the four arms, and a scan of onlookers' experience rows to confirm what a watcher is told today.
- Paid: R3 with four arms, 16 runs × about $0.15 ≈ **$2.4**. After a perception change, one more watcher arm, 4 runs ≈ **$0.6**.

**Risks against the rules.**
- **Proximity copying.** Seeing must never grant know-how or a routine. The lesson is the watcher's own belief, consolidated from its own percepts. For crafts it is the odds of its own attempt, never the technique.
- **Battle load.** Witnessed blows already wake every minded onlooker in the 100-fighter collapse ([ATTENTION](ATTENTION.md#cost), [FAST_LANE](FAST_LANE.md)). An onlooker's account must not ask for a thought, and its rate must be bounded per onlooker. Measure the experience rows per second in a battle scene before it goes near a default.
- No fixture pattern, routine or lesson is installed in a character or seed.

## 3. The rethink gate's quality cost in a world of minds

**Why it matters.** "Budget and latency matter" ([SIMULATION_VISION](SIMULATION_VISION.md#behavior-execution-and-llm-reasoning)), and the contract's 2,000 characters at $0.13 per resident-hour would cost about $260 an hour. The vision also wants AI-controlled players to "recognize an approach is failing and reconsider without waiting only for dramatic external events". The gate decides exactly when that happens.

**Evidence.**
- Blind judging of 650 non-urgent deliberations: 42% wasted, mostly restated plans, phantom targets and asking loops; 16% would have hurt to skip ([MIND_HARNESS §6](MIND_HARNESS.md#6-rethink-gate)).
- Live, the gate cut deliberations by 37–50% and cost by 24–40%. **The quality cost is not established** ([LIVING_CORE](LIVING_CORE.md#robustness-layers-found-necessary-in-live-runs)).
- The live run used a lone newcomer among instinct residents. The worlds where minds answer each other (hamlet, Cullet) were never gated.
- The "quiet moment" timer drove 903 of 1,871 sleepers' deliberations in bi1. Reasons reused from an earlier thought are 31–55% of reason lines ([ar2](TRIALS.md#thinking-and-money-baseline-for-the-meters-alarm-level-change)).

**What is missing in the engine.** Nothing. `LIVING_RETHINK=jev|llm` is built, and `rethink-replay` and `rethink_report.py` exist.

**What it measures.**
- Free first: replay the gate (`rethink-replay`) over the all-minds evidence that now exists (bi1, ar2, st2b). Report hold rates, and which reasons it holds by kind: quiet moment, plan finished, feeling, first sight, cue.
- Then live: hamlet `default` against `rethink-jev`, 4 replicates × 1 hour, plus one Cullet pair (20 minutes, strangers script).
- Measures: deliberations and dollars per resident-hour; reaction to a plan broken (time from a failed act to a changed plan); ar2's contact measures in Cullet; the three talk guards; `plans_other`.
- Pass reading: cost down by more than the spread, and no guard or reaction time worse.

**Cost.**
- Free: replay (Jev is about $0.00006 a question, so pennies).
- Paid: hamlet, 8 runs × 12 thinkers × $0.13 ≈ $12.5, less in the gated arm. Cullet, 2 × $2.5 = $5. **About $16.**

**Risks against the rules.**
- A judge deciding when a character may think is close to an attention rule. Keep it a cost gate in the mind service with no world law. Urgent reasons, a player's acts and the first thought are never judged, as built.
- Held thoughts must keep their reasons, which they do (pending rows merge).
- The gate must not become the reason a character seems dull. The guards and an owner-rated excerpt pair are the check.

## 4. Speaking within earshot

**Why it matters.** "Free-form communication is required from the first slice", and the chain runs from the chosen speech to "eligible listeners' perceptions" ([SIMULATION_VISION](SIMULATION_VISION.md#communication-from-the-first-slice)). A line the listener never hears breaks that chain before interpretation begins, and listeners then read silence as refusal.

**Evidence.**
- In ar2's winning arm, 62% of lines to the newcomer were out of earshot. Re-asks ran 5–11 per run, and residents read silence never heard as a threat: "a stranger who lets five greetings pass … someone with a reason to keep quiet" ([ar2](TRIALS.md#what-the-inspector-shows-beyond-the-tables), item 4).
- Lines are spoken after the speaker moved: "You're close enough to hear me now…" said from 27 m, after a prompt that had the newcomer at 5.3 m (item 5).
- In ls1/ls2, 27 of the newcomer's 58 asks went to people out of earshot ([diagnosis](TRIALS.md#why-the-newcomer-got-so-little-diagnosis-from-ls1ls2-journals-and-rows)). The fast-iteration notes leave open "whether its scene says who is within earshot" ([candidates](TRIALS.md#fast-iterations)).
- ar2's recommendation names this a mind change to make before the next arrival batch ([ar2](TRIALS.md#recommendation-2)).

**What is missing in the engine.** One perception fact. Each person in a deliberation or talk scene would carry whether they are within one's hearing now, by the `senses` law the authority already applies to speech. A person sees how far someone stands and knows whether they could hear a call. This adds no rule about when to speak. Optionally, a `say` act with a named target could walk into hearing range as `give` walks into reach. That is act semantics the owner should approve, so it is a second arm, not the first.

**What it measures.** ar2's `arrive` trial with the `all` laws off (the owner rejected them; use main's defaults) on the hamlet, control against the earshot mark, 4 replicates × 14 minutes. Measures:
- the share of lines to the newcomer out of earshot (`arrive_report` reach);
- re-asks;
- the first heard line;
- "silence means trouble" readings (keyword, with examples);
- the three guards.

Also a Cullet 20-minute pair if the hamlet moves.

**Cost.**
- Free: a verify-minds scene check that the mark reaches prompts, and a fake proof.
- Paid: 8 hamlet runs × about $0.45 (ar2's per-run figure) ≈ **$3.6**. A Cullet pair adds $5 if wanted.

**Risks against the rules.** The mark is the character's own sense of hearing, not an omniscient channel. It must use the same law that decides hearing, at the moment of the scene, and say nothing about whether the listener is attending. It must not become "the engine waits to deliver speech".

## 5. Confabulation about one's own deeds

**Why it matters.** "Calling a record 'knowledge' must not make it an omniscient source", and the audit must separate what a character believes from what happened ([SIMULATION_VISION](SIMULATION_VISION.md#truth-perception-and-subjective-understanding)). A character wrongly sure of its own past is allowed. But a player cannot trust a world whose people routinely say they did things they did not, and those claims enter others' minds as testimony.

**Evidence.**
- The ladder newcomer told the scribe "about ten times" that it had read the signs while no read percept existed until minute 83 ([wide batch](TRIALS.md#results-of-the-wide-batch-finished-2258), arm 3).
- A theft owner thought "My berries are safely stored" half a minute after the theft percept ([b3](TRIALS.md#what-the-minds-did)).
- Residents promised berries they had eaten and lessons in techniques they did not know ([ls1/ls2](TRIALS.md#why-the-newcomer-got-so-little-diagnosis-from-ls1ls2-journals-and-rows)). Iteration 8's "You carry …" lines made residents more honest ("two berries is all I carry"), with no gain in help ([i8](TRIALS.md#fast-iterations)).
- Player memory's first summary overreached ("eating through their berries") ([w4](TRIALS.md#results-of-the-wide-batch-finished-2258), arm 8).

**What is missing in the engine.** A measure first. There is no count of claims against rows. The lever, if the count is high, is mind-side and general: a talk turn and a think step see the character's own recent deeds and their outcomes (the `act` experiences it already has), as iteration 8 showed what it carries. No rule refuses a false statement.

**What it measures.**
- Free: a read-only `confab_report.py` over existing journals (w2 ladder, ls1/ls2, ar2, st2b, bi1). It finds first-person claims of a deed in lines and thoughts ("I read", "I gave you", "I taught", "I built", "I already") and matches each against the speaker's act and percept rows within the claimed window. It reports supported, contradicted and unverifiable, with examples, per model. This gives the base rate.
- Paid, only if the base rate is high: hamlet control against the own-deeds section, 3 replicates × 1 hour. Measure contradicted claims per hundred lines, the guards, and `led_res`.

**Cost.**
- Free: the report.
- Paid: 6 runs × 12 thinkers × $0.13 ≈ **$9.5**.

**Risks against the rules.**
- Lies told on purpose are a character's right. The measure must tell a deliberate deception (a thought that says so) apart from a confused claim, and nothing may stop either.
- The audit's truth must never reach the character. Only its own perceived outcomes go into its prompt.

## 6. Why the run-born do not pair

**Why it matters.** "Population renewal comes from reproduction and fabrication … Extinction remains a possible simulation outcome" ([WORLD_VISION](WORLD_VISION.md#mortality-and-population-renewal--agreed)). A world renews only if people born in it choose families, by their own lives and not by a rule.

**Evidence.**
- In bi1, no world kept its numbers, and `gen2_births` was 0 in all four arms ([bi1](TRIALS.md#population)).
- Grown run-born people felt "You long for a child of your own." from minute 142–258, but planned to learn fire, cooking or fishing instead. The cap of 12 minds left others on their graphs for 6–149 minutes, and graph adults do not conceive ([journals](TRIALS.md#what-the-journals-showed-beyond-the-tables)).
- Kin paired in two worlds. The owner decided no kin rule and no roof rule ([decided](TRIALS.md#recommendation)). Births 2 (24 people, `minds.max` 48, 10 hours, about $137) is planned for this question ([births 2](TRIALS.md#plan-for-the-paid-batch-not-run)).

**What is missing in the engine.** Nothing. The mind question is what a run-born adult knows of its options: who is unrelated and unpartnered, and whether the longing has a person to attach to. Read it before adding anything.

**What it measures.** Add to the planned births-2 batch, at no extra paid cost:
- per run-born adult, the share of its deliberations whose scene held an unrelated adult who was not partnered;
- its longing percepts against its conceive acts;
- `birth_identity_system`'s narrative: does it name family aims?
- the time from adulthood to the first conceive decision.

Free now: the same reading over bi1's four worlds, to set the expectation before the paid batch.

**Cost.** Free reading. Paid: **$0 extra**, riding births 2's $137.

**Risks against the rules.** No pairing nudge, no matchmaking, no rule. Any lever that comes out of this (such as birth identities hearing what their parents lived) must be perception or memory, never a drive aimed at a partner.

## 7. Who lives where: finding people one knows

**Why it matters.** The coordinator's candidate. The vision's societies depend on seeking people out: trade, visiting, keeping promises across a day.

**Evidence.**
- Gaka tried to give berries when the newcomer "had walked out of sight", and Iseos tried 8 times ([ls1/ls2](TRIALS.md#why-the-newcomer-got-so-little-diagnosis-from-ls1ls2-journals-and-rows)). Agreements in the social runs were kept twice of four, the others forgotten when due.
- Minds plan around remembered ids and places that are gone: "My entire eastern map is phantom" ([life runs](TRIALS.md#where-it-stalled-or-looped-rows)). Partly fixed by `feedback-1` and the place clamp fix (8fd4f43).
- Minds can already name places in consolidation (`place` concepts, remembered-place selectors), and `home` resolves only to one's own home ([behavior graph](LIVING_CORE.md#behavior-graph)).

**What is missing in the engine.** Probably nothing. A mind can already remember "Ilsa's house" as a named place. Whether it does is the question.

**What it measures.**
- Free: a read-only audit of existing runs. Count acts toward a person not in sight (refusals "no #N in sight"). Check whether the mind held a place tied to that person, and whether a `goto` to it followed.
- Paid only if the audit shows minds lack such places when they need them: a hamlet trial where the newcomer is told one resident's home by another, against not told, and must deliver a promised give the next day.

**Cost.**
- Free: the audit.
- Paid: about 8 hamlet runs × 30 min ≈ **$5**.

**Risks against the rules.** No engine directory of homes. A home known only by being shown, told or visited, and wrong when the person moved.

## 8. Working together: carrying and building

**Why it matters.** The coordinator's candidate. The vision's "infrastructure is built from world resources", with "construction, maintenance and competition for resources" ([WORLD_VISION](WORLD_VISION.md#physical-economy-and-compute--agreed-direction)), implies work bigger than one person.

**Evidence.**
- The engine has no shared work: `build` and `craft` are one actor's acts, with fixed durations ([skills.rhai](../living/scripts/skills.rhai), `build_check`, `build_duration`). Nothing in a seed needs two people.
- Cooperation today runs through gives, stores into another's household store, trades and agreements, which the rules count and tell ([WORLD_RULES](WORLD_RULES.md)).
- Measured cooperation is thin: "work for keep is agreed in words only" ([candidates](TRIALS.md#fast-iterations)). No record shows minds trying to work together and being blocked.

**What is missing in the engine.** A general law, if anything: work that goes faster with more hands doing the same build, or loads beyond one pack that two can carry. That is the owner's design call: content shape, not mind architecture.

**What it measures.**
- Free first: count joint work in bi1 and st2b (gives and stores toward someone else's build, agreements about work, delivered or lapsed). Read whether minds proposed shared work in words.
- Paid only after a law exists: the hamlet with a build only feasible together.

**Cost.**
- Free: the count.
- Paid: after a build, about 6 runs × 2 h ≈ **$20**.

**Risks against the rules.** A task that requires cooperation is content; the cooperation must not be. No scripted helper, and no "join work" instinct. The rule is physics (hands, weight, time), the same for players.

## How these interact with the three other tracks

**Movement and navigation** carries ideas 4, 7 and 8:
- a line meant for someone fails when the body is elsewhere when it is said;
- a remembered home is useful only if the body can walk to it through gates;
- shared carrying is steering with two bodies.

So the earshot and who-lives-where measures should report navigation failures (unreachable, turned back) beside their own, so a result is not blamed on the wrong layer.

**Wolf packs against people** is the natural ground for idea 2. People who watch a pack hunt or fight a neighbour are watchers with no fixture. The pack track's battles also carry the same risk as the onlooker account: the 100-fighter collapse came from witnessed blows waking onlookers, so any perception change for watchers must be measured in a pack fight first. The fast lane, off by default, shares R3's arenas.

**Local models on the GPU** change every price here. The rethink judge (Jev) and the cheaper purposes (talk, consolidation, the fast lane) are the first candidates to move local, and idea 3's measure of quality against cost is the test any such move needs. A local model is not free in quality: a batch must hold one model mix across its arms and record it, or the arms are not comparable. Ideas 1 and 5 need more calls or larger prompts; a local tier would make their arms cheap to replicate more than the 3–4 this list assumes.

## Not on this list, and why

- **First sight asks for a thought** (minds noticing only what they know). It is built, off, and its paid stage (about $13) is already approved ([FIRST_SIGHT](FIRST_SIGHT.md)).
- **The fast lane** (minds planning too late in fights). It is built and off, and waits on the battle collapse ([FAST_LANE](FAST_LANE.md)). It belongs to the combat line.
- **Repeated lines.** They are guarded and low (0.03–0.17 share). Their remaining source is re-asks fed by unheard lines, which idea 4 addresses.
- **The player frame.** Its paid run pf2 is in the records (`LOST` against the guards, still running when scored). It is the coordinator's to re-read, not a new idea.

## SpacetimeDB

Ideas 1, 3, 5, 6 and 7 change no table, reducer, view or subscription. Idea 4 adds a field to the scene JSON the authority already builds for a deliberation request. That is private data the mind service reads as the owner; no client subscribes to it. Idea 2's later change adds experience rows, which the owner's [table performance](https://spacetimedb.com/docs/tables/performance/) guidance says to keep narrow and bounded; their rate in a battle is the measure that gates it. Idea 8 depends on the law chosen. None of these was designed against the docs in this pass: each build must read the relevant SpacetimeDB pages first, as AGENTS.md requires.
