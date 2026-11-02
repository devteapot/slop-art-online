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
        s.graph(a, {"first": [{"do": {"skill": "attack", "target": {"id": b}, "item": "hurt"}}, {"wait": 1}]})
        s.wait(lambda: s.told(a, "enough", "own"), seconds=65)
        v = s.vitals(b)
        if v["hp"] / v["max_hp"] >= 0.35:
            s.graph(a, {"first": [{"do": {"skill": "attack", "target": {"id": b}, "item": "kill"}}, {"wait": 1}]})
            s.wait(lambda: s.vitals(b)["hp"] / s.vitals(b)["max_hp"] < 0.3, seconds=10, every=0.1)
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
    s.graph(a, {"first": [{"do": {"skill": "attack", "target": {"id": b}, "item": "kill"}}, {"wait": 1}]})
    s.wait(lambda: not s.rows(f"SELECT alive FROM character WHERE id = {b}")[0]["alive"], seconds=90)
    dead = s.rows(f"SELECT * FROM character WHERE id = {b}", "killed")[0]
    s.expect("kill intent can kill someone who yielded", "after yielding" in dead["cause"] and bool(s.story("killing", a, "killing")))


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
    s.expect("cooldown prevents another group below the floor", {c["id"] for c in after} == ids)


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


SCENES = {"infant": infant, "tick": tick, "needs": needs, "seize": seize, "lifecycle": lifecycle, "wildlife": wildlife, "grazing": grazing, "arrival": arrival}


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
