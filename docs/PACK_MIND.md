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
- **A harness bug, fixed.** The trial runner wrote a background as `"bold": true`, and the authority reads `"bold":true` from the text (`act.rs`). So no trial before this one ever had a bold pack: the island pack trial `pack-mind` included. Its wolves were seeded bold, and their seed backgrounds were intact. `trials.py` now writes backgrounds compact. The authority's text match is fragile, but it is left as it is (a rules change, not needed here).
- **Sampling.** `record.bodies` reads five tables per sample, concurrently (2.14.1's SQL endpoint takes one statement a request). The rate actually reached is reported per run.
- **The calibration fixtures (step 2).** Both live in their trial files only.
  - **C1, "sides".** Each wolf circles the nearest person at 4 m on an assigned side, alternating left and right, and bites, with chance 0.3 a check, when within 3.5 m. The sides are assigned by us, so this shows only whether steering and the bite let wolves on different sides form a ring.
  - **C2, "Muro with today's grammar".** No sides are assigned. Each wolf, in order: flees when badly hurt; if another wolf is within 3 m and a person within 6 m, backs off 4 m from that wolf; if a person is within 3.5 m, attacks with chance 0.3 a check; otherwise keeps 3–5 m from the nearest person.
  - **Reading.** If C2 reaches M2's 180° at k ≥ 3, a keep-apart reflex is expressible today, and under the owner's rule below it may go in the starting instinct. If only C1 reaches it, the gap is in what a wolf can perceive or steer by (A4, A5). If neither does, the physics blocks encirclement.

### 5.7 Decisions (owner, 2026-11-12)

1. **The spacing reflex** is allowed in the wolves' starting instinct, but only if calibration (step 2) shows it is needed. It takes the form of a weighted desire ("keep apart from mates") in the starting graph. The wolf's own mind must be able to revise it, and it names no target and no role. The rule it was made under: the starting instinct holds individual drives, as it already holds "attack the nearest deer". It never holds a group plan.
2. **The howl's reach** becomes the howl's loudness in its sound spec, under the same loudness rule that wakes sleepers (`fix-sleep-talk`). The 150 m arm measures the difference. The result goes to the owner before the shipped value changes.
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
