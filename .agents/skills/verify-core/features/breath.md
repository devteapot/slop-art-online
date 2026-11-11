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
    - the run 4.81 m/s, capped at 5.5 on a road.
  - `pools::tests` (level, refill after the delay, run out, resume at 2.2 s).
  - `steer::tests::a_road_speeds_a_run_only_up_to_the_top_speed`.
  - `moves_are_a_law_per_creature` (run 1.85 for people, 1.5 and `charge` for wolves, `top` 5.5).
- **Live, `scenes.py stamina` on a default-seed run (about 2 min):**
  - **The run.** A person's run is 1.85 times its walk (`body.speed`). The row's rate is −`stamina_run` from its anchor. The scene sets `stamina_run` to 20 with `set_world_law`, so a 48 m line holds a run to empty.
    - Out of breath, it walks, and the row says the refill starts at `at_ms + 1000`.
    - It runs again about 2.2 s later, at 30.
    - The row has at most 8 distinct `at_ms` over the whole run.
  - **The refill and tiredness.**
    - Standing, the row is identical 3 s apart while the projected breath rises.
    - Breath spent costs about 0.02 energy a point.
  - **A dodge** takes 20, from a second later, and almost no energy.
  - **Too little breath.** With `stamina_max` 15 a new body has 15. Its dodge is refused "out of breath" (its `experience`). Its jump goes and takes 10.
  - **The tiredness cap.** `spawn_energy` 17.5 gives a new body 75 breath.
  - **Mana.** Three fire bolts 4.2 s apart go. The fourth is refused "not enough mana". Focus is under 30, refilling at 3.
  - **A guard.** A 3 s guard drains 4 a second. It drops and takes 12 + 5, refilling a second later.
  - **The walk law.** `walk_base` 3.0 walks 3.0/2.6 as fast.
  - **Animals.** A wolf's attack approach runs at 1.5 times its walk (`charge`). A deer flees at a run.
  - Every law is set back at the end.
- **`scenes.py moves`:** a flight with `run: false` is 1.15 times the walk. A flight by default runs at 1.85.

## Gotchas

- **Genes.** `body.speed` carries the genes' `speed`, so compare ratios, not absolute speeds.
- **Law changes reinstall.** `set_world_law` reinstalls the script, and a running graph keeps going.
- **Spawn values.** `stamina_max` and `spawn_energy` change only new bodies' rows (a spawn sets the cap). A living body's cap follows at its next write.
