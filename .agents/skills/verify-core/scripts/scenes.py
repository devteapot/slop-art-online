#!/usr/bin/env python3
"""Assert core behavior through the authority on a shared-harness scratch run."""
import argparse
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
        if not re.fullmatch(r"core-[a-z0-9-]+", run):
            raise ValueError("use a core-* run name with lowercase letters, digits and hyphens")
        self.out = BASE / run
        state = json.loads((self.out / "state.json").read_text())
        self.db = state["db"]
        if self.db != "verify-" + run or not state.get("published"):
            raise ValueError("use a published core-* run created by verify.py launch")
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
        "beliefs": None, "judgments": [], "places": [], "thought": None, "replace": True})
    for actor in (b, witness):
        s.call("place_near", actor, a)
    s.call("place_near", baby["id"], a)
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
    fallback = s.wait(lambda: [d for d in requests() if "crying" in d["reason"] and baby["name"] in d["reason"]], seconds=55)
    time.sleep(3)
    fallback = [d for d in requests("fallback-requests") if "crying" in d["reason"] and baby["name"] in d["reason"]]
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
    As the `low` scene the same is driven over a low thing (tile 9: a cart, below eye height,
    `LandParams.sight`) on an `island` run."""
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
            time.sleep(1)
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


def doing(s):
    """What one character perceives another doing, for AI bodies (docs/PERCEPTION.md, "Activity
    derived from the body"): its activity's label, unchanged by the derivation from the body,
    which applies only to a body moving under motion intent (a player's movement keys; no AI
    body steers that way). On an open line an observer O stands at the west end; W1 walks to O
    (goto), W2 walks in from 10 m to a spot near O (goto a point), F follows O, S stands by.
    O's graph thinks (a `think` leaf), which writes O's deliberation scene: the `doing` of each
    must be its activity's label, and none of their bodies steers by direction (`steer.goal`
    3). About a minute: the observer can ask for a deliberation only 45 s after it arrives."""
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
    s.graph(f, {"seq": [{"do": {"skill": "follow", "target": {"id": obs}}}, {"wait": 300}]})
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
    s.expect("the scene's doing is each AI body's activity label", all(seen.get(i) == a["label"] for i, a in acts.items() if i in seen) and len(seen.keys() & acts.keys()) >= 3, {"seen": seen, "labels": {i: a["label"] for i, a in acts.items()}})
    s.expect("a walk to a place reads goto → (x,y)", (seen.get(w2) or "").startswith("goto → ("), seen.get(w2))
    s.expect("a follow reads follow → person", seen.get(f) == "follow → person", seen.get(f))
    s.expect("standing by reads wait", seen.get(st) == "wait", seen.get(st))
    s.expect("a walk to the observer reads goto → person", seen.get(w1) == "goto → person", {"seen": seen.get(w1), "activity": acts.get(w1)}, fatal=False)
    s.expect("no AI body steers by direction (motion intent)", not [r for r in steer if r["goal"] == 3 and r["id"] in (obs, w1, w2, f, st)], [r for r in steer if r["id"] in (w1, w2, f, st)])


def moves(s):
    """How a creature moves besides its walk is the script's `motion(a)` law: a flight at 1.15
    times the walk, turning on the spot at 6 rad/s. A person walks off (its cruising speed is
    its walk), then flees a second person (1.15 times that), then turns to face someone behind
    it (the body row's turn rate). An installed overlay with a flight of 2 and turning at 3
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
        s.graph(a, {"seq": [{"do": {"skill": "flee", "target": {"id": b}}}, {"wait": 300}]})
        time.sleep(1.5)
        flee = body(f"{label}-flee")["speed"]
        s.graph(a, {"wait": 300})
        time.sleep(2.5)
        h = body(f"{label}-stand")["heading"]
        here = body_at(s, a)
        s.call("place_at", b, here[0] - 3 * math.cos(h), here[1] - 3 * math.sin(h))
        time.sleep(0.5)
        s.graph(a, {"seq": [{"do": {"skill": "face", "target": {"id": b}}}, {"wait": 300}]})
        time.sleep(2)
        turn = abs(body(f"{label}-face")["turn"])
        return {"walk": walk, "flee": flee, "ratio": round(flee / walk, 3) if walk else None, "turn": round(turn, 3)}

    try:
        got = measure("shipped")
        s.expect("shipped law: a flight is 1.15 times the walk", got["ratio"] and abs(got["ratio"] - 1.15) < 0.02, got)
        s.expect("shipped law: turning on the spot at 6 rad/s", abs(got["turn"] - 6.0) < 0.01, got)
        src = shipped.replace("fn motion(a)", "fn base_motion(a)", 1) + "\nfn motion(a) { let m = base_motion(a); m.flee = 2.0; m.turn_rate = 3.0; m }\n"
        s.call("install_script", src)
        got = measure("overlay")
        s.expect("an installed law changes the flight: 2 times the walk", got["ratio"] and abs(got["ratio"] - 2.0) < 0.03, got)
        s.expect("an installed law changes turning: 3 rad/s", abs(got["turn"] - 3.0) < 0.01, got)
    finally:
        s.call("install_script", shipped)


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


REMAINS_S = 90


def carcass_law(kind):
    """What the shipped script gives a kind's remains: the `carcass` trait of its row in
    `kinds()` (read by the `carcass(kind)` law)."""
    src = (ROOT / "living/scripts/skills.rhai").read_text()
    m = re.search(r'name:\s*"%s"[^\n]*?carcass:\s*#\{([^}]*)\}' % kind, src)
    return {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", m.group(1))} if m else {}


def remains(s):
    """Every death leaves remains with the `carcass` law's items; a kill feeds nobody by itself;
    any creature beside the remains takes from them; they are gone after `remains_s`; a wander
    keeps its heading (the `motion` law's `wander_turn`, `wander_keep_s`). Needs a world with deer and wolves (stage1-acts)."""
    src = compose((ROOT / "living/scripts/skills.rhai").read_text(), {"remains_s": f"fn remains_s(kind) {{ {REMAINS_S} }}"})
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
    s.expect("its remains are due after the remains_s law", len(rot) == 1 and rot[0]["due_ms"] - r_a["built_ms"] == REMAINS_S * 1000, rot)

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


SCENES = {"skirmish": skirmish, "infant": infant, "tick": tick, "needs": needs, "seize": seize, "lifecycle": lifecycle, "wildlife": wildlife, "grazing": grazing, "arrival": arrival, "sight": sight, "dealings": dealings, "flee": flee, "food": food, "refusal": refusal, "senses": senses, "moves": moves, "remains": remains, "laws": laws, "doing": doing, "death-names": death_names, "drop": drop, "low": drop, "family_laws": family_laws, "fov": fov}


def goods(s):
    """Goods are script data matched by trait, and fires eat fuel (docs/WORLD_RULES.md, "Goods,
    recipes and fuel"), on the goods fixture: Cullet's goods (living/scripts/cullet_goods.rhai)
    installed over the shipped rules; kelp, peat and sand gathered from nodes placed beside a
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
    acts(a, {"do": "make", "item": "glass", "target": {"nearest": "furnace"}})
    s.wait(lambda: s.inventory(a).get("glass", 0) == 1, seconds=60)
    inv = s.inventory(a, "after-glass")
    after = structure("furnace", b)
    unit = hour_ms / 3
    s.expect("an alkali and two sand make glass at the burning furnace", inv.get("glass") == 1 and inv.get("ash", 0) == 0 and inv.get("sand", 0) == 0, inv)
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


SCENES["goods"] = goods
SCENES["stock"] = stock


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scene", choices=SCENES)
    ap.add_argument("--run", required=True)
    ap.add_argument("--baseline", action="store_true", help="measure pre-change infant authority without new-policy assertions")
    ap.add_argument("--resume-infant", action="store_true", help="rerun cry checks from the retained thermal checkpoint")
    a = ap.parse_args()
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


if __name__ == "__main__":
    raise SystemExit(main())
