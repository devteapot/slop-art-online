#!/usr/bin/env python3
"""Heed for players (docs/ATTENTION_BUDGET.md, "Player-side interface"; the `heed_players` law with
`heed_on`, both off as shipped): the player's `perceived` set is its individuals, the rest of its
sight a counted throng in `seen_throng`, its pins and focus taken through `human_heed`.

    heed.py --run player-...      (a run launched with verify.py launch, any seed)

On an open line the run's player P stands facing east with eight held walkers 3-14 m east of it.
The heed ceiling (`heed_ceiling`) is set to 2, so P's capacity is 2. Checks, in order:

- **off (as shipped):** P perceives all eight (`seen_characters`); no `seen_throng` row;
- **on:** P perceives at most 2 of them, the nearest; its `seen_throng` rows count the other six
  (counts exact under 6), none names anyone (cells, counts and bits only); with `far_cap` 1 too,
  still 2 (heed replaces `far_cap`'s trim, never both);
- **`human_heed`'s refusals:** five pins ("at most 4"); a pin on a throng member and one on an id
  no one has, refused with the same words; a second call within 250 ms ("too many inputs");
  `heed_choice` is refused to the player's SQL (private);
- **a pin keeps a creature:** P pins one of its individuals, which then walks to the far end of
  the walkers: it stays an individual (`heed_choice` holds the pin); unpinned, it goes back into
  the throng within its rule's hold and a pass;
- **contact:** a throng member strikes P: it is in P's `perceived` set from the blow's own tick
  (its row's `since_ms` is the feed row's `at_ms`);
- **the kill switch:** `heed_players` off: every `seen_throng` row is gone within a tick or two
  of the switch, and P perceives all eight again.

The laws are put back as the world had them. Admin calls (`spawn_crowd`, `set_behavior`,
`place_at`, `admin_set_vitals`, `set_world_law`) set the scene. Writes `RUN/heed-proof.jsonl`.
Python standard library only.
"""
import argparse
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


def heed_input(pins, focus=None):
    """`HeedInput` as the HTTP API takes it: a product by field names, an Option as a sum."""
    return [{"pins": pins, "focus": {"some": focus} if focus is not None else {"none": []}}]


def hexid(v_):
    while isinstance(v_, (list, dict)):
        v_ = v_[0] if isinstance(v_, list) else next(iter(v_.values()))
    return str(v_).lower().removeprefix("0x")


me = sql("SELECT id FROM my_characters", player)[0]["id"]
ident = hexid(sql(f"SELECT controller FROM character WHERE id = {me}")[0]["controller"])
was = own_laws(lambda q: sql(q))


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
        x, y = line[3 + (k // 2) * 3][0], line[0][1] + (1.0 if k % 2 else -1.0)
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
    record("on: seen_throng counts the rest", total == len(crowd - ind), {"rows": rows, "total": total})
    record("on: a throng row carries cells, counts and bits only",
           all(set(r) == {"id", "viewer", "cell", "size", "count", "spread", "heading", "moving", "fighting", "kinds"} for r in rows) and all(hexid(r["viewer"]) == ident for r in rows), rows[:2])
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
    far_end = max(x for x, _ in spots.values()) + 2.0
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

    # Contact.
    striker = next(w for w in sorted(crowd - seen(), key=lambda w: dist[w]) if w != pick)
    do("place_at", [striker, line[0][0] + 1.2, line[0][1]])
    time.sleep(0.6)
    in_throng = striker not in seen()
    do("set_behavior", [striker, json.dumps({"seq": [{"do": {"skill": "strike", "target": {"id": me}}}, {"wait": 600}]})])
    row = until(lambda: next((r for r in perceived_rows() if r["body"] == striker), None), 8)
    fed = until(lambda: [r for r in sql(f"SELECT * FROM combat_seen WHERE viewer = 0x{ident}") if r["actor"] == striker], 8)
    record("contact: the striker was in P's throng before its blow", in_throng, striker)
    record("contact: the striker joins P's perceived set in the blow's tick (since_ms = the feed row's at_ms)",
           row is not None and fed and row["since_ms"] in {r["at_ms"] for r in fed}, {"perceived": row, "feed": fed[:2]})

    # The kill switch.
    t0 = sql("SELECT tick FROM clock")[0]["tick"]
    law("heed_players", False)
    gone = until(lambda: not throng_rows(), 3, 0.02)
    t1 = sql("SELECT tick FROM clock")[0]["tick"]
    record("off: every seen_throng row goes at once (within a few ticks of the switch)", gone and t1 - t0 <= 6, {"ticks": t1 - t0})
    back = until(lambda: crowd <= seen(), 4)
    record("off: P perceives all eight again", bool(back), sorted(seen() & crowd))
finally:
    shipped = {"heed_on": "false", "heed_players": "false", "heed_ceiling": "16", "far_cap": "0"}
    for name in LAWS:
        call("set_world_law", [name, was.get(name) or shipped[name]])
print(f"{'all' if not failed else len(failed)} checks {'pass' if not failed else 'fail'}: {out}")
sys.exit(1 if failed else 0)
