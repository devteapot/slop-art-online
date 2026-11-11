#!/usr/bin/env python3
"""Residents of a seeded island know their own past and people (docs/SEEDED_LIVES.md).

On an island run (`verify.py launch --run RUN --seed island`) every resident has a mind from
the start. The running `living-mind` (LIVING_ONLY naming the residents under test) installs
each one's world facts and authored sheet (no model call) into a scratch Neo4j at start, and
thinks and talks for it. A player then speaks to each named resident in turn, and the driver
reads what each mind was given and what it said.

    lives_mind.py --run RUN --who "Wat Fenner=What do you make of Kettlebridge folk?" \\
        --who "Hester Crane=What do people here say about Brackenford?" [--real deepseek-flash]

Free tier (default): a local fake model (`verify-llm/scripts/fake_llm.py`); the checks are on the
prompts. With `--real PROFILE` (paid: only when authorized), the profile answers every purpose
and the replies are recorded for reading; the same prompt checks run.

Checks per resident: an AI character under the world admin before anyone engages it; its
`relation` rows match its sheet; the people it knows by name are introduced (`acquaintance`) and one it
does not (`knows_name: false`) stays "a stranger" in its mind; its persona is its authored
narrative; its first prompt carries its narrative, people from its sheet and its authored
memories (`[before all this]`); every seeded situation it is in (`cast/*.json`) shows in that
prompt through the other people in it it knows by name; its mind marks the sheet `authored`
and its world facts `world`; its consolidations see its identity; its own secret
reaches only its own prompts ("Known only to you"), and no other resident's secret reaches it.

Evidence: `.local/living/verify/RUN/lives-mind/` (prompts, replies, rows, mind log, journal).
Stops the mind and the fake model and removes the scratch Neo4j container in `finally`.
"""

import argparse
import importlib.util
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("verify", ROOT / ".agents/skills/verify/scripts/verify.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
FAKE = ROOT / ".agents/skills/verify-llm/scripts/fake_llm.py"
NEO4J_IMAGE = "docker.io/library/neo4j:2026.09.0"
MIND = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "living/target") / "release/living-mind"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def env_file():
    vals = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"')
    return vals


class Lab:
    def __init__(self, run):
        self.run = run
        self.st = V.load(run)
        self.db = self.st["db"]
        self.dir = V.run_dir(run) / "lives-mind"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.token = V.admin_token()
        self.procs = []
        self.container = None
        self.results = []

    def sql(self, q):
        code, body = V.http(f"/v1/database/{self.db}/sql", q, self.token, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q}: {code} {body}")
        res = json.loads(body)[-1]
        names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def harness(self, *args):
        r = subprocess.run([sys.executable, str(ROOT / ".agents/skills/verify/scripts/verify.py"), args[0], "--run", self.run, *args[1:]], cwd=ROOT, capture_output=True, text=True, timeout=120)
        (self.dir / "harness.log").open("a").write(f"$ {args}\n{r.stdout}\n{r.stderr}\n")
        if r.returncode != 0:
            raise RuntimeError(f"harness {args}: {r.stderr.strip()[-400:]}")
        return r.stdout

    def admin(self, reducer, *args):
        code, body = V.http(f"/v1/database/{self.db}/call/{reducer}", list(args), self.token)
        if code != 200:
            raise RuntimeError(f"{reducer}{args}: {code} {body}")

    def check(self, name, ok, detail):
        self.results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)

    def wait(self, f, what, secs):
        end = time.time() + secs
        while time.time() < end:
            v = f()
            if v:
                return v
            time.sleep(1)
        raise RuntimeError(f"timed out waiting for {what}")

    def start_neo4j(self):
        self.container = f"lives-neo4j-{self.run}"
        self.port = free_port()
        self.password = secrets.token_hex(12)
        subprocess.run(["docker", "run", "-d", "--name", self.container, "-p", f"127.0.0.1:{self.port}:7687", "-e", f"NEO4J_AUTH=neo4j/{self.password}", NEO4J_IMAGE], check=True, capture_output=True)
        cy = ["docker", "exec", self.container, "cypher-shell", "-a", "bolt://localhost:7687", "-u", "neo4j", "-p", self.password, "RETURN 1;"]
        self.wait(lambda: subprocess.run(cy, capture_output=True).returncode == 0, "scratch Neo4j", 180)

    def models(self, real):
        if real:
            m = json.loads((ROOT / "living/configs/models.json").read_text())
            for k in ("groups", "assign", "rotate", "stages"):
                m.pop(k, None)
            m["default"] = real
            path = self.dir / "models.json"
            path.write_text(json.dumps(m, indent=2))
            return path, {}
        script = {"replies": {"think": {"thought": "lives fake think", "intend": ["wait"], "say": "lives fake answer"},
                              "deliberate": {"thought": "lives fake", "plan": "lives fake wait", "graph": {"wait": 60}, "say": None, "acts": []},
                              "talk": {"thought": "lives fake talk", "say": "lives fake talk answer", "end": False}}}
        (self.dir / "fake-script.json").write_text(json.dumps(script, indent=2))
        log = (self.dir / "fake.log").open("w")
        p = subprocess.Popen([sys.executable, str(FAKE), "--port", "0", "--log", str(self.dir / "requests.jsonl"), "--script", str(self.dir / "fake-script.json")], stdout=log, stderr=subprocess.STDOUT)
        self.procs.append(p)
        port = int(self.wait(lambda: re.search(r"READY http://127.0.0.1:(\d+)/v1", (self.dir / "fake.log").read_text()), "fake model", 15)[1])
        m = {"default": "fake", "profiles": {"fake": {"base_url": f"http://127.0.0.1:{port}/v1", "model": "lives-fake", "key_env": "LIVING_VERIFY_FAKE_KEY", "max_tokens": 2048,
             "reasoning_effort": {p: p for p in ("think", "deliberate", "consolidate", "talk")}}}}
        path = self.dir / "models.json"
        path.write_text(json.dumps(m, indent=2))
        return path, {"LIVING_VERIFY_FAKE_KEY": "local-only"}

    def start_mind(self, models, extra, ids):
        env = dict(os.environ, **env_file())
        env.update(extra)
        env.update(LIVING_ROOT=str(ROOT), LIVING_SERVER=V.URL, LIVING_DB=self.db, LIVING_RUN=self.db, LIVING_SEED="island", LIVING_MODELS=str(models),
                   LIVING_ONLY=",".join(map(str, ids)), LIVING_TOKEN=self.token, LIVING_NEO4J="on", LIVING_NEO4J_URI=f"127.0.0.1:{self.port}",
                   LIVING_NEO4J_PASSWORD=self.password, LIVING_LLM_PER_MIN="0", LIVING_CONCURRENCY="4", LIVING_LOD="0", NO_PROXY="127.0.0.1,localhost",
                   RUST_LOG="info,neo4rs=warn,spacetimedb_sdk=warn")
        self.journal = ROOT / ".local/living/journal" / self.db
        log = (self.dir / "mind.log").open("w")
        p = subprocess.Popen([str(MIND)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        self.procs.append(p)
        self.wait(lambda: "world subscribed:" in (self.dir / "mind.log").read_text(), "mind subscription", 120)

    def cypher(self, q):
        r = subprocess.run(["docker", "exec", self.container, "cypher-shell", "-a", "bolt://localhost:7687", "-u", "neo4j", "-p", self.password, "--format", "plain", q], capture_output=True, text=True)
        return [l for l in r.stdout.splitlines()[1:] if l.strip()]

    def exchanges(self, name):
        f = self.journal / f"{re.sub(r'[^0-9A-Za-z]', '_', name)}.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []

    def cleanup(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
        if self.journal and self.journal.exists():
            shutil.copytree(self.journal, self.dir / "journal", dirs_exist_ok=True)
        if self.container:
            subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)


def text_of(entry):
    """The prompt messages of a journal entry, as one string."""
    req = entry.get("request") or entry.get("body") or {}
    msgs = req.get("messages") if isinstance(req, dict) else None
    if msgs:
        return "\n".join(m.get("content", "") if isinstance(m.get("content"), str) else json.dumps(m.get("content")) for m in msgs)
    return json.dumps(entry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--who", action="append", required=True, help='"Name=line to say"')
    ap.add_argument("--real", default="")
    ap.add_argument("--secs", type=int, default=150)
    a = ap.parse_args()
    lab = Lab(a.run)
    lab.journal = None
    seed = json.loads((ROOT / "living/seeds/island.json").read_text())
    authored = {r["name"]: r for t in seed.get("towns", []) + seed.get("villages", []) for r in t.get("residents", [])}
    secrets_of = {n: r["sheet"].get("secret", "") for n, r in authored.items() if r.get("sheet", {}).get("secret")}
    situations = [x for f in sorted((ROOT / "living/seeds/worlds/island/cast").glob("*.json")) for x in json.loads(f.read_text()).get("situations", [])]
    who = [w.split("=", 1) for w in a.who]
    out = {}
    try:
        people = {c["name"]: c for c in lab.sql("SELECT * FROM character WHERE kind = 'person'") if c["alive"]}
        ids = [people[n]["id"] for n, _ in who]
        lab.start_neo4j()
        models, extra = lab.models(a.real)
        lab.start_mind(models, extra, ids)
        admin = lab.sql("SELECT * FROM world")[0]["admin"]
        lab.harness("player", "join", "LivesVisitor")
        me = lab.sql("SELECT id FROM character WHERE name = 'LivesVisitor'")[0]["id"]
        for (name, line), rid in zip(who, ids):
            sheet = authored[name]["sheet"]
            rel_before = lab.sql(f"SELECT * FROM relation WHERE actor = {rid}")
            char = lab.sql(f"SELECT * FROM character WHERE id = {rid}")[0]
            lab.admin("place_near", me, rid)
            time.sleep(1.5)
            lab.harness("player", "say", line, "--to", str(rid))
            # A mind already living answers a line in a talk turn, whose prompt shows the
            # conversation; its whole circle shows when it deliberates. Ask for one (an admin
            # scene call, as verify_minds.py does).
            time.sleep(3)
            lab.admin("set_behavior", rid, json.dumps({"think": "A quiet moment to take stock of how things are going. lives check"}))
            ex = lab.wait(lambda: [e for e in lab.exchanges(name) if e.get("purpose") in ("think", "deliberate") and (e.get("reply") or e.get("response"))], f"{name}'s first deliberation", a.secs)
            # Let a talk turn or two land.
            time.sleep(20 if a.real else 6)
            ex = lab.exchanges(name)
            prompts = [text_of(e) for e in ex]
            # The first prompt a person deliberates with (a talk turn or a consolidation may come first).
            first = next((text_of(e) for e in ex if e.get("purpose") in ("think", "deliberate")), "")
            heard = [e["text"] for e in lab.sql(f"SELECT * FROM experience WHERE observer = {me}") if e["subject"] == rid]
            persona = lab.sql(f"SELECT * FROM persona WHERE id = {rid}")
            names_in_sheet = [r["name"] for r in sheet["relations"]]
            named = [n for n in names_in_sheet if n in first]
            authored_mems = first.count("[before all this]")
            others = {n: s for n, s in secrets_of.items() if n != name}
            leaked = [n for n, s in others.items() if s[:60] in "\n".join(prompts)]
            own = secrets_of.get(name, "")
            rec = {"name": name, "id": rid, "line": line, "ai_before_engaged": char["ai"], "relations_before_engaged": [{k: r[k] for k in ("other", "trust", "affinity", "label")} for r in rel_before],
                   "persona": persona[0]["narrative"] if persona else None, "sheet_narrative": sheet["narrative"], "people_named_in_first_prompt": named,
                   "authored_memories_in_first_prompt": authored_mems, "heard_by_player": heard, "exchanges": [{"purpose": e.get("purpose"), "reply": e.get("reply") or e.get("response")} for e in ex]}
            (lab.dir / f"{re.sub(r'[^0-9A-Za-z]', '_', name)}-first-prompt.txt").write_text(first)
            out[name] = rec
            lab.check(f"{name} is a mind before anyone engages it", char["ai"] and char["controller"] == admin, json.dumps({"ai": char["ai"], "controller_is_admin": char["controller"] == admin}))
            lab.check(f"{name}'s relations are rows from world creation", len(rel_before) >= len(names_in_sheet) * 0.8, f"{len(rel_before)} rows, {len(names_in_sheet)} in the sheet")
            # The identity installed at start is the sheet's (a later consolidation may revise
            # the persona row: that is the mind's to do, and is reported, not checked).
            installed = [t for t in lab.sql(f"SELECT * FROM thought WHERE actor = {rid}") if t["summary"] == "Who I am (authored)."]
            narrative = json.loads(installed[0]["detail"]).get("narrative", "") if installed else ""
            lab.check(f"{name} began as its authored self", narrative.strip() == sheet["narrative"].strip(), narrative[:120] or "no authored install")
            rec["persona_now"] = persona[0]["narrative"] if persona else None
            lab.check(f"{name} knows its people", len(named) >= min(3, len(names_in_sheet)), f"{len(named)} of {len(names_in_sheet)} sheet people named in its first prompt: {named[:8]}")
            lab.check(f"{name} knows its past", authored_mems >= 1, f"{authored_mems} authored memories recalled in its first prompt")
            lab.check(f"{name} holds no one else's secret", not leaked, f"other residents' secrets in its prompts: {leaked}")
            # Names: introductions at world creation, and who stays a stranger in its mind.
            acq = {a["known"] for a in lab.sql(f"SELECT * FROM acquaintance WHERE observer = {rid}")}
            ids = {c["name"]: c["id"] for c in lab.sql("SELECT id, name FROM character WHERE kind = 'person'")}
            unnamed = [x["name"] for x in sheet["relations"] if x.get("knows_name") is False and x["name"] in ids]
            mind_names = {}
            for x in unnamed:
                rows = lab.cypher(f"MATCH (n {{run: '{lab.db}', actor: {rid}, key: 'person:{ids[x]}'}}) RETURN n.name")
                mind_names[x] = rows[0].strip('"') if rows else None
            lab.check(f"{name}: who it does not know by name stays a stranger", all(ids[x] not in acq for x in unnamed) and all(v in (None, "a stranger") for v in mind_names.values()), f"{len(unnamed)} not known by name, in its mind as {mind_names}; {len(acq)} introductions")
            # Source marks in its mind.
            marks = {}
            for l in lab.cypher(f"MATCH (n {{run: '{lab.db}', actor: {rid}}}) WHERE n.lived_under IS NOT NULL UNWIND n.lived_under AS l RETURN l, count(*)") + lab.cypher(f"MATCH ({{run: '{lab.db}', actor: {rid}}})-[r]->() WHERE r.lived_under IS NOT NULL UNWIND r.lived_under AS l RETURN l, count(*)"):
                k, _, v = l.rpartition(",")
                marks[k.strip().strip('"')] = marks.get(k.strip().strip('"'), 0) + int(v)
            lab.check(f"{name}'s mind marks its sources", marks.get("authored", 0) > 0 and marks.get("world", 0) > 0, json.dumps(marks))
            rec["marks"] = marks
            rec["not_known_by_name"] = mind_names
            # Its seeded situations, through the people in them it knows by name.
            mine_s = [x for x in situations if name in x["people"]]
            seen = []
            for x in mine_s:
                named = [q for q in x["people"] if q != name and q in first]
                seen.append({"id": x["id"], "summary": x["summary"], "side": x["sides"].get(name, ""), "named_in_prompt": named})
            rec["situations"] = seen
            lab.check(f"{name} is in its seeded situations", mine_s and all(z["named_in_prompt"] for z in seen), json.dumps([(z["id"], z["named_in_prompt"]) for z in seen]))
            # Consolidation: never shown an empty identity; when it rewrites the identity (the
            # identity sentence: wants follow the life lived), what became of the seeded wants
            # and the situations is recorded for reading.
            consol = [e for e in ex if e.get("purpose") == "consolidate"]
            blind = [i for i, e in enumerate(consol) if "(no persona yet)" in text_of(e)]
            lab.check(f"{name}'s consolidations see its identity", not blind, f"{len(consol)} consolidations, {len(blind)} shown no identity")
            rewrites = []
            for e in consol:
                r = e.get("reply") or e.get("response")
                try:
                    r = json.loads(r) if isinstance(r, str) else r
                except ValueError:
                    continue
                idn = (r or {}).get("identity") if isinstance(r, dict) else None
                if idn:
                    rewrites.append({"goals": idn.get("goals"), "values": idn.get("values"), "narrative": idn.get("narrative"), "why": idn.get("why")})
            rec["seeded_goals"] = sheet.get("goals", [])
            rec["identity_rewrites"] = rewrites
            if own:
                lab.check(f"{name}'s own secret only in its own prompt", own[:60] in "\n".join(prompts), own[:80])
            print(f"  {name} heard by the player: {heard[-3:]}", flush=True)
        (lab.dir / "lives.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    finally:
        lab.cleanup()
        (lab.dir / "checks.json").write_text(json.dumps(lab.results, indent=1) + "\n")
    failed = [r for r in lab.results if not r["ok"]]
    print(f"{len(lab.results) - len(failed)} of {len(lab.results)} checks pass")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
