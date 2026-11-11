# The small city: Cullet

Started 2026-11-11, after the owner's first real play-test. This is a design target, not an implementation report. The owner answered the decisions on 2026-11-11 ([answers](#the-owners-answers-2026-11-11)), and phases 2 and 4 are being built. It replaces the island as the game's test world; the island seed stays for the labs.

**The owner's verdict.** The world feels bad. The city has no character and looks slopped together. The NPCs feel like NPCs, not like players run by AI. Survival dominates everything.

**The request.** One small city with real character, filled with people who live in it properly, as the whole world, so that looks and sustainability can be tested with players and AI characters together.

**What this document decides.** The city's identity, its size and land, its 64 people, how survival steps back, how far people see, the assets to build, a model A/B test, and the build plan. Open choices are marked **Decision** and gathered [at the end](#decisions-for-the-owner).

**What it does not do.** It designs no table, view, reducer or subscription. Phases that touch them must do the SpacetimeDB documentation check that [AGENTS.md](../AGENTS.md) requires, at that time. The client-feel faults (ice-cube walking, pop-in, jump, camera, UI) belong to another worker and are left alone here.

## Why the current town reads as slop

Based on look-dev photographs of Brackenford taken for this document (2026-11-11, the play-test binary, 13:00, six shots; `.local/living/small-city/look/town/`).

| What the pictures show | Why it reads as slop |
|---|---|
| Every house is cream plaster, brown timber and X-braces. Roofs are orange, green, teal, grey or brown at random. | Colour is drawn from a list by a random number. No material has a source, so nothing says where the town is or what it is built from. |
| Houses stand apart on a lawn, 5 to 10 m from each other, each turned its own way. | A town is made of streets: shared walls, continuous fronts, lanes and yards. Detached boxes on grass read as a model village. |
| The square is about 60 m of flat beige paving with a well, a cross and six identical striped stalls in a grid. Paving stones are 1.5 to 3 m long. | The space is far too big for the people in it, and the paving is out of scale, so figures look like toys. Six clones of one stall say "copy and paste". |
| Everything is new. No stains, patches, repairs, moss, ruts or leaning walls. | A place with no past has no character. Wear is where history shows. |
| Windows are orange rectangles at one in the afternoon. | The pane's own colour is the glow colour, so the houses look lit at noon. |
| Nothing is visible beyond about 100 m. The 140 m overview is plain fog. | There is no skyline. No landmark can orient you, because none can be seen from another street. |
| The tallest things are a grey chapel and a hall with a green roof. | Neither has a shape you would know as a black outline. They are bigger houses. |
| The ground is one flat plane. Lawn meets paving in a clean line. | No kerbs, gutters, steps, dirt or slope. The camera looks down at 28°, so on flat ground it sees mostly floor. |
| People are the same two young anime bases in bright modern dresses. One stands inside the well. | Nobody looks like their trade, age or household. The well shows the known fault that everyone is sent to the same point of a place. |

The buildings themselves are competent: recessed windows, sagging ridges, leaning chimneys. The fault is one level up. The generator samples buildings from a distribution and the planner scatters them. Nothing was decided about this particular place.

The rule this document takes from that: **every variation must have a cause the plan can name.** A wall is dark because it faces the furnace. A roof is patched because of last autumn's storm. A door is oxblood because the Tarns have always painted theirs so.

## 1. Identity

### Premise

**Cullet** is a glassmakers' harbour on a treeless rock. It burns seaweed to make glass, and it grows its food under that glass.

- **Where.** The south slope of a small island its people call **the Wrack**, after the seaweed the sea throws up. The slope faces the sun and steps down to a stone harbour.
- **Why it exists.** It was built as a port of call. Ships came, paid their dues at the Counting House, and left. Then they stopped. This is year 83 since the Last Sail. The harbour, the hall and the bollards are sized for a trade that no longer exists.
- **What it lives from.** The island has thin soil and wind. So the town burns kelp to ash, melts ash and sand into glass, and builds glasshouses on the old house plots. Fish come from the jetties and weirs. Roots grow in walled plots fed with kelp. Peat from the moor and a single small wood are all the fuel there is.
- **The name.** Cullet is the glassmaker's word for broken glass kept to be melted again. Nothing comes into this world from outside, so everything is remelted, patched and reused. That is the town's whole way of life, and it suits a world where nothing spawns by magic.
- **What makes it unmistakable.** A 24 m brick cone that glows at its foot all night. A hillside of small-paned glasshouses that light up like lanterns at dusk. Every window in town patched from bottle-green, amber and pale aqua panes, because nobody can make a large clear sheet.

### Landmarks

Each must be recognisable as a black outline 64 pixels high. Each can be seen from most of the town, because the town climbs a slope.

| Landmark | Shape | Size | Where | What happens there |
|---|---|---|---|---|
| **The Cone** | A brick cone with its top cut off, smoking, with three arched mouths at the foot that glow orange | 14 m across the base, 24 m high | East end, on the quay level | The glass furnace. Tended in three watches, so it never goes dark. |
| **The Watchglass** | A squat eight-sided tower with a lantern room too big for it, glazed in faceted panes with one band of cobalt | 6 m across, 17 m high | The tip of the mole, 60 m out to sea | The harbour light. Lit every night, though no ship has come in 83 years. |
| **The Counting House** | A long hall on an open arcade of seven arches, hipped slate roof, a cupola with a clock stopped at ten past four | 30 × 12 m, 15 m to the cupola | Middle of the quay | The tally room upstairs. Under the arches: the market, the counters game and shelter from rain. |
| **The Heron** | A hunched timber crane house with a long jib like a beak, tarred black | 7 × 5 m, 13 m high, jib reaching 9 m | On the quay edge, west of the Fish Steps | A treadwheel crane from the ship days. It still lifts boats and kelp loads. |
| **The Ladder** | Fourteen lean-to glasshouses stepping up the west slope, their roofs a sawtooth of small panes | 90 × 90 m in all | Upper west side | Where the greens grow. Three houses are broken since the storm. |
| **The Lintel** (see Decision 8) | Two standing stones and a capstone, with a slab of dark glass filling the opening | 9 m high | The north headland, 330 m from town | Nothing. It is shut. It is this floor's gate, if the owner wants one. |

### Districts

The built town is about 300 m east to west and 190 m from the quay to the Crown. It rises 20 m. Coordinates used later: origin at the Fish Steps, x east, y north (uphill), in metres.

```
                         the Moss (peat moor, +28 to +36 m)
                                                                  the Hanger
              root plots     THE CROWN  (+20 m)                   (the only wood)
           ..............   cistern · Readers' House · graves
        THE LADDER          --------- High Row (+13.5 m) ---------
     glasshouses  ####      ========= Mid Row  (+9.5 m)  =========     CINDER ROW
     on terraces  ####      ========= Low Row  (+5.5 m)  =========    lehr · pots · cullet yard
                  ####       |      |      |       |       |           wash-house (  the  )
  Wrack Strand   slip  net lofts  smoke  COUNTING HOUSE   store        ( CONE )
  kelp racks  ~~~~~~~[dock]=====THE STRAND (quay, +2 m)=====[Heron]=========\\
  and kilns   ~~~~~~~~~~~~~~~~~~~~~~ Fish Steps ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ \\ the mole
      the Weirs  ~~~~~~~~~~~~~~~~~~~ harbour ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~  \\
                                                                             (Watchglass)
                              the Combs (reef) · · · · · · · the Pale (fog)
```

| District | What is there | Mood | Busiest |
|---|---|---|---|
| **The Strand** | The quay (150 × 10 m), the Fish Steps, the Heron, the Counting House and its yard (the only square, 30 × 14 m), six net lofts, two smokehouses, the slip, the dry dock with a half-built ship, the Store | Tarred black wood, wet dark stone, rope, nets, gulls, a green tide line on every wall | Dawn and whenever the tide is low |
| **Cinder Row** | The Cone and its yard, the lehr house (in an old bonded warehouse), the pot house, the cullet yard with its heaps of coloured broken glass, the ash house, the wash-house built against the Cone's warm north wall | Soot-black brick, orange light, heat shimmer, sparkle underfoot | Never empty. Loudest from 06:00 to 22:00 |
| **The Rows** | Three terraced streets along the slope, joined by five stair lanes called wynds. 24 houses. The Batch (the common oven) on Low Row. The Marver (the cookshop) on Mid Row with a terrace over the harbour | Narrow, close, domestic. Washing across the wynds, cats, doorstep benches, children | Morning and evening |
| **The Ladder** | 14 glasshouses on five terraces, 18 walled root plots above and west of them, rain butts, kelp heaps | Bright, green, humid. Warm yellow glow at dusk | 07:00 to 16:00, in any weather |
| **The Crown** | The round cistern, the Readers' House, the graveyard with glass markers, one wind-bent thorn tree, a bench | Quiet, wind, the whole town below | Late afternoon |

**Decision 7: no interiors.** Buildings are blockers in the rules today, and people indoors are not drawn. A city where everyone works behind closed walls would look empty. So Cullet's working buildings have **open ground floors**: arcades, open sheds, furnace mouths, workshop fronts with the shutters up. Homes stay closed. This is a design answer to an engine limit, and it becomes part of the look. The alternative, interiors as separate small maps ([floors, verticality](FLOORS.md#verticality)), is a later engine step and not needed for this test.

### Palette

About 70% of any view is dark stone, off-white and slate. About 20% is wood and ground. At most 10% is colour, and that colour is always glass or a painted door. Roofs are never saturated.

| Use | Name | sRGB (0 to 1) |
|---|---|---|
| Ground floors, quay, walls | basalt | 0.24, 0.25, 0.28 |
| Weathered stone, paving | pale basalt | 0.36, 0.37, 0.39 |
| Upper walls, fresh | limewash | 0.90, 0.89, 0.84 |
| Upper walls, old | old lime | 0.78, 0.77, 0.71 |
| Roofs | slate | 0.30, 0.34, 0.40 |
| Roof repairs | new slate | 0.38, 0.43, 0.50 |
| Roofs and walls, weather side | lichen | 0.72, 0.66, 0.30 |
| Sheds, lofts, boats | tar | 0.13, 0.12, 0.12 |
| Fences, racks, bare timber | driftwood | 0.52, 0.50, 0.46 |
| The Cone, flues | sooted brick | 0.33, 0.20, 0.17 |
| Brick repairs | new brick | 0.58, 0.30, 0.22 |
| Ironwork | iron / rust | 0.17, 0.17, 0.19 / 0.50, 0.27, 0.15 |
| Landmark trims only | verdigris | 0.36, 0.62, 0.55 |
| Glass | bottle green / amber / aqua / smoke | 0.20, 0.42, 0.30 / 0.78, 0.50, 0.16 / 0.62, 0.80, 0.78 / 0.55, 0.60, 0.62 |
| Glass, rare | cobalt | 0.16, 0.26, 0.60 |
| Doors (house marks) | oxblood / mustard / sea green / chalk blue | 0.45, 0.14, 0.13 / 0.78, 0.60, 0.18 / 0.22, 0.45, 0.42 / 0.50, 0.62, 0.72 |
| Shore | kelp / sand | 0.30, 0.28, 0.12 / 0.86, 0.82, 0.70 |
| Moor | peat / moor grass / heather | 0.20, 0.15, 0.11 / 0.52, 0.50, 0.28 / 0.50, 0.34, 0.48 |
| Light | furnace / oil lamp / the Watchglass | 1.0, 0.45, 0.12 / 1.0, 0.74, 0.40 / 0.80, 0.95, 1.0 |

Cobalt is rationed: the Watchglass has one band, and each district has one cobalt thing. A pane's daytime colour is its glass colour. It glows only at night.

### Material language

Each material has a source on the island, and that source is a place you can walk to.

| Material | Source | Used for |
|---|---|---|
| Basalt | The island itself, the old quarry face behind High Row | Ground floors, quay, retaining walls, plot walls |
| Limewash | Burnt shells from the strand | Upper walls. Renewed on the sheltered side, flaking on the weather side |
| Slate | Stripped from the abandoned houses | Every roof. There is no new slate, so every repair is a different shade |
| Tarred timber | Ship planks and driftwood | Lofts, sheds, the Heron, fences. Timber is precious, so little is used structurally |
| Brick | Fired in the ship days from the clay bank, now nearly dug out | The Cone, flues, chimneys only |
| Glass | Kelp ash and sand, melted at the Cone | Small panes, never larger than 0.45 m. Floats, bottles, lamp glass, the island's tokens |
| Iron | Ship fittings, none new | Bands, bollards, hinges. All of it rusting |

### Shape language

- **Narrow and tall.** House fronts are 4.5 to 6.5 m wide and share their side walls. Roofs pitch at 45 to 50°. Ridges run along the row, so each row is one long stepped roof.
- **Gable to the sea** on the quay. The net lofts are tall thin black sheds, 3.5 m wide and 8 to 9 m high, standing in a rank.
- **Round means fire or water.** The Cone, the kelp kilns, the lehr arches, the cistern and the Watchglass lantern are round. Everything people live in is square. This one rule makes the landmarks stand out.
- **Everything leans on something.** Glasshouses lean on terrace walls. Sheds lean on houses. The wash-house leans on the Cone. Free-standing buildings are rare and important.
- **The small-pane grid.** Since no pane is larger than 0.45 m, every window and glasshouse is a grid. The grid, with a few odd-coloured panes in it, is the town's motif.
- **Ship parts reused.** An anchor is a bench end. A mast is the flagpole. Hull planks are fences. An upturned boat is a shed roof. A figurehead hangs over the Marver's door.
- **Human scale, checked.** Doors 0.9 × 2.0 m. Storeys 2.6 to 2.9 m. Steps 0.18 m. Paving setts 0.3 to 0.6 m. Lanes 2.5 to 3.5 m wide, rows 5 m, the quay 10 m.

### History and wear

Three layers, each visible.

1. **The ship days** (more than 83 years ago). The Counting House, the mole, the dry dock, the bonded warehouse and bollards far too big for a fishing boat. Carved lintels in a formal script. The clock.
2. **The lean years** (two generations ago). When the ships stopped, half the town left or died. Roofs of empty houses were stripped for fuel, and the wood was cut to stumps. Three houses are still roofless shells. The Hanger was replanted, so all its trees are the same age and stand among old stumps.
3. **Now.** Glasshouses built inside old house walls. A band of newer, redder brick on the Cone where it cracked. Last autumn's storm: three broken glasshouses, missing slates, the end rail of the mole gone.

Wear is placed by cause, from a short list. A model takes these as inputs from the plan; it does not roll for them.

| Cause | Where | What it does |
|---|---|---|
| Salt | Below +6 m | Rust streaks under iron, a green band up to 1.2 m on quay walls, white bloom on stone |
| Soot | Within 60 m north-east of the Cone (the wind is south-westerly) | Grey limewash, black slates, soot fans above every flue |
| Wind | South-west faces everywhere | Flaked lime, lichen, patched slates. Every tree leans north-east |
| Feet | Steps, thresholds, corners | Dished treads, polished setts, dirt paths cutting corners |
| Repair | Anywhere | A patch in a newer material that never matches. Boards where panes were. Timber props against a bulging wall |
| Abandonment | 7 of the 24 row houses | Boarded windows, weeds on the stoop, a roofless shell with a tree inside |

**Household marks.** Each household has a door colour and one thing it keeps outside: a row of glass floats, a caged gull, wind chimes of cullet, a bench made from a thwart. These come from the residents' sheets, so the street tells you who lives there.

### Names

All names here are original. Glassmaking supplied several: cullet (broken glass), marver (the slab glass is rolled on), lehr (the cooling oven), batch (the raw mix), pontil (the iron rod). The currency is small glass tokens called **drops**; mechanically they are the existing `marks` item.

## 2. Size

### The city

- **Built area:** about 300 × 190 m, 4.5 hectares, rising from +2 m at the quay to +20 m at the Crown.
- **Buildings: 65.**
  - 27 houses. 24 stand in the terraces: 17 lived in, 4 sound and empty (for players and newcomers), 3 roofless. 3 stand outside town: the turf house, the Hanger cottage and the lamp house.
  - 4 landmark buildings: the Cone, the Counting House, the Heron, the Watchglass.
  - 20 working buildings: 6 net lofts, 2 smokehouses, the boatshed, the Store, the Batch, the Marver, the wash-house, the lehr house, the pot house, the cullet shed, the ash house, the peat barn, the Readers' House, the cistern house.
  - 14 glasshouses.
- **Streets:** the quay (150 m), three rows (150 to 180 m each), five wynds of stairs (about 90 m each, rising in 3 m flights).
- **Walking times** at the rules' 2.6 m/s: the length of the quay in 1 minute, quay to Crown in 2, town to the far end of the Wrack Strand in 3, town to the Lintel in 3.

This is the smallest size at which the town still has a front, a back, a top, a bottom, a rich end and a working end. Below about 50 buildings it becomes a village: one street, no districts. I am not certain 65 is the floor; 65 is what the cast of 64 needs.

For comparison, Brackenford has 136 homes for 78 people. Cullet has 27 homes for 64, and every one is placed.

### The land that feeds it

The owner's rule: resources come from the world, and nothing spawns by magic. So each thing people eat or burn has a place.

| Place | Size and position | What it gives | Who works it |
|---|---|---|---|
| The jetties, the mole and the Fish Steps | 12 fishing spots | Fish by line | 6 fishers |
| **The Weirs** | Stake fences in the shallows south-west, 10 spots, reachable at low water | Fish by trap | 3 fishers |
| **The Wrack Strand** | West beach, 190 × 40 m | Kelp: fertiliser for the plots and ash for glass | 3 gatherers, 1 ash burner |
| The root plots | 18 walled plots of about 8 × 6 m, west of and above the Ladder | Roots, the staple | 2 growers |
| The Ladder | 14 glasshouses, 11 working | Greens and fruit | 5 growers |
| **The Moss** | The peat moor on the plateau, 400 × 250 m | Peat for fuel | 3 cutters |
| **The Hanger** | A wind-bent copse in a gully north-east, about 60 trees | Timber. The only wood. | 1 warden, who lets nobody fell |
| **The Sand Spit** | East shore, 120 × 40 m of white sand | Sand for glass | Whoever the Cone sends |
| The clay bank | Below the Crown, nearly dug out | Clay for crucibles | The pot-maker |
| The cistern | On the Crown, 9 m across | Water, from rain | The water keeper |

**The food chain, in order:** kelp is gathered and burnt to ash. Ash and sand are melted into glass with peat. Glass mends the glasshouses. Glasshouses grow greens. Kelp also feeds the root plots. Fish are caught, eaten fresh, cooked or smoked. The Counting House arcade is where these change hands.

**Sustainability targets** (to be tuned by a soak with no minds, then checked with minds):

- The island yields about 1.3 times what 64 residents and 10 players eat, when its 16 food workers work about five game hours a day.
- Fish are about 55% of food, roots 30%, greens 15%.
- The stores hold six days of food at the start.
- A resident whose trade is not food spends under a tenth of the waking day getting and eating it.
- Fuel is the tight resource, not food. The Cone burns about as much peat as all the homes together. The seeded stock lasts 12 days of full firing, and the cutters bring in about 70% of what is burnt. So the stock falls slowly, and someone has to decide something.

**Rule gaps this needs** (general rules for every world, not Cullet hooks; see the [build plan](#8-build-plan)):

- **Goods.** The catalog has berries, fish and meat. Cullet needs kelp, ash, sand, glass, roots, greens, peat and lamp oil, with their recipes. The owner's "traits, not lists" decision suggests goods should become data with properties, so that food is anything with nutrition and fuel is anything that burns.
- **Fire that eats fuel.** A furnace or hearth is lit only while it is fed.

  *Built 2026-11-11 on `goods-1`:* goods, fires that eat fuel, recipes and shared fishing stocks, with Cullet's goods as data in its laws file, `living/seeds/worlds/cullet/laws.rhai` ([world rules](WORLD_RULES.md#goods-recipes-and-fuel)). Placing Cullet's nodes and fires is the authored plan's.

  *Placed 2026-11-11 on `rates-2`:* Cullet's resources, fires, lamps and the Store's food, with amounts and regrowth computed from the sustainability targets above as starting values for the soak ([Cullet's goods, placed](CULLET_RULES.md#cullets-goods-placed-rates-2)).
- **Decay and upkeep.** Panes break and need glass. The owner has asked for this, as Rhai laws.
- **Fish as a stock.** Today a fishing spot regrows. The owner wants fish to be animals eventually. For this test, regrowing spots with a shared limit are enough.
- **Tide** (optional, recommended). A law that gives the water's state from the clock, shifting about 50 minutes later each day. It gates the Weirs and the wrack. It changes no terrain.

### Where the world ends

The world is the island and the water round it: a land map 1024 m on a side, with the Wrack about 760 × 560 m in the middle.

- **The Combs** are a reef 120 to 200 m off the south shore. Nothing with a keel has crossed them since the Last Sail.
- **The Pale** is a fog bank that stands beyond the Combs on every side. The map ends inside it. From the Crown you see sea, then white.
- **The Lintel** is shut.

The rules have no boats and water blocks walking, so nobody can leave. The fiction agrees with the mechanics, and nothing has to be scripted to keep people in.

## 3. People

### How many

**64 residents, every one a full mind from the first tick.** 50 adults (6 of them elders) and 14 children, in 22 households.

Why 64:

- **Cost.** The measured mix is about €0.23 per person-hour on stage and €0.035 off stage ([model cost](MODEL_COST.md)). In a town this small, a player is near almost everyone, so plan for on-stage rates: about €15 per real hour. A four-hour play-test is about €60. An idle day at off-stage rates is about €54.
- **Load.** At lab rates a person makes about two model calls a minute. 64 people make about 130 calls a minute. That rate has not been run for hours on the current providers. It needs a trial before the play-test.
- **Feel.** With 64 people in 4.5 hectares, the camera usually frames four to ten of them on the quay. A player can learn every face in a few sessions. That is the point of a small city.

| Option | Residents | Cost per on-stage hour | Trade-off |
|---|---:|---:|---|
| A | 40 | about €9 | Cheaper, but the three furnace watches and the two family groups get thin. Some houses would have to go. |
| **B (recommended)** | **64** | **about €15** | Every trade is filled without doubling up. Three watches at the Cone. |
| C | 96 | about €22 | A busier quay, but 50% more authoring, load and cost before anything is proven. |

**Decision 3.** I recommend B. If load trials fail at 64, drop to A by removing the eight weakest-tied households, not by putting anyone on instincts.

### Two kinds of family

- **Kiln families** descend from the glassmakers who were here before the ships stopped. They hold the Cone, the best houses on High Row and most shares in the Ladder.
- **Strand families** descend from the last crews, who stayed because they had to. They fish, gather wrack and live on Low Row. Their names come from everywhere, which is why Cullet's names are mixed.

Neither is a faction in the rules. They are a past that people carry in their sheets, with marriages, debts and friendships across the line.

### The households

One line each. "Wants" is what the person wants beyond staying alive. Hours are starting habits, not rules: every mind owns its routine and may change it.

**Kiln families**

| Household, house | Person | Age, trade | Wants, and what is going on |
|---|---|---|---|
| **Pontil**, High Row 1 | Vessa Pontil | 61, Glassmaster | Is losing her sight and can no longer judge the colour of the melt. Hides it. Wants to choose who follows her before anyone finds out. |
| | Ode Pontil | 66, sorts cullet | Her brother. Knows her secret. Keeps the old colour recipes in his head and has written none down. Collects one piece of every colour ever made here. |
| | Lumi | 9 | Her granddaughter. Goes to the Cone with her at 05:00 and tells her what colour the melt is. Thinks it is a game. |
| **Hollin**, High Row 2 | Corvin Hollin | 38, first blower | Certain the Cone will be his. Wants to make clear glass, which nobody has managed since his grandfather. |
| | Tamsin Hollin | 35, glazier | Fits the panes on the Ladder, so she decides whose glasshouse is mended first. Wants the empty house on Mid Row for her sister's family. |
| | Edda, Pim | 12, 6 | Edda leads the children who play in the cullet yard, where they are forbidden to go. |
| **Sarro**, Mid Row 5 | Imre Sarro | 29, second blower | The better hands, and he knows it. His mother was Strand-born. Wants the Cone on merit. Loves Neve Calloway. |
| | Runa Sarro | 55, keeps the lehr | Suspects what is wrong with Vessa. Has said nothing, because the truth helps her son and she does not trust her own motive. |
| **Quill**, High Row 3 | Aldous Quill | 52, tally keeper | Keeps the ledger of who owes whom. Wants the clock to run again. Has one entry in the book he hopes nobody checks. |
| | Mirren Quill | 49, healer and midwife | Knows everyone's bodies and most of their secrets. Wants a second healer trained before she is old. |
| | Sabine Quill | 19, the Reader's pupil | Reads the ship-day tablets. Wants to know what is past the Pale more than she wants anyone in Cullet. |
| **Brandt**, Mid Row 7 | Otto Brandt | 44, pot-maker | Makes the clay pots the glass melts in. The clay bank is almost gone. The only other clay is under the graveyard. |
| | Fenn Brandt | 41, stoker, day watch | His husband. Wants Otto to stop looking at the graveyard. Keeps hens and names them after people. |
| | Juno | 8 | Wants a hen of her own. |
| **Marl**, Low Row 10 | Thessaly Marl | 33, stoker, night watch | Alone with a child. Works 22:00 to 06:00 and sleeps while he is at lessons. Wants the day watch. |
| | Wick | 5 | Sleeps at the wash-house with Greta when his mother is at the Cone. |
| **Dunmore**, High Row 5 | Halvard Dunmore | 70, retired blower | Sits on the bench at the Cone's mouth all day and judges everyone's work aloud. Wants his grandson at the furnace. |
| | Greta Dunmore | 68, keeps the wash-house | Hears everything. Wants the kelp smoke kept off the washing. |
| | Tobiah Dunmore | 16, stoker, evening watch | Wants to fish. Has not said so at home. |

**Strand families**

| Household, house | Person | Age, trade | Wants, and what is going on |
|---|---|---|---|
| **Calloway**, Low Row 2 | Bram Calloway | 47, boatwright | Is building a ship, the *Second Thought*, in the old dry dock. Means to cross the Combs. Needs fourteen trees from the Hanger. |
| | Ysolde Calloway | 45, fisher at the Weirs | Does not want to sail and will not say so in front of the children. |
| | Neve Calloway | 22, fisher | Would sail with her father. Loves Imre Sarro, who would never leave the Cone. |
| | Kit Calloway | 14, boatwright's apprentice | Wants to blow glass. Kiln families have never taken a Strand apprentice. |
| **Tarn**, Low Row 4 | Magda Tarn | 58, eldest fisher | Divides the catch on the Fish Steps each morning. Seven people in her house. Wants the empty house on Mid Row. |
| | Joss Tarn, Eamon Tarn | 31 and 27, fishers | Joss wants a glasshouse share for the family. Eamon wants a place on Bram's ship. |
| | Petra Tarn | 30, smoker | Runs the smokehouse. Wants the Marver to pay what it owes her. |
| | Nell, Ansel, Dory | 7, 4, 1 | |
| **Okoro**, Low Row 5 | Chidi Okoro | 40, fisher and line-maker | Makes the best line on the island and trades it dear. Wants his children to learn to read. |
| | Amara Okoro | 37, wrack gatherer | Up with the tide whatever the hour. Collects sea-glass and knows which wreck each colour came from. |
| | Zeke, Ife | 11, 9 | Cullet yard children. |
| **Vane**, Low Row 6 | Lorcan Vane | 34, fisher | Plays counters every night and loses. Owes drops to the ledger and to the Marver. |
| | Davin Vane | 26, porter | Pushes the handcart and walks the Heron's treadwheel. Pays his brother's debts quietly. Wants a trade of his own. |
| **Morrow**, Low Row 7 | Ingrid Morrow | 63, net-mender | Mends nets on the Fish Steps and moves with the sun across the day. Wants her granddaughter to stop talking about sails. |
| | Lark Morrow | 17, wrack gatherer | Saw a sail beyond the Combs last spring. Nobody else did. Watches for it every dusk. |
| **Sato**, Low Row 8 | Kenji Sato | 50, ash burner | Burns kelp in the kilns on the strand. The smoke blows over Low Row. He is tired of hearing about it. |
| | Hana Sato | 46, wrack gatherer | Wants a house further from her husband's smoke. |
| | Ren Sato | 20, fisher | Courting Sabine Quill. Her father does not approve. Neither, quite, does she. |
| **Dunlin**, Low Row 1 | Rafe Dunlin | 36, fisher | A widower. Fishes from the mole by lamplight, 22:00 to 03:00, when the fish come to the light. |
| | Tilly | 10 | Wants to stay up with him. |

**The Ladder, the Moss and the rest**

| Household, house | Person | Age, trade | Wants, and what is going on |
|---|---|---|---|
| **Greave**, Mid Row 1 | Oswin Greave | 57, head grower | Wants every pane on the Ladder growing food. |
| | Elke Greave | 54, grower | Wants her son to stop wasting a bay on a tree. |
| | Jory Greave | 25, grower | Is trying to grow a fruit tree under glass, in a bay of glasshouse 9. It has taken three years and has not fruited. |
| | Suri Greave | 24, grower | Expecting a child in the spring. Wants a house of their own. |
| **Fenwick**, Mid Row 2 | Nan Fenwick | 42, root plots | Wants more kelp than the gatherers will bring up the hill. |
| | Hobb Fenwick | 45, root plots, water keeper | Keeps the cistern. Measures its level every dusk and writes it on a tablet nobody reads. |
| | Alder, Posy | 13, 10 | Alder wants to be a reader. |
| **Roon**, the turf house on the Moss | Tam Roon | 48, peat cutter | Lives up on the moor. Comes down at 15:00 and stays at the Marver too long. Wants to be paid more for peat. |
| | Eilidh Roon | 44, peat cutter | Wants to move into town. |
| | Col Roon | 15, peat cutter | Walks the strand alone every evening. Wants to know other people his age. |
| **Sedge**, the Hanger cottage | Marit Sedge | 39, warden of the wood | Planted half the Hanger with her mother. Will not let anyone fell a tree, for a ship or for the furnace. |
| **Faro**, the lamp house on the mole | Anselm Faro | 64, lamp keeper | Lights the Watchglass at dusk and tends it till dawn. Sleeps 06:00 to 13:00. Has never missed a night. |
| | Livia Faro | 23, renders lamp oil | His niece. Works by day. Has begun to wonder who the light is for. |
| **Achterberg**, over the Marver on Mid Row | Dolly Achterberg | 51, cook | Keeps the Marver. Wants a full house every night and gets it. |
| | Pieter Achterberg | 53, baker | Lights the Batch at 03:00. Asleep by 13:00. Plays counters with Anselm at dawn, when both are finishing. |
| | Roos Achterberg | 18, serves at the Marver | Carves the counters and runs the nightly game. Wants to beat Aldous Quill at it, once. |
| **Orme**, the Readers' House | Benedikt Orme | 59, reader and teacher | Teaches the children 09:00 to 12:00. Spends his afternoons at the Lintel with tablets. Wants to know what it is. |
| **Stannard**, Mid Row 4 | Gwil Stannard | 43, mason and roofer | Every roof leaks and he is one man. Owes favours all over town. |
| | Cora Stannard | 40, grower | Grows flowers in a corner of glasshouse 4. Oswin wants the corner back. |

What each person does about any of this is theirs to decide. A mind can drop its trade, change its hours, tell a secret or keep it. The sheets say what is the case on day one. They say nothing about what happens next.

### Different rhythms

At the play-test everyone ran for shelter together at dusk. There were three causes: one cold rule that hurt everyone alike, one sleep signal tied to the clock, and one evening place per settlement. Cullet gives people real reasons to keep different hours.

| What sets the hours | Who | Their day |
|---|---|---|
| The oven | Pieter | Up 02:30, bakes 03:00 to 08:00, asleep by 13:00 |
| The tide (if the tide law is built) | Weir fishers, wrack gatherers | Out at low water, which comes 50 minutes later each day. Their week drifts against the clock. |
| First light | Line fishers | On the jetties at dawn. Done by noon. |
| The furnace | Three watches | 06:00 to 14:00, 14:00 to 22:00, 22:00 to 06:00 |
| The melt | Vessa and Lumi | At the Cone at 05:00, before anyone else |
| The lamp | Anselm; Rafe, who fishes by it | Dusk to dawn |
| Daylight under glass | Growers | 07:00 to 16:00, rain or shine. They water at dusk. |
| Dry, windy weather | Kenji | Burns kelp only on such days. Otherwise mends kilns or idles. |
| The moor | The Roons | Leave at 06:00, back at 15:00 |
| Opening hours | Counting House 09:00 to 15:00; the Batch hot until 10:00; the Marver 11:00 to 22:00; the wash-house 08:00 to 20:00 | People bake their own roots at the Batch in the morning, so it is the morning meeting place |
| The sun | Ingrid, Halvard | Each keeps a bench. Ingrid moves hers with the light. |

**Evening places differ by person.** The Marver for Strand men and Tam. The wash-house wall, warm from the Cone, for gossip. The Counting House arcade for the counters game. The Fish Steps for the young. The Crown bench for Benedikt and for couples. The mole for Rafe, and for Thessaly on her break.

**How this is seeded.** Each resident's sheet carries a small `rhythm`: usual waking hour, hours of sleep needed, working hours, and one or two evening places. The starting routines read those values instead of fixed hours. Sleep follows tiredness more than the clock. These are per-person starting values of the same routines everyone has, not per-role scripts. This needs a small seed and graph change, listed in the build plan.

**Places need spots.** Today everyone at a place stands on one point. A place needs several named spots, such as a bench's seats, a stall's two sides, or the steps of the Fish Steps, so that six people at the Marver sit at six seats. This is a general rule gap.

### Tensions

Each is made of seeded state: who owns what, who owes what, what is running out, and what people remember. None has a schedule, a trigger or an outcome.

| Tension | What it is made of | Who carries it |
|---|---|---|
| **Fuel** | Peat and wood counts in the stores. The Cone's burn rate. The size of the Hanger. | Vessa, Tam and Eilidh, Marit, Bram, every cold household |
| **The succession** | Vessa's failing sight (a secret, on three sheets). Two blowers. No rule for who follows. | Vessa, Ode, Lumi, Corvin, Imre, Runa, Halvard |
| **Panes** | Three broken glasshouses. Glass enough for about one. Tamsin chooses the order. | Tamsin, Oswin, Joss, Cora, Jory |
| **The ship** | A hull in the dry dock. Fourteen trees needed. A reef. | Bram, Ysolde, Neve, Eamon, Marit, Sabine |
| **The lamp** | Oil burnt each night that could be eaten or traded. A vow. A girl who saw a sail. | Anselm, Livia, Lark, Ingrid, Aldous |
| **The ledger** | Debts in drops between Strand and Kiln households. One false entry. | Aldous, Lorcan, Davin, Petra, Dolly |
| **The empty house** | Mid Row 6: sound, empty, wanted by two families. A newcomer could also ask for it. | Magda, Tamsin, Suri, any player |
| **Apprentices** | A Strand boy who wants glass. A Kiln boy who wants the sea. A custom against both. | Kit, Tobiah, Halvard, Bram, Imre |
| **The smoke** | The kelp kilns stand upwind of Low Row's washing. | Kenji, Hana, Greta |
| **The clay** | The clay bank is nearly gone. There is more under the graveyard. | Otto, Fenn, Mirren, Benedikt |
| **Two loves** | Imre and Neve, across the two families. Ren and Sabine, uneven. | Those four, and their parents |

A human player arrives as a stranger, which Cullet has not seen in living memory. That alone is an event the residents will have opinions about, and nothing needs to be written to make it one.

**Authoring.** The existing tool ([seeded lives](SEEDED_LIVES.md#authoring-at-scale)) can draft the 64 sheets from a Cullet bible and the anchor table above. That is a paid run of about €0.30 to €0.50 and needs the owner's go-ahead (Decision 11).

## 4. Survival made secondary

### What is wrong now

The numbers per game day are not harsh. The clock is.

- A game day is 12 real minutes. Hunger rises 5 points a real minute, so a person is hungry again every 11 minutes of play.
- Starving costs 6 health a real minute: from full health to dead in 17 minutes.
- Every night outside without a fire, a roof or a cloak costs health. Night falls for everyone at 20:00. So every character, mind or not, heads home at the same moment.
- A mind's decision takes 9 to 18 seconds, which is 20 to 35 game minutes. In a day that short, people cannot do much besides eat and sleep.

### Targets, in game time

| Need | Outcome |
|---|---|
| **Food** | A person eats twice a day. A third meal is pleasure. |
| | Missing a meal changes nothing. |
| | A whole day without food makes a person hungry: a mood, and slower healing. No harm. |
| | Harm starts after about two days without food. Death comes about eight days after that. |
| | A player can ignore food for a whole session and find their character hungry, not dying. |
| **Sleep** | About 16 hours awake and 7 to 8 asleep, varying by person. |
| | One night without sleep means a slow walk the next day. Harm starts after two. |
| | Sleeping rough restores at half the rate of a bed. |
| **Cold** | An ordinary night outdoors costs nothing but poorer rest. |
| | Cold hurts only on winter nights, slowly: a whole winter night outside without a coat or a fire costs about 15 health. It never kills a healthy person in one night. |
| | Every adult in Cullet owns a coat, as most people in a town do. |
| | Warm public places exist at night: the Cone's mouth, the wash-house wall, the Marver's hearth, the Batch from 03:00. |
| **Rain** | Tiring, not harmful. People under the arcade or under glass carry on. |

### The numbers

**Decision 4: a game day of 48 real minutes.** That is two real minutes per game hour. A two-hour session sees two and a half days. A mind's 9 to 18 second decision becomes 5 to 9 game minutes, so characters can talk, work and play within an hour. Night lasts 20 real minutes.

| Option | Real minutes per day | Good | Bad |
|---|---:|---|---|
| A | 24 | Faster turn of day and night | Minds still spend much of each game hour deciding |
| **B (recommended)** | **48** | Room for lives; needs feel slow | A whole night is 20 minutes of dark; night must be worth being out in |
| C | 72 | Calmer still | A short session never sees a day turn |

Law values for a 48-minute day. They are Rhai numbers in `rates(a)` and `cold(a)`, written per real minute as today.

| Law | Now (12-minute day) | Proposed (48-minute day) | Per game day |
|---|---:|---:|---|
| Hunger, a person | +5.0 a minute | +1.0 a minute | +48 (two meals of about 24) |
| Hungry at | 55 | 55 | |
| Starving at | 100 | 100 | About 2 days from a full stomach |
| Starving, health | −6.0 a minute | −0.25 a minute | −12, so about 8 days |
| Energy awake | −3.0 a minute | −1.6 a minute | −51 over 16 hours |
| Energy asleep, in a bed | +26 a minute | +7.5 a minute | +120 over 8 hours |
| Energy asleep, rough | +16 a minute | +3.75 a minute | Half a bed's |
| Out of energy, health | −2.0 a minute | −0.2 a minute | |
| Healing, fed and rested | +3.0 a minute | +0.75 a minute | +36 |
| Cold, health | −2.0 a minute at night, −5.0 in winter | 0, and −0.75 on winter nights | A winter night: −15 |
| Rain, energy | −2.5 a minute (−1.0 with a cloak) | −0.6 (−0.25 with a coat) | |
| Spoiling, raw fish | 5% a minute | 1.25% a minute | Gone in about a day, as now |

Other points:

- **Rates should be written per game hour.** Today every rate is per real minute, so changing the day length silently changes every balance. The engine should convert. This is a rules change, flagged for the rules worker. *Built:* need rates on `rules-1`; spoiling, regrowth, traps and remains on `rates-2` ([Cullet's rules](CULLET_RULES.md#the-other-rates-in-game-time-rates-2)).
- **The day length is not in the seed.** `World.day_ms` exists, but the seed cannot set it. It needs one seed field.
- **Night is fixed in Rust** as 20:00 to 06:00 (`is_night`). It should become a law, eased over a game hour at dusk and dawn, so that light, sight and sleepiness do not all flip in one tick.
- **Warm places.** Warmth today is a campfire within 3.5 m or a roof within 2.5 m. A lit furnace, hearth or oven should warm like a fire, with its own radius as a property.
- **Minds' prompts.** If a mind's prompt leads with hunger and cold, it will talk about hunger and cold. Needs should appear in a prompt only when they pass a threshold. This belongs to the mind service; it is flagged, not designed here.
- **Food effort** is set by how fast the sea and the beds give, not by hunger. Those rates are tuned in the soak against the [sustainability targets](#the-land-that-feeds-it).

**Decision 5.** Accept these targets, or name which ones feel wrong.

## 5. View distance

### What is there now

One tile is one metre (`living/rules/src/map.rs`: chunks of 16 tiles; walking 2.6 tiles a second is 2.6 m/s; the land's `size` is in metres). Sight is 11 m by day, 6 m at night and 9 m with a torch. Hearing is 9 m.

The camera sits 22 m from the character, 28° down, with a 50° field of view. Its lowest ray lands about 12 m behind the character. Its highest ray, 3° below level, lands about 180 m ahead. So the screen shows 180 m of ground, and the rules show people only within 11 m of the middle of it. Everyone further off does not exist, then appears. That is a large part of the pop-in the owner saw.

### Proposal

| Sight | Now | Proposed | Why |
|---|---:|---:|---|
| Day, to see that a creature is there | 11 m | **48 m** | Three chunks. At 48 m a person is about 26 pixels tall at 900p: a readable figure. At 100 m they are a speck. |
| Day, to know who it is (name, health band) | 11 m | **24 m** | Faces and voices, not outlines. Beyond it you see "a figure" or "a child". |
| Night, in the dark | 6 m | **14 m** | Enough to walk a lane and meet someone |
| Night, anyone standing in lamplight | 6 m | **28 m** | You see people under lamps from across the quay. Lit places become where night life is. |
| Carrying a light | 9 m | **20 m**, and you are seen at 48 m | A light shows you more and shows you to everyone |
| Speech | 9 m | **12 m** | A conversation across a lane |
| A shout (new) | none | **30 m** | Calling up a wynd |
| The Counting House bell (`signal`) | | **300 m** | The whole town |

How skills and passives change it, all as laws that multiply the base:

- **Keen eyes** (a passive, inborn or trained): +25%.
- **A spyglass** (an item made of glass, so made in Cullet): doubles sight in a 30° cone while it is used.
- **High ground:** from the Crown or the Watchglass gallery, +50% over lower ground. This needs the authority to read height, which it does not do today.
- **Weather:** fog halves sight. Rain takes a quarter.
- **Knowing someone:** kin and close friends are recognised at 36 m, by their walk.
- **Darkness skills:** a fisher who works by night sees 20 m in the dark.

The two-distance rule (see at 48 m, know at 24 m) fits the existing `perceived_of` law, which already decides per observer whether a name is shown.

### The scale cost (flagged, not solved)

Another worker owns perception scale. The facts they need:

- 48 m against 11 m is 19 times the area. On the open quay or the moor a character perceives everyone in that disc. Between buildings, sight lines cut most of it.
- In Cullet the worst case is small: a person on the Crown sees perhaps 40 of 64 residents. The per-sender views can carry that for a handful of players.
- At the gate (216 players) or the contract (2,000) it is not small. The 216 gate already failed on per-sender perception views at 11 m ([seeded lives](SEEDED_LIVES.md#against-the-performance-envelope)). 48 m will not pass there without a different delivery.
- The owner has ruled out an attention cap. So the cost has to come down another way, or sight has to be a law each floor sets for itself, with Cullet at 48 m and a crowded floor lower.

This document only asks that sight be a per-floor law (it already is) and that Cullet's value be 48 m.

### Showing what you cannot see (options only)

The owner is still thinking about this. Buildings, ground and resources are public and always drawn. The question is what the screen says about people out of sight.

| Option | What you see | Cost and risk |
|---|---|---|
| **A. Soft edge only** | People fade in and out over 0.4 s at the edge of sight, with a dither, instead of popping | Cheapest. Honest. The far half of the screen looks empty of people. |
| **B. Memory tint** | Ground beyond your sight is drawn slightly cooler and flatter, with a soft boundary | Tells you where your sight ends. Risks looking like a filter laid over the art. |
| **C. Last seen** | Where someone left your sight, a faint outline stays for about 10 s, then fades | Feels like memory. Can mislead, since they have moved. |
| **D. Heard, not seen** | Footsteps and voices beyond sight show as small rings on the ground | Uses hearing, which the rules already have. Needs sound first to feel right. |

My recommendation: A now, since it also softens today's pop-in. Then try B as a slider in the look panel. C and D are for later, if at all.

## 6. Asset plan

### How assets are built

- **Procedural Blender scripts**, as now: metres, the origin at the floor, fronts facing −Y, vertex colours on one white material with the surface tag in alpha, glowing parts on the `Glow` materials. A new script, `living/tools/blender/cullet.py`, imports the helpers from `buildings.py` as `city.py` does. Its runner is `gen_cullet.sh`, and its output goes to `living/game/assets/envs/cullet/<kind>/`.
- **The id is `cullet`.** `small_city` is already the small folk's city in `living/game/assets/envs/`.
- **A plan, not a sample.** The city is described by one file, `living/seeds/worlds/cullet/plan.json`: every lot with its position, size, the level it stands on, its neighbours, its household and its wear inputs. The generator builds each building for its lot from a seed recorded in the plan. The result is 65 named buildings, each made once.
- **Wear inputs come from the plan.** Each model takes `salt`, `soot`, `wind`, `age`, `repair` and `empty` from 0 to 1. The plan computes them from where the lot stands: height above the sea, distance and bearing from the Cone, which way it faces. The model never rolls for them.
- **Rows are built as rows.** A terrace of three to six houses is one generator call that knows about party walls, the step of the street and the shared roof line. No house is a detached box.
- **Individuality comes from the household.** Door colour and the thing kept outside are fields in the plan, taken from the cast.
- **Checks every model must pass:** footprint within 0.1 m of its lot; a door of 0.9 × 2.0 m; within its triangle budget; at least 90% of lit triangles tagged with a surface; the palette above and no other colours; a contact sheet through the game's renderer with a 1.75 m figure.
- **The look-dev environment** `cullet.json` sets the mood. Fog starts at 180 m and ends at 600 m on a clear day, so the Cone and the Watchglass can be seen from anywhere in town. Today's fog hides everything past about 100 m.

### The list

P0 is needed to walk the city at all. P1 is needed for it to have character. P2 is polish.

**Landmarks**

| Model | Priority | Budget (triangles) | Notes |
|---|---|---:|---|
| The Cone, with pot room, stair and gallery | P0 | 12,000 | One model. Mouths glow. |
| The Counting House | P0 | 14,000 | The arcade is open and walkable. Stopped clock. |
| The Watchglass | P0 | 9,000 | The lantern glows at night. One cobalt band. |
| The mole | P0 | 6,000 in 12 m sections | Basalt, with oversized bollards. The end rail is missing. |
| The Heron | P1 | 9,000 | The jib is fixed. A turning jib would be a client feature. |
| The Lintel | P2 | 3,000 | If kept |

**Housing**

| Model | Priority | Budget | Notes |
|---|---|---:|---|
| Row terraces: 6 terraces of 3 to 6 houses, 24 houses | P0 | about 4,000 a house | Generated per lot from the plan |
| Roofless shell, 3 | P1 | 2,500 | Walls only. One has a tree inside. |
| Lean-tos, privies, hen coops, boat-roof sheds | P1 | 600 to 1,500 | About 20, attached to named houses |
| The turf house, the Hanger cottage, the lamp house | P1 | 3,500 | One-offs outside town |

**Working buildings**

| Model | Priority | Budget | Notes |
|---|---|---:|---|
| Glasshouse, lean-to, 14 from one generator | P0 | 9,000 | Sound, patched and broken states from the `repair` input |
| Net lofts, a rank of 6 | P0 | 2,500 each | Tall, black, gable to the sea |
| The Marver, with its terrace | P0 | 9,000 | Open front. Figurehead over the door. |
| The lehr house, the pot house, the cullet shed, the ash house | P1 | 5,000 to 8,000 | Open fronts. The lehr house is the old warehouse. |
| The wash-house | P1 | 4,000 | Built against the Cone's wall |
| Smokehouses, 2 | P1 | 3,500 | Louvred roofs. Smoke is an effect. |
| The Batch | P1 | 4,000 | Oven mouth to the street, glowing from 03:00 |
| The boatshed, the dry dock and the hull of the *Second Thought* | P1 | 10,000 | The hull's stage of building is a model state |
| The Store, the peat barn, the Readers' House, the cistern and its house | P1 | 3,000 to 6,000 | |
| Kelp kilns, 4 | P2 | 800 | Round stone pits |

**Ground and structure**

| Model | Priority | Notes |
|---|---|---|
| Quay wall and edge, in 4 m sections, with the tide line | P0 | The Fish Steps as one piece |
| Retaining walls of 1.5 and 3 m, and stair flights rising 3 m | P0 | The existing prop forms, in basalt |
| Plot walls of dry stone, in 2, 3 and 4 m sections, with gates | P0 | |
| Setts, kerbs, gutters; ground textures for setts, quay flags, wet sand, peat and heather | P0 | Setts of 0.3 to 0.6 m |
| Weir stakes, jetties | P1 | |

**Street dressing, by district**

| Set | Priority | Props |
|---|---|---|
| Strand | P0 | Net rack with net, fish barrels, kelp creels, ship's bollard with rope, quay lamp, upturned boat on trestles, peat stack, glass-float string and cullet crate |
| Cinder Row | P1 | Blowpipe rack, crucible stack, cullet heaps in four colours, ash sacks, handcart, water trough, the bench at the Cone's mouth |
| Rows | P1 | Doorstep bench, washing line across a wynd, flower box, rain butt, boot scraper, cat, chalk marks, the household keepsakes |
| Ladder | P1 | Cold frame, rain butt and downpipe, kelp heap and fork, cane wigwam, wheelbarrow, pane crate |
| Crown | P2 | Glass grave markers, the thorn tree, the bench, a sundial |
| Market, under the arcade | P1 | Trestle tables, fish slabs, root baskets, tally board, counters table with stools |

**Nature**

| Model | Priority | Notes |
|---|---|---|
| Wind-bent trees for the Hanger, 6 forms, all leaning north-east | P1 | From `nature.py`'s broadleaf, with a lean and a clipped crown |
| Kelp on the strand: wet heaps, drying racks | P1 | |
| Heather, moor grass, bog cotton, peat cuttings and stacks | P1 | |
| Glasshouse plants: beds of greens, vines, Jory's tree | P1 | Seen through the gaps |
| Basalt rocks, the Combs' reef teeth | P2 | |

**People**

| Asset | Priority | Notes |
|---|---|---|
| More base bodies | P0 | **Decision 2.** The two bases are both young women. 64 residents need men, elders and children. See below. |
| Outfit set `cullet` in `outfits.py` | P0 | Oilskin smock, knitted jersey, leather apron, headscarf, flat cap, sea boots, clogs, shawl, patched coat, child's smock |
| 64 recipes in `recipes.json`, one per resident | P1 | Build, height, hair, outfit and colours from the cast |
| Work clips, made with Kimodo on the Spark | P1 | Blow glass, rake kelp, mend a net, carry a yoke, dig peat, fish with a line, hang washing, sweep, sit on a bench or step, lean on a wall, warm hands, play counters |
| Hand props | P2 | Blowpipe, rake, creel, peat spade, net needle |

**Client features the assets assume** (flagged for the client owner):

- Seats: a prop's sitting spots, so people sit on benches and steps.
- Glass that glows at night but shows its own colour by day.
- Smoke from the Cone and the kilns, blowing north-east.
- Optional: see-through glass in the toon shader. Without it, glasshouses use opaque pale panes with gaps and open vents that show the plants.

**Decision 2: the characters' bases.** Today's residents are built on two VRoid bases, both young women in modern dress. No outfit set can turn them into Halvard, 70, or Pim, 6. VRoid Studio is a GUI, so new bases need a person.

| Option | What | Trade-off |
|---|---|---|
| **A (recommended)** | The owner makes four to six new bases in VRoid Studio: a man, an older man, an older woman, a boy, a girl | A few hours of the owner's time. Keeps the one-skeleton pipeline and the anime look. |
| B | Stretch the two bases with recipes (proportions, hair, outfits) | No owner time. Men and elders will read as girls in costume. |
| C | A different character source for some residents | Breaks the one-look rule and the shared animation set |

## 7. The model A/B

**Question.** For this pipeline, does Fable 5.2 or Opus 5.5 write the better asset generators? And how do both compare with the existing fantasy kit, which Opus produced before?

### The brief (identical for both arms)

> You are building four asset sets for **Cullet**, a glassmakers' harbour on a treeless rock. Read `docs/SMALL_CITY.md`, section 1 (identity, palette, material and shape language, wear) before you start. Follow it exactly.
>
> **Deliver** one Blender Python script that runs headless (`blender -b -P <script> -- --out <dir> --seed 1`) and writes the eleven GLB files below, plus `report.json` with each model's footprint, height and triangle count. You may import helpers from `living/tools/blender/buildings.py`. You may not edit it.
>
> **Conventions** (as `buildings.py`): metres; origin at the floor, centred on the footprint; +Z up; the front faces −Y. Colour is per vertex (`Color`) on one white material named `Body`, with the surface tag in alpha through `surfaces.alpha`. Glowing parts use the materials `Glow`, `GlowAmber` or `GlowCyan`. A glowing pane's vertex colour is its daytime glass colour. Buildings have a stepped stone foundation 1.8 m below the floor; props have 0.4 m. Use no textures and no external files. The same seed must give the same output. Use only the palette in section 1, with jitter up to ±0.05.
>
> **1. `cone.glb`: the Cone.** A brick glass-furnace cone. Round base 14.0 m across. 24.0 m to the rim. Rim opening 3.2 m across. Sooted brick on a 1.2 m basalt plinth. Five iron bands. Three arched mouths at the foot, 2.4 m wide and 3.0 m high, at the front and at ±120°; the front one glows. A lean-to pot room on the left, 5 × 4 m, with a slate roof. An outside timber stair and gallery to a charging door at 7 m. Soot fans above each mouth and 4 m down from the rim. One band of newer brick between 9 and 12 m on the south-west side. At most 12,000 triangles.
>
> **2. `row.glb`: a Low Row terrace.** One model: four houses sharing walls. Overall 22.0 × 7.5 m; fronts 5.0, 6.0, 4.5 and 6.5 m wide. Two storeys and an attic; eaves 5.6 to 6.2 m; ridge at most 9.5 m. The street drops 0.5 m at each party wall, so floors and roofs step. Basalt ground floor, limewashed upper floor, slate roof, a chimney on each party wall. Each house has a 0.9 × 2.0 m door with a two-step stoop, and small-paned windows (panes at most 0.45 m, at most two glass colours in a window). The four houses must be told apart at a glance:
> - House 1, tidy: chalk-blue door, a flower box, a bench.
> - House 2, a fisher's: oxblood door, a string of glass floats, a creel, oilskins on a peg.
> - House 3, empty: boarded ground window, missing slates, weeds on the stoop, no glow.
> - House 4, crowded: mustard door, a lean-to on the end wall, a washing-line bracket, an extra chimney pot.
>
> Wear inputs for the whole row: salt 0.6, soot 0.1, wind 0.7. At most 16,000 triangles.
>
> **3. `glasshouse.glb`: a Ladder glasshouse.** A lean-to, 12.0 × 4.5 m. The back wall is a whitewashed stone wall 3.2 m high and 0.5 m thick, part of the model. The front is a 0.7 m basalt dwarf wall. A timber glazing frame in flaking pale paint, bays 1.0 m wide. A single-pitch roof falling from 3.2 m to 1.9 m. Panes at most 0.45 m, drawn opaque in pale aqua with the `glass` surface. Between 15% and 25% of panes are not original: boarded, a mismatched colour (at most 8%), or missing (3 to 5 holes). Two roof vents propped open and one door open. Beds with plants inside, visible through the door, the vents and the holes. A rain butt with a downpipe, a kelp heap with a fork at one end, a cold frame beside it. One faint glowing strip inside for a lantern. At most 9,000 triangles.
>
> **4. The Strand set: eight props, one GLB each.**
> - `net_rack.glb`: a drying rack with a net, 3.0 × 0.6 × 2.2 m.
> - `barrels.glb`: three fish barrels and one on its side, salt-crusted, 1.8 × 1.4 × 1.1 m.
> - `creels.glb`: three wicker creels, one tipped with kelp spilling, 1.4 × 1.0 × 0.9 m.
> - `bollard.glb`: a cast-iron ship's bollard, 1.1 m high and 0.6 m across, far too big for a fishing boat, with a coil of rope.
> - `quay_lamp.glb`: an iron post 3.2 m high with a lantern of mismatched glass panes that glows.
> - `boat.glb`: an upturned boat on two trestles, 4.2 × 1.5 × 1.3 m, tarred and patched.
> - `peat_stack.glb`: stacked peat under a tarred cloth, 2.0 × 1.2 × 1.4 m.
> - `floats.glb`: a 2 m post hung with glass floats (0.25 m, in net bags, three colours), with a 0.8 m crate of cullet beside it.
>
> Each at most 1,500 triangles; the boat at most 2,500.
>
> **Judged on:** silhouette; whether it belongs to this town and no other; scale against a 1.75 m person; palette and materials; wear that has a cause; individuality without noise; how it reads from the game camera (22 m away, 28° down); and glow at night.
>
> **Process.** You may render your own models through the game's asset view and revise, up to three rounds. Do not look at the other arm's files. Write a short `notes.md`: what you built, what you would do next, and anything in the brief you could not meet.

### Files, so the arms cannot collide

| | Fable 5.2 arm | Opus 5.5 arm |
|---|---|---|
| Script | `living/tools/blender/ab/cullet_fable.py` | `living/tools/blender/ab/cullet_opus.py` |
| Output | `.local/living/small-city/ab/fable/` | `.local/living/small-city/ab/opus/` |
| In it | the 11 GLBs, `report.json`, `notes.md`, `renders/` | the same |

Neither arm writes anywhere else. In particular, neither touches `living/game/assets/`, `living/rules/data/buildings.json`, `buildings.py`, or any `gen_*.sh`. Neither runs `--table`, which rewrites the planner's footprint table. Both arms get the same effort setting, the same three rounds and the same prebuilt game binary.

The asset view copies outside files into `living/game/assets/view/` under their own names. Both arms use the same file names, so they must not run the view at the same time on one checkout. Give each arm its own worktree, or run them one after the other.

### Rendering, so the pictures compare blind

The coordinator runs this, not the arms.

1. **Blind copy.** A script copies both arms' models to `.local/living/small-city/ab/blind/`, as `x-<piece>.glb` and `y-<piece>.glb`. Which arm is x is chosen at random for each piece. The key goes to `key.json`, which the owner does not open until the scores are in.
2. **Baseline.** The nearest pieces of the existing fantasy kit, rendered the same way and shown labelled, as the starting point: the tower, four townhouses side by side, the workshop, and the market stall, barrel, crate, bench and lamp.
3. **Asset view, day.** The game's own renderer on the 1 m checker, with one prebuilt binary for everything. Size 1600 × 900. `LIVING_GAME_VIEW_ENV=island`, `LIVING_GAME_HOUR=15`. Shots: `three-quarter`, `front`, `back`, `game`, `140:12:1.0`, `40:10:0.4:0.25` (close and low) and `above`.
4. **Asset view, low sun.** `LIVING_GAME_HOUR=18.5`. Shots: `three-quarter` and `game`.
5. **In a scene.** The coordinator lays out each side's eleven pieces the same way on a 60 × 40 m pad: the Cone at the back right, the row at the back left, the glasshouse in front of the row, the props along a 30 m quay edge. These are two temporary look-dev environments, `ab_x` and `ab_y`, removed afterwards. A tour at 13:00 and at 21:30 takes the shots `default`, `close` and `30:14:40:55`. The night tour is the only test of glow.
6. **Silhouette.** The `front` and `three-quarter` shots of the three buildings, reduced to black on white at 64 pixels high.
7. **One sheet per piece:** x on the left and y on the right, with the same shots in the same order and no file names shown.

### Scoring

The owner scores each piece blind, from 1 to 5 on each line.

| Criterion | Weight | 1 means | 5 means |
|---|---:|---|---|
| Silhouette | 3 | Could be anything | Known at once as a black shape |
| Belongs to Cullet | 3 | Could stand in any game | Could only stand here |
| Reads from the game camera | 3 | Mush or noise at 22 m | Clear shapes, with detail where the eye lands |
| Scale and proportion | 2 | Doors, steps or panes look wrong beside a person | A person would fit every part |
| Material and palette | 2 | Colours off the palette, or materials unclear | You can name each material and where it came from |
| Wear with a cause | 2 | Clean, or dirty at random | Each mark has a reason you can point to |
| Individuality without noise | 2 | Clones, or clutter | The four houses and eight props are distinct and calm |
| Night and glow | 1 | Dead, or glaring | Warm, sparse and true to what is lit |

The coordinator checks these separately, as pass or fail: triangle budgets; footprints within 0.1 m; origin and foundation; surface tags on at least 90% of lit triangles; only `Body` and glow materials; the same output from the same seed; generation time; lines of script, and how much is shared between pieces.

**Verdict.** The weighted total per piece. An arm that wins three of the four sets, or wins on total with no failed check, becomes the model for the kit. If the result is split, take each piece from its winner and have the kit's author fold the better ideas of the loser in.

## 8. Build plan

Each phase ends with something the owner can look at. "Touches" names what changes. Who builds each part is the coordinator's call under the project's routing rules.

| Phase | What is done | Touches | Owner's checkpoint |
|---|---|---|---|
| **0. Decide** | The owner answers the decisions below | This document | The answers |
| **1. Model A/B** | Both arms build the four sets. Blind renders and scores. | Assets (tools only, in scratch) | Scores the sheets. Picks the model for the kit. |
| **2. Grey city** | Land parameters for the Wrack. The plan file with all 65 lots, streets, terraces and stairs. Boxes of the right size on every lot. Walk it with the game camera. | Seed format: an authored plan (the planner today only generates). Rules: reading the plan instead of planning. Client: nothing new if it draws lots as now; a `cullet` environment. | Walks the grey city. Are the landmarks seen from everywhere? Do the rows feel like streets? Is it too big or too small? |
| **3. The kit** | Landmarks, rows, working buildings, ground, then dressing. The wear pass. The night pass. | Assets: `cullet.py`, `gen_cullet.sh`, the footprint table. Client: the mood file, textures, seats, glass glow, smoke. | Walks the dressed, empty city at noon, dusk and night |
| **4. Rules** | The day length in the seed. The needs and cold laws as Cullet's overlay. Goods and recipes. Fire that eats fuel. Sight values. Night as a law. Spots at places. Per-person rhythm. Optionally the tide, and decay of panes. | Rules and Rhai. Seed format: `day`, goods, `rhythm`, spots. Verification: `verify-core`, `verify-generation`, and `maintain-verification-skill` where a surface changes shape. | A census of ten game days with no minds: nobody starves, stores hold, fuel falls slowly, and people's hours are spread out |
| **5. People** | The Cullet bible and anchor file from section 3. The 64 sheets. Outfits, recipes and clips. | Seed content. Assets: outfits, clips. A paid authoring run. | Reads the bible before the sheets are drafted. Looks at a line-up of all 64. |
| **6. Minds** | All 64 with minds. First with the fake model, then one paid hour. | Seed: `rules.minds`. The mind service: needs in prompts, load. Verification: `verify-minds`, `verify-llm`. | Watches an hour. Do they keep different hours? Do the tensions come up unprompted? |
| **7. Play** | The owner plays. Then an 8-hour run with players and minds. | Measurement: tick, bytes, memory and model spend, under the evidence rules in AGENTS.md | The play-test verdict |

**Order and overlap.** Phase 1 can start today. Phases 2 and 4 do not depend on each other. Phase 3 needs phases 1 and 2. Phase 5's bible can be written during phase 3. The client-feel work runs alongside all of it and is not in this plan.

**Phase 2, engine part (2026-11-11, branch `plan-1`).** A land seed can now carry hand-authored plans (`map.params.plans`): levels at exact heights, streets, stairs, a square, a harbour and lots with explicit models and heights, drawn as grey boxes until the kit exists. Households bind to lots (`homes`). See [authored plans](AUTHORED_PLANS.md). The full plan followed in phase 2's second part (below).

**Phase 2, the grey city (2026-11-11, branch `plan-2`).** The plan of all 65 buildings (93 lots), the Wrack's land and the grey boxes, walkable in the real client: [Cullet's plan](AUTHORED_PLANS.md#cullets-plan). The generator could not make this island from its parameters (its coast follows a random range, its sand is a strip at the water's edge, and resources could not be put at named points), so three general seed fields were added: an authored coastline and relief stamps (height, region kind, ground) in `map.params.relief`, and `resources` in a plan. Measured: the quay end to end in 58 s, the Fish Steps to the Crown in about 80 s (not the 2 minutes of §2), the Lintel in about 4 minutes. From the game camera's height the five landmarks are seen from 75 to 99% of the town's streets; the rules' own sight, blocked by the terrace drops, sees them from 2 to 19%.

**Phase 5, the bible and the cast (2026-11-11, branch `bible-1`).** [`bible.md`](../living/seeds/worlds/cullet/bible.md) and [`cast.json`](../living/seeds/worlds/cullet/cast.json): the 64 residents of §3 in 22 households, each household on its plan lot, each person with §3's want and what is going on as anchors, kin both ways, ties, a starting rhythm, and the secrets on their knowers' entries only; 20 situations with every side's view, and the 11 tensions. `author_world.py cullet --check` checks them without a model, and `--dry-run` builds the 22 prompts and estimates the paid run (53 calls with DeepSeek V4.1 Flash, about €0.16 to €0.39); no sheets are drafted yet ([authored worlds](AUTHORED_WORLDS.md#cullet-cullet-cast-by-hand-with-anchors)). To fill kin, the bible adds the fever winter six years ago and a few family links that §3 does not give; the owner reviews them before the run.

**What could stop it:**

- **The authored plan** (phase 2) is the largest unknown. The planner generates settlements, and nothing today reads a hand-made layout. `SeedTown.buildings` is the nearest existing hook.
- **Goods** (phase 4) depend on how far "traits, not lists" has gone in the rules.
- **Bases** (phase 5) need the owner's hands in VRoid Studio.
- **64 minds at once** (phase 6) has not been run. It needs a load trial before the paid hour.
- **This is not a scale result.** Cullet is 64 residents and a few players. It says nothing about 216 or 2,000.

## Decisions for the owner

| # | Decision | Recommendation |
|---|---|---|
| 1 | Is the city Cullet: a glassmakers' harbour on a treeless rock? | Yes |
| 2 | Characters' bases: who makes the men, elders and children? | The owner makes four to six bases in VRoid Studio |
| 3 | Population: 40, 64 or 96, all full minds? | 64 |
| 4 | Day length: 24, 48 or 72 real minutes? | 48 |
| 5 | The survival targets in section 4 | Accept, then tune in the soak |
| 6 | Sight: 48 m by day, 14 m by night, 28 m in lamplight; names at 24 m | Accept for Cullet. The perception worker judges the cost. |
| 7 | No interiors; working buildings have open fronts | Accept for this test |
| 8 | The Lintel: does this world have a shut gate on the headland? | Yes, as a fact with no purpose attached. It can be left out with no other change. |
| 9 | New rules: goods, fuel-burning fires, decay of panes, the tide | Goods and fuel are needed. Decay and tide are recommended, and can follow. |
| 10 | A hand-authored plan for this city, instead of the generator | Yes. It is what gives the place its character. |
| 11 | Paid runs: the sheets (about €0.50), then minds (about €15 an hour) | Authorise each when its phase is reached |
| 12 | The A/B: is the brief right, and will the owner score it blind? | Run it as written |
| 13 | Fog of war: which option to try first | A (soft edge), then B as a slider |
| 14 | Does Cullet replace the island as the game's test world? | Yes. The island stays for the labs. |

### The owner's answers (2026-11-11)

Given through the general coordinator. The owner's words on the recommendations: "I kind of agree with the recommendations". So they are accepted, and anything that turns out wrong in practice is raised again.

| # | Answer |
|---|---|
| 1, 3, 4, 5, 7, 8, 9, 10, 11, 14 | Accepted as recommended. For 9: goods and fuel now, decay and tide later. For 11: each paid run is authorised when its phase is reached, through the general coordinator. |
| 2 | **Decided after the spike (2026-11-11): replace VRoid with our own generator.** The spike's `living/tools/blender/person.py` built an adult man, a woman, an elder and children, all with no VRoid base. The owner's words: "It's a solid start, but we can and should do much better. I would like to get to a point where we can generate and parameterize characters that are similar quality to what we currently have." So the bar is VRoid's quality close up, not only at the game camera, from a parameterized tool of our own: age, build, sex, face, hair and outfit, with a seed giving a repeatable person. This follows AGENTS.md's "Build tools we own". The work runs as its own track on Fable 5.2, in passes the owner judges by looking, ours beside a VRoid control. The order is faces (quality and variety), then hair, then women's silhouettes and outfits, then cloth and hands. Spring bones, outfit slots, level of detail and crowd frame cost come later; crowd cost is measured before Cullet's 64 are built with it. |
| 6 | Accepted with a requirement. The distances stand as Cullet's law values: 48 m by day, 14 m in the dark, 28 m in lamplight, names at 24 m. What the screen shows of the ground and what it shows of people must agree; today you see the whole place clearly while people pop in and out. Sight stays as law values, so it can change without code. Longer sight wakes more minds, so it is measured at 64 residents before the values are called settled. |
| 12 | Fable 5.2 builds the asset kit, starting from the Fable arm (branch `ab-arm1`). The owner liked Fable's results more in general. That is a general preference; no sheet-by-sheet scores were given. The Opus arm (`ab-arm2`) is kept for the record. |
| 13 | Replaced. How the view shows the edge of sight is being prototyped in the client for the owner's next play-test. What the owner picks there replaces options A to D. |

**Decisions 4 and 5 against the current rules.** Section 4's "Now" column was written before the change that paces people's needs to real time (`person_pace` 0.3 in `skills.rhai`, on the island's 12-minute day). With that law, hunger already rises about 1.2 a real minute, not 5. Phase 4 derives Cullet's law values again from the current script, for a 48-minute day, and keeps the outcomes in the targets table. Where the two differ, it records which it chose. Done on `rules-1`: [Cullet's rules](CULLET_RULES.md) has the law table, the outcomes computed from the script, and the choices.
