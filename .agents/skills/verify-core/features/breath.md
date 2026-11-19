# Breath, tiredness and focus

Since `stamina-1` (2026-11-11, [docs/STAMINA.md](../../../../docs/STAMINA.md)) a body has three pools. Breath (`stamina`, real seconds) pays for running and bodily moves. Tiredness (`energy`) is unchanged. `focus` pays for fire bolt and heal; its screen word is `pool_word("focus")`, "mana". They live on the `vitals` row: a value at `at_ms`, a cap, a signed rate a second, and the rate's start `*_from_ms`. The row is written at a spend and at a drain's edges, never per tick.

## Checks

- **Rules (Cargo, `living-rules`):**
  - `moves_cost_breath_or_focus_and_too_little_refuses_them`:
    - every cost and its pool;
    - "out of breath" for dodge, jump, guard and a wolf's bite;
    - "not enough mana" for a fire bolt;
    - a guard as long as its breath;
    - a guard's rates being an awake body's.
  - `the_pools_law_gives_breath_and_focus_in_real_seconds`:
    - the law's numbers, deer 120 and elders 0.7;
    - the tiredness cap (50 at energy 0, 75 at 17.5) and the halved refill below 10;
    - the law kept per kind and stage;
    - world laws changed with `with_world_laws`.
  - `the_walk_is_the_walk_base_law_and_a_slowed_body_says_why`:
    - 2.6 m/s from `walk_base`, and ×0.8 exhausted on the island;
    - Cullet's ×0.8 below 35, with the `slowed` words;
    - `walk_base` 3.0 on both worlds;
    - the run at the `run_share` law times the walk, capped at `run_top` on a road, and 1.65 when the law is set to it.
  - `pools::tests` (level, refill after the delay, run out, resume at 2.2 s).
  - `steer::tests::a_road_speeds_a_run_only_up_to_the_top_speed`.
  - `moves_are_a_law_per_creature` (the `run_share` law for people, 1.5 and `charge` for wolves, `top` the `run_top` law).
- **Live, `scenes.py stamina` on a default-seed run (about 2 min):**
  - **The run.** A person's run is the `run_share` law times its walk (`body.speed`; the scene reads the law in force). The row's rate is −`stamina_run` from its anchor. The scene sets `stamina_run` to 14 with `set_world_law`, so a 64 m line holds a run to empty and a second run, even for a fast runner.
    - Out of breath, it walks, and the row says the refill starts at `at_ms + 1000`.
    - It runs again about 2.2 s later, at 30.
    - The row has at most 8 distinct `at_ms` over the whole run.
  - **The refill and tiredness.**
    - Standing, the row is identical 3 s apart while the projected breath rises.
    - Breath spent costs about 0.02 energy a point.
  - **A dodge** takes 20, from a second later, and almost no energy.
  - **Too little breath.** With `stamina_max` 15 a new body has 15. Its dodge is refused "out of breath" (its `experience`). Its jump goes and takes 10.
  - **The tiredness cap.** `spawn_energy` 17.5 gives a new body 75 breath.
  - **Mana.** Three or four fire bolts 4.2 s apart go (the refill between them decides), then one is refused "not enough mana". Focus is under 30, refilling at 3.
  - **A guard.** A 3 s guard drains 4 a second. It drops and takes 12 + 5, refilling a second later.
  - **The walk law.** `walk_base` 3.0 walks 3.0/2.6 as fast.
  - **Animals.** A wolf's attack approach runs at 1.5 times its walk (`charge`). A deer flees at a run.
  - Every law is set back at the end.
- **`scenes.py moves`:** a flight with `run: false` is 1.15 times the walk. A flight by default runs at `run_share` times the walk.

## Fight length and the chase

- `scenes.py fights` (default seed, about 15 min). Graph-driven 1v1s, the same graphs on any module, so a world built from main measures the before.
  - **Three types.**
    - `pp-dodge`: each person strikes the other, dodges a windup at 0.15 a graph look, and flees below 20% of its health.
    - `pp-trade`: the same without the dodge.
    - `pw`: such a person against a bold wolf that attacks it and flees below 20%.
  - **The span.** A fight runs from the first blow to a death or the first flight, else `FIGHT_S` (90). After a flight the scene watches 20 s: caught, clear (12 m), or neither.
  - **The record.** `fights-results.json` holds per fight its length, blows made and landed by each side, dodges and how it ended. `FIGHTS` (5) of each; `FIGHT_TYPES` picks types.
- `scenes.py chase` (about 5 min a pursuer at the default `CHASES` 4; `PURSUERS=wolf,person` for both). A pursuer goes for a person 5 m away, who walks or runs (`goto`, `run: true` while breath lasts, then walking) along a 64 m line: a bold wolf (`attack`, charging at its run) or a person (`attack` with `run: true`).
  - **The measures.** `caught_s`, when the gap is first down to the pursuer's catch distance (reach and lunge: a wolf 3.2 m, a person 2 m), which does not hang on the time of day; and `blow_s`, when its first blow starts (its `skill_use` row, within the attack's reach of 1.4 m and its approach's report at 1.45 m), with `prey_moving_at_blow`. A chase ends when the prey reaches the line's end (`prey_away_s`, after about 55 m: about 20 s walking, 12 s running), so every blow counted is on prey still going away. `chase-chases.json` (since `fix-pursuit-speed`; `chase-results.json` before, which the scene's own result file overwrote).
  - **Pairings.** Set `run_share` and `wolf_run` with `set_world_law` to measure another pairing.
  - **Before and after `fix-pursuit-speed`** (2026-11-12): an approach slowed near its reach to the prey's own speed, so a wolf held about 1.7 m behind a walker it had caught up with and bit only when the prey turned; a pursuit now keeps at least the speed its target draws away at (steering.md, "Movement intents"). See the validation record for the numbers.
- **Gotchas.**
  - **Wolves are reused.** A wolf hurt in an earlier fight comes to the next hurt, so a world's later `pw` fights are shorter. Compare fresh worlds.
  - **Health comes at spawn.** `hp_*` laws apply only to bodies spawned after the change.
  - **Uses roll over.** `skill_use` keeps each actor's newest 24, so the scene gathers uses as the fight goes.

## Gotchas

- **Genes.** `body.speed` carries the genes' `speed`, so compare ratios, not absolute speeds.
- **Law changes reinstall.** `set_world_law` reinstalls the script, and a running graph keeps going.
- **Spawn values.** `stamina_max` and `spawn_energy` change only new bodies' rows (a spawn sets the cap). A living body's cap follows at its next write.
