# World rules in Rhai

**Status:** built on branch `rules-2`, 2026-11-10. Skill specs and descriptions are in the script, a small set of engine primitives lets the script define social state and reactions, and agreements, demands and community regard are built from them as Rhai content. Evidence: [Verification](#verification); costs: [Costs](#costs).

**The user's decisions (2026-11-10):**

- "Export the primitives so that these kinds of things can emerge, but are not hard-coded in the core/engine," and allow custom rules per world.
- Skills declare their spec in Rhai. Adding a skill needs no Rust catalog line.
- Every skill needs a description good enough that a model has the right context to do the right thing.

**Why now.** The social trials ended with a diagnosis ([trials](TRIALS.md#why-the-newcomer-got-so-little-diagnosis-from-ls1ls2-journals-and-rows)): residents offered bed and food for work ("woodpile at my store by dark"), but work-for-keep deals lived in words only. Nothing recorded the job, and nothing told the resident that the wood was stacked. [Seeded lives](SEEDED_LIVES.md#rule-gaps) listed the rule gaps the island's tensions wait on: a community's regard for another, and a toll as an ordinary demand.

## Skills declare their spec in the script

Each skill in [`skills.rhai`](../living/scripts/skills.rhai) has a `<skill>_spec()`, read once when the script compiles. The `_combat` and `_shows` declarations are the precedent.

| Trait | Meaning |
| --- | --- |
| `target` | It is aimed at something. |
| `item` | It takes an item: `true`, or a word for what the item names (`"technique"`, `"signal name"`). |
| `items` | The item words it is given (`build`: campfire, shelter...). These are choices for clients and prompts. They are accepted for the skill even when they are not items, structures or techniques (`lodging`). |
| `args` | Further arguments it reads, for prompts (`qty`, `want`, `text`, `graph`...). |
| `reach` | Tiles within which it is done; an act walks into reach first. |
| `about` | What it is, written for a mind: what it does, when it is useful, what it is not. Required. |
| `takes`, `gives` | What it uses up and what comes of it, built from the rules' own numbers. |
| `listed` | Shown to people (false: only species that name it, such as grazing). |
| `talk` | Offered in a conversation turn among the acts one may do there. |

**Where the specs are read:**

- `Scripts::new` reads every `_spec`, in the order the source declares them. The order matters to the client: the likely act on a bush is `gather`, ahead of `face`.
- `Scripts::skills()` returns them as `catalog::Skills`. The Rust `SKILLS` list is gone.
- `catalog::skills()` is the world's skills in this process. It is set where a process adopts a world's script: the authority's script cache (`common::scripts`), the mind's `prompts::set_rules` and the client's compile in `verbs::Rules`. Until then it holds the shipped script's. `catalog::scoped` overrides it on one thread, for tests. A build without the script runtime (the lab viewer) takes any skill name: it only shows graphs the authority accepted.
- **Graph normalization and validation** (`normalize.rs`, `graph.rs`) take names, target and item needs, and the items a skill accepts from there.
- **The acts path:** `acts::parse`, `human_act` and `mind_act`.
- **The authority:** reach (`act::reach`, `combat::cards`) and founders' knacks (`seed::spawn_creature`).
- **The mind's prompts:** `catalog::skills_help`, `species::skills_help` and `prompts::talk_acts`.
- **The client's verbs:** `verbs::skills_of`, and the items for a target from `items`.
- `skill_io(name)` is the spec's `takes` and `gives`; the Rhai `skill_io` function is gone.

**Install checks** (`script/check.rs`):

- A skill with rules (a `_duration` or `_done`) but no `_spec` is refused: "`whittle` has rules but no `whittle_spec()`".
- A spec without `about` is refused when the script compiles, and so is a spec with an unknown trait.
- **Old scripts:** a script that declares no spec at all (a world's script installed before this change) is given the shipped script's specs, so the world keeps its skills until its next install. `living-publish` installs the tree's script.

**Proof:**

- `a_skill_added_only_in_the_script_is_everyones`: a `whittle` skill exists only in an appended script (its spec, check, duration and done). Graph normalization, graph validation and `acts::parse` accept it, and the mind's skill reference lists "`- whittle(item: wood): Carve a piece of wood...`". The shipped skills do not know it. Without its spec, `validate` refuses the script.
- The client test `a_skill_the_rules_add_is_offered`: a `polish` spec and check offer the skill on a boulder, and not on a bush or on oneself.

## Descriptions for models

Every skill's `about` says what it does, when it is useful and what it is not. Examples:

- "Build a structure... There is no repairing or mending of anything: a structure stands until it is gone."
- "Close wounds at once with your hands... It heals bodies only: it does not mend tools, hinges, nets or anything else." (`heal`)
- "Propose a swap now... For goods in hand; for work, or for something delivered later, offer_terms." (`offer`)
- "Strike a creature beside you. Every blow does its full damage and whoever reaches 0 health dies; there is no holding back. To frighten someone without harm, threaten." (`attack`)

The specs are functions, so a floor overrides a skill's description the way it overrides any law: it redefines `<skill>_spec()` in its overlay ([floors](FLOORS.md#how-a-floor-overrides-laws)).

**The skill reference minds read** (`catalog::skills_help`, in the deliberation grammar) grew from 12,835 to 16,978 characters (56 skills to 58: `offer_terms` and `demand`). In the real run below, a deliberation's prompt averaged 12.0k tokens against 10.9k on main: the longer reference plus the dealings section. Regenerate it with `cargo test -p living-rules --lib print_skill_reference -- --ignored --nocapture`, at `bbf7271` for the old text. Before and after, three lines:

```text
before:
- give(target, item): hand items to another creature
- offer(target, item): offer a trade to a person beside you: item + qty you give, want + want_qty you ask in return; they may accept
- heal(): mend the wounds of yourself or an ally you can see within 8 tiles, quickly, even in a fight; needs mending and a lot of energy
    takes: knowing mending, 15.0 energy, yourself or a hurt ally in sight within 8 tiles; ready again after 8 s
after:
- give(target, item, qty): Hand items from your pack to someone beside you. Nothing is asked in return; for an exchange now, offer. It is also how you pay what you agreed to or what is demanded of you: the world counts it.
- offer(target, item, qty, want, want_qty): Propose a swap now to a person beside you: item × qty you give for want × want_qty you ask. If they accept, both sides change hands at once. For goods in hand; for work, or for something delivered later, offer_terms.
- heal(): Close wounds at once with your hands, your own or an ally's in sight within 8 tiles, even in a fight. Needs the wound_tending technique. It heals bodies only: it does not mend tools, hinges, nets or anything else.
    takes: knowing wound_tending, 15.0 energy, yourself or a hurt ally in sight within 8 tiles; ready again after 8 s
```

Arguments are now listed in full (`qty`, `want`, `text`), and `takes`/`gives` come from the spec for every skill: 13 skills had none before.

### `mending` is now `wound_tending`

The newcomer kit's know-how `mending` was the `heal` skill's wound-closing, and models read it as mending things. In `i8` every newcomer pitched itself as a mender of hinges and tools ([trials](TRIALS.md#fast-iterations), row 8).

**Rename and migration:**

- The technique is now `wound_tending`, with help "close wounds quickly with your hands (the heal skill), your own or an ally's, even in a fight; not mending things".
- Seeds and trials are rewritten: `island.json` has 79 knows entries, plus `wolves.json` and `wolves-valley.json`.
- `catalog::RENAMED` maps the old name to the new. Wherever a name comes in, it is read as the new one: `catalog::technique`, `common::learn`, `common::knows`, and normalization of `teach` items and `write` topics.
- `install_script` renames a world's stored know-how and written topics once (`lib.rs` `rename_techniques`). There is no index by technique, so this reads every know-how row and artifact; an install is a rare admin call.
- Memory graphs in Neo4j keep the word in the characters' own memories. That is history, not a rule.

**Before and after on real replays.**

- **The calls:** the eight newcomer identity requests recorded in `i8` (one per run, on the Spark under `.local/living/trials/i8/*/journal/Arlen.jsonl`, line 1), replayed three times each on glm-flash at `high` effort:
  - as recorded;
  - with `mending` renamed to `wound_tending`, the only difference.
- **Counted:** the narrative only, not the model's thinking.

| | Narratives that read it as mending things ("mend what's torn", nets, hinges) | Narratives about tending wounds |
| --- | ---: | ---: |
| As recorded (`mending`) | 19 of 24 | 0 of 24 |
| Renamed (`wound_tending`) | 1 of 24 | 23 of 24 |

Recorded: "I know how to coax a fire and mend what's torn". Renamed: "nothing but a knack for fire and for closing wounds"; one renamed narrative still added "I'll watch, mend what's broken". 48 calls; 88k prompt and 17k completion tokens, about $0.02. A first attempt with the same calls failed to parse its replies, so the spend was about $0.04 in all.

## Laws

**Status:** built on branch `laws-2`, 2026-11-11. The owner's principles: world rules are Rhai laws, like skills, and Rust only exposes primitives; laws are cached by how often they run; each law has a description models can read.

**A law's declaration.** Each law the engine asks is declared by `<law>_law()`, read once when the script compiles (`Scripts::law_specs`):

| Trait | Meaning |
| --- | --- |
| `about` | What the law says, written for a mind, in the world's units (one tile is one metre). Required. |
| `cadence` | `compile` (read once per script revision), `event` (run when something happens) or `hot` (asked per creature on the hot path, and kept for every creature in the same state). Required. |
| `topic` | The section of the minds' world text it belongs to. |
| `reach` | For `senses`: the farthest anyone sees by day and by night, and hears. |

A declaration without `about` or `cadence` is refused when the script compiles.

**Senses** (`senses(a)`, hot): how far a creature sees and hears, a map of `sight` and `hearing` in metres. The shipped law keeps the values the engine had as constants (`SIGHT`, `NIGHT_SIGHT`, `TORCH_SIGHT`, `HEARING`, now gone): 11 m by day, 6 at night, 9 at night with a torch in the pack, hearing 9 m. Its description: "By day one sees 11 m; at night 6 m, or 9 m carrying a torch. Rock, walls and shut gates block the line of sight. Speech carries 9 m." The numbers in it come from the same functions as the law (`sight_in`, `hearing_of_people`), so the text follows the law. A passive is a line of the law (`+ if knows(a, "…") { 2.0 }`); `reach` must still bound it.

**How it stays cheap.**

- **Per state.** The field analysis (`Scripts::law_plan`) says the shipped law reads `night` and `actor.inv[torch]`. `Scripts::senses` keeps one answer per value of those fields (at most 1,024 states, then the memo starts over), like `rates`.
- **Only what it reads.** The authority builds the law's context from its plan (`act::law_ctx`): here the clock and one inventory lookup, not a whole `facts()`. A law that reads costly fields (warmth, terrain, vitals) gets the whole facts.
- **Per moment.** `common::senses_of` keeps each creature's answer for the current moment, so the many looks within one tick ask once per creature.
- **Reach.** Onlookers (`widest_sight`) and listeners (`widest_hearing`) are gathered within the reach, then each one's own senses are tested. The engine holds every answer to the reach; an install refuses a law whose answer passes it on the samples (`senses gives sight 13 … beyond senses_law's reach`).

**Fuel** (`just living-script-gate`, dev-box, deterministic): the authority's call `senses` 3,100 per call (0.16 µs); the law itself `senses-law` 43,497 (4.2 µs), asked only when a state is new. Budgets 4,000 and 55,000. The other laws on this branch against main: rates 7,322 / 7,312, rates-law 120,429 / 120,208, strike 257,207 / 256,303, perceived 53,123 / 52,953, hook 432,458 / 431,135.

**Moving** (`motion(a)`, hot): how a creature moves besides its walking pace (`move_speed`, already a law): `run` 1.5, `flee` 1.15 and `aside` 0.8 as shares of its walk; `turn_rate` 6 rad/s and `turn_slow` 0.4 (speed kept in the sharpest turns); `separation` 0.8 m at `separation_weight` 0.9. These were `laws()` constants (`run_speed`, `turn_rate`, `turn_slow`, `separation`, `separation_weight`) shared by every creature, and two Rust numbers (a flight at 1.15 × the walk, stepping aside at 0.8). Steering asks it at every step (`motion.rs` `update`, `separate`), a body turning on the spot (`face`), a player's run (`intent`) and a flight or step aside (`act.rs`). The shipped law reads nothing, so every creature shares one answer; a floor where wolves run harder reads `a.actor.kind` and the key grows by the kind. Its description is built from `move_speed` on sample bodies and from the law: "Grown people walk 2.6, wolves 3.4, deer 3.7; … Running is 1.5 times one's walk and a flight 1.15 times …". Fuel: `moves` 1,922 per call (budget 2,500). The world's road speed, where walkers slow and cut corners, and how often they look again stay world constants in `laws()`.

**Where the constants were read:** `common::sight` and `sight_for` (graphs' scenes, perceived sets, witnesses, the combat feed), `perceive` speech (hearing), `perception::widest_sight`. Three readers skipped the laws and are fixed: the nearest tile of a terrain used the crate's `SIGHT`/`NIGHT_SIGHT` and ignored the torch (`brain.rs`); a chase was lost beyond 1.4 × the world's sight, not the chaser's (`motion.rs`); an empty `if` compared a theft against `SIGHT` (`act.rs`, removed). A graph's `count` with no `within` used to be given 11 at normalization; it now counts everyone in sight (the count already read only the scene).

**Other rule numbers that were Rust constants** are now world constants in `laws()` (read once per script revision into `Laws`, so reading one costs nothing per tick). Values unchanged:

| Law | Value | Was | Read where |
| --- | ---: | --- | --- |
| `follow_s` | 12 s | `FOLLOW_MS` (`act.rs`) | how long one `follow` lasts |
| `read_sign_m` | 8 m | literal (`act.rs`) | `read` with nothing named |
| `kin_near_m` | 4 m | literal (`act.rs`) | `a.actor.kin_near` |
| `trade_window_s` | 180 s | three literals (`act.rs`, `perceive.rs`) | accepting a trade offer; dropped 60 s after (was 240 s, a fourth literal in `tick.rs`) |
| `join_window_s` | 300 s | two literals | a request to join a community |
| `address_m` | 6 m | two literals (`perceive.rs`) | speech to no one in particular is for the only listener this close |
| `keep_seen_m` | 1 m | `KEEP_MARGIN` (`perception.rs`) | a player's perceived set keeps a creature this far past sight |
| `chase_lost_share` | 1.4 | literal (`motion.rs`) | a chase is lost beyond this share of the chaser's sight |
| `spawn_hunger`, `spawn_energy` | 25, 85 | literals (`seed.rs`) | a body that comes into the world |
| `pasture_per_tile` | 0.02 | `PASTURE_PER_TILE` (`common.rs`) | grazing a grassy tile holds |

Two couplings that let a law and the engine disagree are fixed:

- **Bond offers** were dropped after 180 s whatever `bond_window_s` said; now 60 s after the window, like trade offers.
- **Need rates' key.** `settle_needs` (`brain.rs`) re-asks `rates(a)` when a body's state changes. Its key compared hunger and energy with 100, 70, 15 and 0, copies of the law's `starving_at`, `fed_below`, `rested_above` and `spent_at`. A world whose law moved a threshold kept stale rates until something else changed the key. The key now compares with the thresholds the law last gave that body (`NeedLaw::cuts`, kept per body for the module instance; unknown after a restart, which asks the law once).

**A world's own laws.** A seed's `rules` block used to be compiled into the module (`build.rs` wrote `rules_flags.rs`: `MINDS`, `CRY_PROMPTS_CARERS`), so each lab arm and each floor seed needed its own build (`LIVING_RULES` for a floor module). Now:

- `cry_prompts_carers` is a `laws()` constant (true in the shipped script), described like any law. `minds` was one too until `lives-2` (2026-11-11) removed it: every person has a mind ([seeded lives](SEEDED_LIVES.md#every-person-a-mind)), so a seed that sets it is refused as naming no law.
- A seed's `rules` is a map of law names to the world's own values: `{"fire_warmth": 5}` (the island sets none). Any constant of `laws()` can be set this way.
- When a world is created (`floor::begin`, for a compiled seed and for `create_floor`), its `rules` are kept in the private table `world_law` (name, value as JSON) and `clock.scripts_rev` moves, so every cache reads them. `common::laws` reads the script's laws with the world's values over them (`Scripts::laws_with`), once per script revision. An install moves the revision past the clock's.
- A name that is not a law, or a value of another kind (a number for `cry_prompts_carers`), is refused: by `init` for a compiled seed, by `create_floor` for a floor's ("seed rules: `mindz` is not a law of this world (laws are …)").
- Table design: one row per law a world sets (none on the island), primary key the name, read in full once per script revision; never written after creation. No subscription; private ([tables](https://spacetimedb.com/docs/tables/)). Adding a table is an automatic migration ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations)); a world created before this change has no rows, and its laws are the script's (`minds` true), not its seed's `minds: false`. Recreate such a world, or insert its rows as the owner.

**Old scripts.** A script installed before a required law existed (`REQUIRED_LAWS`: `senses`, `motion`) runs with the shipped script's functions underneath its own until its next install, and `install_script` refuses a script without it. An old `laws()` with `sight_day`, `run_speed`, `turn_rate` and the rest is ignored: those keys are no longer read.

### Traits instead of lists

Rules read what a thing is, declared in the script, instead of lists of names in Rust or in rules:

| Was | Now |
| --- | --- |
| `catalog::ITEMS` (26 names in Rust) | `items()`: the world's items in order, each with its traits; read once into `catalog::Skills::items` (`catalog::item`, `item_names`), so normalization, install samples, the game client's verbs and name laws take the world's items |
| `cook_check`, `smoke_check`: only `"fish"` or `"meat"`, and `"cooked_" + item` | the items' `cooks_to` and `smokes_to` traits (`item_trait`, `items_with`); the refusal lists them ("only raw fish or meat can be cooked") |
| `graze_check`: "only deer graze"; `act.rs` filled `pasture` and ate the grass for the skill named `graze` | `kinds()`: the kind's `grazes` trait ("only grazing animals graze"); the engine works out `a.actor.pasture` for any skill whose rules read it (`Scripts::skill_reads_actor`), and grass is eaten by the `graze` effect `graze_done` returns |
| `lunge`, `max_hp`, `carcass_meat`, `carcass_hide`, `dodge_dist`, `dodge_speed` switches by species, and an attack's bare damage | traits of each kind in `kinds()` (`blow` for the bare attack); the functions read the table, so the engine's calls by name are unchanged |
| `foods_text` listed seven foods; `source_of("food")` and `act.rs`'s food hint named berries and fish | built from the items' `nutrition` and the resources' yields; `act.rs` asks `source_of("food")` (`Scripts::text_of`) |
| `LATCHES` (`brain.rs`), the notable skills in `report()` (`act.rs`), `rooted` (`act.rs`), `MOVES` (`combat.rs`), `skill == "flee"` for a reflex | skill spec traits `latch`, `notable`, `moving`, `moment`, `reflex` (`catalog::SkillSpec`) |
| the theft rule in `act.rs` (owner, community, guest) | the `theft(a)` law; the engine fills `a.target.community` and the new `a.target.hosts` (the actor is the owner's guest) for a structure, and does what follows: the owner roused if it sees, onlookers told |
| warmth by structure kind (`act.rs` `warmth`: campfire, shelter, house, hall, inn, workshop) | `structure_traits()`: `warms` (a hearth) and `roof`; distances stay the laws' `fire_warmth` and `shelter_warmth`. Since `goods-1` (2026-11-11) these are traits of `structures()`, with `burns` for fires that eat fuel ([goods](#goods-recipes-and-fuel)) |
| food in any structure spoils at a third (`tick.rs`) | `kept_spoil(kind)`, a name law over the structure kinds |
| a planted bush's 5 berries (`act.rs`, `seed.rs`) | `planted_max(kind)` |
| `occupation_know_how` (`seed.rs`) | `occupation_knows(occ)` (`Scripts::words_of`) |

**Stayed in Rust as primitives,** and why:

- The torch in `senses`: the law names the item it reads (`inv(a, "torch")`), in the script. A `light` trait read through the items would make the law read the whole pack, so the per-state key would be every pack and the hot-path memo would stop sharing answers.
- `catalog::CREATURES`: the names generation, species files and the client draw from. `RESOURCES`, `STRUCTURES` and `TECHNIQUES` moved into the script on `goods-1` (2026-11-11) as `resources()`, `structures()` and `know_how()` ([goods](#goods-recipes-and-fuel)); a build without the script runtime (the lab viewer) keeps the old resource and structure names to tell kinds apart.
- The calendar (night 20:00–06:00, the world starting at 07:00, winter as a quarter of the year): `is_night` and `season_of` run in the rules crate, the authority and the client on every frame or tick. The minds' world text states them (`calendar_law`).
- Infrastructure limits (memo sizes, sweep and step cadences, table bounds, input buckets' clamps) and generation constants: not rules a world varies.
- Many remaining numbers the survey found (alert thresholds in `brain.rs`, think and re-think timings, fight-report pacing, mutation sizes, wander distances): rules, still in Rust; listed for the next pass in the branch's survey.

### Every law described, and the minds' world text built from them

- **Declarations.** Every law the engine asks is declared by `<law>_law()` with `about`, `cadence` and, for laws that belong in the minds' world text, a `topic`; `covers` lists further functions one declaration describes (`combat_law` covers `lunge`, `max_hp`, …). A law with no function of its own states a rule the engine keeps (`calendar_law`, `settlements_law`).
- **World constants.** `laws_about(l)` gives each `laws()` key its words for the values in force (`a campfire warms those within 3.5 m`).
- **Install refusal** (`check::described`, run last so a law's own failure is reported first): "the law `theft` has no description (declare `theft_law()` with `about`, or list it in another law's `covers`)", "the world constant `follow_s` has no description", or "a law's description failed: …". The asked laws are the context laws, the hooks, the laws by name (`name_laws`) and `ENGINE_LAWS`; a skill's own numbers by kind (`dodge_dist`, `jump_speed`) are described by its spec.
- **Numbers come from the laws.** Each `about` is built when the script compiles, from the same functions the engine asks: sight from `sight_in`, walking speeds from `move_speed` on sample bodies, foods from `nutrition`, recipes from `cost`, a blow's reach from `attack_spec().reach + lunge(kind)`, a yield's seconds from `yield_ms`. A floor that changes a law changes what minds are told (`world_text_is_built_from_the_laws`: day sight 7 on a floor gives "By day one sees 7 m").
- **The minds' world text** (`Scripts::world_text`): one line per section of `world_topics()`, its laws' `about` in source order, with the world's own sections (`seasons`, `life`, from the seed) where they belong. `prompts::world_rules` builds it once per rules revision (the WORLD line from the seed first), so the static prefix of every prompt changes only when the rules do; the prefix-cache tests (`*_shares_prefix`) pass. Print it with `cargo test -p living-rules --lib print_world_text -- --ignored --nocapture`.
- **What changed in the text** against the old hard-coded `RULES` (`living/mind/src/prompts.rs`): two numbers it had wrong are now the laws' (a deer gives 5 meat, not 3; a person moves 2.6 m/s walking, the old line called it running), warmth distances are exact (3.5 and 2.5 m, not 3 and 2), sight, hearing and moving have their own sections (SENSES, MOVING; hearing moved out of OTHERS), recipes list every ingredient, theft is stated under SETTLEMENTS, and OTHERS says when a name is known.

### Costs and verification (laws-2)

**Fuel** (`just living-script-gate`, dev-box, head of the branch): rates 7,318, rates-law 120,539, strike 257,804, cooldown 1,704, perceived 53,125, hook 432,380, senses 3,093, senses-law 43,742, moves 1,922. Main on the same machine: 7,312, 120,208, 256,303, 1,694, 52,953, 431,135. Every law is within its budget.

**In the authority.** Island seed, 277 people and 34 animals at rest, each window a fresh world on my own 2.14.1 container (`laws2-stdb`), 20 s settling, 60 s profiled with `living/tools/bench.py`, arms alternated A B B A; no subscribers, no minds. Not a performance acceptance at the 216-character gate.

| Arms | run | tick p50 / p99 ms | tick work ms/s | `needs.rates` ms/s | `tick.slots` ms/s |
| --- | --- | ---: | ---: | ---: | ---: |
| main | 1 | 1.64 / 3.27 | 80.8 | 3.3 | 40.4 |
| senses and motion (units 1–2) | 2 | 1.42 / 3.34 | 71.6 | 2.7 | 35.5 |
| senses and motion | 3 | 1.40 / 3.14 | 70.7 | 2.6 | 34.1 |
| main | 4 | 1.43 / 3.18 | 72.4 | 2.9 | 36.3 |
| main | 1 | 1.62 / 4.55 | 83.4 | 3.2 | 41.5 |
| branch head (all units) | 2 | 1.65 / 3.20 | 80.7 | 3.0 | 39.1 |
| branch head | 3 | 1.31 / 2.75 | 65.3 | 2.5 | 31.8 |
| main | 4 | 1.26 / 2.99 | 62.5 | 2.5 | 31.1 |

The arms differ by less than main's own two runs differ (8–21 ms/s of tick work); no tick passed 16.7 ms. The first pair's run 4 overlapped a build of mine. Graph evaluations (`tick.slots`, where scenes ask a creature's sight) and steering (`tick.motion`) are flat.

**Verification:** `verify-core` (cargo checks; tick, needs, food, refusal, seize, sight, senses, moves, skirmish, dealings, town, infant, lives, mechanics, steering), `verify-player` (deal, new_skill, told, appraise, combat, gesture), `verify-client` (30 of 30), `verify-generation` (island and the 4 km floor, with the seed rules kept as world laws), `verify-minds` with the fake model (17 cases); details and the failed attempts in each skill's `references/validation.md`. One rules bug was found by them and fixed (a new body's need rates). Not covered: a real model reading the new world text; the game client drawn and driven; `verify-knowledge` and `verify-llm` (not touched).

## Primitives

Four engine primitives, with no engine code per kind of social state:

1. **Records:** durable state.
2. **Event hooks:** laws the engine calls when something happens.
3. **Stances:** standing and regard, read by graphs.
4. **Experiences from rules:** what the rules tell a party, in that party's own terms.

The Rhai side is in `skills.rhai` ("agreements, demands and regard"); the engine side is in `living/rules/src/records.rs` and `living/authority/src/records.rs`.

### Records

A record has:

- a **kind** and a **status** (strings the script defines);
- **parties** by role: a character, or a community as `records::COMMUNITY | id`;
- **terms**: a map of strings, numbers and booleans;
- the character who made it, and the time it was made;
- the time it **falls due**.

**Tables** (private; [table design](https://spacetimedb.com/docs/tables/), [indexes](https://spacetimedb.com/docs/tables/indexes/)):

- `record`: primary key `id`; btree index on `due_ms` (`u64::MAX` means never).
- `record_party`: one row per party; btree indexes on `party` (records involving me) and `record` (a record's parties).
- `record_clock`: one row counting changes to stance records.

**Effect ops,** from a skill's `_done` or a hook:

- `#{ op: "record", kind, status, parties: #{ role: id }, terms, due_h }` makes a record. The actor must be one of its parties, and every character party must be alive.
- `#{ op: "amend", id, status, terms, due_h }` changes the status, merges terms and moves the due time.
- `#{ op: "close", id, status, keep_h }` closes a record. It stays readable for `keep_h` world hours, then the engine drops it.

Only a party to a record, or a hook asked about that record, may amend or close it. Times are world hours ("by dusk" is a law of the script, `due_by_dark`).

**Read access in laws:**

- `a.records`: the actor's records, as a party itself or through its community. Each is `#{ id, kind, status, open, terms, parties, me, by, age_s, due_s }`, where `me` is the role the actor holds.
- `a.record`: the record at hand, for `on_expire`.

The engine fills them only for a law that reads them; the field analysis marks it (`Scripts::reads`, `skill_reads_records`). The lean-context plans cover the new fields: `a.records`, `a.record`, `a.want`, `a.want_qty`, `a.actor.community`, `a.actor.home`, `a.target.community`, `a.target.owner` and `a.target.home`.

**Bounds:**

- A character holds at most 12 open records; making a 13th is refused ("has too many dealings in hand already").
- A record has at most 4 parties and 16 terms of at most 1 KB in JSON, and runs at most 720 world hours.
- Closed records are dropped after their keep time.
- Seeded records (regard) are not counted against a character's bound. Communities are parties to them, not characters.

**Knowledge against audit truth.** A record is audit truth. Who knows of it is perception's:

- the rules tell the parties (`tell`), and onlookers in sight see it made (`witness`);
- a player reads only their own characters' records through `my_records`;
- a mind is shown only its own character's records (`mind/src/mind/dealings.rs`).

Nobody learns of a record by reading the table. A dead party's records are not closed by death; the rules settle them when they fall due, as the survivor would find out.

### Event hooks

The engine calls `on_<event>(a)` where the script defines one:

| Hook | When | Context |
| --- | --- | --- |
| `on_<skill>` | after that skill was done successfully (`on_give`, `on_store`, `on_host` in the shipped rules) | the skill's own context, at completion |
| `on_expire` | a record's due time has come (1 Hz housekeeping, at most 64 a second) | its maker as actor, another character party as target, the record as `a.record` |
| `on_death` | a creature dies, before its things are gone | the dead as actor |

**Limits on what a hook does:**

- A hook returns effects, and only `record`, `amend`, `close`, `tell` and `witness`. It notices and tells; it moves no goods and no bodies (`Effect::of_a_hook`). An install refuses a hook that returns anything else, and so does the engine at run time.
- Hooks run on events only, never per tick. They run under the same Rhai limits as every law: 2,000 operations per call. A hook that fails is logged; the act it follows stands.
- The install probes call every hook over the samples of its event: each body, each target, the items `wood`, `berries` and `lodging`, and seven sample records. A hook for an event the engine does not have is refused: "the engine calls on_<skill> after a skill is done, on_expire and on_death".
- After `on_expire`, a record whose due time has not been moved is dropped: the rules let it run out.

Not built: `on_day`. A daily law (rent, regard that drifts) would take a context per record or per community, once a world day; no content needs it yet.

### Standing and regard (stances)

A record with a `holder` and a `toward` party whose terms carry a `label` (and a `value`, -100..100) is a stance: how the holder regards the other side. The record's kind is the script's (`regard` on the island); the engine reads only the roles and those two terms.

**Where stances are read:**

- **Graph relation filters.** When `me` has no personal relation to `other`, `relation_ok` (`brain.rs`) checks whether my community's stance toward theirs fits the filter word:
  - `enemy`: value ≤ -25, or a label with rival, enemy, threat or foe;
  - `friend`: value ≥ 25, or a label with friend, ally or kin;
  - any other word: a word of the label (`"relation": "rival town"`).

  Stances are cached per module instance and rebuilt when `record_clock` moves (any change to a record with a `holder` party).
- **Laws:** `a.records` includes the stance records of the actor's community. `regard_toward(a, community)` in the script returns their terms.
- **Minds:** the character's own dealings section lists them ("your people hold Kettlebridge as rival town (the broken match...)").

**Seeded records.** A seed's `records` list makes records at genesis, with parties by role naming a community or a person:

```json
{"kind": "regard", "parties": {"holder": {"community": "Brackenford"}, "toward": {"community": "Kettlebridge"}},
 "terms": {"label": "rival town", "value": -35, "why": "the broken match, and Kettlebridge's sharp prices and pride"}}
```

The island seeds 13 regards from the bible's tensions (`world.json` `records`; `author_world.py` copies them into `island.json`). They cover:

- Brackenford and Kettlebridge, each a rival town to the other;
- Brackenford and the Coldwell outlaws;
- Thornby's debt;
- the giants and the cairn-cutters;
- Lanternquay and the dear stone;
- the small folk and the giants (old friends);
- the Lakemead rivals.

Not built:

- **Perception's `perceived_of` does not read stances yet.** A projection label such as "a Kettlebridge carter (rival town)" needs to know whether the observer can tell the target's community. That is the perception work's (`scale-1`).
- **A regard writable by an act.** Rule gap 1 proposed that a community's head could change it. The world has no heads (no roles); a `declare` skill whose check is the script's own condition would be content on the same ops.

### Experiences from rules

- `#{ op: "tell", to: id, text, salience, ask }` tells a character something in the rules' words. The engine rewrites `{actor}`, `{target}` and `{id:N}` as the one told refers to them: a name it knows, "a stranger", or "you". A community's id becomes its name.
  - The text becomes an experience of kind `record`.
  - `ask` has the told character's mind think about it, as an offer does.
  - Told to the actor of a skill, the text is that act's outcome. A player's client shows it as the act's result; a mind reads it as feedback.
- `#{ op: "witness", text }`: everyone with a clear sight line to the actor perceives it, with `{a}` and `{b}` labelled per onlooker.

## Content built from the primitives

All of this is in `skills.rhai`. It is the same for players, minds and graphs: the skills are ordinary skills.

**Agreements** (`offer_terms` → `accept`):

- `offer_terms` (target, item × qty, want × want_qty, text) makes an `agreement` record with status `offered`, roles `from` and `to`, and both sides' homes in its terms. The other side is told the terms and asked to think about them. The proposal stands 4 world hours (`proposal_h`).
- `accept` toward the proposer makes it `agreed`, due at the first dusk at least `agreement_min_h` (12) game hours away (`due_by_dark`); both sides are told which ("by dusk today" or "by dusk tomorrow"). Until 2026-11-10 the minimum was 2 game hours, about a minute in a 12-minute day, and both agreements accepted in the social trials lapsed before anyone could deliver (docs/TRIALS.md, "Fast iterations"). The proposer is told, and onlookers see "came to an agreement". Without terms standing, `accept` is the trade accept, as before.
- **Deliveries** are counted by hooks:
  - `give` to the other side (`on_give`);
  - `store` into a storage whose owner is the other side, or shares their home (their household's store, `on_store`);
  - `host` for `lodging` (`on_host`).

  When one side has delivered its part, the other is told what it owes, and its mind is asked. When both have, the agreement is `kept`, and both are told.
- **At dusk** (`on_expire`):
  - delivered by one side only: `broken` by the other, and each side is told in its own terms ("they broke your agreement" / "you broke your agreement");
  - by neither: `lapsed`;
  - a proposal never accepted: "did not take up your terms".

  Nothing pays automatically: paying is the debtor's act.

**Demands** (`demand`):

- `demand` (target, item × qty, text: why) makes a `demand` record. The target is told and asked to think; onlookers see it.
- A `give` of the item to the demander counts toward it (`on_give`); paid in full, it is `met` and the demander is told.
- Unpaid after 3 world hours (`demand_h`), it is `unpaid`, and both are told. Refusing is not an act, and what follows is the demander's choice.
- A second demand of the same person while one stands is refused.

**Community regard:** the seeded stances above, read by relation filters, laws and minds.

**How a party reads a record:** `record_text(r)` in the script words each record for its party ("agreement with Mira, by dusk: you give 10 wood, they give 3 berries; so far you delivered 4 of 10, they 0 of 3"). The mind service compiles the world's script once per thread and asks it. The text then goes to:

- the deliberation prompt, in a dynamic section "Your dealings and your people's standing" (so the per-character cached prefix stays stable);
- the talk turn's "between" lines, for the records shared with the other person.

**Prompts.** Skills marked `talk` that the talk turn's examples do not already show (`offer_terms`, `demand`, `welcome`) are listed under the talk turn's acts, from the specs. The deliberation grammar lists every skill from the specs.

**The game client:**

- A skill whose spec reads `want` offers one choice per thing to ask for, from what the player carries and the skill's `items`: `offer`, and now `offer_terms`.
- What the rules tell the player (experiences of kind `record`) shows as a toast.

## Goods, recipes and fuel

**Status:** built on branch `goods-1`, 2026-11-11, for Cullet's phase 4 ([small city](SMALL_CITY.md#the-land-that-feeds-it), decision 9: goods and fire that eats fuel now; pane decay and the tide later). The owner's standing decisions it follows: items satisfy requirements by traits, not lists; the world is self-sufficient; world rules are Rhai laws over Rust primitives; no hard-coded guardrails and no engine behaviour for tests.

### The trait model

What the world has is data in the script, each a list of maps with a `name`, read once when the script compiles. The engine keeps them as tables and gives the rules three primitives over them, so a rule asks by trait for one operation instead of rebuilding a list:

| Primitive | Gives |
| --- | --- |
| `entry_of(table, name)` | the entry's map, or `()` |
| `names_of(table)` | its names, in the script's order |
| `having(table, trait)` | the names whose entry has the trait (neither `()` nor false) |

| Table | Required | What its traits are |
| --- | --- | --- |
| `items()` | yes | `cooks_to`, `smokes_to` (what cooking or smoking makes), `fuel` (units a fire that burns `fuel` gets from one), and any trait a world's recipes read (`alkali`, `bakes_to`, `oil`) |
| `structures()` | yes (new) | `warms` (a fire that needs no feeding), `roof`, `light` (metres a fire that needs no feeding lights), `burns` (below); other traits are the rules' data |
| `resources()` | yes (new) | `yields`, `regrow` (a minute), `max`, `ground` and `by_water` (where a settlement's promised nodes go), `gather_ms` |
| `know_how()` | yes (new) | `help` (what someone taught or reading is told), `requires` |
| `recipes()` | no (none) | below |

These replace the Rust constants `catalog::RESOURCES`, `STRUCTURES` and `TECHNIQUES`, and the Rhai switches `yield_of`, `regrow` and `requires`, which now read the tables. The shipped tables hold exactly what the constants and switches held. Requirements match by trait:

- **Food** is anything with nutrition (`nutrition(item) > 0`), as before.
- **Fuel** for a fire is anything with the item trait its kind's `burns.fuel` names. Peat (`fuel: 1.0`) and wood (`fuel: 1.0`) burn in a hearth; lamp oil (`oil: 1.0`) burns only in a lamp (`burns.fuel: "oil"`).
- **A recipe's input** is an item by name or anything carrying a trait: glass's `alkali: 1` takes ash, or a world's soda with `alkali: true`, with no recipe changed.

### Fire that eats fuel

A structure kind with a `burns` trait is a fire that eats fuel:

```rhai
#{ name: "hearth", burns: #{ fuel: "fuel", rate: 0.5, warmth: 4.0, light: 8.0, holds: 12.0 } }
```

- `fuel`: the item trait it burns; `rate`: units a game hour while lit (converted with the world's `day_ms`); `warmth`, `light`: metres while lit; `holds`: the most units it takes.
- **Lit only while it holds fuel.** Its one number is `structure.lit_until_ms`: the moment its fuel runs out. The fuel left is the time left times the rate (`living_rules::fire`). Nothing is written or scanned while it burns.
- **Settled on change.** Feeding it (`feed`) or drawing on it (a recipe's `fuel`, op `burn`) settles what is left and writes the new moment once. Fed fuel is gone from the pack; it is not an item to take back.
- **Goes out** when the moment passes, with no write. **Relit** by feeding it again, which takes knowing `fire` (the rules' check, `feed_check`); anyone may feed a lit fire.
- **Warmth and light come only from lit fires.** `act::warmth` counts a burning structure within its `burns.warmth` as a fire and within `burns.light` as light (`a.actor.near_light`, a new fact the shipped laws do not read yet; sight is the rules worker's). A fire that needs no feeding (a campfire, `warms` without `burns`) warms as before, within `fire_warmth`. A body's needs pick up a fire going out at the next look (the needs' state key includes `near_fire`), as when it walks away.
- **What others perceive.** A mind's scene says a burning structure is "burning, about N hours of fuel left on it", or "out". A client reads `lit_until_ms` on the public `structure` table: lit while it is ahead of the clock. Under `LIVING_PERCEPTION=scoped` the inventory table is private, so the fuel is not kept as items.
- **What reads it:** `a.target.lit` and `a.target.fuel` (units) for a structure target. Cooking and smoking work at a burning fire that eats fuel as at a campfire, and are refused at an out one.

### Recipes

`recipes()` entries, made with the `make` skill (target: the workplace; item: what is made):

| Trait | Meaning |
| --- | --- |
| `gives`, `makes` | the item made (the recipe's name by default) and how many (1) |
| `takes` | `#{ name or trait: qty }` from the pack |
| `turns` | instead of `gives` and `takes`: an item trait naming what an item becomes (`smokes_to`); one of the item is used |
| `at` | the structure kind it is made at, or `"fire"` for any fire (none: anywhere) |
| `lit` | the fire must be burning |
| `fuel` | units the heat draws from the fire it is made at (a fire that needs no feeding gives its heat free) |
| `knows`, `ms` | the technique it needs; how long it takes (8,000 ms) |

The shipped world has no recipes and no fires that burn fuel, so `make` and `feed` are not offered to its people (`listed` is computed from the tables), and its minds' world text is unchanged. A world with them gets a "Fires that burn fuel" and "Made at workplaces" sentence in its making section (`workplaces_law`), built from the same tables.

### Cullet's goods, as data

[`living/scripts/cullet_goods.rhai`](../living/scripts/cullet_goods.rhai) is an overlay composed over the shipped script (`floors::compose`); it adds no rule. Its numbers are first guesses for the soak.

| Goods | Traits |
| --- | --- |
| kelp, sand, glass, greens | plain items; greens nutrition 10 |
| ash | `alkali` |
| roots, baked roots | roots `bakes_to: baked_roots`; nutrition 14 and 30 |
| peat | `fuel: 1.0` |
| lamp oil | `oil: 1.0` |
| fish fresh and smoked, marks | the shipped items |

| Place | Kind | Gives |
| --- | --- | --- |
| hearth, oven, furnace (the Cone), smokehouse | `burns` peat or wood at 0.5, 1, 3 and 0.5 units a game hour | warmth 4, 2.5, 6 and 2 m while lit |
| lamp | `burns` oil at 0.25 a game hour | light 10 m |
| kelp_bed, sand_bank, peat_bank, root_plot, greens_bed, weir | resources | kelp, sand, peat, roots, greens, fish |

| Recipe | At | Takes | Heat |
| --- | --- | --- | --- |
| ash | any burning fire | 4 kelp | — |
| glass | a burning furnace, knowing `glassmaking` | 1 alkali, 2 sand | 1 unit |
| smoking | a burning smokehouse, knowing `smoking` | 1 of anything that `smokes_to` | 0.5 unit |
| baking | a burning oven | 1 of anything that `bakes_to` | 0.25 unit |
| lamp oil | any burning fire | 2 fish | — |

**Shared stocks.** A resource node may draw on another's stock (`resource_node.pool`, the id of the node holding it; 0: its own). A spot of a fishing ground is fished from, but its amount, max and regrowth are its pool's: target facts, a mind's scene and the harvest all read the stock. A seed places nodes with `resource_nodes: [{kind, at, max, regrow, pool}]`; nodes naming the same pool share the first one's stock. The authored plan (task `plan-1`) is to place Cullet's.

### What changed for old worlds

- **The same goods.** The shipped tables hold what the constants and switches held; the install checks, the rules tests and the verify-core scenes below pass unchanged (except two lists in `rules_read_traits_not_lists`, which now include `feed` and `make`).
- **A script installed before this change** lacks `structures()`, `resources()` and `know_how()`. It runs with the shipped script's functions underneath its own, as for any required law it lacks (`REQUIRED_LAWS`), until it is installed again; its own `structure_traits()` still decides `warms` and `roof`. An install without the three tables is refused. Old worlds have no fires that burn fuel, so `lit_until_ms` stays 0 and their campfires and houses warm as before.
- **Schema.** Two columns appended with defaults, `structure.lit_until_ms` and `resource_node.pool` (both `#[default(0u64)]`); one admin reducer added, `place_resource` (scene setup, like `place_structure`). Clients need regenerated bindings to see the new columns.
- **Engine limits.** Rhai counts nested array and map entries together, so the data tables set the limits: arrays 64 → 256 and maps 64 → 512 per value (`script::LIMITS`). The shipped rules need 27 and 35 (`measure_limits`).
- **Installing the script.** `skills.rhai` grew from 113 KB to 128 KB, and its JSON is past Linux's 128 KiB limit on one command-line argument, so `spacetime call ... install_script "<source>"` no longer runs. Installs go over HTTP: `living/tools/install_script.py` (and `just living-publish`), the verify harness, the scenes, `codes.py`, verify-knowledge, `soak.py`, `perception_bench.py` and `verify_steering.py`.

### Data paths

| Path | Reads | Writes | Recipients | Frequency | Growth |
| --- | --- | --- | --- | --- | --- |
| Warmth (`act::warmth`, in `facts` and the needs' look) | structures in the chunks within the farthest warmth, shelter or light radius (the cached chunk lists, as before; the radius is 6 m for Cullet's furnace instead of 3.5) | — | — | as before | — |
| `feed` | the structure row, the items table entry | 1 `structure` row (`lit_until_ms`), the pack's inventory row | `structure` subscribers | per feeding | — |
| `make` with heat | the structure row | pack inventory rows; 1 `structure` row | as above | per recipe made | — |
| A fire burning down | — | — | — | — | — |
| Harvest at a pooled spot | the spot and its stock's row (PK) | the stock's row | `resource_node` subscribers | per gathering | — |

No whole-World scan was added. A fire costs nothing while it burns: no per-tick work, no scheduled row.

### Costs (measured)

- **Install checks**, operations per function (most over the samples; the limit is 2,000), release build on the dev-box. Main `6593f725` against this branch, shipped script: `cook_check` 489 → 189 (traits read through the primitives), `store_check` 386 → 482, `teach_check` 635 → 635 (the heaviest), samples 9,014 → 12,971 calls. Cullet's goods over it: `make_check` 817, `make_done` 326, `feed_check` 217, `store_check` 901 (the heaviest), 24,802 calls.
- **Fuel gate** (`living/tools/script_bench/gate.sh`, fuel per call under SpacetimeDB 2.14.1's wasmtime settings, dev-box), main `6593f725` → this branch: rates 8,528 → 8,523, rates-law 207,882 → 219,828 (+5.7%), strike 271,129 → 264,039, cooldown 1,704 → 1,704, perceived 74,259 → 67,046, hook 448,259 → 449,824, senses 3,097 → 3,115, senses-law 41,999 → 46,599, moves 1,928 → 1,928. **rates-law is over its 160,000 budget on main already** (207,882); this branch adds 5.7%. The budget was not raised here.
- **Not measured:** tick time and subscription volume at population. A fire changes one public row per feeding or recipe made; at Cullet's 64 residents that is a few rows a game hour.

## How a floor adds its own rules

A floor's overlay is Rhai composed onto the base (`floors::compose`): replaced functions keep the base's as `base_NAME`. The same composition gives a floor its own social rules with no engine change:

```rhai
// A floor where debts outlive the day: agreements fall due after three days, not at dusk.
fn due_by_dark(a) { 72.0 }

// A floor with rent: whoever is hosted owes the host a fish, demanded at once.
fn on_host(a) {
    base_on_host(a) + [#{ op: "record", kind: "demand", status: "open",
        parties: #{ by: a.actor.id, of: a.target.id },
        terms: #{ item: "fish", qty: 1, done: 0, words: "rent for the night" }, due_h: 12.0 },
        #{ op: "tell", to: a.target.id, ask: true, text: "{actor} asks a fish for the night's lodging." }]
}

// A guild that keeps its members' grudges: a broken agreement turns their people's regard sour.
fn agreement_due(r) {
    let fx = base_agreement_due(r);
    // ... add or amend a `holder`/`toward` stance record between the parties' communities.
    fx
}
```

The `dealings` scene composes such an overlay to shorten the hours (below), the way a floor would.

## Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
| --- | --- | --- | --- | --- | --- | --- |
| A law that reads `a.records` (`offer_terms`, `accept`, `demand` checks and effects, the three hooks) | `record_party.party` for the actor and its community, `record.id` and `record_party.record` per row | — | btree `party`, PK, btree `record` | — | per act start and completion of those skills | — |
| A record effect | the record's parties | 1 `record`, 1–4 `record_party` rows; `record_clock` for a stance | PK, btree `record` | — | per dealing step | at most 12 open records per character; closed ones dropped after their keep |
| Tell / witness | the told character; witnesses in sight (`perceive::witnessed`) | `experience` rows | existing | the party (`my_experience`), minds | per dealing step | the existing experience window |
| Due records (housekeeping, 1 Hz) | `record.due_ms` range up to now, at most 64 | `on_expire` effects; deletes | btree `due_ms` | — | 1 Hz, empty most seconds | — |
| Relation filter, no personal relation | 2 `membership.member`, `record_clock` (1 row), the module's stance cache | — | unique `member`, PK | — | per selector candidate with a relation filter | the cache: one entry per stance |
| Stance cache rebuild | every `record_party` row with role `holder` and its record | — | full scan of `record_party` | — | when a stance record changes (rare: the seed's, or a rule changing regard) | — |
| `my_records` (player view) | my characters (`character.controller`), their and their community's `record_party` rows, each record | — | btree `controller`, `party`, PK | the player | when a read row changes | — |
| Mind service | `record`, `record_party` (whole tables, as owner) | — | — | the mind | per change | bounded as above |

No whole-World scan was added to a routine action. The two full scans are in rare paths: the stance cache rebuild, and the install-time technique rename.

[Views](https://spacetimedb.com/docs/functions/views/): `my_records` is a per-caller view built from index lookups only. A view re-runs when its read set changes; its read set is the player's own records and their parties. Adding the tables and the view to a live world is an automatic migration ([automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations): adding tables is always allowed). The docs pages read are labelled 2.0.0; the code was checked against the pinned 2.14.1 macros by building and publishing it.

## Costs

Measured on the Mac (Apple Silicon, Docker Desktop), on my own SpacetimeDB 2.14.1 container (`sao-rules2-stdb`), island seed modules of main `bbf7271` (base) and this branch (change), each window on a fresh world, 20 s settling, then 60 s profiled with `living/tools/bench.py`. Driver: a scratch `dealbench.py`, not committed; its load is described below. No subscribers. These runs do not establish performance acceptance at the 216-character gate or beyond.

**Fuel per call** (`just living-script-gate`, the bench module under SpacetimeDB's wasmtime config; deterministic):

| Law | main | this branch's code, main's script | this branch |
| --- | ---: | ---: | ---: |
| `rates` (the authority's call) | 7,024 | 7,159 | 7,183 |
| `rates-law` | 127,901 | 134,249 | 138,010 |
| strike (check + done) | 269,046 | 268,355 | 274,912 |
| `perceived_of` | 60,601 | 60,884 | 62,671 |
| `hook`: `on_give` over an agreement, a demand and a regard | — | — | 446,967 |

The new context fields cost up to 5% on the rates path, and the larger script 2–3% per call. Every law is within its budget. The hook is about 1.6 strikes. Its budget is 560,000 (`budgets.json`). It runs only after a give, store or host, never per tick. Most of its cost is turning each of the actor's records into a Rhai map; with no records it is a few thousand instructions.

**Install:** 8,905 calls over 212 functions, 540 ms in the island module on the Mac (`install.validate`). The heaviest are `teach_check` (635 operations), `on_store` (459) and `on_give` (454), against the 2,000 limit. The hook probes add the most calls: each body × each target × four items.

**At rest on the island** (277 people, 34 animals; 13 regard records): mean tick and p50/p99 in ms.

| | run | mean | p50 | p99 | max |
| --- | --- | ---: | ---: | ---: | ---: |
| base | 4 | 1.17 | 1.02 | 3.36 | 4.6 |
| base | 9 | 1.22 | 1.12 | 3.01 | 4.7 |
| change | 2 | 1.19 | 1.04 | 3.19 | 5.3 |
| change | 3 | 1.43 | 1.25 | 3.75 | 7.1 |
| change, a later pair (the Mac busier) | 5 | 2.46 | 2.39 | 4.84 | 13.2 |
| base, the same pair | 6 | 2.32 | 2.25 | 4.78 | 8.8 |

No difference beyond the run-to-run spread. In a minute at rest the hooks ran 17 times and record reads 38 times (0.02 ms/s). Base run 1 overlapped a scratch world's cleanup and is left out. Relation filters reading stances are included in these windows; no separate span was taken.

**With dealings in flight:**

- **The load:** 60 pairs of walkers (397 people), each handing the other a wood every ~4 s for the whole window: about 45 gives a second.
- **On the change arm:** each pair also holds an agreement (`offer_terms`, 900 wood wanted, so it stays open) and a demand. Every give runs `on_give` over the giver's two records (walkers belong to no community, so no regard is among them) and amends the agreement. That is 133 open records.
- **Arms:** alternated base, change, change, base.

| | run | mean tick | p50 | p95 | p99 | max | over 16.7 ms | hook span | record reads |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 3.55 | 3.09 | 7.79 | 9.86 | 13.1 | 0 | — | — |
| change | 2 | 4.38 | 3.85 | 9.54 | 11.63 | 14.9 | 0 | 4.4 ms/s, 2,679 calls | 1.1 ms/s, 5,396 |
| change | 3 | 4.06 | 3.57 | 8.74 | 10.60 | 13.8 | 0 | 4.5 ms/s, 2,495 calls | 1.1 ms/s, 5,024 |
| base | 4 | 3.96 | 3.65 | 8.15 | 10.23 | 14.2 | 0 | — | — |

- **The change:** +0.1 to +0.8 ms mean per tick, from a spread of 0.4 ms between the two base runs, so roughly +10%. About 5.5 ms/s of it is in the hook and record-read spans (about 95 µs per give in the module). The rest is the record writes (an amend per give) and the effects.
- **Mean, not ms/s:** the change arm logs more span lines, which cut the start of bench.py's log window (1,850–1,900 tick samples against 2,530–2,560), so the table compares means.
- **A stress case, not ordinary life.** Each walker delivers on its agreement every 4 seconds without end.
- **An earlier version** told the other side every partial delivery. It wrote about 50 more experiences a second than the base under this load and was dropped: a give is seen by its receiver anyway, and each side reads progress in its dealings. The table is the version without it.

**What grows:**

- at most 12 open records per character;
- closed records for 12 world hours (6 minutes at the island's day);
- seeded stances for the world's life;
- one `record_clock` row.

## Verification

On the Mac, my own SpacetimeDB 2.14.1 container (`sao-rules2-stdb`, `127.0.0.1:3342`), scratch `verify-*` databases only, code `eaee6b0` plus the driver fixes in this commit. Evidence: `.local/living/verify/` (git-ignored).

| Surface | What was driven | Result | Evidence |
| --- | --- | --- | --- |
| Project check | `set -o pipefail; just living-check` | exit 0; rules 120 passed, including `a_skill_added_only_in_the_script_is_everyones`, `agreements_and_demands_are_rules_on_records` and the records tests | — |
| Core | `scenes.py dealings` (island): agreements kept, broken, lapsed and not taken; demands met and unpaid; closed records dropped; regard records seeded and read by a relation filter | 16 of 16, twice (`8bc4f14` and the final code) | `core-rules2-deal1/`, `core-rules2-final-dealings/` |
| Core | `tick`, `needs`, `seize` (default seed), `skirmish` (island) | 6/6, 6/6, 6/6, 8/8 | `core-rules2-final/`, `core-rules2-final-dealings/` |
| Player | `deal.py`: proposes terms with the verbs' node, reads `my_records`, is told accepted, owed and kept; `record` and `record_party` private; a demand on the player told and unpaid when due (world rules, no overlay) | 13 of 13; the first attempt failed 1 on the driver (the outcome begins with a capital) | `player-rules2-deal2/`, `-deal1/` |
| Player | `new_skill.py`: `whittle` only in the script; no spec refused at install; done by a player (`human_act`), a graph leaf and a mind's act; the tree's script reinstalled | 6 of 6; the first attempt failed 1 on the driver (it assumed the player's wood) | `player-rules2-deal2/` |
| Client | `verify-client/scripts/run.py` on my own server | 30 PASS, exit 0. Three harness fixes made it run: any loopback server; the table inventory reads every authority file (`records.rs`); the floor's private tables and reducers (`floor_seed`, `genesis_timer`, `create_floor`, `genesis_step`), missing from its lists since floors merged | `client-rules2-4/` |
| Minds | `verify_minds.py --case dealings` (fake model) | pass: the demand is told, the deliberation shows it under "Your dealings", the model's give pays it, the demand is `met` and the demander told. Three driver fixes: the demander held still; the next thought requested when the cadence drops the ask; the fake rule matching the quoted reason | `minds-rules2-4-dealings/` (failed attempts `-1`–`-3` kept) |
| Minds | `acts`, `roundtrip`, `conversation` | pass | `minds-rules2-1-*/` |
| Fuel gate | `just living-script-gate`, with the new `hook` case | every law within budget (table above) | `target-gate/script-gate/` |

**Not covered:**

- the game client binary drawn and driven (its verbs tests run; no headless session);
- a woken resident proposing terms through a real model (the real run had none);
- `on_death` content (the shipped rules define none);
- `verify-knowledge` (unchanged: memory text keeps the word "mending" as history);
- `verify-generation`'s own driver for seeded records (the core scene checks they exist).

**Maintenance of the verification skills (a scoped pass):** the feature maps of `verify-core` (new `dealings.md`), `verify-player` (new `dealings.md`, `verbs.md`), `verify-minds` (new `dealings.md`), `verify-client` (`visibility.md`, `reconnect.md`, SKILL) and `verify-generation` (`seeded-world.md`) were updated, and `verify`'s surface table. The pass covered the features this change touches and drove each of them live (above). It did not re-read every other feature from source with subagents.

## The real run

**Question:** with agreements, demands and regard available (and the renamed know-how), does help reach the newcomer in the social preset?

**Setup:**

- **Batch:** `r2`, on the Spark's trial service, 2026-11-10 14:04–15:05.
- **Trial:** `life-social` (residents wake into minds when engaged; `LIVING_ONLY=<subject>,woken`), island world seeds 7, 11, 7 (the seeds where the newcomer arrives inside the walls), 60 minutes, glm-flash for the newcomer and the models file's `woken` route for residents.
- **Arms**, each 3 replicates, run in parallel:
  - control: main `bbf7271` (its module built for the same world seeds from its own seed, its rules, models and mind);
  - change: `rules-2` `8bc4f14` (module, rules, mind; same models).
- The change arm ran before the partial-delivery tells were dropped. No delivery happened in it, so this makes no difference.

| | control (main) | change (`rules-2`) |
| --- | --- | --- |
| Asks by the newcomer (food, a lesson, a bed) | 3.3 (0–6) | 2.3 (0–6) |
| Heard | 1.3 (0–4) | 0.3 (0–1) |
| Residents woken | 0.7 (0–1) | 1.0 (1–1) |
| Talk turns | 1.0 (0–3) | 0 |
| Gives, teaches, hosts toward the newcomer decided | 0 | 0 |
| Food, lodging, lessons received | 0 | 0 |
| Agreements or demands made (records other than regard) | — | 0 |
| Tokens per run | 1.22M (0.92–1.48M) | 1.74M (1.52–1.90M) |
| Cost per run | $0.20 | $0.30 |

**Did help arrive?** No, in either arm. The run cannot say whether agreements help: almost no encounter happened.

- The newcomers spoke mostly to no one in earshot ("If these walls won't talk, I'll leave something that can"). They fed themselves by gathering, and built.
- No resident heard more than one ask in the change arm, and no conversation turn ran.
- `i8` had 10–17 asks and 7–11 heard per run on the same preset. Both arms of `r2` share main `bbf7271`'s world (after `hunger-1`, residents make food rounds), so the drop is the world's, not this change's.

**What the change arm did show:**

- The newcomer's identity spoke of tending wounds, not mending things.
- Its prompts and the woken resident's carried their dealings: 20–22 prompts per engaged world, the resident's with its town's regard.
- The change arm made more deliberations (255 against 191 over three runs) with larger prompts (12.0k against 10.9k tokens).

**Spend:** $1.48 for the batch (control $0.61, change $0.87; 8.8M tokens), plus about $0.04 of replays: about $1.52.

**Evidence:**

- archived on the Mac under `.local/living/trials/rules2-r2/` (`trials/r2/` with `report.md`, `social_report.txt`, `r2_final.json`; `journal/`);
- the trial databases deleted; the replays' `rules2_replay_mending.json`;
- the Spark's checkouts removed. Its 6 replica directories were left for the next `trials.py reclaim`, which refused while another batch was live.

**Next, to test the question:** a preset where the newcomer meets people (arrival among residents at their work), or a scripted resident who answers asks. Then compare agreements made, kept and broken, and help received, over 3+ replicates.

## Files

- **Rules crate:** `living/rules/src/catalog.rs` (skill table, `RENAMED`), `records.rs` (new), `script.rs` (specs, hooks, effects, `record_text`), `script/context.rs` (new fields), `script/check.rs` (spec, hook and record-text probes), `normalize.rs`, `graph.rs`, `species.rs`.
- **Script:** `living/scripts/skills.rhai`: specs and descriptions; agreements, demands, regard, hooks, `record_text`.
- **Authority:**
  - new: `living/authority/src/records.rs` (tables, ops, expiry, seed, stances, `my_records`);
  - shared files, small edits: `act.rs` (context fields, record effects, post-skill hook, `on_death`), `brain.rs` (stance in `relation_ok`), `tick.rs` (one call in housekeeping), `lib.rs` (module, `rename_techniques`), `seed.rs` (`records`), `common.rs` (world skills, technique names), `combat.rs` (reach).
- **Bindings:** regenerated (`record`, `record_party`, `record_clock`, `my_records`).
- **Mind:** `living/mind/src/mind/dealings.rs` (new), `prompts.rs` (rules source, `record_text`, `talk_acts`, a dealings section), `mind.rs`, `mind/talk.rs`, `mind/lived.rs`, `main.rs` (subscriptions).
- **Client:** `living/game/src/verbs.rs`.
- **Seeds and tools:** `living/seeds/island.json`, `living/seeds/worlds/island/world.json`, `living/tools/author_world.py`, `living/trials/wolves*.json`, `living/trials/life.json`, `living/tools/script_bench/bench/src/fixtures.rs`.
