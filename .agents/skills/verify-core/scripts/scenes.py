#!/usr/bin/env python3
"""Assert core behavior through the authority on a shared-harness scratch run."""
import argparse
import importlib.util
import datetime
import json
import math
import re
import subprocess
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STDB = ROOT / "living/tools/stdb"
BASE = ROOT / ".local/living/verify"


class Scene:
    def __init__(self, run, name):
        # gate-*: the merge's scene gate (living/tools/scene_gate.py), databases verify-gate-*.
        if not re.fullmatch(r"(core|gate)-[a-z0-9-]+", run):
            raise ValueError("use a core-* (or the scene gate's gate-*) run name with lowercase letters, digits and hyphens")
        self.out = BASE / run
        state = json.loads((self.out / "state.json").read_text())
        self.db = state["db"]
        if self.db != "verify-" + run or not state.get("published"):
            raise ValueError("use a published core-* or gate-* run created by verify.py launch")
        self.name = name
        self.results = {}
        self.log = self.out / f"{name}-actions.jsonl"

    def command(self, *args, check=True):
        r = subprocess.run([str(STDB), *args], capture_output=True, text=True, timeout=180)
        with self.log.open("a") as f:
            f.write(json.dumps({"at_ms": time.time_ns() // 1_000_000, "args": args,
                                "exit": r.returncode, "stdout": r.stdout, "stderr": r.stderr}) + "\n")
        if check and r.returncode:
            raise RuntimeError(f"stdb {args[0]} failed: {r.stderr[-500:]}")
        return r

    def call(self, reducer, *args, check=True):
        enc = [json.dumps(a) for a in args]
        if sum(map(len, enc)) > 64_000:
            return self.http_call(reducer, list(args), check)
        return self.command("call", "-s", "local", self.db, reducer, *enc, check=check)

    def http_call(self, reducer, args, check=True):
        """A call too big for the command line (a script is past the 128 KiB one argument may
        hold), over HTTP as the world admin (the CLI's identity)."""
        if not getattr(self, "token", None):
            out = self.command("login", "show", "--token").stdout
            self.token = next(line.rsplit(" is ", 1)[1].strip() for line in out.splitlines() if "auth token" in line and " is " in line)
        url = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
        req = urllib.request.Request(f"{url}/v1/database/{self.db}/call/{reducer}", data=json.dumps(args).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                code, body = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read().decode()
        with self.log.open("a") as f:
            f.write(json.dumps({"at_ms": time.time_ns() // 1_000_000, "args": ["call (http)", self.db, reducer, f"{len(json.dumps(args))} bytes"], "exit": 0 if code == 200 else 1, "stdout": body, "stderr": ""}) + "\n")
        if check and code != 200:
            raise RuntimeError(f"{reducer} over HTTP failed: {code} {body[-500:]}")
        return subprocess.CompletedProcess([reducer], 0 if code == 200 else 1, body, "")

    def http_rows(self, query):
        """Rows over HTTP as the world admin (no CLI process per call: tens of ms, for polling a
        moment such as a windup starting)."""
        if not getattr(self, "token", None):
            out = self.command("login", "show", "--token").stdout
            self.token = next(line.rsplit(" is ", 1)[1].strip() for line in out.splitlines() if "auth token" in line and " is " in line)
        url = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
        req = urllib.request.Request(f"{url}/v1/database/{self.db}/sql", data=query.encode(), method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=30) as r:
            table = json.loads(r.read().decode())[-1]
        names = [e["name"]["some"] for e in table["schema"]["elements"]]
        return [dict(zip(names, row)) for row in table["rows"]]

    def rows(self, query, label=None):
        r = self.command("sql", "--format", "json", "-s", "local", self.db, query)
        response = json.loads(next(line for line in r.stdout.splitlines() if line.startswith("[")))
        table = response[-1]
        names = [e["name"]["some"] for e in table["schema"]["elements"]]
        rows = [dict(zip(names, row)) for row in table["rows"]]
        if label:
            (self.out / f"{self.name}-{label}.json").write_text(json.dumps(rows, indent=2) + "\n")
        return rows

    def expect(self, name, passed, detail=None, fatal=True, known=False):
        status = ("XPASS" if passed else "XFAIL") if known else ("PASS" if passed else "FAIL")
        self.results[name] = {"passed": bool(passed), "status": status, "detail": detail}
        print(status + " " + name, flush=True)
        if not passed and fatal:
            raise AssertionError(f"{name}: {detail}")

    def wait(self, predicate, seconds=30, every=0.5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = predicate()
            if value:
                return value
            time.sleep(every)
        raise TimeoutError(f"{self.name}: condition did not become true in {seconds} s")

    def graph(self, actor, node):
        self.call("set_behavior", actor, json.dumps(node))
        self.rows(f"SELECT * FROM brain WHERE id = {actor}", f"installed-graph-{actor}-{time.time_ns()}")

    def act(self, actor, node):
        self.call("mind_act", actor, [json.dumps(node)], "verify-core")

    def people(self, n):
        before = {c["id"] for c in self.rows("SELECT id FROM character")}
        self.call("spawn_crowd", n, True)
        made = [c["id"] for c in self.rows("SELECT id, name FROM character") if c["id"] not in before]
        self.expect("scene actors created", len(made) == n, made)
        for actor in made:
            self.graph(actor, {"wait": 120})
        return made

    def vitals(self, actor, label=None):
        return self.rows(f"SELECT * FROM vitals WHERE id = {actor}", label)[0]

    def needs(self, actor, label):
        v = self.vitals(actor)
        now = self.rows("SELECT last_ms FROM clock")[0]["last_ms"]
        m = max(0, now - v["at_ms"]) / 60000
        n = {k: max(0, min(v[k] + v[k + "_rate"] * m, v["max_hp"] if k == "hp" else 100))
             for k in ("hp", "hunger", "energy")}
        (self.out / f"{self.name}-{label}.json").write_text(json.dumps({"vitals": v, "now_ms": now, "needs": n}, indent=2) + "\n")
        return n

    def inventory(self, actor, label=None):
        return {r["item"]: r["qty"] for r in self.rows(f"SELECT item, qty FROM inventory WHERE owner = {actor}", label)}

    def story(self, kind, actor, label=None):
        return self.rows(f"SELECT * FROM chronicle WHERE kind = '{kind}' AND a = {actor}", label)

    def told(self, actor, words, kind="act"):
        return [r for r in self.rows(f"SELECT kind, text FROM experience WHERE observer = {actor}")
                if r["kind"] == kind and words in r["text"]]


def tick(s):
    a, b = s.people(2)
    s.call("place_near", b, a)
    c0 = s.rows("SELECT * FROM clock", "clock-before")[0]
    time.sleep(5)
    c1 = s.rows("SELECT * FROM clock", "clock-after")[0]
    seconds = (c1["last_ms"] - c0["last_ms"]) / 1000
    hz = (c1["tick"] - c0["tick"]) / seconds
    s.expect("nominal 60 Hz ticks advance", 52 <= hz <= 65, {"hz": hz, "seconds": seconds})
    stats0 = s.rows("SELECT * FROM stats", "stats-before")[0]
    time.sleep(2)
    stats1 = s.rows("SELECT * FROM stats", "stats-after")[0]
    s.expect("housekeeping refreshes stats", stats1["at_ms"] > stats0["at_ms"] and stats1["ticks"] > stats0["ticks"])
    s.call("grant_items", a, "stone", 1)
    s.graph(a, {"first": [{"do": "rest"}]})
    s.wait(lambda: s.rows(f"SELECT skill FROM activity WHERE id = {a}")[0]["skill"] == "rest")
    s.graph(a, {"seq": [{"wait": 3}, {"do": "give", "target": {"id": b}, "item": "stone"}, {"wait": 120}]})
    s.wait(lambda: any(r["skill"] == "wait" and r["qty"] == 3 for r in s.rows(f"SELECT skill, qty FROM activity WHERE id = {a}")))
    s.call("set_paused", True)
    try:
        paused0 = s.rows("SELECT * FROM clock", "paused-clock-before")
        slow0 = s.rows("SELECT * FROM stats", "paused-stats-before")
        activity0 = s.rows(f"SELECT * FROM activity WHERE id = {a}", "paused-activity-before")
        time.sleep(5)
        paused1 = s.rows("SELECT * FROM clock", "paused-clock-after")
        slow1 = s.rows("SELECT * FROM stats", "paused-stats-after")
        activity1 = s.rows(f"SELECT * FROM activity WHERE id = {a}", "paused-activity-after")
        s.expect("pause stops ticks, housekeeping and completion", paused0 == paused1 and slow0 == slow1
                 and activity0 == activity1 and s.inventory(b).get("stone", 0) == 0)
    finally:
        s.call("set_paused", False)
    s.wait(lambda: s.inventory(b).get("stone", 0) == 1)
    s.expect("resume completes overdue work", bool(s.story("give", a, "resumed-gift")))
    s.call("set_profile", True)
    try:
        time.sleep(1)
    finally:
        s.call("set_profile", False)
    r = s.command("logs", "-s", "local", s.db)
    (s.out / "tick-profile.txt").write_text(r.stdout)
    s.expect("profile emits actual tick spans", 'tick' in r.stdout and ('µs' in r.stdout or 'us' in r.stdout), s.db)


def person_pace():
    """The rules' `person_pace` law (a person's need rates against real time; 1.0 before iter-11)."""
    m = re.search(r"fn person_pace\(x\) \{ ([0-9.]+) \}", (Path(__file__).resolve().parents[4] / "living/scripts/skills.rhai").read_text())
    return float(m.group(1)) if m else 1.0


def needs(s):
    a = s.people(1)[0]
    k = person_pace()
    s.wait(lambda: s.vitals(a)["hunger_rate"] > 0)
    n0 = s.needs(a, "idle-before")
    time.sleep(8)
    n1 = s.needs(a, "idle-after")
    s.expect("hunger rises and idle energy falls", n1["hunger"] > n0["hunger"] + 0.4 * k and n1["energy"] < n0["energy"] - 0.1 * k, {"person_pace": k})
    s.graph(a, {"first": [{"do": "rest"}]})
    s.wait(lambda: s.vitals(a)["energy_rate"] > 0)
    rest0 = s.needs(a, "rest-before")
    time.sleep(8)
    rest1 = s.needs(a, "rest-after")
    s.expect("rest recovers energy over time", rest1["energy"] > rest0["energy"] + 0.4 * k)
    s.call("grant_items", a, "cooked_meat", 1)
    before = s.needs(a, "eat-before")
    s.graph(a, {"seq": [{"do": "eat", "item": "cooked_meat"}, {"wait": 120}]})
    s.wait(lambda: s.inventory(a).get("cooked_meat", 0) == 0)
    after = s.needs(a, "eat-after")
    s.expect("eating consumes food and reduces hunger", after["hunger"] < before["hunger"] - 10)
    w = s.rows("SELECT * FROM world", "world")[0]
    def night():
        now = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
        hour = ((now - w["epoch_ms"] + w["day_ms"] * 7 // 24) % w["day_ms"]) / w["day_ms"] * 24
        return hour >= 20 or hour < 6
    print("Waiting for the real night boundary; no world clock is changed.", flush=True)
    s.wait(night, seconds=730, every=5)
    s.graph(a, {"first": [{"do": "rest"}]})
    s.wait(lambda: s.vitals(a)["rate_key"] & 2)
    cold = s.vitals(a, "cold")
    s.expect("actor is exposed to night cold", not cold["rate_key"] & (64 | 128))
    s.call("grant_items", a, "cloak", 1)
    s.graph(a, {"first": [{"do": "rest"}]})
    # The new rest resets the key to 0 before the needs are next read; wait for the key that
    # holds the cloak (bit 10) while still resting (bit 9) at night (bit 1), not that reset.
    s.wait(lambda: (s.vitals(a)["rate_key"] & (1024 | 512 | 2)) == (1024 | 512 | 2))
    warm = s.vitals(a, "cloaked")
    # An ordinary night's cold tires (1.5 a minute times `person_pace`, divided by the body's
    # hardiness gene) and does not hurt; only winter nights and nights in the rain do
    # (docs/SEEDED_LIVES.md).
    hardy = hardiness(s, a)
    s.expect("cloak removes the cold's tiring", abs(warm["energy_rate"] - cold["energy_rate"] - 1.5 * k / hardy) < 0.05,
             {"cold_energy_rate": cold["energy_rate"], "cloaked_energy_rate": warm["energy_rate"], "hardiness": hardy, "person_pace": k})
    s.expect("an ordinary night's cold does not hurt", abs(warm["hp_rate"] - cold["hp_rate"]) < 0.05,
             {"cold_hp_rate": cold["hp_rate"], "cloaked_hp_rate": warm["hp_rate"]})


def hardiness(s, actor):
    """The body's hardiness gene (1.0 when it has none)."""
    g = s.rows(f"SELECT genes FROM genome WHERE id = {actor}")
    return float(json.loads(g[0]["genes"]).get("hardiness", 1.0)) if g else 1.0


def seize(s):
    a, b, witness = s.people(3)
    s.call("place_near", b, a)
    s.call("place_near", witness, a)
    s.call("grant_items", b, "stone", 4)
    s.act(a, {"do": "seize", "target": {"id": b}, "item": "stone", "qty": 2})
    s.wait(lambda: s.told(a, "has not given in"))
    s.expect("seize refuses an unyielded healthy person", s.inventory(b, "refused-victim").get("stone") == 4
             and s.inventory(a, "refused-actor").get("stone", 0) == 0 and not s.story("seize", a))
    s.graph(b, {"seq": [{"do": "yield", "target": {"id": a}}, {"wait": 120}]})
    s.wait(lambda: s.story("yield", b))
    s.act(a, {"do": "seize", "target": {"id": b}, "item": "stone", "qty": 2})
    time.sleep(4)
    yielded = s.inventory(a).get("stone", 0) == 2
    s.rows(f"SELECT kind, text FROM experience WHERE observer = {a}", "yielded-seize-feedback")
    s.story("yield", b, "yield")
    s.expect("seize accepts a yielded healthy person", yielded,
             "act.rs skill_ctx must fill target.yielded_ago for seize; skills.rhai seize_check needs it.", fatal=False)
    if not yielded:
        s.call("grant_items", a, "spear", 1)
        # Blows do their full damage: stop striking once b is badly hurt (below the seize line).
        s.graph(a, {"first": [{"do": {"skill": "attack", "target": {"id": b}}}, {"wait": 1}]})
        s.wait(lambda: s.vitals(b)["hp"] / s.vitals(b)["max_hp"] < 0.3, seconds=65, every=0.1)
        s.graph(a, {"wait": 120})
        s.wait(lambda: all(r["skill"] != "attack" for r in s.rows(f"SELECT skill FROM activity WHERE id = {a}")))
        s.vitals(b, "beaten")
        s.act(a, {"do": "seize", "target": {"id": b}, "item": "stone", "qty": 2})
        s.wait(lambda: s.story("seize", a))
    s.expect("seize transfers exactly the requested quantity", s.inventory(b, "victim-after").get("stone") == 2
             and s.inventory(a, "actor-after").get("stone") == 2)
    s.expect("victim and witness perceive the force", bool(s.wait(lambda: s.told(b, "by force", "seize")))
             and bool(s.wait(lambda: s.told(witness, "by force", "seize"))))
    s.rows(f"SELECT kind, text FROM experience WHERE observer = {b}", "victim-feedback")
    s.rows(f"SELECT kind, text FROM experience WHERE observer = {witness}", "witness-feedback")
    s.story("seize", a, "chronicle")
    previous = max(r["at_ms"] for r in s.story("yield", b))
    s.graph(b, {"seq": [{"do": "yield", "target": {"id": a}}, {"wait": 120}]})
    s.wait(lambda: max(r["at_ms"] for r in s.story("yield", b)) > previous, seconds=30)
    s.call("grant_items", a, "spear", 1)
    # No mode: an attack's blows go on to death, a yield does not hold them back, and striking
    # the yielded is news.
    s.graph(a, {"first": [{"do": {"skill": "attack", "target": {"id": b}}}, {"wait": 1}]})
    s.wait(lambda: not s.rows(f"SELECT alive FROM character WHERE id = {b}")[0]["alive"], seconds=90)
    dead = s.rows(f"SELECT * FROM character WHERE id = {b}", "killed")[0]
    news = [r for r in s.story("attack", a, "struck-yielded") if "had yielded" in r["text"]]
    s.expect("a blow can kill someone who yielded, and striking them is news",
             "after yielding" in dead["cause"] and bool(s.story("killing", a, "killing")) and bool(news))


def death_names(s):
    """A community member killed by an outsider in front of another member and a bystander.

    Who knew the dead by name when they died still names them in the death percept and at
    the remains; the killer reads the death as done by "you"; the bystander, who never knew
    either, reads strangers (`die`, `witnessed`, `perception::knows_name`)."""
    victim, member, killer, bystander = s.people(4)
    names = {c["id"]: c["name"] for c in s.rows("SELECT id, name FROM character")}
    vname, kname = names[victim], names[killer]
    community = f"Verify Hollow {victim}"
    s.act(victim, {"do": "found", "text": community})
    s.wait(lambda: s.rows(f"SELECT * FROM membership WHERE member = {victim}"))
    s.call("place_near", member, victim)
    s.act(member, {"do": "join", "target": {"id": victim}})
    s.wait(lambda: s.rows(f"SELECT * FROM join_request WHERE asker = {member}"))
    s.act(victim, {"do": "welcome", "target": {"id": member}})
    s.wait(lambda: s.rows(f"SELECT * FROM membership WHERE member = {member}"))
    s.rows(f"SELECT * FROM membership WHERE member = {victim} OR member = {member}", "membership-before")
    s.expect("the two share a community and the others belong to none",
             len({m["community"] for m in s.rows(f"SELECT community FROM membership WHERE member = {victim} OR member = {member}")}) == 1
             and not s.rows(f"SELECT * FROM membership WHERE member = {killer} OR member = {bystander}"))
    for w in (killer, bystander):
        s.call("place_near", w, victim)
    s.call("grant_items", killer, "spear", 1)
    # As in the play-test: the victim gives in, and the blows go on to death.
    s.graph(victim, {"seq": [{"do": "yield", "target": {"id": killer}}, {"wait": 120}]})
    s.wait(lambda: s.story("yield", victim))
    s.graph(killer, {"first": [{"do": {"skill": "attack", "target": {"id": victim}}}, {"wait": 1}]})
    s.wait(lambda: not s.rows(f"SELECT alive FROM character WHERE id = {victim}")[0]["alive"], seconds=90)
    s.graph(killer, {"wait": 120})
    dead = s.rows(f"SELECT * FROM character WHERE id = {victim}", "killed")[0]
    s.rows(f"SELECT * FROM membership WHERE member = {victim} OR member = {member}", "membership-after")
    known = s.rows(f"SELECT * FROM acquaintance WHERE known = {victim}", "acquaintance-after")
    s.expect("the surviving member keeps the dead's name as an acquaintance, and no one else gains it",
             sorted(r["observer"] for r in known) == [member], known, fatal=False)
    deaths = {w: s.wait(lambda w=w: [r["text"] for r in s.rows(f"SELECT kind, text FROM experience WHERE observer = {w}") if r["kind"] == "death"], seconds=20)
              for w in (member, killer, bystander)}
    # The remains are noticed when each mind next looks round (`brain.rs`, structures).
    remains = {w: s.wait(lambda w=w: [r["text"] for r in s.rows(f"SELECT kind, text FROM experience WHERE observer = {w}") if r["kind"] == "saw" and "remains of" in r["text"]], seconds=60)
               for w in (member, bystander)}
    texts = {"victim": vname, "killer": kname, "death": {names[w]: t for w, t in deaths.items()}, "remains": {names[w]: t for w, t in remains.items()}}
    (s.out / f"{s.name}-texts.json").write_text(json.dumps(texts, indent=2) + "\n")
    print(json.dumps(texts, indent=2), flush=True)
    s.expect("the victim yielded before the killing blow", "after yielding" in dead["cause"], dead["cause"], fatal=False)
    s.expect("a member who saw it names the dead in the death percept",
             any(t.startswith(vname + " was killed by a stranger") for t in deaths[member]), deaths[member], fatal=False)
    s.expect("a member names the dead at the remains", any(f"the remains of {vname}" in t for t in remains[member]), remains[member], fatal=False)
    s.expect("the killer reads the death as done by you",
             any(t.endswith("was killed by you") or "was killed by you after yielding" in t for t in deaths[killer]) and not any(kname in t for t in deaths[killer]),
             deaths[killer], fatal=False)
    s.expect("a bystander who knew neither reads strangers",
             any(t.startswith("A stranger was killed by a stranger") for t in deaths[bystander]) and any("the remains of a stranger" in t for t in remains[bystander]),
             {"death": deaths[bystander], "remains": remains[bystander]}, fatal=False)


def health_seen(s):
    """Another's health reaches a fighter as the band everyone sees, never as a number, except
    while the fighter's own appraisal of them holds (docs/PERCEPTION.md, `perception::health_seen`).

    Strangers fight in pairs; the scene plays the mind's part by reading each pending
    `deliberation` (fight reports, `act::fight_report`, arrive there) and skipping it, so the
    next report can come. Pair one fights once (band words); then a graph's `health_of` on it
    reads the band's middle, and B's exact health once A appraises B. Pair two: C appraises D
    and they fight within the 20 s reveal (exact for C, band for D), then fight again after it
    ends (band). Each pair fights at most twice so no one dies of the scene."""
    thought = {"kind": "verify", "summary": "scripted acknowledgement, no model",
               "detail": "", "latency_ms": 0, "tokens": 0, "model": "none", "reference": "verify-core-health-seen"}
    a, b, c, d = s.people(4)
    s.call("place_near", b, a)
    s.call("place_near", c, a)
    s.call("place_near", d, c)
    reports, seen = [], set()
    exact_re = re.compile(r"they have (\d+) of (\d+) health\.$")
    words = ("unhurt", "scratched", "hurt", "badly hurt", "barely standing")
    pair = {a: b, b: a, c: d, d: c}

    def drain(phase):
        for row in s.rows(f"SELECT * FROM deliberation WHERE actor = {a} OR actor = {b} OR actor = {c} OR actor = {d}"):
            for line in row["reason"].splitlines():
                key = (row["actor"], line, row["updated_ms"])
                if line.startswith("The fight with") and key not in seen:
                    seen.add(key)
                    reports.append({"phase": phase, "actor": row["actor"], "text": line, "at_ms": row["updated_ms"],
                                    "revealed": [r["what"] for r in s.rows(f"SELECT * FROM reveal WHERE observer = {row['actor']}")]})
            s.call("mind_skip", row["actor"], row["updated_ms"], thought)

    def fight(x, y, phase, want, seconds=40):
        s.graph(x, {"first": [{"do": {"skill": "attack", "target": {"id": y}}}, {"wait": 1}]})
        s.graph(y, {"first": [{"do": {"skill": "attack", "target": {"id": x}}}, {"wait": 1}]})
        end = time.monotonic() + seconds
        while time.monotonic() < end and not want():
            drain(phase)
            time.sleep(0.4)
        for z in (x, y):
            s.graph(z, {"wait": 120})
        time.sleep(1.5)
        drain(phase)

    def of(phase, actor):
        return [r for r in reports if r["phase"] == phase and r["actor"] == actor]

    def band_only(r):
        return any(r["text"].endswith(f"they look {w}.") for w in words) and not exact_re.search(r["text"]) and "%" not in r["text"]

    def alive(*ids):
        return all(s.rows(f"SELECT alive FROM character WHERE id = {i}")[0]["alive"] for i in ids)

    drain("before")
    fight(a, b, "band", lambda: of("band", a) and of("band", b))
    s.expect("fight reports reach both fighters", of("band", a) and of("band", b), reports, fatal=False)
    s.expect("without an appraisal, fight reports carry the band's words, no number",
             of("band", a) and all(band_only(r) for r in reports if r["phase"] == "band"), [r["text"] for r in reports], fatal=False)

    s.act(c, {"do": "appraise", "target": {"id": d}})
    look = s.wait(lambda: s.told(c, "over:", "appraise"), seconds=20)
    reveal = s.wait(lambda: s.rows(f"SELECT * FROM reveal WHERE observer = {c} AND target = {d}", "reveal"), seconds=10)[0]
    s.expect("appraise tells exact health and starts a 20 s reveal",
             re.search(r"over: \d+ of \d+ health\.$", look[-1]["text"]) is not None, look[-1]["text"])
    max_d = round(s.vitals(d)["max_hp"])
    fight(c, d, "appraised", lambda: of("appraised", c), seconds=16)
    inside = [r for r in of("appraised", c) if r["at_ms"] < reveal["until_ms"]]
    s.expect("while C's appraisal holds, C's fight report gives D's exact health",
             inside and all(exact_re.search(r["text"]) and int(exact_re.search(r["text"]).group(2)) == max_d for r in inside),
             {"reports": [r["text"] for r in of("appraised", c)], "until_ms": reveal["until_ms"]}, fatal=False)
    s.expect("D, who appraised no one, still gets only C's band", all(band_only(r) for r in of("appraised", d)),
             [r["text"] for r in of("appraised", d)], fatal=False)
    s.wait(lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"] > reveal["until_ms"] + 1500, seconds=30)
    s.wait(lambda: not s.rows(f"SELECT * FROM reveal WHERE observer = {c}"), seconds=10)
    s.expect("C and D alive for the fight after the reveal", alive(c, d))
    fight(c, d, "after", lambda: of("after", c), seconds=40)
    s.expect("after the reveal ends, C's reports are back to the band", of("after", c) and all(band_only(r) for r in of("after", c)),
             [r["text"] for r in of("after", c)], fatal=False)
    (s.out / f"{s.name}-reports.json").write_text(json.dumps(reports, indent=2) + "\n")
    print(json.dumps([[r["phase"], r["actor"], r["text"]] for r in reports], indent=2), flush=True)

    # A graph's health_of reads the same perception: a threshold between B's exact share and
    # its band's middle tells which one the condition saw. A person's non-urgent think is
    # dropped within its think_min_s (20 s) of the last deliberation unless one is pending:
    # wait it out once, then leave the request pending so the second ask joins it.
    time.sleep(21)
    s.expect("A and B alive for health_of", alive(a, b))
    v = s.vitals(b)
    pct = s.needs(b, "health-of-b")["hp"] / v["max_hp"] * 100
    band = 4 if pct >= 90 else 3 if pct >= 65 else 2 if pct >= 40 else 1 if pct >= 20 else 0
    middle = {4: 95, 3: 77, 2: 52, 1: 30, 0: 10}[band]
    if abs(middle - pct) < 4 or min(abs(pct - e) for e in (20, 40, 65, 90)) < 2:
        s.expect("health_of: B's exact share is clear of its band's edges and middle", False,
                 {"pct": pct, "middle": middle}, fatal=False, known=True)
        return
    thr = (pct + middle) / 2
    exact_says = "below" if pct < thr else "above"
    band_says = "below" if middle < thr else "above"

    def asked(label):
        s.graph(a, {"if": {"cond": {"health_of": {"target": {"id": b}, "below": thr}},
                           "then": {"think": f"verify health_of {label} below"},
                           "else": {"think": f"verify health_of {label} above"}}})
        row = s.wait(lambda: [r for r in s.rows(f"SELECT * FROM deliberation WHERE actor = {a}") if f"verify health_of {label}" in r["reason"]], seconds=30)[0]
        s.graph(a, {"wait": 120})
        return "below" if f"verify health_of {label} below" in row["reason"] else "above"
    plain = asked("plain")
    s.expect("health_of without an appraisal reads the band's middle", plain == band_says,
             {"pct": round(pct, 1), "band": band, "middle": middle, "below": round(thr, 1), "said": plain}, fatal=False)
    s.act(a, {"do": "appraise", "target": {"id": b}})
    s.wait(lambda: s.rows(f"SELECT * FROM reveal WHERE observer = {a} AND target = {b}"), seconds=20)
    shown = asked("appraised")
    s.expect("health_of during an appraisal reads exact health", shown == exact_says,
             {"pct": round(pct, 1), "below": round(thr, 1), "said": shown}, fatal=False)


def lifecycle(s):
    w = s.rows("SELECT * FROM world", "world")[0]
    s.expect("compressed lifecycle seed selected", w["run"] == "s1-acts" and w["life_pace"] < 0.1)
    people = s.rows("SELECT * FROM character WHERE kind = 'person'", "before")
    before_ids = {c["id"] for c in people}
    infant = next((c for c in people if c["alive"] and c["stage"] == 0), None)
    s.expect("seed has a living infant", infant is not None)
    adults = [c["id"] for c in people if c["alive"] and c["stage"] == 2]
    a, b = adults[:2]
    for actor in (a, b, infant["id"]):
        s.graph(actor, {"first": [{"do": "rest"}]})
    s.call("place_near", b, a)
    s.call("place_structure", a, "shelter")
    for actor in (a, b):
        s.call("grant_items", actor, "cooked_meat", 2)
        s.graph(actor, {"seq": [{"do": "eat", "item": "cooked_meat"}, {"wait": 120}]})
        s.wait(lambda actor=actor: s.needs(actor, f"fed-{actor}")["hunger"] < 60)
    s.act(a, {"do": "conceive", "target": {"id": b}})
    time.sleep(3)
    s.act(b, {"do": "conceive", "target": {"id": a}})
    expected = s.wait(lambda: s.rows(f"SELECT * FROM expecting WHERE a = {a}", "expecting"))
    timeout = max(10, (expected[0]["due_ms"] - time.time_ns() // 1_000_000) / 1000 + 10)
    child = s.wait(lambda: [c for c in s.rows(f"SELECT * FROM character WHERE parent_a = {a} AND parent_b = {b}")
                           if c["id"] not in before_ids], seconds=timeout, every=2)[0]
    s.rows(f"SELECT * FROM character WHERE id = {child['id']}", "born")
    s.expect("birth creates a new living infant with both parents", child["alive"] and child["stage"] == 0
             and child["birth_age_days"] == 0 and child["id"] not in {c["id"] for c in people})
    s.expect("birth consumes pregnancy and starts rearing", not s.rows(f"SELECT * FROM expecting WHERE a = {a}")
             and len(s.rows(f"SELECT * FROM rearing WHERE id = {a}", "rearing")) == 1)
    s.expect("birth writes the child's chronicle", bool(s.story("birth", child["id"], "birth-chronicle")))
    aged = s.wait(lambda: [c for c in s.rows(f"SELECT * FROM character WHERE id = {infant['id']}") if c["stage"] == 1], seconds=450, every=2)
    s.expect("housekeeping advances infant to child", bool(aged) and bool(s.story("life", infant["id"], "grew")))
    s.rows(f"SELECT * FROM character WHERE id = {infant['id']}", "aged")


def grazing(s, deer=None):
    if deer is None:
        animals = s.rows("SELECT * FROM character WHERE kind = 'deer'", "deer-before")
        deer = next(c["id"] for c in animals if c["alive"])
        for c in s.rows("SELECT * FROM character"):
            if c["alive"]:
                s.graph(c["id"], {"wait": 120})
    rejected = s.call("set_behavior", deer, json.dumps({"do": "craft", "item": "spear"}), check=False)
    s.expect("deer body refuses human crafting", rejected.returncode != 0 and "cannot craft" in rejected.stderr)
    before = s.needs(deer, "graze-before")
    s.graph(deer, {"first": [{"do": "graze"}]})
    s.wait(lambda: any(r["skill"] == "graze" for r in s.rows(f"SELECT skill FROM activity WHERE id = {deer}")))
    s.rows(f"SELECT * FROM activity WHERE id = {deer}", "grazing")
    # Grazing is shown (`graze_shows` in skills.rhai): a `doing` row anyone in view sees.
    shown = s.wait(lambda: s.rows(f"SELECT * FROM doing WHERE id = {deer}", "graze-doing"), seconds=10)
    s.expect("grazing has a visible doing row", bool(shown), shown)
    s.wait(lambda: s.needs(deer, "graze-after")["hunger"] < before["hunger"] - 10, seconds=15)
    s.expect("grazing actually reduces hunger", True)


def wildlife(s):
    animals = s.rows("SELECT * FROM character WHERE kind = 'deer'", "deer-before")
    wolves = s.rows("SELECT * FROM character WHERE kind = 'wolf'", "wolves-before")
    for c in s.rows("SELECT * FROM character"):
        if c["alive"]:
            s.graph(c["id"], {"wait": 120})
    s.expect("world contains both wildlife kinds", any(c["alive"] for c in animals) and any(c["alive"] for c in wolves))
    deer = next(c["id"] for c in animals if c["alive"])
    grazing(s, deer)
    for c in animals:
        if c["alive"]:
            s.call("kill", c["id"], "verify-core migration floor")
    s.expect("deer floor starts below its threshold", not s.rows("SELECT id FROM character WHERE kind = 'deer' AND alive = true", "empty"))
    print("Waiting for the actual deer migration cooldown and minute housekeeping boundary.", flush=True)
    arrival(s)


def arrival(s):
    empty = s.out / "wildlife-empty.json"
    s.expect("deer extinction evidence is retained", empty.exists() and json.loads(empty.read_text()) == [])
    founders = "SELECT * FROM character WHERE kind = 'deer' AND alive = true AND parent_a = 0 AND parent_b = 0"
    newcomers = s.wait(lambda: s.rows(founders), seconds=1270, every=10)
    s.rows(founders, "newcomers")
    s.expect("migration creates five adult founders", len(newcomers) == 5 and all(c["stage"] == 2 and c["parent_a"] == 0 and c["parent_b"] == 0 for c in newcomers), newcomers)
    w = s.rows("SELECT * FROM world")[0]
    for c in newcomers:
        body = s.rows(f"SELECT * FROM body WHERE id = {c['id']}", f"arrival-body-{c['id']}")[0]
        x, y = c["home_x"], c["home_y"]
        chunk = s.rows(f"SELECT tiles FROM terrain_chunk WHERE id = {(int(y)//16 << 16) | int(x)//16}")[0]["tiles"]
        if isinstance(chunk, str):
            chunk = bytes.fromhex(chunk.removeprefix("0x"))
        ground = chunk[(int(y) % 16) * 16 + int(x) % 16]
        s.expect(f"newcomer {c['id']} lands near an edge on grass", min(x, y, w["width"]-x, w["height"]-y) <= 15.5 and ground == 0)
        s.graph(c["id"], {"wait": 120})
    story = s.rows("SELECT * FROM chronicle WHERE kind = 'arrival'", "chronicle")
    s.expect("migration writes the deer arrival story", any("deer" in c["text"] for c in story), story)
    ids = {c["id"] for c in newcomers}
    time.sleep(65)
    after = s.rows(founders, "cooldown")
    # The cooldown is about no second group coming in; a newcomer may meet a wolf meanwhile
    # (the scene's waits are over by the time the migration comes), so its death is recorded.
    fates = s.rows("SELECT id, alive, cause FROM character WHERE " + " OR ".join(f"id = {i}" for i in sorted(ids)), "cooldown-newcomers")
    s.expect("cooldown prevents another group below the floor", {c["id"] for c in after} <= ids, {"other_founders": sorted({c["id"] for c in after} - ids), "newcomers_dead": [c for c in fates if not c["alive"]]})


def infant(s):
    """One infant, two parents, a caring witness and two fallback adults; no minds."""
    if s.resume_infant:
        cast = json.loads((s.out / "infant-cast.json").read_text())
        infant_cries(s, **cast)
        return
    w = s.rows("SELECT * FROM world", "world")[0]
    s.expect("long-lived infant fixture selected", w["run"] == "verify-infant" and w["life_pace"] == 1)
    people = s.rows("SELECT * FROM character WHERE id <= 5", "cast-before")
    baby = next(c for c in people if c["alive"] and c["stage"] == 0)
    a, b = baby["parent_a"], baby["parent_b"]
    carers = [c["id"] for c in people if c["stage"] >= 2 and c["id"] not in (a, b)]
    s.expect("two adult parents and two fallback carers", len(carers) == 2 and all(
        any(c["id"] == p and c["stage"] >= 2 for c in people) for p in (a, b)))
    witness, warm_anchor = s.people(2)
    for c in s.rows("SELECT * FROM character"):
        s.graph(c["id"], {"first": [{"do": "rest"}]})
    # The caring witness would have been eligible alongside parents before this change.
    s.call("mind_update", witness, {"persona": None, "relations": [{"other": baby["id"],
        "trust": 50, "affinity": 50, "label": "care", "note": "verification fixture"}],
        "beliefs": None, "judgments": [], "places": [], "thought": None, "replace": True, "cues": None})
    for actor in (b, witness):
        s.call("place_near", actor, a)
    s.call("place_near", baby["id"], a)
    # The warm anchor stands well beyond the cry's hearing (12 m), placed there: where
    # spawn_crowd puts it is anywhere from 25 m (seen 26.98 and 28.68 against the 30 m check).
    pa = s.rows(f"SELECT x, y FROM body WHERE id = {a}")[0]
    for dx, dy in ((40, 0), (-40, 0), (0, 40), (0, -40), (32, 32), (-32, -32), (32, -32), (-32, 32)):
        if s.call("place_at", warm_anchor, pa["x"] + dx, pa["y"] + dy, check=False).returncode == 0:
            break
    s.call("place_structure", warm_anchor, "shelter")
    s.rows("SELECT * FROM relation", "relations")
    positions = {r["id"]: r for r in s.rows("SELECT * FROM body", "positions-before")}
    remote = math.hypot(positions[a]["x"] - positions[warm_anchor]["x"], positions[a]["y"] - positions[warm_anchor]["y"])
    s.expect("warm anchor lies outside crying hearing", remote > 30, remote)

    thought = {"kind": "verify", "summary": "scripted acknowledgement, no model",
        "detail": "", "latency_ms": 0, "tokens": 0, "model": "none", "reference": "verify-core-infant"}
    def clear(d):
        s.call("mind_skip", d["actor"], d["updated_ms"], thought)
    def requests(label=None):
        return s.rows("SELECT * FROM deliberation", label)
    def scene_for(parent, label):
        s.graph(parent, {"think": "verify-core infant looks " + label})
        d = s.wait(lambda: [d for d in requests() if d["actor"] == parent and label in d["reason"]], seconds=60)[0]
        scene = json.loads(d["scene"])
        (s.out / f"infant-{label}-scene.json").write_text(json.dumps(scene, indent=2) + "\n")
        visible = next(c for c in scene["creatures"] if c["id"] == baby["id"])
        clear(d)
        s.graph(parent, {"first": [{"do": "rest"}]})
        return visible.get("looks", "")
    def night_and_no_healing():
        now = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
        hour = ((now - w["epoch_ms"] + w["day_ms"] * 7 // 24) % w["day_ms"]) / w["day_ms"] * 24
        v = s.vitals(baby["id"])
        hunger = v["hunger"] + v["hunger_rate"] * max(0, now - v["at_ms"]) / 60000
        return (20 <= hour < 22 or hour < 2) and 70 <= hunger < 95
    print("Waiting for real night with infant hunger >=70 (no healing), so health shows only the cold.", flush=True)
    # Hunger rises at the rules' pace (`person_pace`): a slower pace means a longer wait.
    s.wait(night_and_no_healing, seconds=2100 / person_pace(), every=5)
    s.expect("infant is still alive and infant", s.rows(f"SELECT stage, alive FROM character WHERE id = {baby['id']}")[0] == {"stage": 0, "alive": True})
    s.call("place_near", baby["id"], warm_anchor)
    s.call("place_near", a, baby["id"])
    s.wait(lambda: s.vitals(baby["id"])["rate_key"] & 128)
    warm = s.vitals(baby["id"], "sheltered-vitals")
    warm_looks = scene_for(a, "sheltered")
    s.call("place_near", baby["id"], b)
    s.call("place_near", a, baby["id"])
    s.wait(lambda: not s.vitals(baby["id"])["rate_key"] & (64 | 128))
    cold = s.vitals(baby["id"], "exposed-vitals")
    cold_looks = scene_for(b, "exposed")
    # A summer night's cold tires and does not hurt (docs/SEEDED_LIVES.md); only winter nights
    # and nights in the rain do.
    s.expect("a summer night's cold does not hurt the exposed infant", abs(warm["hp_rate"] - cold["hp_rate"]) < 0.05 and cold["hp_rate"] >= 0,
             {"sheltered": warm["hp_rate"], "exposed": cold["hp_rate"]})
    if not s.baseline:
        s.expect("parent sees warm shelter and cold exposure",
                 "warm" in warm_looks and "cold" in cold_looks,
                 {"sheltered_looks": warm_looks, "exposed_looks": cold_looks})
    n0 = s.needs(baby["id"], "cold-before")
    time.sleep(8)
    n1 = s.needs(baby["id"], "cold-after")
    s.expect("the exposed infant keeps its health on a summer night", n1["hp"] >= n0["hp"] - 0.05)

    cast = {"baby": baby, "a": a, "b": b, "carers": carers, "witness": witness, "warm_anchor": warm_anchor}
    (s.out / "infant-cast.json").write_text(json.dumps(cast, indent=2) + "\n")
    infant_cries(s, **cast)


def infant_cries(s, baby, a, b, carers, witness, warm_anchor):
    thought = {"kind": "verify", "summary": "scripted acknowledgement, no model",
        "detail": "", "latency_ms": 0, "tokens": 0, "model": "none", "reference": "verify-core-infant"}
    def clear(d):
        s.call("mind_skip", d["actor"], d["updated_ms"], thought)
    def requests(label=None):
        return s.rows("SELECT * FROM deliberation", label)
    # Adults must not introduce starvation/injury alarms into the infant's requests.
    for actor in (a, b, witness, *carers):
        s.call("grant_items", actor, "cooked_meat", 3)
        for _ in range(3):
            before = s.inventory(actor).get("cooked_meat", 0)
            s.act(actor, {"do": "eat", "item": "cooked_meat"})
            s.wait(lambda actor=actor, before=before: s.inventory(actor).get("cooked_meat", 0) < before)
        s.needs(actor, f"fed-adult-{actor}")

    # Park every fallback carer by the remote warm anchor during the parents phase.
    for actor in carers:
        s.call("place_near", actor, warm_anchor)
    s.call("place_near", a, baby["id"])
    s.call("place_near", b, baby["id"])
    s.call("place_near", witness, baby["id"])
    for actor in (a, b, witness):
        s.graph(actor, {"first": [{"do": "rest"}]})
    # Keep hunger as the only cause across dawn, without patching food or energy.
    s.call("grant_items", baby["id"], "cloak", 1)
    # Feed only enough to keep hunger as the sole physical cause throughout the window.
    s.graph(baby["id"], {"first": [{"do": "rest"}]})
    hunger = s.needs(baby["id"], "before-cry-food")["hunger"]
    count = max(0, math.ceil((hunger - 54) / 12))
    s.call("grant_items", baby["id"], "berries", count)
    for _ in range(count):
        before = s.inventory(baby["id"]).get("berries", 0)
        s.act(baby["id"], {"do": "eat", "item": "berries"})
        s.wait(lambda before=before: s.inventory(baby["id"]).get("berries", 0) < before)
    time.sleep(3)
    s.wait(lambda: 55 < s.needs(baby["id"], "hunger-ready")["hunger"] < 80, seconds=300 / person_pace(), every=2)
    for d in requests():
        clear(d)
    time.sleep(21)
    hunger = s.needs(baby["id"], "measurement-start")["hunger"]
    s.expect("infant has room for a stable hunger-only measurement", 55 < hunger < 80, hunger)
    start = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.graph(baby["id"], {"seq": [{"do": "signal", "item": "cry"}, {"wait": 6}]})
    events, initial = [], {}
    seen = set()
    cause = None
    unrelated = None
    unrelated_reason = "verify-core unrelated reminder request"
    inject_at = time.monotonic() + 60
    end = time.monotonic() + 250
    while time.monotonic() < end:
        if not s.baseline and unrelated is None and a in initial and time.monotonic() >= inject_at:
            s.graph(a, {"think": unrelated_reason})
            unrelated = s.wait(lambda: [d for d in requests() if d["actor"] == a
                and unrelated_reason in d["reason"]], seconds=30)[0]
            s.expect("answered parent has an unrelated pending request before reminder",
                     "crying" not in unrelated["reason"], unrelated)
            (s.out / "infant-unrelated-pending.json").write_text(json.dumps(unrelated, indent=2) + "\n")
            s.graph(a, {"first": [{"do": "rest"}]})
        rows = {d["actor"]: d for d in requests()}
        if s.baseline:
            heard = s.rows(f"SELECT * FROM experience WHERE subject = {baby['id']} AND kind = 'signal'")
            stamps = [(e["observer"], e["at_ms"]) for e in heard if e["at_ms"] >= start and "crying" in e["text"]]
        else:
            state = s.rows(f"SELECT * FROM infant_cry WHERE infant = {baby['id']}")
            stamps = [tuple(p) for p in state[0]["prompted"]] if state else []
            if state:
                cause = state[0]["needs"] if cause is None else cause
                if state[0]["needs"] != cause or cause != [[0, []]]:
                    s.expect("cry cause remains hunger alone", False, state[0]["needs"])
        for actor, stamp in stamps:
            key = (actor, stamp)
            d = rows.get(actor)
            if key in seen or stamp < start or not d or baby["name"] not in d["reason"] or "crying" not in d["reason"]:
                continue
            if s.baseline and not d["requested_ms"] <= stamp <= d["updated_ms"]:
                continue
            event = {"at_ms": stamp, "actor": actor, "kind": "created" if d["requested_ms"] == stamp else "merged", "request": d}
            events.append(event)
            seen.add(key)
            initial.setdefault(actor, d)
            with (s.out / "infant-prompt-events.jsonl").open("a") as f:
                f.write(json.dumps(event) + "\n")
            s.rows("SELECT * FROM deliberation", f"requests-{len(events)}")
            if actor == a:
                clear(d)
        with (s.out / "infant-request-observations.jsonl").open("a") as f:
            f.write(json.dumps({"at_ms": time.time_ns() // 1_000_000, "requests": list(rows.values())}) + "\n")
        time.sleep(1)
    finish = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    metrics = {"baseline": s.baseline, "infants": 1, "run_count": 1, "start_ms": start,
        "finish_ms": finish, "minutes": (finish-start)/60000, "created": sum(e["kind"] == "created" for e in events),
        "merged": sum(e["kind"] == "merged" for e in events), "events": len(events),
        "prompts_per_infant_minute": len(events) * 60000 / (finish-start),
        "recipient_counts": {str(actor): sum(e["actor"] == actor for e in events) for actor in sorted(initial)}}
    (s.out / "infant-prompt-rate.json").write_text(json.dumps(metrics, indent=2) + "\n")
    s.needs(baby["id"], "measurement-end")
    requests("parents-final-requests")
    s.rows("SELECT * FROM experience", "parents-experiences")
    if not s.baseline:
        cry = s.rows(f"SELECT * FROM infant_cry WHERE infant = {baby['id']}", "cry-state")
        s.expect("only parents receive crying deliberations", set(initial) == {a, b}, metrics)
        s.expect("same-cause pending cry is never re-triggered", sum(e["actor"] == b for e in events) == 1, metrics)
        a_events = [e for e in events if e["actor"] == a]
        gaps = [(r["at_ms"]-l["at_ms"])/1000 for l,r in zip(a_events,a_events[1:])]
        s.expect("answered parent receives 120-second reminders", len(gaps) >= 1 and all(120 <= gap <= 128 for gap in gaps), gaps)
        s.expect("due reminder merges into the unrelated pending request", unrelated is not None and any(
            e["kind"] == "merged" and e["request"]["requested_ms"] == unrelated["requested_ms"]
            and unrelated_reason in e["request"]["reason"] for e in a_events), a_events)
        s.expect("cry cause stays unchanged for over 120 seconds", bool(cry) and cry[0]["needs"] == [[0, []]] and finish - start > 120_000, cry)
        s.expect("caring witness receives experience without deliberation", bool(s.told(witness, "crying", "signal")) and witness not in initial)

    # Parents and witness leave hearing; two eligible carers remain at different distances.
    for actor in (a, b, witness):
        s.call("place_near", actor, warm_anchor)
    for d in requests():
        clear(d)
    s.call("place_near", carers[0], baby["id"])
    s.call("place_near", carers[1], carers[0])
    positions = {r["id"]: r for r in s.rows("SELECT * FROM body", "fallback-positions")}
    def distance(actor):
        return math.hypot(positions[actor]["x"] - positions[baby["id"]]["x"], positions[actor]["y"] - positions[baby["id"]]["y"])
    s.expect("parents leave hearing and carers have unequal nearby distances", all(distance(p) > 12 for p in (a, b, witness))
             and distance(carers[0]) < distance(carers[1]) <= 12, {str(p): distance(p) for p in (a, b, witness, *carers)})
    # The cry names the baby only to one who knows its name (fix-kill-name: every told line
    # names others as the teller perceives them); a fallback carer may know it only as "a baby".
    cried = lambda r: "crying" in r and (baby["name"] in r or "a baby" in r.lower())
    fallback = s.wait(lambda: [d for d in requests() if cried(d["reason"])], seconds=55)
    time.sleep(3)
    fallback = [d for d in requests("fallback-requests") if cried(d["reason"])]
    if not s.baseline:
        s.expect("exactly the nearest caring adult receives fallback", {d["actor"] for d in fallback} == {carers[0]}, fallback)
    s.rows("SELECT * FROM experience", "fallback-experiences")


def skirmish(s):
    """Graph-driven fighters use the starter skills through the same rules as players
    (docs/COMBAT.md): two sides of 10, strike in reach, bow shots at range, block or dodge when
    threatened, heal when hurt. Asserts accepted uses from graphs, missiles that struck, the
    timing gate (cooldowns), fighter bands, and deaths through the ordinary death rule."""
    before = {c["id"] for c in s.rows("SELECT id FROM character")}
    t0 = int(time.time() * 1000)
    s.call("spawn_skirmish", 20, 16.0)
    made = [c["id"] for c in s.rows("SELECT id, name FROM character") if c["id"] not in before]
    s.expect("skirmish fighters created", len(made) == 20, made)
    def uses():
        return s.rows("SELECT * FROM skill_use")
    s.wait(lambda: len([u for u in uses() if u["actor"] in made and u["accepted_ms"] > 0]) >= 30, seconds=60, every=2)
    time.sleep(20)
    u = [x for x in s.rows("SELECT * FROM skill_use", "uses") if x["actor"] in made]
    by = {}
    for x in u:
        by.setdefault(x["skill"], []).append(x)
    s.expect("graphs use the starter skills", {"strike", "bowshot"} <= set(by) and len(set(by) & {"block", "dodge", "heal"}) >= 1,
             {k: len(v) for k, v in by.items()})
    s.expect("graph uses are recorded from acceptance, source graph", all(x["source"] == "graph" and x["accepted_ms"] >= t0 for x in u), len(u))
    struck = [x for x in by.get("bowshot", []) if x["outcome"].startswith("struck")]
    s.expect("arrows fly and strike bodies on their path", len(struck) >= 1, [x["outcome"] for x in by.get("bowshot", [])][:6])
    # Cooldowns hold for graphs too: no two accepted uses of a skill by one actor closer than its cooldown.
    cards = {c["skill"]: c["cooldown_ms"] for c in s.rows("SELECT * FROM skill_card", "cards")}
    tight = []
    for actor in made:
        for skill, cd in cards.items():
            ts = sorted(x["accepted_ms"] for x in u if x["actor"] == actor and x["skill"] == skill and x["accepted_ms"])
            tight += [(actor, skill, b - a) for a, b in zip(ts, ts[1:]) if b - a < cd]
    s.expect("cooldowns hold for graph-driven fighters", not tight, tight[:5])
    f = s.rows("SELECT * FROM fighter", "fighters")
    s.expect("fighters show a health band", any(x["id"] in made and x["band"] < 4 for x in f), [(x["id"], x["band"]) for x in f if x["id"] in made][:8])
    s.wait(lambda: any(not c["alive"] for c in s.rows("SELECT id, alive FROM character") if c["id"] in made), seconds=120, every=3)
    dead = [c for c in s.rows("SELECT id, alive, cause FROM character", "after") if c["id"] in made and not c["alive"]]
    s.expect("skirmish deaths through the death rule", dead and all(c["cause"].startswith("killed by") for c in dead), [c["cause"] for c in dead][:5])
    gone = {c["id"] for c in dead}
    s.expect("the dead leave no fighter or readiness rows", not [x for x in s.rows("SELECT id FROM fighter") + s.rows("SELECT id FROM readiness") if x["id"] in gone])


def wall_geometry(s):
    """Tile centres on this world's own map: an `eye` tile, a `hidden` one at most 4 tiles away
    on one axis with only rock or wall between (within even night sight), and an `open` one
    3 tiles the other way with open ground between."""
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
    at = lambda x, y: tiles[y * W + x] if 0 <= x < W and 0 <= y < H else 4
    walk = lambda x, y: at(x, y) not in (2, 4, 7, 8, 9)
    for y in range(4, H - 4):
        for x in range(4, W - 4):
            if not walk(x, y):
                continue
            for dx, dy in [(1, 0), (0, 1)]:
                for gap in (1, 2, 3):
                    bx, by = x + (gap + 1) * dx, y + (gap + 1) * dy
                    if walk(bx, by) and all(at(x + i * dx, y + i * dy) in (4, 7) for i in range(1, gap + 1)) \
                            and all(walk(x - i * dx, y - i * dy) for i in range(1, 4)):
                        return {"eye": (x + .5, y + .5), "hidden": (bx + .5, by + .5), "open": (x - 3 * dx + .5, y - 3 * dy + .5)}
    raise RuntimeError("no wall geometry on this map")


def sight(s):
    """Minds and behaviour graphs see by the players' rule (docs/PERCEPTION.md, "Minds see what
    their character sees"): sight and a clear sight line. A fight at one spot is watched by a
    resident in the open and one behind rock or a wall, both within sight: the open one's
    graph sees the attacker and waves at it, and it witnesses the fight; the hidden one does
    neither. Admin `place_at` and `set_behavior` set the scene."""
    spots = wall_geometry(s)
    (s.out / f"{s.name}-spots.json").write_text(json.dumps(spots, indent=2) + "\n")
    attacker, victim, open_eye, hidden_eye = s.people(4)
    fight = spots["eye"]
    s.call("place_at", attacker, fight[0], fight[1])
    s.call("place_at", victim, fight[0] + 0.0, fight[1] + 0.0)
    s.call("place_at", open_eye, *spots["open"])
    s.call("place_at", hidden_eye, *spots["hidden"])
    watch = lambda: {"first": {"label": "watch", "children": [
        {"if": {"cond": {"sees": {"id": attacker}}, "then": {"do": {"skill": "wave", "target": {"id": attacker}}}}},
        {"wait": 3}]}}
    t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.graph(open_eye, watch())
    s.graph(hidden_eye, watch())
    s.graph(attacker, {"do": {"skill": "attack", "target": {"id": victim}}})
    time.sleep(8)
    uses = [u for u in s.rows("SELECT * FROM skill_use", "uses") if u["at_ms"] >= t0 and u["skill"] == "wave"]
    s.expect("a graph in the open sees the attacker (waves at it)", any(u["actor"] == open_eye and u["target"] == attacker for u in uses), uses)
    s.expect("a graph behind rock or a wall does not see it", not any(u["actor"] == hidden_eye for u in uses), uses)
    fights = {e: [r for r in s.rows(f"SELECT * FROM experience WHERE observer = {e}", f"experience-{e}") if r["kind"] == "fight" and r["at_ms"] >= t0] for e in (open_eye, hidden_eye)}
    s.expect("the resident in the open witnesses the fight", fights[open_eye], fights[open_eye][:2])
    s.expect("the resident behind the wall does not", not fights[hidden_eye], fights[hidden_eye][:2])
    attacked = s.rows(f"SELECT * FROM chronicle WHERE kind = 'attack' AND a = {attacker}", "attack-story")
    s.expect("the fight happened (chronicle)", attacked, attacked[:1])



def drop_geometry(s, cls=8):
    """On this world's own map: an `eye` tile and an `across` one on one axis with only tiles of
    class `cls` (8 a drop, 9 a low thing; 1 to 3 of them) between and walkable ground behind each
    for 3 tiles, away from the obstacle's ends (it runs on across the line for 2 tiles each way, 1
    for a low thing), so the way round is not a step past its end. Returns the spots and a tile
    lookup."""
    w = s.rows("SELECT width, height FROM world")[0]
    W, H = w["width"], w["height"]
    tiles = bytearray([4]) * (W * H)
    for row in s.rows("SELECT * FROM terrain_chunk"):
        data = row["tiles"]
        data = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
        cx, cy = row["id"] & 0xFFFF, row["id"] >> 16
        for k, t in enumerate(data):
            x, y = cx * 16 + k % 16, cy * 16 + k // 16
            if x < W and y < H:
                tiles[y * W + x] = t
    at = lambda x, y: tiles[y * W + x] if 0 <= x < W and 0 <= y < H else 4
    walk = lambda x, y: at(x, y) not in (2, 4, 7, 8, 9)
    for y in range(4, H - 4):
        for x in range(4, W - 4):
            if at(x, y) != cls:
                continue
            ext = 2 if cls == 8 else 1
            for dx, dy in [(1, 0), (0, 1)]:
                if not walk(x - dx, y - dy) or not all(at(x + k * dy, y + k * dx) == cls for k in range(-ext, ext + 1)):
                    continue
                for gap in (1, 2, 3):
                    bx, by = x + gap * dx, y + gap * dy
                    if walk(bx, by) and all(at(x + i * dx, y + i * dy) == cls for i in range(gap)) \
                            and all(walk(x - i * dx, y - i * dy) and walk(bx + i * dx, by + i * dy) for i in range(1, 4)):
                        return {"eye": (x - 2 * dx + .5, y - 2 * dy + .5), "across": (bx + 2 * dx + .5, by + 2 * dy + .5), "drop": [(x + i * dx, y + i * dy) for i in range(gap)]}, at
    raise RuntimeError(f"no {'drop' if cls == 8 else 'low'} geometry on this map")


def drop(s):
    """A drop between two ground levels (tile 8, `Terrain::Drop`) blocks the foot, not the eye
    (docs/PERCEPTION.md). A fight on one side is watched from the other: the watcher's graph sees
    the attacker and waves at it, and it witnesses the fight. Then a person on the far side is
    sent (`goto`) to the fight's spot: its body never stands on a drop tile, and the route the
    authority keeps for it (`body.path`, from where it is) never crosses one; it goes round (by a
    stair or the drop's end) or is refused. On a world with
    drops (`--seed plan-test` or `island`). Admin `place_at` and `set_behavior` set the scene.
    As the `low` scene the same is driven over low tiles (9: a cart, an open stall, a well, a
    building's overhang: open at eye height, `LandParams.sight` and the table's `eye_cells`) on
    an `island` run."""
    what = "drop" if s.name == "drop" else "low thing"
    spots, at = drop_geometry(s, 8 if s.name == "drop" else 9)
    (s.out / f"{s.name}-spots.json").write_text(json.dumps(spots, indent=2) + "\n")
    attacker, victim, watcher, walker = s.people(4)
    fight = spots["eye"]
    s.call("place_at", attacker, *fight)
    s.call("place_at", victim, *fight)
    s.call("place_at", watcher, *spots["across"])
    s.call("place_at", walker, spots["across"][0] + 1.0, spots["across"][1])
    t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.graph(watcher, {"first": {"label": "watch", "children": [
        {"if": {"cond": {"sees": {"id": attacker}}, "then": {"do": {"skill": "wave", "target": {"id": attacker}}}}},
        {"wait": 3}]}})
    s.graph(attacker, {"do": {"skill": "attack", "target": {"id": victim}}})
    time.sleep(8)
    uses = [u for u in s.rows("SELECT * FROM skill_use", "uses") if u["at_ms"] >= t0 and u["skill"] == "wave"]
    s.expect(f"a graph across the {what} sees the attacker (waves at it)", any(u["actor"] == watcher and u["target"] == attacker for u in uses), uses, fatal=False)
    fights = [r for r in s.rows(f"SELECT * FROM experience WHERE observer = {watcher}", "experience-watcher") if r["kind"] == "fight" and r["at_ms"] >= t0]
    s.expect(f"the resident across the {what} witnesses the fight", fights, fights[:2], fatal=False)
    s.expect("the fight happened (chronicle)", s.rows(f"SELECT * FROM chronicle WHERE kind = 'attack' AND a = {attacker}", "attack-story"))
    s.graph(attacker, {"wait": 120})
    # The walker is sent across: steering and routing keep it off the drop.
    start = body_at(s, walker)
    s.graph(walker, {"seq": [{"do": {"skill": "goto", "target": {"at": list(fight)}}}, {"wait": 300}]})
    pts, routes = [], []
    end = time.monotonic() + 12
    while time.monotonic() < end:
        row = s.rows(f"SELECT x, y, t_ms, vx, vy, next_ms, path FROM body WHERE id = {walker}")[0]
        here = body_at(s, walker, row=row)
        pts.append(here)
        corners = [(w["x"], w["y"]) if isinstance(w, dict) else (w[0], w[1]) for w in row["path"]]
        routes.append([here] + corners)
        time.sleep(0.25)
    is_blocked = lambda q: at(math.floor(q[0]), math.floor(q[1])) in (2, 4, 7, 8, 9)
    blocked = [q for q in pts if is_blocked(q)]
    # The route ahead, walked in 0.1 m steps: no leg crosses a blocked tile.
    def crosses(a, b):
        n = max(1, math.ceil(math.dist(a, b) / 0.1))
        return any(is_blocked((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)) for i in range(n + 1))
    jumps = [(r[i], r[i + 1]) for r in routes for i in range(len(r) - 1) if crosses(r[i], r[i + 1])]
    goto = [u for u in s.rows(f"SELECT * FROM skill_use WHERE actor = {walker}", "walker-uses") if u["skill"] == "goto" and u["at_ms"] >= t0]
    (s.out / f"{s.name}-walk.json").write_text(json.dumps({"start": start, "trail": pts, "routes": routes, "uses": goto}, indent=1) + "\n")
    s.expect(f"a walk across the {what} never stands on it, and its route never crosses it", pts and not blocked and not jumps,
             {"start": start, "end": pts[-1] if pts else None, "walked_m": round(sum(math.dist(a, b) for a, b in zip(pts, pts[1:])), 1), "goto": [u["outcome"] for u in goto][-1:], "route_corners": max((len(r) - 1 for r in routes), default=0), "blocked": blocked[:5], "crossing_legs": jumps[:3]})


def open_line(s, length=16, avoid=()):
    """A row of `length` walkable tiles on this world's map, west to east, with nothing that
    blocks sight on it: the tile centres from its west end. With `avoid`, the row starts more
    than 10 m from each of those points."""
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
    walk = lambda x, y: 0 <= x < W and 0 <= y < H and tiles[y * W + x] not in (2, 4, 7, 8, 9)
    for y in range(8, H - 8, 3):
        for x in range(8, W - length - 8, 2):
            if all(walk(x + i, y + d) for i in range(length) for d in (-1, 0, 1)) and all(math.dist((x + .5, y + .5), q) > 10 for q in avoid):
                return [(x + i + .5, y + .5) for i in range(length)]
    raise RuntimeError("no open line on this map")


def world_hour(s):
    w = s.rows("SELECT epoch_ms, day_ms FROM world")[0]
    now = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    day = w["day_ms"]
    return ((now - w["epoch_ms"] + day * 7 // 24) % day) / day * 24, day


def senses(s):
    """Sight and hearing are the script's `senses(a)` law per creature (docs/WORLD_RULES.md,
    "Laws"): by day one sees 11 m, at night 6, with a torch 9; speech carries 9 m. Watchers
    stand 5, 8, 10 and 13 m from a subject on an open line; each one's graph faces the subject
    when it `sees` it. Then installed overlays change the law, as a floor or a passive would:
    day sight 14 m (and its reach with it), and a world where it is always dark for the eyes,
    where a torch in the pack is the difference at 8 m. Hearing: the subject speaks; listeners
    at 8 and 10 m, then with hearing 12. The shipped script is installed again at the end."""
    line = open_line(s)
    (s.out / f"{s.name}-line.json").write_text(json.dumps(line) + "\n")
    subject, *watchers = s.people(5)
    for w in watchers:
        s.graph(w, {"wait": 1})
    dists = [5, 8, 10, 13]
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()

    def overlay(**fns):
        src = shipped
        for name in fns:
            src = src.replace(f"fn {name}(", f"fn base_{name}(", 1)
        return src + "\n" + "\n".join(fns.values()) + "\n"

    def place():
        s.call("place_at", subject, *line[0])
        for w, d in zip(watchers, dists):
            s.call("place_at", w, *line[d])

    def seen(label, want):
        place()
        s.graph(subject, {"wait": 300})
        t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
        # A watcher that sees the subject faces it, then turns away (east), so the next look is a
        # real turn again ("you already face it" refuses a turn to where one faces).
        for w, d in zip(watchers, dists):
            away = {"do": {"skill": "face", "target": {"at": [line[d][0] + 4.0, line[d][1]]}}}
            s.graph(w, {"first": {"label": "watch", "children": [
                {"seq": [{"if": {"cond": {"sees": {"id": subject}}, "then": {"do": {"skill": "face", "target": {"id": subject}}}}}, away]},
                away,
                {"wait": 2}]}})
        # Graphs start at each body's own evaluation slot: wait until the expected watchers have
        # faced the subject (at most 30 s), then 4 s more for any that should not.
        def faced():
            uses = [u for u in s.rows("SELECT * FROM skill_use", f"uses-{label}") if u["at_ms"] >= t0 and u["skill"] == "face" and u["target"] == subject]
            return sorted(d for w, d in zip(watchers, dists) if any(u["actor"] == w for u in uses))
        end = time.monotonic() + 30
        while time.monotonic() < end and not set(want) <= set(faced()):
            time.sleep(1)
        time.sleep(4)
        got = faced()
        # Short waits between phases: a body in a long wait is looked at again only when it ends.
        for w in watchers:
            s.graph(w, {"wait": 1})
        return got

    def heard(label):
        place()
        t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
        s.graph(subject, {"seq": [{"say": f"Can you hear me? ({label})"}, {"wait": 300}]})
        time.sleep(4)
        got = []
        for w, d in zip(watchers, dists):
            rows = [r for r in s.rows(f"SELECT * FROM experience WHERE observer = {w}") if r["kind"] == "speech" and r["at_ms"] >= t0]
            if rows:
                got.append(d)
        s.graph(subject, {"wait": 300})
        return got

    def light():
        hour, day = world_hour(s)
        # Keep a margin of 25 s of world time from dusk and dawn.
        margin = 25_000 / day * 24
        if any(abs(hour - b) < margin for b in (6.0, 20.0)):
            time.sleep(30)
            hour, day = world_hour(s)
        return "night" if not 6.0 <= hour < 20.0 else "day"

    try:
        now = light()
        want = [5, 8, 10] if now == "day" else [5]
        got = seen("shipped", want)
        s.expect(f"shipped law ({now}): seen within {11 if now == 'day' else 6} m", got == want, {"seen": got, "want": want, "light": now})
        got = heard("shipped")
        s.expect("shipped law: speech heard within 9 m", got == [5, 8], got)

        s.call("install_script", overlay(sight_in='fn sight_in(light) { if light == "day" { 14.0 } else { base_sight_in(light) } }',
                                         hearing_of_people="fn hearing_of_people() { 12.0 }"))
        now = light()
        want = [5, 8, 10, 13] if now == "day" else [5]
        got = seen("day14", want)
        s.expect(f"an installed law changes sight, and its reach with it ({now})", got == want, {"seen": got, "want": want, "light": now})
        got = heard("hear12")
        s.expect("an installed law changes hearing: 10 m heard at 12", got == [5, 8, 10], got)

        s.call("install_script", overlay(light_of='fn light_of(a) { if inv(a, "torch") > 0 { "torch" } else { "night" } }'))
        got = seen("dark", [5])
        s.expect("always dark for the eyes: seen within 6 m", got == [5], got)
        s.call("grant_items", watchers[1], "torch", 1)
        s.call("grant_items", watchers[2], "torch", 1)
        got = seen("torch", [5, 8])
        s.expect("a torch in the pack: 8 m seen, 10 m not (9 m with a torch)", got == [5, 8], got)
    finally:
        s.call("install_script", shipped)


def set_law(s, name, value, check=True):
    """Change a law on the running world (`set_world_law`, admin)."""
    return s.call("set_world_law", name, json.dumps(value), check=check)


def fov(s):
    """Sight that depends on facing (docs/PERCEPTION.md, "The field of view"), switched by the
    world's `fov_on` law through `set_world_law` on a running world. A watcher stands on an open
    line facing east with someone 5 m ahead, 5 m behind and 1.5 m behind; its graph turns where it
    is told and says whom it `sees`. Off (as shipped): all three, as before. On: ahead and the one
    within the near ring, not the one behind; facing west, the reverse. Off again: all three.
    Every change is in `law_change` and the chronicle, and the installed script carries the
    values. Then a duel from behind: a strike from the one behind at the watcher facing away,
    whose graph guards when `threatened`. With the field on and the starting near ring (3 m, 2 m in
    the dark) the striker 1 m behind is within the ring, seen, and guarded against; with a near
    ring of 0.5 m (`set_world_law fov_near_m`, `fov_near_dark_m`) the windup is not seen, there is
    no guard, and the blow lands (a backstab). Off, it guards as before. Two onlookers 4 m off face
    toward the duel and away from it (4 and 5 m off on the line): with the field on only the one
    facing it witnesses it."""
    line = open_line(s)
    (s.out / f"{s.name}-line.json").write_text(json.dumps(line) + "\n")
    eye, ahead, behind, close, w_toward, w_away = s.people(6)
    e = line[7]
    places = {eye: e, ahead: line[12], behind: line[2], close: (e[0] - 1.5, e[1])}
    names = {ahead: "ahead", behind: "behind", close: "close"}
    rounds = iter(range(1000))

    def place():
        for c, p in places.items():
            s.call("place_at", c, p[0], p[1])

    def probe(label, way):
        """The watcher turns to face `way` (+1 east, -1 west), then says whom it sees."""
        place()
        tag = f"{label}-{next(rounds)}"
        t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
        # One line every 2 s at most (speaking faster is refused).
        tell = [x for c, n in names.items() for x in ({"if": {"cond": {"sees": {"id": c}}, "then": {"say": f"{tag} sees {n}"}, "else": {"say": f"{tag} not {n}"}}}, {"wait": 2.2})]
        s.graph(eye, {"seq": [{"first": [{"do": {"skill": "face", "target": {"at": [e[0] + 4.0 * way, e[1]]}}}, {"wait": 0.1}]}, {"wait": 1.5}, *tell, {"wait": 300}]})

        def said():
            rows = [r for r in s.rows(f"SELECT * FROM chronicle WHERE kind = 'speech' AND a = {eye}") if r["at_ms"] >= t0 and tag in r["text"]]
            return rows if len(rows) >= len(names) else None
        rows = s.wait(said, seconds=40, every=1)
        (s.out / f"{s.name}-said-{tag}.json").write_text(json.dumps(rows, indent=2) + "\n")
        return {n: any(f"{tag} sees {n}" in r["text"] for r in rows) for n in names.values()}

    shipped = s.rows("SELECT revision FROM script WHERE name = 'skills'")[0]["revision"]
    try:
        got = probe("off", +1)
        s.expect("off (as shipped): seen all round, as before", got == {"ahead": True, "behind": True, "close": True}, got)
        r = set_law(s, "no_such_law", True, check=False)
        s.expect("set_world_law refuses a name that is no law", r.returncode != 0 and "not a law" in (r.stderr + r.stdout), (r.stderr + r.stdout)[-300:])
        r = set_law(s, "fov_on", 2, check=False)
        s.expect("set_world_law refuses a value of another kind", r.returncode != 0 and "true or false" in (r.stderr + r.stdout), (r.stderr + r.stdout)[-300:])
        set_law(s, "fov_on", True)
        script = s.rows("SELECT revision, source FROM script WHERE name = 'skills'")[0]
        s.expect("the installed script carries the world's law values, at a new revision",
                 script["revision"] > shipped and re.search(r"fn world_law_values\(\) \{ #\{[^}]*\bfov_on: true\b", script["source"]) is not None, script["revision"])
        changes = s.rows("SELECT * FROM law_change", "law-changes")
        s.expect("the change is recorded (name, old, new, when, who, revision)",
                 any(c["name"] == "fov_on" and c["old"] == "false" and c["new"] == "true" and c["at_ms"] > 0 and c["revision"] == script["revision"] for c in changes), changes)
        story = [r for r in s.rows("SELECT * FROM chronicle WHERE kind = 'law'", "law-story")]
        s.expect("and in the chronicle", any("fov_on changed from false to true" in r["text"] for r in story), story)
        got = probe("on-east", +1)
        s.expect("on, facing east: ahead and the near ring, not behind", got == {"ahead": True, "behind": False, "close": True}, got)
        got = probe("on-west", -1)
        s.expect("on, facing west: behind seen, ahead not", got == {"ahead": False, "behind": True, "close": True}, got)

        # A duel from behind. The watcher faces east; the one behind (1 m west) strikes it.
        last_blow = [-1000.0]

        def duel(label):
            places[behind] = (e[0] - 1.0, e[1])
            place()
            s.call("place_at", ahead, *line[15])
            # Onlookers on the open line east of the duel, 4 and 5 m off: one faces it (west),
            # one faces away (east).
            s.call("place_at", w_toward, *line[11])
            s.call("place_at", w_away, *line[12])
            for w, at in ((w_toward, line[7]), (w_away, line[15])):
                s.graph(w, {"seq": [{"first": [{"do": {"skill": "face", "target": {"at": [at[0], at[1]]}}}, {"wait": 0.1}]}, {"wait": 60 + next(rounds)}]})
            s.graph(eye, {"seq": [{"first": [{"do": {"skill": "face", "target": {"at": [e[0] + 4.0, e[1]]}}}, {"wait": 0.1}]}, {"wait": 300}]})
            time.sleep(2)
            # Then it guards whenever it is threatened (a graph runs again from its root).
            s.graph(eye, {"first": {"label": "guard", "children": [{"if": {"cond": {"threatened": True}, "then": {"do": {"skill": "block"}}}}, {"wait": 0.2}]}})
            time.sleep(3)
            # Witnesses are told a fight's first blow: one more than 30 s after the attacker last
            # hurt the victim (`act.rs` `first_blow`).
            time.sleep(max(0.0, 31.0 - (time.monotonic() - last_blow[0])))
            t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
            # The striker turns to where the watcher stands first: with a field it must see its
            # target to strike it (a target it cannot see does not resolve). A graph of its own
            # each time (the same graph again would not start over; a wait is held to 120 s).
            s.graph(behind, {"seq": [{"first": [{"do": {"skill": "face", "target": {"at": [e[0], e[1]]}}}, {"wait": 0.1}]},
                                     {"do": {"skill": "strike", "target": {"id": eye}}}, {"wait": 60 + next(rounds)}]})
            def struck():
                u = [x for x in s.rows("SELECT * FROM skill_use") if x["at_ms"] >= t0 and x["actor"] == behind and x["skill"] == "strike" and x["outcome"]]
                return u or None
            strikes = s.wait(struck, seconds=30, every=1)
            last_blow[0] = time.monotonic()
            # Short waits from now on, so the next round's graph is taken at once.
            s.graph(behind, {"wait": 1.0 + 0.01 * next(rounds)})
            # Onlookers' lines are folded (`witness_fold_ms`): told when each one's window ends.
            time.sleep(1 + law_value(s, "witness_fold_ms") / 1000)
            uses = [x for x in s.rows("SELECT * FROM skill_use", f"duel-uses-{label}") if x["at_ms"] >= t0]
            guards = [x for x in uses if x["actor"] == eye and x["skill"] in ("block", "dodge")]
            seen = {w: [r for r in s.rows(f"SELECT * FROM experience WHERE observer = {w}", f"duel-exp-{label}-{w}") if r["kind"] == "fight" and r["at_ms"] >= t0] for w in (w_toward, w_away)}
            return strikes, guards, seen

        # With the starting values the one striking from 1 m behind is within the near ring
        # (3 m all round, 2 m in the dark): seen, so the guard goes up.
        strikes, guards, seen = duel("on")
        s.expect("on (near ring 3 m, 2 m dark): a strike from 1 m behind is within the ring, seen, guarded", guards, [x["outcome"] for x in strikes])
        s.expect("on: the onlooker facing the duel witnesses it", seen[w_toward], seen[w_toward][:1])
        s.expect("on: the onlooker facing away does not", not seen[w_away], seen[w_away][:1])
        # A near ring under a strike's reach (a law value): the windup from behind is not seen,
        # no guard, and the blow lands: a backstab.
        set_law(s, "fov_near_m", 0.5)
        set_law(s, "fov_near_dark_m", 0.5)
        keep_behind = places[behind]
        places[behind] = line[2]
        got = probe("on-near", +1)
        s.expect("on (near ring 0.5 m, a law value): 1.5 m behind is not seen", got == {"ahead": True, "behind": False, "close": False}, got)
        places[behind] = keep_behind
        strikes, guards, seen = duel("on-near")
        s.expect("on (near ring 0.5 m): a windup from behind is not seen (no guard)", not guards, guards)
        s.expect("on (near ring 0.5 m): the blow from behind lands", any(x["outcome"].startswith("struck") or "hit" in x["outcome"] for x in strikes), [x["outcome"] for x in strikes])
        set_law(s, "fov_near_m", 3.0)
        set_law(s, "fov_near_dark_m", 2.0)

        set_law(s, "fov_on", False)
        places[behind] = line[2]
        got = probe("off-again", +1)
        s.expect("off again: seen all round, as before", got == {"ahead": True, "behind": True, "close": True}, got)
        strikes, guards, seen = duel("off")
        s.expect("off: the one struck from behind guards, as before", guards, [x["outcome"] for x in strikes])
        s.expect("off: both onlookers witness it, as before", seen[w_toward] and seen[w_away], {k: len(v) for k, v in seen.items()})
    finally:
        set_law(s, "fov_on", False, check=False)
        set_law(s, "fov_near_m", 3.0, check=False)
        set_law(s, "fov_near_dark_m", 2.0, check=False)
        # Off the shared open line: later scenes (doing) count who stands near its west end.
        for k, who in enumerate((eye, ahead, behind, close, w_toward, w_away)):
            s.call("place_at", who, line[0][0] + 60 + 2 * k, line[0][1] + 44, check=False)


def doing(s):
    """What one character perceives another doing, for AI bodies (docs/PERCEPTION.md, "Activity
    derived from the body"): its activity's label, unchanged by the derivation from the body,
    which applies only to a body moving under motion intent (a player's movement keys; no AI
    body steers that way), with a creature target named as O perceives it (first-sight-crowd).
    On an open line an observer O stands at the west end; W1 walks to O (goto), W2 walks in from
    10 m to a spot near O (goto a point), F follows S, S stands by. O's graph thinks (a `think`
    leaf), which writes O's deliberation scene: W1 reads "goto → you", F "follow → a stranger"
    (S, whose name O does not know), W2 its point, S wait, and none of their bodies steers by
    direction (`steer.goal` 3). About a minute: the observer can ask for a deliberation only 45 s
    after it arrives."""
    line = open_line(s)
    (s.out / f"{s.name}-line.json").write_text(json.dumps(line) + "\n")
    obs, w1, w2, f, st = s.people(5)
    born = time.monotonic()
    s.call("place_at", obs, *line[0])
    s.call("place_at", w1, *line[10])
    s.call("place_at", w2, line[10][0], line[10][1] + 1.0)
    s.call("place_at", f, line[9][0], line[9][1] - 1.0)
    s.call("place_at", st, line[4][0], line[4][1] + 1.0)
    # A `think` leaf asks only when the last deliberation is over 45 s old (`brain.rs`: a fresh
    # decision is not second-guessed), and newcomers count from their arrival.
    time.sleep(max(1.5, 47.0 - (time.monotonic() - born)))
    near = list(line[1])
    s.graph(w2, {"seq": [{"do": {"skill": "goto", "target": {"at": [near[0], near[1] + 1.0]}}}, {"wait": 300}]})
    s.graph(f, {"seq": [{"do": {"skill": "follow", "target": {"id": st}}}, {"wait": 300}]})
    s.graph(w1, {"seq": [{"do": {"skill": "goto", "target": {"id": obs}}}, {"wait": 300}]})
    stamp = lambda: next((d["updated_ms"] for d in s.rows(f"SELECT actor, updated_ms FROM deliberation WHERE actor = {obs}")), -1)
    before = stamp()
    s.call("set_behavior", obs, json.dumps({"seq": [{"think": "a look around"}, {"wait": 300}]}))
    row = s.wait(lambda: next((d for d in s.rows(f"SELECT * FROM deliberation WHERE actor = {obs}") if d["updated_ms"] > before), None), 15)
    acts = {a["id"]: a for a in s.rows("SELECT id, skill, label, phase FROM activity", "activities") if a["id"] in (w1, w2, f, st)}
    steer = s.rows("SELECT id, goal FROM steer", "steer")
    scene = json.loads(row["scene"])
    (s.out / f"{s.name}-scene.json").write_text(json.dumps(scene, indent=1, ensure_ascii=False) + "\n")
    seen = {c["id"]: c.get("doing") for c in scene.get("creatures", [])}
    named = {w1: "you", f: "a stranger"}
    want = {i: (a["label"].rsplit(" → ", 1)[0] + " → " + named[i]) if i in named and " → " in a["label"] else a["label"] for i, a in acts.items()}
    s.expect("the scene's doing is each AI body's activity, its creature target named as O perceives it", all(seen.get(i) == want[i] for i in acts if i in seen) and len(seen.keys() & acts.keys()) >= 3, {"seen": seen, "want": want, "labels": {i: a["label"] for i, a in acts.items()}})
    s.expect("a walk to a place reads goto → (x,y)", (seen.get(w2) or "").startswith("goto → ("), seen.get(w2))
    s.expect("a follow of someone O does not know reads follow → a stranger", seen.get(f) == "follow → a stranger", seen.get(f))
    s.expect("standing by reads wait", seen.get(st) == "wait", seen.get(st))
    s.expect("a walk to the observer reads goto → you", seen.get(w1) == "goto → you", {"seen": seen.get(w1), "activity": acts.get(w1)}, fatal=False)
    s.expect("no AI body steers by direction (motion intent)", not [r for r in steer if r["goal"] == 3 and r["id"] in (obs, w1, w2, f, st)], [r for r in steer if r["id"] in (w1, w2, f, st)])


def moves(s):
    """How a creature moves besides its walk is the script's `motion(a)` law: a flight at 1.15
    times the walk (`run: false`; a flight runs by default, at the `run_share` law), turning on the spot at
    6 rad/s. A person walks off (its cruising speed is its walk), then flees a second person
    (1.15 times that, then at a run), then turns to face someone behind it (the body row's turn rate). An installed overlay with a flight of 2 and turning at 3
    shows both changed; the shipped script is installed again at the end."""
    line = open_line(s)
    a, b = s.people(2)
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()

    def body(label):
        return s.rows(f"SELECT * FROM body WHERE id = {a}", label)[0]

    def measure(label):
        s.call("place_at", a, *line[3])
        s.call("place_at", b, *line[0])
        time.sleep(1)
        s.graph(a, {"seq": [{"do": {"skill": "goto", "target": {"at": [line[15][0], line[15][1]]}}}, {"wait": 300}]})
        time.sleep(1.5)
        walk = body(f"{label}-walk")["speed"]
        s.call("place_at", a, *line[3])
        s.graph(a, {"seq": [{"do": {"skill": "flee", "target": {"id": b}, "run": False}}, {"wait": 300}]})
        time.sleep(1.5)
        flee = body(f"{label}-flee")["speed"]
        # A flight runs by default (breath permitting, docs/STAMINA.md): the run's share.
        s.graph(a, {"wait": 300})
        time.sleep(1.0)
        s.call("place_at", a, *line[3])
        s.graph(a, {"seq": [{"do": {"skill": "flee", "target": {"id": b}}}, {"wait": 300}]})
        time.sleep(1.5)
        fled = body(f"{label}-flee-run")["speed"]
        s.graph(a, {"wait": 300})
        time.sleep(2.5)
        h = body(f"{label}-stand")["heading"]
        here = body_at(s, a)
        s.call("place_at", b, here[0] - 3 * math.cos(h), here[1] - 3 * math.sin(h))
        time.sleep(0.5)
        s.graph(a, {"seq": [{"do": {"skill": "face", "target": {"id": b}}}, {"wait": 300}]})
        time.sleep(2)
        turn = abs(body(f"{label}-face")["turn"])
        return {"walk": walk, "flee": flee, "ratio": round(flee / walk, 3) if walk else None, "run_ratio": round(fled / walk, 3) if walk else None, "turn": round(turn, 3)}

    try:
        got = measure("shipped")
        s.expect("shipped law: a flight that does not run is 1.15 times the walk", got["ratio"] and abs(got["ratio"] - 1.15) < 0.02, got)
        share = law_value(s, "run_share")
        s.expect("a flight runs by default, at the run_share law times the walk", got["run_ratio"] and abs(got["run_ratio"] - share) < 0.02, {**got, "run_share": share})
        s.expect("shipped law: turning on the spot at 6 rad/s", abs(got["turn"] - 6.0) < 0.01, got)
        src = shipped.replace("fn motion(a)", "fn base_motion(a)", 1) + "\nfn motion(a) { let m = base_motion(a); m.flee = 2.0; m.turn_rate = 3.0; m }\n"
        s.call("install_script", src)
        got = measure("overlay")
        s.expect("an installed law changes the flight: 2 times the walk", got["ratio"] and abs(got["ratio"] - 2.0) < 0.03, got)
        s.expect("an installed law changes turning: 3 rad/s", abs(got["turn"] - 3.0) < 0.01, got)
    finally:
        s.call("install_script", shipped)


def law_value(s, name):
    """A world law in force: the world's own value (`world_law`, set with `set_world_law`), else
    the installed script's `laws()` number."""
    def val(v):
        v = str(v).strip().strip('"')
        return {"true": True, "false": False}[v] if v in ("true", "false") else float(v)
    own = [r for r in s.rows("SELECT * FROM world_law") if r["name"] == name]
    if own:
        return val(own[0]["value"])
    src = s.rows("SELECT source FROM script WHERE name = 'skills'")[0]["source"]
    # A world's own values block (`world_law_values`, a seed's `laws`) comes before laws().
    m = re.search(r"\b" + name + r": (true|false|[0-9.]+)", src)
    return val(m.group(1))


def body_at(s, actor, now=None, row=None):
    """A body's position now, from its segment (straight-line; turns are short)."""
    b = row or s.rows(f"SELECT x, y, t_ms, vx, vy, next_ms FROM body WHERE id = {actor}")[0]
    now = now or s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    t = max(0, min(now, b["next_ms"]) - b["t_ms"]) / 1000
    return (b["x"] + b["vx"] * t, b["y"] + b["vy"] * t)


def apart(s, a, b):
    """Distance between two bodies at one moment (one query for both and the clock)."""
    rows = s.rows(f"SELECT id, x, y, t_ms, vx, vy, next_ms FROM body WHERE id = {a} OR id = {b}")
    now = max(r["t_ms"] for r in rows)
    now = max(now, s.rows("SELECT last_ms FROM clock")[0]["last_ms"])
    at = {r["id"]: body_at(s, r["id"], now, r) for r in rows}
    return round(math.dist(at[a], at[b]), 2)


def breath_now(v, now):
    """A pool's level now from the vitals row (living_rules::pools::level): `stamina` anchored at
    `at_ms`, changing by `stamina_rate` a second from `max(at_ms, stamina_from_ms)`."""
    def level(pool):
        start = max(v["at_ms"], v[pool + "_from_ms"])
        return max(0.0, min(v[pool] + v[pool + "_rate"] * max(0, now - start) / 1000, v[pool + "_max"]))
    return level("stamina"), level("focus")


def stamina(s):
    """Breath and focus (docs/STAMINA.md) through the authority, for graph-driven bodies, with the
    shipped laws and world laws changed on the running world (`set_world_law`). A person's run is
    the `run_share` law times its walk and drains breath (the vitals row's rate, written once when the run starts);
    when breath runs out the body walks (the row says the refill starts a second later) and runs
    again at 30; a body standing refills with no row written; a dodge takes 20 breath and no
    tiredness worth the name; too little breath refuses it ("out of breath"); fire takes mana and
    the fourth bolt in 12 s is refused ("not enough mana"); a held guard drains 4 a second and
    drops; tiredness caps breath (75 at energy 17.5); a wolf charges at 1.5 times its walk and a
    deer flees at a run; `walk_base` changes the walk."""
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    law = lambda name, value: s.call("set_world_law", name, json.dumps(value))
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    line = open_line(s, length=64)
    a, b = s.people(2)
    s.call("place_at", b, line[0][0], line[0][1] + 30)
    try:
        # The walk: the body's cruising speed walking to the far end, then at a run.
        s.call("place_at", a, *line[0])
        time.sleep(0.5)
        s.graph(a, {"seq": [{"do": {"skill": "goto", "target": {"at": list(line[-1])}}}, {"wait": 300}]})
        time.sleep(1.0)
        walk = s.rows(f"SELECT speed FROM body WHERE id = {a}", "walk")[0]["speed"]
        s.graph(a, {"wait": 300})
        time.sleep(4)
        # A drain that empties in about 7 s instead of 25 (a world law changed on the running
        # world), so the 64 m line holds a run to empty, its walk and a second run of about 2 s
        # even for a fast runner (genes: 5.5 m/s at run 1.65); at 10 one reached the line's end
        # 0.45 s into the second run and the sampled rows missed its drain.
        law("stamina_run", 14.0)
        s.call("place_at", a, *line[0])
        time.sleep(3)
        v0 = s.vitals(a, "before-run")
        s.expect("a body standing has its breath full and no drain", abs(breath_now(v0, now())[0] - v0["stamina_max"]) < 0.5 and v0["stamina_rate"] >= 0, v0)
        s.graph(a, {"seq": [{"do": {"skill": "goto", "target": {"at": list(line[-1])}, "run": True}}, {"wait": 300}]})
        samples = []
        end = time.monotonic() + 20
        while time.monotonic() < end:
            rows = s.rows(f"SELECT * FROM body WHERE id = {a}")
            v = s.vitals(a)
            samples.append({"t": now(), "speed": rows[0]["speed"], "vx": rows[0]["vx"], "vy": rows[0]["vy"], "running": rows[0]["running"], "vitals": v})
            if rows[0]["vx"] == 0 and rows[0]["vy"] == 0 and len(samples) > 5:
                break
            time.sleep(0.25)
        (s.out / f"{s.name}-run-samples.json").write_text(json.dumps(samples, indent=1) + "\n")
        speeds = [x["speed"] for x in samples]
        run = max(speeds)
        share = law_value(s, "run_share")
        s.expect("a person runs the run_share law times its walk", walk and abs(run / walk - share) < 0.02, {"walk": walk, "run": run, "run_share": share})
        draining = [x for x in samples if x["vitals"]["stamina_rate"] < 0]
        s.expect("the run drains breath at the law's rate, from the row's anchor", draining and all(abs(x["vitals"]["stamina_rate"] + 14.0) < 1e-3 and x["vitals"]["stamina_from_ms"] == x["vitals"]["at_ms"] for x in draining), draining[:1])
        winded = [i for i, x in enumerate(samples) if i and samples[i - 1]["speed"] > walk * 1.5 and abs(x["speed"] - walk) < 0.05]
        s.expect("out of breath, the run becomes a walk", winded, speeds)
        w = samples[winded[0]]["vitals"]
        s.expect("the row says breath comes back a second after it ran out, at 25 a second", abs(w["stamina"]) < 0.5 and abs(w["stamina_rate"] - 25.0) < 1e-3 and 0 < w["stamina_from_ms"] - w["at_ms"] <= 1000, w)
        # Timed by the rows themselves (the samples come about a second apart): the drain starts
        # again, from 30, 2.2 s after the row said breath ran out.
        resumed = [x["vitals"] for i, x in enumerate(samples) if i > winded[0] and x["vitals"]["stamina_rate"] < 0]
        again = [i for i, x in enumerate(samples) if i > winded[0] and x["speed"] > walk * 1.5]
        s.expect("it runs again once it has 30 breath back, 2.2 s after it ran out", resumed and again and abs(resumed[0]["stamina"] - 30.0) < 0.6 and 2100 <= resumed[0]["at_ms"] - w["at_ms"] <= 2400,
                 {"winded_row": w["at_ms"], "resumed_row": resumed[0] if resumed else None, "running_again_sample": samples[again[0]]["t"] if again else None})
        # `body.running` (what a client draws): true at the run's speed, false walking out of breath.
        fast = [x for x in samples if x["speed"] > walk * 1.5 and (x["vx"] or x["vy"])]
        slow = [x for x in samples if abs(x["speed"] - walk) < 0.05 and (x["vx"] or x["vy"])]
        s.expect("body.running says running at a run and walking out of breath", fast and slow and all(x["running"] for x in fast) and not any(x["running"] for x in slow),
                 {"running_at_run": [x["running"] for x in fast], "running_walking": [x["running"] for x in slow]})
        writes = sorted({x["vitals"]["at_ms"] for x in samples})
        s.expect("the row is written at the run's edges only, not every tick", len(writes) <= 8, writes)
        s.wait(lambda: s.rows(f"SELECT vx, vy FROM body WHERE id = {a}")[0]["vx"] == 0, seconds=20)
        law("stamina_run", 4.0)
        time.sleep(1.5)
        # Refill without writes: the row stays as it is while breath comes back.
        r0 = s.vitals(a, "refill-0")
        time.sleep(3)
        r1 = s.vitals(a, "refill-1")
        s.expect("standing, breath comes back with no row written", r0 == r1 and breath_now(r1, now())[0] > breath_now(r0, r0["at_ms"])[0] - 0.01 and r1["stamina_rate"] > 0, {"row": r1, "now": breath_now(r1, now())})
        e_spent = v0["energy"] - s.needs(a, "after-run")["energy"]
        s.expect("breath spent tires a little (0.02 a point), not by itself much", 0.5 < e_spent < 6.0, {"energy_spent": e_spent})
        # A dodge: 20 breath, its refill a second after.
        time.sleep(5)
        n0 = s.needs(a, "before-dodge")
        s.graph(a, {"seq": [{"do": "dodge"}, {"wait": 300}]})
        d = s.wait(lambda: next((v for v in [s.vitals(a)] if v["stamina_rate"] > 0 and v["stamina"] < v["stamina_max"] - 10), None), seconds=10, every=0.2)
        s.expect("a dodge takes 20 breath; it comes back from a second later", abs(d["stamina_max"] - d["stamina"] - 20.0) < 0.6 and 0 < d["stamina_from_ms"] - d["at_ms"] <= 1000, d)
        n1 = s.needs(a, "after-dodge")
        s.expect("a dodge costs no tiredness but its spillover", n0["energy"] - n1["energy"] < 0.6, {"before": n0["energy"], "after": n1["energy"]})
        # Too little breath: a world where breath holds 15 refuses a dodge (20), not a jump (10).
        law("stamina_max", 15.0)
        c, = s.people(1)
        cv = s.vitals(c, "small-breath")
        s.expect("a body comes into the world with its breath at the law's cap", abs(cv["stamina"] - 15.0) < 0.01 and cv["stamina_max"] == 15.0, cv)
        t0 = now()
        s.graph(c, {"seq": [{"do": "dodge"}, {"wait": 300}]})
        s.wait(lambda: s.told(c, "out of breath", kind="own") or s.told(c, "out of breath"), seconds=10)
        told = [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {c}", "refused") if "out of breath" in r["text"] and r["at_ms"] >= t0]
        s.expect("too little breath refuses a dodge: out of breath", told, told[:2])
        s.graph(c, {"seq": [{"do": "jump"}, {"wait": 300}]})
        j = s.wait(lambda: next((v for v in [s.vitals(c)] if v["stamina"] < 14.0), None), seconds=10, every=0.2)
        s.expect("a jump with enough breath goes, taking 10", abs(j["stamina"] - 5.0) < 0.6, j)
        law("stamina_max", 100.0)
        # Tiredness caps breath: a body come into the world at energy 17.5 has 75.
        law("spawn_energy", 17.5)
        t, = s.people(1)
        tv = s.vitals(t, "tired-breath")
        s.expect("tiredness caps breath: 75 at energy 17.5", abs(tv["stamina_max"] - 75.0) < 0.6 and abs(tv["stamina"] - tv["stamina_max"]) < 0.01, tv)
        law("spawn_energy", 85.0)
        # Fire takes mana: three bolts from full, a fourth if 4 s of refill came back in time (30
        # each, 3 a second from 2 s after each), then refused.
        s.call("grant_know_how", a, "fire_bolt")
        aim = [line[-1][0], line[-1][1] + 6]
        t0 = now()
        s.graph(a, {"seq": [{"do": {"skill": "firebolt", "target": {"at": aim}}}, {"wait": 4.2}, {"do": {"skill": "firebolt", "target": {"at": aim}}}, {"wait": 4.2},
                            {"do": {"skill": "firebolt", "target": {"at": aim}}}, {"wait": 4.2}, {"do": {"skill": "firebolt", "target": {"at": aim}}}, {"wait": 4.2},
                            {"do": {"skill": "firebolt", "target": {"at": aim}}}, {"wait": 300}]})
        s.wait(lambda: [r for r in s.rows(f"SELECT text, at_ms FROM experience WHERE observer = {a}") if "not enough mana" in r["text"] and r["at_ms"] >= t0], seconds=35)
        bolts = [u for u in s.rows(f"SELECT * FROM skill_use WHERE actor = {a}", "bolts") if u["skill"] == "firebolt" and u["at_ms"] >= t0 and u["accepted_ms"] > 0]
        fv = s.vitals(a, "after-bolts")
        s.expect("three or four fire bolts from full, then refused: not enough mana", len(bolts) in (3, 4), [(u["at_ms"], u["outcome"]) for u in bolts])
        s.expect("the bolts took mana, not breath or tiredness", fv["focus"] < 30.0 and fv["focus_rate"] == 3.0, fv)
        # A held guard: 4 breath a second while up, 5 at the release, then the refill.
        time.sleep(6)
        s.graph(a, {"seq": [{"do": {"skill": "block", "qty": 3000}}, {"wait": 300}]})
        g = s.wait(lambda: next((v for v in [s.vitals(a)] if v["stamina_rate"] < 0), None), seconds=5, every=0.1)
        s.expect("a held guard drains 4 breath a second", abs(g["stamina_rate"] + 4.0) < 1e-3, g)
        e = s.wait(lambda: next((v for v in [s.vitals(a)] if v["stamina_rate"] > 0 and v["stamina_from_ms"] > g["at_ms"]), None), seconds=8, every=0.2)
        s.expect("the guard drops and breath comes back after the delay: 3 s held, 12 + 5 taken", abs(e["stamina_max"] - e["stamina"] - 17.0) < 1.5 and 0 < e["stamina_from_ms"] - e["at_ms"] <= 1000, e)
        # The narrow walk law: a setting of 3.0 walks 3.0 / 2.6 as fast.
        law("walk_base", 3.0)
        s.call("place_at", a, *line[0])
        time.sleep(0.5)
        s.graph(a, {"seq": [{"do": {"skill": "goto", "target": {"at": list(line[-1])}}}, {"wait": 300}]})
        time.sleep(1.0)
        faster = s.rows(f"SELECT speed FROM body WHERE id = {a}", "walk-3")[0]["speed"]
        s.expect("walk_base 3.0 walks 3.0 / 2.6 as fast, through the same move_speed", abs(faster / walk - 3.0 / 2.6) < 0.02, {"walk": walk, "walk_3": faster})
        law("walk_base", 2.6)
        # Animals: a wolf charges at a run (1.5 times its walk), a deer flees at a run.
        wolf = next((c["id"] for c in s.rows("SELECT id FROM character WHERE kind = 'wolf' AND alive = true")), None)
        deer = next((c["id"] for c in s.rows("SELECT id FROM character WHERE kind = 'deer' AND alive = true")), None)
        if wolf and deer:
            s.graph(wolf, {"wait": 300})
            s.graph(deer, {"wait": 300})
            s.call("place_at", wolf, *line[0])
            s.call("place_at", deer, *line[-1])
            time.sleep(1)
            s.graph(wolf, {"seq": [{"do": {"skill": "goto", "target": {"at": list(line[-1])}}}, {"wait": 300}]})
            time.sleep(1)
            wolf_walk = s.rows(f"SELECT speed FROM body WHERE id = {wolf}")[0]["speed"]
            s.call("place_at", wolf, *line[0])
            s.graph(wolf, {"seq": [{"do": {"skill": "attack", "target": {"id": deer}}}, {"wait": 300}]})
            time.sleep(1)
            charge = s.rows(f"SELECT speed FROM body WHERE id = {wolf}", "wolf-charge")[0]["speed"]
            s.expect("a wolf charges at a run: 1.5 times its walk", wolf_walk and abs(charge / wolf_walk - 1.5) < 0.03, {"walk": wolf_walk, "charge": charge})
            s.graph(wolf, {"wait": 300})
            s.call("place_at", wolf, line[-1][0] - 5, line[-1][1])
            s.call("place_at", deer, *line[-1])
            time.sleep(0.5)
            s.graph(deer, {"seq": [{"do": {"skill": "flee", "target": {"id": wolf}}}, {"wait": 300}]})
            time.sleep(1)
            fled = s.rows(f"SELECT speed FROM body WHERE id = {deer}", "deer-flight")[0]["speed"]
            s.expect("a deer flees at a run (1.5 times a deer's walk of 3.7, by its genes)", 3.7 * 1.5 * 0.7 < fled < 3.7 * 1.5 * 1.3, fled)
        else:
            s.expect("the world has a wolf and a deer for the animals' run", False, {"wolf": wolf, "deer": deer}, fatal=False)
    finally:
        for name, value in (("stamina_run", 4.0), ("stamina_max", 100.0), ("spawn_energy", 85.0), ("walk_base", 2.6)):
            law(name, value)


def fights(s):
    """How long a fight between equals lasts under the world's laws (health, damage, breath and
    the run): graph-driven 1v1s, the same graphs on any module (docs/STAMINA.md, "Fight length").
    Each side strikes the other (a wolf attacks) and flees below 20% of its health; in `pp-dodge`
    and `pw` a person also dodges a blow it sees coming, at 0.15 a look of its graph (about half
    the windups: a graph that dodged every one was never hit). `pp-trade` trades blows, no dodge.
    A fight runs from the first blow to a death or a flight (the first `flee`), or `FIGHT_S` (90)
    seconds; after a flight the scene watches 20 s more: caught (hurt again or killed) or clear
    (12 m off). `fights-results.json`: per fight its type, length, blows made and landed by each
    side, dodges, how it ended, and the flight's outcome. `FIGHTS` (5) of each type."""
    import statistics, collections
    n = int(os.environ.get("FIGHTS", "5"))
    limit = float(os.environ.get("FIGHT_S", "90"))
    line = open_line(s, length=16)
    out = []

    def graph(other, flee_below, melee="strike", dodge=True):
        return {"first": [
            {"if": {"cond": {"all": [{"hurt_within": 30}, {"health": {"below": flee_below}}]}, "then": {"do": {"skill": "flee", "target": {"id": other}}}}}]
            + ([{"if": {"cond": {"all": [{"threatened": True}, {"chance": 0.15}]}, "then": {"do": "dodge"}}}] if dodge else [])
            + [{"do": {"skill": melee, "target": {"id": other}}}]}

    def fight(kind, a, b, melee_b, dodge=True):
        va, vb = s.vitals(a), s.vitals(b)
        s.call("place_at", a, *line[6])
        s.call("place_at", b, *line[8])
        time.sleep(1.0)
        t_start = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
        s.graph(a, graph(b, 0.2 * va["max_hp"], dodge=dodge))
        s.graph(b, graph(a, 0.2 * vb["max_hp"], melee_b, dodge=dodge and melee_b == "strike"))
        first, end, how, fled, fled_at, flight = None, None, "timeout", None, None, None
        seen_uses, trail = {}, []
        t0 = time.monotonic()
        while time.monotonic() - t0 < limit + 40:
            now = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
            alive = {c["id"]: c["alive"] for c in s.rows(f"SELECT id, alive FROM character WHERE id = {a} OR id = {b}")}
            hp = {v["id"]: round(v["hp"] + v["hp_rate"] * max(0, now - v["at_ms"]) / 60000, 1) for v in s.rows(f"SELECT id, hp, hp_rate, at_ms FROM vitals WHERE id = {a} OR id = {b}")}
            d = apart(s, a, b) if all(alive.values()) else None
            acts = {x["id"]: x["skill"] for x in s.rows(f"SELECT id, skill FROM activity WHERE id = {a} OR id = {b}")}
            trail.append({"t": now, "hp": hp, "d": d, "acts": acts})
            for u in s.rows(f"SELECT * FROM skill_use WHERE actor = {a} OR actor = {b}"):
                if u["at_ms"] >= t_start:
                    seen_uses[u["id"]] = u
            if first is None:
                used = [u["accepted_ms"] for u in seen_uses.values() if u["accepted_ms"] and u["skill"] in ("strike", "attack", "dodge")]
                first = min(used) if used else None
            dead = [x for x in (a, b) if not alive.get(x)]
            if fled is None:
                if dead:
                    end, how = now, "death"
                    break
                runner = next((x for x in (a, b) if acts.get(x) == "flee"), None)
                if runner:
                    fled, fled_at, end, how = runner, now, now, "flight"
                    fled_hp = hp.get(runner)
                elif first and now - first > limit * 1000:
                    end = now
                    break
            else:
                # After a flight: caught (hurt again, or dead) or clear.
                if dead or hp.get(fled, 0) < fled_hp - 2:
                    flight = "caught" + (" and killed" if dead else "")
                    break
                if d is not None and d > 12:
                    flight = "clear"
                    break
                if now - fled_at > 20000:
                    flight = "neither in 20 s"
                    break
            time.sleep(0.3)
        for x in (a, b):
            s.graph(x, {"wait": 300})
        time.sleep(1.0)
        for u in s.rows(f"SELECT * FROM skill_use WHERE actor = {a} OR actor = {b}"):
            if u["at_ms"] >= t_start:
                seen_uses[u["id"]] = u
        uses = [u for u in seen_uses.values() if u["at_ms"] <= (end or 1e18)]
        blows = lambda who: [u for u in uses if u["actor"] == who and u["skill"] in ("strike", "attack") and u["accepted_ms"]]
        landed = lambda who: [u for u in blows(who) if u["outcome"].startswith("hit") or "killed" in u["outcome"]]
        r = {"type": kind, "a": a, "b": b, "seconds": round((end - first) / 1000, 1) if first and end else None,
             "ended": how + ({a: " of A", b: " of B"}.get(fled, "") if how == "flight" else ""), "flight": flight,
             "blows": [len(blows(a)), len(blows(b))], "landed": [len(landed(a)), len(landed(b))],
             "dodges": len([u for u in uses if u["skill"] == "dodge" and u["accepted_ms"]]),
             "exchanges": len(blows(a)) + len(blows(b)), "refused": [u["outcome"] for u in uses if not u["accepted_ms"] and u["outcome"]][:6],
             "hp_end": trail[-1]["hp"] if trail else None, "max_hp": [va["max_hp"], vb["max_hp"]]}
        print(json.dumps(r), flush=True)
        out.append(r)
        (s.out / f"{s.name}-trail-{kind}-{a}-{b}.json").write_text(json.dumps(trail) + "\n")

    types = os.environ.get("FIGHT_TYPES", "pp-dodge,pp-trade,pw").split(",")
    for k in range(n if "pp-dodge" in types else 0):
        a, b = s.people(2)
        fight("pp-dodge", a, b, "strike")
    for k in range(n if "pp-trade" in types else 0):
        a, b = s.people(2)
        fight("pp-trade", a, b, "strike", dodge=False)
    wolves = [] if "pw" not in types else [c["id"] for c in s.rows("SELECT id, stage FROM character WHERE kind = 'wolf' AND alive = true") if c["stage"] >= 2]
    for k in range(min(n, len(wolves))):
        p, = s.people(1)
        # A bold wolf (as a seed's hostile pack is), so it attacks a healthy adult, not only back.
        s.call("set_background", wolves[k], json.dumps({"pack": "verify fights", "bold": True}, separators=(",", ":")))
        fight("pw", p, wolves[k], "attack")
    (s.out / f"{s.name}-results.json").write_text(json.dumps(out, indent=1) + "\n")
    for kind in ("pp-dodge", "pp-trade", "pw"):
        f = [r for r in out if r["type"] == kind and r["seconds"] is not None]
        if f:
            secs = sorted(r["seconds"] for r in f)
            print(f"{kind}: {len(f)} fights, median {statistics.median(secs)} s (range {secs[0]}-{secs[-1]}), exchanges median {statistics.median(r['exchanges'] for r in f)}, "
                  f"ends {dict(collections.Counter(r['ended'] for r in f))}, flights {dict(collections.Counter(r['flight'] for r in f if r['flight']))}", flush=True)
    s.expect("the fights happened", any(r["seconds"] for r in out), [r["seconds"] for r in out])


def chase(s):
    """A pursuer goes for a person 5 m away who goes off along an open 64 m line, running (`goto`
    with `run: true`, while breath lasts, then walking) or walking; a chase ends when the prey
    reaches the line's end (`prey_away_s`: it never turns back into the pursuer) or at `CHASE_S`:
    a bold wolf (`attack`, charging at a run by its `motion` law) and, with `PURSUERS` naming it,
    a person (`attack` with `run: true`). Per chase: `caught_s`, when the gap is first down to the
    pursuer's catch distance (its attack's reach and its lunge: a wolf 3.2 m, a person 2 m), and
    `blow_s`, when its first blow starts (its `skill_use` row: within reach of a moving target),
    with whether the prey was still moving then; or neither before the line's end. `CHASES` (4) of
    each, `PURSUERS` (`wolf`; `wolf,person` for both), `MODES` (`run,walk`); a wolf is used once
    (a world has about a dozen grown); `chase-chases.json`. The runner and the
    wolf go at their `motion` laws (`run_share`, `wolf_run`): set them with `set_world_law` to
    measure another pairing."""
    import statistics
    n = int(os.environ.get("CHASES", "4"))
    limit = float(os.environ.get("CHASE_S", "30"))
    pursuers = [x.strip() for x in os.environ.get("PURSUERS", "wolf").split(",") if x.strip()]
    modes = [x.strip() for x in os.environ.get("MODES", "run,walk").split(",") if x.strip()]
    line = open_line(s, length=64)
    wolves = [c["id"] for c in s.rows("SELECT id, stage FROM character WHERE kind = 'wolf' AND alive = true") if c["stage"] >= 2]
    clock = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    out = []
    used = set()

    def fresh_wolf():
        """A grown wolf not used yet in this scene, unhurt and with full breath (a wolf that has
        just chased is winded and tired: `fights`' "wolves are reused")."""
        alive = {c["id"] for c in s.rows("SELECT id FROM character WHERE kind = 'wolf' AND alive = true")}
        for w in wolves:
            if w in used or w not in alive:
                continue
            v = s.vitals(w)
            if v["hp"] >= v["max_hp"] - 1e-3 and v["stamina"] >= v["stamina_max"] - 1e-3:
                used.add(w)
                return w
        return None

    for who in pursuers:
        catch = 3.2 if who == "wolf" else 2.0
        for mode in modes:
            for k in range(n):
                if who == "wolf":
                    w = fresh_wolf()
                    if w is None:
                        print(f"no fresh wolf left for {who} vs {mode} #{k}", flush=True)
                        continue
                    s.call("set_background", w, json.dumps({"pack": "verify chase", "bold": True}, separators=(",", ":")))
                    p, = s.people(1)
                else:
                    w, p = s.people(2)
                s.graph(w, {"wait": 300})
                s.call("place_at", p, *line[8])
                s.call("place_at", w, *line[3])
                time.sleep(1.0)
                # The pursuer first: at night (6 m sight) prey already off would be out of sight.
                s.graph(w, {"do": {"skill": "attack", "target": {"id": p}, **({"run": True} if who == "person" else {})}})
                s.graph(p, {"seq": [{"do": {"skill": "goto", "target": {"at": list(line[63])}, "run": mode == "run"}}, {"wait": 300}]})
                t0 = clock()
                hour = round(world_hour(s)[0], 1)
                caught, blow, d, speeds, gaps, prey_moving, away = None, None, None, [], [], None, None
                while True:
                    now = clock()
                    b = {r["id"]: r for r in s.rows(f"SELECT id, vx, vy FROM body WHERE id = {p} OR id = {w}")}
                    speeds.append({x: round(math.hypot(b[x]["vx"], b[x]["vy"]), 2) for x in b})
                    d = apart(s, p, w)
                    gaps.append((now - t0, d))
                    if caught is None and d <= catch:
                        caught = round((now - t0) / 1000, 1)
                    uses = [u for u in s.rows(f"SELECT skill, at_ms FROM skill_use WHERE actor = {w}") if u["skill"] == "attack" and u["at_ms"] >= t0]
                    if uses:
                        blow = round((min(u["at_ms"] for u in uses) - t0) / 1000, 1)
                        prey_moving = speeds[-1].get(p, 0) > 0.3
                        break
                    if body_at(s, p, now)[0] >= line[62][0]:
                        away = round((now - t0) / 1000, 1)
                        break
                    if now - t0 > limit * 1000:
                        break
                    time.sleep(0.15)
                s.graph(p, {"wait": 300})
                s.graph(w, {"wait": 300})
                s.call("place_at", w, *line[0])
                s.call("place_at", p, line[20][0], line[20][1] + 1)
                moving = lambda x: [sp[x] for sp in speeds if sp.get(x, 0) > 0.3]
                med = lambda v: round(statistics.median(v), 2) if v else 0
                late = [g for t, g in gaps if t > 3000]
                r = {"pursuer": who, "mode": mode, "person": p, "chaser": w, "caught_s": caught, "blow_s": blow, "prey_moving_at_blow": prey_moving, "prey_away_s": away, "hour": hour,
                     "gap_end": d, "gap_min_after_3s": min(late) if late else None,
                     "person_speed_med": med(moving(p)), "chaser_speed_med": med(moving(w))}
                print(json.dumps(r), flush=True)
                out.append(r)
                time.sleep(3)
    (s.out / f"{s.name}-chases.json").write_text(json.dumps(out, indent=1) + "\n")
    for who in pursuers:
        for mode in modes:
            rs = [r for r in out if r["pursuer"] == who and r["mode"] == mode]
            for key in ("caught_s", "blow_s"):
                got = sorted(r[key] for r in rs if r[key] is not None)
                print(f"{who} vs {mode}: {key} {len(got)} of {len(rs)}, median {round(statistics.median(got), 1) if got else None} s, range {got[:1] + got[-1:]}", flush=True)
    s.expect("the chases happened", out, len(out))

def flee(s):
    """A deer flees a wolf 6 tiles off: it runs away from the wolf (the distance only grows)
    until it is `flee_clear` (9) tiles farther than it began. Before 2026-11-10 the goal ran
    from a point 9 tiles beyond the deer, so the deer ran at the wolf. Needs a world with deer
    and wolves (`--seed stage1-acts`)."""
    for c in s.rows("SELECT id, alive FROM character"):
        if c["alive"]:
            s.graph(c["id"], {"wait": 300})
    deer = [c["id"] for c in s.rows("SELECT id FROM character WHERE kind = 'deer' AND alive = true")]
    wolf = next(c["id"] for c in s.rows("SELECT id FROM character WHERE kind = 'wolf' AND alive = true"))
    s.expect("world has deer and a wolf", bool(deer) and bool(wolf), {"deer": deer[:4], "wolf": wolf})
    track, start = [], None
    for d in deer[:6]:
        here = body_at(s, d)
        s.call("place_at", wolf, here[0] + 6.0, here[1])
        time.sleep(0.5)
        w = body_at(s, wolf)
        start = math.dist(body_at(s, d), w)
        if not 4.5 <= start <= 7.5:
            continue
        # Flight is real-time behaviour: a graph runs it (a one-off act may not).
        s.graph(d, {"seq": [{"do": {"skill": "flee", "target": {"id": wolf}}}, {"wait": 300}]})
        t0 = time.monotonic()
        track, seen, goal = [], False, None
        while time.monotonic() - t0 < 15:
            track.append(apart(s, d, wolf))
            act = s.rows(f"SELECT skill FROM activity WHERE id = {d}")
            fleeing = any(r["skill"] == "flee" for r in act)
            if fleeing and goal is None:
                goal = s.rows(f"SELECT goal, target, gx, gy, keep FROM steer WHERE id = {d}", "steer")[0]
            seen = seen or fleeing
            if seen and not fleeing:
                break
        track.append(apart(s, d, wolf))
        if goal is not None:
            break
        # Never started: nowhere to run from here (told "cornered"); try another deer.
        s.graph(d, {"wait": 300})
    (s.out / f"{s.name}-track.json").write_text(json.dumps({"deer": d, "wolf": wolf, "start": start, "track": track}, indent=2) + "\n")
    s.rows(f"SELECT * FROM experience WHERE observer = {d}", "deer-feedback")
    s.expect("the flight steers away from the wolf itself", goal and goal["goal"] == 4 and goal["target"] == wolf, goal)
    falls = [(a, b) for a, b in zip(track, track[1:]) if b < a - 0.3]
    s.expect("the distance to the wolf never falls while fleeing", track and not falls, {"start": start, "track": track, "falls": falls})
    s.expect("the flight ends about flee_clear farther than it began", track and track[-1] >= start + 7.0, {"start": start, "end": track[-1] if track else None})



def wall_spots(s, n=4):
    """Points where a flight straight away from a threat runs into an inside corner within a
    few metres: walkable, the way `d` blocked within 3.5 m and the way 45° round from it within
    4.5 m, while a way 90° round has 9 m of open ground and 6 m behind (where the threat stands)
    is open. Up to `n`, at least 30 m apart: (point, way)."""
    W, H, walk = tile_grid(s)

    def run(x, y, h, m):
        c, sn = math.cos(h), math.sin(h)
        k = 0.25
        while k <= m:
            if not (walk(x + c * k, y + sn * k) and walk(x + c * (k + 0.25), y + sn * (k + 0.25))):
                return k - 0.25
            k += 0.25
        return m

    out = []
    for y in range(12, H - 12, 2):
        for x in range(12, W - 12, 2):
            if any(math.dist((x, y), q) < 30 for q, _ in out):
                continue
            px, py = x + 0.5, y + 0.5
            if not walk(px, py):
                continue
            for k in range(8):
                d = k * math.pi / 4
                for turn in (math.pi / 4, -math.pi / 4):
                    if run(px, py, d, 4.0) <= 3.5 and run(px, py, d + turn, 5.0) <= 4.5 and run(px, py, d - 2 * turn, 9.0) >= 9.0 and run(px, py, d + math.pi, 6.5) >= 6.5:
                        out.append(((px, py), d))
                        break
                if out and out[-1][0] == (px, py):
                    break
            if len(out) >= n:
                return out
    return out


def flee_wall(s):
    """A person flees another into an inside corner (the way straight away blocked within
    3.5 m, the way 45° round it too) with an open side: the flight takes the open side
    (`steer::flee_way`) and gets clear, never "cornered" and never closing on the
    threat by more than a stride. Default seed (the map's edge, water and town walls)."""
    for c in s.rows("SELECT id, alive FROM character"):
        if c["alive"]:
            s.graph(c["id"], {"wait": 300})
    people = [c["id"] for c in s.rows("SELECT id FROM character WHERE kind = 'person' AND alive = true")]
    spots = wall_spots(s)
    W, H, _ = tile_grid(s)
    opaque = set()
    for row in s.rows("SELECT * FROM terrain_chunk"):
        data = row["tiles"]
        data = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
        cx, cy = row["id"] & 0xFFFF, row["id"] >> 16
        opaque.update((cx * 16 + k % 16, cy * 16 + k // 16) for k, t in enumerate(data) if t in (4, 7))

    def in_sight(a, b):
        n = max(1, int(math.dist(a, b) * 4))
        return math.dist(a, b) <= 11.0 and not any((int(a[0] + (b[0] - a[0]) * i / n), int(a[1] + (b[1] - a[1]) * i / n)) in opaque for i in range(n + 1))
    s.expect("the map has inside corners with an open side", len(spots) >= 2, {"spots": spots})
    results = []
    for i, ((px, py), d) in enumerate(spots):
        f, t = people[2 * i], people[2 * i + 1]
        s.call("place_at", f, px, py)
        s.call("place_at", t, px - 5.0 * math.cos(d), py - 5.0 * math.sin(d))
        time.sleep(0.6)
        start = apart(s, f, t)
        since = max([r["id"] for r in s.rows(f"SELECT id FROM experience WHERE observer = {f}")] or [0])
        s.graph(f, {"seq": [{"do": {"skill": "flee", "target": {"id": t}}}, {"wait": 300}]})
        t0 = time.monotonic()
        track, seen, goal = [], False, None
        while time.monotonic() - t0 < 15:
            track.append(apart(s, f, t))
            fleeing = any(r["skill"] == "flee" for r in s.rows(f"SELECT skill FROM activity WHERE id = {f}"))
            if fleeing and goal is None:
                goal = s.rows(f"SELECT goal, target, gx, gy, keep FROM steer WHERE id = {f}", "steer")[0]
            seen = seen or fleeing
            if seen and not fleeing:
                break
            time.sleep(0.3)
        track.append(apart(s, f, t))
        # A plan step's failure is told at the graph's next evaluation.
        time.sleep(1.5)
        told = [r["text"] for r in s.rows(f"SELECT id, text FROM experience WHERE observer = {f}") if r["id"] > since]
        cornered = any("cornered" in x for x in told)
        seen_at_end = in_sight(body_at(s, f), body_at(s, t))
        falls = [(a, b) for a, b in zip(track, track[1:]) if b < a - 1.0]
        results.append({"spot": [px, py], "way": round(d, 3), "fleer": f, "threat": t, "start": start, "end": track[-1], "cornered": cornered, "seen_at_end": seen_at_end, "falls": falls, "goal": goal, "told": told[-4:], "track": track})
        s.graph(f, {"wait": 300})
    (s.out / f"{s.name}-flights.json").write_text(json.dumps(results, indent=2) + "\n")
    s.expect("no flight is cornered", all(not r["cornered"] for r in results), [(r["spot"], r["told"]) for r in results if r["cornered"]])
    # A flight ends `flee_clear` farther, or sooner once the threat is out of the fleer's sight
    # (a graph's flee step ends when what it fled is no longer perceived: beyond day sight, 11 m,
    # or behind a wall or rock).
    s.expect("every flight gets clear: 6 m farther than it began, or out of the threat's sight", all(r["end"] >= r["start"] + 6.0 or not r["seen_at_end"] for r in results), [(r["spot"], r["start"], r["end"], r["seen_at_end"]) for r in results])
    s.expect("no flight closes on the threat by more than a stride", all(not r["falls"] for r in results), [(r["spot"], r["falls"]) for r in results if r["falls"]])


def open_patch(s, size=14, avoid=()):
    """The centre of a `size` × `size` square of walkable tiles (nothing that blocks sight or the
    foot in it), for movement that needs room on every side; with `avoid`, more than 12 m from
    each of those points."""
    W, H, walk = tile_grid(s)
    half = size // 2
    for y in range(half + 4, H - half - 4, 4):
        for x in range(half + 4, W - half - 4, 4):
            if any(math.dist((x, y), q) <= 12 + half for q in avoid):
                continue
            if all(walk(x + i, y + j) for i in range(-half, half + 1) for j in range(-half, half + 1)):
                return (x + 0.5, y + 0.5)
    raise RuntimeError(f"no open {size} m square on this map")


def facing_now(b, now):
    """Which way a body faces at `now` (`living_rules::steer::facing`): its heading along its
    segment's turn, plus its facing offset along its own turn."""
    dt = max(0, min(now, b["next_ms"]) - b["t_ms"]) / 1000
    h = b["heading"] + b["turn"] * min(dt, b["turn_s"])
    off = b["face_off"] + b["face_turn"] * min(max(dt, 0), b["face_turn_s"])
    return h + off


def angle_off(a, b):
    """The angle between two directions, 0..π."""
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def intents(s):
    """Movement intents (docs/COMBAT_MIND.md §3.3, features/steering.md "Movement intents"):
    graph leaves for any controller, on the same steering as a player's keys. On an open line:
    `keep_distance` (3–6 m) holds its band against a walker coming at it, then re-aims when the
    walker turns away; `close_in` with `run: true` catches a walker at the run's speed, draining
    breath, and ends within its distance; `back_off` reaches its distance and stands facing what
    it backed from; `follow` (3 m) trails a walker out and back. In an open square: `circle`
    (4 m, left, then right) keeps its radius and its side, and re-aims when the centre moves.
    Then a target taken out of sight ends a keep_distance after the `lost_after_s` law with "lost
    sight of them", and an unseen target, oneself and a band upside down are refused."""
    line = open_line(s, length=44)
    a, b = s.people(2)
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    # People walk at their own pace (their genes): a body cannot keep away from, or keep up
    # with, a faster one at a walk, as a player cannot. The faster of the two holds and follows.
    pace = {}
    for i, k in ((a, 1), (b, 2)):
        s.call("place_at", i, line[0][0], line[0][1] + (-1) ** k)
        s.graph(i, {"do": {"skill": "goto", "target": {"at": [line[30][0], line[0][1] + (-1) ** k]}}})
    time.sleep(1.2)
    for i in (a, b):
        pace[i] = s.rows(f"SELECT speed FROM body WHERE id = {i}")[0]["speed"]
    if pace[b] > pace[a]:
        a, b = b, a
    (s.out / f"{s.name}-paces.json").write_text(json.dumps({"holder": a, "walker": b, "walk": pace}, indent=1) + "\n")
    y0 = line[0][1]
    lost = law_value(s, "lost_after_s")

    def rowsof(*ids):
        return {r["id"]: r for r in s.rows("SELECT * FROM body WHERE " + " OR ".join(f"id = {i}" for i in ids))}

    def sample():
        t = now()
        r = rowsof(a, b)
        pa, pb = body_at(s, a, t, r[a]), body_at(s, b, t, r[b])
        act = s.rows(f"SELECT skill FROM activity WHERE id = {a}")
        return {"t": t, "a": [round(pa[0], 2), round(pa[1], 2)], "b": [round(pb[0], 2), round(pb[1], 2)],
                "gap": round(math.dist(pa, pb), 2), "speed_a": round(math.hypot(r[a]["vx"], r[a]["vy"]), 2), "cruise_a": round(r[a]["speed"], 3),
                "running": r[a]["running"], "facing_off": round(angle_off(facing_now(r[a], t), math.atan2(pb[1] - pa[1], pb[0] - pa[0])), 3),
                "act": act[0]["skill"] if act else None}

    def watch(label, seconds, until=None):
        out, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            out.append(sample())
            if until and until(out[-1]):
                break
            time.sleep(0.1)
        (s.out / f"{s.name}-{label}.json").write_text(json.dumps(out, indent=1) + "\n")
        return out

    def still(*ids):
        for i in ids:
            s.graph(i, {"wait": 300})

    def settled(seconds=8):
        """The holder's state once it has stood for two looks running (or after `seconds`)."""
        last, end = None, time.monotonic() + seconds
        while time.monotonic() < end:
            x = sample()
            if x["speed_a"] == 0 and last is not None and last["speed_a"] == 0:
                return x
            last = x
            time.sleep(0.3)
        return sample()

    def put(i, x, y):
        s.call("place_at", i, x, y)

    # 1. keep_distance against a walker coming at it.
    still(a, b)
    put(b, *line[2])
    put(a, line[6][0] + 0.5, y0)
    time.sleep(1.0)
    s.graph(a, {"seq": [{"do": {"skill": "keep_distance", "target": {"id": b}, "min": 3, "max": 6, "qty": 60}}, {"wait": 300}]})
    time.sleep(1.0)
    st = s.rows(f"SELECT goal, target, keep, far, flags FROM steer WHERE id = {a}", "keep-steer")[0]
    s.expect("keep_distance is a band goal held to the walker by sight", st["goal"] == 5 and st["target"] == b and abs(st["keep"] - 3) < 1e-3 and abs(st["far"] - 6) < 1e-3 and st["flags"] & 128, st)
    start_a = body_at(s, a)
    s.graph(b, {"do": {"skill": "goto", "target": {"at": list(line[36])}}})
    track = watch("keep-approach", 16, until=lambda x: x["b"][0] >= line[36][0] - 0.3 and x["speed_a"] == 0)
    end = settled()
    moving = [x for x in track if x["b"][0] > line[3][0]]
    s.expect("held its band against the walker: never nearer than 2 m (the band's 3 m less a look's reaction)", moving and min(x["gap"] for x in moving) >= 2.0,
             {"min_gap": min((x["gap"] for x in moving), default=None), "samples": len(moving)})
    s.expect("it backed off: walked over 10 m away along the line", end["a"][0] - start_a[0] > 10, {"start": start_a, "end": end["a"]})
    s.expect("the walker stopped: it stands in the band facing it", 2.8 <= end["gap"] <= 6.2 and end["speed_a"] == 0 and end["facing_off"] < 0.45, end)
    # Re-aims as the target moves: the walker turns and goes back down the line; the holder
    # follows it there (both put back on the open line, a band well within night sight).
    still(a, b)
    put(a, *line[40])
    put(b, *line[37])
    time.sleep(1.5)
    s.graph(a, {"seq": [{"do": {"skill": "keep_distance", "target": {"id": b}, "min": 2.5, "max": 4.5, "qty": 60}}, {"wait": 300}]})
    time.sleep(1.0)
    end = sample()
    s.graph(b, {"do": {"skill": "goto", "target": {"at": list(line[16])}}})
    track = watch("keep-reaim", 14, until=lambda x: x["b"][0] <= line[16][0] + 0.3 and x["speed_a"] == 0)
    end2 = settled()
    s.expect("re-aims at the walker as it goes back: follows it down the line and stands in the band", end2["a"][0] < end["a"][0] - 15 and 2.3 <= end2["gap"] <= 4.7,
             {"before": end["a"], "after": end2["a"], "gap": end2["gap"]})

    # 2. close_in at a run on a walker going away: the run's speed, breath drains, ends within 2 m.
    still(a, b)
    put(a, *line[1])
    put(b, *line[6])
    time.sleep(1.5)
    # 5 m apart (within sight by night too), the walker going away at a walk.
    s.graph(a, {"seq": [{"do": {"skill": "close_in", "target": {"id": b}, "distance": 1, "run": True}}, {"wait": 300}]})
    s.graph(b, {"do": {"skill": "goto", "target": {"at": list(line[43])}}})
    time.sleep(0.6)
    v = s.vitals(a, "close-vitals-running")
    track = watch("close-in", 14, until=lambda x: x["act"] == "wait")
    # The cruising speed on the row (what steering moves it at; the velocity is lower while it
    # slows in near its distance, and a catch from 5 m lasts about a second).
    runs = [x["cruise_a"] for x in track if x["act"] == "close_in" and x["running"]]
    share = law_value(s, "run_share")
    s.expect("close_in with run: true runs at run_share times its own walk", runs and abs(max(runs) / pace[a] - share) < 0.1,
             {"run_speed": max(runs, default=None), "own_walk": pace[a], "run_share": share})
    s.expect("the run drains breath (the vitals row's rate, as for anyone's run)", v["stamina_rate"] < 0, {"stamina_rate": v["stamina_rate"], "stamina": v["stamina"]})
    done = track[-1]
    s.expect("close_in ends within its distance of the walker, re-aimed at it all the way", done["act"] == "wait" and done["gap"] <= 1.6, done)
    time.sleep(1.5)
    v2 = s.vitals(a, "close-vitals-after")
    s.expect("standing again, breath comes back", v2["stamina_rate"] >= 0, {"stamina_rate": v2["stamina_rate"]})

    # 3. back_off to 7 m, then stand facing it.
    still(a, b)
    put(b, *line[22])
    put(a, *line[20])
    time.sleep(1.5)
    s.graph(a, {"seq": [{"do": {"skill": "back_off", "target": {"id": b}, "distance": 7}}, {"wait": 300}]})
    time.sleep(0.6)
    st = s.rows(f"SELECT goal, target, keep, flags FROM steer WHERE id = {a}", "back-steer")[0]
    track = watch("back-off", 8, until=lambda x: x["act"] == "wait")
    time.sleep(1.0)
    end = settled()
    s.expect("back_off steers away from the creature, held by sight", st["goal"] in (4, 0) and st["flags"] & 128 and abs(st["keep"] - 7) < 1e-3, st)
    s.expect("back_off reaches its distance and is done", track[-1]["act"] == "wait" and end["gap"] >= 6.9, {"end": end, "last": track[-1]})
    s.expect("it stands facing what it backed from", end["speed_a"] == 0 and end["facing_off"] < 0.3, end)

    # 4. follow at 3 m: trails a walker out, then back the other way.
    still(a, b)
    put(a, *line[1])
    put(b, *line[4])
    time.sleep(1.5)
    s.graph(a, {"seq": [{"do": {"skill": "follow", "target": {"id": b}, "distance": 3, "qty": 40}}, {"wait": 300}]})
    s.graph(b, {"seq": [{"do": {"skill": "goto", "target": {"at": list(line[34])}}}, {"wait": 1}, {"do": {"skill": "goto", "target": {"at": list(line[8])}}}, {"wait": 300}]})
    went = []
    out = watch("follow", 34, until=lambda x: went.append(x["b"][0] > line[30][0]) or (any(went) and x["b"][0] <= line[8][0] + 0.3 and x["speed_a"] == 0))
    outward = [x for x in out if line[10][0] < x["b"][0] < line[32][0] and x["b"][0] > x["a"][0]]
    gaps = sorted(x["gap"] for x in outward)
    turn = max(out, key=lambda x: x["a"][0])
    # The follower sets off up to a look (1 s for a still target) after the walker and gains
    # only what its own walk has over the walker's (`intents-paces.json`): it trails a little
    # beyond its 3 m, never falling back.
    s.expect("follow trails the walker out near its distance (median 2.5–5.5 m, never over 6.5)", gaps and 2.5 <= gaps[len(gaps) // 2] <= 5.5 and gaps[-1] <= 6.5,
             {"median": gaps[len(gaps) // 2] if gaps else None, "max": gaps[-1] if gaps else None, "n": len(gaps)})
    s.expect("follow re-aims when the walker turns back: it comes back down the line after it", out[-1]["a"][0] < turn["a"][0] - 10, {"farthest": turn["a"], "end": out[-1]["a"]})

    # 5. circle at 4 m in an open square, left then right; the centre moves and it re-aims.
    still(a, b)
    c = open_patch(s, 16)
    put(b, *c)
    put(a, c[0] + 4, c[1])
    time.sleep(1.5)
    s.graph(a, {"seq": [{"do": {"skill": "circle", "target": {"id": b}, "radius": 4, "side": "left", "qty": 60}}, {"wait": 300}]})

    def orbit(label, seconds):
        out = watch(label, seconds)
        swept, last = 0.0, None
        for x in out:
            ang = math.atan2(x["a"][1] - x["b"][1], x["a"][0] - x["b"][0])
            if last is not None:
                swept += (ang - last + math.pi) % (2 * math.pi) - math.pi
            last = ang
        settled = out[len(out) // 4:]
        return out, swept, max((abs(x["gap"] - 4) for x in settled), default=None)

    out, swept, worst = orbit("circle-left", 12)
    s.expect("circle keeps its radius: within 0.8 m of 4 m once going", worst is not None and worst <= 0.8, {"worst": worst})
    s.expect("circle goes round to the left (facing it; the angle about it falling): over half a turn", swept < -math.pi, {"swept_rad": round(swept, 2)})
    s.expect("circling, it faces the centre as far as walking allows (look_walk_deg)", max(x["facing_off"] for x in out[len(out) // 2:]) < math.radians(law_value(s, "look_walk_deg") - 60) + 0.35,
             {"worst_facing_off": max(x["facing_off"] for x in out[len(out) // 2:])})
    s.graph(b, {"do": {"skill": "goto", "target": {"at": [c[0] - 3, c[1]]}}})
    out, _, _ = orbit("circle-moved", 9)
    late = out[len(out) // 2:]
    s.expect("the centre moved 3 m: the circle follows it (within 1 m of 4 m from where it is now)", late and max(abs(x["gap"] - 4) for x in late) <= 1.0, {"gaps": [x["gap"] for x in late]})
    s.graph(a, {"seq": [{"do": {"skill": "circle", "target": {"id": b}, "radius": 4, "side": "right", "qty": 60}}, {"wait": 300}]})
    out, swept, _ = orbit("circle-right", 8)
    s.expect("circle to the right goes the other way round", swept > math.pi / 2, {"swept_rad": round(swept, 2)})

    # 6. Out of sight: the target taken 40 m off ends a keep_distance after lost_after_s.
    s.graph(a, {"seq": [{"do": {"skill": "keep_distance", "target": {"id": b}, "min": 3, "max": 6, "qty": 60}}, {"wait": 300}]})
    time.sleep(1.0)
    still(b)
    gone = open_patch(s, 6, avoid=[c, body_at(s, a)])
    t0 = now()
    put(b, *gone)
    told = s.wait(lambda: [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {a}") if r["kind"] == "own" and "lost sight of them" in r["text"] and r["at_ms"] >= t0], seconds=lost + 8, every=0.25)
    ended = (told[0]["at_ms"] - t0) / 1000
    s.expect(f"a target out of sight ends it after lost_after_s ({lost} s): 'lost sight of them'", lost - 0.3 <= ended <= lost + 1.5,
             {"after_s": round(ended, 2), "gone_m": round(math.dist(gone, c), 1), "told": told[0]["text"]})

    # 7. Refusals, told truthfully: an unseen target (a mind's one-off close_in), oneself, a
    # band upside down (refused by the grammar, naming the fix).
    s.graph(a, {"wait": 300})
    s.act(a, {"do": "close_in", "target": {"id": b}, "distance": 2})
    unseen = s.wait(lambda: s.told(a, "in sight", kind="act"), seconds=10)
    s.expect("a one-off close_in toward someone out of sight is refused: not in sight", unseen, [t["text"] for t in unseen][-1:])
    put(b, c[0] + 2, c[1])
    put(a, *c)
    time.sleep(1.0)
    s.graph(a, {"seq": [{"do": {"skill": "circle", "target": "self", "radius": 3}}, {"wait": 300}]})
    time.sleep(1.5)
    selfish = s.told(a, "not yourself", kind="own")
    s.expect("refused toward oneself", selfish, [t["text"] for t in s.rows(f"SELECT kind, text FROM experience WHERE observer = {a}")][-3:])
    r = s.call("set_behavior", a, json.dumps({"do": {"skill": "keep_distance", "target": {"id": b}, "min": 6, "max": 3}}), check=False)
    s.expect("a band upside down is refused by the grammar, naming the fix", r.returncode != 0 and "beyond" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-300:])
    still(a, b)


def intents_cost(s):
    """What movement intents cost the tick (features/steering.md "Movement intents"): `N`
    (default 16) people stand still, then each circles (4 m) or keeps a 3–6 m band from a
    partner who walks back and forth, for `SECONDS` (default 20) each. With the module's
    profiling on, the `tick.motion` span (the steering updates) and the `stats.motions` count
    give the steering updates a second and the time per update; `intents_cost-cost.json`."""
    from datetime import datetime, timezone
    n = int(os.environ.get("N", "16"))
    secs = float(os.environ.get("SECONDS", "20"))
    people = s.people(2 * n)
    holders, partners = people[:n], people[n:]
    centre = open_patch(s, 10)
    spots = []
    taken = [centre]
    for k in range(n):
        p = open_patch(s, 10, avoid=taken)
        taken.append(p)
        spots.append(p)

    def stats():
        return s.rows("SELECT motions, ticks FROM stats")[0]

    def window(label):
        s.call("set_profile", True)
        t0, k0 = time.time(), stats()
        time.sleep(secs)
        t1, k1 = time.time(), stats()
        s.call("set_profile", False)
        logs = s.command("logs", "-s", "local", s.db, "-n", str(int(secs * 60 * 12 + 4000))).stdout
        spent = 0.0
        for m in re.finditer(r'^(\S+Z)\s.*Timing span "tick\.motion": ([\d.]+)(µs|ms|s)\b', logs, re.M):
            stamp = m.group(1)[:26].rstrip("Z")
            at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%f" if "." in stamp else "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            if t0 <= at <= t1:
                spent += float(m.group(2)) * {"µs": 1e-3, "ms": 1.0, "s": 1e3}[m.group(3)]
        dt = t1 - t0
        out = {"label": label, "seconds": round(dt, 1), "motions_per_s": round((k1["motions"] - k0["motions"]) / dt, 1), "motion_ms_per_s": round(spent / dt, 3)}
        print(json.dumps(out), flush=True)
        return out

    for h, p, at in zip(holders, partners, spots):
        s.graph(h, {"wait": 300})
        s.graph(p, {"wait": 300})
        s.call("place_at", p, *at)
        s.call("place_at", h, at[0] + 4, at[1])
    time.sleep(2)
    base = window("standing")
    for k, (h, p, at) in enumerate(zip(holders, partners, spots)):
        if k % 2:
            s.graph(p, {"seq": [{"do": {"skill": "goto", "target": {"at": [at[0] - 3, at[1]]}}}, {"do": {"skill": "goto", "target": {"at": [at[0] + 3, at[1]]}}}]})
            s.graph(h, {"do": {"skill": "keep_distance", "target": {"id": p}, "min": 3, "max": 6, "qty": 600}})
        else:
            s.graph(h, {"do": {"skill": "circle", "target": {"id": p}, "radius": 4, "qty": 600}})
    time.sleep(2)
    held = window("intents")
    walkers = n // 2
    extra_updates = held["motions_per_s"] - base["motions_per_s"]
    extra_ms = held["motion_ms_per_s"] - base["motion_ms_per_s"]
    res = {"n_holders": n, "walking_partners": walkers, "standing": base, "intents": held,
           "updates_per_s_per_intent": round(extra_updates / n, 2),
           "us_per_update": round(1000 * extra_ms / max(extra_updates, 1), 1),
           "motion_ms_per_s_per_intent": round(extra_ms / n, 4)}
    (s.out / f"{s.name}-cost.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res), flush=True)
    for x in people:
        s.graph(x, {"wait": 300})
    s.expect("the intents ran and were measured", held["motions_per_s"] > base["motions_per_s"], res)


def food(s):
    """\"food\" is anything the rules give nutrition: a person carrying only smoked fish has
    food, and eats and gives it as \"food\" (before 2026-11-10 `best_food` listed five foods and
    missed smoked ones, so `has food` held while eat/give/store/take of food failed)."""
    a, b = s.people(2)
    s.call("place_near", b, a)
    s.call("grant_items", a, "smoked_fish", 2)
    before = s.needs(a, "before")["hunger"]
    s.act(a, {"do": "eat", "item": "food"})
    s.wait(lambda: s.inventory(a).get("smoked_fish", 0) == 1, seconds=15)
    s.expect("eat food eats the smoked fish and feeds", s.needs(a, "after-eat")["hunger"] <= max(0, before - 10), s.inventory(a, "after-eat"))
    s.act(a, {"do": "give", "item": "food", "target": {"id": b}})
    s.wait(lambda: s.inventory(b).get("smoked_fish", 0) == 1, seconds=20)
    s.expect("give food hands over the smoked fish", s.inventory(a, "giver-after").get("smoked_fish", 0) == 0 and s.inventory(b, "taker-after").get("smoked_fish") == 1)
    # The most nourishing first: cooked meat (42) over smoked fish (24) over berries (12).
    s.call("grant_items", a, "smoked_fish", 1)
    s.call("grant_items", a, "cooked_meat", 1)
    held = s.inventory(a, "before-best")
    s.act(a, {"do": "eat", "item": "food"})
    s.wait(lambda: s.inventory(a).get("cooked_meat", 0) == 0, seconds=15)
    after = s.inventory(a, "after-best")
    s.expect("eat food picks the most nourishing food held", after.get("smoked_fish") == held.get("smoked_fish")
             and after.get("berries", 0) == held.get("berries", 0), {"before": held, "after": after})


def teach(s):
    """Every know-how can be taught, not only what experimenting can reveal: a person who
    knows fire_bolt and wound_tending teaches each to a learner (before 2026-11-11
    `teach_check` checked `techniques()`, the materials' discoveries, and refused both as "no
    technique called …"). A thing is still refused, with what makes it."""
    a, b = s.people(2)
    s.call("place_near", b, a)
    for t in ("fire_bolt", "wound_tending"):
        s.call("grant_know_how", a, t)
    for t in ("fire_bolt", "wound_tending"):
        s.act(a, {"do": "teach", "item": t, "target": {"id": b}})
        known = lambda: [k for k in s.rows(f"SELECT * FROM know_how WHERE actor = {b}") if k["technique"] == t]
        try:
            row = s.wait(known, seconds=40)
        except TimeoutError:
            row = []
        s.expect(f"a knower teaches {t}", row and "taught by" in row[0]["source"], {"learner": s.rows(f"SELECT * FROM know_how WHERE actor = {b}", f"learner-{t}"), "teacher told": [r["text"] for r in s.rows(f"SELECT kind, text FROM experience WHERE observer = {a}") if t in r["text"]]}, fatal=False)
        s.expect(f"the learner is told it was taught {t}", s.told(b, f"taught you {t}", "learned"), [r["text"] for r in s.rows(f"SELECT kind, text FROM experience WHERE observer = {b}") if t in r["text"]], fatal=False)
    s.act(a, {"do": "teach", "item": "leather", "target": {"id": b}})
    try:
        why = s.wait(lambda: [r["text"] for r in s.rows(f"SELECT kind, text FROM experience WHERE observer = {a}") if "leather is a thing, not a technique" in r["text"]], seconds=15)
    except TimeoutError:
        why = []
    s.expect("a thing is refused with what makes it", why, why, fatal=False)


def refusal(s):
    """A routine whose action is refused as it would start is counted and told like any
    failure: its `routine_stat` counts it with the reason, the character is told once (not
    every second while the graph retries), and `fails` counts it. Before 2026-11-10 a refusal
    at start left no trace while the graph retried it every second."""
    a, = s.people(1)
    s.call("mind_routines", a, [{"name": "snack", "graph": json.dumps({"do": {"skill": "eat", "item": "cooked_meat"}})}])
    routine = next(r for r in s.rows(f"SELECT id, name FROM routine WHERE actor = {a}") if r["name"] == "snack")
    t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.graph(a, {"seq": [{"routine": "snack"}, {"wait": 1}]})
    time.sleep(10)
    stat = s.rows(f"SELECT * FROM routine_stat WHERE id = {routine['id']}", "routine-stat")
    s.expect("the routine's statistics count the refused start, with its reason", stat and stat[0]["failed"] >= 1 and stat[0]["last_fail"], stat)
    told = [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {a}", "feedback") if r["kind"] == "own" and r["at_ms"] >= t0 and "cooked_meat" in r["text"]]
    s.expect("the character is told once in the repeat window, not every retry", len(told) == 1, told)
    st = s.rows(f"SELECT fails, status FROM mind_state WHERE id = {a}", "mind-state")[0]
    s.expect("the refusal counts in fails", st["fails"] >= 1, st)


# Rules with short hours for the dealings scene, composed as a floor composes its laws
# (living_rules::floors::compose): each replaced base function keeps its body as base_NAME.
SHORT_HOURS = {
    "due_by_dark": "fn due_by_dark(a) { 1.0 }",
    "proposal_h": "fn proposal_h(x) { 1.5 }",
    "demand_h": "fn demand_h(x) { 1.0 }",
    "kept_h": "fn kept_h(x) { 2.0 }",
}


def compose(base, overlay):
    for name in overlay:
        base = base.replace(f"fn {name}(", f"fn base_{name}(")
    return base + "\n" + "\n".join(overlay.values()) + "\n"


def dealings(s):
    """Agreements, demands and regard, built in the rules on the engine's records."""
    src = compose((ROOT / "living/scripts/skills.rhai").read_text(), SHORT_HOURS)
    s.call("install_script", src)
    hour_s = s.rows("SELECT day_ms FROM world")[0]["day_ms"] / 24000
    a, b, c, d = s.people(4)
    for x in (b, c, d):
        s.call("place_near", x, a)
    s.call("grant_items", a, "berries", 6)
    s.call("grant_items", b, "wood", 8)
    s.call("place_structure", a, "storage")
    store = max(r["id"] for r in s.rows(f"SELECT id FROM structure WHERE owner = {a}"))

    def records(label=None):
        return s.rows("SELECT * FROM record", label)

    def record_of(kind, by):
        rs = [r for r in records() if r["kind"] == kind and r["by"] == by]
        return max(rs, key=lambda r: r["id"]) if rs else None

    # Kept: A offers 2 berries for 3 wood stacked at its store; B accepts, stores the wood and
    # A pays. Each step is counted by the rules' hooks and each side is told.
    s.act(a, {"do": "offer_terms", "target": {"id": b}, "item": "berries", "qty": 2, "want": "wood", "want_qty": 3, "text": "stack it in my store"})
    offered = s.wait(lambda: record_of("agreement", a))
    s.expect("terms make an offered agreement record", offered["status"] == "offered" and offered["open"], offered)
    s.expect("the other side is told the terms", bool(s.wait(lambda: s.told(b, "proposes an agreement", "record"))))
    s.act(b, {"do": "accept", "target": {"id": a}})
    s.wait(lambda: record_of("agreement", a)["status"] == "agreed")
    s.expect("accepting makes it agreed and tells the proposer", bool(s.wait(lambda: s.told(a, "accepted your terms", "record"))))
    s.act(b, {"do": "store", "target": {"id": store}, "item": "wood", "qty": 3})
    owed = s.wait(lambda: s.told(a, "You owe them 2 berries", "record"), seconds=40)
    s.expect("work stored in the proposer's store counts and the debt is told", bool(owed),
             json.loads(record_of("agreement", a)["terms"]))
    s.act(a, {"do": "give", "target": {"id": b}, "item": "berries", "qty": 2})
    kept = s.wait(lambda: record_of("agreement", a)["status"] == "kept" and record_of("agreement", a), seconds=40)
    s.expect("paying keeps it on both sides", not kept["open"] and bool(s.told(b, "kept on both sides", "record")), kept)
    records("kept")

    # Broken: B offers 2 wood for 1 berry; A accepts; B delivers; A never pays.
    s.act(b, {"do": "offer_terms", "target": {"id": a}, "item": "wood", "qty": 2, "want": "berries", "want_qty": 1})
    s.wait(lambda: (record_of("agreement", b) or {}).get("status") == "offered")
    s.act(a, {"do": "accept", "target": {"id": b}})
    s.wait(lambda: record_of("agreement", b)["status"] == "agreed")
    s.act(b, {"do": "give", "target": {"id": a}, "item": "wood", "qty": 2})
    s.wait(lambda: json.loads(record_of("agreement", b)["terms"])["from_done"] == 2, seconds=30)
    broken = s.wait(lambda: record_of("agreement", b)["status"] == "broken" and record_of("agreement", b), seconds=hour_s * 3 + 20)
    s.expect("unpaid by the due hour, it is broken and both sides are told",
             bool(s.told(b, "they broke your agreement", "record")) and bool(s.told(a, "you broke your agreement", "record")), broken)

    # Lapsed and not taken: C and D agree and neither delivers; D's own terms are never taken up.
    s.act(c, {"do": "offer_terms", "target": {"id": d}, "item": "berries", "qty": 1, "want": "stone", "want_qty": 1})
    s.wait(lambda: record_of("agreement", c))
    s.act(d, {"do": "accept", "target": {"id": c}})
    s.wait(lambda: record_of("agreement", c)["status"] == "agreed")
    s.act(d, {"do": "offer_terms", "target": {"id": c}, "item": "stone", "qty": 1, "want": "fiber", "want_qty": 1})
    s.wait(lambda: s.wait(lambda: record_of("agreement", c)["status"] == "lapsed", seconds=hour_s * 3 + 20))
    s.expect("neither side delivering, it lapses and both are told",
             bool(s.told(c, "has lapsed", "record")) and bool(s.told(d, "has lapsed", "record")))
    s.wait(lambda: s.told(d, "did not take up your terms", "record"), seconds=hour_s * 3 + 20)
    s.expect("terms not accepted lapse and the proposer is told", True)

    # Demands: one paid with a give, one not paid. Refusing is not an act.
    s.call("grant_items", c, "berries", 3)
    s.act(a, {"do": "demand", "target": {"id": c}, "item": "berries", "qty": 2, "text": "the gate-due"})
    s.wait(lambda: s.told(c, "demands 2 berries of you", "record"))
    s.expect("a demand is told to its target, and onlookers see it", bool(s.wait(lambda: s.told(d, "demanded 2 berries of", "record"))))
    s.act(c, {"do": "give", "target": {"id": a}, "item": "berries", "qty": 2})
    met = s.wait(lambda: (record_of("demand", a) or {}).get("status") == "met" and record_of("demand", a), seconds=40)
    s.expect("a demand paid by a give is met and the demander told", bool(s.told(a, "paid the 2 berries you demanded", "record")), met)
    s.act(b, {"do": "demand", "target": {"id": d}, "item": "stone", "qty": 1})
    unpaid = s.wait(lambda: (record_of("demand", b) or {}).get("status") == "unpaid" and record_of("demand", b), seconds=hour_s * 2 + 20)
    s.expect("a demand not paid falls due unpaid; both are told",
             bool(s.told(b, "has not paid the 1 stone", "record")) and bool(s.told(d, "You did not pay", "record")), unpaid)
    records("after")
    s.expect("records are bounded: closed ones are dropped after their keep",
             bool(s.wait(lambda: not [r for r in records() if r["kind"] == "agreement" and r["by"] == a], seconds=hour_s * 3 + 30)))

    # Regard: the seed's stance records read by a relation filter. A resident of a community that
    # holds another as "rival town" waves at that town's resident, not at a neighbour.
    stances = [r for r in records("regard") if r["kind"] == "regard"]
    s.expect("the seed's regard records exist", len(stances) >= 10, len(stances))
    comm = {c["name"]: c["id"] for c in s.rows("SELECT id, name FROM community")}
    members = s.rows("SELECT community, member FROM membership")
    alive = {c["id"] for c in s.rows("SELECT id FROM character WHERE alive = true")}
    of = lambda name: [m["member"] for m in members if m["community"] == comm.get(name) and m["member"] in alive]
    brack, kettle = of("Brackenford"), of("Kettlebridge")
    s.expect("both towns have residents", len(brack) >= 2 and len(kettle) >= 1, (len(brack), len(kettle)))
    host, neighbour, rival = brack[0], brack[1], kettle[0]
    s.call("place_near", neighbour, host)
    s.call("place_near", rival, host)
    s.graph(rival, {"wait": 120})
    s.graph(neighbour, {"wait": 120})
    s.graph(host, {"first": [{"do": {"skill": "wave", "target": {"nearest": {"kind": "person", "relation": "rival town"}}}}, {"wait": 60}]})
    waved = s.wait(lambda: [r for r in s.rows(f"SELECT * FROM skill_use WHERE actor = {host}") if r["skill"] == "wave"], seconds=30)
    s.rows(f"SELECT * FROM skill_use WHERE actor = {host}", "regard-wave")
    s.expect("a relation filter reads the community's regard", any(r.get("target") == rival for r in waved), waved)
    s.call("install_script", (ROOT / "living/scripts/skills.rhai").read_text())


def answers(s):
    """Accept and decline name what they answer (docs/WORLD_RULES.md, "Answering"): a trade
    offer (`"offer": id`) or a proposal of terms (`"record": id`). Named, exactly that is taken
    or refused with the reason; without a name, accept takes what it always took (terms first,
    then the trade). Decline ends the offer or proposal, its maker is told (kind `record`) and
    an onlooker sees it."""
    a, b, c, d = s.people(4)
    for x in (b, c, d):
        s.call("place_near", x, a)
    s.call("grant_items", a, "berries", 6)
    s.call("grant_items", b, "wood", 6)

    def offer_of(maker):
        rows = [o for o in s.rows("SELECT * FROM trade_offer") if o["from"] == maker]
        return rows[0] if rows else None

    def proposal_of(maker, to):
        rs = [r for r in s.rows("SELECT * FROM record") if r["kind"] == "agreement" and r["by"] == maker]
        rs = [r for r in rs if any(p["party"] == to for p in s.rows(f"SELECT * FROM record_party WHERE record = {r['id']}"))]
        return max(rs, key=lambda r: r["id"]) if rs else None

    def refused(actor, words, since):
        return [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {actor}")
                if r["at_ms"] >= since and "did not work out" in r["text"] and words in r["text"]]

    def now():
        return s.rows("SELECT last_ms FROM clock")[0]["last_ms"]

    # A proposes terms to B and offers a trade too: B accepts the trade by its id, though the
    # terms stand (before, an accept toward A took the terms first).
    s.act(a, {"do": "offer_terms", "target": {"id": b}, "item": "berries", "qty": 2, "want": "wood", "want_qty": 3})
    terms = s.wait(lambda: proposal_of(a, b))
    s.act(a, {"do": "offer", "target": {"id": b}, "item": "berries", "qty": 2, "want": "wood", "want_qty": 1})
    trade = s.wait(lambda: offer_of(a))
    s.rows("SELECT * FROM trade_offer", "standing")
    wood0 = s.inventory(a).get("wood", 0)
    s.act(b, {"do": "accept", "target": {"id": a}, "offer": trade["id"]})
    s.wait(lambda: offer_of(a) is None, seconds=20)
    s.expect("accept with an offer id takes that trade, though terms stand",
             s.inventory(a, "after-named-accept").get("wood", 0) == wood0 + 1 and proposal_of(a, b)["status"] == "offered", proposal_of(a, b))

    # Wrong references are refused with the rules' reasons.
    t0 = now()
    s.act(b, {"do": "accept", "target": {"id": a}, "offer": trade["id"]})
    s.expect("an offer already taken is refused: gone", bool(s.wait(lambda: refused(b, "that offer is gone", t0), seconds=20)))
    s.act(a, {"do": "offer", "target": {"id": b}, "item": "berries", "qty": 1, "want": "wood", "want_qty": 1})
    first = s.wait(lambda: offer_of(a))
    s.act(a, {"do": "offer", "target": {"id": b}, "item": "berries", "qty": 3, "want": "wood", "want_qty": 1})
    s.wait(lambda: (offer_of(a) or {}).get("id", first["id"]) != first["id"])
    t0 = now()
    s.act(b, {"do": "accept", "target": {"id": a}, "offer": first["id"]})
    s.expect("an offer replaced since is refused with the new terms", bool(s.wait(lambda: refused(b, "they have changed their offer: now their 3 berries for your 1 wood", t0), seconds=20)))
    t0 = now()
    s.act(c, {"do": "accept", "target": {"id": a}, "offer": offer_of(a)["id"]})
    s.expect("someone else's offer is refused: not addressed to you", bool(s.wait(lambda: refused(c, "that offer is not addressed to you", t0), seconds=20)))
    t0 = now()
    s.act(b, {"do": "accept", "target": {"id": a}, "record": terms["id"] + 100000})
    s.expect("a proposal no longer there, with other terms standing, is refused with those terms",
             bool(s.wait(lambda: refused(b, "they have changed their terms: now you give 3 wood, they give 2 berries", t0), seconds=20)))
    t0 = now()
    s.act(a, {"do": "accept", "target": {"id": b}, "record": terms["id"]})
    s.expect("one's own proposal is refused: not addressed to you", bool(s.wait(lambda: refused(a, "that proposal is not addressed to you", t0), seconds=20)))

    # Decline the standing trade by its id: it ends, A is told, D (beside them) sees it.
    standing = offer_of(a)
    t0 = now()
    s.act(b, {"do": "decline", "target": {"id": a}, "offer": standing["id"]})
    s.wait(lambda: offer_of(a) is None, seconds=20)
    told = s.wait(lambda: s.told(a, "declined your offer of 3 berries for 1 wood.", "record"), seconds=20)
    s.expect("decline ends the offer and its maker is told", offer_of(a) is None and bool(told), told)
    seen = s.wait(lambda: s.told(d, "turned down", "record"), seconds=20)
    s.expect("an onlooker sees the decline", bool(seen), seen)
    s.expect("the decline is the decliner's own outcome", bool(s.wait(lambda: s.told(b, "eclined", "act"), seconds=10)),
             s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {b}", "decliner"))

    # Decline the terms by their record id: declined, closed, the proposer told.
    s.act(b, {"do": "decline", "target": {"id": a}, "record": terms["id"]})
    closed = s.wait(lambda: (lambda r: r if r and r["status"] == "declined" else None)(proposal_of(a, b)), seconds=20)
    s.expect("decline closes the proposal as declined", closed and not closed["open"], closed)
    s.expect("the proposer is told the terms were declined", bool(s.wait(lambda: s.told(a, "declined your terms: you give 2 berries, they give 3 wood.", "record"), seconds=20)))
    t0 = now()
    s.act(b, {"do": "accept", "target": {"id": a}, "record": terms["id"]})
    s.expect("a declined proposal cannot be accepted after", bool(s.wait(lambda: refused(b, "that proposal was declined", t0), seconds=20)))
    t0 = now()
    s.act(b, {"do": "accept", "target": {"id": a}, "record": terms["id"] + 100000})
    s.expect("a proposal that does not exist, nothing standing, is refused: gone", bool(s.wait(lambda: refused(b, "that proposal is gone", t0), seconds=20)))
    t0 = now()
    s.act(b, {"do": "decline", "target": {"id": a}})
    s.expect("decline with nothing standing is refused", bool(s.wait(lambda: refused(b, "they have no standing offer for you", t0), seconds=20)))

    # Without a reference, accept is what it was: terms first (C proposes to D and offers a
    # trade; D's plain accept agrees the terms and leaves the trade standing).
    s.call("grant_items", c, "berries", 2)
    s.act(c, {"do": "offer_terms", "target": {"id": d}, "item": "berries", "qty": 1, "want": "stone", "want_qty": 1})
    s.wait(lambda: proposal_of(c, d))
    s.act(c, {"do": "offer", "target": {"id": d}, "item": "berries", "qty": 1, "want": "wood", "want_qty": 1})
    s.wait(lambda: offer_of(c))
    s.act(d, {"do": "accept", "target": {"id": c}})
    agreed = s.wait(lambda: (lambda r: r if r and r["status"] == "agreed" else None)(proposal_of(c, d)), seconds=20)
    s.expect("a plain accept takes the terms first, as before", agreed and offer_of(c) is not None, {"terms": agreed, "trade": offer_of(c)})
    # And a plain decline then ends the trade (the one a plain accept would take now).
    s.act(d, {"do": "decline", "target": {"id": c}})
    s.wait(lambda: offer_of(c) is None, seconds=20)
    s.expect("a plain decline ends what a plain accept would take", offer_of(c) is None and bool(s.told(c, "declined your offer of 1 berries for 1 wood.", "record")))
    s.rows("SELECT * FROM record", "records-after")


# Remains lie 3 game hours here: 90 real seconds on the 12-minute day (`remains_h`, turned into
# real time for the world's day by the engine).
REMAINS_H = 3


def carcass_law(kind):
    """What the shipped script gives a kind's remains: the `carcass` trait of its row in
    `kinds()` (read by the `carcass(kind)` law)."""
    src = (ROOT / "living/scripts/skills.rhai").read_text()
    m = re.search(r'name:\s*"%s"[^\n]*?carcass:\s*#\{([^}]*)\}' % kind, src)
    return {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", m.group(1))} if m else {}


def remains(s):
    """Every death leaves remains with the `carcass` law's items; a kill feeds nobody by itself;
    any creature beside the remains takes from them; they are gone after `remains_h` (game hours); a wander
    keeps its heading (the `motion` law's `wander_turn`, `wander_keep_s`). Needs a world with deer and wolves (stage1-acts)."""
    src = compose((ROOT / "living/scripts/skills.rhai").read_text(), {"remains_h": f"fn remains_h(kind) {{ {REMAINS_H}.0 }}"})
    s.call("install_script", src)
    for c in s.rows("SELECT id FROM character WHERE alive = true"):
        s.graph(c["id"], {"wait": 600})
    deer = [c["id"] for c in s.rows("SELECT id FROM character WHERE kind = 'deer' AND alive = true")]
    wolves = [c["id"] for c in s.rows("SELECT id FROM character WHERE kind = 'wolf' AND alive = true")]
    s.expect("world has two deer and three wolves", len(deer) >= 2 and len(wolves) >= 3, {"deer": deer, "wolves": wolves})
    law = carcass_law("deer")
    s.expect("the carcass law gives a deer meat and hide", law.get("meat", 0) > 0 and law.get("hide", 0) > 0, law)

    def remains_of(victim, label=None):
        rows = s.rows(f"SELECT * FROM structure WHERE kind = 'remains' AND owner = {victim}", label)
        return rows[0] if rows else None

    def held(structure):
        return {r["item"]: r["qty"] for r in s.rows(f"SELECT item, qty FROM inventory WHERE owner = {(1 << 40) | structure}")}

    # A death that is no kill (an admin's) leaves remains too, due under the law.
    a = deer[0]
    s.call("kill", a, "verify-core remains")
    r_a = s.wait(lambda: remains_of(a, "admin-death-remains"), seconds=10)
    s.expect("a deer's death leaves remains holding the carcass law's items", held(r_a["id"]) == law, held(r_a["id"]))
    rot = s.rows(f"SELECT * FROM rot WHERE structure = {r_a['id']}", "admin-death-rot")
    s.expect("its remains are due after the remains_h law, in real time for the day", len(rot) == 1 and rot[0]["due_ms"] - r_a["built_ms"] == REMAINS_H * s.rows("SELECT day_ms FROM world")[0]["day_ms"] // 24, rot)

    # A wolf's kill: the carcass goes into the remains, not into the killer's pack.
    b, killer, other, walker = deer[1], wolves[0], wolves[1], wolves[2]
    s.call("place_near", killer, b)
    before = s.inventory(killer, "killer-before")
    s.graph(killer, {"first": [{"do": "attack", "target": {"id": b}}, {"wait": 1}]})
    r_b = s.wait(lambda: remains_of(b, "kill-remains"), seconds=150, every=1)
    s.graph(killer, {"wait": 600})
    victim = s.rows(f"SELECT alive, cause FROM character WHERE id = {b}", "kill-victim")[0]
    s.expect("the wolf killed the deer", not victim["alive"] and "killed by" in victim["cause"], victim)
    after = s.inventory(killer, "killer-after")
    s.expect("a kill puts nothing in the killer's pack", after.get("meat", 0) == before.get("meat", 0) and after.get("hide", 0) == before.get("hide", 0), {"before": before, "after": after})
    s.expect("the kill's remains hold the carcass law's items", held(r_b["id"]) == law, held(r_b["id"]))

    # The killer and another wolf both take meat from the one carcass.
    s.call("place_near", other, killer)
    for w in (killer, other):
        s.graph(w, {"first": [{"if": {"not": {"has": {"item": "meat"}}}, "then": {"do": "take", "target": {"nearest": "remains"}, "item": "meat"}}, {"wait": 2}]})
    s.wait(lambda: all(s.inventory(w).get("meat", 0) >= 1 for w in (killer, other)), seconds=30, every=1)
    left = held(r_b["id"])
    s.expect("two wolves take meat from one kill", left.get("meat", 0) == law["meat"] - 2, {"left": left, "killer": s.inventory(killer, "killer-took"), "other": s.inventory(other, "other-took")})
    for w in (killer, other):
        s.graph(w, {"wait": 600})

    # A wander keeps roughly its heading between waits (the wander laws).
    s.graph(walker, {"seq": [{"do": "wander"}, {"wait": 3}]})
    stops, last = [], None
    end = time.monotonic() + 75
    while time.monotonic() < end:
        b_ = s.rows(f"SELECT x, y, vx, vy FROM body WHERE id = {walker}")[0]
        if b_["vx"] == 0 and b_["vy"] == 0 and (last is None or math.dist(last, (b_["x"], b_["y"])) > 1.5):
            last = (b_["x"], b_["y"])
            stops.append(last)
        time.sleep(0.5)
    s.graph(walker, {"wait": 600})
    legs = [math.atan2(q[1] - p_[1], q[0] - p_[0]) for p_, q in zip(stops, stops[1:])]
    turns = [abs((b2 - b1 + math.pi) % (2 * math.pi) - math.pi) for b1, b2 in zip(legs, legs[1:])]
    kept = sum(t <= 1.6 for t in turns)
    (s.out / f"{s.name}-wander.json").write_text(json.dumps({"stops": stops, "turns_rad": turns}, indent=2) + "\n")
    # Uniform random headings would turn by at most 1.6 rad about half the time.
    s.expect("a wander keeps its heading between waits", len(turns) >= 5 and kept >= 0.8 * len(turns), {"turns": len(turns), "within_1.6_rad": kept})

    # Remains are gone once due, with what was left in them (housekeeping runs each minute).
    due = rot[0]["due_ms"]
    wait_s = max(0, due - s.rows("SELECT last_ms FROM clock")[0]["last_ms"]) / 1000 + 70
    s.wait(lambda: remains_of(a) is None, seconds=wait_s + 30, every=5)
    s.expect("remains are gone after their time, with their items and rot row",
             remains_of(a, "expired") is None and not held(r_a["id"]) and not s.rows(f"SELECT * FROM rot WHERE structure = {r_a['id']}"), r_a)
    s.call("install_script", (ROOT / "living/scripts/skills.rhai").read_text())


def family_laws(s):
    """The laws of starting a family and of the longing for a child (docs/TRIALS.md, "Births
    that keep a settlement's numbers"). An installed overlay sets `conceive_roof` true and
    `conceive_food` 6: two fresh adults in the open are refused for the roof, then (by a
    shelter) for the food they carry, then, carrying 3 berries each, start a family. Then laws()
    with `longing_after_min` 0.1 and `longing_food` 3: by day, a calm adult carrying 4 berries
    feels the longing for a child and one carrying nothing does not, until `longing_food` is 0.
    The shipped script is installed again at the end."""
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    a, b, c, d = s.people(4)
    built = [(r["x"], r["y"]) for r in s.rows("SELECT x, y FROM structure", "structures")]
    line = open_line(s, avoid=built)
    (s.out / f"{s.name}-line.json").write_text(json.dumps(line) + "\n")
    for who, at in ((a, 0), (b, 1), (c, 8), (d, 12)):
        s.call("place_at", who, *line[at])
        s.graph(who, {"first": [{"do": "rest"}]})
    try:
        s.call("install_script", compose(shipped, {"conceive_food": "fn conceive_food() { 6 }", "conceive_roof": "fn conceive_roof() { true }"}))
        for who in (a, b):
            for item, qty in s.inventory(who).items():
                if qty:
                    s.act(who, {"do": "drop", "item": item, "qty": qty})
        time.sleep(3)
        s.expect("the two carry no food", not any(s.inventory(a).values()) and not any(s.inventory(b).values()), [s.inventory(a), s.inventory(b)])
        s.act(a, {"do": "conceive", "target": {"id": b}})
        roof = s.wait(lambda: s.told(a, "not under a roof"), seconds=20)
        s.expect("conceive_roof: refused in the open", bool(roof), roof)
        s.call("place_structure", a, "shelter")
        s.act(a, {"do": "conceive", "target": {"id": b}})
        food = s.wait(lambda: s.told(a, "not enough food put by"), seconds=20)
        s.expect("conceive_food: refused by a shelter with no food carried", "carry 0, a family needs 6" in food[-1]["text"], food[-1])
        s.call("grant_items", a, "berries", 3)
        s.call("grant_items", b, "berries", 3)
        s.act(a, {"do": "conceive", "target": {"id": b}})
        time.sleep(3)
        s.act(b, {"do": "conceive", "target": {"id": a}})
        expecting = s.wait(lambda: s.rows(f"SELECT * FROM expecting WHERE a = {a} OR b = {a}", "expecting"), seconds=20)
        s.expect("with 6 food between them and a roof, they start a family", bool(expecting), expecting)
        longing = shipped.replace("longing_after_min: 20.0, longing_food: 0.0", "longing_after_min: 0.1, longing_food: LONGING_FOOD")
        s.expect("the shipped laws() has the longing values", longing != shipped)
        # Empty-handed before the law can make the longing felt (it is a rising edge: felt
        # once while it holds, so a moment with food in hand would already count).
        for item, qty in s.inventory(d).items():
            if qty:
                s.act(d, {"do": "drop", "item": item, "qty": qty})
        s.wait(lambda: not any(s.inventory(d).values()), seconds=20)
        s.call("grant_items", c, "berries", 4)
        s.call("install_script", longing.replace("LONGING_FOOD", "3.0"))
        hour, day = world_hour(s)
        if hour >= 19.5 or hour < 6:
            wait_s = ((6 - hour) % 24) / 24 * day / 1000 + 5
            print(f"Waiting {wait_s:.0f} s for day (world hour {hour:.1f}).", flush=True)
            time.sleep(wait_s)
        felt = s.wait(lambda: s.told(c, "You long for", kind="feeling"), seconds=90, every=2)
        s.expect("longing_food 3: an adult carrying 4 food longs for a child", bool(felt), felt)
        time.sleep(20)
        s.expect("longing_food 3: an adult carrying nothing does not", not s.told(d, "You long for", kind="feeling"), s.inventory(d))
        s.call("install_script", longing.replace("LONGING_FOOD", "0.0"))
        felt = s.wait(lambda: s.told(d, "You long for", kind="feeling"), seconds=90, every=2)
        s.expect("longing_food 0: the same adult then longs for a child", bool(felt), felt)
        s.rows(f"SELECT * FROM experience WHERE observer = {c} OR observer = {d}", "longing-experiences")
    finally:
        s.call("install_script", shipped)


def tile_grid(s):
    """This world's tiles: (width, height, bytes), and whether a tile can be walked."""
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
    return W, H, lambda x, y: 0 <= x < W and 0 <= y < H and tiles[int(y) * W + int(x)] not in (2, 4, 7, 8, 9)


def open_ray(s, length):
    """Points 0, 1, ..., `length` metres along a straight ray in any of 32 directions, over open
    ground with nothing that blocks sight on it or beside it (a small map has no long east-west
    line)."""
    W, H, walk = tile_grid(s)
    for k in range(32):
        t = k * math.pi / 16
        dx, dy = math.cos(t), math.sin(t)
        for y in range(4, H - 4, 3):
            for x in range(4, W - 4, 3):
                pts = [(x + 0.5 + dx * i, y + 0.5 + dy * i) for i in range(length + 1)]
                if all(walk(px + ox, py + oy) for px, py in pts for ox, oy in ((0, 0), (-dy, dx), (dy, -dx))):
                    return pts
    raise RuntimeError(f"no open {length} m ray on this map")


def law_number(src, fn, key=None):
    """A number a law gives, read from the overlay's source (`fn known_within() { 24.0 }`, or
    one arm of `sight_in`)."""
    body = re.search(r"fn " + fn + r"\([^)]*\) \{(.*?)\}\n", src, re.S).group(1)
    arm = (r"_ => " if key == "_" else r'"' + key + r'" => ') if key else ""
    m = re.search(arm + r"([0-9.]+)", body)
    return float(m.group(1))


def laws(s):
    """A world created from a seed with its own laws (a `laws_file` overlay, docs/CULLET_RULES.md;
    the `cullet-laws` seed): its day length is the seed's, its laws are the composed overlay, its
    need rates are written per game hour and turned into real time for its day, and its sight is
    the overlay's: by day far (figures seen to the day sight), names only within the knowing
    distance, and at night the dark's sight, lamplight and a carried light. Then a body outside
    on an ordinary night. Waits for the real night (no clock is changed)."""
    w = s.rows("SELECT * FROM world", "world")[0]
    seed = json.loads((ROOT / "living/seeds" / f"{json.loads((s.out / 'state.json').read_text())['seed']}.json").read_text())
    src = (ROOT / "living/seeds" / seed["laws_file"]).read_text()
    s.expect("the world's day is the seed's day_minutes", w["day_ms"] == round(seed["day_minutes"] * 60000), {"day_ms": w["day_ms"], "day_minutes": seed["day_minutes"]})
    script = s.rows("SELECT name, revision, source FROM script")[0]
    over = script["source"].split("// ---- floor overlay ----", 1)
    s.expect("the installed script is the shipped one with the seed's laws composed over it",
             len(over) == 2 and over[1].strip() == src.strip() and "fn base_rates(a)" in over[0] and "fn base_senses(a)" in over[0], {"revision": script["revision"]})
    hour_ms = w["day_ms"] / 24
    day, dark, torch = law_number(src, "sight_in", "day"), law_number(src, "sight_in", "_"), law_number(src, "sight_in", "torch")
    known, lamp_seen, carried = law_number(src, "known_within"), law_number(src, "lamplight_seen"), law_number(src, "carried_light_seen")

    # Rates: a person awake by day under the law's per-hour numbers, in real minutes.
    a = s.people(1)[0]
    s.wait(lambda: s.vitals(a)["hunger_rate"] > 0)
    v = s.vitals(a, "awake-vitals")
    g = s.rows(f"SELECT genes FROM genome WHERE id = {a}")
    genes = json.loads(g[0]["genes"]) if g else {}
    per_min = 60000 / hour_ms
    want_h = law_number(src, "hunger_awake") * per_min * genes.get("appetite", 1.0)
    want_e = -abs(law_number(src, "energy_awake")) * per_min / genes.get("endurance", 1.0)
    s.expect("need rates are the law's per game hour, in real time for this day", abs(v["hunger_rate"] - want_h) < 0.02 and abs(v["energy_rate"] - want_e) < 0.02,
             {"hunger_rate": v["hunger_rate"], "want": want_h, "energy_rate": v["energy_rate"], "want_energy": want_e, "genes": genes})

    # A player and figures on one open line.
    st = json.loads((s.out / "state.json").read_text())
    verify = [str(ROOT / ".agents/skills/verify/scripts/verify.py")]
    # A player of an earlier attempt on this run keeps its living character.
    subprocess.run(["python3", *verify, "player", "--run", st["run"], "join", "Watcher"], check=False, capture_output=True)
    st = json.loads((s.out / "state.json").read_text())
    viewer = st["identity"]
    # A call as the player hands back a character the world's minds took over meanwhile.
    subprocess.run(["python3", *verify, "player", "--run", st["run"], "move", "0", "0"], check=False, capture_output=True)
    me = s.wait(lambda: next(iter(s.rows(f"SELECT id FROM character WHERE controller = 0x{viewer}")), None))["id"]
    span = int(day) + 6
    line = open_ray(s, span)
    (s.out / f"{s.name}-line.json").write_text(json.dumps(line) + "\n")
    near, mid, far, beyond = 10, int(known) + 6, int(day) - 2, int(day) + 4
    figures = s.people(4)
    for f in figures:
        s.graph(f, {"wait": 300})
    talker = figures[0]
    name = s.rows(f"SELECT name FROM character WHERE id = {talker}")[0]["name"]

    def place(at):
        s.call("place_at", me, *line[0])
        for f, d in zip(figures, at):
            x, y = d if isinstance(d, tuple) else line[d]
            s.call("place_at", f, x, y)

    def scene(label, seconds=3):
        # A call as the player keeps its person present: after the `takeover_s` law (30 s)
        # without one the world's minds take the character over and nobody is swept for it.
        subprocess.run(["python3", *verify, "player", "--run", st["run"], "move", "0", "0"], check=False, capture_output=True)
        time.sleep(seconds)
        seen = {r["body"] for r in s.rows(f"SELECT body FROM perceived WHERE viewer = 0x{viewer}", f"perceived-{label}")}
        shown = {r["body"]: r for r in s.rows(f"SELECT body, name, label, band FROM projected WHERE viewer = 0x{viewer}", f"projected-{label}")}
        return seen, shown

    def hour():
        return world_hour(s)[0]
    dark_now = 21.0 <= hour() or hour() < 5.0
    if dark_now:
        # Started at night (a rerun): the day checks need the world's morning.
        print("SKIP the day checks: it is night; launch afresh for them", flush=True)
    else:
        # The talker says its name beside the player: the player knows it from then on.
        place([3, mid, far, beyond])
        s.graph(talker, {"seq": [{"say": f"I am {name}."}, {"wait": 300}]})
        s.wait(lambda: s.rows(f"SELECT * FROM acquaintance WHERE observer = {me} AND known = {talker}"), seconds=20)
        seen, shown = scene("day")
        s.expect(f"by day figures are seen to {day:g} m", {talker, figures[1], figures[2]} <= seen and figures[3] not in seen,
                 {"seen": sorted(seen), "at": {figures[1]: mid, figures[2]: far, figures[3]: beyond}})
        s.expect(f"a figure beyond {known:g} m is not known (no name, no health band)", shown.get(figures[1], {}).get("band") == 255 and not shown.get(figures[1], {}).get("name"), shown.get(figures[1]))
        place([int(known) - 4, mid, far, beyond])
        seen, shown = scene("known-near", 2)
        s.expect(f"someone one knows is named within {known:g} m", shown.get(talker, {}).get("name") == name and shown.get(talker, {}).get("band", 255) != 255, shown.get(talker))
        place([int(known) + 4, mid, far, beyond])
        seen, shown = scene("known-far", 2)
        s.expect(f"and only a figure beyond {known:g} m", talker in seen and shown.get(talker, {}).get("name") == "" and shown.get(talker, {}).get("label") != name, shown.get(talker))

    # The night: fully dark an hour after dusk.
    print("Waiting for full dark (21:00 by the world's clock); no clock is changed.", flush=True)
    s.wait(lambda: 21.0 <= hour() or hour() < 5.0, seconds=int(16 * hour_ms / 1000) + 60, every=10)
    # The lamp and an open line of sight from it.
    lamp = next(iter(s.rows("SELECT x, y FROM structure WHERE kind = 'lamp'")), None)
    W, H, walk = tile_grid(s)
    def clear(a, b):
        n = int(math.dist(a, b) * 2) + 1
        return all(walk(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1))
    lit = None
    if lamp:
        far_lit = (lamp_seen + dark) / 2
        for k in range(32):
            t = k * math.pi / 16
            o = (lamp["x"] + 1.5 * math.cos(t), lamp["y"] + 1.5 * math.sin(t))
            e = (o[0] + far_lit * math.cos(t), o[1] + far_lit * math.sin(t))
            if clear(o, e) and walk(*o) and walk(*e):
                lit = (o, e)
                break
    s.expect("the seed has a lamp with an open line of sight from it", lit is not None, lamp)
    gap = int((dark + torch) / 2)
    s.call("grant_items", figures[2], "torch", 1)
    place([gap - 4, gap + 2, int(carried) - 4, beyond])
    seen, shown = scene("night")
    s.expect(f"in the dark one sees {dark:g} m: {gap - 4} m seen, {gap + 2} m not", figures[0] in seen and figures[1] not in seen, {"seen": sorted(seen)})
    s.expect(f"a figure carrying a light is seen from {carried:g} m", figures[2] in seen, {"seen": sorted(seen), "at": int(carried) - 4})
    (o, e) = lit
    s.call("place_at", figures[3], *o)
    s.call("place_at", me, *e)
    seen, shown = scene("lamplight")
    d = math.dist(o, e)
    s.expect(f"someone standing in lamplight is seen from {lamp_seen:g} m ({d:.0f} m off, beyond the dark's {dark:g})", figures[3] in seen, {"seen": sorted(seen), "dist": d})
    # The same distance from the player the other way, far from any light: not seen.
    mirror = (2 * e[0] - o[0], 2 * e[1] - o[1])
    if walk(*mirror) and clear(e, mirror):
        s.call("place_at", figures[3], *mirror)
        seen, shown = scene("dark-same-distance")
        s.expect("the same distance off in the dark, away from the lamp, is not seen", figures[3] not in seen, {"seen": sorted(seen), "at": mirror})
    else:
        print("SKIP the mirrored dark spot is not open ground with a clear line", flush=True)

    # An ordinary night outside: no cold harm and no cold tiring under these laws.
    out = s.people(1)[0]
    s.graph(out, {"first": [{"do": "rest"}]})
    s.wait(lambda: s.vitals(out)["rate_key"] & 2, seconds=60)
    night = s.vitals(out, "night-out")
    s.expect("an ordinary night outside costs no health", night["hp_rate"] >= 0, night)


def audience(s):
    """Who heard a line (the `speech_audience` law; perceive.rs `speak`, the private `audience`
    table; on by default since 2026-11-11). With the law turned off a line writes nothing. On,
    a line writes one row: each person who heard it (within hearing, not beyond), the distance to
    them and how far off the speaker's facing they stood; a row older than 60 s is deleted by the
    next line. The shipped script is installed again at the end."""
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    s.expect("the shipped laws() keeps who heard a line", shipped.count("speech_audience: true,") == 1)
    a, b, c, far = s.people(4)
    line = open_line(s)
    (s.out / f"{s.name}-line.json").write_text(json.dumps(line) + "\n")
    # West to east: the speaker, one 1 m east, one 4 m east, one 13 m east (beyond hearing).
    for who, at in ((a, 1), (b, 2), (c, 5), (far, 14)):
        s.call("place_at", who, *line[at])
        s.graph(who, {"wait": 120})
    s.act(a, {"do": "face", "target": {"id": c}})
    time.sleep(3)
    thought = {"kind": "verify", "summary": "verify-core audience", "detail": "", "latency_ms": 0, "tokens": 0, "model": "", "reference": "verify-core"}
    say = lambda text: (s.call("mind_say", a, text, 0, "", 0, thought), time.sleep(2.2))
    hearers = lambda row: {(h["id"] if isinstance(h, dict) else h[0]): (h["d"], h["off"]) if isinstance(h, dict) else (h[1], h[2]) for h in row["hearers"]}
    try:
        s.call("install_script", shipped.replace("speech_audience: true,", "speech_audience: false,"))
        time.sleep(2.2)
        say("verify audience while the law is off")
        s.expect("law off: a line writes no audience row", not s.rows("SELECT * FROM audience", "audience-off"))
        s.call("install_script", shipped)
        time.sleep(2.2)
        say("verify audience while the law is on")
        rows = s.rows(f"SELECT * FROM audience WHERE speaker = {a}", "audience-on")
        s.expect("law on: one row for the line, said to no one", len(rows) == 1 and rows[0]["to"] == 0, rows)
        h = hearers(rows[0])
        s.expect("the hearers within hearing are in it, the one beyond is not", b in h and c in h and far not in h, h)
        s.expect("distances to the hearers", abs(h[b][0] - 1.0) < 0.4 and abs(h[c][0] - 4.0) < 0.4, h)
        s.expect("both stand ahead of the speaker, who faces east", h[b][1] < 0.35 and h[c][1] < 0.35, h)
        time.sleep(61)
        say("verify audience a minute later")
        later = s.rows(f"SELECT * FROM audience WHERE speaker = {a}", "audience-later")
        s.expect("a row older than a minute is deleted by the next line", [r["id"] for r in later] != [rows[0]["id"]] and rows[0]["id"] not in [r["id"] for r in later] and len(later) == 1, later)
    finally:
        s.call("install_script", shipped)


THOUGHT = {"kind": "deliberate", "summary": "verify-core say scene", "detail": "", "latency_ms": 0, "tokens": 0, "model": "fake", "reference": ""}


def say(s):
    """A graph's `say` to a person by id speaks, in every written form and through both install
    paths (admin `set_behavior`, and `mind_install` as a mind delivers it), like a `do` to the
    same id. A line that cannot be said yet waits for the speaker's turn instead of being lost:
    two installs back to back, or two lines in one sequence, are both spoken (before
    fix-graph-say-id the 2 s speaking limit refused the second, and the node's 45 s mark, set
    before speaking, then skipped it silently). A say that cannot be spoken (its listener out of
    sight) tells the speaker why, as other failed leaves do. A say node repeated in a looping
    graph is still paced to once per 45 s."""
    a, b, far = s.people(3)
    line = open_line(s)
    s.call("place_at", a, *line[4])
    s.call("place_at", b, *line[7])
    s.call("place_at", far, line[0][0] + 80, line[0][1])
    (s.out / f"{s.name}-cast.json").write_text(json.dumps({"speaker": a, "listener": b, "far": far, "hour": world_hour(s)}, indent=2) + "\n")
    hold = {"wait": 60}
    n = [0]

    def now():
        return s.rows("SELECT last_ms FROM clock")[0]["last_ms"]

    def lines(t0, label=None):
        return [r for r in s.rows(f"SELECT * FROM chronicle WHERE kind = 'speech' AND a = {a}", label) if r["at_ms"] >= t0]

    def install(path, node):
        if path == "set_behavior":
            s.graph(a, node)
        else:
            s.call("mind_install", a, json.dumps(node), "verify say", "", 0, 0, THOUGHT)
            s.rows(f"SELECT * FROM brain WHERE id = {a}", f"installed-graph-{a}-{time.time_ns()}")

    def heard(text, t0, seconds=8):
        try:
            return s.wait(lambda: [r for r in lines(t0) if text in r["text"]], seconds=seconds)
        except TimeoutError:
            return []

    forms = {
        "canonical": lambda t, to: {"say": {"text": t, "to": to}},
        "flat": lambda t, to: {"say": t, "to": to},
        "do": lambda t, to: {"do": "say", "text": t, "target": to},
        "do-object": lambda t, to: {"do": {"skill": "say", "text": t, "to": to}},
    }
    targets = {"id": {"id": b}, "bare-id": b, "nearest": {"nearest": {"kind": "person"}}}
    for path in ("set_behavior", "mind_install"):
        for form, make in forms.items():
            for tname, to in targets.items():
                n[0] += 1
                text = f"Morning, line {n[0]} ({form}, {tname}, {path})."
                t0 = now()
                install(path, {"seq": [make(text, to), hold]})
                got = heard(text, t0)
                want_b = b if tname != "nearest" else None
                s.expect(f"{path} {form} to {tname} speaks", got and (want_b is None or got[0]["b"] == want_b), got[:1], fatal=False)
                time.sleep(2.5)

    # A do to the same id (the comparison in the report): wave, and strike where the seed has it.
    t0 = now()
    s.graph(a, {"seq": [{"do": "wave", "target": {"id": b}}, hold]})
    time.sleep(4)
    uses = [u for u in s.rows(f"SELECT * FROM skill_use WHERE actor = {a}", "wave-uses") if u["at_ms"] >= t0]
    s.expect("do wave to the same id acts", any(u["skill"] == "wave" and u["target"] == b for u in uses), uses[:2], fatal=False)

    # Two installs back to back: the second line comes within the speaking limit.
    first, second = "Back to back, first.", "Back to back, second."
    t0 = now()
    s.graph(a, {"seq": [{"say": {"text": first, "to": {"id": b}}}, hold]})
    s.graph(a, {"seq": [{"say": {"text": second, "to": {"id": b}}}, hold]})
    s.expect("back-to-back installs: the first line is spoken", heard(first, t0), lines(t0)[:2], fatal=False)
    s.expect("back-to-back installs: the second line is spoken too", heard(second, t0, 10), lines(t0, "back-to-back")[:3], fatal=False)
    time.sleep(2.5)

    # Two lines in one sequence.
    one, two = "Two lines: hello.", "Two lines: welcome to town."
    t0 = now()
    s.graph(a, {"seq": [{"say": {"text": one, "to": {"id": b}}}, {"say": {"text": two, "to": {"id": b}}}, hold]})
    s.expect("a sequence of two lines speaks the first", heard(one, t0), lines(t0)[:2], fatal=False)
    s.expect("a sequence of two lines speaks the second", heard(two, t0, 10), lines(t0, "two-lines")[:3], fatal=False)
    time.sleep(2.5)

    # Ids are not words: a line naming people by the `#<id>` a mind is shown them by is heard as
    # the speaker refers to them (`normalize::spoken_without_ids`, applied by `speech::speak`).
    # r2e's minds said three such lines (docs/TRIALS.md).
    idline = f"Watch out, #{b} is here, and the archer #{far} too."
    t0 = now()
    install("mind_install", {"seq": [{"say": {"text": idline, "to": {"id": b}}}, hold]})
    got = heard("Watch out,", t0)
    said_text = got[0]["text"] if got else ""
    s.expect("a line naming people by id is spoken without the ids", bool(got) and f"#{b}" not in said_text and f"#{far}" not in said_text and "and the archer too." in said_text, got[:1], fatal=False)
    told_b = [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {b}", "id-line-heard") if r["at_ms"] >= t0 and "Watch out," in r["text"]]
    s.expect("the listener hears it without the ids", len(told_b) >= 1 and all(f"#{b}" not in r["text"] and f"#{far}" not in r["text"] for r in told_b), told_b[:2], fatal=False)
    kept = [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {a}", "id-line-kept") if r["at_ms"] >= t0 and r["kind"] == "spoken_as"]
    s.expect("the speaker keeps what it wrote beside what was said (spoken_as)", len(kept) == 1 and idline in kept[0]["text"] and "and the archer too." in kept[0]["text"], kept, fatal=False)
    time.sleep(2.5)

    # Out of sight: not spoken, and the speaker is told why.
    lost = "Can you hear me over there?"
    t0 = now()
    s.graph(a, {"seq": [{"say": {"text": lost, "to": {"id": far}}}, hold]})
    time.sleep(5)
    s.expect("a line to someone out of sight is not spoken", not [r for r in lines(t0) if lost in r["text"]], lines(t0)[:2], fatal=False)
    told = [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {a}", "out-of-sight-feedback") if r["kind"] == "own" and r["at_ms"] >= t0 and lost in r["text"]]
    s.expect("the speaker is told the line could not be said", len(told) == 1, told, fatal=False)
    time.sleep(2.5)

    # Pacing: a say in a looping graph speaks once per 45 s, not every pass.
    paced = "Still here, still here."
    t0 = now()
    s.graph(a, {"first": [{"seq": [{"say": {"text": paced, "to": {"id": b}}}, {"wait": 2}]}]})
    time.sleep(12)
    said = [r for r in lines(t0, "paced") if paced in r["text"]]
    s.expect("a looping say is paced (spoken once in 12 s)", len(said) == 1 and " (×" not in said[0]["text"], said, fatal=False)

    if any(c["skill"] == "strike" for c in s.rows("SELECT skill FROM skill_card")):
        t0 = now()
        s.graph(a, {"seq": [{"do": "strike", "target": {"id": b}}, hold]})
        time.sleep(4)
        uses = [u for u in s.rows(f"SELECT * FROM skill_use WHERE actor = {a}", "strike-uses") if u["at_ms"] >= t0]
        s.expect("do strike to the same id acts", any(u["skill"] == "strike" and u["target"] == b for u in uses), uses[:2], fatal=False)
    s.graph(a, {"wait": 120})
    s.rows(f"SELECT * FROM experience WHERE observer = {a}", "speaker-experience")
    s.rows(f"SELECT * FROM chronicle WHERE kind = 'speech' AND a = {a}", "speech")
    # Off the shared open line: later scenes (doing) count who stands near its west end.
    for k, who in enumerate((a, b)):
        s.call("place_at", who, line[0][0] + 60 + 2 * k, line[0][1] + 40)



def alarms(s):
    """A body's alarms are the world's `status_of` law's (docs/WORLD_RULES.md, "The body: meters
    and statuses"): an overlay adds a status with an alarm to every body; a person the minds hold
    is told it once while it lasts (a `body` line), asked to think with its words ("Your body:
    …"), and told again only after it has ended and begun again. A meter naming a field the vitals
    row lacks is refused at install. The shipped script is installed again at the end."""
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    word = "You feel the verify alarm."
    status = 'fn status_of(a) { let out = base_status_of(a); out.push(#{ name: "verify", tone: "warn", text: "Verify", alarm: "%s", salience: 0.6, think: "always" }); out }' % word
    on = compose(shipped, {"status_of": status})
    a = s.people(1)[0]
    try:
        s.expect("the shipped law gives no such alarm", not s.told(a, word, "body"))
        s.call("install_script", on)
        s.wait(lambda: s.told(a, word, "body"), seconds=30)
        time.sleep(6)
        once = s.told(a, word, "body")
        s.expect("an alarm the law gives is told once while it lasts", len(once) == 1, once)
        reasons = s.rows(f"SELECT reason FROM deliberation WHERE actor = {a}", "alarm-requests")
        s.expect("think: always asks the mind to think, in the alarm's words", any(f"Your body: {word}" in r["reason"] for r in reasons), reasons)
        s.call("install_script", shipped)
        time.sleep(5)
        s.call("install_script", on)
        s.wait(lambda: len(s.told(a, word, "body")) >= 2, seconds=30)
        s.expect("ended and begun again, it is told again", len(s.told(a, word, "body")) == 2, s.told(a, word, "body"))
        # (a meter of its own name over a field the row lacks: `stamina` is a shipped meter
        # and a row field since stamina-1, so it no longer tests this)
        bad = compose(shipped, {"meters": 'fn meters() { base_meters() + [#{ name: "thirst", value: "thirst", max: 100.0 }] }'})
        r = s.call("install_script", bad, check=False)
        out = (r.stdout or "") + (r.stderr or "")
        s.expect("a meter naming a field the vitals row lacks is refused at install", r.returncode != 0 and "not a my_vitals field" in out, out[-300:])
    finally:
        s.call("install_script", shipped)


def sleeper(s):
    """A sleeping body's mind thinks only on what wakes it (perceive.rs `Wake`, the `slumber`
    table). Any other reason to think waits in its `slumber` row, through the moments between two
    sleeps of one rest, and is asked for, after "You woke up.", once the body wakes. Being
    attacked wakes it at once whoever plays it: the sleep stops, it is told why, and its mind is
    asked with the waking reason first and what waited after it. No mind runs here, so requests
    stay pending in `deliberation`."""
    a, b = s.people(2)
    marker = "verify sleeper thought"
    pending = lambda label=None: "\n".join(r["reason"] for r in s.rows(f"SELECT reason FROM deliberation WHERE actor = {a}", label))
    slumber = lambda label=None: s.rows(f"SELECT * FROM slumber WHERE actor = {a}", label)
    sleeping = lambda: [x for x in s.rows(f"SELECT skill FROM activity WHERE id = {a}") if x["skill"] == "sleep"]
    # A rest of short sleeps (5 s rested) with a think between them: the think comes in the gap,
    # where the body has no sleep act and still sleeps.
    s.graph(a, {"seq": [{"do": "sleep"}, {"think": marker}]})
    s.wait(lambda: slumber(), seconds=20)
    # (a think node asks once the deliberation clock has settled 45 s, brain.rs)
    s.wait(lambda: any(marker in r["reason"] for r in slumber()), seconds=90, every=1)
    row = slumber("deferred")[0]
    s.expect("a reason that arrives while asleep waits in slumber, not in deliberation", marker not in pending("pending-asleep"), row)
    s.wait(lambda: sleeping(), seconds=10)
    s.expect("the body sleeps on through the gap between two sleeps", bool(slumber()), row)
    # It wakes on its own (its graph gives it something else to do): told, and asked then.
    s.graph(a, {"wait": 120})
    s.wait(lambda: not slumber(), seconds=20)
    reason = s.wait(lambda: (lambda p: p if "You woke up." in p and marker in p else None)(pending("pending-woke")), seconds=20)
    s.expect("on waking, the waited reasons are asked after \"You woke up.\"", reason.index("You woke up.") < reason.index(marker), reason)
    s.expect("the sleeper is told it woke", bool(s.told(a, "You woke up.", "body")))
    # Asleep again, and attacked: woken at once with the attack as the reason.
    s.graph(a, {"seq": [{"do": "sleep"}, {"think": marker + " again"}]})
    # (a think node asks at most every 90 s, brain.rs)
    s.wait(lambda: any((marker + " again") in r["reason"] for r in slumber()), seconds=150, every=1)
    s.graph(b, {"wait": 120})
    s.call("place_near", b, a)
    # (an attack is graph behaviour, not a one-off act; the sleeper is the one beside it)
    s.graph(b, {"do": "attack", "target": {"nearest": "person"}})
    s.wait(lambda: s.told(a, "You woke up: ", "body"), seconds=30)
    reason = s.wait(lambda: (lambda p: p if "You woke up: " in p and "attacking you" in p else None)(pending("pending-attacked")), seconds=10)
    s.expect("an attack wakes a sleeper and its mind is asked why it woke", "attacking you" in reason.split("You woke up: ", 1)[1].split("\n")[0], reason)
    s.expect("what waited is asked with the waking reason", (marker + " again") in reason, reason)
    broke = [e for e in s.rows(f"SELECT text FROM experience WHERE observer = {a} AND kind = 'body'", "woken") if e["text"].startswith("You woke up: ")]
    s.expect("it is told it woke and why", "attacking you" in broke[0]["text"], broke)
    s.graph(b, {"wait": 120})
    s.graph(a, {"wait": 120})
    sleeper_cue(s)
    sleeper_sounds(s)


def sleeper_cue(s):
    """An attention cue does not wake a sleeper (a sleeping body is not watching): under `cues_on`,
    a cue of a sleeper's mind (an unknown person near its bed) that begins to match fires, and
    its thought waits in `slumber` like any other reason; no request is made and the body sleeps
    on. Woken, its mind is asked with the cue's line after "You woke up."."""
    line = clear_line(s)
    o, n = s.people(2)
    s.call("place_at", n, line[0][0] + 80, line[0][1] + 60)
    s.graph(n, {"wait": 300})
    s.call("place_at", o, *line[0])
    bed = {"name": "verify bed", "x": line[0][0], "y": line[0][1]}
    rows = lambda: s.rows(f"SELECT * FROM cue WHERE actor = {o}")
    slumber = lambda label=None: s.rows(f"SELECT * FROM slumber WHERE actor = {o}", label)
    pending = lambda label=None: "\n".join(r["reason"] for r in s.rows(f"SELECT reason FROM deliberation WHERE actor = {o}", label))
    try:
        set_law(s, "cues_on", True)
        set_cues(s, o, [cue("stance:verify_watch", who="unknown", at="verify bed", within=20.0)], [bed])
        s.wait(lambda: any(w["name"] == "cues_on" and w["value"] == "true" for w in s.rows("SELECT * FROM world_law")), 10)
        s.graph(o, {"seq": [{"do": "sleep"}]})
        s.wait(lambda: slumber(), seconds=20)
        s.call("place_at", n, line[2][0], line[2][1] + 1.0)
        s.wait(lambda: rows() and rows()[0]["fires"] >= 1, seconds=20)
        time.sleep(2)
        kept = slumber("cue-asleep")
        s.expect("a cue that matches for a sleeper fires and its thought waits in slumber", kept and WHY in kept[0]["reason"], kept)
        s.expect("no request is made while it sleeps", WHY not in pending("cue-pending-asleep"), pending())
        woken = [e for e in s.rows(f"SELECT text FROM experience WHERE observer = {o} AND kind = 'body'") if e["text"].startswith("You woke up: ")]
        s.expect("the cue does not wake the body", bool(slumber()) and not woken, woken)
        s.graph(o, {"wait": 300})
        reason = s.wait(lambda: (lambda p: p if "You woke up." in p and WHY in p else None)(pending("cue-pending-woke")), seconds=20)
        s.expect("woken, its mind is asked with the cue's line after \"You woke up.\"", reason.index("You woke up.") < reason.index(WHY), reason)
    finally:
        set_law(s, "cues_on", False, check=False)
        set_cues(s, o, [])
        s.graph(o, {"wait": 300})
        # (off the open line, so a later scene's cues and sight see no one of this one)
        off_the_line(s, line, [o, n], dy=56)


def sleeper_sounds(s):
    """What wakes a sleeper by sound (perceive::wakes): a sound at least `wake_loudness` loud (its
    spec's `loudness`: a way of speaking, a signal, a blow) within `wake_reach` metres, whoever
    plays the sleeper and whoever made the sound. A baby's cry wakes its parent and a stranger at
    the same distance; a quiet line does not wake, a called name does, and the quiet line is told
    on waking as heard while asleep; a fight 3 m away wakes, one beyond the reach does not.
    Needs a world with an infant (the infant fixture)."""
    babies = [c for c in s.rows("SELECT * FROM character WHERE stage = 0", "babies") if c["alive"] and c["kind"] == "person"]
    s.expect("a world with an infant (the infant fixture)", bool(babies), len(babies))
    baby = babies[0]
    parent = baby["parent_a"]
    line = open_line(s, 40)
    x0, y = line[0]
    park = lambda who, k: s.call("place_at", who, line[30 + k][0], y)
    adults = s.people(6)
    speaker, z_line, f1, f2, z_near, z_far = adults
    stranger = adults[0]
    for who in [baby["id"], parent] + adults:
        s.graph(who, {"wait": 120})
    for k, who in enumerate(adults):
        park(who, k)
    slumber = lambda who: s.rows(f"SELECT * FROM slumber WHERE actor = {who}")
    def sleep(who):
        s.graph(who, {"seq": [{"do": "sleep"}]})
        s.wait(lambda: slumber(who), seconds=20)
    def woke(who, words, seconds=60):
        def found():
            told = [e for e in s.rows(f"SELECT text FROM experience WHERE observer = {who} AND kind = 'body'") if e["text"].startswith("You woke up: ") and words in e["text"]]
            return told
        try:
            return s.wait(found, seconds=seconds, every=1)
        except TimeoutError:
            return []
    # A parent 3 m from its crying baby wakes.
    s.call("place_at", baby["id"], x0, y)
    s.call("place_at", parent, x0 + 3, y)
    sleep(parent)
    s.graph(baby["id"], {"do": {"skill": "signal", "item": "cry"}})
    told = woke(parent, "crying")
    s.graph(baby["id"], {"wait": 120})
    s.expect("a parent 3 m from its crying baby wakes, told why", bool(told), told)
    s.graph(parent, {"wait": 120})
    s.call("place_at", parent, line[36][0], y)
    # A stranger at the same distance wakes too (the cry comes again after 45 s at most).
    s.call("place_at", stranger, x0 + 3, y)
    sleep(stranger)
    s.graph(baby["id"], {"do": {"skill": "signal", "item": "cry"}})
    told = woke(stranger, "crying", seconds=75)
    s.graph(baby["id"], {"wait": 120})
    s.expect("a stranger 3 m from someone else's crying baby wakes too", bool(told), told)
    s.graph(stranger, {"wait": 120})
    park(stranger, 0)
    s.call("place_at", baby["id"], line[38][0], y)
    # A quiet line does not wake; a called name does, and the quiet line is then told as heard asleep.
    names = {c["id"]: c["name"] for c in s.rows("SELECT id, name FROM character")}
    s.call("place_at", z_line, x0 + 3, y)
    s.call("place_at", speaker, x0, y)
    sleep(z_line)
    quiet = f"{names[z_line]}, are you awake? verify quiet line"
    s.call("mind_say", speaker, quiet, z_line, "", 0, THOUGHT)
    time.sleep(2.2)
    # A quiet line to the room that names the sleeper: kept too, with how it was said
    # (speech-address) in the sleeper's own labels.
    s.call("mind_say", speaker, f"{names[z_line]}, the boat is in. verify room line", 0, "", 0, THOUGHT)
    time.sleep(4)
    kept = s.rows(f"SELECT * FROM heard_asleep WHERE actor = {z_line}", "heard-asleep")
    told_now = [e for e in s.rows(f"SELECT kind, text FROM experience WHERE observer = {z_line}") if "verify quiet line" in e["text"]]
    s.expect("a quiet line to a sleeper does not wake it", bool(slumber(z_line)) and not woke(z_line, "", seconds=1), slumber(z_line))
    s.expect("the line waits for its waking, untold", any("verify quiet line" in r["text"] for r in kept) and not told_now, {"kept": kept, "told": told_now})
    s.call("mind_say", speaker, f"{names[z_line]}!", z_line, "call", 0, THOUGHT)
    told = woke(z_line, "calls out", seconds=15)
    s.expect("a called name wakes the sleeper, told why", bool(told), told)
    heard = [e for e in s.rows(f"SELECT kind, text FROM experience WHERE observer = {z_line}", "heard-on-waking") if "verify quiet line" in e["text"]]
    s.expect("on waking, the quiet line is told as heard while asleep", len(heard) == 1 and heard[0]["kind"] == "heard_asleep" and heard[0]["text"].startswith("While you slept, you heard: "), heard)
    room = [e for e in s.rows(f"SELECT kind, text FROM experience WHERE observer = {z_line}", "heard-room-on-waking") if "verify room line" in e["text"]]
    s.expect("a line to the room heard asleep is told with how it was said, in the sleeper's labels", len(room) == 1 and room[0]["kind"] == "heard_asleep" and "to the room, naming you" in room[0]["text"], room)
    s.expect("nothing is left waiting", not s.rows(f"SELECT * FROM heard_asleep WHERE actor = {z_line}"))
    for who in (speaker, z_line):
        s.graph(who, {"wait": 120})
    park(speaker, 1); park(z_line, 2)
    # A fight 3 m away wakes; one beyond the reach (wake_reach, 8 m by default) does not.
    s.call("place_at", f1, x0, y)
    s.call("place_at", f2, x0 + 1, y)
    s.call("place_at", z_near, x0 + 4, y)
    s.call("place_at", z_far, x0 + 13, y)
    sleep(z_near)
    sleep(z_far)
    s.graph(f1, {"do": "attack", "target": {"nearest": "person"}})
    told = woke(z_near, "fight", seconds=30)
    time.sleep(3)
    s.graph(f1, {"wait": 120})
    s.graph(f2, {"wait": 120})
    s.expect("a fight 3 m away wakes a sleeper", bool(told), told)
    s.expect("a fight 12 m away (beyond the reach) does not", bool(slumber(z_far)) and not woke(z_far, "", seconds=1), slumber(z_far))
    # (off the open line, so a later scene finds no one of this one on it)
    off_the_line(s, line, adults + [baby["id"], parent], dy=56)


def world_tiles(s):
    """This world's tiles (`terrain_chunk`) and a walkable test by tile code (water, rock,
    wall, drop and low tiles are not walkable; off the map is rock)."""
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
    at = lambda x, y: tiles[y * W + x] if 0 <= x < W and 0 <= y < H else 4
    return W, H, at, lambda x, y: at(x, y) not in (2, 4, 7, 8, 9)


def old_snap(walk, x, y):
    """The tile the pre-fix `place_at` chose (`Map::nearest_walkable`: rings outward, first
    walkable tile in row order), for the evidence."""
    tx, ty = math.floor(x), math.floor(y)
    for r in range(12):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if (abs(dx) == r or abs(dy) == r) and walk(tx + dx, ty + dy):
                    return (tx + dx, ty + dy)
    return None


PLACE_RADIUS = 6.0


def placement(s):
    """Admin placement (`place_near`, `place_at`) puts a body on the nearest free walkable tile:
    walkable, and no other body on it, within 6 m (`PLACE_RADIUS` in living/authority/src/lib.rs),
    and refuses when there is none. `place_near` beside a target whose east tile is an obstacle
    lands on a walkable tile of the target's ground and the body then walks (`goto`) away; two
    `place_at` requests 1.9 m apart that the old nearest-walkable snapping put on one tile land
    on two; a request with no free walkable tile within the radius is refused."""
    W, H, at, walk = world_tiles(s)
    tile = lambda p: (math.floor(p[0]), math.floor(p[1]))
    # A target tile with an obstacle (rock, wall or water) east and open ground west of it,
    # more than 10 m from every body (the world's people, an earlier attempt's actors).
    now = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    others = [body_at(s, None, now, row=b) for b in s.rows("SELECT x, y, t_ms, vx, vy, next_ms FROM body")]
    spot = next(((x, y) for y in range(8, H - 8) for x in range(12, W - 8)
                 if walk(x, y) and at(x + 1, y) in (2, 4, 7)
                 and all(math.dist((x + .5, y + .5), o) > 10 for o in others)
                 and all(walk(x - i, y + d) for i in range(1, 7) for d in (-1, 0, 1))), None)
    if spot is None:
        raise RuntimeError("no walkable tile with an obstacle east of it on this map")
    # Two requests 1.9 m apart that the old snapping put on one tile, a few metres off.
    pair = None
    for y in range(4, H - 4):
        for x in range(4, W - 4):
            if walk(x, y):
                continue
            p = (x + .5, y + .5)
            for q in ((p[0] + 1.9, p[1]), (p[0], p[1] + 1.9)):
                o = old_snap(walk, *p)
                if not walk(*tile(q)) and o is not None and o == old_snap(walk, *q) \
                        and max(math.dist(r, (o[0] + .5, o[1] + .5)) for r in (p, q)) <= 2.5:
                    pair = (p, q)
                    break
            if pair:
                break
        if pair:
            break
    # A point with no walkable tile within the radius: deep water or rock if the map has it,
    # else off the map's edge (off the map is rock).
    deep = next(((x + .5, y + .5) for y in range(0, H, 2) for x in range(0, W, 2)
                 if not any(walk(x + dx, y + dy) for dy in range(-7, 8) for dx in range(-7, 8))), (-20.0, -20.0))
    (s.out / f"{s.name}-spots.json").write_text(json.dumps({"target": spot, "pair": pair, "deep": deep,
        "old_pair_tiles": [old_snap(walk, *p) for p in pair] if pair else None}, indent=2) + "\n")
    target, near, c, d, e = s.people(5)
    s.call("place_at", target, spot[0] + .5, spot[1] + .5)
    s.expect("place_at on a free walkable tile puts the body on that tile's centre",
             body_at(s, target) == (spot[0] + .5, spot[1] + .5), body_at(s, target))
    s.call("place_near", near, target)
    p = body_at(s, near)
    s.expect("place_near beside an obstacle lands on a walkable tile, not the target's own",
             walk(*tile(p)) and tile(p) != spot and tile(p) != (spot[0] + 1, spot[1]) and math.dist(p, (spot[0] + .5, spot[1] + .5)) <= PLACE_RADIUS + .5,
             {"placed": p, "tile_code": at(*tile(p)), "obstacle": (spot[0] + 1, spot[1]), "obstacle_code": at(spot[0] + 1, spot[1])})
    goal = (spot[0] - 5 + .5, spot[1] + .5)
    t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.graph(near, {"seq": [{"do": {"skill": "goto", "target": {"at": list(goal)}}}, {"wait": 300}]})
    s.wait(lambda: math.dist(body_at(s, near), goal) < 1.0, seconds=20)
    uses = [u for u in s.rows(f"SELECT * FROM skill_use WHERE actor = {near}", "near-uses") if u["skill"] == "goto" and u["at_ms"] >= t0]
    s.expect("the placed body can then goto (it walks 5 m away)", math.dist(body_at(s, near), goal) < 1.0
             and not any("could not get there" in (u["outcome"] or "") or "blocked" in (u["outcome"] or "") for u in uses),
             {"at": body_at(s, near), "goal": goal, "goto": [u["outcome"] for u in uses]})
    s.call("place_near", e, target)
    pe = body_at(s, e)
    s.expect("a second place_near beside the same target takes another free tile",
             walk(*tile(pe)) and tile(pe) not in (spot, tile(body_at(s, near))), {"placed": pe})
    if pair:
        s.call("place_at", c, *pair[0])
        s.call("place_at", d, *pair[1])
        pc, pd = body_at(s, c), body_at(s, d)
        s.expect("two place_at requests 1.9 m apart land on different free walkable tiles",
                 tile(pc) != tile(pd) and walk(*tile(pc)) and walk(*tile(pd)),
                 {"requests": pair, "placed": [pc, pd], "old_snap": [old_snap(walk, *q) for q in pair]})
    else:
        s.expect("this map has two requests 1.9 m apart the old snapping joined", False, "none found", fatal=False)
    before = body_at(s, c)
    r = s.call("place_at", c, *deep, check=False)
    out = (r.stdout or "") + (r.stderr or "")
    s.expect("a request with no free walkable tile within 6 m is refused, and the body stays",
             r.returncode != 0 and "no free walkable tile within 6 m" in out and body_at(s, c) == before,
             {"request": deep, "exit": r.returncode, "error": out[-300:]})


def clear_line(s):
    """An open line more than 10 m from every person now in the world: scenes before this one
    (`doing`, ...) leave their actors on the first open line, and these scenes count who is in
    sight."""
    people = {c["id"] for c in s.rows("SELECT id, kind FROM character WHERE alive = true") if c["kind"] == "person"}
    return open_line(s, avoid=[(b["x"], b["y"]) for b in s.rows("SELECT id, x, y FROM body") if b["id"] in people])


def off_the_line(s, line, actors, dy=40):
    """Move a scene's actors far off its open line (as `say` does), so that the scenes after it,
    which find the same line, do not find them on it."""
    for k, who in enumerate(actors):
        s.call("place_at", who, line[0][0] + 60 + 2 * k, line[0][1] + dy, check=False)


def crowd_sight(s):
    """Everyone in sight is perceived (docs/STRANGERS.md, decision 3; `brain.rs` `noticed`): in a
    crowd (more than 6 people in sight) a person seen for the first time is still told, first
    sights of one look sharing one line ("For the first time you see a stranger, 2 tiles east;
    and ..."), and each gets its `familiar` row. On an open line an observer O stands among 8
    minded strangers within 4.5 m (a crowd of 9), then two more are brought in. Measures the
    first-sight lines (count, characters) for the before/after record; `--baseline` on a build
    from before the fix records them without asserting (there: none in a crowd)."""
    line = clear_line(s)
    obs, *crowd = s.people(9)
    try:
        crowd_sight_on(s, line, obs, crowd)
    finally:
        off_the_line(s, line, [obs, *crowd, *getattr(s, "crowd_new", [])], dy=44)


def crowd_sight_on(s, line, obs, crowd):
    spots = [(dx, dy) for dx in (1, 2, 3, 4) for dy in (-1.0, 1.0)]
    # Counted from before the placing: since novelty is looked for once a second (BATTLE_SCALE
    # fix 2), the first look often falls while the crowd is still being placed.
    t_place = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.call("place_at", obs, *line[0])
    for a, (dx, dy) in zip(crowd, spots):
        s.call("place_at", a, line[dx][0], line[dx][1] + dy)
    t1 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    time.sleep(10)
    fam = lambda ids: {r["thing"] & 0xFFFFFFFF for r in s.rows(f"SELECT thing FROM familiar WHERE actor = {obs}") if r["thing"] >> 40 == 2} & set(ids)
    firsts = lambda since: [r for r in s.rows(f"SELECT id, at_ms, kind, subject, object, text, salience FROM experience WHERE observer = {obs}") if r["at_ms"] >= since and "first time you see" in r["text"]]
    exps = s.rows(f"SELECT id, at_ms, kind, subject, object, text FROM experience WHERE observer = {obs}", "experiences-crowd")
    lines1 = firsts(t_place)
    parts1 = sum(len(r["text"].split("; ")) for r in lines1)
    m1 = {"lines": len(lines1), "chars": sum(len(r["text"]) for r in lines1), "people_named": parts1, "crowd_line": any("among a crowd" in r["text"] for r in exps), "texts": [r["text"] for r in lines1]}
    print("MEASURE crowd of 9 (8 new to O):", json.dumps(m1), flush=True)
    # Two more, brought in from wherever they were spawned (out of O's sight).
    new = s.crowd_new = s.people(2)
    t2 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.call("place_at", new[0], line[5][0], line[5][1] - 1.0)
    s.call("place_at", new[1], line[5][0], line[5][1] + 1.0)
    time.sleep(10)
    lines2 = [r for r in firsts(t2) if r["at_ms"] >= t2]
    named2 = {i for r in lines2 for i in (r["subject"], r["object"]) if i in new}
    parts2 = sum(len(r["text"].split("; ")) for r in lines2)
    m2 = {"lines": len(lines2), "chars": sum(len(r["text"]) for r in lines2), "people_named": parts2, "both_by_id": sorted(named2), "texts": [r["text"] for r in lines2]}
    print("MEASURE two more among 10 (2 new to O):", json.dumps(m2), flush=True)
    (s.out / f"{s.name}-measure.json").write_text(json.dumps({"crowd_of_9": m1, "two_more": m2, "observer": obs, "crowd": crowd, "new": new}, indent=1) + "\n")
    if getattr(s, "baseline", False):
        print("BASELINE: recorded, not asserted", flush=True)
        return
    s.expect("the crowd is a crowd (more than 6 people in sight)", m1["crowd_line"], m1)
    s.expect("all 8 first seen in the crowd are told", parts1 >= 8, m1)
    s.expect("first sights of one look share a line (fewer lines than people)", 1 <= len(lines1) < 8, m1)
    s.expect("each of the 8 has its familiar row", fam(crowd) == set(crowd), sorted(fam(crowd)))
    s.expect("the two seen for the first time among 10 are both mentioned", parts2 >= 2 and named2 == set(new), m2)
    s.expect("both have their familiar rows", fam(new) == set(new), sorted(fam(new)))


FAR = "someone too far away to make out"


def stranger_filter(s):
    """What a graph's `relation: "stranger"` matches (docs/STRANGERS.md section 3), and how a
    person too far away to make out is perceived (far-label). With the world's `stranger_by_name`
    law off, "stranger" is someone with no relation row (or one labelled "stranger"); on, someone
    whose name one does not know (`perception::knows_name`). On an open line O stands at the west
    end; A, of O's community with no relation row, 2 m east; N, unknown to O but with a relation
    row O's mind wrote ("wary"), 3 m east; F, of O's community, 5 m east. O's graph waves at the
    nearest stranger: off at A, on at N. Then an overlay of `perceived_of` (as Cullet's law: who
    someone is only within 4 m, `far` beyond) is installed: O's scene shows F as "someone too far
    away to make out" with its id, no name and no `community`; with the law on and N gone, O's
    graph finds no stranger and does not wave at F; a relation "stranger" O's mind writes about F
    (whose name O knows) is not written, one about N is; an unknown U placed 5 m away gets no
    first sight until brought within 4 m. The law and the shipped script are restored at the end."""
    line = clear_line(s)
    o, a, n, f = s.people(4)
    s.act(o, {"do": "found", "text": f"Verify Strand {o}"})
    s.wait(lambda: s.rows(f"SELECT * FROM membership WHERE member = {o}"))
    for m in (a, f):
        s.call("place_near", m, o)
        s.act(m, {"do": "join", "target": {"id": o}})
        s.wait(lambda m=m: s.rows(f"SELECT * FROM join_request WHERE asker = {m}"))
        s.act(o, {"do": "welcome", "target": {"id": m}})
        s.wait(lambda m=m: s.rows(f"SELECT * FROM membership WHERE member = {m}"))
    s.call("mind_update", o, {"persona": None, "relations": [{"other": n, "trust": -10, "affinity": -5, "label": "wary", "note": "verification fixture: seen, never named"}],
                              "beliefs": None, "judgments": [], "places": [], "thought": None, "replace": False, "cues": None})
    s.rows(f"SELECT * FROM relation WHERE actor = {o}", "relations")
    for who, k in ((o, 0), (a, 2), (n, 3), (f, 5)):
        s.call("place_at", who, *line[k])
    for x in (a, n, f):
        s.graph(x, {"wait": 300})
    sel = {"nearest": {"kind": "person", "relation": "stranger"}}
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    extra = []

    def waved_at(wait=20):
        since = now()
        s.graph(o, {"seq": [{"do": "wave", "target": sel}, {"wait": 300}]})
        rows = s.wait(lambda: [r for r in s.rows(f"SELECT * FROM skill_use WHERE actor = {o}") if r["skill"] == "wave" and r["at_ms"] >= since], wait)
        return rows[0]["target"]

    def scene():
        stamp = lambda: next((d["updated_ms"] for d in s.rows(f"SELECT actor, updated_ms FROM deliberation WHERE actor = {o}")), -1)
        before = stamp()
        end = time.monotonic() + 75
        while time.monotonic() < end:
            # A `think` leaf asks only 45 s after the last deliberation, so it is installed again.
            s.call("set_behavior", o, json.dumps({"seq": [{"think": "a look around"}, {"wait": 300}]}))
            row = next((d for d in s.rows(f"SELECT * FROM deliberation WHERE actor = {o}") if d["updated_ms"] > before), None)
            if row:
                sc = json.loads(row["scene"])
                (s.out / f"{s.name}-scene-far.json").write_text(json.dumps(sc, indent=1, ensure_ascii=False) + "\n")
                return {c["id"]: c for c in sc.get("creatures", [])}
            time.sleep(5)
        raise TimeoutError("no deliberation scene for O in 75 s")
    try:
        off = waved_at()
        s.expect("law off: the nearest stranger is A, of O's community with no relation row", off == a, {"waved_at": off, "A": a, "N": n})
        set_law(s, "stranger_by_name", True)
        s.wait(lambda: any(r["name"] == "stranger_by_name" and r["value"] == "true" for r in s.rows("SELECT * FROM world_law")), 10)
        on = waved_at()
        s.expect("law on: the nearest stranger is N, whose name O does not know (its relation row does not count)", on == n, {"waved_at": on, "A": a, "N": n})
        # Too far away to make out: who someone is only within 4 m (as Cullet's law within 24 m).
        far_law = 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }'
        s.call("install_script", compose(shipped, {"perceived_of": far_law}))
        seen = scene()
        # Since far-handle the far figure is named by a handle of the sighting, never F's id.
        far_entries = [c for c in seen.values() if c.get("who") == FAR]
        fe, ae, ne = (far_entries[0] if far_entries else {}), seen.get(a, {}), seen.get(n, {})
        s.expect("far: F (known, 5 m) is someone too far away to make out, under a handle (not its id), no name and no community",
                 fe.get("who") == FAR and "name" not in fe and "community" not in fe and fe.get("id", 0) >= 1_000_000_000 and f not in seen, {"far": fe, "ids": sorted(seen)})
        s.expect("near: A keeps its name and community; N is a stranger", ae.get("name") and ae.get("community") == "yours" and ne.get("who") == "a stranger" and "community" not in ne, {"A": ae, "N": ne})
        # The filter (law on) never matches a known neighbour, however far.
        s.call("place_at", n, line[0][0] + 70, line[0][1] + 52)
        since = now()
        s.graph(o, {"seq": [{"do": "wave", "target": sel}, {"wait": 300}]})
        time.sleep(8)
        waves = [r for r in s.rows(f"SELECT * FROM skill_use WHERE actor = {o}") if r["skill"] == "wave" and r["at_ms"] >= since]
        s.expect("law on, N gone: no stranger in sight, F (far, known) is not waved at", not waves, waves)
        # No "stranger" relation about someone whose name one knows, however they were seen.
        s.call("mind_update", o, {"persona": None, "relations": [{"other": f, "trust": 0, "affinity": 0, "label": "stranger", "note": "verification fixture: a figure far off"},
                                                                  {"other": n, "trust": 0, "affinity": 0, "label": "stranger", "note": "verification fixture: never named"}],
                                  "beliefs": None, "judgments": [], "places": [], "thought": None, "replace": False, "cues": None})
        rel = {r["other"]: r["label"] for r in s.rows(f"SELECT * FROM relation WHERE actor = {o}", "relations-after")}
        s.expect("a relation \"stranger\" to F (known by name) is not written; to N (unknown) it is", "stranger" not in rel.get(f, "") and rel.get(n) == "stranger", rel)
        # A first sight waits until someone can be made out.
        u = s.people(1)[0]
        extra.append(u)
        t0 = now()
        s.call("place_at", u, line[5][0], line[5][1] + 1.0)
        time.sleep(8)
        firsts = lambda: [r for r in s.rows(f"SELECT at_ms, subject, object, text FROM experience WHERE observer = {o}") if r["at_ms"] >= t0 and "first time you see" in r["text"] and u in (r["subject"], r["object"])]
        early = firsts()
        s.call("place_at", u, line[2][0], line[2][1] - 1.0)
        # Within 25 s: the far figure is looked at again 5 s after each look, on O's own look slot.
        try:
            late = s.wait(firsts, 25) if not early else early
        except TimeoutError:
            late = []
        bodies = {b["id"]: (b["x"], b["y"]) for b in s.rows(f"SELECT id, x, y FROM body WHERE id = {o} OR id = {u}")}
        gap = math.dist(bodies[o], bodies[u]) if o in bodies and u in bodies else None
        s.expect("U at 5 m (too far to make out) gets no first sight; within 4 m it does, as a stranger",
                 not early and late and "a stranger" in late[0]["text"] and FAR not in late[0]["text"], {"at_5m": early, "at_2m": late, "o_to_u_m": gap})
    finally:
        s.call("install_script", shipped, check=False)
        set_law(s, "stranger_by_name", False, check=False)
        off_the_line(s, line, [o, a, n, f] + extra, dy=50)



WHY = "verify-core fixture: the words of O's own mind, quoted as written"


def cue(for_key, **kw):
    """A `CueIn` as the mind service projects it (docs/ATTENTION.md)."""
    c = {"for_key": for_key, "why": WHY, "who_id": 0, "who": "", "doing": "", "phase": "", "thing": "", "at": "", "within": 0.0, "near_me": 0.0, "source": "verify-core"}
    c.update(kw)
    return c


def fired_subject(f):
    """A `CueFire` as SQL's JSON gives it: `[subject, at_ms]`."""
    return f[0] if isinstance(f, list) else f["subject"]


def set_cues(s, actor, cues, places=()):
    s.call("mind_update", actor, {"persona": None, "relations": [], "beliefs": None, "judgments": [], "places": list(places),
                                  "thought": None, "replace": False, "cues": {"some": cues}})


def cues(s):
    """Attention cues (docs/ATTENTION.md; `brain.rs` `Ev::cues`, `mind.rs` `set_cues`). O's mind
    writes (through `mind_update`, as the mind service does) a cue on "a person whose name I do not
    know, within 20 m of my place verify yard". With the `cues_on` law off nothing is matched.
    On: N (unknown to O) coming within 3 m gives exactly one `noticed` experience, quoting the
    mind's own `why` verbatim, and one deliberation request with that line; N leaving and coming
    back within `cue_cooldown_s` gives nothing; U (another unknown) coming in within `cue_gap_s`
    of that fire is told only once the gap has passed. Under a `perceived_of` overlay that makes
    anyone beyond 4 m too far away to make out, V (unknown) at 6 m and K (O's community, cued by
    id) at 6 m match nothing; V at 2 m does. Cues the world cannot watch for are kept with their
    reason in `refused`. The laws, the script and O's cues are restored at the end."""
    line = clear_line(s)
    o, k, n, u, v = s.people(5)
    s.act(o, {"do": "found", "text": f"Verify Watch {o}"})
    s.wait(lambda: s.rows(f"SELECT * FROM membership WHERE member = {o}"))
    s.call("place_near", k, o)
    s.act(k, {"do": "join", "target": {"id": o}})
    s.wait(lambda: s.rows(f"SELECT * FROM join_request WHERE asker = {k}"))
    s.act(o, {"do": "welcome", "target": {"id": k}})
    s.wait(lambda: s.rows(f"SELECT * FROM membership WHERE member = {k}"))
    away = lambda who, j=0: s.call("place_at", who, line[0][0] + 80 + 2 * j, line[0][1] + 60)
    for j, who in enumerate((k, n, u, v)):
        away(who, j)
        s.graph(who, {"wait": 300})
    s.call("place_at", o, *line[0])
    s.graph(o, {"wait": 300})
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    noticed = lambda since: [r for r in s.rows(f"SELECT id, at_ms, kind, subject, object, text, salience FROM experience WHERE observer = {o}") if r["kind"] == "noticed" and r["at_ms"] >= since]
    rows = lambda: s.rows(f"SELECT * FROM cue WHERE actor = {o}")
    yard = {"name": "verify yard", "x": line[0][0], "y": line[0][1]}
    try:
        set_law(s, "cues_on", False)
        set_cues(s, o, [cue("stance:verify_watch", who="unknown", at="verify yard", within=20.0)], [yard])
        r = rows()
        s.expect("the cue is kept, watched (no refusal)", len(r) == 1 and r[0]["refused"] == "" and r[0]["who"] == "unknown", r)
        t0 = now()
        s.call("place_at", n, line[2][0], line[2][1] + 1.0)
        time.sleep(6)
        s.expect("law off: nothing is matched", not noticed(t0) and rows()[0]["fires"] == 0, noticed(t0))
        away(n, 1)
        time.sleep(2)
        set_law(s, "cues_on", True)
        set_law(s, "cue_gap_s", 15)
        s.wait(lambda: any(w["name"] == "cues_on" and w["value"] == "true" for w in s.rows("SELECT * FROM world_law")), 10)
        t1 = now()
        s.call("place_at", n, line[2][0], line[2][1] + 1.0)
        got = s.wait(lambda: noticed(t1), 10)
        time.sleep(4)
        got = noticed(t1)
        s.expect("law on: N coming in gives exactly one noticed line, about N", len(got) == 1 and got[0]["subject"] == n, got)
        s.expect("the line quotes the mind's own words verbatim", f'"{WHY}"' in got[0]["text"] and abs(got[0]["salience"] - 0.65) < 1e-6, got[0]["text"])
        d = s.rows(f"SELECT * FROM deliberation WHERE actor = {o}", "deliberation-after-fire")
        s.expect("and asks O to think, with that line as the reason", d and WHY in d[0]["reason"], d)
        s.expect("the cue counts its fire", rows()[0]["fires"] == 1 and [fired_subject(f) for f in rows()[0]["fired"]] == [n], rows())
        fire1 = got[0]["at_ms"]
        # Cooldown: N leaves and comes back; U (unknown too) comes in while the gap holds.
        away(n, 1)
        time.sleep(2.5)
        s.call("place_at", n, line[2][0], line[2][1] + 1.0)
        s.call("place_at", u, line[3][0], line[3][1] - 1.0)
        late = s.wait(lambda: [x for x in noticed(t1) if x["at_ms"] > fire1], 25)
        s.expect("N back within the cooldown is not told again", late and n not in (late[0]["subject"], late[0]["object"]), late)
        s.expect("U is told only once the gap (15 s) since the last fire has passed", late and late[0]["subject"] == u and late[0]["at_ms"] - fire1 >= 15_000, {"fire1": fire1, "late": late})
        time.sleep(3)
        s.expect("one line per fire: two in all", len(noticed(t1)) == 2, noticed(t1))
        # Far figures: who someone is only within 4 m.
        for who in (n, u):
            away(who, 2)
        set_law(s, "cue_gap_s", 0)
        far_law = 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }'
        s.call("install_script", compose(shipped, {"perceived_of": far_law}))
        set_cues(s, o, [cue("stance:verify_watch", who="unknown"), cue("goal:verify_kin", who_id=k)])
        time.sleep(2)
        t2 = now()
        s.call("place_at", v, line[6][0], line[6][1])
        s.call("place_at", k, line[6][0], line[6][1] - 1.5)
        time.sleep(6)
        s.expect("far: V (unknown) and K (cued by id) 6 m away, too far to make out, match nothing", not noticed(t2), noticed(t2))
        s.call("place_at", v, line[2][0], line[2][1] - 1.0)
        near = s.wait(lambda: noticed(t2), 10)
        s.expect("V within 4 m is told", near and near[0]["subject"] == v, near)
        # What the world cannot watch for is kept, refused, with its reason.
        set_cues(s, o, [cue("stance:x", at="no such place"), cue("stance:x", who="wolf", phase="dancing"), cue("stance:x", who="dragon"),
                        cue("stance:x", thing="no_such_kind"), cue("stance:x", doing="strike"), cue("x", who="wolf"), cue("stance:x", who="wolf", doing="strike", phase="winding up")])
        ref = [c["refused"] for c in sorted(rows(), key=lambda c: c["id"])]
        s.expect("refusals: unknown place, no such phase, no such creature, no such thing, a deed with no doer, serving nothing; a wolf winding up a strike is watched",
                 len(ref) == 7 and all(ref[:6]) and ref[6] == "" and "no place" in ref[0] and "not a phase" in ref[1] and "dragon" in ref[2] and "no_such_kind" in ref[3], ref)
        set_cues(s, o, [])
        s.expect("an empty set clears the cues", not rows(), rows())
    finally:
        s.call("install_script", shipped, check=False)
        set_law(s, "cues_on", False, check=False)
        set_law(s, "cue_gap_s", 60, check=False)
        set_cues(s, o, [])
        off_the_line(s, line, [o, k, n, u, v], dy=56)

def regard_check(s):
    """The shared answers (docs/ATTENTION.md, "Cost"; `perception.rs` `with_answers`) equal
    fresh ones. With the `regard_cache_check` law on, every answer the transaction's cache gives
    (whether one knows a target's name, the `perceived_of` answer) is computed afresh too and any
    difference logged and counted (`regard answers: ... compared=N differed=M`, one line a
    second). Drives what asks: first sights in a crowd (`crowd_sight`), the stranger filter and
    the far label under an overlay (`stranger_filter`), cues (`cues`), and on a world with the
    bow (the island) the told lines naming others (`outcomes`); then a fight watched by minded
    onlookers while one says its name to another (an introduction mid-run). Passes when many
    answers were compared and none differed. The law is restored at the end."""
    t0 = time.time()
    set_law(s, "regard_cache_check", True)
    try:
        crowd_sight(s)
        stranger_filter(s)
        cues(s)
        if any(c["skill"] == "bowshot" for c in s.rows("SELECT skill FROM skill_card")):
            outcomes(s)
        line = clear_line(s)
        a, b, *watch = s.people(6)
        s.call("place_at", a, *line[1])
        s.call("place_at", b, line[2][0], line[2][1])
        for k, w in enumerate(watch):
            s.call("place_at", w, line[4 + k][0], line[4 + k][1] + 1.5)
        s.graph(a, {"first": [{"do": {"skill": "attack", "target": {"id": b}}}]})
        s.graph(b, {"first": [{"do": {"skill": "attack", "target": {"id": a}}}]})
        time.sleep(4)
        name = next(c["name"] for c in s.rows(f"SELECT id, name FROM character WHERE id = {watch[0]}"))
        s.graph(watch[0], {"seq": [{"say": {"text": f"I am {name}.", "to": watch[1]}}, {"wait": 60}]})
        time.sleep(8)
        off_the_line(s, line, [a, b, *watch], dy=60)
        time.sleep(2)
    finally:
        set_law(s, "regard_cache_check", False, check=False)
    logs = s.command("logs", "-s", "local", s.db, "-n", "400000").stdout
    compared = differed = hits = 0
    for m in re.finditer(r'regard answers: hits=(\d+) computed=(\d+) compared=(\d+) differed=(\d+)', logs):
        hits += int(m.group(1))
        compared += int(m.group(3))
        differed += int(m.group(4))
    errors = [l for l in logs.splitlines() if "regard cache:" in l][:10]
    told = s.rows(f"SELECT * FROM acquaintance WHERE observer = {watch[1]}", "regard-check-acquaintance")
    (s.out / f"{s.name}-regard-check.json").write_text(json.dumps({"hits": hits, "compared": compared, "differed": differed, "errors": errors, "introduced": told, "seconds": round(time.time() - t0)}, indent=1) + "\n")
    print(f"MEASURE regard answers: hits {hits}, compared {compared}, differed {differed}", flush=True)
    s.expect("the introduction happened mid-run (an acquaintance row)", any(r.get("known") == watch[0] for r in told), told, fatal=False)
    s.expect("many shared answers were compared with fresh ones", compared >= 1000, {"compared": compared, "hits": hits})
    s.expect("no shared answer differed from a fresh one", differed == 0 and not errors, errors)



def doing_seen(s):
    """What someone is visibly doing, and how far into it (docs/PERCEPTION.md, "What someone is
    visibly doing"; docs/COMBAT_MIND.md §3.2): a graph's `doing` condition and the scene's
    `visibly`, read from the `fighter` and `doing` rows a player's client draws, under the same
    sight rules. On an open line W stands facing east; A 2 m ahead, B 2 m behind, F 5 m ahead
    with Y beside it, G 14 m ahead (beyond the day's 11 m sight) with Z beside it. An overlay of
    `perceived_of` makes anyone beyond 3 m too far away to make out (as Cullet's law beyond 24 m).
    With sight on a field (`fov_on`, near ring 0.5 m): W's routine dodges when a person in sight is
    about to release a hostile move at it; A's attack (a 650 ms windup) is dodged in the second
    half of its windup, and W's scene (a `think` in the same branch) shows A `visibly` attacking,
    about to release, at you; B's attack from behind (outside the field) is not dodged. With the
    field off, W's routine dodges when a person in sight holds up a guard: F's guard 5 m off
    triggers it and W's scene shows F as someone too far away to make out, holding a block;
    G's guard beyond sight does not. A dodge is committed (committed-moves): with the field on it
    runs its course though the dash turns W's back on A, and the blow misses. About two minutes
    (a `think` waits 45 s from arrival)."""
    people = {c["id"] for c in s.rows("SELECT id, kind FROM character WHERE alive = true") if c["kind"] == "person"}
    line = open_line(s, length=20, avoid=[(b["x"], b["y"]) for b in s.rows("SELECT id, x, y FROM body") if b["id"] in people])
    (s.out / f"{s.name}-line.json").write_text(json.dumps(line) + "\n")
    born = time.monotonic()
    w, a, b, f, y, g, z = cast = s.people(7)
    e = line[2]
    home = {w: e, a: line[4], b: line[0], f: line[7], y: line[8], g: line[16], z: line[17]}
    (s.out / f"{s.name}-cast.json").write_text(json.dumps({"W": w, "A": a, "B": b, "F": f, "Y": y, "G": g, "Z": z}) + "\n")
    rounds = iter(range(1000))
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()

    def place():
        for c, at in home.items():
            s.call("place_at", c, at[0], at[1])

    def facing_east():
        s.graph(w, {"seq": [{"first": [{"do": {"skill": "face", "target": {"at": [e[0] + 4.0, e[1]]}}}, {"wait": 0.1}]}, {"wait": 60 + next(rounds)}]})
        time.sleep(2)

    def routine(tag, cond):
        # A graph of its own each time (the same graph again would not start over).
        s.graph(w, {"first": {"label": "doing-seen", "children": [
            {"if": {"cond": {"doing": cond}, "then": {"seq": [{"think": f"doing_seen {tag}"}, {"do": "dodge"}]}}},
            {"wait": 0.2 + 0.001 * next(rounds)}]}})

    def uses(t0, label):
        return [x for x in s.rows("SELECT * FROM skill_use", f"uses-{label}") if x["at_ms"] >= t0]

    def scene_since(t0, label):
        row = next((d for d in s.rows(f"SELECT * FROM deliberation WHERE actor = {w}") if d["updated_ms"] >= t0), None)
        if not row:
            return None
        sc = json.loads(row["scene"])
        (s.out / f"{s.name}-scene-{label}.json").write_text(json.dumps(sc, indent=1, ensure_ascii=False) + "\n")
        return {c["id"]: c for c in sc.get("creatures", [])}

    def attack(who, target, label):
        """`who` turns to `target` and attacks it once; its use, once it has an outcome."""
        t0 = now()
        at = home[target]
        s.graph(who, {"seq": [{"first": [{"do": {"skill": "face", "target": {"at": [at[0], at[1]]}}}, {"wait": 0.1}]},
                              {"do": {"skill": "attack", "target": {"id": target}}}, {"wait": 60 + next(rounds)}]})
        done = s.wait(lambda: [x for x in s.rows("SELECT * FROM skill_use") if x["at_ms"] >= t0 and x["actor"] == who and x["skill"] == "attack" and x["outcome"]] or None, seconds=30, every=1)
        s.graph(who, {"wait": 1.0 + 0.01 * next(rounds)})
        time.sleep(1)
        return t0, done[0], uses(t0, label)

    at_me = {"who": "person", "is": "hostile", "phase": "about to release", "at_me": True}
    try:
        for c in cast:
            s.graph(c, {"wait": 60 + next(rounds)})
        place()
        s.call("install_script", compose(shipped, {"perceived_of": 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 3.0 { r.name = false; r.health = "none"; r.far = true; } r }'}))
        set_law(s, "fov_on", True)
        set_law(s, "fov_near_m", 0.5)
        set_law(s, "fov_near_dark_m", 0.5)
        # A `think` asks only 45 s after arrival (`brain.rs`: a fresh decision is not second-guessed).
        time.sleep(max(1.0, 47.0 - (time.monotonic() - born)))

        # 1. In front, in the field: the routine dodges in the second half of the windup.
        place()
        facing_east()
        routine("front", at_me)
        time.sleep(1)
        t0, use, got = attack(a, w, "front")
        dodges = [x for x in got if x["actor"] == w and x["skill"] == "dodge"]
        wind = (use["accepted_ms"], use["released_ms"])
        half = wind[0] + (wind[1] - wind[0]) / 2
        s.expect("front (field on): W's routine dodges A's attack", dodges, {"attack": use, "dodges": dodges})
        s.expect("front (field on): the dodge starts in the second half of the windup (about to release), not before",
                 wind[0] > 0 and half - 1 <= dodges[0]["at_ms"] <= wind[1], {"windup": wind, "half": half, "dodge_at": dodges[0]["at_ms"]})
        # A dodge is committed (committed-moves): the dash turns W's back on A and the routine's
        # condition stops holding, but the dodge runs its course and the blow misses. Before,
        # it was broken off about 66 ms in and the blow landed.
        s.expect("front (field on): the dodge runs its course though A leaves the field (committed), and the blow misses",
                 dodges[0]["outcome"] == "made way" and "hit" not in use["outcome"], {"dodge": dodges[0]["outcome"], "attack": use["outcome"]})
        # 2. Behind, outside the field (near ring 0.5 m): not seen, not dodged.
        place()
        facing_east()
        routine("behind", at_me)
        time.sleep(1)
        t0, use, got = attack(b, w, "behind")
        dodges = [x for x in got if x["actor"] == w and x["skill"] == "dodge"]
        s.expect("behind: B's attack from outside the field is not dodged", use["accepted_ms"] > 0 and not dodges, {"attack": use, "dodges": dodges})

        # 3. Field off (sight all round): the same routine against A again; nothing turns A out
        # of sight, the dodge carries through, and W's scene (taken by the branch's `think`, the
        # last request: no blow lands to ask again) shows what W saw.
        set_law(s, "fov_on", False)
        place()
        facing_east()
        routine("front-all-round", at_me)
        time.sleep(1)
        t0, use, got = attack(a, w, "front-all-round")
        dodges = [x for x in got if x["actor"] == w and x["skill"] == "dodge"]
        wind = (use["accepted_ms"], use["released_ms"])
        half = wind[0] + (wind[1] - wind[0]) / 2
        s.expect("front (all round): the dodge starts in the second half of the windup", dodges and wind[0] > 0 and half - 1 <= dodges[0]["at_ms"] <= wind[1],
                 {"windup": wind, "half": half, "dodges": dodges})
        s.expect("front (all round): A's blow does not land", "hit" not in use["outcome"], {"attack": use["outcome"], "dodge": dodges[0]["outcome"] if dodges else None}, fatal=False)
        seen = s.wait(lambda: scene_since(t0, "front"), seconds=10)
        v = seen.get(a, {}).get("visibly")
        s.expect("front: W's scene shows A visibly attacking, about to release, at you", v == {"is": "attack", "phase": "about to release", "at": "you"}, seen.get(a))

        # 4. F, 5 m off and too far to make out, holds up a guard: seen, and W reacts. A guard is
        # aimed at nobody; its `at` is "you" only when F happens to face W (its drawn aim).
        place()
        guard = {"who": "person", "is": "guard", "phase": "holding"}
        routine("far", guard)
        t0 = now()
        s.graph(f, {"first": [{"do": {"skill": "block", "qty": 5000}}]})
        got = s.wait(lambda: [x for x in uses(t0, "far") if x["actor"] == w and x["skill"] == "dodge"] or None, seconds=15)
        s.expect("far: F's guard 5 m off (seen) triggers W's routine", got, got[:1])
        seen = s.wait(lambda: scene_since(t0, "far"), seconds=10)
        fe = seen.get(f, {})
        s.expect("far: W's scene shows F as someone too far away to make out, visibly holding a block",
                 fe.get("who") == FAR and "name" not in fe and {k: v for k, v in (fe.get("visibly") or {}).items() if k != "at"} == {"is": "block", "phase": "holding"}
                 and (fe.get("visibly") or {}).get("at", "you") == "you", fe)
        s.graph(f, {"wait": 60 + next(rounds)})
        time.sleep(1.5)

        # 5. G's guard 14 m off, beyond sight: nothing.
        place()
        routine("beyond", guard)
        t0 = now()
        s.graph(g, {"first": [{"do": {"skill": "block", "qty": 5000}}]})
        time.sleep(6)
        got = uses(t0, "beyond")
        blocks = [x for x in got if x["actor"] == g and x["skill"] == "block"]
        dodges = [x for x in got if x["actor"] == w and x["skill"] == "dodge"]
        s.expect("beyond sight: G's guard (14 m) does not trigger W's routine", blocks and not dodges, {"blocks": len(blocks), "dodges": dodges})
    finally:
        s.call("install_script", shipped, check=False)
        set_law(s, "fov_on", False, check=False)
        set_law(s, "fov_near_m", 3.0, check=False)
        set_law(s, "fov_near_dark_m", 2.0, check=False)
        for c in cast:
            s.graph(c, {"wait": 60 + next(rounds)})
        off_the_line(s, line, cast, dy=56)


def committed(s):
    """A committed move runs its whole course whoever controls the body (committed-moves; the
    `committed` trait of `<skill>_combat()`, `combat::committed`), and ends early only by
    something physical. On the world's map (`wall_geometry`): P stands a tile back from a wall
    and its routine dodges toward it: the rules cut the dash at the wall (the farthest free point
    with a clear line), so it covers about half its length and ends in about half its time;
    the same dodge the open way covers its whole length. Then W winds up an attack on Y and is
    killed (admin `kill`) inside its 650 ms windup: the attack never releases, Y takes no blow.
    (No rule staggers on a hit today, so a blow does not end a committed move.) Last, a routine
    that dodges while it stands (`{"moving": false}`, a condition the dash itself ends), in a
    fight (a threat engages it, so its graph is looked at about 15 times a second): the dodge
    runs its course; then the world's own laws make the dodge uncommitted (an overlay through
    `floors::compose`, `install_script.py`'s `compose_laws`, installed by the admin), and the same
    routine's dodge is broken off as its condition stops holding, while a jump stays committed.

    Staging (fix-committed-staging): every check has characters of its own, spawned for it and
    set to wait; the spots it uses are first cleared of every other body (an earlier run's actors
    stay where they were left, and `place_at` would put the next one beside them), and each body
    is read back where it was put, standing, with its breath full, before the check starts. The
    shipped script is installed first when the world runs another (an interrupted run's overlay)
    and again at the end. The kill is timed off W's windup as the authority shows it (its
    `fighter` row, read over HTTP), not a fixed sleep."""
    geo = wall_geometry(s)
    (s.out / f"{s.name}-geometry.json").write_text(json.dumps(geo) + "\n")
    eye, hidden, opened = geo["eye"], geo["hidden"], geo["open"]
    ax, ay = (hidden[0] - eye[0], hidden[1] - eye[1])
    n = math.hypot(ax, ay)
    ux, uy = ax / n, ay / n
    back = (eye[0] - ux, eye[1] - uy)
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    rounds = iter(range(1000))
    spots = [back, opened, eye, hidden, (back[0] - 4 * ux, back[1] - 4 * uy)]
    tool = importlib.util.spec_from_file_location("install_script", ROOT / "living/tools/install_script.py")
    inst = importlib.util.module_from_spec(tool)
    tool.loader.exec_module(inst)
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    cast = []

    def at_of(c):
        b = s.rows(f"SELECT x, y FROM body WHERE id = {c}")[0]
        return (b["x"], b["y"])

    def fresh(k):
        made = s.people(k)
        cast.extend(made)
        return made

    def clear(keep):
        """Every body within 7 m of the scene's spots but `keep` goes 60 m off (earlier runs' actors
        and residents who wandered in)."""
        bodies = s.rows("SELECT id, x, y FROM body")
        alive = {c["id"] for c in s.rows("SELECT id, alive FROM character") if c["alive"]}
        for k, b in enumerate(x for x in bodies if x["id"] in alive and x["id"] not in keep and any(math.dist((x["x"], x["y"]), q) < 7 for q in spots)):
            s.graph(b["id"], {"wait": 120})
            s.call("place_at", b["id"], opened[0] + 60 + 2 * (k % 10), opened[1] + 50 + 2 * (k // 10), check=False)

    def stage(who, at, label):
        """`who` waits at `at` (exactly: read back), standing, breath full."""
        s.graph(who, {"wait": 30 + next(rounds)})
        s.call("place_at", who, *at)
        def settled():
            b = s.rows(f"SELECT x, y, vx, vy FROM body WHERE id = {who}")[0]
            v = s.vitals(who)
            full = breath_now(v, now())[0] >= v["stamina_max"] - 0.5
            return math.dist((b["x"], b["y"]), at) < 0.3 and b["vx"] == 0 and b["vy"] == 0 and full
        s.wait(settled, 10, every=0.5)
        (s.out / f"{s.name}-staged-{label}-{who}.json").write_text(json.dumps({"at": at_of(who), "vitals": s.vitals(who)}, indent=2) + "\n")

    def use_of(t0, who, skill, seconds=15):
        return s.wait(lambda: [x for x in s.rows("SELECT * FROM skill_use") if x["at_ms"] >= t0 and x["actor"] == who and x["skill"] == skill and x["outcome"]] or None, seconds)[0]

    def dash(label, toward):
        p = fresh(1)[0]
        clear(set(cast))
        stage(p, back, label)
        start = at_of(p)
        t0 = now()
        s.graph(p, {"seq": [{"do": {"skill": "dodge", "target": {"at": [toward[0], toward[1]]}}}, {"wait": 30 + next(rounds)}]})
        u = use_of(t0, p, "dodge")
        time.sleep(0.5)
        end = at_of(p)
        out = {"actor": p, "start": start, "end": end, "moved": round(math.dist(start, end), 2), "ms": u["outcome_ms"] - u["accepted_ms"], "outcome": u["outcome"]}
        (s.out / f"{s.name}-dash-{label}.json").write_text(json.dumps({"use": u, **out}, indent=2) + "\n")
        return out

    def engaged(who):
        st = s.rows(f"SELECT fast_until FROM mind_state WHERE id = {who}")
        return st and st[0]["fast_until"] > now() + 1500

    def standing(label, skill):
        """A fresh P in a fight (a fresh Z threatens it), its routine doing `skill` while it stands."""
        p, z = fresh(2)
        clear(set(cast))
        stage(p, opened, label)
        s.call("place_near", z, p)
        s.graph(z, {"seq": [{"do": {"skill": "threaten", "target": {"id": p}}}, {"wait": 30 + next(rounds)}]})
        s.wait(lambda: engaged(p), 10, every=0.3)
        s.graph(z, {"wait": 30 + next(rounds)})
        stage(p, opened, label + "-again")
        s.expect(f"{label}: P is in a fight (its graph is looked at at fight cadence)", engaged(p), s.rows(f"SELECT fast_until FROM mind_state WHERE id = {p}"))
        t0 = now()
        s.graph(p, {"first": {"label": f"standing-{label}", "children": [
            {"if": {"cond": {"moving": False}, "then": {"do": skill}}}, {"wait": 0.2 + 0.001 * next(rounds)}]}})
        u = use_of(t0, p, skill)
        s.graph(p, {"wait": 30 + next(rounds)})
        (s.out / f"{s.name}-standing-{label}.json").write_text(json.dumps(u, indent=2) + "\n")
        return u

    def script_is(src):
        return s.rows("SELECT source FROM script WHERE name = 'skills'")[0]["source"].strip() == src.strip()

    try:
        if not script_is(shipped):
            s.call("install_script", shipped)
            time.sleep(1.5)
        full = dash("open", (back[0] - 4 * ux, back[1] - 4 * uy))
        s.expect("a dodge the open way covers its whole length (2.6 m) in about 0.5 s", full["outcome"] == "made way" and full["moved"] > 2.2 and 400 <= full["ms"] <= 650, full)
        walled = dash("wall", hidden)
        s.expect("a dodge toward a wall ends early, at the wall (shorter and sooner than the open one)",
                 walled["outcome"] == "made way" and walled["moved"] < full["moved"] - 0.8 and walled["ms"] < full["ms"] - 100, {"wall": walled, "open": full})

        # Death inside a committed windup: the attack never releases. A fresh pair each try; the
        # kill goes as soon as W's windup shows (its `fighter` row), well inside 650 ms.
        code = next(c["code"] for c in s.rows("SELECT skill, code FROM skill_card") if c["skill"] == "attack")
        tries = []
        for k in range(3):
            w, y = fresh(2)
            clear(set(cast))
            stage(w, opened, f"death-{k}")
            s.call("place_near", y, w)
            s.graph(y, {"wait": 60})
            time.sleep(0.5)
            hp0 = s.vitals(y)["hp"]
            t0 = now()
            s.http_call("set_behavior", [w, json.dumps({"seq": [{"do": {"skill": "attack", "target": {"id": y}}}, {"wait": 30 + next(rounds)}]})])
            end = time.monotonic() + 5
            seen = None
            while time.monotonic() < end and not seen:
                f = s.http_rows(f"SELECT act, act_ms, release_ms FROM fighter WHERE id = {w}")
                seen = next((r for r in f if r["act"] == code and r["act_ms"] >= t0), None)
            if seen:
                s.http_call("kill", [w, "verify: killed inside a windup"])
                killed_ms = now()
            time.sleep(1.5)
            use = next((x for x in s.rows("SELECT * FROM skill_use", f"death-uses-{k}") if x["at_ms"] >= t0 and x["actor"] == w and x["skill"] == "attack"), None)
            dead = s.rows(f"SELECT alive, cause FROM character WHERE id = {w}")[0]
            hit = [r for r in s.rows(f"SELECT * FROM experience WHERE observer = {y}") if r["at_ms"] >= t0 and r["subject"] == w and "attacked you" in r["text"]]
            tries.append({"windup": seen, "use": use, "dead": dead, "hit": hit, "y_hp": [hp0, s.vitals(y)["hp"]]})
            if seen and use:
                break
        last = tries[-1]
        use = last["use"]
        s.expect("death inside a committed windup ends it: the attack never releases and lands nothing",
                 last["windup"] and use and use["accepted_ms"] > 0 and use["released_ms"] == 0 and not last["dead"]["alive"] and not last["hit"] and last["y_hp"][1] >= last["y_hp"][0] - 0.01,
                 {"tries": tries})

        # A condition the dash ends: shipped, the dodge runs on; uncommitted by the world's laws,
        # it is broken off; the jump, still committed there, runs on.
        u = standing("shipped", "dodge")
        s.expect("shipped: a routine's dodge runs its course though the condition that started it (standing) stops holding", u["outcome"] == "made way", u)
        s.call("install_script", inst.compose_laws(shipped, "fn dodge_combat() { let s = base_dodge_combat(); s.committed = false; s }"))
        src = s.rows("SELECT source FROM script WHERE name = 'skills'")[0]["source"]
        s.expect("the world's laws make the dodge uncommitted (an overlay over the shipped script)", "base_dodge_combat" in src and "s.committed = false" in src, len(src))
        time.sleep(1.5)
        u = standing("uncommitted", "dodge")
        s.expect("uncommitted by the world's laws: the same routine's dodge is broken off as its condition stops holding", u["outcome"].startswith("broken off"), u)
        j = standing("jump", "jump")
        s.expect("the jump, still committed in that world, runs its course", j["outcome"] == "made way", j)
    finally:
        s.call("install_script", shipped, check=False)
        # Off the spots, so the next run on this world finds them clear.
        for k, c in enumerate(cast):
            s.call("set_behavior", c, json.dumps({"wait": 120}), check=False)
            s.call("place_at", c, opened[0] + 60 + 2 * (k % 10), opened[1] - 50 - 2 * (k // 10), check=False)


def doing_cost(s):
    """What the `doing` condition costs in a crowded fight (docs/PERCEPTION.md, "What someone is
    visibly doing", cost): `spawn_battle` packs N spear fighters within 14 m; each attacks the
    nearest person and defends when threatened. Two windows of `living/tools/bench.py` (profiling
    spans): the battle's own graphs (`threatened`), then the same graphs with the guard read from
    `{"doing": {"who": "person", "is": "hostile", "phase": "about to release", "at_me": true}}`.
    Reports `brain.doing` (count, p50, p99, ms/s), `brain.scene` and the tick in each. No pass
    mark: a measurement. N from DOING_COST_N (default 100), seconds from DOING_COST_S (20)."""
    n = int(os.environ.get("DOING_COST_N", "100"))
    secs = int(os.environ.get("DOING_COST_S", "20"))
    before = {c["id"] for c in s.rows("SELECT id FROM character")}
    s.call("spawn_battle", n)
    fighters = [c["id"] for c in s.rows("SELECT id, name FROM character") if c["id"] not in before and c["name"].startswith("Fighter")]
    s.expect("the battle's fighters are spawned", len(fighters) >= n * 0.9, len(fighters))

    def bench(label):
        r = subprocess.run(["python3", str(ROOT / "living/tools/bench.py"), "--db", s.db, "--seconds", str(secs), "--settle", "2", "--log-lines", str(secs * 4000 + 20000)],
                           capture_output=True, text=True, timeout=secs * 6 + 300)
        (s.out / f"{s.name}-bench-{label}.txt").write_text(r.stdout + r.stderr)
        rep = json.loads(r.stdout[r.stdout.index("{"):])
        (s.out / f"{s.name}-bench-{label}.json").write_text(json.dumps(rep, indent=2) + "\n")
        return rep

    def pick(rep):
        sp = rep.get("spans_ms", {})
        return {"tick_ms": rep.get("tick_ms"), "evals_per_s": rep.get("evals_per_s"), "combat": rep.get("combat"), **{k: sp.get(k) for k in ("brain.doing", "brain.scene", "tick.combat")}}

    base = bench("threatened")
    for fid in fighters:
        defend = "dodge" if fid % 2 == 0 else "block"
        s.call("set_behavior", fid, json.dumps({"first": {"label": "combat", "children": [
            {"if": {"cond": {"doing": {"who": "person", "is": "hostile", "phase": "about to release", "at_me": True}}, "then": {"do": {"skill": defend}}}},
            {"do": {"skill": "attack", "target": {"nearest": "person"}}}]}}))
    s.rows(f"SELECT * FROM brain WHERE id = {fighters[0]}", "installed-graph")
    arm = bench("doing")
    out = {"fighters": len(fighters), "seconds": secs, "threatened": pick(base), "doing": pick(arm),
           "graph_scenes": {"threatened": base.get("graph_scenes"), "doing": arm.get("graph_scenes")}}
    (s.out / f"{s.name}-cost.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2), flush=True)
    s.expect("the doing condition was evaluated and timed", (arm.get("spans_ms", {}).get("brain.doing") or {}).get("n", 0) > 0, out["doing"])
    for fid in fighters:
        s.call("set_behavior", fid, json.dumps({"wait": 300}), check=False)


def outcomes(s):
    """Whoever strikes or shoots is told how it came out (the `force_outcomes` law,
    docs/COMBAT_MIND.md §3.1). Before 2026-11-11 a mind-held archer was never told how its
    arrow went (0 of 10 tries in the wolves trials), while `attack` reported "hit for 7".
    Three minded people (`spawn_crowd`, no mind service): an archer shoots a still target 4.5 m
    off (told "struck …: hit for N" when the arrow lands), a striker beside the target strikes
    it (told "hit for N"), the archer looses at an empty point past its sight (told it came to
    nothing), and with the law off a hit is not told."""
    a, b, c = s.people(3)
    # Earlier scenes on the same world (a duel's strikes in `fov`) leave outcome lines of their own.
    t_scene = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    here = body_at(s, a)
    # 4.5 m: within sight by night too (6 m), so the archer sees its target at any hour.
    s.call("place_at", b, here[0] + 4.5, here[1])
    s.call("place_at", c, here[0] + 4.5, here[1] + 1.2)
    s.call("grant_items", a, "bow", 1)
    s.call("grant_items", a, "arrow", 20)
    time.sleep(1.0)
    gap = apart(s, a, b)
    s.expect("archer and target 4-8 m apart, in the open", 4.0 <= gap <= 8.0, gap)

    def own(actor, words):
        return [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {actor}") if r["kind"] == "own" and words in r["text"]]

    s.graph(a, {"seq": [{"do": {"skill": "bowshot", "target": {"id": b}}}, {"wait": 60}]})
    hit = s.wait(lambda: own(a, "You finished: bowshot") or own(a, "You failed to bowshot"), seconds=20)
    s.rows(f"SELECT * FROM experience WHERE observer = {a}", "archer-told")
    s.rows(f"SELECT * FROM skill_use WHERE actor = {a}", "archer-uses")
    s.expect("the archer is told its arrow struck the target, with the damage",
             any("struck" in r["text"] and ("hit for" in r["text"] or "got through" in r["text"]) for r in hit), [r["text"] for r in hit])

    s.graph(c, {"seq": [{"do": {"skill": "strike", "target": {"id": b}}}, {"wait": 60}]})
    blow = s.wait(lambda: own(c, "You finished: strike") or own(c, "You failed to strike"), seconds=20)
    s.rows(f"SELECT * FROM experience WHERE observer = {c}", "striker-told")
    s.expect("the striker is told its blow's outcome", any("hit for" in r["text"] or "got through" in r["text"] for r in blow), [r["text"] for r in blow])

    # An arrow loosed at an empty point 20 m off (beyond day sight, 11 m) comes to nothing.
    far = (here[0] - 20.0, here[1])
    s.graph(a, {"seq": [{"do": {"skill": "bowshot", "target": {"at": [far[0], far[1]]}}}, {"wait": 60}]})
    gone = s.wait(lambda: [r for r in own(a, "You failed to bowshot") if any(w in r["text"] for w in ("out of your sight", "hit nothing", "struck a wall"))], seconds=20)
    s.expect("an arrow that reaches no one is told as coming to nothing", bool(gone), [r["text"] for r in gone])

    # Bounded to the maker: every outcome line in the world for these moves is the archer's or
    # the striker's own, never a bystander's or the target's.
    lines = [r for r in s.rows("SELECT observer, kind, text, at_ms FROM experience", "outcome-lines")
             if r["kind"] == "own" and r["at_ms"] >= t_scene and any(r["text"].startswith(p) for p in ("You finished: bowshot", "You failed to bowshot", "You finished: strike", "You failed to strike"))]
    s.expect("outcome lines reach the one who made the move only",
             lines and all((r["observer"] == a) == ("bowshot" in r["text"]) and r["observer"] in (a, c) for r in lines),
             sorted({(r["observer"], r["text"][:40]) for r in lines}))

    # The switch: with the law off, a hit is not told (the archer's lines stay as they were).
    set_law(s, "force_outcomes", False)
    before = len(own(a, "You finished: bowshot"))
    s.graph(a, {"seq": [{"do": {"skill": "bowshot", "target": {"id": b}}}, {"wait": 60}]})
    s.wait(lambda: [u for u in s.rows(f"SELECT outcome FROM skill_use WHERE actor = {a}") if u["outcome"].startswith("struck")][1:], seconds=20)
    time.sleep(1.0)
    after = len(own(a, "You finished: bowshot"))
    s.rows(f"SELECT * FROM skill_use WHERE actor = {a}", "archer-uses-law-off")
    set_law(s, "force_outcomes", True)
    s.expect("with force_outcomes off, a hit is not told", after == before, {"before": before, "after": after})

    names_told(s)
    missiles_told(s)


def missiles_told(s):
    """A hit by a missile is told as a shot, never as an attack (fix-missile-told): to the one
    struck, by the shooter as it perceives them when it sees them ("A stranger shot you with an
    arrow: hit for 7"), else by the missile alone ("An arrow struck you from somewhere you could
    not see: hit for 7"); to a witness the same way ("A stranger shot a stranger with an
    arrow"). The missile is named by its skill's `called` (`<skill>_missile`). Four strangers:
    an archer, a target 4.5 m off (within night sight) with a witness beside it, and a far target 19 m off (past day
    sight, within the bow's 22 m) shot at by a point aim. No line any of them is told about the
    arrows says "attacked", and the unseen shot names no one."""
    a, b, w, f = s.people(4)
    here = body_at(s, a)
    # 4.5 m: within sight by night too (6 m); the far target stays past day sight (11 m), and
    # the line to it passes 1.4 m clear of the near target and the witness.
    s.call("place_at", b, here[0] + 4.5, here[1])
    s.call("place_at", w, here[0] + 4.5, here[1] + 1.5)
    s.call("place_at", f, here[0] + 19.0, here[1] - 6.0)
    s.call("grant_items", a, "bow", 1)
    s.call("grant_items", a, "arrow", 20)
    time.sleep(1.0)
    names = {c["id"]: c["name"] for c in s.rows("SELECT id, name FROM character") if c["id"] in (a, b, w, f)}

    def lines(obs):
        return s.rows(f"SELECT kind, subject, text FROM experience WHERE observer = {obs}")

    s.graph(a, {"seq": [{"do": {"skill": "bowshot", "target": {"id": b}}}, {"wait": 60}]})
    struck = s.wait(lambda: [r for r in lines(b) if r["kind"] == "attacked"], seconds=20)
    s.rows(f"SELECT * FROM experience WHERE observer = {b}", "shot-victim-told")
    s.expect("the one struck is told it was shot with an arrow, by the shooter as it sees them",
             any(re.match(r"^(A stranger|Someone[^:]*) shot you with an arrow: (hit for \d+|blocked, \d+ got through)$", r["text"]) and r["subject"] == a for r in struck),
             [r["text"] for r in struck])
    seen = s.wait(lambda: [r for r in lines(w) if r["kind"] == "fight"], seconds=10)
    s.rows(f"SELECT * FROM experience WHERE observer = {w}", "shot-witness-told")
    s.expect("a witness who sees the shooter is told it shot the one struck with an arrow",
             any(re.search(r"shot .* with an arrow", r["text"]) for r in seen), [r["text"] for r in seen])

    s.graph(a, {"seq": [{"do": {"skill": "bowshot", "target": {"at": [here[0] + 19.0, here[1] - 6.0]}}}, {"wait": 60}]})
    far = s.wait(lambda: [r for r in lines(f) if r["kind"] == "attacked"], seconds=20)
    s.rows(f"SELECT * FROM experience WHERE observer = {f}", "unseen-victim-told")
    s.rows(f"SELECT * FROM skill_use WHERE actor = {a}", "archer-uses")
    s.expect("one struck by an unseen shooter is told only the arrow, from somewhere it could not see",
             any(re.match(r"^An arrow struck you from somewhere you could not see: (hit for \d+|blocked, \d+ got through)$", r["text"]) and r["subject"] == 0 for r in far),
             [(r["text"], r["subject"]) for r in far])
    told = [r for o in (b, w, f) for r in lines(o) if r["kind"] in ("attacked", "fight", "combat")]
    s.expect("no line about the arrows says \"attacked\", or a name its hearer was not told",
             told and not [r for r in told if "attacked" in r["text"] or any(n in r["text"] for n in names.values())],
             [r["text"] for r in told])


def names_told(s):
    """Every told line names others as the teller perceives them (fix-kill-name): a name it was
    told, else "a stranger" (or "a baby", the far label), never a real name it does not know.
    Four strangers (`spawn_crowd`) act on each other through the ordinary acts: a gift, an offer
    and its acceptance (a trade), a demand, teaching, a bow shot, and a melee strike until the
    one struck dies, with a fourth standing by as witness. Then no line any of them was told,
    and no outcome in their `skill_use`, carries the name of one of the others it has not been
    introduced to (`acquaintance`). Before fix-kill-name a melee kill read "killed Agnes Fenner",
    and an arrow's record "struck Wren"."""
    p, q, r, w = s.people(4)
    here = body_at(s, p)
    for who, (dx, dy) in ((q, (1.2, 0.0)), (r, (0.0, 1.2)), (w, (2.5, 2.5))):
        s.call("place_at", who, here[0] + dx, here[1] + dy)
    s.call("grant_items", p, "stone", 3)
    s.call("grant_items", p, "spear", 1)
    s.call("grant_items", p, "bow", 1)
    s.call("grant_items", p, "arrow", 10)
    s.call("grant_items", q, "berries", 3)
    s.call("grant_items", r, "berries", 3)
    s.call("grant_know_how", p, "fire")
    t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    time.sleep(1.0)
    s.act(p, {"do": "give", "target": {"id": q}, "item": "stone", "qty": 1})
    s.act(p, {"do": "offer", "target": {"id": q}, "item": "stone", "qty": 1, "want": "berries", "want_qty": 1})
    time.sleep(3.0)
    s.act(q, {"do": "accept", "target": {"id": p}})
    s.act(p, {"do": "demand", "target": {"id": r}, "item": "berries", "qty": 1, "text": "a toll"})
    time.sleep(3.0)
    s.act(p, {"do": "teach", "target": {"id": q}, "item": "fire"})
    # Teaching takes a while: wait for its outcome (done or not) before the next scene.
    s.wait(lambda: [e for e in s.rows(f"SELECT kind, text FROM experience WHERE observer = {p}") if e["kind"] == "act" and "teach" in e["text"]], seconds=90, every=2)
    # A shot at the witness-to-be, then the strike that kills r, the witness standing by.
    s.graph(p, {"seq": [{"do": {"skill": "bowshot", "target": {"id": w}}}, {"wait": 60}]})
    time.sleep(3.0)
    s.call("place_at", w, here[0] + 2.5, here[1] + 2.5)
    s.graph(p, {"seq": [{"do": {"skill": "strike", "target": {"id": r}}}, {"wait": 1}]})
    s.wait(lambda: not [c for c in s.rows(f"SELECT id, alive FROM character WHERE id = {r}") if c["alive"]], seconds=120, every=2)
    s.graph(p, {"wait": 60})
    time.sleep(2.0)
    people = {c["id"]: c["name"] for c in s.rows("SELECT id, name FROM character") if c["id"] in (p, q, r, w)}
    known = {(a["observer"], a["known"]) for a in s.rows("SELECT * FROM acquaintance") if a["observer"] in people}
    lines = [e for e in s.rows("SELECT id, observer, kind, text, at_ms FROM experience", "names-lines") if e["observer"] in people and e["at_ms"] >= t0]
    uses = [u for u in s.rows("SELECT id, actor, skill, outcome FROM skill_use", "names-uses") if u["actor"] in people]

    def leaks(observer, text):
        return [n for i, n in people.items() if i != observer and (observer, i) not in known and re.search(rf"\b{re.escape(n)}\b", text or "")]
    bad = [(e["observer"], e["kind"], e["text"][:120], leaks(e["observer"], e["text"])) for e in lines if leaks(e["observer"], e["text"])]
    bad += [(u["actor"], "skill_use:" + u["skill"], (u["outcome"] or "")[:120], leaks(u["actor"], u["outcome"])) for u in uses if leaks(u["actor"], u["outcome"])]
    kill = [e["text"] for e in lines if e["observer"] == p and e["kind"] == "own" and "killed" in e["text"]]
    seen_death = [e["text"] for e in lines if e["observer"] == w and "killed" in e["text"]]
    told = {k: [e["text"][:90] for e in lines if k in e["text"]][:3] for k in ("gave", "offer", "traded", "demand", "taught", "teach", "bowshot", "strike", "killed")}
    (s.out / f"{s.name}-names.json").write_text(json.dumps({"people": people, "known": sorted(known), "told_p": told, "kill": kill, "witness": seen_death, "leaks": bad}, indent=1) + "\n")
    s.expect("the killer is told the kill (a melee kill of a stranger)", bool(kill), [e["text"] for e in lines if e["observer"] == p][-8:])
    s.expect("the witness is told of the death", bool(seen_death), [e["text"] for e in lines if e["observer"] == w][-8:])
    s.expect("no told line or own outcome names someone the teller does not know", not bad, bad[:8])


def owners(s):
    """Whose a structure is, and what places are called, reach only those who know (owner-known,
    docs/PERCEPTION.md). On a world with an authored plan (`--seed plan-test`, or `cullet`):
    the public `land` row's params carry none of the seed's lot, spot or street names, which the
    private `land_plan` keeps; a newcomer standing at a resident's house is told only "house" (no
    `by` or `home_of` in its deliberation scene, no "built by" in what it notices, the owner's
    name nowhere), while the owner, and someone of the owner's community, are told whose it is."""
    seed = json.loads((ROOT / "living/seeds" / f"{json.loads((s.out / 'state.json').read_text())['seed']}.json").read_text())
    plan = seed["map"]["params"]["plans"][0]
    names = sorted({l["name"] for l in plan["lots"] if l.get("name")} | {sp["name"] for l in plan["lots"] for sp in l.get("spots", [])} | {st["id"] for st in plan.get("streets", []) if st.get("id")})
    public = s.rows("SELECT params FROM land", "land-public")[0]["params"]
    private = s.rows("SELECT params FROM land_plan", "land-private")
    s.expect("the public land row carries none of the seed's lot, spot or street names", not [n for n in names if f'"{n}"' in public], [n for n in names if f'"{n}"' in public][:6])
    s.expect("land_plan (private) keeps the full parameters with the names", private and all(f'"{n}"' in private[0]["params"] for n in names[:5]), len(private))
    s.expect("the public land row is no bigger than the full parameters (no defaults written out)", private and len(public) <= len(private[0]["params"]), f"{len(public)} vs {len(private[0]['params']) if private else None} bytes")
    people = {c["id"]: c for c in s.rows("SELECT id, name, alive, kind FROM character")}
    owned = [h for h in s.rows("SELECT id, kind, owner, x, y FROM structure", "owned") if h["owner"] and h["kind"] != "remains" and people.get(h["owner"], {}).get("alive")]
    houses = sorted(owned, key=lambda h: h["kind"] != "house")
    s.expect("a structure with a living owner", bool(houses), len(houses))
    members = {m["member"]: m["community"] for m in s.rows("SELECT member, community FROM membership")}
    house = next((h for h in houses if h["owner"] in members and any(o != h["owner"] and c == members[h["owner"]] and people.get(o, {}).get("alive") and people[o]["kind"] == "person" for o, c in members.items())), houses[0])
    owner = house["owner"]
    owner_name = people[owner]["name"]
    fellow = next((o for o, c in members.items() if o != owner and c == members.get(owner) and people.get(o, {}).get("alive") and people[o]["kind"] == "person"), None)

    def scene_of(who, marker):
        s.call("place_at", who, house["x"] + 1.5, house["y"] + 1.5)
        time.sleep(1.0)
        s.call("set_behavior", who, json.dumps({"think": f"I finished my plan. verify owners {marker}"}))
        row = s.wait(lambda: s.rows(f"SELECT * FROM deliberation WHERE actor = {who}"), seconds=60, every=2)[0]
        (s.out / f"{s.name}-scene-{marker}.json").write_text(row["scene"] + "\n")
        scene = json.loads(row["scene"])
        entry = next((x for x in scene.get("structures", []) if x.get("id") == house["id"]), None)
        s.call("set_behavior", who, json.dumps({"wait": 120}))
        return scene, entry, row["scene"]

    newcomer = s.people(1)[0]
    scene, entry, text = scene_of(newcomer, "newcomer")
    s.expect("the newcomer's scene shows the structure without whose it is", entry is not None and "by" not in entry and "home_of" not in entry, entry)
    noticed = [e["text"] for e in s.rows(f"SELECT kind, text FROM experience WHERE observer = {newcomer}") if house["kind"] in e["text"]]
    s.expect("the newcomer's own lines and scene never name the owner", owner_name not in text and not [t for t in noticed if owner_name in t or "built by" in t], noticed[:4])
    scene, entry, _ = scene_of(owner, "owner")
    s.expect("the owner is told the structure is its own", entry is not None and ("home_of" in entry or "by" in entry), entry)
    if fellow:
        scene, entry, _ = scene_of(fellow, "fellow")
        s.expect("someone of the owner's community is told whose it is, by name", entry is not None and owner_name in (entry.get("home_of"), entry.get("by")), {"entry": entry, "owner": owner_name})
    owners_away(s, house, owner, owner_name, fellow, newcomer)


FAR = "someone too far away to make out"


def owners_away(s, house, owner, owner_name, fellow, newcomer):
    """Where the owner stands never matters (house-owner-label, docs/PERCEPTION.md "Whose a thing
    is"): whether one can make someone out is about the person in sight, never their house. An
    overlay of the world's script makes anyone past 4 m too far away to make out (as Cullet's
    `perceived_of` does past 24 m) and lets a storage show its owner (`shows_owner`). With the owner
    50 m off: the fellow's scene still names the house's owner (`home_of`, `by`); a campfire the
    owner built is noticed by the fellow as "built by <owner>" and by the newcomer with no owner;
    the owner's storage, which shows its owner, is named to the newcomer too; and the newcomer's
    theft from it is witnessed by the fellow as taken "from <owner>'s storage". Those lines carry
    the owner by id (never a far figure's handle), and a line that does not name the owner does not
    carry them (subject 0). The world's own script is installed again at the end."""
    if not fellow:
        s.expect("someone of the owner's community, for the away checks", False, "no fellow in the owner's community")
    base = s.rows("SELECT source FROM script")[0]["source"]
    far_law = 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }'
    shows = 'fn structures() { let l = base_structures(); for i in 0..l.len() { if l[i].name == "storage" { l[i].shows_owner = true; } } l }'
    overlay = base.replace("fn perceived_of(p)", "fn base_perceived_of(p)", 1).replace("fn structures()", "fn base_structures()", 1) + "\n" + far_law + "\n" + shows + "\n"
    (s.out / f"{s.name}-overlay.rhai").write_text(overlay)
    hx, hy = house["x"], house["y"]
    try:
        s.call("install_script", overlay)
        for who in (owner, fellow, newcomer):
            s.graph(who, {"wait": 300})
        # The two onlookers far apart, so neither notices the owner's new things before its turn.
        s.call("place_at", fellow, hx + 1.5, hy - 40.0)
        s.call("place_at", newcomer, hx + 1.5, hy + 40.0)
        s.call("place_at", owner, hx + 1.5, hy + 1.5)
        time.sleep(1.0)
        s.call("place_structure", owner, "campfire")
        s.call("grant_items", owner, "berries", 3)
        s.call("place_at", owner, hx + 1.5, hy + 4.0)
        s.call("place_structure", owner, "storage")
        mine = {r["kind"]: r for r in sorted(s.rows(f"SELECT * FROM structure WHERE owner = {owner}", "owner-structures"), key=lambda r: r["id"])}
        fire, store = mine.get("campfire"), mine.get("storage")
        s.expect("the owner's new campfire and storage", fire and store, list(mine))
        s.act(owner, {"do": "store", "item": "berries", "qty": 3, "target": {"id": store["id"]}})
        s.wait(lambda: [e for e in s.rows(f"SELECT kind, text FROM experience WHERE observer = {owner}") if e["kind"] == "act" and "stored 3 berries" in e["text"]], seconds=30)
        s.call("place_at", owner, hx + 50.0, hy)
        time.sleep(1.5)
        ob = s.rows(f"SELECT * FROM body WHERE id = {owner}")[0]
        s.expect("the owner is far from its house (50 m)", abs(ob["x"] - hx) > 40, ob)

        def scene_at(who, marker, x, y):
            since = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
            s.call("place_at", who, x, y)
            time.sleep(1.5)
            s.call("set_behavior", who, json.dumps({"think": f"I finished my plan. verify owners {marker}"}))
            row = s.wait(lambda: s.rows(f"SELECT * FROM deliberation WHERE actor = {who}"), seconds=60, every=2)[0]
            (s.out / f"{s.name}-scene-{marker}.json").write_text(row["scene"] + "\n")
            s.call("set_behavior", who, json.dumps({"wait": 300}))
            rows = [e for e in s.rows(f"SELECT at_ms, kind, subject, object, text FROM experience WHERE observer = {who}") if e["at_ms"] >= since]
            (s.out / f"{s.name}-lines-{marker}.json").write_text(json.dumps(rows, indent=1) + "\n")
            scene_at.rows = rows
            return json.loads(row["scene"]), [e["text"] for e in rows]

        scene, lines = scene_at(fellow, "fellow-away", hx + 1.5, hy + 2.5)
        by_id = {x.get("id"): x for x in scene.get("structures", [])}
        h = by_id.get(house["id"], {})
        s.expect("owner away: the fellow's scene still names the house's owner", h.get("home_of") == owner_name and h.get("by") == owner_name, h)
        s.expect("owner away: no structure in the fellow's scene is labelled by a far figure", not [x for x in scene.get("structures", []) if FAR in json.dumps(x)], [x for x in scene.get("structures", []) if FAR in json.dumps(x)])
        s.expect("owner away: the fellow notices the owner's campfire as built by them, by name", any(f"campfire built by {owner_name}" in t for t in lines), [t for t in lines if "campfire" in t])
        s.expect("the fellow's notice line is about the owner by id, not a far figure's handle", [e["subject"] for e in scene_at.rows if "campfire built by" in e["text"]] == [owner], [e for e in scene_at.rows if "campfire" in e["text"]])
        # The newcomer, a stranger to the owner, beside the fellow: it watches the theft too.
        scene, lines = scene_at(newcomer, "newcomer-away", hx + 2.0, hy + 3.5)
        by_id = {x.get("id"): x for x in scene.get("structures", [])}
        s.expect("a stranger's house stays unnamed to the newcomer", "home_of" not in by_id.get(house["id"], {}) and "by" not in by_id.get(house["id"], {}), by_id.get(house["id"]))
        s.expect("the newcomer notices the campfire with no owner", any("campfire" in t for t in lines) and not any(f"campfire built by" in t for t in lines), [t for t in lines if "campfire" in t])
        s.expect("an owner the line does not name is not tied to it (subject 0)", [e["subject"] for e in scene_at.rows if e["text"].startswith("You notice a campfire")] == [0], [e for e in scene_at.rows if "campfire" in e["text"]])
        s.expect("a storage that shows its owner (shows_owner) names the owner to the newcomer", by_id.get(store["id"], {}).get("by") == owner_name, by_id.get(store["id"]))
        s.expect("the newcomer notices the storage as built by the owner, by name", any(f"storage built by {owner_name}" in t for t in lines), [t for t in lines if "storage" in t])
        since = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
        s.call("place_at", fellow, hx + 2.0, hy + 6.5)
        s.act(newcomer, {"do": "take", "item": "berries", "qty": 1, "target": {"id": store["id"]}})
        seen = s.wait(lambda: [e["text"] for e in s.rows(f"SELECT at_ms, kind, text FROM experience WHERE observer = {fellow}") if e["at_ms"] >= since and e["kind"] == "took"], seconds=40)
        (s.out / f"{s.name}-theft-seen.json").write_text(json.dumps(seen, indent=1) + "\n")
        s.expect("owner away: the fellow sees the berries taken from the owner's storage, by name", any(f"from {owner_name}'s storage" in t for t in seen), seen)
        took = [e for e in s.rows(f"SELECT at_ms, kind, subject, object, text FROM experience WHERE observer = {fellow}", "theft-rows") if e["at_ms"] >= since and e["kind"] == "took"]
        s.expect("the theft line's object is the owner by id, not a far figure's handle", took and all(e["object"] == owner for e in took), took)
    finally:
        s.call("install_script", base, check=False)



def apart_intent(s):
    """`apart` on the movement intents (docs/PACK_MIND.md, A5): bodies holding `keep_distance`
    3-5 m from one standing person, bunched on one side at the start, spread round it when each
    also keeps `apart` m from others of its own kind it sees, and stay bunched without it. The
    same for four people and for four wolves (any kind; a wolf's `keep_distance` is no attack,
    so no dare applies). Also: `apart` is refused on an intent that does not take it and out of
    its range, and with no one of its kind near a body holds its band as before."""
    c = open_patch(s, 16)
    centre, *ring = s.people(5)
    s.graph(centre, {"wait": 300})
    s.call("place_at", centre, *c)
    # Awake ones: a sleeper (a `slumber` row or a sleep under way) keeps lying where it is,
    # whatever graph it is given, until something wakes it.
    sleeping = {r["actor"] for r in s.rows("SELECT actor FROM slumber")} | {r["id"] for r in s.rows("SELECT id, skill FROM activity") if r["skill"] == "sleep"}
    wolves = [w["id"] for w in s.rows("SELECT id, stage FROM character WHERE kind = 'wolf' AND alive = true") if w["stage"] >= 2 and w["id"] not in sleeping][:4]
    s.expect("four grown wolves, awake, to use", len(wolves) == 4, {"awake": wolves, "asleep": sorted(sleeping)})
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    starts = [(-4.0, 0.0), (-4.0, 0.8), (-4.3, -0.7), (-3.7, 0.4)]

    def coverage(ids):
        t = now()
        cx, cy = body_at(s, centre, t)
        b = sorted(math.atan2(body_at(s, i, t)[1] - cy, body_at(s, i, t)[0] - cx) % (2 * math.pi) for i in ids)
        gaps = [b[k + 1] - b[k] for k in range(len(b) - 1)] + [b[0] + 2 * math.pi - b[-1]]
        dists = [math.dist(body_at(s, i, t), (cx, cy)) for i in ids]
        near = min(math.dist(body_at(s, i, t), body_at(s, j, t)) for i in ids for j in ids if i < j)
        return {"coverage": round(math.degrees(2 * math.pi - max(gaps)), 1), "dists": [round(d, 2) for d in dists], "nearest_pair": round(near, 2)}

    out = {}
    for kind, ids in (("people", ring), ("wolves", wolves)):
        for arm, extra in (("without", {}), ("apart4", {"apart": 4}), ("apart6", {"apart": 6})):
            for i, (dx, dy) in zip(ids, starts):
                s.graph(i, {"wait": 300})
                s.call("place_at", i, c[0] + dx, c[1] + dy)
            time.sleep(1.5)
            for i in ids:
                s.graph(i, {"do": {"skill": "keep_distance", "target": {"id": centre}, "min": 3, "max": 5, "qty": 60, **extra}})
            time.sleep(14)
            out[f"{kind}-{arm}"] = coverage(ids)
            for i in ids:
                s.graph(i, {"wait": 300})
            for i in ids:
                s.call("place_at", i, c[0] + 12, c[1] + 12 + ids.index(i))
            time.sleep(0.5)
    (s.out / f"{s.name}-apart.json").write_text(json.dumps(out, indent=1) + "\n")
    for kind in ("people", "wolves"):
        w0, w4, w6 = out[f"{kind}-without"], out[f"{kind}-apart4"], out[f"{kind}-apart6"]
        s.expect(f"{kind}: without apart they stay bunched on one side (coverage under 90°)", w0["coverage"] < 90, w0)
        s.expect(f"{kind}: apart 4 spreads them round it (coverage at least 150°, nearest pair at least 3 m)", w4["coverage"] >= 150 and w4["nearest_pair"] >= 3.0, w4)
        s.expect(f"{kind}: apart 6 spreads them wider than apart 4", w6["coverage"] > w4["coverage"], {"apart4": w4["coverage"], "apart6": w6["coverage"]})
        s.expect(f"{kind}: with apart each still holds its band (2.5-5.5 m)", all(2.5 <= d <= 5.5 for d in w4["dists"] + w6["dists"]), {"apart4": w4["dists"], "apart6": w6["dists"]})
    # Refusals: apart on an intent that does not take it, and out of its range.
    a = ring[0]
    for node, words in (({"do": {"skill": "back_off", "target": {"id": centre}, "apart": 4}}, "`apart` is for"),
                        ({"do": {"skill": "circle", "target": {"id": centre}, "apart": 0.5}}, "from 1 to 12")):
        r = s.call("set_behavior", a, json.dumps(node), check=False)
        said = (r.stdout or "") + (r.stderr or "")
        s.expect(f"refused: {words}", r.returncode != 0 and words in said, (r.returncode, said[-300:]))


def howl_reach(s):
    """A howl carries by its loudness (docs/PACK_MIND.md, decision 2): the shipped howl has no
    range of its own but loudness 2, so it reaches twice each listener's hearing (18 m on a world
    whose people hear 9 m), and, as loud as a shout, it wakes a sleeper within `wake_reach`
    (`wake_loudness` 2). On an open line: a wolf howls; a person asleep 6 m off wakes, told the
    howl; one awake 15 m off hears it; one 25 m off does not."""
    line = open_line(s, length=30)
    hearing = law_value(s, "wake_reach")
    sleeping = {r["actor"] for r in s.rows("SELECT actor FROM slumber")} | {r["id"] for r in s.rows("SELECT id, skill FROM activity") if r["skill"] == "sleep"}
    wolf = next(w["id"] for w in s.rows("SELECT id, stage FROM character WHERE kind = 'wolf' AND alive = true") if w["stage"] >= 2 and w["id"] not in sleeping)
    near, mid, far = s.people(3)
    s.graph(wolf, {"wait": 300})
    s.call("place_at", wolf, *line[0])
    s.call("place_at", near, *line[6])
    s.call("place_at", mid, *line[15])
    s.call("place_at", far, *line[25])
    s.graph(near, {"seq": [{"do": "sleep"}, {"wait": 300}]})
    # (`hearing` above is the wake reach: a loud sound wakes a sleeper within it)
    s.wait(lambda: s.rows(f"SELECT * FROM slumber WHERE actor = {near}"), seconds=30)
    s.graph(wolf, {"seq": [{"do": {"skill": "signal", "item": "howl"}}, {"wait": 300}]})
    s.wait(lambda: s.told(mid, "a long howl", "signal"), seconds=20)
    time.sleep(3)
    heard = {who: [r["text"] for r in s.told(i, "a long howl", "signal")] for who, i in (("6 m, asleep", near), ("15 m", mid), ("25 m", far))}
    (s.out / f"{s.name}-heard.json").write_text(json.dumps({"heard": heard, "wake_reach": hearing}, indent=1) + "\n")
    s.expect("a person 15 m off hears the howl (within twice the island's 9 m)", bool(heard["15 m"]), heard)
    s.expect("a person 25 m off does not (beyond 18 m)", not heard["25 m"], heard)
    # (its graph, a sleep then a wait, may lay it down again once woken: what shows the waking
    # is the line it is told, naming the howl)
    woke = [t for t in s.told(near, "You woke up: ", "body") if "a long howl" in t["text"]]
    s.expect("a sleeper 6 m off wakes, told of the howl", bool(woke), s.told(near, "You woke up", "body"))


def pack_reflex(s):
    """The wolves' spacing reflex, a world law (`pack_reflex`, docs/PACK_MIND.md): while it is
    on (the shipped value), every hunt in a wolf's starting graph (an attack on the nearest
    person or deer) sits beside the desire "keep apart from mates" (`keep_distance` 3-5 m from
    the prey with `apart` 4); with the law off, none does. Three install paths: a seed's pack
    (`packs[].instinct`, `wolf_bold`: the brain), a grown founding wolf's ways (`give_ways`,
    repertoire.json: its `hunt` routine), a young founding wolf's instinct (`wolf`: the brain).
    A newborn's `wolf_young` is never given it. Run it on `--seed pack-reflex-on` (expects the
    reflex) and `--seed pack-reflex-off` (expects none): it reads the law's value from the world."""
    on = law_value(s, "pack_reflex")
    bg = {r["id"]: r["text"] for r in s.rows("SELECT id, text FROM background")}
    wolves = s.rows("SELECT id, stage FROM character WHERE kind = 'wolf' AND alive = true")
    brains = {r["id"]: r for r in s.rows("SELECT id, graph, plan FROM brain")}
    hunts = {r["actor"]: r["graph"] for r in s.rows("SELECT actor, name, graph FROM routine") if r["name"] == "hunt"}
    seen = {"pack": [], "grown founders (hunt routine)": [], "young founders": [], "newborns": []}
    for w in wolves:
        b = brains.get(w["id"], {})
        if '"bold":true' in bg.get(w["id"], ""):
            key, g = "pack", b.get("graph", "")
        elif w["stage"] == 0:
            key, g = "newborns", b.get("graph", "")
        elif w["id"] in hunts:
            key, g = "grown founders (hunt routine)", hunts[w["id"]]
        else:
            key, g = "young founders", b.get("graph", "")
        seen[key].append({"id": w["id"], "stage": w["stage"], "reflexes": g.count("keep apart from mates"), "apart": '"apart"' in g, "plan": b.get("plan", "")[:40]})
    (s.out / f"{s.name}-wolves.json").write_text(json.dumps({"law": on, "wolves": seen}, indent=1) + "\n")
    s.expect("the world has a bold pack and grown founding wolves to check", bool(seen["pack"]) and bool(seen["grown founders (hunt routine)"]), {k: len(v) for k, v in seen.items()})
    checked = [x for k in ("pack", "grown founders (hunt routine)", "young founders") for x in seen[k]]
    if on:
        for k in ("pack", "grown founders (hunt routine)", "young founders"):
            s.expect(f"law on: {k}: the reflex beside both hunts (people and deer)", all(x["reflexes"] == 2 and x["apart"] for x in seen[k]), seen[k])
    else:
        s.expect("law off: no wolf's starting graph or hunt routine carries the reflex", all(x["reflexes"] == 0 for x in checked), seen)
    s.expect("a newborn's instinct (wolf_young) never carries it", all(x["reflexes"] == 0 for x in seen["newborns"]), seen["newborns"])

SCENES = {"say": say, "skirmish": skirmish, "infant": infant, "tick": tick, "needs": needs, "seize": seize, "lifecycle": lifecycle, "wildlife": wildlife, "grazing": grazing, "arrival": arrival, "sight": sight, "dealings": dealings, "answers": answers, "flee": flee, "flee_wall": flee_wall, "food": food, "refusal": refusal, "teach": teach, "senses": senses, "moves": moves, "remains": remains, "laws": laws, "doing": doing, "death-names": death_names, "drop": drop, "low": drop, "family_laws": family_laws, "fov": fov, "placement": placement, "alarms": alarms, "health_seen": health_seen, "audience": audience, "outcomes": outcomes, "crowd_sight": crowd_sight, "stranger_filter": stranger_filter, "cues": cues, "regard_check": regard_check}


def goods(s):
    """Goods are script data matched by trait, and fires eat fuel (docs/WORLD_RULES.md, "Goods,
    recipes and fuel"), on the goods fixture: Cullet's goods (the goods section of
    living/seeds/worlds/cullet/laws.rhai) composed over the shipped rules; kelp, peat and sand gathered from nodes placed beside a
    person; kelp burnt to ash at a hearth fed with peat; ash and sand melted to glass at a
    furnace, drawing a unit of its fuel; the hearth going out on its own, refusing what needs it
    burning, and lit again only by someone who knows fire; warmth only while it burns; a seeded
    fishing ground whose three spots share one stock."""
    # The fixture names Cullet's laws (`laws_file`), its goods among them: composed over the
    # shipped script and installed when the world was created, with the seed's own hearth (12
    # units of peat, lit from creation) and a kelp bed among its resource nodes.
    src = s.rows("SELECT source FROM script")[0]["source"]
    s.expect("the world was made with Cullet's laws and goods", "fn goods_structures()" in src and "fn recipes()" in src.split("---- floor overlay ----")[-1])
    hour_ms = s.rows("SELECT day_ms FROM world")[0]["day_ms"] / 24
    seeded = [r for r in s.rows("SELECT * FROM structure", "seeded-structures") if r["kind"] == "hearth"]
    clock = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.expect("the seed's hearth with fuel is lit from creation, for its fuel's burn", len(seeded) == 1 and clock < seeded[0]["lit_until_ms"] <= clock + 12 * 2 * hour_ms + 1000, {"hearth": seeded, "now": clock})
    s.expect("the seed placed a node of a kind its laws add (a kelp bed)", any(r["kind"] == "kelp_bed" for r in s.rows("SELECT kind FROM resource_node")))

    def now():
        return s.rows("SELECT last_ms FROM clock")[0]["last_ms"]

    def structure(kind, owner):
        return max((r for r in s.rows(f"SELECT * FROM structure WHERE owner = {owner}") if r["kind"] == kind), key=lambda r: r["id"])

    def node(kind):
        return max((r for r in s.rows("SELECT * FROM resource_node") if r["kind"] == kind), key=lambda r: r["id"])

    def acts(actor, *nodes):
        s.call("mind_act", actor, [json.dumps(n) for n in nodes], "verify-core")

    def heard(actor, words, since):
        return [r["text"] for r in s.rows(f"SELECT text, at_ms FROM experience WHERE observer = {actor}") if r["at_ms"] >= since and words in r["text"]]

    def near_fire(actor):
        # The needs' state key keeps whether the body is warmed by a fire (brain.rs, bit 6).
        return bool(s.vitals(actor)["rate_key"] & (1 << 6))

    people = [c["id"] for c in s.rows("SELECT id, kind FROM character") if c["kind"] == "person"]
    s.expect("the fixture's three people", len(people) == 3, people)
    knows = {p: [k["technique"] for k in s.rows(f"SELECT technique FROM know_how WHERE actor = {p}")] for p in people}
    unlit = [p for p in people if "fire" not in knows[p]]
    s.expect("someone who does not know fire", unlit, knows)
    b = unlit[0]
    a, c = [p for p in people if p != b][:2]
    for p in people:
        s.graph(p, {"wait": 120})
    # A clear spot by the seeded fishing ground; the furnace stands 9 m off, in sight, beyond the
    # reach of its warmth (6 m) from the one warmed by the hearth.
    s.call("place_at", a, 42.5, 42.0)
    s.call("place_near", c, a)
    s.call("place_structure", a, "hearth")
    ax, ay = body_at(s, a)
    s.call("place_at", b, ax + 9.0, ay)
    s.call("place_structure", b, "furnace")
    s.call("place_near", b, a)
    hearth, furnace = structure("hearth", a), structure("furnace", b)
    s.expect("a placed fire that burns fuel starts out", hearth["lit_until_ms"] == 0 and furnace["lit_until_ms"] == 0, [hearth, furnace])
    for kind, dx, dy in (("kelp_bed", 0.0, 1.0), ("peat_bank", 1.0, 1.0), ("sand_bank", 0.0, 2.0)):
        s.call("place_resource", a, kind, dx, dy, 0.0, 0)
    s.call("grant_know_how", a, "fire")
    s.call("grant_know_how", a, "glassmaking")
    s.call("grant_know_how", a, "cooking")

    # Gather: each node gives what its kind yields.
    # At most four acts wait at a time (rules::acts::MAX_QUEUED).
    for kind, item, n in (("kelp_bed", "kelp", 4), ("peat_bank", "peat", 4), ("peat_bank", "peat", 8), ("sand_bank", "sand", 2)):
        have = s.inventory(a).get(item, 0)
        acts(a, *[{"do": "gather", "target": {"nearest": kind}}] * (n - have))
        s.wait(lambda: s.inventory(a).get(item, 0) >= n, seconds=60, every=1)
    inv = s.inventory(a, "gathered")
    s.expect("kelp, peat and sand are gathered from their nodes", inv.get("kelp") == 4 and inv.get("peat") == 8 and inv.get("sand") == 2, inv)
    kelp = node("kelp_bed")
    s.expect("the kelp bed holds what was taken less", kelp["amount"] <= kelp["max"] - 4 + 0.5, kelp)

    # The hearth is out: what needs it burning is refused, and nobody is warmed by it.
    t0 = now()
    acts(a, {"do": "make", "item": "ash", "target": {"nearest": "hearth"}})
    s.wait(lambda: heard(a, "did not work out", t0), seconds=20)
    s.expect("making ash at an out hearth is refused", heard(a, "is out: feed it first", t0), heard(a, "", t0))
    time.sleep(3)
    s.expect("an out hearth warms nobody", not near_fire(c), s.vitals(c, "cold-before"))

    # Fed one peat, it is lit for one unit at its rate (0.5 a game hour: two game hours).
    t0 = now()
    acts(a, {"do": "feed", "item": "peat", "qty": 1, "target": {"nearest": "hearth"}})
    s.wait(lambda: structure("hearth", a)["lit_until_ms"] > 0, seconds=20)
    lit = structure("hearth", a)
    expect_ms = 2 * hour_ms
    s.expect("feeding lights the hearth: lit_until_ms is one unit's burn ahead", abs(lit["lit_until_ms"] - t0 - expect_ms) < 6000, {"lit_until_ms": lit["lit_until_ms"], "fed_after": t0, "unit_ms": expect_ms})
    s.expect("the peat fed is gone from the pack", s.inventory(a, "after-feed").get("peat") == 7)
    s.expect("lighting it is seen", [r for r in s.rows(f"SELECT kind, text FROM experience WHERE observer = {c}", "lit-witness") if "lit the hearth" in r["text"]])
    s.expect("a lit hearth warms those beside it", s.wait(lambda: near_fire(c), seconds=20, every=1), s.vitals(c, "warm-lit"))
    s.rows(f"SELECT id, kind, lit_until_ms FROM structure WHERE id = {lit['id']}", "hearth-lit")

    # Kelp burnt to ash at the burning hearth.
    acts(a, {"do": "make", "item": "ash", "target": {"nearest": "hearth"}})
    s.wait(lambda: s.inventory(a).get("ash", 0) == 1, seconds=30)
    inv = s.inventory(a, "after-ash")
    s.expect("four kelp burnt to one ash at the hearth", inv.get("ash") == 1 and inv.get("kelp", 0) == 0, inv)

    # Ash and sand melted into glass at the furnace, with a unit of its fuel.
    acts(a, {"do": "feed", "item": "peat", "qty": 5, "target": {"nearest": "furnace"}})
    s.wait(lambda: structure("furnace", b)["lit_until_ms"] > 0, seconds=60)
    fed = structure("furnace", b)["lit_until_ms"]
    # Glass is melted in a crucible the glassmaker holds and keeps (goods-3, a recipe's
    # `tools`): refused without one, in the rules' words naming it, and no fuel drawn.
    t0 = now()
    acts(a, {"do": "make", "item": "glass", "target": {"nearest": "furnace"}})
    s.wait(lambda: heard(a, "did not work out", t0), seconds=20)
    s.expect("glass without a crucible is refused, naming the tool", heard(a, "glass is made with a crucible in your pack, not used up", t0), heard(a, "", t0))
    s.expect("the refusal drew no fuel", structure("furnace", b)["lit_until_ms"] == fed)
    s.call("grant_items", a, "crucible", 1)
    acts(a, {"do": "make", "item": "glass", "target": {"nearest": "furnace"}})
    # Others see the work while it lasts (`make_shows`, goods-2): a `doing` row at the furnace.
    card = {r["skill"]: r["code"] for r in s.rows("SELECT skill, code FROM act_card", "act-cards")}
    s.expect("making and feeding are shown skills (act_card)", "make" in card and "feed" in card, card)
    work = s.wait(lambda: [r for r in s.rows(f"SELECT * FROM doing WHERE id = {a}") if r["code"] == card["make"]], seconds=20)
    fx, fy = structure("furnace", b)["x"], structure("furnace", b)["y"]
    s.expect("making glass is seen at the furnace while it lasts (doing)", abs(work[0]["x"] - fx) < 0.01 and abs(work[0]["y"] - fy) < 0.01, {"doing": work, "furnace": [fx, fy]})
    s.wait(lambda: s.inventory(a).get("glass", 0) == 1, seconds=60)
    inv = s.inventory(a, "after-glass")
    after = structure("furnace", b)
    unit = hour_ms / 3
    s.expect("an alkali and two sand make glass at the burning furnace", inv.get("glass") == 1 and inv.get("ash", 0) == 0 and inv.get("sand", 0) == 0, inv)
    s.expect("the crucible is held, not used up", inv.get("crucible") == 1, inv)
    s.expect("the glass took one unit of the furnace's fuel", abs((fed - after["lit_until_ms"]) - unit) < 1500, {"fed_until": fed, "after_until": after["lit_until_ms"], "unit_ms": unit})

    # The hearth burns down on its own: nothing is written until someone feeds it again.
    until = structure("hearth", a)["lit_until_ms"]
    s.wait(lambda: now() > until + 1000, seconds=int(expect_ms / 1000) + 60, every=2)
    out = structure("hearth", a)
    s.expect("the hearth is out once its fuel is spent (its row unchanged)", out["lit_until_ms"] == until and now() > until, out)
    s.expect("an out hearth warms nobody again", s.wait(lambda: not near_fire(c), seconds=30, every=1), s.vitals(c, "cold-after"))
    t0 = now()
    acts(a, {"do": "give", "item": "peat", "qty": 1, "target": {"id": b}})
    s.wait(lambda: s.inventory(b).get("peat", 0) == 1, seconds=20)
    acts(b, {"do": "feed", "item": "peat", "qty": 1, "target": {"nearest": "hearth"}})
    s.wait(lambda: heard(b, "did not work out", t0), seconds=20)
    s.expect("someone who does not know fire cannot light it", heard(b, "you don't know how to light a fire", t0), heard(b, "", t0))
    s.expect("and the hearth stays out", structure("hearth", a)["lit_until_ms"] == until)
    acts(a, {"do": "feed", "item": "peat", "qty": 1, "target": {"nearest": "hearth"}})
    s.wait(lambda: structure("hearth", a)["lit_until_ms"] > until, seconds=20)
    s.expect("someone who knows fire lights it again", structure("hearth", a)["lit_until_ms"] > now())


def stock(s):
    """A seeded fishing ground (the goods fixture's `resource_nodes`): three spots share one
    stock of 3 fish, held by the first; fishing one spot empties the others."""
    def now():
        return s.rows("SELECT last_ms FROM clock")[0]["last_ms"]

    def heard(actor, words, since):
        return [r["text"] for r in s.rows(f"SELECT text, at_ms FROM experience WHERE observer = {actor}") if r["at_ms"] >= since and words in r["text"]]

    def acts(actor, *nodes):
        s.call("mind_act", actor, [json.dumps(n) for n in nodes], "verify-core")

    c, = s.people(1)
    # The valley grows wild fishing spots of its own (pool 0); the seeded ground's are pooled.
    spots = sorted((r for r in s.rows("SELECT * FROM resource_node", "fishing-ground") if r["kind"] == "fishing_spot" and r["pool"] != 0), key=lambda r: r["id"])
    head = spots[0]
    s.expect("the seed's pooled spots draw on the first one's stock", len(spots) == 3 and head["pool"] == head["id"] and all(r["pool"] == head["id"] for r in spots[1:]) and head["max"] == 3, spots)
    s.call("place_at", c, spots[1]["x"], spots[1]["y"] + 1.0)
    # Node ids and creature ids are separate sequences: aim at the nearest spot, not an id.
    acts(c, *[{"do": "gather", "target": {"nearest": "fishing_spot"}}] * 3)
    s.wait(lambda: s.inventory(c).get("fish", 0) >= 3, seconds=60)
    s.call("place_at", c, spots[2]["x"], spots[2]["y"] + 1.0)
    t0 = now()
    acts(c, {"do": "gather", "target": {"nearest": "fishing_spot"}})
    s.wait(lambda: heard(c, "did not work out", t0), seconds=30)
    stock = s.rows(f"SELECT * FROM resource_node WHERE id = {head['id']}", "stock-after")[0]
    s.expect("three fish from one spot empty the shared stock", s.inventory(c, "fisher").get("fish") == 3 and stock["amount"] < 1.0, stock)
    s.expect("another spot of the same ground is depleted too", heard(c, "depleted", t0), heard(c, "", t0))


# How long the decay scene watches, in game hours (`--game-hours`; a whole day by default).
DECAY_HOURS = 24.0


def decay(s):
    """Rates written in game time run in real time for the world's day (docs/CULLET_RULES.md,
    rates-2), on a world with its own day and laws (`cullet-laws`: a 48-minute day): raw fish in a
    pack and in a storage spoils at the laws' `spoil_per_h` turned into real minutes, once a real
    minute (a storage at its `kept_spoil` share), and an emptied greens bed regrows its kind's
    `regrow_per_h` a game hour, kept per real minute in the node's `regen`. Watches for
    `--game-hours` (default a whole game day, 48 real minutes on Cullet); no clock is changed."""
    w = s.rows("SELECT * FROM world", "world")[0]
    hour_ms = w["day_ms"] / 24
    seed = json.loads((ROOT / "living/seeds" / f"{json.loads((s.out / 'state.json').read_text())['seed']}.json").read_text())
    src = (ROOT / "living/seeds" / seed["laws_file"]).read_text()
    per_min = 60000 / hour_ms
    fish_min = law_number(src, "spoil_per_h", "fish") * per_min
    kept = 1.0 / 3.0  # the shipped `kept_spoil` (Cullet keeps it)

    def now():
        return s.rows("SELECT last_ms FROM clock")[0]["last_ms"]

    def heard(actor, words, since):
        return [r["text"] for r in s.rows(f"SELECT text, at_ms FROM experience WHERE observer = {actor}") if r["at_ms"] >= since and words in r["text"]]

    def acts(actor, *nodes):
        s.call("mind_act", actor, [json.dumps(n) for n in nodes], "verify-core")

    def empty(actor, kind):
        """Gather from the nearest node of a kind until it is depleted; how many were taken."""
        got = 0
        for _ in range(12):
            t0, before = now(), sum(s.inventory(actor).values())
            acts(actor, *[{"do": "gather", "target": {"nearest": kind}}] * 4)
            try:
                s.wait(lambda: heard(actor, "depleted", t0) or sum(s.inventory(actor).values()) >= before + 4, seconds=60, every=1)
            except TimeoutError:
                pass
            time.sleep(2)
            got += sum(s.inventory(actor).values()) - before
            # A spent node is not `nearest` any more: "no nearest ... in sight", not "depleted".
            if heard(actor, "depleted", t0) or heard(actor, f"no nearest {kind}", t0):
                return got
        return got

    a, b = s.people(2)
    for p in (a, b):
        s.graph(p, {"wait": 3600})
    s.call("place_near", b, a)
    # Raw fish: 1,000 in a pack, 100 put in a storage beside it (a storage holds its kind's `holds`, 120;
    # a `{"id": n}` target names a creature, so the storage is aimed at as the nearest).
    s.call("place_structure", b, "storage")
    store = max((r for r in s.rows(f"SELECT * FROM structure WHERE owner = {b}") if r["kind"] == "storage"), key=lambda r: r["id"])
    s.call("grant_items", b, "fish", 100)
    t0 = now()
    acts(b, {"do": "store", "item": "fish", "qty": 100, "target": {"nearest": "storage"}})
    owner = (1 << 40) | store["id"]
    held = lambda: {r["item"]: r["qty"] for r in s.rows(f"SELECT item, qty FROM inventory WHERE owner = {owner}")}
    try:
        s.wait(lambda: held().get("fish", 0) >= 90, seconds=60, every=1)
    except TimeoutError:
        s.expect("the fish are stored", False, heard(b, "", t0))
    s.call("grant_items", a, "fish", 1000)
    t_fish = now()
    stored0 = held().get("fish", 0)
    # A greens bed placed beside the pair, emptied, to regrow.
    s.call("place_resource", a, "greens_bed", 2.0, 0.0, 0.0, 0)
    bed = max((r for r in s.rows("SELECT * FROM resource_node") if r["kind"] == "greens_bed"), key=lambda r: r["id"])
    regrow_h = float(re.search(r'name:\s*"greens_bed"[^\n]*?regrow_per_h:\s*([\d.]+)', src).group(1))
    s.expect("a node's regen is its kind's regrow_per_h in real minutes for the day", abs(bed["regen"] - regrow_h * per_min) < 1e-6, {"regen": bed["regen"], "regrow_per_h": regrow_h, "per_real_minute": regrow_h * per_min})
    took = empty(b, "greens_bed")
    t_empty = now()
    left = s.rows(f"SELECT * FROM resource_node WHERE id = {bed['id']}", "bed-emptied")[0]
    # The bed's own row says it is spent; the pack is no count (spoiling and eating shrink it).
    s.expect("the bed is emptied by gathering", left["amount"] < 1.0 and left["at_ms"] > bed["at_ms"], {"took_into_pack": took, "row": left})

    # Watch, sampling the stacks every few real minutes.
    watch_ms = DECAY_HOURS * hour_ms
    samples = []
    while now() < t_fish + watch_ms:
        samples.append({"at_ms": now(), "carried": s.inventory(a).get("fish", 0), "stored": held().get("fish", 0)})
        time.sleep(min(180, max(5, (t_fish + watch_ms - now()) / 1000)))
    t1 = now()
    carried, stored = s.inventory(a, "fish-after").get("fish", 0), held().get("fish", 0)
    samples.append({"at_ms": t1, "carried": carried, "stored": stored})
    (s.out / "decay-samples.json").write_text(json.dumps(samples, indent=1) + "\n")
    # Once a real minute each stack loses its share in expectation (the fraction by chance):
    # after k sweeps a stack holds about q (1 - r)^k; k is the real minutes passed, give or take
    # one, and each sweep's chance adds at most one.
    mins = (t1 - t_fish) / 60000

    def band(q, r):
        ks = [max(0, int(mins) - 1), int(mins) + 1]
        return min(q * (1 - r) ** k for k in ks) - mins - 2, max(q * (1 - r) ** k for k in ks) + mins + 2

    lo, hi = band(1000, fish_min)
    s.expect(f"raw fish carried over {DECAY_HOURS:g} game hours spoils at spoil_per_h in real time ({fish_min:.4f} a real minute)", lo <= carried <= hi, {"carried": carried, "band": [round(lo, 1), round(hi, 1)], "real_minutes": round(mins, 2), "share_left": carried / 1000})
    lo, hi = band(stored0, fish_min * kept)
    s.expect("raw fish in a storage spoils at a third of that", lo <= stored <= hi, {"stored": stored, "from": stored0, "band": [round(lo, 1), round(hi, 1)], "share_left": stored / max(1, stored0)})

    # Regrowth, read from the bed's own row: one gathering beside it takes one unit and writes
    # what it held then less one (`Effect::Harvest`), so what it had regrown is the new amount
    # plus one, against its regen times the real minutes since it was emptied (growing time:
    # not winter). Gathering more would count other beds too (`nearest` walks on to the wild
    # ones once this one is spent).
    t0 = now()
    acts(b, {"do": "gather", "target": {"nearest": "greens_bed"}})
    s.wait(lambda: s.rows(f"SELECT at_ms FROM resource_node WHERE id = {bed['id']}")[0]["at_ms"] > left["at_ms"] or heard(b, "did not work out", t0), seconds=60, every=1)
    row = s.rows(f"SELECT * FROM resource_node WHERE id = {bed['id']}", "bed-regrown")[0]
    had = row["amount"] + 1.0
    grown = left["amount"] + left["regen"] * (row["at_ms"] - left["at_ms"]) / 60000
    s.expect(f"the emptied bed regrew regrow_per_h a game hour over {DECAY_HOURS:g} game hours (growing time)", row["at_ms"] > left["at_ms"] and abs(had - min(grown, left["max"])) < 0.01,
             {"had": round(had, 4), "expected": round(grown, 4), "game_hours": round((row["at_ms"] - left["at_ms"]) / hour_ms, 3), "row": row})


def winter(s):
    """Regrowth by season is a value on each resource kind (docs/CULLET_RULES.md, "Winter";
    rules-3), on the winter fixture (winter.json: Cullet's laws on a 4-minute day and a 4-day
    year, no wild nodes): in a Cullet winter a fishing spot keeps regrowing at its kind's winter
    share (0.75 of `regrow_per_h`), and a root plot, which rests, regrows nothing. Waits for the
    world's own winter (about 11 real minutes after creation); no clock is changed."""
    w = s.rows("SELECT * FROM world", "world")[0]
    day, epoch, year = w["day_ms"], w["epoch_ms"], max(4, w["year_days"])
    src = (ROOT / "living/seeds/worlds/cullet/laws.rhai").read_text()
    shares = {k: float(v) for k, v in re.findall(r"(\w+): ([\d.]+)", re.search(r"fn winter_regrowth\(\)\s*\{([^}]*)\}", src).group(1))}
    s.expect("the world has Cullet's laws on a short day and year", "fn winter_regrowth()" in s.rows("SELECT source FROM script")[0]["source"] and day == 4 * 60000 and year == 4, w)
    # The seasons are quarters of the year from day 1's midnight (the world starts at 07:00).
    origin = epoch - day * 7 // 24
    winter0, winter1 = origin + day * year * 3 // 4, origin + day * year

    def now():
        return s.rows("SELECT last_ms FROM clock")[0]["last_ms"]

    def heard(actor, words, since):
        return [r["text"] for r in s.rows(f"SELECT text, at_ms FROM experience WHERE observer = {actor}") if r["at_ms"] >= since and words in r["text"]]

    def acts(actor, *nodes):
        s.call("mind_act", actor, [json.dumps(n) for n in nodes], "verify-core")

    def node(kind):
        return max((r for r in s.rows("SELECT * FROM resource_node") if r["kind"] == kind), key=lambda r: r["id"])

    def empty(actor, n):
        """Gather at node `n` one at a time until its own row holds less than one. Read the row:
        a node under one unit is not `nearest` any more ("no nearest ... in sight", not
        "depleted"), and spoiling shrinks the pack, so neither words nor the pack can tell."""
        row = lambda: s.rows(f"SELECT * FROM resource_node WHERE id = {n['id']}")[0]
        for _ in range(20):
            before, t0 = row(), now()
            if before["amount"] < 1.0 and before["at_ms"] >= winter0:
                return
            acts(actor, {"do": "gather", "target": {"nearest": n["kind"]}})
            try:
                s.wait(lambda: row()["at_ms"] > before["at_ms"] or heard(actor, "did not work out", t0), seconds=30, every=0.5)
            except TimeoutError:
                pass
        raise AssertionError(f"the {n['kind']} was not emptied")

    a, = s.people(1)
    # Everyone waits: the fixture's band would forage from the placed nodes, hungry on a 4-minute day.
    for p in [c["id"] for c in s.rows("SELECT id, kind FROM character") if c["kind"] == "person"]:
        s.graph(p, {"wait": 3600})
    s.call("place_resource", a, "fishing_spot", 1.0, 0.0, 0.0, 0)
    s.call("place_resource", a, "root_plot", 0.0, 1.5, 0.0, 0)
    fish, roots = node("fishing_spot"), node("root_plot")
    s.expect("a placed fishing spot and root plot, with their kinds' regen", fish["regen"] > 0 and roots["regen"] > 0, [fish, roots])
    print(f"waiting {max(0, winter0 - now()) / 1000:.0f} s for winter", flush=True)
    s.wait(lambda: now() >= winter0 + 2000, seconds=max(60, (winter0 - now()) / 1000 + 120), every=5)
    s.expect("it is winter in the world (the calendar's last quarter)", winter0 <= now() < winter1, {"now": now(), "winter": [winter0, winter1]})
    # Empty both in winter, the root plot first: it is checked last, once its full rate would
    # have grown more than a unit (so a refusal means it rested), the fishing spot 45 s after it.
    empty(a, roots)
    empty(a, fish)
    left = {k: s.rows(f"SELECT * FROM resource_node WHERE id = {n['id']}", f"{k}-emptied")[0] for k, n in (("fishing_spot", fish), ("root_plot", roots))}
    s.expect("both nodes are emptied in winter", all(r["amount"] < 1.0 for r in left.values()) and all(r["at_ms"] >= winter0 for r in left.values()), left)
    s.wait(lambda: now() >= left["fishing_spot"]["at_ms"] + 45_000, seconds=90, every=2)
    s.expect("still winter", now() < winter1 - 15_000, {"now": now(), "winter_ends": winter1})
    # One gathering at each: the fishing spot gives what it regrew at its winter share (the row
    # holds what it had less one), the root plot refuses, depleted, its row unchanged.
    t0 = now()
    acts(a, {"do": "gather", "target": {"nearest": "fishing_spot"}})
    s.wait(lambda: s.rows(f"SELECT at_ms FROM resource_node WHERE id = {fish['id']}")[0]["at_ms"] > left["fishing_spot"]["at_ms"] or heard(a, "did not work out", t0), seconds=60, every=1)
    row = s.rows(f"SELECT * FROM resource_node WHERE id = {fish['id']}", "fishing_spot-regrown")[0]
    lf = left["fishing_spot"]
    had = row["amount"] + 1.0
    share = shares["fishing_spot"]
    grown = lf["amount"] + lf["regen"] * share * (row["at_ms"] - lf["at_ms"]) / 60000
    s.expect(f"a fishing spot regrows in a Cullet winter, at {share:g} of its rate", row["at_ms"] > lf["at_ms"] and abs(had - min(grown, lf["max"])) < 0.01,
             {"had": round(had, 4), "expected": round(grown, 4), "at_full_rate": round(lf["amount"] + lf["regen"] * (row["at_ms"] - lf["at_ms"]) / 60000, 4), "game_hours": round((row["at_ms"] - lf["at_ms"]) / (day / 24), 3), "row": row})
    lr = left["root_plot"]
    full = lambda: lr["regen"] * (now() - lr["at_ms"]) / 60000
    s.wait(lambda: full() >= 1.5 or now() >= winter1 - 12_000, seconds=240, every=1)
    t0 = now()
    acts(a, {"do": "gather", "target": {"nearest": "root_plot"}})
    # A node under one unit is not `nearest`: the gathering is refused ("no nearest root_plot").
    s.wait(lambda: heard(a, "did not work out", t0) or s.rows(f"SELECT at_ms FROM resource_node WHERE id = {roots['id']}")[0]["at_ms"] > lr["at_ms"], seconds=60, every=1)
    rrow = s.rows(f"SELECT * FROM resource_node WHERE id = {roots['id']}", "root_plot-after")[0]
    grown_full = round(full(), 3)
    s.expect(f"a root plot regrows nothing in a Cullet winter (share {shares['root_plot']:g}), where its full rate would have grown a unit", now() < winter1 and grown_full >= 1.0 and heard(a, "did not work out", t0) and rrow["at_ms"] == lr["at_ms"] and rrow["amount"] < 1.0,
             {"heard": heard(a, "", t0), "row": rrow, "would_have_grown_at_full_rate": grown_full, "winter_left_ms": winter1 - now()})


def making(s):
    """Crafting, cooking and smoking are recipes of one table made by one mechanism (recipes-1,
    docs/WORLD_RULES.md "One table of what is made"), on the goods fixture (Cullet's laws, whose
    recipes() is base_recipes() + its own): a person cooks fish at the seeded hearth that burns
    peat, by an act and by an old behaviour graph naming `cook`; is refused smoking and crafting
    a spear in the old words until they know how; then smokes meat and crafts a spear. Cooking at
    a fire that eats fuel draws none of it."""
    src = s.rows("SELECT source FROM script")[0]["source"]
    overlay = src.split("---- floor overlay ----")[-1]
    s.expect("the world was made with Cullet's laws over the shipped recipes", "for r in base_recipes()" in overlay and "fn craft_making()" in src)
    hearth = next(r for r in s.rows("SELECT * FROM structure", "seeded-structures") if r["kind"] == "hearth")

    def now():
        return s.rows("SELECT last_ms FROM clock")[0]["last_ms"]

    def heard(actor, words, since):
        return [r["text"] for r in s.rows(f"SELECT text, at_ms FROM experience WHERE observer = {actor}") if r["at_ms"] >= since and words in r["text"]]

    people = [c["id"] for c in s.rows("SELECT id, kind FROM character") if c["kind"] == "person"]
    a = people[0]
    for p in people:
        s.graph(p, {"wait": 120})
    s.call("place_at", a, hearth["x"] - 1.0, hearth["y"])
    s.call("grant_know_how", a, "cooking")
    for item, n in (("fish", 2), ("meat", 1), ("wood", 2), ("stone", 1)):
        s.call("grant_items", a, item, n)
    before = s.inventory(a, "before")
    lit_before = s.rows(f"SELECT lit_until_ms FROM structure WHERE id = {hearth['id']}")[0]["lit_until_ms"]
    s.expect("the seeded hearth burns", lit_before > now(), {"lit_until_ms": lit_before, "now": now()})

    # Cooking by an act, then by an old graph naming the skill as before.
    s.act(a, {"do": "cook", "item": "fish", "target": {"nearest": "hearth"}})
    s.wait(lambda: s.inventory(a).get("cooked_fish", 0) >= 1, seconds=30)
    inv = s.inventory(a, "cooked-by-act")
    s.expect("cook fish at a burning hearth makes cooked fish from one fish", inv.get("cooked_fish") == 1 and inv.get("fish") == before["fish"] - 1, inv)
    s.graph(a, {"seq": [{"do": "cook", "item": "fish", "target": {"nearest": "hearth"}}, {"wait": 120}]})
    s.wait(lambda: s.inventory(a).get("cooked_fish", 0) >= 2, seconds=30)
    inv = s.inventory(a, "cooked-by-graph")
    s.expect("an old graph naming cook still cooks", inv.get("cooked_fish") == 2 and inv.get("fish", 0) == 0, inv)
    lit_after = s.rows(f"SELECT lit_until_ms FROM structure WHERE id = {hearth['id']}", "hearth-after-cooking")[0]["lit_until_ms"]
    s.expect("cooking draws no fuel from the hearth", lit_after == lit_before, {"before": lit_before, "after": lit_after})

    # Refused in the old words until known.
    t0 = now()
    s.graph(a, {"wait": 120})
    s.act(a, {"do": "smoke", "item": "meat", "target": {"nearest": "hearth"}})
    s.act(a, {"do": "craft", "item": "spear"})
    s.wait(lambda: len(heard(a, "did not work out", t0)) >= 2, seconds=30)
    s.expect("smoking unknown is refused as before", heard(a, "you don't know how to smoke food", t0), heard(a, "", t0))
    s.expect("crafting a spear unknown is refused as before", heard(a, "you don't know how to make a spear", t0), heard(a, "", t0))

    s.call("grant_know_how", a, "smoking")
    s.call("grant_know_how", a, "spear")
    s.act(a, {"do": "smoke", "item": "meat", "target": {"nearest": "hearth"}})
    s.act(a, {"do": "craft", "item": "spear"})
    s.wait(lambda: s.inventory(a).get("spear", 0) >= 1 and s.inventory(a).get("smoked_meat", 0) >= 1, seconds=60)
    inv = s.inventory(a, "after")
    s.expect("smoke meat makes smoked meat; craft spear uses 2 wood and 1 stone", inv.get("smoked_meat") == 1 and inv.get("meat", 0) == 0 and inv.get("spear") == 1 and inv.get("wood", 0) == before.get("wood", 0) - 2 and inv.get("stone", 0) == before.get("stone", 0) - 1, {"before": before, "after": inv})


def workplace(s):
    """A workplace built from materials and a recipe that needs a tool held (goods-3,
    docs/GOODS.md), on the goods fixture (Cullet's laws): someone who does not know masonry is
    refused building a hearth; knowing it, they build one from 4 stone and 2 clay (used up)
    where they stand, out until fed; they light it; rendering lamp oil there is refused without
    a vessel, in the rules' words naming it; with a pot (a vessel by its trait, not by name) the
    oil is rendered from two fish and the pot is kept."""
    src = s.rows("SELECT source FROM script")[0]["source"]
    s.expect("the world was made with Cullet's built kinds and tools", "fn built_here()" in src and "tools: #{ vessel: 1 }" in src)

    def now():
        return s.rows("SELECT last_ms FROM clock")[0]["last_ms"]

    def heard(actor, words, since):
        return [r["text"] for r in s.rows(f"SELECT text, at_ms FROM experience WHERE observer = {actor}") if r["at_ms"] >= since and words in r["text"]]

    people = [c["id"] for c in s.rows("SELECT id, kind FROM character") if c["kind"] == "person"]
    a = people[-1]
    for p in people:
        s.graph(p, {"wait": 120})
    s.call("place_at", a, 36.5, 46.0)
    for item, n in (("stone", 4), ("clay", 2), ("peat", 2), ("fish", 4)):
        s.call("grant_items", a, item, n)
    s.call("grant_know_how", a, "fire")
    hearths = lambda: [r for r in s.rows(f"SELECT * FROM structure WHERE owner = {a}") if r["kind"] == "hearth"]
    before = len(hearths())

    # Building a hearth takes masonry: refused, in the build rule's words.
    t0 = now()
    s.act(a, {"do": "build", "item": "hearth"})
    s.wait(lambda: heard(a, "did not work out", t0), seconds=30)
    s.expect("building a hearth without masonry is refused", heard(a, "you don't know how to build a hearth", t0), heard(a, "", t0))
    s.call("grant_know_how", a, "masonry")
    s.act(a, {"do": "build", "item": "hearth"})
    s.wait(lambda: len(hearths()) > before, seconds=60)
    built = max(hearths(), key=lambda r: r["id"])
    inv = s.inventory(a, "after-build")
    x, y = body_at(s, a)
    s.expect("the hearth is built from 4 stone and 2 clay where they stand", inv.get("stone", 0) == 0 and inv.get("clay", 0) == 0 and abs(built["x"] - x) < 1.5 and abs(built["y"] - y) < 1.5, {"inv": inv, "hearth": built, "at": [x, y]})
    s.expect("a built hearth starts out", built["lit_until_ms"] == 0, built)
    s.expect("its building is in the chronicle", [r for r in s.story("build", a, "build-story") if "hearth" in r.get("text", "")])
    s.act(a, {"do": "feed", "item": "peat", "qty": 2, "target": {"nearest": "hearth"}})
    s.wait(lambda: any(r["lit_until_ms"] > now() for r in hearths()), seconds=30)

    # Lamp oil is rendered in a vessel the renderer keeps: refused without one.
    t0 = now()
    s.act(a, {"do": "make", "item": "lamp_oil", "target": {"nearest": "hearth"}})
    s.wait(lambda: heard(a, "did not work out", t0), seconds=30)
    s.expect("rendering oil without a vessel is refused, naming it", heard(a, "lamp_oil is made with a vessel in your pack, not used up", t0), heard(a, "", t0))
    s.call("grant_items", a, "pot", 1)
    before = s.inventory(a, "before-oil")
    s.act(a, {"do": "make", "item": "lamp_oil", "target": {"nearest": "hearth"}})
    s.wait(lambda: s.inventory(a).get("lamp_oil", 0) > before.get("lamp_oil", 0), seconds=60)
    inv = s.inventory(a, "after-oil")
    s.expect("two fish rendered to lamp oil with a pot, the pot kept", inv.get("lamp_oil", 0) == before.get("lamp_oil", 0) + 1 and inv.get("fish", 0) == before.get("fish", 0) - 2 and inv.get("pot") == 1, {"before": before, "after": inv})


SCENES["goods"] = goods
SCENES["workplace"] = workplace
SCENES["making"] = making
SCENES["stock"] = stock
SCENES["decay"] = decay
SCENES["winter"] = winter
SCENES["stamina"] = stamina
SCENES["fights"] = fights
SCENES["chase"] = chase
SCENES["doing_seen"] = doing_seen
SCENES["committed"] = committed
SCENES["doing_cost"] = doing_cost
SCENES["owners"] = owners
SCENES["intents"] = intents
SCENES["apart"] = apart_intent
SCENES["howl_reach"] = howl_reach
SCENES["pack_reflex"] = pack_reflex
SCENES["intents_cost"] = intents_cost
SCENES["sleeper"] = sleeper
SCENES["sex"] = body_sex



def alert_after_hit(s):
    """A body does not fall asleep in a fight (the script's `sleep_check`, the same for every
    controller): struck within the `alert_after_hit_s` law (15 s) it is refused, "you cannot sleep:
    you were struck moments ago", and sleeps once that has passed; with the one who struck it within
    `wake_reach` and the fight on (struck within 30 s, the fact `hurt_by_near`, law
    `alert_while_attacker_near`) it is refused, "you cannot sleep: someone who struck you is close",
    until they go. A refused sleep fails its routine. And every blow wakes a sleeping victim, not only
    a fight's first (`perceive::wake_struck`): with both laws off a struck body sleeps again at once,
    and the fight's second blow wakes it. The laws are restored at the end."""
    line = clear_line(s)
    a, b = s.people(2)
    struck = lambda: s.rows(f"SELECT hurt_ms, hurt_by FROM vitals WHERE id = {a}")[0]
    sleeping = lambda: [x for x in s.rows(f"SELECT skill, phase FROM activity WHERE id = {a}") if x["skill"] == "sleep"]
    told = lambda words, since=0: [e for e in s.rows(f"SELECT text, at_ms, kind FROM experience WHERE observer = {a}") if words in e["text"] and e["at_ms"] >= since]
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    def blow(seconds=20):
        """b, beside a, strikes it once; returns the blow's time."""
        before = struck()["hurt_ms"]
        s.call("place_at", b, line[1][0], line[1][1])
        s.graph(b, {"seq": [{"do": "attack", "target": {"nearest": "person"}}, {"wait": 300}]})
        s.wait(lambda: struck()["hurt_ms"] > before, seconds=seconds, every=0.3)
        s.graph(b, {"wait": 300})
        return struck()["hurt_ms"]
    try:
        s.call("place_at", a, *line[0])
        s.graph(a, {"wait": 300})
        # 1. Struck: sleep refused for 15 s, then allowed (b walks off at once).
        t = blow()
        s.call("place_at", b, line[0][0] + 30, line[0][1])
        s.graph(a, {"seq": [{"do": "sleep"}]})
        refused = s.wait(lambda: told("you cannot sleep: you were struck moments ago", t), seconds=10)
        time.sleep(max(0.0, (t + 12_000 - now()) / 1000))
        s.expect("struck: a sleep is refused, in the body fact's words", bool(refused) and not sleeping(), refused)
        s.expect("and not slept for the law's 15 s", not sleeping() and not s.rows(f"SELECT * FROM slumber WHERE actor = {a}"), now() - t)
        s.wait(lambda: sleeping(), seconds=15, every=0.5)
        began = now()
        s.expect("once 15 s have passed it sleeps", 15_000 <= began - t < 25_000, began - t)
        s.graph(a, {"wait": 300})
        s.wait(lambda: not sleeping(), seconds=10)
        # 2. The one who struck stays close: refused past 15 s, while the fight is on; allowed once they go.
        t = blow()
        s.call("place_at", b, line[2][0], line[2][1])
        s.graph(a, {"seq": [{"do": "sleep"}]})
        time.sleep(max(0.0, (t + 18_000 - now()) / 1000))
        near = told("you cannot sleep: someone who struck you is close", t)
        s.expect("past 15 s, with the one who struck within reach: refused, in the body fact's words", bool(near) and not sleeping(), near)
        s.call("place_at", b, line[0][0] + 30, line[0][1])
        s.wait(lambda: sleeping(), seconds=12, every=0.5)
        s.expect("they go beyond reach: it sleeps, the fight still within 30 s", now() - t < 30_000, now() - t)
        s.graph(a, {"wait": 300})
        s.wait(lambda: not sleeping(), seconds=10)
        # 3. Every blow wakes a sleeper: both laws off, so a struck body sleeps again at once.
        set_law(s, "alert_after_hit_s", 0)
        set_law(s, "alert_while_attacker_near", False)
        time.sleep(31)  # the last fight is over: the next blow is a new fight's first
        s.graph(a, {"seq": [{"do": "sleep"}]})
        s.wait(lambda: sleeping(), seconds=15)
        t1 = blow()
        s.wait(lambda: told("You woke up: ", t1), seconds=10)
        s.call("place_at", b, line[0][0] + 30, line[0][1])
        s.wait(lambda: sleeping(), seconds=15)
        t2 = blow()
        s.expect("the fight's second blow is not its first (within 30 s)", t2 - t1 < 30_000, t2 - t1)
        woke = s.wait(lambda: told("You woke up: ", t2), seconds=10)
        s.expect("and wakes the sleeper, told why", bool(woke) and woke[0]["kind"] == "body" and "attacking you" in woke[0]["text"], woke)
    finally:
        set_law(s, "alert_after_hit_s", 15, check=False)
        set_law(s, "alert_while_attacker_near", True, check=False)
        for who in (a, b):
            s.graph(who, {"wait": 300})
        off_the_line(s, line, [a, b], dy=56)


SCENES["alert_after_hit"] = alert_after_hit



# ---- body sex (sex-1, docs/LIVING_CORE.md "Body sex") ------------------------------------------
SEX_SALT = 0x5E70F00D0B0D1E55
SEX_SEED = ROOT / ".local/living/verify/sex-family.json"


def sex_pick(seed, i, share=0.5):
    """`living_rules::sex::pick`, recomputed: female when splitmix64((seed ^ SALT) ^ id * 0x9E37…)
    >> 11, over 2^53, is below the share."""
    M = (1 << 64) - 1
    z = (((int(seed) ^ SEX_SALT) ^ ((i * 0x9E3779B97F4A7C15) & M)) + 0x9E3779B97F4A7C15) & M
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M
    z ^= z >> 31
    return 1 if (z >> 11) / float(1 << 53) < share else 2


def sex_family_seed():
    """stage1-acts (one family at a compressed pace: a child is carried about 2.6 real minutes)
    with the band members' sexes given for the grown and left to the world for the young
    (`SeedMember.sex`). Launch the scene's run with `--seed <this path without .json>`."""
    seed = json.loads((ROOT / "living/seeds/stage1-acts.json").read_text())
    seed["run"] = "sex-family"
    for m, x in zip(seed["bands"][0]["family"], ["f", "m", "f", "f", "m"]):
        m["sex"] = x
    SEX_SEED.parent.mkdir(parents=True, exist_ok=True)
    SEX_SEED.write_text(json.dumps(seed, indent=1) + "\n")
    return seed


def body_sex(s):
    """Body sex as a world fact (sex-1). On the family seed (`sex_family_seed`; `scenes.py
    sex-seed` writes it): every person has one `sex` row and no animal has one; the grown band
    members have the seed's sexes and the young the world's pick (recomputed here); newcomers
    (`spawn_crowd`) take the pick under `female_share()` 1.0, 0.0 and the shipped 0.5. Kin words
    by sex: a child's "Mother" names its female parent and not its male one, "Father" the other way,
    "parent" both. `conceive_needs_pair()`: on, two women are refused ("a family is started by a
    woman and a man") and a woman and a man start one; off (shipped), two women start one. Each
    child born has the world's pick for its id. The shipped script is installed again at the end."""
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    w = s.rows("SELECT seed, run FROM world", "world")[0]
    s.expect("the family seed is in force", w["run"] == "sex-family", w)
    seed = int(w["seed"])
    sex_of = lambda: {r["id"]: r["sex"] for r in s.rows("SELECT * FROM sex", "sex-rows")}
    people = s.rows("SELECT id, name, kind, stage, parent_a, parent_b, alive, born_ms FROM character", "characters")
    persons = [c for c in people if c["kind"] == "person"]
    sexes = sex_of()
    s.expect("every person has a sex row (1 or 2) and no animal has one", all(sexes.get(c["id"]) in (1, 2) for c in persons) and set(sexes) <= {c["id"] for c in persons},
             {"people": len(persons), "rows": len(sexes)})
    family = sorted(persons, key=lambda c: c["id"])
    grown = [c for c in family if c["stage"] >= 2][:5]
    young = [c for c in family if c["stage"] < 2]
    s.expect("the grown band members have the seed's sexes (f, m, f, f, m)", [sexes[c["id"]] for c in grown] == [1, 2, 1, 1, 2], [(c["id"], sexes[c["id"]]) for c in grown])
    s.expect("the young (no sex in the seed) have the world's pick", all(sexes[c["id"]] == sex_pick(seed, c["id"]) for c in young), [(c["id"], sexes[c["id"]], sex_pick(seed, c["id"])) for c in young])
    try:
        # female_share: newcomers by the law in force.
        made = {}
        for share in (1.0, 0.0):
            s.call("install_script", compose(shipped, {"female_share": f"fn female_share() {{ {share} }}"}))
            made[share] = s.people(4)
        s.call("install_script", shipped)
        made[0.5] = s.people(6)
        sexes = sex_of()
        for share, ids in made.items():
            want = [sex_pick(seed, i, share) for i in ids]
            s.expect(f"female_share {share}: each newcomer has the world's pick for its id", [sexes.get(i) for i in ids] == want, {"ids": ids, "got": [sexes.get(i) for i in ids], "want": want})
        s.expect("female_share 1.0 makes women and 0.0 men", all(sexes[i] == 1 for i in made[1.0]) and all(sexes[i] == 2 for i in made[0.0]))

        # Kin words by sex: the band's children are the first two non-elder adults' (a man and a woman).
        child = next((c for c in young if c["stage"] == 1 and c["parent_a"] and c["parent_b"]), None)
        s.expect("the family has a child with both parents", child is not None, young)
        mother, father = sorted((child["parent_a"], child["parent_b"]), key=lambda i: sexes[i])
        s.expect("its parents are a woman and a man", (sexes[mother], sexes[father]) == (1, 2))
        line = open_line(s)
        for who, at in ((child["id"], 4), (mother, 5), (father, 6)):
            s.call("place_at", who, *line[at])
            s.graph(who, {"wait": 120})
        def named(who, marker):
            return [e for e in s.rows(f"SELECT kind, text FROM experience WHERE observer = {who}") if marker in e["text"] and "naming you" in e["text"]]
        for words, marker, yes, no in (("Mother, come and see.", "verify kin mother", [mother], [father]), ("Father, come and see.", "verify kin father", [father], [mother]), ("Ask a parent.", "verify kin parent", [mother, father], [])):
            s.call("mind_say", child["id"], f"{words} {marker}", 0, "", 0, THOUGHT)
            time.sleep(2.5)
            got = {i: bool(named(i, marker)) for i in yes + no}
            s.expect(f"kin words by sex: {words!r} names {['the mother' if i == mother else 'the father' for i in yes]} and not {['the mother' if i == mother else 'the father' for i in no]}",
                     all(got[i] for i in yes) and not any(got[i] for i in no), got)

        # conceive_needs_pair: two women from the share-1.0 newcomers, the family's mother and father.
        w1, w2 = made[1.0][:2]
        for who, at in ((w1, 9), (w2, 10)):
            s.call("place_at", who, *line[at])
        for who in (w1, w2, mother, father):
            s.call("grant_items", who, "cooked_meat", 2)
            s.graph(who, {"seq": [{"do": "eat", "item": "cooked_meat"}, {"wait": 120}]})
        for who in (w1, w2, mother, father):
            s.wait(lambda who=who: s.needs(who, f"fed-{who}")["hunger"] < 60, seconds=60)
        s.call("install_script", compose(shipped, {"conceive_needs_pair": "fn conceive_needs_pair() { true }"}))
        s.act(w1, {"do": "conceive", "target": {"id": w2}})
        refused = s.wait(lambda: s.told(w1, "a family is started by a woman and a man"), seconds=20)
        s.expect("conceive_needs_pair on: two women are refused, told why", bool(refused), refused)
        s.act(mother, {"do": "conceive", "target": {"id": father}})
        time.sleep(3)
        s.act(father, {"do": "conceive", "target": {"id": mother}})
        pair = s.wait(lambda: s.rows(f"SELECT * FROM expecting WHERE a = {mother} OR b = {mother}", "expecting-pair"), seconds=30)
        s.expect("conceive_needs_pair on: a woman and a man start a family", bool(pair), pair)
        s.call("install_script", shipped)
        s.act(w1, {"do": "conceive", "target": {"id": w2}})
        time.sleep(3)
        s.act(w2, {"do": "conceive", "target": {"id": w1}})
        same = s.wait(lambda: s.rows(f"SELECT * FROM expecting WHERE a = {w1} OR b = {w1}", "expecting-same"), seconds=30)
        s.expect("conceive_needs_pair off (shipped): two women start a family", bool(same), same)
        before = {c["id"] for c in s.rows("SELECT id FROM character")}
        due = max(r["due_ms"] for r in pair + same)
        wait_s = max(10, (due - time.time_ns() // 1_000_000) / 1000 + 20)
        born = s.wait(lambda: [c for c in s.rows("SELECT id, parent_a, parent_b FROM character") if c["id"] not in before and {c["parent_a"], c["parent_b"]} & {mother, w1}] if len([c for c in s.rows("SELECT id, parent_a, parent_b FROM character") if c["id"] not in before and {c["parent_a"], c["parent_b"]} & {mother, w1}]) >= 2 else None, seconds=wait_s, every=3)
        sexes = sex_of()
        s.expect("each child born has a sex row, the world's pick for its id", all(sexes.get(c["id"]) == sex_pick(seed, c["id"]) for c in born), [(c["id"], sexes.get(c["id"]), sex_pick(seed, c["id"])) for c in born])
        s.rows("SELECT * FROM sex", "sex-after")
    finally:
        s.call("install_script", shipped)

def main():
    import sys
    if sys.argv[1:2] == ["sex-seed"]:
        # The `sex` scene's seed (sex-1): writes it and says how to launch with it.
        sex_family_seed()
        print(f"wrote {SEX_SEED}; launch with --seed {SEX_SEED.with_suffix('')}")
        return 0
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scene", choices=SCENES)
    ap.add_argument("--run", required=True)
    ap.add_argument("--baseline", action="store_true", help="measure pre-change infant authority without new-policy assertions")
    ap.add_argument("--resume-infant", action="store_true", help="rerun cry checks from the retained thermal checkpoint")
    ap.add_argument("--game-hours", type=float, default=DECAY_HOURS, help="decay: game hours to watch (default a whole game day)")
    a = ap.parse_args()
    globals()["DECAY_HOURS"] = a.game_hours
    s = Scene(a.run, a.scene)
    s.baseline = a.baseline
    s.resume_infant = a.resume_infant
    error = None
    try:
        SCENES[a.scene](s)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        print(error, flush=True)
    finally:
        (s.out / f"{a.scene}-results.json").write_text(json.dumps({"db": s.db, "checks": s.results, "error": error}, indent=2) + "\n")
    return int(error is not None or any(r["status"] in {"FAIL", "XPASS"} for r in s.results.values()))


def wall_by(s):
    """A walkable tile, the next one along an axis walkable and the one after it wall or rock, and
    the tile beside the first (a quarter turn) walkable, away from people: the tile, the axis
    toward the wall, and the side."""
    w = s.rows("SELECT width, height FROM world")[0]
    W, H = w["width"], w["height"]
    tiles = bytearray(W * H)
    for row in s.rows("SELECT * FROM terrain_chunk"):
        data = row["tiles"]
        data = bytes.fromhex(data.removeprefix("0x")) if isinstance(data, str) else bytes(data)
        cx, cy = row["id"] & 0xFFFF, row["id"] >> 16
        for k, t in enumerate(data):
            tx, ty = cx * 16 + k % 16, cy * 16 + k // 16
            if tx < W and ty < H:
                tiles[ty * W + tx] = t
    at = lambda x, y: tiles[y * W + x] if 0 <= x < W and 0 <= y < H else 4
    walk = lambda x, y: at(x, y) not in (2, 4, 7, 8, 9)
    bodies = [(b["x"], b["y"]) for b in s.rows("SELECT x, y FROM body")]
    for y in range(6, H - 6):
        for x in range(6, W - 6):
            if not walk(x, y) or any(math.dist((x + .5, y + .5), q) < 8 for q in bodies):
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if walk(x + dx, y + dy) and at(x + 2 * dx, y + 2 * dy) in (4, 7) and walk(x - dy, y + dx) and walk(x - dy + dx, y + dx + dy):
                    return (x, y), (dx, dy), (-dy, dx)
    raise RuntimeError("no wall to dodge into on this map")


def dodge_told(s):
    """A dodge's told outcome gives its real reason, and a cooldown's refusals are told once
    (fix-dodge-told; docs/COMBAT.md "A dodge over before the blow came"). Two strangers 1.2 m
    apart in the open. A dodges, toward B, as soon as B's heavy blow (`attack`, a spear) winds up
    at it: its dash is over before the blow releases, the blow lands, and A is told "You failed to
    dodge: it was over before the blow came", once, with its `skill_use` saying so. Then A's
    routine retries a dodge every tick for 4 s: "dodge is not ready yet" is told at most once per
    cooldown (one more than the dodges made), while the routine's `routine_stat` counts every
    refusal (recorded in full)."""
    # A stands two tiles short of a wall (`wall_by`), B beside A. A's dodge, aimed at the wall,
    # has room for half of its 2.6 m (`begin`: as far as there is room), so it ends 1.6 m from B,
    # within the blow's reach (1.4 m and the 0.6 m lunge), and the blow lands after it.
    (x, y), (dx, dy), (sx, sy) = wall_by(s)
    a, b = s.people(2)
    at_a = (x + 0.5, y + 0.5)
    s.call("place_at", a, at_a[0], at_a[1])
    s.call("place_at", b, at_a[0] + sx, at_a[1] + sy)
    s.call("grant_items", b, "spear", 1)
    time.sleep(1.0)
    clock = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.graph(a, {"first": [{"if": {"cond": {"doing": {"is": "attack", "phase": "winding up", "at_me": True}}, "then": {"do": {"skill": "dodge", "target": {"at": [at_a[0] + 3.0 * dx, at_a[1] + 3.0 * dy]}}}}}, {"wait": 0.2}]})
    t0 = clock()
    s.graph(b, {"seq": [{"do": {"skill": "attack", "target": {"id": a}}}, {"wait": 60}]})
    told = lambda t, words: [r for r in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {a}") if r["at_ms"] >= t and words in r["text"]]
    early = s.wait(lambda: told(t0, "it was over before the blow came"), seconds=20)
    uses = [u for u in s.rows("SELECT * FROM skill_use", "early-uses") if u["at_ms"] >= t0 and u["actor"] in (a, b)]
    s.rows(f"SELECT * FROM experience WHERE observer = {a}", "early-told")
    blow = [u for u in uses if u["actor"] == b and u["skill"] == "attack"]
    dodge = [u for u in uses if u["actor"] == a and u["skill"] == "dodge"]
    s.expect("a dodge made at the windup is over before the blow, and the blow lands", blow and blow[-1]["outcome"].startswith("hit for") and dodge and dodge[-1]["accepted_ms"],
             {"blow": [(u["accepted_ms"], u["released_ms"], u["outcome"]) for u in blow], "dodge": [(u["accepted_ms"], u["outcome_ms"], u["outcome"]) for u in dodge]})
    s.expect("the dodger is told its dodge was over before the blow came, once, and its use says so",
             [r["text"] for r in early] == ["You failed to dodge: it was over before the blow came"] and any(u["outcome"] == "made way: it was over before the blow came" for u in dodge),
             {"told": [r["text"] for r in early], "dodge": [u["outcome"] for u in dodge]})
    # A routine retrying a dodge every tick for 4 s.
    s.graph(b, {"wait": 60})
    # As r2c's plans did: a dodge whose condition holds and nothing else, so the graph starts it
    # again on the next tick after each one and is refused until it is ready.
    s.call("mind_routines", a, [{"name": "hop", "graph": json.dumps({"if": {"cond": {"chance": 1.0}}, "then": {"do": "dodge"}})}])
    routine = next(r for r in s.rows(f"SELECT id, name FROM routine WHERE actor = {a}") if r["name"] == "hop")
    t1 = clock()
    s.graph(a, {"routine": "hop"})
    time.sleep(4.0)
    s.graph(a, {"wait": 60})
    waiting = told(t1, "dodge is not ready yet")
    made = [u for u in s.rows("SELECT * FROM skill_use", "streak-uses") if u["actor"] == a and u["skill"] == "dodge" and u["at_ms"] >= t1 and u["accepted_ms"]]
    stat = s.rows(f"SELECT * FROM routine_stat WHERE id = {routine['id']}", "streak-stat")
    s.expect("a dodge refused while it is not ready is told at most once per cooldown, not once a tick",
             made and 1 <= len(waiting) <= len(made) + 1, {"told": [r["text"] for r in waiting], "dodges": len(made)})
    s.expect("every refusal is still recorded (the routine's stat counts more refusals than were told)",
             stat and stat[0]["failed"] > len(waiting), {"stat": stat, "told": len(waiting)})


SCENES["dodge_told"] = dodge_told


def seen_again(s):
    """The fast lane's triggers (docs/FAST_LANE.md), on the authority alone (no mind service):
    with `fast_lane_on` and `fast_lane_inflight` 0 nothing is issued, so a character's `fast_ask`
    row keeps its newest trigger and can be read. Polled every 0.1 s.

    - A blow taken: the row's reason is the victim's own line for it ("A stranger attacked you …").
    - The repeat: B (a spear) strikes at A with its heavy blow over and over; A dodges every
      windup it sees (its own graph), so the blows miss and the reason is not overwritten. The
      reason "<B as A perceives it> winds up an attack at you" first appears at B's N-th windup at
      A, N the `seen_again_n` law (3 as shipped; then 2 on a fresh pair after the law is changed).
    - Nothing counts or repeats in words: no reason, and no experience of A's, says "again" or how
      many times.
    - Not seen, not counted: with `fov_on`, C faces away from D, who shoots it from 8 m behind;
      C's reason is only ever its struck line, never "winds up"."""
    set_law(s, "fast_lane_on", True)
    set_law(s, "fast_lane_inflight", 0)
    set_law(s, "fast_lane_stale_s", 600)
    people = {c["id"] for c in s.rows("SELECT id, kind FROM character WHERE alive = true") if c["kind"] == "person"}
    line = open_line(s, length=16, avoid=[(b["x"], b["y"]) for b in s.rows("SELECT id, x, y FROM body") if b["id"] in people])
    count_words = re.compile(r"again|\btimes?\b|\(×|\d+(st|nd|rd|th) time")

    def pair(n, at):
        a, b = s.people(2)
        s.call("place_at", a, at[0], at[1])
        s.call("place_at", b, at[0] + 1.2, at[1])
        s.call("grant_items", b, "spear", 1)
        time.sleep(1.0)
        s.graph(a, {"first": [{"if": {"cond": {"doing": {"is": "attack", "phase": "winding up", "at_me": True}}, "then": {"do": "dodge"}}}, {"wait": 0.2}]})
        t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
        s.graph(b, {"first": [{"do": {"skill": "attack", "target": {"id": a}}}, {"wait": 0.5}]})
        seen, end, first = [], time.monotonic() + 45, None
        while time.monotonic() < end and first is None:
            r = s.rows(f"SELECT reason, trigger_ms FROM fast_ask WHERE actor = {a}")
            if r and (not seen or seen[-1] != r[0]["reason"]):
                seen.append(r[0]["reason"])
            if r and "winds up" in r[0]["reason"]:
                windups = [u for u in s.rows(f"SELECT skill, accepted_ms, target FROM skill_use WHERE actor = {b}") if u["skill"] == "attack" and u["target"] == a and u["accepted_ms"] and u["accepted_ms"] <= r[0]["trigger_ms"]]
                first = len(windups)
            time.sleep(0.1)
        s.graph(b, {"wait": 60})
        s.graph(a, {"wait": 60})
        told = [e["text"] for e in s.rows(f"SELECT kind, text, at_ms FROM experience WHERE observer = {a}") if e["at_ms"] >= t0]
        (s.out / f"{s.name}-pair-{n}.json").write_text(json.dumps({"a": a, "b": b, "reasons": seen, "windups_at_first": first, "told": told}, indent=1) + "\n")
        return seen, first, told

    seen, first, told = pair(3, line[2])
    s.expect("the repeat trigger: the reason first says B winds up an attack at A at B's 3rd windup at A (seen_again_n 3)",
             first is not None and first % 3 == 0 and first >= 3, {"windups_when_first_seen": first, "reasons": seen})
    s.expect("a reason is the event as perceived, with no count and no \"again\"",
             seen and all(not count_words.search(x) for x in seen if "winds up" in x) and all("again" not in x for x in seen), seen)
    s.expect("nothing A was told counts B's moves or says \"again\" about them",
             not [t for t in told if re.search(r"again \(|\d+ times|\(×", t)], [t for t in told if "again" in t or "times" in t][:5])
    set_law(s, "seen_again_n", 2)
    seen2, first2, _ = pair(2, line[8])
    s.expect("with the law at 2, the reason first comes at the 2nd windup", first2 is not None and first2 % 2 == 0 and first2 >= 2 and first2 < 4, {"windups_when_first_seen": first2, "reasons": seen2})
    set_law(s, "seen_again_n", 3)
    # Not seen, not counted: facing away (fov_on), shot from behind.
    set_law(s, "fov_on", True)
    c, d = s.people(2)
    at = line[13]
    s.call("place_at", c, at[0], at[1])
    s.call("place_at", d, at[0] + 8.0, at[1])
    s.call("grant_items", d, "bow", 1)
    s.call("grant_items", d, "arrow", 30)
    s.graph(c, {"seq": [{"do": {"skill": "face", "target": {"at": [at[0] - 5.0, at[1]]}}}, {"wait": 60}]})
    time.sleep(1.5)
    # D turns to C first (with fov_on it sees only the way it faces), then shoots again and again.
    s.graph(d, {"seq": [{"do": {"skill": "face", "target": {"at": [at[0], at[1]]}}}, {"wait": 60}]})
    time.sleep(1.5)
    s.graph(d, {"first": [{"do": {"skill": "bowshot", "target": {"id": c}}}, {"wait": 0.3}]})
    reasons, end = [], time.monotonic() + 15
    while time.monotonic() < end:
        r = s.rows(f"SELECT reason FROM fast_ask WHERE actor = {c}")
        if r and (not reasons or reasons[-1] != r[0]["reason"]):
            reasons.append(r[0]["reason"])
        time.sleep(0.1)
    s.graph(d, {"wait": 60})
    shots = [u for u in s.rows(f"SELECT skill, accepted_ms, target FROM skill_use WHERE actor = {d}") if u["skill"] == "bowshot" and u["target"] == c and u["accepted_ms"]]
    set_law(s, "fov_on", False)
    s.expect("a move the victim does not see is not counted: shot from behind, its reasons are only its struck lines",
             len(shots) >= 4 and reasons and not [x for x in reasons if "winds up" in x], {"shots": len(shots), "reasons": reasons})
    set_law(s, "fast_lane_on", False)
    set_law(s, "fast_lane_inflight", 4)
    set_law(s, "fast_lane_stale_s", 8)



SCENES["seen_again"] = seen_again


FIRST = "For the first time you see "
FS_TALK = {"kind": "talk", "summary": "verify-core first_sight: K says its name", "detail": "", "latency_ms": 0, "tokens": 0, "model": "fake", "reference": ""}
THOUGHT = {"kind": "deliberate", "summary": "verify-core first_sight: a thought taken", "detail": "", "latency_ms": 0, "tokens": 0, "model": "fake", "reference": ""}


def first_sight(s):
    """A first sight of someone one cannot place asks for one thought (docs/FIRST_SIGHT.md; the
    `first_sight_thinks` law, `brain.rs` `first_sight_asks`). No mind runs here: a thought is
    stood in for by `mind_skip` (the request is cleared and the mind counts as having just
    thought). With the law off, U1 seen for the first time is told and asks nothing. On:
    - U2, first seen within `think_min_s` of a thought, is refused, owed, and asked again at a
      later look while in sight: one request, its reason the first-sight line word for word;
    - U3, first seen once `think_min_s` has passed but within `first_sight_gap_s` of that
      request, asks nothing, then or later (dropped, not owed);
    - under a `perceived_of` overlay (who someone is only within 4 m), V (unknown) at 6 m gets
      no first sight and asks nothing; K (who told O its name from afar) brought within 4 m is a
      first sight that asks nothing; V within 4 m asks, its reason naming only V's part;
    - V leaving and coming back asks nothing (once per first sight);
    - a sleeping O does not see W (no line, no `familiar` row, nothing in `slumber`); awake,
      W's first sight is told and asks;
    - with `cues_on` and a cue on someone unknown, X's first sight and the cue's fire are one
      pending request holding both lines.
    The laws, the script and O's cues are restored at the end."""
    line = clear_line(s)
    o, k, u1, u2, u3, v, w, x = s.people(8)
    others = (k, u1, u2, u3, v, w, x)
    away = lambda who, j=0: s.call("place_at", who, line[0][0] + 80 + 2 * j, line[0][1] + 60)
    for j, who in enumerate(others):
        away(who, j)
        s.graph(who, {"wait": 300})
    s.call("place_at", o, *line[0])
    s.graph(o, {"wait": 300})
    shipped = (ROOT / "living/scripts/skills.rhai").read_text()
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    name = lambda who: s.rows(f"SELECT name FROM character WHERE id = {who}")[0]["name"]
    firsts = lambda since: [r for r in s.rows(f"SELECT id, at_ms, subject, object, text FROM experience WHERE observer = {o}") if r["at_ms"] >= since and r["text"].startswith(FIRST)]
    about = lambda who, since: [r for r in firsts(since) if who in (r["subject"], r["object"])]
    pending = lambda label=None: "\n".join(r["reason"] for r in s.rows(f"SELECT reason FROM deliberation WHERE actor = {o}", label))
    asks = lambda label=None: [l for l in pending(label).split("\n") if l.startswith(FIRST)]
    familiar = lambda who: any((r["thing"] & 0xFFFFFFFF) == who and r["thing"] >> 40 == 2 for r in s.rows(f"SELECT thing FROM familiar WHERE actor = {o}"))
    near = lambda who, i, dy=1.0: s.call("place_at", who, line[i][0], line[i][1] + dy)

    def think_now():
        s.call("mind_skip", o, now() + 60_000, THOUGHT)
        s.wait(lambda: not s.rows(f"SELECT actor FROM deliberation WHERE actor = {o}"), 10)
        return now()

    s.expect("none of the scene's people is familiar to O yet", not any(familiar(p) for p in others), [p for p in others if familiar(p)])
    try:
        # Off.
        set_law(s, "first_sight_thinks", False)
        think_now()
        t0 = now()
        near(u1, 2)
        s.wait(lambda: about(u1, t0), 10)
        time.sleep(3)
        s.expect("law off: U1's first sight is told", len(about(u1, t0)) == 1, firsts(t0))
        s.expect("law off: it asks for no thought", not asks("off"), pending())
        away(u1, 1)
        # On: refused within think_min_s, owed, asked again while in sight.
        set_law(s, "first_sight_thinks", True)
        set_law(s, "first_sight_gap_s", 40)
        s.wait(lambda: any(r["name"] == "first_sight_thinks" and r["value"] == "true" for r in s.rows("SELECT * FROM world_law")), 10)
        t1 = think_now()
        near(u2, 2)
        seen = s.wait(lambda: about(u2, t1), 10)
        time.sleep(3)
        s.expect("on: within think_min_s (20 s) of a thought the request is refused", not asks("refused"), pending())
        got = s.wait(lambda: asks(), 30)
        s.expect("owed and asked again at a later look, after think_min_s", now() - t1 >= 19_000, {"t1": t1, "now": now()})
        s.expect("one request for U2's first sight", len(got) == 1, got)
        s.expect("its reason is the first-sight line word for word", got[0] == seen[0]["text"], {"reason": got[0], "line": seen[0]["text"]})
        asked1 = now()
        # The gap: U3 once think_min_s has passed but within 40 s of U2's request.
        think_now()
        time.sleep(21)
        t3 = now()
        near(u3, 3, -1.0)
        s.wait(lambda: about(u3, t3), 10)
        time.sleep(3)
        s.expect("within first_sight_gap_s: U3's first sight is told and asks nothing", not asks("gap"), pending())
        s.wait(lambda: now() - asked1 > 45_000, 40, every=1)
        s.expect("dropped, not owed: nothing once the gap has passed either", not asks("gap-after"), pending())
        for who in (u2, u3):
            away(who, 2)
        # Far and named.
        set_law(s, "first_sight_gap_s", 0)
        far_law = 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }'
        s.call("install_script", compose(shipped, {"perceived_of": far_law}))
        set_law(s, "first_sight_thinks", True)
        set_law(s, "first_sight_gap_s", 0)
        t4 = think_now()
        time.sleep(21)
        near(v, 6)
        near(k, 7, -1.0)
        s.call("mind_say", k, f"I am {name(k)}.", 0, "", 0, FS_TALK)
        s.wait(lambda: s.rows(f"SELECT * FROM acquaintance WHERE observer = {o} AND known = {k}"), 10)
        time.sleep(6)
        s.expect("far: V and K 6-7 m off, too far to make out, get no first sight", not about(v, t4) and not about(k, t4), firsts(t4))
        s.expect("far: they ask nothing", not asks("far"), pending())
        s.expect("far: no familiar rows for them", not familiar(v) and not familiar(k))
        near(k, 2, -1.0)
        s.wait(lambda: about(k, t4), 15)
        time.sleep(2)
        s.expect("K, whose name O knows, made out: a first sight naming K", name(k) in about(k, t4)[0]["text"], about(k, t4))
        s.expect("a first sight of someone O can place asks nothing", not asks("named"), pending())
        near(v, 3)
        seen = s.wait(lambda: about(v, t4), 15)
        got = s.wait(lambda: asks(), 10)
        s.expect("V made out: asks, with V's line", len(got) == 1 and got[0] == seen[0]["text"] and "a stranger" in got[0] and name(k) not in got[0], {"asks": got, "line": seen})
        # Once per first sight.
        think_now()
        away(v, 3)
        time.sleep(3)
        t5 = now()
        near(v, 3)
        time.sleep(25)
        s.expect("V back: no new first sight and no request", not about(v, t5) and not asks("again"), {"firsts": firsts(t5), "pending": pending()})
        away(v, 3)
        away(k, 4)
        s.call("install_script", shipped)
        set_law(s, "first_sight_thinks", True)
        set_law(s, "first_sight_gap_s", 0)
        # A sleeper does not see someone it cannot place for the first time.
        think_now()
        s.graph(o, {"seq": [{"do": "sleep"}]})
        s.wait(lambda: s.rows(f"SELECT * FROM slumber WHERE actor = {o}"), 20)
        time.sleep(21)
        t6 = now()
        near(w, 2)
        time.sleep(6)
        slept = "\n".join(r["reason"] for r in s.rows(f"SELECT reason FROM slumber WHERE actor = {o}", "slumber-asleep"))
        s.expect("asleep: W gets no first-sight line", not about(w, t6), firsts(t6))
        s.expect("asleep: no familiar row for W", not familiar(w))
        s.expect("asleep: nothing waits in slumber and nothing is asked", FIRST not in slept and not asks("asleep"), {"slumber": slept, "pending": pending()})
        s.graph(o, {"wait": 300})
        s.wait(lambda: not s.rows(f"SELECT * FROM slumber WHERE actor = {o}"), 20)
        seen = s.wait(lambda: about(w, t6), 15)
        got = s.wait(lambda: asks(), 30)
        s.expect("awake: W's first sight is told and asks", len(got) == 1 and got[0] == seen[0]["text"], {"asks": got, "line": seen, "pending": pending()})
        away(w, 5)
        # One thought with a matching cue.
        set_law(s, "cues_on", True)
        set_cues(s, o, [cue("stance:verify_watch", who="unknown")])
        think_now()
        time.sleep(21)
        t7 = now()
        near(x, 2)
        s.wait(lambda: about(x, t7), 10)
        both = s.wait(lambda: (lambda p: p if WHY in p and FIRST in p else None)(pending("cue-and-first-sight")), 15)
        s.expect("with a matching cue: the cue's line and the first sight are one request", len(s.rows(f"SELECT actor FROM deliberation WHERE actor = {o}")) == 1 and len(asks()) == 1, both)
    finally:
        s.call("install_script", shipped, check=False)
        set_law(s, "first_sight_thinks", False, check=False)
        set_law(s, "first_sight_gap_s", 300, check=False)
        set_law(s, "cues_on", False, check=False)
        set_cues(s, o, [])
        s.graph(o, {"wait": 300})
        off_the_line(s, line, [o, *others], dy=58)



def profile_diag(s, seconds):
    """The authority's diagnostic counts per second over a profiled window (`common::diag`)."""
    t0 = time.time()
    s.call("set_profile", True)
    time.sleep(seconds)
    s.call("set_profile", False)
    logs = s.command("logs", "-s", "local", s.db, "-n", "200000").stdout
    total, n = {}, 0
    for m in re.finditer(r"^(\S+)Z?\s.*diag: (\{.*\})\s*$", logs, re.M):
        stamp = m.group(1).rstrip("Z")[:26]
        try:
            at = time.mktime(time.strptime(stamp.split(".")[0], "%Y-%m-%dT%H:%M:%S")) - time.timezone
        except ValueError:
            continue
        if at + 1 < t0:
            continue
        n += 1
        for k, v in json.loads(m.group(2)).items():
            total[k] = total.get(k, 0) + v
    return {k: round(v / max(n, 1), 1) for k, v in total.items()}, n


def familiar_dense(s):
    """Familiarity forgets by age only, never what is in view (docs/BATTLE_SCALE.md, fix 1;
    `brain.rs` `prune_familiar`, `FAMILIAR_LIMIT` 2,048). O stands among about 360 people (well
    over the old cap of 256), placed round it within 8 m and standing still, for 150 s: past the
    rows' 30 s touch and 60 s keep. Each of them O can see is told once and has one familiarity
    row (none forgotten and made again: under the old cap the rows past 256 were evicted while in
    view, and those people were told again). The rows are made over a minute or two: a look tells
    a crowd's first sights a few at a time, once a second."""
    line = clear_line(s)
    o = s.people(1)[0]
    s.call("place_at", o, *line[4])
    before = {c["id"] for c in s.rows("SELECT id FROM character")}
    s.call("spawn_crowd", 360, False)
    crowd = [c["id"] for c in s.rows("SELECT id FROM character") if c["id"] not in before]
    cx, cy = line[4]
    for k, who in enumerate(crowd):
        ring, step = 1.2 + (k // 30) * 0.55, (k % 30) / 30 * 2 * math.pi
        s.call("place_at", who, cx + ring * math.cos(step), cy + ring * math.sin(step), check=False)
        s.call("set_behavior", who, json.dumps({"wait": 600}), check=False)
    t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    time.sleep(150)
    fam = [r for r in s.rows(f"SELECT thing, first_ms, last_ms, times FROM familiar WHERE actor = {o}") if r["thing"] >> 40 == 2 and (r["thing"] & 0xFFFFFFFF) in set(crowd)]
    distinct = len({r["thing"] for r in fam})
    firsts = [r for r in s.rows(f"SELECT at_ms, text FROM experience WHERE observer = {o}") if "first time you see" in r["text"]]
    told = sum(len(r["text"].split("; ")) for r in firsts)
    # Tellings name everyone O sees for the first time, a scene's actors parked within sight
    # included: they are counted against all of O's rows of people, not the crowd's alone.
    people_rows = [r for r in s.rows(f"SELECT thing, first_ms FROM familiar WHERE actor = {o}") if r["thing"] >> 40 == 2]
    spread = (max(r["first_ms"] for r in fam) - min(r["first_ms"] for r in fam)) if fam else None
    m = {"crowd": len(crowd), "familiar_rows": len(fam), "distinct": distinct, "told": told, "people_rows": len(people_rows), "first_ms_spread_ms": spread, "t_place": t0}
    (s.out / f"{s.name}-familiar-dense.json").write_text(json.dumps(m, indent=1) + "\n")
    print("MEASURE", json.dumps(m), flush=True)
    try:
        s.expect("O knows more of them than the old cap (256), each by one row", len(fam) > 256, m)
        # A look tells a crowd's first sights a few at a time (FIRST_SIGHTS_PER_LINE), once a
        # second, so the rows are made over a minute or two; one forgotten and made again would be
        # a second row or a second telling.
        s.expect("one row per person: none forgotten and made again", distinct == len(fam), m)
        s.expect("each is told as a first sight exactly once (as many tellings as rows)", told == len(people_rows), m)
    finally:
        off_the_line(s, line, [o] + crowd[:40], dy=64)
        for who in crowd:
            s.call("kill", who, "verify familiar_dense done", check=False)


def notice_rate(s):
    """What is new is looked for at most once a second per character (fix 2; `brain.rs` `after`,
    `NOTICE_MS`): with a fight among minded people waking and fast-evaluating them, the noticing
    passes a second stay at most one per 0.9 s for each minded character (`NOTICE_MS`, a little under
    the 1 Hz slot), while evaluations run far above them."""
    line = clear_line(s)
    people = s.people(10)
    fighters, watchers = people[:4], people[4:]
    for k, who in enumerate(people):
        s.call("place_at", who, line[2 + k % 5][0], line[2 + k % 5][1] + (1.0 if k >= 5 else -1.0))
    for a, b in ((fighters[0], fighters[1]), (fighters[2], fighters[3])):
        s.graph(a, {"first": [{"do": {"skill": "attack", "target": {"id": b}}}, {"wait": 1}]})
        s.graph(b, {"first": [{"do": {"skill": "attack", "target": {"id": a}}}, {"wait": 1}]})
    time.sleep(2)
    try:
        d, secs = profile_diag(s, 12)
        minded = sum(1 for c in s.rows("SELECT id, ai, alive, stage FROM character") if c["ai"] and c["alive"] and c["stage"] >= 1)
        evals = d.get("eval:wake", 0) + d.get("eval:combat", 0) + d.get("eval:slot", 0)
        m = {"seconds": secs, "noticed_per_s": d.get("noticed", 0), "evals_per_s": evals, "minded": minded, "diag": {k: v for k, v in d.items() if k.startswith(("eval:", "noticed", "familiar"))}}
        (s.out / f"{s.name}-notice-rate.json").write_text(json.dumps(m, indent=1) + "\n")
        print("MEASURE", json.dumps(m), flush=True)
        s.expect("the counts were read (a profiled window)", secs >= 8, m)
        # At most one look per 0.9 s per character (NOTICE_MS, a little under the 1 Hz slot): 1.11 a second.
        s.expect("noticing about once a second per minded character, never more than once per 0.9 s", d.get("noticed", 0) <= minded / 0.9 + 2, m)
        s.expect("evaluations run well above the noticing passes", evals >= 1.3 * max(d.get("noticed", 0), 1), m)
    finally:
        for who in people:
            s.graph(who, {"wait": 300})
        off_the_line(s, line, people, dy=66)


def witness_wake(s):
    """A bystander is woken by what it sees at most once per `witness_wake_ms` (fix 3;
    `common::wake_bystander`), and still reacts within that bound; a party is woken at once. B
    stands beside V and has appraised V (exact health); B's graph waves at V once V is hurt. Five
    decoy fights start in B's sight one after another, so B's wakes are held back; then A
    strikes V. Unfolded, every percept is written at once (B's line about A and V comes with V's own). B
    waves within `witness_wake_ms` (plus 100 ms) of the blow; V, struck (a party), within 100 ms
    of its hurt; and wakes were held back meanwhile (`wake:deferred`). With fights folded
    (`witness_fold_ms`, fix 4) B's line holding the blow comes within its fold window, the wake
    still at the blow."""
    line = clear_line(s)
    ppl = s.people(13)
    a, v, b = ppl[0], ppl[1], ppl[2]
    decoys = [(ppl[3 + 2 * k], ppl[4 + 2 * k]) for k in range(5)]
    ms = law_value(s, "witness_wake_ms")
    s.call("place_at", v, *line[3])
    s.call("place_at", b, line[3][0], line[3][1] + 1.2)
    s.call("place_at", a, line[2][0], line[2][1] - 0.5)
    for k, (c, d) in enumerate(decoys):
        s.call("place_at", c, line[6 + k][0], line[6 + k][1] + 2.5)
        s.call("place_at", d, line[6 + k][0] + 0.8, line[6 + k][1] + 2.5)
    for who in ppl:
        s.graph(who, {"wait": 300})
    s.act(b, {"do": "appraise", "target": {"id": v}})
    s.wait(lambda: s.told(b, "over:", "appraise"), seconds=20)
    s.graph(b, {"first": [{"if": {"cond": {"health_of": {"target": {"id": v}, "below": 99}}, "then": {"do": {"skill": "wave", "target": {"id": v}}}}}, {"wait": 60}]})
    s.graph(v, {"first": [{"if": {"cond": {"hurt_within": 3}, "then": {"do": {"skill": "wave", "target": {"id": a}}}}}, {"wait": 60}]})
    t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.call("set_profile", True)
    try:
        for c, d in decoys:
            s.graph(c, {"first": [{"do": {"skill": "attack", "target": {"id": d}}}, {"wait": 60}]})
        s.graph(a, {"first": [{"do": {"skill": "attack", "target": {"id": v}}}, {"wait": 60}]})
        hurt = s.wait(lambda: [r for r in s.rows(f"SELECT at_ms, kind, subject, text FROM experience WHERE observer = {v}") if r["kind"] == "attacked" and r["at_ms"] >= t0], seconds=20)
        time.sleep(3)
    finally:
        s.call("set_profile", False)
    seen = [r for r in s.rows(f"SELECT at_ms, kind, subject, object, text FROM experience WHERE observer = {b}") if r["kind"] == "fight" and r["at_ms"] >= t0]
    # Folded (`witness_fold_ms`, fix 4): B's line holding the blow on V comes when B's window ends
    # and names V by B's anchor for them; unfolded, its own line comes with V's hurt.
    fold = law_value(s, "witness_fold_ms")
    about_v = [r for r in seen if ((f"#{v})" in r["text"] and r["at_ms"] >= hurt[0]["at_ms"]) if fold > 0 else r["object"] == v)]
    uses = s.rows("SELECT actor, skill, at_ms FROM skill_use")
    wave_b = sorted(u["at_ms"] for u in uses if u["actor"] == b and u["skill"] == "wave" and u["at_ms"] >= t0)
    wave_v = sorted(u["at_ms"] for u in uses if u["actor"] == v and u["skill"] == "wave" and u["at_ms"] >= t0)
    t_hurt = hurt[0]["at_ms"]
    logs = s.command("logs", "-s", "local", s.db, "-n", "100000").stdout
    deferred = sum(int(x) for x in re.findall(r'"wake:deferred":(\d+)', logs))
    m = {"witness_wake_ms": ms, "witness_fold_ms": fold, "t_hurt": t_hurt, "b_fight_lines": len(seen), "b_line_about_v": about_v[:1], "b_wave_after_ms": (wave_b[0] - t_hurt) if wave_b else None,
         "v_wave_after_ms": (wave_v[0] - t_hurt) if wave_v else None, "wakes_held_back": deferred}
    (s.out / f"{s.name}-witness-wake.json").write_text(json.dumps(m, indent=1) + "\n")
    print("MEASURE", json.dumps(m), flush=True)
    try:
        if fold > 0:
            s.expect(f"B saw the decoy fights and A's blow on V, folded: told within witness_fold_ms ({fold:.0f} ms)", len(seen) >= 1 and about_v and 0 < about_v[0]["at_ms"] - t_hurt <= fold + 100, m)
        else:
            s.expect("B saw the decoy fights and A's blow on V, each told at once", len(seen) >= 3 and about_v and about_v[0]["at_ms"] == t_hurt, m)
        s.expect("wakes were held back meanwhile (bystanders coalesced)", deferred > 0, m)
        s.expect(f"B, a bystander, reacts within witness_wake_ms ({ms} ms) of the blow on its neighbour", wave_b and 0 <= wave_b[0] - t_hurt <= ms + 100, m)
        s.expect("V, struck (a party), reacts at once (within 100 ms)", wave_v and 0 <= wave_v[0] - t_hurt <= 100, m)
    finally:
        for who in ppl:
            s.graph(who, {"wait": 300})
        off_the_line(s, line, ppl, dy=68)


BLOWS = re.compile(r"(\d+) (?:blow|shot)s? \(([^)]*)\)")


def folded_blows(text):
    """The blows a folded line counts (`living_rules::fold::line`): (blows, landed, blocked,
    dodged, missed, fell) summed over its sentences."""
    total = {"blows": 0, "landed": 0, "blocked": 0, "dodged": 0, "missed": 0}
    for n, parts in BLOWS.findall(text):
        total["blows"] += int(n)
        for part in parts.split(", "):
            k, word = part.split(" ", 1)
            total[word] += int(k)
    total["fell"] = text.count(" fell.")
    return total


def witness_fold(s):
    """What an onlooker sees of fights it is not party to is told as one folded line per
    `witness_fold_ms` (docs/BATTLE_SCALE.md, fix 4; `fold.rs`). On an open line O stands between
    two fights: A strikes V, who stands still, until V falls; C strikes D, who blocks when
    threatened. Every blow O could see is in its lines: the blows its lines count, landed and
    blocked, equal the `fight_seen` rows naming O (read while the fights go on), at most the
    strikes the rules resolved (`skill_use` outcomes), and V's fall is told. O gets at most one fight line per window, the first within the window of
    the first blow. Neither of the two in a blow is among its onlookers (`fight_seen`), and
    D's own lines come at each blow. With `witness_fold_ms` 0, a fight's first blow is told to O
    at once on its own line, as before."""
    line = clear_line(s)
    ppl = s.people(6)
    a, v, o, c, d, e = ppl
    fold = law_value(s, "witness_fold_ms")
    s.call("place_at", o, *line[3])
    s.call("place_at", a, line[2][0], line[2][1] + 1.0)
    s.call("place_at", v, line[2][0] + 0.8, line[2][1] + 1.0)
    s.call("place_at", c, line[4][0], line[4][1] + 1.0)
    s.call("place_at", d, line[4][0] + 0.8, line[4][1] + 1.0)
    s.call("place_at", e, line[5][0], line[5][1] + 3.0)
    for who in ppl:
        s.graph(who, {"wait": 300})
    s.call("grant_items", a, "spear", 1)
    s.graph(d, {"first": [{"if": {"cond": {"threatened": True}, "then": {"do": {"skill": "block"}}}}, {"wait": 60}]})
    t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    s.graph(c, {"first": [{"do": {"skill": "attack", "target": {"id": d}}}, {"wait": 60}]})
    s.graph(a, {"first": [{"do": {"skill": "attack", "target": {"id": v}}}, {"wait": 60}]})
    # The pending blows, read while the fights go on: who could see each.
    rows, start = [], time.time()
    while time.time() - start < 90:
        rows += [r for r in s.rows("SELECT * FROM fight_seen") if r["id"] not in {x["id"] for x in rows}]
        if not s.rows(f"SELECT alive FROM character WHERE id = {v}")[0]["alive"]:
            break
        time.sleep(0.3)
    s.graph(c, {"wait": 300})
    # A blow already winding up lands after the stop; its row is read before it is told.
    end = time.time() + 3
    while time.time() < end:
        rows += [r for r in s.rows("SELECT * FROM fight_seen") if r["id"] not in {x["id"] for x in rows}]
        time.sleep(0.3)
    time.sleep(fold / 1000 + 1)
    t1 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    exp = lambda who: [r for r in s.rows(f"SELECT at_ms, kind, subject, object, text FROM experience WHERE observer = {who}") if t0 <= r["at_ms"] <= t1]
    o_lines = [r for r in exp(o) if r["kind"] == "fight"]
    # The blows struck, as the rules resolved them (each strike's `skill_use` outcome: "hit for 9",
    # "blocked, 1 got through", "killed …", "dodged", "missed"); V's own lines go with V's death.
    struck = [u for u in s.rows("SELECT * FROM skill_use") if (u["actor"], u["target"]) in ((a, v), (c, d)) and t0 <= u["outcome_ms"] <= t1
              and re.match(r"(hit for|blocked|killed|dodged|missed)", u["outcome"] or "")]
    d_own = [r for r in exp(d) if r["subject"] == c and r["kind"] in ("attacked", "combat")]
    o_sum = folded_blows(" ".join(r["text"] for r in o_lines))
    first_blow = min([u["outcome_ms"] for u in struck], default=None)
    rows = [r for r in rows if (r["attacker"], r["victim"]) in ((a, v), (c, d))]
    onlookers = [x & 0x7FFFFFFF for r in rows for x in r["onlookers"]]
    m = {"witness_fold_ms": fold, "o_lines": [r["text"] for r in o_lines][:6], "o_line_count": len(o_lines), "o_counted": o_sum,
         "struck": len(struck), "struck_landed": sum(1 for u in struck if u["outcome"].startswith(("hit", "killed"))), "struck_blocked": sum(1 for u in struck if u["outcome"].startswith("blocked")),
         "d_told": len(d_own), "v_dead": not s.rows(f"SELECT alive FROM character WHERE id = {v}")[0]["alive"],
         "rows_read": len(rows), "first_line_after_ms": (o_lines[0]["at_ms"] - first_blow) if o_lines and first_blow else None,
         "seconds": round((t1 - t0) / 1000, 1)}
    (s.out / f"{s.name}-witness-fold.json").write_text(json.dumps(m, indent=1) + "\n")
    print("MEASURE", json.dumps(m), flush=True)
    try:
        s.expect("the fights happened: V fell, and D blocked", m["v_dead"] and any("You blocked" in r["text"] for r in d_own), m)
        # Every blow O could see: the rows naming O (O's facing may hide some), at most every strike.
        o_rows = [r for r in rows if o in [x & 0x7FFFFFFF for x in r["onlookers"]]]
        m["o_rows"] = len(o_rows)
        # The rows are read by polling, so a few may go unread under load: a lower bound. When O
        # was among every row read, it saw the fights whole, and its lines count every strike.
        whole = len(o_rows) == len(rows)
        exact = o_sum["blows"] == m["struck"] and o_sum["landed"] == m["struck_landed"] and o_sum["blocked"] == m["struck_blocked"]
        s.expect("every blow O could see is in its folded lines, each with its outcome",
                 len(o_rows) <= o_sum["blows"] <= m["struck"] and o_sum["blocked"] >= 1 and (exact if whole else True), m)
        s.expect("O's lines say V fell, once", o_sum["fell"] == 1 and any("fell" in r["text"] and ("attacked" in r["text"] or "kept on at" in r["text"]) for r in o_lines), m)
        s.expect("folded: fewer lines than blows, at most one a window", 0 < len(o_lines) < o_sum["blows"] and len(o_lines) <= (t1 - t0) / fold + 2, m)
        s.expect(f"O's first line comes within witness_fold_ms ({fold:.0f} ms) of the first blow", m["first_line_after_ms"] is not None and 0 < m["first_line_after_ms"] <= fold + 100, m)
        s.expect("O saw most blows, and neither of the two in a blow is among its onlookers (the other fight's pair may be)",
                 rows and len(o_rows) * 2 >= len(rows) and not any({r["attacker"], r["victim"]} & {x & 0x7FFFFFFF for x in r["onlookers"]} for r in rows),
                 {"rows": len(rows), "onlookers": sorted(set(onlookers))})
        s.expect("D was told of each blow at it at once (its own lines, not folded)", len([r for r in d_own if r["kind"] == "attacked"]) == m["struck_blocked"] and not any("blow" in r["text"] and f"#{d})" in r["text"] for r in exp(d) if r["kind"] == "fight"), m)
        # As before, with the law at 0: a fight's first blow is told to O at once, on its own line.
        s.call("set_world_law", "witness_fold_ms", "0")
        try:
            t2 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
            s.graph(e, {"first": [{"do": {"skill": "attack", "target": {"id": c}}}, {"wait": 60}]})
            hit = s.wait(lambda: [r for r in s.rows(f"SELECT at_ms, kind, subject FROM experience WHERE observer = {c}") if r["at_ms"] >= t2 and r["subject"] == e and r["kind"] in ("attacked", "combat")], seconds=20)
            time.sleep(1)
            unfolded = [r for r in s.rows(f"SELECT at_ms, kind, text FROM experience WHERE observer = {o}") if r["at_ms"] >= t2 and r["kind"] == "fight"]
            s.expect("with witness_fold_ms 0, O is told the first blow at once on its own line", unfolded and unfolded[0]["at_ms"] == hit[0]["at_ms"] and "attacked" in unfolded[0]["text"] and "blow" not in unfolded[0]["text"], unfolded[:2])
        finally:
            s.call("set_world_law", "witness_fold_ms", str(int(fold)))
    finally:
        for who in ppl:
            if who != v:
                s.graph(who, {"wait": 300})
        off_the_line(s, line, [x for x in ppl if x != v], dy=72)

SCENES["first_sight"] = first_sight


SCENES["familiar_dense"] = familiar_dense
SCENES["notice_rate"] = notice_rate
SCENES["witness_wake"] = witness_wake
SCENES["witness_fold"] = witness_fold


HF_TALK = {"kind": "talk", "summary": "verify-core heard_first: L speaks", "detail": "", "latency_ms": 0, "tokens": 0, "model": "fake", "reference": ""}


def hf_decided(latency_ms):
    """A deliberation's thought whose model calls took `latency_ms` (its decision read its scene that long ago)."""
    return {"kind": "deliberate", "summary": "verify-core heard_first: O decides", "detail": "", "latency_ms": latency_ms, "tokens": 0, "model": "fake", "reference": ""}


def heard_first(s):
    """A line a mind decided to say to someone, coming due after it heard another address them
    since its decision read its scene, waits under the `heard_first_rethinks` law
    (docs/FIRST_SIGHT.md, "Crowds"; `speech::addressed_by_another`, `held_for_another`): it is
    not said, the speaker is told ("You had not yet said … when you heard: …") and its mind is
    asked to think again with that line as the reason. On an open line O, L and U stand within
    3 m. No mind runs: O's decisions are delivered as the mind service delivers them
    (`mind_say` carrying on, `mind_install` with a `say`), with the thought's latency standing
    for when the decision read its scene. Checks:
    - law off: after L says a line to U, O's line to U from a decision made 10 s before is said;
    - law on: the same through `mind_say` and through `mind_install` is held, told and asked for;
    - a decision made after L's line (latency 0: its prompt was built after it) is said;
    - a line to U with nobody else speaking is said;
    - a plan's say node to U (a mind's install) that comes due after L addressed U is held;
    - L's line to someone else (not U) holds nothing.
    The law is restored at the end."""
    line = clear_line(s)
    o, l, u, k = s.people(4)
    for i, who in enumerate((o, l, u, k)):
        s.call("place_at", who, line[2 * i][0], line[2 * i][1])
        s.graph(who, {"wait": 300})
    now = lambda: s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    said_by = lambda who, since: [c for c in s.rows(f"SELECT at_ms, kind, a, b, text FROM chronicle WHERE kind = 'speech'") if c["a"] == who and c["at_ms"] >= since]
    unsaid = lambda since: [e for e in s.rows(f"SELECT at_ms, kind, text FROM experience WHERE observer = {o}") if e["kind"] == "unsaid" and e["at_ms"] >= since]
    pending = lambda: "\n".join(r["reason"] for r in s.rows(f"SELECT reason FROM deliberation WHERE actor = {o}"))
    clear = lambda: s.call("mind_skip", o, now() + 60_000, hf_decided(0))

    def l_says(text, to):
        s.call("mind_say", l, text, to, "", 0, HF_TALK)
        time.sleep(2.3)

    try:
        # Off.
        set_law(s, "heard_first_rethinks", False)
        clear()
        t0 = now()
        l_says("Morning to you, stranger. verify hf L1", u)
        s.call("mind_say", o, "Who are you? verify hf O1", u, "", t0 - 10_000, hf_decided(10_000))
        time.sleep(2.3)
        s.expect("law off: O's line after L's is said", any("verify hf O1" in c["text"] for c in said_by(o, t0)), said_by(o, t0))
        # On: mind_say (a deliberation carrying on).
        set_law(s, "heard_first_rethinks", True)
        s.wait(lambda: any(w["name"] == "heard_first_rethinks" and w["value"] == "true" for w in s.rows("SELECT * FROM world_law")), 10)
        clear()
        t1 = now()
        l_says("Good day, friend. verify hf L2", u)
        s.call("mind_say", o, "Who are you? verify hf O2", u, "", t1 - 10_000, hf_decided(10_000))
        time.sleep(1.5)
        s.expect("on (mind_say): O's line is not said", not any("verify hf O2" in c["text"] for c in said_by(o, t1)), said_by(o, t1))
        told = unsaid(t1)
        s.expect("O is told what it had not said and the line it heard", told and "verify hf O2" in told[0]["text"] and "verify hf L2" in told[0]["text"] and told[0]["text"].startswith("You had not yet said"), told)
        s.expect("O's mind is asked to think, with that as the reason", told and told[0]["text"] in pending(), pending())
        # On: mind_install (a new plan with its own line).
        clear()
        t2 = now()
        l_says("You'll be new here. verify hf L3", u)
        s.call("mind_install", o, json.dumps({"wait": 300}), "verify hf plan", "Welcome. verify hf O3", u, t2 - 10_000, hf_decided(10_000))
        time.sleep(1.5)
        s.expect("on (mind_install): the install's line is not said", not any("verify hf O3" in c["text"] for c in said_by(o, t2)), said_by(o, t2))
        s.expect("and is told and asked for", any("verify hf O3" in e["text"] for e in unsaid(t2)) and "verify hf O3" in pending(), {"told": unsaid(t2), "pending": pending()})
        # A decision made after L's line (its calls began after it): said.
        clear()
        t3 = now()
        l_says("Fair weather. verify hf L4", u)
        s.call("mind_say", o, "And who might you be? verify hf O4", u, "", now(), hf_decided(0))
        time.sleep(2.3)
        s.expect("a decision whose prompt came after L's line: said", any("verify hf O4" in c["text"] for c in said_by(o, t3)), said_by(o, t3))
        # Nobody else speaking: said (past the 10 s window of the lines above).
        time.sleep(11)
        clear()
        t4 = now()
        s.call("mind_say", o, "Still here? verify hf O5", u, "", t4 - 10_000, hf_decided(10_000))
        time.sleep(2.3)
        s.expect("no one else spoke to U: said", any("verify hf O5" in c["text"] for c in said_by(o, t4)), said_by(o, t4))
        # L speaks to K, not U: nothing held (past the window of L's earlier lines to U).
        time.sleep(11)
        clear()
        t5 = now()
        l_says("K, the nets. verify hf L6", k)
        s.call("mind_say", o, "Name yourself. verify hf O6", u, "", t5 - 10_000, hf_decided(10_000))
        time.sleep(2.3)
        s.expect("L's line to K holds nothing of O's line to U", any("verify hf O6" in c["text"] for c in said_by(o, t5)), said_by(o, t5))
        # A plan's say node, coming due after L addressed U.
        clear()
        t6 = now()
        plan = {"seq": [{"wait": 4}, {"say": {"text": "Where from? verify hf O7", "to": {"id": u}}}, {"wait": 300}]}
        s.call("mind_install", o, json.dumps(plan), "verify hf say node", "", 0, now(), hf_decided(0))
        time.sleep(1.0)
        l_says("Come in from the rain. verify hf L7", u)
        time.sleep(4)
        s.expect("a plan's say node after L's line to U is not said", not any("verify hf O7" in c["text"] for c in said_by(o, t6)), said_by(o, t6))
        s.expect("and is told and asked for", any("verify hf O7" in e["text"] for e in unsaid(t6)) and "verify hf O7" in pending(), {"told": unsaid(t6), "pending": pending()})
        (s.out / f"{s.name}-told.json").write_text(json.dumps({"unsaid": unsaid(t1), "pending": pending()}, indent=1, ensure_ascii=False) + "\n")
    finally:
        set_law(s, "heard_first_rethinks", False, check=False)
        for who in (o, l, u, k):
            s.graph(who, {"wait": 300})
        off_the_line(s, line, [o, l, u, k], dy=62)


SCENES["heard_first"] = heard_first


def battle_cheap(s):
    """The fighters' cheaper paths change nothing a fighter perceives or does (docs/BATTLE_SCALE.md,
    battle-cheap). A battle of 12 minded people on an open line, a campfire and a shelter among
    them and three dead lying there (remains), with each path's diagnostic law on: every move's
    check before it starts is also asked with the whole context (`check_ctx_check`), every alarm
    answer kept is also asked of the law (`alarm_cells_check`), and warmth is also worked out from
    a full copy (`warmth_check`). For 60 s of strikes, blocks, heals and refusals ("out of breath")
    each diagnostic counts how often it compared and how often the two differed. The case named
    asserts its path: compared many times, never differed (and, for the alarms, most answers
    kept)."""
    which = s.name
    line = clear_line(s)
    ppl = s.people(15)
    fighters, dead = ppl[:12], ppl[12:]
    for k, who in enumerate(fighters):
        s.call("place_at", who, line[2 + k % 6][0], line[2 + k % 6][1] + (k // 6) * 1.4)
    for k, who in enumerate(dead):
        s.call("place_at", who, line[3 + k][0], line[3 + k][1] + 2.6)
    s.call("place_structure", fighters[0], "campfire")
    s.call("place_structure", fighters[6], "shelter")
    for who in dead:
        s.call("kill", who, "verify-core battle_cheap: remains to lie among the fighters")
    for who in fighters:
        s.call("grant_know_how", who, "wound_tending")
        s.graph(who, {"first": [
            {"if": {"cond": {"health": {"below": 50}}, "then": {"do": {"skill": "heal", "target": "self"}}}},
            {"if": {"cond": {"threatened": True}, "then": {"do": {"skill": "dodge" if who % 2 == 0 else "block"}}}},
            {"do": {"skill": "strike", "target": {"nearest": "person"}}}]})
    for law in ("check_ctx_check", "alarm_cells_check", "warmth_check"):
        set_law(s, law, True)
    s.call("set_profile", True)
    t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    # The server log's own stamps (UTC) bound this case's `diag:` lines: earlier cases on the
    # same world left theirs.
    since = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        time.sleep(60)
    finally:
        s.call("set_profile", False)
        for law in ("check_ctx_check", "alarm_cells_check", "warmth_check"):
            set_law(s, law, False)
    logs = "\n".join(l for l in s.command("logs", "-s", "local", s.db, "-n", "200000").stdout.splitlines() if l[:19] >= since and "diag:" in l)
    count = lambda key: sum(int(x) for x in re.findall(rf'"{re.escape(key)}":(\d+)', logs))
    uses = [u for u in s.rows("SELECT actor, skill, outcome, at_ms FROM skill_use") if u["at_ms"] >= t0 and u["actor"] in fighters]
    m = {k: count(k) for k in ("check_ctx:checked", "check_ctx:differed", "alarm:kept", "alarm:checked", "alarm:asked", "alarm:differed", "warmth:checked", "warmth:differed")}
    m["uses"] = len(uses)
    m["strikes_landed"] = sum(1 for u in uses if u["skill"] == "strike" and (u["outcome"] or "").startswith(("hit", "blocked", "killed")))
    m["out_of_breath"] = sum(1 for u in uses if "out of breath" in (u["outcome"] or ""))
    m["remains"] = len([r for r in s.rows("SELECT id, kind FROM structure") if r["kind"] == "remains"])
    (s.out / f"{s.name}-battle-cheap.json").write_text(json.dumps(m, indent=1) + "\n")
    print("MEASURE", json.dumps(m), flush=True)
    try:
        s.expect("a battle went on: strikes landed, and some were refused for want of breath or tried again", m["strikes_landed"] >= 10, m)
        if which == "cheap_check_ctx":
            s.expect("every move's check on its plan's fields gave the whole context's answer", m["check_ctx:checked"] >= 100 and m["check_ctx:differed"] == 0, m)
        elif which == "cheap_alarms":
            s.expect("every kept alarm answer was the law's, and most answers were kept", m["alarm:checked"] == m["alarm:kept"] and m["alarm:kept"] > m["alarm:asked"] and m["alarm:differed"] == 0, m)
        elif which == "cheap_warmth":
            s.expect("warmth among remains, a fire and a shelter came out the same both ways", m["warmth:checked"] >= 100 and m["warmth:differed"] == 0 and m["remains"] >= 3, m)
    finally:
        for who in fighters:
            s.graph(who, {"wait": 300})
        off_the_line(s, line, fighters, dy=76)


SCENES["cheap_check_ctx"] = battle_cheap
SCENES["cheap_alarms"] = battle_cheap
SCENES["cheap_warmth"] = battle_cheap


def admin_vitals(s):
    """`admin_set_vitals(id, hp)` (admin only): sets a living body's health, more than its maximum
    being its maximum, and chronicles each use as an `admin` line; a health of 0 or less, or a dead
    character, is refused and writes nothing. Trial timelines use it to start an arena's meetings at
    full health (docs/COMBAT_MIND.md §5.4); verify-client checks that no other identity may call it."""
    a = s.people(1)[0]
    hp = lambda label: s.rows(f"SELECT * FROM vitals WHERE id = {a}", label)[0]
    admin_lines = lambda label: [c for c in s.rows(f"SELECT * FROM chronicle WHERE a = {a}", label) if c["kind"] == "admin"]
    s.call("admin_set_vitals", a, 40.0)
    v = hp("vitals-40")
    s.expect("health set to 40", abs(v["hp"] - 40.0) < 0.5, v["hp"])
    s.call("admin_set_vitals", a, 1000.0)
    v = hp("vitals-max")
    s.expect("more than the maximum is the maximum", abs(v["hp"] - v["max_hp"]) < 0.01, [v["hp"], v["max_hp"]])
    lines = admin_lines("admin-lines")
    s.expect("each use is an admin chronicle line", len(lines) == 2 and "health 40 ->" not in lines[0]["text"] and "-> 40" in lines[0]["text"] and f"-> {v['max_hp']:.0f}" in lines[1]["text"], [c["text"] for c in lines])
    # (a negative value cannot be passed through the admin CLI, which reads "-5" as a flag)
    for bad in (0.0,):
        r = s.call("admin_set_vitals", a, bad, check=False)
        out = (r.stdout or "") + (r.stderr or "")
        s.expect(f"a health of {bad:g} is refused", r.returncode != 0 and "health must be above 0" in out, out[-200:])
    s.expect("a refused call writes nothing", len(admin_lines("admin-lines-after")) == 2 and abs(hp("vitals-after")["hp"] - v["max_hp"]) < 0.5)
    s.call("kill", a, "verify admin_vitals")
    r = s.call("admin_set_vitals", a, 50.0, check=False)
    out = (r.stdout or "") + (r.stderr or "")
    s.expect("a dead character is refused", r.returncode != 0 and "no living character" in out, out[-200:])


SCENES["admin_vitals"] = admin_vitals


if __name__ == "__main__":
    raise SystemExit(main())
