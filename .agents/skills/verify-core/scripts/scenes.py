#!/usr/bin/env python3
"""Assert core behavior through the authority on a shared-harness scratch run."""
import argparse
import json
import math
import re
import subprocess
import time
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
        return self.command("call", "-s", "local", self.db, reducer,
                            *(json.dumps(a) for a in args), check=check)

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


def needs(s):
    a = s.people(1)[0]
    s.wait(lambda: s.vitals(a)["hunger_rate"] > 0)
    n0 = s.needs(a, "idle-before")
    time.sleep(8)
    n1 = s.needs(a, "idle-after")
    s.expect("hunger rises and idle energy falls", n1["hunger"] > n0["hunger"] + 0.4 and n1["energy"] < n0["energy"] - 0.1)
    s.graph(a, {"first": [{"do": "rest"}]})
    s.wait(lambda: s.vitals(a)["energy_rate"] > 0)
    rest0 = s.needs(a, "rest-before")
    time.sleep(8)
    rest1 = s.needs(a, "rest-after")
    s.expect("rest recovers energy over time", rest1["energy"] > rest0["energy"] + 0.4)
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
    s.graph(a, {"wait": 120})
    s.wait(lambda: s.vitals(a)["hp_rate"] > cold["hp_rate"] + 1.5)
    warm = s.vitals(a, "cloaked")
    s.expect("cloak removes the cold penalty", abs(warm["hp_rate"] - cold["hp_rate"] - 2) < 0.1,
             {"cold_hp_rate": cold["hp_rate"], "cloaked_hp_rate": warm["hp_rate"]})


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
    print("Waiting for real night with infant hunger >=70 to isolate cold HP loss.", flush=True)
    s.wait(night_and_no_healing, seconds=2100, every=5)
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
    s.expect("shelter removes exactly the summer cold penalty", abs(warm["hp_rate"] - cold["hp_rate"] - 2) < 0.1,
             {"sheltered": warm["hp_rate"], "exposed": cold["hp_rate"]})
    if not s.baseline:
        s.expect("parent sees warm shelter and cold exposure matching HP-rate sign",
                 "warm" in warm_looks and "cold" in cold_looks and warm["hp_rate"] >= 0 and cold["hp_rate"] < 0,
                 {"sheltered_looks": warm_looks, "exposed_looks": cold_looks})
    n0 = s.needs(baby["id"], "cold-before")
    time.sleep(8)
    n1 = s.needs(baby["id"], "cold-after")
    s.expect("exposed infant actually loses health", n1["hp"] < n0["hp"] - 0.15)

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
    s.wait(lambda: 55 < s.needs(baby["id"], "hunger-ready")["hunger"] < 80, seconds=300, every=2)
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
    walk = lambda x, y: at(x, y) not in (2, 4, 7)
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


SCENES = {"skirmish": skirmish, "infant": infant, "tick": tick, "needs": needs, "seize": seize, "lifecycle": lifecycle, "wildlife": wildlife, "grazing": grazing, "arrival": arrival, "sight": sight, "dealings": dealings}


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
