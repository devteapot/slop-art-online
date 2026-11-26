#!/usr/bin/env python3
"""Heed for players (docs/ATTENTION_BUDGET.md, "Player-side interface"; the `heed_players` law with
`heed_on`, both off as shipped): the player's `perceived` set is its individuals, the rest of its
sight a counted throng in `seen_throng`, its pins and focus taken through `human_heed`.

    heed.py --run player-...      (a run launched with verify.py launch; a seed with looks, e.g. island)

On an open line the run's player P stands facing east with eight held walkers 2-8 m east of it (within a night's 11 m sight).
The heed ceiling (`heed_ceiling`) is set to 2, so P's capacity is 2. Checks, in order:

- **off (as shipped):** P perceives all eight (`seen_characters`); no `seen_throng` row;
- **on:** P perceives at most 2 of them, the nearest; its `seen_throng` rows count the other six
  (counts exact under 6), none names anyone (cells, counts, bits and colour indices only); each
  cell's three colours are its members' most worn cloth colours from their looks (read as the
  owner), counts quantized as `count`; its counts by kind match its members (people here), and its
  centre is their mean position to the metre within the square; with `far_cap` 1 too, still 2 (heed replaces `far_cap`'s
  trim, never both);
- **`human_heed`'s refusals:** five pins ("at most 4"); a pin on a throng member and one on an id
  no one has, refused with the same words; a second call within 250 ms ("too many inputs");
  `heed_choice` is refused to the player's SQL (private);
- **a pin keeps a creature:** P pins one of its individuals, which then walks to the far end of
  the walkers: it stays an individual (`heed_choice` holds the pin); unpinned, it goes back into
  the throng within its rule's hold and a pass;
- **pin_at:** a point where P has no throng is refused with `NO_ONE_THERE`; four pins and a
  point, with the four-pin words; a point in a throng cell makes the member nearest it there an
  individual and its pin; at capacity 0 for P (below) a point in a cell is refused with
  `NO_PLACE` and no one is promoted. Both refusals are compared word for word: they name no one;
- **contact:** at capacity 0 for P alone (an installed `heed_capacity` that returns 0 for it; so no rule, the instinct's threat rule at the windup included, can
  take it) a throng member strikes P: it is in P's `perceived` set from the blow's own tick (its
  row's `since_ms` is the feed row's `at_ms`);
- **the kill switch:** `heed_players` off: every `seen_throng` row is gone within a tick or two
  of the switch, and P perceives all eight again.

The laws are put back as the world had them. Admin calls (`spawn_crowd`, `set_behavior`,
`place_at`, `admin_set_vitals`, `set_world_law`, `install_script`) set the scene; the world's own script
(the `script` row) is installed back after the contact check. Writes `RUN/heed-proof.jsonl`.
Python standard library only.
"""
import argparse
import math
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "verify/scripts"))
import verify as v  # noqa: E402
sys.path.insert(0, str(HERE.parents[2] / "verify-client/scripts"))
from earshot import open_line  # noqa: E402
sys.path.insert(0, str(HERE.parents[4] / "living/tools"))
from law_values import own_laws  # noqa: E402

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--run", required=True)
a = p.parse_args()
st = v.load(a.run)
db = st["db"]
owner = v.admin_token()
player = st["token"]
out = v.run_dir(a.run) / "heed-proof.jsonl"
out.write_text("")
UNSEEN = "You can only keep track of someone you can see now."
NO_ONE_THERE = "There is no one in the throng there to pick out."
NO_PLACE = "You are already keeping track of as many as you can."
LAWS = ("heed_on", "heed_players", "heed_ceiling", "far_cap")
failed = []


def record(name, ok, data=None):
    with out.open("a") as f:
        f.write(json.dumps({"check": name, "passed": bool(ok), "data": data}, default=str) + "\n")
    print(("PASS" if ok else "FAIL"), name, json.dumps(data, default=str)[:300], flush=True)
    if not ok:
        failed.append(name)


def call(reducer, args, token=owner):
    return v.http(f"/v1/database/{db}/call/{reducer}", args, token, timeout=90)


def do(reducer, args, token=owner):
    code, body = call(reducer, args, token)
    assert code == 200, (reducer, code, body)
    return body


def sql(query, token=owner):
    code, body = v.http(f"/v1/database/{db}/sql", query, token, raw=True)
    assert code == 200, (query, code, body)
    res = json.loads(body)[0]
    fields = [c["name"]["some"] for c in res["schema"]["elements"]]
    return [dict(zip(fields, r)) for r in res["rows"]]


def until(read, limit=10.0, every=0.1):
    deadline = time.monotonic() + limit
    value = read()
    while not value and time.monotonic() < deadline:
        time.sleep(every)
        value = read()
    return value


def law(name, value):
    do("set_world_law", [name, json.dumps(value)])


def heed_input(pins, focus=None, at=None):
    """`HeedInput` as the HTTP API takes it: a product by field names, an Option as a sum."""
    opt = lambda x: {"some": x} if x is not None else {"none": []}
    return [{"pins": pins, "focus": opt(focus), "pin_at": opt({"x": at[0], "y": at[1]} if at else None)}]


CLOTH = ["yellow", "black", "green", "tan", "blue", "red", "cream", "navy", "purple", "grey"]
CELL_M = 6.0


def about(n):
    return n if n <= 5 else (n + 2) // 5 * 5


def cloth_of(top):
    w = (top or "").split()
    word = w[1] if len(w) > 1 and w[0] in ("a", "an") else (w[0] if w else "")
    return CLOTH.index(word) if word in CLOTH else 255


def square(r):
    return (r["cell"] >> 16) * CELL_M, (r["cell"] & 0xFFFF) * CELL_M, max(1, r["size"]) * CELL_M


def inside(r, p):
    x0, y0, side = square(r)
    return x0 <= p[0] < x0 + side and y0 <= p[1] < y0 + side


def expected_colours(members):
    """The authority's rule, from the members' look rows read as the owner: the three cloth colours
    most worn (most first, ties by index), counts quantized; (255, 0) for an empty place."""
    n = {}
    for m in members:
        look = sql(f"SELECT words FROM look WHERE id = {m}")
        if not look:
            continue
        w = look[0]["words"]
        top = w.get("top") if isinstance(w, dict) else w[4]
        i = cloth_of(top)
        if i != 255:
            n[i] = n.get(i, 0) + 1
    order = sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    order += [(255, 0)] * (3 - len(order))
    return [(i, about(k)) for i, k in order]


def hexid(v_):
    while isinstance(v_, (list, dict)):
        v_ = v_[0] if isinstance(v_, list) else next(iter(v_.values()))
    return str(v_).lower().removeprefix("0x")


me = sql("SELECT id FROM my_characters", player)[0]["id"]
ident = hexid(sql(f"SELECT controller FROM character WHERE id = {me}")[0]["controller"])
was = own_laws(lambda q: sql(q))
# The world's installed script, put back after the contact check (and at the end, whatever happened).
shipped_src = sql("SELECT source FROM script WHERE name = 'skills'")[0]["source"]


def seen():
    return {r["id"] for r in sql("SELECT id FROM seen_characters", player)} - {me}


def throng_rows():
    return sql(f"SELECT * FROM seen_throng WHERE viewer = 0x{ident}")


def perceived_rows():
    return sql(f"SELECT * FROM perceived WHERE viewer = 0x{ident}")


try:
    for name in ("heed_on", "heed_players"):
        law(name, False)
    law("far_cap", 0)
    line = open_line(a.run, 30)
    before = {r["id"] for r in sql("SELECT id FROM character")}
    do("spawn_crowd", [8, False])
    walkers = sorted(r["id"] for r in sql("SELECT id FROM character") if r["id"] not in before)[:8]
    for w in walkers:
        do("set_behavior", [w, json.dumps({"wait": 600})])
    do("admin_set_vitals", [me, 1000.0])
    do("place_at", [me, *line[0]])
    spots = {}
    for k, w in enumerate(walkers):
        x, y = line[2 + (k // 2) * 2][0], line[0][1] + (1.0 if k % 2 else -1.0)
        spots[w] = (x, y)
        do("place_at", [w, x, y])
    do("human_face", [1, 0], player)
    dist = {w: abs(spots[w][0] - line[0][0]) for w in walkers}
    crowd = set(walkers)

    # Off (as shipped).
    got = until(lambda: crowd <= seen() and seen(), 6)
    record("off: P perceives all eight", crowd <= seen(), sorted(seen() & crowd))
    record("off: no seen_throng row", not throng_rows(), throng_rows())

    # On, capacity 2.
    law("heed_ceiling", 2)
    law("heed_on", True)
    law("heed_players", True)
    time.sleep(2.5)
    ind = seen() & crowd
    record("on: P perceives at most 2 of the eight", 0 < len(ind) <= 2, sorted(ind))
    nearest = sorted(walkers, key=lambda w: (dist[w], w))[:2]
    record("on: its individuals are among the nearest (the instinct's nearness rule)", all(dist[i] <= dist[nearest[-1]] for i in ind), {"ind": sorted(ind), "nearest": nearest})
    rows = until(throng_rows, 4)
    total = sum(r["count"] for r in rows)
    # Counts are exact to 5, then to the nearest 5: each such row may be off by up to 2.
    slack = 2 * sum(1 for r in rows if r["count"] >= 5)
    record("on: seen_throng counts the rest (exact to 5, then to the nearest 5)", rows and abs(total - len(crowd - ind)) <= slack, {"rows": rows, "total": total, "rest": len(crowd - ind)})
    record("on: a throng row carries cells, counts, bits and colour indices only (no id of anyone)",
           all(set(r) == {"id", "viewer", "cell", "size", "count", "spread", "heading", "moving", "fighting", "kinds",
                          "colour_a", "colour_a_count", "colour_b", "colour_b_count", "colour_c", "colour_c_count",
                          "people", "wolves", "deer", "others", "centre_x", "centre_y"} for r in rows) and all(hexid(r["viewer"]) == ident for r in rows), rows[:2])
    # The colours: each row's three, from its members' looks (positions and looks read as the owner).
    pos = {b["id"]: (b["x"], b["y"]) for b in sql("SELECT id, x, y FROM body") if b["id"] in crowd - ind}
    colours = []
    for r in rows:
        members = [m for m, p_ in pos.items() if inside(r, p_)]
        got_c = [(r["colour_a"], r["colour_a_count"]), (r["colour_b"], r["colour_b_count"]), (r["colour_c"], r["colour_c_count"])]
        colours.append({"cell": r["cell"], "members": len(members), "got": got_c, "want": expected_colours(members)})
    record("on: each cell's colours are its members' most worn cloth colours, counts quantized as count",
           colours and all(c["got"] == c["want"] for c in colours) and any(c["got"][0][0] != 255 for c in colours), colours)
    # Kinds and centre: each row's counts by kind (all people here) and its members' mean position
    # to the metre within its square, from the owner's reading of their bodies.
    shape = []
    for r in rows:
        members = [p_ for p_ in pos.values() if inside(r, p_)]
        x0, y0, side = square(r)
        mx, my = (sum(p_[0] for p_ in members) / len(members), sum(p_[1] for p_ in members) / len(members)) if members else (x0, y0)
        want_c = [min(max(math.floor(mx - x0), 0), int(side) - 1), min(max(math.floor(my - y0), 0), int(side) - 1)]
        shape.append({"cell": r["cell"], "members": len(members), "kinds": [r["people"], r["wolves"], r["deer"], r["others"]],
                      "want_kinds": [about(len(members)), 0, 0, 0], "centre": [r["centre_x"], r["centre_y"]], "want_centre": want_c})
    record("on: each cell's counts by kind (quantized as count) and its members' centre to the metre",
           shape and all(c["kinds"] == c["want_kinds"] and c["centre"] == c["want_centre"] for c in shape), shape)
    record("on: perceived rows are the individuals only", {r["body"] for r in perceived_rows()} == ind, sorted(r["body"] for r in perceived_rows()))
    law("far_cap", 1)
    time.sleep(1.5)
    record("on with far_cap 1: still 2 individuals (heed replaces far_cap's trim)", len(seen() & crowd) == len(ind), sorted(seen() & crowd))
    law("far_cap", 0)

    # human_heed's refusals.
    throng = sorted(crowd - seen())
    code, body = call("human_heed", heed_input(walkers[:5]), player)
    record("human_heed: five pins refused", code != 200 and "at most 4" in body, [code, body[:200]])
    code1, body1 = call("human_heed", heed_input([throng[0]]), player)
    code2, body2 = call("human_heed", heed_input([], 999999), player)
    record("human_heed: a throng member and an id no one has are refused with the same words",
           code1 != 200 and code2 != 200 and UNSEEN in body1 and body1 == body2, [code1, body1[:200], code2, body2[:200]])
    code, _ = v.http(f"/v1/database/{db}/sql", "SELECT * FROM heed_choice", player, raw=True)
    record("heed_choice is private (refused to the player's SQL)", code != 200, code)

    # A pin keeps a creature.
    far_end = max(x for x, _ in spots.values()) + 1.5
    pick = sorted(seen() & crowd, key=lambda w: (dist[w], w))[0]
    do("human_heed", heed_input([pick]), player)
    code, body = call("human_heed", heed_input([pick], pick), player)
    record("human_heed: a second call within 250 ms is refused", code != 200 and "too many inputs" in body, [code, body[:200]])
    choice = sql(f"SELECT * FROM heed_choice WHERE actor = {me}")
    record("human_heed: heed_choice holds the pin", choice and choice[0]["pins"] == [pick], choice)
    do("place_at", [pick, far_end, line[0][1]])
    time.sleep(3.0)
    record("a pinned creature stays an individual at the far end", pick in seen(), sorted(seen() & crowd))
    time.sleep(0.3)
    do("human_heed", heed_input([]), player)
    gone = until(lambda: pick not in seen(), 10, 0.25)
    record("unpinned, it goes back into the throng (within its hold and a pass)", gone, sorted(seen() & crowd))

    # Picking someone out of the throng by a point (pin_at).
    time.sleep(0.4)
    behind = (line[0][0] - 9.0, line[0][1] + 7.0)
    code, body = call("human_heed", heed_input([], at=behind), player)
    record("pin_at where P has no throng is refused, naming no one", code != 200 and body.strip() == NO_ONE_THERE, [code, body[:200]])
    code, body = call("human_heed", heed_input(walkers[:4], at=spots[walkers[-1]]), player)
    record("pin_at with four pins is refused (the pick would be a fifth)", code != 200 and "at most 4" in body, [code, body[:200]])
    rows = throng_rows()
    thr_now = crowd - seen()
    pos = {b["id"]: (b["x"], b["y"]) for b in sql("SELECT id, x, y FROM body") if b["id"] in thr_now}
    cell = max(rows, key=lambda r: sum(1 for p_ in pos.values() if inside(r, p_)))
    in_cell = {m: p_ for m, p_ in pos.items() if inside(cell, p_)}
    x0, y0, side = square(cell)
    point = (x0 + side * 0.25, y0 + side * 0.25)
    want = min(in_cell, key=lambda m: (((in_cell[m][0] - point[0]) ** 2 + (in_cell[m][1] - point[1]) ** 2), m))
    before_pick = seen() & crowd
    code, body = call("human_heed", heed_input([], at=point), player)
    after_pick = seen() & crowd
    record("pin_at in a throng cell picks out the member nearest the point there (now an individual)",
           code == 200 and want not in before_pick and want in after_pick, {"code": code, "body": body[:200], "want": want, "before": sorted(before_pick), "after": sorted(after_pick)})
    choice = sql(f"SELECT * FROM heed_choice WHERE actor = {me}")
    prow = next((r for r in perceived_rows() if r["body"] == want), None)
    record("pin_at: the picked one is a pin, and in P's perceived set from that call", choice and choice[0]["pins"] == [want] and prow is not None, {"choice": choice, "perceived": prow})
    time.sleep(0.3)
    do("human_heed", heed_input([]), player)
    until(lambda: want not in seen(), 10, 0.25)

    # Contact, at capacity 0: no rule takes anyone, so its windup cannot make the striker an
    # individual (the instinct's first rule would, at its windup); only the blow's contact can.
    # The player's own capacity alone (the walker must still be able to aim at it by id).
    capped_src = shipped_src.replace("fn heed_capacity(a) {", "fn heed_capacity(a) {" + f"\n    if a.actor.id == {me} {{ return 0.0; }}", 1)
    assert capped_src != shipped_src
    do("install_script", [capped_src])
    # Its individuals go within their rules' holds (at most 5 s) and a pass.
    until(lambda: not (seen() & crowd), 12, 0.25)
    rows = throng_rows()
    code, body = call("human_heed", heed_input([], at=spots[walkers[-1]]), player)
    record("pin_at with no place for anyone (capacity 0) is refused truthfully, naming no one",
           code != 200 and body.strip() == NO_PLACE and not (seen() & crowd), [code, body[:200], sorted(seen() & crowd)])
    striker = next(w for w in sorted(crowd - seen(), key=lambda w: dist[w]) if w != pick)
    do("place_at", [striker, line[0][0] + 1.2, line[0][1]])
    time.sleep(0.6)
    before_blow = seen() & crowd
    in_throng = striker not in before_blow
    do("set_behavior", [striker, json.dumps({"seq": [{"do": {"skill": "strike", "target": {"id": me}}}, {"wait": 600}]})])
    row = until(lambda: next((r for r in perceived_rows() if r["body"] == striker), None), 8)
    fed = until(lambda: [r for r in sql(f"SELECT * FROM combat_seen WHERE viewer = 0x{ident}") if r["actor"] == striker], 8)
    record("contact (capacity 0): the striker was in P's throng before its blow", in_throng and not before_blow, {"striker": striker, "seen": sorted(before_blow)})
    record("contact (capacity 0): the striker joins P's perceived set in the blow's tick (since_ms = the feed row's at_ms)",
           row is not None and fed and row["since_ms"] in {r["at_ms"] for r in fed}, {"perceived": row, "feed": fed[:2]})

    do("install_script", [shipped_src])
    time.sleep(1.0)
    # The kill switch.
    t0 = sql("SELECT tick FROM clock")[0]["tick"]
    law("heed_players", False)
    gone = until(lambda: not throng_rows(), 3, 0.02)
    t1 = sql("SELECT tick FROM clock")[0]["tick"]
    record("off: every seen_throng row goes at once (within a few ticks of the switch)", gone and t1 - t0 <= 6, {"ticks": t1 - t0})
    back = until(lambda: crowd <= seen(), 4)
    record("off: P perceives all eight again", bool(back), sorted(seen() & crowd))
finally:
    call("install_script", [shipped_src])
    shipped = {"heed_on": "false", "heed_players": "false", "heed_ceiling": "16", "far_cap": "0"}
    for name in LAWS:
        call("set_world_law", [name, was.get(name) or shipped[name]])
print(f"{'all' if not failed else len(failed)} checks {'pass' if not failed else 'fail'}: {out}")
sys.exit(1 if failed else 0)
