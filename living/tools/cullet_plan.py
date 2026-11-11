#!/usr/bin/env python3
"""Cullet's grey city: write the hand-authored plan and the land seed (docs/SMALL_CITY.md, phase 2).

    python3 living/tools/cullet_plan.py            # writes both files below
    python3 living/tools/cullet_plan.py --check    # exits 1 if either file differs from what it would write

Writes
- `living/seeds/worlds/cullet/plan.json`: the town as SMALL_CITY §1 and §2 describe it, in the
  plan frame (origin at the Fish Steps, x east, y north, metres): levels, streets, wynds, the
  square, the harbour, 74 lots (65 buildings and 9 open lots), spots, authored resources, and the
  asset generator's inputs per lot (wear, household, door colour, keepsake), which the engine
  ignores;
- `living/seeds/cullet.json`: the land seed, the Wrack (an authored coastline and relief stamps,
  `docs/AUTHORED_PLANS.md`) with the plan merged into `map.params.plans`.

Every number that varies has a cause written beside it: a front's width comes from its household's
size and family, a lot's wear from where it stands (height above the sea, distance and bearing
from the Cone, which way it faces) by SMALL_CITY's wear table, its height from its storeys and
roof pitch. Nothing here is random; the same run writes the same files. Standard library only.
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN_OUT = ROOT / "living/seeds/worlds/cullet/plan.json"
SEED_OUT = ROOT / "living/seeds/cullet.json"

SEED = 83  # year 83 since the Last Sail
SIZE = 1024
# The plan's (0, 0), the Fish Steps, on the land (x east, y south). The island's middle, plan
# (2, 272), lands on the map's middle (512, 512).
ORIGIN = (510.0, 784.0)


def land(p):
    """Plan frame -> land metres (rotation 0: plan north is land north)."""
    return [round(ORIGIN[0] + p[0], 2), round(ORIGIN[1] - p[1], 2)]


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def r2(v):
    return round(v, 2)


# ---------------------------------------------------------------------------------------------
# Levels (SMALL_CITY §1 districts, §2 heights): the quay at +2, the Rows at +5.5, +9.5, +13.5,
# the upper terrace at +17 and the Crown at +20. Outlying pads sit at their stamped ground.

H = {"strand": 2.0, "mole": 2.0, "low": 5.5, "mid": 9.5, "high": 13.5, "upper": 17.0, "crown": 20.0, "moss": 32.0, "hanger": 14.0, "headland": 46.0}
BAND = {"strand": (0, 32), "low": (32, 60), "mid": (60, 90), "high": (90, 120), "upper": (120, 134), "crown": (134, 196)}
WEST = {"low": -165, "mid": -175, "high": -185, "upper": -260, "crown": -260}
EAST = {"low": 80, "mid": 80, "high": 80, "upper": 55, "crown": 55}
# The Heron stands on a stage out over the water, and the mole leaves the quay at x 126..146.
HERON_STAGE = (-21.5, -12.5, -6.0)
# The Fish Steps go down into the harbour from a 3 m notch in the quay's edge.
FISH_STEPS = [[-4, 0], [-4, -3], [4, -3], [4, 0]]
MOLE = {"root": (126, 146, -14), "arm": (132, 139, -54), "tip": (129, 142, -67)}

LEVELS = [
    {"id": "strand", "height_m": H["strand"], "area": [[-125, 0], [HERON_STAGE[0], 0], [HERON_STAGE[0], HERON_STAGE[2]], [HERON_STAGE[1], HERON_STAGE[2]], [HERON_STAGE[1], 0], *FISH_STEPS, [175, 0], [175, 62], [80, 62], [80, 32], [-125, 32]],
     "note": "the quay (x -75..75, y 0..10), the strand buildings behind it, the slip and the dry dock west, Cinder Row east (x 80..175, up to y 62), all at +2"},
    {"id": "mole", "height_m": H["mole"], "area": [[126, 0], [126, -14], [132, -14], [132, -54], [129, -54], [129, -67], [142, -67], [142, -54], [139, -54], [139, -14], [146, -14], [146, 0]],
     "note": "the ship-day mole: a 20 x 14 m root with the lamp house, a 7 m arm, and the Watchglass's 13 m tip 60 m out"},
]
for lv in ("low", "mid", "high", "upper", "crown"):
    y0, y1 = BAND[lv]
    LEVELS.append({"id": lv, "height_m": H[lv], "area": rect(WEST[lv], y0, EAST[lv], y1)})
LEVELS[2]["note"] = "Low Row and the Ladder's first terrace"
LEVELS[3]["note"] = "Mid Row and the Ladder's second terrace"
LEVELS[4]["note"] = "High Row and the Ladder's third terrace"
LEVELS[5]["note"] = "the upper terrace: the Ladder's fourth, and the landing below the Crown"
LEVELS[6]["note"] = "the Crown (x -55..55) and, west of it, the root plots and the Ladder's top terrace"
OUTLYING = {
    "moss": {"area": rect(-78, 318, -46, 344), "note": "the turf house's yard on the Moss"},
    "hanger": {"area": rect(196, 196, 218, 214), "note": "the Hanger cottage's yard, at the foot of the copse"},
    "headland": {"area": rect(-40, 520, -10, 536), "note": "the Lintel's ground on the north headland"},
}
for k, v in OUTLYING.items():
    LEVELS.append({"id": k, "height_m": H[k], "area": v["area"], "note": v["note"]})

SEA = [[-125, 0], [HERON_STAGE[0], 0], [HERON_STAGE[0], HERON_STAGE[2]], [HERON_STAGE[1], HERON_STAGE[2]], [HERON_STAGE[1], 0], *FISH_STEPS, [126, 0], [126, -14], [132, -14], [132, -54], [129, -54], [129, -67], [142, -67], [142, -54], [139, -54], [139, -14], [146, -14], [146, 0], [175, 0], [175, -100], [-125, -100]]

# Row streets: 5 m wide, 9 m into each band, so a 6.5 m walk overlooks the drop to the row below.
ROW_Y = {lv: BAND[lv][0] + 9.0 for lv in ("low", "mid", "high")}
FRONT_GAP = 2.8  # a house's front stands 2.8 m from its street's middle: 0.3 m of kerb
HOUSE_DEPTH = 7.5

# The five wynds (x of the lane) and the flights that climb them, level to level.
WYNDS = [
    ("the Ladder Wynd", -100, ["strand", "low", "mid", "high", "upper", "crown"]),
    ("the Net Wynd", -30, ["strand", "low", "mid", "high"]),
    ("the Tally Wynd", [24, 32, -8, 34, -8], ["strand", "low", "mid", "high", "upper", "crown"]),
    ("the Store Wynd", 66, ["strand", "low", "mid", "high"]),
]
STAIR_W = 3.0
SLOPE = 0.55  # rise per metre of run: 0.18 m treads on 0.33 m goings


def flight(x, lo, hi):
    """A flight from level lo up to hi at plan x, against hi's drop: (foot, head)."""
    rise = H[hi] - H[lo]
    run = rise / SLOPE
    b = BAND[hi][0]
    return [x, r2(b - run + 0.5)], [x, r2(b + 0.5)], r2(rise)


# ---------------------------------------------------------------------------------------------
# Wear (SMALL_CITY §1 "History and wear"): from where a lot stands, never rolled.

CONE = (147.0, 33.0)


def bearing(dx, dy):
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


FACING_DEG = {"north": 0, "east": 90, "south": 180, "west": 270}


def wear(at, floor_m, facing, age, repair, empty, sheltered=0.0):
    fdeg = FACING_DEG.get(facing, facing) if isinstance(facing, str) else facing
    # Salt: below +6 m, strongest on the quay.
    salt = max(0.0, min(1.0, (6.0 - floor_m) / 4.0))
    # Soot: within 60 m north-east of the Cone (the wind is south-westerly); a little within 20 m.
    dx, dy = at[0] - CONE[0], at[1] - CONE[1]
    d = math.hypot(dx, dy)
    downwind = max(0.0, math.cos(math.radians(bearing(dx, dy) - 45))) if d > 0 else 1.0
    soot = max(0.0, 1 - d / 60) * downwind + max(0.0, 1 - d / 20) * 0.5
    # Wind: how much the front faces south-west, and how high and open it stands.
    wind = 0.55 * max(0.0, math.cos(math.radians(fdeg - 225))) + 0.45 * min(1.0, floor_m / 34.0)
    wind *= 1.0 - sheltered
    w = {"salt": r2(salt), "soot": r2(min(1.0, soot)), "wind": r2(min(1.0, wind)), "age": r2(age), "repair": r2(repair), "empty": r2(empty)}
    w["cause"] = f"+{floor_m:g} m above the sea; {d:.0f} m from the Cone at bearing {bearing(dx, dy):.0f}; front faces {fdeg:g}"
    return w


def pitched(storeys, storey_m, span_m, pitch_deg, plinth=0.4):
    """Height to the ridge: storeys, a plinth, and a roof pitched over half the span."""
    return r2(storeys * storey_m + plinth + span_m / 2 * math.tan(math.radians(pitch_deg)))


# ---------------------------------------------------------------------------------------------
# Households (SMALL_CITY §3): who lives where, and the marks on their houses.

HOUSEHOLDS = {
    # key: (name, family, people, door colour, keepsake)
    "pontil": ("Pontil", "kiln", 3, "chalk_blue", "a sill of cullet, one piece of every colour Ode has kept"),
    "hollin": ("Hollin", "kiln", 4, "sea_green", "a bucket of off-cuts the children play with by the step"),
    "sarro": ("Sarro", "kiln", 2, "chalk_blue", "a pontil rod hung over the door"),
    "quill": ("Quill", "kiln", 3, "mustard", "a slate tally board by the door"),
    "brandt": ("Brandt", "kiln", 3, "sea_green", "a hen coop against the front"),
    "marl": ("Marl", "kiln", 2, "mustard", "wind chimes of cullet"),
    "dunmore": ("Dunmore", "kiln", 3, "chalk_blue", "a bench made from a boat's thwart"),
    "calloway": ("Calloway", "strand", 4, "sea_green", "a ship's knee of timber propped by the door"),
    "tarn": ("Tarn", "strand", 7, "oxblood", "a row of glass floats; the Tarns have always painted their door so"),
    "okoro": ("Okoro", "strand", 4, "mustard", "a string of sea-glass, each colour from a known wreck"),
    "vane": ("Vane", "strand", 2, "chalk_blue", "a counters board chalked on the step"),
    "morrow": ("Morrow", "strand", 2, "oxblood", "a caged gull"),
    "sato": ("Sato", "strand", 3, "sea_green", "a sack of kelp ash and a smoke-grey line of washing"),
    "dunlin": ("Dunlin", "strand", 2, "chalk_blue", "a lamp hook and a creel"),
    "greave": ("Greave", "ladder", 4, "sea_green", "seedling trays on the sill"),
    "fenwick": ("Fenwick", "ladder", 4, "mustard", "a rain gauge on a post"),
    "stannard": ("Stannard", "ladder", 2, "oxblood", "a stack of odd slates"),
}

# House number -> household, empty (sound) or a roofless shell. Numbered from the Cone's end.
ROWS = {
    "low": {1: "dunlin", 2: "calloway", 3: "empty", 4: "tarn", 5: "okoro", 6: "vane", 7: "morrow", 8: "sato", 9: "roofless", 10: "marl"},
    "mid": {1: "greave", 2: "fenwick", 3: "roofless", 4: "stannard", 5: "sarro", 6: "empty", 7: "brandt"},
    "high": {1: "pontil", 2: "hollin", 3: "quill", 4: "empty", 5: "dunmore", 6: "empty", 7: "roofless"},
}
# The six terraces: (row, house numbers east to west, east end x, extra building first).
TERRACES = [
    ("low", "Low Row east", [1, 2, 3, 4, 5], 64.0, None),
    ("low", "Low Row west", [6, 7, 8, 9, 10], 22.0, "batch"),
    ("mid", "Mid Row east", [1, 2, 3, 4], 64.0, "marver"),
    ("mid", "Mid Row west", [5, 6, 7], 22.0, None),
    ("high", "High Row east", [1, 2, 3, 4], 64.0, None),
    ("high", "High Row west", [5, 6, 7], 22.0, None),
]
ROW_NAME = {"low": "Low Row", "mid": "Mid Row", "high": "High Row"}


def front_width(slot):
    """4.5 m, plus 0.4 m for each person past the first and 0.5 m for a Kiln house (the best
    plots), at most 6.5 m. Empty houses keep the 5.0 m of the original plots; shells 4.8 m."""
    if slot == "empty":
        return 5.0, "an original 5 m plot, empty"
    if slot == "roofless":
        return 4.8, "an original plot, its roof stripped for fuel in the lean years"
    name, fam, n, *_ = HOUSEHOLDS[slot]
    w = min(6.5, 4.5 + 0.4 * (n - 1) + (0.5 if fam == "kiln" else 0.0))
    return r2(w), f"{n} people" + (", a Kiln house" if fam == "kiln" else "")


# ---------------------------------------------------------------------------------------------
# Lots

lots = []
LANDMARKS = {"cone", "counting_house", "heron", "watchglass", "lintel"}


def lot(id, kind, name, at, size, facing, level, height, building=True, age=0.6, repair=0.6, empty=0.0, sheltered=0.0, spots=None, district="", **extra):
    l = {"id": id, "kind": kind, "name": name, "at": [r2(at[0]), r2(at[1])], "size": [r2(size[0]), r2(size[1])], "facing": facing, "level": level, "height_m": r2(height)}
    if id in LANDMARKS:
        l["landmark"] = True
    if spots:
        l["spots"] = [{"name": n, "at": [r2(p[0]), r2(p[1])]} for n, p in spots]
    l["district"] = district
    l["building"] = building
    l["wear"] = wear(at, H[level], facing, age, repair, empty, sheltered)
    l.update(extra)
    lots.append(l)
    return l


def south_front(x0, x1, front_y, depth):
    """Centre and size of a lot facing south whose front runs x0..x1 at front_y."""
    return ((x0 + x1) / 2, front_y + depth / 2), (abs(x1 - x0), depth)


# The Strand (quay level). Fronts face south onto the quay, gable to the sea, at y 10.3.
QF = 10.3
STRAND = "the Strand"
# Open lots (steps, yards, a terrace, the graveyard) are `lamp` lots of no height: named, with
# spots, never planted (a `garden` lot is planted) and drawn by nothing until their model exists.
lot("fish_steps", "lamp", "the Fish Steps", (0, -1.5), (8, 3), "south", "strand", 0, building=False, age=1.0, repair=0.3, district=STRAND,
    spots=[("the top step", (0, 1.0)), ("the second step, west", (2.5, 0.2)), ("the second step, east", (-2.5, 0.2)), ("Magda's place, where the catch is divided", (0, 2.4))],
    note="stone steps down into the harbour; the catch is divided here each morning")
c, s = (-17.0, -3.25), (7.0, 5.0)
lot("heron", "workshop", "the Heron", c, s, "north", "strand", 13.0, age=1.0, repair=0.5, district=STRAND,
    note="treadwheel crane house, tarred black, on its stage over the water; the jib reaches 9 m out (fixed)", jib_m=9.0)
c, s = south_front(-15, 15, QF, 12)
lot("counting_house", "hall", "the Counting House", c, s, "south", "strand", 15.0, age=1.0, repair=0.5, district=STRAND,
    spots=[(f"arcade bay {i + 1}", (r2(-12.86 + i * 4.286), 6.8)) for i in range(7)],
    note="the ship-day hall on an open arcade of seven arches; hipped slate roof; cupola, clock stopped at ten past four. The rules block its footprint, so the bays' spots stand at the arcade's mouth",
    storeys="arcade 4.2 m, hall 3.4 m, roof and cupola to 15 m")
# Six net lofts in a rank: 3.5 m wide, 8 m deep, 8.5 m to the ridge (tall thin sheds).
for i in range(6):
    x1 = -54.0 - i * 3.5
    c, s = south_front(x1 - 3.5, x1, QF, 8)
    lot(f"net_loft_{i + 1}", "workshop", f"net loft {i + 1}", c, s, "south", "strand", 8.5, age=0.8, repair=0.4 + 0.05 * i, sheltered=0.3 if 0 < i < 5 else 0.0, district=STRAND,
        note="a tall thin tarred shed, gable to the sea; one of a rank of six")
for i, (x0, x1) in enumerate([(-50.0, -44.0), (-44.0, -38.0)]):
    c, s = south_front(x0, x1, QF, 6)
    lot(f"smokehouse_{i + 1}", "workshop", f"smokehouse {i + 1}" + (" (Petra Tarn's)" if i == 0 else ""), c, s, "south", "strand", pitched(1, 3.0, 6, 45), age=0.7, repair=0.5, district=STRAND,
        note="louvred roof; smoke is an effect")
c, s = south_front(48, 60, QF, 10)
lot("store", "barn", "the Store", c, s, "south", "strand", pitched(2, 2.8, 10, 47), age=0.9, repair=0.6, district=STRAND, note="the common store")
c, s = south_front(-97, -85, 12.0, 12)
lot("boatshed", "workshop", "the boatshed", c, s, "south", "strand", pitched(1, 4.2, 12, 45), age=0.8, repair=0.5, district=STRAND, note="open front onto the slipway lane")
c, s = south_front(-124, -104, 12.0, 19)
lot("dry_dock", "workshop", "the dry dock", c, s, "south", "strand", 8.0, building=False, age=1.0, repair=0.3, district=STRAND,
    note="the ship-day dry dock with the hull of the Second Thought on its stocks (8 m to the top of the frames); not one of the 65 buildings")
lot("slip", "lamp", "the slip", (-119, 5), (10, 10), "south", "strand", 0, building=False, age=1.0, repair=0.4, district=STRAND, note="a stone slip into the harbour")

# Cinder Row (quay level, east): the Cone and its yard, the lehr house, the pot house, the
# cullet shed, the ash house and the wash-house against the Cone's warm north wall.
CINDER = "Cinder Row"
lot("cone", "workshop", "the Cone", CONE, (14, 14), "south", "strand", 24.0, age=0.9, repair=0.55, district=CINDER,
    spots=[("the west mouth", (6.1, 7.8)), ("the front mouth", (0, 7.8)), ("the east mouth", (-6.1, 7.8)), ("Halvard's bench at the mouth", (3.0, 9.2))],
    note="a brick cone, 14 m across, 24 m high, three arched mouths that glow; a band of newer, redder brick where it cracked (9 to 12 m, south-west side)")
lot("cone_yard", "lamp", "the Cone yard", (150, 15.5), (36, 13), "south", "strand", 0, building=False, age=0.9, repair=0.5, district=CINDER,
    spots=[("the cullet heaps", (6, 2)), ("the trough", (-8, 2))], note="cinder underfoot; heaps of coloured broken glass")
c = (147.0, 43.0)
lot("wash_house", "workshop", "the wash-house", c, (12, 6), "north", "strand", pitched(1, 3.0, 6, 45), age=0.6, repair=0.6, district=CINDER,
    spots=[("the warm wall, west", (-4, 3.6)), ("the warm wall", (0, 3.6)), ("the warm wall, east", (4, 3.6)), ("Greta's stool", (2, 4.2))],
    note="built against the Cone's warm north wall; the wall is where people gossip on cold evenings", leans_on="cone")
c, s = south_front(82, 106, 12.0, 14)
lot("lehr_house", "workshop", "the lehr house", c, s, "south", "strand", pitched(2, 3.6, 14, 45), age=1.0, repair=0.5, district=CINDER,
    note="the old bonded warehouse of the ship days; the lehr's round arches inside")
c, s = south_front(108, 120, 12.0, 8)
lot("pot_house", "workshop", "the pot house", c, s, "south", "strand", pitched(1, 3.2, 8, 45), age=0.7, repair=0.5, district=CINDER, note="where Otto makes the crucibles")
lot("cullet_shed", "barn", "the cullet shed", (112, 33), (6, 8), "east", "strand", pitched(1, 2.8, 6, 40), age=0.6, repair=0.4, district=CINDER, note="open-fronted; crates of sorted cullet")
c, s = south_front(84, 94, 32.0, 8)
lot("ash_house", "barn", "the ash house", c, s, "south", "strand", pitched(1, 3.0, 8, 45), age=0.7, repair=0.5, district=CINDER, note="kelp ash in sacks, kept dry")

# The mole: the lamp house at its root, the Watchglass at its tip.
lot("lamp_house", "house", "the lamp house", (142.5, -10.5), (6, 6), "west", "mole", pitched(2, 2.6, 6, 47), age=0.9, repair=0.7, district="the mole",
    household="faro", household_name="Faro", family="other", people=2, door_colour="sea_green", keepsake="a lamp-oil drum and a coil of wick", address="the lamp house on the mole")
lot("watchglass", "tower", "the Watchglass", (135.5, -60.5), (6, 6), "north", "mole", 17.0, age=1.0, repair=0.6, district="the mole",
    spots=[("the door", (0, 3.6)), ("Rafe's place by the light", (3.8, 2.0)), ("the tip of the mole", (0, -5.8))],
    note="squat eight-sided tower with a lantern room too big for it; one band of cobalt; lit every night")

# The Rows: six terraces of 3 to 6 houses sharing walls, fronts 4.5 to 6.5 m.
ROWS_D = "the Rows"
STOREY = {"kiln": 2.9, "strand": 2.6, "ladder": 2.7, None: 2.75}
PITCH = 47.0
terrace_lots = {}
for row, tname, numbers, east_x, extra in TERRACES:
    fy = ROW_Y[row] + FRONT_GAP
    x = east_x
    members = []
    if extra == "batch":
        w = 8.0
        c, s = south_front(x - w, x, fy, HOUSE_DEPTH)
        lot("batch", "workshop", "the Batch", c, s, "south", row, pitched(1, 3.2, HOUSE_DEPTH, PITCH), age=0.8, repair=0.6, sheltered=0.3, district=ROWS_D,
            spots=[("the oven mouth", (0, 4.4)), ("the bench by the oven", (2.6, 4.6)), ("the step", (-2.6, 4.4))],
            note="the common oven; its mouth to the street, glowing from 03:00", terrace=tname)
        members.append("batch")
        x -= w
    if extra == "marver":
        w = 12.0
        c, s = south_front(x - w, x, fy, HOUSE_DEPTH + 1.0)
        lot("marver", "inn", "the Marver", c, s, "south", row, pitched(2, 2.8, HOUSE_DEPTH + 1, PITCH), age=0.7, repair=0.7, sheltered=0.2, district=ROWS_D,
            spots=[("the door", (0, 4.7)), ("the hearth bench", (3.5, 4.9))],
            household="achterberg", household_name="Achterberg", family="other", people=3, door_colour="mustard", keepsake="a ship's figurehead over the door",
            address="over the Marver, Mid Row", note="the cookshop: open front, figurehead over the door; the Achterbergs live over it", terrace=tname)
        members.append("marver")
        # Its terrace over the harbour: the walk on the street's south side, above the drop.
        lot("marver_terrace", "lamp", "the Marver's terrace", (x - w / 2, BAND[row][0] + 3.25), (12, 6.5), "south", row, 0, building=False, age=0.5, repair=0.6, district=ROWS_D,
            spots=[(f"terrace seat {i + 1}", (r2(-4.5 + (i % 4) * 3.0), r2(1.5 if i < 4 else -1.0))) for i in range(6)], note="tables over the harbour")
        x -= w
    for k, n in enumerate(numbers):
        slot = ROWS[row][n]
        w, why = front_width(slot)
        c, s = south_front(x - w, x, fy, HOUSE_DEPTH)
        ends = (k == 0 and extra is None) or k == len(numbers) - 1
        fam = HOUSEHOLDS[slot][1] if slot in HOUSEHOLDS else None
        storeys = 2
        h = pitched(storeys, STOREY[fam], HOUSE_DEPTH, PITCH)
        if slot == "roofless":
            h = r2(storeys * 2.75 + 0.4)
        extra_fields = {"address": f"{ROW_NAME[row]} {n}", "terrace": tname, "front_cause": why}
        if slot in HOUSEHOLDS:
            name, fam, people, door, keep = HOUSEHOLDS[slot]
            extra_fields.update(household=slot, household_name=name, family=fam, people=people, door_colour=door, keepsake=keep)
            age = 0.8 if fam == "kiln" else 0.65
            repair = 0.75 if fam == "kiln" else 0.55
            empty = 0.0
        elif slot == "empty":
            extra_fields.update(state="empty, sound", door_colour="faded")
            age, repair, empty = 0.7, 0.4, 1.0
        else:
            extra_fields.update(state="roofless shell", door_colour="none")
            age, repair, empty = 0.9, 0.0, 1.0
            if (row, n) == ("low", 9):
                extra_fields["note"] = "a tree grows inside the walls"
        lid = f"{row}_{n}"
        lot(lid, "house", f"{ROW_NAME[row]} {n}", c, s, "south", row, h, age=age, repair=repair, empty=empty, sheltered=0.15 if ends else 0.4, district=ROWS_D, storeys=storeys, pitch_deg=PITCH, **extra_fields)
        members.append(lid)
        x -= w
    terrace_lots[tname] = members
    if x < -28.01 and east_x < 30:
        raise SystemExit(f"{tname} runs past the Net Wynd to x {x}")
    if x < 26 - 0.01 and east_x > 30:
        raise SystemExit(f"{tname} runs past the Tally Wynd to x {x}")

# The Ladder: 14 lean-to glasshouses (12 x 4.5 m) against the terrace walls of five terraces,
# west of the Net Wynd, and 18 walled root plots above them. Three broken since the storm.
LADDER = "the Ladder"
GLASS_BACK = {"low": BAND["low"][1] - 0.7, "mid": BAND["mid"][1] - 0.7, "high": BAND["high"][1] - 0.7, "upper": BAND["upper"][1] - 0.7, "crown": BAND["crown"][1] - 0.7}
GLASS_X = {  # east ends of each terrace's glasshouses, clear of the Ladder Wynd at x -100
    "low": [-33.0, -47.0, -103.0],
    "mid": [-33.0, -47.0, -103.0],
    "high": [-33.0, -61.0, -103.0],
    "upper": [-33.0, -47.0, -103.0],
    "crown": [-125.0, -139.0],
}
BROKEN = {6, 11, 13}  # the storm's three
gh = 0
for lv in ("low", "mid", "high", "upper", "crown"):
    for ex in GLASS_X[lv]:
        gh += 1
        back = GLASS_BACK[lv]
        c, s = (ex - 6.0, back - 2.25), (12.0, 4.5)
        note = "a lean-to against the terrace wall; bays 1 m, panes at most 0.45 m"
        if gh in BROKEN:
            note += "; broken in last autumn's storm, not mended"
        if gh == 9:
            note += "; Jory Greave's fruit tree in one bay"
        if gh == 4:
            note += "; Cora Stannard's flowers in a corner"
        lot(f"glasshouse_{gh}", "workshop", f"glasshouse {gh}", c, s, "south", lv, 3.2, age=0.3, repair=0.15 if gh in BROKEN else 0.7, empty=0.6 if gh in BROKEN else 0.0, district=LADDER,
            spots=[("the door", (4.5, 2.8)), ("the rain butt", (-6.6, 0.0))], note=note, leans_on=f"the {lv} terrace wall", state="broken" if gh in BROKEN else "working")
assert gh == 14
# Root plots: three rows of six, 8 x 6 m with dry-stone walls, on the Crown's level west of it.
p = 0
for rr in range(3):
    for cc in range(6):
        p += 1
        cx = -236.0 + cc * 10.0
        cy = 147.0 + rr * 8.5
        # An open lot, not a `garden`: a garden is planted with berry bushes, and a root plot
        # grows roots (its `root_plot` resource below).
        lot(f"root_plot_{p}", "lamp", f"root plot {p}", (cx, cy), (8, 6), "south", "crown", 0, building=False, age=0.7, repair=0.6, district=LADDER, note="walled with dry stone; fed with kelp")

# The Crown (+20 m): the cistern and its house, the Readers' House, the graveyard, the thorn and a bench.
CROWN = "the Crown"
lot("cistern", "well", "the cistern", (-4.5, 160.5), (9, 9), "south", "crown", 2.6, building=False, age=1.0, repair=0.6, district=CROWN,
    spots=[("the cistern's rim", (0, 5.0))], note="round, 9 m across; rain-fed; Hobb measures it every dusk")
lot("cistern_house", "barn", "the cistern house", (8.5, 159.0), (5, 4), "south", "crown", pitched(1, 2.6, 4, 45), age=0.9, repair=0.6, district=CROWN, note="the pump and the tablets of the cistern's level")
c, s = south_front(18, 30, 162.0, 10)
lot("readers_house", "hall", "the Readers' House", c, s, "south", "crown", pitched(2, 2.8, 10, 47), age=0.9, repair=0.65, district=CROWN,
    spots=[("the step", (0, 5.6)), ("the bench by the door", (3.0, 5.8))],
    household="orme", household_name="Orme", family="other", people=1, door_colour="chalk_blue", keepsake="a shelf of ship-day tablets in the window", address="the Readers' House",
    note="the school and the ship-day tablets; Benedikt Orme lives here")
lot("graveyard", "lamp", "the graveyard", (-35.0, 176.0), (26, 18), "south", "crown", 0, building=False, age=1.0, repair=0.5, district=CROWN, note="glass markers")
lot("thorn", "lamp", "the thorn", (-22.0, 138.6), (2, 2), "south", "crown", 4.5, building=False, age=1.0, repair=0.0, district=CROWN, note="one wind-bent thorn, leaning north-east")
lot("crown_bench", "lamp", "the Crown bench", (-17.5, 137.0), (2.2, 0.7), "south", "crown", 0.5, building=False, age=0.6, repair=0.5, district=CROWN,
    spots=[("the bench, west seat", (0.55, 0.8)), ("the bench, east seat", (-0.55, 0.8))], note="the whole town below")
lot("peat_barn", "barn", "the peat barn", (44.0, 184.0), (12, 8), "west", "crown", pitched(1, 3.2, 8, 45), age=0.6, repair=0.5, district=CROWN, note="at the top of the Moss road; peat comes down here")

# Outside town.
lot("turf_house", "house", "the turf house", (-62.0, 328.5), (8, 6), "south", "moss", pitched(1, 2.6, 6, 45), age=0.8, repair=0.5, district="the Moss",
    household="roon", household_name="Roon", family="other", people=3, door_colour="oxblood", keepsake="a stack of drying peat by the door", address="the turf house on the Moss")
lot("hanger_cottage", "house", "the Hanger cottage", (207.0, 207.5), (7, 6), "south", "hanger", pitched(1, 2.7, 6, 47), age=0.7, repair=0.7, district="the Hanger",
    household="sedge", household_name="Sedge", family="other", people=1, door_colour="sea_green", keepsake="a seedling bed of thorn and rowan", address="the Hanger cottage")
lot("lintel", "tower", "the Lintel", (-25.0, 528.0), (6.0, 2.0), "south", "headland", 9.0, building=False, age=1.0, repair=0.0, district="the north headland",
    note="two standing stones and a capstone; a slab of dark glass fills the opening. It is shut. A fact with no purpose")

# ---------------------------------------------------------------------------------------------
# Streets: the quay 10 m, the Rows 5 m, lanes 2.5 to 3.5 m; paths out of town 2 m.

streets = [
    {"id": "the Strand", "points": [[-75, 5], [75, 5]], "width_m": 10.0, "class": "street", "surface": "quay_flags", "level": "strand"},
    {"id": "the slipway", "points": [[-75, 5], [-100, 6], [-110, 6]], "width_m": 3.5, "class": "lane", "surface": "setts", "level": "strand"},
    {"id": "Cinder Row", "points": [[75, 5], [124, 5], [124, 58]], "width_m": 3.5, "class": "lane", "surface": "cinders", "level": "strand"},
    {"id": "the mole", "points": [[136, 0], [136, -54]], "width_m": 4.0, "class": "lane", "surface": "flags", "level": "mole"},
]
for row in ("low", "mid", "high"):
    streets.append({"id": ROW_NAME[row], "points": [[-98, ROW_Y[row]], [78, ROW_Y[row]]], "width_m": 5.0, "class": "street", "surface": "setts", "level": row})
    streets.append({"id": f"{ROW_NAME[row]} walk", "points": [[-102, ROW_Y[row]], [WEST[row] + 3, ROW_Y[row]]], "width_m": 3.0, "class": "lane", "surface": "earth", "level": row})
streets.append({"id": "the upper walk", "points": [[-255, 124.5], [50, 124.5]], "width_m": 3.0, "class": "lane", "surface": "earth", "level": "upper"})
streets.append({"id": "the Crown path", "points": [[-255, 139.0], [-30, 139.0]], "width_m": 3.0, "class": "lane", "surface": "earth", "level": "crown"})
stairs = []
for wname, xs, lvls in WYNDS:
    prev_head = None
    pieces = []
    # A wynd climbs straight, or dog-legs: each flight in its own gap, the row between them.
    xs = xs if isinstance(xs, list) else [xs] * (len(lvls) - 1)
    for x, a, b in zip(xs, lvls, lvls[1:]):
        foot, head, rise = flight(x, a, b)
        stairs.append({"id": f"{wname}, {a} to {b}", "from": a, "to": b, "foot": foot, "head": head, "width_m": STAIR_W, "rise_m": rise})
        start = prev_head if prev_head else ([x, QF] if a == "strand" else None)
        if start and start[0] != x:
            # A dog-leg: up to the level's street, along it (the street is the lane), up to the flight.
            wy = {**ROW_Y, "upper": 124.5}[a]
            if abs(wy - start[1]) > 0.5:
                pieces.append((a, start, [start[0], wy]))
            start = [x, wy]
        if start and start[1] < foot[1] - 0.5:
            pieces.append((a, start, foot))
        prev_head = head
    for i, (lv, a, b) in enumerate(pieces):
        part = sum(1 for q in pieces[:i] if q[0] == lv)
        streets.append({"id": f"{wname} ({lv}{', ' + str(part + 1) if part or sum(1 for q in pieces if q[0] == lv) > 1 else ''})", "points": [a, b], "width_m": STAIR_W, "class": "lane", "surface": "setts", "level": lv})
# The Cinder Steps: the fifth wynd, from Cinder Row up to Low Row's east end.
stairs.append({"id": "the Cinder Steps", "from": "strand", "to": "low", "foot": [r2(80 + 3.5 / SLOPE - 0.5), 50.0], "head": [79.5, 50.0], "width_m": STAIR_W, "rise_m": 3.5})
# Paths out of town, on the natural ground.
streets += [
    {"id": "the Moss road", "points": [[50, 190], [58, 230], [20, 290], [-40, 322]], "width_m": 2.5, "class": "path", "surface": "earth"},
    {"id": "the Lintel path", "points": [[-40, 322], [-35, 420], [-25, 518]], "width_m": 2.0, "class": "path", "surface": "earth"},
    {"id": "the Hanger path", "points": [[124, 58], [160, 110], [200, 170], [207, 196]], "width_m": 2.0, "class": "path", "surface": "earth"},
    {"id": "the strand path", "points": [[-127, 5], [-180, 12], [-240, 22], [-300, 40]], "width_m": 2.5, "class": "path", "surface": "sand"},
]

SQUARE = {"level": "strand", "area": rect(15.5, 10.3, 45.5, 24.3), "paved": True,
          "note": "the Counting House yard, the only square (30 x 14 m): the market"}

# ---------------------------------------------------------------------------------------------
# Resources (SMALL_CITY §2 "The land that feeds it"), under the resource kinds of Cullet's laws
# (`resources()` in living/seeds/worlds/cullet/laws.rhai). A kind the world's tables lack refuses
# the seed (`floor::check`).
#
# How much each gives is computed from §2's sustainability targets. Starting values for the soak
# with no minds, not tuned:
# - 64 residents and 10 players eat 48 hunger points a game day each (docs/CULLET_RULES.md);
# - the island yields 1.3 times that: fish 55%, roots 30%, greens 15%;
# - fish are counted as eaten smoked (24 points; fresh and cooked gives 34, raw 16), roots baked
#   at the Batch (30; raw 14), greens raw (10).
# A node regrows only in growing time (not in winter, for every kind; `living_rules::growing_ms`).

EATERS = 64 + 10
EATEN_A_DAY = 48.0
YIELD = 1.3
DAILY = EATERS * EATEN_A_DAY * YIELD  # hunger points the land gives in a game day
EATEN_AS = {"fish": 24.0, "roots": 30.0, "greens": 10.0}
SHARE = {"fish": 0.55, "roots": 0.30, "greens": 0.15}
WANTED = {k: DAILY * SHARE[k] / EATEN_AS[k] for k in SHARE}  # units a game day
# Fish by ground: the lines (12 spots, 6 fishers) about 60% of the catch, the Weirs' traps (10
# spots, 3 fishers) 40%; the lines split by spots.
GROUNDS = [  # (pool, kind, share of the fish, where, points)
    ("the Fish Steps", "fishing_spot", 0.6 * 2 / 12, "the Fish Steps", [[-2.0, -2.0], [2.0, -2.0]]),
    ("the quay", "fishing_spot", 0.6 * 4 / 12, "the quay edge (the jetties)", [[-62.0, 0.6], [-35.0, 0.6], [40.0, 0.6], [68.0, 0.6]]),
    ("the mole", "fishing_spot", 0.6 * 6 / 12, "the mole", [[132.6, -22.0], [138.4, -30.0], [132.6, -40.0], [138.4, -48.0], [129.6, -63.0], [141.4, -63.0]]),
]
WEIRS = [[-160, -2], [-235, 20]]  # the shore in front of the shallows
GROUNDS.append(("the Weirs", "weir", 0.4, "the Weirs (fish by trap)", None))
# Kelp: ash for about 12 glass a day (4 kelp an ash, one ash a glass) and as much again for the
# plots. Sand: two a glass. Peat: the Cone at full firing (3 a game hour) and the homes about as
# much (§2); the cutters bring in 70% of it, so the stock falls slowly.
GLASS_A_DAY = 12
CONE_PEAT_H = 3.0  # the furnace's `burns.rate` in Cullet's laws
CONE_DAY = CONE_PEAT_H * 24
GOODS_DAY = {
    "kelp_bed": GLASS_A_DAY * 4 * 1.25,
    "sand_bank": GLASS_A_DAY * 2,
    "peat_bank": 0.7 * (CONE_DAY + CONE_DAY),
    "root_plot": WANTED["roots"],
    "greens_bed": WANTED["greens"],
}
# A node holds about two days of its regrowth (a bed left a day loses nothing), at least 6.
DAYS_HELD = 2.0


def pts_line(a, b, n):
    return [[r2(a[0] + (b[0] - a[0]) * (i + 0.5) / n), r2(a[1] + (b[1] - a[1]) * (i + 0.5) / n)] for i in range(n)]


resources = []


def res(kind, points, where, per_day=None, pool=None):
    """Nodes of a kind at points. `per_day`: what all of them give together in a game day (each
    node its share, or a pool's stock the whole of it)."""
    n = 1 if pool else len(points)
    for q in points:
        r = {"kind": kind, "at": q, "where": where}
        if per_day is not None:
            r["regrow_per_h"] = round(per_day / n / 24, 4)
            r["max"] = round(max(6.0, per_day / n * DAYS_HELD), 1)
        if pool:
            r["pool"] = pool
        resources.append(r)


# The fishing grounds, each one stock its spots share (`pool`).
for pool, kind, share, where, pts in GROUNDS:
    res(kind, pts if pts else pts_line(WEIRS[0], WEIRS[1], 10), where, WANTED["fish"] * share, pool=pool)
# The Hanger: about 60 trees of one age, on a jittered grid in the gully (a fixed pattern, not drawn).
HANGER = [[175, 225], [235, 210], [300, 250], [315, 300], [270, 330], [215, 300], [185, 265]]


def inside(poly, p):
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        a, b = poly[i], poly[j]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            c = not c
        j = i
    return c


trees = []
for j in range(14):
    for i in range(14):
        q = (170 + i * 13.0 + (5.0 if j % 2 else 0) + ((i * 7 + j * 3) % 5 - 2) * 0.8, 205 + j * 12.0 + ((i * 3 + j * 5) % 5 - 2) * 0.8)
        if inside(HANGER, q) and math.hypot(q[0] - 207, q[1] - 205) > 14:
            trees.append([r2(q[0]), r2(q[1])])
res("tree", trees, "the Hanger")
# The clay bank below the Crown, nearly dug out.
res("clay_bank", [[64.0, 140.0]], "the clay bank below the Crown")
# Cullet's goods (goods-1's kinds).
res("kelp_bed", pts_line([-140, 4], [-300, 36], 12), "the Wrack Strand (kelp: fertiliser and ash)", GOODS_DAY["kelp_bed"])
res("sand_bank", pts_line([352, 100], [372, 205], 6), "the Sand Spit (white sand for glass)", GOODS_DAY["sand_bank"])
res("peat_bank", [[x, y] for y in (360, 400, 440) for x in (-150, -90, -30, 30, 90, 150)], "the Moss (peat cuttings)", GOODS_DAY["peat_bank"])
res("root_plot", [[r2(l["at"][0]), r2(l["at"][1])] for l in lots if l["id"].startswith("root_plot_")], "the root plots", GOODS_DAY["root_plot"])
res("greens_bed", [[r2(l["at"][0]), r2(l["at"][1] - 2.0)] for l in lots if l["id"].startswith("glasshouse_") and int(l["id"].split("_")[1]) not in BROKEN], "the working glasshouses", GOODS_DAY["greens_bed"])

# ---------------------------------------------------------------------------------------------
# Fires, lamps and stores (SMALL_CITY §2 and §4; fires that burn fuel are Cullet's laws'
# `structures()`: rates a game hour, `holds` the most a fire takes). Each starts lit with `fuel`.

HOLDS = {"furnace": 40.0, "oven": 8.0, "hearth": 12.0, "smokehouse": 8.0, "lamp": 8.0}
# The Cone's peat: 12 days of full firing (§2), the furnace full and the rest in a store in the
# Cone yard.
CONE_STOCK = 12 * CONE_DAY
structures = [
    {"kind": "furnace", "lot": "cone", "spot": "the front mouth", "fuel": HOLDS["furnace"], "note": "the Cone's furnace, full (13 game hours at full firing)"},
    {"kind": "storage", "lot": "cone_yard", "contents": {"peat": int(CONE_STOCK - HOLDS["furnace"])},
     "note": f"the Cone's peat: with the furnace's, {CONE_STOCK:.0f} units, 12 days of full firing at {CONE_PEAT_H:g} a game hour"},
    {"kind": "oven", "lot": "batch", "spot": "the oven mouth", "fuel": HOLDS["oven"], "note": "the Batch's oven, full (8 game hours)"},
    {"kind": "hearth", "lot": "marver", "spot": "the hearth bench", "fuel": HOLDS["hearth"], "note": "the Marver's public hearth, full (a game day)"},
]
for i in (1, 2):
    structures.append({"kind": "smokehouse", "lot": f"smokehouse_{i}", "fuel": HOLDS["smokehouse"], "note": "full (16 game hours)"})
# A hearth at the door of every home lived in (the Marver's household uses its public hearth).
HEARTHS = [l["id"] for l in lots if l.get("household") and l["id"] != "marver"]
for lid in HEARTHS:
    structures.append({"kind": "hearth", "lot": lid, "fuel": HOLDS["hearth"], "note": "the household's hearth, full (a game day)"})
# Seven lamps where people are at night (§5: lamplight is where night life is), each full: 32
# game hours, about three nights.
LAMPS = [
    ({"at": [6.0, 1.5]}, "at the top of the Fish Steps"),
    ({"at": [-60.0, 4.0]}, "on the quay by the net lofts"),
    ({"at": [54.0, 7.5]}, "on the quay by the Store"),
    ({"at": [30.0, 17.0]}, "in the Counting House yard"),
    ({"lot": "marver", "spot": "the door"}, "at the Marver's door"),
    ({"at": [136.0, -8.0]}, "on the mole by the lamp house"),
    ({"lot": "watchglass", "spot": "Rafe's place by the light"}, "at the Watchglass, where Rafe fishes by the light"),
]
for where, note in LAMPS:
    structures.append({"kind": "lamp", **where, "fuel": HOLDS["lamp"], "note": note})
assert len([s_ for s_ in structures if s_["kind"] == "lamp"]) == 7

# Stores: six days of food for 64 residents at the start (§2), half in the Store (the common
# store, now) and half in the households (when the cast lands). Kept food: smoked fish for the
# fish share and roots for the roots' and the greens' (greens do not keep), counted raw (14).
RESIDENTS = 64
STORE_DAYS = 6
KEPT_AS = {"smoked_fish": (24.0, SHARE["fish"]), "roots": (14.0, SHARE["roots"] + SHARE["greens"])}


def food_for(people, days):
    return {k: math.ceil(people * EATEN_A_DAY * days * share / pts) for k, (pts, share) in KEPT_AS.items()}


COMMON_STORE = food_for(RESIDENTS, STORE_DAYS / 2)
for l in lots:
    if l["id"] == "store":
        l["contents"] = COMMON_STORE
HOUSEHOLD_STORES = {
    "note": f"Not placed: residents do not exist yet (phase 5). When the cast lands, each household's home holds the other {STORE_DAYS / 2:g} days of food for its people, and peat for its hearth beyond the hearth's first fill; with the Store's {STORE_DAYS / 2:g} days that is the {STORE_DAYS} days of §2.",
    "per_person": food_for(1, STORE_DAYS / 2),
    "by_household": {l["household"]: {"lot": l["id"], "people": l["people"], **food_for(l["people"], STORE_DAYS / 2)} for l in lots if l.get("household")},
}
assert sum(h["people"] for h in HOUSEHOLD_STORES["by_household"].values()) == RESIDENTS

FEATURES = {
    "kelp_kilns": {"note": "four round stone pits on the Wrack Strand, upwind (south-west) of Low Row; P2 props", "at": [[-150, 12], [-170, 15], [-190, 18], [-210, 22]]},
    "weirs": {"note": "stake fences in the shallows south-west of town; the shallows are a relief stamp", "between": WEIRS},
    "the_combs": {"note": "a reef 120 to 200 m off the south shore: a submerged relief stamp; nothing with a keel crosses it"},
}

# ---------------------------------------------------------------------------------------------
# The land: the Wrack, about 760 x 560 m in the middle of a 1024 m map (SMALL_CITY §2).

OUTLINE = [
    [-128, -4], [-200, -6], [-262, 16], [-322, 40], [-352, 95], [-376, 175], [-380, 265], [-352, 360], [-300, 430], [-215, 470], [-130, 492],
    [-72, 502], [-30, 508], [14, 502], [80, 494], [170, 478], [252, 446], [322, 395], [365, 320], [378, 240], [388, 205], [386, 120],
    [362, 92], [328, 58], [262, 22], [196, 0], [180, -4],
]
STAMPS = [
    {"id": "the island's moor grass", "area": [[x * 1.12, y * 1.06 - 14] for x, y in OUTLINE], "region": "meadow"},
    {"id": "the Moss", "area": [[-210, 238], [-80, 222], [60, 228], [160, 250], [170, 310], [140, 390], [40, 415], [-120, 410], [-230, 380], [-255, 310]], "height_m": 30.0, "blend_m": 60.0, "region": "highland"},
    {"id": "the Moss's high middle", "area": [[-130, 300], [110, 300], [90, 380], [-100, 380]], "height_m": 35.0, "blend_m": 40.0},
    {"id": "the turf house's ground", "area": OUTLYING["moss"]["area"], "height_m": 32.0, "blend_m": 30.0},
    {"id": "the north headland's shoulder", "area": [[-90, 470], [30, 470], [12, 512], [-30, 520], [-78, 508]], "height_m": 34.0, "blend_m": 45.0},
    {"id": "the north headland", "area": [[-40, 517], [-12, 517], [-12, 537], [-40, 537]], "height_m": 46.0, "blend_m": 48.0, "note": "the island's highest ground, so the Lintel shows over the Moss from the town"},
    {"id": "the Hanger", "area": HANGER, "height_m": 15.0, "blend_m": 35.0, "region": "forest"},
    {"id": "the Wrack Strand", "area": [[-128, 4], [-200, 2], [-258, 24], [-312, 46], [-306, 78], [-250, 60], [-190, 42], [-130, 38]], "height_m": 0.8, "blend_m": 26.0, "region": "beach", "ground": "sand"},
    {"id": "the Sand Spit", "area": [[346, 92], [384, 110], [390, 210], [352, 212], [342, 150]], "height_m": 0.8, "blend_m": 18.0, "region": "beach", "ground": "sand"},
    {"id": "the Weirs", "area": [[-150, -10], [-250, 4], [-262, -30], [-160, -40]], "height_m": -0.6, "blend_m": 30.0},
    {"id": "the Combs", "area": [[-260, -150], [260, -150], [260, -170], [-260, -170]], "height_m": -0.8, "blend_m": 15.0},
]
LAND_PARAMS = {
    "relief": {
        "outline": [land(q) for q in OUTLINE],
        "outline_rise_m": 120.0,
        "coast_warp": 0.035,
        "coast_feature": 0.08,
        "lowland_m": 12.0,
        "sea_floor_m": 22.0,
        "hills_m": 4.0,
        "hills_feature_m": 220.0,
        "peak_m": [1.0, 1.0],
        "foothills_m": 0.0,
        "islets": 0,
        "stamps": [dict(st, area=[land(q) for q in st["area"]]) for st in STAMPS],
    },
    "water": {"river_catchment_m2": 1.0e9, "lakes_per_km2": 0.0, "natural_lakes": 0},
    "regions": {
        # A treeless rock: every kind but the Hanger's forest has a negative tree share, since the
        # tile rule's noise passes a share of 0 here and there.
        "wetlands_per_km2": 0.0,
        "looks": [
            {"kind": "sea", "trees": -0.5, "detail_m": 0.5, "beach_m": 20.0, "outcrops": 0.0, "dirt": 0.0},
            {"kind": "beach", "trees": -0.5, "detail_m": 0.3, "beach_m": 60.0, "outcrops": 0.03, "dirt": 0.0},
            {"kind": "meadow", "trees": -0.5, "detail_m": 0.8, "beach_m": 5.0, "outcrops": 0.025, "dirt": 0.06},
            {"kind": "forest", "trees": 0.62, "detail_m": 1.2, "beach_m": 4.0, "outcrops": 0.01, "dirt": 0.05},
            {"kind": "old_forest", "trees": -0.5, "detail_m": 0.8, "beach_m": 5.0, "outcrops": 0.02, "dirt": 0.06},
            {"kind": "spirit_grove", "trees": -0.5, "detail_m": 0.8, "beach_m": 5.0, "outcrops": 0.02, "dirt": 0.06},
            {"kind": "wetland", "trees": -0.5, "detail_m": 0.4, "beach_m": 5.0, "outcrops": 0.0, "dirt": 0.2},
            {"kind": "highland", "trees": -0.5, "detail_m": 1.4, "beach_m": 4.0, "outcrops": 0.03, "dirt": 0.32},
            {"kind": "peaks", "trees": -0.5, "detail_m": 2.0, "beach_m": 2.0, "outcrops": 0.2, "dirt": 0.5},
        ],
    },
    "sites": [],
}

# ---------------------------------------------------------------------------------------------
# Output


def plan():
    return {
        "id": "cullet",
        "kind": "town",
        "style": "cullet",
        "origin": list(ORIGIN),
        "rotation_deg": 0,
        "blend_m": 70,
        "skirt_m": 10,
        "note": "Cullet, a glassmakers' harbour on the south slope of the Wrack (docs/SMALL_CITY.md). Written by living/tools/cullet_plan.py; edit the script, not this file. Plan frame: origin at the Fish Steps, x east, y north (uphill), metres.",
        "levels": LEVELS,
        "sea": SEA,
        "square": SQUARE,
        "streets": streets,
        "stairs": stairs,
        "lots": lots,
        "resources": resources,
        "structures": structures,
        "household_stores": HOUSEHOLD_STORES,
        "features": FEATURES,
        "terraces": terrace_lots,
        "count": count(),
    }


def count():
    b = [l for l in lots if l["building"]]
    by = {}
    for l in b:
        by.setdefault(l["district"], 0)
        by[l["district"]] += 1
    houses = [l for l in b if l["kind"] == "house"]
    row_houses = [l for l in houses if l["id"].split("_")[0] in ("low", "mid", "high")]
    return {
        "buildings": len(b),
        "houses": len(houses),
        "row_houses": len(row_houses),
        "lived_in": len([l for l in row_houses if "household" in l]),
        "empty_sound": len([l for l in row_houses if l.get("state") == "empty, sound"]),
        "roofless": len([l for l in row_houses if l.get("state") == "roofless shell"]),
        "landmarks": sorted(l["id"] for l in lots if l.get("landmark")),
        "glasshouses": len([l for l in b if l["id"].startswith("glasshouse_")]),
        "working": len([l for l in b if l["kind"] != "house" and l["id"] not in LANDMARKS and not l["id"].startswith("glasshouse_")]),
        "open_lots": len([l for l in lots if not l["building"]]),
        "by_district": by,
    }


def seed(p):
    rough = {k: v for k, v in p.items() if k not in ("features", "terraces", "count", "household_stores")}
    return {
        "run": "cullet",
        "seed": SEED,
        # Cullet's day and laws (docs/CULLET_RULES.md): a 48-minute day, its needs, light and sight.
        "day_minutes": 48,
        "laws_file": "worlds/cullet/laws.rhai",
        "map": {"kind": "land", "size": SIZE, "params": dict(LAND_PARAMS, plans=[rough])},
        "setting": "Cullet, a glassmakers' harbour on the south slope of a treeless island its people call the Wrack, in year 83 since the Last Sail (docs/SMALL_CITY.md). The grey city: every lot of the hand-authored plan, the land round it, its fishing spots and its one wood; no residents yet.",
        # Only the plan's resources of these kinds: the wild spawn adds none.
        "resource_scale": {"tree": 0.0, "fishing_spot": 0.0, "berry_bush": 0.0, "clay_bank": 0.0, "boulder": 0.4, "reeds": 0.3,
                           "kelp_bed": 0.0, "sand_bank": 0.0, "peat_bank": 0.0, "root_plot": 0.0, "greens_bed": 0.0, "weir": 0.0},
        "animals": {"deer": 0, "wolf": 0},
        "towns": [{
            "name": "Cullet",
            "site": "cullet",
            "walled": False,
            "character": "a glassmakers' harbour: the Cone, the Counting House, the Rows, the Ladder",
            "buildings": [
                {"kind": "hall", "name": "the Counting House", "lot": "counting_house", "about": "the tally room upstairs; the market and the counters game under the arches"},
                {"kind": "inn", "name": "the Marver", "lot": "marver", "about": "the cookshop, with a terrace over the harbour"},
                {"kind": "workshop", "name": "the Cone", "lot": "cone", "about": "the glass furnace; it never goes dark"},
                {"kind": "workshop", "name": "the Batch", "lot": "batch", "about": "the common oven"},
                {"kind": "hall", "name": "the Readers' House", "lot": "readers_house", "about": "the school and the ship-day tablets"},
            ],
        }],
        "villages": [],
    }


def dump(v):
    return json.dumps(v, indent=1, ensure_ascii=False) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    p = plan()
    out = {PLAN_OUT: dump(p), SEED_OUT: dump(seed(p))}
    if a.check:
        bad = [str(k) for k, v in out.items() if not k.exists() or k.read_text() != v]
        if bad:
            print("differs:", *bad)
            sys.exit(1)
        return
    for k, v in out.items():
        k.parent.mkdir(parents=True, exist_ok=True)
        k.write_text(v)
    print(json.dumps(p["count"], indent=1))


if __name__ == "__main__":
    main()
