#!/usr/bin/env python3
"""A player's command (`human_act` with a real-time node) runs once, then the character waits
for its person again.

The player joins and sends `{"wait":4}`. The brain's plan is `your command` while the wait
runs and becomes `waiting for you` about 4 s later; the command does not start over. Before
2026-11-10 `human_act` installed `{"seq":[node,{"wait":60}]}`, a root `seq` restarts, so
the 4 s wait lasted 64 s and then repeated.

    command.py --run RUN

Needs `verify.py launch --run RUN` (any seed). Reads `brain` and `activity` as the owner
(developer truth; the player acts with its own identity). Writes `RUN/command.json`. Python
standard library only.
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("verify", HERE.parent.parent / "verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    st = V.load(a.run)
    db = st["db"]
    admin = V.admin_token()
    if not st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        st["token"], st["identity"] = j["token"], j["identity"]
        V.save(st)

    def sql(q, token):
        code, body = V.http(f"/v1/database/{db}/sql", q, token, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(reducer, args):
        code, body = V.http(f"/v1/database/{db}/call/{reducer}", args, st["token"])
        V.log(st, f"call {reducer}{json.dumps(args)} as player -> {code} {body.strip()}", sys.stderr)
        return code, body

    mine = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    if not mine:
        call("join", ["Commander"])
        mine = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    me = mine[0]["id"]
    results, trace = [], []

    def check(name, ok, detail):
        results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + f": {detail}", flush=True)

    code, body = call("human_act", [json.dumps({"wait": 4})])
    sent = time.monotonic()
    check("human_act {wait:4} is accepted", code == 200, f"{code} {body.strip()[:120]}")
    ended = None
    while time.monotonic() - sent < 20:
        b = sql(f"SELECT plan, revision, graph FROM brain WHERE id = {me}", admin)[0]
        act = sql(f"SELECT skill, qty, started_ms, ends_ms FROM activity WHERE id = {me}", admin)
        trace.append({"t": round(time.monotonic() - sent, 2), "plan": b["plan"], "revision": b["revision"], "graph": b["graph"], "activity": act})
        if ended is None and b["plan"] == "waiting for you":
            ended = time.monotonic() - sent
        if ended is not None and time.monotonic() - sent > ended + 8:
            break
        time.sleep(0.25)
    first = next((t for t in trace if t["plan"] == "your command"), None)
    check("the command is the node itself, under plan 'your command'", first and json.loads(first["graph"]) == {"wait": 4.0}, first and first["graph"])
    check("the 4 s wait ends in about 4 s and the character waits for you", ended is not None and 3.0 <= ended <= 6.5, f"waiting for you after {ended and round(ended, 2)} s")
    later = [t for t in trace if ended is not None and t["t"] > ended]
    check("the command does not start over", later and all(t["plan"] == "waiting for you" for t in later), f"{len(later)} samples after, plans {sorted({t['plan'] for t in later})}")
    out = V.run_dir(a.run) / "command.json"
    out.write_text(json.dumps({"character": me, "results": results, "trace": trace}, indent=2) + "\n")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
