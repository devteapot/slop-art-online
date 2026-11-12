#!/usr/bin/env python3
"""A first sight asks a mind for a thought, never a player (docs/FIRST_SIGHT.md, the
`first_sight_thinks` law).

With the law on (and its gap at 0), the player's character P is placed beside S, a resident it
does not know, and R, a resident who has never seen P:

- P, played, gets no thought asked for it: no `deliberation` row, no first-sight line in its own
  log (`my_experience`; a played body's look tells it none), and the person still plays it;
- P still sees S as a stranger: `seen_characters` has S with an empty `name` and the label
  `a stranger` (the player perceives the same fact on screen);
- R's first sight of P (a stranger to R) asks R's mind for a thought: R's `deliberation` reason
  holds a first-sight line naming "a stranger";
- the law is the world's: `set_world_law first_sight_thinks` from the player's identity is
  refused.

    first_sight.py --run RUN

Needs `verify.py launch --run RUN` on a seed with AI people (the default `world`). Admin reducers
set the scene only: `place_near`, `place_at`, `set_behavior`, `set_world_law`. Writes
`RUN/first_sight.json`. Python standard library only.
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

FIRST = "For the first time you see "


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

    def call(reducer, args, as_admin=False):
        code, body = V.http(f"/v1/database/{db}/call/{reducer}", args, admin if as_admin else st["token"])
        V.log(st, f"call {reducer}{json.dumps(args)} as {'admin' if as_admin else 'player'} -> {code} {body.strip()}", sys.stderr)
        if as_admin and code != 200:
            raise RuntimeError(f"{reducer}: {code} {body}")
        return code, body

    results, snaps = [], {}

    def check(name, ok, detail):
        results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + f": {json.dumps(detail)[:300]}", flush=True)

    def wait_for(pred, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            v = pred()
            if v:
                return v
            time.sleep(0.5)
        return pred()

    live = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    if not live:
        call("join", ["FirstSight"])
        live = [c for c in sql("SELECT id, alive FROM my_characters", st["token"]) if c["alive"]]
    me = live[0]["id"]
    people = [c["id"] for c in sql("SELECT id, kind, ai, alive, stage FROM character", admin)
              if c["kind"] == "person" and c["ai"] and c["alive"] and c["stage"] == 2 and c["id"] != me]
    familiar = lambda actor, who: any((r["thing"] & 0xFFFFFFFF) == who and r["thing"] >> 40 == 2 for r in sql(f"SELECT thing FROM familiar WHERE actor = {actor}", admin))
    fresh = [p for p in people if not familiar(p, me)]
    s_id, r_id = people[0], fresh[-1] if fresh else people[-1]
    snaps["cast"] = {"player": me, "stranger_to_player": s_id, "resident_seeing_player": r_id, "residents_who_had_not_seen_p": len(fresh)}
    for who in (s_id, r_id):
        call("set_behavior", [who, json.dumps({"wait": 300})], as_admin=True)
    try:
        call("set_world_law", ["first_sight_thinks", "true"], as_admin=True)
        call("set_world_law", ["first_sight_gap_s", "0"], as_admin=True)
        laws = {w["name"]: w["value"] for w in sql("SELECT * FROM world_law", admin)}
        check("the law is on for the world", laws.get("first_sight_thinks") == "true", laws)
        code, body = call("set_world_law", ["first_sight_thinks", "false"])
        check("a player may not set the law", code != 200, f"{code} {body.strip()[:160]}")
        t0 = sql("SELECT last_ms FROM clock", admin)[0]["last_ms"]
        call("place_near", [s_id, me], as_admin=True)
        call("place_near", [r_id, me], as_admin=True)
        reason = lambda who: "\n".join(d["reason"] for d in sql(f"SELECT reason FROM deliberation WHERE actor = {who}", admin))
        r_asked = wait_for(lambda: [l for l in reason(r_id).split("\n") if l.startswith(FIRST) and "a stranger" in l], 20)
        time.sleep(4)
        snaps["p_deliberation"] = sql(f"SELECT * FROM deliberation WHERE actor = {me}", admin)
        snaps["p_lines"] = [r for r in sql("SELECT id, kind, text, at_ms FROM my_experience", st["token"]) if r["at_ms"] >= t0]
        snaps["p_played"] = sql(f"SELECT ai FROM character WHERE id = {me}", admin)
        snaps["p_sees_s"] = [r for r in sql("SELECT * FROM seen_characters", st["token"]) if r.get("id") == s_id]
        snaps["r_reason"] = reason(r_id)
        check("the person still plays P", snaps["p_played"] and not snaps["p_played"][0]["ai"], snaps["p_played"])
        check("P, played, gets no thought asked for it", not snaps["p_deliberation"], snaps["p_deliberation"])
        check("P's log has no first-sight line", not any(r["text"].startswith(FIRST) for r in snaps["p_lines"]), [r["text"] for r in snaps["p_lines"]][:6])
        check("P sees S as a stranger (empty name, label a stranger)", snaps["p_sees_s"] and snaps["p_sees_s"][0].get("name") == "" and snaps["p_sees_s"][0].get("label") == "a stranger", snaps["p_sees_s"])
        check("R's first sight of P asks R's mind, in the line's words", bool(r_asked), {"asked": r_asked, "reason": snaps["r_reason"][:300]})
    finally:
        call("set_world_law", ["first_sight_thinks", "false"], as_admin=True)
        call("set_world_law", ["first_sight_gap_s", "300"], as_admin=True)
    out = {"results": results, "snapshots": snaps}
    (V.run_dir(a.run) / "first_sight.json").write_text(json.dumps(out, indent=1) + "\n")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
