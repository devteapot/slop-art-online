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

  A run goes at `motion(a).run` times the walk: a person 1.85 (4.81 m/s), animals 1.5 (a wolf 5.1, a deer 5.55). It drains `stamina_run` (4) breath a second. When breath runs out, the body walks at the goal's own pace (a flight at 1.15). It runs again once it has `stamina_resume` (30). A run also needs 30 to start.
- **Road cap.** No road takes a body past `motion(a).top` (`run_top`, 5.5 m/s). A body that is faster on its own is not slowed.
- **Walk.** The walk is 2.6 m/s from the narrow `walk_base` law, read by the shipped `move_speed` (Cullet's overlay reads it through `base_move_speed`). An exhausted body (energy below 10) walks at `tired_pace` (0.8, was 0.6). Cullet keeps its own ×0.8 below 35.
- **Why a body is slowed.** A `slowed(a)` law gives the words: on the island "exhausted, so you walk slower", on Cullet also "tired, so you walk slower". A mind's scene shows them as `you.slowed`, beside `you.stamina` (and the focus pool under the world's word while it is not full). The mind's felt body adds "out of breath" below 20 breath.
- **Graphs.** A `{"stamina": {"below": 30}}` condition reads breath, like `energy`.
- **Unchanged.** `look_walk_deg` is untouched (dev-box's look-2 owns it).

## Every number is a world law

`laws()` holds these, so `set_world_law` changes them on a running world (each has its words in `laws_about`):

| Group | Laws (shipped value) |
|---|---|
| Moving | `walk_base` 2.6, `run_share` 1.85, `run_top` 5.5, `tired_pace` 0.8 |
| Breath | `stamina_max` 100, `stamina_regen` 25, `stamina_delay_s` 1, `stamina_run` 4, `stamina_guard` 4, `stamina_resume` 30, `stamina_tires` 0.02 |
| Focus | `focus_max` 100, `focus_regen` 3, `focus_delay_s` 2 |
| Costs | `cost_strike` 10, `cost_bowshot` 6, `cost_dodge` 20, `cost_jump` 10, `cost_block` 5, `cost_attack` 8, `cost_throw` 10, `cost_shoot` 6, `cost_threaten` 3 (breath); `cost_firebolt` 30, `cost_heal` 35 (focus) |

A client Settings switch for the walk is `set_world_law("walk_base", "3.0")`.

`pools(a)` turns these into each creature's pools. It is a hot law kept per state, and it reads only kind and stage. It gives:

- elders 0.7 of the refill;
- deer 120 breath;
- the tiredness cap: full from energy 35, half at 0 (`rested_at`, `spent_share`);
- half the refill below energy 10 (`exhausted_below`, `exhausted_regen`).

The engine finishes the cap and the refill for each body's own energy (`living_rules::pools::PoolLaw::cap`, `regen`), as it finishes `rates`.

A guard lasts at most as long as its breath (`block_duration`): (breath − its cost) / `stamina_guard`. So it drops when breath runs out, without a per-tick check.

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
