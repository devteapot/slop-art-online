# Goods: two proposals for every world

**Status:** proposals, not built. Written on branch `goods-3` (2026-11-12) for the owner's direction that everything should be craftable from base resources gathered in the world ([goods](GOODS.md)). Each would change the rules of every world. They need the owner's or the general coordinator's decision before anyone builds them.

## 1. Minerals: living things regrow, minerals do not

**The recommendation to test.** Living things regrow: plants, kelp, fish stocks and animals. Minerals do not regrow. A deposit is large and finite, and new deposits are found or opened by work. Today every resource kind regrows like a plant. A boulder grows back 0.1 stone a game hour, and a peat bank 0.233 peat.

### Peat is the hard case

Peat is Cullet's fuel. Its numbers come from [`living/tools/goods_minerals.py`](../living/tools/goods_minerals.py), on the pattern of rules-3's [`cullet_winter.py`](../living/tools/cullet_winter.py). It reads the plan's peat banks, fires and stores, and Cullet's laws: burn rates, gathering time, winter share and day length. To rerun it: `python3 living/tools/goods_minerals.py`. The town is counted as one peat heap, one game day at a time.

**Inputs**

- 18 peat banks. Each holds up to 11.2 and regrows 0.233 a game hour. That is 101 peat a growing day, and none in winter.
- A year is 8 game days, and the last 2 are winter. It gives 605 peat.
- At the start the town holds 1,684 peat in its stores, its packs and the fires' first fill.
- Gathering one peat takes 5 real seconds (2.5 game minutes), so one cutter cuts 24 a game hour. The plan's 3 cutters, working 5 game hours a day, could cut 360 a day.
- The town has room for 2,756 peat: the peat barn, the Cone yard's store, the fires' own fill, and each household's 24.

| How much is burnt | Peat a game day | A year | Share of a year's burn that regrowth covers |
| --- | ---: | ---: | ---: |
| design (SMALL_CITY §2: the Cone at full firing, and the homes about as much again) | 144 | 1,152 | 52% |
| evenings (the Cone at full firing, each home hearth lit 6 game hours, the oven and smokehouses 8) | 154 | 1,232 | 49% |
| all lit (every fire the plan places kept burning around the clock) | 384 | 3,072 | 20% |

The "about 70%" in the brief is a growing day: 101 ÷ 144. Winter regrows nothing, so over a whole year regrowth covers 52%.

**Three rules, over 12 game years**

- *regrows*: today's rule.
- *finite*: a cutting is a deposit of 330 peat with no regrowth. That is a 10 m face, 1 m deep. Cutters cut what the town has room for. When a cutting is spent, one cutter opens a new one in 5 game hours, until the Moss is used up. At this size the Moss holds 200 cuttings, or 66,000 peat.
- *finite, drying*: as finite, but cut peat is wet. It burns only after drying 2 game days, and nothing dries in winter.

| Burn | Rule | Heap after year 1 | Heap after year 3 | First day short | Days short in 12 years | Peat short | Moss left after 12 years |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| design | regrows | 1,238 | 143 | 28 | 69 | 4,783 | – |
| design | finite | 2,612 | 2,612 | none | 0 | 0 | 51,248 |
| design | finite, drying | 1,972 | 2,036 | none | 0 | 0 | 51,248 |
| evenings | regrows | 1,158 | 0 | 24 | 73 | 5,743 | – |
| evenings | finite | 2,602 | 2,602 | none | 0 | 0 | 50,298 |
| evenings | finite, drying | 1,892 | 1,986 | none | 0 | 0 | 50,298 |
| all lit | regrows | 0 | 0 | 7 | 90 | 27,823 | – |
| all lit | finite | 1,492 | 718 | 38 | 59 | 3,170 | 33,990 |
| all lit | finite, drying | 52 | 0 | 16 | 21 | 4,490 | 33,990 |

At the design burn the Moss lasts 57 game years. At the evenings burn it lasts 54, and with everything lit it lasts 21.

### What this says

- **Today's rule starves Cullet of peat. The finite rule does not.** Under today's rule, at the design burn, the stock runs out on game day 28, in the 4th game year. That is about 22 real hours on the 48-minute day. After that the town is short of peat for most of every winter.
- **Under the finite rule, regrowth stops being the limit.** The cutters' labour and the town's storage room become the limits instead. Three cutters cover the design and evenings burns with time to spare. Only the "all lit" ceiling is short: 384 a day is more than 3 cutters can cut. That shortage is real, because it would take more cutters.
- **The game is not starved of peat.** It loses the squeeze that SMALL_CITY §2 wanted ("someone has to decide something"), unless the squeeze moves somewhere else.
- **Drying keeps a seasonal squeeze.** Peat for winter must be cut and stacked by the end of autumn, which is the real peat calendar. At the all-lit burn, drying is what runs the town short.
- **The Moss at real scale holds about 2 million peat.** The worked area is about 7 ha, cut 1 m deep, and one peat is about 3 kg. Even 66,000 is a choice made so that depletion can be seen within a few dozen game years. The proposal is therefore about where the limit sits: the cutters, their pay and their year, rather than a stock that drains on its own.
- **Stone.** Today Cullet's only stone is wild boulders, at a `resource_scale` of 0.4. Each holds 6 and regrows 0.1 a game hour. Building is the only demand. The Cone takes 24 stone, a hall 30, a hearth 4, and everything Cullet's laws build together comes to about 160. Under the finite rule a boulder is 6 stone once. The quarry face on the upper terrace ([layout](CULLET_LAYOUT.md#the-quarry)) would be the deposit, opened by work. Neither the 160 stone nor the clay pit's needs (about 50 for the fires, plus pots and crucibles) comes near a finite deposit of any honest size. Nothing starves.
- **Sand.** Sand is a mineral, but the sea brings it. It could stay renewing at the tide's rate as a flow, and be called that in the rules, rather than counted as regrowth. Glass takes 2 sand, and about 12 glass a day uses 24 sand.

### What it would take

1. **A resource kind trait instead of the regrowth rate.**
   - `regrow_per_h: 0` with a `deposit` amount, or `finite: true` with `max` as the whole deposit.
   - The authority already stops a node at 0 and removes nothing. A spent node stays at 0, which says "this cutting is worked out".
2. **An act to open a new deposit.** For example `dig` or `open`, which places a node of the kind where one stands. The rules would allow it only on the ground the kind's `ground` names, and only within an area that has that mineral, such as the Moss stamp or the quarry face.
   - This needs a primitive that places a resource node from an act. `plant` does that today, but for `berry_bush` only, hard-coded in `act.rs`. Generalising it into an effect that plants or opens a node of a kind is a small engine change.
3. **Drying, if wanted.**
   - An item that becomes another after time (`dries_to`, `cures_to`). Spoiling is the same mechanism, but it ends in nothing rather than in another item.
   - It needs a timed transform in the spoiling sweep (`tick::spoil`), which already visits every stack once a real minute. The new cost is a write per stack that turns.
4. **Cullet's values.** These are the numbers above. The island's boulders, clay banks and reeds would change too. Today a boulder holds 6 and regrows. Under the finite rule its stone would come from finding more boulders, or from a quarry.

**A decision is needed:** whether "minerals don't regrow" applies to every world now, or to Cullet first; whether drying comes with it; and the deposit sizes.

## 2. Weapons and metal

With sheathe and draw arriving, a weapon should be something a character owns, made by someone from something.

**What there is today**

- A spear is crafted from 2 wood and 1 stone. Bows and arrows are crafted from wood, fiber and stone.
- A strike needs no weapon. `strike_done` reads only whether a spear is held, as a bonus, and the starter bar's sword icon is presentation. There is no metal anywhere.
- In Cullet the bible's iron is "ship fittings, none new": bands, bollards and hinges. goods-3 makes the Cone's 4 blowpipes seed-only for that reason ([goods](GOODS.md)).

### The smallest honest chain

There are two candidates:

| Chain | Steps | New rules and data |
| --- | --- | --- |
| **Salvaged ship iron + a smithy** (the coordinator's lean) | Prise iron from a ship-day fitting, a finite deposit placed by the plan. Work it at a smithy, a fire that burns, with peat or charcoal, knowing smithing: 1 iron and 1 fuel make a blade, a spearhead or a blowpipe. | 1 resource kind (`ship_iron`, finite: proposal 1), 1 structure (`smithy`, `burns`), 1 technique, 1 item (`iron`), recipes for what is forged, and a `weapon` trait on what strikes harder |
| **Bog iron** | Dig bog ore on the Moss, a finite deposit. Burn wood into charcoal at a clamp. Smelt ore and charcoal into a bloom at a bloomery. Forge the bloom at a smithy. | 2 resource kinds, 2 structures, 2 techniques, 3 items, and the forging recipes |

**Numbers for salvage in Cullet**

- The plan's quays have about ten ship's bollards. Each is cast iron 1.1 m high, about 150 kg.
- The mole, the Cone's five bands, hinges and anchors add more.
- At one iron to about a kilo of worked bar, a deposit of about 300 iron is honest for what can be prised loose without pulling down the Cone's bands.
- At 1 iron for a blade or a spearhead and 2 for a blowpipe, that is about 150 weapons, or 30 new blowpipes and 90 blades.
- Each piece taken is a bollard or a band gone. That gives the town a tension of its own: who may take the town's iron, and for what.

**Weighing them**

- **Salvage fits the bible** and is the smallest chain: one finite deposit, one workplace, one technique. Its limit is real and visible, because when the ship iron is gone it is gone.
- **Bog iron makes iron renewable on a long view.** Bog ore re-forms over decades, and it gives the Moss a second use. But it is twice the content, and its charcoal competes for the Hanger's 70 trees, which Bram needs fourteen of for the *Second Thought*.
- **Either chain needs proposal 1's finite deposits to be honest.** Without them, ship iron would regrow on the bollards.

**What it would take, beyond proposal 1**

1. **Who holds a weapon decides what they can strike with.** That is a rule for every world:
   - a `weapon` trait on items (spear, knife, sword), read by `strike_check` and `strike_done`;
   - sheathe and draw as the held state the combat shape reads ([interface](INTERFACE.md): "a strike needs the weapon drawn" belongs in the combat shape).
   - The island would then need a weapon to strike well. Its people carry 21 spears at the start, and every newcomer arrives with a bow. A bare-handed strike could stay at today's damage, with a weapon adding to it, so that nobody loses the ability to fight back.
2. The smithy, the iron item and the forging recipes, as data in a world's laws (Cullet's).
3. A ship-iron deposit in Cullet's plan (`cullet_plan.py`): a few nodes at the bollards and the dry dock.

**Recommendation for Cullet's first version:** keep spears and bows for now, made from wood and stone as today, and have strikes read a held `weapon` trait when sheathe and draw land. Add salvage and a smithy, the coordinator's lean, as soon as proposal 1's finite deposits exist. It is the smallest chain, and it fits what Cullet is: a town living off what the ships left. Bog iron can follow if the town ever runs out of ship iron.
