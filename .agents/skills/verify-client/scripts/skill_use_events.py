#!/usr/bin/env python3
"""Skill uses for exporters, and a dead fighter's uses drained after the grace (skill-use-drain,
docs/COMBAT.md "Skill uses"): `skill_use_event`, a private event table (the owner's alone, never
kept), carries each `skill_use` row as it was finished; `dead_skill_use_due`, private, holds each
dead character whose rows go `DEAD_USES_GRACE_MS` (120 s) after its death.

    skill_use_events.py --run client-...   (a run launched with verify.py launch, any seed; build the probe first)

Three players join with fresh identities: A and B 1 m apart on a quiet open line, D 40 m or more
away. Rust SDK probes stream `skill_use_event` from their connections on: the owner (the world
admin's token), an anonymous connection and player A. B strikes A three times, A tries a strike
at D (out of reach: refused), then A's health is set to 1 and B strikes until A is dead. The
script reads A's and B's `skill_use` rows and A's `dead_skill_use_due` row (owner SQL) right
after the death, waits past the grace, and reads them again. Checks:

- privacy: the anonymous connection and player A are refused (`private`), nothing delivered;
  owner SQL of the event table returns no row (it holds none between transactions);
- the events: every finished row (an outcome, not "in flight") of A and B read at the end has an
  `outcome` event equal to it, field by field, and the last event per use id is its final row;
  the refused strike is among them; no event names an actor other than A and B;
- the grace: A's `dead_skill_use_due` row is due 120 s after its death; A's rows are there at its
  death and gone (with the due row) once the grace is over, while B's are still there; A's rows
  that never had an outcome event (if any) were sent as `drained`.

Writes `RUN/skill-use-events-<who>.jsonl` and `RUN/skill_use_events.json`. Python standard
library only.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cues import ROOT, V, accepted, hcall, lines  # noqa: E402
from earshot import call, open_line, sql  # noqa: E402
from combat_feed import stream  # noqa: E402

EVENTS = "SELECT * FROM skill_use_event"
GRACE_MS = 120_000
FIELDS = ("id", "actor", "skill", "source", "at_ms", "target", "aim_x", "aim_y", "accepted_ms", "released_ms", "outcome", "outcome_ms")


def events(evs):
    """Every `skill_use_event` row a probe received, as (why, sent_ms, row)."""
    return [(e["row"]["why"], e["row"]["sent_ms"], e["row"]["skill_use"]) for e in evs
            if e.get("table") == "skill_use_event" and e.get("event") == "insert"]


def same(a, b):
    return all(math.isclose(float(a[f]), float(b[f]), abs_tol=1e-4) if f in ("aim_x", "aim_y") else a[f] == b[f] for f in FIELDS)


def finished(u):
    return bool(u["outcome"]) and u["outcome"] != "in flight"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    st = V.load(rid)
    db = st["db"]
    out = ROOT / ".local/living/verify" / rid
    tok = {}
    for who in ("a", "b", "d"):
        code, body = V.http("/v1/identity", {})
        tok[who] = json.loads(body)["token"]
        hcall(db, tok[who], "join", [f"Uses {who.upper()}"])
    chars = {c["name"]: c for c in sql(rid, "SELECT * FROM character")}
    a, b, d = (chars[f"Uses {x}"]["id"] for x in "ABD")
    line = open_line(rid, 30)
    call(rid, "place_at", [a, *line[10]])
    call(rid, "place_at", [b, *line[11]])
    call(rid, "place_at", [d, line[0][0], line[0][1] + (60 if line[0][1] < 200 else -60)])
    time.sleep(1.5)
    pos = {x["id"]: (x["x"], x["y"]) for x in sql(rid, "SELECT id, x, y FROM body")}
    seconds = 60 + GRACE_MS // 1000 + 30
    paths = {w: out / f"skill-use-events-{w}.jsonl" for w in ("owner", "anon", "player")}
    threads = [stream(db, V.admin_token(), [EVENTS], seconds, paths["owner"]),
               stream(db, None, [EVENTS], 20, paths["anon"]),
               stream(db, tok["a"], [EVENTS], 20, paths["player"])]
    time.sleep(3.0)
    pa = pos[a]
    for _ in range(3):
        hcall(db, tok["b"], "use_skill", ["strike", a, pa[0], pa[1]])
        time.sleep(1.6)
    hcall(db, tok["a"], "use_skill", ["strike", d, *pos[d]])
    time.sleep(1.6)
    call(rid, "admin_set_vitals", [a, 1.0])
    for _ in range(8):
        if not any(x["alive"] for x in sql(rid, f"SELECT alive FROM character WHERE id = {a}")):
            break
        hcall(db, tok["b"], "use_skill", ["strike", a, pa[0], pa[1]])
        time.sleep(1.6)
    dead = sql(rid, f"SELECT alive, died_ms FROM character WHERE id = {a}")[0]
    killed = not dead["alive"]
    died_ms = int(dead["died_ms"])
    at_death = {"a": sql(rid, f"SELECT * FROM skill_use WHERE actor = {a}"),
                "due": sql(rid, f"SELECT * FROM dead_skill_use_due WHERE actor = {a}")}
    try:
        owner_sql_events, owner_sql_error = sql(rid, EVENTS), ""
    except Exception as e:  # noqa: BLE001 (the SQL refusal is the evidence)
        owner_sql_events, owner_sql_error = [], str(e)
    # Past the grace (the world's clock is the wall clock outside det_clock), plus housekeeping's second.
    wait = died_ms + GRACE_MS + 3_000 - int(time.time() * 1000)
    time.sleep(max(0, wait) / 1000)
    after = {"a": sql(rid, f"SELECT * FROM skill_use WHERE actor = {a}"),
             "due": sql(rid, f"SELECT * FROM dead_skill_use_due WHERE actor = {a}"),
             "b": sql(rid, f"SELECT * FROM skill_use WHERE actor = {b}")}
    for t in threads:
        t.join()
    ev = {w: lines(p) for w, p in paths.items()}
    got = events(ev["owner"])
    last = {}
    for why, sent, u in got:
        last[u["id"]] = (why, sent, u)
    final_rows = {u["id"]: u for u in at_death["a"] + after["b"]}
    done = [u for u in final_rows.values() if finished(u)]
    open_rows = [u for u in at_death["a"] if not finished(u)]
    refusal = [u for u in at_death["a"] if u["skill"] == "strike" and u["target"] == d and u["accepted_ms"] == 0 and u["outcome"].startswith("refused")]
    checks = {
        "every probe ran to its end": all(e and e[-1].get("code") == 0 for e in ev.values()),
        "the owner's subscription was accepted": accepted(ev["owner"]),
        "anonymous and player subscriptions are refused as private, nothing delivered":
            all(any(x.get("status") == "rejected" and "private" in str(x.get("error", "")).lower() for x in ev[w]) and not events(ev[w]) for w in ("anon", "player")),
        "owner SQL of the event table returns no row": not owner_sql_events,
        "B killed A": killed,
        "A had skill_use rows at its death, the refused strike at D among them": bool(at_death["a"]) and bool(refusal),
        "every finished row of A and B has an outcome event equal to it": bool(done) and all(
            any(why == "outcome" and same(u, r) for why, _, r in got if r["id"] == u["id"]) for u in done),
        "the last event per use id is that use's final row": all(same(last[k][2], u) for k, u in final_rows.items() if k in last),
        "no event names an actor other than A and B": all(r["actor"] in (a, b) for _, _, r in got),
        "A's dead_skill_use_due row is due 120 s after its death": len(at_death["due"]) == 1 and int(at_death["due"][0]["due_ms"]) == died_ms + GRACE_MS,
        "past the grace A's rows and its due row are gone, B's still there": not after["a"] and not after["due"] and bool(after["b"]),
        "A's rows that never had an outcome were sent as drained":
            all(any(why == "drained" and r["id"] == u["id"] for why, _, r in got) for u in open_rows),
    }
    result = {"a": a, "b": b, "d": d, "died_ms": died_ms, "events": len(got), "by_why": {w: sum(1 for x in got if x[0] == w) for w in ("outcome", "trimmed", "drained")},
              "a_rows_at_death": len(at_death["a"]), "a_open_at_death": len(open_rows), "due": at_death["due"], "after": {k: len(v) for k, v in after.items()},
              "owner_sql_error": owner_sql_error[:200], "checks": checks}
    (out / "skill_use_events.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print(json.dumps({k: result[k] for k in ("events", "by_why", "a_rows_at_death", "a_open_at_death", "after")}))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
