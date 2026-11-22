#!/usr/bin/env python3
"""The gate case's tables (docs/HUMAN_FIGHTER_COST.md §6, §7): per arm ticks/s, step p50/p99/max and the
share of steps later than 25 ms (from the tick watcher, battle_viewers.py `steps_from`), the database
thread, the humans' inputs and deaths, the relay's privacy check; and series u's unchanged sight tests.
Usage: tables.py [RUNS_DIR] (default .local/gr/runs). Writes RUNS_DIR/tables.json."""
import json, re, statistics, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "living/tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cc_tables as ct  # noqa: E402
R = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / ".local/gr/runs"; ct.R = R
out = {}
for d in sorted(R.glob("u-*")):
    if not d.is_dir():
        continue
    log = next(d.glob("v*/module.log"), None)
    txt = log.read_text(errors="replace") if log else ""
    w = re.findall(r"sweep unchanged: (\d+) candidates, (\d+) exactly unchanged, (\d+) loosely unchanged; (\d+) sweeps compared, (\d+) with the eye unchanged", txt)
    tot = [sum(int(x[i]) for x in w) for i in range(5)]
    r = {"windows": len(w), "candidates": tot[0], "exact": tot[1], "loose": tot[2], "sweeps": tot[3], "eye_same": tot[4]}
    if tot[0]:
        r["exact_share"] = round(tot[1] / tot[0], 4); r["loose_share"] = round(tot[2] / tot[0], 4); r["eye_same_share"] = round(tot[4] / max(tot[3], 1), 4)
    out[d.name] = r
    print(d.name, r)
arms = {}
for d in sorted(R.iterdir()):
    if d.is_dir() and not d.name.startswith("u-") and (d / "battle-viewers.json").exists():
        arms.setdefault(re.sub(r"-r\d+$", "", d.name), []).append(d)
for name, ds in arms.items():
    rs = [ct.one(d) for d in ds]
    num = lambda k: [x[k] for x in rs if isinstance(x.get(k), (int, float))]
    a = {k: (round(statistics.mean(num(k)), 2), round(min(num(k)), 2), round(max(num(k)), 2)) for k in ("db", "ticks", "step_p50", "step_p99", "step_max", "over25", "skipped", "human_inputs_s", "human_deaths_s", "update", "views", "input", "relay_cpu") if num(k)}
    a["runs"] = len(rs); a["host"] = [x.get("host") for x in rs]; a["privacy"] = [x.get("privacy") for x in rs if x.get("privacy")]
    out[name] = a
    print(name, {k: a[k] for k in a if k not in ("host",)}, [h and (h.get("runner_cores"), h.get("runner_peak10s_cores")) for h in a["host"]])
(R / "tables.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
