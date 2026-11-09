#!/usr/bin/env python3
"""Wake N island residents the ordinary way, for a measurement: a player walks up to each
resident at its post and speaks to it (`human_say` to its id). Admin `place_at` moves the
player between residents (a scene set-up, named in the log). Writes `RUN/wake_many.json`
with the residents woken and how long it took. Python standard library only.

    wake_many.py --run RUN [--count 20]
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gesture", HERE.parents[1] / "verify-player/scripts/gesture.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
V = G.V


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--count", type=int, default=20)
    a = ap.parse_args()
    p = G.P(a.run)
    if not p.st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        p.st["token"], p.st["identity"] = j["token"], j["identity"]
        V.save(p.st)
    mine = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    if not mine:
        p.call("join", ["Wren"])
        mine = [c for c in p.sql("SELECT id, alive FROM my_characters", "player") if c["alive"]]
    me = mine[0]["id"]
    start = time.monotonic()
    done, tried = [], set()
    while len(done) < a.count and time.monotonic() - start < 300:
        acts = {x["id"]: x["skill"] for x in p.sql("SELECT id, skill FROM activity")}
        people = {c["id"]: c for c in p.sql("SELECT id, ai, alive, stage FROM character WHERE kind = 'person'")}
        bodies = {b["id"]: (b["x"], b["y"]) for b in p.sql("SELECT id, x, y FROM body")}
        pick = next((i for i, c in people.items() if i not in tried and c["alive"] and not c["ai"] and c["stage"] >= 2
                     and acts.get(i) == "keep" and i in bodies), None)
        if pick is None:
            time.sleep(2)
            continue
        tried.add(pick)
        x, y = bodies[pick]
        p.call("place_at", [me, x + 1.5, y + 0.5], "admin")
        time.sleep(0.5)
        p.call("human_say", ["Good day. Could you spare some food, or tell me where to sleep?", pick])
        time.sleep(2.1)
        if any(w["id"] == pick for w in p.sql(f"SELECT id FROM woken WHERE id = {pick}")):
            done.append(pick)
    out = {"woken": done, "tried": len(tried), "seconds": round(time.monotonic() - start, 1)}
    (V.run_dir(a.run) / "wake_many.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out))
    sys.exit(0 if len(done) >= a.count else 1)


if __name__ == "__main__":
    main()
