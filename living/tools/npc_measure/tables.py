#!/usr/bin/env python3
"""NPC-MEASURE (branch npc-measure only; docs/NPC_CLIENT_SERVICE.md): the series' tables. Per arm
(runs named ARM-rN), each run's database thread and its split (gate_remeasure/cc_tables.py `one`),
the stand-in service's counts, the reflex latencies (reflex.py; share from the arm: npc50 1,
npc100 2, npc200 4, the AI arms the same ids for each), and the microsecond re-read with the
Spark's us_reread.py (gate216-x925 5956bc2da, run unmodified as a separate process).

    tables.py RUNS_DIR US_REREAD_PY
Writes RUNS_DIR/tables.json."""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "gate_remeasure"))
sys.path.insert(0, str(HERE.parent))
import cc_tables as ct  # noqa: E402
import reflex  # noqa: E402

R = Path(sys.argv[1]).resolve()
US = sys.argv[2]
ct.R = R
SHARE = {"npc50": 1, "npc100": 2, "npc200": 4}
out = {}
for d in sorted(R.iterdir()):
    if not (d.is_dir() and (d / "battle-viewers.json").exists()):
        continue
    arm = re.sub(r"-r\d+$", "", d.name)
    r = ct.one(d)
    rec = {k: r.get(k) for k in ("db", "ticks", "tick", "update", "views", "input", "by_reducer", "step_p50", "step_p99", "step_max", "over25", "skipped", "human_inputs_s", "human_deaths_s", "ai_fallen_s", "relay_cpu", "host")}
    bv = json.loads((d / "battle-viewers.json").read_text())["rows"][0]
    if bv.get("npc"):
        rec["npc"] = bv["npc"]["counts"] | {"driven": bv["npc"]["driven"]}
        shares = {SHARE.get(arm, 0), 1, 2, 4} - {0}
        rec["reflex"] = {f"share{s}": reflex.read(d, s) for s in sorted(shares)}
    if (d / "ticks-watch.csv").exists() and (d / "v0" / "result.json").exists():
        p = subprocess.run([sys.executable, US, str(d)], capture_output=True, text=True)
        rec["us"] = json.loads(p.stdout)["runs"][0] if p.returncode == 0 else {"error": p.stderr[-300:]}
    out.setdefault(arm, []).append({"run": d.name, **rec})
(R / "tables.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
for arm, runs in out.items():
    print(arm)
    for x in runs:
        us = x.get("us") or {}
        rf = (x.get("reflex") or {})
        sh = rf.get(f"share{SHARE.get(arm, 4)}") or {}
        print(f"  {x['run']:12} db {x['db']} ticks {x['ticks']} step p99 {x['step_p99']} over25 {x['over25']} | us p99 {us.get('p99_ms')} over25 {us.get('over25_pct')} pass {us.get('pass')} | npc_intents {x['by_reducer'].get('npc_intents')} | reflex p50 {sh.get('p50_ms')} p99 {sh.get('p99_ms')} answered {sh.get('answered_share')} | npc {x.get('npc')}")
