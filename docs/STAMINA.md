# Breath, tiredness and focus (stamina-1)

Built 2026-11-11 on the Spark (branch `stamina-1`) from the approved [proposal](STAMINA_PROPOSAL.md) and the general coordinator's decisions. This note says what the rules and the authority do now, where the numbers live, the data path, and where the build departs from the proposal. Evidence is in the branch's verification records (`.agents/skills/verify-*/references/validation/history.md`).

## What changed

- **Three pools.** `stamina` is breath, in real seconds. It pays for running and for every bodily move. `energy` is tiredness, as before, so every graph condition, desire weight and mind body word keeps its meaning. `focus` pays for fire bolt and heal. On screen it is the world's `pool_word("focus")`, `"mana"` in the shipped script.
- **Combat no longer spends tiredness.** A move spends its pool (`combat_pool(skill)`, `combat_cost(skill)`) at its release. Holding a guard no longer appears in `rates`. Each point of breath spent costs 0.02 energy (`stamina_tires`).
- **Too little refuses.** A move with too little breath is refused with "out of breath". A fire bolt or heal with too little focus is refused with "not enough mana" (the world's word). The refusal goes into the same `act_outcome`/`skill_use` path as any other refusal.
- **Running, for every controller.** A run is a steering goal flag (`FLAG_RUN`) for every controller:
  - a player's `human_move(.., run)`;
  - `run: true` on a graph's or a mind's `goto`, `follow` or attack approach;
  - every `flee`, unless it says `run: false`;
  - the approach to a blow by a creature whose `motion` law sets `charge` (wolves).

  A run goes at `motion(a).run` times the walk: a person `run_share`, animals 1.5 (a wolf 5.1 m/s, a deer 5.55). **`run_share` is 1.65**, about 4.3 m/s at the 2.6 walk. The general coordinator set it from the laptop's look-dev: up to about 4.3 m/s the run reads as natural (about 3.1 steps a second); at 4.8 it scurries (3.4). The proposal's 1.85 is kept only as the comparison in the report. It drains `stamina_run` (4) breath a second. When breath runs out, the body walks at the goal's own pace (a flight at 1.15). It runs again once it has `stamina_resume` (30). A run also needs 30 to start.
- **Road cap.** No road takes a body past `motion(a).top` (`run_top`, 4.6 m/s). A body that is faster on its own is not slowed. A wolf (5.1 m/s at `wolf_run` 1.5) is faster than any person running, on a road too. That is intended: a person cannot outrun a wolf.
- **Walk.** The walk is 2.6 m/s from the narrow `walk_base` law, read by the shipped `move_speed` (Cullet's overlay reads it through `base_move_speed`). An exhausted body (energy below 10) walks at `tired_pace` (0.8, was 0.6). Cullet keeps its own ×0.8 below 35.
- **Why a body is slowed.** A `slowed(a)` law gives the words: on the island "exhausted, so you walk slower", on Cullet also "tired, so you walk slower". A mind's scene shows them as `you.slowed`, beside `you.stamina` (and the focus pool under the world's word while it is not full). The mind's felt body adds "out of breath" below 20 breath.
- **Graphs.** A `{"stamina": {"below": 30}}` condition reads breath, like `energy`.
- **Unchanged.** `look_walk_deg` is untouched (dev-box's look-2 owns it).

## Merge note: law values, old → new

Every law this branch adds or changes, with the value on main before it (or "new") and after it. A world reverts any **law** by name on a running world: `set_world_law("<name>", "<value>")`. Some rows say "not a law". Those are a function or a number inside `pools(a)`/`motion(a)`, and a world changes them with a script overlay (a seed's `laws_file`), not `set_world_law`.

| Law | Old (main) | New | Units, notes |
|---|---|---|---|
| `run_share` | new (a person's run was `motion(a).run` 1.5) | 1.65 | share of the walk; 1.5 restores the old run speed (the run now costs breath either way) |
| `run_top` | new (no cap) | 4.6 | m/s; the fastest a road takes a body (a body faster on its own keeps its speed); 50 is effectively no cap |
| `walk_base` | new (2.6 hard-coded in `move_speed`) | 2.6 | m/s, a grown person's walk; Settings choices 3.0 and 3.4 |
| `tired_pace` | new (×0.6 hard-coded) | 0.8 | share of the walk below energy 10 (island); 0.6 restores it. Cullet's ×0.8 below 35 is unchanged (its overlay) |
| `wolf_run` | new (1.5, shared by all animals) | 1.5 | share of a wolf's walk (3.4 m/s → 5.1) |
| `deer_run` | new (1.5) | 1.5 | share of a deer's walk (3.7 → 5.55) |
| `charge` | new | true for wolves | **not a law**: a `motion(a)` field (a wolf's approach to a blow runs) |
| `slowed` / `slow_words` | new | "exhausted, so you walk slower" (Cullet: also "tired, …") | **not a law**: words, a script function |
| run start / resume | new | 30 | breath; `stamina_resume` (a run starts, or starts again after running out, with at least this) |
| `stamina_max` | new | 100 | breath points (deer ×1.2: **not a law**, in `pools(a)`) |
| `stamina_regen` | new | 25 | breath a second (elders ×0.7, exhausted ×0.5: **not laws**, in `pools(a)`) |
| `stamina_delay_s` | new | 1 | s after the last spend before the refill starts |
| `stamina_run` | new (running was free) | 4 | breath a second while running; 0 makes running free again |
| `stamina_guard` | new (a held guard took energy: −6 a game hour × 0.3) | 4 | breath a second while a guard is held |
| `stamina_tires` | new | 0.02 | energy per point of breath spent |
| tiredness cap | new | full from energy 35, 50% at 0 | **not a law**: `rested_at` and `spent_share` in `pools(a)` |
| `focus_max` | new | 100 | focus points (shown as "Mana") |
| `focus_regen` | new | 3 | focus a second |
| `focus_delay_s` | new | 2 | s after the last use |
| `cost_strike` | 2 energy | 20 | breath |
| `cost_bowshot` | 1.5 energy | 6 | breath |
| `cost_dodge` | 4 energy (refused below 5) | 20 | breath |
| `cost_jump` | 2 energy | 10 | breath |
| `cost_block` | 1 energy (+ the held drain above) | 5 | breath, at the release |
| `cost_attack` | 1.5 energy | 20 | breath (a graph's or an animal's blow, a wolf's bite) |
| `cost_throw` | 2 energy | 10 | breath |
| `cost_shoot` | 1 energy | 6 | breath |
| `cost_threaten` | 0.5 energy | 3 | breath |
| `cost_firebolt` | 12 energy | 30 | focus |
| `cost_heal` | 15 energy | 35 | focus |
| `dmg_strike` | 10 | 5 | health, before strength, skill and armor |
| `dmg_strike_spear` | 15 | 8 | health |
| `dmg_spear` | 18 | 9 | health (a person's attack with a spear) |
| `dmg_bowshot` | 14 | 7 | health |
| `dmg_firebolt` | 24 | 12 | health |
| `dmg_throw` | 24 | 12 | health |
| `dmg_shoot` | 16 | 8 | health |
| `blow_person` | 7 | 4 | health, a bare blow |
| `blow_wolf` | 13 | 7 | health, a wolf's bite |
| `blow_deer` | 4 | 2 | health |
| `hp_person` | 100 (in `kinds()`) | 100 | health; read when a body comes into the world |
| `hp_wolf` | 55 | 80 | health; living wolves keep their `max_hp` until they die |
| `hp_deer` | 40 | 22 | health; the same |

- **Costs are no longer energy.** Old costs were energy. The new ones are breath (or focus), and combat no longer spends energy except the `stamina_tires` spillover. So setting a cost back to its old number restores the number, not the energy cost.
- **Unchanged.** `look_walk_deg` is untouched (look-2 owns it).

## Every number is a world law

`laws()` holds these, so `set_world_law` changes them on a running world (each has its words in `laws_about`):

| Group | Laws (shipped value) |
|---|---|
| Moving | `walk_base` 2.6 (Settings: 3.0, 3.4), `run_share` 1.65, `wolf_run` 1.5, `deer_run` 1.5, `run_top` 4.6, `tired_pace` 0.8 |
| Breath | `stamina_max` 100, `stamina_regen` 25, `stamina_delay_s` 1, `stamina_run` 4, `stamina_guard` 4, `stamina_resume` 30, `stamina_tires` 0.02 |
| Focus | `focus_max` 100, `focus_regen` 3, `focus_delay_s` 2 |
| Costs | `cost_strike` 20, `cost_bowshot` 6, `cost_dodge` 20, `cost_jump` 10, `cost_block` 5, `cost_attack` 20, `cost_throw` 10, `cost_shoot` 6, `cost_threaten` 3 (breath); `cost_firebolt` 30, `cost_heal` 35 (focus) |
| Health | `hp_person` 100, `hp_wolf` 80, `hp_deer` 22 (read when a body comes into the world: a living body keeps its `max_hp`) |
| Blows | `blow_person` 4, `blow_wolf` 7, `blow_deer` 2 (a bare blow by kind); `dmg_strike` 5, `dmg_strike_spear` 8, `dmg_spear` 9, `dmg_bowshot` 7, `dmg_firebolt` 12, `dmg_throw` 12, `dmg_shoot` 8 (before strength, skill and armor) |

A client Settings switch for the walk is `set_world_law("walk_base", "3.0")`.

`pools(a)` turns these into each creature's pools. It is a hot law kept per state, and it reads only kind and stage. It gives:

- elders 0.7 of the refill;
- deer 120 breath;
- the tiredness cap: full from energy 35, half at 0 (`rested_at`, `spent_share`);
- half the refill below energy 10 (`exhausted_below`, `exhausted_regen`).

The engine finishes the cap and the refill for each body's own energy (`living_rules::pools::PoolLaw::cap`, `regen`), as it finishes `rates`.

A guard lasts at most as long as its breath (`block_duration`): (breath − its cost) / `stamina_guard`. So it drops when breath runs out, without a per-tick check.

### Measured (2026-11-12, branch head with look-2 merged)

Graph-driven 1v1s (`scenes.py fights`, 5 of each) and chases (`scenes.py chase`, 4 of each) ran on fresh default-seed worlds on the Spark's trial server. A fight runs from the first blow to the first flight or a death. "Main" is a world built from main (4b76ef41) with the old values and no breath.

**Fights** (length in seconds: median and range; exchanges are blows made by both sides, median):

| | Main (old values) | Run 1.65, shipped | Run 1.85, comparison |
|---|---|---|---|
| Person v person, dodging | 8.4 s (6.6–11.5), 20 | 27.0 s (22.8–36.3), 33 | 25.2 s (20.7–35.4), 30 |
| Person v person, trading blows | 5.4 s (1.9–6.6), 14 | 23.3 s (17.7–23.7), 32 | 22.1 s (14.4–90.2*), 30 |
| Person v bold wolf | 5.9 s (3.2–7.2), 12 | 15.0 s (14.4–18.3), 20 | 16.3 s (15.2–17.7), 22 |

\* One timed out at 90 s.

How the fights ended:

- **Person v person.** Every one ended in a flight, and most fleers were caught. None ended in a yield (the graphs have none).
- **Person v wolf.** The person fled first in 9 of 10, and the wolf in 1 of 10.
- **The facing limit.** The look-2 facing limit changed none of these beyond the run-to-run spread: before the merge, the same worlds at 1.85 measured 25.1 / 21.8 / 16.2 s.

**A bold wolf charges a person 5 m away who goes straight off.** The table gives the time to close to the wolf's catch distance (3.2 m), and how many of the chases got there:

| Fleeing person | Main (wolf walks 3.4) | Run 1.65 | Run 1.85 |
|---|---|---|---|
| Running | 2.75 s (2.2–3.4), 4/4 caught (main has no run: it walks) | 4.95 s (3.9–6.1), 4/4 | 10.0 s (3.6–12.0), 3/4 |
| Walking | 4.7 s (2.1–8.0), 4/4 | 0.9 s (0.3–1.5), 4/4 | 1.35 s (0.6–1.9), 4/4 |

The arithmetic above gives 2.2 s at 1.65 and 6.2 s at 1.85. The measured chases are slower: a pursuer slows within its slow radius of the target, and genes spread the speeds.

**The bite, after `fix-pursuit-speed` (2026-11-12).** Closing to 3.2 m was not the bite. The approach to strike slowed within its slow radius (1.2 m) of its keep (1.15 m, the attack's reach 1.4 less 0.25) down to the target's own speed, so a wolf held about 1.6–1.8 m behind a walker it had caught up with and never came within the 1.45 m at which a blow starts. It bit only when the prey slowed to stop at the end of its walk. Now a pursuit, for every controller, keeps at least the speed its target draws away at, plus 0.3 m/s (`motion.rs` `toward`). `scenes.py chase` with a fresh wolf each chase (unhurt, full breath) and prey going 55 m straight away; the first blow's start, from the pursuer's `skill_use` (Spark, trial service, default seed, `run_share` 1.65):

| Pursuer against | Before: first blow | After: first blow |
|---|---|---|
| Wolf, walker | 2 of 9 within 55 m, 19.0–19.4 s, both as the prey slowed at its end | 11 of 11, median 1.9 s (1.3–2.6) |
| Wolf, runner (1.65, while breath lasts, then walking) | 3 of 5, median 13.4 s (13.2–14.2), all as the prey slowed at its end | 5 of 5, median 4.4 s (4.1–4.6) |
| Person (`attack`, `run: true`), walker | 1 of 5, 24.2 s, at the end | 5 of 5, median 2.9 s (2.7–3.6) |
| Person (`attack`, `run: true`), runner | 2 of 5, 14.1 and 14.4 s, at the end | 2 of 5, 7.2 and 10.8 s; 3 never caught, slower than their runner |

The time to close to 3.2 m did not change: a wolf there in 0.2–1.3 s, a walker or a runner alike, before and after. So a wolf that has caught up with a walker now bites within about 2 s instead of trailing it, and a runner within about 4.5 s. A person who attacks catches a walker in about 3 s, while a runner with breath stays ahead of an equal runner. Fight-length tuning (`scenes.py fights`) was measured with the old approach; fights from a standing start are not affected, chases are.

- **At 1.65.** A running person lasts about 5 s from a 5 m start, five times longer than a walker (0.9 s) and close to the proposal's 6 s. The coordinator kept the wolf at 5.1 m/s: no one outruns a wolf, even on a road. So no wolf change is proposed.
- **Pairing.** `wolf_run` 1.35 at 1.65 was also measured: 2 of 4 caught, 8.3 s median. It is there if the owner wants it.

**Fake trials** (`trials.py run --fake`; no model calls):

- **`wolves`** (4 × 8 min after the merge, 4 × 7 min on main):
  - Every subject survived on both.
  - **After:** the wolves attacked at 4.1–5.3 m/s (main: 3.5–3.7), and subjects fled at 3.2–4.5 m/s (main: 2.9–3.1). They took 0–1 blows (lowest health 88–100) and came within 0.6–2.1 m.
- **`hamlet`** (4 × 12 min at run 1.85, before the merge):
  - Residents ran in at most 0.3% of their moving samples; one resident ever ran (main: 0).
  - No one runs everywhere: the shipped graphs and seeded ways never ask to run.

### After the merge (2026-11-12, main 12d96e66 against its first parent 9e8d372f)

- **Hamlet at run 1.65** (`trials.py run --fake`, 4 × 12 min, batch `st1ham`):
  - Residents ran in 0.0–0.2% of their moving samples (a moving body faster than 3.95 m/s or draining breath, sampled every 2 s).
  - One resident in one replicate ran, while storing; it may have been a fast road walk. The median moving speed was 2.33–2.46 m/s.
  - No one runs everywhere.
- **Ecology** (`stage1-acts`: 16 deer, 3 wolves, compressed lives, 12-minute day; no mind service, instinct graphs; 2 worlds per arm, 62 min, 5.2 game days; sampled every minute):

| World | Wolves (start → range → end) | Deer (start → peak → low → end) | Deer deaths: starved / killed / old age |
|---|---|---|---|
| main, 1 | 3 → 2–12 → 12 | 16 → 98 → 14 → 39 | 84 / 9 / 9 |
| main, 2 | 3 → 3–8 → 6 | 16 → 89 → 15 → 32 | 72 / 6 / 10 |
| pre-merge, 1 | 3 → 3–10 → 10 | 16 → 95 → 18 → 24 | 66 / 9 / 16 |
| pre-merge, 2 | 3 → 3–7 → 6 | 16 → 99 → 18 → 22 | 73 / 6 / 15 |

**Ecology result.** Both arms follow the same course: deer boom to about 90–99 by day 2.5, starve back to 14–18 by day 4, and recover. That boom and starvation is the seed's own (compressed lives, finite grass), on main and before it alike. The wolves' run, the halved bite and the new deer and wolf health moved neither population outside the pre-merge spread; one main world ended with 12 wolves against the pre-merge 10. Neither population collapsed or exploded because of this change, and no value was changed.

## Wolves on people and deer, before and after `fix-pursuit-speed` (ecology check, 2026-11-12)

The bite came about 10× sooner after `fix-pursuit-speed` (4b3dc2b3; the table above). This checks what that does to a world over two full nights. **Builds:** main's first parent before the merge (`f5ebdcba`) against main with it (`4b3dc2b3`). Their rules side differs by the one condition in `motion.rs` `toward`, so "before" is this tree with that line put back, as for the chase worlds. **Worlds:** fresh, each from its seed, starting at 07:00 (every world does), run 48 game hours (two full nights, 20:00–06:00), on the Spark's trial server. **Minds:** none (no mind service, no model): every character lives by its instinct graph, which flees no better than a fake mind would, and worse than a real one. The comparison between builds is fair; the absolute rates are not what minds would live. **Measured** with `living/tools/wolf_ecology.py` every 2 s:

- an attack episode: one wolf on one person, a new episode after 20 s without a blow begun;
- the victim's state when the episode began, or at its last sample before a death: a child (stage 0–1), badly hurt (under half its health), asleep away from a fire (sleeping, no campfire, house, hall, inn, shelter or hearth within 4 m), alone at night (no other person within 10 m).

**The hamlet and Cullet as shipped have no wolves** (`hamlet.json`, `hamlet-6.json` and `cullet.json`: deer 0, wolf 0), so wolves cannot touch their people under either build. The shipped world with wolves is the island (24 deer, two packs: 5 by the deer meadows and a bold pack of 4 in the low hills, 370–800 m from the arrival point, 40 m off the road). So the check ran the island as shipped, and the hamlet and Cullet each with 16 deer and wolves added for this check: the hamlet with a bold pack of 4 in the island's own pack form; Cullet with 4 ordinary wolves (the pack form found no spot on Cullet's treeless island). The two overlays are in the runs' evidence, not in `living/seeds`.

| World (runs per build) | Resident-hours | Attack episodes per 1,000 resident-h (night) | People killed by wolves, per 1,000 resident-h | Killed: child / badly hurt / asleep, no fire / alone at night | Deer killed per 100 wolf-h | Wolves: start → end; starved |
|---|---|---|---|---|---|---|
| Island, before (2) | 26,483 | 0.15 (2 of 4 at night) | 0 (0 people) | – | 1.05 (9) | 9 → 9; 0 |
| Island, after (2) | 26,462 | 0.04 (1, by day) | 0 (0 people) | – | 0.93 (8) | 9 → 9; 0 |
| Hamlet + bold pack, before (4) | 1,749 | 62 (0 at night) | 7.4 (13 of 48 residents; per run 2, 3, 4, 4) | 2 / 13 / 0 / 0 | 0.54 (6) | 4 → 6–10; 0 |
| Hamlet + bold pack, after (4) | 1,535 | 50 (4 at night) | 11.7 (18 of 48; per run 5, 3, 5, 5) | 3 / 18 / 1 / 1 | 1.05 (12) | 4 → 4–14; 0 |
| Cullet + 4 wolves, before (2) | 6,138 | 0 | 0 | – | 0.90 (4) | 4 → 6; 0 |
| Cullet + 4 wolves, after (2) | 6,137 | 0 | 0 | – | 1.00 (4) | 4 → 4–5; 0 |

- **The island.** One to two attack episodes per 48 hours among 277 people, none deadly, before and after. Its bold pack lives far from the arrival point and off the road. Deer 24 → 20–22, wolves 9 throughout in both.
- **The hamlet with a bold pack.** The one world where wolves live beside people. The pack reaches the village at once: under either build 2–5 of the 12 residents die by wolves within the first 12–18 game hours, all of them badly hurt when they died (worn down over several episodes), and none die after that (the deer, booming from 16 to 160–256 under the hamlet's fast life pace, feed the pack). After the change there are fewer episodes (76 against 109) but each is twice as deadly (0.24 deaths an episode against 0.12): a wolf now keeps its bite on a person walking away. Deaths rise by about 1.6× (13 → 18 of 48 residents over four runs each). The wolves died only of old age, none starved.
- **Cullet with wolves.** Its four ordinary (not bold) wolves never went for any of its 64 residents under either build. Deer killed per wolf-hour about the same.
- **Deer.** Deer killed per wolf-hour does not move on the island or in Cullet (1.05 → 0.93, 0.90 → 1.00); in the hamlet it doubles on small counts (6 → 12 over four runs), with the deer booming either way.

**Verdict.** In the shipped worlds people killed by wolves do not rise: none die on the island under either build, and the hamlet and Cullet have no wolves. Where a bold pack lives beside a village (the hamlet with one added), deaths rise by about 1.6×, on a baseline that is already harsh under instincts: a bold pack kills a quarter to two-fifths of a 12-person hamlet in its first half day, before and after. Real minds, which flee, call for help and avoid the wolves' ground, should do better than instincts in both builds.

**Fights after the change** (`scenes.py fights`, fresh default-seed worlds, 5 of each, then 8 more person-against-wolf; median and range of fights that started):

| | The table above ("Run 1.65, shipped") | Before (`f5ebdcba`) | After (`4b3dc2b3`) |
|---|---|---|---|
| Person v person, dodging | 27.0 s (22.8–36.3) | 44.0 s (27.5–90.9), one timed out | 34.2 s (25.2–48.1) |
| Person v person, trading blows | 23.3 s (17.7–23.7) | 23.1 s (15.8–25.7) | 22.0 s (16.2–26.7) |
| Person v bold wolf | 15.0 s (14.4–18.3) | 23.6 s (19.3–26.3), 11 fights | 27.5 s (18.1–90.6), 9 fights, 2 timed out |

- **Trading blows.** Unchanged by the fix.
- **Dodging.** Within the spread on both builds.
- **The wolf fights.** Run about 24 s on both builds, longer than the table's 15 s: the table no longer holds for them, and not because of this change. It was measured on an older main.
- **The two "after" timeouts.** Each came after a dodge that left the person where something on the default map blocked sight: both sides then stood "no #N in sight" for the rest of the 90 s. Placed at those same spots on the "before" build, a person and a wolf do the same, so they are this scene's geometry.
- **Fights that never started.** Two before and four after (0 blows in the window).

## Whether a body runs: `body.running`

A client should draw the gait the rules move, not infer it from speed. A Settings walk of 3.0 or 3.4 m/s (`walk_base`) would otherwise read as a run.

- **`body.running` (bool).** True while a run is under way with breath, for every controller:
  - a player's run key;
  - a graph's or a mind's `run`;
  - every flight;
  - a wolf's charge.

  It is false walking, out of breath, standing, dashing, and on a road walk however fast. The steering update sets it from the run's drain (`FLAG_DRAIN`). A halt, a glide to a stand, a stop and a placement clear it. It changes only where the motion row is written anyway.
- **Where clients get it.** It is appended to `body` and to `motion_seen` (where look-2 appended the facing; `motion` keeps its stored type) and returned in `Moving`. So `seen_bodies` and `my_body` carry it as `running`.
- **Schema.** `motion_seen.motion` is an embedded product type, and changing it in place would be a column type change, so it stays as it was. Both new columns are appended with `#[default(false)]`, the automatic migration's rule for an added column. A bool adds 1 byte to `body`.

Proved in place on 2026-11-12:

1. A world from the merged main (23771d59) was published fresh: 264 bodies, 182 people.
2. It ticked, then this branch's module was published over it with its data kept (`verify.py launch --keep-data`).
3. Every vitals row was kept, the new columns took their defaults, the world ticked on, `skill_card` had its pools, and `body.running` was set on 3 bodies within seconds.

Evidence: `.local/living/verify/core-st1mig/`.

## What a player and a mind read: meters and statuses

The meters law from `rules-senses-outcomes` describes the bars, and `status_of` gives the words for the screen and the minds (one set of thresholds):

- `meters()`:
  - health;
  - `stamina` (bar, always);
  - `focus`, labelled with the world's `pool_word("focus")` ("Mana") and shown always (it had `while_short: true`, shown only while not full, until meters-always on 2026-11-12, after the owner's play-test 6 asked "why not always visible ?"; the `while_short` meter key stays for worlds that want it);
  - `energy` and `hunger` as `shown: false`. Tiredness is now pills ("Tired", "Exhausted", "Spent", from `energy_status`), not a bar.
- `status_of` adds two statuses:
  - `out_of_breath` ("Out of breath", felt "out of breath") below 20 breath;
  - `slowed` ("Walking slower", felt "walking slower") whenever `slow_words(kind, energy)` says the walk is slower: exhausted on the island, also tired (10–35) on Cullet. `slowed(a)` gives the same words to a mind's scene (`you.slowed`).
- `BodyFacts` treats a field with a `<field>_from_ms` as a pool: its rate is a second's, from the later of `at_ms` and that time. So the client's pills and the minds' words project breath as the authority does.
- `Vitals::FIELDS`/`fields()` and the rules' `SHIPPED_VITALS` carry the eight pool columns.

## Fight length

Fights between equals should last tens of seconds, enough exchanges for a character to learn within one. Every blow still does its full damage; only law values moved. Measured with `scenes.py fights` (graph-driven 1v1s, the same graphs on any module; a fight runs from the first blow to a death or the first flight) and `scenes.py chase` (a bold wolf charges a person 5 m away). The numbers are in the branch's report and in the verify-core validation record.

**What moved:**

| Law | Before | Now |
|---|---|---|
| `dmg_strike` | 10 | 5 |
| `dmg_strike_spear` | 15 | 8 |
| `dmg_spear` | 18 | 9 |
| `dmg_bowshot` | 14 | 7 |
| `dmg_firebolt` | 24 | 12 |
| `dmg_throw` | 24 | 12 |
| `dmg_shoot` | 16 | 8 |
| `blow_person` | 7 | 4 |
| `blow_wolf` | 13 | 7 |
| `blow_deer` | 4 | 2 |
| `hp_wolf` | 55 | 80 |
| `hp_deer` | 40 | 22 (a wolf still kills a deer in 4 bites) |
| `cost_strike` | 10 | 20 |
| `cost_attack` | 8 | 20 |

`hp_person` stays 100, so starving, cold and healing keep their timings.

**Why these numbers.**

- **The blows.** Before, a person brought another to its 20% flight point in about 8 strikes, in about 5 s. Halving every blow doubles the blows a fight needs.
- **The costs.** Doubling `cost_strike` and `cost_attack` to 20 lets breath pace them. Five blows come from a full bar. After that, one blow comes every 1.8 s: the refill waits a second after each spend, then gives 25 a second.
- **The wolf.** A wolf at 80 health takes about 13 of the new strikes. A person at 100 takes about 12 of the new bites, so person and wolf are equals.

**The run and the wolf, paired.**

- **The arithmetic.** A chase from a 5 m gap ends when the wolf is within its reach and lunge (3.2 m). With both running, that takes 1.8 m / (wolf speed − runner speed) while both have breath (25 s at 4 a second).
- **At `run_share` 1.85.** A runner goes 4.81 m/s against the wolf's 5.1 (`wolf_run` 1.5): caught in about 6 s. The proposal's §3 says the same.
- **At 1.65.** A runner goes 4.29: caught in about 2.2 s. A walker fleeing at 1.15 (2.99 m/s) is caught in about 0.9 s.
- **Keeping the catch with a lower run.** A lower run keeps a 6 s catch only if `wolf_run` comes down with it. At 1.65 that is `wolf_run` 1.35, 4.59 m/s. `wolf_run` and `deer_run` are their own laws for that reason.
- **Measured.** The measured chases (the report) are noisier. A flight ends `flee_clear` farther away, and at night a wolf loses its prey beyond its sight.

## Data path (SpacetimeDB 2.14.1)

| Change | Rows written | When | Who receives it |
|---|---|---|---|
| `vitals` + 8 columns: `stamina`, `stamina_max`, `stamina_rate`, `stamina_from_ms`, and the same four for `focus` | the body's one `vitals` row (by primary key) | a spend; a run's or guard's drain starting or stopping; a run running out of breath or running again; any write that already re-anchors the needs (`common::settle`) | the owner's `my_vitals` view (one row read by key); the mind service as database owner |
| `skill_card.pool` | one row per combat skill | at a script install, as before | every client (public, static) |
| `steer.pace`, `steer.run_pace` | the body's `steer` row (private) | when a goal starts, as before | no one (private) |

- **No per-tick writes.** The refill is the row's rate from `*_from_ms`, and readers project it. While a run lasts, the steering update is due no later than the moment breath runs out (`living_rules::pools::reaches`). While a winded run walks, the update is due when breath reaches the resume level (`refilled`). So the speed change and the row agree to the update, with no polling.
- **A held run writes 2 rows:** its start, and its stop or its empty. A held guard writes 2: raise and drop.
- **No new table, no new index, no scan.** Every read and write is by primary key on rows the path already touched (`vitals`, `steer`, `body`).
- **Retained data.** One row per character, as before. Nothing grows.
- **Not measured.** The cost of `pools(a)` per steering update of a running body (one per-state lookup when cached) and of the extra `vitals` writes has not been measured at 216 characters. No performance claim is made.

### SpacetimeDB documentation check

Pages read on 2026-11-11 (the site shows version 2.0.0; the repository pins `spacetimedb = "=2.14.1"`, and the trial server and the bindings image are `clockworklabs/spacetime:v2.14.1`):

- [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations).
  - Allowed: "Adding new columns to the end of a table with a default value."
  - Not allowed: "Adding columns without a default value", "Adding columns in the middle of a table".
  - "Non-updated clients will not be aware of the new column."

  So every new column is the last of its table, with a default.
- [Default values](https://spacetimedb.com/docs/tables/default-values).
  - `#[default(value)]` takes a const-evaluable expression, a string literal included (`#[default("")] bio: String`).
  - On migration, "existing rows are automatically populated with that default".

  The defaults: breath and focus full (100, cap 100), no rate (0), no start (0), and `pool` `"stamina"`. A migrated body therefore starts rested and full. Its first write sets its real cap (deer 120, or the tiredness cap). The versioned evidence that the attribute works on 2.14.1 is the repository's existing `#[default(..)]` columns (`steer.look_on`, `skill_card.needs`).
- [Views](https://spacetimedb.com/docs/functions/views/).
  - A view is re-evaluated when its read set changes, and "the key to optimizing a view function is keeping its read set small".
  - `my_vitals` reads the caller's one row by key, so one spend re-runs one caller's view.
- [Table performance](https://spacetimedb.com/docs/tables/performance/). It recommends indexed lookups and splitting hot and cold data, and warns about unbounded growth. The pools added no column to a hot public table.
- The bindings were regenerated with `spacetime generate` in a throwaway `clockworklabs/spacetime:v2.14.1` container. Only `vitals_type.rs`, `skill_card_type.rs` and `steer_type.rs` changed.

## Departures from the proposal

- **The numbers are world laws in `laws()`.** The proposal had literals in `pools(a)` and `combat_cost`; the coordinator's "every number is a law value" puts them in `laws()`. `pools(a)` still gives the structure the proposal named, with the caps' shape in the law.
- **`charge`.** A new `motion(a)` field. A wolf's approach to a blow runs without a graph saying so: the wolves trial's own pack graph and the instinct graphs stay unchanged. A graph's `run: false` keeps a walk.
- **`slowed(a)`.** A new law for the words of a slowdown, shared by the minds' scene (`you.slowed`) and, once `meters()`/`status_of` land from `rules-senses-outcomes`, the player's status pill. Until then the client has no status words for it.
- **A run needs 30 breath to start, not only to resume.** Tapping the run key can't restart a run from an empty bar.
- **`stamina_max` in the row is the cap as of `at_ms`.** It follows tiredness at each write, about 1.3 a real minute at most, not continuously. The authority's own checks use the row's cap.
- **The screen word for focus is `pool_word("focus")`, "mana".** A `meters()` row will read that word when it lands. The refusal says "not enough mana", not "your focus is spent", because the pool can be short without being empty.
- **Blocks:** a guard's length is set when it starts, from the breath then, instead of a tick-time drop.
- **A dash is checked.** A dodge or jump with too little breath is refused. Before this branch a dash never ran its check, so main's "too exhausted to dodge" never fired.
- **Health, blows, and wolf and deer runs are world laws.** The fight-length values above moved, and `wolf_run`/`deer_run` were added so the run can be paired with the wolf's.
