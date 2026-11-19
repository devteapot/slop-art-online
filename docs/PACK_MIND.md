# Pack mind: wolves together against people together

Research and design, 2026-11-12, branch `research-packs` from origin/main `dfbb3ae1`. Nothing here was built or run: no build, no model calls. The owner's ask was a fight of "a bunch of wolves against a bunch of people", with the wolves cooperating.

The design follows the standing rules:

- **Emergent, not written.** We write no pack tactics: no roles, formations, leaders' orders or "you go left".
- **One set of rules.** Minds and players have the same rules and physical limits.
- **Perception only.** A wolf or a person knows only what it perceived or remembers. Nothing shared is hidden.
- **Architecture changes only where general.** A change must be general and shown necessary by a measurement.
- **Arenas measure.** They never train or install behaviour.

Sections:

1. what wolves do today and what cooperation can already happen;
2. the survey;
3. what each animal and person needs to perceive;
4. the brain;
5. the arena, with its measures and targets fixed before any run;
6. the build plan and its cost.

## 1. Today

### 1.1 Where wolves live

The shipped play worlds have no wolves. `hamlet.json`, `hamlet-6.json` and `cullet.json` have deer 0 and wolf 0 ([STAMINA.md](STAMINA.md#wolves-on-people-and-deer-before-and-after-fix-pursuit-speed-ecology-check-2026-11-12)). The island has wolves:

- 24 deer;
- an ordinary pack of 5 by the deer meadows;
- a bold pack of 4, 370–800 m from the arrival point and 40 m off the road.

So most of this note is about what packs would do once added.

A pack is only a placement. `SeedPack` (`living/authority/src/seed.rs`) puts `count` animals within 4 m of a centre. It writes each animal's `background` as `{"pack": "...", "bold": bool}` and can install a named instinct (`wolf_bold`). Founding animals are also spawned in their species' `group` (5 for wolves). After that, no table records a pack. A wolf has no pack-mate relation, other than parents and children, which it knows by name like anyone.

### 1.2 The graphs (`living/seeds/instincts.json`)

**`wolf`** is a `first` priority list, read top to bottom:

1. Flee a campfire within 5 m.
2. Flee the attacker when hurt within 8 s and below 25 health.
3. Eat meat carried, when hunger is above 15.
4. Take meat from remains it sees.
5. Attack the attacker when hurt within 5 s.
6. **Flee the nearest person within 7 m, unless hunger is 90 or more.**
7. At hunger above 50, attack the nearest deer. Failing that, at night with hunger above 88, attack the nearest person.
8. Sleep, wander or conceive.

**`wolf_bold`** is the same except:

- there is no fire branch;
- it flees below 20 health;
- it **attacks the nearest person within 10 m** before anything about deer;
- when fed, it goes home.

**`deer`:**

1. Flee the nearest wolf within 7 m.
2. Flee the attacker.
3. Flee the nearest person within 8 m.
4. Graze, sleep, wander or conceive.

**`person` (danger branches only):**

1. Flee a wolf when hurt and below half health.
2. Yield when losing.
3. **Flee the nearest wolf within 5 m.**

Nothing in the person instinct makes people stand together. The "a wolf near and others close by: attack it together" line in [LIVING_CORE.md](LIVING_CORE.md#graded-force-and-when-predators-attack-people-2026-09-28) describes the rule's design. The shipped instinct has no such branch.

The rules side (`living/scripts/skills.rhai`):

- **The dare law.** `dares(a)` refuses an animal's attack on a person ("you do not dare: people are dangerous"), approach included, unless one of these holds:
  - the animal is bold;
  - it is fighting back (hurt by that person within 10 s);
  - it is desperate (hunger 85 or more, no deer seen or smelled);
  - the person is easy prey: a child, below 35% health, asleep away from a fire, or **alone at night away from a fire** (`t.company == 0`).
- **Speed.** A wolf walks 3.4 m/s and runs 1.5×, 5.1 m/s, with a `charge` on its approach to a blow. A deer runs 5.55 m/s. A person outruns no wolf.
- **The bite.** The windup is 550 ms. It lands within reach plus a 1.8 m lunge. A bite does 7 against a person's 100 health. A wolf has 80 health, and a person's strike does 5.
- **The senses.** Sight is 11 m by day and 6 m at night, for wolves and people alike. A wolf smells deer and wolves within 150 m, and a deer smells wolves within 30 m.
- **Evaluation.** Each body's graph runs about once a second, and about 15 times a second for 8 s after any blow.

### 1.3 What a wolf perceives of its pack mates

| Fact | How a graph gets it | How a mind gets it |
|---|---|---|
| A mate is in sight, and how many | `sees`, `near`, `count {of: wolf, within}` (around *me*) | the scene's creatures, with direction and distance |
| A mate beyond sight | `smells` (150 m). `{"nearest": "wolf"}` resolves by smell when none is seen, so `follow` works at range | "You smell a wolf to the north-east, far, about 40 tiles" (at most 3 per kind) |
| What a mate is visibly doing, and how far into it | `doing {who: wolf, is: attack, phase: …}` (3.2, [PERCEPTION.md](PERCEPTION.md#what-someone-is-visibly-doing)) | `visibly: {is, phase, at}` |
| Where a fight is | the `commotion` target, a point, and the `commotion` desire weight | experiences of the fight |
| A mate's howl, yip or growl | **nothing**: no graph condition reads a heard signal, and no target points at a signaller | a percept, "Ash makes a long howl (howl), north", for bodies with a mind only. `perceive::minds_near` drops instinct-only bodies |
| A mate's health | `health_of` on a named or id target (band) | the wound band |
| Where mates are *relative to the prey* | **nothing**: `count` counts around me, never around a target | positions in the scene, which the model can reason over in words |
| The prey: hurt, alone, fleeing, facing away | only `health_of` on one already-chosen target. Targets are `nearest` by kind and relation. There is no "the hurt one", "the one alone" or "the one running" | health band, `doing`, position. Others' facing is not listed |

### 1.4 Minds

Wolves have minds like anyone. Their impulse is a small model call, or the `choose` mode, which picks one of a few template options; see [MIND_HARNESS.md](MIND_HARNESS.md#3-cheaper-animal-minds). The authority asks an animal's mind only while a person is within 25 tiles. Wolves have no fast lane: it is for people only (`fast.rs`). `LIVING_ANIMAL_MINDS=pack` makes the animal that thinks decide for the others of its kind that it sees, for 60 s. The others' graphs change with no signal they perceived. **That is shared hidden state.** It must stay off in every pack arena, and §4.4 proposes retiring it.

### 1.5 What the ecology runs showed

The runs are `wolf_ecology.py`, 48 game hours, instincts only ([STAMINA.md](STAMINA.md#wolves-on-people-and-deer-before-and-after-fix-pursuit-speed-ecology-check-2026-11-12)):

- **The island.** 0–2 attack episodes per 48 h among 277 people, and none deadly. The bold pack lives far from people.
- **The hamlet with a bold pack added.** 2–5 of 12 residents died in the first 12–18 game hours. All were badly hurt when they died, worn down over several episodes. None died after the deer boom fed the pack.
- **Cullet with 4 ordinary wolves.** No attack on any of 64 residents, by day or night.
- **Earlier (`la2`, `eco9`).** On the island under instincts, 9 of 10 wolves starved and they killed 0–7 deer per run. The stamina pursuit fix since then left the island's 9 wolves alive over 48 h.

An episode is one wolf on one person. No tool yet measures whether several wolves acted together.

### 1.6 Cooperation that already happens by accident, read from the code and not measured

- **Arriving together.** A bold pack starts within 4 m of itself, and every member attacks the *nearest* person within 10 m. That is usually the same person, so they arrive together and bite the same target. This "focus" comes from the shared start and the nearest-target rule, not from any wolf noticing another.
- **A partial ring from crowding.** Steering keeps bodies about 0.8 m apart (`separation`). Wolves converging on one person at a 1.5–3 m striking distance spread round it, about 20–30° apart per wolf. That is some angular cover with nobody choosing a side.
- **Wolves catch a deer between them (Muro's mechanism, by luck).** A deer flees only the *nearest* wolf, so a deer fleeing one wolf can run toward another wandering wolf. Since a deer outruns a wolf, this is the only way the faster prey gets caught, and today it happens only when the positions happen to fall that way.
- **Selecting the isolated, by a rule.** For ordinary wolves at night, the dare law permits an attack only on a person alone (no one with them) away from a fire, or on one badly hurt. That is a preference for isolated and weak targets, but it lives in the world's predator-fear rule. It is not cooperation, and the arena must read it apart (§5).
- **Sharing kills.** Remains feed whoever reaches them, so a kill feeds the pack.
- **People scatter.** Each person flees the nearest wolf within 5 m on its own. That spreads them out and makes isolation easy. It is the opposite of standing together.

### 1.7 What cannot happen today

- **Waiting for mates.** Only partly possible: a graph can hold until `count {of: wolf, within: 15, at_least: 2}`, but nothing in the shipped graphs does.
- **Choosing a side of the prey away from a mate** (Muro's second rule). Not possible: no condition or steering parameter reads mates' positions relative to a target. `circle` takes a fixed side.
- **Picking the weak, alone or fleeing prey.** Not possible: targets are only the nearest of a kind or relation.
- **Answering a howl or yip** with no mind. Not possible: a signal is not delivered to instinct-only bodies, and no graph reads one.
- **Striking from behind on purpose.** Not possible: others' facing is in no condition or scene.
- **People rallying to a call.** Partly possible. A `call` reaches 22.5 m on the island, and `heard_within` and `speaker` let a graph turn or walk to the voice. The shipped instinct does neither.
- **Carrying the hurt.** Not possible: there is no skill that moves another body.

## 2. Survey

### 2.1 How wolves hunt

- **The sequence.** MacNulty, Mech & Smith (2007, *J. Mammal.* 88:595–605) split a hunt into search, approach, **watch**, **attack-group**, **attack-individual** and capture, from more than 2,150 h of Yellowstone observation (517 elk and 134 bison encounters). "Testing the herd" is approach, watch and attack-group: the wolves run at a group, watch who falters, then switch to one animal. Mech, Smith & MacNulty, *Wolves on the Hunt* (U. Chicago Press, 2015), is the book-length account. Wolves persist in seeking vulnerable individuals (young, old, infirm), most hunts fail, and wolves avoid injury by choosing those few.
- **Group size.** MacNulty et al. (2012, *Behav. Ecol.* 23:75–82): elk-hunting success rises to about 4 wolves and then levels off, while each wolf's effort falls (free-riding). MacNulty et al. (2014, *PLoS ONE* 9:e112884): on bison, about three times harder to catch, success keeps rising to 9–13 wolves. Cooperation scales with how formidable the prey is. People who fight back are formidable prey.
- **Packs are families.** Mech (1999, *Can. J. Zool.* 77:1196–1203): a pack is parents and their offspring. "Alpha" leadership in hunts is not supported, so there is no leader to model.
- **Prey that stands its ground.** Mech (1966, *The Wolves of Isle Royale*): moose that stood and faced wolves were usually left alone, and those that ran were chased. Standing together works against wolves.
- **Relay chasing** (wolves taking turns to tire the prey) is reported anecdotally. The systematic Yellowstone work (MacNulty et al. 2007; Mech et al. 2015) describes group chases and switching targets, not organised relays. Treat relays as not established. They are not a target here.
- **Howling.** Harrington & Mech (1979, *Behaviour* 68:207–249): howls are immediate and long-range, scent marks long-term and local. Howling serves spacing between packs and assembly within one. Howls carry kilometres in open country (secondary sources give about 10 km). Wolves can tell individual callers apart. Short-range hunting signals (yips, growls) are less studied.

### 2.2 Cooperation from simple local rules

- **Muro et al. (2011, *Behav. Processes* 88:192–197).** Each wolf follows two rules:
  1. move toward the prey until a minimum safe distance;
  2. when close enough, move away from other wolves that are also near that safe distance.

  Tracking, pursuit and encirclement emerge, with no hierarchy or communication. Escobedo et al. (2014, *J. R. Soc. Interface* 11:20140204) add that role differentiation emerges in a homogeneous group, and that 4–5 is the most effective size for surrounding.
- **Janosov et al. (2017, *New J. Phys.* 19:053003), on catching a faster prey.** Here the prey is faster than its chasers, as a deer is faster than a wolf. Encircling arises directly from local chasing rules with delay and limited acceleration. Three chasers are optimal in 2D in a confined space, and odd numbers do better because an even number leaves a gap.
- **Boids** (Reynolds 1987, *Computer Graphics* 21(4):25–34) and zone models (Couzin et al. 2002, *J. Theor. Biol.* 218:1–11). Separation, alignment and cohesion with local neighbours give flocking. Our steering already has the separation term.
- **The selfish herd** (Hamilton 1971, *J. Theor. Biol.* 31:295–311). Prey that each move to reduce their own exposure end up grouped. This is the people's side of the same coin: grouping can come from each person's own safety rule.
- **Multi-agent reinforcement learning.**
  - Leibo et al. (2017, *AAMAS*, arXiv:1702.03037) built a "Wolfpack" game in which two wolves are rewarded for capturing prey together. Cooperation emerged, and more so with more capacity to implement complex strategies.
  - Lowe et al. (2017, *NeurIPS*, MADDPG) studied predator–prey "tag": learned predators herd and corner.
  - Baker et al. (2020, *ICLR*, hide-and-seek): teams developed six phases of strategy, including coordinated tool use, from a simple team objective.
  - Jaderberg et al. (2019, *Science* 364:859–865, Capture the Flag) report emergent teammate following and base camping.

  What these show is that individual reward plus local perception is enough for coordination. What we cannot take from them is the training: arenas never train, and a policy we trained and installed would be tactics written by proxy.

### 2.3 Cheap animal brains

- **Utility AI** (Mark, *Behavioral Mathematics for Game AI*, 2009; Mark & Dill, GDC 2010). Score each option from response curves over inputs and pick the best. Our graph's `desires` node is exactly this. Each desire has a weight built from signals such as hunger, hurt, threatened, alone, company and commotion. So a utility layer already exists inside the graph runner.
- **Behaviour trees** (Isla, "Handling Complexity in the Halo 2 AI", GDC 2005; Colledanchise & Ögren, *Behavior Trees in Robotics and AI*, 2018). Reactive priority (`first`), sequences and guards: our `first`, `seq` and `if`.
- **GOAP** (Orkin, "Three States and a Plan: The AI of F.E.A.R.", GDC 2006). F.E.A.R.'s squads looked coordinated though each soldier planned alone over shared facts. The lesson is that "coordination" read by a player often comes from individuals reacting to the same visible situation.
- **Small policies.** A tiny network per agent maps observations to actions in microseconds. It must be trained, which we may not do in arenas (above). A small *language* model picking among options (our `choose` mode) needs no training, and is the seam left for Track L (§4.3).

## 3. What each animal and person needs to perceive

### 3.1 The test for any addition

The addition must be something a player's client already draws, or could draw, from rows it receives, read through the same `perception::sensed` set as every other condition: sight, the field when `fov_on` is on, the sight line, and smell where the species smells. It must work the same for a wolf's graph, a person's graph, a mind's scene and a player's screen. No pack table, no shared plan, no "pack mate" flag. A mate is another wolf that I perceive.

### 3.2 Additions, smallest and most general first

Each addition is built only if the step in §6 before it shows it is needed.

| # | Addition | What it is | Who else uses it | Already perceived by players as |
|---|---|---|---|---|
| A1 | **Heard signals for every body** | `perceive::signal` also sets a per-listener "last heard sound" mark (what, from which kind, from where, when), including on instinct-only bodies. The mark sits beside the speech mark (`mind_state.speaker/heard_ms`). New condition `{"heard": {"is": "howl", "of": "wolf", "within_s": 10}}`. New target `"signaller"`: the creature if it is in sight, else the point it was heard from, as `speaker` resolves | people answering a baby's cry or a call; deer answering an alarm snort | the told line "You hear a long howl from a wolf, north" and `heard_sounds` |
| A2 | **Target filters on what is seen** | `nearest` gains optional fields: `hurt` (the observer's projected band, at or below "hurt", via `perception::health_seen`), `alone` (metres: no other of its kind within that distance, among the bodies I perceive), `stage` (`young`/`old`, from the label) and `running` (`body.running`) | a person going to the hurt or the one alone; a hunter picking the slow deer | health bands in `seen_fighters`; positions; the gait in `seen_bodies.running` |
| A3 | **Others' facing** | Each creature in a mind's scene gets `faces: "you" \| "away" \| <compass>`. New condition `{"faces": {"who": F, "me": false}}` | a sneak; guarding toward a threat; a person turning their back | the drawn body's facing (`motion_seen` since look-2) |
| A4 | **Counting round a target** | `count` gains `around`: count creatures of a filter within `within` m of a target, not of me | "is anyone with the hurt one?"; "how many wolves are on her?" | positions |
| A5 | **Keeping apart while closing** (only if A4 plus `circle` cannot spread wolves; §6 step 2) | An optional `apart: {of: F, m: 4}` on `keep_distance`, `circle` and `close_in`. While holding the goal, the body also keeps `m` from seen bodies of filter F that are themselves within the band of the same target. This is Muro's rule 2 as a steering parameter. It is not a tactic: it never says where to go, only how far to keep from whom | people forming a line or a ring; herders; a crowd round a stall | positions |

### 3.3 The prey's state

A2 gives the prey's state:

- **hurt** is the band anyone sees;
- **alone** is the distances anyone sees;
- **fleeing** is `running` plus the existing `doing`;
- **engaged with a mate** is `doing {who: person, is: hostile, at_me: false}`, which exists today.

### 3.4 Signals as sound

Howls stay species signals under the existing rules (`species.json` range, salience, the 45 s repeat rule). Their reach is species data: the howl is 18 m today, against kilometres in the field (§2.1). Whether to lengthen it is world content and the owner's call. The arena runs it as shipped, plus one arm at 150 m, matching the wolves' scent radius, to measure what the reach does. A shout is heard by animals as "a person shouting" out to 2.5× hearing. Nothing here makes a howl carry meaning: a wolf learns what a yip near a fight tends to mean, or does not.

### 3.5 The people's side, with the same additions

- **Calling for help.** This exists: `call` at 22.5 m, and `heard_within` plus `speaker` to go to the voice. A1 lets a person's graph also answer a howl, for instance by moving toward others.
- **Standing together.** This exists as `follow`, `keep_distance` from a friend, `count` of people, and the `company` and `alone` desire weights. A2's `alone` lets a person go to whoever is alone, and A5's `apart` lets people hold a ring without bunching.
- **Fire.** Campfires exist, and ordinary wolves flee them within 5 m. A lit torch carried is seen only as light. Making "carries a lit torch" perceptible would need the client to draw held items first: open, not proposed here.
- **Carrying the hurt.** This needs a new shared skill (`carry`: lift a badly hurt, yielded, sleeping or infant body; walk slowed; no fighting). That is new mechanics and feel, so it is the owner's decision. It is not needed for the first arena and is listed in §6 as optional.

### 3.6 No shared hidden state, checked

- A1 reads a sound the listener's body heard.
- A2–A4 read rows that players' clients receive (`seen_bodies`, `seen_fighters`, `seen_doing`).
- A5 is steering on bodies in sight.

None reads another body's graph, plan, mind or intent. The `pack` mind switch (§1.4) fails this test.

### 3.7 SpacetimeDB data paths

The official pages were checked by search on 2026-11-12: [Performance](https://spacetimedb.com/docs/tables/performance/), [Tables](https://spacetimedb.com/docs/tables/) and [Indexes](https://spacetimedb.com/docs/tables/indexes/). They recommend preferring indexed lookups over full scans, splitting tables by how often data changes, and adding indexes only for real query patterns. They also say views read only through indexes. The full pages were not re-read this turn. [PERCEPTION.md](PERCEPTION.md#spacetimedb-documentation-consulted-2026-11-12) records the same pages for the same access pattern against the pinned 2.14.1. The build steps must re-check them, as AGENTS.md requires.

- **A1.** One write per listener in range per signal, to an existing private row (`mind_state`) already written for speech. No new table, view or subscription.
- **A2–A4.** Reads only, over the evaluation's existing scene: primary-key reads of `vitals`/`fighter`/`body`, bounded by sight (at most 84 creatures per scene in the doing-cost run). The `alone` test is pairwise over the scene and is computed once per evaluation. A3 reads the `body` row already read.
- **A5.** A parameter on the private `steer` row: an appended column with a default, an automatic migration.
- **Never.** A scan of `character` or `body`, a pack table, or a view over packs.

## 4. The brain

### 4.1 Where it runs

| Option | Real-time? | Cooperation from | Fits the rules? | Choice |
|---|---|---|---|---|
| **Graph runner, as today** (each wolf's own graph; `desires` as the utility layer) | yes: 1 Hz, 15 Hz in a fight | each wolf's own conditions over what it perceives | yes | **the body's brain** |
| A separate utility layer | yes | the same | it duplicates `desires` | no: extend desire signals instead (e.g. a `prey_hurt` weight from A2) only if a measure asks for it |
| Fast lane | ~3 s from a blow to a patch | a model call per trigger | people only. The global cap (2/s) gives 60 wolves one call per ~30 s | no, not for wolves |
| Animal mind, `choose` + `salient`, without `pack` | slow (seconds), occasional | the wolf's own impulse revising its own graph | yes | **the slow revision layer, as today** |
| Small local model (Track L) | depends on Track L's latency | the same impulse, cheaper | yes, if it reads the same prompt | **the seam, §4.3** |
| Trained policy | yes | training | no: arenas never train, and an installed policy is tactics by proxy | no |

### 4.2 Cost

The figures are from measurements already in the repository. They are not new.

| | 6 wolves | 60 wolves |
|---|---|---|
| **Graph evaluations.** About 0.07 ms each with the scene (`brain.doing` p50 0.068 ms, [PERCEPTION.md](PERCEPTION.md#data-paths-and-cost)); 15 Hz while fighting | 90/s → about 6 ms of work a second (≈0.1 ms a tick) | 900/s → about 63 ms a second (≈1 ms a tick). The doing-cost battle (100 fighters, ~1,000 evaluations/s) kept tick p99 at 9.2 ms with none over 16.7 ms |
| **Steering intents.** About 0.14 ms of tick time a second per intent ([COMBAT_MIND.md](COMBAT_MIND.md#33-movement-as-intent-the-body-carries-out-steering-rules)) | ~0.8 ms/s | ~8 ms/s |
| **Scent.** 0.26 ms/s for the island's wolves at 1 Hz | <0.3 ms/s | ~2 ms/s (estimate, linear) |
| **A1–A4** | ≤ tens of µs per evaluation, inside the figure above | the same per evaluation |
| **Animal minds** (GLM Flash, all three switches: €0.0027 per animal-hour, 70% of it memory; switches off €0.0050) | ≈ €0.02–0.03 an hour on stage | ≈ €0.16–0.30 an hour on stage |

The 60-wolf rows are estimates scaled from those runs. They are not a performance claim. A 60-wolf battle sits inside the contract's 200-character battle and must be measured there. The 100-fighter battle collapse under diagnosis ([FAST_LANE.md](FAST_LANE.md#per-battle-of-20-fighters)) is a known confound.

### 4.3 The seam for Track L

There are two seams. Neither needs a new protocol.

1. **Animal `think`.** The animal `think` purpose is routed per species in `living/configs/models.json` (`species.wolf.think`). Any OpenAI-compatible endpoint is a profile, so a local server on the Spark's GPU becomes one. The `choose` prompt is about 1.1k tokens a call (4,526 prompt tokens over 4.1 calls per animal-hour), and the reply is an option number and a strength. That is the right size for a small model. At 60 wolves the need is about 0.07 calls/s at rest and a few a second in a fight.
2. **The `judged` cache.** A graph reads a cached judgment of the character's own (`{"judged": {"q": …}}`) and never waits on it, falling back to `else`. A local model could refresh a wolf's own judgment ("is this one weak?") from its own scene at a few Hz.

Either way, the input is the wolf's own scene and the output is the wolf's own graph or judgment. Track L supplies the latency and quality numbers. This note does not assume them.

### 4.4 How cooperation would emerge from each wolf's own rules

Nobody writes a pack rule. Each wolf's graph, first the species instinct and later what its own mind writes, reads only its own perception:

- **Muro's rules as individual reflexes.** "Close to a safe distance from the prey" is `keep_distance {min: 3, max: 5}` on a target. "Keep away from other wolves also close to it" is A5's `apart`, or a choice of `circle` side from A4. Encirclement is not written anywhere. It would appear, if it appears, because every wolf does this round the same prey while the prey moves.
- **Choosing the moment.** A wolf may bite when the prey's `doing` shows a hostile move at another (`at_me: false`) or when `faces {me: false}` holds (A3). It then strikes from behind because the prey turned to a mate, not because a plan assigned it the back.
- **Selecting the weak.** `nearest {kind: deer, hurt: true}` or `{kind: person, alone: 8}` (A2) is each wolf's own preference. Focus on one target follows when several wolves see the same weakest one.
- **Gathering.** A yip at a fight (`signal`) is heard (A1) by mates, who may go to the `signaller` or the `commotion`. Whether a wolf yips, and whether its mates come, is each wolf's own graph.
- **Where those graphs come from.** Two places. (a) Minds write them: the strongest claim, since no one wrote them for the wolf. (b) The species' starting instinct: seed content, which we write as we wrote "attack the nearest deer".

**Owner decision.** May a starting instinct contain an individual-level spacing reflex (Muro's rule 2), or must every such rule be a mind's own? Until decided, the Muro graph is used only as an arena fixture, to calibrate the meters and to show whether the physics allows encirclement. It is never shipped.

**Retire `LIVING_ANIMAL_MINDS=pack`.** Replace it with each wolf's own `choose` call: about 1.7 more calls per animal-hour at €0.0008 decision cost, so pennies. Until then, every arena records it as off.

## 5. Arena design

### 5.1 The setup

The arena is a [trial](TRIALS.md) like the combat arenas ([COMBAT_MIND.md §4.1](COMBAT_MIND.md#41-arenas-are-trials)). It is a trial file in `living/trials/` with a cast, timeline `place`/`graph`/`call` steps and replicates, run by `trials.py` on scratch worlds.

- **World.** The island seed, with a clearing of open grass: no structures within 40 m and no road. Wolves come from the island's packs and people from its residents, placed there. Hunger is set by timeline step so that ordinary wolves are hungry (90) and people fed. The world is deleted after the evidence is taken.
- **Starts.**
  - *Clustered*: the wolves within 4 m of each other, 25 m from the people.
  - *Scattered*: the wolves on a 25–40 m ring round the people, at random bearings at least 60° apart. Only scattered starts can show coordinated arrival that the placement did not cause.
- **Sides.** 3v3, 6v3, 3v6 and 6v6 (wolves v people). Then **mixed**: 6v6 plus 12 deer within 60 m.
- **Wolves.**
  - *Bold* by day. The dare law is off for them, so any isolation they show is theirs.
  - *Ordinary* hungry at night, with and without a campfire at the people's start. The dare law selects people who are alone away from fire, so isolation there is partly the rule's (§1.6).
- **Controllers, the free tiers.** Instinct against instinct; the Muro fixture wolves (calibration) against instinct people; instinct wolves against people with the fake model.
- **Controllers, the paid tiers.** People with minds; wolves with minds (`choose,salient`, no `pack`); both with minds.
- **Cap.** 10 real minutes a run.
- **Replicates.** 6 per free arm, 4 per paid arm.
- **Recorded switches**, per the batch-record rule: `LIVING_ANIMAL_MINDS`, `fast_lane_on`, `fov_on`, `force_outcomes`, the howl range, and `skills.sha256` against main.

### 5.2 Sampling

- **Positions and facing.** `body` rows (x, y, vx, vy, t_ms, next_ms, facing), projected to the sample time at 5 Hz.
- **Blows.** `skill_use` (actor, target, skill, accepted_ms, outcome) for every blow begun and its result.
- **State.** `fighter` for bands, and `character` for deaths and their cause.
- **Activities.** The wolves' activity targets, read as audit truth by the measure only.
- **Tool.** A new `living/tools/pack_arena.py`, read-only, with a self-test on synthetic tracks that reproduces the nulls below.

### 5.3 Definitions

- **Contact ring** of a person p: r_c = 3.5 m (the attack reach of 1.4 m plus the wolf's 1.8 m lunge, rounded up).
- **Engagement** e on target p:
  - It begins at the first blow any wolf begins on p.
  - It ends when no wolf has begun a blow on p for 20 s (as `wolf_ecology.py`'s `EPISODE_S`), or when p dies.
  - Its wolves are those that began a blow on p within it.
- **Arrival** a_w: the first time wolf w is within r_c of p, after its last time at 10 m or more from p.

### 5.4 The measures

**M1. Coordinated approach.**

- **Defined.** For an engagement with two or more wolves, the arrival spread S₂ is the second arrival minus the first. S₃ is the third minus the first. An engagement is *coordinated* when S₂ ≤ 3 s, about five bite windups and less than a turn and a guard. *Holding*: the share of an engagement's wolves that stayed 4–10 m from p for 2 s or more before their arrival.
- **Reported.** The share of multi-wolf engagements that are coordinated, the median S₂ and S₃, and the holding share. Scattered starts only.

**M2. Flanking angle spread.**

- **Defined.** At each sample of an engagement with k ≥ 2 wolves within 6 m of p, take the bearings θᵢ from p.
  - **Coverage** C = 360° minus the largest circular gap between consecutive bearings. For k = 2 it is the angle between them.
  - **Concentration** R̄ = |Σ e^{iθᵢ}| / k. 1 means all on one side, 0 means evenly round.
  - **Rear-blow share**: of the blows begun on a p that was *not running* at release, the share from outside p's facing ±75° (the block arc).
- **Reported.** The time-weighted median of C and R̄ per engagement, by k, and the rear-blow share.
- **Nulls**, computed by the tool's self-test, for uniform random bearings:
  - mean coverage is 90° for k = 2, 140° for k = 3 and 172.5° for k = 4;
  - the rear share is 58% (210 of 360°).
- **Muro's even ring** gives 180° for k = 2, 240° for k = 3 and 270° for k = 4.
- **Encircled**: a sample with k ≥ 3 and C ≥ 180°. Reported as the share of engagement time.

**M3. Isolation of one target.**

- **Defined.** d_iso(p, t) is the distance to the nearest other living person.
  - **(a) Selection index.** I = (share of wolf blows begun on people with d_iso ≥ 8 m) ÷ (share of person-seconds with d_iso ≥ 8 m among people with a wolf within 15 m). I = 1 means no preference.
  - **(b) Cut-offs.** Count the events where p's d_iso goes from ≤ 5 m to ≥ 10 m while a wolf w is within 8 m of p and lies between p and the centroid of the other people (the angle at p between w and the centroid ≤ 45°). Reported per engagement-minute.
  - **(c) Focus.** Within each 20 s window with pack blows, the share of the pack's blows that fall on its most-struck person, against 1/n for the n people within 6 m of any striking wolf.
- **Read on bold arms.** On ordinary night arms, I is partly the dare law's.

**M4. People grouping.**

- **Defined.** Cluster the living people at each sample by single linkage with a 4 m link.
  - **G(t)** = the mean over people of the size of their cluster, divided by the number alive. 1 means one group.
  - **ΔG** = the median G over the 30 s after the first wolf comes within any person's sight radius (11 m day, 6 m night, clear line), minus the median G over the 30 s before.
  - **Standing together**: the share of blows on people where the struck person had another person within 4 m.
  - **Assist rate**: the share of people's blows aimed at a wolf whose current blow or activity targets a *different* person.

**M5. Casualties.**

- **Defined.** People killed by wolves; wolves killed by people (from `character.cause`); health lost per side (from `fighter` band changes and `skill_use` outcomes); wolves routed (fled below their flee threshold).
- **Reported.** Per replicate, with the median and range per arm.

**M6. Duration.**

- **Defined.** From the first blow begun by either side to the end. The end is the first of:
  - one side all dead;
  - every survivor of one side more than 30 m from every opponent for 30 s;
  - the 10 minute cap.

  The time from the start to the first blow (search and approach) is also reported.

### 5.5 Targets and spread, fixed before any run

- **The decision rule.** An arm *differs* from its control on a measure when its median lies outside the control's replicate range (min–max), and at least ⅔ of its replicates do too. With 6 or fewer replicates per arm, no p-values are claimed.
- **Today's instinct baseline: our prediction, to be checked.**
  - Clustered bold starts: S₂ ≤ 1 s (by placement), C at k = 3 of 40–90° (crowding, below the random null), I ≈ 1 (nearest target), ΔG < 0 (people scatter).
  - Scattered starts: coordinated share ≤ 20%.
  - Ordinary wolves by day: no blows on fed, grouped people.
- **What would count as cooperation having emerged**, on scattered starts and bold arms, against the instinct control by the rule above:
  - **M1:** the coordinated share is at least 50%.
  - **M2:** median C at k ≥ 3 is at least **180°**, above both the 140° random null and the control; R̄ ≤ 0.5; the rear-blow share is above 58%.
  - **M3:** I ≥ 1.5, and cut-offs above the control.
  - **M4 (people with minds):** ΔG > 0 and the assist rate above the control.
- **The calibration fixture** (Muro graphs) must reach the M2 target. If it cannot, the world's physics or steering is what blocks encirclement. That result is the measurement that would justify A5, not the minds.
- **M5 and M6 have no targets.** They are reported for the owner's feel, beside two references: a 1v1 fight between a person and a bold wolf lasts about 24 s, and a bold pack killed 2–5 of 12 villagers in its first half day.
- **Guards against putting it there.**
  - Audit every prompt sent for pack-tactic words ("surround", "flank", "encircle", "cut off", "pincer", "drive") outside the character's own experiences and memory.
  - Check `skills.sha256` against main.
  - Move no routine, stance or graph from an arena into a seed.
  - Delete the arena worlds once the evidence is taken.

### 5.6 Amendments before the first measured run (2026-11-12, branch `packs`)

Found while building step 0, from two pipeline probes (`pk0`, `pk1`, 4 minutes each, not counted as evidence). Written before any baseline run. The measures and targets of §5.4–5.5 are unchanged except where said.

- **Starts.** Day sight is 11 m, wolves do not smell people, and the bold instinct attacks only a person within 10 m. So the two starts are:
  - *close*: the pack in a cluster about 3 m across, its centre about 10 m west of the people's centre, every wolf in sight of them. M1 is reported for close starts but not read: arriving together is the placement's doing.
  - *spread*: the wolves 15–35 m west of the people, in a 120° sector (bearings 138–210°), each at least 9 m from the others (3 wolves at 15, 25 and 35 m; 6 wolves at 15, 20, 25, 28, 30 and 35 m). They start out of sight, so arriving together needs a wolf to wait or gather. This replaces "a 25–40 m ring at random bearings at least 60° apart". For 6 wolves that rule forces an even ring, which would put the encirclement in by placement.
- **The arena is cleared.** The island's other wolves are moved to the map's far corner and kept still (`wait`). Outside the mixed arm, so are its deer.
- **People.** The people are adults of Brackenford, with items and routines cleared, on `instinct:person`. That instinct never strikes back (§1.2), so under instincts the people's blows, and with them M4's assist rate, are empty.
- **ΔG on close starts.** The wolves are in sight from the first sample. "Before" is then G at the first sample.
- **Not run in step 1: ordinary wolves at night.** No admin reducer sets a wolf's hunger. Ordinary wolves dare a person only when desperate (hunger 85) or, by the instinct's branch, at night with hunger 88. The bold night arm stays.
- **A harness bug, fixed.** The trial runner's `background` step wrote `"bold": true`, and the authority reads `"bold":true` from the text (`act.rs`). So a pack made bold *through that step* never was bold. `trials.py` now writes backgrounds compact. The authority's text match is fragile, but it is left as it is (a rules change, not needed here).
  - **Corrected 2026-11-12:** this note first said that no trial before it ever had a bold pack, "`pack-mind` included". That was wrong. `pack-mind` picks the island's seeded bold pack and never uses the step.
  - **Every pack made bold by a seed is unaffected.** `seed.rs` writes its background as compact JSON, which the authority reads. That covers the island's bold pack, `life-pressure`'s packs, and the hamlet + bold pack overlays of `ecology-pursuit` and `pursue-last-seen`.
  - **The two ecology checks were bold.** Read from their samples: in all 8 `ecology-pursuit` hamlet runs and all 4 `pursue-last-seen` runs, the pack's first attack on a person came within 0.7–3.6 game hours, on an adult at full health, awake, by day. Each run had 47–95 such attack starts, which no dare exception allows a wolf that is not bold. Their figures (STAMINA's "deaths rise by about 1.6×" included) stand.
  - **The only trials affected** were this branch's own arena files, fixed before any measured run (the `pk0` probe was discarded).
- **Sampling.** `record.bodies` reads five tables per sample, concurrently (2.14.1's SQL endpoint takes one statement a request). The rate actually reached is reported per run.
- **The calibration fixtures (step 2).** Both live in their trial files only.
  - **C1, "sides".** Each wolf circles the nearest person at 4 m on an assigned side, alternating left and right, and bites, with chance 0.3 a check, when within 3.5 m. The sides are assigned by us, so this shows only whether steering and the bite let wolves on different sides form a ring.
  - **C2, "Muro with today's grammar".** No sides are assigned. Each wolf, in order: flees when badly hurt; if another wolf is within 3 m and a person within 6 m, backs off 4 m from that wolf; if a person is within 3.5 m, attacks with chance 0.3 a check; otherwise keeps 3–5 m from the nearest person.
  - **Reading.** If C2 reaches M2's 180° at k ≥ 3, a keep-apart reflex is expressible today, and under the owner's rule below it may go in the starting instinct. If only C1 reaches it, the gap is in what a wolf can perceive or steer by (A4, A5). If neither does, the physics blocks encirclement.

### 5.7 Decisions (owner, 2026-11-12)

1. **The spacing reflex** is allowed in the wolves' starting instinct, but only if calibration (step 2) shows it is needed. It takes the form of a weighted desire ("keep apart from mates") in the starting graph. The wolf's own mind must be able to revise it, and it names no target and no role. The rule it was made under: the starting instinct holds individual drives, as it already holds "attack the nearest deer". It never holds a group plan.
2. **The howl's reach** becomes the howl's loudness in its sound spec, under the same loudness rule that wakes sleepers (`fix-sleep-talk`). The 150 m arm measures the difference. The result goes to the owner before the shipped value changes.
   - **Built on `packs-2`.** A species signal with no `range` carries its `loudness` times each listener's hearing (`Signal::reach`), as a way of speaking does. The shipped howl is now `loudness: 2` with no range: 18 m on the island's 9 m hearing, its old reach, and 24 m where people hear 12 m (Cullet, which has no wolves).
   - **One consequence.** As loud as a shout, a howl now wakes a sleeper within `wake_reach` (8 m); before, with loudness 0, it woke no one.
   - **Unchanged.** The other signals keep their ranges.
   - **The 150 m arm** is `pack-minds-howl150-spread-6v6`, a world override of the howl to loudness 16.7. It runs in the paid step.
3. **`carry`** is on hold.
4. **The hidden `pack` copying** is retired in this work (`LIVING_ANIMAL_MINDS=pack` is ignored with a warning). verify-minds `animals` checks that each animal of a herd makes its own decision.
5. **The paid step** is approved up to $10, but only after battle-scale's fixes 1–3 are on main. The thresholds are committed before the first paid call, and the owner is asked before it starts.

## 6. Plan and cost, smallest first

| Step | What | Tier | Cost |
|---|---|---|---|
| 0 | Write the arena trial files and `pack_arena.py` with its self-test (the nulls of M2 from synthetic tracks). Check that trials can cast and place several wolves and people and set hunger. No world change | free | none |
| 1 | **Baseline on main.** Instinct against instinct: clustered and scattered; 3v3, 6v3, 3v6, 6v6; bold by day; ordinary by night with and without fire; 6 replicates each. This checks §5.5's predictions | free | none; ~16 arm-sets × 6 × 10 min on the trial server, about 16 h of server time, run outside the quiet window |
| 2 | **Calibration.** Muro fixture wolves (existing `keep_distance`, `circle`, `count`), clustered and scattered, against instinct people. Does the physics allow M2's target? | free | none |
| 3 | Build the perception additions, each only if steps 1–2 show it is needed: A1 heard signals, then A2 filters, then A3 facing, then A4 `around`, then A5 `apart` (only if step 2 failed for lack of it). Each comes with its verify-core scene, verify-minds for the grammar and scene, and `maintain-verification-skill` on the surfaces it reshapes | free | engineering only |
| 4 | Retire the `pack` switch, or record it as off | free | none |
| 5 | Fake-model arms: wolves and people on the mind pipeline with `--fake`. Check the plumbing and that minds' grammar documents A1–A4 | free | none |
| 6 | **Paid.** People with minds against instinct wolves; wolves with minds (`choose,salient`) against instinct people; both with minds. 6v6 bold by day, scattered; 4 replicates × 10 min. Then mixed (plus deer), 4 replicates | paid | ≈ 16 runs. People on stage cost about $0.14–0.24 per person-hour (i11, R2), so 6 people for 10 min ≈ $0.15–0.25 a run; wolves add < $0.01. **≈ $3–5**; with `fast_lane_on` for the people (+ ≤ $0.25 a run), **≤ $8**. Hold $10 as the ceiling |
| 7 | Optional and the owner's call: the howl-reach arm (150 m); a `carry` skill for the hurt; the starting-instinct question of §4.4 | — | — |

Paid runs need the owner's authorization for that run. Track L's local model, when ready, is an arm of step 6 at no API cost.

## 7. Results, steps 0–5 (2026-11-12, branch `packs`)

All runs are free: instinct graphs or the fake model, on the Spark's trial service (`slop-trials-stdb`, SpacetimeDB 2.14.1).

**Switches.**
- `fast_lane_on` off.
- `fov_on` off (the shipped island).
- `force_outcomes` as shipped.
- The howl as shipped (range 18 m).
- `LIVING_ANIMAL_MINDS=salient,choose` in the fake arm only.
- Every run's `skills.sha256` is the shipped script's.

**Evidence** is under `.local/living/trials/` on the Spark (git-ignored): `pkb2`, `pkb3` and `pkb3b` (baseline), `pkc1` and `pkc2` (calibration), `pkf1` (fake minds). It is summed in `pack-baseline.json`/`.txt`, and each batch's commit is in `<batch>.commit`.

**Host load.**
- Other agents' builds and tests kept the Spark's load at 40–135 on 20 cores through most of these runs.
- From `pkc1` on, the sampler records each world's tick lag. The world clock ran a median of about 30 ms behind wall time, read latency included. The longest gap between ticks per run was 0.2–1.7 s.
- The arena worlds themselves are light: the server process sat at about one core.
- Timing measures (M1's arrival spread, rear blows) carry this caveat. Positions and counts do not.

### Step 0: the harness

- **Built.**
  - `trials.py`:
    - `record.bodies`: every role member at 5 Hz, five reads in parallel; 3.5–4.8 Hz reached. It also records tick lag.
    - per-member `spread` start offsets and per-member `graphs`;
    - the `farthest_town` anchor;
    - `end.side_down`;
    - `minds.roles`, so both sides of an arena can think.
  - `living/tools/pack_arena.py`, with its self-test reproducing §5.4's nulls: coverage 90.4°, 140.0° and 172.8° for 2, 3 and 4 random bearings.
  - `living/tools/pack_arena_trials.py`, which writes the trial files.
- **Found and fixed.**
  - **A trial's bold flag never took effect** (§5.6).
  - **Wolves could not use any movement intent.** Setting a graph with `circle` was refused: "a wolf cannot circle". The wolf's species skills now include the four general intents `keep_distance`, `close_in`, `circle` and `back_off` (`living/seeds/species.json`). Before this, no wolf, graph or mind could hold a distance, circle or step back: Muro's two rules could not be written for a wolf at all. This is data, not code. It adds nothing a person lacks; people have had the intents since `move-intents`.
  - **Spare animals sent to a map corner stayed put** (the corner is sea: "no free walkable tile"), so they stood beside the arena. A first baseline (`pkb1`) was discarded for this. They now go to the settlement farthest from the arena, about 1.86 km away.

### Step 1: the baseline (54 runs)

Instinct against instinct, 6 replicates per arm, 10 minutes. Medians, with the replicate range in brackets.

| Arm | Engagements | Coverage ° | Encircled | Rear blows | I | Focus × chance | ΔG | People killed | Wolves killed | Fight s |
|---|---|---|---|---|---|---|---|---|---|---|
| close 3v3 | 15 | 7.5 (1–19) | 0 | 0.86 | 1.08 (0.93–1.14) | 1.0 | −0.22 | 0 (0–1) | 0 | 80 (30–133) |
| close 6v3 | 17 | 16 (7.5–34) | 0 | 0.93 | 0.96 | 1.5 | −0.45 | 0 (0–1) | 0 | 96 |
| close 3v6 | 26 | 12 (6.8–13) | 0 | 1.0 | 1.10 | 1.0 | −0.56 | 0 (0–2) | 0 | 214 |
| close 6v6 | 31 | 20 (14–23) | 0 (0–0.01) | 1.0 | 0.96 (0.66–1.05) | 1.2 | −0.58 | 1 (0–3) | 0 (0–1) | 187 |
| spread 3v3 | 20 | 6.4 (2.5–10) | 0 | 1.0 | 1.14 | 1.0 | −0.22 | 1 (0–1) | 0 | 108 |
| spread 6v3 | 10 | 5.9 (one run) | – | 0 | 1.0 | 1.0 | −0.22 | 0 | 0 | 58 |
| spread 3v6 | 22 | 5.1 (one run) | – | 1.0 | 1.2 (1.1–1.6) | 1.0 | −0.17 | 0.5 (0–2) | 0 | 130 |
| spread 6v6 | 31 | 110 (110–160, 1–2 runs) | – | 1.0 | 1.2 (1.0–1.6) | 1.1 | −0.42 | 0.5 (0–2) | 0 | 160 |
| spread 6v6, night | 25 | 11 (3.9–140) | 0 | 0.88 | 1.3 (1.1–1.6) | 1.0 | −0.14 | 0 (0–2) | 0 | 88 |

**Against §5.5's predictions.**
- **Coverage.** It was predicted at 40–90° from crowding; it is lower. Instinct wolves follow a fleeing person single file and bite from behind (rear blows 86–100%), well below the 90° and 140° random nulls. Spread 6v6's 110° comes from 1–2 runs whose engagements began with the wolves still in their 120° start sector. It is not a ring.
- **I ≈ 1:** as predicted, the nearest person is bitten.
- **ΔG < 0:** as predicted, people scatter.
- **"Spread coordinated ≤ 20%": wrong for 3v3 and 6v3** (1.0), where the second arrival is 2.1–2.5 s after the first. A wolf charging at 5.1 m/s covers 10 m in 2 s, so the start distances alone put a second wolf inside the 3 s window. M1's absolute 50% target therefore does not separate coordination from these instincts. Only the decision rule against this control can.
- **Fights are short and few people die.** The people outrun the bold instinct's 10 m attack range (`attack the nearest person within 10 m`) within one to three minutes. No wolf was killed: instinct people never strike back.

### Step 2: calibration

- **`pkc1`: the first fixtures walked.** Their intents lacked `run: true`, so the wolves went at 3.4 m/s after people fleeing at a run: a flaw in the fixtures, not in the world. In 20 runs:
  - C1 (sides) reached 64–68° median coverage (range 23–80°), against the baseline's 6–20°, and was encircled 0–3% of the time;
  - C2 bit almost never (0–1 blows a run): the wolves kept 3–5 m from people who kept fleeing at 5 m.
  - Kept as evidence of walking fixtures, nothing more.
- **`pkc2` and `pkc3`: the fixtures at a run, and a standing-prey arm** (people on `{"wait": 900}`: they hold their ground and do not strike). 6 replicates each, against the close 6v6 instinct control (coverage 20°, encircled 0):

| Fixture | Prey | Coverage ° | Encircled (k ≥ 3) | Differs from control (§5.5 rule) |
|---|---|---|---|---|
| C1r: sides assigned by us | fleeing, 3v3 / 6v6 | 94 (61–99) / 101 (34–116) | 0.13 / 0.15 | coverage and encircled, yes |
| C1r | standing, 6v6 | **176 (125–192)**; 2 of 6 runs > 180 | **0.52** | yes |
| C2r: Muro in today's grammar (back off when a mate is within 3 m) | fleeing, 3v3 / 6v6 | 44 / 29 (26–49) | 0.11 / 0 | coverage only |
| C2r | standing, 6v6 | 94 (77–166) | 0 (one run 0.32) | coverage only |
| **C3: Muro with `apart` (A5)** | fleeing, 3v3 / 6v6 | 66 / 59 (50–75) | 0 / 0.01 | coverage only |
| **C3** | standing, 6v6 | **146 (50–210)**; 3 of 6 runs ≥ 178 | **0.76** | yes |

**Reading (§5.6).**
- **Assigned sides.** C1r nearly reaches the 180° target, but only around a target that stands: the world's steering and bite let wolves on different sides ring a person.
- **Today's grammar.** C2r does not ring even a standing target: without a way to steer relative to its mates, a wolf can only back off. The gap is in steering, not in the physics. That is the measurement that justified A5.
- **With A5.** C3's wolves follow only their own two rules, with nobody assigned a side. They ring a standing person as often as wolves with assigned sides do (encircled 0.76 against 0.52), though the median coverage, 146°, stays under 180°.
- **Fleeing people.** No fixture rings instinct people, who flee any wolf within 5 m, within 10 minutes. The best is C1r's 100°.

### Step 3: A5 built (`apart`); A1–A4 not built

The measurement above shows the need for A5, and only A5. Nothing in steps 1–2 shows a need for A1–A4:
- **A1, heard signals.** Instinct wolves never call. Minds already receive signals as percepts.
- **A2, target filters.** No mind has yet asked for "the one alone" or "the hurt one".
- **A3, facing.** Rear blows are already 86–100%, because instinct people flee.
- **A4, counting round a target.** `apart` covers the same ground.

Each waits for a paid arm, or for a mind's plan that cannot be written without it.

- **What it is.** `apart` (metres, 1 to 12) on `keep_distance`, `close_in` and `circle`: how far to keep from others of one's own kind one sees while holding the intent. The same rule serves wolves and people. It says how far, never where: no side, slot or role.
- **Data.** One column appended to the private `steer` row: `apart` f32, `#[default(0.0)]`, an automatic migration. This is the case `schema-guard` (main `ce5e09b9`, merged before the push) covers. No other table, and no view or subscription.
- **Steering.** Each update of an intent that has it gathers the bodies within `apart` (the per-tick chunk cache) and keeps those of its own kind it sees by the one sight rule. The goal's target is left out. Each is pushed away from by how far inside `apart` it is (`steer::apart_push`). Moving, the way bends (`steer::apart_way`). Standing in its band, the body moves round the target, never in or out.
- **Grammar.** `Spacing::apart` and `Action::apart`, checked ("`apart` is for keep_distance, close_in, circle"; "from 1 to 12"). The specs in `skills.rhai` document it, so the minds' reference does too.
- **Bindings.** Regenerated. They also gained `heard_asleep`, which `fix-sleep-talk` had not regenerated on main.
- **Cost.** Not measured at the gate. Per steering update of an intent with `apart`: one chunk gather within at most 12 m, and a sight test per same-kind body in it (at most a pack, in practice).
- **Verified:**
  - `living-check` passes;
  - Cargo `steer::apart_tests` (4) passes;
  - verify-core `apart`, `core-apart2-175631`: 12/12 (people 28° → 191° at 4 m → 213° at 6 m; wolves 28° → 170° → 254°; each within its band). `intents` passes 24/24 as the regression check;
  - verify-client `client-packs-181156`: 43/43, and `steer`, new column included, still refused to clients;
  - verify-minds `intents`, `minds-packs3-181702`: the reference documents `apart`;
  - not run: verify-player (no player reducer changed) and the 216-character gate.

### The spacing reflex, as a candidate (`pkr1`, 24 runs; decision 1)

This is `instinct:wolf_bold` with one weighted desire beside each hunt (`pack_arena_trials.py` `with_reflex`): "keep apart from mates" (weight 1.2), which acts while a mate is within 3 m and the prey within 6 m, holding 3–5 m from the nearest prey at a run with `apart: 4`. Otherwise the hunt (weight 1) acts as before. It names a kind, as the instinct already does, never a creature or a role. It lives in the wolf's own graph, which its mind may rewrite. It is in the trial files only.

| Arm | Coverage ° (instinct → with the reflex) | Encircled | People killed (median) | People's health lost |
|---|---|---|---|---|
| close 3v3, fleeing people | 7.5 → 36 (34–40) | 0 → 0 | 0 → 0 | 11.5 → 0 |
| close 6v6, fleeing people | 20 → 40 (34–105) | 0 → 0 (0–0.20) | 1 → 0 | 123 → 14 |
| spread 6v6, fleeing people | 114* → 37 (35–147) | – | 0.5 → 0 | 89 → 7 |
| close 6v6, standing people (against C3) | 146 → **201 (162–239)**; 5 of 6 ≥ 186 | 0.76 → **0.68** (0.49–0.84) | 0 → **6 of 6, in about 67 s** | 8 → 557 |

\*The spread baseline's 114° is from the 3 runs whose engagements began with the wolves still in their start sector.

**Reading.**
- **Standing prey.** Wolves living only by their starting instinct plus this reflex ring a target that holds its ground: median coverage 201°, the first arm to reach §5.5's 180°, and the pack kills in about a minute. Rear blows are 57%, about the random null: they come from all round, not from behind a fleeing back.
- **Fleeing prey.** The wolves hold back at 3–5 m whenever crowded, so they bite and kill less: health lost 123 → 14 at 6v6.
- **It meets decision 1's condition.** Without it nothing rings. But it is not shipped. It changes how dangerous wolves are, which is the owner's call. And deer flee too: on the island, under instincts, wolves have starved before (`la2`), and the reflex could slow their hunts. A free ecology check (as `stamina-1`'s: wolves and deer over two game days, with and without the reflex) should come before it goes into `instincts.json`.

### The reflex's ecology check (island, 2026-11-12)

The island as shipped (277 people, 24 deer, 9 wolves: the bold pack of 4 and the ordinary pack of 5), 48 game hours from 07:00, 3 worlds per arm, no minds. Driver `living/tools/pack_ecology.py` on `packs-2` (`7810dd1b`); sampled every 2 s by `living/tools/wolf_ecology.py`.
- **On.** Every grown wolf alive at the start got its own instinct with the reflex beside each hunt: `wolf_bold` with the reflex for the 4 bold, `wolf` with the reflex for the 5 ordinary. Wolves born or grown up during the run lived by the shipped instincts.
- **Off.** Nothing changed.
- **Evidence.** `.local/living/pack-ecology/` (Spark, git-ignored): `report-off.json` and `report-on.json`. The worlds were deleted after pausing.

| Arm | Deer killed per run | Deer killed per 100 wolf-hours | Hunting attempts on deer | Attacks on people | People killed | Wolves starved (or died) |
|---|---|---|---|---|---|---|
| reflex off | 1, 0, 1 | 0.23 (0–0.23) | 95, 301, 167 | 5, 4, 0 | 0 | 0 (0) |
| reflex on | 1, 2, 4 | 0.47 (0.23–0.93) | 173, 116, 82 | 2, 2, 7 | 0 | 0 (0) |

**Reading.**
- **Hunts are not slowed.** Deer kills rose: 7 against 2 over three runs each. By §5.5's rule this differs: the median of 2 lies outside off's 0–1, as do 2 of the 3 runs. Counts this small are only a direction.
- **No wolf starved or died in either arm.**
- **People.** None were killed in either arm, and attacks on them stayed rare (0–7 in 48 hours among 277 people).
- **The risk that prompted the check did not appear.** The reflex did not slow deer hunts or starve the wolves on the island.
- **Not covered.** Two game days is not a life. The ecology over many days, and the hamlet with a bold pack beside its people, were not run. The shipping decision goes to the coordinator.

### Step 4: the hidden `pack` copying, retired

Done (§5.7, decision 4). The mind ignores `pack` with a warning, and the choose prompt's "# Your pack" section is gone. The `animal-switches` variant and `animal_minds.py` drop it. verify-minds `animals` (`minds-packs-133930`) passes: three deer, three separate `choose` calls, no copied decision.

### Step 5: fake-model arms (`pkf1`, 4 runs)

Both sides with minds (`minds.roles`): 6 people on the default mix and 6 wolves on `salient,choose`, close and spread 6v6.

- **Plumbing.** 0 errors. Every wolf decision was its own `choose` (5–10 a run), and no thought was copied.
- **Calls a 10-minute run**: 139–169. About 150 are the people's (think about 48, compile about 50, talk 9–23, consolidation 35–42). The wolves made 5–10 decisions and 6 consolidations.
- **What a wolf mind can change in 10 minutes: little.** Wolves think at most every 240 s (`think_min_s`) and only on a salient change, so a wolf thinks once or twice in a fight.
- **The `choose` menu cannot express spacing.** It offers flee from, hunt or attack a creature by id; keep close to the nearest of its kind; rest; roam; a call. It offers none of the movement intents. A wolf mind in `choose` mode can never hold a distance, circle or step away from a mate. On the two-call path (an impulse, then a compile against the full grammar) it can.
- **The behaviour measures of fake runs mean nothing** (the replies are fixed), and are not reported.

## 8. The paid step: plan and thresholds (committed before any paid call; not run)

**Gate.** The step waits for battle-scale's fixes 1–3 on main and the owner's go-ahead for this run. The ceiling is $10, as approved.

**Build.**
- `packs` merged with main once the fixes are in.
- The trial module and the mind rebuilt.
- Every run records its commit and its switches.

**Switches.**
- `fast_lane_on` off;
- `fov_on` off;
- `force_outcomes` as shipped;
- the howl as shipped;
- people on the models file's default mix;
- wolves on GLM Flash through the species map, with `LIVING_ANIMAL_MINDS=salient` (the impulse-then-compile path). `choose` is left off because its menu cannot express spacing (§7, step 5);
- no `pack`.

**Arms.** 6v6, spread start, bold wolves, 10 minutes, 4 replicates each, 20 runs:

| Arm | People | Wolves | What it asks |
|---|---|---|---|
| P1 | minds | instinct (shipped) | Do people with minds group and help (M4) where instinct people scatter? |
| P2 | instinct | minds, starting from the shipped instinct | Does any wolf's own mind write spacing (`apart`, `circle`, waiting for mates), and does a ring follow (M1–M3)? |
| P3 | minds | minds | Both sides together: the owner's "bunch of wolves against a bunch of people" |
| P4 | minds | minds | As P3, with the island's deer left in place (the mixed arm) |
| P5 | minds | minds | As P3, the howl as loud as 16.7 voices (150 m; shipped 2, 18 m): decision 2's arm. Measured: howls made, by whom and when; wolves that came toward a howl they heard (within 30 s, closing at least 10 m); M1–M3 against P3 |

**Thresholds** (§5.5's rule: an arm differs from its control when its median lies outside the control's replicate range and at least ⅔ of its replicates do). Controls are the instinct arms already run: `pkb3` spread 6v6. People's arms also compare against P2's instinct people.

- **P1 / P3, people.** Cooperation from people means ΔG > 0 (they close up when the wolves appear), standing-together share above the control's 0–0, and assist rate > 0 (a person strikes a wolf that is on someone else).
- **P2 / P3, wolves.** Cooperation from wolves means median coverage at k ≥ 3 ≥ 180°, encircled share above the control's 0, and selection index I ≥ 1.5, with M1's coordinated share read only against its control (the 3 s window is reached by charging alone, §7).
- **Descriptive, no threshold.** The count of wolf graphs a mind wrote that use `apart`, `circle`, `keep_distance` or a wait on mates (`count` of wolves); calls to `signal`; casualties and fight length.
- **The guards (§5.5).** Every prompt is audited for pack-tactic words outside the character's own experiences and memory. `skills.sha256` is checked against main. Nothing from the arena goes into a seed.

**Cost estimate.**
- **People.** Trials and R2 put people on stage at about $0.14–0.24 a person-hour. Six people for 10 minutes is $0.15–0.25 a run; the fake arm's call counts (about 150 people's calls a run) fit that.
- **Wolves.** On the two-call path, about $0.005 a wolf-hour, so under $0.01 a run.
- **Total.** 16 runs with people's minds plus 4 without (P2): about **$3–5**.
- **Bound.** The batch is stopped if the ledger passes $8.

## 9. The paid step's results (`pkp1`, 2026-11-12)

**Run.**
- 20 runs: P1–P5 × 4, 6v6, spread start, bold wolves, 10 minutes.
- `packs-2` at `14b103aa`.
- Variant `pack-minds`: people on the default mix; wolves on GLM Flash with `LIVING_ANIMAL_MINDS=salient`, the impulse-then-compile path.
- `fast_lane_on` off, `fov_on` off. The howl at loudness 2 (18 m), or 16.7 (150 m) in P5.
- 5 worlds at a time on `slop-trials-stdb` beside other agents' batches.

**Spend: $2.34** (1,921 calls) of the $8 stop, read from the live journals at `trials.PRICES` by `pack_spend.py`. Evidence: `.local/living/trials/pkp1/` and `pack-paid.json`/`.txt` (Spark, git-ignored). The worlds were deleted after pausing.

**Against §8's thresholds.** The control is `pkb3` spread 6v6, instinct.

| Arm | Coverage ° | Encircled | I | ΔG | Standing together | Assists | People killed | Wolves killed | People's blows on wolves |
|---|---|---|---|---|---|---|---|---|---|
| control (instinct) | 114* | – | 1.15 | −0.42 | 0 | – | 0.5 (0–2) | 0 | 0 |
| P1 people think | 7 | – | 1.15 | −0.61 | 0 (0–0.04) | 0 | 0 | 0 | 2–9 |
| P2 wolves think | 12 | 0.04 (1 run) | 1.13 | −0.56 | 0 | – | 0 | 0 | 0 |
| P3 both | 18 (15–100) | 0.5 (1 run) | 1.11 | −0.56 | 0 (0–0.05) | 0 | 0 | 0 | 4–17 |
| P4 both, with deer | 116 (71–161, 2 runs) | – | 0.99 | −0.22 | **0.09** (0–0.25) | 0 | 0 | 0 (0–1) | 5–36 |
| P5 both, howl 150 m | 44 (25–58) | 0.03 | 0.81 | −0.28 | **0.12** (0–0.65) | 0 | 0 (0–1) | 0 | 2–20 |

\*The control's coverage is from the 3 runs whose fights began in the wolves' start sector (§7).

**Reading, by the committed thresholds.**
- **People (P1, P3).**
  - They do not close up when the wolves appear (ΔG stays negative in every arm).
  - No person ever struck a wolf that was on someone else (assist rate 0 in all 16 runs with people's minds).
  - Standing together rose above the control's 0 only in P4 and P5. That is 2 of the 3 people-side thresholds unmet: **no cooperation from people by §8's rule.**
  - What minds did change: they fight back. They landed 2–36 blows a run, where instinct people landed none, and the wolves lost 8–95 health.
- **Wolves (P2, P3).**
  - Coverage stayed far under 180° (12–18° median), encircled stayed about 0 apart from single runs, and I is about 1.1: **no cooperation from wolves.**
  - Their plans (17–20 per arm, about 4–5 per run, since a wolf thinks at most every 240 s) were mostly attack, flee and a call.
  - Some plans used the new means: `circle` in 2–3 plans per arm, `count` in 2–3, `apart` once (P4), `keep_distance` 1–2.
  - Some named mates: "press in with teeth while Frost and Ember close in", "move toward Rook and the pack".
  - None of these ran long enough, at the thinking pace wolves have, to show in the measures.
- **The howl (P5, decision 2): unanswered.** In P5's 4 runs no wolf howled. Their minds chose growls and yips (13 growls heard by wolves, 4 yips). P3, on the shipped 18 m howl, had 8 howls heard by wolves and 15 by people. So the 150 m arm measured nothing about the howl's reach. **The shipped value stays at loudness 2.** A howl-reach measure needs wolves that howl: a fixture that howls on a timer, against minds and graphs that can answer it.
- **Casualties.** Fewer than under instincts: no person died in 16 of the 20 runs, and one wolf died (P4). Wolves with minds attack less doggedly than the bold instinct: P2's people lost 0–15 health against the control's 0–190.
- **Guards.**
  - No pack-tactic word appeared in any system prompt. The only phrase hit was "from behind", in the `block` skill's spec ("blows from the front do a quarter of their damage; from behind it does not help"), which is a rule of the body, not a tactic.
  - Every run's `skills.sha256` is the branch's. Nothing went into a seed.
  - User prompts carry the characters' own experiences, which were not audited word by word.

**What this says.**
- **The arena works, and the world now allows a ring.** The spacing reflex, an instinct-level desire, rings prey that stands. The minds, in ten minutes and at a wolf's thinking pace, do not get there.
- **The open questions are pace and learning, not perception.**
  - A wolf mind thinks every 240 s.
  - It has no memory of earlier hunts in a fresh arena.
  - Whether a pack that keeps hunting together over days, with the reflex in its starting instinct, learns to wait, circle and come in together is the next question. It needs longer life runs, not more arenas.
- **People.** Whether minds learn to stand together needs the same: days with wolves near, not ten minutes.

## 10. Shipped, and what is next (2026-11-12)

- **The spacing reflex is shipped, on by default (branch `pack-reflex-on`).** It is the world law `pack_reflex` (`true`).
  - **What it does.** While it is on, every hunt in a wolf's starting graph sits beside the desire "keep apart from mates" (`graph::with_pack_reflex`). A hunt is an attack on the nearest person or deer, guarded or bare.
  - **The three install paths:**
    - a seed pack's named instinct (`wolf_bold`);
    - a spawned or born wolf's species instinct (`wolf`), once past infancy;
    - a grown animal's species ways (repertoire.json): the wolf's `hunt` routine.
  - **Not given to** a newborn's `wolf_young`.
  - **When it is read.** Only at those installs: world creation and birth. It reaches every world with wolves, bold packs included. A wolf's mind may rewrite it like any instinct.
  - **To turn it off.** `"rules": {"pack_reflex": false}` in a seed (the seed's own law values). Wolves already placed keep the graph they were given.
  - **The shipped reflex is broader than the arena's.** The arena and first ecology runs (`pkr1`, `eco-reflex-*`) built the reflex in Python (`pack_arena_trials.with_reflex`) and gave it only to guarded hunts in `instincts.json` graphs. The shipped one also covers bare hunts (the ordinary wolf's deer hunt) and the repertoire's `hunt` routine, which grown founding wolves actually live by.
  - **The first ecology check was confounded.** Its "on" arm replaced the ordinary wolves' repertoire ways with `instincts.json` graphs. So the shipped path was checked again: law on (`island`) against off (the island with `rules` off), 3 worlds each, 48 game hours, on `slop-packs-stdb`.
    - Deer killed: on 1, 2, 3 (0.47 per 100 wolf-hours, range 0.23–0.70); off 1, 1, 2 (0.23, range 0.23–0.47).
    - No wolf died or starved in either arm, and no person was killed.
    - Attacks on people: on 2–3, off 2–5.
    - By §5.5's rule nothing differs: on's median, 2, lies within off's range, 1–2. The first check's 7 against 2 is kept in §7 as history.
- **Track P's paid work is parked.** Whether minds cooperate is not a 10-minute question: a wolf thinks about every 240 s, and neither side remembers earlier encounters in a fresh arena. The cooperation question folds into a multi-day life run with wolves beside people, when one exists. Measure it there with this note's M1–M4, from the same `record.bodies` samples, over days rather than minutes.

## Sources

- MacNulty, Mech & Smith (2007), [*J. Mammal.* 88:595–605](https://pubs.usgs.gov/publication/70030114).
- MacNulty et al. (2012), [*Behav. Ecol.* 23:75–82](https://pubs.usgs.gov/publication/70037814).
- MacNulty et al. (2014), [*PLoS ONE* 9:e112884](https://doi.org/10.1371/journal.pone.0112884).
- Mech, Smith & MacNulty (2015), [*Wolves on the Hunt*](https://pubs.usgs.gov/publication/70148344).
- Mech (1999), *Can. J. Zool.* 77:1196–1203.
- Mech (1966), *The Wolves of Isle Royale*.
- Harrington & Mech (1979), [*Behaviour* 68:207–249](https://pubs.usgs.gov/publication/5221155).
- Muro et al. (2011), [*Behav. Processes* 88:192–197](https://doi.org/10.1016/j.beproc.2011.09.006).
- Escobedo et al. (2014), *J. R. Soc. Interface* 11:20140204.
- Janosov et al. (2017), [*New J. Phys.* 19:053003](https://arxiv.org/abs/1701.00284).
- Reynolds (1987), *Computer Graphics* 21(4):25–34.
- Couzin et al. (2002), *J. Theor. Biol.* 218:1–11.
- Hamilton (1971), *J. Theor. Biol.* 31:295–311.
- Leibo et al. (2017), [arXiv:1702.03037](https://arxiv.org/abs/1702.03037).
- Lowe et al. (2017), *NeurIPS* (MADDPG).
- Baker et al. (2020), [*ICLR*](https://arxiv.org/abs/1909.07528).
- Jaderberg et al. (2019), *Science* 364:859–865.
- Mark (2009), *Behavioral Mathematics for Game AI*.
- Isla (2005), GDC.
- Orkin (2006), GDC.
- Colledanchise & Ögren (2018), *Behavior Trees in Robotics and AI*.

Citations without a link were not re-checked online this turn.
