#!/usr/bin/env python3
"""Heed for players as a client receives it (docs/ATTENTION_BUDGET.md, "Player-side interface";
the `heed_players` law with `heed_on`, both off as shipped): a throng member is never named on
any path, and `seen_throng` reaches only its own viewer.

    heed_rows.py --run client-...      (a run launched with verify.py launch, any seed; build the probe first)

Two players join with fresh identities: P on an open line facing east with eight held walkers
3-14 m east of it, and Q 30 m east of P facing west, both seeing the walkers. The heed laws go on
with `heed_ceiling` 2, with cues (`cue_transport_on`) and the feed's events (`combat_feed_on`).
Rust SDK probes stream from their connections on: P every view and copy that names a creature
(`seen_*`, the cue and copy tables, `combat_feed`, `my_combat`, `my_earshot`, `my_heard`,
`seen_throng`), Q `seen_throng`, an anonymous connection `seen_throng`, and P asking for Q's
`seen_throng` rows by identity. Then, with nobody moving for 4 s, three blows: a throng member
of P's on another, one of P's individuals on a throng member, and a throng member on P.

- **Never named:** a walker P never perceived as an individual (never in its `seen_characters`)
  is named in none of P's rows: views, copies, cues, feed rows (actor, target), earshot hearers,
  heard rows.
- **The feed's rule:** the throng-on-throng blow gives P no feed row; the individual's blow on a
  throng member gives P a row naming the individual, with target 0.
- **Contact:** the throng member that strikes P is in P's `seen_characters` (an individual).
- **`seen_throng`:** P and Q receive rows, every one with their own identity as viewer; the
  anonymous connection none; P asking for Q's by identity none. Every probe's subscription must be
  accepted: an empty stream proves nothing.
- **Change only:** while nobody moves, P receives no `seen_throng` insert, update or delete.

The laws are put back as the world had them. Admin calls (`spawn_crowd`, `set_behavior`,
`place_at`, `admin_set_vitals`, `set_world_law`) set the scene. Writes `RUN/heed-<who>.jsonl` and
`RUN/heed_rows.json`. Python standard library only.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cues import ROOT, V, accepted, hcall, lines, norm, stream  # noqa: E402
from earshot import call, open_line, sql  # noqa: E402
sys.path.insert(0, str(ROOT / "living/tools"))
from law_values import own_laws  # noqa: E402

RESULTS = []
LAWS = {"heed_on": "true", "heed_players": "true", "heed_ceiling": "2", "cue_transport_on": "true", "combat_feed_on": "true"}
SHIPPED = {"heed_on": "false", "heed_players": "false", "heed_ceiling": "16", "cue_transport_on": "false", "combat_feed_on": "false"}
P_QUERIES = ["SELECT * FROM seen_bodies", "SELECT * FROM seen_characters", "SELECT * FROM seen_fighters", "SELECT * FROM seen_doing",
             "SELECT * FROM seen_character_copy", "SELECT * FROM seen_fighter_copy", "SELECT * FROM seen_body_copy",
             "SELECT * FROM seen_body_cue", "SELECT * FROM seen_fighter_cue", "SELECT * FROM seen_doing_cue",
             "SELECT * FROM combat_feed", "SELECT * FROM my_combat", "SELECT * FROM my_earshot", "SELECT * FROM my_heard",
             "SELECT * FROM seen_throng"]
# The fields of each table that name a creature.
NAMES = {"seen_bodies": ("id",), "seen_characters": ("id",), "seen_fighters": ("id", "target"), "seen_doing": ("id", "target"),
         "seen_character_copy": ("body", "id"), "seen_fighter_copy": ("body", "target"), "seen_body_copy": ("body",),
         "seen_body_cue": ("motion.id",), "seen_fighter_cue": ("body", "target"), "seen_doing_cue": ("body", "target"),
         "combat_feed": ("actor", "target"), "my_combat": ("actor", "target"), "my_heard": ("id", "body", "speaker"), "my_earshot": ("ways.hearers",)}


def check(name, ok, detail):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS" if ok else "FAIL"), name, json.dumps(detail, default=str)[:300], flush=True)


def field(row, path):
    """Every value at a dotted path (lists flattened; an Option's `some` unwrapped)."""
    vals = [row]
    for part in path.split("."):
        nxt = []
        for x in vals:
            if isinstance(x, dict) and set(x) <= {"some", "none"}:
                x = x.get("some")
            if isinstance(x, dict) and part in x:
                y = x[part]
                nxt.extend(y if isinstance(y, list) else [y])
            elif isinstance(x, list):
                for e in x:
                    if isinstance(e, dict) and part in e:
                        y = e[part]
                        nxt.extend(y if isinstance(y, list) else [y])
        vals = nxt
    return [x for x in vals if isinstance(x, int)]


def rows_of(events):
    """Every row the stream delivered: the initial tables and each insert or update."""
    for e in events:
        if e.get("event") == "initial":
            for t, rs in (e.get("tables") or {}).items():
                for r in rs:
                    yield t, r
        elif e.get("event") in ("insert", "update"):
            yield e["table"], e["row"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    rid = ap.parse_args().run
    st = V.load(rid)
    db = st["db"]
    out = ROOT / ".local/living/verify" / rid
    out.mkdir(parents=True, exist_ok=True)
    was = own_laws(lambda q: sql(rid, q))
    try:
        line = open_line(rid, 34)
        before = {x["id"] for x in sql(rid, "SELECT id FROM character")}
        call(rid, "spawn_crowd", [8, False])
        walkers = sorted(x["id"] for x in sql(rid, "SELECT id FROM character") if x["id"] not in before)[:8]
        for w in walkers:
            call(rid, "set_behavior", [w, json.dumps({"wait": 600})])
        tok = {}
        for who in ("p", "q"):
            _, body = V.http("/v1/identity", {})
            tok[who] = json.loads(body)["token"]
            hcall(db, tok[who], "join", [f"Heed {who.upper()}"])
        chars = {c["name"]: c for c in sql(rid, "SELECT * FROM character")}
        P, Q = chars["Heed P"]["id"], chars["Heed Q"]["id"]
        ident = {"p": norm(chars["Heed P"]["controller"]), "q": norm(chars["Heed Q"]["controller"])}
        for who in (P, Q):
            call(rid, "admin_set_vitals", [who, 1000.0])
        call(rid, "place_at", [P, *line[0]])
        call(rid, "place_at", [Q, *line[30]])
        spots = {}
        for k, w in enumerate(walkers):
            spots[w] = (line[3 + (k // 2) * 3][0], line[0][1] + (1.0 if k % 2 else -1.0))
            call(rid, "place_at", [w, *spots[w]])
        hcall(db, tok["p"], "human_face", [1, 0])
        hcall(db, tok["q"], "human_face", [-1, 0])
        for k, v in LAWS.items():
            call(rid, "set_world_law", [k, v])
        time.sleep(3.0)
        seconds = 34
        paths = {w: out / f"heed-{w}.jsonl" for w in ("p", "q", "anon", "peek")}
        threads = [stream(db, tok["p"], P_QUERIES, seconds, paths["p"]),
                   stream(db, tok["q"], ["SELECT * FROM seen_throng"], seconds, paths["q"]),
                   stream(db, None, ["SELECT * FROM seen_throng"], seconds, paths["anon"]),
                   stream(db, tok["p"], [f"SELECT * FROM seen_throng WHERE viewer = 0x{ident['q']}"], seconds, paths["peek"])]
        time.sleep(4.0)
        # Still for 4 s: P's throng rows must not change.
        still0 = time.time() * 1000
        time.sleep(4.0)
        still1 = time.time() * 1000
        perceived = lambda: {r["body"] for r in sql(rid, f"SELECT body FROM perceived WHERE viewer = 0x{ident['p']}")}
        ind = perceived() & set(walkers)
        thr = sorted((w for w in walkers if w not in ind), key=lambda w: spots[w][0])
        # A throng member on another (side by side), then an individual on a throng member.
        t1, t2, t3, t4 = thr[0], thr[1], thr[2], thr[3]
        call(rid, "place_at", [t1, spots[t2][0], spots[t2][1] + (0.9 if spots[t2][1] < line[0][1] else -0.9)])
        b0 = time.time() * 1000
        call(rid, "set_behavior", [t1, json.dumps({"seq": [{"do": {"skill": "strike", "target": {"id": t2}}}, {"wait": 600}]})])
        time.sleep(3.0)
        b1 = time.time() * 1000
        i1 = sorted(ind)[0] if ind else None
        if i1 is not None:
            call(rid, "place_at", [t3, spots[i1][0], spots[i1][1] + (0.9 if spots[i1][1] < line[0][1] else -0.9)])
            call(rid, "set_behavior", [i1, json.dumps({"seq": [{"do": {"skill": "strike", "target": {"id": t3}}}, {"wait": 600}]})])
        time.sleep(3.0)
        # A throng member on P.
        call(rid, "place_at", [t4, line[0][0] + 1.2, line[0][1]])
        time.sleep(0.5)
        t4_throng = t4 not in perceived()
        call(rid, "set_behavior", [t4, json.dumps({"seq": [{"do": {"skill": "strike", "target": {"id": P}}}, {"wait": 600}]})])
        for t in threads:
            t.join()
        ev = {w: lines(p) for w, p in paths.items()}
        for w, e in ev.items():
            check(f"{w}: the subscription was accepted", accepted(e), [x.get("event") for x in e[:3]])

        # Who P ever had as an individual (its seen_characters), and who never.
        ever = {P}
        for t, r in rows_of(ev["p"]):
            if t == "seen_characters":
                ever.add(r["id"])
        never = set(walkers) - ever
        named = []
        for t, r in rows_of(ev["p"]):
            for path in NAMES.get(t, ()):
                for x in field(r, path):
                    if x in never:
                        named.append((t, path, x))
        check("a walker P never perceived as an individual is named in none of its rows", never and not named, {"never": sorted(never), "named": named[:10]})
        feed = [r for t, r in rows_of(ev["p"]) if t in ("combat_feed", "my_combat")]
        # Any feed row P received while only the throng-on-throng blow was under way (P no party).
        throng_blow = [e["row"] for e in ev["p"] if e.get("event") == "insert" and e.get("table") in ("combat_feed", "my_combat")
                       and b0 <= e.get("ms", 0) < b1 and P not in (e["row"].get("actor"), e["row"].get("target"))]
        check("the feed's rule: a throng member's blow on another gives P no feed row", t1 in never and t2 in never and not throng_blow, {"t1": t1, "t2": t2, "rows": throng_blow[:4], "never": sorted(never)})
        if i1 is not None:
            mixed = [r for r in feed if r.get("actor") == i1]
            check("the feed's rule: an individual's blow on a throng member names the individual, not the target",
                  mixed and all(r.get("target") == 0 for r in mixed) and t3 in never, {"i1": i1, "t3": t3, "rows": mixed[:4]})
        check("contact: the throng member that struck P is an individual to it after", t4_throng and t4 in ever, {"t4": t4, "was_throng": t4_throng})
        mine = [r for t, r in rows_of(ev["p"]) if t == "seen_throng"]
        theirs = [r for t, r in rows_of(ev["q"]) if t == "seen_throng"]
        check("seen_throng: P receives its own rows only", mine and all(norm(r["viewer"]) == ident["p"] for r in mine), len(mine))
        check("seen_throng: Q receives its own rows only", theirs and all(norm(r["viewer"]) == ident["q"] for r in theirs), len(theirs))
        anon = [r for _, r in rows_of(ev["anon"])]
        peek = [r for _, r in rows_of(ev["peek"])]
        check("seen_throng: an anonymous connection receives none", not anon, len(anon))
        check("seen_throng: P asking for Q's rows by identity receives none", not peek, len(peek))
        changes = [e for e in ev["p"] if e.get("table") == "seen_throng" and e.get("event") in ("insert", "update", "delete") and still0 <= e.get("ms", 0) < still1]
        check("change only: while nobody moves, no seen_throng row is written", not changes, changes[:4])
    finally:
        for k in LAWS:
            call(rid, "set_world_law", [k, was.get(k) or SHIPPED[k]])
    (out / "heed_rows.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(bad)} of {len(RESULTS)} checks pass")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
