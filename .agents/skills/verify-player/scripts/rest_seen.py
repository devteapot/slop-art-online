#!/usr/bin/env python3
"""What a player sees of a resident resting on (doing-renew; docs/TOWN_LIFE.md).

A resident whose only desire is to rest rests 8 s at a time, renewing each rest as it ends. A
player's character stands 3 m from it and sees it. The player's own client subscription
(`SELECT * FROM seen_doing`, the real Rust SDK probe of verify-client, under the player's
identity) is streamed for 30 s: the resident's row arrives, and every renewal reaches the client
as one update of that row (its end moved on, its `since_ms` kept), never a delete followed by an
insert, so a client never sees "doing nothing" between two rests. Then the resident is walked off
(`set_behavior`): the row is deleted at once. `--baseline` (a build before doing-renew) records the
same stream without asserting the renewal.

    rest_seen.py --run RUN [--baseline]

Needs `verify.py launch --run RUN` and the probe built (verify-client SKILL.md); joins a player
if the run has none. Admin calls set the scene: `spawn_crowd`, `place_at`, `set_behavior`. Writes
`RUN/rest-seen.json` and the stream `RUN/rest-seen-stream.jsonl`. Python standard library only.
"""

import argparse
import importlib.util
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location("verify", HERE.parent.parent / "verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
PROBE = ROOT / ".local/living/verify/target-client/debug/verify-client-probe"
REST_MS = 8000

RESULTS = []


def sql(st, q, token):
    code, body = V.http(f"/v1/database/{st['db']}/sql", q, token, raw=True)
    if code != 200:
        raise RuntimeError(f"sql {q}: {code} {body}")
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def call(st, reducer, args, token, who):
    code, body = V.http(f"/v1/database/{st['db']}/call/{reducer}", args, token)
    V.log(st, f"call {reducer}{json.dumps(args)} as {who} -> {code} {body.strip()}", sys.stderr)
    if code != 200:
        raise RuntimeError(f"{reducer}: {code} {body}")
    return body


def check(st, name, ok, detail):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
    V.log(st, f"{'PASS' if ok else 'FAIL'} {name}: {json.dumps(detail)[:600]}")


def stream(db, token, queries, seconds, path):
    """Run the probe on QUERIES for SECONDS; every line it prints, stamped with the local time it
    arrived (`at_ms`), is written to PATH and returned. Starts reading at once; returns a thread
    and the list it fills."""
    out = []
    req = {"uri": V.URL, "db": db, "token": token, "queries": queries, "seconds": seconds, "stream": True}

    def run():
        with path.open("w") as f, subprocess.Popen([str(PROBE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as p:
            p.stdin.write(json.dumps(req))
            p.stdin.close()
            for line in p.stdout:
                if token and token in line:
                    raise RuntimeError("credential in probe output")
                ev = json.loads(line)
                ev["at_ms"] = time.time_ns() // 1_000_000
                if ev.get("event") == "initial":
                    ev.pop("identity", None)
                out.append(ev)
                f.write(json.dumps(ev) + "\n")
            p.wait(timeout=10)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out


def changes(events, table, who):
    """The live changes of `who`'s row in TABLE: (at_ms, event, old, new)."""
    out = []
    for ev in events:
        if ev.get("table") != table:
            continue
        row = ev.get("row") or {}
        doing = row.get("doing", row)
        if doing.get("id") != who:
            continue
        old = ev.get("old")
        out.append((ev["at_ms"], ev["event"], old.get("doing", old) if old else None, doing))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--seconds", type=int, default=30)
    a = ap.parse_args()
    st = V.load(a.run)
    admin = V.admin_token()
    if not PROBE.exists():
        raise SystemExit(f"build the probe first: {PROBE}")
    if not st.get("token"):
        code, body = V.http("/v1/identity", {})
        j = json.loads(body)
        st["token"], st["identity"] = j["token"], j["identity"]
        V.save(st)
    tok = st["token"]
    mine = [c for c in sql(st, "SELECT id, alive FROM my_characters", tok) if c["alive"]]
    if not mine:
        call(st, "join", ["Watcher"], tok, "player")
        mine = [c for c in sql(st, "SELECT id, alive FROM my_characters", tok) if c["alive"]]
    me = mine[0]["id"]
    before = {c["id"] for c in sql(st, "SELECT id FROM character", admin)}
    call(st, "spawn_crowd", [1, True], admin, "admin")
    rester = next(c["id"] for c in sql(st, "SELECT id FROM character", admin) if c["id"] not in before)
    call(st, "set_behavior", [rester, json.dumps({"wait": 120})], admin, "admin")
    here = sql(st, f"SELECT x, y FROM body WHERE id = {me}", admin)[0]
    seen = False
    for dx, dy in [(3.0, 0.5), (-3.0, 0.5), (0.5, 3.0), (0.5, -3.0)]:
        call(st, "place_at", [rester, here["x"] + dx, here["y"] + dy], admin, "admin")
        end = time.monotonic() + 3
        while time.monotonic() < end and not seen:
            seen = any(c["id"] == rester for c in sql(st, "SELECT id FROM seen_characters", tok))
            time.sleep(0.25)
        if seen:
            break
    check(st, "the player sees the resident 3 m off", seen, {"me": me, "resident": rester})
    if not seen:
        return finish(st, a)
    call(st, "set_behavior", [rester, json.dumps({"desires": [{"want": "rest", "weight": {"base": 1.0}, "do": {"do": "rest"}}]})], admin, "admin")
    end = time.monotonic() + 10
    while time.monotonic() < end and not any(d["id"] == rester for d in sql(st, "SELECT * FROM seen_doing", tok)):
        time.sleep(0.2)
    path = st_dir(st) / "rest-seen-stream.jsonl"
    t, events = stream(st["db"], tok, ["SELECT * FROM seen_doing"], a.seconds + 4, path)
    time.sleep(a.seconds)
    sent = time.time_ns() // 1_000_000
    call(st, "set_behavior", [rester, json.dumps({"seq": [{"do": {"skill": "goto", "target": {"at": [here["x"] + 12.0, here["y"] + 0.5]}}}, {"wait": 300}]})], admin, "admin")
    # When the authority's own row went (the truth the client's copy follows at its frame).
    truth_gone = None
    while time.time_ns() // 1_000_000 - sent < 5000:
        if not sql(st, f"SELECT id FROM doing WHERE id = {rester}", admin):
            truth_gone = time.time_ns() // 1_000_000 - sent
            break
        time.sleep(0.02)
    t.join(timeout=30)
    init = next((e for e in events if e.get("event") == "initial"), {})
    first = [r for r in (init.get("tables") or {}).get("seen_doing", []) if (r.get("doing") or r).get("id") == rester]
    live = changes(events, "seen_doing", rester)
    resting = [c for c in live if c[0] < sent]
    walked = [c for c in live if c[0] >= sent]
    ups = [c for c in resting if c[1] == "update"]
    dels = [c for c in resting if c[1] == "delete"]
    ins = [c for c in resting if c[1] == "insert"]
    renewals = [{"at_ms": at, "gap_ms": (new["until_ms"] - REST_MS) - old["until_ms"], "since_kept": new["since_ms"] == old["since_ms"]} for at, ev, old, new in ups if old and new["until_ms"] != old["until_ms"]]
    # On a build before doing-renew a renewal is a delete, then an insert: how long the row was gone.
    gone = []
    for at, ev, _, _ in dels:
        nxt = next((c for c in ins if c[0] >= at), None)
        if nxt:
            gone.append(nxt[0] - at)
    summary = {"me": me, "resident": rester, "seconds": a.seconds, "initial_row": bool(first), "updates": len(ups), "deletes": len(dels), "inserts": len(ins),
               "renewals": renewals, "absent_ms": gone, "after_walk": [(at - sent, ev) for at, ev, _, _ in walked], "authority_gone_ms": truth_gone}
    print(json.dumps(summary), flush=True)
    if a.baseline:
        check(st, "baseline: the stream was recorded", bool(first), summary)
    else:
        check(st, "the player's client has the resident's seen_doing row (resting)", bool(first), first[:1])
        check(st, "each rest renewal reaches the client as one update (none deleted, none inserted)", len(renewals) >= 3 and not dels and not ins, {k: summary[k] for k in ("updates", "deletes", "inserts")})
        check(st, "each renewed row keeps its since_ms, its end moved on within 100 ms of the old end", all(r["since_kept"] and r["gap_ms"] < 100 for r in renewals), renewals)
    check(st, "walked off: the client's row is deleted within a second", any(ev == "delete" and d < 1000 for d, ev in summary["after_walk"]), summary["after_walk"])
    return finish(st, a, summary)


def st_dir(st):
    return V.run_dir(st["run"])


def finish(st, a, summary=None):
    out = st_dir(st) / "rest-seen.json"
    out.write_text(json.dumps({"db": st["db"], "baseline": a.baseline, "checks": RESULTS, "summary": summary}, indent=1) + "\n")
    print(f"evidence: {out}")
    return 0 if all(r["ok"] for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
