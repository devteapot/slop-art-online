#!/usr/bin/env python3
"""Ticks a second in a 200-fighter battle by the number of player viewers in it (frame-views,
docs/TICK_RATE.md): whether a dense battle's cost is the players' frames and views.

    battle_viewers.py --label NAME --wasm FILE --load GATE_LOAD --viewers 0,1,4,16
                      [--fighters 200] [--seconds 60] [--warmup 20] [--tiers] [--cues] [--law NAME=VALUE]

For each count: publish fresh as `verify-lookcost-<label>-v<count>-<stamp>` on the worker's own
server (`LIVING_STDB_CONTAINER`, `LIVING_STDB_URL`, as look_cost.py), stage the battle with the
admin's `spawn_battle` (AI fighters within 7 m of the arrival less 20 m, a fight graph: attack the
nearest person, dodge or block when threatened), join that many players over their own WebSocket
connections (gate-load, the gate's subscriptions; `--tiers`/`--cues` as look_cost.py) and stand
them within 6 m of the battle's centre, walking small circles; after the warm-up, the tick count
of the server's own counter over the window. Writes `<out>/battle-viewers.json`. Delete each
database after. Python standard library.
"""
import argparse
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import look_cost as lc  # noqa: E402


def tick_count(ident):
    text = urllib.request.urlopen(f"{lc.URL}/v1/metrics", timeout=60).read().decode()
    for line in text.splitlines():
        if line.startswith("spacetime_reducer_plus_query_duration_sec_count{") and f'"{ident}"' in line and 'reducer="tick"' in line:
            return float(line.rsplit(" ", 1)[1])
    return None


def one(a, n, out):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    db = f"verify-lookcost-{a.label}-v{n}-{stamp}"
    res = {"viewers": n, "fighters": a.fighters, "db": db}
    load = None
    try:
        lc.stdb("publish", "-s", "local", "-b", str(Path("/wasm") / a.wasm), db, "--delete-data", "-y")
        token = lc.admin_token()
        ident = json.loads(lc.http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
        time.sleep(3)
        for law in a.law:
            name, value = law.split("=", 1)
            lc.call(db, "set_world_law", [name, value], token)
        lc.call(db, "spawn_battle", [a.fighters], token)
        land = lc.sql(db, "SELECT * FROM land", token)[0]
        site = (land["arrive_x"], land["arrive_y"] - 20.0)
        if n:
            players = [{"token": lc.new_identity(), "name": f"Watch{i}", "role": "walk"} for i in range(n)]
            load = lc.Proc([a.load, "players"], out / f"players-v{n}.stderr")
            load.send(json.dumps({"uri": lc.URL, "db": db, "events": str(out / f"events-v{n}.jsonl"), "battle": list(site),
                                  "behaviour": {"walk_period_ms": 1500, "rejoin_s": 3}, "players": players, "client": "gate",
                                  "tiers": a.tiers, "cues": a.cues}))
            joined = load.expect("joined", 900)
            for i, p in enumerate(sorted(joined["players"], key=lambda p: p["p"])):
                ang, rr = i * 2.399963, 6.0 * ((i + 0.5) / n) ** 0.5
                try:
                    lc.call(db, "place_at", [p["id"], site[0] + rr * math.cos(ang), site[1] + rr * math.sin(ang)], token)
                except RuntimeError:
                    lc.call(db, "place_at", [p["id"], site[0], site[1] + 8.0], token)
            load.send("placed")
            ready = load.expect("ready", 900)
            res["held_at_ready"] = ready.get("held")
            load.send("go")
        time.sleep(a.warmup)
        c0, t0 = tick_count(ident), time.time()
        time.sleep(a.seconds)
        c1, t1 = tick_count(ident), time.time()
        res["ticks_per_s"] = round((c1 - c0) / (t1 - t0), 2) if c0 is not None and c1 is not None else None
        res["alive_characters"] = lc.sql(db, "SELECT COUNT(*) AS n FROM character WHERE alive = true", token)[0]["n"]
        res["window"] = {"t0": t0, "t1": t1}
        if load:
            load.send("stop")
            try:
                load.expect("done", 300)
            except RuntimeError:
                pass
    finally:
        if load and load.p.poll() is None:
            load.p.terminate()
        lc.stdb("delete", "-s", "local", db, "-y") if db.startswith("verify-lookcost-") else None
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    ap.add_argument("--wasm", required=True)
    ap.add_argument("--load", required=True)
    ap.add_argument("--viewers", default="0,1,4,16")
    ap.add_argument("--fighters", type=int, default=200)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--tiers", action="store_true")
    ap.add_argument("--cues", action="store_true")
    ap.add_argument("--law", action="append", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in (int(x) for x in a.viewers.split(",")):
        rows.append(one(a, n, out))
        print(json.dumps(rows[-1]), flush=True)
    (out / "battle-viewers.json").write_text(json.dumps({"label": a.label, "wasm": a.wasm, "laws": a.law, "rows": rows}, indent=1) + "\n")


if __name__ == "__main__":
    main()
