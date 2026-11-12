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
        # Off the shared open line: later scenes (doing) count who stands near its west end.
        for k, who in enumerate((eye, ahead, behind, close, w_toward, w_away)):
            s.call("place_at", who, line[0][0] + 60 + 2 * k, line[0][1] + 44, check=False)


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
    own = [r for r in s.rows("SELECT * FROM world_law") if r["name"] == name]
    if own:
        return float(own[0]["value"])
    src = s.rows("SELECT source FROM script WHERE name = 'skills'")[0]["source"]
    return float(re.search(r"\b" + name + r": ([0-9.]+)", src).group(1))


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
    """A bold wolf charges a person 5 m away who goes straight off along an open line, running
    (`goto` with `run: true`, while breath lasts) or walking: the time until the gap is down to
    the wolf's catch distance (its attack's reach and its lunge, 3.2 m), or the gap at 30 s
    (`CHASE_S`) if never. Timed on the distance, not on a blow landing, so the time of day (a
    wolf losing its prey beyond its night sight) does not decide it. `CHASES` (4) of each;
    `chase-results.json`. The runner and the wolf go at their `motion` laws (`run_share`,
    `wolf_run`): set them with `set_world_law` to measure another pairing."""
    import statistics
    n = int(os.environ.get("CHASES", "4"))
    limit = float(os.environ.get("CHASE_S", "30"))
    catch = 3.2
    line = open_line(s, length=64)
    wolves = [c["id"] for c in s.rows("SELECT id, stage FROM character WHERE kind = 'wolf' AND alive = true") if c["stage"] >= 2]
    out = []
    for mode in ("run", "walk"):
        for k in range(min(n, len(wolves))):
            alive = {c["id"] for c in s.rows("SELECT id FROM character WHERE kind = 'wolf' AND alive = true")}
            if wolves[k] not in alive:
                continue
            p, = s.people(1)
            w = wolves[k]
            s.call("set_background", w, json.dumps({"pack": "verify chase", "bold": True}, separators=(",", ":")))
            s.graph(w, {"wait": 300})
            s.call("place_at", p, *line[8])
            s.call("place_at", w, *line[3])
            time.sleep(1.0)
            s.graph(p, {"do": {"skill": "goto", "target": {"at": list(line[63])}, "run": mode == "run"}})
            s.graph(w, {"do": {"skill": "attack", "target": {"id": p}}})
            t0 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
            caught, d, speeds, gaps = None, None, [], []
            while True:
                now = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
                b = {r["id"]: r for r in s.rows(f"SELECT id, vx, vy FROM body WHERE id = {p} OR id = {w}")}
                speeds.append({x: round(math.hypot(b[x]["vx"], b[x]["vy"]), 2) for x in b})
                d = apart(s, p, w)
                gaps.append((now - t0, d))
                if d <= catch:
                    caught = round((now - t0) / 1000, 1)
                    break
                if now - t0 > limit * 1000:
                    break
                time.sleep(0.15)
            s.graph(p, {"wait": 300})
            s.graph(w, {"wait": 300})
            moving = lambda x: [sp[x] for sp in speeds if sp.get(x, 0) > 0.3]
            med = lambda v: round(statistics.median(v), 2) if v else 0
            r = {"mode": mode, "person": p, "wolf": w, "caught_s": caught, "gap_end": d, "gap_max": max(g for _, g in gaps),
                 "person_speed_med": med(moving(p)), "wolf_speed_med": med(moving(w))}
            print(json.dumps(r), flush=True)
            out.append(r)
            time.sleep(3)
    (s.out / f"{s.name}-results.json").write_text(json.dumps(out, indent=1) + "\n")
    for mode in ("run", "walk"):
        c = [r["caught_s"] for r in out if r["mode"] == mode]
        got = sorted(x for x in c if x is not None)
        print(f"{mode}: caught {len(got)} of {len(c)}, median {statistics.median(got) if got else None} s, range {got[:1] + got[-1:]}", flush=True)
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
        bad = compose(shipped, {"meters": 'fn meters() { base_meters() + [#{ name: "stamina", value: "stamina", max: 100.0 }] }'})
        r = s.call("install_script", bad, check=False)
        out = (r.stdout or "") + (r.stderr or "")
        s.expect("a meter naming a field the vitals row lacks is refused at install", r.returncode != 0 and "not a my_vitals field" in out, out[-300:])
    finally:
        s.call("install_script", shipped)


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
    s.call("place_at", obs, *line[0])
    for a, (dx, dy) in zip(crowd, spots):
        s.call("place_at", a, line[dx][0], line[dx][1] + dy)
    t1 = s.rows("SELECT last_ms FROM clock")[0]["last_ms"]
    time.sleep(10)
    fam = lambda ids: {r["thing"] & 0xFFFFFFFF for r in s.rows(f"SELECT thing FROM familiar WHERE actor = {obs}") if r["thing"] >> 40 == 2} & set(ids)
    firsts = lambda since: [r for r in s.rows(f"SELECT id, at_ms, kind, subject, object, text, salience FROM experience WHERE observer = {obs}") if r["at_ms"] >= since and "first time you see" in r["text"]]
    exps = s.rows(f"SELECT id, at_ms, kind, subject, object, text FROM experience WHERE observer = {obs}", "experiences-crowd")
    lines1 = firsts(t1 - 2000)
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
                              "beliefs": None, "judgments": [], "places": [], "thought": None, "replace": False})
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
                                  "beliefs": None, "judgments": [], "places": [], "thought": None, "replace": False})
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
    G's guard beyond sight does not. About two minutes (a `think` waits 45 s from arrival)."""
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
        # Found 2026-11-12: a graph's dodge dashes away from the threat and the body turns with
        # it, so the attacker leaves the field, the routine's condition stops holding and the
        # dodge is broken off (as a `threatened` guard would be): the blow lands.
        s.expect("front (field on): the dodge carries through (known: broken off when the dash turns the back on A)",
                 not dodges[0]["outcome"].startswith("broken off"), {"dodge": dodges[0]["outcome"], "attack": use["outcome"]}, fatal=False, known=True)
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
    Three minded people (`spawn_crowd`, no mind service): an archer shoots a still target 6 m
    off (told "struck …: hit for N" when the arrow lands), a striker beside the target strikes
    it (told "hit for N"), the archer looses at an empty point past its sight (told it came to
    nothing), and with the law off a hit is not told."""
    a, b, c = s.people(3)
    here = body_at(s, a)
    s.call("place_at", b, here[0] + 6.0, here[1])
    s.call("place_at", c, here[0] + 6.0, here[1] + 1.2)
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
    lines = [r for r in s.rows("SELECT observer, kind, text FROM experience", "outcome-lines")
             if r["kind"] == "own" and any(r["text"].startswith(p) for p in ("You finished: bowshot", "You failed to bowshot", "You finished: strike", "You failed to strike"))]
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
    an archer, a target 6 m off with a witness beside it, and a far target 19 m off (past day
    sight, within the bow's 22 m) shot at by a point aim. No line any of them is told about the
    arrows says "attacked", and the unseen shot names no one."""
    a, b, w, f = s.people(4)
    here = body_at(s, a)
    s.call("place_at", b, here[0] + 6.0, here[1])
    s.call("place_at", w, here[0] + 6.0, here[1] + 1.5)
    s.call("place_at", f, here[0] + 19.0, here[1] - 3.0)
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

    s.graph(a, {"seq": [{"do": {"skill": "bowshot", "target": {"at": [here[0] + 19.0, here[1] - 3.0]}}}, {"wait": 60}]})
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


SCENES = {"say": say, "skirmish": skirmish, "infant": infant, "tick": tick, "needs": needs, "seize": seize, "lifecycle": lifecycle, "wildlife": wildlife, "grazing": grazing, "arrival": arrival, "sight": sight, "dealings": dealings, "answers": answers, "flee": flee, "food": food, "refusal": refusal, "teach": teach, "senses": senses, "moves": moves, "remains": remains, "laws": laws, "doing": doing, "death-names": death_names, "drop": drop, "low": drop, "family_laws": family_laws, "fov": fov, "placement": placement, "alarms": alarms, "health_seen": health_seen, "audience": audience, "outcomes": outcomes, "crowd_sight": crowd_sight, "stranger_filter": stranger_filter}


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
SCENES["doing_cost"] = doing_cost
SCENES["owners"] = owners


def main():
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


if __name__ == "__main__":
    raise SystemExit(main())
