#!/usr/bin/env python3
"""What a player sees of a resident resting on (doing-renew; docs/TOWN_LIFE.md).

A resident whose only desire is to rest rests 8 s at a time, renewing each rest as it ends. A
player's character stands 3 m from it and sees it. The player's own subscriptions (the real Rust
SDK probe of verify-client, under the player's identity) are streamed for 30 s: what the game
client takes under the world's delivery laws (`seen_doing_near`, `seen_doing_far` and the
`seen_doing_cue` event table, frame-views) and the untiered `seen_doing`. The resident's row
arrives; at each rest's end the row is held (open-ended, `until_ms` 0) and at the next rest's
start renewed (its end moved on, its `since_ms` kept), both updates, in `seen_doing` and in the
tier it is in, never a delete followed by an insert, and no cue says it is doing nothing, so a
client never shows "doing nothing" between two rests. The next rest still begins at the old pace
(about a second after the last ended). Then the
resident is walked off (`set_behavior`): the client is told at once (a cue of nothing, the row
deleted). `--baseline` (a build before doing-renew) records the
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


# What the game client subscribes for what others are doing (living/game/src/net.rs): the tiers
# and the cue table while either delivery law is on (TIERED_STREAMS), `seen_doing` while both are
# off (UNTIERED_STREAMS). All are streamed; each is checked for the resident.
QUERIES = ["SELECT * FROM seen_doing", "SELECT * FROM seen_doing_near", "SELECT * FROM seen_doing_far", "SELECT * FROM seen_doing_cue"]
CUE = "seen_doing_cue"


def option(v):
    """A SATS `Option` as the probe prints it: the value, or None."""
    if isinstance(v, dict) and set(v) <= {"some", "none"}:
        return v.get("some")
    return v


def changes(events, table, who):
    """The live changes of `who`'s row in TABLE: (at_ms, event, old, new). A cue (`seen_doing_cue`,
    inserts only) is (at_ms, "cue", None, its doing or None for nothing)."""
    out = []
    for ev in events:
        if ev.get("table") != table:
            continue
        row = ev.get("row") or {}
        if table == CUE:
            if row.get("body") == who:
                out.append((ev["at_ms"], "cue", None, option(row.get("doing"))))
            continue
        doing = row.get("doing", row)
        if doing.get("id") != who:
            continue
        old = ev.get("old")
        out.append((ev["at_ms"], ev["event"], old.get("doing", old) if old else None, doing))
    return out


def tally(live, first=None):
    """Counts of one table's changes, and its renewals: an update to a new rest's end, through the
    row held open-ended between two rests (`until_ms` 0). `gap_ms` is the authority's gap between
    the old rest's end and the next one's start (the pacing, as before doing-renew)."""
    ups = [c for c in live if c[1] == "update"]
    renewals, last = [], first
    for at, ev, old, new in live:
        if ev not in ("update", "insert") or new is None or new.get("until_ms", 0) == 0:
            continue
        if last is not None and new["until_ms"] != last["until_ms"]:
            renewals.append({"at_ms": at, "gap_ms": (new["until_ms"] - REST_MS) - last["until_ms"], "since_kept": new["since_ms"] == last["since_ms"]})
        last = new
    return {"updates": len(ups), "holds": sum(1 for c in ups if c[3].get("until_ms") == 0), "deletes": sum(1 for c in live if c[1] == "delete"),
            "inserts": sum(1 for c in live if c[1] == "insert"), "cues": sum(1 for c in live if c[1] == "cue"),
            "cues_of_nothing": sum(1 for c in live if c[1] == "cue" and c[3] is None), "renewals": renewals}


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
    t, events = stream(st["db"], tok, QUERIES, a.seconds + 4, path)
    time.sleep(a.seconds)
    sent = time.time_ns() // 1_000_000
    call(st, "set_behavior", [rester, json.dumps({"seq": [{"do": {"skill": "goto", "target": {"at": [here["x"] + 12.0, here["y"] + 0.5]}}}, {"wait": 300}]})], admin, "admin")
    # When the authority's own row went (the truth the client's copies follow).
    truth_gone = None
    while time.time_ns() // 1_000_000 - sent < 5000:
        if not sql(st, f"SELECT id FROM doing WHERE id = {rester}", admin):
            truth_gone = time.time_ns() // 1_000_000 - sent
            break
        time.sleep(0.02)
    t.join(timeout=30)
    init = next((e for e in events if e.get("event") == "initial"), {})
    tables = init.get("tables") or {}
    first = {name: [r for r in tables.get(name, []) if (r.get("doing") or r).get("id") == rester] for name in ("seen_doing", "seen_doing_near", "seen_doing_far")}
    per, walk = {}, {}
    for q in QUERIES:
        name = q.rsplit(" ", 1)[1]
        live = changes(events, name, rester)
        start = (first.get(name) or [None])[0]
        per[name] = tally([c for c in live if c[0] < sent], (start or {}).get("doing", start) if start else None)
        walk[name] = [(at - sent, ev if ev != "cue" else ("cue of nothing" if new is None else "cue")) for at, ev, _, new in live if at >= sent]
    # On a build before doing-renew a renewal is a delete, then an insert: how long the row was gone.
    gone = []
    rest_untiered = [c for c in changes(events, "seen_doing", rester) if c[0] < sent]
    for at, ev, _, _ in rest_untiered:
        if ev == "delete":
            nxt = next((c for c in rest_untiered if c[1] == "insert" and c[0] >= at), None)
            if nxt:
                gone.append(nxt[0] - at)
    tier = "seen_doing_near" if first["seen_doing_near"] else "seen_doing_far"
    summary = {"me": me, "resident": rester, "seconds": a.seconds, "initial": {k: bool(v) for k, v in first.items()}, "tier": tier, "per_stream": per,
               "absent_ms": gone, "after_walk": walk, "authority_gone_ms": truth_gone}
    print(json.dumps(summary), flush=True)
    u = per["seen_doing"]
    if a.baseline:
        check(st, "baseline: the stream was recorded", bool(first["seen_doing"]), summary)
    else:
        check(st, "the player's client has the resident's row (seen_doing and its tier)", bool(first["seen_doing"]) and bool(first[tier]), first)
        check(st, "seen_doing: each rest renewal reaches the client as updates of the row (held, then renewed), none deleted, none inserted", len(u["renewals"]) >= 2 and u["holds"] >= 2 and not u["deletes"] and not u["inserts"], {k: u[k] for k in ("updates", "holds", "deletes", "inserts")})
        check(st, "seen_doing: each renewed row keeps its since_ms, the next rest beginning at the old pace (within 1.1 s of the old end)", u["renewals"] and all(r["since_kept"] and 0 <= r["gap_ms"] <= 1100 for r in u["renewals"]), u["renewals"])
        tt = per[tier]
        check(st, f"{tier}: the tier's row is never deleted or inserted while it rests, and follows the renewals", not tt["deletes"] and not tt["inserts"] and tt["updates"] >= 1, {k: tt[k] for k in ("updates", "deletes", "inserts")})
        c = per[CUE]
        check(st, "no cue tells the client the resident is doing nothing while it rests", c["cues_of_nothing"] == 0, {k: c[k] for k in ("cues", "cues_of_nothing")})
    w = walk["seen_doing"] + walk[tier] + walk[CUE]
    check(st, "walked off: within a second the client is told it is doing nothing (a cue or the row deleted)", any(ev in ("delete", "cue of nothing") and d < 1000 for d, ev in w), walk)
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
