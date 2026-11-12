# Stamina, tiredness and focus: a proposal

Written 2026-11-11 on the Spark (branch `design-stamina`, from `origin/main` 601d1f68). This is a design with numbers, not a build: no rule, table or client file is changed. The numbers come from the laws as written. [`living/tools/stamina_numbers.py`](../living/tools/stamina_numbers.py) reproduces every figure below. No world was run.

The owner's play-test complaints:

> "When you walk, it's really slow."
> "The stamina doesn't get replenished, doesn't go up automatically. Or movement skills don't use stamina but use mana. That system is not great."

## 0. Findings

The hypothesis is right, with three corrections.

- **One number, `energy`, does everything.** Being awake drains it, sleep refills it, and it pays for every combat skill: dodge, jump, strike, bow shot and block, and also fire bolt and heal. Awake, its rate is always negative. Only `sleep`, and `rest` at a trickle, give it back. So **a spent dodge comes back only with sleep**. On the island, sitting through an 8 s `rest` returns 0.24 energy, and a dodge costs 4.
- **There is no mana.** No rule, table or seed has one (`grep -w mana`; the only stamina in the code is the mind's conversation stamina in `living/mind/src/mind/talk.rs`). The owner probably read **the energy bar as a mana bar**. It is a thin bar under health, in teal (`theme::EN_LO`/`EN_HI`, 0.15/0.62/0.70 → 0.45/0.88/0.86; `living/game/src/ui/frame.rs:130`), with no label. That is the MMO colour and place for mana. Fire bolt (12) and heal (15) drain it, and so do dodge (4) and jump (2). So "movement skills use mana" is accurate as the owner saw it.
- **Running is free, and only players run.** `human_move(dx, dy, run)` multiplies the walk by `motion(a).run` (1.5) and charges nothing (`living/authority/src/motion.rs:800`). Behaviour graphs and minds never run. `goto`, `follow` and the approach to a target all go at walking pace, `flee` at ×1.15 and `aside` at ×0.8 (`living/authority/src/act.rs:795-809`).
- **The "slow walk" is mostly a hidden penalty, not the base speed.** The base is 2.6 m/s, a brisk walk (a real one is about 1.4). The rules drop it to ×0.6 below 10 energy, and on Cullet to ×0.8 below 35. In play-test 2, strikes and bow shots were refused as "too tired", so energy was under 2, and the owner was walking at **1.56 m/s and running at 2.34**. A look held off the way of travel takes off another 13% (§1.3). Nothing on screen says why.

### Where energy goes today

| | Island (12-min day, `person_pace` 0.3) | Cullet (48-min day, own `rates`) |
|---|---|---|
| Awake | −0.9 a real minute | −1.25 a real minute |
| `rest` (8 s) | +1.8 a minute: **+0.24 a rest** | +1.25 a minute: **+0.17 a rest** |
| `sleep` beside a shelter / rough | +7.8 / +4.8 a minute | +2.5 / +1.25 a minute |
| Holding `block` | −3.6 a minute, plus 1 at the release | −3.6 a minute, plus 1 |
| One use of a skill (`combat_cost`, `skills.rhai:1231`) | strike 2, bowshot 1.5, dodge 4, jump 2, block 1, fire bolt 12, heal 15. Work: gather 1, clear 3, build 4, tend 1, rework 1 | same |
| …in minutes awake | dodge 4.4, fire bolt 13.3, heal 16.7 | dodge 3.2, fire bolt 9.6, heal 12 |
| Spawn 85, idle | < 10 after 83 min | < 35 after 40 min, < 10 after 60 |
| Slower | ×0.6 below 10 (`move_speed`, `skills.rhai:448`) | ×0.8 from 10 to 35 and ×0.6 below 10 (`laws.rhai:86`) |
| At zero | refused: "too tired" (`winded`), "too exhausted to dodge" (< 5), "too tired to jump"; −1 health a game hour × 0.3 (`spent_hp`) | the same refusals; −0.4 health a game hour |

On the island, an hour shaped like play-test 3 (five dodges, five jumps, three fire bolts, a heal, twelve strikes and three guards: 109 energy) reaches 0 inside ten minutes. The character then walks at 1.56 m/s for the rest of the session unless it sleeps.

The client draws what the rules send. `my_vitals` carries `energy` and a per-minute `energy_rate` (`living/authority/src/tables.rs:346`). `live.rs:126` projects `energy + energy_rate × minutes`. While awake that rate is negative, so the bar only ever falls. A slot greys with "Too tired" when `energy < card.cost` (`live.rs:290`).

## 1. Walking and running speeds

### 1.1 Today

The island and Cullet share the person's base: `move_speed` in `living/scripts/skills.rhai:448`, with Cullet's overlay at `living/seeds/worlds/cullet/laws.rhai:86`. The shares come from `motion(a)` (`skills.rhai:139`), which Cullet does not override. `road_speed` is 1.4 (`laws()`), and the bonus applies on `Road` tiles. Cullet's streets, quay and square are `Road` (`settle/plan.rs`). So are Brackenford's streets (`city.rs`).

| m/s | walk | run (×1.5) | flee (×1.15) | on Road: walk / run |
|---|---|---|---|---|
| Rested, both worlds | 2.60 | 3.90 | 2.99 | 3.64 / 5.46 |
| Cullet, energy 10–35 | 2.08 | 3.12 | 2.39 | 2.91 / 4.37 |
| Exhausted (< 10), both | 1.56 | 2.34 | 1.79 | 2.18 / 3.28 |
| Elder ×0.85, child ×0.8, infant ×0.4 | applied to all of the above | | | |

### 1.2 Proposed

- **Walk stays 2.6 m/s.** Every walking time in [Cullet's layout](CULLET_LAYOUT.md#walking-times-and-landmarks) and [SMALL_CITY §2](SMALL_CITY.md#2-size) stays as written. Residents' errands, the clip fit of `walk_brisk` and every trial's timing stay the same.
- **Run rises from ×1.5 to ×1.85, so 4.81 m/s, and costs stamina** (§2): 4 a second, so a full bar runs 25 s, about 120 m. The bar refills 1 s after stopping, at 25 a second (empty to full in 5 s). If the run key is held at empty, the body walks. It runs again once the bar is back at 30.
- **The road's bonus stops at 5.5 m/s** (a new `top` share in `motion`, the same for every kind's run). A walk on a road is 3.64, as today. A run on a road is 5.5, about today's 5.46. Without the cap, a road run would be 6.7 m/s, beyond what any clip can play.
- **The hidden slowdowns become shown, and the island's gets milder.** Exhausted goes from ×0.6 to ×0.8 and caps stamina (§2.4). Cullet's ×0.8 when tired is seed content ("a sleepless night means a slow walk the next day", SMALL_CITY §4), so it stays, but the meter says so (§4). Combat no longer spends tiredness, so a fight cannot push a character into either penalty.

What the owner feels, holding the run key from a full bar (off road / on Road tiles):

| Crossing | walk (today = proposed) | run today (free) | run proposed | on Road: walk | run today | run proposed |
|---|---|---|---|---|---|---|
| Cullet's square, 30 × 14 m (the Counting House yard) | 12 s | 8 s | 6 s | 8 s | 5 s | 5 s |
| …its diagonal, 33 m | 13 s | 8 s | 7 s | 9 s | 6 s | 6 s |
| Brackenford's square, about 60 m | 23 s | 15 s | 12 s | 16 s | 11 s | 11 s |
| Cullet's quay end to end, 150 m | 58 s | 38 s | 32 s | 41 s | 27 s | 28 s |
| Fish Steps to the Crown bench, 227 m | 87 s | 58 s | 50 s | 62 s | 42 s | 43 s |
| Fish Steps to the far Wrack Strand, 315 m | 121 s | 81 s | 71 s | 87 s | 58 s | 60 s |
| Fish Steps to the Lintel, 612 m | 235 s | 157 s | 139 s | 168 s | 112 s | 119 s |

Held over a long trip, the run averages 4.34 m/s off road and 5.10 on a road (run to empty, walk 2.2 s, run 7.5 s). The table's routes are straight-line equivalents of the `cullet_check.py` paths. Stairs and turns add the same time in every column.

On a road, the proposal is about as fast as today and stops being unlimited. Off road (the island's fields, the Wrack, the Moss, the wolves' country) it is 23% faster for 25 s at a time. The main change to the feel is not these numbers. It is that **walking no longer drops to 1.56 m/s after a fight.**

**Owner decision (feel):** if 2.6 m/s still feels slow once the penalty is gone, the next lever is the walk itself. At 3.0, every Cullet walking time shrinks by 13% (the Crown in 76 s, the Lintel in 204 s), and `walk_brisk` would need ×1.48, beyond `max-scale` 1.4: a new take, or the run clip at a walk. I would play-test 2.6 without the penalty first.

### 1.3 The look's bend (for the laptop's question)

`human_face` holds a look. Walking under the movement keys, the body's **travel** turns toward the look, by at most `look_walk_deg` (30°) off the keys' direction (`living/authority/src/motion.rs:487-500`). The heading is the travel, and the speed stays the full `b.speed`. The rules do not strafe.

- **Speed toward where the keys point drops to cos 30° = 0.866:** 2.25 m/s walking and 3.38 running. Half the speed (sin 30°) goes sideways, so the player drifts and has to correct.
- **The rules' turn slowdown never applies here.** `steer::sweep_plan` (`living/rules/src/steer.rs:163`) slows only for heading errors above 0.6 rad (34°), and the bend is at most 30° (0.52 rad).

So yes, the rules' bend does cut forward progress, by up to 13%, and with the exhaustion penalty a walk "toward" something comes to 1.35 m/s. The crossed legs cannot come from the rules, because the rules' body always faces where it goes. They would come from the client drawing the body facing the look while it travels up to 30° off, with a diagonal or strafe take (`walk_diag_*`, `strafe_walk_cross_*`). That is the laptop's measurement. My recommendation for the rules: if the laptop confirms the client draws a strafe, keep the bend. If the owner wants the full speed along the keys, set `look_walk_deg` to 0 in the shipped `laws()`: the body walks where the keys point and only turns its head.

### 1.4 What the clips need

The client picks a gait from each body's actual speed. Walking clips serve up to 2.8 m/s, running clips above (`living/game/src/gait.rs`, docs/GAME_BRIEF.md "Gaits"). Natural speeds (Vivi / Shino) are walk 1.44/1.48, walk_brisk 2.03/2.10, run 3.15/3.25 and run_fast 3.50/3.61. `animate.py --max-scale` is 1.4.

| Speed | Served today by | Proposed |
|---|---|---|
| Walk 2.6 | walk_brisk ×1.24–1.28 | unchanged |
| Road walk 3.64 | the run family (above 2.8) | unchanged |
| Run 4.81 | (3.9 today: run_fast ×1.08–1.11) | run_fast ×1.33–1.37, inside max-scale: rebake with `--target run_fast=4.8`. `run` cannot reach it (×1.5) and keeps serving the 2.8–4 band (flee, tired runs) |
| Road run 5.5 | run_fast ×1.51–1.57 (today's 5.46, already over max-scale) | a new Kimodo `sprint` loop (natural about 5–5.5 m/s) in `living/tools/blender/clips.json`, made on the Spark by `kimodo/spark.sh`, baked with `--target sprint=5.5`. Until then, run_fast over-scaled, as today |
| Directional runs (`run_diag_*`, `strafe_run_*`, `run_back`) | runs ×≈1.2 | at 4.8 they step 1.5–2.4× as often as forward: past `CADENCE_MAX` 1.6 for most. They fall back to the forward run (gait.rs already does this) |
| Wolf run 5.1 (§3) | — | between trot (3.4) and gallop (7.0) in `wolf.py`: the gallop ×0.73 or a canter take. Deer are unchanged |

The look-dev defaults (`--speed 1.4 --run-speed 3.6`) were never the rules' pair. Bake with `--target walk_brisk=2.6 --target run_fast=4.8 --target sprint=5.5`.

## 2. Three pools: stamina, tiredness, focus

### 2.1 The split

| Pool | Field | What it is | Drained by | Returns |
|---|---|---|---|---|
| **Stamina** (short) | new `stamina`, 0..`stamina_max` | Breath and muscle: seconds | running; body skills; holding a guard | by itself, **1 s** after the last drain, at **25 a second** (empty to full in 5 s), walking or standing |
| **Tiredness** (long) | `energy`, 0..100, as today | Being awake: hours | as today: awake, rain, cold, and work skills (gather, build, clear, tend, rework, keep, play, threaten). New: **0.02 per stamina point spent** | sleep, and a little rest, as today |
| **Focus** (non-bodily) | new `focus`, 0..`focus_max` | What a technique such as fire bolt or wound tending draws on | fire bolt, heal | by itself, **2 s** after the last use, at **3 a second** (empty to full in 35 s) |

`energy` keeps its name and meaning, so every graph condition (`{"energy": {"below": 20}}`), desire weight (`tired`, `exhausted`), seeded way, prompt line and mind body word that reads it now means tiredness, as it always did. Hunger, sleep and cold are unchanged. The only change to tiredness is that combat stops paying with it, except the small 0.02 spillover: a full bar of stamina spent costs 2 energy, about two awake minutes on the island. A long fight still wears a body down, by 10–20 over a hard ten minutes, not by 109.

**Reusable mechanics, world words.** The rules name the pools `stamina` and `focus`. What a player and a mind read is the seed's word, from `meters()` (§4). The island and Cullet would say "stamina" and "focus". If the owner wants "mana" on screen, it is one word in a seed's `meters()`, with no code change. [WORLD_VISION](WORLD_VISION.md#core-premise--agreed) keeps compute and AI concepts from being "disguised as mana or magic". Fire is not one of them, but the word is a seed's choice, not the engine's.

### 2.2 Each skill

Costs are paid at the release, as `combat_cost` is today. The check refuses when the pool is below the cost.

| Skill | Pool | Today (energy) | Proposed | Check at too little |
|---|---|---|---|---|
| run (`human_move` run, and `run: true` for graphs and minds, §3) | stamina | free | 4 a second | below 0: the body walks. It runs again at 30 |
| dodge | stamina | 4 (refused below 5) | **20**: five from full, and 1.8 s of rest buys one more | "out of breath" |
| jump | stamina | 2 | **10** | "out of breath" |
| strike | stamina | 2 | 10 | "out of breath" |
| bowshot | stamina | 1.5 | 6 | "out of breath" |
| block | stamina | 1, plus −6 energy a game hour while held | 5 at the release, **4 a second while held**, and no regeneration while it is up | "out of breath"; a guard at 0 drops |
| attack (graph or animal melee) | stamina | 1.5 | 8 | "out of breath" |
| throw (spear) | stamina | 2 | 10 | "out of breath" |
| shoot (graph bow) | stamina | 1 | 6 | "out of breath" |
| threaten | stamina | 0.5 | 3 | "out of breath" |
| **fire bolt** | **focus** | 12 | **30**: three from full, then one every 10 s (cooldown 4 s) | "your focus is spent" (the seed's word) |
| **heal** (combat) | **focus** | 15 | **35** (cooldown 8 s) | "your focus is spent" |
| tend, gather, clear, build, rework, keep, play | tiredness | 0.3–4 | unchanged | unchanged |
| sleep, rest | tiredness | +, as today | unchanged; stamina and focus refill anyway | — |

A one-off fight from full: about 10 strikes, or 5 dodges, or a mix. The bar is back 5 s after the last effort. That matches the owner's "returns by itself within seconds of stopping".

### 2.3 Behaviour at zero

- **Stamina at zero:** body skills are refused with "out of breath". The refusal is an `act_outcome` reason like any other, and the client greys the slot with the same words. A held run becomes a walk. A raised guard drops. Nothing hurts.
- **Focus at zero:** fire bolt and heal are refused with the seed's words. Nothing hurts.
- **Tiredness at zero:** as today, −1 health a game hour × 0.3 on the island and −0.4 on Cullet (`spent_hp`), refusals of work skills, and the minds' "utterly spent".

### 2.4 Interactions (one law, `pools(a)`)

Tiredness caps the short pool, smoothly. The engine asks the law per state, like `rates`, and keeps one answer per state key.

- `stamina_max = 100 × (0.5 + 0.5 × min(1, energy / 35))`: full above 35, 75 at 17.5, 50 at 0. Exhaustion means short bursts. It no longer means a slow walk.
- Exhausted (energy < 10): stamina regeneration is halved (12.5 a second). On the island the walk penalty eases to ×0.8 (from ×0.6). Cullet keeps its own `tired_below` ×0.8.
- `focus_max = 100`. Focus does not depend on tiredness (an owner's call; a world can make it depend in its `pools`).
- Per kind (the `kinds()` table): person stamina 100, wolf 100, deer 120 (deer outlast wolves in a flight). Elders' stamina regenerates ×0.7.
- Stamina and focus are in **real seconds**, never scaled by `person_pace` or the day length. A dodge is the same on every world. Tiredness stays per game hour.

## 3. The same rules for every controller

Today players run and nobody else does. That is a rule difference by controller. The proposal removes it.

- **Graphs:** a `run: true` option on `goto`, `follow` and `flee`, and on the approach of the `closes_in` skills (attack, strike, threaten). Without it, a graph walks. `flee` runs by default while stamina lasts, then flees at ×1.15. The behaviour graph reads `{"stamina": {"below": 30}}` like `energy`.
- **Minds:** the act forms get the same optional `run`, one line in `prompts.rs` beside `goto`. The `moving` law's text tells them running costs breath and is for hurry, flight and fights.
- **Animals:** wolves run (×1.5 = 5.1 m/s) on the approach of a hunt. Deer flee at a run (3.7 × 1.5 = 5.55).

Predictions to check:

1. **Residents do not run everywhere.** The shipped instinct graphs and seeded ways call `goto` without `run`, so their errands are unchanged until a mind asks for it. A mind may ask often. The cost bounds it: a run spends tiredness through the 0.02 spillover, and 25 s at most at a time. Measure the share of minds' `goto` acts with `run: true`. Over 20% outside threats, the prompt line needs work.
2. **A wolf chase becomes a real chase.** From a 5 m gap with a catch at 3.2 m (reach 1.4 + lunge 1.8): today a running player is **never caught** (3.9 against the wolf's 3.4 walk), which contradicts the rules' own text ("you can outrun a person who keeps stopping to swing, not a wolf"). A fleeing resident is caught in 4.4 s. Proposed, both full: the wolf (5.1) catches a running person (4.81) in 6.2 s. Once both are out of breath, walking, 2.3 s. A person escapes by dodging (20), by a head start beyond 10 m, by walls or by fighting.
3. **A fight is paced by breath.** Ten strikes or five dodges, then a few seconds apart. Today a fight is paced by nothing until a character is "too tired" for the rest of the session, as in play-test 2.

Checks (all on the trial stack, `trials.py`):

| Check | What | Cost |
|---|---|---|
| Scripted rules (verify-core) | a body that runs to empty and walks, stamina refusing a dodge, regeneration after the delay, `stamina_max` at energy 17.5, focus refusing a fire bolt, no `energy` spent by a dodge, wolves running on the approach, deer fleeing at a run | free |
| `wolves` and `wolves-valley`, `--fake`, 4 replicates per arm (today / proposed) | the probes `survived`, `hp_min`, `fled_m`, `min_dist`, `skills`, plus new probes: time from attack to first blow, dodges per fight, refusals "out of breath" | free (fake model, 15 min each) |
| `hamlet`, `--fake`, 60 min, 2 arms × 2 | the share of movement at a run by residents, tiredness at bedtime against today (the spillover must not change sleep), and walking times on errands | free |
| A small paid run: `wolves` × 4 per arm on glm-flash | whether minds choose to run, flee or fight differently | about $0.05 a run (b5: 24 runs for $0.96, wolves the dearest), about **$0.40** in all |
| Optional paid: `hamlet` 60 min × 2 arms × 1 | minds' `run: true` share | 12 thinking people × 1 h × $0.10 ≈ $1.20 a run, about **$2.40** |

## 4. What the player sees: `meters()`

Bars and their words come from one `meters()` law and one `status_of`, so the client's bar and the minds' body words share one description (docs/INTERFACE.md §6 "Meters and statuses", built on `rules-senses-outcomes`). Proposed rows. `value` and `max` name `my_vitals` fields, as the install check requires.

```rhai
fn meters() {
    [
        #{ name: "health",  value: "hp",      max: "max_hp",      order: 0, look: "bar" },
        #{ name: "stamina", value: "stamina", max: "stamina_max", order: 1, look: "bar",  word: "stamina", tint: "stamina" },
        #{ name: "focus",   value: "focus",   max: "focus_max",   order: 2, look: "bar",  word: "focus",   tint: "focus", hide_full: true },
        #{ name: "rest",    value: "energy",  max: 100.0,         order: 3, look: "pill", word: "rest" },
    ]
}
```

- **Stamina:** a bar, gold or green, not teal, so it does not read as mana. It sits under health, always visible, as the energy bar is today.
- **Focus:** a bar, the teal of today's energy bar. Shown while not full, or always once the character knows a technique that draws on it.
- **Tiredness (`rest`):** no bar. A status pill with words from `status_of`, at one set of thresholds:

| energy | `status_of` (client pill, tone) | Minds' body words (`felt_body`) |
|---|---|---|
| ≥ 85 | — | "well rested" |
| 50–85 | — | — |
| 35–50 | — | "a little tired" |
| 12–35 | "Tired" (warn); on Cullet "Tired: walking slower" | "tired" (Cullet: "tired; your legs are slow") |
| < 12 | "Exhausted: short of breath" (bad) | "exhausted" |
| 0 | "Spent: it is hurting you" (bad) | "utterly spent" |
| stamina < 20 | "Out of breath" (warn, only in a fight or a run) | "out of breath" (only when it matters to an act) |

A world changes the words in its overlay: Cullet's line above is in `laws.rhai`, not the shipped script.

## 5. For the client

The laptop coordinator's three questions, answered exactly.

**(a) Walk and run speed: law names.**

| | Island (shipped `living/scripts/skills.rhai`) | Cullet (overlay `living/seeds/worlds/cullet/laws.rhai`) |
|---|---|---|
| Walk | `move_speed(a)` (line 448): person 2.6, ×stage (infant 0.4, child 0.8, elder 0.85), ×`a.actor.speed` (genes), ×0.6 when `energy < 10` | `move_speed(a)` (line 86): `base_move_speed(a)` ×0.8 when 10 ≤ `energy` < `tired_below()` (35) |
| Run | `motion(a).run` (line 139): 1.5, a share of the walk | not overridden: 1.5 |
| Flee / aside | `motion(a).flee` 1.15, `.aside` 0.8 | same |
| Road | `laws().road_speed` 1.4 on `Road` tiles (`steer::road_share`, the share of 5 samples ahead) | same |
| Look bend | `laws().look_walk_deg` 30: travel turns up to 30° toward the look at full speed | same |
| Proposed | `motion(a).run` → 1.85; new `motion(a).top` 5.5 (m/s, caps run × road); exhausted ×0.6 → ×0.8; running ends at stamina 0 and resumes at `pools(a).stamina.resume` (30) | inherits the shipped values; keeps its `tired_below` ×0.8 |

The client already compiles the world's script (`ui-decl-1`). It can call `move_speed(a)` and `motion(a)` with the same `a.actor` facts the authority passes (kind, stage, speed, energy). The body's actual speed is in `seen_bodies`' motion segment; the laws only predict it. Under the proposal, a run's speed also depends on stamina. The client predicts the switch from the stamina fields in (b): the body walks from the moment the projected stamina reaches 0.

**(b) Where the pools live.**

All three are columns of the private `vitals` table, read through the caller-scoped `my_vitals` view (`living/authority/src/perception.rs:965`). New columns go at the end of `Vitals` with `#[default(...)]`, as the table already does elsewhere.

| Pool | Columns | Units | Animate between updates |
|---|---|---|---|
| Tiredness | `energy`, `energy_rate` (existing) | 0..100; per real minute, anchored at `at_ms` | as today: `energy + energy_rate × (now − at_ms) / 60000`, clamped to 0..100. Awake it falls; asleep it rises |
| Stamina | **`stamina: f32`, `stamina_max: f32`, `stamina_rate: f32`, `stamina_from_ms: u64`** | points; `stamina_rate` per **second**, signed | `stamina + stamina_rate × max(0, now − max(at_ms, stamina_from_ms)) / 1000`, clamped to 0..`stamina_max`. While draining (running, guarding) the rate is negative and `stamina_from_ms` = `at_ms`. After a drain the rate is the regeneration (+25, or 12.5 exhausted) and `stamina_from_ms` = the last drain + the delay (1000 ms) |
| Focus | **`focus: f32`, `focus_max: f32`, `focus_rate: f32`, `focus_from_ms: u64`** | the same, per second | the same formula; delay 2000 ms, rate +3 |

The rates, delays and maxima come from one law, `pools(a)`: `#{ stamina: #{ max, regen_per_s, delay_ms, run_per_s, guard_per_s, resume, tires_per_point }, focus: #{ max, regen_per_s, delay_ms } }`, asked per state like `rates(a)`. The client does not need the law to animate, because the row carries the rate and the start time. It needs the law only to explain a cost.

When rows are written: one `vitals` update per spend (as `energy` is written today, at the release), at a run's start and stop, at a guard's raise and drop, at stamina 0 during a run (a motion segment ends there exactly, so the speed change and the row agree), and on a tiredness-state change that moves `stamina_max`. Regeneration's start is in the row (`*_from_ms`), so it needs no write. A held run writes 2 rows: start and stop, or start and empty. Only the owner's `my_vitals` subscription receives them. Minds read the authority's own row.

**(c) Dodge and jump costs.**

Yes, they change, and they move off energy. **Dodge: 20 stamina** (today 4 energy, refused below 5). **Jump: 10 stamina** (today 2 energy). Neither touches energy, apart from the 0.02 a point spillover: 0.4 and 0.2.

`skill_card.cost` stays the number, and a new column **`skill_card.pool: String`** (`#[default("stamina")]`) names the pool: `"stamina"` or `"focus"` from a new `combat_pool(skill)` law. The bar greys a slot when the projected value of `card.pool` is below `card.cost`, with the check's words ("Out of breath" or the seed's focus words). Today it compares `energy` with "Too tired" (`live.rs:290`).

## 6. SpacetimeDB data path

Checked against the official docs (2.0 docs; the project pins `spacetimedb = "=2.14.1"`):

- [Automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations): "Adding new columns to the end of a table with a default value" is allowed. Columns without a default, or in the middle, are not, and "non-updated clients will not be aware of the new column". So the eight `vitals` columns and `skill_card.pool` go last, with defaults (stamina 100, max 100, rate 0, from 0; focus the same; pool `"stamina"`). The repository already uses `#[default(...)]` for numbers and `""` (`tables.rs:28-37`, `397`, `1046`). That is the versioned evidence that the attribute works on 2.14.1. Bindings are regenerated with `just living-generate`.
- [Views](https://spacetimedb.com/docs/functions/views/): a view is re-evaluated when its read set changes, and "the key to optimizing a view function is keeping its read set small". `my_vitals` reads one row by primary key, so the new writes re-run one caller's view. No new view and no scan are needed.
- Rows and growth: no new table, and no per-tick writes. Writes come from discrete events (spends, run and guard edges, empty), bounded per character by the `input_hz`/`input_burst` laws for players and by the combat cadence for graphs. The anchored rate avoids per-tick regeneration writes. Retained data: one row per character, unchanged in count.
- The engine's need machinery (`brain.rs` rate keys) is per game hour. Stamina and focus are per real second, with their own anchor, so they do not disturb the need-rate cache. `pools(a)` is memoised per state key, like `senses` and `rates`. Measure its tick cost at 216 characters before calling it accepted.

## 7. Not decided here

- The owner's feel calls: run ×1.85, the walk (2.6 or 3.0), the cost of the dodge, the word "focus" or "mana" on screen, and whether the bend stays.
- Whether minds use `run` sensibly. Only the paid wolves run in §3 says.
- The sprint and canter clips (§1.4) are asset work for the Spark's Kimodo queue and the wolf rig.
- Nothing here is a performance claim.
