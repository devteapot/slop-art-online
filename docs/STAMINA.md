# Breath, tiredness and focus (stamina-1)

Built 2026-11-11 on the Spark (branch `stamina-1`) from the approved [proposal](STAMINA_PROPOSAL.md) and the general coordinator's decisions. This note says what the rules and the authority do now, where the numbers live, the data path, and where the build departs from the proposal. Evidence is in the branch's verification records (`.agents/skills/verify-*/references/validation.md`).

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

## What a player and a mind read: meters and statuses

The meters law from `rules-senses-outcomes` describes the bars, and `status_of` gives the words for the screen and the minds (one set of thresholds):

- `meters()`:
  - health;
  - `stamina` (bar, always);
  - `focus`, labelled with the world's `pool_word("focus")` ("Mana") and `while_short: true` (shown only while not full; a new meter key);
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
