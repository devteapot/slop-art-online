#!/usr/bin/env python3
"""BATTLE_CONTRACT_CASES' tables (docs/BATTLE_CONTRACT_CASES.md) from .local/cc/runs/<prefix>-*: per arm
the database thread, ticks, the steps' intervals (tick watcher), the human fighters' inputs and deaths,
the AI fallen (keeper refills), and the database thread split by transaction: the tick (Reducer), its
subscription evaluation (Update), input reducers (human_move, use_skill, release_skill, join), the
keep-alive, the rest. Usage: cc_tables.py PREFIX. Writes .local/cc/tables-PREFIX.json."""
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "living/tools"))
import e2_report as e  # noqa: E402

R = ROOT / ".local/gr/runs"  # set by the caller (tables.py)
INPUT = ("human_move", "use_skill", "release_skill", "join", "human_act")


def txn(d, s, reducer, typ=None):
    return sum(v for k, v in d.items() if k.startswith("spacetime_txn_cpu_time_sec_sum{") and f'reducer="{reducer}"' in k and (typ is None or f'txn_type="{typ}"' in k)) / s * 1000


def host_window(t0, t1):
    """From runners.log: the host's busy cores and the runner processes' cores over [t0, t1] (HZ 100),
    and the busiest 10 s of the runners (a job starting shows there)."""
    f = R / "runners.log"
    if not f.exists():
        return {}
    rows = [tuple(float(x) for x in l.split()) for l in open(f) if len(l.split()) == 4]
    w = [r for r in rows if t0 - 2 <= r[0] <= t1 + 2]
    if len(w) < 2:
        return {}
    dt = w[-1][0] - w[0][0]
    busy = (w[-1][1] - w[0][1]) / 100 / dt
    # Runner CPU: the positive steps of the live sum (short-lived listeners restart; a drop is one gone).
    steps = [(b[0], max(0.0, b[2] - a[2]) / 100 / (b[0] - a[0])) for a, b in zip(w, w[1:])]
    run_c = sum(x * 2 for _, x in steps) / dt
    peak = max((sum(x for t, x in steps if t0w <= t < t0w + 10) / max(1, sum(1 for t, _ in steps if t0w <= t < t0w + 10)) for t0w, _ in steps), default=0)
    return {"host_busy_cores": round(busy, 2), "runner_cores": round(run_c, 2), "runner_peak10s_cores": round(peak, 2), "runner_procs_max": int(max(r[3] for r in w))}


def one(d):
    r = e.one(d)
    bv = json.loads((d / "battle-viewers.json").read_text())["rows"][0]
    n = bv["viewers"]
    m = json.loads((d / f"v{n}" / "metrics.json").read_text())
    diff, s = m["diff"], m["seconds"]
    views = sum(v for k, v in diff.items() if k.startswith("view_total_time_usec")) / s / 1000
    reducers = sorted({m.group(1) for k in diff if k.startswith("spacetime_txn_cpu_time_sec_sum{") and (m := re.search(r'reducer="([^"]+)"', k))})
    by = {x: round(txn(diff, s, x), 2) for x in reducers}
    steps = bv.get("steps") or {}
    hw = bv.get("humans_window") or {}
    kw = bv.get("keeper_window") or {}
    out = {"n": n, "humans": bv.get("humans", 0), "walkers": bv.get("walkers", 0), "db": r["db_ms_s"], "ticks": r["ticks_per_s"],
           "tick": txn(diff, s, "tick", "Reducer"), "update": txn(diff, s, "tick", "Update"), "views": views,
           "input": sum(txn(diff, s, x) for x in INPUT), "keepalive": txn(diff, s, "admin_set_vitals"), "by_reducer": by,
           "step_p99": (steps.get("interval_ms") or {}).get("p99"), "step_p50": (steps.get("interval_ms") or {}).get("p50"), "step_max": (steps.get("interval_ms") or {}).get("max"),
           "over25": steps.get("over_25ms_pct"), "skipped": steps.get("grid_skipped"), "steps_per_s": steps.get("steps_per_s"),
           "human_inputs_s": hw.get("inputs_total_per_s"), "human_inputs": hw.get("inputs_per_s"), "human_deaths_s": hw.get("deaths_per_s"),
           "human_outcomes": hw.get("outcomes"), "ai_fallen_s": kw.get("refills_per_s"), "relay_cpu": (bv.get("relay_process") or {}).get("cpu_ms_per_s"),
           "clients": bv.get("clients_summary"), "host": host_window(bv["window"]["t0"], bv["window"]["t1"])}
    if (d / "checker.log").exists() and (d / "relay-ids.json").exists():
        import subprocess
        p = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "privacy.py"), str(d)], capture_output=True, text=True)
        out["privacy"] = json.loads(p.stdout) if p.stdout.strip() else {"error": p.stderr[-300:]}
    return out


def main():
    pre = sys.argv[1]
    arms = {}
    # Runs marked for the runner listeners' CPU (flagged.txt) are left out; their redo is r3.
    flagged = set((R / "flagged.txt").read_text().split()) if (R / "flagged.txt").exists() else set()
    for d in sorted(R.iterdir()):
        if d.name in flagged:
            continue
        if d.is_dir() and d.name.startswith(pre + "-") and (d / "battle-viewers.json").exists():
            try:
                json.loads((d / "battle-viewers.json").read_text())["rows"][0]["viewers"]
            except Exception:
                continue
            arms.setdefault(re.sub(r"-r\d+$", "", d.name), []).append(d)
    data = {}
    for name, ds in arms.items():
        rs = [one(d) for d in ds]
        num = lambda k: [x[k] for x in rs if isinstance(x.get(k), (int, float))]
        data[name] = {"runs": len(rs), "n": rs[0]["n"], "humans": rs[0]["humans"], "walkers": rs[0]["walkers"], "each": rs,
                      **{k: (statistics.mean(num(k)), min(num(k)), max(num(k))) for k in ("db", "ticks", "tick", "update", "views", "input", "keepalive", "step_p99", "step_p50", "step_max", "over25", "skipped", "steps_per_s", "human_inputs_s", "human_deaths_s", "ai_fallen_s", "relay_cpu") if num(k)}}
    (ROOT / f".local/cc/tables-{pre}.json").write_text(json.dumps(data, indent=1, default=str) + "\n")
    g = lambda a, k, i=0: (a.get(k) or (None, None, None))[i]
    f = lambda x, p=1: "-" if x is None else f"{x:.{p}f}"
    for name, a in sorted(data.items()):
        priv = [x.get("privacy", {}).get("violations") for x in a["each"] if x.get("privacy")]
        print(f"{name:18} H={a['humans']:3} n={a['n']:3} W={a['walkers']:3} runs={a['runs']} ticks={f(g(a,'ticks'))} db={f(g(a,'db'))} ({f(g(a,'db',1))}-{f(g(a,'db',2))}) "
              f"tick={f(g(a,'tick'))} upd={f(g(a,'update'))} views={f(g(a,'views'))} input={f(g(a,'input'))} keep={f(g(a,'keepalive'))} "
              f"step p50/p99/max={f(g(a,'step_p50'),0)}/{f(g(a,'step_p99'),0)}/{f(g(a,'step_max'),0)} >25ms%={f(g(a,'over25'),2)} skipped={f(g(a,'skipped'),0)} "
              f"hin/s={f(g(a,'human_inputs_s'))} hdeaths/s={f(g(a,'human_deaths_s'),2)} aifallen/s={f(g(a,'ai_fallen_s'),2)} relay={f(g(a,'relay_cpu'))} privacy={priv} host={[x.get('host') for x in a['each']]}")


if __name__ == "__main__":
    main()
