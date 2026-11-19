#!/usr/bin/env python3
"""No AI advantage in movement (docs/COMBAT_MIND.md §3.3, verify-core features/steering.md
"Movement intents"): the movement intents a graph or an act uses (`keep_distance`, `close_in`,
`circle`, `back_off`, `follow`) move a body at the speeds its person's keys give it, and an AI
character's intents at its own walk and the same run share.

On open ground, with a resident R held still (admin `set_behavior`, `place_at`):

1. Keys: the player walks east (`human_move(1, 0, false)`), then runs (`human_move(1, 0, true)`):
   its cruising speeds from `my_body` (the row's vx, vy), and the run drains breath (the vitals
   row's rate, read as the admin).
2. Intents, as the player's own commands (`human_act`): `back_off` from R to 9 m (a walk), then
   `close_in` on R with `run: true` (a run). Same body: the walk and the run within 1% of the
   keys', no faster.
3. The AI: R `back_off`s from the player (walk) and `close_in`s on it at a run through its graph
   (admin `set_behavior`); its run is the same `run_share` times its own walk as the player's.

    intents.py --run RUN

Needs `verify.py launch --run RUN` (any seed). Writes `RUN/intents.json`. Python standard library only.
"""

import argparse
import importlib.util
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("appraise", HERE / "appraise.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
spec = importlib.util.spec_from_file_location("face", HERE / "face.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
V = A.V

RESULTS = A.RESULTS
EVIDENCE = {}
TOL = 0.01


def speed(b):
    return math.hypot(b["vx"], b["vy"]) if b else 0.0


def peak(fn, secs, before=None):
    """The body's cruising speed (`speed`, what its steering moves it at, kept on the row after it
    stops) once it has moved from `before` (its row before the command), and its rows sampled
    every 0.15 s over `secs` (velocities)."""
    rows, end = [], time.monotonic() + secs
    while time.monotonic() < end:
        b = fn()
        if b:
            rows.append({k: b[k] for k in ("t_ms", "x", "y", "vx", "vy", "speed", "running")})
        time.sleep(0.15)
    first = before or (rows[0] if rows else None)
    moved = rows and (math.dist((first["x"], first["y"]), (rows[-1]["x"], rows[-1]["y"])) > 0.5 or any(speed(r) > 0 for r in rows))
    return (round(rows[-1]["speed"], 4) if moved else 0.0), rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    p = A.P(a.run)
    me = p.me("player", "Mover")
    r = A.wait_for(lambda: A.resident(p, {me}), 60)
    if not r:
        A.check(p, "a resident stands still", False, "none found within 60 s")
        return finish(p)
    rid = r["id"]
    p.call("set_behavior", [rid, json.dumps({"wait": 600})], "admin")
    spot = F.open_ground(p, r["at"], box=(-14, 22, -2, 2))
    A.check(p, "open ground to walk and run on", spot is not None, f"{spot}")
    if spot is None:
        return finish(p)
    x, y = spot
    mine = lambda: F.body(p)
    theirs = lambda: next(iter(p.sql(f"SELECT * FROM body WHERE id = {rid}")), None)
    vitals = lambda i: p.sql(f"SELECT stamina, stamina_rate FROM vitals WHERE id = {i}")[0]
    try:
        # 1. Keys.
        p.call("place_at", [rid, x - 12, y], "admin")
        p.call("place_at", [me, x, y], "admin")
        time.sleep(1.0)
        p.call("human_move", [1.0, 0.0, False])
        walk_keys, rows_w = peak(mine, 2.0)
        p.call("human_move", [0.0, 0.0, False])
        time.sleep(1.5)
        p.call("place_at", [me, x, y], "admin")
        time.sleep(3.0)
        p.call("human_move", [1.0, 0.0, True])
        time.sleep(0.6)
        v_run = vitals(me)
        run_keys, rows_r = peak(mine, 1.5)
        p.call("human_move", [0.0, 0.0, False])
        EVIDENCE["keys"] = {"walk": walk_keys, "run": run_keys, "vitals_running": v_run, "rows_walk": rows_w, "rows_run": rows_r}
        A.check(p, "keys: the player walks and runs (run faster than walk)", walk_keys > 0.5 and run_keys > walk_keys * 1.2, f"walk {walk_keys} m/s, run {run_keys} m/s")
        A.check(p, "keys: the run drains breath", v_run["stamina_rate"] < 0, f"{v_run}")
        time.sleep(4.0)

        # 2. The same body under its intents, as the player's commands.
        p.call("place_at", [rid, x - 3, y], "admin")
        p.call("place_at", [me, x, y], "admin")
        time.sleep(1.5)
        before = mine()
        code, out = p.call("human_act", [json.dumps({"do": "back_off", "target": {"id": rid}, "distance": 9})])
        walk_intent, rows_bi = peak(mine, 2.0, before)
        A.check(p, "human_act back_off is accepted (a one-off act, the player's command)", code == 200, f"{code} {out.strip()[:120]}")
        time.sleep(1.5)
        # Within sight by night too (6 m).
        p.call("place_at", [rid, x - 5, y], "admin")
        p.call("place_at", [me, x, y], "admin")
        time.sleep(3.0)
        before = mine()
        code, out = p.call("human_act", [json.dumps({"do": "close_in", "target": {"id": rid}, "distance": 1, "run": True})])
        v_ci = vitals(me)
        run_intent, rows_ci = peak(mine, 1.6, before)
        EVIDENCE["player_intents"] = {"back_off_walk": walk_intent, "close_in_run": run_intent, "vitals_running": v_ci, "rows_back_off": rows_bi, "rows_close_in": rows_ci}
        A.check(p, "back_off walks the player's body at its keys' walk (within 1%, no faster)", walk_intent > 0 and abs(walk_intent / walk_keys - 1) <= TOL, f"intent {walk_intent} vs keys {walk_keys} m/s")
        A.check(p, "close_in with run: true runs it at its keys' run (within 1%, no faster)", run_intent > 0 and abs(run_intent / run_keys - 1) <= TOL, f"intent {run_intent} vs keys {run_keys} m/s")
        A.check(p, "and that run drains breath as the keys' does (draining, or drained below full)", v_ci["stamina_rate"] < 0 or v_ci["stamina"] < 99, f"{v_ci}")
        p.call("human_move", [0.0, 0.0, False])
        time.sleep(3.0)

        # 3. The AI's intents: its own walk, and the same run share.
        p.call("place_at", [me, x, y], "admin")
        p.call("place_at", [rid, x - 3, y], "admin")
        time.sleep(1.5)
        before = theirs()
        p.call("set_behavior", [rid, json.dumps({"seq": [{"do": {"skill": "back_off", "target": {"id": me}, "distance": 9}}, {"wait": 600}]})], "admin")
        ai_walk, rows_aw = peak(theirs, 2.0, before)
        p.call("set_behavior", [rid, json.dumps({"wait": 600})], "admin")
        time.sleep(1.5)
        p.call("place_at", [rid, x - 5, y], "admin")
        p.call("place_at", [me, x, y], "admin")
        time.sleep(3.0)
        before = theirs()
        p.call("set_behavior", [rid, json.dumps({"seq": [{"do": {"skill": "close_in", "target": {"id": me}, "distance": 1, "run": True}}, {"wait": 600}]})], "admin")
        ai_run, rows_ar = peak(theirs, 1.6, before)
        p.call("set_behavior", [rid, json.dumps({"wait": 600})], "admin")
        ratio_p, ratio_ai = run_keys / walk_keys, ai_run / ai_walk if ai_walk else 0
        EVIDENCE["ai_intents"] = {"resident": rid, "walk": ai_walk, "run": ai_run, "run_over_walk": round(ratio_ai, 4), "player_run_over_walk": round(ratio_p, 4), "rows_walk": rows_aw, "rows_run": rows_ar}
        A.check(p, "an AI's intents run at the same share of its own walk as the player's keys", ai_walk > 0 and abs(ratio_ai / ratio_p - 1) <= TOL, f"AI {ai_run}/{ai_walk} = {round(ratio_ai, 4)}; player keys {run_keys}/{walk_keys} = {round(ratio_p, 4)}")
    finally:
        p.call("human_move", [0.0, 0.0, False])
        p.call("set_behavior", [rid, json.dumps({"wait": 600})], "admin")
    return finish(p)


def finish(p):
    (V.run_dir(p.st["run"]) / "intents.json").write_text(json.dumps({"checks": RESULTS, "evidence": EVIDENCE}, indent=1) + "\n")
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(failed)} of {len(RESULTS)} passed")
    for r in RESULTS:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + ": " + str(r["detail"])[:160])
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
