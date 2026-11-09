#!/usr/bin/env python3
"""Set a combat photo scene on a scratch world for a connected game client (docs/COMBAT.md).

Waits for the client's character (`--name`), then with admin test reducers puts it at the
arrival point with residents around it: a passive one beside it (east, for a strike), one
8 m north (for skillshots) and, after `--attack-after` seconds, one west that strikes it every
two seconds (for blocks, dodges, hits and heals). `--wolves` instead puts it 9 m from the
seed's bold pack. Uses the verify harness (`verify.py`) for HTTP and the admin token.

    combat_scene.py --run RUN --name Shooter [--wolves] [--attack-after 8]
"""
import argparse, importlib.util, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("combat", ROOT / ".agents/skills/verify-player/scripts/combat.py")
C = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]] + sys.argv[1:]
spec.loader.exec_module(C)

ap = argparse.ArgumentParser()
ap.add_argument("--run", required=True)
ap.add_argument("--name", default="Shooter")
ap.add_argument("--wolves", action="store_true")
ap.add_argument("--attack-after", type=float, default=8.0)
a = ap.parse_args()
st = C.V.load(a.run)
me = None
for _ in range(600):
    rows = C.sql(st, f"SELECT id FROM character WHERE name = '{a.name}' AND alive = true")
    if rows:
        me = rows[-1]["id"]
        break
    time.sleep(0.5)
if me is None:
    sys.exit("the client never joined")
time.sleep(1.0)
land = C.sql(st, "SELECT arrive_x, arrive_y FROM land")[0]
p = (land["arrive_x"], land["arrive_y"] + 6.0)
if a.wolves:
    w = C.wolves(st)
    wp = C.body(st, w[0])
    C.call(st, "place_at", [me, wp[0], wp[1] + 9.0], "admin")
    print("placed near the pack", wp, flush=True)
    sys.exit(0)
C.call(st, "place_at", [me, p[0], p[1]], "admin")
used = {me}
def resident(at, graph):
    for r in C.sql(st, "SELECT id FROM character WHERE kind = 'person' AND alive = true"):
        if r["id"] in used:
            continue
        h = C.hp(st, r["id"])
        if h is None or h < 60:
            continue
        used.add(r["id"])
        C.call(st, "place_at", [r["id"], at[0], at[1]], "admin")
        C.call(st, "set_behavior", [r["id"], graph], "admin")
        return r["id"]
east = resident((p[0] + 1.6, p[1]), '{"wait":60}')
north = resident((p[0], p[1] - 8.0), '{"wait":60}')
print("passive", east, north, flush=True)
time.sleep(a.attack_after)
g = json.dumps({"seq": [{"do": {"skill": "strike", "target": {"id": me}}}, {"wait": 2}]})
west = resident((p[0] - 1.3, p[1]), g)
print("attacker", west, flush=True)
