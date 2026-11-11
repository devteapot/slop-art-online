#!/usr/bin/env python3
"""Cullet's grey city: write the hand-authored plan and the land seed (docs/SMALL_CITY.md, phase 2).

    python3 living/tools/cullet_plan.py            # writes the three files below
    python3 living/tools/cullet_plan.py --check    # exits 1 if any of them differs from what it would write

Writes
- `living/seeds/worlds/cullet/plan.json`: the town as SMALL_CITY §1 and §2 describe it, in the
  plan frame (origin at the Fish Steps, x east, y north, metres): levels, streets, wynds, the
  square, the harbour, 74 lots (65 buildings and 9 open lots), spots, authored resources, and the
  asset generator's inputs per lot (wear, household, door colour, keepsake), which the engine
  ignores;
- `living/seeds/cullet.json`: the land seed, the Wrack (an authored coastline and relief stamps,
  `docs/AUTHORED_PLANS.md`) with the plan merged into `map.params.plans`, and the starting ways
  and town life of `living/seeds/worlds/cullet/ways.json` (the trades' workplaces and habits) as
  its `ways` and `town_life`;
- the `ground` map of `living/game/assets/envs/cullet.json` (GROUND_MAP below): which painted
  layer and colour the game's terrain takes for each street surface, area, terrain class and
  region. The rest of that file is kept as it is.

Every number that varies has a cause written beside it: a front's width comes from its household's
size and family, a lot's wear from where it stands (height above the sea, distance and bearing
from the Cone, which way it faces) by SMALL_CITY's wear table, its height from its storeys and
roof pitch. Nothing here is random; the same run writes the same files. Standard library only.
"""
import argparse
import json
import math
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN_OUT = ROOT / "living/seeds/worlds/cullet/plan.json"
# Cullet's starting ways and town life (the trades' workplaces and habits), hand-written data
# merged into the seed as they are (docs/SEEDED_LIVES.md).
WAYS = ROOT / "living/seeds/worlds/cullet/ways.json"
SEED_OUT = ROOT / "living/seeds/cullet.json"
ENV_OUT = ROOT / "living/game/assets/envs/cullet.json"

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
# Layout pass 1 (docs/CULLET_LAYOUT.md): the town is drawn in. The Rows run from the Net Wynd to
# the Store Wynd and no further; the Ladder stands against them, west of the Net Wynd, on the
# house plots the lean years emptied, and ends at its wind wall. West of that the hill is the
# island's own. High Row's level ends past the Store Wynd; the Crown keeps a ledge over the Ladder.
LADDER_W, LADDER_E = -84.0, -19.5  # the Ladder's block: its wind wall, and its wall on the Net Wynd
WEST = {"low": LADDER_W, "mid": LADDER_W, "high": LADDER_W, "upper": LADDER_W, "crown": LADDER_W}
EAST = {"low": 80, "mid": 80, "high": 70, "upper": 55, "crown": 55}
# The Ladder's own terraces: each of the Rows' bands is cut in two west of the Net Wynd, the back
# half 2 m higher, so a glasshouse leans on a wall every 13 to 15 m up the slope (seven walls
# from Low Row's level to the Crown's) instead of every 30 m.
RUNG = {"lad_1": ("low", 47.0), "lad_2": ("mid", 75.0), "lad_3": ("high", 105.0)}  # id -> (the band it halves, where it begins)
for _k, (_band, _y) in RUNG.items():
    H[_k] = H[_band] + 2.0
    BAND[_k] = (_y, BAND[_band][1])
CROWN_LEDGE = (-58.0, 146.0)  # west of x -58 the Crown's level is a 12 m ledge over the Ladder's top wall
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
_band_rung = {band: (k, y) for k, (band, y) in RUNG.items()}
for lv in ("low", "mid", "high", "upper", "crown"):
    y0, y1 = BAND[lv]
    if lv in _band_rung:  # an L: the whole band east of the Ladder, its front half inside it
        ys = _band_rung[lv][1]
        area = [[WEST[lv], y0], [EAST[lv], y0], [EAST[lv], y1], [LADDER_E, y1], [LADDER_E, ys], [WEST[lv], ys]]
    elif lv == "crown":
        area = [[WEST[lv], y0], [EAST[lv], y0], [EAST[lv], y1], [CROWN_LEDGE[0], y1], [CROWN_LEDGE[0], CROWN_LEDGE[1]], [WEST[lv], CROWN_LEDGE[1]]]
    else:
        area = rect(WEST[lv], y0, EAST[lv], y1)
    LEVELS.append({"id": lv, "height_m": H[lv], "area": area})
LEVELS[2]["note"] = "Low Row, and west of the Net Wynd the Ladder's lowest terrace"
LEVELS[3]["note"] = "Mid Row, and the Ladder's third terrace"
LEVELS[4]["note"] = "High Row, and the Ladder's fifth terrace"
LEVELS[5]["note"] = "the upper terrace: the Ladder's seventh, and the old quarry's bench below the Crown"
LEVELS[6]["note"] = "the Crown, and a ledge over the Ladder's top wall"
for _k, (_band, _y) in RUNG.items():
    LEVELS.append({"id": _k, "height_m": H[_k], "area": rect(LADDER_W, _y, LADDER_E, BAND[_band][1]),
                   "note": f"the Ladder's own terrace in the back half of the {_band} band, 2 m above it"})
OUTLYING = {
    "moss": {"area": rect(-78, 318, -46, 344), "note": "the turf house's yard on the Moss"},
    "hanger": {"area": rect(196, 196, 218, 214), "note": "the Hanger cottage's yard, at the foot of the copse"},
    "headland": {"area": rect(-40, 520, -10, 536), "note": "the Lintel's ground on the north headland"},
}
for k, v in OUTLYING.items():
    LEVELS.append({"id": k, "height_m": H[k], "area": v["area"], "note": v["note"]})
_STRAND = LEVELS[0]
assert _STRAND["id"] == "strand"

SEA = [[-125, 0], [HERON_STAGE[0], 0], [HERON_STAGE[0], HERON_STAGE[2]], [HERON_STAGE[1], HERON_STAGE[2]], [HERON_STAGE[1], 0], *FISH_STEPS, [126, 0], [126, -14], [132, -14], [132, -54], [129, -54], [129, -67], [142, -67], [142, -54], [139, -54], [139, -14], [146, -14], [146, 0], [175, 0], [175, -100], [-125, -100]]

# Row streets: 5 m wide, 4.5 m into each band: a balcony street. On its sea side a 2 m sill under
# the parapet (benches, washing poles), then the drop over the backs of the row below. The grey
# city had the street 9 m in, behind 6.5 m of bare walk; that ground is now behind the houses,
# where a town keeps its yards.
ROW_Y = {lv: BAND[lv][0] + 4.5 for lv in ("low", "mid", "high")}
# Behind each row: a walled back court against the house, a back lane, then plots that lean on
# the wall of the row above. The court is deeper on the 30 m bands.
COURT_D = {"low": 4.4, "mid": 5.2, "high": 5.2}
BACK_LANE_W = 2.5
UPPER_WALK_Y = 123.5
FRONT_GAP = 2.8  # a house's front stands 2.8 m from its street's middle: 0.3 m of kerb
HOUSE_DEPTH = 7.5

# The five wynds (x of the lane) and the flights that climb them, level to level.
# Layout pass 1: where each wynd runs, and what its view ends on.
# - The Ladder Wynd climbs the middle of the Ladder, a flight at each wall (the rungs), and ends
#   on the top walk: the way to the Crown is the Tally Wynd, past the oven and the Rows, and a
#   grower bound for the cistern walks the upper terrace to it. It comes out on the quay through
#   the 4 m slot between the net lofts and the smokehouses.
# - The Net Wynd comes down the Counting House's west wall onto the Heron.
# - The Tally Wynd dog-legs through the hollow the factors' houses left: from the Counting House
#   yard to the oven court, along each Row past its old plots, and up the last flight on the line
#   of the cupola and the Fish Steps.
# - The Store Wynd is as it was.
LADDER_WYND_X, NET_WYND_X, STORE_WYND_X = -52.0, -17.0, 66.0
TALLY_X = [24.0, 34.7, 2.2, 39.7, 0.0]
WYNDS = [
    ("the Ladder Wynd", LADDER_WYND_X, ["strand", "low", "lad_1", "mid", "lad_2", "high", "lad_3", "upper"]),
    ("the Net Wynd", NET_WYND_X, ["strand", "low", "mid", "high"]),
    ("the Tally Wynd", TALLY_X, ["strand", "low", "mid", "high", "upper", "crown"]),
    ("the Store Wynd", STORE_WYND_X, ["strand", "low", "mid", "high"]),
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
# Layout pass 1: the east terraces end on the Store Wynd as before; the west terraces now end on
# the Net Wynd (their west gable is its east side), so the ground the lean years emptied lies in
# the middle of each Row, on the Tally Wynd, and not at its end. `ROW_W` is that gable's x; a west
# terrace's east end follows from its houses' fronts.
ROW_W, ROW_E = NET_WYND_X + 1.5, 64.0
TERRACES = [
    ("low", "Low Row east", [1, 2, 3, 4, 5], ROW_E, None),
    ("low", "Low Row west", [6, 7, 8, 9, 10], None, "batch"),
    ("mid", "Mid Row east", [1, 2, 3, 4], ROW_E, "marver"),
    ("mid", "Mid Row west", [5, 6, 7], None, None),
    ("high", "High Row east", [1, 2, 3, 4], ROW_E, None),
    ("high", "High Row west", [5, 6, 7], None, None),
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
# The kit's folders (living/tools/blender/cullet.py writes `envs/cullet/<folder>/<id>.glb`): one
# folder per kind of thing, so a lot whose model is not built yet finds no other model of its
# folder and stays a grey box. Ids with a number share their folder (net_loft_3 -> net_loft).
ROW_FOLDER = "row_house"
# Open lots people walk on are built as fixtures (below), not as lot models: the game client
# keeps its camera out of every lot's model and fades a low one when you stand by it, which
# suits a building and not a landing or a terrace. The lots stay, for their names and spots.
WALKED_ON = {"fish_steps": 0.9, "marver_terrace": 2.6}  # id -> what stands on it, in metres


def model_path(id):
    head = id.rsplit("_", 1)
    folder = head[0] if len(head) == 2 and head[1].isdigit() else id
    if folder in ("low", "mid", "high"):
        folder = ROW_FOLDER
    # A folder named as one of the engine's structure kinds holds that structure's model (the
    # client draws every `smokehouse` fire with what it finds in `cullet/smokehouse/`), so the
    # smokehouses' own buildings live in another.
    folder = {"smokehouse": "smoke_shed"}.get(folder, folder)
    return f"cullet/{folder}/{id}.glb"


def seed_of(id):
    """The one number a model may roll from (which stone is a shade darker): fixed by its id."""
    return zlib.crc32(f"cullet:{id}".encode()) % 100000


LANDMARKS = {"cone", "counting_house", "heron", "watchglass", "lintel"}


def lot(id, kind, name, at, size, facing, level, height, building=True, age=0.6, repair=0.6, empty=0.0, sheltered=0.0, spots=None, district="", modelled=True, **extra):
    l = {"id": id, "kind": kind, "name": name, "at": [r2(at[0]), r2(at[1])], "size": [r2(size[0]), r2(size[1])], "facing": facing, "level": level, "height_m": r2(height)}
    if id in LANDMARKS:
        l["landmark"] = True
    if spots:
        l["spots"] = [{"name": n, "at": [r2(p[0]), r2(p[1])]} for n, p in spots]
    l["district"] = district
    l["building"] = building
    if modelled and kind not in ("garden", "field") and id not in WALKED_ON:
        l["model"] = model_path(id)
    l["seed"] = seed_of(id)
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
    note="the ship-day dry dock with the hull of the Second Thought on its stocks (8 m to the top of the frames); not one of the 65 buildings",
    stage=0.4, stage_cause="the hull's stage of building, 0 to 1: in frame, planked four strakes of ten")
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
terrace_span = {}  # terrace -> (west x, east x)
for row, tname, numbers, east_x, extra in TERRACES:
    fy = ROW_Y[row] + FRONT_GAP
    if east_x is None:  # a west terrace: its west gable stands on the Net Wynd
        east_x = r2(ROW_W + sum(front_width(ROWS[row][n])[0] for n in numbers) + (8.0 if extra == "batch" else 0.0))
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
        # Its terrace over the harbour: the corner bastion where Mid Row ends, across the Store
        # Wynd from the Marver's door, over the drop to Low Row (south) and to Cinder Row (east).
        # The tables look down the harbour and across at the Cone. (The grey city had it on the
        # walk before the Marver; Mid Row now runs along the parapet there.)
        lot("marver_terrace", "lamp", "the Marver's terrace", (EAST[row] - 6.0, BAND[row][0] + 3.25), (12, 6.5), "south", row, 0, building=False, age=0.5, repair=0.6, district=ROWS_D,
            spots=[(f"terrace seat {i + 1}", (r2(-4.5 + (i % 4) * 3.0), r2(1.5 if i < 4 else -1.0))) for i in range(6)],
            note="tables on the corner bastion at Mid Row's end, over the harbour and Cinder Row")
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
    terrace_span[tname] = (r2(x), r2(east_x))
    if x < ROW_W - 0.01:
        raise SystemExit(f"{tname} runs past the Net Wynd to x {x}")

# The Ladder (layout pass 1): 14 lean-to glasshouses (12 x 4.5 m) and the 18 walled root plots,
# two glasshouses and two or three plots against each of seven walls, from Low Row's level to the
# Crown's. About 65 x 100 m; the glass itself 54 x 92 m (SMALL_CITY §1 asks 90 x 90; the grey
# city's spread over 85 x 140 m, the plots 60 m further west). The Ladder Wynd climbs its middle.
# Which side of the wynd the glass stands on changes from rank to rank, each with a cause:
# - east, toward the Rows: the lee of their roofs, where glass lasts;
# - one each side of the wynd: the rungs;
# - west, toward the wind wall: the last plots to be taken, and the storm's three broken houses
#   are the westernmost of the upper ranks (the storm came from the south-west).
LADDER = "the Ladder"
GLASS_W, GLASS_D, PLOT_W, PLOT_D = 12.0, 4.5, 8.0, 6.0
RANKS = [  # (the wall's y, the terrace below it, pattern, glasshouse numbers east to west)
    (47.0, "low", "east", (1, 2)),
    (60.0, "lad_1", "both", (3, 4)),
    (75.0, "mid", "west", (5, 6)),
    (90.0, "lad_2", "both", (7, 8)),
    (105.0, "high", "east", (9, 10)),
    (120.0, "lad_3", "both", (12, 11)),
    (134.0, "upper", "west", (14, 13)),
]
_WE, _WW = LADDER_WYND_X + STAIR_W / 2, LADDER_WYND_X - STAIR_W / 2  # the wynd's east and west sides
# East ends (x) of what stands in a rank: glasshouses, then root plots.
SLOTS = {
    "east": ([_WE + 12.2, _WE + 25.7], [_WW - 0.2, _WW - 10.2, _WW - 20.2]),
    "both": ([_WE + 12.2, _WW - 0.2], [_WE + 22.2, _WW - 14.2]),
    "west": ([_WW - 0.2, _WW - 13.7], [_WE + 10.0, _WE + 20.0, _WE + 30.0]),
}
PATTERN_CAUSE = {
    "east": "both east of the wynd, in the lee of the Rows' roofs",
    "both": "one each side of the Ladder Wynd: a rung",
    "west": "both west of the wynd, toward the wind wall: the last plots taken for glass",
}
BROKEN = {6, 11, 13}  # the storm's three: the westernmost houses of the third, sixth and top ranks
SOUND = {1, 2, 3}  # the lowest rank, and the east house of the second: in the Rows' shelter
LADDER_LANE = 10.5  # a rank's walk runs this far south of its wall: glass, a bed, then the walk
p = 0
for rank, (wall_y, lv, pattern, numbers) in enumerate(RANKS, 1):
    gx, px = SLOTS[pattern]
    for gh, ex in zip(numbers, gx):
        c, s = (ex - GLASS_W / 2, wall_y - 0.7 - GLASS_D / 2), (GLASS_W, GLASS_D)
        note = "a lean-to against the terrace wall; bays 1 m, panes at most 0.45 m"
        if gh in BROKEN:
            note += "; broken in last autumn's storm, not mended"
        if gh == 9:
            note += "; Jory Greave's fruit tree in one bay"
        if gh == 4:
            note += "; Cora Stannard's flowers in a corner"
        # Repair: the storm's three are broken (0.15); the three in the Rows' shelter are whole
        # (0.9); the others are patched (0.7).
        rep = 0.15 if gh in BROKEN else 0.9 if gh in SOUND else 0.7
        state = "broken" if gh in BROKEN else "sound" if gh in SOUND else "patched"
        lot(f"glasshouse_{gh}", "workshop", f"glasshouse {gh}", c, s, "south", lv, 3.2, age=0.3, repair=rep, empty=0.6 if gh in BROKEN else 0.0, district=LADDER,
            spots=[("the door", (4.5, 2.8)), ("the rain butt", (-6.6, 0.0))], note=note, leans_on=f"the Ladder's wall {rank} of 7 (y {wall_y:g})", state=state, rank=rank, rank_cause=PATTERN_CAUSE[pattern],
            repair_cause="the westernmost house of its rank, open to the south-westerly: broken in last autumn's storm" if gh in BROKEN
            else "low on the Ladder and east of the wynd, in the Rows' shelter: whole" if gh in SOUND else "open to the wind above the Rows: patched")
    for ex in px:
        p += 1
        # An open lot, not a `garden`: a garden is planted with berry bushes, and a root plot
        # grows roots (its `root_plot` resource below). No lot model: its walls are a fixture.
        lot(f"root_plot_{p}", "lamp", f"root plot {p}", (ex - PLOT_W / 2, wall_y - 1.2 - PLOT_D / 2), (PLOT_W, PLOT_D), "south", lv, 0, building=False, age=0.7, repair=0.6, district=LADDER,
            note="walled with dry stone against the terrace wall; fed with kelp", rank=rank)
lots.sort(key=lambda l: (0, 0) if not l["id"].startswith(("glasshouse_", "root_plot_")) else (1 if l["id"].startswith("glasshouse_") else 2, int(l["id"].rsplit("_", 1)[1])))
assert p == 18 and len([l for l in lots if l["id"].startswith("glasshouse_")]) == 14

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
# Lit windows (the dev-box coordinator's decision for pass 2): a window is a static model, so each
# house shows one fixed evening, and it shows 0 to 2 lit windows for a cause its household gives,
# not one to three on every lived-in house. Empty houses are dark. The causes, in order:
# - a night worker: Thessaly Marl (Low Row 10) stokes the Cone by night, Anselm Faro keeps the
#   Watchglass; their houses keep a lamp when the others are asleep;
# - the bakers: Pieter Achterberg rises at 02:30, so the Marver shows one window over the hearth;
# - a Kiln house has someone on a watch at the Cone two evenings in three (three watches: it never
#   goes dark), and then a lamp waits in the kitchen; a Strand house rises with the tide and is
#   dark by now, save one in four where someone mends by lamplight; a Ladder house, done at 16:00,
#   sits up in every second one;
# - a full house (four or more) has someone still up above, two times in three.
# "One in four" and the like are the lot's recorded seed, never a roll.
NIGHT_WORK = {
    "marl": ("g", "u1"), "faro": ("g", "u0"),
}
LIT_CAUSE = {
    "marl": "Thessaly Marl stokes the Cone by night: the kitchen lamp is left for her, and a night light burns above for Wick, who is five",
    "faro": "Anselm Faro keeps the Watchglass: the lamp house is awake all night, below and above",
    "achterberg": "Pieter Achterberg rises at 02:30 to fire the Batch: one window over the hearth",
    "orme": "Benedikt Orme reads the ship-day tablets by lamp: the window with the shelf",
}


def lit_windows(l):
    """Which of a home's windows are lit, and why: {'windows': [...], 'cause': str}. Windows are
    `g` (ground, front), `u0` and `u1` (upper, front: west and east)."""
    h = l.get("household")
    if not h:
        return {"windows": [], "cause": "empty: dark"}
    if h in NIGHT_WORK:
        return {"windows": list(NIGHT_WORK[h]), "cause": LIT_CAUSE[h]}
    if h == "achterberg":
        return {"windows": ["u1"], "cause": LIT_CAUSE[h]}
    if h == "orme":
        return {"windows": ["g"], "cause": LIT_CAUSE[h]}
    seed, fam, people = l["seed"], l.get("family"), l.get("people", 1)
    win, why = [], []
    if fam == "kiln":
        if seed % 3 != 0:
            win.append("g")
            why.append(f"a Kiln house, two in three (seed {seed}): someone is on the evening watch at the Cone, and the kitchen lamp waits")
        else:
            why.append(f"a Kiln house off the watch tonight (seed {seed}): dark")
    elif fam == "strand":
        if seed % 4 == 0:
            win.append("g")
            why.append(f"a Strand house, one in four (seed {seed}): someone mends by lamplight")
        else:
            why.append(f"a Strand house: asleep, they rise with the tide (seed {seed})")
    elif fam == "ladder":
        if seed % 2 == 0:
            win.append("g")
            why.append(f"a Ladder house, every second one (seed {seed}): done at 16:00, they sit up")
        else:
            why.append(f"a Ladder house: early to bed (seed {seed})")
    else:
        why.append("asleep")
    if people >= 4:
        if seed % 3 != 0:
            win.append("u1" if seed % 2 else "u0")
            why.append(f"a full house ({people}): someone is still up above")
        else:
            why.append(f"a full house ({people}), all abed (seed {seed})")
    return {"windows": win[:2], "cause": "; ".join(why)}


for l in lots:
    if l["kind"] == "house" or "household" in l:
        l["lit"] = lit_windows(l)

# ---------------------------------------------------------------------------------------------
# Streets: the quay 10 m, the Rows 5 m, lanes 2.5 to 3.5 m; paths out of town 2 m.

streets = [
    {"id": "the Strand", "points": [[-75, 5], [75, 5]], "width_m": 10.0, "class": "street", "surface": "quay_flags", "level": "strand"},
    {"id": "the slipway", "points": [[-75, 5], [-100, 6], [-110, 6]], "width_m": 3.5, "class": "lane", "surface": "setts", "level": "strand"},
    {"id": "Cinder Row", "points": [[75, 5], [124, 5], [124, 58]], "width_m": 3.5, "class": "lane", "surface": "cinders", "level": "strand"},
    {"id": "the mole", "points": [[136, 0], [136, -54]], "width_m": 4.0, "class": "lane", "surface": "flags", "level": "mole"},
]
# Layout pass 1. A Row runs from the Net Wynd to where it ends with a cause: Low Row at the head
# of the Cinder Steps, Mid Row at the Marver's terrace, High Row at the Store Wynd. West of the
# Net Wynd each Row goes on into the Ladder as a 3 m walk under a rank of glass (so every Row's
# view west ends on glass), and the Ladder's own terraces have a walk each. Behind each Row a
# 2.5 m back lane runs between the courts' walls and the plots under the wall of the row above.
# (Mid Row stops half a metre short of the wynd's middle: a street's end is round, and the
# Marver's terrace begins 2 m past the wynd.)
ROW_END = {"low": 77.5, "mid": STORE_WYND_X - 0.5, "high": STORE_WYND_X}
BACK_LANE_Y = {row: r2(ROW_Y[row] + FRONT_GAP + HOUSE_DEPTH + COURT_D[row] + BACK_LANE_W / 2) for row in ("low", "mid", "high")}
for row in ("low", "mid", "high"):
    streets.append({"id": ROW_NAME[row], "points": [[NET_WYND_X, ROW_Y[row]], [ROW_END[row], ROW_Y[row]]], "width_m": 5.0, "class": "street", "surface": "setts", "level": row})
    streets.append({"id": f"{ROW_NAME[row]} walk", "points": [[NET_WYND_X, ROW_Y[row]], [LADDER_W + 2, ROW_Y[row]]], "width_m": 3.0, "class": "lane", "surface": "earth", "level": row})
    streets.append({"id": f"{ROW_NAME[row]} backs", "points": [[NET_WYND_X, BACK_LANE_Y[row]], [STORE_WYND_X, BACK_LANE_Y[row]]], "width_m": BACK_LANE_W, "class": "lane", "surface": "earth", "level": row})
for _k, _name in (("lad_1", "the Ladder's second walk"), ("lad_2", "the Ladder's fourth walk"), ("lad_3", "the Ladder's sixth walk")):
    streets.append({"id": _name, "points": [[LADDER_W + 2, BAND[_k][1] - LADDER_LANE], [LADDER_E - 2.0, BAND[_k][1] - LADDER_LANE]], "width_m": 3.0, "class": "lane", "surface": "earth", "level": _k})
streets.append({"id": "the upper walk", "points": [[LADDER_W + 2, UPPER_WALK_Y], [50, UPPER_WALK_Y]], "width_m": 3.0, "class": "lane", "surface": "earth", "level": "upper"})
# The Crown's paths are the ones feet make: from the head of the Tally Wynd west to the bench
# beside the thorn, and north-east to the Readers' House (the children, every morning) past
# the cistern (everyone's water), then on to the peat barn and the Moss road (the peat comes down
# this way).
streets.append({"id": "the Crown path", "points": [[-19, 139.0], [TALLY_X[4], 139.0], [14, 150.0], [24, 160.3]], "width_m": 3.0, "class": "lane", "surface": "earth", "level": "crown"})
streets.append({"id": "the peat road", "points": [[24, 160.3], [32.5, 160.3], [35, 176.0], [37.5, 192.5], [50, 192.5]], "width_m": 3.0, "class": "lane", "surface": "earth", "level": "crown"})
# Low Row's end: the lane to the head of the Cinder Steps.
streets.append({"id": "the Cinder Steps' head", "points": [[ROW_END["low"], ROW_Y["low"]], [ROW_END["low"], 50.0]], "width_m": 3.0, "class": "lane", "surface": "setts", "level": "low"})
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
            wy = {**ROW_Y, "upper": UPPER_WALK_Y}[a]
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
# store) and half in the households (once a plan's structure can belong to a household). Kept food: smoked fish for the
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
    "note": f"Not placed yet. Each household's home holds the other {STORE_DAYS / 2:g} days of food for its people, and peat for its hearth beyond the hearth's first fill; with the Store's {STORE_DAYS / 2:g} days that is the {STORE_DAYS} days of §2. The cast exists (towns[].residents, homes), but a household's store must be its own (the theft law reads a store's owner), and a plan's structures have no owner yet: a general `owner` (a household key) on `structures[]` would place these.",
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
# Fixtures (SMALL_CITY §6 "Ground and structure" and "Street dressing"): what stands in the town
# and is not a lot. The engine never sees them (they are kept out of the seed); the asset
# generator builds one model for each and writes where it stands for the game client
# (`envs/cullet/fixtures.json`). `at` is the centre of the fixture's rectangle (`size`: along its
# front, then deep), `facing` the way its front looks, `floor_m` the ground its origin stands on.

fixtures = []


def fixture(id, kind, at, size, facing, floor_m, height, cause, age=0.8, repair=0.5, **extra):
    f = {"id": id, "kind": kind, "model": f"cullet/{kind}/{id}.glb", "at": [r2(at[0]), r2(at[1])], "size": [r2(size[0]), r2(size[1])], "facing": facing,
         "floor_m": r2(floor_m), "height_m": r2(height), "seed": seed_of(id), "cause": cause, "wear": wear(at, floor_m, facing, age, repair, 0.0)}
    f.update(extra)
    fixtures.append(f)
    return f


def sections(a, b, most):
    """a..b cut into equal lengths of at most `most`: [(start, end)]."""
    n = max(1, math.ceil((b - a - 1e-6) / most))
    return [(a + (b - a) * i / n, a + (b - a) * (i + 1) / n) for i in range(n)]


# The quay's wall and edge: wherever the Strand's level meets the harbour, in sections of at most
# 12 m. The face stands 0.5 m out over the water and the coping runs 1.5 m in over the quay (the
# ground's own edge is a bank a metre wide), so the rectangle straddles the edge. Iron ladders every third section (the ship
# days' spacing); the slip's mouth (x -124..-114) is left open for its own model.
QUAY_D = 2.0
SLIP_MOUTH = (-124.0, -114.0)
qn = 0


def quay_run(a, b, edge, facing, note):
    """A run of quay wall between a and b along x (facing south) or along y (facing east or west)."""
    global qn
    for u0, u1 in sections(a, b, 12.0):
        qn += 1
        mid, inn = (u0 + u1) / 2, 0.5
        at = {"south": (mid, edge + inn), "east": (edge - inn, mid), "west": (edge + inn, mid)}[facing]
        fixture(f"quay_{qn:02d}", "quay", at, (u1 - u0, QUAY_D), facing, H["strand"], 0.3, note, age=1.0, repair=0.45,
                ladder=qn % 3 == 0, ring=qn % 3 == 1, tide_m=1.2, water_m=H["strand"])


OUT = 0.5  # how far the face stands out: runs meet at the corners on that line
quay_run(SLIP_MOUTH[1], HERON_STAGE[0] - OUT, 0.0, "south", "the ship-day quay, west of the Heron")
quay_run(HERON_STAGE[2] - OUT, -OUT, HERON_STAGE[0], "west", "the Heron's stage, west side")
quay_run(HERON_STAGE[0], HERON_STAGE[1], HERON_STAGE[2], "south", "the Heron's stage, its front")
quay_run(HERON_STAGE[2] - OUT, -OUT, HERON_STAGE[1], "east", "the Heron's stage, east side")
quay_run(HERON_STAGE[1] + OUT, FISH_STEPS[0][0] - OUT, 0.0, "south", "between the Heron and the Fish Steps")
quay_run(FISH_STEPS[1][1] - OUT, -OUT, FISH_STEPS[0][0], "west", "the Fish Steps' landing, west flank")
quay_run(FISH_STEPS[1][1] - OUT, -OUT, FISH_STEPS[3][0], "east", "the Fish Steps' landing, east flank")
quay_run(FISH_STEPS[3][0] + OUT, MOLE["root"][0] - OUT, 0.0, "south", "the ship-day quay, from the Fish Steps to the mole")
quay_run(MOLE["root"][1] + OUT, 175.0, 0.0, "south", "the quay before the Cone yard")

# The mole (a P0 landmark): its root, three sections of its 40 m arm and its tip. Sea walls on
# both sides, a wave wall on the open (east) side, oversized bollards on the harbour (west) side,
# an iron rail round the tip whose south end went in last autumn's storm.
mr, ma, mt = MOLE["root"], MOLE["arm"], MOLE["tip"]
fixture("mole_root", "mole", ((mr[0] + mr[1]) / 2, mr[2] / 2 - 0.25), (mr[1] - mr[0] + 1.0, -mr[2] + 0.5), "south", H["mole"], 1.2, "the mole's root: 20 x 14 m, the lamp house on it",
        age=1.0, repair=0.5, part="root", arm_x=[ma[0], ma[1]], lamp_house=[139.5, -13.5, 145.5, -7.5], tide_m=1.2, water_m=H["mole"])
for i, (y1, y0) in enumerate((mr[2] - (mr[2] - ma[2]) * i / 3, mr[2] - (mr[2] - ma[2]) * (i + 1) / 3) for i in range(3)):
    fixture(f"mole_arm_{i + 1}", "mole", ((ma[0] + ma[1]) / 2, (y0 + y1) / 2), (ma[1] - ma[0] + 1.0, y1 - y0), "south", H["mole"], 1.2,
            "the mole's arm, a 13.3 m section: the wave wall east, a ship's bollard west", age=1.0, repair=0.5 - 0.1 * i, part="arm", bollard=True, tide_m=1.2, water_m=H["mole"])
fixture("mole_tip", "mole", ((mt[0] + mt[1]) / 2, (mt[2] + ma[2]) / 2), (mt[1] - mt[0] + 1.0, ma[2] - mt[2] + 1.0), "south", H["mole"], 1.2,
        "the mole's tip, 13 x 13 m round the Watchglass; the south rail went in the storm", age=1.0, repair=0.25, part="tip", arm_x=[ma[0], ma[1]], rail_gone="south", tide_m=1.2, water_m=H["mole"])

# Retaining walls: along every drop between two levels of the town, in sections of at most 12 m
# between the wynds' flights. The wall stands in the lower level's 0.6 m drop strip and rises
# 0.4 m above the upper level as a coping (a low wall to sit on). The same walls the engine
# derives as 4 m grey pieces (`settle::plan::retaining`), built here for their places.
WALL_D, COPING, PARAPET = 0.6, 0.4, 1.0
ALONG_M = 10.0  # a street or lane whose middle runs within this of a drop's edge runs along its top


def street_along(level, axis, edge, u0, u1):
    """The street or lane on `level` that runs along the top of a drop (its middle parallel to the
    edge and within ALONG_M of it) over more than half of u0..u1: its id, or None."""
    k, o = (0, 1) if axis == "x" else (1, 0)
    for st in streets:
        if st.get("level") != level or st.get("class") not in ("street", "lane"):
            continue
        covered = 0.0
        for q0, q1 in zip(st["points"], st["points"][1:]):
            if abs(q0[o] - q1[o]) > 0.5 or not (0.0 < abs(q0[o] - edge) <= ALONG_M):
                continue
            covered += max(0.0, min(u1, max(q0[k], q1[k])) - max(u0, min(q0[k], q1[k])))
        if covered > 0.5 * (u1 - u0):
            return st["id"]
    return None


DROPS = [  # (lower, upper, axis, edge, from, to, facing)
    ("strand", "low", "x", 32.0, WEST["low"], 80.0, "south"),
    ("strand", "low", "y", 80.0, 32.0, 60.0, "east"),
    ("strand", "mid", "y", 80.0, 60.0, 62.0, "east"),
    # The Rows' walls, east of the Ladder.
    ("low", "mid", "x", 60.0, LADDER_E, 80.0, "south"),
    ("mid", "high", "x", 90.0, LADDER_E, EAST["high"], "south"),
    ("high", "upper", "x", 120.0, LADDER_E, 55.0, "south"),
    ("upper", "crown", "x", 134.0, WEST["upper"], 55.0, "south"),
    # The Ladder's seven walls (layout pass 1), the top one the Crown's above; and its wall on
    # the Net Wynd, where its own terraces stand 2 m over the Rows' backs.
    ("low", "lad_1", "x", 47.0, LADDER_W, LADDER_E, "south"),
    ("lad_1", "mid", "x", 60.0, LADDER_W, LADDER_E, "south"),
    ("mid", "lad_2", "x", 75.0, LADDER_W, LADDER_E, "south"),
    ("lad_2", "high", "x", 90.0, LADDER_W, LADDER_E, "south"),
    ("high", "lad_3", "x", 105.0, LADDER_W, LADDER_E, "south"),
    ("lad_3", "upper", "x", 120.0, LADDER_W, LADDER_E, "south"),
    ("low", "lad_1", "y", LADDER_E, 47.0, 60.0, "east"),
    ("mid", "lad_2", "y", LADDER_E, 75.0, 90.0, "east"),
    ("high", "lad_3", "y", LADDER_E, 105.0, 120.0, "east"),
]
wn = 0
for lo, hi, axis, edge, a, b, facing in DROPS:
    # The flights that cross this drop leave a gap of their own width.
    gaps = []
    for st in stairs:
        if st["from"] == lo and st["to"] == hi:
            u = st["head"][0] if axis == "x" else st["head"][1]
            across = st["head"][1] if axis == "x" else st["head"][0]
            if abs(across - edge) < 1.0 and a < u < b:
                gaps.append((u - st["width_m"] / 2, u + st["width_m"] / 2))
    runs, at = [], a
    for g0, g1 in sorted(gaps):
        if g0 - at > 0.3:
            runs.append((at, g0, at > a, True))
        at = g1
    if b - at > 0.3:
        runs.append((at, b, at > a, False))
    fall = H[hi] - H[lo]
    for r0, r1, stair_w, stair_e in runs:
        secs = sections(r0, r1, 12.0)
        for k, (u0, u1) in enumerate(secs):
            wn += 1
            mid = (u0 + u1) / 2
            at_ = (mid, edge - WALL_D / 2) if axis == "x" else (edge + WALL_D / 2, mid)
            # A 1 m parapet where a street or lane runs along the top (the dev-box coordinator's
            # decision for pass 2: the edge must read as one people would not step off); the 0.4 m
            # coping, a wall to sit on, elsewhere. The Marver's terrace keeps the coping: it has
            # its own iron rail above the drop.
            along = street_along(hi, axis, edge, u0, u1)
            terr = next((l for l in lots if l["id"] == "marver_terrace"), None)
            railed = bool(terr and axis == "x" and hi == terr["level"] and abs(edge - (terr["at"][1] - terr["size"][1] / 2)) < 0.1
                          and u0 >= terr["at"][0] - terr["size"][0] / 2 - 0.5 and u1 <= terr["at"][0] + terr["size"][0] / 2 + 0.5)
            cop = PARAPET if along and not railed else COPING
            why = (f"a 1 m parapet: {along} runs along the top" if cop == PARAPET else
                   "a 0.4 m coping: the Marver's terrace has its own rail here" if railed else "a 0.4 m coping to sit on: no street or lane runs along the top")
            fixture(f"wall_{wn:03d}", "retaining_wall", at_, (u1 - u0, WALL_D), facing, H[lo], fall + cop,
                    f"the drop from the {hi} level to the {lo} level ({fall:g} m)", age=0.9, repair=0.6, fall_m=fall, coping_m=cop, coping_cause=why,
                    lower=lo, upper=hi, ends=[bool(stair_w and k == 0), bool(stair_e and k == len(secs) - 1)])

# The wynds' flights: one model for each of the plan's stairs, its treads the client's own
# (0.18 m risers: round(rise / 0.18) treads over the flight's run), between basalt cheek walls.
for st in stairs:
    foot, head = st["foot"], st["head"]
    run = math.hypot(head[0] - foot[0], head[1] - foot[1])
    down = "south" if abs(head[0] - foot[0]) < 1e-6 else ("east" if foot[0] > head[0] else "west")
    slug = st["id"].lower().replace("the ", "").replace(",", "").replace(" ", "_")
    fixture(f"stairs_{slug}", "stairs", ((foot[0] + head[0]) / 2, (foot[1] + head[1]) / 2), (st["width_m"], run), down, H[st["from"]], st["rise_m"] + 0.25,
            f"{st['id']}: {st['rise_m']:g} m in {round(st['rise_m'] / 0.18)} treads", age=1.0, repair=0.5, rise_m=st["rise_m"], treads=round(st["rise_m"] / 0.18), stair=st["id"], wall_d=WALL_D)

# The open lots people walk on (WALKED_ON): the Fish Steps' landing and flight, the Marver's
# terrace. Each stands on its lot's rectangle.
for l in [l for l in lots if l["id"] in WALKED_ON]:
    f = fixture(l["id"], l["id"], l["at"], l["size"], l["facing"], H[l["level"]], WALKED_ON[l["id"]], f"{l['name']}: {l['note']}", lot=l["id"])
    f["wear"] = l["wear"]

# The Heron's jib: it reaches 9 m out over the harbour from the king post, past the lot, so it
# is a fixture (a lot's model must stand inside its lot). The numbers are the crane house's own
# (cullet.py HERON): the king post stands 1.55 m south of the lot's middle, 0.42 m thick.
_h = next(l for l in lots if l["id"] == "heron")
fixture("heron_jib", "heron_jib", (_h["at"][0], _h["at"][1] - 1.76 - _h["jib_m"] / 2), (1.6, _h["jib_m"]), "north", H["strand"], _h["height_m"],
        "the Heron's jib, like a beak: 9 m out over the water from the king post, fixed; it still lifts boats and kelp loads",
        age=1.0, repair=0.5, lot="heron", pivot_z=8.3, tip_z=12.2, head_z=12.87, load_z=2.4)

# Plot walls: dry stone round each root plot, 0.45 m thick and 1.0 m high, with a gate gap on the
# side of the Crown path (south).
for l in [l for l in lots if l["id"].startswith("root_plot_")]:
    n = int(l["id"].rsplit("_", 1)[1])
    fixture(f"plot_wall_{n}", "plot_wall", l["at"], l["size"], "south", H[l["level"]], 1.0, f"dry stone round root plot {n}, its back to the terrace wall; the gate faces the walk",
            age=0.7, repair=0.6 - 0.02 * ((n - 1) % 6), gate_at=r2(-2.4 + 1.2 * ((n - 1) % 3)), plot=l["id"])

# The Strand's dressing (SMALL_CITY §6): each thing where its use puts it.
STRAND_H = H["strand"]
DRESS = [
    # (id, kind, at, size, facing, height, cause)
    *[(f"net_rack_{i + 1}", "net_rack", (-72.0 + 6.4 * i, 2.3), (3.0, 0.6), "south", 2.2, f"nets dry on the quay before the lofts they are kept in (loft {6 - 2 * i})") for i in range(3)],
    ("barrels_1", "barrels", (-47.0, 9.25), (1.8, 1.4), "south", 1.1, "fish barrels at the door of Petra Tarn's smokehouse"),
    ("barrels_2", "barrels", (6.2, 1.2), (1.8, 1.4), "west", 1.1, "salt barrels beside the Fish Steps, where the catch is divided"),
    ("creels_1", "creels", (-6.0, 1.0), (1.4, 1.0), "east", 0.9, "creels left beside the Fish Steps by the wrack gatherers"),
    ("creels_2", "creels", (-59.5, 9.6), (1.4, 1.0), "south", 0.9, "creels at the net lofts' doors"),
    *[(f"bollard_{i + 1}", "bollard", (x, 0.85), (0.6, 0.6), "south", 1.1, "a ship's bollard: one every 24 m, a ship's length apart, far too big for a fishing boat")
      for i, x in enumerate((-108.0, -84.0, -60.0, -36.0, 14.0, 38.0, 62.0, 86.0, 110.0))],
    *[(f"quay_lamp_{i + 1}", "quay_lamp", at, (0.6, 0.6), "south", 3.2, why) for i, (at, why) in enumerate([
        ((LADDER_WYND_X + 2.6, 0.9), "the quay lamp at the foot of the Ladder Wynd"), ((-23.0, 0.9), "the quay lamp at the foot of the Net Wynd, west of the Heron's stage"),
        ((-5.3, 0.9), "the quay lamp at the Fish Steps, west"),  # east of the steps the engine's own lamp stands (structures: a `lamp` with fuel)
        ((24.0, 0.9), "the quay lamp at the foot of the Tally Wynd"), ((66.0, 0.9), "the quay lamp at the foot of the Store Wynd"),
        ((127.2, -1.2), "the quay lamp at the root of the mole")])],
    ("boat_1", "boat", (-80.0, 13.0), (4.2, 1.5), 200, 1.3, "an upturned boat on trestles beside the boatshed, waiting on Bram Calloway"),
    ("peat_stack_1", "peat_stack", (46.75, 12.2), (2.0, 1.2), "west", 1.4, "peat under a tarred cloth in the gap between the Counting House yard and the Store"),
    ("floats_1", "floats", (-36.6, 9.7), (1.8, 1.0), "south", 2.0, "a string of glass floats and a crate of cullet at the east wall of the smokehouses (the slot west of them is the Ladder Wynd's mouth)"),
    ("floats_2", "floats", (16.4, 9.6), (1.8, 1.0), "south", 2.0, "floats and cullet for sale at the corner of the Counting House yard"),
]
for id, kind, at, size, facing, height, cause in DRESS:
    fixture(id, kind, at, size, facing, STRAND_H, height, cause, age=0.6, repair=0.5, dressing=True)

# ---------------------------------------------------------------------------------------------
# Layout pass 1 (docs/CULLET_LAYOUT.md): what stands on the ground the grey city left bare, and
# why. All of it is fixtures: an enclosure is a rectangle with walls and things in it, and the
# kit's generator (cullet.py `gen_enclosure`) builds exactly what is written here. Nothing is
# rolled: a household's yard holds what its people do (SMALL_CITY §3), a wall is as high as the
# family that keeps it can afford, an empty house's yard has gone to weed.
# Coordinates here are the plan's; `enclosure` stores walls and contents relative to the
# rectangle's middle (x east, y north: every enclosure faces south).

WALL_TH = 0.4


def enclosure(id, kind, x0, y0, x1, y1, level, cause, walls=(), contents=(), ground=None, age=0.7, repair=0.6, **extra):
    """A rectangle x0..x1, y0..y1 on a level. walls: (side or ((xa, ya), (xb, yb)), height, style,
    gaps) with side one of s, n, w, e (the wall lies just inside that edge), style `dry` (rough
    basalt, uneven top), `coped` (coursed, a coping) or `stub` (a pulled-down house's wall: its
    height falls along its length to `low`), gaps [(from, to)] in metres along the wall from its
    west or south end. contents: (what, (x, y), {options})."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ws, top = [], 0.3
    for w in walls:
        side, h, style = w[0], w[1], w[2]
        gaps = w[3] if len(w) > 3 else ()
        opt = w[4] if len(w) > 4 else {}
        hw = opt.get("th", WALL_TH) / 2
        side_line = {"s": ((x0, y0 + hw), (x1, y0 + hw)), "n": ((x0, y1 - hw), (x1, y1 - hw)), "w": ((x0 + hw, y0), (x0 + hw, y1)), "e": ((x1 - hw, y0), (x1 - hw, y1))}
        a, b = side_line[side] if isinstance(side, str) else side
        ws.append({"from": [r2(a[0] - cx), r2(a[1] - cy)], "to": [r2(b[0] - cx), r2(b[1] - cy)], "h": h, "style": style, "gaps": [[r2(g[0]), r2(g[1])] for g in gaps], **opt})
        top = max(top, h)
    cs = []
    for c in contents:
        what, at = c[0], c[1]
        opt = dict(c[2]) if len(c) > 2 else {}
        for k_ in ("to",):
            if k_ in opt:
                opt[k_] = [r2(opt[k_][0] - cx), r2(opt[k_][1] - cy)]
        cs.append({"what": what, "at": [r2(at[0] - cx), r2(at[1] - cy)], **opt})
        top = max(top, CONTENT_H.get(what, 1.0))
    f = fixture(id, kind, (cx, cy), (x1 - x0, y1 - y0), "south", H[level], top, cause, age=age, repair=repair, level=level, walls=ws, contents=cs, **extra)
    if ground:
        f["ground"] = ground
    return f


# How high each thing stands (the fixture's height, for the client), and what it is.
CONTENT_H = {
    "privy": 2.3, "lean_to": 2.2, "boat_shed": 2.0, "peat": 1.3, "butt": 1.1, "washing": 2.4, "hens": 1.3, "beds": 0.4, "herbs": 0.6, "flowers": 0.6, "boat": 1.3, "nets": 2.4,
    "kelp": 1.1, "frames": 0.6, "slates": 1.0, "blocks": 0.9, "pots": 0.9, "cullet": 0.8, "timber": 1.0, "handcart": 1.0, "barrels": 1.1, "creels": 0.9, "bench": 0.9, "weeds": 0.7,
    "rubble": 0.8, "hearth": 3.4, "paving": 0.06, "table": 0.9, "sundial": 1.1, "trough": 0.7, "ropewalk": 2.0, "barrow": 0.7, "wigwam": 1.9, "stoop": 0.4, "ash_sacks": 0.7,
}
# A court's wall, by who keeps it: Kiln families cope theirs at 2 m; the others build dry.
YARD_WALL = {"kiln": (2.0, "coped"), "strand": (1.5, "dry"), "ladder": (1.7, "dry"), "other": (1.8, "coped")}
# What a household keeps behind its house, and why (SMALL_CITY §3). court: beside the standing
# things of every lived-in court (a privy, a rain butt, a peat stack for the hearth); plot: the
# use of its plot across the back lane, under the wall of the row above.
BACKS = {
    "dunlin": ("creels", "boat", "Rafe Dunlin fishes from the mole by lamplight: his boat is up on trestles, his creels in the court"),
    "calloway": ("lean_to", "timber", "Bram Calloway is building the Second Thought: planks and ship's knees season under the wall, his tools in a lean-to"),
    "tarn": ("washing", "nets", "seven Tarns: a line of washing never down in the court, the family's nets drying on poles in the plot"),
    "okoro": ("boat_shed", "kelp", "Chidi Okoro keeps his line in a shed roofed with an upturned boat; Amara dries her wrack on racks"),
    "vane": ("handcart", "beds", "Davin Vane's handcart stands in the court; a few rows of roots, poorly kept"),
    "morrow": ("bench", "nets", "Ingrid Morrow mends nets where the sun is: her frame and poles in the plot, a bench she carries about"),
    "sato": ("ash_sacks", "kelp", "Kenji Sato's ash sacks under the eave and the smoke-grey washing; Hana's wrack drying"),
    "marl": ("washing", "beds", "Thessaly Marl works nights: a child's washing, and a bed of roots she digs at dusk"),
    "achterberg": ("barrels", "hens", "the Marver's kitchen court: fish barrels (Petra Tarn's, unpaid) and the cookshop's hens"),
    "greave": ("frames", "frames", "four growers: seedlings hardening in cold frames before they go up to the Ladder"),
    "fenwick": ("butt", "beds", "Hobb Fenwick keeps the cistern and catches every drop at home too; Nan's roots"),
    "stannard": ("slates", "flowers", "Gwil Stannard's odd slates, sorted by size; Cora's flowers, which Oswin wants off the Ladder"),
    "sarro": ("bench", "beds", "the Sarros: a bench in the evening sun, roots"),
    "brandt": ("pots", "hens", "Otto Brandt's crucibles drying on planks; Fenn's hens, each named after someone"),
    "pontil": ("cullet", "beds", "Ode Pontil's cullet, one crate a colour; roots Lumi waters"),
    "hollin": ("frames", "washing", "Tamsin Hollin's pane crates and a frame glazed with her offcuts; four people's washing"),
    "quill": ("bench", "herbs", "Mirren Quill's physic garden: the healer's herbs in beds edged with slate"),
    "dunmore": ("lean_to", "beds", "the Dunmores: Tobiah's fishing lines hidden in the lean-to; roots"),
}
back_of = {}  # lot id -> (court fixture, plot fixture)
for row, tname, numbers, _e, extra_b in TERRACES:
    members = terrace_lots[tname]
    by_id = {l["id"]: l for l in lots}
    y_house = ROW_Y[row] + FRONT_GAP + HOUSE_DEPTH
    y_court = y_house + COURT_D[row]
    y_plot0, y_plot1 = BACK_LANE_Y[row] + BACK_LANE_W / 2, BAND[row][1] - WALL_D
    for i, lid in enumerate(members):
        l = by_id[lid]
        x0, x1 = l["at"][0] - l["size"][0] / 2, l["at"][0] + l["size"][0] / 2
        yb = l["at"][1] + l["size"][1] / 2  # the Marver is a metre deeper
        east_end, hh = i == 0, l.get("household")
        fam = l.get("family") if hh else None
        state = l.get("state", "")
        if lid == "batch":
            court_c = [("peat", (x0 + 2.4, y_court - 1.2), {"n": 3}), ("barrow", (x1 - 1.4, yb + 1.4))]
            plot_use, why = "peat", "the Batch's fuel: peat for the common oven, stacked under tarred cloth in its court and its plot"
            wh, wstyle = 1.6, "dry"
        elif hh:
            thing, plot_use, why = BACKS[hh]
            wh, wstyle = YARD_WALL[fam]
            mid = (x0 + x1) / 2
            court_c = [("privy", (x1 - 0.95 - (WALL_TH if east_end else 0.0), y_court - WALL_TH - 0.8)), ("butt", (x0 + WALL_TH + 0.55, yb + 0.5)), ("peat", (x0 + WALL_TH + 1.0, y_court - WALL_TH - 0.75), {"n": 1})]
            if thing in ("washing",):
                court_c.append(("washing", (x0 + 0.9, yb + COURT_D[row] * 0.45), {"to": (x1 - 1.6, yb + COURT_D[row] * 0.45), "cloth": "smoke" if hh == "sato" else "linen"}))
            elif thing in ("lean_to", "boat_shed"):
                court_c.append((thing, (mid + 0.4, yb + 0.85), {"w": 2.4}))
            elif thing != "butt":
                court_c.append((thing, (mid + 0.2, yb + 1.3)))
            else:
                court_c += [("butt", (mid, yb + 0.5)), ("butt", (mid + 1.1, yb + 0.5))]
            if hh == "sato":
                court_c.append(("washing", (x0 + 0.9, yb + 2.6), {"to": (x1 - 1.6, yb + 2.6), "cloth": "smoke"}))
        elif state == "empty, sound":
            court_c, plot_use, why, wh, wstyle = [("weeds", ((x0 + x1) / 2, (yb + y_court) / 2), {"r": 1.8})], "weeds", f"{l['name']} stands empty: its court and plot have gone to weed, the wall's top is down", 1.3, "dry"
        else:
            court_c, plot_use, why, wh, wstyle = [("rubble", ((x0 + x1) / 2, yb + 1.2), {"r": 1.6}), ("weeds", (x0 + 1.5, y_court - 1.4), {"r": 1.2})], "rubble", f"{l['name']} is a roofless shell: its roof went for fuel in the lean years, and what fell lies in the court", 1.1, "dry"
        # The court: the party wall on its west, the back wall with a gate onto the back lane,
        # and the terrace's east end wall. (The house is its south wall.)
        gate = (l["size"][0] * 0.5 - 0.5, l["size"][0] * 0.5 + 0.5)
        cw = [("w", wh, wstyle), ("n", wh, wstyle, [gate], {"gate": True})] + ([("e", wh, wstyle)] if east_end else [])
        court = enclosure(f"court_{lid}", "yard", x0, yb, x1, y_court, row, f"the back court of {l['name']}: {why}", cw, court_c, ground="setts" if hh or lid == "batch" else "earth",
                          age=l["wear"]["age"], repair=l["wear"]["repair"], lot=lid, family=fam or "", state=state or "kept")
        # The plot across the lane: a knee-high dry-stone wall on the lane, the party wall, and
        # the wall of the row above behind it.
        pc = {
            "boat": [("boat", ((x0 + x1) / 2, (y_plot0 + y_plot1) / 2 + 0.4)), ("creels", (x0 + 1.2, y_plot0 + 1.2))],
            "timber": [("timber", ((x0 + x1) / 2, y_plot1 - 1.3), {"len": min(4.6, x1 - x0 - 0.9)}), ("timber", ((x0 + x1) / 2, y_plot1 - 3.2), {"len": 3.2, "knees": True})],
            "nets": [("nets", ((x0 + x1) / 2, (y_plot0 + y_plot1) / 2 + 0.3), {"len": x1 - x0 - 1.6})],
            "kelp": [("kelp", ((x0 + x1) / 2, y_plot1 - 1.4), {"len": x1 - x0 - 1.4, "rack": True}), ("kelp", (x0 + 1.5, y_plot0 + 1.5), {"len": 1.4})],
            "beds": [("beds", ((x0 + x1) / 2, (y_plot0 + y_plot1) / 2 + 0.2), {"w": x1 - x0 - 1.3, "d": y_plot1 - y_plot0 - 1.5, "poor": hh == "vane"}), ("kelp", (x1 - 1.0, y_plot1 - 0.9), {"len": 1.0})],
            "herbs": [("herbs", ((x0 + x1) / 2, (y_plot0 + y_plot1) / 2 + 0.2), {"w": x1 - x0 - 1.3, "d": y_plot1 - y_plot0 - 1.5}), ("bench", (x0 + 1.4, y_plot1 - 0.6))],
            "flowers": [("flowers", ((x0 + x1) / 2, (y_plot0 + y_plot1) / 2 + 0.2), {"w": x1 - x0 - 1.3, "d": y_plot1 - y_plot0 - 1.5})],
            "hens": [("hens", ((x0 + x1) / 2, (y_plot0 + y_plot1) / 2 + 0.3), {"w": x1 - x0 - 1.2, "d": y_plot1 - y_plot0 - 1.6, "n": 7 if hh == "brandt" else 5})],
            "frames": [("frames", ((x0 + x1) / 2, y_plot1 - 1.3), {"n": 3}), ("frames", ((x0 + x1) / 2, y_plot0 + 1.6), {"n": 2}), ("wigwam", (x1 - 1.1, (y_plot0 + y_plot1) / 2))],
            "washing": [("washing", (x0 + 0.9, (y_plot0 + y_plot1) / 2 + 1.0), {"to": (x1 - 0.9, (y_plot0 + y_plot1) / 2 + 1.0), "cloth": "linen"}), ("washing", (x0 + 0.9, (y_plot0 + y_plot1) / 2 - 1.0), {"to": (x1 - 0.9, (y_plot0 + y_plot1) / 2 - 1.0), "cloth": "colours"})],
            "peat": [("peat", ((x0 + x1) / 2 - 1.2, y_plot1 - 1.0), {"n": 3}), ("peat", ((x0 + x1) / 2 + 1.6, y_plot0 + 1.6), {"n": 2})],
            "weeds": [("weeds", ((x0 + x1) / 2, (y_plot0 + y_plot1) / 2), {"r": 2.2})],
            "rubble": [("rubble", ((x0 + x1) / 2 - 0.6, y_plot1 - 1.2), {"r": 1.3}), ("weeds", ((x0 + x1) / 2, (y_plot0 + y_plot1) / 2 - 0.6), {"r": 2.0})],
        }[plot_use]
        pg = (l["size"][0] * 0.5 - 0.6, l["size"][0] * 0.5 + 0.6)
        ph = 0.9 if hh or lid == "batch" else 0.6
        pw = [("w", ph, "dry"), ("s", ph, "dry", [pg])] + ([("e", ph, "dry")] if east_end else [])
        plot = enclosure(f"plot_{lid}", "back_plot", x0, y_plot0, x1, y_plot1, row, f"the plot of {l['name']}, across the back lane under the wall of the row above: {why}", pw, pc,
                         ground="worked_soil" if plot_use in ("beds", "herbs", "flowers", "frames") else "earth", age=0.7, repair=l["wear"]["repair"], lot=lid, use=plot_use)
        back_of[lid] = (court["id"], plot["id"])

# The hollow on the Tally Wynd: the middle of each Row, straight above the Counting House, was the
# factors' and shipmasters' houses. They left first when the ships stopped, and their roofs were
# the first stripped (SMALL_CITY §1, the lean years). What is left is different on each Row:
# - Low Row: the ground was cleared to the setts and is the oven court, before the Batch: where
#   the town meets every morning while its roots bake;
# - Mid Row: five tofts, the houses' walls pulled down to the height a person could reach, the
#   hearths left standing; the Row's households work them;
# - High Row: seven walled gardens, the walls kept whole and coped by the Kiln families who took
#   the plots.
HOLLOW = {}
for row in ("low", "mid", "high"):
    w_e = terrace_span[f"{ROW_NAME[row]} west"][1]
    e_w = terrace_span[f"{ROW_NAME[row]} east"][0]
    tx = TALLY_X[{"low": 1, "mid": 2, "high": 3}[row]]  # this Row's flight up
    lane = (tx - STAIR_W / 2, tx + STAIR_W / 2)
    HOLLOW[row] = (w_e, lane[0]) if lane[1] > e_w - 0.3 else (lane[1], e_w)
    assert abs((lane[1] if HOLLOW[row][0] == w_e else lane[0]) - (e_w if HOLLOW[row][0] == w_e else w_e)) < 0.31, (row, lane, w_e, e_w)
fy = {row: ROW_Y[row] + FRONT_GAP for row in ROW_Y}

# Low Row: the oven court.
x0, x1 = HOLLOW["low"]
yb, yc = fy["low"], fy["low"] + HOUSE_DEPTH + COURT_D["low"]
enclosure("oven_court", "oven_court", x0, yb, x1, yc, "low",
          "the oven court before the Batch: the factors' plots on Low Row, cleared to the setts; the town meets here each morning while its roots bake, and the Tally Wynd comes up into it",
          [("n", 1.1, "coped", [((x1 - x0) / 2 - 1.2, (x1 - x0) / 2 + 1.2)])],
          [("paving", ((x0 + x1) / 2, (yb + yc) / 2), {"w": x1 - x0, "d": yc - yb}), ("bench", (x0 + 1.0, yb + 3.0), {"turn": 90, "len": 2.4}), ("bench", (x0 + 1.0, yb + 7.0), {"turn": 90, "len": 2.4}),
           ("table", ((x0 + x1) / 2 - 0.5, yb + 6.4), {"len": 3.0}), ("bench", ((x0 + x1) / 2 - 0.5, yb + 7.5), {"len": 2.6}), ("bench", ((x0 + x1) / 2 - 0.5, yb + 5.3), {"len": 2.6}),
           ("peat", (x0 + 1.6, yc - 1.3), {"n": 2}), ("trough", (x1 - 1.4, yb + 5.0), {"turn": 90}), ("butt", (x1 - 0.8, yc - 1.0)), ("stoop", ((x0 + x1) / 2 + 3.0, yb + 0.5), {"w": 1.2})],
          ground="setts", age=0.9, repair=0.6, spots_for="batch")
enclosure("plot_oven_court", "back_plot", x0, BACK_LANE_Y["low"] + BACK_LANE_W / 2, x1, BAND["low"][1] - WALL_D, "low",
          "under the wall behind the oven court: the town's drying green on Low Row, poles and lines anyone may use (the factors' back plots)",
          [("w", 0.9, "dry"), ("s", 0.9, "dry", [(3.0, 4.2), (10.5, 11.7)])],
          [("washing", (x0 + 1.0, 55.3), {"to": (x1 - 1.0, 55.3), "cloth": "linen"}), ("washing", (x0 + 1.0, 57.2), {"to": (x1 - 1.0, 57.2), "cloth": "colours"}), ("bench", (x1 - 1.6, 58.6))], ground="earth", use="washing")

# Mid Row: the tofts.
TOFTS = [  # (use, who, why)
    ("beds", "the Sarros", "dug for roots inside the old walls; the door's step is the way in"),
    ("frames", "the Greaves", "cold frames glazed with broken panes, in the lee of the old gable: seedlings for the Ladder"),
    ("weeds", "nobody", "nobody's: the back wall has fallen in, the hearth stands in nettles"),
    ("washing", "the Row", "Mid Row's drying green: lines strung between the old party walls"),
    ("slates", "Gwil Stannard", "the mason's yard: slates stripped from the empty houses, sorted, and stone for mending"),
]
x0, x1 = HOLLOW["mid"]
n = len(TOFTS)
tw = (x1 - x0) / n
yb, yh, yc = fy["mid"], fy["mid"] + HOUSE_DEPTH, fy["mid"] + HOUSE_DEPTH + COURT_D["mid"]
for i, (use, who, why) in enumerate(TOFTS):
    a, b = x0 + i * tw, x0 + (i + 1) * tw
    door = (tw * 0.5 - 0.5, tw * 0.5 + 0.5)
    walls = [("s", 1.1, "stub", [door], {"low": 0.7}), ("w", 2.6, "stub", (), {"low": 1.0}), (((a, yh), (b, yh)), 2.9 if use != "weeds" else 1.2, "stub", [(tw * 0.5 + 0.9, tw * 0.5 + 1.9)], {"low": 1.6 if use != "weeds" else 0.5}),
             ("n", 1.2, "dry", [door])] + ([("e", 2.6, "stub", (), {"low": 1.0})] if i == n - 1 else [])
    mx, my = (a + b) / 2, (yb + yh) / 2
    inside = {
        "beds": [("beds", (mx, my), {"w": tw - 1.6, "d": HOUSE_DEPTH - 2.2}), ("kelp", (mx + 1.2, yh + 1.6), {"len": 1.4})],
        "frames": [("frames", (mx, yh - 1.2), {"n": 3}), ("frames", (mx, my - 1.2), {"n": 3}), ("wigwam", (mx - 1.4, yh + 2.0)), ("butt", (b - 0.9, yh + 0.8))],
        "weeds": [("weeds", (mx, my), {"r": 2.4}), ("rubble", (mx + 0.8, yh - 0.6), {"r": 1.5}), ("weeds", (mx, yh + 2.4), {"r": 2.0})],
        "washing": [("washing", (a + 0.5, my + 1.2), {"to": (b - 0.4, my + 1.2), "cloth": "linen"}), ("washing", (a + 0.5, my - 1.4), {"to": (b - 0.4, my - 1.4), "cloth": "colours"}), ("bench", (mx, yh + 1.0))],
        "slates": [("slates", (mx - 1.0, my + 1.6)), ("slates", (mx + 1.2, my - 0.6)), ("blocks", (mx, yh + 2.2)), ("barrow", (mx + 1.4, my + 2.0))],
    }[use]
    enclosure(f"toft_{i + 1}", "toft", a, yb, b, yc, "mid", f"toft {i + 1} on Mid Row, a factor's house pulled down in the lean years ({who}): {why}", walls,
              [("stoop", (a + tw * 0.5, yb + 0.35), {"w": 1.2}), ("hearth", (a + tw * 0.5 - 1.4, yh - 0.45))] + inside,
              ground="worked_soil" if use in ("beds", "frames") else "earth", age=1.0, repair=0.2, use=use, who=who)
    enclosure(f"plot_toft_{i + 1}", "back_plot", a, BACK_LANE_Y["mid"] + BACK_LANE_W / 2, b, BAND["mid"][1] - WALL_D, "mid", f"the old back plot of toft {i + 1}: gone to weed under the wall" if use in ("weeds", "washing", "slates") else f"the old back plot of toft {i + 1}: {who} dig it too",
              [("w", 0.6, "dry"), ("s", 0.6, "dry", [door])] + ([("e", 0.6, "dry")] if i == n - 1 else []),
              [("weeds", (mx, 85.6), {"r": 2.2})] if use in ("weeds", "washing", "slates") else [("beds", (mx, 85.6), {"w": tw - 1.5, "d": 5.6}), ("kelp", (b - 1.1, 88.4), {"len": 1.0})],
              ground="earth" if use in ("weeds", "washing", "slates") else "worked_soil", use="weeds" if use in ("weeds", "washing", "slates") else "beds")

# High Row: the walled gardens.
GARDENS = [  # (use, who, why)
    ("beds", "the Dunmores", "roots in straight rows; Greta sits here out of the wash-house steam"),
    ("frames", "the Hollins", "Tamsin Hollin's frames, glazed whole: the glazier's own panes"),
    ("weeds", "nobody since the fever winter", "locked: the family that kept it died six winters ago, and no one has asked for it"),
    ("herbs", "Mirren Quill", "the healer's second garden: what will not grow in her plot's shade"),
    ("cullet", "Ode Pontil", "Ode Pontil's colours: a bed edged with one lump of every glass the Cone has made"),
    ("beds", "the Quills", "roots, and a bench where Aldous Quill reads the ledger"),
    ("hens", "the Pontils", "the Kiln's hens, behind a wall no hawk-gull stoops over"),
]
x0, x1 = HOLLOW["high"]
n = len(GARDENS)
tw = (x1 - x0) / n
yb, yc = fy["high"], fy["high"] + HOUSE_DEPTH + COURT_D["high"]
for i, (use, who, why) in enumerate(GARDENS):
    a, b = x0 + i * tw, x0 + (i + 1) * tw
    door = (tw * 0.5 - 0.5, tw * 0.5 + 0.5)
    walls = [("s", 2.0, "coped", [door], {"gate": use != "weeds", "boarded": use == "weeds"}), ("w", 2.0, "coped"), ("n", 2.0, "coped", [door], {"gate": True})] + ([("e", 2.0, "coped")] if i == n - 1 else [])
    mx, my = (a + b) / 2, (yb + yc) / 2
    inside = {
        "beds": [("beds", (mx, my + 1.0), {"w": tw - 1.7, "d": 7.0}), ("bench", (mx, yb + 1.3)), ("butt", (b - 0.8, yc - 0.9))],
        "frames": [("frames", (mx, yc - 1.5), {"n": 3, "whole": True}), ("frames", (mx, my), {"n": 3, "whole": True}), ("frames", (mx, yb + 2.2), {"n": 2, "whole": True}), ("wigwam", (a + 1.3, my + 2.6))],
        "weeds": [("weeds", (mx, my + 2.0), {"r": 2.4}), ("weeds", (mx, my - 3.0), {"r": 2.2})],
        "herbs": [("herbs", (mx, my + 0.6), {"w": tw - 1.7, "d": 8.0}), ("sundial", (mx, yb + 1.6))],
        "cullet": [("cullet", (mx, my + 1.0), {"w": tw - 1.8, "d": 7.0, "bed": True}), ("bench", (mx, yb + 1.3))],
        "hens": [("hens", (mx, my + 1.4), {"w": tw - 1.5, "d": 6.6, "n": 6}), ("butt", (a + 0.9, yb + 0.9))],
    }[use]
    enclosure(f"garden_{i + 1}", "walled_garden", a, yb, b, yc, "high", f"walled garden {i + 1} on High Row, a shipmaster's plot ({who}): {why}", walls, inside,
              ground="worked_soil" if use in ("beds", "herbs", "frames", "cullet") else "earth", age=0.9, repair=0.75 if use != "weeds" else 0.3, use=use, who=who)
    enclosure(f"plot_garden_{i + 1}", "back_plot", a, BACK_LANE_Y["high"] + BACK_LANE_W / 2, b, BAND["high"][1] - WALL_D, "high",
              f"under the quarry face behind garden {i + 1}: stone that was cut and never carried down", [("w", 0.6, "dry"), ("s", 0.6, "dry", [door])] + ([("e", 0.6, "dry")] if i == n - 1 else []),
              [("blocks", (mx - 0.6, 118.2)), ("weeds", (mx, 115.0), {"r": 2.0})] if i % 2 == 0 else [("weeds", (mx, 115.6), {"r": 2.3}), ("rubble", (mx + 0.6, 117.6), {"r": 1.0})], ground="earth", use="quarry")

# The ends of the Rows, east of the Store Wynd.
enclosure("the_bleach", "drying_green", STORE_WYND_X + 2.2, fy["low"] + 0.6, ROW_END["low"] - 2.0, BAND["low"][1] - WALL_D - 0.4, "low",
          "the Bleach: the wash-house's drying green on the corner over Cinder Row, up the Cinder Steps from the Cone's warm wall and upwind of its soot (Greta Dunmore wants the smoke kept off the washing)",
          [("s", 0.8, "dry", [(3.0, 4.4)]), ("w", 0.8, "dry"), ("n", 0.8, "dry")],
          [("washing", (STORE_WYND_X + 3.2, fy["low"] + 2.6 + 3.1 * j), {"to": (ROW_END["low"] - 3.0, fy["low"] + 2.6 + 3.1 * j), "cloth": "linen" if j % 2 == 0 else "colours", "tall": True}) for j in range(6)] + [("bench", (STORE_WYND_X + 4.0, fy["low"] + 1.3)), ("barrow", (ROW_END["low"] - 3.4, fy["low"] + 1.4))],
          ground="earth", use="washing")
enclosure("marver_yard", "yard", STORE_WYND_X + 2.2, BAND["mid"][0] + 7.3, EAST["mid"] - 0.8, BACK_LANE_Y["mid"] - 2.0, "mid",
          "the Marver's kitchen garden, behind its terrace on the corner bastion: roots and greens for the pot, kelp to feed them",
          [("s", 1.2, "coped", [(1.0, 2.2)]), ("w", 1.2, "coped"), ("n", 1.2, "coped"), ("e", 1.2, "coped")],
          [("beds", (STORE_WYND_X + 7.0, BAND["mid"][0] + 13.2), {"w": 8.4, "d": 7.6}), ("kelp", (EAST["mid"] - 2.2, BAND["mid"][0] + 9.0), {"len": 1.4}), ("butt", (STORE_WYND_X + 3.2, BAND["mid"][0] + 8.2)), ("frames", (STORE_WYND_X + 7.0, BACK_LANE_Y["mid"] - 3.2), {"n": 3})],
          ground="worked_soil", lot="marver", family="other", state="kept")

# The Ladder's wind wall: a 2.4 m dry-stone wall down its west side, stepping with the terraces,
# against the south-westerly. (The storm's three broken houses are the ones nearest it: it was
# not enough.) And each rank's working corner: kelp for the beds, cold frames, canes, a barrow.
_terr = [("low", BAND["low"][0], 47.0), ("lad_1", 47.0, 60.0), ("mid", 60.0, 75.0), ("lad_2", 75.0, 90.0), ("high", 90.0, 105.0), ("lad_3", 105.0, 120.0), ("upper", 120.0, 134.0)]
for i, (lv, ya, yb_) in enumerate(_terr, 1):
    enclosure(f"wind_wall_{i}", "wind_wall", LADDER_W, ya, LADDER_W + 0.7, yb_ - WALL_D, lv, f"the Ladder's wind wall on its terrace {i} of 7: dry basalt, 2.4 m, against the south-westerly",
              [("w", 2.4, "dry", (), {"th": 0.6})], [], age=0.5, repair=0.5 - 0.04 * i)
for rank, (wall_y, lv, pattern, numbers) in enumerate(RANKS, 1):
    ya = wall_y - 7.6
    spare = {"east": (-24.3, LADDER_E - 0.5), "both": (-27.3, LADDER_E - 0.5), "west": (LADDER_W + 0.9, -79.7)}[pattern]
    cx_ = (spare[0] + spare[1]) / 2
    cont = [("kelp", (cx_, wall_y - 2.3), {"len": min(2.4, spare[1] - spare[0] - 1.0), "fork": True}), ("frames", (cx_, wall_y - 4.4), {"n": 2 if spare[1] - spare[0] > 5 else 1, "turn": 0 if spare[1] - spare[0] > 5 else 90})]
    if spare[1] - spare[0] > 6:
        cont += [("wigwam", (spare[0] + 1.2, wall_y - 6.4)), ("barrow", (spare[1] - 1.4, wall_y - 6.6))]
    enclosure(f"ladder_corner_{rank}", "ladder_corner", spare[0], ya, spare[1], wall_y - WALL_D, lv, f"the working corner of the Ladder's rank {rank}: a kelp heap and fork for the beds, cold frames, canes",
              [], cont, ground="earth", age=0.4, repair=0.6)
    if pattern == "both":  # the west end of a rung has the room for a second corner
        enclosure(f"ladder_corner_{rank}w", "ladder_corner", LADDER_W + 0.9, ya, -76.6, wall_y - WALL_D, lv, f"the west corner of the Ladder's rank {rank}, under the wind wall: canes and a second kelp heap",
                  [], [("kelp", (-80.0, wall_y - 2.3), {"len": 2.2}), ("wigwam", (-78.4, wall_y - 5.0)), ("wigwam", (-81.2, wall_y - 5.6)), ("butt", (-82.2, wall_y - 1.3))], ground="earth", age=0.4, repair=0.6)

# The Strand's backs: the ground between the quay's buildings and Low Row's wall.
_sb0, _sb1 = 19.0, BAND["strand"][1] - WALL_D
enclosure("ropewalk", "ropewalk", -49.0, _sb1 - 2.4, NET_WYND_X - 2.5, _sb1, "strand",
          "Chidi Okoro's ropewalk, under Low Row's wall behind the smokehouses: 29 m, the longest straight, sheltered run in town, which a line-maker needs",
          [], [("ropewalk", (-49.0 + 0.8, _sb1 - 1.2), {"to": (NET_WYND_X - 3.3, _sb1 - 1.2)})], ground="earth", age=0.6, repair=0.6, who="Chidi Okoro")
enclosure("net_green", "drying_green", -75.0, _sb0, LADDER_WYND_X - 2.4, _sb1 - 0.3, "strand",
          "the net green behind the lofts: the six lofts' nets dry here out of the spray, on poles; a boat laid up against the wall",
          [("w", 1.0, "dry"), (((-75.0, _sb0 + 0.2), (LADDER_WYND_X - 2.4, _sb0 + 0.2)), 1.0, "dry", [(9.0, 12.0)])],
          [("nets", (-70.6 + 6.2 * j, _sb0 + 3.6 + (2.6 if j % 2 else 0.0)), {"len": 4.6}) for j in range(3)] + [("boat", (-60.0, _sb1 - 2.0), {"turn": 4}), ("creels", (-71.5, _sb1 - 1.6)), ("barrels", (-56.2, _sb0 + 1.8))],
          ground="earth", use="nets")
enclosure("smoke_yard", "yard", -49.0, 17.0, -38.0, _sb1 - 3.2, "strand",
          "the smokehouses' yard: peat and driftwood for the smoke, fish barrels waiting on the Marver's drops (Petra Tarn)",
          [("n", 1.4, "dry", [(4.0, 5.4)]), ("e", 1.4, "dry")], [("peat", (-46.5, 24.0), {"n": 3}), ("barrels", (-41.0, 19.2)), ("barrels", (-43.6, 19.0)), ("timber", (-41.6, 25.0), {"len": 3.0}), ("creels", (-47.4, 19.0))],
          ground="earth", lot="smokehouse_1", family="strand", state="kept")
enclosure("tally_court", "yard", -14.0, 23.0, 14.0, _sb1 - 0.3, "strand",
          "the Counting House's back court: the ship days' bonded yard, its wall still coped; the porter's cart and the Store's empties stand in it now",
          [("w", 2.2, "coped", [(2.2, 3.6)], {"gate": True}), ("e", 2.2, "coped")],
          [("barrels", (-8.0, 29.0)), ("barrels", (-5.4, 29.4)), ("handcart", (4.0, 27.0)), ("blocks", (10.0, 29.6)), ("weeds", (0.0, 25.0), {"r": 1.6}), ("butt", (12.6, 24.2))],
          ground="quay_flags", lot="counting_house", family="other", state="kept")
enclosure("store_yard", "yard", 48.0, 21.0, 60.0, _sb1 - 0.3, "strand",
          "the Store's yard: the town's peat, counted in by the tally keeper, and the barrels going back to the smokehouses",
          [("w", 1.8, "coped", [(3.0, 4.4)], {"gate": True}), ("e", 1.8, "coped")], [("peat", (51.0, 29.4), {"n": 3}), ("peat", (56.0, 29.4), {"n": 3}), ("barrels", (57.4, 23.4)), ("timber", (52.0, 24.0), {"len": 3.4})],
          ground="earth", lot="store", family="other", state="kept")
# The old quarry's bench (the upper terrace east of the Ladder): the basalt of every wall in town
# came off this face (SMALL_CITY §1, materials). Cut blocks never carried down, and the waste.
for i, x in enumerate((-12.0, 14.0, 27.0, 47.0)):
    enclosure(f"quarry_{i + 1}", "quarry_bench", x - 4.5, 126.2, x + 4.5, BAND["upper"][1] - WALL_D, "upper", "the old quarry's bench below the Crown: cut stone never carried down, and waste under the face",
              [], [("blocks", (x - 1.6, 131.0)), ("blocks", (x + 2.0, 129.6), {"turn": 30}), ("rubble", (x + 0.8, 131.9), {"r": 1.0}), ("weeds", (x - 2.6, 128.6), {"r": 1.2})], ground="earth", age=1.0, repair=0.2)
# The graveyard's wall (the Crown): dry stone, a gate toward the Crown path.
_g = next(l for l in lots if l["id"] == "graveyard")
enclosure("graveyard_wall", "graveyard_wall", _g["at"][0] - _g["size"][0] / 2, _g["at"][1] - _g["size"][1] / 2, _g["at"][0] + _g["size"][0] / 2, _g["at"][1] + _g["size"][1] / 2, "crown",
          "the graveyard's wall: dry stone, breast high, against the wind and the sheep the island no longer has; the gate faces the town",
          [("s", 1.2, "dry", [(16.0, 17.4)], {"gate": True}), ("w", 1.2, "dry"), ("n", 1.2, "dry"), ("e", 1.2, "dry")], [], age=1.0, repair=0.5, lot="graveyard")
# Benches on the Rows' sills, where the sun is, and washing across the wynds (SMALL_CITY §6).
for row, x, who in (("low", 30.0, "the oven court's bench on the sill: the harbour below"), ("low", 0.0, "Ingrid Morrow's sill: the bench she mends on in the morning sun"),
                    ("mid", 16.0, "a bench before the tofts"), ("high", 20.0, "the Kiln's bench before the walled gardens: the whole harbour"), ("high", 52.0, "a bench before the Pontils' and the Hollins' doors")):
    enclosure(f"sill_{row}_{int(x)}".replace("-", "m"), "sill", x - 1.6, BAND[row][0] + 0.25, x + 1.6, BAND[row][0] + 1.5, row, who, [], [("bench", (x, BAND[row][0] + 0.85), {"len": 2.4, "back": "s"})], age=0.6, repair=0.5)
for wid, x, row, why in (("net_low", NET_WYND_X, "low", "the Marls' and the Tarns' washing across the Net Wynd, from Low Row 10's gable to the Ladder's wall"),
                         ("tally_mid", TALLY_X[2], "mid", "washing across the Tally Wynd between the Sarros' gable and the first toft")):
    y = fy[row] + 3.0
    enclosure(f"wynd_washing_{wid}", "wynd_washing", x - 2.1, y - 0.4, x + 2.1, y + 0.4, row, why, [], [("washing", (x - 1.9, y), {"to": (x + 1.9, y), "cloth": "colours", "high": True})], age=0.5, repair=0.5)

# Pass 2's dressing (SMALL_CITY §6 "Street dressing": Cinder Row, the Rows, the Ladder; "Nature").
# Every place below is worked out from the lots and streets above, so it follows them if they
# move; every thing has the cause that puts it there.


def by_id(i):
    return next(l for l in lots if l["id"] == i)


def spot_at(l, name):
    """A lot's named spot in the plan's frame (spots are along the front, then out from the middle)."""
    sp = next(q for q in l["spots"] if q["name"] == name)["at"]
    b = math.radians(FACING_DEG[l["facing"]] if isinstance(l["facing"], str) else l["facing"])
    fx, fy = math.sin(b), math.cos(b)  # the front's direction; a spot's first number runs to its right hand
    return (l["at"][0] + fx * sp[1] + fy * sp[0], l["at"][1] + fy * sp[1] - fx * sp[0])


def dress(id, kind, at, size, facing, height, cause, floor, **extra):
    return fixture(id, kind, at, size, facing, floor, height, cause, age=0.6, repair=0.5, dressing=True, **extra)


# Cinder Row: the Cone yard.
_cone, _yard, _pot, _ash = by_id("cone"), by_id("cone_yard"), by_id("pot_house"), by_id("ash_house")
_bx, _by = spot_at(_cone, "Halvard's bench at the mouth")
dress("cone_bench_1", "cone_bench", (_bx, _by - 0.4), (1.9, 0.7), "north", 0.95, "Halvard Dunmore's bench at the Cone's mouth, where the heat reaches (the plan's spot)", STRAND_H)
_hx, _hy = spot_at(_yard, "the cullet heaps")
for i, col in enumerate(("green", "amber", "aqua", "smoke")):
    dress(f"cullet_heap_{col}", "cullet_heap", (_hx - 3.6 + 2.4 * i, _hy), (2.2, 1.9), "south", (0.75, 0.3, 0.9, 0.6)[i],
          f"the yard's heap of {col} cullet (the plan's spot): " + ("nearly out, amber is the rarest" if col == "amber" else "the most there is, every window's glass" if col == "aqua" else "sorted, waiting for the melt"),
          STRAND_H, colour=col, shovel=col == "aqua")
_tx, _ty = spot_at(_yard, "the trough")
dress("trough_1", "trough", (_tx, _ty), (2.4, 0.8), "south", 0.63, "the Cone yard's water trough (the plan's spot)", STRAND_H)
dress("blowpipe_rack_1", "blowpipe_rack", (_cone["at"][0] + 3.1, _cone["at"][1] - _cone["size"][1] / 2 - 1.9), (2.2, 0.6), "south", 1.5,
      "the blowpipe rack between the front and the east mouths, a pipe's length from the heat", STRAND_H)
dress("crucible_stack_1", "crucible_stack", (_pot["at"][0] + 3.0, _pot["at"][1] - _pot["size"][1] / 2 - 0.75), (1.7, 1.1), "south", 1.4, "fired pots stacked before the pot house, waiting for the Cone", STRAND_H)
dress("crucible_stack_2", "crucible_stack", (_cone["at"][0] - _cone["size"][0] / 2 + 1.2, _yard["at"][1] + _yard["size"][1] / 2 - 0.8), (1.7, 1.1), 150, 1.4, "pots brought to the Cone's pot room door for the next setting", STRAND_H)
dress("ash_sacks_1", "ash_sacks", (_ash["at"][0] + 3.6, _ash["at"][1] - _ash["size"][1] / 2 - 0.7), (1.7, 1.1), "south", 0.7, "kelp ash come from the kilns, not yet carried into the ash house", STRAND_H)
dress("ash_sacks_2", "ash_sacks", (_yard["at"][0] + 11.0, _yard["at"][1] + 4.5), (1.7, 1.1), 200, 0.7, "ash for the day's batch, set down in the yard by the mixing floor", STRAND_H)
dress("handcart_1", "handcart", (_hx - 6.4, _hy - 1.2), (1.3, 2.6), 115, 0.95, "the yard's handcart by the heaps: cullet comes down from the Rows on it", STRAND_H)

# The Rows' backs and the Ladder's beds are layout pass 1's enclosures above (yards, back plots,
# tofts, the Ladder's corners: each with its privy, lean-to, butt, washing, hens or canes, and
# its cause). Pass 2's own fixtures for them (a lean-to, a privy and a rain butt by house, washing,
# hens, canes) were built before that pass moved the houses and walled the yards, and are gone:
# one yard cannot hold both.

# The Hanger. Its trees are the plan's `tree` resources: the engine's, which the client draws with
# its own models. The kit builds the six wind-bent forms (`hanger_tree_1..6`) and stands them
# where no resource tree is: round the woodward's yard (the plan plants nothing within 14 m of
# the Hanger cottage), on the yard's level, the one ground there whose height the plan knows (a
# fixture stands at the `floor_m` it is given, and the wood's own slope is the land's). Three
# stumps of the old wood stand with them (SMALL_CITY §1: cut to stumps in the lean years, the
# replanting among them). The rest of the wood takes these forms when the client draws Cullet's
# `tree` resources from `envs/cullet/hanger_tree/`.
_hc = by_id("hanger_cottage")
_hx, _hy = _hc["at"]
for i, (dx, dy) in enumerate(((-8.5, 4.0), (8.8, 4.3), (-8.0, -8.5), (8.5, -8.7), (0.5, -9.5), (-9.2, -2.2))):
    fixture(f"hanger_tree_{i + 1}", "hanger_tree", (_hx + dx, _hy + dy), (9.0, 9.0), "south", H["hanger"], 8.0,
            f"the Hanger's wind-bent tree, form {i + 1} of six, leaning north-east: at the edge of the woodward's yard", age=0.4, repair=0.5, form=i + 1, natural=True)
for i, (dx, dy) in enumerate(((-4.5, -7.0), (5.0, 5.0), (9.5, -2.5))):
    fixture(f"stump_{i + 1}", "stump", (_hx + dx, _hy + dy), (1.1, 1.1), "south", H["hanger"], 0.5 + 0.1 * i, "a stump of the old wood in the woodward's yard, cut for fuel in the lean years",
            age=1.0, repair=0.0, dressing=True, natural=True)

# What the engine stands in a town, in Cullet's look: the client draws a structure of these kinds
# with the model of its settlement's environment (`envs/cullet/<kind>/*.glb`), origin on the
# ground at the structure's place, front (-Y) to the street. Not placed by the plan: the engine
# places them (a `sign` 1.5 m east of each named building's door point, 0.5 m beyond its lot).
structure_models = [
    {"id": "sign", "kind": "sign", "model": "cullet/sign/sign.glb", "size": [0.5, 1.2], "height_m": 2.75, "facing": "south", "at": [0, 0], "seed": seed_of("sign"),
     "cause": "the engine's sign at a named building's door: a painted board on an iron bracket and a spar at the kerb, its back to the building",
     "wear": wear((0, 5), H["strand"], "south", 0.6, 0.5, 0.0)},
    {"id": "storage", "kind": "storage", "model": "cullet/storage/storage.glb", "size": [3.2, 2.9], "height_m": 1.35, "facing": "south", "at": [0, 0], "seed": seed_of("storage"),
     "cause": "the engine's common store in the Counting House yard: a covered handcart, crates and barrels, in tarred timber",
     "wear": wear((30, 17), H["strand"], "south", 0.6, 0.5, 0.0)},
    {"id": "campfire", "kind": "campfire", "model": "cullet/campfire/campfire.glb", "size": [1.0, 1.0], "height_m": 0.7, "facing": "south", "at": [0, 0], "seed": seed_of("campfire"),
     "cause": "the engine's fire in the yard: an iron fire basket on three stones, peat in it",
     "wear": wear((30, 17), H["strand"], "south", 0.6, 0.5, 0.0)},
]
# The fires and lamps the plan places (`structures` above, rates-2), in Cullet's look.
for _id, _size, _h, _cause in (
        ("hearth", [1.3, 0.8], 0.9, "a household's hearth, which the engine stands at its door: a basalt fire box with a pot on it, peat beside it"),
        ("lamp", [0.6, 0.6], 3.2, "one of the plan's seven lamps: the quay lamp, iron on a basalt block, odd panes"),
        ("furnace", [2.8, 1.2], 1.5, "the Cone's furnace, which the engine stands at the front mouth: the stoker's rake and shovel in their stand, a barrow of peat"),
        ("oven", [1.5, 0.8], 1.0, "the Batch's oven, which the engine stands at the oven mouth: the cooling trestle with the morning's loaves, the ember pan"),
        ("smokehouse", [1.6, 0.8], 1.7, "a smokehouse's fire, which the engine stands at its door: the smoulder pot and a rack of split fish")):
    structure_models.append({"id": _id, "kind": _id, "model": f"cullet/{_id}/{_id}.glb", "size": _size, "height_m": _h, "facing": "south", "at": [0, 0], "seed": seed_of(_id),
                             "cause": _cause, "wear": wear((30, 17), H["strand"], "south", 0.6, 0.5, 0.0)})

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
# The ground (docs/CULLET_KIT.md "The ground"). Two things, both for the game client only:
# - GROUND_MAP, written into `living/game/assets/envs/cullet.json` as the keys of its `ground`
#   object that hold a colon: which painted layer (living/tools/textures/paint.py) and which base
#   colour the terrain takes for a street's `surface`, an area below, a relief stamp's `ground`,
#   a terrain class of the rules or a region, most specific first;
# - `grounds`, the areas: polygons of the plan with a surface and a cause, later ones on top.
#   The kit's generator writes them in land metres to `envs/cullet/ground.json`. They are kept
#   out of the seed, as the fixtures are: the rules know nothing of them.
# Every colour is a palette colour of SMALL_CITY §1 or a mix of two, as the models' are.

PAL = {
    "basalt": (0.24, 0.25, 0.28), "pale basalt": (0.36, 0.37, 0.39), "tar": (0.13, 0.12, 0.12), "sooted brick": (0.33, 0.20, 0.17),
    "kelp": (0.30, 0.28, 0.12), "sand": (0.86, 0.82, 0.70), "peat": (0.20, 0.15, 0.11), "moor grass": (0.52, 0.50, 0.28), "heather": (0.50, 0.34, 0.48),
    "driftwood": (0.52, 0.50, 0.46),
}


def rgb(a, b=None, t=0.0):
    """A palette colour, or a mix of two (t of the second), as sRGB 0-255."""
    c = PAL[a] if b is None else tuple(x + (y - x) * t for x, y in zip(PAL[a], PAL[b]))
    return [round(v * 255) for v in c]


def ground(layer, colour, tint=None, why=""):
    g = {"layer": layer, "colour": colour}
    if tint is not None:
        g["tint"] = tint
    g["note"] = why
    return g


FLAGS = ground("quay_flags", rgb("pale basalt", "basalt", 0.3), rgb("basalt"), "the ship-day quay's flags: pale basalt, wet")
SETTS = ground("slate_setts", rgb("pale basalt"), None, "basalt setts, polished by feet")
CINDERS = ground("cinders", rgb("tar", "pale basalt", 0.3), rgb("sooted brick"), "furnace cinders and ash, 83 years of them: charcoal, rusty where brick has crumbled into it")
WET_SAND = ground("wet_sand", rgb("sand", "pale basalt", 0.38), rgb("sand"), "sand the tide has just left")
EARTH = ground("dirt", rgb("peat", "driftwood", 0.5), rgb("moor grass"), "trodden earth")
ROCK = ground("rock", rgb("basalt"), None, "the island's own basalt")
GROUND_MAP = {
    # A street's surface (the plan's `streets[].surface`).
    "street:setts": SETTS,
    "street:quay_flags": FLAGS,
    "street:flags": ground("quay_flags", rgb("pale basalt", "basalt", 0.15), rgb("basalt"), "the mole's flags"),
    "street:cinders": CINDERS,
    "street:earth": EARTH,
    "street:sand": WET_SAND,
    # An area (`grounds` below).
    "area:quay_flags": FLAGS,
    "area:setts": SETTS,
    "area:cinders": CINDERS,
    "area:earth": EARTH,
    "area:worked_soil": ground("worked_soil", rgb("peat", "driftwood", 0.28), rgb("kelp"), "dug soil fed with kelp"),
    "area:peat": ground("peat", rgb("peat", "driftwood", 0.1), None, "a cutting's bare peat"),
    "area:kelp_shingle": ground("kelp_shingle", rgb("kelp", "pale basalt", 0.3), rgb("kelp"), "the wrack line"),
    "area:white_sand": ground("sand", rgb("sand"), None, "the Sand Spit's white sand, the glass's"),
    # A relief stamp's ground (the rules allow grass, sand, dirt, rock and forest there).
    "stamp:sand": ground("wet_sand", rgb("sand", "pale basalt", 0.38), rgb("sand", "kelp", 0.5), "the Wrack Strand: wet sand, kelp in it"),
    # The rules' terrain classes. Grass and Water are left to the regions and to today's rules.
    "class:Road": FLAGS,
    "class:Sand": WET_SAND,
    "class:Dirt": ground("peat", rgb("peat", "driftwood", 0.14), None, "bare peat where the turf is broken"),
    "class:Rock": ground("rock", rgb("basalt", "pale basalt", 0.3), None, "basalt outcrops"),
    "class:Drop": ROCK,
    "class:Wall": ROCK,
    "class:Low": ROCK,
    "class:Forest": ground("forest_floor", rgb("moor grass", "peat", 0.55), rgb("peat"), "the Hanger's floor: needles and peat"),
    # Regions (for Grass tiles).
    "region:meadow": ground("thin_turf", rgb("moor grass", "basalt", 0.5), rgb("basalt"), "the island's thin turf, the rock showing through: moor grass greyed by the stone under it (at 0.12 it read mustard beside the setts in the game, at 0.32 ochre on the Crown)"),
    "region:highland": ground("heather", rgb("moor grass", "peat", 0.4), rgb("heather"), "the Moss: heather and moor grass over peat"),
    "region:beach": ground("kelp_shingle", rgb("kelp", "pale basalt", 0.42), rgb("kelp"), "shingle above the tide, wrack thrown on it"),
    "region:forest": ground("thin_turf", rgb("moor grass", "peat", 0.35), rgb("peat"), "under the Hanger's trees"),
}

grounds = []


def area(id, surface, poly, cause):
    assert f"area:{surface}" in GROUND_MAP, surface
    grounds.append({"id": id, "surface": surface, "area": [[r2(q[0]), r2(q[1])] for q in poly], "cause": cause})


_quay_west = [[-125, 0], [HERON_STAGE[0], 0], [HERON_STAGE[0], HERON_STAGE[2]], [HERON_STAGE[1], HERON_STAGE[2]], [HERON_STAGE[1], 0], *FISH_STEPS, [80, 0], [80, 32], [-125, 32]]
area("the quay", "quay_flags", _quay_west, "the ship-day quay: flags from the edge to the wall behind the strand's buildings")
area("the slip and the dock yard", "setts", rect(-125, 0, -99, 32), "where hulls are hauled: setts for the grip, not flags")
area("Cinder Row", "cinders", rect(80, 0, 175, 62), "the Cone's cinders, spread over the whole yard since the ship days")
area("the mole", "quay_flags", LEVELS[1]["area"], "the ship-day mole")
for row in ("low", "mid", "high"):
    b0 = BAND[row][0]
    area(f"{ROW_NAME[row]}'s sill", "setts", rect(NET_WYND_X, b0, ROW_END[row], ROW_Y[row] - 2.5), f"{ROW_NAME[row]}: the sill between the street and the parapet over the drop")
    area(f"{ROW_NAME[row]}'s kerb", "setts", rect(NET_WYND_X, ROW_Y[row] + 2.5, ROW_END[row], ROW_Y[row] + FRONT_GAP + 0.3), f"{ROW_NAME[row]}: the strip before the doors")
# Layout pass 1's enclosures say what lies inside their walls (`ground`: a court's setts, a yard's
# trodden earth, a plot's dug soil, the oven court's flags).
for f in [f for f in fixtures if f.get("ground")]:
    (x, y), (w_, d_) = f["at"], f["size"]
    area(f["id"], f["ground"], rect(x - w_ / 2, y - d_ / 2, x + w_ / 2, y + d_ / 2), f"inside its walls: {f['cause']}")
for l in [l for l in lots if l["id"].startswith("root_plot_")]:
    (x, y), (w_, d_) = l["at"], l["size"]
    area(l["name"], "worked_soil", rect(x - w_ / 2 + 0.45, y - d_ / 2 + 0.45, x + w_ / 2 - 0.45, y + d_ / 2 - 0.45), f"{l['name']}: dug and fed with kelp, inside its wall")
area("the Sand Spit", "white_sand", STAMPS[8]["area"], "white sand for the glass")
assert STAMPS[8]["id"] == "the Sand Spit" and STAMPS[7]["id"] == "the Wrack Strand"
_ws = STAMPS[7]["area"][:4]
area("the wrack line", "kelp_shingle", _ws + [[q[0] + 3, q[1] + 9] for q in reversed(_ws)], "the tide's wrack line along the Wrack Strand: kelp to gather")
for r in [r for r in resources if r["kind"] == "peat_bank"]:
    x, y = r["at"]
    area(f"a peat cutting at {x:g}, {y:g}", "peat", rect(x - 6, y - 2.2, x + 6, y + 2.2), "a bank cut to bare peat: the Moss's fuel")

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
        "fixtures": fixtures,
        "grounds": grounds,
        "structure_models": structure_models,
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
        "fixtures": {k: len([f for f in fixtures if f["kind"] == k]) for k in sorted({f["kind"] for f in fixtures})},
        "by_district": by,
    }


def seed(p):
    rough = {k: v for k, v in p.items() if k not in ("fixtures", "grounds", "structure_models", "features", "terraces", "count", "household_stores")}
    ways = json.loads(WAYS.read_text())
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
        "ways": {k: ways[k] for k in ("top", "common", "occupations")},
        "town_life": ways["town_life"],
    }


def dump(v):
    return json.dumps(v, indent=1, ensure_ascii=False) + "\n"


def env_text():
    """Cullet's environment file with its `ground` map set from GROUND_MAP: the keys of `ground`
    that hold a colon are this script's, everything else in the file is kept as it is."""
    env = json.loads(ENV_OUT.read_text())
    g = {k: v for k, v in env["ground"].items() if ":" not in k}
    # Only what the client reads (layer, colour, tint): each entry's `note` stays in this script.
    g.update({k: {kk: vv for kk, vv in v.items() if kk != "note"} for k, v in GROUND_MAP.items()})
    env["ground"] = g
    return json.dumps(env, indent=1, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    p = plan()
    s = seed(p)
    # The residents and their homes are `author_world.py cullet --compile-only`'s (from the cast
    # and the drafted sheets, merged into this seed): keep them when rewriting the rest.
    if SEED_OUT.exists():
        old = {t["name"]: t for t in json.loads(SEED_OUT.read_text()).get("towns", [])}
        for t in s["towns"]:
            for k in ("residents", "homes"):
                if k in old.get(t["name"], {}):
                    t[k] = old[t["name"]][k]
    out = {PLAN_OUT: dump(p), SEED_OUT: dump(s), ENV_OUT: env_text()}
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
