# Goods: where everything comes from

**Status:** built on branch `goods-3`, 2026-11-12, for the owner's question: "I've seen that we have goods now, but how do these goods generate? Are they crafted? I think everything should be kind of craftable from base resources that can be gathered with different things, and I'm not sure that we are there yet." It follows the standing decisions:

- a self-sufficient world, with little spawned from nothing;
- items match requirements by traits, not lists;
- world rules are Rhai laws over Rust primitives;
- nothing in the engine is there for tests;
- decay and upkeep are wanted.

This note covers the audit, the general rules it led to, what changed for the island, and a [trial spec](#trial-do-residents-use-the-goods) for whether residents use the goods. Cullet's own content and the reasons for each choice are in [Cullet's rules](CULLET_RULES.md#where-cullets-goods-come-from-goods-3). Two rule changes for every world are proposed, not built, in [goods proposals](GOODS_PROPOSALS.md).

## The audit

`living-rules` [`goods_audit`](../living/rules/src/goods_audit.rs) takes a world as it is created: its rules (the shipped script with the world's laws composed over it) and its seed. For every item and every kind of structure it reports where the thing comes from and what it is used for. Nothing in it is written by hand.

**Where a thing comes from**

- **Resources.** The audit takes the resource kinds the world has. A kind is wild where the seed's `resource_scale` lets it grow (default 1); a kind may also be placed by the seed's plan or its `resource_nodes`. Each kind gives what it `yields`.
- **Remains.** It takes the creature kinds the world has: animals, packs, and people where it has residents. Each leaves its `carcass` law's items in its remains.
- **Recipes.** It reads every entry of `recipes()` for every way: make, craft, cook, smoke, build and pave. For each it records the inputs (used up), the tools (held), the workplace and the fuel the heat burns.
- **Other skills.** It calls every other skill's effects (`<skill>_done`) on sample targets, with no item and with each item the skill's spec lists. Whatever the effects add or build counts as made: gathering, clearing, writing, planting and building.
- **The engine's own acts.** A death leaves remains. Writing makes a tablet, or a sign when the item is `sign`. Planting makes a berry bush. A trap catches meat while `trap_every_h` is above 0. These live in `act.rs` and `common.rs`; the audit names them in one place, and each sits beside a rule that the audit reads.

**What a thing is used for**

- **Recipes and acts.** Any recipe or act that uses the thing up (`in glass`, `in a wall`) or holds it as a tool (`tool for lamp_oil`).
- **Fuel.** The fires it feeds: an item carrying the fuel trait that a kind's `burns` names. Only fires the world has, or can build, count.
- **Traits.** Its nutrition (`food`), and the room it adds to a pack (`room`).
- **Rules that read a pack.** The install's own field analysis lists which items each law and skill reads by name, in the actor's pack (`held: attack, gather` for a spear) or in the target's (`worn against: strike` for armor).
- **Structures.** What a structure kind does: its traits (warms, a roof, lights, burns, holds), the recipes made at it, and the acts that pass only at it (open a gate, take from a store, feed a fire).
- **Notes in the laws.** What the world's laws say it is kept for (`kept_for`), when no rule reads it.

**Sources and failures**

A thing has a source in the world when some way makes it from things that have sources: the inputs it uses up and the fuel its heat burns. A tool or a workplace is not used up, so a seeded one serves. The audit computes this as a fixed point, starting from the world's resources and creatures.

As a rules test, `goods_audit::tests::the_goods_come_from_the_world` fails for any of these:

- something the seed holds or places that has no source in the world;
- something with a source and no use;
- a `seeded` mark on something that does have a source.

The first two are allowed when the world's laws mark the thing on purpose and give the reason: `seeded: "why"` on an item or structure kind for the first, `kept_for: "why"` for the second.

A thing that has no source and that the seed does not hold is not in that world. It is listed as such; Cullet's berries and meat are examples.

`the_audit_finds_what_is_wrong` checks that each failure is caught, by changing Cullet's laws in four ways:

- the drops' recipe removed: 377 seeded marks with no source;
- a glass bead that nothing uses;
- a recipe for the blowpipe added: its seed-only mark no longer holds;
- the kelp beds removed from the seed: the seeded ash and marks have no source.

```bash
cargo test -p living-rules --lib goods_audit -- --nocapture   # the tests, printing both worlds' tables
just living-goods                                             # writes the tables below
```

**What the audit cannot see**

- Who in the world knows a technique. A recipe whose technique nobody knows still counts as a source.
- Terrain an act needs. Clearing gives wood only on forest.
- Whether anyone will choose to make a thing.
- How many structures the town generator places on a world whose towns are generated. On the island these show as "the town generator".

## What it found on main, and what goods-3 closed

The same audit was run over main's scripts before goods-3 (`goods_audit::tests::audit_of_main`, ignored; it reads `LIVING_OLD_SKILLS`, `LIVING_OLD_CULLET` and `LIVING_OLD_CULLET_SEED`). With this branch's content, neither world has a gap.

| World | Found on main | Closed by |
| --- | --- | --- |
| island | `mark`: 36 in the town stores, and nothing makes one | Marked `seeded` in the shipped items: money is what a town's seed holds, and a world that mints it adds the recipe. Kept for trade (`kept_for`). |
| island | `hall`, `workshop`, `inn`, `lamp` (and `market`): the town generator places them, and nothing builds them | Marked `seeded`: a town's founding plan lays them out. A recipe would change the island, so none was added; Cullet builds them. `market` is kept for trade. |
| island, Cullet | `tablet`, `sign`: made by writing, but no rule reads them (the engine's `read` does) | `kept_for`: what is written on them |
| island, Cullet | `basket`: made, but its use is invisible to the rules, because the old `pack_full` read every item in the pack | The pack's extra room is now the item's `room: 20` trait, read by the carry law ([below](#the-carry-count)) |
| Cullet | `cloak`: 51 seeded, but no hides in Cullet | Cullet's cloak is an oilskin: 3 fiber and 1 lamp oil, knowing basketry |
| Cullet | `mark`: 377 seeded, and nothing makes one | Drops are cast at the Cone: 1 glass makes 4, using the mould, knowing glassmaking |
| Cullet | `glass`: made, and nothing uses it | Panes, floats, bottles and drops are made of it |
| Cullet | `hearth`, `oven`, `furnace`, `smokehouse`, `lamp`, `store`, `peat_barn`, `yard_store`, `house_store`, `hall`, `inn`, `workshop`: only the plan places them | A build recipe for each, from stone, clay, wood and panes |

Main's audit also showed `house`, `campfire`, `storage` and `gate` as built only after it learned to probe `build`. They were built by a list in the build rule that no table held; they are now recipes. The audit found one more thing that was not a goods gap: **a lamp counted as a fire to cook at.** Any kind that `burns` was a fire, so on Cullet one could cook, smoke, burn ash and render oil at a lamp. Now a fire to cook at is one that burns fuel and warms (`fire_kind`); a lamp burns oil for light only. This is a change for Cullet; the island has no fires that burn fuel.

## General rules (every world)

### Building is recipes

What is built is now an entry of `recipes()`, as making is since recipes-1:

- `by: "build"`: a structure kind, or a wall, gate or bridge placed on the tile beside one (`beside: true`).
- `by: "pave"`: road.

Each entry has `takes`, `knows` and `ms`. `apart: "fire"` or `apart: "shelter"` refuses a build where one already is near a fire or a shelter (the campfire's and the shelter's old checks).

`cost(kind)`, `build_check`, `build_duration` and `build_spec` read the table instead of three switches. A world adds its own builds after `base_recipes()`, as Cullet does with `built_here()`, and `build`'s spec lists them. A world whose `recipes()` leaves out `base_recipes()` builds nothing, and `build` is not offered there.

`build` is not a way of making. It has no `build_making()` and no recipe grid, and it places a structure rather than adding an item. `recipe_for`, `made_how` and `source_of` skip build recipes, because a structure is no item.

### Tools

A recipe's `tools`, `#{ name or trait: qty }`, is held in the pack and not used up. It is matched by name or by trait, like `takes`: `tools: #{ vessel: 1 }` is any item with the trait `vessel`.

The one making check (`making_check`) refuses a missing tool after the inputs, in the way's words, filled with the tool and how it is come by:

- `make`: "glass is made with a crucible in your pack, not used up (crucible: make it at an oven from 3 clay and 0.5 fuel from it (knowing toolmaking))".
- `craft`: "need a … in your pack to make a …, not used up".
- Other ways: a default.

`RecipeParts.tools` is filled (`Scripts::recipe_parts`), and `made_how` reads "…, using a crucible (knowing glassmaking)". The tool comes before the knowing, as recipes-1 set out with the laptop. The shipped recipes have no tools, so the island is unchanged; Cullet's tools are in [Cullet's rules](CULLET_RULES.md#where-cullets-goods-come-from-goods-3).

### The carry count

A pack counts each item by its `carry` value in the goods table (none: 1).

- `carry_of(item)` reads it. `load(inv)` and `carried(a)` sum it. `room_of(inv)` is the largest `room` among the carried items.
- `pack_limit(kind, inv)` is `carry_limit(kind)` plus `room_of`. A pack is full at `carried + 0.0001 ≥ pack_limit`, so ten arrows fill what one stone does.
- `give_check` counts the receiver's pack the same way, and the item given at its own `carry`.
- No item is named in the law. Shipped values: an arrow and a mark are each 0.1, and a basket has `room: 20` (it was `inv(a, "basket")` in the law).
- The limit stays in the rules: `carry_limit(kind)`, 40 for a person and 6 for an animal.
- The food law's words now say what counts for less: "A pack holds about 40 things (an arrow counts as 0.1, a mark 0.1)". It declares `carry_of` (`covers`), and the engine samples `carry_of` for every item at install.

**Stores are unchanged.** They still count things (`holds`). Cullet's store sizes were worked out in things, and every good placed in them counts 1. A store counting by `carry` would be a separate decision.

### What a script reads once may take more operations

Some functions are read only once, when the script compiles: the data tables, skills' specs, ways, laws' descriptions and the interface's declarations. Their size grows with a world's content. Cullet's making law lists every recipe and took 3,724 operations, and `build`'s spec lists every built kind.

They now run under `script::COMPILE_OPERATIONS`, 20,000, a budget of their own. Calls the engine makes while the world runs keep `MAX_OPERATIONS`, 2,000. `goods_audit::tests::descriptions_fit_their_budget` keeps each description within half its budget.

### Cheaper lookups

Cullet's recipes doubled, so three lookups that walked every recipe now ask the table for the one they want:

- `making_for` looks up the recipe named for the product first, then those that `give` it, then those that turn an item into it.
- `recipe_for` does the same.
- `source_of` asks the resources for a kind that yields the item, with `entries_where`.

`make`'s refusal for something no workplace makes now says how the thing is come by ("no one makes spear at a workplace (spear: craft it (1 stone, 2 wood))") rather than listing every product. That list cost 300 operations in Cullet. A bug was fixed on the way: `entries_where(table, "gives", item, "")` with an empty item matched every recipe without `gives`.

Two engine helpers were added:

- `Scripts::yes_of(f, name)`: a yes-or-no law of one name, such as `fire_kind("hearth")`.
- `script::COMPILE_OPERATIONS`.

## The island: what changed, and the evidence

The island changes only by the carry count:

- **Packs.** A pack holding arrows or marks is full later: at 40 by count, with an arrow or a mark counting 0.1. This affects gathering, clearing, taking (all `pack_full`) and giving (`give_check`).
- **Words.** The food law's words gain " (an arrow counts as 0.1, a mark 0.1)", and its `covers` list gains `carry_of`.
- **Data no rule reads.** Items gained `carry`, `room`, `seeded` and `kept_for`; structure kinds gained `seeded` and `kept_for`. The engine's `StructureTraits` and `SkillSpec` are unchanged.

**The evidence:** [`goods_check`](../living/rules/src/goods_check.rs) (ignored; `LIVING_OLD_SKILLS` = main's script before goods-3) answers 4,312,560 states three times:

- with main's script;
- with this branch's;
- with this branch's with every item counting 1 in a pack (`fn carry_of(item) { 1.0 }` composed over it).

The states cover every skill's verdict and words, duration and effects:

- **Actors:** a grown person, a child, an infant, an elder, a deer and a wolf, knowing nothing or everything.
- **Packs:** empty, plenty, and near the limit with arrows, marks, stones and a basket.
- **Targets:** nothing, a place, people with empty, full and arrow-laden packs, an infant, a deer, every resource kind, and every structure kind lit and out.
- **Items:** every item, every structure, and a few names that are none.
- **Also compared:** `teach`, `source_of`, `made_how` and the recipe parts of every name; every skill's spec as the engine reads it; the skill reference; every law's words and `covers`; the minds' world text.

The results:

- **Carry forced to 1:** this branch answers every state exactly as main does. Error messages are compared without the script line numbers they carry.
- **This branch as built:** 1,274 states differ from main, and every one holds an arrow or a mark: give 792, clear 336, take 96, gather 48, the food law's words, and the world text that carries them. A pack of 39 stones and 5 arrows is no longer full, so gathering goes ahead. Nothing else differs. Run against main `94c9e60f`, after merging it.

## For the client (the laptop)

The recipe grid shows a recipe that needs a tool, a workplace or a lit fire from `Scripts::recipe_parts(skill, product) -> Option<&RecipeParts>`. It is read once at install and holds no names of skills in Rust. The fields:

| Field | What it is |
| --- | --- |
| `skill`, `product`, `look` | the way (`make`, `craft`, `cook`, `smoke`), what is made, and how it looks (`icon`, `label`, `group`) |
| `item` | what the act names: the product, or for `cook` and `smoke` the raw item |
| `makes` | how many one act makes (Cullet's `pane` 2, `mark` 4, `float` 2) |
| `takes: Vec<RecipePart>` | used up: each `name`, `qty`, `any_of` (the items that satisfy it: the item itself, or every item with that trait, such as `alkali` → `ash`), `look` |
| `tools: Vec<RecipePart>` | **new, filled:** held and not used up, the same shape. A tool by name: `crucible`, `blowpipe`, `mould`. A tool by trait: `vessel` with `any_of` `["bottle", "pot"]`. A trait's `look` is its name as icon and label (`vessel`), so draw the first of `any_of` if you prefer |
| `at` | the structure kind it is made at, `"fire"` for any fire, or empty for anywhere. A fire is a kind the rules' `fire_kind` takes for one: `Scripts::yes_of("fire_kind", kind)`. A lamp is not one |
| `lit` | the fire there must be burning |
| `fuel` | units it draws from that fire (0: none) |
| `knows` | the technique (empty: none) |
| `ms` | how long one act takes |

**A cell's state and its words.** Run the rules' own check (`Scripts::check(skill, ctx)`), with the target facts as `docs/WORLD_RULES.md` "What a client shows" describes: `lit` and `fuel` from `StructureTraits::fire_state`. Missing tools are refused in their own words, after the inputs: "glass is made with a crucible in your pack, not used up (crucible: …)". `made_how(product)` reads "make it at a furnace from 1 alkali, 2 sand and 1 fuel from it, using a crucible (knowing glassmaking)".

**New icons** in `ui::ITEM_ICONS`: `pane`, `float`, `bottle`, `crucible`, `mould`, `blowpipe`. Cullet's `pot` reuses `vessel`, and Cullet labels `mark` as "drop". An icon with no image draws with the fallback.

**Building.** `build` has no grid. Its kinds are `skills().get("build").items`. Each kind's cost, technique and time are its `recipes()` entry (`tables().entry("recipes", kind)`: `by: "build"`, `takes`, `knows`, `ms`, `beside`).

**Carry.** The pack header's "N / limit" comes from the rules:

- N = Σ qty × `Scripts::num_of("carry_of", item, 1.0)`. It is cached by argument and may be fractional: 5 arrows are 0.5.
- limit = `num_of("carry_limit", kind, 0.0)` plus the largest `tables().number("items", item, "room")` among the items carried. A basket adds 20.
- The client today shows `carry_limit` without the basket. The rules count the pack as full at N + 0.0001 ≥ limit.

## Trial: do residents use the goods

**Status:** a spec for a Spark trial on Cullet with real minds, to be routed after play-test 6. Nothing here is built. The rules tests and the verify-core scenes prove that each recipe, tool and build *can* happen. This trial asks whether Cullet's 64 residents *do* make, build, cast and run short, left to their own minds, and whether the peat holds.

### Setup

- **The world:** a fresh Cullet from its seed (`living/seeds/cullet.json`, its laws composed as created). Use the Spark's own trial server (`slop-trials-stdb`), not a reference world.
- **The minds:** the mind service with the model profile the general coordinator chooses, every resident a mind, no players.
- **No scripted events or nudges.** Nothing is granted and no admin act is made after creation. The setup is only to see the world as seeded.
- **What the residents start with:**
  - Tools: blowpipes with Vessa Pontil, Corvin Hollin, Imre Sarro and Halvard Dunmore; crucibles with the first three; the mould with Aldous Quill; a pot with Livia Faro.
  - Money: 377 drops (`mark`) among the residents.
  - Peat: 1,684 in the stores, packs and the fires' first fill.
- **Who knows what matters:** glassmaking 7 people, toolmaking 2 (Otto Brandt, Bram Calloway), masonry 1 (Gwil Stannard), carpentry 6, basketry 2, smoking 1. A build or recipe nobody knows is not a finding about goods.

### How to read the authority

Read every table as the world's owner, with the admin token, as `verify.py sql` does. `structure`, `resource_node` and `world` are public. In the default `scoped` build, `inventory`, `experience`, `chronicle`, `clock`, `character` and `know_how` are private developer truth. Four sources, at three cadences:

| Source | What it gives | Cadence | Why that cadence |
| --- | --- | --- | --- |
| `experience` rows with `id` above the last read | each resident's own acts, as lines in their log | every 10 real seconds | The mind service deletes the lines it has consolidated (`mind_consolidated`), and each log keeps at most 400. Lines read late are gone |
| `structure` (every row), and `inventory` summed by `owner` and `item` | what stands, its owner, `built_ms`, `lit_until_ms`; what every pack and store holds | every game hour (2 real minutes on the 48-minute day) | Durable rows, so an hourly census shows the daily curves with 24 points a day |
| `chronicle` rows with `id` above the last read | the story feed: `kind = "build"`, "{name} built a {kind}" | every 5 real minutes | Bounded at 4,000 rows. It is a cross-check on builds, not the count |
| `world` (`day_ms`, epoch), `clock` | game day and hour of each sample | with each sample | To put every count on game days |

The act lines a resident is told, and how to count them:

- **Success, a deliberate act:** "You did what you had decided: {act} ({notes})." Notes such as "+2 pane" or "+4 mark" say what was made.
- **Success, a graph's action:** "You finished: {act}. {notes}". Residents act mostly through their graphs, the town-life routines.
- **Refusal:** "What you had decided did not work out: {act}: {why}." for a deliberate act, or "You failed to {act}: {why}" for a graph's. `why` is the rules' own words.
- **A repeated failure** within the `repeat_failure_s` law of the last is not told again. Count refusals as **episodes**: one per resident, recipe and reason, with a new episode after a told success or after `repeat_failure_s`. Do not count them as attempts.
- **Building a structure:** a new `structure` row whose `id` is above the highest at creation. Its `owner` is the builder and its `built_ms` the time. "{name} built a {kind}" is in `chronicle`.

Keep the raw samples (JSON lines per source) with the trial's evidence, so every number below can be recomputed.

### The measures

**1. What gets built, by kind and by whom, over game days**

- **Read:** new `structure` rows by `kind`, `owner` and the game day of `built_ms`. Exclude `remains` (deaths) and `sign` (writing). Check against `chronicle` `build` rows. Count refusals of `build` by reason: "you don't know how to build a {kind}", "need {n} {k} for a {kind}", "cannot build here".
- **Report:**
  - a table of kind by game day;
  - the builders, with what they knew;
  - the stone, clay, wood and panes the builds took (from each kind's recipe, `tables().entry("recipes", kind)`) against what was gathered and made.
- **Pass:** at least one fire, workplace or store kind is built by a resident who chose to, with materials they gathered or got from others.
- **Concern:**
  - nothing built in the whole trial;
  - builds refused for want of masonry while Gwil Stannard is alive and nobody asks him to teach;
  - stone running out: the wild boulders are Cullet's only stone (`resource_scale` 0.4), and the Cone alone takes 24.

**2. Drops cast, by whom, and in circulation**

- **Read:**
  - Casting: success lines with "+4 mark" from a `make` at the furnace, by observer.
  - In circulation: Σ `inventory.qty` of `mark` over every owner, packs and stores, each census. Split into packs (owners below `1 << 40`) and stores (`structure` owners, `owner & ~(1 << 40)`). Count the distinct residents holding any.
  - Moving: give and trade lines that name drops, and agreements paid in them, from the `experience` lines of `give`, `accept` and `offer_terms` outcomes.
- **Report:**
  - drops cast per game day, and by whom;
  - the total against the starting 377;
  - holders over time;
  - who holds the mould at each census: inventory rows with `item = "mould"`. Another mould fired at the oven shows up here too.
- **Pass:** drops change hands for goods or work, the total moves only by casting, and casting happens when someone wants it, through the custom the bible gives or around it.
- **Concern:**
  - drops cast in bulk with no use for them: the total climbing with nothing bought;
  - no drop ever changing hands;
  - the mould unused for the whole trial while its keeper is asked for drops.

**3. Tool shortages**

- **Read:** refusal episodes whose `why` names a missing tool.
  - `make`: "{product} is made with a {tool} in your pack, not used up ({tool}: …)".
  - `craft`: "need a {tool} in your pack to make a {product}, not used up".
  - Report them by tool and by recipe: `crucible` for glass; `blowpipe` for float and bottle; `mould` for mark; `vessel` for lamp_oil.
  - Also track who holds each tool at each census (inventory rows for `crucible`, `blowpipe`, `mould`, `pot`, `bottle`).
  - Track new crucibles, pots and moulds made: "+1 crucible" etc. from `make` at the oven.
- **Report:**
  - episodes by tool, recipe and resident per game day;
  - each tool's holders over time;
  - the time from a resident's first tool refusal to that resident next holding the tool, or to the recipe being made by someone who holds it.
- **Pass:** shortages are met by people: a crucible fired by the pot maker, a tool lent or given, the work moved to someone who holds the tool.
- **Concern:**
  - the same resident refused for the same tool over more than a game day with nobody responding;
  - every blowpipe lost, for example by a death whose remains rot, so that no float or bottle can be made again. Blowpipes are seed-only, so report their count every census.

**4. Peat: the stores against the burn**

- **Read, each census:**
  - peat held by the Store (`store`), the peat barn (`peat_barn`), the Cone yard (`yard_store`) and the 22 house stores (`house_store`), as inventory rows with owner `(1 << 40) | structure.id`;
  - peat carried in packs;
  - each fire's fuel left, `(lit_until_ms − now) × rate`, from its kind's `burns.rate` and the world's `day_ms` (`StructureTraits::fire_state`);
  - the burn: the fall in fuel left across fires between censuses, plus the units fed. A feed is told as "fed the {kind} with {n} peat: it burns about … more hours", or "lit the {kind} …" when it was out.
  - The cut: "+1 peat" from gathering at a `peat_bank`.
- **Report:** peat a game day (cut, burnt, the total heap) against `goods_minerals.py`'s figures: 101 cut a growing day at most by regrowth and none in winter; 144 burnt a day at the design burn, 154 at the evenings burn, 384 all lit.
  - Under today's rule, the 1,684 at the start run out on game day 28 at the design burn, 24 at evenings and 7 all lit.
  - Report which burn the residents actually run at, and the day the heap would run out at that rate.
  - Report each household's own store and whether its hearth is lit on winter nights.
- **Pass:** the heap's fall matches the predicted fall for the observed burn, and the residents' choices respond to it: cutting more in growing days, laying by before winter, letting fires out by day, or the Cone's firing decided by someone.
- **Concern:**
  - a household's store at 0 with its hearth out on a winter night while the barn holds peat;
  - the heap falling faster than the all-lit rate, which would mean a burn the model does not know;
  - cutting never reaching what regrowth allows (101 a growing day) while the heap falls.

**5. Panes, floats and bottles made and used**

- **Read:**
  - Made: "+2 pane", "+2 float" and "+1 bottle" from `make` at the furnace.
  - Used: panes go into builds (lamp 4, hall 8, inn 6, workshop 2: the builds of measure 1); floats into nets, from "+1 net" by `craft`, 2 floats each.
  - Bottles are kept as vessels: the holders at each census.
  - Glass made, "+1 glass", against glass used by these recipes and by drops.
  - The stocks of `pane`, `float`, `bottle` and `glass` over all owners at each census.
- **Report:** made, used and held per game day, for each of the four.
- **Pass:** glass goes to a use: panes built into something, floats into nets, bottles used for oil.
- **Concern:**
  - glass or panes piling up with no use made;
  - no glass made in the whole trial while the Cone burns. The furnace burns 3 peat an hour whether anyone melts or not.

**6. Lamp oil without a vessel**

- **Read:**
  - Refusal episodes "lamp_oil is made with a vessel in your pack, not used up (vessel: …)" by resident.
  - Successes "+1 lamp_oil" and who made them, and whether they held a pot or a bottle at the census before.
  - The lamps' fuel (`lit_until_ms` of the 7 `lamp` structures), and the feed lines "fed the lamp with {n} lamp_oil", or "lit the lamp …" when it was out.
- **Report:** refusal episodes against oil made per game day, and the lamps lit at each night's census.
- **Pass:** oil is rendered by someone holding a vessel (Livia Faro's pot, or a bottle or pot made later), and the lamps are fed.
- **Concern:**
  - repeated refusals by residents who never get a vessel;
  - every lamp dark through a night with fish in the stores.

### How long the trial must run

| Measure | Needs | Game days | Real hours on the 48-minute day |
| --- | --- | ---: | ---: |
| Builds, drops, tools, glass, oil | several working days, to see a choice made, a shortage met or not, a use found | 4 | 3.2 |
| Peat through a winter | a whole year: 6 growing days and 2 winter days (YEAR_DAYS 8), and the next spring's first day to see the recovery | 9 | 7.2 |
| Peat run-out at today's rule | the predicted day the heap is empty at the observed burn (design 28, evenings 24, all lit 7) | up to 28 | up to 22.4 |

The trial should run **9 game days** (7.2 real hours), which covers every measure but the run-out. If the burn at day 9 says the heap would empty within about 3 years, extend to the predicted day only if the coordinator wants the run-out itself seen. Otherwise report the prediction from the observed rate. A burn near the all-lit rate empties the heap by day 7 inside the 9-day run.

### Measures that wait for stores counting `carry`

Stores still count things (`holds`), while packs count by `carry`. Until a store counts by `carry` too, these measures would mislead and are left out:

- **Drops kept in stores against a store's room.** A drop is a tenth of a thing in a pack but a whole thing in a store, so a household that banks its drops fills its 150-thing store ten times as fast as its pack would. Store-full refusals while storing drops or arrows are an artefact of that, not a shortage of room.
- **What a household can lay by.** The room left in a store for food and peat, when part of it holds drops or arrows, has the same artefact.
- **Comparing what is carried with what is stored.** For example, whether people carry their money or bank it.

Peat, food, glass and the tools all count 1 either way, so measures 1 to 6 are unaffected.

## Data paths and costs

- **Schema.** No table, column, reducer or view changed. The generated bindings are unchanged, and no seed format changed.
- **Seeds.** `cullet.json`'s residents changed through `author_world.py cullet --compile-only` from the cast: 6 inventories gained their tools. The compile changed nothing else.
- **Reads and writes.** Building and making write what they did before: the structure row, inventory rows, and a fire's `lit_until_ms` when heat is drawn. A tool is read from the pack the check already reads. No scan was added.
- **Operations at install** (the most over the samples; the limit is 2,000 and the policy half of it; `--nocapture` on `goods_are_data_matched_by_trait_and_fires_eat_fuel`). The shipped script's heaviest is `smoke_check`, 520. Cullet's is `seasons_text`, 853, unchanged from rules-3. Cullet's other heavy checks:
  - `make_check` 676, down from 1,262 before the lookups were made cheaper;
  - `store_check` 821, down from 1,766;
  - `cook_check` and `smoke_check` 536;
  - `make_done` 362;
  - `feed_check` 179.
- **Operations at compile** (`descriptions_fit_their_budget`, budget 20,000). The island's heaviest are `craft_spec` 1,633, `making_law` 1,453 and `food_law` 945. Cullet's are `workplaces_law` 3,894, `build_spec` 1,945 and `food_law` 1,775.

## Verification

See [Cullet's rules](CULLET_RULES.md#goods-3).

## The generated tables

Written by `just living-goods`. Do not edit between the markers.

<!-- goods-audit: begin -->
### The island

Resources: berry_bush (wild), boulder (wild), clay_bank (wild), fishing_spot (wild), reeds (wild), tree (wild). Creatures: deer, person, wolf.

**Items**

| Item | Comes from | Used for | In the seed | Verdict |
| --- | --- | --- | --- | --- |
| berries | gathered at a berry_bush | in salve; in a berry_bush; held: plant; food | 1388 | made here |
| fish | gathered at a fishing_spot | in cooked_fish; in smoked_fish; food | 34 | made here |
| meat | the remains of a deer (5); the remains of a wolf (2); caught in a trap | in cooked_meat; in smoked_meat; food | — | made here |
| cooked_fish | cook fish at a fire, knowing cooking | food | 82 | made here |
| cooked_meat | cook meat at a fire, knowing cooking | food | 59 | made here |
| wood | gathered at a tree; clear | in spear; in torch; in axe; in pick; in basket; in bow; in arrow; in campfire; in shelter; in storage; in house; in gate; in trap; in a bridge; in tablet; in sign; build; held: write | 184 | made here |
| stone | gathered at a boulder | in spear; in axe; in pick; in arrow; in house; in a wall; in a bridge; in a road; build; pave | 72 | made here |
| fiber | gathered at a reeds | in cloak; in torch; in net; in basket; in bow; in salve; in armor; in shelter; in trap | 87 | made here |
| spear | craft from 1 stone, 2 wood, knowing spear | throw; held: attack, gather, strike, throw | 21 | made here |
| hide | the remains of a deer (1); the remains of a wolf (1) | in cloak; in leather | 24 | made here |
| cloak | craft from 1 fiber, 2 hide, knowing cloak | held: body_state, rates | — | made here |
| torch | craft from 1 fiber, 1 wood, knowing torch | held: senses | — | made here |
| tablet | write from 1 wood | — | — | made here. kept for: what is written on it: anyone who knows writing reads it |
| clay | gathered at a clay_bank | in house | 16 | made here |
| axe | craft from 1 stone, 2 wood, knowing toolmaking | held: clear, gather | 6 | made here |
| pick | craft from 2 stone, 2 wood, knowing toolmaking | held: gather | 3 | made here |
| smoked_fish | smoke fish at a fire, knowing smoking | food | — | made here |
| smoked_meat | smoke meat at a fire, knowing smoking | food | — | made here |
| net | craft from 3 fiber, knowing fishing | held: gather | — | made here |
| basket | craft from 2 fiber, 1 wood, knowing basketry | 20 more room in a pack | — | made here |
| bow | craft from 1 fiber, 2 wood, knowing archery | held: bowshot, shoot | 1 | made here |
| arrow | craft 3 from 1 stone, 1 wood, knowing archery | bowshot; shoot; held: bowshot, shoot | 30 | made here |
| salve | craft from 2 berries, 1 fiber, knowing medicine | tend; held: tend | 9 | made here |
| leather | craft from 1 hide, knowing tanning | in armor | — | made here |
| armor | craft from 1 fiber, 3 leather, knowing tanning | worn against: attack, bowshot, firebolt, shoot, strike, throw | — | made here |
| mark | — | — | 36 | seed only, on purpose. seeded: money: a town's seed holds what there is; a world that mints it adds the recipe. kept for: money: given and taken in trade, worth what people agree |

**Structures**

| Kind | Comes from | Used for | In the seed | Verdict |
| --- | --- | --- | --- | --- |
| campfire | build from 3 wood, knowing fire | where cooked_fish is made; where cooked_meat is made; where smoked_fish is made; where smoked_meat is made; warms | the town generator | made here |
| shelter | build from 3 fiber, 6 wood, knowing shelter | a roof | — | made here |
| storage | build from 4 wood, knowing storage | a store of 120; store; take | the town generator | made here |
| remains | a deer's death; a person's death; a wolf's death | take | — | made here |
| sign | write from 1 wood | — | the town generator | made here. kept for: what is written on it: anyone near who knows writing reads it |
| bush_patch | — | — | — | not in this world |
| house | build from 4 clay, 2 stone, 6 wood, knowing carpentry | warms; a roof | the town generator | made here |
| gate | build from 4 wood, knowing carpentry | open; close | the town generator | made here |
| trap | build from 2 fiber, 2 wood, knowing trapping | where meat is made; take | — | made here |
| hall | — | warms; a roof | the town generator | seed only, on purpose. seeded: a town's founding plan lays it out; no recipe builds one in this world |
| workshop | — | a roof | the town generator | seed only, on purpose. seeded: a town's founding plan lays it out; no recipe builds one in this world |
| market | — | — | — | seed only, on purpose. seeded: a town's founding plan lays it out; no recipe builds one in this world. kept for: a place to trade: people meet there; no rule reads it |
| inn | — | warms; a roof | the town generator | seed only, on purpose. seeded: a town's founding plan lays it out; no recipe builds one in this world |
| lamp | — | — | the town generator | seed only, on purpose. seeded: a town's founding plan lays it out; no recipe builds one in this world |

### Cullet

Resources: boulder (wild), clay_bank (placed by the plan), fishing_spot (placed by the plan), greens_bed (placed by the plan), kelp_bed (placed by the plan), peat_bank (placed by the plan), reeds (wild), root_plot (placed by the plan), sand_bank (placed by the plan), tree (placed by the plan), weir (placed by the plan). Creatures: person.

**Items**

| Item | Comes from | Used for | In the seed | Verdict |
| --- | --- | --- | --- | --- |
| berries | — | held: plant; food | — | not in this world |
| fish | gathered at a fishing_spot; gathered at a weir | in cooked_fish; in smoked_fish; in lamp_oil; food | 2 | made here |
| meat | — | food | — | not in this world |
| cooked_fish | cook fish at a fire, knowing cooking | food | — | made here |
| cooked_meat | — | food | — | not in this world. cannot be made here: cook meat at a fire, knowing cooking (no meat) |
| wood | gathered at a tree; clear | in spear; in torch; in axe; in pick; in basket; in bow; in arrow; in campfire; in shelter; in storage; in house; in gate; in trap; in a bridge; in smokehouse; in hall; in inn; in workshop; in market; in store; in peat_barn; in yard_store; in house_store; in tablet; in sign; build; fed to a fire (feed); held: write; fuel for a hearth; fuel for an oven; fuel for a furnace; fuel for a smokehouse | — | made here |
| stone | gathered at a boulder | in spear; in axe; in pick; in arrow; in house; in a wall; in a bridge; in a road; in hearth; in oven; in furnace; in smokehouse; in lamp; in hall; in inn; in workshop; in market; in store; in peat_barn; in yard_store; build; pave | — | made here |
| fiber | gathered at a reeds | in cloak; in torch; in net; in basket; in bow; in shelter; in trap | — | made here |
| spear | craft from 1 stone, 2 wood, knowing spear | throw; held: attack, gather, strike, throw | — | made here |
| hide | — | — | — | not in this world |
| cloak | craft from 3 fiber, 1 lamp_oil, knowing basketry | held: body_state, rates | 51 | made here |
| torch | craft from 1 fiber, 1 wood, knowing torch | held: glow, senses | — | made here |
| tablet | write from 1 wood | — | 2 | made here. kept for: what is written on it: anyone who knows writing reads it |
| clay | gathered at a clay_bank | in house; in pot; in crucible; in mould; in hearth; in oven; in furnace | 3 | made here |
| axe | craft from 1 stone, 2 wood, knowing toolmaking | held: clear, gather | — | made here |
| pick | craft from 2 stone, 2 wood, knowing toolmaking | held: gather | — | made here |
| smoked_fish | smoke fish at a fire, knowing smoking; make fish at a smokehouse, knowing smoking | food | 443 | made here |
| smoked_meat | — | food | — | not in this world. cannot be made here: smoke meat at a fire, knowing smoking (no meat); make meat at a smokehouse, knowing smoking (no meat) |
| net | craft from 3 fiber, 2 float, knowing fishing | held: gather | — | made here |
| basket | craft from 2 fiber, 1 wood, knowing basketry | 20 more room in a pack | — | made here |
| bow | craft from 1 fiber, 2 wood, knowing archery | held: bowshot, shoot | — | made here |
| arrow | craft 3 from 1 stone, 1 wood, knowing archery | bowshot; shoot; held: bowshot, shoot | — | made here |
| salve | — | tend; held: tend | — | not in this world. cannot be made here: craft from 2 berries, 1 fiber, knowing medicine (no berries) |
| leather | — | — | — | not in this world. cannot be made here: craft from 1 hide, knowing tanning (no hide) |
| armor | — | worn against: attack, bowshot, firebolt, shoot, strike, throw | — | not in this world. cannot be made here: craft from 1 fiber, 3 leather, knowing tanning (no leather) |
| mark | make 4 from 1 glass at a furnace, with 1 mould, knowing glassmaking | — | 377 | made here. kept for: money: given and taken in trade, worth what people agree |
| kelp | gathered at a kelp_bed | in ash | — | made here |
| ash | make from 4 kelp at a fire | in glass | 3 | made here |
| sand | gathered at a sand_bank | in glass | — | made here |
| glass | make from 1 alkali (ash), 2 sand at a furnace, with 1 crucible, knowing glassmaking | in pane; in float; in bottle; in mark | — | made here |
| roots | gathered at a root_plot | in baked_roots; food | 603 | made here |
| baked_roots | make roots at an oven | food | 4 | made here |
| greens | gathered at a greens_bed | food | — | made here |
| peat | gathered at a peat_bank | fed to a fire (feed); fuel for a hearth; fuel for an oven; fuel for a furnace; fuel for a smokehouse | 1356 | made here |
| lamp_oil | make from 2 fish at a fire, with 1 vessel (bottle or pot) | in cloak; fed to a fire (feed); fuel for a lamp | 4 | made here |
| pane | make 2 from 1 glass at a furnace, knowing glassmaking | in lamp; in hall; in inn; in workshop | — | made here |
| float | make 2 from 1 glass at a furnace, with 1 blowpipe, knowing glassmaking | in net | — | made here |
| bottle | make from 1 glass at a furnace, with 1 blowpipe, knowing glassmaking | tool for lamp_oil | — | made here |
| pot | make from 2 clay at an oven, knowing toolmaking | tool for lamp_oil | 1 | made here |
| crucible | make from 3 clay at an oven, knowing toolmaking | tool for glass | 3 | made here |
| mould | make from 1 clay at an oven, knowing toolmaking | tool for mark | 1 | made here |
| blowpipe | — | tool for float; tool for bottle | 4 | seed only, on purpose. seeded: iron: the island's iron is the ships' fittings and none is new (docs/SMALL_CITY.md, materials); the Cone's pipes are what the ships left |

**Structures**

| Kind | Comes from | Used for | In the seed | Verdict |
| --- | --- | --- | --- | --- |
| campfire | build from 3 wood, knowing fire | where cooked_fish is made; where smoked_fish is made; where ash is made; where lamp_oil is made; warms; lights | — | made here |
| shelter | build from 3 fiber, 6 wood, knowing shelter | a roof | — | made here |
| storage | build from 4 wood, knowing storage | a store of 120; store; take | — | made here |
| remains | a person's death | take | — | made here |
| sign | write from 1 wood | — | — | made here. kept for: what is written on it: anyone near who knows writing reads it |
| bush_patch | — | — | — | not in this world |
| house | build from 4 clay, 2 stone, 6 wood, knowing carpentry | warms; a roof | 22 | made here |
| gate | build from 4 wood, knowing carpentry | open; close | — | made here |
| trap | build from 2 fiber, 2 wood, knowing trapping | take | — | made here |
| hall | build from 8 pane, 30 stone, 12 wood, knowing masonry | warms; a roof; lights | 2 | made here |
| workshop | build from 2 pane, 12 stone, 8 wood, knowing carpentry | a roof | 2 | made here |
| market | build from 4 stone, 8 wood, knowing carpentry | — | — | made here. kept for: a place to trade: people meet there; no rule reads it |
| inn | build from 6 pane, 20 stone, 10 wood, knowing masonry | warms; a roof; lights | 1 | made here |
| hearth | build from 2 clay, 4 stone, knowing masonry | where cooked_fish is made; where smoked_fish is made; where ash is made; where lamp_oil is made; a fire that burns fuel; lights; feed | 22 | made here |
| oven | build from 4 clay, 8 stone, knowing masonry | where cooked_fish is made; where smoked_fish is made; where ash is made; where pot is made; where crucible is made; where mould is made; where baked_roots is made; where lamp_oil is made; a fire that burns fuel; lights; feed | 1 | made here |
| furnace | build from 12 clay, 24 stone, knowing masonry | where cooked_fish is made; where smoked_fish is made; where ash is made; where glass is made; where pane is made; where float is made; where bottle is made; where mark is made; where lamp_oil is made; a fire that burns fuel; lights; feed | 1 | made here |
| smokehouse | build from 4 stone, 6 wood, knowing carpentry | where cooked_fish is made; where smoked_fish is made; where ash is made; where lamp_oil is made; a fire that burns fuel; a roof; lights; feed | 2 | made here |
| lamp | build from 4 pane, 2 stone, knowing glassmaking | a fire that burns oil; lights | 7 | made here |
| store | build from 16 stone, 8 wood, knowing masonry | a store of 1200; store; take | 1 | made here |
| peat_barn | build from 10 stone, 6 wood, knowing masonry | a store of 1000; store; take | 1 | made here |
| yard_store | build from 8 stone, 4 wood, knowing masonry | a store of 900; store; take | 1 | made here |
| house_store | build from 5 wood, knowing carpentry | a store of 150; store; take | 22 | made here |

<!-- goods-audit: end -->
