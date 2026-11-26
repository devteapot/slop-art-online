#!/usr/bin/env python3
"""S7 §6: the cost runs' table. Per scenario and arm: the median frame time and frame interval over its three runs, and
the draw counts (the people's mesh-material pairs, materials, meshes, triangles); port - main and port-sb - port
against the limits (+0.3 ms at 8 near, +1.0 ms on the 64-crowd).
    python3 cost_table.py RUN_DIR OUT.json"""
import json
import statistics
import sys
from pathlib import Path

d = Path(sys.argv[1])
LIMIT = dict(near8=0.3, close8=0.3, crowd64=1.0)
out = {}
for sc in ("near8", "close8", "crowd64"):
    f = d / f"{sc}.json"
    if not f.exists():
        continue
    runs = json.loads(f.read_text())
    arms = {}
    for r in runs:
        arms.setdefault(r["arm"], []).append(r)
    row = {}
    for arm, rs in arms.items():
        med = lambda k: statistics.median([r[k] for r in rs if r.get(k) is not None]) if any(r.get(k) is not None for r in rs) else None  # noqa: E731
        row[arm] = dict(runs=len(rs), frame_ms=med("frame_ms"), frame_ms_all=[r.get("frame_ms") for r in rs], interval_p50=med("interval_ms_p50"), interval_p95=med("interval_ms_p95"),
                        people_pairs=med("people_pairs"), people_materials=med("people_materials"), main_materials=med("main_materials"), toon_materials=med("toon_materials"),
                        main_meshes=med("main_meshes"), people_ktris=med("people_ktris"), composed=med("composed"), governor=sorted({r["governor"] for r in rs}),
                        load_before=[r["load_before"] for r in rs], gpu_texture_mib=med("gpu_texture_mib"))
    diff = lambda a, b, k: round(row[a][k] - row[b][k], 2) if a in row and b in row and row[a][k] is not None and row[b][k] is not None else None  # noqa: E731
    out[sc] = dict(arms=row, limit_ms=LIMIT[sc],
                   port_minus_main=dict(frame_ms=diff("port", "main", "frame_ms"), interval_p50=diff("port", "main", "interval_p50"), people_pairs=diff("port", "main", "people_pairs"), people_materials=diff("port", "main", "people_materials")),
                   sb_minus_port=dict(frame_ms=diff("port-sb", "port", "frame_ms"), interval_p50=diff("port-sb", "port", "interval_p50"), people_pairs=diff("port-sb", "port", "people_pairs"), people_materials=diff("port-sb", "port", "people_materials")),
                   sb_minus_main=dict(frame_ms=diff("port-sb", "main", "frame_ms"), interval_p50=diff("port-sb", "main", "interval_p50")))
    o = out[sc]
    print(f"{sc}: " + "; ".join(f"{a} {v['frame_ms']} ms (p50 {v['interval_p50']}, pairs {v['people_pairs']}, materials {v['people_materials']})" for a, v in row.items()))
    print(f"   port-main {o['port_minus_main']}  sb-port {o['sb_minus_port']}  sb-main {o['sb_minus_main']}  limit +{LIMIT[sc]} ms")
Path(sys.argv[2]).write_text(json.dumps(out, indent=1))
