#!/usr/bin/env python3
"""The public copy tables as real clients receive them (battle-views, docs/BATTLE_VIEWERS.md,
"Addendum: B on the motion stream" and addendum 2): `seen_body_copy` (the motion copies, the
`motion_tables_on` law) and `seen_character_copy` (the mirror of a player's projections, the
`characters_table_on` law), each filtered per client by row-level security.

    motion_tables.py --run client-...      (a run launched with verify.py launch, any seed; build the probe first)

With the `motion_tables_on` law on, a player's motion copies are rows of the public
`seen_body_copy` table, which row-level security (`viewer = :sender`) filters per client, in
place of the private `motion_seen`/`motion_near` tables behind the motion views. Three players
join with fresh identities: A and B 1 m apart on a quiet open line, a held stranger F 10 m from
A, and C 40 m or more away. The law goes on; Rust SDK probes stream from their connections on
(the initial rows checked, not only the changes) while B steps and F is moved: A (the table, the
motion views and their tiers, `my_body`), B, C and an anonymous connection (the table). Checks:

- row-level security: every row a client receives names it as the viewer; C and the anonymous
  connection receive none of A's or B's; B asking for A's rows by identity, by subscription and
  by SQL, gets nothing; C subscribing every public table by name (what the SDK's
  `subscribe_to_all_tables` sends) and `SELECT * FROM *` receives no one else's row. Every probe
  must show its subscription accepted: an empty stream from a refused subscription proves nothing;
- the copies: A's rows hold B (near) and F (far); A's table ends on exactly the rows of its
  `seen_bodies` view, and its `near` flag on exactly the tier views' split; the private tables
  hold none of A's copies;
- the mirror: the same isolation checks for `seen_character_copy`, and A's mirror ends on exactly
  the rows of its `seen_characters` view;
- the kill switches: both laws off (each a `law_override` row, no reinstall), both tables are empty
  to the owner within a second, A's stream of the motion table ends empty, and A's views still
  show the same creatures (the motion copies from the private tables); on again, A's rows return
  in both. The laws are put back as the world had them.

Admin calls (`spawn_crowd`, `set_behavior`, `place_at`, `set_world_law`) set the scene. Writes
`RUN/motion-tables-<who>.jsonl` and `RUN/motion_tables.json`. Python standard library only.
"""

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cues import ROOT, V, accepted, hcall, lines, norm, stream  # noqa: E402
from earshot import call, open_line, sql  # noqa: E402

TABLE = "SELECT * FROM seen_body_copy"
CHARS = "SELECT * FROM seen_character_copy"
FIGHT = "SELECT * FROM seen_fighter_copy"
VIEWS = ["SELECT * FROM seen_bodies", "SELECT * FROM seen_bodies_near", "SELECT * FROM seen_bodies_far", "SELECT * FROM my_body", "SELECT * FROM seen_characters",
         "SELECT * FROM seen_fighters", "SELECT * FROM seen_fighters_near", "SELECT * FROM seen_fighters_far"]
LAWS = ("motion_tables_on", "characters_table_on", "fighter_tables_on")


def player_sql(db, token, query):
    code, body = V.http(f"/v1/database/{db}/sql", query, token, raw=True)
    if code != 200:
        raise RuntimeError(f"{query}: {code} {body[:200]}")
    res = json.loads(body)[0]
    names = [c["name"]["some"] if isinstance(c.get("name"), dict) else c.get("name") for c in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def final(events, table):
    """A table's rows at the end of a probe's stream (its initial rows, then each change), by `id`;
    `seen_body_copy` (no primary key: a change is a delete and an insert, in either order) by its
    `body`, as the set of rows the stream leaves."""
    if table == "seen_body_copy":
        # A set of rows: the probe streams from the connection on, so the initial rows arrive both
        # as inserts and in the `initial` snapshot; a change's delete and insert carry different rows.
        rows = set()
        for e in events:
            if e.get("event") == "initial":
                rows |= {json.dumps(r, sort_keys=True) for r in (e.get("tables") or {}).get(table, [])}
            elif e.get("table") == table and e.get("event") == "insert":
                rows.add(json.dumps(e["row"], sort_keys=True))
            elif e.get("table") == table and e.get("event") == "delete":
                rows.discard(json.dumps(e["row"], sort_keys=True))
        # By (viewer, creature): a leak (another viewer's rows) stays visible to the checks.
        out = {}
        for k in rows:
            r = json.loads(k)
            out[(norm(r["viewer"]), r["body"])] = r
        return out
    rows = {}
    for e in events:
        if e.get("event") == "initial":
            rows.update({r["id"]: r for r in (e.get("tables") or {}).get(table, [])})
        elif e.get("table") == table and e.get("event") in ("insert", "update"):
            rows[e["row"]["id"]] = e["row"]
        elif e.get("table") == table and e.get("event") == "delete":
            rows.pop(e["row"]["id"], None)
    return rows


def moving_of(r):
    """The `Moving` a `seen_body_copy` row stands for: its `body` and its segment."""
    return {"id": r["body"], **r["seg"]}


def copies(events, table="seen_body_copy"):
    """Every row of a copy table a probe received: its initial rows and each insert or update."""
    out = []
    for e in events:
        if e.get("event") == "initial":
            out += (e.get("tables") or {}).get(table, [])
        elif e.get("table") == table and e.get("event") in ("insert", "update"):
            out.append(e["row"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    db = V.load(rid)["db"]
    out = ROOT / ".local/living/verify" / rid
    tok = {}
    for who in ("a", "b", "c"):
        tok[who] = json.loads(V.http("/v1/identity", {})[1])["token"]
        hcall(db, tok[who], "join", [f"Copy {who.upper()}"])
    chars = {c["name"]: c for c in sql(rid, "SELECT * FROM character")}
    a, b, c = (chars[f"Copy {x}"]["id"] for x in "ABC")
    ident = {x: norm(chars[f"Copy {x.upper()}"]["controller"]) for x in "abc"}
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
    # The world's own values live in `law_override` (docs/LAW_OVERRIDE.md).
    had = {r["name"]: r["value"] for r in sql(rid, "SELECT * FROM law_override") if r.get("name") in LAWS}
    for law in LAWS:
        call(rid, "set_world_law", [law, "true"])
    time.sleep(2.0)
    pos = {x["id"]: (x["x"], x["y"]) for x in sql(rid, "SELECT id, x, y FROM body")}
    seconds = 16
    paths = {w: out / f"motion-tables-{w}.jsonl" for w in ("a", "b", "c", "anon")}
    threads = [stream(db, tok["a"], [TABLE, CHARS, FIGHT] + VIEWS, seconds, paths["a"]),
               stream(db, tok["b"], [TABLE, CHARS, FIGHT], seconds, paths["b"]),
               stream(db, tok["c"], [TABLE, CHARS, FIGHT], seconds, paths["c"]),
               stream(db, None, [TABLE, CHARS, FIGHT], seconds, paths["anon"])]
    time.sleep(2.0)
    # A fight, so the fighter copies have rows (views step 3): B strikes A once.
    hcall(db, tok["b"], "use_skill", ["strike", a, pos[a][0], pos[a][1]])
    peek = stream(db, tok["b"], [f"SELECT * FROM seen_body_copy WHERE viewer = 0x{ident['a']}",
                                 f"SELECT * FROM seen_character_copy WHERE viewer = 0x{ident['a']}",
                                 f"SELECT * FROM seen_fighter_copy WHERE viewer = 0x{ident['a']}"], 10, out / "motion-tables-b-peek.jsonl")
    public = sorted(set(re.findall(r"#\[spacetimedb::table\(accessor = (\w+), public", "\n".join(
        p.read_text() for p in (ROOT / "living/authority/src").glob("*.rs")))))
    all_c = stream(db, tok["c"], [f"SELECT * FROM {t}" for t in public], 10, out / "motion-tables-c-all-names.jsonl")
    star_c = stream(db, tok["c"], ["SELECT * FROM *"], 10, out / "motion-tables-c-star.jsonl")
    # B's own SQL: its rows only, and none of A's by identity.
    b_sql = player_sql(db, tok["b"], "SELECT * FROM seen_body_copy")
    b_peek_sql = player_sql(db, tok["b"], f"SELECT * FROM seen_body_copy WHERE viewer = 0x{ident['a']}")
    b_chars_sql = player_sql(db, tok["b"], "SELECT * FROM seen_character_copy")
    b_peek_chars = player_sql(db, tok["b"], f"SELECT * FROM seen_character_copy WHERE viewer = 0x{ident['a']}")
    time.sleep(1.0)
    b_fight_sql = player_sql(db, tok["b"], FIGHT)
    b_peek_fight = player_sql(db, tok["b"], f"SELECT * FROM seen_fighter_copy WHERE viewer = 0x{ident['a']}")
    for dx in (1, -1, 1):
        hcall(db, tok["b"], "human_move", [dx, 0, False])
        time.sleep(0.4)
        hcall(db, tok["b"], "human_move", [0, 0, False])
        call(rid, "place_at", [f, line[20][0] + dx * 0.5, line[20][1]])
        time.sleep(0.6)
    call(rid, "place_at", [b, *line[11]])
    for t in threads + [peek, all_c, star_c]:
        t.join()
    ev = {w: lines(p) for w, p in paths.items()}
    peek_ev = lines(out / "motion-tables-b-peek.jsonl")
    all_ev, star_ev = lines(out / "motion-tables-c-all-names.jsonl"), lines(out / "motion-tables-c-star.jsonl")
    got = {w: copies(e) for w, e in ev.items()}
    a_table = final(ev["a"], "seen_body_copy")
    a_view = final(ev["a"], "seen_bodies")
    a_near, a_far = final(ev["a"], "seen_bodies_near"), final(ev["a"], "seen_bodies_far")
    by_body = {b: r for (v, b), r in a_table.items() if v == ident["a"]}
    private_a = sql(rid, f"SELECT COUNT(*) AS n FROM motion_seen WHERE viewer = 0x{ident['a']}")[0]["n"] + \
        sql(rid, f"SELECT COUNT(*) AS n FROM motion_near WHERE viewer = 0x{ident['a']}")[0]["n"]
    foreign_c = lambda evs: [r for t in ("seen_body_copy", "seen_character_copy", "seen_fighter_copy") for r in copies(evs, t) if norm(r["viewer"]) != ident["c"]]
    gotf = {w: copies(e, "seen_fighter_copy") for w, e in ev.items()}
    # Keyed by `id` (views step 3): a change is an update.
    a_ftable = final(ev["a"], "seen_fighter_copy")
    f_by_body = {r["body"]: r for r in a_ftable.values() if norm(r["viewer"]) == ident["a"]}
    a_fview = final(ev["a"], "seen_fighters")
    a_fnear, a_ffar = final(ev["a"], "seen_fighters_near"), final(ev["a"], "seen_fighters_far")
    private_fa = sql(rid, f"SELECT COUNT(*) AS n FROM fighter_seen WHERE viewer = 0x{ident['a']}")[0]["n"] + \
        sql(rid, f"SELECT COUNT(*) AS n FROM fighter_near WHERE viewer = 0x{ident['a']}")[0]["n"]
    gotc = {w: copies(e, "seen_character_copy") for w, e in ev.items()}
    a_mirror = {r["row"]["id"]: r["row"] for r in final(ev["a"], "seen_character_copy").values()}
    a_chars = final(ev["a"], "seen_characters")
    checks = {
        "every probe ran to its end": all(e[-1].get("code") == 0 for e in ev.values()) and peek_ev[-1].get("code") == 0,
        "placed as planned (B within 1.5 m of A, F 9-12 m, C 30 m or more)": math.dist(pos[a], pos[b]) <= 1.5 and 9 <= math.dist(pos[a], pos[f]) <= 12 and math.dist(pos[a], pos[c]) >= 30,
        "every probe's subscription was accepted (applied, never rejected), the negative ones included": all(accepted(e) for e in ev.values()) and accepted(peek_ev) and accepted(all_ev) and accepted(star_ev),
        "every row A receives names A as the viewer": bool(got["a"]) and all(norm(r["viewer"]) == ident["a"] for r in got["a"]),
        "every row B receives names B": bool(got["b"]) and all(norm(r["viewer"]) == ident["b"] for r in got["b"]),
        "C receives only its own rows, none of A's or B's": all(norm(r["viewer"]) == ident["c"] for r in got["c"]),
        "the anonymous connection receives no row": not got["anon"],
        "B subscribing A's rows by identity receives none": not copies(peek_ev),
        "B's SQL reads only its own rows, and none of A's by identity": bool(b_sql) and all(norm(r["viewer"]) == ident["b"] for r in b_sql) and not b_peek_sql,
        "C subscribing every public table by name (the SDK's subscribe-all) receives no one else's row": not foreign_c(all_ev),
        "C subscribing SELECT * FROM * receives no one else's row": not foreign_c(star_ev),
        "A's table holds only A's rows at the end": bool(a_table) and all(v == ident["a"] for v, _ in a_table),
        "A's rows hold B in the near tier and F in the far tier": by_body.get(b, {}).get("near") is True and by_body.get(f, {}).get("near") is False,
        "A's table ends on exactly its seen_bodies view's rows": bool(a_view) and {k: moving_of(r) for k, r in by_body.items()} == a_view,
        "A's near flags split exactly as its tier views": {k for k, r in by_body.items() if r["near"]} == set(a_near) and {k for k, r in by_body.items() if not r["near"]} == set(a_far),
        "the private copy tables hold none of A's copies while the law is on": private_a == 0,
        "mirror: every row A receives names A, and every row B receives names B": bool(gotc["a"]) and all(norm(r["viewer"]) == ident["a"] for r in gotc["a"]) and bool(gotc["b"]) and all(norm(r["viewer"]) == ident["b"] for r in gotc["b"]),
        "mirror: C receives only its own rows; the anonymous connection none": all(norm(r["viewer"]) == ident["c"] for r in gotc["c"]) and not gotc["anon"],
        "mirror: B subscribing A's rows by identity, and asking by SQL, gets none; its own SQL only its own": not copies(peek_ev, "seen_character_copy") and not b_peek_chars and bool(b_chars_sql) and all(norm(r["viewer"]) == ident["b"] for r in b_chars_sql),
        "mirror: A's table ends on exactly its seen_characters view's rows": bool(a_chars) and a_mirror == a_chars,
        "fighters: every row A receives names A, every row B receives names B, C only its own; the anonymous connection none": bool(gotf["a"]) and all(norm(r["viewer"]) == ident["a"] for r in gotf["a"])
        and all(norm(r["viewer"]) == ident["b"] for r in gotf["b"]) and all(norm(r["viewer"]) == ident["c"] for r in gotf["c"]) and not gotf["anon"],
        "fighters: B subscribing A's rows by identity, and asking by SQL, gets none; its own SQL only its own": not copies(peek_ev, "seen_fighter_copy") and not b_peek_fight and all(norm(r["viewer"]) == ident["b"] for r in b_fight_sql),
        "fighters: A's table holds B (it fought) and ends on exactly its seen_fighters view's rows": b in f_by_body and {k: r["fighter"] for k, r in f_by_body.items()} == a_fview,
        "fighters: A's near flags split exactly as its fighter tier views": {k for k, r in f_by_body.items() if r["near"]} == set(a_fnear) and {k for k, r in f_by_body.items() if not r["near"]} == set(a_ffar),
        "fighters: the private fighter tables hold none of A's copies while the law is on": private_fa == 0,
    }
    # The kill switch: off, every public copy goes back at once; the views still show the scene.
    seen_on = {r["id"] for r in player_sql(db, tok["a"], "SELECT id FROM seen_bodies")}
    # The switch is a value-only law (docs/LAW_OVERRIDE.md): an override row, no reinstall.
    script_rev = sorted((r["name"], r["revision"]) for r in sql(rid, "SELECT name, revision FROM script"))
    off_path = out / "motion-tables-off-a.jsonl"
    chars_on = {r["id"] for r in player_sql(db, tok["a"], "SELECT id FROM seen_characters")}
    fight_on = {r["id"] for r in player_sql(db, tok["a"], "SELECT id FROM seen_fighters")}
    off_stream = stream(db, tok["a"], [TABLE], 6, off_path)
    time.sleep(2.0)
    for law in LAWS:
        call(rid, "set_world_law", [law, "false"])
    time.sleep(1.0)
    owner_after = sql(rid, "SELECT COUNT(*) AS n FROM seen_body_copy")[0]["n"]
    owner_chars = sql(rid, "SELECT COUNT(*) AS n FROM seen_character_copy")[0]["n"]
    owner_fight = sql(rid, "SELECT COUNT(*) AS n FROM seen_fighter_copy")[0]["n"]
    call(rid, "set_paused", [True])
    try:
        fight_off = {r["id"] for r in player_sql(db, tok["a"], "SELECT id FROM seen_fighters")}
        private_foff = sql(rid, f"SELECT COUNT(*) AS n FROM fighter_seen WHERE viewer = 0x{ident['a']}")[0]["n"] + \
            sql(rid, f"SELECT COUNT(*) AS n FROM fighter_near WHERE viewer = 0x{ident['a']}")[0]["n"]
        chars_off = {r["id"] for r in player_sql(db, tok["a"], "SELECT id FROM seen_characters")}
        seen_off = {r["id"] for r in player_sql(db, tok["a"], "SELECT id FROM seen_bodies")}
        private_ids = [
            int(r["id"]) & 0xFFFFFFFF
            for table in ("motion_seen", "motion_near")
            for r in sql(rid, f"SELECT id FROM {table} WHERE viewer = 0x{ident['a']}")
        ]
    finally:
        call(rid, "set_paused", [False])
    off_stream.join()
    off_ev = lines(off_path)
    for law in LAWS:
        call(rid, "set_world_law", [law, "true"])
    time.sleep(1.0)
    back = player_sql(db, tok["a"], "SELECT * FROM seen_body_copy")
    back_chars = {r["row"][0] if isinstance(r["row"], list) else r["row"]["id"] for r in player_sql(db, tok["a"], "SELECT * FROM seen_character_copy")}
    chars_back = {r["id"] for r in player_sql(db, tok["a"], "SELECT id FROM seen_characters")}
    fight_back = {r["body"] for r in player_sql(db, tok["a"], "SELECT * FROM seen_fighter_copy")}
    fight_view_back = {r["id"] for r in player_sql(db, tok["a"], "SELECT id FROM seen_fighters")}
    script_rev_after = sorted((r["name"], r["revision"]) for r in sql(rid, "SELECT name, revision FROM script"))
    override = [r for r in sql(rid, "SELECT * FROM law_override") if r.get("name") in LAWS]
    for law in LAWS:
        # The shipped defaults: the copy tables on since bv-defaults-on, the fighter table off (views step 3).
        restore = had.get(law, "false" if law == "fighter_tables_on" else "true")
        call(rid, "set_world_law", [law, restore if isinstance(restore, str) else json.dumps(restore)])
    # The switch checks use the scene's actors for cross-time comparisons: a
    # world resident can walk into sight between the samples (creature 165 did in gate
    # 1122193749, a 328 s run), which changes A's views for a reason that is not the switch. The
    # off view and private rows are read while paused, so their full creature IDs can be compared.
    scene = {a, b, c, f}
    seen_on, seen_off_all = seen_on & scene, seen_off
    seen_off = seen_off & scene
    chars_on, chars_off = chars_on & scene, chars_off & scene
    # The same for the mirror's return (motion-tables-staging-2: gate 1122235743 failed it with the
    # mirror back on [307, 308, 310]; A's whole view, read by a second query, is not kept to compare).
    back_chars_all, chars_back_all = back_chars, chars_back
    back_chars, chars_back = back_chars & scene, chars_back & scene
    # And the fighter switch checks (motion-tables-staging-3): A's whole seen_fighters, read by
    # separate queries across the switch, can gain a passer-by too.
    fight_off_all = fight_off
    fight_on, fight_off = fight_on & scene, fight_off & scene
    fight_back, fight_view_back = fight_back & scene, fight_view_back & scene
    checks.update({
        "law off: the table is empty to the owner within a second": owner_after == 0,
        "law off: A's stream of the table, accepted, ends empty": accepted(off_ev) and off_ev[-1].get("code") == 0 and not final(off_ev, "seen_body_copy"),
        "law off: A's views still show the same creatures, from the private tables": {b, f} <= seen_on and {b, f} <= seen_off and sorted(private_ids) == sorted(seen_off_all),
        "law on again: A's rows return within a second": {r["body"] for r in back} & scene == seen_on,
        "law off: the mirror is empty to the owner within a second, and A's seen_characters view is unchanged": owner_chars == 0 and bool(chars_on) and chars_off == chars_on,
        "law on again: A's mirror returns within a second, on its view's rows": back_chars == chars_back and bool(back_chars),
        "fighters, law off: the table is empty to the owner within a second, A's seen_fighters view unchanged, from the private tables": owner_fight == 0 and bool(fight_on) and fight_off == fight_on and private_foff == len(fight_off_all),
        "fighters, law on again: A's rows return within a second, on its view's rows": bool(fight_back) and fight_back == fight_view_back,
        "every switch went through law_override rows, with no reinstall (the script rows' revisions unchanged)": len(override) == len(LAWS) and script_rev == script_rev_after,
    })
    result = {"a": a, "b": b, "c": c, "f": f, "dist": {k: round(math.dist(pos[a], pos[k]), 2) for k in (b, c, f)},
              "rows": {w: len(r) for w, r in got.items()}, "a_table": sorted(by_body), "a_view": sorted(a_view),
              "near": sorted(a_near), "far": sorted(a_far), "off": {"owner_rows": owner_after, "seen": sorted(seen_off), "before": sorted(seen_on), "view_all": sorted(seen_off_all), "private_ids": sorted(private_ids)},
              "back": len(back), "fighters": {"a": sorted(f_by_body), "view": sorted(a_fview), "near": sorted(a_fnear), "far": sorted(a_ffar), "owner_after_off": owner_fight, "back": sorted(fight_back)}, "mirror": {"a": sorted(a_mirror), "view": sorted(a_chars), "owner_after_off": owner_chars, "back": sorted(back_chars), "view_back": sorted(chars_back_all), "back_all": sorted(back_chars_all)}, "checks": checks}
    (out / "motion_tables.json").write_text(json.dumps(result, indent=1) + "\n")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
