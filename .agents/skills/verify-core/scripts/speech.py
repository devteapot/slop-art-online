#!/usr/bin/env python3
"""Speech scenes on a verify-core run (docs/COMMUNICATION.md).

  regress  the shipped `say`, through every entry point (mind_say, human_say, a graph's say),
           with its rows written out with ids and names replaced by roles, so the same scene on
           two modules can be compared (`diff`). `--baseline` drives a module from before ways
           of speaking (mind_say without a way; no new checks).
  ways     what the speech primitive adds: `introduced` rows, `heard` and `my_heard`,
           `speech_card`, `human_speak` and its refusals, a graph's say and mind_say with a way,
           `heard` retention.
  crowd    the cost of one line in a talking crowd: rows written per line by table, listeners,
           and the reducer's WASM time and fuel per line from the server's metrics.
  diff A B compare two `regress` outputs (runs A and B), the new kinds of rows left out.
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402

URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
NEW_KINDS = {"introduced"}
SPEECH_KINDS = {"said", "repeat", "silence", "speech", "signal", "introduced"}
TALK = {"kind": "talk", "summary": "verify-core speech scene", "detail": "", "latency_ms": 0, "tokens": 0, "model": "fake", "reference": ""}
GAP = 2.6


def http(path, body=None, token=None, raw=False, timeout=60):
    data = (body if raw else json.dumps(body)).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method="POST" if data is not None else "GET")
    req.add_header("Content-Type", "text/plain" if raw else "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class Person:
    """A player of the scene: its own identity (POST /v1/identity), never the admin."""

    def __init__(self, s, name):
        self.s = s
        # A scene's player stands for a connected one. Its person never connects to the world
        # (HTTP calls only), so after the `takeover_s` law's 30 s the minds would take it over, and
        # its first look round ("discovered", "saw" rows) would land in whichever check is then
        # counting rows (channels failed so in 2 of 4 runs on fix-sleep-talk). The law is raised
        # for the scene before the first join and restored at its end (`main`).
        if not hasattr(s, "takeover_s"):
            s.takeover_s = scenes.law_value(s, "takeover_s")
            scenes.set_law(s, "takeover_s", 3600.0, check=False)
        code, body = http("/v1/identity", {})
        assert code == 200, body
        self.token = json.loads(body)["token"]
        self.call("join", [name])
        self.id = self.sql("SELECT * FROM my_characters")[0]["id"]

    def call(self, reducer, args):
        code, body = http(f"/v1/database/{self.s.db}/call/{reducer}", args, self.token)
        with self.s.log.open("a") as f:
            f.write(json.dumps({"at_ms": time.time_ns() // 1_000_000, "player": True, "reducer": reducer, "args": args, "code": code, "body": body}) + "\n")
        return code, body

    def sql(self, query):
        return sql(self.s, query, self.token)


def sql(s, query, token=None):
    code, body = http(f"/v1/database/{s.db}/sql", query, token, raw=True)
    if code != 200:
        raise RuntimeError(f"sql {code}: {body[:300]}")
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def now(s):
    return s.rows("SELECT last_ms FROM clock")[0]["last_ms"]


def quiet_line(s, length=24, clear=30.0):
    """A row of `length` open tiles (west to east) with no creature within `clear` m of it."""
    w = s.rows("SELECT width, height FROM world")[0]
    W, H = w["width"], w["height"]
    tiles = bytearray(W * H)
    for row in s.rows("SELECT * FROM terrain_chunk"):
        data = row["tiles"]
        data = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
        cx, cy = row["id"] & 0xFFFF, row["id"] >> 16
        for k, t in enumerate(data):
            x, y = cx * 16 + k % 16, cy * 16 + k // 16
            if x < W and y < H:
                tiles[y * W + x] = t
    bodies = [(b["x"], b["y"]) for b in s.rows("SELECT x, y FROM body")]
    walk = lambda x, y: 0 <= x < W and 0 <= y < H and tiles[y * W + x] not in (2, 4, 7, 8, 9)
    for y in range(8, H - 8, 3):
        for x in range(8, W - length - 8, 2):
            if not all(walk(x + i, y + d) for i in range(length) for d in (-2, -1, 0, 1, 2)):
                continue
            mid = (x + length / 2, y + .5)
            if all(math.dist(mid, b) > clear + length / 2 for b in bodies):
                return [(x + i + .5, y + .5) for i in range(length)]
    raise RuntimeError("no quiet open line on this map")


def say_as(s, actor, text, to=0, way=None, check=False):
    """mind_say as the admin (the world's minds' identity); `way` None for a module from before ways."""
    args = [actor, text, to] + ([] if way is None else [way]) + [0, TALK]
    return s.call("mind_say", *args, check=check)


def intruders(s, cast, at, r=15.0):
    return [b["id"] for b in s.rows("SELECT id, x, y FROM body") if b["id"] not in cast and math.dist((b["x"], b["y"]), at) <= r]


class Cast:
    def __init__(self, s, baseline):
        self.s = s
        self.baseline = baseline
        self.a, self.b, self.c, self.d = s.people(4)
        deer = [c["id"] for c in s.rows("SELECT id, kind, alive FROM character") if c["kind"] == "deer" and c["alive"]]
        s.expect("a deer to listen", deer, None)
        self.deer = deer[0]
        s.graph(self.deer, {"wait": 120})
        self.p = Person(s, "Listener")
        s.graph(self.p.id, {"wait": 120})
        self.line = quiet_line(s)
        x0, y0 = self.line[0]
        # From the speaker a: b 3 m, the deer about 4 m, c 7 m, the player 8.5 m (all within
        # the shipped 9 m hearing), d 14 m (out of earshot).
        self.at = {self.a: (x0 + 2, y0), self.b: (x0 + 5, y0), self.deer: (x0 + 5.5, y0 + 2.5), self.c: (x0 + 9, y0), self.p.id: (x0 + 10.5, y0), self.d: (x0 + 16, y0)}
        for who, (x, y) in self.at.items():
            s.call("place_at", who, x, y)
        self.roles = {self.a: "a", self.b: "b", self.c: "c", self.d: "d", self.deer: "deer", self.p.id: "p", 0: "-"}
        names = {c["id"]: c["name"] for c in s.rows("SELECT id, name FROM character") if c["id"] in self.roles}
        self.names = {names[i]: f"<{r}>" for i, r in self.roles.items() if i in names}
        (s.out / f"{s.name}-cast.json").write_text(json.dumps({"roles": self.roles, "names": names, "at": {str(k): v for k, v in self.at.items()}, "hour": scenes.world_hour(s)[0]}, indent=2) + "\n")

    def role(self, i):
        return self.roles.get(i, "other")

    def norm(self, text):
        for n, r in sorted(self.names.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(n, r)
        return text


def lines_of_regress(s, k):
    """The scene's lines, in order: (label, callable returning (code, error text))."""
    a, b, c, d, p = k.a, k.b, k.c, k.d, k.p
    way = None if k.baseline else "say"
    def mind(actor, text, to=0):
        def go():
            r = say_as(s, actor, text, to, way)
            return r.returncode, (r.stderr or "")[-300:]
        return go
    def player(text, to=0):
        def go():
            return p.call("human_say", [text, to])
        return go
    return [
        ("room", mind(a, "Good morning, all.")),
        ("to c", mind(a, "Fine weather today, is it not?", c)),
        ("to d out of earshot", mind(a, "Are you over there?", d)),
        ("self-introduction", mind(a, f"I am {k.rev('a')}, new in these parts.")),
        ("repeat", mind(a, "Good morning, all.")),
        ("names c", mind(a, f"{k.rev('c')}, come over here.")),
        ("player room", player("Hello from the listener.")),
        ("player to d", player("You there, can you hear me?", d)),
        ("player introduces", player("I am Listener.", a)),
        ("b introduces", mind(b, f"I am {k.rev('b')}.")),
    ]


def collect(s, k, t0, label):
    cast = set(k.roles) - {0}
    out = {"experience": {}, "line_seen": {}, "acquaintance": [], "chronicle": [], "mind_state": {}}
    for who in sorted(cast):
        rows = sorted(s.rows(f"SELECT * FROM experience WHERE observer = {who}"), key=lambda r: r["id"])
        rows = [r for r in rows if r["at_ms"] >= t0 and r["kind"] in SPEECH_KINDS and (r["subject"] in cast or r["object"] in cast)]
        out["experience"][k.role(who)] = [{"kind": r["kind"], "subject": k.role(r["subject"]), "object": k.role(r["object"]), "text": k.norm(r["text"]), "salience": round(r["salience"], 3)} for r in rows]
    for r in sorted(s.rows(f"SELECT * FROM line_seen WHERE observer = {k.p.id}"), key=lambda r: r["id"]):
        e = r["line"]
        e = dict(zip(["id", "observer", "controller", "at_ms", "kind", "subject", "object", "x", "y", "text", "salience"], e)) if isinstance(e, list) else e
        if e["at_ms"] >= t0 and e["kind"] in SPEECH_KINDS and (e["subject"] in cast or e["object"] in cast):
            out["line_seen"].setdefault("p", []).append({"kind": e["kind"], "subject": k.role(e["subject"]), "text": k.norm(e["text"])})
    for r in s.rows("SELECT * FROM acquaintance"):
        if r["since_ms"] >= t0 and (r["observer"] in cast or r["known"] in cast):
            out["acquaintance"].append([k.role(r["observer"]), k.role(r["known"])])
    out["acquaintance"].sort()
    for r in sorted(s.rows("SELECT * FROM chronicle WHERE kind = 'speech'"), key=lambda r: r["id"]):
        if r["at_ms"] >= t0 and r["a"] in cast:
            out["chronicle"].append({"a": k.role(r["a"]), "b": k.role(r["b"]), "text": k.norm(r["text"])})
    for who in sorted(cast):
        st = s.rows(f"SELECT * FROM mind_state WHERE id = {who}")
        if st:
            out["mind_state"][k.role(who)] = {"heard_since_t0": st[0]["heard_ms"] >= t0, "speaker": k.role(st[0]["speaker"]) if st[0]["heard_ms"] >= t0 else None, "spoke_since_t0": st[0]["spoke_ms"] >= t0}
    (s.out / f"{s.name}-{label}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return out


def regress(s):
    k = Cast(s, s.baseline)
    k.rev = lambda role: next(n for n, r in k.names.items() if r == f"<{role}>")
    time.sleep(1.5)
    t0 = now(s)
    calls = []
    for label, go in lines_of_regress(s, k):
        crowd = intruders(s, set(k.roles), k.at[k.a])
        code, err = go()
        calls.append({"line": label, "code": code, "error": err if code else "", "intruders": crowd})
        time.sleep(GAP)
    # The speaking limit: a second line within 2 s is refused, and writes nothing.
    way = None if k.baseline else "say"
    first = say_as(s, k.a, "Too fast, one.", 0, way)
    second = say_as(s, k.a, "Too fast, two.", 0, way)
    calls.append({"line": "too fast", "code": [first.returncode, second.returncode], "error": (second.stderr or "")[-200:]})
    s.expect("the speaking limit refuses a second line within 2 s", first.returncode == 0 and second.returncode != 0 and "speaking too fast" in (second.stderr + second.stdout), calls[-1], fatal=False)
    time.sleep(GAP)
    # A graph's say in a looping graph speaks once per 45 s (fix-graph-say-id).
    s.graph(k.a, {"first": [{"seq": [{"say": {"text": "Still here, still here.", "to": {"id": k.b}}}, {"wait": 2}]}]})
    time.sleep(12)
    s.graph(k.a, {"wait": 120})
    time.sleep(1.5)
    out = collect(s, k, t0, "rows")
    paced = [r for r in out["chronicle"] if "Still here" in r["text"]]
    s.expect("a looping graph say is paced (once in 12 s)", len(paced) == 1, paced, fatal=False)
    out["calls"] = [{"line": c["line"], "code": c["code"], "error": c["error"]} for c in calls]
    out["intruders"] = {c["line"]: c["intruders"] for c in calls if c.get("intruders")}
    (s.out / "speech-regress.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    s.expect("every scripted line was accepted", all(c["code"] in (0, 200) for c in calls[:-1]), calls, fatal=False)
    s.expect("no one else came within 15 m during the lines", not out["intruders"], out["intruders"], fatal=False)
    if not k.baseline:
        intro = {o: [r for r in rows if r["kind"] == "introduced"] for o, rows in out["experience"].items()}
        s.expect("introduced: those who heard a's name for the first time are told (b, c, p)",
                 {o for o, r in intro.items() if any(x["subject"] == "a" for x in r)} == {"b", "c", "p"}, intro, fatal=False)
        s.expect("introduced: the row reads `<name> told you their name.` at 0.55",
                 all(x["text"] == f"{'<' + x['subject'] + '>'} told you their name." and x["salience"] == 0.55 for r in intro.values() for x in r), intro, fatal=False)


def rows_differ(a, b):
    diffs = []
    # A repeat row says how long ago the first line was: the scene's own pacing, not behaviour.
    ago = lambda r: {**r, "text": re.sub(r"\b\d+ s ago", "<n> s ago", r["text"])} if "text" in r else r
    strip = lambda rows: [ago(r) for r in rows if r.get("kind") not in NEW_KINDS]
    for section in ("experience", "line_seen"):
        for who in sorted(set(a[section]) | set(b[section])):
            ra, rb = strip(a[section].get(who, [])), strip(b[section].get(who, []))
            if ra != rb:
                diffs.append({"section": section, "observer": who, "a": ra, "b": rb})
    # A refusal's error names the database's own identity.
    db = lambda v: json.loads(re.sub(r"database/[0-9a-f]{64}", "database/<db>", json.dumps(v)))
    for section in ("acquaintance", "chronicle", "mind_state", "calls"):
        if db(a.get(section)) != db(b.get(section)):
            diffs.append({"section": section, "a": a.get(section), "b": b.get(section)})
    return diffs


def diff(run_a, run_b):
    base = scenes.BASE
    a = json.loads((base / run_a / "speech-regress.json").read_text())
    b = json.loads((base / run_b / "speech-regress.json").read_text())
    diffs = rows_differ(a, b)
    new = {who: [r for r in rows if r["kind"] in NEW_KINDS] for who, rows in b["experience"].items()}
    report = {"a": run_a, "b": run_b, "identical_except_new_kinds": not diffs, "differences": diffs,
              "rows_compared": sum(len(v) for v in a["experience"].values()), "new_rows_in_b": {k: v for k, v in new.items() if v}}
    out = base / run_b / "speech-diff.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in ("identical_except_new_kinds", "rows_compared")}), "->", out)
    for d in diffs:
        print(json.dumps(d, ensure_ascii=False)[:2000])
    return 0 if not diffs else 1


def nearest_first(got, want, dist):
    """The same hearers, nearest first (equally near ones in any order)."""
    return sorted(got) == sorted(want) and all(dist(x) <= dist(y) + 1e-3 for x, y in zip(got, got[1:]))


def ways(s):
    k = Cast(s, False)
    k.rev = lambda role: next(n for n, r in k.names.items() if r == f"<{role}>")
    a, b, c, d, p = k.a, k.b, k.c, k.d, k.p
    time.sleep(1.5)
    # speech_card: public, one row per way (the shipped script: `say`).
    cards = sql(s, "SELECT * FROM speech_card")
    (s.out / "ways-speech-card.json").write_text(json.dumps(cards, indent=2) + "\n")
    got = sorted((r["name"], r["label"], r["order"], r["needs_to"], r["reach_m"], r["carry_m"], r["requires"], r["needs_sight"], r["private"], r["max_chars"], r["gap_ms"]) for r in cards)
    s.expect("speech_card is public and lists the shipped ways: say (today's speech), whisper, call",
             got == sorted([("say", "Say", 0, False, 0.0, 9.0, "", False, False, 400, 2000), ("whisper", "Whisper", 1, True, 1.5, 1.5, "", False, True, 400, 2000),
                            ("call", "Call out", 2, False, 0.0, 22.5, "", False, False, 80, 6000)]), cards, fatal=False)
    night = not (6 <= scenes.world_hour(s)[0] < 20)
    sight = 6.0 if night else 11.0
    dist = lambda x, y: math.dist(k.at[x], k.at[y])
    # A self-introduction: the name is news to b, c and the player (in earshot), not to d.
    t0 = now(s)
    say_as(s, a, f"I am {k.rev('a')}, new in these parts.", 0, "say", check=True)
    time.sleep(1.0)
    said = [r for r in s.rows(f"SELECT * FROM experience WHERE observer = {a}") if r["kind"] == "said" and r["at_ms"] >= t0]
    s.expect("the speaker's own `said` row", len(said) == 1, said)
    heard = s.rows(f"SELECT * FROM line_heard WHERE line = {said[0]['id']}", "heard-intro")
    want = [x for x in sorted((b, c, p.id), key=lambda x: dist(a, x)) if dist(a, x) <= sight]
    s.expect(f"heard: one row with the line, its way and the hearers a saw, nearest first ({'night' if night else 'day'})",
             len(heard) == 1 and heard[0]["speaker"] == a and heard[0]["way"] == "say" and nearest_first(heard[0]["hearers"], want, lambda x: dist(a, x)), (heard, want), fatal=False)
    intro = {who: [r for r in s.rows(f"SELECT * FROM experience WHERE observer = {who}") if r["kind"] == "introduced" and r["at_ms"] >= t0] for who in (b, c, d, p.id)}
    s.expect("introduced: b, c and the player are told the name, d (out of earshot) is not",
             all(len(intro[x]) == 1 and intro[x][0]["subject"] == a and intro[x][0]["text"] == f"{k.rev('a')} told you their name." for x in (b, c, p.id)) and not intro[d], intro, fatal=False)
    time.sleep(GAP)
    t1 = now(s)
    say_as(s, a, f"Again: I am {k.rev('a')}.", 0, "say", check=True)
    time.sleep(1.0)
    again = [r for x in (b, c, p.id) for r in s.rows(f"SELECT * FROM experience WHERE observer = {x}") if r["kind"] == "introduced" and r["at_ms"] >= t1]
    s.expect("introduced: a name already known is not news again", not again, again, fatal=False)
    mine = p.sql("SELECT * FROM my_experience")
    s.expect("introduced reaches the player's client (my_experience)", any(r["kind"] == "introduced" and r["subject"] == a for r in mine), [r for r in mine if r["kind"] == "introduced"], fatal=False)
    time.sleep(GAP)
    # The player speaks through human_speak, human_say, and is refused in the world's words.
    t2 = now(s)
    ok = p.call("human_speak", ["Hello through human_speak.", 0, "say"])
    time.sleep(GAP)
    old = p.call("human_say", ["Hello through human_say.", a])
    time.sleep(GAP)
    empty_way = p.call("human_speak", ["Hello with no way named.", 0, ""])
    time.sleep(GAP)
    unknown = p.call("human_speak", ["Hello in a way there is not.", 0, "shout"])
    nothing = p.call("human_speak", ["   ", 0, "say"])
    s.expect("human_speak, human_say and an empty way are accepted", ok[0] == old[0] == empty_way[0] == nothing[0] == 200, (ok, old, empty_way, nothing), fatal=False)
    s.expect("an unknown way is refused: no way of speaking called `shout`", unknown[0] != 200 and "no way of speaking called `shout`" in unknown[1], unknown, fatal=False)
    time.sleep(1.0)
    psaid = sorted((r for r in s.rows(f"SELECT * FROM experience WHERE observer = {p.id}") if r["kind"] == "said" and r["at_ms"] >= t2), key=lambda r: r["id"])
    s.expect("the player's three lines, and nothing for the refused or empty one",
             [r["text"] for r in psaid] == ["You said: “Hello through human_speak.”", f"You said to {k.rev('a')}: “Hello through human_say.”", "You said: “Hello with no way named.”"], [r["text"] for r in psaid], fatal=False)
    mh = p.sql("SELECT * FROM my_heard")
    (s.out / "ways-my-heard.json").write_text(json.dumps(mh, indent=2) + "\n")
    want_p = [x for x in sorted((a, b, c, d), key=lambda x: dist(p.id, x)) if dist(p.id, x) <= 9.0 and dist(p.id, x) <= sight]
    s.expect("my_heard: the player's own lines, joinable to my_experience by `line`, with whom it saw hear them",
             sorted(r["line"] for r in mh) == sorted(r["id"] for r in psaid) and all(nearest_first(r["hearers"], want_p, lambda x: dist(p.id, x)) and r["speaker"] == p.id for r in mh), (mh, want_p), fatal=False)
    shown = {r["id"] for r in p.sql("SELECT * FROM my_experience")}
    s.expect("each my_heard line is a `said` row the client was shown", all(r["line"] in shown for r in mh), None, fatal=False)
    other = Person(s, "Stranger")
    s.expect("another player's my_heard holds none of the player's lines", not other.sql("SELECT * FROM my_heard"), None, fatal=False)
    code, body = http(f"/v1/database/{s.db}/sql", "SELECT * FROM line_heard", p.token, raw=True)
    s.expect("the heard table itself is private to a player", code != 200 or json.loads(body)[-1]["rows"] == [], (code, body[:200]), fatal=False)
    # A graph's say in a named way, and one in a way there is not (a refused leaf).
    time.sleep(GAP)
    t3 = now(s)
    s.graph(a, {"seq": [{"say": {"text": "A graph line, said.", "to": {"id": b}, "way": "say"}}, {"wait": 60}]})
    time.sleep(3)
    s.graph(a, {"seq": [{"say": "A graph line in no way.", "way": "shout"}, {"wait": 60}]})
    time.sleep(3)
    s.graph(a, {"wait": 120})
    spoken = [r["text"] for r in s.rows(f"SELECT * FROM chronicle WHERE kind = 'speech' AND a = {a}") if r["at_ms"] >= t3]
    told = [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {a}", "graph-way-feedback") if r["at_ms"] >= t3 and "no way of speaking" in r["text"]]
    s.expect("a graph say with `way: say` speaks", any("A graph line, said." in t for t in spoken), spoken, fatal=False)
    s.expect("a graph say in an unknown way is not spoken, and the speaker is told why", not any("in no way" in t for t in spoken) and told, (spoken, told), fatal=False)
    time.sleep(GAP)
    bad = say_as(s, a, "In no way at all.", 0, "shout")
    s.expect("mind_say in an unknown way is refused", bad.returncode != 0 and "no way of speaking called `shout`" in (bad.stderr + bad.stdout), (bad.stderr or "")[-200:], fatal=False)
    # Who heard, out of sight: d behind a wall within earshot hears the words but is not listed.
    g = scenes.wall_geometry(s)
    s.call("place_at", a, *g["eye"])
    s.call("place_at", d, *g["hidden"])
    s.call("place_at", c, *g["open"])
    for who in (b, p.id):
        s.call("place_at", who, g["eye"][0] + 40, g["eye"][1] + 40)
    time.sleep(GAP)
    t4 = now(s)
    say_as(s, a, "Can anyone hear me through this wall?", 0, "say", check=True)
    time.sleep(1.0)
    line = [r for r in s.rows(f"SELECT * FROM experience WHERE observer = {a}") if r["kind"] == "said" and r["at_ms"] >= t4]
    h = s.rows(f"SELECT * FROM line_heard WHERE line = {line[0]['id']}", "heard-wall") if line else []
    behind = [r for r in s.rows(f"SELECT * FROM experience WHERE observer = {d}") if r["kind"] == "speech" and r["at_ms"] >= t4]
    s.expect("heard: one behind a wall hears the words but is not among the hearers the speaker saw",
             behind and h and d not in h[0]["hearers"] and c in h[0]["hearers"], (behind, h), fatal=False)
    # Retention: the lines a mind integrated leave with their rows; a played character's stay.
    upto = max(r["id"] for r in s.rows(f"SELECT id FROM experience WHERE observer = {a}"))
    before = len(s.rows(f"SELECT * FROM line_heard WHERE speaker = {a}"))
    s.call("mind_consolidated", a, upto)
    after = len(s.rows(f"SELECT * FROM line_heard WHERE speaker = {a}"))
    s.expect("heard: a mind's lines go when it has integrated them (mind_consolidated)", before >= 3 and after == 0, (before, after), fatal=False)
    s.expect("heard: a played character's lines stay", len(p.sql("SELECT * FROM my_heard")) == len(mh), None, fatal=False)


def channels(s):
    """Whisper, call, truthful silence and overheard names (docs/COMMUNICATION.md items 6, 7, 8,
    10) on one quiet line: from the speaker a, b at 1 m, the deer at about 4 m, c at 4 m, the
    player at 7 m, e at 10 m (in sight by day, beyond the 9 m voice), d at 20 m (within a call)."""
    # By day from start to end: e is placed to be seen by day, and the queued checks need it.
    # The scene takes about 8 game hours on the 12-minute day, so on a reused world (a fresh
    # launch starts at 07:00) it waits for the next morning when it would run into the dusk.
    hour, day_ms = scenes.world_hour(s)
    if not 6.0 <= hour < 11.0:
        print(f"world hour {hour:.1f}: waiting for the morning (06:00-07:00)", flush=True)
        s.wait(lambda: 6.0 <= scenes.world_hour(s)[0] < 7.0, seconds=day_ms / 1000 + 60, every=5)
    a, b, c, d, e = s.people(5)
    deer = next(x["id"] for x in s.rows("SELECT id, kind, alive FROM character") if x["kind"] == "deer" and x["alive"])
    s.graph(deer, {"wait": 120})
    p = Person(s, "Mara Quill")
    line = quiet_line(s, length=26)
    x0, y0 = line[0]
    at = {a: (x0 + 2, y0), b: (x0 + 3, y0), deer: (x0 + 5.5, y0 + 2.5), c: (x0 + 6, y0), p.id: (x0 + 9, y0), e: (x0 + 12, y0), d: (x0 + 22, y0)}
    for who, (x, y) in at.items():
        s.call("place_at", who, x, y)
    names = {x["id"]: x["name"] for x in s.rows("SELECT id, name FROM character") if x["id"] in at}
    night = not (6 <= scenes.world_hour(s)[0] < 20)
    (s.out / f"{s.name}-cast.json").write_text(json.dumps({"a": a, "b": b, "c": c, "d": d, "e": e, "deer": deer, "p": p.id, "names": names, "at": {str(k): v for k, v in at.items()}, "night": night}, indent=2) + "\n")
    time.sleep(1.5)
    # What the world tells the cast meanwhile and no line ever writes (food spoiling, a first
    # sight, a place, a feeling): not counted as a line's rows, or a check that a line wrote
    # nothing fails whenever one lands in its window (run 9 on fix-channels-race: "Some of your
    # berries spoiled").
    ambient = {"body", "discovered", "saw", "feeling", "life"}
    def rows(who, since, kinds=None):
        return sorted((r for r in s.rows(f"SELECT * FROM experience WHERE observer = {who}") if r["at_ms"] >= since and (r["kind"] in kinds if kinds is not None else r["kind"] not in ambient)), key=lambda r: r["id"])
    def collect(r, t, label):
        got = {who: rows(who, t) for who in at}
        (s.out / f"{s.name}-{label}.json").write_text(json.dumps({"code": r.returncode, "error": (r.stderr or "")[-300:], "rows": {names.get(k, str(k)): v for k, v in got.items()}}, indent=2, ensure_ascii=False) + "\n")
        return got

    def line_by(speaker, text, to, way, label):
        t = now(s)
        r = say_as(s, speaker, text, to, way)
        time.sleep(1.0)
        return r, collect(r, t, label), t
    # Whisper to b beside a: b gets the words; c (4 m, sees a) notices without the words; the
    # player (7 m), e, d and the deer get nothing.
    r, got, t = line_by(a, "The tally is short tonight.", b, "whisper", "whisper")
    s.expect("whisper: accepted", r.returncode == 0, (r.stderr or "")[-200:])
    words = lambda who: [x for x in got[who] if "tally is short" in x["text"]]
    s.expect("whisper: b gets the words as a `whisper` row (0.9)", [(x["kind"], x["salience"]) for x in words(b)] == [("whisper", 0.9)] and "whispers to you: “The tally is short tonight.”" in words(b)[0]["text"], got[b], fatal=False)
    s.expect("whisper: c, beside and seeing a, notices it without the words", [x["text"] for x in got[c] if x["kind"] == "whispered"] == ["A stranger whispers something to a stranger."] and not words(c), got[c], fatal=False)
    s.expect("whisper: the player, e, d and the deer get nothing at all", not any(got[w] and any(x["subject"] == a for x in got[w]) for w in (p.id, e, d, deer)), {w: got[w] for w in (p.id, e, d, deer)}, fatal=False)
    s.expect("whisper: the speaker's row reads `You whispered to …`", [x["text"] for x in got[a] if x["kind"] == "said"] == ["You whispered to a stranger: “The tally is short tonight.”"], got[a], fatal=False)
    said = [x for x in got[a] if x["kind"] == "said"]
    h = s.rows(f"SELECT * FROM line_heard WHERE line = {said[0]['id']}") if said else []
    s.expect("whisper: heard lists b alone, way whisper", h and h[0]["hearers"] == [b] and h[0]["way"] == "whisper", h, fatal=False)
    chron = [x["text"] for x in s.rows("SELECT * FROM chronicle WHERE kind = 'speech'") if x["at_ms"] >= t and x["a"] == a]
    s.expect("whisper: the chronicle (audit) keeps the words and the way", chron == [f"{names[a]} (whisper) to {names[b]}: “The tally is short tonight.”"], chron, fatal=False)
    ms = {w: s.rows(f"SELECT heard_ms, speaker FROM mind_state WHERE id = {w}")[0] for w in (b, c)}
    s.expect("whisper: only b's hearing mark moves", ms[b]["heard_ms"] >= t and ms[c]["heard_ms"] < t, ms, fatal=False)
    time.sleep(GAP)
    # Refused whispers write nothing.
    for label, to, text, want in (("to c at 4 m", c, "Come closer, c.", "too far to whisper: step closer"), ("to no one", 0, "Anyone?", "a whisper needs someone to whisper to")):
        r, got, t = line_by(a, text, to, "whisper", f"whisper-refused-{to}")
        s.expect(f"whisper {label} is refused: {want}", r.returncode != 0 and want in (r.stderr + r.stdout) and not any(got[w] for w in at), (r.stderr or "")[-200:], fatal=False)
        time.sleep(GAP)
    # A whispered introduction teaches only the one it was whispered to.
    r, got, t = line_by(a, f"I am {names[a]}.", b, "whisper", "whisper-intro")
    acq = sorted(x["observer"] for x in s.rows("SELECT * FROM acquaintance") if x["known"] == a)
    s.expect("whisper: a whispered name teaches b alone", acq == [b], acq, fatal=False)
    time.sleep(GAP)
    # A call carries to d at 20 m and to animals as a shout; a second within 6 s is refused; a
    # long line is cut to 80 characters.
    long = "Hey, everyone, the cart from the coast is here with fish and salt and news from the south road!"
    # The second call is said 2.1 s after the first (past the 2 s speaking limit, within the
    # call's own 6 s), before either is read: reading every watcher's rows between them took
    # more than 6 s on a loaded machine, and the second call was then rightly accepted.
    t = now(s)
    r = say_as(s, a, long, 0, "call")
    time.sleep(2.1)
    t2 = now(s)
    r2 = say_as(s, a, "Again!", 0, "call")
    time.sleep(1.0)
    got, got2 = collect(r, t, "call"), collect(r2, t2, "call-again")
    cut = long[:80]
    s.expect("call: d, 20 m away, hears it, and how far", [x["text"] for x in got[d] if x["kind"] == "speech"] == [f"A stranger calls out from about 20 m: “{cut}”"], got[d], fatal=False)
    s.expect("call: the deer hears a person shouting", any(x["kind"] == "signal" and x["text"].startswith("You hear a person shouting,") for x in got[deer]), got[deer], fatal=False)
    s.expect("call: those near hear it too, cut to 80 characters", all(any(x["kind"] == "speech" and x["text"].endswith(f"“{cut}”") for x in got[w]) for w in (b, c, p.id, e)), None, fatal=False)
    s.expect("call: a second within 6 s is refused in call_check's words", r2.returncode != 0 and "too soon to call out again: wait a few seconds" in (r2.stderr + r2.stdout) and not any(got2[w] for w in at), (r2.stderr or "")[-200:], fatal=False)
    time.sleep(6.5)
    # Silence that tells the truth (`speech_truth`, on by default; docs/COMMUNICATION.md §15):
    # e is seen (by day) but beyond the voice; d is out of sight.
    seen_far = "A stranger is too far away: they could not have heard you."
    unseen = "A stranger is out of earshot: they could not have heard you."
    r, got, t = line_by(a, "Can you hear me, e?", e, "say", "silence")
    sil = [x["text"] for x in got[a] if x["kind"] == "silence"]
    s.expect(f"silence: {'e, seen but beyond the voice, is too far away (the fact, no advice)' if not night else 'at night e is not seen: out of earshot'}", sil == [seen_far if not night else unseen], sil, fatal=False)
    time.sleep(GAP)
    r, got, t = line_by(a, "Can you hear me, d?", d, "say", "silence-unseen")
    s.expect("silence: d, out of sight, is out of earshot (never `No answer`)", [x["text"] for x in got[a] if x["kind"] == "silence"] == [unseen], got[a], fatal=False)
    time.sleep(GAP)
    # A line to the room: from d (10 m beyond e, 13 m beyond the player, more beyond the rest),
    # nobody is near enough, and d is told so; from a (b at 1 m), no such row.
    r, got, t = line_by(d, "Is anyone out here?", 0, "say", "room-nobody")
    hearers_d = [w for w in at if w not in (d, deer) and any("anyone out here" in x["text"] for x in got[w])]
    s.expect("room: a line to the room that nobody receives gives the speaker `Nobody was near enough to hear you.`",
             r.returncode == 0 and not hearers_d and [(x["subject"], x["text"]) for x in got[d] if x["kind"] == "silence"] == [(0, "Nobody was near enough to hear you.")], (hearers_d, got[d]), fatal=False)
    time.sleep(GAP)
    r, got, t = line_by(a, "Good evening, all of you.", 0, "say", "room-heard")
    s.expect("room: a line to the room that someone receives gives no `silence` row",
             r.returncode == 0 and any("Good evening, all" in x["text"] for x in got[b]) and not [x for x in got[a] if x["kind"] == "silence"], got[a], fatal=False)
    time.sleep(GAP)
    # A player who speaks to someone out of earshot gets the same words, and an act outcome
    # (code `reach`) its client can draw a note from.
    t = now(s)
    p.call("human_say", ["Can you hear me, d?", d])
    time.sleep(1.0)
    psil = [x for x in rows(p.id, t) if x["kind"] == "silence"]
    outs = [o for o in s.rows(f"SELECT * FROM act_outcome WHERE observer = {p.id}") if psil and o["id"] == psil[0]["id"]]
    s.expect("silence: the player gets the words and an act outcome (act, reach, not ok, the same words)",
             len(psil) == 1 and psil[0]["text"].endswith("they could not have heard you.") and len(outs) == 1 and (outs[0]["kind"], outs[0]["code"], outs[0]["ok"], outs[0]["skill"], outs[0]["why"], outs[0]["other"]) == ("act", "reach", False, "say", psil[0]["text"], d),
             (psil, outs), fatal=False)
    time.sleep(GAP)
    # A queued line (a graph's say) to e, due while e is beyond the voice: not said; a is told.
    t = now(s)
    s.graph(a, {"seq": [{"say": {"text": "Queued words for e.", "to": {"id": e}}}, {"wait": 60}]})
    time.sleep(3.0)
    s.graph(a, {"wait": 120})
    chron = [x["text"] for x in s.rows("SELECT * FROM chronicle WHERE kind = 'speech'") if x["at_ms"] >= t and x["a"] == a]
    told = [x["text"] for x in rows(a, t) if x["kind"] == "silence"]
    heard_q = [w for w in at if w != a and any("Queued words for e." in x["text"] for x in rows(w, t))]
    s.expect("queued: a planned line to e, out of earshot as it comes due, is not said, and a is told so",
             not chron and not heard_q and told == [f"{seen_far if not night else unseen} You did not say your planned line: “Queued words for e.”."], (chron, heard_q, told), fatal=False)
    time.sleep(GAP)
    # The law off: speech-2's words, and the queued line said into the air.
    s.call("set_world_law", "speech_truth", "false")
    try:
        r, got, t = line_by(d, "Anyone at all? (law off)", 0, "say", "room-off")
        s.expect("law off: a room line nobody receives gives no row", not [x for x in got[d] if x["kind"] == "silence"], got[d], fatal=False)
        time.sleep(GAP)
        r, got, t = line_by(a, "Can you hear me, d? (law off)", d, "say", "silence-off")
        s.expect("law off: d out of sight gives speech-2's `No answer`", [x["text"] for x in got[a] if x["kind"] == "silence"] == ["No answer from a stranger; they don't seem to be within earshot."], got[a], fatal=False)
        time.sleep(GAP)
        t = now(s)
        s.graph(a, {"seq": [{"say": {"text": "Queued words for e, law off.", "to": {"id": e}}}, {"wait": 60}]})
        time.sleep(3.0)
        s.graph(a, {"wait": 120})
        chron = [x["text"] for x in s.rows("SELECT * FROM chronicle WHERE kind = 'speech'") if x["at_ms"] >= t and x["a"] == a]
        told = [x["text"] for x in rows(a, t) if x["kind"] == "silence"]
        s.expect("law off: the queued line is said into the air, with speech-2's silence", len(chron) == 1 and "Queued words for e, law off." in chron[0] and told == ["A stranger is too far to hear you; call out or go closer." if not night else "No answer from a stranger; they don't seem to be within earshot."], (chron, told), fatal=False)
    finally:
        s.call("set_world_law", "speech_truth", "true")
    time.sleep(GAP)
    # Overheard names: b says c's name to c; whoever hears it in full and sees c learns it.
    r, got, t = line_by(b, f"{names[c]}, come over here.", c, "say", "names")
    # (the cast only: a resident who wanders into earshot learns the name too, rightly)
    learned = sorted(x["observer"] for x in s.rows("SELECT * FROM acquaintance") if x["known"] == c and x["since_ms"] >= t and x["observer"] in at)
    want = sorted(w for w in (a, p.id, e) if math.dist(at[b], at[w]) <= 9.0 and (math.dist(at[w], at[c]) <= (6.0 if night else 11.0)))
    s.expect("names: those who heard c named and saw c learn c's name; c and d do not", learned == want, (learned, want), fatal=False)
    told = [x["text"] for x in got[a] if x["kind"] == "introduced"]
    s.expect("names: the row reads `You heard <caller> call <Name> by name.`", told == [f"You heard a stranger call {names[c]} by name."], told, fatal=False)
    time.sleep(GAP)
    r, got, t = line_by(a, f"{names[b]}, listen closely.", b, "whisper", "names-whisper")
    s.expect("names: a name in a whisper teaches no onlooker", not [x for x in s.rows("SELECT * FROM acquaintance") if x["known"] == b and x["since_ms"] >= t], None, fatal=False)
    time.sleep(GAP)
    # A name of two words is mentioned by its given name.
    t = now(s)
    p.call("human_say", ["I'm Mara.", 0])
    time.sleep(1.0)
    learned = sorted(x["observer"] for x in s.rows("SELECT * FROM acquaintance") if x["known"] == p.id and x["since_ms"] >= t and x["observer"] in at)
    s.expect("names: saying a given name (Mara of Mara Quill) introduces to those in earshot", learned == sorted(w for w in (a, b, c, e, d) if math.dist(at[p.id], at[w]) <= 9.0), learned, fatal=False)
    time.sleep(GAP)
    # Someone too far away to make out (fix-far-silence): with an overlay of `perceived_of` that
    # makes everyone past 8 m `far` (as Cullet's law does past 24 m), the label is not followed by
    # "is too far away": the words say "They are …", in the silence row and the player's outcome.
    shipped = (scenes.ROOT / "living/scripts/skills.rhai").read_text()
    far_law = 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 8.0 { r.name = false; r.health = "none"; r.far = true; } r }'
    s.call("install_script", scenes.compose(shipped, {"perceived_of": far_law}))
    try:
        r, got, t = line_by(a, "Can you hear me, far one?", e, "say", "silence-far")
        sil = [x["text"] for x in got[a] if x["kind"] == "silence"]
        want = "They are too far away: they could not have heard you." if not night else "They are out of earshot: they could not have heard you."
        s.expect("far: a line to e, too far away to make out, reads `They are …`, not the label twice", sil == [want] and not any("make out is" in x for x in sil), sil, fatal=False)
        time.sleep(GAP)
        t = now(s)
        p.call("human_say", ["Can you hear me, far one?", d])
        time.sleep(1.0)
        psil = [x for x in rows(p.id, t) if x["kind"] == "silence"]
        outs = [o for o in s.rows(f"SELECT * FROM act_outcome WHERE observer = {p.id}") if psil and o["id"] == psil[0]["id"]]
        s.expect("far: the player's silence and act outcome to d say `They are out of earshot …`",
                 [x["text"] for x in psil] == ["They are out of earshot: they could not have heard you."] and len(outs) == 1 and outs[0]["why"] == psil[0]["text"], (psil, outs), fatal=False)
        played = s.rows(f"SELECT ai FROM character WHERE id = {p.id}")
        s.expect("the player listener is still played at the end (the minds never took it over mid-scene)", played and played[0]["ai"] is False, played, fatal=False)
    finally:
        s.call("install_script", shipped, check=False)


def metrics(s):
    # The database's identity, as the server's metrics name it (`spacetime list`).
    ident = next(l.split("|")[1].strip() for l in s.command("list").stdout.splitlines() if "|" in l and l.split("|")[0].strip() == s.db)
    code, text = http("/v1/metrics")
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or f'db="{ident}"' not in line:
            continue
        name, value = line.rsplit(" ", 1)
        out[name] = float(value)
    return out


def crowd(s):
    """N people stand in a square, each saying room lines in turn at a declared rate; the cost of
    one line from the server's metrics (per reducer and table, this database only)."""
    n, side, lines, every = s.args.n, s.args.side, s.args.lines, s.args.every
    card = next((c for c in sql(s, "SELECT * FROM speech_card") if c["name"] == s.args.way), None) if not s.baseline else None
    if card and card["needs_to"]:
        s.expect(f"crowd: `{s.args.way}` needs someone to say it to; a crowd of room lines does not drive it", False, card, fatal=False, known=True)
        return
    people = s.people(n)
    line = quiet_line(s, length=int(side) + 4, clear=40.0)
    x0, y0 = line[2]
    cols = math.ceil(math.sqrt(n))
    for i, who in enumerate(people):
        s.call("place_at", who, x0 + (i % cols) * side / max(1, cols - 1), y0 - 2 + (i // cols) * side / max(1, cols - 1))
    time.sleep(2)
    way = None if s.baseline else s.args.way
    before = metrics(s)
    t0 = time.monotonic()
    for i in range(lines):
        say_as(s, people[i % n], f"Line {i}: the market opens at noon.", 0, way)
        time.sleep(max(0.0, t0 + (i + 1) * every - time.monotonic()))
    time.sleep(1.5)
    after = metrics(s)
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}
    pick = lambda prefix, reducer: next((v for k, v in delta.items() if k.startswith(prefix) and f'reducer="{reducer}"' in k), 0.0)
    calls = pick("spacetime_reducer_plus_query_duration_sec_count", "mind_say")
    rows = {}
    for k, v in delta.items():
        if k.startswith("spacetime_num_rows_inserted_total") and 'reducer_or_query="mind_say"' in k:
            table = k.split('table_name="', 1)[1].split('"', 1)[0] if 'table_name="' in k else k
            rows[table] = rows.get(table, 0) + v
    exp = [r for who in people for r in s.rows(f"SELECT kind, at_ms FROM experience WHERE observer = {who}")]
    heard_rows = [r for r in s.rows("SELECT * FROM line_heard")] if not s.baseline else []
    report = {"way": way or "say (before ways)", "population": n, "square_m": side, "density_per_m2": round(n / (side * side), 3), "lines": lines, "line_every_s": every,
              "lines_per_min": round(60 / every, 1), "calls_counted": calls,
              "wasm_us_per_line": round(pick("reducer_wasm_time_usec", "mind_say") / max(calls, 1), 1),
              "fuel_per_line": round(pick("reducer_wasmtime_fuel_used", "mind_say") / max(calls, 1)),
              "reducer_plus_query_ms_per_line": round(1000 * pick("spacetime_reducer_plus_query_duration_sec_sum", "mind_say") / max(calls, 1), 3),
              "rows_inserted_per_line": {t: round(v / max(calls, 1), 2) for t, v in sorted(rows.items())},
              "speech_rows_per_line": round(sum(1 for r in exp if r["kind"] == "speech") / lines, 2),
              "mean_hearers_listed": round(sum(len(h["hearers"]) for h in heard_rows) / max(1, len(heard_rows)), 2) if heard_rows else None,
              "rows_deleted_per_line": {k.split('table_name="', 1)[1].split('"', 1)[0]: round(v / max(calls, 1), 2) for k, v in sorted(delta.items()) if k.startswith("spacetime_num_rows_deleted_total") and 'reducer_or_query="mind_say"' in k},
              "metric_keys": sorted(k for k in delta if 'mind_say' in k)}
    (s.out / f"crowd-{n}-{way or 'base'}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "metric_keys"}, indent=1))
    s.expect("every line was counted", calls == lines, calls, fatal=False)


SCENES = {"regress": regress, "ways": ways, "channels": channels, "crowd": crowd}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", choices=[*SCENES, "diff"])
    ap.add_argument("--run")
    ap.add_argument("runs", nargs="*", help="diff: the two runs")
    ap.add_argument("--baseline", action="store_true", help="a module from before ways of speaking")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--side", type=float, default=10.0)
    ap.add_argument("--lines", type=int, default=60)
    ap.add_argument("--every", type=float, default=0.5)
    ap.add_argument("--way", default="say", help="crowd: the way the lines are said in")
    a = ap.parse_args()
    if a.scene == "diff":
        return diff(*a.runs)
    s = scenes.Scene(a.run, f"speech-{a.scene}")
    s.baseline, s.args = a.baseline, a
    error = None
    try:
        SCENES[a.scene](s)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        print(error, flush=True)
    finally:
        if hasattr(s, "takeover_s"):
            scenes.set_law(s, "takeover_s", s.takeover_s, check=False)
        (s.out / f"speech-{a.scene}-results.json").write_text(json.dumps({"db": s.db, "checks": s.results, "error": error}, indent=2) + "\n")
    return int(error is not None or any(r["status"] in {"FAIL", "XPASS"} for r in s.results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
