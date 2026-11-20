#!/usr/bin/env python3
"""A player's combat feed as event rows (views step 2, docs/BATTLE_VIEWERS.md "Addendum 4"):
`combat_feed`, public, filtered per client by row-level security (`viewer = :sender`), one event
row per `combat_seen` row while the `combat_feed_on` law is on, delivered at commit and never kept.

    combat_feed.py --run client-...      (a run launched with verify.py launch, any seed; build the probe first)

Four players join with fresh identities: A and B 1 m apart on a quiet open line, an onlooker C
4 m from A (in sight by day), and D 40 m or more away. The law goes on; Rust SDK probes stream
from their connections on (initial rows included): A, B, C and D (`combat_feed` and `my_combat`),
an anonymous connection (`combat_feed`), B asking for A's rows by identity, and C subscribing every
public table by name, `SELECT * FROM *` and the SDK's own `subscribe_to_all_tables`. B strikes A,
A tries a refused move, then A's health is set to 1 and B kills A; a new connection of A's then
reads `my_combat` once (the reconnect read); the law goes off and B strikes C. Checks:

- row-level security: every event row a client receives names it as the viewer (A, B and C each
  receive some); D's are its own, the anonymous connection's none; B asking for A's by identity
  gets none; C's subscribe-all by name gets no one else's, `SELECT * FROM *` none at all (event
  tables left out) and the SDK helper is refused whole (it names private tables). Every probe
  must show its subscription accepted (or, the helper, refused): an empty stream proves nothing;
- the same rows: for A, B and C, the event rows and the `my_combat` rows the client received
  while the law was on are the same rows (the same ids, every field equal);
- the death screen (the GC's check): A's death as its event rows alone give it (the killer, the
  skill, the damage, the time, the place, and who saw it) equals what its `my_combat` view shows
  for that death, field by field, and what a new connection's one read of `my_combat` shows;
- the kill switch: with the law off (a `law_override` row, no reinstall: the `script` rows'
  revisions unchanged), no event row reaches anyone while `my_combat` still delivers B's and C's.

The law is put back as the world had it. Admin calls (`place_at`, `admin_set_vitals`,
`set_world_law`) set the scene. Writes `RUN/combat-feed-<who>.jsonl` and `RUN/combat_feed.json`.
Python standard library only.
"""

import argparse
import json
import math
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cues import BINARY, ROOT, V, accepted, hcall, lines, norm  # noqa: E402
from earshot import call, open_line, sql  # noqa: E402

FEED = "SELECT * FROM combat_feed"
VIEW = "SELECT * FROM my_combat"
LAW = "combat_feed_on"
DEATH, WITNESS, REFUSED = 7, 8, 9
FIELDS = ("id", "viewer", "expires_ms", "at_ms", "kind", "actor", "target", "skill", "x", "y", "dx", "dy", "amount", "ms", "note")


def stream(db, token, queries, seconds, path, all_tables=False):
    """The probe in stream mode from the connection on; with `all_tables`, the SDK's own
    `subscribe_to_all_tables` in place of `queries`."""
    req = {"uri": V.URL, "db": db, "token": token, "queries": queries, "seconds": seconds, "stream": True, "from_start": True, "all_tables": all_tables}

    def go():
        with open(path, "w") as out:
            p = subprocess.run([str(BINARY)], input=json.dumps(req), text=True, stdout=out, stderr=subprocess.DEVNULL, timeout=seconds + 60)
            out.write(json.dumps({"event": "exit", "code": p.returncode}) + "\n")

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


def rejected(events):
    return next((e.get("error") or e.get("status") for e in events if e.get("status") in ("rejected", "error")), None)


def feed(events):
    """Every `combat_feed` row a probe received (event rows arrive as inserts only)."""
    return [e["row"] for e in events if e.get("table") == "combat_feed" and e.get("event") == "insert"]


def view_rows(events):
    """Every `my_combat` row a probe received (its initial rows and each insert), by id."""
    out = {}
    for e in events:
        if e.get("event") == "initial":
            out.update({r["id"]: r for r in (e.get("tables") or {}).get("my_combat", [])})
        elif e.get("table") == "my_combat" and e.get("event") == "insert":
            out[e["row"]["id"]] = e["row"]
    return out


def view_final(events):
    """`my_combat`'s rows at the end of a probe's stream."""
    rows = {}
    for e in events:
        if e.get("event") == "initial":
            rows.update({r["id"]: r for r in (e.get("tables") or {}).get("my_combat", [])})
        elif e.get("table") == "my_combat" and e.get("event") == "insert":
            rows[e["row"]["id"]] = e["row"]
        elif e.get("table") == "my_combat" and e.get("event") == "delete":
            rows.pop(e["row"]["id"], None)
    return rows


def same(a, b):
    """Two feed rows field by field (identities normalised; floats exactly, they are one value)."""
    return all((norm(a[f]) == norm(b[f])) if f == "viewer" else a[f] == b[f] for f in FIELDS)


def death_screen(rows, me):
    """What a death screen shows of `me`'s death: the death row (killer, skill, damage, time,
    place) and who saw it (the witness rows' actors), from any one source's rows."""
    deaths = [r for r in rows if r["kind"] == DEATH and r["actor"] == me]
    if not deaths:
        return None
    d = max(deaths, key=lambda r: r["id"])
    return {"killer": d["target"], "skill": d["skill"], "amount": d["amount"], "at_ms": d["at_ms"], "x": d["x"], "y": d["y"],
            "expires_ms": d["expires_ms"], "id": d["id"],
            "witnesses": sorted(r["actor"] for r in rows if r["kind"] == WITNESS and r["target"] == me)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    st = V.load(rid)
    db = st["db"]
    out = ROOT / ".local/living/verify" / rid
    tok = {}
    for who in ("a", "b", "c", "d"):
        code, body = V.http("/v1/identity", {})
        tok[who] = json.loads(body)["token"]
        hcall(db, tok[who], "join", [f"Feed {who.upper()}"])
    chars = {c["name"]: c for c in sql(rid, "SELECT * FROM character")}
    a, b, c, d = (chars[f"Feed {x}"]["id"] for x in "ABCD")
    ident = {x: norm(chars[f"Feed {x.upper()}"]["controller"]) for x in "abcd"}
    line = open_line(rid, 30)
    call(rid, "place_at", [a, *line[10]])
    call(rid, "place_at", [b, *line[11]])
    call(rid, "place_at", [c, *line[14]])
    call(rid, "place_at", [d, line[0][0], line[0][1] + (60 if line[0][1] < 200 else -60)])
    had = {r["name"]: r["value"] for r in sql(rid, "SELECT * FROM law_override") if r.get("name") == LAW}
    rev0 = sorted((r["name"], r["revision"]) for r in sql(rid, "SELECT name, revision FROM script"))
    call(rid, "set_world_law", [LAW, "true"])
    time.sleep(1.5)
    pos = {x["id"]: (x["x"], x["y"]) for x in sql(rid, "SELECT id, x, y FROM body")}
    public = sorted(set(re.findall(r"#\[spacetimedb::table\(accessor = (\w+), public", "\n".join(
        p.read_text() for p in (ROOT / "living/authority/src").glob("*.rs")))))
    seconds = 45
    paths = {w: out / f"combat-feed-{w}.jsonl" for w in ("a", "b", "c", "d", "anon", "peek", "names", "star", "helper")}
    threads = [stream(db, tok[w], [FEED, VIEW], seconds, paths[w]) for w in "abcd"]
    threads += [stream(db, None, [FEED], seconds, paths["anon"]),
                stream(db, tok["b"], [f"{FEED} WHERE viewer = 0x{ident['a']}"], seconds, paths["peek"]),
                stream(db, tok["c"], [f"SELECT * FROM {t}" for t in public], seconds, paths["names"]),
                stream(db, tok["c"], ["SELECT * FROM *"], seconds, paths["star"]),
                stream(db, tok["c"], [], seconds, paths["helper"], all_tables=True)]
    time.sleep(3.0)
    pa = pos[a]
    # B strikes A three times; A tries a move the rules refuse (a strike at D, out of reach).
    for _ in range(3):
        hcall(db, tok["b"], "use_skill", ["strike", a, pa[0], pa[1]])
        time.sleep(1.6)
    hcall(db, tok["a"], "use_skill", ["strike", d, *pos[d]])
    time.sleep(1.6)
    # The kill: A at 1 health, B strikes until A is dead (a blow may miss or be dodged).
    call(rid, "admin_set_vitals", [a, 1.0])
    for _ in range(6):
        if not any(x["alive"] for x in sql(rid, f"SELECT alive FROM character WHERE id = {a}")):
            break
        hcall(db, tok["b"], "use_skill", ["strike", a, pa[0], pa[1]])
        time.sleep(1.6)
    killed = not any(x["alive"] for x in sql(rid, f"SELECT alive FROM character WHERE id = {a}"))
    time.sleep(1.0)
    # The reconnect read: a new connection of A's reads `my_combat` once (subscribe, take, stop).
    again = out / "combat-feed-a-again.jsonl"
    stream(db, tok["a"], [VIEW], 3, again).join()
    # Off: no event row; the view still delivers. B strikes C.
    off_ms = int(time.time() * 1000)
    call(rid, "set_world_law", [LAW, "false"])
    # B beside C (it stood 3 m off, out of reach: a strike would be refused, told to B alone).
    call(rid, "place_at", [b, *line[13]])
    time.sleep(1.0)
    pc = pos[c]
    for _ in range(2):
        hcall(db, tok["b"], "use_skill", ["strike", c, pc[0], pc[1]])
        time.sleep(1.6)
    for t in threads:
        t.join()
    rev1 = sorted((r["name"], r["revision"]) for r in sql(rid, "SELECT name, revision FROM script"))
    restore = had.get(LAW, "false")
    call(rid, "set_world_law", [LAW, restore if isinstance(restore, str) else json.dumps(restore)])
    ev = {w: lines(p) for w, p in paths.items()}
    again_ev = lines(again)
    got = {w: feed(ev[w]) for w in ev}
    on = {w: [r for r in got[w] if r["at_ms"] < off_ms] for w in "abcd"}
    off_events = [r for w in got for r in got[w] if r["at_ms"] >= off_ms + 50]
    views = {w: view_rows(ev[w]) for w in "abcd"}
    views_on = {w: {k: r for k, r in views[w].items() if r["at_ms"] < off_ms} for w in "abcd"}
    views_off = {w: {k: r for k, r in views[w].items() if r["at_ms"] >= off_ms + 50} for w in "abcd"}
    pair = {w: {"events": len(on[w]), "view": len(views_on[w]),
                "ids_equal": {r["id"] for r in on[w]} == set(views_on[w]),
                "rows_equal": all(r["id"] in views_on[w] and same(r, views_on[w][r["id"]]) for r in on[w]),
                "duplicates": len(on[w]) - len({r["id"] for r in on[w]})} for w in "abc"}
    by_event = death_screen(got["a"], a)
    by_view = death_screen(list(view_final(ev["a"]).values()), a)
    by_again = death_screen(list(view_final(again_ev).values()), a)
    helper_refusal = rejected(ev["helper"])
    foreign = lambda evs, own: [r for r in feed(evs) if norm(r["viewer"]) != own]
    checks = {
        "every probe ran to its end": all(e and e[-1].get("code") == 0 for e in ev.values()) and again_ev and again_ev[-1].get("code") == 0,
        "placed as planned (B within 1.5 m of A, C 3-6 m, D 30 m or more)": math.dist(pos[a], pos[b]) <= 1.5 and 3 <= math.dist(pos[a], pos[c]) <= 6 and math.dist(pos[a], pos[d]) >= 30,
        "every probe's subscription was accepted, the negative ones included (the SDK helper aside)": all(accepted(ev[w]) for w in ev if w != "helper") and accepted(again_ev),
        "A, B and C each receive event rows, every one naming it as the viewer": all(on[w] and all(norm(r["viewer"]) == ident[w] for r in got[w]) for w in "abc"),
        "D receives only its own event rows; the anonymous connection none": all(norm(r["viewer"]) == ident["d"] for r in got["d"]) and not got["anon"],
        "B asking for A's event rows by identity receives none": not got["peek"],
        "C subscribing every public table by name receives no one else's event row": accepted(ev["names"]) and not foreign(ev["names"], ident["c"]),
        "C subscribing SELECT * FROM * receives no event row at all (event tables left out)": accepted(ev["star"]) and not got["star"],
        "the SDK's subscribe_to_all_tables is refused whole for a player (it names private tables), nothing delivered": helper_refusal is not None and "marked private" in helper_refusal and not got["helper"],
        "law on, A, B and C: the event rows and the my_combat rows received are the same rows (ids, every field), none twice": all(p["ids_equal"] and p["rows_equal"] and p["duplicates"] == 0 and p["events"] > 0 for p in pair.values()),
        "A saw a refusal by its event rows (the actor alone)": any(r["kind"] == REFUSED and r["actor"] == a for r in got["a"]) and not any(r["kind"] == REFUSED for w in "bc" for r in got[w]),
        "B killed A": killed,
        "the death screen by the event rows alone equals the my_combat view's, field by field (killer, skill, damage, time, place, witnesses)": by_event is not None and by_event == by_view and by_event["killer"] == b,
        "a new connection's one read of my_combat shows the same death screen": by_again is not None and by_again == by_event,
        "C, who saw it, is among A's witnesses": by_event is not None and c in by_event["witnesses"],
        "law off: no event row reaches anyone, while my_combat still delivers B's and C's": not off_events and bool(views_off["b"]) and bool(views_off["c"]),
        "both switches went through a law_override row, with no reinstall (the script rows' revisions unchanged)": rev0 == rev1,
    }
    result = {"a": a, "b": b, "c": c, "d": d, "dist": {k: round(math.dist(pos[a], pos[k]), 2) for k in (b, c, d)},
              "events": {w: len(got[w]) for w in got}, "pairs": pair, "death": {"event": by_event, "view": by_view, "again": by_again},
              "helper": helper_refusal, "off_view_rows": {w: len(views_off[w]) for w in "abcd"}, "checks": checks}
    (out / "combat_feed.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print(json.dumps({k: result[k] for k in ("dist", "events", "pairs", "death", "off_view_rows")}))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
