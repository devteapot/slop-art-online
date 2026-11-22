#!/usr/bin/env python3
"""The blow-order diagnostic (docs/BLOW_ORDER.md; branch blow-order, not for main): identical
spear duellists (`spawn_duel`, a fixture) on a scratch world, with the lower id alternately west
and east, read back from the module log lines the branch adds (`duel windup|complete|blow|drop`,
in the order each tick resolves them). Python standard library and docker.

    blow_order.py run --db verify-bo-b --container C --url http://127.0.0.1:P --out DIR \
                      [--batches 8] [--per-batch 24] [--defend none,block,dodge] [--between 0,1,2,3] \
                      [--hold 0] [--seed 1]
    blow_order.py analyse --out DIR      (again, from DIR/duels.json and DIR/module.log)

`run`: per batch, every living character is killed, then `--per-batch` pairs are spawned on a
grid 25 tiles apart (beyond a person's 11-tile sight), each with its own gap (2.5–6 tiles), id gap
(`between` + 1), defence and side of the lower id (alternating). With `--hold MS` the east
duellist waits and its attack graph is installed MS ms later (a jittered offset start: no tie at
the first exchange). A batch ends when every pair has a dead duellist or after 150 s. The module
log is then read whole and each pair's events are taken by its two ids.
"""
import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import det_compare  # noqa: E402  (its Server: HTTP as the container CLI's identity, the owner)

# Offsets from spawn_battle's spot (55, 60) on a 96-tile map: 16 spots 25 tiles apart.
GRID = [(dx, dy) for dx in (-45, -20, 5, 30) for dy in (-50, -25, 0, 25)]
LINE = re.compile(r"duel (windup|complete|blow|drop|dodged) (.*)")


def graph(other, defend):
    guard = f'{{"if":{{"cond":{{"threatened":true}},"then":{{"do":{{"skill":"{defend}"}}}}}}}},' if defend else ""
    return f'{{"first":{{"label":"combat","children":[{guard}{{"do":{{"skill":"attack","target":{{"id":{other}}}}}}}]}}}}'


def kv(s):
    return {k: v for k, v in (p.split("=", 1) for p in s.split() if "=" in p)}


def module_log(srv):
    r = srv.newest_replica()
    return srv.replica_log(r)


def run(a):
    srv = det_compare.Server(a.container, a.url)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(a.seed)
    defends = ["" if d == "none" else d for d in a.defend.split(",")]
    betweens = [int(b) for b in a.between.split(",")]
    specs = []
    k = 0
    for batch in range(a.batches):
        for who in srv.sql(a.db, "SELECT id FROM character WHERE alive = true"):
            srv.call(a.db, "kill", [who["id"], "cleared for the duel fixture"])
        spots = GRID[:]
        rnd.shuffle(spots)
        made = []
        for i in range(a.per_batch):
            lo_gap, hi_gap = (float(x) for x in a.gap.split(","))
            spec = {"batch": batch, "gap": round(rnd.uniform(lo_gap, hi_gap), 2), "between": betweens[k % len(betweens)],
                    "defend": defends[(k // len(betweens)) % len(defends)], "low_west": (k // (len(betweens) * len(defends))) % 2 == 0,
                    "east_first": (k // (2 * len(betweens) * len(defends))) % 2 == 1 if a.vary_first else False,
                    "hold_ms": a.hold, "hp": a.hp}
            k += 1
            for _ in range(len(spots)):
                dx, dy = spots.pop()
                jx, jy = rnd.uniform(-3, 3), rnd.uniform(-3, 3)
                code, body = srv.http(f"/v1/database/{a.db}/call/spawn_duel", [spec["gap"], dx + jx, dy + jy, spec["between"], spec["low_west"], a.hold > 0, spec["defend"], a.hp, spec["east_first"]])
                if code == 200:
                    break
            else:
                break
            rows = srv.sql(a.db, "SELECT id, name FROM character WHERE alive = true")
            lo = max(r["id"] for r in rows if r["name"] == "DuelLow")
            hi = max(r["id"] for r in rows if r["name"] == "DuelHigh")
            spec.update(lo=lo, hi=hi, west=lo if spec["low_west"] else hi, east=hi if spec["low_west"] else lo)
            if a.hold > 0:
                jitter = a.hold * rnd.uniform(0.5, 1.5) / 1000.0
                time.sleep(jitter)
                srv.call(a.db, "set_behavior", [spec["east"], graph(spec["west"], spec["defend"])])
                spec["held_s"] = round(jitter, 3)
            made.append(spec)
        specs += made
        print(f"batch {batch}: {len(made)} duels", flush=True)
        end = time.time() + 150
        while time.time() < end:
            alive = {r["id"] for r in srv.sql(a.db, "SELECT id FROM character WHERE alive = true")}
            open_ = [s for s in made if s["lo"] in alive and s["hi"] in alive]
            if not open_:
                break
            time.sleep(2)
        print(f"  undecided after wait: {len(open_)}", flush=True)
        (out / "duels.json").write_text(json.dumps(specs, indent=1))
    time.sleep(3)
    # A busy module's log lands late: read until two reads agree.
    prev = None
    for _ in range(10):
        log = module_log(srv)
        if log == prev:
            break
        prev = log
        time.sleep(3)
    (out / "module.log").write_text("\n".join(l for l in log.splitlines() if '"duel ' in l or "spawn_duel" in l))
    analyse(a)


def events(out):
    ev = []
    for n, line in enumerate((out / "module.log").read_text().splitlines()):
        try:
            msg = json.loads(line)["message"]
        except (ValueError, KeyError):
            continue
        m = LINE.match(msg)
        if m:
            d = kv(m.group(2))
            d["kind"], d["n"] = m.group(1), n
            ev.append(d)
    return ev


def pair_report(s, ev):
    lo, hi = s["lo"], s["hi"]
    ids = {str(lo), str(hi)}
    mine = [e for e in ev if (e.get("id") in ids and e.get("skill") in ("attack", "block", "dodge")) or (e.get("a") in ids and e.get("v") in ids)]
    wind = [e for e in mine if e["kind"] == "windup" and e["skill"] == "attack"]
    blows = [e for e in mine if e["kind"] in ("blow", "dodged")]
    kills = [e for e in blows if e.get("dead") == "true"]
    r = {k: s.get(k) for k in ("batch", "lo", "hi", "west", "between", "defend", "low_west", "east_first", "gap", "hold_ms", "hp")}
    r["d"] = hi - lo
    r["blows"] = len([b for b in blows if b["kind"] == "blow"])
    # Exchanges: attack windups by both whose ends coincide exactly (a same-tick tie).
    ends = {}
    for w in wind:
        ends.setdefault(w["ends"], []).append(w["id"])
    tied = [e for e, who in ends.items() if len(set(who)) == 2]
    r["windups"] = len(wind)
    r["tied_exchanges"] = len(tied)
    # In each tied tick, whose blow resolved first (the first `complete` line of the two).
    first_in_tie = []
    for e in tied:
        comp = [c for c in mine if c["kind"] in ("complete", "drop") and c.get("ends") == e and c.get("skill") == "attack"]
        if comp:
            first_in_tie.append(int(comp[0]["id"]))
    r["tie_first_lo"] = sum(1 for x in first_in_tie if x == lo)
    r["tie_first_hi"] = sum(1 for x in first_in_tie if x == hi)
    r["tie_first_west"] = sum(1 for x in first_in_tie if x == s["west"])
    # Who started the first windup (strictly earlier), and the leader of the last exchange.
    if wind:
        t0 = min(int(w["t"]) for w in wind)
        first = {int(w["id"]) for w in wind if int(w["t"]) == t0}
        r["first_windup"] = "both" if len(first) == 2 else ("lo" if lo in first else "hi")
    if not kills:
        r["winner"] = None
        r["decided_by"] = "undecided"
        return r
    k = kills[0]
    killer, victim, t = int(k["a"]), int(k["v"]), k["t"]
    r["winner"] = "lo" if killer == lo else "hi"
    r["winner_west"] = killer == s["west"]
    # The killing blow's windup, and the loser's last attack windup that never landed (`die`
    # deletes a dead character's activity, so the tick finds nothing due for it).
    kw = [w for w in wind if int(w["id"]) == killer and int(w["ends"]) <= int(t)]
    kend = int(kw[-1]["ends"]) if kw else None
    landed = {(b["a"], b["t"]) for b in blows}
    pending = [w for w in wind if int(w["id"]) == victim and int(w["t"]) <= int(t)]
    pending = [w for w in pending if not any(a_ == str(victim) and int(w["ends"]) <= int(t_) for a_, t_ in landed if int(t_) >= int(w["t"]))]
    lend = int(pending[-1]["ends"]) if pending else None
    if lend is not None and kend is not None and lend == kend:
        r["decided_by"] = "tie"  # the loser's blow was due at the same moment and never landed
    elif lend is not None and lend <= int(t):
        r["decided_by"] = "same_tick_earlier_end"  # due by this tick, later than the killer's (fair)
    else:
        r["decided_by"] = "lead"
    if lend is not None and kend is not None:
        r["loser_pending_end_minus_killer_end_ms"] = lend - kend
    return r


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None, None)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (round(p, 3), round(c - h, 3), round(c + h, 3))


def analyse(a):
    out = Path(a.out)
    specs = json.loads((out / "duels.json").read_text())
    ev = events(out)
    rows = [pair_report(s, ev) for s in specs]
    (out / "pairs.json").write_text(json.dumps(rows, indent=1))
    summary = {}

    def add(key, r):
        g = summary.setdefault(key, {"n": 0, "decided": 0, "lo_won": 0, "west_won": 0, "first_installed_won": 0, "tie": 0, "lo_won_tie": 0, "west_won_tie": 0, "lead": 0, "lo_won_lead": 0,
                                     "same_tick_earlier_end": 0, "tied_exchanges": 0, "tie_first_lo": 0, "tie_first_west": 0})
        g["n"] += 1
        g["tied_exchanges"] += r["tied_exchanges"]
        g["tie_first_lo"] += r["tie_first_lo"]
        g["tie_first_west"] += r["tie_first_west"]
        if r["winner"]:
            g["decided"] += 1
            g["lo_won"] += r["winner"] == "lo"
            g["west_won"] += r["winner_west"]
            g["first_installed_won"] += r["winner_west"] != bool(r.get("east_first"))
            g[r["decided_by"]] += 1
            if r["decided_by"] == "tie":
                g["lo_won_tie"] += r["winner"] == "lo"
                g["west_won_tie"] += r["winner_west"]
            if r["decided_by"] == "lead":
                g["lo_won_lead"] += r["winner"] == "lo"

    for r in rows:
        add("all", r)
        add(f"d={r['d']}", r)
        add(f"d%4={r['d'] % 4}", r)
        add(f"defend={r['defend'] or 'none'}", r)
        add(f"east_first={r.get('east_first')}", r)
    for g in summary.values():
        g["lo_win_rate"] = wilson(g["lo_won"], g["decided"])
        g["west_win_rate"] = wilson(g["west_won"], g["decided"])
        g["first_installed_win_rate"] = wilson(g["first_installed_won"], g["decided"])
        g["lo_win_rate_tie"] = wilson(g["lo_won_tie"], g["tie"])
        g["lo_win_rate_lead"] = wilson(g["lo_won_lead"], g["lead"])
        g["tie_first_lo_rate"] = wilson(g["tie_first_lo"], g["tied_exchanges"])
        g["tie_first_west_rate"] = wilson(g["tie_first_west"], g["tied_exchanges"])
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    for k in sorted(summary):
        g = summary[k]
        print(f"{k:14} n={g['n']:3} decided={g['decided']:3} tie={g['tie']:3} lead={g['lead']:3} earlier_end={g['same_tick_earlier_end']:2} "
              f"lo_won={g['lo_won']:3} {g['lo_win_rate']} west_won={g['west_won']:3} first_inst_won={g['first_installed_won']:3} | tie: lo {g['lo_won_tie']}/{g['tie']} | lead: lo {g['lo_won_lead']}/{g['lead']} "
              f"| tied exch {g['tied_exchanges']}, first lo {g['tie_first_lo']} west {g['tie_first_west']}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="step", required=True)
    r = sub.add_parser("run")
    r.add_argument("--db", required=True)
    r.add_argument("--container", required=True)
    r.add_argument("--url", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--batches", type=int, default=8)
    r.add_argument("--per-batch", type=int, default=24)
    r.add_argument("--defend", default="none,block,dodge")
    r.add_argument("--between", default="0,1,2,3")
    r.add_argument("--hold", type=int, default=0)
    r.add_argument("--gap", default="2.5,6.0", help="min,max tiles between the two")
    r.add_argument("--hp", type=float, default=0.0, help="both healths (0: as spawned; 5: one blow kills)")
    r.add_argument("--vary-first", action="store_true", help="alternate whose graph is installed first (west or east)")
    r.add_argument("--seed", type=int, default=1)
    s = sub.add_parser("analyse")
    s.add_argument("--out", required=True)
    a = ap.parse_args()
    return {"run": run, "analyse": analyse}[a.step](a)


if __name__ == "__main__":
    sys.exit(main())
