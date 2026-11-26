#!/usr/bin/env python3
"""relation-fight's island measurement (free, no model): the island seed, the `relation_fight_on` law
off against on, N worlds each, run side by side for `--minutes` real minutes (12 = 24 game hours at
the island's 12-minute day). Outcome counts only, not timing.

Per world: published fresh from `--wasm` (an island module) on LIVING_STDB_CONTAINER, the law set on
for the `on` arm before anything is read, then polled every `--every` seconds as the owner over
HTTP SQL: `skill_use` (every attacking use by id: attack, strike, shoot, throw, fire_bolt and
threaten; since the second pass every targeted use, by skill, at a hostile or friendly people), `activity` (each flight: a `flee` begun), `vitals` (each wound: a new `hurt_ms` with a
lower health), `character` (deaths). At the start: memberships, communities and the regard records
(holder, toward, label, value), so each attack's target is classed as of a people the attacker's
people hold as an enemy (value <= -25 or rival/enemy/threat/foe in the label: "rival town",
"outlaws"), or not. At the end: the chronicle's kinds, then the world is paused, read back paused and
deleted (world_delete.py).

    island_fight.py --wasm FILE --worlds 3 --minutes 12 --out DIR

Writes DIR/<arm>-<n>/{start.json,events.jsonl,end.json} and DIR/summary.json.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import genesis_wait  # noqa: E402
import world_delete  # noqa: E402

STDB = os.environ.get("LIVING_STDB", str(Path(__file__).resolve().parent / "stdb"))
URL = os.environ.get("LIVING_STDB_URL", "").rstrip("/")
ATTACKS = {"attack", "strike", "shoot", "throw", "fire_bolt", "firebolt", "bowshot", "threaten"}
HOSTILE = ("rival", "enemy", "threat", "foe")


def cli(*args, check=True):
    r = subprocess.run([STDB, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{args[:3]}: {r.stderr[-300:]}")
    return r


def token():
    out = cli("login", "show", "--token").stdout
    return next(l.rsplit(" is ", 1)[1].strip() for l in out.splitlines() if "auth token" in l and " is " in l)


def sql(db, tok, q):
    if not URL:
        raise RuntimeError("set LIVING_STDB_URL to the measurement server")
    req = urllib.request.Request(f"{URL}/v1/database/{db}/sql", data=q.encode(), method="POST", headers={"Authorization": f"Bearer {tok}"})
    res = json.loads(urllib.request.urlopen(req, timeout=60).read())[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def call(db, reducer, *args):
    cli("call", "-s", "local", db, reducer, *[json.dumps(a) for a in args])


def world(arm, n, a, tok, out):
    db = f"verify-isle-{arm}-{n}-{time.strftime('%H%M%S')}"
    d = out / f"{arm}-{n}"
    d.mkdir(parents=True, exist_ok=True)
    cli("publish", "-s", "local", "-b", f"/wasm/{a.wasm}", db, "--delete-data", "-y")
    genesis_wait.wait_ready_cli(lambda *x: cli(*x).stdout, db)
    if arm == "on":
        call(db, "set_world_law", "relation_fight_on", "true")
    deadline = time.monotonic() + a.minutes * 60
    observe(db, arm, tok, d, a.every, lambda: time.monotonic() >= deadline, deadline + a.every)
    deleted, why = world_delete.cli_pause_and_delete(lambda *x: subprocess.run([STDB, *x], capture_output=True, text=True), db)
    (d / "deleted.txt").write_text(f"{db}: {why}\n")


def band(trust, label):
    label = label.lower()
    hostile = trust <= -25 or any(w in label for w in ("enemy", "rival", "threat", "thief", "foe"))
    peaceful = trust >= 25 or any(w in label for w in ("friend", "family", "partner", "ally", "kin"))
    return "hostile" if hostile and not peaceful else "peaceful" if peaceful and not hostile else "neutral"


def exposure_at(db, tok):
    laws = {"world_law": sql(db, tok, "SELECT * FROM world_law"), "law_override": sql(db, tok, "SELECT * FROM law_override")}
    comm = {c["id"]: c["name"] for c in sql(db, tok, "SELECT id, name FROM community")}
    member = {m["member"]: m["community"] for m in sql(db, tok, "SELECT member, community FROM membership")}
    parties = sql(db, tok, "SELECT record, party, role FROM record_party")
    records = {r["id"]: r for r in sql(db, tok, "SELECT id, kind, open, terms FROM record")}
    COMMUNITY = 1 << 40
    hold = {}
    for rid, r in records.items():
        roles = {p["role"]: p["party"] for p in parties if p["record"] == rid}
        if "holder" in roles and "toward" in roles and roles["holder"] >= COMMUNITY and roles["toward"] >= COMMUNITY:
            t = json.loads(r["terms"]) if isinstance(r["terms"], str) else r["terms"]
            if "label" in t:
                hold[(roles["holder"] - COMMUNITY, roles["toward"] - COMMUNITY)] = (t["label"], t.get("value", 0))
    chars = sql(db, tok, "SELECT id, name, kind, alive, stage FROM character")
    residents = {c["id"] for c in chars if c["kind"] == "person" and c["alive"]}
    hostile = lambda a_, b_: (lambda s: s is not None and (s[1] <= -25 or any(w in str(s[0]).lower() for w in HOSTILE)))(hold.get((member.get(a_), member.get(b_))))
    friendly = lambda a_, b_: (lambda s: s is not None and (s[1] >= 25 or any(w in str(s[0]).lower() for w in ("friend", "ally", "kin"))))(hold.get((member.get(a_), member.get(b_))))
    # Exposure: the relation rows held about people of a people one's own holds as an enemy, by
    # how they decide under the law (brain.rs `personal`): hostile, peaceful or neutral.
    pairs = {}
    exposure = {}
    for r in sql(db, tok, "SELECT actor, other, trust, label FROM relation"):
        if hostile(r["actor"], r["other"]):
            k = band(r["trust"], r["label"])
            pairs[(r["actor"], r["other"])] = k
            exposure[k] = exposure.get(k, 0) + 1
    return laws, comm, member, hold, residents, hostile, friendly, pairs, exposure


def observe(db, arm, tok, d, every, finished, deadline, sample=None):
    laws, comm, member, hold, residents, hostile, friendly, _, exposure = exposure_at(db, tok)
    start = {"db": db, "arm": arm, "laws": laws, "communities": comm, "members": len(member), "residents": len(residents),
             "regard": [[comm.get(a_), comm.get(b_), l, v] for (a_, b_), (l, v) in hold.items()],
             "rows_about_hostile_people_by_band": exposure}
    (d / "start.json").write_text(json.dumps(start, indent=1) + "\n")
    seen_use, seen_flee, seen_hurt, hp = {}, set(), set(), {}
    deaths = {}
    with open(d / "events.jsonl", "w") as ev:
        while True:
            t0 = time.time()
            final = finished()
            try:
                for u in sql(db, tok, "SELECT id, actor, target, skill, source, at_ms, accepted_ms, outcome FROM skill_use"):
                    if ((u["target"] or sample and u["skill"] in ATTACKS)
                            and (u["id"] not in seen_use or sample and seen_use[u["id"]] != u["accepted_ms"])):
                        seen_use[u["id"]] = u["accepted_ms"]
                        from_group, to_group = member.get(u["actor"]), member.get(u["target"])
                        regard = hold.get((from_group, to_group))
                        ev.write(json.dumps({"e": "use", "skill": u["skill"], "a": u["actor"], "b": u["target"], "ms": u["accepted_ms"],
                                             "hostile_people": hostile(u["actor"], u["target"]), "friendly_people": friendly(u["actor"], u["target"]),
                                             "resident_target": u["target"] in residents, "source": u["source"],
                                             "attempt_ms": u["at_ms"], "outcome": u["outcome"],
                                             "actor_community": comm.get(from_group), "target_community": comm.get(to_group),
                                             "regard": regard[0] if regard else None}) + "\n")
                for x in sql(db, tok, "SELECT id, victim, started_ms FROM activity WHERE skill = 'flee'"):
                    k = (x["id"], x["started_ms"])
                    if k not in seen_flee:
                        seen_flee.add(k)
                        ev.write(json.dumps({"e": "flee", "a": x["id"], "victim": x["victim"], "ms": x["started_ms"]}) + "\n")
                for v in sql(db, tok, "SELECT id, hp, hurt_ms, hurt_by FROM vitals"):
                    k = (v["id"], v["hurt_ms"])
                    if v["hurt_ms"] and k not in seen_hurt and v["hp"] < hp.get(v["id"], 1e9):
                        seen_hurt.add(k)
                        ev.write(json.dumps({"e": "wound", "a": v["id"], "by": v["hurt_by"], "ms": v["hurt_ms"], "resident": v["id"] in residents,
                                             "hostile_people": hostile(v["hurt_by"], v["id"]) if v["hurt_by"] else False}) + "\n")
                    hp[v["id"]] = v["hp"]
                for c in sql(db, tok, "SELECT id, kind, alive, died_ms, cause FROM character WHERE alive = false"):
                    if c["id"] not in deaths:
                        deaths[c["id"]] = c
                        ev.write(json.dumps({"e": "death", "a": c["id"], "kind": c["kind"], "ms": c["died_ms"], "cause": c["cause"], "resident": c["id"] in residents}) + "\n")
                if sample:
                    sample(ev, final)
            except Exception as e:  # a busy server can refuse one poll; the next one catches up
                ev.write(json.dumps({"e": "poll_error", "why": str(e)[:200], "t": time.time()}) + "\n")
            ev.flush()
            if final:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("observer timed out waiting for runner")
            time.sleep(max(0.0, every - (time.time() - t0)))
    kinds = {}
    for r in sql(db, tok, "SELECT kind, a, b, text FROM chronicle"):
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    clock = sql(db, tok, "SELECT tick, last_ms FROM clock")[0]
    (d / "end.json").write_text(json.dumps({"chronicle_kinds": kinds, "clock": clock}, indent=1) + "\n")


def summarize(out):
    rows = []
    for d in sorted(p for p in out.iterdir() if p.is_dir() and (p / "events.jsonl").exists()):
        ev = [json.loads(l) for l in open(d / "events.jsonl")]
        start = json.loads((d / "start.json").read_text())
        every = [e for e in ev if e["e"] == "use"]
        uses = [e for e in every if e["skill"] in ATTACKS]
        att = [e for e in uses if e["skill"] != "threaten"]
        by_skill = {}
        for e in every:
            b = by_skill.setdefault(e["skill"], {"all": 0, "at_hostile_people": 0, "at_friendly_people": 0})
            b["all"] += 1
            b["at_hostile_people"] += bool(e["hostile_people"])
            b["at_friendly_people"] += bool(e.get("friendly_people"))
        deaths = [e for e in ev if e["e"] == "death"]
        res_deaths = [e for e in deaths if e["resident"]]
        kills = {}
        for e in deaths:
            if e["cause"].startswith("killed by"):
                kills.setdefault(e["cause"], []).append(e["ms"])
        rows.append({"world": d.name, "arm": start["arm"], "residents": start["residents"],
                     "attacks": len(att), "attacks_on_hostile_people": sum(e["hostile_people"] for e in att),
                     "attackers": len({e["a"] for e in att}), "threats": len(uses) - len(att),
                     "threats_on_hostile_people": sum(e["hostile_people"] for e in uses if e["skill"] == "threaten"),
                     "flights": sum(e["e"] == "flee" for e in ev),
                     "wounds": sum(e["e"] == "wound" for e in ev), "resident_wounds": sum(e["e"] == "wound" and e["resident"] for e in ev),
                     "wounds_by_hostile_people": sum(e["e"] == "wound" and e["hostile_people"] for e in ev),
                     "deaths": len(deaths), "resident_deaths": len(res_deaths), "resident_deaths_by_cause": sorted({e["cause"] for e in res_deaths}),
                     "killed": sum(e["cause"].startswith("killed by") for e in deaths),
                     "most_attacks_by_one": max([sum(1 for e in att if e["a"] == x) for x in {e["a"] for e in att}] or [0]),
                     "poll_errors": sum(e["e"] == "poll_error" for e in ev),
                     "targeted_uses_by_skill": by_skill, "exposure": start.get("rows_about_hostile_people_by_band")})
    (out / "summary.json").write_text(json.dumps(rows, indent=1) + "\n")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wasm", required=True)
    ap.add_argument("--worlds", type=int, default=3)
    ap.add_argument("--minutes", type=float, default=12.0)
    ap.add_argument("--every", type=float, default=2.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summarize-only", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if not a.summarize_only:
        tok = token()
        threads = [threading.Thread(target=world, args=(arm, n, a, tok, out)) for n in range(1, a.worlds + 1) for arm in ("off", "on")]
        for t in threads:
            t.start()
            time.sleep(20)  # staggered publishes: genesis is the heavy part
        for t in threads:
            t.join()
    for r in summarize(out):
        print(json.dumps(r))


if __name__ == "__main__":
    main()
