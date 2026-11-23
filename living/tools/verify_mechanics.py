#!/usr/bin/env python3
"""Deterministic end-to-end checks of checkpoint-2 mechanics on a benchmark database.

Two scripted characters (installed behavior graphs, no LLM) exercise writing and reading a
tablet that teaches a technique, crafting with the learned technique, an atomic trade,
planting, teaching and consensual conception, then the same kind of interactions as
deliberate acts decided outside the graph (`mind_act`: a gift, conception chosen by both, a
failure reported back), and force (a threat, a blow that kills, blows on the yielded as news, a
wolf that does not dare). Each check reads the authority's tables.

Usage: living/tools/verify_mechanics.py [--db living-verify] [--wasm NAME] [--out FILE]
Publishes the database fresh (deletes its data).
"""
import argparse
import json
import re
import os
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import world_delete  # noqa: E402  (pause a world before deleting it)

ROOT = Path(__file__).resolve().parents[2]
STDB = os.environ.get("LIVING_STDB", str(ROOT / "living/tools/stdb"))


def stdb(*args):
    r = subprocess.run([STDB, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()[-300:]}")
    return r.stdout


def rows(db, q):
    out = stdb("sql", "-s", "local", db, q)
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    res = []
    for l in lines[1:]:
        r = {}
        for h, v in zip(head, [v.strip() for v in l.split("|")]):
            r[h] = v.strip('"')
        res.append(r)
    return res


def call(db, reducer, *args):
    """Numbers (or numeric strings) go raw; other strings are JSON-encoded (the CLI parses JSON)."""
    enc = []
    for a in args:
        if isinstance(a, (int, float)) or (isinstance(a, str) and a.isdigit()):
            enc.append(str(a))
        else:
            enc.append(json.dumps(a))
    stdb("call", "-s", "local", db, reducer, *enc)


def wait_for(pred, timeout=40, every=1.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(every)
    return None


# Terrain codes (living_rules::map::Terrain): grass and dirt take a planting, forest a clearing;
# these are walkable.
GRASS, FOREST, DIRT = 0, 1, 5
WALKABLE = {0, 1, 3, 5, 6}
PLANT_REACH = 20.0


def ground_spot(db, ax, ay, kinds, reach=PLANT_REACH):
    """The centre of the nearest tile of a terrain in `kinds` within `reach` of (ax, ay) whose
    straight line from there crosses only walkable tiles, or None. Reads the `terrain_chunk` rows
    around."""
    x0, y0, x1, y1 = (int(max(0.0, v)) for v in (ax - reach, ay - reach, ax + reach, ay + reach))
    ids = sorted({((cy << 16) | cx) for cx in range(x0 // 16, x1 // 16 + 1) for cy in range(y0 // 16, y1 // 16 + 1)})
    chunks = {int(r["id"]): bytes.fromhex(r["tiles"].removeprefix("0x"))
              for r in rows(db, "SELECT id, tiles FROM terrain_chunk WHERE " + " OR ".join(f"id = {i}" for i in ids))}

    def tile(x, y):
        c = chunks.get(((y // 16) << 16) | (x // 16))
        return c[(y % 16) * 16 + x % 16] if c and x >= 0 and y >= 0 else None

    def straight(tx, ty):
        n = max(1, int(((tx - ax) ** 2 + (ty - ay) ** 2) ** 0.5 / 0.1))
        return all(tile(int(ax + (tx - ax) * k / n), int(ay + (ty - ay) * k / n)) in WALKABLE for k in range(n + 1))

    near = sorted(((x + 0.5 - ax) ** 2 + (y + 0.5 - ay) ** 2, x + 0.5, y + 0.5)
                  for x in range(x0, x1 + 1) for y in range(y0, y1 + 1) if tile(x, y) in kinds)
    return next(((x, y) for d, x, y in near if d <= reach ** 2 and straight(x, y)), None)


def plant_spot(db, ax, ay):
    """The nearest grass or dirt tile A can walk to in a straight line (`ground_spot`)."""
    return ground_spot(db, ax, ay, (GRASS, DIRT))


def terrain_under(db, who):
    """The terrain code of the tile under `who`'s body now: its row is a segment (`x`, `y` at
    `t_ms`, moving at `vx`, `vy` until `next_ms`), so a moving body is past its `x`, `y`. Also
    whether it is still moving."""
    b = rows(db, f"SELECT x, y, t_ms, vx, vy, next_ms FROM body WHERE id = {who}")[0]
    t = max(0, min(int(time.time() * 1000), int(b["next_ms"])) - int(b["t_ms"])) / 1000.0
    x, y = float(b["x"]) + float(b["vx"]) * t, float(b["y"]) + float(b["vy"]) * t
    cid = ((int(y) // 16) << 16) | (int(x) // 16)
    c = rows(db, f"SELECT id, tiles FROM terrain_chunk WHERE id = {cid}")  # two columns: `rows` reads a table with a separator
    code = bytes.fromhex(c[0]["tiles"].removeprefix("0x"))[(int(y) % 16) * 16 + int(x) % 16] if c else None
    return code, (float(b["vx"]), float(b["vy"])) != (0.0, 0.0)


def clear_ready(db, D):
    """Stands D on forest for the clearing check, and says how (walked or placed), or why not.
    Returns whether D stands still on a forest tile."""
    seq = lambda *steps: json.dumps({"seq": list(steps) + [{"wait": 120}]})
    # Clearing needs forest underfoot when it starts (`clear_check`). D walks to the nearest forest
    # tile it can reach in a straight line, or is placed on one by the nearest tree, and the clear
    # is installed only once D stands still on forest. Until 2026-11-22 D went to the nearest tree by
    # straight-line distance, then `goto {nearest: forest}`, then `clear`, in one sequence
    # (features/mechanics.md, "Clearing from the forest's edge"): a goto reports its arrival when
    # the final approach begins (`motion::FLAG_EARLY`), so the clear could start on the grass beside
    # the forest ("there is no forest to clear where you stand", 3 of 50 probe runs, each retried
    # and cleared; gate-1122224047-489894-a-mechanics did not within the 150 s), and the nearest
    # tree could lie across water ("no path there" on every retry, 2 of 50).
    body = rows(db, f"SELECT x, y FROM body WHERE id = {D}")[0]
    dx, dy = float(body["x"]), float(body["y"])
    spot = ground_spot(db, dx, dy, (FOREST,))
    if spot is None:
        trees = [(float(r["x"]), float(r["y"])) for r in rows(db, "SELECT x, y FROM resource_node WHERE kind = 'tree'")]
        near = min(trees, key=lambda p: (p[0] - dx) ** 2 + (p[1] - dy) ** 2)
        at = ground_spot(db, *near, (FOREST,)) or near
        print(f"  clearing: no forest in a straight walk within {PLANT_REACH:.0f} m of D at ({dx:.1f}, {dy:.1f}); D placed at ({at[0]:.1f}, {at[1]:.1f}) by the tree at ({near[0]:.1f}, {near[1]:.1f})")
        call(db, "place_at", str(D), at[0], at[1])
    else:
        print(f"  clearing: D at ({dx:.1f}, {dy:.1f}) walks {((spot[0] - dx) ** 2 + (spot[1] - dy) ** 2) ** 0.5:.1f} m to forest at ({spot[0]:.1f}, {spot[1]:.1f})")
        call(db, "set_behavior", str(D), seq({"do": {"skill": "goto", "target": {"at": [spot[0], spot[1]]}}}))
    on_forest = wait_for(lambda: (lambda u: u[0] == FOREST and not u[1])(terrain_under(db, D)), timeout=60, every=0.5)
    if not on_forest:
        b = rows(db, f"SELECT x, y FROM body WHERE id = {D}")[0]
        print(f"  clearing: D not standing on forest after 60 s: at ({float(b['x']):.1f}, {float(b['y']):.1f}), under it {terrain_under(db, D)}")
    return bool(on_forest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="living-verify")
    ap.add_argument("--wasm", default="living_authority.wasm", help="module file in the server's /wasm mount")
    ap.add_argument("--out")
    ap.add_argument("--gate-world", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    db = a.db
    if a.gate_world:
        if not re.fullmatch(r"verify-gate-[a-z0-9-]+-mechanics", db):
            ap.error("--gate-world requires a launched mechanics gate database")
    else:
        stdb("publish", "-s", "local", "-b", f"/wasm/{a.wasm}", db, "--delete-data", "-y")
        # Staged genesis: the world is made by scheduled steps after the publish (genesis_wait.py).
        import genesis_wait
        genesis_wait.wait_ready_cli(stdb, db)
        time.sleep(3)
    stdb("call", "-s", "local", db, "spawn_crowd", "10", "true")
    time.sleep(1.5)
    walkers = sorted(int(r["id"]) for r in rows(db, "SELECT id, name FROM character") if r["name"].startswith("Walker"))
    A, B, C, D, E = walkers[:5]
    name_a = f"Walker1"
    # Spawned walkers forage on their own graphs: stop A and B before B is placed beside A, or B
    # walks off during the setup calls below (26 m once, 2026-11-21) and every give fails.
    idle = json.dumps({"wait": 120})
    call(db, "set_behavior", str(A), idle)
    call(db, "set_behavior", str(B), idle)
    call(db, "place_near", str(B), str(A))

    def gap(i, j):
        bi, bj = (rows(db, f"SELECT x, y FROM body WHERE id = {k}")[0] for k in (i, j))
        return ((float(bi["x"]) - float(bj["x"])) ** 2 + (float(bi["y"]) - float(bj["y"])) ** 2) ** 0.5

    print(f"  setup: A-B {gap(A, B):.2f} m after place_near")
    for t in ["writing", "spear", "planting"]:
        call(db, "grant_know_how", str(A), t)
    call(db, "grant_know_how", str(B), "writing")
    call(db, "grant_items", str(A), "wood", "6")
    call(db, "grant_items", str(A), "berries", "6")
    call(db, "grant_items", str(B), "stone", "3")
    call(db, "grant_items", str(B), "wood", "4")
    results = {}

    def seq(*steps):
        return json.dumps({"seq": list(steps) + [{"wait": 120}]})

    # 1. Write a tablet describing spear-making and hand it over.
    call(db, "set_behavior", str(B), idle)
    if gap(A, B) > 2.0:
        print(f"  tablet: B was {gap(A, B):.2f} m from A; placed beside A again")
        call(db, "place_near", str(B), str(A))
    call(db, "set_behavior", str(A), seq(
        {"do": {"skill": "write", "item": "tablet", "text": "Two wood and a stone make a spear. Bind them tight.", "topic": "spear"}},
        {"do": {"skill": "give", "target": {"id": B}, "item": "tablet", "qty": 1}},
    ))
    got = wait_for(lambda: [r for r in rows(db, "SELECT * FROM artifact") if r["kind"] == "tablet" and int(r["holder"]) == B])
    results["tablet written and given"] = bool(got)
    if not got:
        def at(i):
            b = rows(db, f"SELECT x, y FROM body WHERE id = {i}")[0]
            return round(float(b["x"]), 2), round(float(b["y"]), 2)
        told = rows(db, f"SELECT kind, text FROM experience WHERE observer = {A}")
        print("  tablet: A at", at(A), "B at", at(B), "A feedback:", [r["text"][:160] for r in told if "give" in r["text"] or "tablet" in r["text"]][-6:])
    # 2. Read it (learning spear) and craft a spear with what was learned.
    call(db, "set_behavior", str(B), seq({"do": {"skill": "read"}}, {"do": {"skill": "craft", "item": "spear"}}))
    learned = wait_for(lambda: [r for r in rows(db, f"SELECT technique, source FROM know_how WHERE actor = {B}") if r["technique"] == "spear"])
    results["reading taught spear"] = bool(learned) and "tablet" in learned[0]["source"]
    crafted = wait_for(lambda: [r for r in rows(db, f"SELECT item, qty FROM inventory WHERE owner = {B}") if r["item"] == "spear"])
    results["learned technique used (spear crafted)"] = bool(crafted)
    # 3. Atomic trade: A offers 2 wood for 1 stone; B accepts.
    call(db, "set_behavior", str(A), seq({"do": {"skill": "offer", "target": {"id": B}, "item": "wood", "qty": 2, "want": "stone", "want_qty": 1}}))
    time.sleep(2.5)
    call(db, "set_behavior", str(B), seq({"do": {"skill": "accept", "target": {"id": A}}}))
    traded = wait_for(lambda: [r for r in rows(db, "SELECT kind, text FROM chronicle") if r["kind"] == "trade"])
    results["atomic trade"] = bool(traded)
    # 4. Teaching: A teaches B planting.
    call(db, "set_behavior", str(A), seq({"do": {"skill": "teach", "target": {"id": B}, "item": "planting"}}))
    taught = wait_for(lambda: [r for r in rows(db, f"SELECT technique, source FROM know_how WHERE actor = {B}") if r["technique"] == "planting"], timeout=40)
    results["teaching"] = bool(taught) and taught[0]["source"].startswith("taught by")
    # 5. Planting a berry bush (off-winter: a fresh world starts in spring).
    before = {r["id"] for r in rows(db, "SELECT id, kind FROM resource_node")}
    # Planting needs grass or dirt underfoot (`plant_check`). A walks to the nearest such tile it can
    # reach in a straight line over walkable ground. The nearest berry bush, used until 2026-11-22,
    # could lie across a river: A then walked to a far crossing, 220 m in 90 s and still on its way
    # (gate-1122184906-8bd028-a-mechanics; features/mechanics.md).
    body = rows(db, f"SELECT x, y FROM body WHERE id = {A}")[0]
    ax, ay = float(body["x"]), float(body["y"])
    spot = plant_spot(db, ax, ay)
    if spot is None:
        bushes = [(float(r["x"]), float(r["y"])) for r in rows(db, "SELECT x, y FROM resource_node WHERE kind = 'berry_bush'")]
        near = min(bushes, key=lambda p: (p[0] - ax) ** 2 + (p[1] - ay) ** 2)
        at = plant_spot(db, *near) or near
        print(f"  planting: no grass or dirt in a straight walk within {PLANT_REACH:.0f} m of A at ({ax:.1f}, {ay:.1f}); A placed at ({at[0]:.1f}, {at[1]:.1f}) by the bush at ({near[0]:.1f}, {near[1]:.1f})")
        call(db, "place_at", str(A), at[0], at[1])
        b = rows(db, f"SELECT x, y FROM body WHERE id = {A}")[0]
        spot = (float(b["x"]), float(b["y"]))
    else:
        print(f"  planting: A at ({ax:.1f}, {ay:.1f}) walks {((spot[0] - ax) ** 2 + (spot[1] - ay) ** 2) ** 0.5:.1f} m to ({spot[0]:.1f}, {spot[1]:.1f})")
    call(db, "set_behavior", str(A), seq({"do": {"skill": "goto", "target": {"at": [spot[0], spot[1]]}}}, {"do": {"skill": "plant"}}))
    # A's own bush, where A planted it: other characters plant too, and a new node anywhere let the
    # scene go on while A was still walking there (it then walked away from B and the shelter
    # placed beside it, so B was out of A's sight by the tending: features/mechanics.md).
    planted = wait_for(lambda: [r for r in rows(db, "SELECT id, kind, x, y FROM resource_node")
                                if r["id"] not in before and r["kind"] == "berry_bush"
                                and (float(r["x"]) - spot[0]) ** 2 + (float(r["y"]) - spot[1]) ** 2 <= 9.0], timeout=90)
    results["planting"] = bool(planted)
    if not planted:
        b = rows(db, f"SELECT x, y FROM body WHERE id = {A}")[0]
        told = [r["text"][:160] for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {A}")
                if any(w in r["text"] for w in ("plant", "goto", "go to", "berr", "way is", "grows"))]
        print(f"  planting: A at ({float(b['x']):.1f}, {float(b['y']):.1f}), spot at ({spot[0]:.1f}, {spot[1]:.1f}), A started at ({ax:.1f}, {ay:.1f}); "
              f"A feedback: {told[-6:]}", rows(db, f"SELECT id, skill, phase, node FROM activity WHERE id = {A}"))
    # A stops wherever it is: a walk still under way would carry A away from B and the shelter placed
    # beside it below (the conception failure that came with planting's on dev-box, 2026-11-21).
    call(db, "set_behavior", str(A), idle)
    # 6. Consensual conception beside a shelter (B joins A, who walked off to plant).
    call(db, "place_near", str(B), str(A))
    print(f"  conception setup: A-B {gap(A, B):.2f} m after place_near")
    call(db, "place_structure", str(A), "shelter")
    time.sleep(1)
    # Both must be fed ("too hungry to think of a family" otherwise).
    call(db, "grant_items", str(A), "cooked_meat", "3")
    call(db, "grant_items", str(B), "cooked_meat", "3")
    eat = {"do": {"skill": "eat", "item": "food"}}
    call(db, "set_behavior", str(A), seq(eat, eat, {"do": {"skill": "conceive", "target": {"id": B}}}))
    call(db, "set_behavior", str(B), seq(eat, eat, {"wait": 2}, {"do": {"skill": "conceive", "target": {"id": A}}}))
    # A and B themselves: an animal's pregnancy elsewhere is not this check's.
    expecting = wait_for(lambda: [r for r in rows(db, "SELECT a, b FROM expecting") if {int(r["a"]), int(r["b"])} == {A, B}], timeout=30)
    results["consensual conception"] = bool(expecting)
    # 7. Tending wounds: A strikes B once, lets the fight cool down, then tends B.
    def vitals(i):
        return rows(db, f"SELECT hp, hp_rate, at_ms FROM vitals WHERE id = {i}")[0]

    def projected_hp(v, now_ms):
        return float(v["hp"]) + float(v["hp_rate"]) * (now_ms - float(v["at_ms"])) / 60000

    def hp(i):
        return projected_hp(vitals(i), time.time() * 1000)

    def wound_events(kind):
        return [r for r in rows(db, f"SELECT id, kind, subject, text FROM experience WHERE observer = {B}")
                if r["kind"] == kind and int(r["subject"]) == A]

    def pos(i):
        b = rows(db, f"SELECT x, y FROM body WHERE id = {i}")[0]
        return float(b["x"]), float(b["y"])

    call(db, "set_behavior", str(B), idle)
    # The blow and the care need B in A's sight and reach. If anything has parted them since the
    # conception step, B is put back beside A, and that is said.
    if gap(A, B) > 2.0:
        print(f"  tending: B was {gap(A, B):.2f} m from A; placed beside A again")
        call(db, "place_near", str(B), str(A))
        time.sleep(1)
    old_hits = {r["id"] for r in wound_events("attacked")}
    old_feedback = {r["id"] for r in rows(db, f"SELECT id FROM experience WHERE observer = {A}")}
    unwounded_hp = hp(B)
    a_stamina = rows(db, f"SELECT stamina, stamina_max FROM vitals WHERE id = {A}")[0]
    (ax_, ay_), (bx_, by_) = pos(A), pos(B)
    print(f"  tending setup: A stamina {float(a_stamina['stamina']):.1f}/{float(a_stamina['stamina_max']):.0f}, "
          f"A-B {((ax_ - bx_) ** 2 + (ay_ - by_) ** 2) ** 0.5:.2f} m")
    call(db, "set_behavior", str(A), seq({"do": {"skill": "attack", "target": {"id": B}}}))

    def damage_dealt():
        for event in wound_events("attacked"):
            damage = re.search(r"\((\d+) damage\)", event["text"])
            if event["id"] not in old_hits and damage:
                return int(damage.group(1))
        return 0

    damage = wait_for(damage_dealt, timeout=20)
    # Experience rounds damage to whole HP, and natural recovery can start before the poll.
    hurt = bool(damage) and hp(B) <= unwounded_hp - damage / 2
    call(db, "set_behavior", str(A), idle)
    time.sleep(11)
    old_care = {r["id"] for r in wound_events("care")}
    before = vitals(B)
    before_hp = projected_hp(before, time.time() * 1000)
    call(db, "set_behavior", str(A), seq({"do": {"skill": "tend", "target": {"id": B}}}))
    tended = wait_for(lambda: any(r["id"] not in old_care and "tended your wounds" in r["text"]
                                 for r in wound_events("care")), timeout=20)
    after = vitals(B)
    now_ms = time.time() * 1000
    after_hp = projected_hp(after, now_ms)
    natural_hp = projected_hp(before, now_ms)
    results["tending wounds"] = bool(hurt and tended and after_hp > max(before_hp, natural_hp) + 0.1)
    print(f"  tending: {damage} damage reported, {before_hp:.2f} -> {after_hp:.2f} HP "
          f"({natural_hp:.2f} projected without care), care recorded: {bool(tended)}")
    if not results["tending wounds"]:
        told = [r for r in rows(db, f"SELECT id, kind, text FROM experience WHERE observer = {A}") if r["id"] not in old_feedback]
        print(f"  tending A feedback:", [(r["kind"], r["text"][:160]) for r in told][-10:])
        print(f"  tending state A:", rows(db, f"SELECT id, skill, phase, node, started_ms, ends_ms, victim FROM activity WHERE id = {A}"),
              rows(db, f"SELECT stamina, stamina_max, hp FROM vitals WHERE id = {A}"))
    # 8. Settlements: lay road underfoot, build a wall and a gate beside, shut and open the gate.
    for t in ["masonry", "carpentry", "shelter"]:
        call(db, "grant_know_how", str(A), t)
    call(db, "grant_items", str(A), "stone", "6")
    call(db, "grant_items", str(A), "wood", "6")
    body = rows(db, f"SELECT x, y FROM body WHERE id = {A}")[0]
    ax, ay = float(body["x"]), float(body["y"])
    wall_at = [int(ax) + 2 + 0.5, int(ay) + 0.5]
    gate_at = [int(ax) + 2 + 0.5, int(ay) + 1.5]
    call(db, "set_behavior", str(B), idle)
    call(db, "set_behavior", str(A), seq(
        {"first": [{"do": {"skill": "pave"}}, {"wait": 1}]},
        {"do": {"skill": "build", "item": "wall", "target": {"at": wall_at}}},
        {"do": {"skill": "build", "item": "gate", "target": {"at": gate_at}}},
    ))
    built = wait_for(lambda: rows(db, f"SELECT * FROM gate WHERE changed_by = {A}"), timeout=60)
    story = [r["text"] for r in rows(db, "SELECT kind, text FROM chronicle") if r["kind"] == "build"]
    results["road, wall and gate built"] = bool(built)
    if not built:
        told = [r["text"][:160] for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {A}")
                if any(w in r["text"] for w in ("build", "pave", "wall", "gate", "road"))]
        near = [(r["kind"], round(float(r["x"]), 1), round(float(r["y"]), 1)) for r in rows(db, "SELECT kind, x, y FROM resource_node")
                if abs(float(r["x"]) - wall_at[0]) < 3 and abs(float(r["y"]) - wall_at[1]) < 3]
        print(f"  build: A at ({ax:.1f}, {ay:.1f}), wall at {wall_at}, gate at {gate_at}; nodes near: {near}; A feedback: {told[-6:]}",
              rows(db, f"SELECT id, skill, phase, node FROM activity WHERE id = {A}"), story[-4:])
    if built:
        gid = int(built[0]["id"])
        call(db, "set_behavior", str(A), seq({"do": {"skill": "close", "target": {"nearest": "gate"}}}))
        shut = wait_for(lambda: [g for g in rows(db, f"SELECT id, open FROM gate WHERE id = {gid}") if g["open"] == "false"], timeout=20)
        call(db, "set_behavior", str(A), seq({"do": {"skill": "open", "target": {"nearest": "gate"}}}))
        reopened = wait_for(lambda: [g for g in rows(db, f"SELECT id, open FROM gate WHERE id = {gid}") if g["open"] == "true"], timeout=20)
        results["gate shut and opened"] = bool(shut) and bool(reopened)
    # 9. Deliberate acts (decided by a mind, outside the graph; the walkers are controlled by
    # this admin identity like minds). C and D rest in a loop: if the graph could take the
    # body back, rest would cancel the acts. C gives D berries, then both choose each other.
    # Resting before they are placed: on their spawn graphs they forage away during the setup
    # calls (as B did before the tablet; features/mechanics.md).
    rest = json.dumps({"first": [{"do": {"skill": "rest"}}]})
    call(db, "set_behavior", str(C), rest)
    call(db, "set_behavior", str(D), rest)
    call(db, "place_near", str(C), str(A))
    call(db, "place_near", str(D), str(C))
    call(db, "grant_items", str(C), "cooked_meat", "3")
    call(db, "grant_items", str(D), "cooked_meat", "3")
    call(db, "grant_items", str(C), "berries", "4")
    time.sleep(1.5)
    act = lambda who, *nodes: stdb("call", "-s", "local", db, "mind_act", str(who), json.dumps([json.dumps(n) for n in nodes]), json.dumps("test"))
    act(C, {"do": "eat", "item": "food"}, {"do": "give", "target": {"id": D}, "item": "berries", "qty": 2})
    act(D, {"do": "eat", "item": "food"})
    gave = wait_for(lambda: [r for r in rows(db, f"SELECT item, qty FROM inventory WHERE owner = {D}") if r["item"] == "berries"], timeout=30)
    told = lambda who, words: [r for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {who}") if r["kind"] == "act" and words in r["text"]]
    results["act: a gift decided outside the graph, reported back"] = bool(gave) and bool(wait_for(lambda: told(C, "You did what you had decided"), timeout=10))
    if gap(C, D) > 2.0:
        print(f"  acts: D was {gap(C, D):.2f} m from C; placed beside C again")
        call(db, "place_near", str(D), str(C))
    call(db, "place_structure", str(C), "shelter")
    time.sleep(1)
    act(C, {"do": "conceive", "target": {"id": D}})
    time.sleep(2)
    act(D, {"do": "conceive", "target": {"id": C}})
    both = wait_for(lambda: [r for r in rows(db, "SELECT a, b FROM expecting") if {int(r["a"]), int(r["b"])} == {C, D}], timeout=30)
    results["act: conception chosen by both as acts"] = bool(both)
    if not both:
        print(f"  acts: C-D {gap(C, D):.2f} m;", "C told:", [r["text"][:140] for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {C}") if r["kind"] == "act"][-4:],
              "D told:", [r["text"][:140] for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {D}") if r["kind"] == "act"][-4:])
    # A cannot teach what A does not know: the act fails, and A is told why.
    act(A, {"do": "teach", "target": {"id": B}, "item": "cloak"})
    results["act: a failed act is reported with its reason"] = bool(wait_for(lambda: told(A, "did not work out"), timeout=30))
    # Real-time behavior is not an act: it is refused with feedback.
    act(A, {"do": "flee", "target": {"nearest": "wolf"}})
    results["act: real-time behavior refused as an act"] = bool(wait_for(lambda: told(A, "behavior graph"), timeout=10))
    # Ways change through the rework skill: a new way at once, an existing one only once it
    # has been lived with (the rules script decides).
    act(B, {"do": "rework", "item": "Watch_The_Fire", "graph": {"first": [{"do": "rest"}]}})
    made = wait_for(lambda: [r for r in rows(db, f"SELECT actor, name FROM routine WHERE actor = {B}") if r["name"] == "watch the fire"], timeout=40)
    act(B, {"do": "rework", "item": "watch the fire", "graph": {"first": [{"do": "wait"}]}})
    results["act: rework makes a new way, refuses one not yet lived with"] = bool(made) and bool(wait_for(lambda: told(B, "hardly lived with"), timeout=40))
    if not results["act: rework makes a new way, refuses one not yet lived with"]:
        print("  rework: made", bool(made), [r["text"][:160] for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {B}")][-6:])
    # Know-how for trade and a longer life: a net brings in two fish at once, smoked fish
    # keeps, bows and arrows, leather, and clearing forest into open ground.
    for t in ["fishing", "smoking", "fire", "archery", "tanning"]:
        call(db, "grant_know_how", str(D), t)

    def inventory(who):
        return {r["item"]: int(r["qty"]) for r in rows(db, f"SELECT item, qty FROM inventory WHERE owner = {who}")}

    def reset_pack(who, **supplies):
        # Settle the previous graph and verify each drop before granting the new inputs.
        call(db, "set_behavior", str(who), idle)
        for item, qty in inventory(who).items():
            call(db, "set_behavior", str(who), seq({"do": {"skill": "drop", "item": item, "qty": qty}}))
            if not wait_for(lambda: item not in inventory(who), timeout=10):
                raise RuntimeError(f"could not empty pack for actor {who}: {inventory(who)}")
        for item, qty in supplies.items():
            call(db, "grant_items", str(who), item, qty)
        # Raw fish spoils by chance each minute it is carried (tick::spoil), so one can go between
        # the grant and this read (2026-11-21: 3 granted, 2 read). Top a shortfall up, then compare.
        for _ in range(3):
            have = inventory(who)
            short = {k: int(v) - int(have.get(k, 0)) for k, v in supplies.items() if int(have.get(k, 0)) < int(v)}
            if not short:
                break
            for item, n in short.items():
                call(db, "grant_items", str(who), item, n)
        if inventory(who) != supplies:
            raise RuntimeError(f"expected pack {supplies}, got {inventory(who)}")

    def report_pack_failure(case):
        feedback = rows(db, f"SELECT kind, text FROM experience WHERE observer = {D}")
        print(f"  {case}:", [r["text"][:150] for r in feedback][-6:], inventory(D))

    reset_pack(D, fiber=3)
    call(db, "set_behavior", str(D), seq({"do": {"skill": "craft", "item": "net"}}))
    netted = wait_for(lambda: inventory(D).get("net") == 1, timeout=60)
    # Put a stocked spot at the walker so residents cannot empty it during a walk.
    call(db, "place_resource", D, "fishing_spot", 0, 0, 5, 0)
    call(db, "set_behavior", str(D), seq({"do": {"skill": "gather", "target": {"nearest": "fishing_spot"}}}))
    results["a net brings in two fish at once"] = bool(
        netted and wait_for(lambda: inventory(D).get("fish") == 2, timeout=30))
    if not results["a net brings in two fish at once"]:
        report_pack_failure("net")

    # Raw fish spoils by chance each minute it is carried (tick::spoil), so a lone fish can be
    # lost before a slow walk to the campfire ends (gate flakes, 2026-11-20): carry spares and
    # judge the products without the raw fish left over.
    reset_pack(D, fish=3, wood=3, fiber=1, stone=1, hide=1)
    call(db, "place_structure", str(D), "campfire")
    call(db, "set_behavior", str(D), seq(
        {"do": {"skill": "smoke", "target": {"nearest": "campfire"}, "item": "fish"}},
        {"do": {"skill": "craft", "item": "bow"}},
        {"do": {"skill": "craft", "item": "arrow"}},
        {"do": {"skill": "craft", "item": "leather"}},
    ))
    products = {"smoked_fish": 1, "bow": 1, "arrow": 3, "leather": 1}
    made = lambda: {k: v for k, v in inventory(D).items() if k != "fish"}
    results["smoking, bow, arrows and leather"] = bool(
        wait_for(lambda: made() == products, timeout=90))
    if not results["smoking, bow, arrows and leather"]:
        report_pack_failure("craft")

    reset_pack(D)
    clear_ready(db, D)
    call(db, "set_behavior", str(D), seq({"do": {"skill": "clear"}}))
    results["clearing forest yields wood"] = bool(
        wait_for(lambda: inventory(D).get("wood") == 2, timeout=150))
    if not results["clearing forest yields wood"]:
        report_pack_failure("clear")
    # Force. F threatens G: G perceives it, and it counts as being threatened (G's own
    # graph yields to it).
    F, G, H, I, J = walkers[5:10]
    heard = lambda who, words: [r for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {who}") if words in r["text"]]
    story = lambda kind: [r for r in rows(db, "SELECT kind, a, b, text FROM chronicle") if r["kind"] == kind]
    alive = lambda who: rows(db, f"SELECT id, alive FROM character WHERE id = {who}")[0]["alive"] == "true"
    max_hp = lambda who: float(rows(db, f"SELECT id, max_hp FROM vitals WHERE id = {who}")[0]["max_hp"])
    call(db, "place_near", str(G), str(F))
    call(db, "set_behavior", str(G), json.dumps({"first": [{"if": {"threatened": True}, "then": {"do": "yield", "target": {"id": F}}}, {"wait": 1}]}))
    # Threatened holds only while a threat is under way (2 s, brain.rs), and G must evaluate
    # inside it; under load one window can pass unseen (gate flakes, 2026-11-20), so F keeps
    # threatening until G gives in.
    call(db, "set_behavior", str(F), json.dumps({"first": [{"do": {"skill": "threaten", "target": {"id": G}}}, {"wait": 1}]}))
    menaced = wait_for(lambda: heard(G, "threatens you"), timeout=20)
    gave_in = wait_for(lambda: [r for r in story("yield") if int(r["a"]) == G], timeout=30)
    call(db, "set_behavior", str(F), idle)
    results["force: a threat is perceived and counts as being threatened"] = bool(menaced) and bool(story("threat")) and bool(gave_in)
    if not results["force: a threat is perceived and counts as being threatened"]:
        print("  threat:", bool(menaced), story("threat"), [r["text"][:150] for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {G}")][-5:])
        # What G and F were doing when G did not give in (a teleport mid-approach can leave an
        # activity unfinishable; the stuck-jump report, 2026-11-20).
        for who in (G, F):
            print(f"  threat state {who}:", rows(db, f"SELECT id, skill, phase, node, started_ms, ends_ms, victim FROM activity WHERE id = {who}"),
                  rows(db, f"SELECT id, status FROM mind_state WHERE id = {who}"))
    # F attacks H (who does not defend) with a spear: there is no beating that stops short;
    # the blows go on and the one that exceeds H's health kills.
    call(db, "grant_items", str(F), "spear", "1")
    call(db, "place_near", str(H), str(F))
    call(db, "set_behavior", str(H), idle)
    call(db, "set_behavior", str(F), json.dumps({"first": [{"do": {"skill": "attack", "target": {"id": H}}}, {"wait": 1}]}))
    died = wait_for(lambda: not alive(H), timeout=60)
    cause = rows(db, f"SELECT id, cause FROM character WHERE id = {H}")[0]["cause"]
    results["force: a blow does its damage, and the one that exceeds health kills"] = bool(died) and cause.startswith("killed by") and bool([r for r in story("killing") if int(r["a"]) == F and int(r["b"]) == H]) and not story("assault")
    if not results["force: a blow does its damage, and the one that exceeds health kills"]:
        print("  killing:", bool(died), cause, story("killing"), [r["text"][:150] for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {F}")][-5:])
    call(db, "set_behavior", str(F), idle)
    # I attacks J, who yields when hurt: the yield does not hold I's blows back, and striking
    # someone who gave in is news. I stops once it is told, so J lives for the next check.
    call(db, "place_near", str(I), str(J))
    call(db, "set_behavior", str(J), json.dumps({"first": [{"if": {"hurt_within": 10}, "then": {"do": "yield", "target": "attacker"}}, {"wait": 1}]}))
    call(db, "set_behavior", str(I), json.dumps({"first": [{"do": {"skill": "attack", "target": {"id": J}}}, {"wait": 1}]}))
    yielded = wait_for(lambda: [r for r in story("yield") if int(r["a"]) == J], timeout=30)
    news = wait_for(lambda: [r for r in story("attack") if int(r["a"]) == I and int(r["b"]) == J and "had yielded" in r["text"]], timeout=15, every=0.3)
    call(db, "set_behavior", str(I), idle)
    # The blow after the yield landed: J felt its damage ("... though you had yielded (7 damage)").
    told = heard(J, "though you had yielded")
    dealt = [float(m.group(1)) for r in told for m in [re.search(r"\((\d+(?:\.\d+)?) damage\)", r["text"])] if m]
    results["force: blows land on the yielded, and striking them is news"] = bool(yielded) and bool(news) and any(d > 0 for d in dealt)
    if not results["force: blows land on the yielded, and striking them is news"]:
        print("  yield:", bool(yielded), bool(news), [r["text"][:150] for r in told], rows(db, f"SELECT id, status FROM mind_state WHERE id = {I}"))
    call(db, "set_behavior", str(I), idle)
    # A wolf that is not desperate does not dare attack a healthy adult among others.
    call(db, "place_near", str(J), str(I))
    now_ms = time.time() * 1000
    hunger = {r["id"]: float(r["hunger"]) + float(r["hunger_rate"]) * (now_ms - float(r["at_ms"])) / 60000 for r in rows(db, "SELECT id, hunger, hunger_rate, at_ms FROM vitals")}
    wolves = [r["id"] for r in rows(db, "SELECT id, kind, alive FROM character") if r["kind"] == "wolf" and r["alive"] == "true" and r["id"] in hunger]
    if wolves:
        W = int(min(wolves, key=lambda w: hunger[w]))
        # The attack goes in before the wolf is placed. Placed first, its own ways ran beside I
        # until set_behavior arrived: "stay safe" flees the nearest person within 7 tiles, so it
        # ran 10-12 m off, out of sight, and its attack never found I to balk at (3 of 64 gate
        # worlds; features/mechanics.md). Attempted in a loop: just placed, the wolf may not see I
        # yet under load ("stuck: attack: no #I in sight", 2026-11-20).
        call(db, "set_behavior", str(W), json.dumps({"first": [{"do": {"skill": "attack", "target": {"id": I}}}, {"wait": 1}]}))
        call(db, "place_near", str(W), str(I))
        h0 = hp(I)
        balked = wait_for(lambda: [r for r in story("balk") if int(r["a"]) == W], timeout=20)
        time.sleep(3)
        results["force: a wolf does not dare attack a healthy adult among others"] = bool(balked) and hp(I) >= h0 - 0.5
        if not results["force: a wolf does not dare attack a healthy adult among others"]:
            print("  wolf:", W, f"hunger {hunger[str(W)]:.0f}", bool(balked), f"{h0:.1f} -> {hp(I):.1f}", rows(db, f"SELECT id, status FROM mind_state WHERE id = {W}"),
                  f"W-I {gap(W, I):.2f} m, J-I {gap(J, I):.2f} m", rows(db, f"SELECT id, skill, phase, node FROM activity WHERE id = {W}"))
            print("  wolf feedback:", [r["text"][:140] for r in rows(db, f"SELECT kind, text FROM experience WHERE observer = {W}")][-8:])
        call(db, "set_behavior", str(W), idle)
    else:
        results["force: a wolf does not dare attack a healthy adult among others"] = False
        print("  wolf: no living wolf in this world")
    # Death: what only a living body uses goes with it (routines, their stats, practice, the
    # graph, genes); a parent of a child still expected keeps it until the birth.
    act(E, {"do": "rework", "item": "keep watch", "graph": {"first": [{"do": "rest"}]}})
    reworked = wait_for(lambda: rows(db, f"SELECT id, name FROM routine WHERE actor = {E}"), timeout=40)
    call(db, "set_behavior", str(E), seq({"do": {"skill": "gather", "target": {"nearest": "berry_bush"}}}))
    lived = reworked and wait_for(lambda: rows(db, f"SELECT id, skill FROM practice WHERE actor = {E}"), timeout=60)
    routine_ids = [int(r["id"]) for r in rows(db, f"SELECT id, name FROM routine WHERE actor = {E}")]
    call(db, "kill", str(E), "test")
    # A walker expecting a child (A with B, or C with D, from the checks above).
    expecting_walkers = [int(r[k]) for r in rows(db, "SELECT a, b FROM expecting") for k in ("a", "b") if int(r[k]) in (A, B, C, D)]
    P = expecting_walkers[0] if expecting_walkers else C
    call(db, "kill", str(P), "test")
    left = {t: rows(db, f"SELECT id, {c2} FROM {t} WHERE {col} = {E}") for t, col, c2 in [("routine", "actor", "name"), ("practice", "actor", "skill"), ("brain", "id", "revision"), ("genome", "id", "ways")]}
    left["routine_stat"] = [r for r in rows(db, "SELECT id, ok FROM routine_stat") if int(r["id"]) in routine_ids]
    kept = bool(expecting_walkers) and rows(db, f"SELECT id, ways FROM genome WHERE id = {P}") and rows(db, f"SELECT id, revision FROM brain WHERE id = {P}")
    results["death clears the body's rows; an expecting parent keeps its genes"] = bool(lived) and not any(left.values()) and bool(kept)
    if not results["death clears the body's rows; an expecting parent keeps its genes"]:
        print("  death: lived", bool(lived), "left", {k: len(v) for k, v in left.items()}, "parent kept", bool(kept))
    ok = all(results.values())
    for k, v in results.items():
        print(("PASS " if v else "FAIL ") + k)
    report = {"db": db, "results": results, "story": [r["text"] for r in rows(db, "SELECT kind, text FROM chronicle") if r["kind"] not in ("arrival", "time", "speech")]}
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2) + "\n")
    if a.gate_world:
        sys.exit(0 if ok else 1)  # The gate's shared harness owns cleanup.
    # The scratch world would otherwise keep ticking (and writing its log) forever.
    # Paused and read back as paused before the delete (world_delete.py: a busy world's delete can
    # take SpacetimeDB 2.14.1 down).
    deleted, why = world_delete.cli_pause_and_delete(lambda *a: subprocess.run([STDB, *a], capture_output=True, text=True), db)
    print(f"{db}: {why}")
    sys.exit(0 if ok and deleted else 1)


if __name__ == "__main__":
    main()
