#!/usr/bin/env python3
"""A player's lines as rows (experience-incremental, docs/HUMAN_FIGHTER_COST.md §2.5):
`experience_copy`, public, filtered per client by row-level security (`viewer = :sender`), one
row per line `my_experience` returns that player while the `lines_table_on` law is on (shipped
on), written as lines are released and trimmed and made whole again when the character the view
shows changes.

    lines_table.py --run client-...      (a run launched with verify.py launch, any seed; build the probe first)

Four players join with fresh identities: A and B 1 m apart on a quiet open line, an onlooker C
4 m from A, and D 40 m or more away. With the law on, Rust SDK probes stream from their
connections on (initial rows included): A, B, C and D (`experience_copy` and `my_experience`), an
anonymous connection (`experience_copy`), B asking for A's rows by identity, and C subscribing
every public table by name, `SELECT * FROM *` and the SDK's `subscribe_to_all_tables`. B strikes A,
A's health is set to 1 and B kills A; then A joins again (a new character). After the streams end
(A has no connection), A's character passes to the minds (`takeover_s` 2) and is handed back when A
connects again; then the law goes off, and on again. At each of those moments a fresh connection
of A's reads both. Checks:

- row-level security: every row a client receives names it as the viewer (A, B and C each receive
  some); D's are its own, the anonymous connection's none; B asking for A's by identity gets none;
  C's subscribe-all by name and `SELECT * FROM *` get none of anyone else's, and the SDK helper is
  refused whole (it names private tables). Every probe must show its subscription accepted;
- the same rows: for A, B and C, the copies and the `my_experience` rows held at the end of the
  stream are the same rows (the same ids, every field equal), and none arrived twice;
- the death screen: dead, A's copies equal its view (the dead character's lines);
- a rejoin: A's copies follow its view to the new character's lines, none of the dead one's;
- takeover and return: while the minds hold A's character, A has no copy and its record names no
  character; handed back, its copies equal its view again;
- the kill switch and back: with the law off (a `law_override` row, no reinstall) no copy is left
  and the view still shows A's lines; on again, A's copies equal its view.

The laws are put back as the world had them. Admin calls (`place_at`, `admin_set_vitals`,
`set_world_law`) set the scene. Writes `RUN/lines-table-<who>.jsonl` and `RUN/lines_table.json`.
Python standard library only.
"""

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cues import ROOT, V, accepted, hcall, lines, norm  # noqa: E402
from earshot import call, open_line, sql  # noqa: E402
from combat_feed import rejected, stream  # noqa: E402

COPY = "SELECT * FROM experience_copy"
VIEW = "SELECT * FROM my_experience"
LAW = "lines_table_on"


def held(events, table):
    """What a probe holds of `table` at the end of its stream: its initial rows, then every
    insert, update and delete, by id."""
    rows = {}
    for e in events:
        if e.get("event") == "initial":
            rows.update({r["id"]: r for r in (e.get("tables") or {}).get(table, [])})
        elif e.get("table") == table and e.get("event") in ("insert", "update"):
            rows[e["row"]["id"]] = e["row"]
        elif e.get("table") == table and e.get("event") == "delete":
            rows.pop(e["row"]["id"], None)
    return rows


def received(events, table):
    """Every row of `table` a probe received (its initial rows and each insert or update)."""
    out = [r for e in events if e.get("event") == "initial" for r in (e.get("tables") or {}).get(table, [])]
    return out + [e["row"] for e in events if e.get("table") == table and e.get("event") in ("insert", "update")]


def pair(events):
    """The copies and the view held at the end, compared: (equal, copies, view rows)."""
    copies = {k: r["row"] for k, r in held(events, "experience_copy").items()}
    view = held(events, "my_experience")
    return copies == view, len(copies), len(view)


def read(db, token, path):
    """A fresh connection's read of both (subscribe, hold for 3 s, stop)."""
    stream(db, token, [COPY, VIEW], 3, path).join()
    return lines(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    st = V.load(rid)
    db = st["db"]
    out = ROOT / ".local/living/verify" / rid
    laws = {r["name"]: r["value"] for r in sql(rid, "SELECT * FROM law_override")}
    call(rid, "set_world_law", [LAW, "true"])
    tok = {}
    for who in ("a", "b", "c", "d"):
        code, body = V.http("/v1/identity", {})
        tok[who] = json.loads(body)["token"]
        hcall(db, tok[who], "join", [f"Lines {who.upper()}"])
    chars = {c["name"]: c for c in sql(rid, "SELECT * FROM character")}
    a, b, c, d = (chars[f"Lines {x}"]["id"] for x in "ABCD")
    ident = {x: norm(chars[f"Lines {x.upper()}"]["controller"]) for x in "abcd"}
    line = open_line(rid, 30)
    call(rid, "place_at", [a, *line[10]])
    call(rid, "place_at", [b, *line[11]])
    call(rid, "place_at", [c, *line[14]])
    call(rid, "place_at", [d, line[0][0], line[0][1] + (60 if line[0][1] < 200 else -60)])
    time.sleep(1.5)
    pos = {x["id"]: (x["x"], x["y"]) for x in sql(rid, "SELECT id, x, y FROM body")}
    public = sorted(set(re.findall(r"#\[spacetimedb::table\(accessor = (\w+), public", "\n".join(
        p.read_text() for p in (ROOT / "living/authority/src").glob("*.rs")))))
    seconds = 40
    paths = {w: out / f"lines-table-{w}.jsonl" for w in ("a", "b", "c", "d", "anon", "peek", "names", "star", "helper")}
    threads = [stream(db, tok[w], [COPY, VIEW], seconds, paths[w]) for w in "abcd"]
    threads += [stream(db, None, [COPY], seconds, paths["anon"]),
                stream(db, tok["b"], [f"{COPY} WHERE viewer = 0x{ident['a']}"], seconds, paths["peek"]),
                stream(db, tok["c"], [f"SELECT * FROM {t}" for t in public], seconds, paths["names"]),
                stream(db, tok["c"], ["SELECT * FROM *"], seconds, paths["star"]),
                stream(db, tok["c"], [], seconds, paths["helper"], all_tables=True)]
    time.sleep(3.0)
    pa = pos[a]
    for _ in range(3):
        hcall(db, tok["b"], "use_skill", ["strike", a, pa[0], pa[1]])
        time.sleep(1.6)
    call(rid, "admin_set_vitals", [a, 1.0])
    for _ in range(6):
        if not any(x["alive"] for x in sql(rid, f"SELECT alive FROM character WHERE id = {a}")):
            break
        hcall(db, tok["b"], "use_skill", ["strike", a, pa[0], pa[1]])
        time.sleep(1.6)
    killed = not any(x["alive"] for x in sql(rid, f"SELECT alive FROM character WHERE id = {a}"))
    time.sleep(1.5)
    dead_ev = read(db, tok["a"], out / "lines-table-a-dead.jsonl")
    # A joins again: a new character, the view's lines are its.
    hcall(db, tok["a"], "join", ["Lines A2"])
    time.sleep(1.5)
    a2 = max(x["id"] for x in sql(rid, "SELECT id, name FROM character") if x["name"] == "Lines A2")
    call(rid, "place_at", [a2, *line[10]])
    rejoin_ev = read(db, tok["a"], out / "lines-table-a-rejoin.jsonl")
    for t in threads:
        t.join()
    # Takeover: no connection of A's for `takeover_s`; the minds hold its character.
    call(rid, "set_world_law", ["takeover_s", "2"])
    time.sleep(5.0)
    held_ai = [x for x in sql(rid, f"SELECT id, ai FROM character WHERE id = {a2}")]
    state_ai = [x for x in sql(rid, "SELECT * FROM lines_state") if norm(x["viewer"]) == ident["a"]]
    copies_ai = [x for x in sql(rid, "SELECT id, viewer FROM experience_copy") if norm(x["viewer"]) == ident["a"]]
    # Return: A connects again (the character is handed back at the connection).
    back_path = out / "lines-table-a-back.jsonl"
    back_stream = stream(db, tok["a"], [COPY, VIEW], 10, back_path)
    held_back = []
    while back_stream.is_alive():
        held_back = sql(rid, f"SELECT id, ai FROM character WHERE id = {a2}")
        if held_back and not held_back[0]["ai"]:
            break
        time.sleep(0.1)
    back_stream.join()
    back_ev = lines(back_path)
    back2_ev = read(db, tok["a"], out / "lines-table-a-back2.jsonl")
    # The kill switch, then on again (`takeover_s` above is an ordinary law: its change reinstalls
    # the script, so the revisions are taken around these two switches alone).
    rev0 = sorted((r["name"], r["revision"]) for r in sql(rid, "SELECT name, revision FROM script"))
    call(rid, "set_world_law", [LAW, "false"])
    time.sleep(1.5)
    off_copies = len(sql(rid, "SELECT id FROM experience_copy"))
    off_state = len(sql(rid, "SELECT * FROM lines_state"))
    off_ev = read(db, tok["a"], out / "lines-table-a-off.jsonl")
    call(rid, "set_world_law", [LAW, "true"])
    time.sleep(2.0)
    on_ev = read(db, tok["a"], out / "lines-table-a-on.jsonl")
    rev1 = sorted((r["name"], r["revision"]) for r in sql(rid, "SELECT name, revision FROM script"))
    for name, default in ((LAW, "true"), ("takeover_s", "30.0")):
        v = laws.get(name, default)
        call(rid, "set_world_law", [name, v if isinstance(v, str) else json.dumps(v)])
    ev = {w: lines(p) for w, p in paths.items()}
    got = {w: received(ev[w], "experience_copy") for w in ev}
    foreign = lambda w, own: [r for r in got[w] if norm(r["viewer"]) != own]
    pairs = {w: pair(ev[w]) for w in "abc"}
    dupes = {w: len([r for e in ev[w] if e.get("table") == "experience_copy" and e.get("event") == "insert" for r in [e["row"]]]) -
             len({e["row"]["id"] for e in ev[w] if e.get("table") == "experience_copy" and e.get("event") == "insert"}) for w in "abc"}
    dead_view = held(dead_ev, "my_experience")
    rejoin_copies = {k: r["row"] for k, r in held(rejoin_ev, "experience_copy").items()}
    off_view = held(off_ev, "my_experience")
    helper_refusal = rejected(ev["helper"])
    checks = {
        "every probe ran to its end": all(e and e[-1].get("code") == 0 for e in ev.values()) and all(x and x[-1].get("code") == 0 for x in (dead_ev, rejoin_ev, back_ev, back2_ev, off_ev, on_ev)),
        "placed as planned (B within 1.5 m of A, C 3-6 m, D 30 m or more)": math.dist(pos[a], pos[b]) <= 1.5 and 3 <= math.dist(pos[a], pos[c]) <= 6 and math.dist(pos[a], pos[d]) >= 30,
        "every probe's subscription was accepted, the negative ones included (the SDK helper aside)": all(accepted(ev[w]) for w in ev if w != "helper") and all(accepted(x) for x in (dead_ev, rejoin_ev, back_ev, back2_ev, off_ev, on_ev)),
        "A, B and C each receive copies, every one naming it as the viewer": all(got[w] and not foreign(w, ident[w]) for w in "abc"),
        "D receives only its own copies; the anonymous connection none": not foreign("d", ident["d"]) and not got["anon"],
        "B asking for A's copies by identity receives none": not got["peek"],
        "C subscribing every public table by name receives no one else's copy": accepted(ev["names"]) and not foreign("names", ident["c"]),
        "C subscribing SELECT * FROM * receives no one else's copy": accepted(ev["star"]) and not foreign("star", ident["c"]),
        "the SDK's subscribe_to_all_tables is refused whole for a player (it names private tables), nothing delivered": helper_refusal is not None and "marked private" in helper_refusal and not got["helper"],
        "A, B and C: the copies and my_experience held at the end are the same rows (ids, every field; B and C hold some, A has just joined again), none inserted twice": all(p[0] for p in pairs.values()) and pairs["b"][1] > 0 and pairs["c"][1] > 0 and not any(dupes.values()),
        "B killed A": killed,
        "dead: A's copies equal its view (the dead character's lines)": pair(dead_ev)[0] and bool(dead_view) and all(r["observer"] == a for r in dead_view.values()),
        "rejoined: A's copies equal its view, none of the dead character's lines": pair(rejoin_ev)[0] and all(r["observer"] == a2 for r in rejoin_copies.values()),
        "taken over: the minds hold A's character, A has no copy and its record names no character": bool(held_ai) and held_ai[0]["ai"] and not copies_ai and bool(state_ai) and state_ai[0]["character"] == 0,
        "handed back: A's character is A's again and its copies equal its view": bool(held_back) and not held_back[0]["ai"] and pair(back2_ev)[0] and pair(back2_ev)[2] > 0,
        "law off: no copy and no record is left, and the view still shows A's lines": off_copies == 0 and off_state == 0 and bool(off_view) and not received(off_ev, "experience_copy"),
        "law on again: A's copies equal its view": pair(on_ev)[0] and pair(on_ev)[1] > 0,
        "the lines_table_on switches went through law_override rows, with no reinstall (the script rows' revisions unchanged)": rev0 == rev1,
    }
    result = {"a": a, "a2": a2, "b": b, "c": c, "d": d, "dist": {k: round(math.dist(pos[a], pos[k]), 2) for k in (b, c, d)},
              "copies": {w: len(got[w]) for w in got}, "pairs": pairs, "dupes": dupes,
              "moments": {"dead": pair(dead_ev), "rejoin": pair(rejoin_ev), "back": pair(back_ev), "back2": pair(back2_ev), "off": [off_copies, off_state, len(off_view)], "on": pair(on_ev)},
              "takeover": {"character": held_ai, "state": state_ai, "copies": len(copies_ai), "back": held_back},
              "helper": helper_refusal, "checks": checks}
    (out / "lines_table.json").write_text(json.dumps(result, indent=1, default=str) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print(json.dumps({k: result[k] for k in ("dist", "copies", "pairs", "moments")}, default=str))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
