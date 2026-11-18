#!/usr/bin/env python3
"""Cues as real clients receive them (docs/PERCEPTION.md, "Cues"; frame-views, 2026-11-18).

    cues.py --run client-...      (a run launched with verify.py launch, any seed; build the probe first)

Three players join, each with its own identity: A (the harness player), B and C. A and B stand
1 m apart on a quiet open line, a held stranger F 10 m from A (in sight by day, not near), and C
40 m or more away. Four Rust SDK probes stream for about 28 s: A (its `seen_*` views and their
`_near` and `_far` tiers, `my_body` and the three cue event tables), B and C (the cue tables) and an anonymous connection (the cue
tables). Meanwhile B steps (`human_move`), waves at A (`human_act`) and strikes at A
(`use_skill`); F is moved (admin `place_at`). Checks:

- row-level security: every cue a client receives names it as the viewer; C and the anonymous
  connection receive none of A's, B's or F's; B asking for A's rows by identity gets nothing;
- A is cued B's motion and B's strikes: each windup reaches A first by `seen_fighter_cue`, within
  60 ms of its `act_ms` (B is in A's near tier, whose copies follow only every 500 ms); A receives
  B's wave and is never cued F (not near, not engaged);
- the tiers: B is in A's near tier (`seen_*_near`) and F in its far tier; no creature is in both,
  and their union is exactly the untiered view's rows (`seen_bodies`, `seen_fighters`, `seen_doing`);
- convergence: replaying A's stream with the client's rule (the union of the tiers, and a cue that
  stands for that creature until its next tier row) ends on exactly the rows of A's views.

Admin calls (`spawn_crowd`, `set_behavior`, `place_at`) set the scene. Writes
`RUN/cues-<who>.jsonl` and `RUN/cues.json`. Python standard library only.
"""

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HARNESS = ROOT / ".agents/skills/verify/scripts/verify.py"
SPEC = importlib.util.spec_from_file_location("verify_harness", HARNESS)
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from earshot import call, open_line, run, sql  # noqa: E402

BINARY = ROOT / ".local/living/verify/target-client/debug/verify-client-probe"
CUES = ["SELECT * FROM seen_body_cue", "SELECT * FROM seen_fighter_cue", "SELECT * FROM seen_doing_cue"]
VIEWS = ["SELECT * FROM seen_bodies", "SELECT * FROM seen_fighters", "SELECT * FROM seen_doing", "SELECT * FROM my_body"]
TIERS = [f"SELECT * FROM {v}_{t}" for v in ("seen_bodies", "seen_fighters", "seen_doing") for t in ("near", "far")]
CUE_OF = {"seen_body_cue": "seen_bodies", "seen_fighter_cue": "seen_fighters", "seen_doing_cue": "seen_doing"}
STREAMS = ("seen_bodies", "seen_fighters", "seen_doing")


def stream(db, token, queries, seconds, path):
    """Run a probe in stream mode, writing its lines to `path`; returns the thread."""
    req = {"uri": V.URL, "db": db, "token": token, "queries": queries, "seconds": seconds, "stream": True}

    def go():
        with open(path, "w") as out:
            p = subprocess.run([str(BINARY)], input=json.dumps(req), text=True, stdout=out, stderr=subprocess.DEVNULL, timeout=seconds + 60)
            out.write(json.dumps({"event": "exit", "code": p.returncode}) + "\n")

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


def lines(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def hcall(db, token, reducer, args):
    code, body = V.http(f"/v1/database/{db}/call/{reducer}", args, token)
    if code != 200:
        raise RuntimeError(f"{reducer}: {code} {body[:200]}")


def norm(v):
    """An identity as SQL (["0x…"]) or the probe's JSON gives it: bare lower-case hex."""
    while isinstance(v, (list, dict)):
        v = v[0] if isinstance(v, list) else next(iter(v.values()))
    return str(v).lower().removeprefix("0x")


def key_of(row, table):
    return row["id"] if table in ("seen_bodies", "seen_fighters", "seen_doing", "my_body") else row["body"]


def replay(events):
    """Each view's rows at the end, and what the client shows by its rule: the union of a view's
    two tiers, and over it a creature's cue until that creature's next tier row."""
    rows = {}
    over = {t: {} for t in STREAMS}

    def stream_of(table):
        return next((t for t in STREAMS if table in (f"{t}_near", f"{t}_far")), None)

    for ev in events:
        t = ev.get("table")
        if ev.get("event") == "initial":
            for name, got in (ev.get("tables") or {}).items():
                rows.setdefault(name, {}).update({r["id"]: r for r in got})
            continue
        if ev.get("event") in ("insert", "update", "delete") and t not in CUE_OF and t:
            r = ev["row"]
            table = rows.setdefault(t, {})
            if ev["event"] == "delete":
                table.pop(r["id"], None)
            else:
                table[r["id"]] = r
            if stream_of(t):
                over[stream_of(t)].pop(r["id"], None)
        elif t in CUE_OF:
            v = CUE_OF[t]
            r = ev["row"]
            body = r["motion"]["id"] if t == "seen_body_cue" else r["body"]
            if body not in rows.get("seen_bodies_near", {}) and body not in rows.get("seen_bodies_far", {}):
                continue
            value = r["motion"] if t == "seen_body_cue" else r["fighter" if t == "seen_fighter_cue" else "doing"]
            # An Option arrives as {"some": row} or {"none": []} (or the row / null).
            if isinstance(value, dict) and set(value) <= {"some", "none"}:
                value = value.get("some")
            over[v][body] = value
    union, shown = {}, {}
    for t in STREAMS:
        union[t] = {**rows.get(f"{t}_near", {}), **rows.get(f"{t}_far", {})}
        merged = dict(union[t])
        for k, v in over[t].items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        shown[t] = merged
    return rows, union, shown


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    st = V.load(rid)
    db = st["db"]
    out = ROOT / ".local/living/verify" / rid
    run(HARNESS, "player", "--run", rid, "join", "Cue A")
    st = V.load(rid)
    tok = {"a": st["token"]}
    for who in ("b", "c"):
        code, body = V.http("/v1/identity", {})
        tok[who] = json.loads(body)["token"]
        hcall(db, tok[who], "join", [f"Cue {who.upper()}"])
    chars = {c["name"]: c for c in sql(rid, "SELECT * FROM character")}
    a, b, c = (chars[f"Cue {x}"]["id"] for x in "ABC")
    ident = {x: norm(chars[f"Cue {x.upper()}"]["controller"]) for x in "abc"}
    before = {x["id"] for x in sql(rid, "SELECT id FROM character")}
    call(rid, "spawn_crowd", [1, True])
    f = next(x["id"] for x in sql(rid, "SELECT id FROM character") if x["id"] not in before)
    call(rid, "set_behavior", [f, json.dumps({"wait": 600})])
    line = open_line(rid, 30)
    call(rid, "place_at", [a, *line[10]])
    call(rid, "place_at", [b, *line[11]])
    call(rid, "place_at", [f, *line[20]])
    pos = {x["id"]: (x["x"], x["y"]) for x in sql(rid, "SELECT id, x, y FROM body")}
    if math.dist(pos[c], pos[a]) < 40:
        call(rid, "place_at", [c, line[0][0], line[0][1] + (60 if line[0][1] < 200 else -60)])
    time.sleep(2.0)
    pos = {x["id"]: (x["x"], x["y"]) for x in sql(rid, "SELECT id, x, y FROM body")}
    seconds = 28
    paths = {w: out / f"cues-{w}.jsonl" for w in ("a", "b", "c", "anon")}
    threads = [stream(db, tok["a"], VIEWS + TIERS + CUES, seconds, paths["a"]),
               stream(db, tok["b"], CUES, seconds, paths["b"]),
               stream(db, tok["c"], CUES, seconds, paths["c"]),
               stream(db, None, CUES, seconds, paths["anon"])]
    time.sleep(3.0)
    # B asks for A's cues by identity: row-level security must still give it only its own.
    peek = stream(db, tok["b"], [f"SELECT * FROM seen_body_cue WHERE viewer = 0x{ident['a']}"], 12, out / "cues-b-peek.jsonl")
    t0 = time.time()
    for dx in (1, -1, 1):
        hcall(db, tok["b"], "human_move", [dx, 0, False])
        time.sleep(0.4)
        hcall(db, tok["b"], "human_move", [0, 0, False])
        call(rid, "place_at", [f, line[20][0] + dx * 0.5, line[20][1]])
        time.sleep(0.6)
    hcall(db, tok["b"], "human_act", [json.dumps({"do": {"skill": "wave", "target": {"id": a}}})])
    time.sleep(2.5)
    # Back beside A (its steps took it out of reach), then six strikes.
    call(rid, "place_at", [b, *line[11]])
    time.sleep(0.5)
    pa = {x["id"]: (x["x"], x["y"]) for x in sql(rid, f"SELECT id, x, y FROM body WHERE id = {a}")}[a]
    for _ in range(6):
        hcall(db, tok["b"], "use_skill", ["strike", a, pa[0], pa[1]])
        time.sleep(1.6)
    act_window = (t0, time.time())
    for t in threads + [peek]:
        t.join()
    ev = {w: lines(p) for w, p in paths.items()}
    peek_ev = lines(out / "cues-b-peek.jsonl")
    cue_rows = {w: [e for e in ev[w] if e.get("event") == "insert" and e.get("table") in CUE_OF] for w in ev}
    body_of = lambda e: e["row"]["motion"]["id"] if e["table"] == "seen_body_cue" else e["row"]["body"]
    viewer_of = lambda e: norm(e["row"]["viewer"])
    a_cues = cue_rows["a"]
    of = lambda body, table: [e for e in a_cues if body_of(e) == body and e["table"] == table]

    def some(v):
        return v.get("some") if isinstance(v, dict) and set(v) <= {"some", "none"} else v

    # Each of B's moves (by act_ms) and when A first received it: by a cue or by its view,
    # whichever came first. In a small scene a frame every other tick delivers about half.
    first = {}
    for e in ev["a"]:
        if e.get("table") == "seen_fighter_cue":
            row, how = some(e["row"]["fighter"]), "cue"
        elif e.get("table") in ("seen_fighters_near", "seen_fighters_far") and e.get("event") in ("insert", "update") and e["row"]["id"] == b:
            row, how = e["row"], "view"
        else:
            continue
        if row and row.get("id") == b and row.get("act", 0) != 0 and row["act_ms"] not in first:
            first[row["act_ms"]] = (e["ms"] - row["act_ms"], how)
    late = [v[0] for v in first.values()]
    by_cue = [v for v in first.values() if v[1] == "cue"]
    waves = [e for e in of(b, "seen_doing_cue")] + [e for e in ev["a"] if e.get("table") in ("seen_doing_near", "seen_doing_far") and e.get("event") == "insert" and e["row"]["id"] == b]
    rows, union, shown = replay(ev["a"])
    differ = {t: sorted(k for k in set(union[t]) | set(shown[t]) if union[t].get(k) != shown[t].get(k)) for t in STREAMS}
    # The tiers partition the untiered view: no creature in both, and their union is its rows.
    overlap = {t: sorted(set(rows.get(f"{t}_near", {})) & set(rows.get(f"{t}_far", {}))) for t in STREAMS}
    split = {t: sorted(k for k in set(union[t]) | set(rows.get(t, {})) if union[t].get(k) != rows.get(t, {}).get(k)) for t in STREAMS}
    tiers = {"near": sorted(rows.get("seen_bodies_near", {})), "far": sorted(rows.get("seen_bodies_far", {}))}
    checks = {
        "every probe ran to its end": all(e[-1].get("code") == 0 for e in ev.values()) and peek_ev[-1].get("code") == 0,
        "placed as planned (B within 1.5 m of A, F 9-12 m, C 30 m or more)": math.dist(pos[a], pos[b]) <= 1.5 and 9 <= math.dist(pos[a], pos[f]) <= 12 and math.dist(pos[a], pos[c]) >= 30,
        "A's cues all name A as the viewer": bool(a_cues) and all(viewer_of(e) == ident["a"] for e in a_cues),
        "B's cues all name B": all(viewer_of(e) == ident["b"] for e in cue_rows["b"]),
        "C receives no cue of A, B or F": not [e for e in cue_rows["c"] if body_of(e) in (a, b, f)] and all(viewer_of(e) == ident["c"] for e in cue_rows["c"]),
        "the anonymous connection receives no cue": not cue_rows["anon"],
        "B asking for A's cues by identity receives none": not [e for e in peek_ev if e.get("event") == "insert"],
        "A is cued B's motion": len(of(b, "seen_body_cue")) >= 3,
        "A receives B's wave (by a cue or its view)": bool(waves),
        "A receives each of B's strike windups first by a cue, within 60 ms of act_ms (B is near)": len(first) >= 5 and max(late) <= 60 and all(v[1] == "cue" for v in first.values()),
        "A is never cued F (not near, not engaged)": not [e for e in a_cues if body_of(e) == f],
        "B is in A's near tier and F in its far tier": b in tiers["near"] and f in tiers["far"],
        "the tiers partition each view: no creature in both, their union is the untiered view's rows": not any(overlap.values()) and not any(split.values()) and bool(union["seen_bodies"]),
        "replayed with the client's rule (tiers, and a cue until the creature's next row), A ends on its views' rows": not any(differ.values()),
    }
    result = {"a": a, "b": b, "c": c, "f": f, "dist": {k: round(math.dist(pos[a], pos[k]), 2) for k in (b, c, f)},
              "cues": {w: len(r) for w, r in cue_rows.items()}, "cue_tables_a": {t: sum(e["table"] == t for e in a_cues) for t in CUE_OF},
              "windups": {str(k): v for k, v in first.items()}, "differ": differ, "overlap": overlap, "split": split, "tiers": tiers, "act_window": act_window, "checks": checks}
    (out / "cues.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print(json.dumps({k: result[k] for k in ("dist", "cues", "cue_tables_a", "windups", "differ", "tiers")}))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
