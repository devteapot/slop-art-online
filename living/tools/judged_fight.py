#!/usr/bin/env python3
"""Does a cached Jev judgment change how a fight ends? (docs/MIND_HARNESS.md, item 4)

  living/tools/judged_fight.py --tag T [--arms none fake real] [--seconds 120] [--repeats 1]

Each arm is a fresh `verify-jev-<tag>-<arm>-<n>` database (seed world) with the same scene:
`--attackers` residents (1) each strike a defender every two seconds (admin `set_behavior`); the
defender, thought for by a mind service (`LIVING_ONLY`), runs one fixed graph:

    first: [ if judged fight_risk > 0.6 (else no) -> flee from the attacker,
             if hurt within 10 s -> strike back,
             wait ]

Its own model calls go to a fake server whose compile keeps that graph, so only the judgment
differs between arms: `none` (LIVING_JEV off: the judgment never exists, the fallback holds),
`fake` (the fake Jev: risk = how hurt it is) and `real` (TypeSafe's Jev, paid; key from
TYPESAFE_API_KEY). Samples health, activity and distance every second until the defender
dies or `--seconds` pass. Evidence: `.local/living/verify/jev-<tag>-<arm>-<n>/` and
`.local/living/jev/<tag>/report.{json,md}`.
"""
import argparse
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / ".agents/skills/verify/scripts/verify.py"
FAKE = ROOT / ".agents/skills/verify-llm/scripts/fake_llm.py"
STDB = ROOT / "living/tools/stdb"
MIND = Path(os.environ.get("LIVING_MIND_BIN") or Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "living/target") / "release/living-mind")
OUT = ROOT / ".local/living/jev"
STDB_URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300")
# A desires top level: the mind's needs repair (`keep_needs`) leaves it as it is, and the
# fake compile's "keep" carries it on.
DEFENDER_GRAPH = {"desires": [{"want": "this fight", "weight": {"base": 1.0}, "do": {"first": [
    {"if": {"cond": {"judged": {"q": "fight_risk", "above": 0.6}}, "then": {"do": {"skill": "flee", "target": "attacker"}}}},
    {"if": {"cond": {"hurt_within": 10}}, "then": {"do": {"skill": "strike", "target": "attacker"}}},
    {"wait": 1}]}}]}


def sh(args, **kw):
    return subprocess.run([str(a) for a in args], cwd=ROOT, capture_output=True, text=True, **kw)


def harness(run, *args):
    r = sh([VERIFY, args[0], "--run", run, *args[1:]], timeout=900)
    if r.returncode:
        raise RuntimeError(f"verify.py {args[0]} {run}: {r.stderr[-2000:]}{r.stdout[-2000:]}")
    return r.stdout


def sql(run, q):
    return json.loads(harness(run, "sql", q))


def admin(run, reducer, *args):
    r = sh([STDB, "call", "-s", "local", f"verify-{run}", reducer, *[json.dumps(a) for a in args]], timeout=60)
    if r.returncode:
        raise RuntimeError(f"{reducer}: {r.stderr[-500:]}")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def token():
    r = sh([STDB, "login", "show", "--token"], timeout=30)
    return re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", r.stdout)[0]


def one(a, arm, n, tok):
    run = f"jev-{a.tag}-{arm}-{n}"
    d = ROOT / ".local/living/verify" / run
    harness(run, "launch")
    harness(run, "doctor")
    people = [p for p in sql(run, "SELECT id, name, stage, alive FROM character WHERE kind = 'person'") if p["alive"] and p["stage"] == 2]
    people.sort(key=lambda p: p["id"])
    defender, attacker = people[0]["id"], [p["id"] for p in people[1:1 + a.attackers]]
    procs = []
    samples = []
    try:
        return fight(a, arm, n, tok, run, d, defender, attacker, procs, samples)
    finally:
        for p in reversed(procs):
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        journal = ROOT / ".local/living/journal" / f"verify-{run}"
        if journal.exists():
            shutil.copytree(journal, d / "journal", dirs_exist_ok=True)
            shutil.rmtree(journal)
        harness(run, "cleanup")


def fight(a, arm, n, tok, run, d, defender, attacker, procs, samples):
    me = sql(run, f"SELECT x, y FROM body WHERE id = {defender}")[0]
    x, y = me["x"], me["y"]
    port = free_port()
    script = {"replies": {"deliberate": {"thought": "I hold to my way of fighting.", "graph": "keep"},
                          "think": {"thought": "I hold to my way of fighting.", "intend": [], "say": None}}}
    (d / "fake-script.json").write_text(json.dumps(script))
    log = (d / "fake-server.log").open("w")
    procs.append(subprocess.Popen([sys.executable, str(FAKE), "--port", str(port), "--log", str(d / "fake-requests.jsonl"), "--script", str(d / "fake-script.json")], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT))
    time.sleep(1.5)
    models = {"default": "fake", "profiles": {"fake": {"base_url": f"http://127.0.0.1:{port}/v1", "model": "fake-person", "key_env": "LIVING_VERIFY_FAKE_KEY", "max_tokens": 1024, "requests_per_minute": 6000}}}
    (d / "models.json").write_text(json.dumps(models))
    env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=STDB_URL, LIVING_DB=f"verify-{run}", LIVING_RUN=f"verify-{run}", LIVING_SEED="world",
               LIVING_MODELS=str(d / "models.json"), LIVING_NEO4J="off", LIVING_NEO4J_PASSWORD="", LIVING_ONLY=str(defender), LIVING_LLM_PER_MIN="0",
               LIVING_CONCURRENCY="4", LIVING_TOKEN=tok, LIVING_VERIFY_FAKE_KEY="local-only", LIVING_LOD="0", LIVING_PLAYER_MEMORY="0",
               LIVING_JEV="0" if arm == "none" else "1", NO_PROXY="127.0.0.1,localhost", RUST_LOG="info,neo4rs=warn,spacetimedb_sdk=warn")
    if arm == "fake":
        env["LIVING_JEV_URL"] = f"http://127.0.0.1:{port}/v1/systemone"
        env["TYPESAFE_API_KEY"] = "fake-only"
    mlog = (d / "mind.log").open("w")
    procs.append(subprocess.Popen([str(MIND)], cwd=ROOT, env=env, stdout=mlog, stderr=subprocess.STDOUT))
    if True:
        for _ in range(60):
            if "world subscribed" in (d / "mind.log").read_text():
                break
            time.sleep(1)
        time.sleep(3)
        admin(run, "place_at", defender, x, y)
        for i, att in enumerate(attacker):
            ang = 2 * math.pi * i / len(attacker)
            admin(run, "place_at", att, x + 1.3 * math.cos(ang), y + 1.3 * math.sin(ang))
        admin(run, "set_behavior", defender, json.dumps(DEFENDER_GRAPH))
        for att in attacker:
            admin(run, "set_behavior", att, json.dumps({"desires": [{"want": "this fight", "weight": {"base": 1.0}, "do": {"seq": [{"do": {"skill": "strike", "target": {"id": defender}}}, {"wait": 2}]}}]}))
        time.sleep(2)
        admin(run, "set_behavior", defender, json.dumps(DEFENDER_GRAPH))
        t0 = time.time()
        while time.time() - t0 < a.seconds:
            ids = " OR ".join(f"id = {i}" for i in [defender, *attacker])
            rows = {r["id"]: r for r in sql(run, f"SELECT id, alive FROM character WHERE {ids}")}
            vit = {r["id"]: r for r in sql(run, f"SELECT id, hp, max_hp FROM vitals WHERE {ids}")}
            bodies = {r["id"]: r for r in sql(run, f"SELECT id, x, y FROM body WHERE {ids}")}
            act = {r["id"]: r for r in sql(run, f"SELECT id, label FROM activity WHERE {ids}")}
            near = [math.dist((bodies[defender]["x"], bodies[defender]["y"]), (bodies[i]["x"], bodies[i]["y"])) for i in attacker if i in bodies and defender in bodies]
            dist = min(near) if near else None
            s = {"t": round(time.time() - t0, 1), "alive": rows.get(defender, {}).get("alive", False), "hp": vit.get(defender, {}).get("hp"),
                 "attackers_alive": sum(rows.get(i, {}).get("alive", False) for i in attacker), "doing": act.get(defender, {}).get("label"), "attackers_doing": [act.get(i, {}).get("label") for i in attacker], "dist": round(dist, 1) if dist is not None else None}
            samples.append(s)
            if not s["alive"]:
                break
            time.sleep(1)
        (d / "samples.json").write_text(json.dumps(samples, indent=1))
        (d / "brain-end.json").write_text(json.dumps(sql(run, f"SELECT graph, plan, source FROM brain WHERE id = {defender}")))
        (d / "judged.json").write_text(json.dumps(sql(run, f"SELECT * FROM judged WHERE actor = {defender}")))
        (d / "thoughts.json").write_text(json.dumps(sql(run, f"SELECT kind, summary FROM thought WHERE actor = {defender}")))
    for p in reversed(procs):
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    journal = ROOT / ".local/living/journal" / f"verify-{run}"
    if journal.exists():
        shutil.copytree(journal, d / "journal", dirs_exist_ok=True)
        shutil.rmtree(journal)
    ex = [json.loads(l) for p in (d / "journal").glob("*.jsonl") for l in p.read_text().splitlines() if l.strip()] if (d / "journal").exists() else []
    judge = [e for e in ex if e["purpose"] == "judge"]
    lat = sorted(e["latency_ms"] for e in judge if not e.get("error"))
    fled = next((s["t"] for s in samples if s["doing"] and "flee" in s["doing"].lower()), None)
    died = next((s["t"] for s in samples if not s["alive"]), None)
    first_risk = next((e["at_ms"] for e in judge if any(j["value"] > 0.6 for j in e.get("judged", []))), None)
    return {"arm": arm, "n": n, "run": run, "survived": died is None, "died_at_s": died, "first_flee_s": fled, "end_hp": samples[-1]["hp"] if samples else None,
            "min_dist": min((s["dist"] for s in samples if s["dist"] is not None), default=None), "end_dist": samples[-1]["dist"] if samples else None,
            "judgments": len(judge), "judge_errors": sum(bool(e.get("error")) for e in judge),
            "latency_ms_p50": lat[len(lat) // 2] if lat else None, "latency_ms_p95": lat[int(len(lat) * 0.95)] if lat else None,
            "input_tokens": sum(e.get("prompt_tokens") or 0 for e in judge), "cost_usd": round(sum(e.get("cost_usd") or 0 for e in judge), 6),
            "values": [j["value"] for e in judge for j in e.get("judged", [])], "first_risk_above_0.6": first_risk is not None}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--arms", nargs="+", default=["none", "fake"], choices=["none", "fake", "real"])
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--attackers", type=int, default=1)
    a = ap.parse_args()
    if "real" in a.arms and not os.environ.get("TYPESAFE_API_KEY"):
        sys.exit("the real arm needs TYPESAFE_API_KEY")
    out = OUT / a.tag
    out.mkdir(parents=True, exist_ok=True)
    tok = token()
    results = []
    for n in range(a.repeats):
        for arm in a.arms:
            r = one(a, arm, n, tok)
            print(json.dumps(r), flush=True)
            results.append(r)
            (out / "report.json").write_text(json.dumps(results, indent=2))
    cols = ["arm", "n", "survived", "died_at_s", "first_flee_s", "end_hp", "end_dist", "judgments", "judge_errors", "latency_ms_p50", "latency_ms_p95", "input_tokens", "cost_usd"]
    md = "| " + " | ".join(cols) + " |\n|" + " --- |" * len(cols) + "\n" + "".join("| " + " | ".join(str(r[c]) for c in cols) + " |\n" for r in results)
    (out / "report.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
