#!/usr/bin/env python3
"""How many `doing` and `seen_doing` row changes subscribers receive (doing-renew; a measurement,
no pass mark).

Two real Rust SDK subscriptions (verify-client's probe) run side by side for `--seconds`: the
database owner's `SELECT * FROM doing` (every character's visible activity, what an observer or
the mind service could follow), and a joined player's `SELECT * FROM seen_doing` (what its client
is sent of the creatures it perceives). The player stands where the most people are within 30 m
(a town's busiest spot), or, with `--battle N`, beside `spawn_battle N`'s fighters. Each stream's
live changes are counted: inserts, deletes and updates per second, row operations per second
(an update travels as one delete and one insert in its transaction), and blinks: a row deleted and
inserted again for the same character within 1.5 s (a renewal shown as "doing nothing" between).

    doing_deltas.py --run RUN [--seconds 60] [--battle N]

Admin calls set the scene: `spawn_battle`, `place_at`. Writes `RUN/doing-deltas[-battle].json`
and both streams (`doing-deltas-*-admin.jsonl`, `-player.jsonl`). Python standard library only.
"""
import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location("rest_seen", ROOT / ".agents/skills/verify-player/scripts/rest_seen.py")
RS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RS)
V = RS.V


def count(events, table, seconds):
    live = [e for e in events if e.get("table") == table and e.get("event") in ("insert", "delete", "update")]
    key = lambda e: (e.get("row") or {}).get("doing", e.get("row") or {}).get("id")
    n = {k: sum(1 for e in live if e["event"] == k) for k in ("insert", "delete", "update")}
    blinks, last_del = 0, {}
    for e in live:
        if e["event"] == "delete":
            last_del[key(e)] = e["at_ms"]
        elif e["event"] == "insert" and key(e) in last_del and e["at_ms"] - last_del[key(e)] <= 1500:
            blinks += 1
    init = next((e for e in events if e.get("event") == "initial"), {})
    rows0 = len((init.get("tables") or {}).get(table, []))
    return {"initial_rows": rows0, **n, "blinks": blinks, "per_s": {k: round(v / seconds, 3) for k, v in n.items()},
            "events_per_s": round(sum(n.values()) / seconds, 3), "row_ops_per_s": round((n["insert"] + n["delete"] + 2 * n["update"]) / seconds, 3),
            "blinks_per_s": round(blinks / seconds, 3)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--battle", type=int, default=0)
    a = ap.parse_args()
    st = V.load(a.run)
    admin = V.admin_token()
    if not st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        st["token"], st["identity"] = j["token"], j["identity"]
        V.save(st)
    tok = st["token"]
    mine = [c for c in RS.sql(st, "SELECT id, alive FROM my_characters", tok) if c["alive"]]
    if not mine:
        RS.call(st, "join", ["Counter"], tok, "player")
        mine = [c for c in RS.sql(st, "SELECT id, alive FROM my_characters", tok) if c["alive"]]
    me = mine[0]["id"]
    tag = "battle" if a.battle else "town"
    if a.battle:
        before = {c["id"] for c in RS.sql(st, "SELECT id FROM character", admin)}
        RS.call(st, "spawn_battle", [a.battle], admin, "admin")
        fighters = [c["id"] for c in RS.sql(st, "SELECT id, name FROM character", admin) if c["id"] not in before]
        pts = [(b["x"], b["y"]) for b in RS.sql(st, "SELECT id, x, y FROM body", admin) if b["id"] in set(fighters)]
    else:
        people = {c["id"] for c in RS.sql(st, "SELECT id, kind, alive FROM character", admin) if c["kind"] == "person" and c["alive"] and c["id"] != me}
        pts = [(b["x"], b["y"]) for b in RS.sql(st, "SELECT id, x, y FROM body", admin) if b["id"] in people]
    spot = max(pts, key=lambda p: sum(1 for q in pts if math.dist(p, q) <= 30))
    near = sum(1 for q in pts if math.dist(spot, q) <= 30)
    RS.call(st, "place_at", [me, spot[0] + 2.0, spot[1]], admin, "admin")
    time.sleep(3)
    out = V.run_dir(st["run"])
    ta, ev_admin = RS.stream(st["db"], admin, ["SELECT * FROM doing"], a.seconds, out / f"doing-deltas-{tag}-admin.jsonl")
    tp, ev_player = RS.stream(st["db"], tok, ["SELECT * FROM seen_doing"], a.seconds, out / f"doing-deltas-{tag}-player.jsonl")
    clock0 = RS.sql(st, "SELECT tick, last_ms FROM clock", admin)[0]
    ta.join(timeout=a.seconds + 60)
    tp.join(timeout=a.seconds + 60)
    clock1 = RS.sql(st, "SELECT tick, last_ms FROM clock", admin)[0]
    world = RS.sql(st, "SELECT * FROM world", admin)[0]
    seen = len(RS.sql(st, "SELECT id FROM seen_characters", tok))
    res = {"db": st["db"], "what": tag, "seconds": a.seconds, "battle": a.battle, "people_within_30m": near, "player_sees": seen,
           "ticks": clock1["tick"] - clock0["tick"], "hour_ms": world.get("day_ms"),
           "doing (owner)": count(ev_admin, "doing", a.seconds), "seen_doing (player)": count(ev_player, "seen_doing", a.seconds)}
    (out / f"doing-deltas-{tag}.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
