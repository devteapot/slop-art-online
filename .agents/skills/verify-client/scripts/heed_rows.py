#!/usr/bin/env python3
"""Heed for players as a client receives it (docs/ATTENTION_BUDGET.md, "Player-side interface";
the `heed_players` law with `heed_on`, both off as shipped): a throng member is never named on
any path, and `seen_throng` reaches only its own viewer.

    heed_rows.py --run client-...      (a run launched with verify.py launch, any seed; build the probe first)

Two players join with fresh identities: P on an open line facing east with eight held walkers
2-8 m east of it, and Q 12 m east of P facing west (beyond P's night sight of 11 m), both seeing the walkers. The heed laws go on
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
- **Earshot reads sight:** P's `my_earshot` text counts the rest as "in the throng" (its hearers
  are individuals only, by the first check).
- **`seen_throng`:** P and Q receive rows, every one with their own identity as viewer; the
  anonymous connection none; P asking for Q's by identity none. Every probe's subscription must be
  accepted: an empty stream proves nothing.
- **Change only:** while nobody moves, P receives no `seen_throng` insert, update or delete.
- **Colours carry no identity:** each row has only its cells, counts, bits and three cloth indices
  (0-9, 255 none) with counts; an index of 255 has count 0; its counts by kind are no larger than
  its count allows and its centre lies within its square; its histogram is one quantized count per
  CLOTH word, no more wearers than its count allows.
- **pin_at:** Q picks a walker out of its own throng by its position; it becomes Q's individual,
  not P's, and P's rows never name it; Q's throng row changes in the pick's own update (within
  50 ms of the picked one's `seen_characters` insert); an anonymous `pin_at` is refused as any `human_heed` is.

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
CLOTH = ["yellow", "black", "green", "tan", "blue", "red", "cream", "navy", "purple", "grey"]
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
        call(rid, "place_at", [Q, *line[12]])
        spots = {}
        for k, w in enumerate(walkers):
            spots[w] = (line[2 + (k // 2) * 2][0], line[0][1] + (1.0 if k % 2 else -1.0))
            call(rid, "place_at", [w, *spots[w]])
        hcall(db, tok["p"], "human_face", [1, 0])
        hcall(db, tok["q"], "human_face", [-1, 0])
        for k, v in LAWS.items():
            call(rid, "set_world_law", [k, v])
        time.sleep(3.0)
        seconds = 34
        paths = {w: out / f"heed-{w}.jsonl" for w in ("p", "q", "anon", "peek")}
        threads = [stream(db, tok["p"], P_QUERIES, seconds, paths["p"]),
                   stream(db, tok["q"], ["SELECT * FROM seen_throng", "SELECT * FROM seen_characters"], seconds, paths["q"]),
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
        # Q picks someone out of its own throng by a point (pin_at): a walker neither P nor Q has as
        # an individual, away from the blows.
        perceived_q = lambda: {r["body"] for r in sql(rid, f"SELECT body FROM perceived WHERE viewer = 0x{ident['q']}")}
        pos = {b["id"]: (b["x"], b["y"]) for b in sql(rid, "SELECT id, x, y FROM body") if b["id"] in walkers}
        spare = [w for w in walkers if w not in perceived() | perceived_q() | {t1, t2, t3, t4}]
        qp = spare[0] if spare else None
        q_pick = None
        if qp is not None:
            tq = time.time() * 1000
            code, body = V.http(f"/v1/database/{db}/call/human_heed", [{"pins": [], "focus": {"none": []}, "pin_at": {"some": {"x": pos[qp][0], "y": pos[qp][1]}}}], tok["q"])
            q_pick = {"code": code, "body": body[:200], "q_has": qp in perceived_q(), "p_has": qp in perceived(), "at": tq}
        code, body = V.http(f"/v1/database/{db}/call/human_heed", [{"pins": [], "focus": {"none": []}, "pin_at": {"some": {"x": pos[t2][0], "y": pos[t2][1]}}}], None)
        anon_pick = {"code": code, "body": body[:200]}
        time.sleep(1.0)
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
            # Each of i1's feed rows against P's individuals at that point of its stream.
            now_ind, mixed = set(), []
            for e in ev["p"]:
                if e.get("event") == "initial":
                    now_ind |= {r["id"] for r in (e.get("tables") or {}).get("seen_characters", [])}
                elif e.get("table") == "seen_characters" and e.get("event") in ("insert", "delete"):
                    (now_ind.add if e["event"] == "insert" else now_ind.discard)(e["row"]["id"])
                elif e.get("table") in ("combat_feed", "my_combat") and e.get("event") == "insert" and e["row"].get("actor") == i1:
                    mixed.append({"target": e["row"].get("target"), "t3_individual": t3 in now_ind, "kind": e["row"].get("kind")})
            in_throng = [m for m in mixed if not m["t3_individual"]]
            check("the feed's rule: an individual's blow on a throng member names the individual, target 0",
                  in_throng and all(m["target"] == 0 for m in in_throng) and all(m["target"] in (0, t3) for m in mixed), {"i1": i1, "t3": t3, "rows": mixed[:6]})
        check("contact: the throng member that struck P is an individual to it after", t4_throng and t4 in ever, {"t4": t4, "was_throng": t4_throng})
        # P gains nothing from Q's pick: not in P's perceived set right after it, and no seen_characters
        # row of it reaching P in the 1.5 s after the call.
        leaked = [e for e in ev["p"] if q_pick and e.get("table") == "seen_characters" and e.get("event") == "insert"
                  and e["row"].get("id") == qp and q_pick["at"] <= e.get("ms", 0) < q_pick["at"] + 1500]
        check("pin_at: Q picks a walker out of its throng (an individual to Q), and P is told nothing of it",
              q_pick and q_pick["code"] == 200 and q_pick["q_has"] and not q_pick["p_has"] and not leaked, {"qp": qp, **(q_pick or {}), "leaked": leaked[:2]})
        check("pin_at from an anonymous connection is refused as any human_heed is", anon_pick["code"] != 200 and "no living character" in anon_pick["body"], anon_pick)
        ears = [r for t, r in rows_of(ev["p"]) if t == "my_earshot"]
        check("earshot reads sight: its text counts the throng, its hearers are individuals (above)", any("in the throng" in r.get("text", "") for r in ears), [r.get("text") for r in ears][:3])
        mine = [r for t, r in rows_of(ev["p"]) if t == "seen_throng"]
        theirs = [r for t, r in rows_of(ev["q"]) if t == "seen_throng"]
        # pin_at's row change reaches Q with the pick itself: a seen_throng update or delete in the
        # same update as the picked one's seen_characters insert (received within 50 ms of it).
        ins = [e.get("ms", 0) for e in ev["q"] if qp is not None and e.get("table") == "seen_characters" and e.get("event") == "insert" and e["row"].get("id") == qp and q_pick and e.get("ms", 0) >= q_pick["at"]]
        with_pick = [e for e in ev["q"] if ins and e.get("table") == "seen_throng" and e.get("event") in ("update", "delete") and abs(e.get("ms", 0) - ins[0]) <= 50]
        check("pin_at: Q's throng row gives the person up in the pick's own update", ins and with_pick, {"insert_ms": ins[:1], "rows": [{"event": e["event"], "ms": e.get("ms")} for e in with_pick[:3]]})
        check("seen_throng: P receives its own rows only", mine and all(norm(r["viewer"]) == ident["p"] for r in mine), len(mine))
        fields = {"id", "viewer", "cell", "size", "count", "spread", "heading", "moving", "fighting", "kinds",
                  "colour_a", "colour_a_count", "colour_b", "colour_b_count", "colour_c", "colour_c_count",
                          "people", "wolves", "deer", "others", "centre_x", "centre_y",
                          *(f"cloth_{w}" for w in CLOTH)}
        colours_ok = all(set(r) == fields and all(r[f"colour_{k}"] in set(range(10)) | {255} for k in "abc")
                         and all((r[f"colour_{k}"] == 255) == (r[f"colour_{k}_count"] == 0) for k in "abc") for r in mine)
        shape_ok = all(sum(r[k] for k in ("people", "wolves", "deer", "others")) >= (1 if r["count"] else 0)
                       and all(r[k] <= max(r["count"], 5) for k in ("people", "wolves", "deer", "others"))
                       and r["centre_x"] < 6 * max(1, r["size"]) and r["centre_y"] < 6 * max(1, r["size"]) for r in mine)
        check("seen_throng kinds and centre carry no identity: counts by kind no larger than the row's, a centre within its square", mine and shape_ok,
              [{k: r[k] for k in ("cell", "size", "count", "people", "wolves", "deer", "others", "centre_x", "centre_y")} for r in mine[:3]])
        hist_ok = all(all(0 <= r[f"cloth_{w}"] <= 255 for w in CLOTH) and sum(r[f"cloth_{w}"] for w in CLOTH) <= r["count"] + 2 * len(CLOTH) for r in mine)
        check("seen_throng's histogram carries no identity: one quantized count per CLOTH word, no more wearers than the row's count allows", mine and hist_ok,
              [{w: r[f"cloth_{w}"] for w in CLOTH} for r in mine[:2]])
        check("seen_throng colours carry no identity: three cloth indices (0-9, 255 none) with counts, nothing else", mine and colours_ok,
              [{k: r[k] for k in sorted(fields - {"viewer"})} for r in mine[:2]])
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
