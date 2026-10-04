#!/usr/bin/env python3
"""Assert core behavior through the authority on a shared-harness scratch run."""
import argparse
import json
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


SCENES = {"tick": tick, "needs": needs, "seize": seize, "lifecycle": lifecycle, "wildlife": wildlife, "grazing": grazing, "arrival": arrival}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scene", choices=SCENES)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    s = Scene(a.run, a.scene)
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
