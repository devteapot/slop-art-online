#!/usr/bin/env python3
"""The side-asymmetry 2x2 (docs/SIDE_ASYMMETRY.md, branch side-asymmetry): in the two-sided melee with block and dodge
mixed within each side and no heed, does the side with the lower ids, or the side dealt one set of
places, break more often? Free: no mind, no model.

  side_swap.py run --container C --url URL --wasm MOD.wasm --out DIR
                   [--cells i0p0,i0p1,i1p0,i1p1] [--fighters 60] [--replicates 10]
                   [--layout-base 1000] [--parallel 4] [--minutes 6] [--side-floor 0.2]
  side_swap.py report DIR... [--json OUT]

Needs the diagnostic reducer `spawn_battle_sides_diag(n, sides, first, place, layout)`: apply
`living/tools/side_swap_diag.patch` (not committed into the module, so the bindings stay as they
are) and build the module with LIVING_SEED=cullet. A cell `i<f>p<q>`: `first` f (i0: Side A
is made first in every pair, so it holds the lower id of each pair; i1: Side B) and `place` q (p0:
Side A takes slot 0 of every pair of places, "position 1"; p1: Side B does). Replicate r uses the
fixed layout `layout-base + r` in every cell, so the four cells of a replicate share the same set
of places and only deal them (and the ids) differently.

Each run publishes a fresh `verify-sideasym-*` world on the given private server, waits for
genesis, pauses it, spawns the sides, unpauses and samples every 2 s (alive, bodies, skill uses)
until a side is down to `side-floor` of its fighters or `minutes` of world time pass. It then
pauses the world, writes its rows and deletes it (paused first and confirmed: world_delete.py).
"""
import argparse
import concurrent.futures
import json
import math
import random
import statistics
import subprocess
import sys
import threading
import time
from collections import defaultdict
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import det_compare  # noqa: E402  (Server: the CLI, SQL and calls of one private server)
import genesis_wait  # noqa: E402
import world_delete  # noqa: E402

lock = threading.Lock()
TIMES = (30, 60, 90, 120, 180, 300)


def cell(c):
    return int(c[1]), int(c[3])


def pos(b, ms):
    dt = max(0.0, (ms - b["t_ms"]) / 1000.0)
    return b["x"] + b["vx"] * dt, b["y"] + b["vy"] * dt


def one(a, c, rep, out):
    first, place = cell(c)
    layout = a.layout_base + rep
    S = det_compare.Server(a.container, a.url)
    db = f"verify-sideasym-{a.fighters}-{c}-n{rep}-{time.strftime('%H%M%S')}"
    d = out / f"f{a.fighters}-{c}-n{rep}"
    d.mkdir(parents=True, exist_ok=True)
    log = lambda m: (d / "actions.log").open("a").write(time.strftime("%H:%M:%S ") + m + "\n")
    with lock:
        S.cli("publish", "-s", "local", "-b", f"/wasm/{a.wasm}", db, "--delete-data", "-y")
        replica = S.newest_replica()
    log(f"published {db} from {a.wasm}, replica {replica}")
    try:
        for attempt in range(10):
            try:
                genesis_wait.wait_ready(S.url, db, S.token())
                break
            except OSError:
                if attempt == 9:
                    raise
                time.sleep(5)
        S.call(db, "set_paused", [True])
        before = {r["id"] for r in S.sql(db, "SELECT id FROM character")}
        S.call(db, "spawn_battle_sides_diag", [a.fighters, 2, first, place, layout])
        sides = {c_["id"]: c_["name"] for c_ in S.sql(db, "SELECT id, name FROM community") if c_["name"] in ("Side A", "Side B")}
        member = {m["member"]: sides[m["community"]] for m in S.sql(db, "SELECT member, community FROM membership") if m["community"] in sides}
        made = [r["id"] for r in S.sql(db, "SELECT id FROM character") if r["id"] not in before]
        side_a = sorted(i for i in made if member.get(i) == "Side A")
        side_b = sorted(i for i in made if member.get(i) == "Side B")
        assert len(side_a) == len(side_b) == a.fighters // 2, (len(side_a), len(side_b))
        fighters = set(side_a) | set(side_b)
        born = max(r["born_ms"] for r in S.sql(db, "SELECT id, born_ms FROM character") if r["id"] in fighters)
        bodies0 = {b["id"]: pos(b, born) for b in S.sql(db, "SELECT id, x, y, t_ms, vx, vy FROM body") if b["id"] in fighters}
        low = "A" if min(side_a) < min(side_b) else "B"
        (d / "roles.json").write_text(json.dumps({"db": db, "cell": c, "first": first, "place": place, "layout": layout, "rep": rep, "fighters": a.fighters,
                                                   "side_a": side_a, "side_b": side_b, "low_id_side": low, "pos1_side": "A" if place == 0 else "B",
                                                   "spawn": {str(k): v for k, v in bodies0.items()}, "replica": replica, "born_ms": born}))
        S.call(db, "set_paused", [False])
        wall0 = time.time()
        # The world's clock stands while paused: the fight starts at the first tick after the unpause.
        while True:
            t0 = S.sql(db, "SELECT last_ms FROM clock")[0]["last_ms"]
            if t0 > born:
                break
            time.sleep(0.05)
        log(f"unpaused; side A {len(side_a)}, side B {len(side_b)}; first {first} place {place} layout {layout}")
        broke, samples, uses = None, [], {}
        while True:
            time.sleep(2)
            ck = S.sql(db, "SELECT last_ms, tick FROM clock")[0]
            now = ck["last_ms"]
            alive = {r["id"] for r in S.sql(db, "SELECT id FROM character WHERE alive = true")}
            bodies = {b["id"]: [round(v, 2) for v in pos(b, now)] for b in S.sql(db, "SELECT id, x, y, t_ms, vx, vy FROM body") if b["id"] in fighters}
            for u in S.sql(db, "SELECT id, actor, skill, target, at_ms, accepted_ms, outcome, outcome_ms FROM skill_use"):
                if u["actor"] in fighters:
                    uses[u["id"]] = u
            na, nb = sum(1 for i in side_a if i in alive), sum(1 for i in side_b if i in alive)
            samples.append({"ms": now, "tick": ck["tick"], "wall": round(time.time() - wall0, 2), "a": na, "b": nb, "bodies": {str(k): v for k, v in bodies.items() if k in alive}})
            if na <= a.side_floor * len(side_a) or nb <= a.side_floor * len(side_b):
                broke = "A" if na <= a.side_floor * len(side_a) else "B"
                break
            if now - t0 >= a.minutes * 60_000:
                break
        S.call(db, "set_paused", [True])
        for u in S.sql(db, "SELECT id, actor, skill, target, at_ms, accepted_ms, outcome, outcome_ms FROM skill_use"):
            if u["actor"] in fighters:
                uses[u["id"]] = u
        chars = S.sql(db, "SELECT id, alive, died_ms, cause FROM character")
        (d / "characters.json").write_text(json.dumps([x for x in chars if x["id"] in fighters]))
        (d / "uses.json").write_text(json.dumps(sorted(uses.values(), key=lambda u: u["id"])))
        (d / "summary.json").write_text(json.dumps({"t0": t0, "end": samples[-1]["ms"] if samples else t0, "broke": broke, "samples": samples}))
        log(f"ended: broke {broke}; {len(uses)} skill uses; world {round((samples[-1]['ms'] - t0) / 1000)} s in {samples[-1]['wall']} s wall")
    finally:
        cli = lambda *args: subprocess.run(["docker", "exec", "-i", a.container, "spacetime", *args], capture_output=True, text=True, timeout=600)
        deleted, why = world_delete.cli_pause_and_delete(cli, db)
        log(f"delete {db}: {why}")


def run(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cells = a.cells.split(",")
    plan = [(c, r) for r in range(1, a.replicates + 1) for c in cells]
    with concurrent.futures.ThreadPoolExecutor(a.parallel) as ex:
        futs = {ex.submit(one, a, c, r, out): (c, r) for c, r in plan}
        for f in concurrent.futures.as_completed(futs):
            c, r = futs[f]
            try:
                f.result()
                print(f"{time.strftime('%H:%M:%S')} {c} r{r} done", flush=True)
            except Exception as e:  # noqa: BLE001 - one run's failure is recorded, the rest go on
                print(f"{time.strftime('%H:%M:%S')} {c} r{r} FAILED: {e}", flush=True)
                (out / f"f{a.fighters}-{c}-n{r}").mkdir(parents=True, exist_ok=True)
                (out / f"f{a.fighters}-{c}-n{r}" / "failed.txt").write_text(repr(e))
    return 0


# ---- report ---------------------------------------------------------------------------------------

def landed(u):
    """A blow that struck its mark unguarded: `hit for N` or `killed … (N)`."""
    o = u["outcome"] or ""
    return o.startswith("hit for") or o.startswith("killed")


def damage(u):
    """Health taken by an attack: `hit for N`, `killed … (N)` or `blocked, N got through`."""
    import re
    o = u["outcome"] or ""
    m = re.match(r"hit for (\d+)|killed .*\((\d+)\)|blocked, (\d+) got through", o)
    return int(next(g for g in m.groups() if g)) if m else 0


def measure(d):
    d = Path(d)
    roles = json.loads((d / "roles.json").read_text())
    summ = json.loads((d / "summary.json").read_text())
    uses = json.loads((d / "uses.json").read_text())
    A, B = set(roles["side_a"]), set(roles["side_b"])
    side = {i: "A" for i in A} | {i: "B" for i in B}
    t0, end = summ["t0"], summ["end"]
    low, p1 = roles["low_id_side"], roles["pos1_side"]
    other = {"A": "B", "B": "A"}

    def dead(sec=None):
        xs = summ["samples"] if sec is None else [q for q in summ["samples"] if q["ms"] - t0 <= sec * 1000]
        q = xs[-1]
        return {"A": len(A) - q["a"], "B": len(B) - q["b"]}

    def diff(s, sec=None):  # s's dead less the other's
        x = dead(sec)
        return x[s] - x[other[s]]

    hits = [u for u in uses if u["skill"] == "attack" and landed(u) and side.get(u["actor"]) and side.get(u["target"]) and side[u["actor"]] != side[u["target"]]]
    hits.sort(key=lambda u: u["outcome_ms"])
    blows = {s: sum(1 for u in hits if side[u["actor"]] == s) for s in "AB"}
    dealt = {s: sum(damage(u) for u in uses if u["skill"] == "attack" and side.get(u["actor"]) == s and side.get(u["target"]) and side[u["target"]] != s) for s in "AB"}
    tries = {s: sum(1 for u in uses if u["skill"] == "attack" and u["accepted_ms"] and side.get(u["actor"]) == s) for s in "AB"}
    spawn = {int(k): v for k, v in roles["spawn"].items()}
    cx = statistics.mean(p[0] for p in spawn.values())
    cy = statistics.mean(p[1] for p in spawn.values())
    geo = {}
    for s, mem in (("A", A), ("B", B)):
        foes = B if s == "A" else A
        geo[s] = {"to_centre": statistics.mean(math.dist(spawn[i], (cx, cy)) for i in mem),
                  "nearest_foe": statistics.mean(min(math.dist(spawn[i], spawn[j]) for j in foes) for i in mem),
                  "foes_within_3": statistics.mean(sum(1 for j in foes if math.dist(spawn[i], spawn[j]) <= 3) for i in mem),
                  "friends_within_3": statistics.mean(sum(1 for j in mem if j != i and math.dist(spawn[i], spawn[j]) <= 3) for i in mem)}
    first = hits[0] if hits else None
    first_by = {s: next(((u["outcome_ms"] - t0) / 1000 for u in hits if side[u["actor"]] == s), None) for s in "AB"}
    fp = spawn.get(first["actor"]) if first else None
    return {"dir": str(d), "cell": roles["cell"], "rep": roles["rep"], "layout": roles["layout"], "fighters": roles["fighters"], "broke": summ["broke"],
            "low": low, "pos1": p1, "duration_s": round((end - t0) / 1000, 1),
            "dead": dead(), "A_minus_B": {str(t): diff("A", t) for t in TIMES} | {"end": diff("A")},
            "low_minus_high": {str(t): diff(low, t) for t in TIMES} | {"end": diff(low)},
            "pos1_minus_pos2": {str(t): diff(p1, t) for t in TIMES} | {"end": diff(p1)},
            "blows": blows, "damage": dealt, "attacks": tries, "first_contact_s": round((first["outcome_ms"] - t0) / 1000, 2) if first else None,
            "first_blow_side": side[first["actor"]] if first else None, "first_blow_by_side_s": first_by,
            "first_contact_from_centre": round(math.dist(fp, (cx, cy)), 2) if fp else None, "geo": geo,
            "outcomes": sorted({(u["outcome"] or "")[:20] for u in uses})[:40]}


def binom_p(k, n):
    if n == 0:
        return None
    tail = sum(comb(n, i) for i in range(max(k, n - k), n + 1)) / 2 ** n
    return min(1.0, 2 * tail) if k != n - k else 1.0


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(c - h, 3), round(c + h, 3)]


def boot_mean(xs, n=4000, seed=7):
    if not xs:
        return None
    r = random.Random(seed)
    ms = sorted(statistics.mean(r.choice(xs) for _ in xs) for _ in range(n))
    return [round(statistics.mean(xs), 2), round(ms[int(0.025 * n)], 2), round(ms[int(0.975 * n)], 2)]


def factor(rs, who):
    """A factor's side (`low` or `pos1`) against the other: broke counts, its dead less the other's."""
    key = {"low": "low_minus_high", "pos1": "pos1_minus_pos2", "A": "A_minus_B"}[who]
    dec = [r for r in rs if r["broke"]]
    k = sum(1 for r in dec if r["broke"] == (r[who] if who != "A" else "A"))
    out = {"n": len(rs), "decided": len(dec), "its_side_broke": k, "share": round(k / len(dec), 3) if dec else None, "wilson95": wilson(k, len(dec)), "sign_p": binom_p(k, len(dec))}
    for t in [str(t) for t in TIMES] + ["end"]:
        xs = [r[key][t] for r in rs]
        out[f"dead_diff_{t}"] = boot_mean(xs)
    xs = [r["blows"][r[who] if who != "A" else "A"] - r["blows"][{"A": "B", "B": "A"}[r[who] if who != "A" else "A"]] for r in rs]
    out["blows_diff"] = boot_mean(xs)
    me = lambda r: r[who] if who != "A" else "A"
    out["damage_diff"] = boot_mean([r["damage"][me(r)] - r["damage"][{"A": "B", "B": "A"}[me(r)]] for r in rs])
    out["first_blow_by_its_side"] = sum(1 for r in rs if r["first_blow_side"] == me(r))
    return out


def report(a):
    dirs = [p for d in a.dirs for p in (sorted(Path(d).iterdir()) if not (Path(d) / "roles.json").exists() else [Path(d)]) if (p / "summary.json").exists()]
    res = [measure(d) for d in dirs]
    out = {"instances": res}
    for n in sorted({r["fighters"] for r in res}):
        rs = [r for r in res if r["fighters"] == n]
        block = {"cells": {}, "factors": {}}
        for c in sorted({r["cell"] for r in rs}):
            cr = [r for r in rs if r["cell"] == c]
            dec = [r for r in cr if r["broke"]]
            block["cells"][c] = {"n": len(cr), "low": cr[0]["low"], "pos1": cr[0]["pos1"], "A_broke": sum(1 for r in dec if r["broke"] == "A"), "B_broke": sum(1 for r in dec if r["broke"] == "B"),
                                 "neither": len(cr) - len(dec), "A_minus_B_dead_60": boot_mean([r["A_minus_B"]["60"] for r in cr]),
                                 "A_minus_B_dead_end": boot_mean([r["A_minus_B"]["end"] for r in cr]),
                                 "A_blows_minus_B": boot_mean([r["blows"]["A"] - r["blows"]["B"] for r in cr]),
                                 "A_damage_minus_B": boot_mean([r["damage"]["A"] - r["damage"]["B"] for r in cr]),
                                 "first_contact_s": statistics.median([r["first_contact_s"] for r in cr if r["first_contact_s"] is not None] or [0]),
                                 "first_blow_A": sum(1 for r in cr if r["first_blow_side"] == "A"), "duration_s_median": statistics.median(r["duration_s"] for r in cr)}
        for f in ("low", "pos1", "A"):
            block["factors"][f] = factor(rs, f)
        # Interaction: does the id effect depend on the places (and the reverse)? Low-id advantage by place deal.
        block["low_by_place"] = {p: boot_mean([r["low_minus_high"]["end"] for r in rs if r["cell"][2:] == p]) for p in ("p0", "p1")}
        # How much the layout decides: per layout, the pos1 side's dead less the other's in its four cells.
        by_layout = defaultdict(list)
        for r in rs:
            by_layout[r["layout"]].append(r["pos1_minus_pos2"]["end"])
        lay = {k: v for k, v in by_layout.items() if len(v) >= 2}
        means = [statistics.mean(v) for v in lay.values()]
        within = [statistics.pvariance(v) for v in lay.values()]
        block["layout"] = {"layouts": len(lay), "var_between_layout_means": round(statistics.pvariance(means), 2) if len(means) > 1 else None,
                           "mean_var_within_layout": round(statistics.mean(within), 2) if within else None,
                           "same_sign_all_cells": sum(1 for v in lay.values() if all(x > 0 for x in v) or all(x < 0 for x in v))}
        # Geometry: does the side nearer the centre, or with more foes in reach at spawn, die less?
        g = []
        for r in rs:
            gA, gB = r["geo"]["A"], r["geo"]["B"]
            g.append((gA["to_centre"] - gB["to_centre"], gA["foes_within_3"] - gB["foes_within_3"], gA["friends_within_3"] - gB["friends_within_3"], r["A_minus_B"]["end"]))
        def corr(i):
            xs, ys = [x[i] for x in g], [x[3] for x in g]
            if len(xs) < 3 or statistics.pstdev(xs) == 0 or statistics.pstdev(ys) == 0:
                return None
            return round(statistics.correlation(xs, ys), 3)
        block["geometry_corr_with_A_minus_B_dead_end"] = {"to_centre": corr(0), "foes_within_3": corr(1), "friends_within_3": corr(2)}
        out[f"fighters_{n}"] = block
        print(f"\n=== {n} fighters ({len(rs)} runs)")
        for c, row in block["cells"].items():
            print(f"  {c} low-id {row['low']} pos1 {row['pos1']}: n {row['n']} A broke {row['A_broke']} B broke {row['B_broke']} neither {row['neither']}; "
                  f"A-B dead 60s {row['A_minus_B_dead_60']} end {row['A_minus_B_dead_end']}; A-B blows {row['A_blows_minus_B']}; first contact {row['first_contact_s']} s; first blow by A {row['first_blow_A']}")
        for f, row in block["factors"].items():
            print(f"  factor {f}: {json.dumps(row)}")
        print(f"  low-id side's dead less other's at end, by place deal: {block['low_by_place']}")
        print(f"  layout: {block['layout']}")
        print(f"  geometry: {block['geometry_corr_with_A_minus_B_dead_end']}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--container", required=True)
    r.add_argument("--url", required=True)
    r.add_argument("--wasm", required=True, help="the module file in the server's /wasm mount")
    r.add_argument("--out", required=True)
    r.add_argument("--cells", default="i0p0,i0p1,i1p0,i1p1")
    r.add_argument("--fighters", type=int, default=60)
    r.add_argument("--replicates", type=int, default=10)
    r.add_argument("--layout-base", type=int, default=1000)
    r.add_argument("--parallel", type=int, default=4)
    r.add_argument("--minutes", type=float, default=6)
    r.add_argument("--side-floor", type=float, default=0.2)
    r.set_defaults(f=run)
    p = sub.add_parser("report")
    p.add_argument("dirs", nargs="+")
    p.add_argument("--json")
    p.set_defaults(f=report)
    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    raise SystemExit(main())
