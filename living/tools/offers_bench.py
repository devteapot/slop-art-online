#!/usr/bin/env python3
"""What `my_offers` costs (docs/PERCEPTION.md "Offers"): M players subscribed to it while K
residents and the players keep making trade offers.

On a scratch `verify-client-*` world (the probe connects only to those) launched with
`.agents/skills/verify/scripts/verify.py launch --run client-…`:
joins M player identities near one another, places K adult residents beside them, and holds
one real SDK subscription per player (`SELECT * FROM my_offers`, the verify-client probe at
`.local/living/verify/target-client/debug/verify-client-probe`). It then measures two windows
from the server's per-database metrics: at rest (no offers written), and under load (the
residents offer to the players and the players to one another, about RATE offers a second in
all). For each window it reports `my_offers` refreshes (`view_calls`), their time with and
without materializing (`view_total_time_usec`, `view_call_time_usec`), every view's refreshes,
and the tick's transaction mean (`spacetime_reducer_plus_query_duration_sec{reducer="tick"}`).

    offers_bench.py --run RUN [--players 20] [--residents 60] [--rate 10] [--seconds 60]

Writes `.local/living/verify/RUN/offers-bench.json`. Python standard library only. Tokens stay
in memory. Admin calls (`place_near`, `grant_items`, `set_behavior`, `mind_act`) set the scene
and drive the residents as a mind would.
"""

import argparse
import importlib.util
import json
import random
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("verify", ROOT / ".agents/skills/verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
PROBE = ROOT / ".local/living/verify/target-client/debug/verify-client-probe"


def metrics(dbid):
    text = urllib.request.urlopen(f"{V.URL}/v1/metrics", timeout=30).read().decode()
    out = {}
    for line in text.splitlines():
        if dbid not in line or line.startswith("#"):
            continue
        m = re.match(r'(\w+)\{([^}]*)\} ([0-9.e+-]+)$', line)
        if not m:
            continue
        name, labels, value = m.groups()
        lab = dict(re.findall(r'(\w+)="([^"]*)"', labels))
        if name in ("view_calls", "view_total_time_usec", "view_call_time_usec"):
            out[(name, lab.get("view"))] = float(value)
        elif name.startswith("spacetime_reducer_plus_query_duration_sec_") and lab.get("reducer") in ("tick", "human_act", "mind_act"):
            out[(name, lab["reducer"])] = float(value)
    return out


def window(m0, m1, secs):
    d = lambda k: m1.get(k, 0.0) - m0.get(k, 0.0)
    views = sorted({k[1] for k in m1 if k[0] == "view_calls"})
    calls = {v: d(("view_calls", v)) for v in views}
    tick_n = d(("spacetime_reducer_plus_query_duration_sec_count", "tick"))
    tick_s = d(("spacetime_reducer_plus_query_duration_sec_sum", "tick"))
    n = calls.get("my_offers", 0.0)
    return {
        "seconds": round(secs, 1),
        "my_offers_refreshes": n,
        "my_offers_refreshes_per_s": round(n / secs, 2),
        "my_offers_total_us_per_refresh": round(d(("view_total_time_usec", "my_offers")) / n, 1) if n else None,
        "my_offers_call_us_per_refresh": round(d(("view_call_time_usec", "my_offers")) / n, 1) if n else None,
        "my_offers_total_ms_per_s": round(d(("view_total_time_usec", "my_offers")) / secs / 1000, 3),
        "tick_tx_mean_ms": round(tick_s / tick_n * 1000, 3) if tick_n else None,
        "ticks_per_s": round(tick_n / secs, 1),
        "view_refreshes_per_s": {v: round(c / secs, 2) for v, c in calls.items() if c},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--players", type=int, default=20)
    ap.add_argument("--residents", type=int, default=60)
    ap.add_argument("--rate", type=float, default=10.0)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--rest", type=float, default=20.0)
    a = ap.parse_args()
    st = V.load(a.run)
    db, admin = st["db"], V.admin_token()
    if not db.startswith("verify-client-"):
        sys.exit("only verify-client-* databases (the probe connects only to those)")
    dbid = json.loads(V.http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")

    def sql(q, token=admin):
        code, body = V.http(f"/v1/database/{db}/sql", q, token, raw=True)
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(reducer, args, token=admin):
        code, body = V.http(f"/v1/database/{db}/call/{reducer}", args, token)
        return code

    # M players, near the first.
    players = []
    for i in range(a.players):
        tok = json.loads(V.http("/v1/identity", {})[1])["token"]
        call("join", [f"Bench{i}"], tok)
        me = next(c["id"] for c in sql("SELECT id, alive FROM my_characters", tok) if c["alive"])
        players.append((me, tok))
    anchor = players[0][0]
    for me, _ in players:
        call("set_behavior", [me, json.dumps({"wait": 600})])
        if me != anchor:
            call("place_near", [me, anchor])
        call("grant_items", [me, "berries", 30])
    pids = {p for p, _ in players}
    people = [c["id"] for c in sql("SELECT id, kind, stage, alive, ai FROM character") if c["kind"] == "person" and c["alive"] and c["ai"] and c["stage"] >= 2 and c["id"] not in pids]
    residents = random.Random(7).sample(people, min(a.residents, len(people)))
    for i, r in enumerate(residents):
        call("set_behavior", [r, json.dumps({"wait": 600})])
        call("place_near", [r, players[i % len(players)][0]])
        call("grant_items", [r, "wood", 30])

    # One real subscription per player for the whole bench.
    hold = int(a.rest + a.seconds + 30)
    procs = []
    logs = V.run_dir(a.run) / "offers-bench-probes"
    logs.mkdir(exist_ok=True)
    for me, tok in players:
        req = {"uri": V.URL, "db": db, "token": tok, "queries": ["SELECT * FROM my_offers"], "seconds": hold, "drop_file": None, "until_actor": None}
        p = subprocess.Popen([str(PROBE)], stdin=subprocess.PIPE, stdout=(logs / f"{me}.jsonl").open("w"), stderr=(logs / f"{me}.log").open("w"), text=True)
        p.stdin.write(json.dumps(req))
        p.stdin.close()
        procs.append(p)
    time.sleep(8)
    dead = [p.poll() for p in procs if p.poll() is not None]
    if dead:
        sys.exit(f"{len(dead)} of {len(procs)} subscriptions ended early (exit {dead[:3]})")

    m0, t0 = metrics(dbid), time.time()
    time.sleep(a.rest)
    m1, t1 = metrics(dbid), time.time()
    rest = window(m0, m1, t1 - t0)

    # Load: residents offer to players, players to one another.
    rng = random.Random(11)
    made = {"resident": 0, "player": 0, "refused_http": 0}
    end = time.time() + a.seconds
    interval = 1.0 / a.rate
    m2, t2 = metrics(dbid), time.time()
    i = 0
    while time.time() < end:
        tick0 = time.time()
        if i % 3 != 2:
            r = residents[rng.randrange(len(residents))]
            to = players[rng.randrange(len(players))][0]
            code = call("mind_act", [r, [json.dumps({"do": "offer", "target": {"id": to}, "item": "wood", "qty": 1, "want": "berries", "want_qty": 1})], "offers-bench"])
            made["resident"] += 1
        else:
            (me, tok), (to, _) = rng.sample(players, 2)
            code = call("human_act", [json.dumps({"do": "offer", "target": {"id": to}, "item": "berries", "qty": 1, "want": "wood", "want_qty": 1})], tok)
            made["player"] += 1
        made["refused_http"] += code != 200
        i += 1
        time.sleep(max(0.0, interval - (time.time() - tick0)))
    m3, t3 = metrics(dbid), time.time()
    load = window(m2, m3, t3 - t2)
    alive = sum(p.poll() is None for p in procs)

    offers = sql("SELECT * FROM trade_offer")
    per_player = [len([o for o in offers if o["to"] == p or o["from"] == p]) for p, _ in players]
    sample = sql("SELECT * FROM my_offers", players[0][1])
    for p in procs:
        p.kill()
    report = {
        "db": db, "players": a.players, "residents": len(residents), "rate_target": a.rate,
        "offers_made": made, "standing_offers_at_end": len(offers),
        "my_offers_rows_per_player_at_end": {"min": min(per_player), "max": max(per_player), "mean": round(sum(per_player) / len(per_player), 1)},
        "sample_player_rows": len(sample), "subscriptions_alive_at_end": alive, "rest": rest, "load": load,
        "characters": len(sql("SELECT id FROM character")),
    }
    out = V.run_dir(a.run) / "offers-bench.json"
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
