# Seeded lives: people with a past, a place and something going on

Started 2026-11-09 (branch `lives-1`). The island had towns and roads, but its people were generated from occupation counts: a name, a trade and a house. They read as background NPCs, though every character in this world is meant to be a person on the same terms as a player. This note designs how the island starts **with people who have identities, households, pasts, relations and situations**, how they are spread over the land, and which **tensions between places** give the world motion from the first tick. It also records what was built, measured and verified.

**Status.** Implemented and verified on scratch databases on the dev-box (SpacetimeDB 2.14.1, its own container `lives-stdb`; no lab or reference world touched). The island seed (`living/seeds/island.json`) now carries **277 authored residents in 92 households across 17 settlements** (8 settlements and 9 new hamlets), with 2,348 relations, 1,236 remembered events, 1,068 stances, 96 secrets and 88 shared situations. See [lab evidence](#lab-evidence) for what they did on their own. `townlife-2` merged while this was built; `lives-1` merges it and makes the one mind-service change the seam needs ([the seam](#the-seam-with-town-life-layer-2)).

## The rule this follows

**Hard-code nothing; seed the world's state and let behaviour come from it** (the user, 2026-11-09).

- **Seeded:** people, households and their pasts, relations, memories, stances, wants; where things are and who owns them; what each place has and lacks.
- **Not in code:** roles. There is no bandit type and no carrier type. An outlaw is a person whose past (fields taken), relations (kin in the town that outlawed them) and wants make raiding the road their choice. A carrier is someone whose work, needs and relations make walking a route worthwhile. Every skill is open to everyone.
- **Routines** exist only as starting graphs, the same as today's instincts. They are seed content, made of the skills every character has, and the character owns them: a mind can rework any of them.
- **Trade and tension come from conditions:** scarcity and surplus between places, people who know where things are, grievances and competition in seeded pasts.
- **Missing mechanics** become general rules that apply to everyone (Rhai laws or seed data), never hooks for one story. Where a tension needs a rule that does not exist, it is listed as a [rule gap](#rule-gaps); no script stands in for it.
- **No scheduled events and no narrative triggers.**

This follows AGENTS.md: mechanics apart from culture and seed content; free-form communication without silent knowledge copying; death is permanent.

## Who lives where

### The island's places (seed 7, 2048 m)

`living_rules::land` lays out 8 settlements and, since this change, **9 hamlets** ([placement](#placement-hamlets-and-known-ways)). `lives_sites` (below) lists each one's region, homes and lots.

| Settlement | Kind, region | Homes | Residents (seeded) | Households | People per household |
|---|---|---:|---:|---:|---:|
| Brackenford | walled town, meadow | 136 | 78 (12 children) | 27 | 2.9 |
| Kettlebridge | steampunk town, meadow (terraced) | 33 | 31 (10) | 9 | 3.4 |
| Lanternquay | cyberpunk town, beach | 51 | 39 (7) | 16 | 2.4 |
| Fernhollow | small folk, old forest | 63 | 31 (9) | 10 | 3.1 |
| Highshelf | giants, highland | 18 | 14 (4) | 3 | 4.7 |
| Elmwick | village, forest | 11 | 14 (3) | 4 | 3.5 |
| Thornby | village, meadow (north shore) | 7 | 14 (3) | 4 | 3.5 |
| Reedmoor | village, beach | 13 | 11 (4) | 3 | 3.7 |
| **8 settlements** | | **332** | **232 (84%)** | **76** | |
| Coldwell | hamlet, forest, on the stone road | 4 | 8 | 3 | |
| Ashby | hamlet, meadow near Brackenford | 4 | 3 | 2 | |
| Highfold | hamlet, highland | 2 | 5 | 1 | |
| Sootwood | hamlet, old forest above Lanternquay | 4 | 7 | 2 | |
| the Lakemead | hamlet, meadow near Reedmoor | 4 | 4 | 2 | |
| Saltings | hamlet, west shore | 5 | 7 | 2 | |
| the North Light | hamlet, north cape | 3 | 2 | 1 | |
| Tanglewood | hamlet, old forest near Fernhollow | 3 | 3 | 1 | |
| Ferncross | hamlet, forest near Elmwick | 5 | 6 | 2 | |
| **9 hamlets** | | **34** | **45 (16%)** | **16** | |

Brackenford's 27 households fill 27 of its 136 homes, so most of the town's houses stand empty: room for newcomers, and for more seeded households toward the contract tier. Highshelf (3 households, 18 homes) and Fernhollow (10, 63) are as empty; the villages and hamlets are about full. Occupations: 64 children, 48 farmers, 34 cooks, 27 fishers, 19 traders, 14 healers, 10 carpenters, 10 hunters, 9 builders, 8 scribes, 8 masons, 7 guards, 6 woodcutters, 4 outlaws, 3 quarriers, 5 carriers (2 fish runners, a stone carter, a meat carrier, a pedlar) and an innkeeper.

### Dispersal

- **Today's split (seeded):** 84% live in the eight settlements and 16% in the hamlets. During the day a few more are out: carriers on four roads, outlaws at their spot on the stone road, woodcutters and quarriers at the trees and boulders round their homes, farmers in fields along the roads.
- **Kinds of dwelling outside the towns,** each a hamlet the generator places and the seed peoples by preference ([`near`, `region`](#placement-hamlets-and-known-ways)):
  - farms in the meadows near a town (Ashby, the Lakemead);
  - woodcutters and charcoal burners in the woods (Sootwood, Ferncross);
  - a herders' fold in the hills (Highfold);
  - salt pans and fish traps on a lonely shore (Saltings);
  - a lone dwelling (the North Light: an old woman and her grandson; Tanglewood: a healer's cottage);
  - an outlaws' steading in the woods by the stone road (Coldwell).
- **On the roads:** whoever carries goods between markets ([routes](#trade-routes)), whoever watches the road, and anyone a mind sends there.
- **Unpeopled houses stay unowned:** empty homes in every settlement, and any hamlet a seed leaves empty, are there for newcomers.

### Against the performance envelope

The [performance contract](PERFORMANCE_CONTRACT.md) locks 2,000 active characters including players; the immediate gate is 216 for 30 minutes. The gate run ([GATE_216](GATE_216.md)) failed because of per-sender perception views for players, with 293 ambient residents and animals beside the 216 players. Instinct-only residents cost little per tick ([measurements](#measurements)), so the ambient population is not what binds today.

| Tier | Residents | In settlements | In hamlets | On the roads by day | Island |
|---|---:|---:|---:|---:|---|
| **Seeded now** | 277 (+ 34 animals) | 232 (84%) | 45 (16%) | 5 carriers, 4 outlaws at the road | 2048 m, 17 settlements |
| Gate (216 players) | as now | | | | as now: residents are ambient, not counted in the 216 |
| Contract (2,000 characters) | about 1,600 residents beside 400 players | 70% | 20% | 10% (carriers, herders, work sites) | 2048 m fits about 1,450 at 4 per home; 2,000 needs bigger households in the town (townhouses), more hamlets (`per_km2` 3 → 6) or the 3 km island |

The contract tier is a plan, not a seed: authoring 1,600 sheets costs about 6× what this island cost ([spend](#spend)), and the tick has not been measured at that population.

## A life's seed

What one resident starts with. Every item is a world fact written once, at world creation; none is recomputed per tick.

| Part | Where it lives | Read by |
|---|---|---|
| Name, age (life stage), sex, parents | `character`, `genome` (traits from the sheet) | rules, everyone who sees them |
| Household and home | the household's house at its lot door (`structure.owner`), `character.home_x/y` | graphs (`home`), shelter, sleep |
| Settlement and community | `membership`, `background.town` | graphs (`outsider`), the stage cap, gates |
| Occupation and know-how | `background.occupation`, `know_how` | starting ways, skill checks |
| Possessions | `inventory` (kit by occupation, a carrier's first load) | skills |
| Places they know | `place` rows: work, square, inn, evening; a known way's stages; a spot on the road | graphs (`{"place": …}`), minds |
| Relations, with reasons | **`relation` rows** (trust, affinity, label, note), written from the sheet at creation | graphs (`friend`, `enemy`, labels), minds |
| Whose name they know | kin and one's own community; **`acquaintance` rows** for each authored relation across communities unless the sheet says `knows_name: false` | perception (names in percepts), minds (`known_as`) |
| A short past | sheet `memories` (in `background`) | the mind, installed as formative memories |
| Stances, wants and fears | sheet `stances`, `values`, `goals`, `mood` | the mind |
| Pastimes and the work they love | sheet `pastimes`, `calling` → `persona` | the mind's prompts |
| Their daily rhythm | `residents[].rhythm` (or drawn) → `rhythm` | graphs (`bedtime`, `evening`), the new day, the mind's prompts |
| Appetite and hardiness | genes (`appetite`, `hardiness`), drawn per person | the needs law |
| A secret | the seed file only (`LIVING_SEED`); never a table | the character's own prompts |
| The situations they are in | **inside each person's sheet, from their side**; the situation records stay in the authoring files (`cast/*.json`) | developer audit only |

**Consistency.** A situation is one record with a side per person (a debt, a courtship, a feud…). Each sheet is drafted from its person's side, and the checks require the people in a shared situation to have relations to each other both ways. A review pass reads each situation against its people's sheets ([authoring](#authoring-at-scale)). If A owes B, both sheets say so; if A is courting B, both know it; a secret appears only on the sheets of the people the record names.

**Situations are starting state, not scripts.** A record says what is the case now ("Reginald Hobson owes Silas Pike for the last load of stone and cannot pay until the Reeve settles the wall account"). It has no outcome and no schedule. Nothing in the world reads the record; only the people in it carry it, as their own memories and stances.

## World tensions

Seeded for the island in [`bible.md`](../living/seeds/worlds/island/bible.md) and [`world.json`](../living/seeds/worlds/island/world.json). Each is held consistently on every side through anchor people (fixed in `world.json`, so every settlement's draft sees them) and situations.

| Tension | Who holds it | What it is made of (seed state) | Mechanics it uses |
|---|---|---|---|
| **The gate-due** | Brackenford's Reeve and guards against the Market Guild and Kettlebridge's carters | the ledger sign; stances; relations | ordinary demands (speech), `give`, `offer`/`accept`: [toll gap](#rule-gaps) |
| **Brackenford against Kettlebridge** | both towns | the broken match (Tobin Marrow, Hester Crane), sharp prices, pride; memories and stances on both sides | speech, trade; [community regard gap](#rule-gaps) |
| **The Coldwell outlaws** | Marta Hale's households, a Lanternquay deserter, a runaway apprentice | their fields leased to the Tolleys of Ashby; outlawed at the gate; kin in Brackenford (Agnes Fenner, secretly feeding them); a road spot; a starting way that threatens outsiders and seizes from those who yield | `threaten`, `yield`, `seize`, `attack`; the `outsider` relation |
| **The Guild and the Reeve** | Brackenford | succession unsettled; the gate-due; a clerk's gambling debt to the Guild head | speech |
| **Thornby's debt** | Thornby and Brackenford | 40 baskets, written on Brackenford's ledger sign; the headman's stances | `give` (paying is a choice); [community debt gap](#rule-gaps) |
| **The giants and Kettlebridge** | Highshelf's elder, her son, Tavvik; Ezra Holt | the cairn cutting; the elder's ban on the shelf's ledger; Tavvik's meat run against it | carrying on the giants' track; speech |
| **The drowned quay** | Lanternquay and the Surge families in Kettlebridge | stone scarce at the quay; Kettlebridge's price; refugees' cheap labour | trade, the fish road |
| **The Lakemead** | Elmwick, Reedmoor, the Coombes | rent paid in grain; fences pulled down | speech; [land claim gap](#rule-gaps) |
| **The north light** | Thornby, Edda Wray | an accusation and a lost boat | speech |
| **Small folk and big folk** | Fernhollow, Highshelf | an old friendship; distrust of Kettlebridge's smoke | speech, the east road |

### Trade routes

Goods differ by place because the seed's stores and resources differ ([bible](../living/seeds/worlds/island/bible.md#money-goods-and-what-each-place-lacks)): Brackenford has berries and lacks stone; Kettlebridge has stone and lacks food; Lanternquay has fish and lacks stone and timber; Highshelf has meat and stone and lacks timber; Fernhollow has fibre and lacks timber.

| Route | Carrier (household) | Out | Back | Stages |
|---|---|---|---|---:|
| The stone road | Silas Pike, Kettlebridge | stone to Brackenford's square | berries | 12 (58–76 m apart), reach 100 m |
| The fish road | Juno Reyes, Lanternquay | cooked fish to Kettlebridge | stone | 14 (83–131 m), reach 180 m |
| The fish road, from the north | Tern Gannet, Thornby (the Thornby cast made a fish runner of its own) | cooked fish to Kettlebridge | stone | 14 (71–98 m), reach 180 m |
| The giants' track | Tavvik, Highshelf (against the elder's word) | cooked meat to Kettlebridge | wood | 10 (50–103 m), reach 115 m |
| The east road | Thistle Mossfoot, Fernhollow | fibre to Reedmoor | fish | 10 (62–81 m), reach 100 m |

A carrier's starting way (`carry_graph` in `author_world.py`, written into `ways.occupations`) is made of `take`, `goto` and `store`. Take a load from the home square's store, walk the known way's stages to the far market, store it there, take that market's surplus, walk back and store it at home. It runs by day under the island's `work` desire, like any trade.

Graphs are weighed again while a walk goes on (movement stays reactive), so each rule must hold for a whole leg: "within `reach` of stage *k*, walk to stage *k*", the furthest such stage first. Each stage lies within `reach` of the last, and a stage two ahead lies beyond it, so a carrier keeps to the road instead of cutting across. A graph holds at most 80 nodes, which caps a way at about 14 stages each direction; longer ways take a larger reach and cut more corners. The carrier is the one who walks it; the town stores give and receive. Paying, bargaining and dues are not in the routine: those are what a woken carrier or the people it meets may choose.

## How it reaches play

- **Every resident has a mind from the start** (since 2026-11-11; before, the island's `rules.minds = false` kept residents instinct-only until someone engaged them). Its body acts on its seeded routines and relations through the existing rules while its mind thinks:
  - **Relations are rows.** World creation writes every sheet relation into `relation` (`seed::settle_authored`), so starting graphs can read them: the common ways now wave at a friend in sight away from home (chance 0.03 a check), stare at an enemy close by (`face`), and nod to a friend first in the evening. An outsider threatened while outnumbered and with no friend near yields (`stay safe`).
  - **Places are rows:** work, square, inn and evening places as before, plus the places the author gave a person (`residents[].places`): a carrier's far market and the stages of the way, an outlaw's spot on the road. They are **given** (`place.given`): a mind's projection never drops them, since the starting ways walk to them.
  - **Goods are stores and packs:** the seed's stores per settlement, a kit per occupation, a carrier's first load.
- **The mind starts from its facts and its sheet.** At the mind service's start (`living/mind/src/mind/facts.rs`), a resident's world facts (household, family, settlement, every place with the lot it stands at) go into its memory marked `world`, then its authored sheet is installed by the existing path ([authored worlds](AUTHORED_WORLDS.md)): the narrative, relations as `FEELS`, stances as `JUDGES`, memories as formative `[before all this]` memories, and the secret in its own prompts only. A resident without a sheet gets one identity call written from the same facts.
- **Authoring cost stays at authoring time.** Sheets are written once, by a model, before the world exists. Installing a sheet costs no model call ([AUTHORED_WORLDS](AUTHORED_WORLDS.md#sheet)). Living costs model calls for every resident; see [every person a mind](#every-person-a-mind).

### The seam with town life layer 2

Layer 2 phase 2 (`townlife-2`) seeds a woken resident's mind "only from world facts". This change supplies more of those facts and keeps them where a mind can read them as itself:

1. **`background.sheet`:** the authored identity, with people resolved to ids. A woken resident with a sheet should install it the way `sheet_persona` does today, before internalizing its ring. What the model writes beyond it is marked as the mind's own (`inferred_from: woken`), as layer 2 already plans.
2. **`relation` rows from day one:** layer 2 reads "its relations if any". For a seeded resident they now exist before waking, and they agree with its sheet. A mind's projection later replaces them as it does for any mind.
3. **`place` rows:** the woken row's places now include the author's places (a carrier's way, an outlaw's road spot), which `mind_update` keeps.
4. **No situation table.** Situations reach a mind only through its own sheet, so waking never copies another person's view of a shared situation.
5. **Keep the authored identity through consolidation.** The paid lab showed the first consolidation rewriting three authored personas with wrong facts within a minute (a Brackenford gate guard became "a guard of Kettlebridge"), because the consolidation prompt does not name the resident's settlement, trade or household. Phase 2 should give consolidation those world facts and revise an authored identity only on lived evidence.

**Made (2026-11-10, after `townlife-2` merged).** Waking an authored resident (`living/mind/src/mind/woken.rs`, `make_mind`) now goes:
1. its world facts as given (household, family, places), marked `world`;
2. its sheet as written (`sheet_persona`, no model call), marked `authored`: a mark of its own, so an experiment can tell what the author invented from what the world holds (`world`), what a model wrote (`ai`) and what the resident lived (`instinct`, `human`). The identity version says `written_by: author`;
3. its ring, as for any woken resident.

People in the sheet go into its mind named as it knows them (`known_as`).

**Names.** Since `townlife-2`, names spread only as the authority projects them: kin, one's own community, or an introduction (`acquaintance`). A feeling is not an introduction. So an authored relation to someone outside one's community is an introduction at world creation (`seed::settle_authored`), unless the sheet marks it `knows_name: false`. The authoring tool decides that per relation in a names pass (one call per settlement, `living/seeds/worlds/island/names/`): would this person recognise the other and know what to call them? Of 524 cross-community relations, 505 are known by name and 19 are not. Wenna Marrow has never met Hester or Josiah Crane, so in her mind they stay "a stranger" until someone tells her their names. World creation writes 508 introductions.

**Verified** (`verify-minds/scripts/lives_wake.py`):
- **Free tier**, three woken Brackenford residents, 29 of 29:
  - each woke as its authored self, its relations rows before waking;
  - Wenna Marrow's two never-met relations stay "a stranger" in her mind; Mercy Abbot and Wat Fenner have 6 and 4 introductions;
  - their minds mark `authored` 55–67 and `world` 6–8;
  - each seeded situation it is in shows in its first prompt through its people (Wenna: the broken match, her mother's grudge; Mercy: the gate-due, the Coldwell fields, the mill toll and three more);
  - its own secret is in its own prompt only.
- **Paid tier** (DeepSeek V4.1 Flash): the marks are `world` 6–7, `authored` 55–67, `ai` 7–11 and `instinct` 6–9 (their rings).
  - Mercy Abbot, asked about the gate-due: "a millstone round Brackenford's neck… that due drives good carters like Silas Pike to take their stone elsewhere."
  - Wenna Marrow, asked why folk in the square look at her, chose not to answer: "The stranger's question only stirs the same old talk, and I have no mind to feed it." Her thoughts carry her side of the broken match ("Tobin chose me and I chose him").

`verify-knowledge`'s `woken_mind.py` still proves the world-facts path on a resident whose sheet the fixture removes (7 of 7), and `verify-minds` `wake` passes.

**Seeded wants under `feedback-1`'s identity wording** (2026-11-10). `feedback-1` (merged in `a25157b`, already in `lives-1` through `c0ff89d`) tells consolidation that an identity changes only when experiences warrant it, and that when it does, "goals and values grow out of what they did, tried, met and went through". The paid run found that seeded wants were lost, but not because of the wording. A consolidation started while a woken resident's mind was still being made was shown "(no persona yet)". Experiences trigger consolidation, and only deliberation waited for the mind to be made. So it wrote an identity afresh over the authored one. Mercy Abbot's model wrote "No persona was set" as its reason and dropped two seeded goals (reopening trade with Kettlebridge, becoming Reeve). Consolidation now waits for a woken mind to be made, as the first deliberation does (`woken_stage("wait_s")`). The same race existed for a resident whose identity a model writes from world facts.

After the fix (paid run, DeepSeek V4.1 Flash, Wenna Marrow, Mercy Abbot and Reeve Aldric Marrow, 32 of 32 checks):
- every consolidation saw the resident's identity;
- Wenna's and Mercy's consolidations left their identities alone;
- Aldric's rewrote his and kept all four seeded goals ("keep the gate-due", "collect Thornby's debt", "find a successor", "clear the outlaws from the stone road"), adding one grounded in what he had just lived ("learn what the stranger wants with the town's debts").

Situations came through in what they said. Asked who owes the town and whom it owes, Aldric answered: "Thornby owes this town forty baskets, lent in the Lean Year, and pays slow in fish. Osbert Ashby holds my promise for grain sold, half paid. The gate-due keeps the guards who keep the road clear of wolves and outlaws." Mercy said of the gate-due: "the due at our gate drives carters like Silas Pike away and makes us poorer for it." `lives_wake.py` now checks that no consolidation is shown an empty identity, and records each identity rewrite's goals against the seeded ones.

*Earlier the same day:* a woken resident with an authored sheet had it installed as written (`sheet_persona`, no model call) instead of an identity a model writes from world facts. A resident without a sheet still gets the world-facts identity (`living/mind/src/mind/woken.rs`, `make_mind`). Before this, the merged build gave Wat Fenner, Agnes Fenner and Hester Crane a model-made persona ("I live here and watch what happens.") and no authored memories (`lives_wake.py`: 14 of 20). After it, 20 of 20. `verify-knowledge`'s `woken_mind.py` still proves the world-facts path: it takes the chosen resident's sheet out of its background first (`set_background`). It also needed two fixes for authored names: its newcomer is now Quorvan, since the island has people called Wren, and journal file names use underscores. All seven of its proofs pass, and `verify-minds` `wake` passes. Item 5, consolidation keeping the authored identity, is not made.

## Culture against mechanics

| In rules and the engine (all worlds) | In the island's seed content |
|---|---|
| hamlets as a dispersed site spec (`SiteSpec::dispersed`, `regions`), a hamlet layout style | which hamlets exist (counts are parameters), and who lives in them |
| choosing a site by `near` and `region` | "Coldwell", "Ashby", the Lakemead |
| knowing a way: stages along the roads, a point on a road (`living_rules::ways`; `SeedPlace::stages`, `along_m`, `between`) | the stone road, the fish road, the giants' track, the east road |
| sheet relations written as `relation` rows | names, kin, grudges, faiths |
| `threaten`, `yield`, `seize`, `give`, `take`, `store` (unchanged) | the outlaws' and carriers' starting ways; the Hearth, the Works Council, the tide lanterns, the cairns, the Old Green |
| marks are an item | prices, dues and debts as things people say and remember |

Settlement styles keep their cultures in the bible: rustic island names and the Hearth in Brackenford and the villages; works, contracts and the clock in Kettlebridge; short names and tide lanterns in Lanternquay; long stone names and cairns among the giants; plant names and the Old Green among the small folk.

## Authoring at scale

`living/tools/author_world.py island` plans a world from `living/seeds/worlds/island/`:

- `bible.md`: land, peoples, money and lacks, history, the world tensions, guidance for sheet writers;
- `world.json`: per settlement a brief, size, occupation mix, stores and ledger, and its **anchor people** (the people the world tensions hang on, with fixed names, households, roles and ties); the routes; the outlaws' road;
- `ways.json`: the starting ways the island adds or changes (seed content).

Stages (each cached on disk, so a rerun drafts only what is missing):

1. **Cast** (`cast/<settlement>.json`), one settlement at a time, so later ones see earlier names. A model drafts the households around the anchors, and 2–12 **situations** with every side's view. The tool then puts anchors back exactly as given, drops duplicate names (anchors elsewhere count as taken), and keeps occupations to the allowed list (with starting ways) and know-how to the rules' techniques. It asks for more households when a draft falls short of the target size.
2. **Sheets** (`sheets/<settlement>--<household>.json`): per household, with the situations its members are in (each member sees their own side; a person not in a situation does not know it).
3. **Ties both ways:** family, household, named ties and everyone in a shared situation must feel something about each other; missing sides are drafted.
4. **Review:** a second model reads every situation against its people's sheets and the family relations as each sheet states them, and lists contradictions. Flagged households are redrafted once with the notes. Results go to `review.json`.
5. **Checks without a model:** items in kits, stores and routes exist in `living/rules/src/catalog.rs`; every occupation has starting ways; a settlement's seeded stores leave a fifth of its storages free (a storage holds 120 things). A parent not on the island, or less than 14 years older, is noted and not linked (the sheet keeps the memory).
6. **Compile into the seed:** residents, stores and ledgers per settlement, new hamlet entries (`site: hamlet_village`, `near`, `region`), carriers' and outlaws' places, and the ways (`common`, `occupations`, `town_life.work`) merged into `living/seeds/island.json`. The settlements' other fields and the rest of the seed are kept.

Models: DeepSeek V4.1 Flash without thinking drafts (`deepseek-flash`, the fastest good model in [model cost](MODEL_COST.md)); GLM 5.3 Flash at `high` reviews. Every call's tokens are logged to `authoring-log.jsonl`.

## Placement: hamlets and known ways

### Hamlets (rules)

- `SiteSpec` gains `dispersed` and `regions`. A dispersed site is placed after every other kind of site, so the towns, villages and caves stay exactly where they were (checked: same centres for seed 7). It may stand on any not-too-rough ground of its region kinds (default meadow, forest, old forest, highland, beach), spread over the island (the existing distance term) and over region kinds (each one already in a kind of region counts against the next).
- The default island adds `hamlet` sites: 2–400, 3 per km², radius 26 m, 230 m apart. Seed 7 gets 9 (2 meadow, 2 forest, 2 old forest, 1 highland, 2 beach) with 2–5 houses each, 34 homes in all; a 4096 m land 33, an 8192 m one 133 (seed 7; native and WASM digests agree at both).
- **A step of staged generation, bounded in fuel** ([floors](FLOORS.md#staged-generation-and-the-largest-floor)): dispersed sites are placed in `land::Gen`'s own steps after the macro pass, at most 24 per step, and the roads as a graph are the planner's last step. Measured with `living/tools/land_fuel`: the hamlet steps cost at most 3.0 × 10⁹ (2.5% of a reducer's budget) at 8192 m. Island roads now run in parts (grid, 8 settlements routed per step, end), so the largest land's worst step went from 62% of a budget on main to 40% here. Same sites and roads as placing them in one go: the island's digests did not change when placement became steps.
- The `hamlet` settlement style is a small village from the fantasy kit: a green with a well, one street, barns and fields along its track (`settle.rs`).
- Every hamlet is joined to the road network like any settlement. Trunk roads grow from 4.8 to 6.6 km. The planner already writes their lots, structures and roads, so the authority, the game client (which draws every lot) and clients deriving the land need no new code. Digests change with the layout, as they should (tiles `9b403da95bba9407`, heights `0d2f77752781845c`, layout `408df4be210092eb`; the WASM authority, `floor_preview` and `lives_sites` natively on x86_64 agree).
- A garden or field inside a terraced zone is no longer laid across a terrace step: the step's edge becomes a wall, and `verify-generation` found one Kettlebridge garden cut through once the hamlets' roads had shifted the town's layout.

### Choosing a site (authority)

A seed entry may say `near` (a settlement placed before it) and `region` (region kinds). Such an entry takes the unused site of its kind in one of its regions, nearest the named settlement; entries without them take the next site of their kind as before (`island::match_seed`). So "the outlaws' steading in the woods near Brackenford" is seed content that survives a change of generator parameters.

### Knowing a way (rules + authority)

A walk across the island is too long for the authority's walk search: `Map::path` gives up after 6,000 expansions. Measured on seed 7 between settlement squares under 800 m apart (`lives_sites`, native release): **0 of 53 pairs** reach at 6,000 expansions, except pairs with a clear straight line; 20 of 53 at 30,000 (p50 2.7 ms); 44 at 100,000 (p50 7.8 ms, max 21.8 ms); all 53 at 400,000 (max 45.8 ms). Raising the budget per walk would cost tens of milliseconds in a 16.7 ms tick, so it is not the fix.

- `living_rules::ways`: the land's roads as a graph (every road's points every 6 m, junctions within 8 m, each plaza joined to the roads that end at it, trunk points marked), a shortest route along it, its trunk-road points, and evenly spaced stages. Test `ways::tests::settlements_join_along_the_roads_in_walkable_stages`: every pair of the 17 settlements is joined along the roads, and at most 2% of 120 m stages fail an ordinary 6,000-expansion search.
- A resident's place may say `stages: n` (up to 48): world creation writes `<name> 1` … `<name> n` along the roads from home to it (the last at the place itself); `along_m`: the point that far along the roads toward it; or `between: [A, B]`: the point of the trunk road between two settlements nearest home (the outlaws' watch). Routes are computed once, in `init`; the graph is dropped with the land.
- **Rule gap kept open:** long journeys for everyone else (a mind sending its body to another town, a newcomer walking to a village) still depend on the 6,000-expansion search. Hierarchical paths or road-following walks are an engine change, not part of this work.
- **Closed 2026-11-10** ([walking routes](PATHS.md)): every walk is planned leg by leg over regions and areas of chunks, so anyone reaches any reachable place. Seeded stages remain the residents' known ways, and they are no longer needed for a walk to succeed.

### Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
|---|---|---|---|---|---|---|
| World creation: relations from sheets | the resolved sheet (in memory) | `relation` (one row per sheet relation: about 9 per resident) | `relation.by_pair` (existing) | none: private | once | none; minds replace their own rows as before |
| World creation: author's places | hosted lots, the road graph (in memory), `place` of the actor | `place` (work + up to 32 stages per carrier; one per outlaw) | `place.actor` | none: private | once | none |
| Choosing hamlet sites | planned settlements (in memory) | — | — | — | once | — |
| Starting ways reading relations | `relation.by_pair` for the target in view | — | btree (existing) | — | per evaluation of a graph that filters by relation (as before) | — |

SpacetimeDB documentation consulted (2026-11-09; the live pages' selector shows 2.0.0, the pin is 2.14.1): [lifecycle](https://spacetimedb.com/docs/functions/reducers/lifecycle/) ("Runs once when the module is first published or when the database is cleared"; "Failure prevents publishing or clearing"), so the extra seeding cannot touch a running world; [performance](https://spacetimedb.com/docs/tables/performance/) ("batch them in a single reducer call"; "Be mindful of unbounded table growth"): all rows are written in `init`'s one transaction, a fixed number per resident; [indexes](https://spacetimedb.com/docs/tables/indexes/) ("Indexes consume additional memory and slow down inserts and updates"): no index added; [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations/): no table, column or reducer added, so nothing to migrate. Relations and places are private tables, as before.

## Measurements

**Tick cost at rest, base against this change** (`living/tools/bench.py`, one 600 s window per arm, the module's tick spans). Each arm is a fresh island world (seed 7, 2048 m) in the scratch container `lives-stdb` on the dev-box (AMD Ryzen AI Max+ 395, 32 threads, SpacetimeDB 2.14.1), measured from 32 s after publishing, with no minds, no subscribers and no players. The base is `origin/main` at `47e82a3` (the island's residents drawn from occupation counts), built from its own worktree. Windows: base 1 at 23:47–23:58 UTC+1 on 2026-11-09, while other agents' labs ran (1-minute load average 16–19); then this change 02:25–02:36 and base 2 02:36–02:47 back to back on 2026-11-10 (load average 4.2–5.8).

| Arm | People + animals | Ticks/s | Evaluations/s | Steering updates/s | p50 | p95 | p99 | Max | Over 16.7 ms | Tick work, ms/s |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base 1 | 261 + 34 | 60.0 | 365 | 39.9 | 1.16 | 2.11 | 2.80 | 22.7 | 1 of 30,288 | 61.1 |
| **this change** | **277 + 34** | 60.0 | 382 | 41.3 | **1.10** | **1.86** | **2.31** | **4.46** | 0 of 29,430 | **54.3** |
| base 2 | 265 + 34 | 60.0 | 369 | 45.3 | 0.99 | 1.69 | 2.12 | 3.79 | 0 of 30,114 | 50.7 |

Times in ms. Phases (ms of work per second; base 2 → change): slot evaluations 27.1 → 27.1, wakes 8.9 → 10.7, activity timers 9.8 → 11.9, motion 2.3 → 2.1.

- With 277 authored residents (16% of them in hamlets up to 1 km from a town), five carriers on long roads and relation-reading starting ways, the tick stays at the base's cost. The change's p50, p99 and tick work lie between the two base windows. The two base windows differ by about as much as the change differs from either, so one window per arm cannot separate a difference this small. It shows no cost at the scale of the 4 ms p99 bar.
- Evaluations per second rise with the population (365–369 → 382). Graphs reading `relation` rows (`friend`, `enemy`) do not show in the slot phase.
- **Seed and storage:** `island.json` grew from 13 kB to 1.8 MB, and the module from 8.5 to 12.3 MB, because the seed is compiled in. Each authored resident's `background` row carries its sheet (1–6 kB; private). Creation writes 2,348 `relation` rows and about 1,100 `place` rows (the carriers' stages among them), once. Nothing per tick grows.
- **World creation:** the town seats take 70 ms for Brackenford and 0.3–13 ms for each other settlement (`init.town.seat`). Land generation in WASM takes 3.3 s with the hamlets.
- This is the island at rest for 10 minutes, not the 216-character gate with observers and players, nor its 8 hours.

## Lab evidence

All on scratch `verify-lives-*` databases in the dev-box's own container `lives-stdb` (2.14.1, `127.0.0.1:3412`), built from this branch's working tree with `LIVING_SEED=island`, `rules.minds = false`. Evidence lies under `.local/living/verify/<run>/` on the dev-box. Copies of the last runs are in `.local/lives-run-0106-kept`, `-0134-kept` and `-0200-kept`.

### Placement (`verify-core/scripts/lives.py`, seat checks)

12 of 12 on the final world (`lives-0200`):

- all 277 people of the seed are placed with their sheets;
- all 9 hamlets are laid out and peopled where the seed's `near`/`region` asked;
- 2,348 `relation` rows (853 pairs felt both ways) were written at creation;
- every carrier knows its way as stages, and every outlaw has its watch on the stone road.

The lab worlds ran before the terrace-garden fix (tiles `fbc8a222a13d130e`, layout `06af78dda449e794`; homes, roads and routes are the same after it). The final build's digests are tiles `9b403da95bba9407`, heights `0d2f77752781845c`, layout `408df4be210092eb`, and the WASM authority matches the native generator.

`verify-generation` on the final build (`generation-lives-0256`):
- the island passes all 968 checks, including the new ones: 9 of 9 hamlets peopled where the seed asks; 2,348 of 2,348 sheet relations as `relation` rows; 9 residents' authored places with 60 stages, the longest 130.6 m;
- the island and Aske Coast compile offline to their committed seeds;
- repeatability passes;
- one unrelated failure, "Saltmere memberships" in the second drawn `realm` world: a resident died in the first seconds, which removes the membership but keeps the background. The first `realm` world passed the same check.

The free-tier wake check passes 20 of 20 on the final build (`lives-0256w`), and the placement checks 12 of 12.

### Residents act on their seeded situations (rows, no minds, no player)

Watched for 24 real minutes (two world days) with samples every 5 s; the driver calls no reducer. Final world `lives-0200`: 19 of 19 checks.

| Tension | Seeded as | What happened (rows) |
|---|---|---|
| **Trade between places** | stores with surpluses and lacks; 5 carriers with known ways and a starting routine of `take`, `goto`, `store` | All five carriers left with goods and walked their stages. **Silas Pike** walked the stone road (stages 2–12 of 12) to Brackenford's square, stored stone there (Brackenford's store +3 stone), took berries and walked back (Kettlebridge's store +15 berries over the window, with its quarriers' stone +15). **Tavvik** walked the giants' track to Kettlebridge's square (0.2 m). **Thistle Mossfoot** reached Reedmoor's square (3.5 m), stored fibre (+3), took fish (Reedmoor −8 fish) and set off home. The two fish runners covered 4 stages of 14 in the window (1.3–1.7 km roads). |
| **Hunger on the road** | nothing seeded beyond a carrier's 4 berries | In an earlier world (`lives-0042`), Thistle, hungry on the way home, ate the fish he was carrying, then gathered by the road. Nothing scripted it: the food desire outweighed carrying. |
| **The Coldwell outlaws** | fields lost, kin in Brackenford; a watch on the stone road between Kettlebridge and Brackenford; a starting way that threatens an outsider in sight when a friend is near and seizes from someone who yielded | The four outlaws kept their watch all day (275–278 of 278 samples). They **threatened an outsider 9 times** (`threat` chronicle rows: Marta Hale, Ned Hale and Kai Ostrander, each several times). The outsider was the lab's player character, left standing in Coldwell after the wake check, not a carrier. **No carrier was stopped**: the samples put Silas 9–40 m from them as he walked by, beyond the 11 m day sight. The road runs past their houses, but a carrier walking from stage to stage passes 20–30 m off. The outsider did not yield (a player has no instinct), so there was no seizure. |
| **Friends and enemies** | sheet relations as `relation` rows; common ways that wave at a friend in sight away from home, stare (`face`) at an enemy close by, and nod to a friend first in the evening | Gestures aimed at someone, by the actor's seeded relation to the target: waves 684 at friends, 3 at enemies, 4 others; nods 996 at friends, 3 at enemies, 122 at others; faces 2,518 at friends, 188 at enemies, 1,586 at others (most faces are the general manners rule turning toward whoever is close). |
| **Wolves on the town road** | (unchanged island pack) | Marta Tolley of Brackenford was killed by Rook of the road pack near the town. |

The trade rows took four worlds to reach. Each failure was in content or a starting way, never a rule, and each is fixed in the generator, the tool or the seed:

1. **Seeded stores were over capacity.** A storage holds 120 things (`storage_holds`), and the shipped island already overfilled its stores (Brackenford 298 in two, Kettlebridge 256 in one), so every `store` was refused as full. The tool now fails a seed whose stores are over 80% of capacity.
2. **A carrier oscillated at its first stage:** "near stage *k* within 10 m" stops holding a few steps into the next leg, so the routine sent it back. Rules now hold for a whole leg (reach).
3. **A carrier cut across the woods:** a large reach skipped stages and left the road. The reach is now set per route.
4. **Route graphs were too big:** 14 stages each way exceeded a composite's 12 children (nested), then 28 exceeded a graph's 80 nodes (stages capped).

### A woken resident knows its past and its people (`verify-minds/scripts/lives_wake.py`)

A player speaks to a resident, which wakes it; the real `living-mind` runs with a scratch Neo4j and installs the authored sheet without a model call.

- **Free tier (fake model), 19 of 20 → 20 of 20 after a driver fix:** Wat Fenner, Agnes Fenner and Hester Crane were woken by speech. Their 12, 11 and 20 relation rows existed before waking and matched their sheets, and each persona is its authored narrative. Each first prompt names 12/12, 11/11 and 17/20 of the people in its sheet and recalls 2–4 authored memories (`[before all this]`). No resident's prompt held anyone else's secret; Agnes's and Hester's own secrets reached only their own prompts. (The one failure was the driver reading a consolidation as Wat's "first prompt"; his think and deliberate prompts carry 2 authored memories each.)
- **Paid tier (DeepSeek V4.1 Flash, no thinking), 22 of 25:** four residents of places at odds, asked about each other:
  - **Josiah Crane** (Kettlebridge), asked about Brackenford and its Reeve: "Brackenford is a town that takes a due at every gate and calls it order. Its Reeve I judge by what his road costs my carters — and it has cost them dear."
  - **Mara Quell** (Lanternquay), asked about Kettlebridge: "Kettlebridge sells stone dear and calls it trade. They sent us a little stone at full price after the surge and named the sum a kindness. I am Mara Quell, Harbour Warden of Lanternquay, and I do not pay for a wall I have not seen."
  - **Marta Hale** (Coldwell), asked why she lives in the woods: "Because it is ours, and no one has yet made us a better offer. Who are you, and what do you want at Coldwell?" and then: "keep clear of Kai; he is quicker with his hands than with his manners."
  - **Wat Fenner** (Brackenford's south gate), asked about the Kettlebridge folk: "Morning to you. You've come to the south gate of Brackenford. What's your business here?" He gave a stranger nothing.

  Each spoke from its own side of the seeded tensions (the gate-due, the stone price after the Surge, the taken fields), knew its people and recalled authored memories, and held no other resident's secret.
- **Finding (the three paid failures): identity drift at the first consolidation.** Within about a minute, the consolidation rewrote three authored personas with wrong facts: "Wat Fenner, a guard of **Kettlebridge**", "Josiah Crane, quarry-master of **Brackenford**". The consolidation prompt does not carry the resident's world facts: Wat's never names Brackenford, so the model took the town from the stranger's question. The authored memories and relations stay (formative), but the persona narrative drifted. This is for the mind service after `townlife-2`: put the background's facts (settlement, occupation, household) in the consolidation prompt, and revise an authored identity only on lived evidence.

### Nothing contradicts across two residents' sheets

- **Deterministic:**
  - every family, household, named and shared-situation tie is felt both ways (0 missing after the fill pass; the 642 one-sided relations are feelings toward someone who need not know you);
  - parents exist and are at least 14 years older (8 links dropped, 70 named parents who are dead or never cast kept in prose only);
  - every occupation has starting ways, and every item and technique exists in the rules.
- **Review by a second model** (GLM 5.3 Flash at high; DeepSeek with thinking when GLM ran out of tokens on two settlements) over every situation and its people's sheets: 48 issues in the first pass (0 in Elmwick, Highfold and Tanglewood; 10 in Lanternquay). Examples: "Pell's sheet labels Kai 'friend' while Kai's sheet calls Pell his younger brother"; "Sayer's memory says she carried Robin to the chapel, but Elspeth, Marta, Robin and Agnes all say Elspeth came to Coldwell"; "Silas labels Corin 'foreman's wife', but she is Ezra's wife". The flagged households were redrafted once with the notes.
- **Spot checks across settlements** agree on shared facts from different sides:
  - Hester and Josiah Crane, Mara Quell and Juno Reyes all hold that Lanternquay owes Kettlebridge for the last load at "a drowning man's price";
  - Agnes Fenner's sheet keeps her secret (food to Coldwell) and her husband Wat's does not know it;
  - Marta Hale knows her sister's secret and keeps it ("keep_agnes_secret");
  - Hester's relief at the broken match is her secret alone.

### Not covered

- Woken residents over hours, and minds of outlaws or carriers deciding for themselves.
- The 216-character gate with seeded residents.
- A carrier robbed on the road (see above).
- `living-game` drawing hamlets was checked by build only: it draws every lot, so hamlets appear, but no screenshot was taken.
- Seeds other than the island.

## Spend

Authoring the island, from the journal of every call (`living/seeds/worlds/island/authoring-log.jsonl`), at [model cost](MODEL_COST.md) prices:

| Model | Purpose | Calls | Prompt (cached) | Output | € |
|---|---|---:|---:|---:|---:|
| DeepSeek V4.1 Flash | casts (incl. top-ups) | 20 | 381,183 (60,416) | 74,984 | 0.16 |
| DeepSeek V4.1 Flash | sheets | 148 | 2,890,806 (2,710,272) | 482,134 | 0.55 |
| DeepSeek V4.1 Flash | ties both ways | 133 | 2,837,775 (2,648,960) | 20,367 | 0.09 |
| GLM 5.3 Flash (high) | review | 25 | 338,858 (41,472) | 255,738 | 0.15 |
| DeepSeek V4.1 Flash (high) | review fallback | 2 | 46,176 (0) | 87,510 | 0.10 |
| **All** | | **328** | **6.49M (5.46M)** | **0.92M** | **€1.05** |

It includes a discarded first Brackenford cast (too small, repeated names). The paid lab run (four woken residents, DeepSeek V4.1 Flash) is in that run's journal: 24 calls, 174,075 prompt tokens (63,360 cached) and 14,073 output, about €0.04.

## Rule gaps

What the tensions need that the rules do not have yet. Each is a general rule, written here so it is not scripted around:

1. **A community's regard for another community.** Today a stranger from Kettlebridge is just an `outsider` to a Brackenford resident, the same as anyone. Proposed: a seed-data table of regards between communities (value, label, why), read by the relation filter when no personal relation exists (`enemy` / `friend` / a label such as `rival town`) and visible to minds as a stance. Writable by a community's head through an act, so it can change. **Built on `rules-2` (2026-11-10)** as seeded stance records: 13 for the island from the bible's tensions, read by relation filters, laws and minds ([world rules](WORLD_RULES.md#standing-and-regard-stances)). Not built: changing a regard by an act (the world has no heads), and `perceived_of` reading it.
2. **A toll as an ordinary demand.** A guard or an outlaw can threaten and seize; a gate cannot ask for a due. Proposed: `demand` (an act aimed at a person, with an item and quantity), whose effect is that the target perceives the demand and may `give`; refusing is not acting. Walking through without paying stays possible; what follows is the demander's choice. It would serve gate-dues, rents, the outlaws' "share" and debts alike. **Built on `rules-2`** as Rhai content on records: the target is told, a give pays it, and both are told when it is paid or falls due unpaid ([world rules](WORLD_RULES.md#content-built-from-the-primitives)).
3. **Debts and rents between people and communities.** They exist as words on signs and in sheets. Nothing records an obligation that both sides can point to. Proposed: a written tally is just a tablet or sign (exists); a mechanic is needed only if trials show people cannot keep track. **On `rules-2`** an agreement (`offer_terms` → `accept`) is a record both sides are told about and that counts deliveries; a rent is a floor's or a world's rule on the same primitives ([world rules](WORLD_RULES.md#how-a-floor-adds-its-own-rules)).
4. **Land and field ownership.** Fields belong to nobody in the rules; the Coldwell grievance and the Lakemead dispute live only in sheets. Proposed: a lot's owner (household), set at creation and by acts, read by gather (taking from someone's field is theft, like a store).
5. **Long journeys** for anyone without a seeded way (above). Closed by [walking routes](PATHS.md).
6. **Prices.** Marks exist as an item and `offer`/`accept` trade them; nothing says what a thing is worth in a place. This is deliberately left to people, but instinct-only stalls cannot sell.
7. **Exile and outlawry.** Being declared an outlaw is words on a gate; community membership has `leave` but no expulsion.
8. **Watching a road.** Day sight is 11 m. A watch on the stone road 20–30 m from where walkers pass never sees them, and walkers cut between road points. An ambush needs either a narrow place (a ford, a bridge, a gate) or a sense that reaches further than sight (hearing footsteps, a lookout's skill). Found in the lab: the outlaws threatened the outsider who came to their steading, not the carrier who walked past.
9. **Markets fill up.** A storage holds 120 things. Farmers store berries all day and nothing takes goods out but eating and carriers, so a market store fills and then refuses everyone, carriers included. A market that sells to strangers, spoilage of stored food, or a second store per market would each be a rule or a seed choice.

## Every person a mind

Decided by the owner on 2026-11-11 after the first play-test, where the residents felt like NPCs: every person is a full LLM mind from the start. The woken residents (instinct-only until someone engaged them; `woken`, `prior`, the `wakes`/`woken_ring`/`woken_stage` laws) were a token-saving idea for test fixtures and could be used by accident, so they are gone, and so is the seed rule `rules.minds = false` ([town life, layer 2](TOWN_LIFE.md#layer-2-residents-who-answer)). Animals keep their cheap minds (asked only near people). Trials that run one mind in a scripted world keep using the mind service's `LIVING_ONLY`.

**What each resident's mind starts from.** At the service's start (`mind/facts.rs`): its world facts (household, family, settlement, every given place with its lot) marked `world`, then its sheet as written (`authored`), or one identity call from the facts for a resident without a sheet. Given places (`place.given`: work, square, inn, evening, a known way's stages) are world facts a mind's projection never drops, for every resident. A new character's first deliberation is not held back by the thinking throttle (its starting graph is not a thought).

**Level of detail and caps at island scale** (311 characters: 277 people, 34 animals). The woken residents' stage cap (6 per settlement) went with them. What remains:

- `LIVING_LOD` is off by default. The shipped models file routes people through the `people` mix, which chooses by stage, so attention is tracked: with no player anywhere every person is off stage and deliberates with the off-stage model (GLM 5.3 Flash), talks with DeepSeek V4.1 Flash.
- The thinking throttle (`think_min_s`, 20 real seconds for people) and reflection (`reflect_s`, a deliberation after 240–360 quiet real seconds) are per person; consolidation waits at least `consolidate_min_s` (90 s) between integrations.
- **The binding cap at island scale is the mind service's `LIVING_CONCURRENCY` (default 64).** The scheduler keeps a quarter of it for interactive calls, so 48 routine and background calls are in flight at most. At 5–11 s a call that admits about 400 calls a minute, while the island asked for more: in the first 12 real minutes on the Spark, routine calls (think, deliberate) waited 19 s at the median and 55 s at p95 before they were sent (a reason waited up to two game hours for its decision). With `LIVING_CONCURRENCY=192` (the default since this change) the same world's routine calls wait 0 s at the median, 10.4 s at p95 and 45 s at most over two hours (the p95 comes from minutes of 650–765 calls). The per-profile rate (`requests_per_minute`, adaptive from 600 to the provider's 1,200) never bound; Mistral answered 1.7 % of GLM Flash calls at about 350 a minute with 429 "not enough capacity".
- `LIVING_LLM_PER_MIN` is 0 (no global cap) unless set.

**Expected calls per person per game hour, from the code** (no player, level of detail off; a game hour is 30 real seconds): a deliberation is two calls (think, then deliberate). Non-urgent deliberations are at most one per 20 real seconds, 1.5 a game hour (3 calls); reflection guarantees at least one per 8–12 quiet game hours; a new day adds one a game day; plans that finish, failures, feelings (restless, lonely, a child longed for) and bodily alarms ask in between. Consolidation is at most one per 90 real seconds (0.33 a game hour), when what was lived is salient enough. Talk turns answer lines addressed to the person. The ceiling is about 3.5 calls per person per game hour plus talk; what minds actually ask is measured below.

**The authority's cost.** Every resident's percepts are now experiences its mind reads: on the Spark, 297 experience rows a second against 0.2 on main's instinct-only island (`bench.py`, 120 s windows, both at 59.9 ticks a second). Tick work rose from 63 to 124 ms a second (slot evaluation 31 → 65, wakes 12.5 → 40.9); p50 1.34 → 2.47 ms, p99 3.3 → 7.4 ms, max 4.2 → 11.2 ms, none over 16.7 ms. The experience window stays bounded (400 per character, about 110,000 rows for the island).

## Measured on the Spark

**Setup.** The island (seed 7, 2048 m, 277 people and 34 animals at the start) on the DGX Spark, two arms side by side for 125 real minutes each (10.4 game days, one winter: days 7–8 of the 8-day year), own containers (`slop-lives-*`), nobody playing. **lives-2** (`efcd489` with the new-day fix `45d4ac6`): every person a mind, the models file as shipped (the `people` mix: GLM 5.3 Flash to think, deliberate, consolidate and reorganize off stage, DeepSeek V4.1 Flash to talk), `LIVING_CONCURRENCY=192`, no `LIVING_ONLY`, no level of detail. **Control**: `main` at `445db09`, residents instinct-only (nobody engages them, so nobody wakes; no mind service). Both sampled every 10 real seconds by `living/tools/lives_lab.py`. Evidence: `.local/living/lives-2/spark/` on the Mac (`l2/report.md`, `main/report.md`, journals, mind logs, bench).

Two earlier lives-2 starts were stopped and are kept: at the default concurrency 64 (12 minutes; deliberations queued up to a minute, above) and with the new-day spam (16 minutes; `45d4ac6`).

| | Control (main, instinct-only) | lives-2 (every person a mind) |
|---|---:|---:|
| Starvation deaths | 6 | 0 |
| Cold deaths | 0 | 0 |
| Killed by wolves / old age | 2 / 3 | 0 / 3 |
| Births | 0 | 61 |
| Hunger, median of people (days 2–7) | 57–61 | 20–22 |
| People over 50 hunger (days 2–7; days 8–11) | 72–85 %; 70–97 % | ≤ 1 %; 5–14 % |
| Activity changed between two samples (20 game minutes): median / p95 / max | 18 % / 62 % / 100 % | 28 % / 41 % / 75 % |
| Doing the most common activity, p95 of samples | 97.5 % | 63.5 % |
| Shelter entry after 16:00 on dry days: IQR | 0.7–4.7 h | 3.4–4.3 h |
| Most people sheltering in one 30 minutes (dry days; rainy days) | 23–46 %; 87–100 % | 11–13 %; 25–37 % |
| Speech lines per person per game day (speakers) | 0 (0) | 1.3 (274) |
| Awake time by what the body does: walking / resting / work / idle / gestures / eating and getting food | 19 / 37 / 18 / 16 / 10 / 1.2 % | 33 / 29 / 20 / 10 / 7 / 1.7 % |

- **Lockstep is gone.** Each day people go in over four hours instead of within one half hour; at most three quarters of people change what they do in any 20 game minutes (all of them, in the control, at 22:00 and 23:00 when the shared evening ended), and the most common activity never takes more than two thirds of the town. Minds change what they do more often one by one (median 28 % against 18 % per sample), not together.
- **Survival is secondary, until the babies.** Of 8,890 plans the minds made, 3.5 % were only about food or warmth; 82.5 % involved other people and 75 % work (by their words: `lives_lab.py`, "plans"). Nobody starved or froze; the control lost six to hunger. But the minds chose to have children: 61 births in ten game days (the drive "You long for a child" is the second most common feeling), with a one-game-day gestation. After the winter's no-growth days, with sixty new mouths, the town stores were bare by day 10 and many minds' days turned to finding berries for crying babies (`timelines-l2-day10.md`). Hunger rose from day 8 (p90 41 → 54). The birth rate, not the needs law, is now what pulls survival back to the centre.
- **What a day looks like.** The ten sampled people's day 10, with their plans, is in `timelines-l2-day10.md`: Aldric Marrow keeps the ledger at his post from 07:12 and plans the town's reckoning at the inn; Jem Coombe rises at 06:44 to walk the hives his father has just given him; Godric Wade gathers berries and gives them out to the foundlings he promised to feed; Sella Mackerel rises at 04:37 and is in bed by 19:30.

**Cost and load** (lives-2, journal over the sampled window): 51,202 calls, **$71.23** ($73.02 with the ten minutes the mind ran on after sampling). $0.123 per person per real hour, $0.025 per person per game day, 0.74 calls per person per game hour (1.49 per real minute for people; the code's ceiling is about 3.5 a game hour). By purpose: deliberate $26.0, consolidate $20.7, think $15.6, reorganize $6.5, talk $2.4. Calls per minute: median 388, p95 666, max 765 (the provider's limit is about 1,333); tokens per minute: median 3.6 M, p95 6.5 M, max 7.7 M (limit about 10.7 M). 66 calls (0.13 %) came back 429 "not enough capacity". Why minds were asked to think (each request may name several reasons): their new day 27.6 %, a finished plan 19.4 %, a quiet moment (reflection) 18.6 %, feelings 12.9 % (mostly longing for a child), the freezing alarm on winter and rainy nights 8.2 %.

**Recommendation for the call budget.** Full minds suit the island: about $34 a real hour, at 50–60 % of the provider's limits at peaks (p95 minutes). They will not scale as they are: the 2,000-character target (about 1,600 people) would need about 2,400 calls and 23 M tokens a minute at the median, past both limits. In order:

1. **A level of detail in game time.** The shipped off-stage gap (`LIVING_LOD_THINK_S` 600 s) is 20 game hours, which would make people nobody watches think once a day. Replaying this journal with nobody on stage (`mind_load.py`): a 180 s gap (6 game hours; prompt 45 s, consolidation 270 s, talk 60 s) cuts calls by 53 %, 90 s by 39 %, 600 s by 74 %. Recommended: `LIVING_LOD=1` with 180 s off stage, unchanged on stage, for worlds above about 400 people.
2. **Fewer routine reasons.** The new day and reflection are nearly half of all reasons; a reflection that falls within a few game hours of the new day adds little. Consolidation is 29 % of the cost: `consolidate_min_s` 90 → 300 s would roughly halve it.
3. **Concurrency.** Keep `LIVING_CONCURRENCY` at 192 for the island (about 120 calls in flight at the measured 17.7 s mean latency); scale it with the number of minds.
4. **Births.** Before longer runs: a longer gestation, or a weaker longing for a child, as Rhai laws (`gestation_days`, the broody drive in `brain.rs`); otherwise each winter turns every mind back to food.

**Authority cost** is above, in "Every person a mind" (tick work 63 → 124 ms a second).

**Spend for this work:** the island's wants fill $0.07 (DeepSeek V4.1 Flash, 92 calls); the Spark runs $4.12 (concurrency 64), $9.39 (new-day spam) and $73.02 (the measured arm): **$86.60** in all, at the prices in `living/tools/trials.py`.

## Survival made secondary

The owner's first play-test (2026-11-11): survival was too hard and too central. The worlds start with a setup, not from nothing, so getting by should take a small share of a person's day and leave the rest to their life. The numbers are Rhai laws (`living/scripts/skills.rhai`: `rates`, `body_state`, `freezing`, `meal`) and seed data (the island's `ways.top` food desire and its "find food and eat" routine).

**Game time.** A game day is 12 real minutes (`DEFAULT_DAY_MS`); a game hour is 30 real seconds. Rates below are per real minute (per game day in brackets).

| Target | Before | After |
|---|---|---|
| A healthy adult wants a meal two or three times a game day | hunger +5/min (60/day); the food desire won over work at hunger ≈ 60 and lost again a few points lower, so people nibbled one item at a time near "hungry" all day | hunger +4/min (48/day) × the body's `appetite` gene; the island's food desire (`base -0.2, hunger 3.6`) wins over work at about 25; a meal (`eat`, `qty` 4) eats as many items as bring hunger to about 5 (`meal(a)`): about 20 hunger a meal, **2.4 meals a game day** |
| A full game day hungry before it becomes dangerous | "hungry" from 55; starving at 100 came 0.75 game days later; starving took 6 health a minute (dead in about 1.4 game days) | "hungry" from 50, starving at 100: **1.04 game days** later; starving takes 4 a minute (25 minutes, about two game days, to kill a healthy body). From the last meal to death is about four game days |
| Ordinary nights are uncomfortable outside, not harmful | a night outside without fire, shelter or a cloak took 2 health a minute (5 in winter), and the "You are freezing" alarm asked every outdoor mind to deliberate as night fell | an ordinary cold night tires (−1.5 energy a minute ÷ `hardiness`) and takes no health; the body still looks and feels cold |
| Only winter nights or storms hurt | — | `freezing(a)`: a winter night takes 3 health a minute, a night in the rain 1.5 (both ÷ `hardiness`), without a fire, shelter or warm cloak; the freezing alarm follows the health it takes, so it no longer fires on ordinary nights |

**Stores and food from the world.** Nothing spawns food: berries regrow on bushes (1.2 a minute), fish at fishing spots (1.4), and farmers, fishers and hunters bring them in by their starting ways; town stores and households start with the seed's stores and kits. At the new rates a person eats about 4 berries' worth a game day instead of 5. Whether that is enough for normal life is measured, not assumed: starvation and cold deaths on the Spark, below.

**Changed with it.** The rules tests that pin the needs law (`rules/src/script.rs`: rates by activity and night, infant appearance against cold damage, the parameter law against the whole computation, food and injury appearance; `floors.rs`, where a frozen floor now overrides `freezing` too) and verify-core's `needs` and `infant` scenes (a cloak or shelter removes the cold's tiring; a summer night does not hurt).

## No lockstep

At the play-test, everyone looked for shelter at the same moment when night fell. Nothing scripted it, but every cause was shared by everyone at once:

1. **The dawn broadcast.** `tick.rs` asked every person to deliberate at 06:00 ("Dawn of day N. A new day."), a scheduled event and an urgent reason that skipped the thinking throttle: 277 deliberations in one burst every game day.
2. **The world's clock in every starting graph.** Every resident had the same top-level desires, weighted by the world's `night` and `day` flags (sleep `night 0.6`, home `night 0.5`, work `day 0.5`), and the same evening routine (`hour` 17.5–22). At 20:00 every weight flipped for everyone in the same tick.
3. **The cold law and its alarm.** At nightfall every body outside without fire or shelter began to lose health in the same tick, and the "You are freezing" alarm asked every outdoor mind to deliberate at once.
4. **Identical thresholds.** The same weights everywhere meant the same hunger at which everyone turned to food, the same pitch at which rain sent everyone in.

What replaced them (general rules and seeded data; no role types, no scripts):

- **A rhythm per person** (`rhythm` table, private; `seed::drawn_rhythm`): when they rise (about 06:00 ± 0.8 h, 04:00–09:00), when they go to bed (about 16 ± 1 waking hours later, 19:30–02:30) and how many hours before bed are their evening (1.5–4.5). A seed may give a resident's (`residents[].rhythm`: `rises`, `sleeps` (past 24 for after midnight), `evening_hours`, and since `lives-3` `works` and `second_sleep`: [below](#rhythms-at-any-hour-and-cullets-trades)); whatever it leaves out is drawn from the person's id alone, so the world's random stream and its generation digests do not change. Newborns get one at birth.
- **Graphs read one's own day.** New weights and conditions `bedtime` and `evening` (`rules/src/graph.rs`; `common::day_phase`): the body's own hours, not the world's. The island's and the repertoire's starting desires use them: sleep `bedtime 1.2`, home `bedtime 0.6`, work `base 0.7, bedtime -0.9, evening -0.4`, and the evening routine runs in one's own evening. `night` and `hour` stay for darkness and the clock. Minds' prompts list them.
- **Evening habits.** `town_life.evening` may name `home` (an evening in) and `work` (working late) beside the inn and the square; the island alternates inn, home, square, work by household.
- **Desires weighed a little differently by each person.** At seeding, a founder's starting desires are varied the way a child's are varied from its parent's (`genes::vary_ways`, drawn from the person's id): weights ±8 % typical, occasionally more. Rain sends most people in, not all (`rain 1.0` against work's 0.7).
- **Tolerance as genes.** `appetite` (how fast hunger grows) and `hardiness` (what cold and wet take) are constitution genes, ±12 % typical, inherited like the others; the needs law reads them (`appetite_gene`, `hardiness_gene`). One can tell one's own: "always hungry", "quick to feel the cold".
- **A new day at one's own rising.** The dawn broadcast is gone. A person's new day begins within three hours of its own `rise_h`, once a game day: a "A new day begins for you" feeling and a deliberation request, which goes through the thinking throttle like any other (not urgent).
- **What minds see.** A person's prompt says when they usually rise and go to bed and how long their evening is (`daily_life` in `mind.rs`).

## Rhythms at any hour and Cullet's trades

Built on branch `lives-3` (2026-11-11), for two gaps Cullet's cast exposed (`author_world.py cullet --check`): a seed's rising hour was clamped to 0–12, so Thessaly Marl (rises 14:00) and Anselm Faro (13:00) would have risen at noon; and 25 of Cullet's trades had no starting ways, so their people would have started as foragers. Everything here is a person's starting values of the routines everyone has, and seed data; the engine gained no notion of a trade.

### The rhythm format

A seed's `residents[].rhythm` (`seed::SeedRhythm`), every field optional:

| Field | Meaning | Limits |
| --- | --- | --- |
| `rises` | the hour they rise, any hour | taken mod 24 |
| `sleeps` | the hour they go to bed (past 24 for after midnight); stored as the next such hour after rising | 8 to 22 hours after rising; without it, the drawn day's length |
| `evening_hours` | the hours before bed that are their evening | 0 to 8 |
| `works` | their working hours `[from, to]`, across midnight as `[22, 6]` or `[22, 30]` | one span; an empty span is none |
| `second_sleep` | a second sleep in the day `[from, to]`, e.g. a baker's afternoon | one span |

**Storage.** The private `rhythm` table keeps `rise_h`, `bed_h` (in `rise_h + 8 ..= rise_h + 22`), `evening_h` and `last_day` as before, and four columns appended with `#[default(0.0f32)]`: `work_from_h`, `work_to_h`, `nap_from_h`, `nap_to_h` (an end may pass 24; an end not after its start is none). Existing rows read 0 and 0: no working hours, no second sleep. Bindings regenerated (`rhythm_type.rs`, the only generated file that changed).

**What graphs read** (`living_rules::rhythm::Hours::phase`, through `common::day_phase`):

- `bedtime`: from going to bed until rising, and during a second sleep.
- `evening`: the hours before bed, not during a second sleep.
- `work_hours` (new weight and condition, `{"work_hours": true}`): within one's working hours; with none set, every waking hour outside one's evening. Minds' graph grammar lists it.

Hours from rising run `rise .. rise + 24`, so a bedtime past midnight compares in one range. The old rule pivoted at noon; for every drawn rhythm (all a seed without `rhythm` has: every world before Cullet) the new rule makes exactly the same comparisons, so their bedtime and evening are unchanged at every instant (authority test `seed::tests::drawn_rhythms_keep_their_phase`: 20,000 drawn rhythms, two instants a minute each; it found one difference within float rounding of rising in a first draft, which the rule now keeps). Drawn rhythms set no working hours and no second sleep, the varied ways draw nothing for a weight a graph does not have (`genes::vary_ways`), and no old seed's graph has `work_hours`: old seeds' rhythms, graphs and behaviour are what they were.

**Sleep follows tiredness more than the clock**, as SMALL_CITY asks: the starting `sleep` desire is still `-0.7 + tired × 1.3 + exhausted + bedtime × 1.2`; the rhythm only moves where its `bedtime` falls. A person's new day begins within three hours of its own rising (not of a second sleep).

**Minds** are told their hours: "Your days: you usually rise about 14:00 and go to bed about 07:00; the last 1 hours before bed are your evening. You usually work 22:00 to 06:00." and, with a second sleep, "You sleep again from 13:00 to 19:00." (`daily_life`).

**Cullet's cast** (`cast.json`) keeps its own day format (`wakes`, `sleep_h`, `works` as spans, `work_at`, `evening`), now with an optional `second_sleep` and a free `note`. `author_world.py` compiles it into the seed's fields (`seed_rhythm`): one working span, from the first start to the last end when that is at most 12 hours, else the longest span (Chidi Okoro 05:00–16:00; Hobb Fenwick's 19:00 cistern hour is left to his evening; Benedikt Orme 09:00–17:00). Pieter Achterberg's hours are the owner's reading: asleep 22:00–02:30 and 13:00–19:00 (`sleep_h` 4.5, `second_sleep` [13, 19]). The wrack gatherers keep fixed early hours until a tide exists; their rhythm's `note` says so.

### Cullet's trades

Cullet's starting ways are `living/seeds/worlds/cullet/ways.json`, merged into `living/seeds/cullet.json` by `cullet_plan.py` as its `ways` (`top`, `common`, `occupations`) and `town_life`. They are starting graphs the character owns and may change, keyed by the occupation string as every world's are (`seed::give_repertoire`). `common` is the island's routines with Cullet's own `find food and eat` (the store, root plots, greens, fishing spots). The `top` is the island's with one change: the work desire is `base 0.1 + work_hours × 0.8 − bedtime × 0.9 − evening × 0.4`, so work comes in one's own hours and outside them is a weak pull, below company. The routines use the rules' kinds and skills (`feed`, `make`, `gather`, `take`, `store`, `keep`) and keep their post where the world has no such thing yet. The plan places no furnace, oven, smokehouse or lamp and no `kelp_bed`, `peat_bank`, `greens_bed` or `root_plot` nodes yet (its resources are of kinds `kelp`, `peat`, `greens`, `roots`, which the rules do not have); those routines act as soon as the world has them.

| Trade (people) | Workplace (`town_life.work`; a resident's own `work_at` stands first) | Starting routine | What it does, in order |
| --- | --- | --- | --- |
| glassmaster (1) | `lot:cone` | keep the melt | make glass at the furnace; feed it peat; take sand, ash, peat from a storage; go to work; keep |
| blower (2) | `lot:cone` | blow glass | store glass (3+); make glass at the furnace; take sand and ash; go to work; keep |
| stoker (3) | `lot:cone` | stoke the Cone | feed the furnace peat; take peat; go to work; keep |
| retired_blower (1) | `lot:cone` | watch the Cone | go to work; rest there |
| cullet_sorter (1) | `lot:cullet_shed` | sort the cullet | go to work; keep |
| glazier (1), lehr_keeper (1) | `lot:lehr_house` | glaze; keep the lehr | go to work; keep |
| grower (5) | `greens_bed`, `lot:glasshouse_1` | tend the glasshouse | store greens (4+); go to work; gather greens; keep |
| root_grower (2) | `root_plot`, `garden` | tend the roots | store roots (6+); go to work; gather roots; keep |
| peat_cutter (3) | `peat_bank`, `lot:peat_barn` | cut peat | carry 8 peat to the peat barn and store it; go to work; gather peat; keep |
| wrack_gatherer (3) | `kelp_bed`, `lot:ash_house` | gather wrack | carry 8 kelp to the ash house and store it; go to work; gather kelp; keep |
| ash_burner (1) | `lot:ash_house` | burn kelp to ash | store ash; make ash at a hearth, the furnace or a campfire; take kelp; go to work; keep |
| baker (1) | `lot:batch` | bake at the Batch | feed the oven peat; bake roots; store baked roots; take roots and peat; go to work; keep |
| smoker (1) | `lot:smokehouse_1`, `lot:smokehouse_2` | smoke fish | feed the smokehouse; smoke fish; store it; take fish and peat; go to work; keep |
| oil_renderer (1) | `lot:lamp_house` | render lamp oil | store lamp oil; render it at a fire; take fish; go to work; keep |
| lamp_keeper (1) | `lot:watchglass` | keep the lamps | feed a lamp lamp oil; take lamp oil; go to work; keep |
| cook (1) | `lot:marver` | keep the kitchen | cook fish at a hearth or campfire; go to work; keep |
| server (1) | `lot:marver` | serve at the Marver | go to work; keep |
| fisher (8) | `fishing_spot`, `lot:fish_steps` | fishing | carry 4 fish to the Store; go to work; fish; keep |
| line_maker (1) | `fishing_spot`, `lot:net_loft_2` | fish and make lines | as a fisher |
| net_mender (1) | `lot:fish_steps` | mend nets | go to work; keep |
| boatwright (2) | `lot:dry_dock`, `lot:boatshed` | work on the boats | go to work; keep |
| porter (1) | `lot:store`, `lot:heron` | carry for the Store | go to work; keep |
| tally_keeper (1), reader (2) | `lot:counting_house`; `lot:readers_house` | keep the tally; teach and read | read a sign in reach; go to work; keep |
| healer (1) | `lot:readers_house`, `hall` | tend the hurt | tend someone hurt in sight; go to work; keep |
| washer (1), pot_maker (1) | `lot:wash_house`; `lot:pot_house` | keep the wash-house; make pots | go to work; keep |
| mason (1) | `boulder`, `workshop` | mend walls | store stone; go to work; gather stone; keep |
| warden (1) | `lot:hanger_cottage` | keep the Hanger | go to work; keep (she fells nothing) |
| child (13; Kit Calloway, 14, is a boatwright) | — | play | the island's (anyone young starts with it whatever their trade) |

`town_life.places` gives everyone `square`, `store`, `peat barn` and `ash house`; `town_life.evening` is `home` for anyone without an evening place of their own (every cast member has one). No guardrail stops anyone doing anything else: a mind may rework any of it.

### SpacetimeDB documentation consulted

Read for this change (the site's 2.0.0 pages; the service and crates are 2.14.1, and the site lists no 2.14 pages): [automatic migrations](https://spacetimedb.com/docs/databases/automatic-migrations) ("Adding new columns to the end of a table with a default value" is allowed; "The new column must be added at the end of the table definition and must have a default value specified"; non-updated clients "will not be aware of the new column"), [default values](https://spacetimedb.com/docs/tables/default-values) ("existing rows are automatically populated with that default"; the expression must be const-evaluable; no stated type restriction, and the repository already uses `#[default(0.0f32)]` on 2.14.1), [tables](https://spacetimedb.com/docs/tables/) (private tables are "visible only to reducers and the database owner") and [table performance](https://spacetimedb.com/docs/tables/performance/). Design consequences: the four columns are appended with defaults, so a world updated in place keeps its rows and reads "no working hours"; the table stays private (only the authority and the mind service, as owner, read it); clients need the regenerated bindings to see the columns.

### Data paths

| Path | Reads | Writes | Index | Recipients | Frequency | Growth |
| --- | --- | --- | --- | --- | --- | --- |
| A graph weighing `work_hours`, `bedtime` or `evening` | the body's `rhythm` row | — | PK | — | per evaluation of a graph that has those weights (as before for `bedtime` and `evening`) | — |
| A person's new day | `rhythm` | `rhythm.last_day` | PK | owner only (private) | once a game day per person | — |
| World creation | the seed's rhythm | one `rhythm` row per person (four more `f32`, 16 bytes a row) | PK | owner only | once | 16 bytes a person |
| The life table (`life_years`) | the script, once per species per revision | — | — | — | a hash lookup per ask (an empty one for a script without the law) | one table per species |

No whole-World scan was added.

## Wants beyond survival

Every seeded person should have wants the mind sees and pursues: ambitions, people they care about, pastimes and a trade they like. Before this, the island's 277 sheets carried values, goals and relations, but their goals were mostly the world's tensions (the gate-due, debts, quarrels) and nothing said what anyone enjoyed. The persona the prompts show (`persona_text`) carried narrative, values, goals, traits and mood, and nothing of one's work or days.

- **Seed format.** A sheet may say `pastimes` (2–3 things they enjoy for their own sake) and `calling` (the work they love, or long for instead). Both go into the persona when the sheet is installed. A model-written identity (`identity_system`, a resident without a sheet, `facts.rs`) and a consolidation's identity rewrite may write them too; an identity that leaves them out keeps the ones it had.
- **Persona.** `persona.pastimes` and `persona.calling` (authority table and `PersonaIn`; bindings regenerated). Prompts show "You enjoy: …" and "The work you love: …", and the world's facts about one's daily life: "Your work: <occupation> in <town>" and one's rhythm.
- **Generator.** `author_world.py`'s sheet prompt asks for goals that mix ambitions, care for particular people and wants of their own beside the situations, and for pastimes and a calling; `check_sheet` keeps them.
- **Filled for the island.** `living/tools/fill_wants.py island` asks a model, one household at a time, for each member's pastimes, calling and one or two goals of their own, from the sheet as it stands, and writes them into the sheets and the compiled seed. 277 of 277 residents; DeepSeek V4.1 Flash, 92 calls, 356,480 prompt tokens (273,408 cached), 36,821 completion, logged in `authoring-log.jsonl` (purpose `wants`). Examples: Aldric Marrow, the Reeve, plays dice with old Wat Fenner at the inn and wants to teach Maud the full ledger; Wenna Marrow spins on her mother's old wheel and would have "a loom of my own and cloth that folk buy for its weave, not for my name"; Fennel Underbank, a child, wants to walk the pedlar's road like Thistle.
- **The format stays general** for the new small city: `pastimes`, `calling`, `rhythm` and the evening habits are seed fields any world may use; nothing in the engine knows a pastime.

## Open questions for the user

1. **Population target for the next step:** keep about 300 ambient residents while the 216 gate is fixed, or seed toward the contract tier now (about 1,600 residents; bigger town households or the 3 km island)?
2. **Dispersal share:** today 84% in settlements, 16% in hamlets. Do you want more people living alone and on the land (lone dwellings along roads, 30–40% outside), or towns that feel full?
3. **Which rule gaps first:** community regard and `demand` (tolls, dues, rents, the outlaws' share) are the two that most of the tensions wait on.
4. **The seam with `townlife-2`:** a woken resident with an authored sheet now installs it whole and then internalizes its ring (made here, since `townlife-2` had merged). Keep that, or treat the sheet as one more world fact the identity call reads? And should consolidation get the resident's world facts so it stops rewriting authored identities with wrong facts (seam item 5)?
5. **Long journeys:** accept seeded stages for now, or make road-following walks an engine rule for everyone (every mind and player-made journey would then work across the island)?
6. **Roads and sight:** should the outlaws' tension wait for a rule that lets a watch notice walkers beyond 11 m (gap 8), or should the seed put Coldwell's watch at a narrow place on the stone road (a ford or the bridge), which needs the generator to report those places?
7. **The other worlds:** extend the same planning to `aske-coast` (written by hand before this tool) and the megacity floor?
8. **Names:** the drafts keep each culture's style but lean on a few forms (several Ostranders and Mackerels in Lanternquay; Norse names among the giants). Do you want name lists per culture in the bible, or is the drift acceptable?
