#!/usr/bin/env python3
"""E4's two-sided melee (docs/ATTENTION_E4.md; docs/ATTENTION_BUDGET.md v2 §8.2): does heed
capacity matter in a fight between people? Free: no mind runs, no model.

  heed_e4_melee.py run --container C --url URL --wasm-dir DIR --wasm MOD.wasm --out DIR
                       [--arms off,formula,cap4,...] [--replicates 6] [--parallel 3] [--minutes 5]
  heed_e4_melee.py report DIR... [--control cap16] [--json OUT]

Each run publishes a fresh `verify-melee-*` world of the module (built with LIVING_SEED=cullet) on
the given private server, waits for genesis, pauses it, stages `spawn_battle_sides(60, 2)` (two
sides of 30 spear fighters on Cullet's arrival plaza: block or dodge when threatened, else attack
the nearest enemy; no refills), installs the shipped script with Cullet's laws and, for a capped
arm, `heed_capacity` fixed at N for Side A's fighters (Side B and everyone else on the shipped
formula), sets `heed_on` (ceiling 32) and the diagnostic `heed_trace`, unpauses, and runs until a
side breaks (at most 20% of its fighters alive) or `--minutes` of world time pass. It then pauses
the world, copies the `heed …` lines of its module log and the fighters' rows, and deletes the
world (paused first and confirmed: world_delete.py).

Measures, Side A the subjects: deaths by side and who broke; first blows on Side A from someone
not an individual at its windup (in sight, in the throng), and out of sight, per Side A
fighter-minute; repeated invisible blows (must be 0); reactions (blocks and dodges per windup aimed
at Side A); Side A's landed blows; the time to break; Side A's capacity, share of passes at capacity
and the wound spiral. The decision rule of docs/PACK_MIND.md §5.5 against `--control`.
"""
import argparse
import concurrent.futures
import json
import statistics
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import det_compare  # noqa: E402  (Server: the CLI, SQL and calls of one private server)
import genesis_wait  # noqa: E402
import heed_e4  # noqa: E402
import install_script  # noqa: E402
import pack_arena  # noqa: E402
import world_delete  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CAP_OLD = "fn heed_capacity(a) {"
FIGHTERS = 60
lock = threading.Lock()


def script_for(arm, side_a):
    src = (ROOT / "living/scripts/skills.rhai").read_text()
    if arm.startswith("cap"):
        n = float(arm[3:])
        ids = ", ".join(str(i) for i in sorted(side_a))
        src = src.replace(CAP_OLD, CAP_OLD + f"\n    if a.actor.id in [{ids}] {{ return {n}; }}", 1)
    source, _ = install_script.seed_script("cullet", src)
    return source


def one(a, arm, rep, out):
    S = det_compare.Server(a.container, a.url)
    db = f"verify-melee-{arm}-r{rep}-{time.strftime('%H%M%S')}"
    d = out / f"{arm}-r{rep}"
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
        S.call(db, "spawn_battle_sides", [FIGHTERS, 2])
        sides = {c["id"]: c["name"] for c in S.sql(db, "SELECT id, name FROM community") if c["name"] in ("Side A", "Side B")}
        member = {m["member"]: sides[m["community"]] for m in S.sql(db, "SELECT member, community FROM membership") if m["community"] in sides}
        made = [r["id"] for r in S.sql(db, "SELECT id FROM character") if r["id"] not in before]
        side_a = sorted(i for i in made if member.get(i) == "Side A")
        side_b = sorted(i for i in made if member.get(i) == "Side B")
        assert len(side_a) == len(side_b) == FIGHTERS // 2, (len(side_a), len(side_b))
        source = script_for(arm, side_a)
        code, body = S.http(f"/v1/database/{db}/call/install_script", [source])
        if code != 200:
            raise RuntimeError(f"install_script: {code} {body[:300]}")
        laws = {"heed_trace": True}
        if arm != "off":
            laws.update({"heed_on": True, "heed_ceiling": 32})
        for k, v in laws.items():
            S.call(db, "set_world_law", [k, json.dumps(v)])
        (d / "roles.json").write_text(json.dumps({"db": db, "arm": arm, "rep": rep, "side_a": side_a, "side_b": side_b, "laws": laws, "replica": replica}))
        t0 = S.sql(db, "SELECT last_ms FROM clock")[0]["last_ms"]
        S.call(db, "set_paused", [False])
        log(f"unpaused; side A {len(side_a)}, side B {len(side_b)}; laws {laws}")
        broke, samples = None, []
        while True:
            time.sleep(2)
            now = S.sql(db, "SELECT last_ms FROM clock")[0]["last_ms"]
            alive = {r["id"] for r in S.sql(db, "SELECT id, alive FROM character WHERE alive = true")}
            na, nb = sum(1 for i in side_a if i in alive), sum(1 for i in side_b if i in alive)
            samples.append({"ms": now, "a": na, "b": nb})
            if na <= 0.2 * len(side_a) or nb <= 0.2 * len(side_b):
                broke = "A" if na <= 0.2 * len(side_a) else "B"
                break
            if now - t0 >= a.minutes * 60_000:
                break
        S.call(db, "set_paused", [True])
        chars = S.sql(db, "SELECT id, alive, died_ms, cause FROM character")
        (d / "characters.json").write_text(json.dumps([c for c in chars if c["id"] in side_a or c["id"] in side_b]))
        time.sleep(5)
        lines = []
        for raw in S.replica_log(replica).splitlines():
            try:
                msg = json.loads(raw).get("message", "")
            except ValueError:
                msg = raw
            if "heed " in msg:
                lines.append(msg)
        (d / "heed.log").write_text("\n".join(lines) + "\n")
        (d / "summary.json").write_text(json.dumps({"t0": t0, "end": samples[-1]["ms"] if samples else t0, "broke": broke, "samples": samples}))
        log(f"ended: broke {broke}, {len(lines)} heed lines")
    finally:
        cli = lambda *args: subprocess.run(["docker", "exec", "-i", a.container, "spacetime", *args], capture_output=True, text=True, timeout=600)
        deleted, why = world_delete.cli_pause_and_delete(cli, db)
        log(f"delete {db}: {why}")


def run(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    arms = a.arms.split(",")
    plan = [(arm, r) for r in range(1, a.replicates + 1) for arm in arms]
    with concurrent.futures.ThreadPoolExecutor(a.parallel) as ex:
        futs = {ex.submit(one, a, arm, r, out): (arm, r) for arm, r in plan}
        for f in concurrent.futures.as_completed(futs):
            arm, r = futs[f]
            try:
                f.result()
                print(f"{time.strftime('%H:%M:%S')} {arm} r{r} done", flush=True)
            except Exception as e:  # noqa: BLE001 - one run's failure is recorded, the rest go on
                print(f"{time.strftime('%H:%M:%S')} {arm} r{r} FAILED: {e}", flush=True)
                (out / f"{arm}-r{r}" / "failed.txt").write_text(repr(e))
    return 0


def measure(d, loads=None):
    d = Path(d)
    roles = json.loads((d / "roles.json").read_text())
    summ = json.loads((d / "summary.json").read_text())
    A, B = set(roles["side_a"]), set(roles["side_b"])
    chars = {c["id"]: c for c in json.loads((d / "characters.json").read_text())}
    t0, end = summ["t0"], summ["end"]
    minutes = sum(max(0.0, ((chars[i]["died_ms"] if not chars[i]["alive"] and chars[i]["died_ms"] else end) - t0) / 60000) for i in A if i in chars)
    lines = heed_e4.heed_lines(d)
    blows = [k for t, k, _ in lines if t == "blow"]
    windups = [k for t, k, _ in lines if t == "windup"]
    on_a = [b for b in blows if int(b["v"]) in A and int(b["a"]) in B]
    w_a = [w for w in windups if int(w["v"]) in A and int(w["a"]) in B]
    firsts = [b for b in on_a if b.get("first") == "1"]
    unheeded = [b for b in firsts if b.get("heeded_at_windup") == "0" and b.get("seen_at_windup") == "1"]
    unseen = [b for b in firsts if b.get("seen_at_windup") == "0"]
    invisible = [b for b in on_a if b.get("repeat_in_window") == "1" and b.get("heeded_at_windup") == "0"]
    reacted = sum(1 for b in on_a if b.get("out") in ("blocked", "dodged"))
    by_a = [b for b in blows if int(b["a"]) in A and int(b["v"]) in B]
    passes = defaultdict(list)
    for t, k, _ in lines:
        if t == "pass" and int(k.get("id", 0)) in A:
            passes[int(k["id"])].append((int(k["cap"]), float(k["health"]), int(k["in_sight"]), int(k["picked"])))
    at_cap, spiral = [], []
    for ps in passes.values():
        at_cap.append(sum(1 for c, _, n, p in ps if c > 0 and n > c and p >= c) / len(ps))
        start = ps[0][0]
        if start > 0:
            spiral.append((1 - min(c for c, _, _, _ in ps) / start, 1 - min(h for _, h, _, _ in ps)))
    per = lambda n: round(n / minutes, 4) if minutes > 0 else None
    dead_a = sum(1 for i in A if i in chars and not chars[i]["alive"])
    dead_b = sum(1 for i in B if i in chars and not chars[i]["alive"])
    return {"dir": str(d), "arm": roles["arm"], "broke": summ["broke"], "duration_s": round((end - t0) / 1000, 1),
            "A_dead": dead_a, "B_dead": dead_b, "A_minus_B_dead": dead_a - dead_b,
            "first_unheeded_per_A_min": per(len(unheeded)), "first_unheeded": len(unheeded), "first_unseen": len(unseen), "first_blows": len(firsts),
            "repeat_invisible": len(invisible), "invariant_lines": sum(1 for t, _, _ in lines if t == "invariant"),
            "windups_at_A": len(w_a), "windups_heeded_share": round(sum(1 for w in w_a if w.get("heeded") == "1") / len(w_a), 3) if w_a else None,
            "reactions_per_blow_reaching_A": round(reacted / len(on_a), 3) if on_a else None,
            "A_landed": sum(1 for b in by_a if b.get("out") == "hit"),
            "A_share_at_capacity": heed_e4.med(at_cap), "A_cap_lost": heed_e4.med([x for x, _ in spiral]), "A_health_lost": heed_e4.med([y for _, y in spiral])}


KEYS = ["A_dead", "B_dead", "A_minus_B_dead", "duration_s", "first_unheeded_per_A_min", "first_unseen", "windups_heeded_share",
        "reactions_per_blow_reaching_A", "A_landed", "A_share_at_capacity", "A_cap_lost", "A_health_lost"]


def report(a):
    dirs = [p for d in a.dirs for p in (sorted(Path(d).iterdir()) if not (Path(d) / "roles.json").exists() else [Path(d)]) if (p / "summary.json").exists()]
    results = [measure(d) for d in dirs]
    by = defaultdict(list)
    for r in results:
        by[r["arm"]].append(r)
    table = {}
    for arm, rs in by.items():
        row = {"n": len(rs), "broke": [r["broke"] for r in rs], "repeat_invisible_total": sum(r["repeat_invisible"] + r["invariant_lines"] for r in rs)}
        for k in KEYS:
            vals = [r[k] for r in rs]
            have = [v for v in vals if v is not None]
            row[k] = {"median": heed_e4.med(have), "min": min(have) if have else None, "max": max(have) if have else None, "values": vals}
        table[arm] = row
    out = {"instances": results, "arms": table}
    if a.control:
        out["differs_from_control"] = pack_arena.decide(table, a.control)
    for arm in sorted(table):
        row = table[arm]
        print(f"\n== {arm} (n={row['n']}; broke {row['broke']}; repeated invisible blows {row['repeat_invisible_total']})")
        for k in KEYS:
            v = row[k]
            flag = "  DIFFERS" if a.control and out.get("differs_from_control", {}).get(arm, {}).get(k) else ""
            print(f"  {k:32s} median {v['median']!s:>8}  range {v['min']!s}..{v['max']!s}{flag}")
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
    r.add_argument("--arms", default="off,formula,cap1,cap2,cap4,cap8,cap16,cap32")
    r.add_argument("--replicates", type=int, default=6)
    r.add_argument("--parallel", type=int, default=3)
    r.add_argument("--minutes", type=float, default=5)
    r.set_defaults(f=run)
    p = sub.add_parser("report")
    p.add_argument("dirs", nargs="+")
    p.add_argument("--control")
    p.add_argument("--json")
    p.set_defaults(f=report)
    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    raise SystemExit(main())
