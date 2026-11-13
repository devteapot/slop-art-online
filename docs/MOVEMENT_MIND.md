# Movement mind: finding the way from what one knows

Status: **design, being built step by step** (designed on branch `research-movement`, from main `e09365be`, 2026-11-12). Built so far:
- `flee-open` (main `33b50ced`): a flight takes open ground ([LIVING_CORE](LIVING_CORE.md#steering-locomotion)).
- `pursue-last-seen` (main `3e58c025`): nothing is followed out of sight; a pursuit goes to the last-seen place, a flight runs from it; `chase_lost_share` removed.
- `known-ground` (step 3; this branch): every character records the ground it sees (`known_ground`, `remembered`, `ground_edit`; `ground_sight_m` 24 m by day), and with the `nav_belief` law (off by default until the arenas pass) walks are planned over it; a mind's scene lists its remembered places with bearings ([LIVING_CORE](LIVING_CORE.md#steering-locomotion)). Built as the step-3 design note approved on 2026-11-13: three new private tables, no column added to an existing table (appending one rewrites the table and disconnects every client in 2.14.1); remembered gates in their own table rather than on `familiar`.

Next: `nav-arenas` (§4; how the arenas are built, committed before any run, in §4.1). The rest of this paragraph is the design as written. Nothing else is built. No module was built and no model was called. The evidence below comes from reading the code on main and from scanning existing trial evidence under `~/dev/*/.local/living/trials/`. The target spread in [§4](#4-measures-the-navigation-arenas) is committed here before any arena runs.

The owner's ask: *"general movement, how they get where they want to go. pathfinding based on memory and what they can see. real time input like a real player, low latency."*

Standing rules this design follows: behaviour emerges and is not hard-coded; minds and players get the same rules and physical limits; minds know only what they perceived or remember; architecture changes only where they are general and a measurement shows them necessary; arenas measure, and never train or install behaviour.

## Summary

- **Today, the way is found from the true map, so walks rarely fail for physical reasons.** The walks fail on knowledge: what the mind names and what it can see.
  - In the 391 trial runs since 2026-11-11, **9,160 of 10,718 `goto` acts arrived (85.5%)**.
  - 881 failed because the target was not perceived now. Of those, 770 named a creature by id that was out of sight, and 111 asked for the nearest of a kind with none in sight.
  - 424 named a place the character had never stored. About 70% of those names are a kind of thing it has seen, such as a hall, an inn, a gate or a campfire.
  - Only **9** failed on the ground: 6 "destination unreachable" and 3 "no path there".
  - Bodies with a `goto` under way stood still away from their target for **0.26%** of the sampled walking time.
  - Flights fail differently. **22 of the 22 told flight failures are "cornered"**, because a flight runs straight away from the threat without looking for open ground.
- **The pathfinder reads ground the character has never seen.** Every route is planned on `common::map(ctx)`: every tile of the floor, every gate's current state, every built wall, and connectivity labels for the whole island. A newcomer's first walk to a town 2 km away takes the near-optimal route through land it has never seen (PATHS: 1.00–1.06 of the best tile path).
- **Proposed map: remembered ground.**
  - Each character keeps a private record of the ground it has seen: a 4 m cell mask per chunk, grouped by 128 m block and stamped with the map's edit epoch.
  - It also keeps the last-seen state of gates, its landmarks, and the last-seen places of creatures, all on the existing `familiar` rows.
  - Places it has been told are stored as told, never as seen.
  - Typical cost: about 6 KB per character, about 13 MB at 2,000 characters.
- **Proposed planner.**
  - The existing leg-by-leg planner runs over a belief view of the map. Seen tiles are as they were seen. Unseen tiles are assumed open, at a cost multiplier (the free-space assumption).
  - When a seen cell contradicts the current leg, the leg is planned again. LPA* or D* Lite is adopted only if those re-plans prove costly.
  - The same planner serves a player's click-to-move and a mind's `goto`.
- **Proposed real-time layer: the "hands".** This is the authority's existing steering, extended rather than replaced. It is deterministic and lives in `living_rules`.
  - It reacts to events from what the body perceives, with no added polling cadence. It produces the same input a player's keys produce, under the same limits.
  - A learned controller, a small model or the fast lane cannot meet the latency or the rules (comparison in [§3](#3-real-time-input-like-a-player)).
  - External inference stays in the mind service and above the hands.
- **Measures.** Four scripted arenas: an unfamiliar town, a blocked route, a moving crowd, and chase and flight. Each reports:
  - arrival rate;
  - time against the optimal on the character's own known map, and against the true map;
  - stuck events;
  - input latency.
- **Cost to test.** The arenas, the fake-model arms and every build step are free. A paid arm on real minds is only needed to ask whether minds use their known and told places. It would cost about **$5** ($8 ceiling), at the measured $0.15–0.17 per resident-hour.

## Built: pursue-last-seen, wolves before and after (2026-11-12)

**Builds.** Before: `flee-open` (`993b757d`). After: this branch on main `33b50ced`. Main's rule changes between the two are speech, earshot and owner labels, nothing that instinct-only wolves read. Trial server (2.14.1), instinct graphs only, no mind service, no model. Host load 25–55 on 20 cores from all agents.

**Chases** (`scenes.py chase`, default seed, 4 chases of each kind, a bold wolf on a person going off along an open 64 m line):

| | Before | After |
|---|---|---|
| Person running: caught | 4 of 4, median 1.2 s (0.4–2.1) | 4 of 4, median 1.2 s (0.8–1.8) |
| Person running: first blow | median 4.8 s (3.8–5.4) | median 5.1 s (4.0–6.3) |
| Person walking: caught | 3 of 4, median 0.4 s | 4 of 4, median 0.2 s |
| Person walking: first blow | median 1.7 s (1.5–1.9) | median 1.9 s (1.5–2.4) |

In the open the target never leaves sight, so the change does not show here, as expected.

**Fights** (`scenes.py fights`, default seed, 5 of each; median and range of fights that started):

| | Before | After |
|---|---|---|
| Person v person, dodging | 33.8 s (29.9–91.2) | 34.4 s (32.0–44.6) |
| Person v person, trading blows | 56.6 s (17.1–94.8), 2 timed out | 25.0 s (18.0–26.9) |
| Person v bold wolf | 24.1 s (20.6–31.6), 5 fights | 25.8 s (21.1–90.4), 3 fights, 1 timed out |

How fights end shifted with the flights: after, a fight's loser more often got clear ("clear" in 5 of 5 trading fights, against 0 of 5), because a flight now runs on from where the pursuer was last seen instead of ending when it went out of sight. Five fights an arm is a small sample.

**Wolf ecology** (`living/tools/wolf_ecology.py`, the hamlet with 16 deer and a bold pack of 4, the overlay of the fix-pursuit-speed check; instinct graphs, no model). **4 worlds an arm, 24 game hours each**, run together on the trial server on 2026-11-13: before is main `db4c1e35` (the branch's base), after is `pursue-last-seen` `9e2b25a5`. Evidence: `~/slop-evidence/pursue-last-seen/eco2/`.

| | Before | After |
|---|---|---|
| Resident-hours | 847 | 896 |
| Attack episodes (per 1,000 resident-h) | 195 (230), none at night | 182 (203), 11 at night |
| Blows begun | 1,389 | 1,518 |
| People killed of 48 (per world) | **19** (5, 7, 3, 4) | **14** (4, 3, 3, 4) |
| … per 1,000 resident-h | 22.4 | 15.6 |
| Deaths per episode | 0.10 | 0.08 |
| Of the killed: badly hurt / children | 18 / 2 | 14 / 1 |
| Deer attacked / killed | 22 / 0 | 44 / 1 |
| Wolves died (all of age) | 16 | 16 |

With a bold pack beside a village, people die no more often with pursue-last-seen, and probably a little less (14 against 19 of 48); wolves went for deer twice as often. The worlds overlap (3–4 dead in most of each arm), so the fall is not certain. Almost every victim was worn down over several episodes, on both builds. An earlier two-world comparison cut to 13.6 game hours (its before worlds were paused for a quiet window and their clock jumped 22.7 game hours on resuming) pointed the other way, 7 against 4 of 24, and is superseded by this one.

## 1. Today

### 1.1 How a character gets where it wants to go

There are three layers, all on the authority except the mind:

1. **The mind names a target** in a plan. A deliberation compiles to a behaviour graph or a one-off act: `goto` with a target from `living_rules::graph::Target` ([graph.rs](../living/rules/src/graph.rs)). The targets are:
   - `{"place": name}`: one of the character's own `place` rows (point, name). Up to 24 written by its mind, plus the given ones: home, work, the town's centre, the stages of a known way.
   - `{"at": [x, y]}`: any coordinate.
   - `home`, `wander`, `commotion`, `sound`.
   - `{"nearest": kind}`, `{"named": …}`, `{"id": …}`.

   Since 2026-11-09 the creature, resource and structure targets "resolve only when currently in sight" (prompt text in `living/mind/src/prompts.rs`). Places and coordinates always resolve.
2. **The graph runner** (`brain.rs`) evaluates the graph on the tick: about 1 Hz on the character's slot, about 15 Hz while in a fight, and at once on a wake. It starts the leaf through `acts::submit` → `motion::start`.
3. **Steering** ([motion.rs](../living/authority/src/motion.rs), geometry in [steer.rs](../living/rules/src/steer.rs)) carries a goal kept in the private `steer` row. The goal kinds are:

   | Goal kind | What it is |
   |---|---|
   | `GOAL_POINT` | a walk to a place |
   | `GOAL_CREATURE` | an approach, a pursuit, `close_in`, `follow` |
   | `GOAL_DIRECTION` | a player's keys |
   | `GOAL_FLEE` | a flight, `back_off` |
   | `GOAL_BAND` | `keep_distance` |
   | `GOAL_ORBIT` | `circle` |

   A steering update writes one analytic segment (a turn, then straight) to the public `body` row:
   - It turns toward the next path corner at the `turn_rate` law.
   - It bends away from bodies close ahead (`separation` 0.8 m, weight 0.9).
   - It cuts corners it can see past.
   - It sweeps the segment at 0.2 m steps and ends it before a wall, water, rock or a shut gate.

   Steering looks again on events (a corner, the final approach, a chunk crossing, an obstacle ahead) and on a cadence: 2 s alone (`steer_s`), 3 Hz in a crowd, 4 Hz in a chase, 8 Hz in a fight.

**Routes** ([PATHS.md](PATHS.md), `living_rules::nav`, since 2026-11-10) are planned leg by leg on three levels:
- A* over **areas** (blocks of 8 × 8 chunks), for the whole way.
- A* over **regions** (the walkable pockets of a 16 m chunk), for the next 384 m.
- The tile A* with string pulling, for the next 64 m.

A walk keeps its area route in `walk_route` and plans the next leg 16 m before the current leg ends. Measured: a warm leg costs 4.9 M fuel at p50 (18.4 M at most), about 0.2 ms. All 16 cross-island walks from Brackenford arrived, and 38 of 40 short clicks (the other 2 were into the sea).

**Being stuck** has a fixed answer. A segment blocked at speed 0 plans once more (`FLAG_STUCK`). If the walker is still blocked, the walk ends "the way is blocked". A walk that gets no nearer for 10 legs ends "you were getting no nearer". A flight or a band backing off that is blocked ends "cornered". An orbit ends "the way round is blocked".

**Last-seen places** exist only inside steering. A goal held by perception (`FLAG_SIGHT`: `follow`, `close_in`, `keep_distance`, `circle`, `back_off` from a creature) keeps where the target was last seen in `steer.gx/gy`. Out of sight, the body goes there. After `lost_after_s` (2 s) the goal ends "lost sight of them". Nothing keeps that place afterwards: a later `goto` to "where #28 was last seen" fails ("no #28's last position in sight").

**`familiar`** ([tables.rs](../living/authority/src/tables.rs), `brain.rs::familiarity`) is bodily recognition: one row per (character, thing) for a region (a chunk), a creature, a structure or an artifact, holding the first and last time and a count. It holds at most 256 rows a character, least recent forgotten. It decides novelty ("You come to a place new to you, around (410, 258)"). It holds **no position and no shape of the ground**: it is not a map. BATTLE_SCALE (origin/battle-diagnosis) shows the 256 cap thrashing in a crowd and proposes age-based eviction with a 2,048-row cap. This design builds on that fix and does not compete with it.

**The 3.3 intents** ([COMBAT_MIND §3.3](COMBAT_MIND.md#33-movement-as-intent-the-body-carries-out-steering-rules), built 2026-11-12) are `keep_distance`, `close_in`, `circle`, `back_off` and `follow`. They are general steering goals held by sight, at the body's own walk or run. They plan around walls only when closing in (`toward()`: a straight aim at where the target will be when the line is clear, else a leg, re-planned at most once a second). Backing off and circling never plan: they fail "cornered" or "the way round is blocked". In r2d they were written into 15 routine installs, ran twice, were done once deliberately, and were twice refused "cornered" ([TRIALS.md](TRIALS.md#r2-again-with-what-a-character-is-told-fixed-r2d-10-fights-030)). `screen` (put cover between oneself and a threat) is designed but not built.

**Players** steer through the same rules:
- `human_move(dx, dy, run)` sets a direction goal, rate-limited by `input_hz` 30/s with a burst of 15.
- Click-to-move is a `human_act` `goto`, through the same planner.
- A movement input is drawn about 13 ms (p50) after it is sent ([LATENCY.md](LATENCY.md)).
- The game client draws terrain out to a 110 m radius (`living/game/src/world.rs`), because terrain is public static data ([PERCEPTION.md, Open](PERCEPTION.md#open)). The character's sight is 11 m by day and 6 m at night.

### 1.2 What the pathfinder reads

Exactly this, all from the authority's cached hosted map `common::map(ctx)` and derived from the world as it is now:

| Read | Where | Known to the character? |
|---|---|---|
| Every tile of the floor (terrain class: walkable, `Wall`, `Low`, `Drop`, water, rock, road share) | `Map::path`, `Map::free`, `line_clear`, `geo::sweep` | Only within its sight, now or before. The rest **is not known, and is read anyway.** |
| Every gate's current open or shut state (`Map::set_blocked`) | regions, areas, tile A*, sweep | Only gates in sight. A gate shut across town **reroutes a walker who never saw it**. |
| Walls built since genesis (`Map::set`) | the same | Only if seen. |
| Region and area connectivity, and connected-component labels for the whole island | `nav.rs`, `Map::reachable`, `Map::nearest_reachable` | No. A click on another shore is refused "no path there" at once: the character instantly "knows" no way exists. |
| `wander`'s "random reachable spot nearby" | `brain.rs` | Reachability is true connectivity, not belief. |
| A pursuit's target position (`GOAL_CREATURE` without `FLAG_SIGHT`: `goto` a creature, an approach to act) | `steer_update` | **By distance only:** within sight × `chase_lost_share`, or scent. No sight line, so a target behind a house is pursued at its true position. |
| A flight's threat position (`GOAL_FLEE` without `FLAG_SIGHT`: `flee`) | `steer_update` | The threat's true body position at every update, seen or not. |
| Bodies within 0.8 m (`separate`, `creatures_near`) | steering | Touching range. Acceptable as a bodily sense. |

So the planner is **omniscient about ground, gates and connectivity**. Pursuits and flights started from a graph are omniscient about where their creature is. Only the 3.3 intents use the sight rule.

### 1.3 Where it fails: the evidence

I scanned 723 runs' `experiences.jsonl` (not the per-character `journal/` copies) and 741 `samples.jsonl` under `~/dev/*/.local/living/trials/`. The runs come from 13 checkouts, dated 2026-11-09 to 2026-11-12. Scripts: [the scanners](#a-the-evidence-scanners). `uses.jsonl` holds skill uses (combat), not walks; `actions.log` holds the trial driver's calls. Neither carries movement outcomes beyond what the experiences already have.

**`goto` acts**, told to the character as "You did what you had decided" or "What you had decided did not work out" (one-off acts and plan steps a mind issued):

| Outcome | Runs from 2026-11-11 (391 runs) | Runs before 2026-11-11 (332 runs) |
|---|---:|---:|
| Arrived | **9,160** (85.5%) | 3,343 (62.5%) |
| Target not perceived now: a creature by id out of sight | 770 | 1,187 (both kinds) |
| Target not perceived now: no `nearest` of that kind in sight (tree 38, fishing spot 21, forest 16, berry bush 7, campfire 7, house 6…) | 111 | (above) |
| A place name it never stored ("hall", "brackenford_hall", "hall near the gate", "campfire by the hall"…) | 424 | 193 |
| A name the grammar could not parse as a target | 30 | 40 |
| Interrupted (broke off to flee or fight; a person took over) | 209 | 24 |
| **Destination unreachable** | **6** | **541** |
| **No path there** | **3** | **17** |
| Other | 5 | 1 |

- **The ground failures were fixed on 2026-11-10.** 541 "destination unreachable" outcomes (in 118 runs) and 17 "no path there" fell to 6 and 3 after `path-1` and connected ground ([PATHS.md](PATHS.md)). Most were places a mind wrote at a house's coordinates (for example "Alwin Wren's house by the chapel wall", or "home ground: house 115, storages 579/580").
- **The failures left are about knowledge and naming.** 881 + 424 + 30 = 1,335 of 10,718 acts (12.5%). The commonest is pursuing someone who has gone out of sight, with no remembered last-seen place to go to. The next is going to a thing the mind knows by kind ("the hall") but never stored as a place. Of the 426 such place names, 299 contain a word for a kind of thing (hall, inn, gate, campfire, square, market, house, camp, sign, road, river…).

**Plan steps** (graph leaves) are told only when they fail, and the same failure is not told again within two minutes, so these are lower bounds. Movement failures among the "own" lines: **flee 22, all "cornered"** (10 from a wolf, 9 with no target named, 1 each from a person, a campfire and #74), back_off 2 "cornered", gather 7 "the way is blocked" (walking to a bush), wander 5 "no path there". The 24 "cornered" lines come from 10 runs: wolves batches b1, b4, b6, w6 and w7, and arenas r2b and r2d. A mind recalled one: *"running got me cornered last time, so I stand and put an arrow in it"* ([COMBAT_MIND §2](COMBAT_MIND.md)).

**Stuck bodies.** In the subjects' 2 s samples, consecutive samples with the same movement activity were counted as stuck when the body moved less than 0.15 m and stood more than 2.5 m from the activity's target point.

| Activity | Sampled time | Stuck | Episodes | ≥ 10 s |
|---|---:|---:|---:|---:|
| `goto` | 108,048 s (30 h) | 276 s (**0.26%**) | 26 | 20 |
| `wander` | 170,389 s | 456 s (0.27%) | 13 | 6 |
| `flee` | 690 s | 0 | 0 | 0 |

The longest `goto` episodes are 20–25 s:
- `i11/iter11-life-iter11-r2`: `goto → (390,245)`, standing at (404.9, 239.2).
- `l8/life-pressure-default-r2`: `goto → house`, 5 m short of the house.

That is about 0.14 stuck episodes per 10 minutes of walking.

**By obstacle:**

| Obstacle | Today | Evidence |
|---|---|---|
| **Getting stuck** | Rare, because the planner knows the true map and re-plans once when blocked. | 0.26% of walking time; 26 episodes in 30 h. |
| **Long detours** | Routes are near-optimal on the true map, so there are no detours. Unrealistic for a stranger: no one explores. | PATHS route quality 1.001–1.060 of the best tile path; walks 0.52–1.00 of the road's length (cross-country through land never seen). |
| **Unknown ground** | Treated as known. | §1.2. |
| **Crowds** | Separation bends the heading; the crowd cadence is 3 Hz. No reciprocal avoidance, and nothing reacts at once when a body steps into the way. | No stuck episodes attributable to crowds were found, but no trial measures crowd crossing. LIVING_CORE: 0.26 abrupt (> 60°) turns per moving body per minute at about 260 characters. |
| **Doors and gates** | A gate counts as blocked when shut, for everyone, seen or not. Houses are solid (`Wall` bands): there are no doors into them. | §1.2; PATHS ("houses are `Wall` tiles in 3-tile bands up to about 90 m long"). |
| **Walls and building rows** | Planned around. Before path-1 this was the main cause of refusals (255 of 319 short clicks). | PATHS. |
| **Stairs and drops** | A drop blocks like a wall; stairs and ramps are walkable and join the levels. The planner finds the stairs through true connectivity. A jump is a dash at 9 m/s and does not cross a drop or a `Low` tile: the authority has no height. | PERCEPTION, "Drops". |
| **Flight** | Straight away from the threat, sliding along walls, then "cornered". | 22 of 22 told flight failures. |

## 2. Navigation from the character's own knowledge

### 2.1 Survey

**How people and animals hold space.**
- Tolman's rats took novel shortcuts toward a goal, which he read as a "cognitive map" rather than a learned chain of turns ([Tolman 1948](https://doi.org/10.1037/h0061626)).
- Place cells gave that map a neural basis ([O'Keefe & Nadel 1978](http://www.cognitivemap.net/)). In humans, map-like coding supports navigation and generalises beyond space ([Epstein et al. 2017](https://doi.org/10.1038/nn.4656)). A hippocampus that predicts the states that follow ([Stachenfeld, Botvinick & Gershman 2017](https://doi.org/10.1038/nn.4650)) is a reminder that a map can be learned from the ways actually walked.
- **Landmark, route and survey knowledge.** Siegel and White proposed that a newcomer first knows landmarks, then routes between them, then a survey ([Siegel & White 1975](https://doi.org/10.1016/S0065-2407(08)60007-5)). Later work found these grow together and vary widely between people (Montello 1998; [Ishikawa & Montello 2006](https://doi.org/10.1016/j.cogpsych.2005.08.003)). Design implication: one store can serve all three, and route knowledge need not be a separate stage.
- Wayfinding tasks differ by what is known: aided, unaided toward a known goal, or searching for an unknown one ([Wiener, Büchner & Hölscher 2009](https://doi.org/10.1080/13875860902906496)). The arenas below sample those cases.
- **Spatial semantic hierarchy.** Kuipers layered control (follow a wall, a corridor), causal (this action from this place leads there), topological (places and paths) and metrical knowledge ([Kuipers 1978](https://doi.org/10.1207/s15516709cog0202_3); [Kuipers 2000](https://doi.org/10.1016/S0004-3702(00)00017-5)). That maps onto what the core already has: steering (control), told outcomes (causal), places and areas (topological), and tiles (metrical).

**Planning with partial knowledge.**
- **The free-space assumption.** Plan as if unknown ground is passable, move, observe, and re-plan when the belief is contradicted. Koenig, Tovey and Smirnov bound how far such an agent travels in unknown terrain, and show it is reasonable in practice ([Koenig, Tovey & Smirnov 2003](https://doi.org/10.1016/S0004-3702(03)00052-3)).
- **Incremental search.** D* ([Stentz 1994](https://doi.org/10.1109/ROBOT.1994.351061)), LPA* ([Koenig, Likhachev & Furcy 2004](https://doi.org/10.1016/j.artint.2002.12.001)) and D* Lite ([Koenig & Likhachev 2002](https://www.ri.cmu.edu/publications/d-lite/), [pdf](https://cse-robotics.engr.tamu.edu/dshell/cs625/aaai02b.pdf)) repair a search tree when edge costs change, instead of searching again. Their gain is largest when the goal is far and the changes are near the agent.
- **Hierarchy.** HPA* ([Botea, Müller & Schaeffer 2004](https://webdocs.cs.ualberta.ca/~mmueller/ps/hpastar.pdf)) and PRA* ([Sturtevant & Buro 2005](https://mlanthology.org/aaai/2005/sturtevant2005aaai-partial)) abstract the grid into clusters and refine a route near the agent. The core's areas, regions and tiles are of this family (PATHS).
- **Real-time search.** LRTA* ([Korf 1990](https://doi.org/10.1016/0004-3702(90)90054-4)) bounds the computation per move and learns heuristic values. In a persistent world those values are per-agent route memory. It is useful as a fallback when a plan is too costly.
- **Frontier exploration.** Go to the nearest boundary between known open space and the unknown ([Yamauchi 1997](https://doi.org/10.1109/CIRA.1997.613851)), over an occupancy grid ([Elfes 1989](https://doi.org/10.1109/2.30720)). This suits a character told to explore. A walk with a goal is the free-space assumption above.

**How game AIs do it.**
- **Left 4 Dead** plans on a navigation mesh. It follows the path reactively: it steers toward the furthest visible point on the path and avoids nearby obstacles locally, without planning again ([Booth 2009](https://cdn.fastly.steamstatic.com/apps/valve/2009/ai_systems_of_l4d_mike_booth.pdf)). That is the split proposed here: plan coarse, execute with fast local reaction.
- **Halo.** A perception and memory layer sits beneath behaviour. Creatures keep beliefs about objects they cannot see ([Isla 2005](https://gamedeveloper.com/programming/gdc-2005-proceeding-handling-complexity-in-the-i-halo-2-i-ai)). Isla and Blumberg's object persistence keeps a probabilistic estimate of where an unseen object is ([Isla & Blumberg 2002](https://characters.media.mit.edu/Papers/objectPersistence.pdf)), which is exactly the missing "last-seen place".
- **F.E.A.R.** separates a planner's goals from the movement and animation states that carry them out ([Orkin 2006](https://gdcvault.com/play/1013394/Three-States-and-a-Plan)).
- In these games, navmesh plus perception usually means the **map is global and the targets are perceived**. Here the stricter rule (minds know only what they perceived) also covers the ground.
- **Local avoidance.** Reynolds' steering behaviours ([Reynolds 1999](https://www.red3d.com/cwr/steer/gdc99/)) are what the core has now. Reciprocal velocity obstacles (RVO and ORCA: [van den Berg, Lin & Manocha 2008](https://doi.org/10.1109/ROBOT.2008.4543489); [van den Berg et al. 2011](https://doi.org/10.1007/978-3-642-19457-3_1)) give smooth avoidance in dense crowds without oscillation. Recast and Detour is the common open-source navmesh and crowd stack ([recastnavigation](https://github.com/recastnavigation/recastnavigation)).

### 2.2 The remembered map

Static terrain is the same for everyone. What differs is **which parts each character has seen, and when**. So the remembered map is a mask over the shared map plus a few beliefs about things that change. It is not a copy of the map.

**Known ground: the `known_ground` table** (private; one row per character and 128 m block it has seen into):

| Column | Type | Meaning |
|---|---|---|
| `id` | u64, primary key | |
| `actor` | u32, btree | the character |
| `block` | u32 | block number (the nav areas' block: 8 × 8 chunks) |
| `cells` | `[u16; 64]` as bytes (128 B) | per chunk, a 4 × 4 mask of 4 m cells seen |
| `seen_at` | `[u32; 64]` as bytes (256 B) | per chunk, the map's edit epoch when it was last seen |
| `last_ms` | u64 | last time a cell here was seen |

Index: `(actor, block)` btree for the planner's point lookups; `actor` for death cleanup and the player's view.

- **What marks a cell.** The one sight rule (`sight::sees`, with facing when `fov_on` is on). On a character's own slot evaluation, which BATTLE_SCALE fix 2 brings to about 1 Hz, mark cells within sight whose centre has a clear sight line from the eye. Cells already marked cost one bit test each, so a resident at home quickly costs nearly nothing. At 11 m day sight, at most about 30 cells are candidates. Walking also marks the cells the body crossed.
- **Players are marked by the same rule.** Their characters build known ground as minds' do.
- **The cell size is a law** (`known_cell_m`, 4 m), so the measurement can move it. 4 m is a quarter of a chunk and half a narrow street. A cell partly seen counts as seen, so up to about 2 m of unseen ground can be known per edge. That is accepted for its cost and is reported by the leak test in §4.
- **Edits since sight.** The authority keeps a bounded per-chunk **edit log**: the map's epoch, plus the tiles before the edit, for each tile changed after genesis (walls and gates built, terrain edits). The planner's belief for a known chunk is its tiles as of `seen_at`: the current tiles, with later edits undone from the log. An entry is dropped once no living character's `seen_at` for that chunk predates it, or past a cap of 64 entries per chunk. Past the cap, the oldest sightings of that chunk fall back to unknown. Edits are rare (building), so the log stays small. Its rows and growth are measured in step 1.

**Remembered gates and things: on the existing `familiar` rows.** This depends on BATTLE_SCALE fix 1 (age-based eviction, a 2,048-row cap).
- Three columns are appended with defaults (an automatic migration): `x`, `y` (where it was last seen) and `state` (a gate: open or shut as last seen; a structure: its kind code).
- They are written when the row is already touched (first sight, the 30 s refresh) and when a gate is seen to change. A gate shut out of sight keeps its open belief until it is seen.
- **Landmarks.** A structure's row with its believed position and kind lets a target `{"known": "hall"}` resolve to "the nearest hall I know of" from memory, not sight. A destroyed hall stays believed until the character sees its site.
- **Last-seen creatures.** A creature's row holds where it was last seen, written also when it leaves sight. A target `{"last_seen": who}` resolves to that point. This is the object persistence of [Isla & Blumberg 2002](https://characters.media.mit.edu/Papers/objectPersistence.pdf), without the probability: a point and a time, which the mind reads as it likes.

**Places and routes told: the existing `place` table**, with two columns appended with defaults:
- `source`: `seen`, `given` or `told`.
- `teller`: the character it was heard from.

A told route is an ordered list of told places (a `route` text key grouping them). This is how "follow the river north to the bridge, then the road east" becomes knowledge. A told place's coordinate is the teller's belief, which can be wrong. Being told a place or route **never marks ground as seen**. The planner treats told places as goals and waypoints over unknown ground.

Minds already write places from conversation (the `update.places` path in `mind.rs`). The change is recording them as told. A future map artifact (a drawn map on a tablet) could mark cells as known-by-map, through the know-how and artifact rules. It is out of scope here.

**Forgetting.** Known ground is not forgotten at first: it is bounded by the world's size, and people rarely forget the shape of a town they lived in. It goes at death with the character's other rows; a new identity inherits nothing. A fading law (blocks unvisited for N game days count as unknown, or cost more) is held back until growth or play shows a need. `familiar` keeps the eviction of BATTLE_SCALE fix 1. Places keep their 24-row cap.

### 2.3 Planning over one's own map

A **`Belief` view** goes into `living_rules::nav`, beside the true `Map`. It answers, for a tile, `Open`, `Blocked` or `Unknown`:
- Seen cells give the tiles as of `seen_at`.
- Remembered gates give their believed state.
- Every other tile is `Unknown`.

Tiles within the character's sight now are by definition seen, so the near field is always true.

- **Cost.** Open tiles cost as today, with the road speed-up. Unknown tiles are passable at `unknown_cost` × (a law; 1.5 to start). A known route is preferred, but a goal across unknown ground is still attempted: the free-space assumption ([Koenig, Tovey & Smirnov 2003](https://doi.org/10.1016/S0004-3702(03)00052-3)).
- **The same three levels.** For areas and regions:
  - A **fully seen chunk whose `seen_at` is at or after its last edit** uses the shared region cache, which is its true structure.
  - A **partly seen chunk** gets believed regions: a flood of its 256 tiles with unknown counted open (microseconds). They are cached per leg, not per character.
  - An **unknown chunk or block** is one open node linked to its neighbours at `unknown_cost`.

  So the shared caches are used only where the character's belief equals the truth, and nothing derived from unseen ground reaches the route.
- **The leg** is the existing tile A* with string pulling, over the belief, 64 m at a time. Its corridor mask is built once per leg, so each expansion is a bit test.
- **Discovery.** When a newly marked cell makes a tile of the current leg `Blocked`, the leg is planned again from where the body is. The same happens when a gate on the leg is seen shut, or the body's sweep hits something the belief said was open: the sweep only stops at what is really there, and the eye has seen it by then.

  This is how a stranger "finds the way": walk toward it, see the building row, go round. Each re-plan is a 64 m leg (about 0.2 ms, 3–5 M fuel). LPA* or D* Lite repair is adopted only if step 2 measures re-plans above 30% of `tick.motion` fuel or legs over the PATHS maximum.
- **Never from the truth:**
  - `nearest_reachable` and `reachable` (connectivity labels) are not used for belief walks.
  - A goal on believed-unwalkable ground snaps to the nearest believed-open tile.
  - A goal that turns out to be unreachable is found out by trying: the walk ends "the way is blocked" or "you were getting no nearer", told as today.
  - `wander` picks a point by heading, not by reachability.
- **Pursuits and flights from a graph hold their creature by sight.** `goto` a creature and an approach to act join `FLAG_SIGHT`, which the 3.3 intents already have. The same applies to a flight from a creature. When sight is lost, they go by the last-seen place and record it in `familiar`.
- **The same for every controller.** A player's click-to-move plans over the character's known ground, as a mind's `goto` does. A player's keys are its own hands.

  **Open for the owner** (it changes the feel): the client draws terrain out to 110 m, beyond the character's sight. Drawing unseen ground as unknown (a fog over cells not in `my_known_ground`) would give the player the character's knowledge. Not drawing it keeps a perception gap that PERCEPTION's Open list already names.
- **Behind a law.** The world law `nav_belief` is off by default until the arenas pass. Off, routes are as today, so a world can be compared before and after.

**What a mind is told:**
- Its places, marked told ("told by Wren, never been there") or seen.
- When it asks for a walk over unknown ground, "you do not know the way there; you will have to find it", as the act's outcome text.
- The new targets `known` and `last_seen`, documented in the grammar.

It is not given a route or a tactic. The body finds the way, as a person's feet do: walking to a remembered place costs no deliberation.

### 2.4 Cost at 2,000 characters

Estimates from the island's geometry (2048 m: 16,384 chunks, 256 blocks) and the measured costs in PATHS and LIVING_CORE. They are to be measured, not claimed.

| Item | Estimate |
|---|---|
| `known_ground` row | about 400 B (plus key and index) |
| Rows per character | a resident about 10–20 blocks; a traveller 40–80; the island's maximum is 256 |
| Storage | typical 4–8 KB a character; **about 13 MB at 2,000**; worst case (everyone has seen the whole island) about 200 MB, not reachable in play |
| Writes | one row rewrite when new cells are seen, coalesced to at most every `known_flush_s` (5 s) per character. At 2,000 with 10% exploring: about 40 rows/s, 16 KB/s of commitlog (about 58 MB an hour). A settled resident writes almost nothing. |
| Marking | about 30 bit tests per slot evaluation, plus a sight line per new cell: well under the 0.05–0.07 ms per evaluation of BATTLE_SCALE's estimate. Zero in a battle once the ground is seen. |
| `familiar` additions | 12 B per row; writes only when the row is touched already, plus a creature leaving sight. Bounded by BATTLE_SCALE's noticing at 1 Hz. |
| Edit log | entries × (tile index + old byte + epoch): a few KB on a built-up island; measured in step 1 |
| Planning | a leg as today (0.2 ms p50, 18.4 M fuel at most), plus one 64 m re-plan per discovery: about one every 10–20 s for an exploring walker in a town. At 200 exploring walkers, about 2–4 ms of tick work a second. |
| Module memory | the corridor masks and believed regions per leg are scratch, not retained |

SpacetimeDB documentation consulted (2026-11-12; server, crates and bindings pinned at 2.14.1):
- [Performance](https://spacetimedb.com/docs/tables/performance/): private tables cost no client bandwidth; focused tables touch fewer rows. **Implication:** knowledge goes in its own private table keyed per block, not on `body`, `steer` or `mind_state`, so the hot public row stays lean and `mind_state` is not rewritten (BATTLE_SCALE found its 96-entry list dominating the commitlog).
- [Reducers](https://spacetimedb.com/docs/functions/reducers/): module-level state is not reliable across calls ("SpacetimeDB may run each reducer in a fresh WASM or JS instance"), and it can survive a rollback. **Implication:** known ground is durable in a table. The 5 s coalescing buffer is a loss-tolerant cache: a lost buffer only forgets a few seconds of cells that are seen again next pass, and cells kept after a rollback were in sight anyway.
- [Constraints](https://spacetimedb.com/docs/tables/constraints/): an update with an unchanged primary key is an in-place update event. **Implication:** a block row is updated in place.
- [Hide information from players](https://spacetimedb.com/docs/how-to/games/hide-information/): keep tables private and expose a caller-scoped view. **Implication:** a `my_known_ground` view (the caller's character's rows, by the `actor` index point lookup) for the client's fog, if the owner wants it.
- [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations) and [default values](https://spacetimedb.com/docs/tables/default-values): new tables are allowed, and new columns go at the end with defaults (`familiar`, `place`).

**Data paths:**

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
|---|---|---|---|---|---|---|
| Mark seen cells (slot evaluation) | own `known_ground` rows in sight (1–4 blocks) | one row per block with new cells, at most every 5 s | `(actor, block)` | none (private); the owner's view if built | about 1 Hz per character, mostly a no-op | rows per block seen |
| Gate or structure seen, creature leaves sight | `familiar` by `(actor, thing)` | that row | `by_actor_thing` | none | on change | none beyond `familiar`'s cap |
| Plan a leg over the belief | own rows for the corridor's blocks; edit log for its chunks; shared map and caches | `body.path`, `walk_route` as today | point lookups | as today | per leg, plus per discovery | none |
| Told place or route | — | `place` rows | `actor` | none | per conversation | 24-row cap, plus told routes (cap 8) |
| Death | — | delete the character's rows | `actor` | — | per death | none |

## 3. Real-time input like a player

### 3.1 What a player's hands do, and what the body already does

A player sends a direction, run, a held look, and discrete moves (dodge, jump, step aside, strike), continuously and about as fast as they perceive. The authority applies the same costs and limits to everyone. For an AI body, the graph runner plus steering already does this: steering turns a goal into segments, and a routine's conditions (`doing`, `threatened`, `near`, stamina) start a dodge on the tick with no model in the loop (COMBAT_MIND 3.2).

What it lacks:
1. **Knowledge-bounded planning** (§2).
2. **Reaction to what is perceived, at the moment it is perceived.** A body that steps into the way ahead is noticed only at the next cadence step: 2 s alone, 333 ms in a crowd, 250 ms in a chase.
3. **Flight that looks for open ground**, not straight away from the threat.
4. **Holding intents planned around walls** (`back_off`, `circle`, `screen`).

So "input like a player" is a change to how the existing layer is triggered and what it reads. No new controller is needed.

### 3.2 Candidates

Input latency here is the time from a perceived change (a body in the way, a blocker seen, the target turning) to the body's new segment. A human's choice reaction is about 200–300 ms. Avatar games become noticeably harder above about 100 ms (first person) to 500 ms (third person) ([Claypool & Claypool 2006](https://doi.org/10.1145/1167838.1167860), [report](https://ftp.cs.wpi.edu/pub/techreports/pdf/06-13.pdf)).

| Option | Latency | Cost | Where | Same-rule fit | Verdict |
|---|---|---|---|---|---|
| **Today's graph runner plus steering** | 40 ms minimum step; looks again at 125 ms (fight), 250 ms (chase), 333 ms (crowd), 2 s (alone); obstacles in the sweep at once | about 19 µs a steering update (`intents_cost`); about 0.2 ms of tick at p50 for 2,000 characters; evaluations 0.05–0.07 ms (BATTLE_SCALE) | authority | Same physics and limits | Keep as the base. |
| **Scripted "hands" (proposed): the same, event-triggered, over the belief** | perceived change → segment in one tick (≤ 17 ms) where an event exists, else the cadence above; target in §4 | adds about 5–20 µs per triggered update; events bounded by a minimum step | authority, `living_rules` (pure, deterministic, replayable) | Produces the player's input tuple; same `input_hz` bucket for discrete moves | **Chosen.** |
| **Learned controller** (a small policy net) | about 10–100 µs inference | training data and runs | authority (WASM) or the mind service | **Violates** "arenas never train or install behaviour", and installs a hidden policy that is neither a script nor a mind's plan. Not replayable from rules alone. | Rejected. |
| **Small language model per step** | 100 ms to 2 s per call plus transport (DeepSeek V4.1 Flash: 1.8 s p50 on talk-sized prompts, MODEL_COST) | 2,000 characters at even 1 Hz is 2,000 calls a second | mind service only (inference never in reducers) | Allowed, but far too slow for motion | Rejected for motion. A model can write intents, never hands. |
| **Fast lane** ([FAST_LANE.md](FAST_LANE.md)) | about 3 s from a blow to the patch installed | capped at 2 a second world-wide, 4 in flight | mind service | Right tool for revising which intent to hold between blows | Not a motion layer. It sits above the hands. |

### 3.3 The hands

They live in `living_rules::steer` (pure) and run from `motion::steer_update`. Everything they read is the character's own:
- the goal and intent from the plan;
- the belief leg;
- bodies perceived within a short range;
- the believed map within sight, which is the true map there.

**Output: the same tuple a player's input sets**:
- direction and speed (walk or run, with the breath rules);
- a held look;
- discrete moves (dodge, jump, step aside) through the same act path, costs, cooldowns and `input_hz` bucket a player's keys use.

Everything changes in steering, so every controller whose body is held by a goal gets it. A player's keys stay its own hands.

1. **Events, not polling.** When a body's segment changes, walkers whose sweep cone (the next `ahead_m`, a law: 4 m) it crosses are made due now. This uses the per-tick chunk-body cache that minds' perception already fills. A gate seen shutting and a newly seen blocked cell on the leg are also events. A minimum step (`MIN_STEP_MS`, 40 ms) and at most 15 re-steers a second per body bound the cost in a crowd. The 2 s, 3, 4 and 8 Hz cadences remain the fallbacks.
2. **Flight and back-off look for open ground.** Instead of straight away, score 16 headings by how far the believed map is open that way within sight (the existing sweep) and by how directly it leads away from the threat. Run the best, and look again at the chase cadence. "Cornered" then means no heading has room, which is the true case. This is the same rule for `flee`, `back_off`, a band backing off and an animal's flight.
3. **Holding intents plan round walls.** `circle` and `keep_distance` take a short belief leg to their next band or orbit point when the straight way is blocked, instead of ending. `screen` (COMBAT_MIND 3.3) uses the same scoring with the sight rule.
4. **Reciprocal avoidance** (ORCA-like) **only if the crowd arena fails** its stuck or contact targets with separation alone.

**The split between authority and mind service:**

| Authority (reducers, deterministic, no external calls) | Mind service (`living/mind`, external inference) |
|---|---|
| Sight, known ground, remembered gates, landmarks and last-seen places | What to want, and which place, person or intent to name |
| The belief planner, legs, discovery re-plans | Writing routines that hold intents (`keep_distance`, `circle`, `screen`) |
| The hands: events, flight scoring, intents round walls, the input bucket | The fast lane: switching intent between blows |
| Telling outcomes ("the way is blocked", "you do not know the way there") | Reading those outcomes and changing plans |

## 4. Measures: the navigation arenas

The arenas are trial configurations (`living/trials/nav-*.json`) with scripted fixtures. Their opponents, crowds and gate-shutters are residents whose graphs the trial sets, as the R2 arenas' foes are. The arenas measure: nothing in them is installed in any character, and the subject's mind is told nothing about them. Each runs on scratch `verify-*` or trial databases, never on the paused reference worlds.

Each arena runs with three kinds of subject:
- **Body only** (free): a fixed graph of walks, to measure the hands and the planner.
- **Click-to-move** (free): a scripted player identity using `human_act` `goto`, so players are measured too.
- **Minded** (fake model free; real model paid): to measure naming and use of known and told places.

Every arm runs with `nav_belief` off (today) and on.

| Arena | Setup | Variants |
|---|---|---|
| **N1 Unfamiliar town** | A newcomer arrives at the gate of a town it has never seen (island, Brackenford or a terraced town). It is given three places to reach in turn (the inn, the square, the north gate), as told places with the teller's coordinates. | told places only; a told route; a terraced town (stairs between levels); one told coordinate 6 m wrong |
| **N2 Blocked route** | Warm-up: the subject walks a route once, so it is known. Then a fixture shuts a gate on it (or builds a wall) out of the subject's sight, and the subject is sent back along it. | alternative way known; alternative way unknown; the gate reopened before arrival (belief wrong the other way) |
| **N3 Moving crowd** | The subject crosses a square through two opposing streams of scripted walkers at 2.6 m/s. | 50 and 200 walkers; a stream that stops in the subject's way; the subject running |
| **N4 Chase and flight** | A scripted chaser (a wolf, or a person at run speed) chases the subject in a town edge with house rows, a fence and an open field. Reversed: the subject chases a fixture that breaks line of sight round corners. | day and night sight; the subject knowing the ground or not |

**Fixed measures.** Every arm reports all of them. Definitions are fixed now; the tools compute them from `samples.jsonl` and `positions.jsonl`, the body rows, `experiences.jsonl` and a fixture stimulus log.

1. **Arrival rate**: the share of walks to a reachable goal that end in arrival within 3 × the true optimal time. For N4 flight, the share of chases where the subject escapes (beyond `flee_clear`, or out of the chaser's sight for 10 s) and the share of flights ending "cornered". For a pursuit, capture within 60 s, and reacquisition after sight is lost.
2. **Time ratio against the known-map optimal**: the walked time over the fastest time on the subject's belief at the moment of the order (the same planner, unlimited budget, rules speeds). It measures the hands and the planner, not the knowledge.
3. **Time ratio against the true optimal**: the walked time over the fastest on the true map. It measures what not knowing costs. Today's omniscient planner sets the floor (about 1.0).
4. **Stuck events**: a body with a movement goal that moves less than 0.15 m in 2 s while more than 2.5 m from its goal, and not standing in a band or within `follow` reach. Reported per 10 walk-minutes, with the longest.
5. **Input latency**: from a fixture's stimulus (a body stepping in the way within 4 m ahead, a gate shut in sight on the leg, the target changing direction) to the first `body` segment whose `t_ms` is at or after the stimulus and whose heading changes more than 15° or whose speed drops more than 30%. Reported as p50 and p95.

Cost guards are reported beside the measures:
- `tick.motion` ms/s and p99;
- fuel per leg (p50 and maximum);
- re-plans per walk;
- `known_ground` rows, bytes and writes per second;
- edit-log size;
- body row updates per second (subscription volume).

A **leak check** goes with every on-arm. Two subjects with the same start and goal, one knowing a shortcut and one not, must take different routes. A gate change out of a subject's sight must leave its route unchanged (a route is a pure function of belief, start and goal).

**Committed target spread** (before any run; `nav_belief` on unless stated):

| Measure | N1 Unfamiliar town | N2 Blocked route | N3 Moving crowd | N4 Chase and flight |
|---|---|---|---|---|
| Arrival rate | ≥ 95% | ≥ 95% (alternative unknown ≥ 90%) | ≥ 98% | flight escapes: report, no target; "cornered" ≤ 10% of flights; pursuit reacquires a lost target ≥ 70% when it is within 10 m of where it was last seen |
| Time ÷ known-map optimal | p50 ≤ 1.15, p90 ≤ 1.40 | p50 ≤ 1.20, p90 ≤ 1.50 | p50 ≤ 1.25, p90 ≤ 1.60 | — |
| Time ÷ true optimal | p50 1.2–2.0, p90 ≤ 3.0 (above 1.0 is expected: that is not knowing) | known alternative p50 ≤ 1.5; unknown alternative p50 ≤ 2.5, p90 ≤ 4.0 | p50 ≤ 1.3 | — |
| Stuck events | ≤ 0.3 per 10 walk-minutes, none ≥ 30 s | ≤ 0.5 per 10, none ≥ 30 s | ≤ 0.5 per 10, none ≥ 15 s; contacts closer than 0.4 m reported | ≤ 0.3 per 10 |
| Input latency (stimulus → segment) | p95 ≤ 300 ms | gate seen: p95 ≤ 150 ms | body ahead: p50 ≤ 50 ms, p95 ≤ 150 ms | chaser turns: p50 ≤ 70 ms, p95 ≤ 150 ms |
| Off arm (today), expected | arrival ≈ 100%, true ratio ≈ 1.0 (omniscient), latency by cadence (up to 333 ms in a crowd) | reroutes before the gate is seen (a leak) | latency up to 333 ms | "cornered" common |
| Cost guards | `tick.motion` ≤ 2 × today's at the same population; leg fuel ≤ 20 M at most; ≤ 1 `known_ground` write per 5 s per exploring character | same | 200 walkers: tick p99 ≤ 16.7 ms, no tick over budget attributable to motion | same |

A miss is reported with its evidence. No target moves after a run.

### 4.1 How the arenas are built (branch `nav-arenas`, committed before any run, 2026-11-13)

The targets above are unchanged. This note fixes how they are measured, before the first run. It is written after steps 1–3 (`flee-open`, `pursue-last-seen`, `known-ground`). Told places as told (`place.source`), the `known` and `last_seen` targets and the hands' event triggers (plan steps 3–5) are not built. So the on arm here is `nav_belief` over recorded ground, and latencies are those of today's cadence.

**Where.** The `island` seed, on scratch `verify-nav-*` databases on the Spark's scratch server (`slop-move-stdb`, :3361). Never the trial server while the merge gate runs, and never a paused reference world.
- N1: Brackenford (walled; its square, its inn, its north gate) and Kettlebridge (terraces joined by stairs and ramps).
- N2: Brackenford's gates. A town member is the gate-keeper fixture, since only the town may shut them.
- N3: Brackenford's square.
- N4: a town edge with a house row, a fence or wall, and open field, found on the map by the driver (the nearest that fits).

**Driver: `living/tools/nav_arena.py`.** It launches through `verify.py` and uses only existing reducers: `spawn_newcomer`, `spawn_crowd`, `place_at`, `set_behavior`, `set_world_law`, `grant_items`, and for players `join` and `human_act`. Fixtures act through the rules as any character does: the gate-keeper shuts a gate with the gate skill, a builder builds a wall with the build skill, a chaser chases with its graph. Nothing is installed in the subject, and no rule is bypassed for it.
- **Fresh subjects.** Each walk's subject is a fresh character (a newcomer for N1, otherwise a spawned adult placed at the start), so it begins with no known ground except what a warm-up gives it.
- **Off and on.** Each phase is run once with `nav_belief` off and once on, each with its own fresh subjects in the same world (the law is world-wide, and changing it between phases changes no character's knowledge).
- **Replicates.** Five per variant, subject and law: five subjects at a time, started 2 s apart from starts at least 6 m apart.
- **Recording.**
  - A body subscription for the arena's characters (every segment, `bodies.jsonl`).
  - The driver's own log of what it did and when (`stimuli.jsonl`, in the authority's time). The clock is sampled before and after each call, and the spread is kept.
  - The gate rows (`changed_ms`), the subjects' `act` experiences, and `known_ground` row counts and bytes.
  - The tick profile (`set_profile`) for `tick.motion` and for ticks over budget.

**Subjects.**
- **Body only:** a fixed graph per walk (a `goto` to the goal's coordinates; a told route is a `seq` of `goto`s).
- **Click-to-move:** a player identity per walker, `human_act` `goto` to the same coordinates. The click goes through the same planner as a mind's `goto`.
- **Minded, fake model (free):** `trials.py` configurations `living/trials/nav-n1-*.json` for N1 only. The newcomer's background sheet holds the three places as its own places, since a told place cannot yet be marked as told. The fake model's replies walk to them by name. This checks that names resolve and the walk completes, not what a mind would choose.
- **Minded, real model (paid):** the same configurations on the trial models, asked for separately (below).

**Variants as run.**
- **N1:** (a) the three places in turn as coordinates; (b) a told route, the same goals through two waypoints; (c) Kettlebridge, three places on different terraces; (d) as (a), with the second goal's coordinates 6 m off. In (d), arrival counts at the told point or the nearest reachable point to it, and the distance to the true place is reported.
- **N2:** warm-up from the start to the goal and back through the gate, then the gate shut (or a wall built on the route) out of the subject's sight, then the walk again. Variants: (a) an alternative way known (a second warm-up walk took it); (b) unknown; (c) the gate shut and then reopened before the subject comes within sight of it.
- **N3:** 50 and 200 walkers in two opposing streams across the square at a run (2.6 m/s), each with a `seq` of `goto`s between the square's two sides. The subject crosses at right angles. Variants: one stream stopping in the subject's way (its walkers' graphs end in `wait`), and the subject running.
- **N4 flight:** a chaser (a wolf from `spawn_crowd`'s animals where a wolf can be had, else a person at run speed with a chasing graph) starts 12 m from a subject whose graph flees it, by day and by night. **N4 pursuit:** the subject chases a fixture that walks a fixed route round a house corner, breaking line of sight. Each is run with the subject knowing the ground (a warm-up walk round the block) and not.

**Report: `living/tools/nav_report.py`.** It computes the five measures of §4 and the cost guards from an arm's folder, by the definitions above, plus a self-test on hand-made rows.
- **Optimal times.** A small Rust example, `living/rules/examples/nav_optimal.rs`, uses the same planner (`living_rules::known` over belief, `nav` over the true map) with no fuel limit. It reads the map's terrain chunks, the subject's `known_ground` and remembered gates at the moment of the order (read by the driver at that moment), the start and the goal. It gives the path's cost in metres at walking pace. The optimal time is that cost ÷ the subject's own pace for the gait (the median speed of its moving segments on open ground).
- **Stimuli** come from authority rows only:
  - N1: the order (the driver's call time). A belief arm also counts as stimuli the moments a replan follows a seen contradiction (the body's `path` changing).
  - N2: the first moment the shut gate or new wall is within the subject's ground sight with a clear line (the map's line test over the tile grid).
  - N3: a walker's body entering a 4 m cone ahead of the subject (±30°).
  - N4: the chaser's or fixture's heading changing more than 30° while within the subject's sight.
- **Latency** is the time from a stimulus to the first subject segment at or after it that turns more than 15° or slows more than 30%, by §4's rule. A stimulus with no such segment within 2 s is counted as "no response", separately.
- **The leak check:** two subjects, the same start and goal, one with the shortcut walked in warm-up and one without. Their first legs must differ on the on arm. A gate shut out of a subject's sight must leave its `path` unchanged until it is seen.

**Outputs.** `.local/living/nav/<run>/<arena>-<variant>-<law>-<subject>/`. A run summary is added to this section with each arm's measures beside its target. A miss stays a miss.

**The paid arm, proposed, not run** (the owner decides; asked before any call):
- N1 with a minded newcomer on the trial models: 2 arms (`nav_belief` off and on) × 5 repeats × 20 minutes. That is 10 × ⅓ h × $0.17 ≈ $0.57.
- A hamlet arm: 11 thinkers × 1 world-hour × 2 arms ≈ $3.8.
- Together about $4.4, stopped at $6, ceiling $8 with reruns.
- The design's third arm (belief + known/told targets) is dropped until those targets exist.

**Free cost.** One scratch world at a time on :3361, through the build slot. About 25 runs of 5–15 minutes. No model calls.

## 5. Plan and cost

Smallest first. Each step is behind a law where it changes behaviour. Each runs the verification surfaces it touches: verify-core for the rules and the tick; verify-player for click-to-move; verify-client for any view; verify-minds for targets and told places. Each changes the surface skills in the same change where it alters their shape.

| Step | What | Cost |
|---|---|---|
| **0. Baseline arenas** | N1–N4 trial configurations, the fixture stimulus log, a `nav_report.py` computing the five measures and the guards. Run against today's planner. This validates the measures and gives the off-arm numbers. No authority change except the stimulus log. | Free (scripted, no minds) |
| **1. Known ground, recording only** | The `known_ground` table, marking at the slot evaluation, the coalescing, death cleanup, and the edit log. The planner is unchanged. Measure rows, bytes, writes and marking cost at the 216-character gate and in a 2,000-character `bench.py` window. | Free |
| **2. Belief planner** | The `Belief` view in `nav.rs`, `unknown_cost`, discovery re-plans, no truth snapping, `wander` by heading, behind `nav_belief`. Pursuits and flights by sight (`FLAG_SIGHT`). Arenas N1, N2 and the leak check, on and off. | Free |
| **3. Remembered things** | `familiar` gains `x`, `y` and `state`, coordinated with BATTLE_SCALE fix 1. Gates by belief; the `known` and `last_seen` targets; the grammar and prompt lines. Fake-model arm of N1 (targets resolve). | Free |
| **4. Told places and routes** | `place.source` and `teller`; told routes; the "never been there" line. Fake-model arm. | Free |
| **5. Hands** | Event triggers for bodies ahead and gates seen, flight scoring, intents round walls, `screen`. Arenas N3 and N4. ORCA-like avoidance only if N3 fails. | Free |
| **6. Incremental search** | LPA* or D* Lite leg repair, only if step 2 shows re-plans above 30% of motion fuel or legs over 20 M. | Free |
| **7. Client fog** (owner decision) | `my_known_ground` view; the client draws unseen ground as unknown, and click-to-move already plans on belief. verify-client and verify-ui. | Free |
| **Paid arm** (one, after steps 3–4) | Do real minds use known and told places? N1 with a minded newcomer, 3 arms (off; belief; belief + known/told targets) × 5 repeats × 20 minutes, on the trial models. At $0.149–0.174 per resident-hour (TRIALS, life runs): 15 × ⅓ h × $0.17 ≈ **$0.85**. A hamlet arm, 11 thinkers × 1 world-hour × 2 arms (off and on), ≈ **$3.8**. | **About $5**, ceiling $8 with re-runs. Run only after the owner authorises it. |

Nothing here needs a battle run. Steps 1, 2 and 5 should be measured once at the 216-character gate before they count as accepted, in the quiet-box window, after the battle-scale acceptance runs.

**Not covered:**
- Height (the authority is 2D: no jumping over a low wall or down a drop). Whether a jump should clear a `Low` tile is a rules question for the owner.
- Houses with interiors and doors.
- Swimming.
- Mounts.
- Maps as artifacts.
- Groups moving together (escort, herding), beyond `follow`.

## A. The evidence scanners

Run with `python3 -I` over `~/dev/*/.local/living/trials/**`, skipping `journal/`:
- **Act outcomes.** `experiences.jsonl` lines of kind `act` matching "You did what you had decided: goto" and "What you had decided did not work out: goto → T: R". They are grouped by reason, and by the file's date (before or from 2026-11-11, when `path-1` and connected ground were on main).
- **Plan-step failures.** Lines of kind `own` matching "You failed to <skill>".
- **Stuck.** In `samples.jsonl`, consecutive samples with the same activity and label in `goto`, `wander` or `flee`, under 10 s apart, moving less than 0.15 m, more than 2.5 m from the activity's target point (`activity[2]`).

The counts in §1.3 are those scripts' output on 2026-11-12. The scripts are in the session scratchpad, not committed: they are a one-off survey, and `nav_report.py` (step 0) replaces them.

## Sources

- Booth, M. (2009). *The AI Systems of Left 4 Dead.* Valve. [pdf](https://cdn.fastly.steamstatic.com/apps/valve/2009/ai_systems_of_l4d_mike_booth.pdf)
- Botea, A., Müller, M., & Schaeffer, J. (2004). Near optimal hierarchical path-finding. *Journal of Game Development* 1(1). [pdf](https://webdocs.cs.ualberta.ca/~mmueller/ps/hpastar.pdf)
- Claypool, M., & Claypool, K. (2006). Latency and player actions in online games. *Communications of the ACM* 49(11). [doi](https://doi.org/10.1145/1167838.1167860), [report](https://ftp.cs.wpi.edu/pub/techreports/pdf/06-13.pdf)
- Elfes, A. (1989). Using occupancy grids for mobile robot perception and navigation. *Computer* 22(6). [doi](https://doi.org/10.1109/2.30720)
- Epstein, R. A., Patai, E. Z., Julian, J. B., & Spiers, H. J. (2017). The cognitive map in humans: spatial navigation and beyond. *Nature Neuroscience* 20. [doi](https://doi.org/10.1038/nn.4656)
- Ishikawa, T., & Montello, D. R. (2006). Spatial knowledge acquisition from direct experience in the environment. *Cognitive Psychology* 52(2). [doi](https://doi.org/10.1016/j.cogpsych.2005.08.003)
- Isla, D. (2005). Handling complexity in the Halo 2 AI. GDC. [article](https://gamedeveloper.com/programming/gdc-2005-proceeding-handling-complexity-in-the-i-halo-2-i-ai)
- Isla, D., & Blumberg, B. (2002). Object persistence for synthetic creatures. AAMAS 2002, pp. 1356–1363. [pdf](https://characters.media.mit.edu/Papers/objectPersistence.pdf)
- Koenig, S., & Likhachev, M. (2002). D* Lite. AAAI-02, pp. 476–483. [page](https://www.ri.cmu.edu/publications/d-lite/), [pdf](https://cse-robotics.engr.tamu.edu/dshell/cs625/aaai02b.pdf)
- Koenig, S., Likhachev, M., & Furcy, D. (2004). Lifelong Planning A*. *Artificial Intelligence* 155. [doi](https://doi.org/10.1016/j.artint.2002.12.001)
- Koenig, S., Tovey, C., & Smirnov, Y. (2003). Performance bounds for planning in unknown terrain. *Artificial Intelligence* 147. [doi](https://doi.org/10.1016/S0004-3702(03)00052-3)
- Korf, R. E. (1990). Real-time heuristic search. *Artificial Intelligence* 42. [doi](https://doi.org/10.1016/0004-3702(90)90054-4)
- Kuipers, B. (1978). Modeling spatial knowledge. *Cognitive Science* 2. [doi](https://doi.org/10.1207/s15516709cog0202_3); (2000). The Spatial Semantic Hierarchy. *Artificial Intelligence* 119. [doi](https://doi.org/10.1016/S0004-3702(00)00017-5)
- Montello, D. R. (1998). A new framework for understanding the acquisition of spatial knowledge in large-scale environments. In Egenhofer & Golledge (eds.), *Spatial and Temporal Reasoning in Geographic Information Systems*, Oxford University Press.
- O'Keefe, J., & Nadel, L. (1978). *The Hippocampus as a Cognitive Map.* Oxford. [online](http://www.cognitivemap.net/)
- Orkin, J. (2006). Three states and a plan: the AI of F.E.A.R. GDC. [GDC Vault](https://gdcvault.com/play/1013394/Three-States-and-a-Plan), [slides](https://pages.cs.wisc.edu/~dyer/cs540/handouts/gdc2006_orkin_jeff_fear.pdf)
- Recast & Detour. [repository](https://github.com/recastnavigation/recastnavigation)
- Reynolds, C. (1999). Steering behaviors for autonomous characters. GDC. [page](https://www.red3d.com/cwr/steer/gdc99/)
- Siegel, A. W., & White, S. H. (1975). The development of spatial representations of large-scale environments. *Advances in Child Development and Behavior* 10. [doi](https://doi.org/10.1016/S0065-2407(08)60007-5)
- Stachenfeld, K. L., Botvinick, M. M., & Gershman, S. J. (2017). The hippocampus as a predictive map. *Nature Neuroscience* 20. [doi](https://doi.org/10.1038/nn.4650)
- Stentz, A. (1994). Optimal and efficient path planning for partially-known environments. ICRA. [doi](https://doi.org/10.1109/ROBOT.1994.351061)
- Sturtevant, N., & Buro, M. (2005). Partial pathfinding using map abstraction and refinement. AAAI-05, pp. 1392–1397. [record](https://mlanthology.org/aaai/2005/sturtevant2005aaai-partial)
- Tolman, E. C. (1948). Cognitive maps in rats and men. *Psychological Review* 55(4). [doi](https://doi.org/10.1037/h0061626)
- van den Berg, J., Lin, M., & Manocha, D. (2008). Reciprocal velocity obstacles for real-time multi-agent navigation. ICRA. [doi](https://doi.org/10.1109/ROBOT.2008.4543489)
- van den Berg, J., Guy, S. J., Lin, M., & Manocha, D. (2011). Reciprocal n-body collision avoidance. *Robotics Research*, STAR 70. [doi](https://doi.org/10.1007/978-3-642-19457-3_1)
- Wiener, J. M., Büchner, S. J., & Hölscher, C. (2009). Taxonomy of human wayfinding tasks. *Spatial Cognition & Computation* 9(2). [doi](https://doi.org/10.1080/13875860902906496)
- Yamauchi, B. (1997). A frontier-based approach for autonomous exploration. CIRA'97. [doi](https://doi.org/10.1109/CIRA.1997.613851)
- In this repository: [PATHS.md](PATHS.md), [LIVING_CORE.md](LIVING_CORE.md#steering-locomotion), [PERCEPTION.md](PERCEPTION.md), [COMBAT_MIND.md](COMBAT_MIND.md), [FAST_LANE.md](FAST_LANE.md), [LATENCY.md](LATENCY.md), [TRIALS.md](TRIALS.md); BATTLE_SCALE.md on `origin/battle-diagnosis`.
