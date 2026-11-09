#!/usr/bin/env python3
"""Trials: one real mind in a scripted world (docs/TRIALS.md).

A trial file (living/trials/<name>.json) names a world seed, the one mind-backed subject,
a scripted cast and a timeline. `run` publishes one scratch database per trial x variant x
replicate on the trial SpacetimeDB service, starts one living-mind per database with
LIVING_ONLY=<subject>, drives the timeline through admin and mind reducers, samples the
subject's rows, and stops at the trial's duration, its token cap or the batch's total cap.

  trials.py up                          start or create the trial SpacetimeDB and Neo4j containers
  trials.py down                        stop them (SIGINT; containers and volumes kept)
  trials.py build TRIAL...              build living-mind and one module per trial world
  trials.py run --batch B TRIAL... [--variants default,...] [--replicates 3] [--minutes M]
                [--fake] [--parallel N] [--keep-db]
  trials.py report --batch B            per-instance summaries and the comparison table
  trials.py clean --batch B             delete the batch's databases and Neo4j minds (evidence kept)
  trials.py ledger                      real tokens spent per batch against the total cap

Defaults are the Spark setup: container slop-trials-stdb on 127.0.0.1:3320 and Neo4j
slop-trials-neo4j on 127.0.0.1:7699 (TRIALS_STDB_CONTAINER, TRIALS_STDB_PORT,
TRIALS_NEO4J_CONTAINER, TRIALS_NEO4J_PORT). Databases are always `verify-trial-<batch>-...`;
the runner never publishes or deletes anything else. Evidence: .local/living/trials/<batch>/.
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRIALS = ROOT / "living/trials"
OUT = ROOT / ".local/living/trials"
CONTAINER = os.environ.get("TRIALS_STDB_CONTAINER", "slop-trials-stdb")
PORT = int(os.environ.get("TRIALS_STDB_PORT", "3320"))
URL = f"http://127.0.0.1:{PORT}"
NEO4J = os.environ.get("TRIALS_NEO4J_CONTAINER", "slop-trials-neo4j")
NEO4J_PORT = int(os.environ.get("TRIALS_NEO4J_PORT", "7699"))
TARGET = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "living/target")
IMAGE_STDB = "clockworklabs/spacetime:v2.14.1"
IMAGE_NEO4J = "neo4j:2026.10.1"
# Services that hold other people's worlds. The runner never addresses them.
PROTECTED = {"sao-living_spacetimedb_1", "sao-living-neo4j-1"}
PREFIX = "verify-trial-"
TOTAL_CAP = int(os.environ.get("TRIALS_TOTAL_TOKENS", "6000000"))
FAKE = ROOT / ".agents/skills/verify-llm/scripts/fake_llm.py"
FOOD = {"berries", "meat", "fish", "cooked_meat", "cooked_fish", "smoked_meat", "smoked_fish", "bread"}
SAMPLE_S = 2.0
LEDGER = OUT / "ledger.json"
_lock = threading.Lock()


# ---- small helpers ---------------------------------------------------------------------

def sh(*args, check=True, timeout=600, **kw):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args[:4]))} failed: {(r.stderr or r.stdout).strip()[-2000:]}")
    return r


def http(path, body=None, token=None, raw=False, timeout=30, method=None):
    data = None if body is None else (body.encode() if raw else json.dumps(body).encode())
    req = urllib.request.Request(URL + path, data=data, method=method or ("POST" if data is not None else "GET"))
    if not raw:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)


# Values under these keys replace the base's value as a whole when a trial extends another
# (a pick, a graph or a sheet is one thing, not a set of fields to merge).
REPLACE = {"pick", "graph", "sheet", "rules", "to", "act", "items"}


def deep_merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = deep_merge(base.get(k), v) if k in base and k not in REPLACE else v
        return out
    return over


def guard():
    if CONTAINER in PROTECTED or NEO4J in PROTECTED:
        sys.exit(f"refusing: {CONTAINER}/{NEO4J} belong to other worlds; trials use their own containers")


def docker_state(name):
    r = sh("docker", "inspect", name, "--format", "{{.State.Status}}", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def admin_token():
    """The trial server's in-container CLI identity (the world admin). Kept in memory only."""
    out = sh("docker", "exec", CONTAINER, "spacetime", "login", "show", "--token").stdout
    m = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", out)
    if len(m) != 1:
        raise RuntimeError("could not read one admin token from the trial container's CLI")
    return m[0]


def neo4j_password():
    p = OUT / "neo4j.env"
    for line in p.read_text().splitlines():
        if line.startswith("LIVING_NEO4J_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"no password in {p}")


def load_trial(name):
    path = TRIALS / f"{name}.json"
    t = json.loads(path.read_text())
    if "extends" in t:
        base = load_trial(t.pop("extends"))
        # Lists (the timeline) are replaced as a whole; objects are merged.
        t = deep_merge(base, t)
    t["name"] = name
    return t


def variants():
    return json.loads((TRIALS / "variants.json").read_text())


def world_seed(world):
    """A trial world is a seed plus overrides, written as a derived seed the module and the
    mind both read (LIVING_SEED is resolved under living/seeds/, so a relative path works)."""
    base = json.loads((ROOT / "living/seeds" / f"{world['seed']}.json").read_text())
    merged = deep_merge(base, {"rules": world.get("rules", {}), **world.get("overrides", {})})
    text = json.dumps(merged, indent=1)
    name = f"trial-{world['seed']}-{hashlib.sha256(text.encode()).hexdigest()[:8]}"
    path = OUT / "seeds" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return name, os.path.relpath(path.with_suffix(""), ROOT / "living/seeds"), merged


def hour_of(now_ms, w):
    t = max(0, now_ms - w["epoch_ms"]) + w["day_ms"] * 7 // 24
    return (t % w["day_ms"]) / w["day_ms"] * 24.0


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


# ---- services --------------------------------------------------------------------------

def up(_a=None):
    guard()
    (OUT / "wasm").mkdir(parents=True, exist_ok=True)
    os.chmod(OUT / "wasm", 0o755)
    env = OUT / "neo4j.env"
    if not env.exists():
        old = os.umask(0o077)
        env.write_text(f"LIVING_NEO4J_PASSWORD={secrets.token_hex(16)}\n")
        os.umask(old)
    state = docker_state(CONTAINER)
    if state is None:
        sh("docker", "run", "-d", "--name", CONTAINER, "--restart", "no", "--stop-signal", "SIGINT",
           "-p", f"127.0.0.1:{PORT}:3000", "-v", f"{CONTAINER}:/home/spacetime",
           "-v", f"{OUT / 'wasm'}:/wasm:ro", IMAGE_STDB, "start", "--listen-addr", "0.0.0.0:3000")
    elif state != "running":
        sh("docker", "start", CONTAINER)
    for _ in range(90):
        if http("/v1/ping")[0] == 200:
            break
        time.sleep(2)
    else:
        sys.exit(f"{CONTAINER} did not answer {URL}/v1/ping")
    if "not logged in" in sh("docker", "exec", CONTAINER, "spacetime", "login", "show", check=False).stdout.lower():
        sh("docker", "exec", CONTAINER, "spacetime", "server", "set-default", "local")
        sh("docker", "exec", CONTAINER, "spacetime", "login", "--server-issued-login", "local")
    state = docker_state(NEO4J)
    if state is None:
        sh("docker", "run", "-d", "--name", NEO4J, "--restart", "no", "-p", f"127.0.0.1:{NEO4J_PORT}:7687",
           "-e", f"NEO4J_AUTH=neo4j/{neo4j_password()}", "-e", "NEO4J_server_memory_heap_max__size=2G",
           "-e", "NEO4J_server_memory_pagecache_size=1G", "-v", f"{NEO4J}:/data", IMAGE_NEO4J)
    elif state != "running":
        sh("docker", "start", NEO4J)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", NEO4J_PORT), timeout=2).close()
            break
        except OSError:
            time.sleep(2)
    print(f"up: {CONTAINER} {URL} ({sh('docker', 'inspect', CONTAINER, '--format', '{{.Config.Image}}').stdout.strip()}), "
          f"{NEO4J} bolt 127.0.0.1:{NEO4J_PORT}")


def down(_a=None):
    guard()
    live = [d for d in databases() if d.startswith(PREFIX)]
    if live:
        print(f"note: {len(live)} trial databases are still published; they pause with the server")
    for name in (CONTAINER, NEO4J):
        if docker_state(name) == "running":
            if name == CONTAINER:
                sh("docker", "kill", "--signal", "SIGINT", name, check=False)
            sh("docker", "stop", "-t", "60", name, check=False)
            code = sh("docker", "inspect", name, "--format", "{{.State.ExitCode}}").stdout.strip()
            print(f"stopped {name} (exit {code}{', forced by SIGKILL' if code == '137' else ''})")


def databases():
    r = sh("docker", "exec", CONTAINER, "spacetime", "list", check=False)
    return [l.split("|")[0].strip() for l in r.stdout.splitlines() if l.strip().startswith(PREFIX)]


def build(a):
    guard()
    env = dict(os.environ, CARGO_TARGET_DIR=str(TARGET))
    sh("cargo", "build", "--manifest-path", ROOT / "living/Cargo.toml", "-p", "living-mind", "--release", env=env, timeout=3600)
    seeds = {}
    for t in a.trials:
        name, rel, _ = world_seed(load_trial(t)["world"])
        seeds[name] = rel
    for name, rel in seeds.items():
        build_module(name, rel)
    print("built:", TARGET / "release/living-mind", *[OUT / "wasm" / f"{n}.wasm" for n in seeds])


def build_module(name, rel):
    # One target dir for every trial world: a seed change rebuilds only the authority crate.
    env = dict(os.environ, CARGO_TARGET_DIR=str(TARGET / "trials-wasm"), LIVING_SEED=rel)
    sh("cargo", "build", "--manifest-path", ROOT / "living/Cargo.toml", "-p", "living-authority",
       "--target", "wasm32-unknown-unknown", "--release", env=env, timeout=3600)
    out = OUT / "wasm" / f"{name}.wasm"
    shutil.copyfile(TARGET / "trials-wasm/wasm32-unknown-unknown/release/living_authority.wasm", out)
    os.chmod(out, 0o644)


# ---- one trial instance ----------------------------------------------------------------

class Stop(Exception):
    pass


class Instance:
    def __init__(self, batch, trial, variant, rep, opts, shared):
        self.trial, self.variant, self.rep, self.opts, self.shared = trial, variant, rep, opts, shared
        self.name = f"{trial['name']}-{variant}-r{rep}"
        self.db = f"{PREFIX}{batch}-{self.name}"
        self.dir = OUT / batch / self.name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.journal = ROOT / ".local/living/journal" / self.db
        self.roles, self.saved_graphs, self.mind, self.t0 = {}, {}, None, None
        self.cursor = {"thought": 0, "experience": 0, "chronicle": 0}
        self.jpos = {}
        self.tokens = Counter()
        self.calls = Counter()
        self.latency = defaultdict(list)
        self.pending = []
        self.fired = Counter()
        self.status = "starting"
        self.stopped_by = None
        self.last_rows = {}
        self.brain_rev = None
        self.kinds = {}

    # -- plumbing
    def log(self, line):
        with open(self.dir / "actions.log", "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {line}\n")

    def emit(self, name, row):
        with open(self.dir / f"{name}.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")

    def sql(self, query, admin=True):
        code, body = http(f"/v1/database/{self.db}/sql", query, self.shared["token"] if admin else None, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {code}: {body[:400]} ({query[:120]})")
        out = []
        for res in json.loads(body):
            names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
            out.append([dict(zip(names, r)) for r in res["rows"]])
        return out

    def rows(self, query):
        return self.sql(query)[0]

    def call(self, reducer, *args, quiet=False):
        code, body = http(f"/v1/database/{self.db}/call/{reducer}", list(args), self.shared["token"])
        self.log(f"call {reducer}{json.dumps(list(args))[:300]} -> {code} {body.strip()[:200]}")
        if code != 200 and not quiet:
            self.emit("events", {"t": self.t(), "error": f"{reducer}: {code} {body.strip()[:300]}"})
        return code == 200

    def t(self):
        return None if self.t0 is None else round(time.time() - self.t0, 1)

    def now_ms(self):
        return int(time.time() * 1000)

    # -- the world
    def publish(self):
        wasm = self.shared["wasm"][self.trial["name"]]
        sh("docker", "exec", CONTAINER, "spacetime", "publish", "-s", "local", "-b", f"/wasm/{wasm}.wasm", self.db, "--delete-data", "-y", timeout=300)
        self.published = True
        code, body = http(f"/v1/database/{self.db}/call/install_script", [(ROOT / "living/scripts/skills.rhai").read_text()], self.shared["token"])
        if code != 200:
            raise RuntimeError(f"install_script {code}: {body[:300]}")
        self.log(f"published {self.db} from {wasm}.wasm; skills installed")
        end = time.time() + 60
        while time.time() < end:
            st = self.rows("SELECT * FROM stats")
            if st and st[0]["ticks"] > 0:
                break
            time.sleep(1)
        self.world = self.rows("SELECT * FROM world")[0]
        try:
            self.land = next(iter(self.rows("SELECT * FROM land")), None)
        except RuntimeError:
            self.land = None  # a world without the land table (older modules)
        self.log(f"arrival: {(self.land['arrive_x'], self.land['arrive_y']) if self.land else 'none (map centre)'}")

    def pos(self, body):
        dt = min(3.0, max(0.0, (self.now_ms() - body["t_ms"]) / 1000))
        return (body["x"] + body["vx"] * dt, body["y"] + body["vy"] * dt)

    def bodies(self, ids):
        if not ids:
            return {}
        return {b["id"]: self.pos(b) for b in self.rows("SELECT * FROM body WHERE " + " OR ".join(f"id = {i}" for i in ids))}

    # -- choosing who plays whom
    def census(self):
        chars = [c for c in self.rows("SELECT * FROM character WHERE alive = true")]
        bgs = {b["id"]: json.loads(b["text"]) if b["text"].startswith("{") else {} for b in self.rows("SELECT * FROM background")}
        know = Counter(k["actor"] for k in self.rows("SELECT * FROM know_how"))
        knows = defaultdict(set)
        for k in self.rows("SELECT * FROM know_how"):
            knows[k["actor"]].add(k["technique"])
        groups = []
        for c in sorted(chars, key=lambda c: c["id"]):
            g = bgs.get(c["id"], {}).get("town") or bgs.get(c["id"], {}).get("band")
            if g and g not in groups:
                groups.append(g)
        return chars, bgs, know, knows, groups

    def pick(self, spec, taken):
        chars, bgs, know, knows, groups = self.census_cache
        admin = self.world["admin"]
        out = []
        for c in chars:
            bg = bgs.get(c["id"], {})
            if c["id"] in taken or c["kind"] != spec.get("kind", "person"):
                continue
            if spec.get("mindable", True) and not (c["ai"] and c["controller"] == admin):
                continue
            if "stage" in spec and c["stage"] != spec["stage"]:
                continue
            if any(bg.get(k) != v for k, v in spec.get("bg", {}).items()):
                continue
            grp = bg.get("town") or bg.get("band")
            if "group" in spec and (spec["group"] >= len(groups) or grp != groups[spec["group"]]):
                continue
            if "not_group" in spec and spec["not_group"] < len(groups) and grp == groups[spec["not_group"]]:
                continue
            if any(t in knows[c["id"]] for t in spec.get("lacks", [])):
                continue
            out.append(c)
        if spec.get("nearest"):
            at = self.anchor(spec["nearest"])
            pos = self.bodies([c["id"] for c in out])
            out.sort(key=lambda c: (dist(pos.get(c["id"], (1e9, 1e9)), at), c["id"]))
        elif spec.get("fewest_know_how"):
            out.sort(key=lambda c: (know[c["id"]], c["id"]))
        n = spec.get("count", 1)
        if len(out) < n:
            raise RuntimeError(f"pick {spec}: only {len(out)} match")
        return [c["id"] for c in out[:n]]

    def cast(self):
        self.census_cache = self.census()
        taken = set()
        self.roles["subject"] = self.pick(self.trial["subject"]["pick"], taken)[:1]
        taken |= set(self.roles["subject"])
        for role, spec in self.trial.get("cast", {}).items():
            self.roles[role] = self.pick(spec["pick"], taken)
            taken |= set(self.roles[role])
        self.subject = self.roles["subject"][0]
        chars = {c["id"]: c for c in self.census_cache[0]}
        genome = self.rows(f"SELECT * FROM genome WHERE id = {self.subject}")
        self.cast_info = {r: [{"id": i, "name": chars[i]["name"], "kind": chars[i]["kind"], "background": self.census_cache[1].get(i, {})} for i in ids] for r, ids in self.roles.items()}
        (self.dir / "cast.json").write_text(json.dumps({"roles": self.cast_info, "subject_genome": genome}, indent=1))
        self.log("cast: " + ", ".join(f"{r}={[chars[i]['name'] + '#' + str(i) for i in ids]}" for r, ids in self.roles.items()))

    def anchor(self, a, member=0):
        w, h = self.world["width"], self.world["height"]
        if "xy" in a:
            p = tuple(a["xy"])
        elif a.get("arrival"):
            p = (self.land["arrive_x"], self.land["arrive_y"]) if self.land else (w / 2, h / 2)
        elif "group" in a or "town" in a:
            # A settlement's centre as its residents know it (town_center, a band's camp),
            # else the middle of their homes.
            chars, bgs, *_ , groups = self.census_cache
            name = a["town"] if "town" in a else groups[a["group"]]
            ids = [c for c in chars if (bgs.get(c["id"], {}).get("town") or bgs.get(c["id"], {}).get("band")) == name]
            centre = next((bgs[c["id"]].get("town_center") or bgs[c["id"]].get("camp") for c in ids if bgs.get(c["id"], {}).get("town_center") or bgs.get(c["id"], {}).get("camp")), None)
            homes = [(c["home_x"], c["home_y"]) for c in ids if c["home_x"] or c["home_y"]]
            p = tuple(centre) if centre else (sum(x for x, _ in homes) / len(homes), sum(y for _, y in homes) / len(homes))
        elif "who" in a:
            ids = self.roles[a["who"]]
            p = self.bodies(ids[:1])[ids[0]]
        elif "structure" in a:
            near = self.anchor(a["near"])
            st = self.rows(f"SELECT * FROM structure WHERE kind = '{a['structure']}'")
            s = min(st, key=lambda s: dist((s["x"], s["y"]), near))
            p = (s["x"], s["y"])
        elif "far_from" in a:
            ref = self.anchor(a["far_from"])
            corners = [(8, 8), (w - 8, 8), (8, h - 8), (w - 8, h - 8)]
            p = max(corners, key=lambda c: dist(c, ref))
        else:
            raise RuntimeError(f"unknown anchor {a}")
        if "away" in a:
            # `distance` tiles from the base point, directly away from another anchor.
            ref = self.anchor(a["away"])
            vx, vy = p[0] - ref[0], p[1] - ref[1]
            n = max(1e-6, (vx * vx + vy * vy) ** 0.5)
            p = (p[0] + vx / n * a["distance"], p[1] + vy / n * a["distance"])
        dx, dy = a.get("offset", (0, 0))
        # Members of a group stand a little apart.
        p = (p[0] + dx + 1.5 * member, p[1] + dy + 0.8 * member)
        return (min(max(p[0], 3), w - 3), min(max(p[1], 3), h - 3))

    # -- the script
    def ids(self, who):
        if who is None:
            return []
        if isinstance(who, int):
            return [who]
        if who.startswith("$#"):
            return [int(who[2:])]
        if who.startswith("$"):
            who = who[1:]
        if who == "addressee":
            return [self.ctx_addressee] if getattr(self, "ctx_addressee", 0) else []
        return self.roles[who]

    def subst(self, v):
        m = re.fullmatch(r"\$(\w+)_xy@(\w+):([\d.]+)", v) if isinstance(v, str) else None
        if m:
            # "$subject_xy@pack:9": 9 tiles from where the subject stands, toward the pack.
            a_id, b_id = self.ids(m.group(1))[0], self.ids(m.group(2))[0]
            pos = self.bodies([a_id, b_id])
            (ax, ay), (bx, by) = pos[a_id], pos[b_id]
            n = max(1e-6, ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5)
            d = float(m.group(3))
            return [round(ax + (bx - ax) / n * d, 1), round(ay + (by - ay) / n * d, 1)]
        m = re.fullmatch(r"\$(\w+)_xy(?:\+(-?[\d.]+),(-?[\d.]+))?", v) if isinstance(v, str) else None
        if m:
            # "$subject_xy+9,0": where that role stands now, plus an offset in tiles.
            ids = self.ids(m.group(1))
            x, y = self.bodies(ids[:1])[ids[0]]
            dx, dy = float(m.group(2) or 0), float(m.group(3) or 0)
            return [round(x + dx, 1), round(y + dy, 1)]
        if isinstance(v, str) and v.startswith("$"):
            ids = self.ids(v)
            return {"id": ids[0]} if ids else v
        if isinstance(v, dict):
            return {k: (self.ids(x)[0] if k in ("to", "near_id") and isinstance(x, str) and x.startswith("$") else self.subst(x)) for k, x in v.items()}
        if isinstance(v, list):
            return [self.subst(x) for x in v]
        return v

    def graph_of(self, g, actor):
        if isinstance(g, str) and g.startswith("instinct:"):
            return json.loads((ROOT / "living/seeds/instincts.json").read_text())[g.split(":", 1)[1]]
        if g == "original":
            return self.saved_graphs.get(actor, {"wait": 30})
        return self.subst(g)

    def step(self, s):
        kind = s["do"]
        who = self.ids(s.get("who"))
        self.emit("events", {"t": self.t(), "do": kind, "who": who, **{k: v for k, v in s.items() if k not in ("do", "who", "when", "at", "steps")}})
        for i, actor in enumerate(who or [None]):
            if kind == "place":
                x, y = self.anchor(s["to"], i)
                self.call("place_at", actor, x, y)
            elif kind == "graph":
                if actor not in self.saved_graphs:
                    b = self.rows(f"SELECT * FROM brain WHERE id = {actor}")
                    if b:
                        self.saved_graphs[actor] = json.loads(b[0]["graph"])
                self.call("set_behavior", actor, json.dumps(self.graph_of(s["graph"], actor)))
            elif kind == "items":
                for item, qty in s["items"].items():
                    self.call("grant_items", actor, item, qty)
            elif kind == "know":
                for t in s["techniques"]:
                    self.call("grant_know_how", actor, t)
            elif kind == "say":
                to = self.ids(s.get("to"))[0] if s.get("to") else 0
                self.call("mind_say", actor, s["text"], to, 0, {"kind": "trial", "summary": f"scripted line (trial fixture): {s['text'][:200]}",
                          "detail": "", "latency_ms": 0, "tokens": 0, "model": "", "reference": f"trial:{self.trial['name']}"})
            elif kind == "act":
                acts = s["acts"] if "acts" in s else [s["act"]]
                self.call("mind_act", actor, [json.dumps(self.subst(x)) for x in acts], "trial")
            elif kind == "structure":
                self.call("place_structure", actor, s["kind"])
            elif kind == "background":
                self.call("set_background", actor, json.dumps(s["background"]))
            elif kind == "kill":
                self.call("kill", actor, s.get("cause", "trial"))
            elif kind == "clear_routines":
                rs = self.rows(f"SELECT * FROM routine WHERE actor = {actor}")
                if rs:
                    self.call("mind_routines", actor, [{"name": r["name"], "graph": ""} for r in rs])
            elif kind == "clear_items":
                self.clear_items(actor)
            elif kind == "call":
                self.call(s["reducer"], *self.subst(s["args"]))
            elif kind == "note":
                pass
            else:
                raise RuntimeError(f"unknown step {kind}")

    def clear_items(self, actor):
        """Drop what the character carries (acts run through the ordinary drop rule)."""
        for _ in range(12):
            inv = [r for r in self.rows(f"SELECT * FROM inventory WHERE owner = {actor}") if r["qty"] > 0]
            if not inv:
                return
            self.call("mind_act", actor, [json.dumps({"do": "drop", "item": r["item"], "qty": r["qty"]}) for r in inv[:4]], "trial")
            time.sleep(3)
        self.emit("events", {"t": self.t(), "error": "inventory not empty after clearing"})

    def schedule(self, entry, base_s):
        for s in entry.get("steps", [entry]):
            self.pending.append((base_s + s.get("after", 0), s))

    def run_phase(self, phase):
        for e in self.trial.get("timeline", []):
            if e.get("at") == phase:
                for s in e.get("steps", [e]):
                    self.step(s)
                    time.sleep(s.get("after", 0.3))

    def triggers(self, new_chron, positions, hour):
        for k, e in enumerate(self.trial.get("timeline", [])):
            w = e.get("when")
            if not w or self.fired[k] >= e.get("max", 1) or self.t() < e.get("after_min", 0) * 60:
                continue
            if "said" in w:
                spec = w["said"]
                by = self.ids(spec.get("by", "subject"))
                for c in new_chron:
                    if c["kind"] != "speech" or c["a"] not in by:
                        continue
                    to = spec.get("to", "any")
                    if to == "any" and c["b"] == 0 and not spec.get("unaddressed"):
                        continue
                    if to not in ("any",) and c["b"] not in self.ids(to):
                        continue
                    said = c["text"].lower()
                    if spec.get("words") and not any(re.search(rf"\b{re.escape(x)}", said) for x in spec["words"]):
                        continue
                    if spec.get("without") and any(re.search(rf"\b{re.escape(x)}", said) for x in spec["without"]):
                        continue
                    if c["b"] and not self.is_person(c["b"]):
                        continue
                    key = (k, c["b"])
                    if e.get("per_addressee") and key in self.fired:
                        continue
                    self.fired[k] += 1
                    self.fired[key] += 1
                    self.ctx_addressee = c["b"]
                    self.emit("events", {"t": self.t(), "trigger": k, "on": c["text"][:200], "addressee": c["b"]})
                    self.schedule(self.subst_addressee(e, c["b"]), self.t())
                    break
            elif "near" in w:
                a, b = self.ids(w["near"].get("who", "subject")), self.ids(w["near"]["of"])
                if any(dist(positions.get(x, (1e9, 1e9)), positions.get(y, (-1e9, -1e9))) <= w["near"]["within"] for x in a for y in b):
                    self.fired[k] += 1
                    self.schedule(e, self.t())
            elif "hour" in w and hour >= w["hour"] and self.t() > 0:
                self.fired[k] += 1
                self.schedule(e, self.t())

    def is_person(self, cid):
        if cid not in self.kinds:
            r = self.rows(f"SELECT * FROM character WHERE id = {cid}")
            self.kinds[cid] = r[0]["kind"] if r else None
        return self.kinds[cid] == "person"

    def subst_addressee(self, e, addressee):
        """Steps of a triggered entry run for the person who was spoken to (`$addressee`)."""
        text = json.dumps(e).replace('"$addressee"', f'"$#{addressee}"')
        return json.loads(text)

    # -- the mind
    def models(self):
        v = self.shared["variants"][self.variant]
        if self.opts.fake:
            p = {"base_url": f"http://127.0.0.1:{self.shared['fake_port']}/v1", "model": "fake-trials", "key_env": "LIVING_VERIFY_FAKE_KEY",
                 "max_tokens": 512, "requests_per_minute": 6000, "reasoning_effort": {p: p for p in ("think", "deliberate", "consolidate", "talk")}}
            return {"default": "fake", "profiles": {"fake": p}, "assign": {}, "rotate": [], "groups": {}, "stages": {}, "species": {}}
        m = json.loads((ROOT / "living/configs/models.json").read_text())
        # The subject thinks with the variant's profile: no groups, assignments or rotation.
        m = {**m, "assign": {}, "rotate": [], "groups": {}, "stages": {}}
        return deep_merge(m, v.get("models", {}))

    def start_mind(self):
        v = self.shared["variants"][self.variant]
        path = self.dir / "models.json"
        path.write_text(json.dumps(self.models(), indent=1))
        budget = self.trial.get("budget", {})
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=URL, LIVING_DB=self.db, LIVING_RUN=self.db,
                   LIVING_SEED=self.shared["seed_rel"][self.trial["name"]], LIVING_MODELS=str(path),
                   LIVING_ONLY=str(self.subject), LIVING_TOKEN=self.shared["token"],
                   LIVING_NEO4J_URI=f"127.0.0.1:{NEO4J_PORT}", LIVING_NEO4J_PASSWORD=self.shared["neo4j_pw"],
                   LIVING_LLM_PER_MIN=str(budget.get("calls_per_min", 12)), LIVING_CONCURRENCY="4",
                   LIVING_VERIFY_FAKE_KEY="dummy-local-only", NO_PROXY="127.0.0.1,localhost",
                   RUST_LOG="info,neo4rs=warn,spacetimedb_sdk=warn")
        if self.opts.fake:
            # A fake run must never reach a provider: no provider keys in its environment.
            for k in ("MISTRAL_API_KEY", "CARLID_NPC_API_KEY", "TYPESAFE_API_KEY"):
                env[k] = ""
        env.update({k: str(x) for k, x in v.get("env", {}).items()})
        (self.dir / "mind-env.json").write_text(json.dumps({k: env[k] for k in sorted(env) if k.startswith("LIVING_") and k not in ("LIVING_TOKEN", "LIVING_NEO4J_PASSWORD")}, indent=1))
        self.mind_log = open(self.dir / "mind.log", "a")
        self.mind = subprocess.Popen([str(TARGET / "release/living-mind")], cwd=ROOT, env=env, stdout=self.mind_log, stderr=subprocess.STDOUT, start_new_session=True)
        self.log(f"mind pid {self.mind.pid} LIVING_ONLY={self.subject} variant {self.variant}")

    def stop_mind(self):
        if self.mind and self.mind.poll() is None:
            os.killpg(self.mind.pid, signal.SIGTERM)
            try:
                self.mind.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.mind.pid, signal.SIGKILL)
                self.mind.wait(timeout=10)
            self.log(f"mind stopped (exit {self.mind.returncode})")

    def read_journal(self):
        """Tokens and calls from the journal's new lines (the actual model exchanges)."""
        for f in self.journal.glob("*.jsonl") if self.journal.exists() else []:
            with open(f) as fh:
                fh.seek(self.jpos.get(f.name, 0))
                for line in fh:
                    if not line.endswith("\n"):
                        break
                    self.jpos[f.name] = self.jpos.get(f.name, 0) + len(line.encode())
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    tok = r.get("tokens") or 0
                    key = (r.get("purpose"), r.get("model"))
                    self.tokens[key] += tok
                    self.calls[key] += 1
                    if r.get("latency_ms"):
                        self.latency[r.get("purpose")].append(r["latency_ms"])
                    if not self.opts.fake:
                        with _lock:
                            self.shared["spent"] += tok

    # -- sampling
    def sample(self):
        S = self.subject
        others = [i for r, ids in self.roles.items() if r != "subject" for i in ids]
        everyone = [S] + others
        ors = " OR ".join(f"id = {i}" for i in everyone)
        q = [f"SELECT * FROM vitals WHERE id = {S}", f"SELECT * FROM activity WHERE id = {S}",
             f"SELECT * FROM inventory WHERE owner = {S}", f"SELECT * FROM brain WHERE id = {S}",
             f"SELECT * FROM character WHERE {ors}", "SELECT * FROM world", f"SELECT * FROM body WHERE {ors}",
             f"SELECT * FROM thought WHERE actor = {S} AND id > {self.cursor['thought']}",
             f"SELECT * FROM experience WHERE observer = {S} AND id > {self.cursor['experience']}",
             f"SELECT * FROM chronicle WHERE id > {self.cursor['chronicle']}",
             f"SELECT * FROM know_how WHERE actor = {S}", f"SELECT * FROM relation WHERE actor = {S}",
             f"SELECT * FROM judgment WHERE actor = {S}", f"SELECT * FROM persona WHERE id = {S}",
             f"SELECT * FROM structure WHERE owner = {S}", f"SELECT * FROM place WHERE actor = {S}"]
        # 2.14.1 answers one statement per request ("Multiple SQL statements are not supported").
        # The mind's projections change slowly, so they are read every fifth sample.
        self.nsample = getattr(self, "nsample", 0) + 1
        slow = self.nsample % 5 == 1
        res = [self.rows(x) if i < 10 or slow else None for i, x in enumerate(q)]
        (vit, act, inv, brain, chars, world, bodies, thoughts, exps, chron, know, rel, jud, persona, structs, places) = res
        now = self.now_ms()
        self.world = world[0]
        hour = hour_of(now, self.world)
        positions = {b["id"]: self.pos(b) for b in bodies}
        v = vit[0] if vit else None
        cur = (lambda field: None) if not v else (lambda field: round(min(100.0, max(0.0, v[field] + v[f"{field}_rate"] * (now - v["at_ms"]) / 60000)), 2))
        alive = {c["id"]: c["alive"] for c in chars}
        sp = positions.get(S)
        row = {"t": self.t(), "hour": round(hour, 2), "alive": alive.get(S), "pos": [round(x, 1) for x in sp] if sp else None,
               "hp": cur("hp"), "hunger": cur("hunger"), "energy": cur("energy"),
               "activity": (act[0]["skill"], act[0]["label"][:80], act[0]["target"]) if act else None,
               "inv": {r["item"]: r["qty"] for r in inv if r["qty"]}, "rev": brain[0]["revision"] if brain else None,
               "plan": brain[0]["plan"][:160] if brain else None,
               "dist": {r: round(min(dist(sp, positions[i]) for i in ids if i in positions), 1) for r, ids in self.roles.items() if r != "subject" and sp and any(i in positions for i in ids)},
               "cast_alive": {r: sum(1 for i in ids if alive.get(i)) for r, ids in self.roles.items() if r != "subject"}}
        self.emit("samples", row)
        if brain and brain[0]["revision"] != self.brain_rev:
            self.brain_rev = brain[0]["revision"]
            self.emit("graphs", {"t": self.t(), **brain[0]})
        for name, rows, key in (("thoughts", thoughts, "thought"), ("experiences", exps, "experience")):
            for r in sorted(rows, key=lambda r: r["id"]):
                self.emit(name, {"t": self.t(), **r})
                self.cursor[key] = max(self.cursor[key], r["id"])
        mine = set(everyone)
        new_chron = sorted(chron, key=lambda r: r["id"])
        for r in new_chron:
            self.cursor["chronicle"] = max(self.cursor["chronicle"], r["id"])
            if r["a"] in mine or r["b"] in mine:
                self.emit("chronicle", {"t": self.t(), **r})
        for name, rows in (("know_how", know), ("relation", rel), ("judgment", jud), ("persona", persona), ("structure", structs), ("place", places)):
            if rows is None:
                continue
            sig = json.dumps(sorted(rows, key=lambda r: json.dumps(r, sort_keys=True)), sort_keys=True)
            if self.last_rows.get(name) != sig:
                self.last_rows[name] = sig
                self.emit("mind_rows", {"t": self.t(), "table": name, "rows": rows})
        return row, new_chron, positions, hour

    def final(self):
        S = self.subject
        snap = {}
        for name, q in (("thought", f"SELECT * FROM thought WHERE actor = {S}"), ("brain", f"SELECT * FROM brain WHERE id = {S}"),
                        ("routine", f"SELECT * FROM routine WHERE actor = {S}"), ("relation", f"SELECT * FROM relation WHERE actor = {S}"),
                        ("judgment", f"SELECT * FROM judgment WHERE actor = {S}"), ("place", f"SELECT * FROM place WHERE actor = {S}"),
                        ("persona", f"SELECT * FROM persona WHERE id = {S}"), ("know_how", f"SELECT * FROM know_how WHERE actor = {S}"),
                        ("inventory", f"SELECT * FROM inventory WHERE owner = {S}"), ("vitals", f"SELECT * FROM vitals WHERE id = {S}"),
                        ("skill_use", f"SELECT * FROM skill_use WHERE actor = {S}"), ("deliberation", f"SELECT * FROM deliberation WHERE actor = {S}"),
                        ("structure", f"SELECT * FROM structure WHERE owner = {S}"), ("chronicle", "SELECT * FROM chronicle"),
                        ("character", "SELECT * FROM character WHERE " + " OR ".join(f"id = {i}" for ids in self.roles.values() for i in ids)),
                        ("stats", "SELECT * FROM stats")):
            try:
                snap[name] = self.rows(q)
            except RuntimeError as e:
                snap[name] = {"error": str(e)}
        (self.dir / "final.json").write_text(json.dumps(snap, indent=1))
        if self.journal.exists():
            shutil.copytree(self.journal, self.dir / "journal", dirs_exist_ok=True)

    # -- the whole run
    def run(self):
        try:
            self.status = "publishing"
            self.publish()
            self.cast()
            self.status = "preparing"
            subj = self.trial["subject"]
            if subj.get("clear_items", True):
                self.clear_items(self.subject)
            self.step({"do": "clear_routines", "who": "subject"})
            if subj.get("background"):
                self.step({"do": "background", "who": "subject", "background": subj["background"]})
            self.run_phase("prepare")
            start_hour = self.trial["world"].get("start_hour")
            self.status = "waiting"
            while start_hour is not None:
                hour = hour_of(self.now_ms(), self.rows("SELECT * FROM world")[0])
                if hour >= start_hour:
                    break
                time.sleep(2)
            self.status = "starting"
            self.run_phase("start")
            self.t0 = time.time()
            self.start_mind()
            self.status = "running"
            minutes = self.opts.minutes or self.trial.get("minutes", 15)
            cap = self.trial.get("budget", {}).get("tokens", 220000)
            died = None
            timeline = [(e.get("at"), e) for e in self.trial.get("timeline", []) if isinstance(e.get("at"), (int, float))]
            done = set()
            while True:
                tick = time.time()
                self.read_journal()
                row, new_chron, positions, hour = self.sample()
                for k, (at, e) in enumerate(timeline):
                    if k not in done and self.t() >= at * 60:
                        done.add(k)
                        self.schedule(e, at * 60)
                self.triggers(new_chron, positions, hour)
                due = [p for p in self.pending if p[0] <= self.t()]
                self.pending = [p for p in self.pending if p[0] > self.t()]
                for _, s in sorted(due, key=lambda p: p[0]):
                    self.step(s)
                total = sum(self.tokens.values())
                if row["alive"] is False and died is None:
                    died = self.t()
                if self.t() >= minutes * 60:
                    self.stopped_by = "duration"
                elif total >= cap:
                    self.stopped_by = "trial token cap"
                elif not self.opts.fake and self.shared["ledger_before"] + self.shared["spent"] >= TOTAL_CAP:
                    self.stopped_by = "total token cap"
                elif died is not None and self.t() - died >= 20:
                    self.stopped_by = "subject died"
                elif self.mind.poll() is not None:
                    self.stopped_by = f"mind exited ({self.mind.returncode})"
                elif self.shared.get("abort"):
                    self.stopped_by = "aborted"
                if self.stopped_by:
                    break
                time.sleep(max(0.0, SAMPLE_S - (time.time() - tick)))
            self.status = "collecting"
            self.stop_mind()
            self.read_journal()
            self.final()
            self.status = "done"
        except Exception as e:
            self.stopped_by = self.stopped_by or f"error: {e}"
            self.status = "failed"
            self.log(f"FAILED: {e!r}")
            self.stop_mind()
        finally:
            if self.mind:
                self.mind_log.close()
            summary = summarize(self.dir, self.trial, extra={"db": self.db, "variant": self.variant, "replicate": self.rep,
                                "stopped_by": self.stopped_by, "fake": bool(self.opts.fake), "minutes_planned": self.opts.minutes or self.trial.get("minutes", 15)})
            (self.dir / "summary.json").write_text(json.dumps(summary, indent=1))
            if not self.opts.keep_db and getattr(self, "published", False):
                delete_db(self.db)


def delete_db(db):
    if not db.startswith(PREFIX):
        raise RuntimeError(f"refusing to delete {db}")
    sh("docker", "exec", CONTAINER, "spacetime", "delete", "-s", "local", db, "-y", check=False)
    return http(f"/v1/database/{db}/sql", "SELECT 1 FROM world", raw=True)[0] == 404


# ---- probes ----------------------------------------------------------------------------

def jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def summarize(d, trial, extra):
    samples = jsonl(d / "samples.jsonl")
    thoughts = jsonl(d / "thoughts.jsonl")
    exps = jsonl(d / "experiences.jsonl")
    chron = jsonl(d / "chronicle.jsonl")
    events = jsonl(d / "events.jsonl")
    graphs = jsonl(d / "graphs.jsonl")
    cast = json.loads((d / "cast.json").read_text()) if (d / "cast.json").exists() else {"roles": {}}
    roles = cast["roles"]
    S = roles.get("subject", [{}])[0].get("id")
    names = {m["id"]: m["name"] for ms in roles.values() for m in ms}
    s = dict(extra)
    s["trial"] = trial["name"]
    s["subject"] = f"{names.get(S)}#{S}" if S else None
    s["samples"] = len(samples)
    s["minutes_run"] = round(samples[-1]["t"] / 60, 2) if samples else 0
    alive = [x for x in samples if x.get("alive") is not None]
    s["survived"] = bool(alive) and alive[-1]["alive"]
    dead = next((x for x in alive if not x["alive"]), None)
    s["died_min"] = round(dead["t"] / 60, 2) if dead else None
    deaths = [c for c in chron if c.get("kind") == "death" and c.get("a") == S]
    s["death"] = deaths[0]["text"][:200] if deaths else None
    hp = [x["hp"] for x in samples if x.get("hp") is not None]
    hunger = [x["hunger"] for x in samples if x.get("hunger") is not None]
    s["hp_min"] = min(hp) if hp else None
    s["hunger_start"] = hunger[0] if hunger else None
    s["hunger_max"] = max(hunger) if hunger else None
    s["hunger_end"] = hunger[-1] if hunger else None
    ate = None
    for a, b in zip(samples, samples[1:]):
        if (b.get("activity") or [None])[0] == "eat" or (a.get("hunger") is not None and b.get("hunger") is not None and b["hunger"] < a["hunger"] - 3):
            ate = b["t"]
            break
    s["first_eat_min"] = round(ate / 60, 2) if ate is not None else None
    gained = Counter()
    for a, b in zip(samples, samples[1:]):
        for item, q in (b.get("inv") or {}).items():
            if q > (a.get("inv") or {}).get(item, 0) and item in FOOD:
                gained[(item, ((a.get("activity") or ["idle"])[0]))] += q - (a.get("inv") or {}).get(item, 0)
    s["food_gained"] = {f"{i} ({how})": q for (i, how), q in gained.items()}
    skills, prev = Counter(), None
    for x in samples:
        a = (x.get("activity") or [None])[0]
        if a and a != prev:
            skills[a] += 1
        prev = a
    s["skills"] = dict(skills.most_common())
    # Distances to cast roles after each role first acted on the subject (or from the start).
    s["min_dist"] = {}
    for role in roles:
        if role == "subject":
            continue
        ds = [x["dist"][role] for x in samples if role in (x.get("dist") or {})]
        s["min_dist"][role] = min(ds) if ds else None
    rel_at = {}
    for e in events:
        if e.get("do") == "place" and e.get("t") is not None:
            for role, ms in roles.items():
                if [m["id"] for m in ms] == e.get("who"):
                    rel_at.setdefault(role, e["t"])
    s["fled_m"] = {}
    for role, t in rel_at.items():
        if role == "subject":
            continue
        start = next((x for x in samples if x["t"] >= t and x.get("pos")), None)
        if start:
            win = [x for x in samples if t <= x["t"] <= t + 120 and x.get("pos")]
            s["fled_m"][role] = round(max(dist(start["pos"], x["pos"]) for x in win), 1) if win else None
    speech = [c for c in chron if c.get("kind") == "speech" and c.get("a") == S]
    s["lines_said"] = len(speech)
    s["said_to"] = dict(Counter(names.get(c["b"], f"#{c['b']}" if c["b"] else "nobody") for c in speech))
    s["lines_heard_scripted"] = sum(1 for e in events if e.get("do") == "say")
    kinds = Counter(t.get("kind") for t in thoughts)
    s["thought_kinds"] = dict(kinds)
    s["errors"] = [t["summary"][:200] for t in thoughts if t.get("kind") == "error"]
    fails = [e for e in exps if re.search(r"did not work out|You failed|could not|cannot|can't|No answer", e.get("text", ""))]
    s["refusals"] = len(fails)
    s["refusal_examples"] = [e["text"][:160] for e in fails[:5]]
    mind_revs = [g for g in graphs if g.get("source") == "mind"]
    s["graph_revisions"] = len(mind_revs)
    s["plans"] = [f"{round(g['t'] / 60, 1)}m: {g.get('plan', '')[:140]}" for g in mind_revs[:12]]
    rows = defaultdict(list)
    for r in jsonl(d / "mind_rows.jsonl"):
        rows[r["table"]].append(r)
    last = {k: v[-1]["rows"] for k, v in rows.items()}
    first = {k: v[0]["rows"] for k, v in rows.items()}
    s["relations_end"] = [f"{names.get(r['other'], '#' + str(r['other']))}: trust {round(r['trust'])}, affinity {round(r['affinity'])}, {r['label']}" + (f" ({r['note'][:80]})" if r.get("note") else "") for r in last.get("relation", [])]
    s["judgments_end"] = [f"{r['key']} {round(r['value'], 2)}" for r in last.get("judgment", [])]
    before = {r["technique"] for r in first.get("know_how", [])}
    s["learned"] = sorted({r["technique"] for r in last.get("know_how", [])} - before)
    s["built"] = dict(Counter(r["kind"] for r in last.get("structure", []) if r["kind"] != "remains") - Counter(r["kind"] for r in first.get("structure", [])))
    s["persona_versions"] = [p.get("version") for p in last.get("persona", [])]
    s["places_named"] = [p["name"] for p in last.get("place", [])]
    # The journal: the actual model exchanges.
    j = []
    for f in sorted((d / "journal").glob("*.jsonl")) if (d / "journal").exists() else []:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            try:
                r = json.loads(line)
                r["_ref"] = f"{f.relative_to(d)}:{n}"
                j.append(r)
            except ValueError:
                pass
    j.sort(key=lambda r: r.get("at_ms", 0))
    by_purpose = defaultdict(lambda: {"calls": 0, "tokens": 0, "errors": 0, "latency_ms": []})
    by_model = defaultdict(lambda: {"calls": 0, "tokens": 0, "prompt": 0, "completion": 0, "cached": 0})
    remembered = 0
    for r in j:
        p = by_purpose[r.get("purpose")]
        p["calls"] += 1
        p["tokens"] += r.get("tokens") or 0
        p["errors"] += 1 if r.get("error") else 0
        if r.get("latency_ms"):
            p["latency_ms"].append(r["latency_ms"])
        m = by_model[r.get("model")]
        m["calls"] += 1
        m["tokens"] += r.get("tokens") or 0
        m["prompt"] += r.get("prompt_tokens") or 0
        m["completion"] += r.get("completion_tokens") or 0
        m["cached"] += r.get("cached_tokens") or 0
        if r.get("purpose") == "consolidate":
            rep = parse_reply(r.get("reply"))
            if isinstance(rep, dict) and isinstance(rep.get("remember"), list):
                remembered += len(rep["remember"])
    s["calls"] = sum(p["calls"] for p in by_purpose.values())
    s["tokens"] = sum(p["tokens"] for p in by_purpose.values())
    s["by_purpose"] = {k: {**v, "latency_p50_ms": int(statistics.median(v["latency_ms"])) if v["latency_ms"] else None, "latency_ms": None} for k, v in by_purpose.items()}
    for v in s["by_purpose"].values():
        v.pop("latency_ms")
    s["by_model"] = dict(by_model)
    s["talk_turns"] = by_purpose["talk"]["calls"] if "talk" in by_purpose else 0
    s["memories_remembered"] = remembered
    s["exchanges"] = [{"ref": r["_ref"], "purpose": r.get("purpose"), "model": r.get("model"), "tokens": r.get("tokens"),
                       "reply": excerpt(r.get("reply"))} for r in j if r.get("purpose") in ("deliberate", "think", "talk")][:40]
    return s


def parse_reply(text):
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


def excerpt(reply):
    r = parse_reply(reply)
    if not isinstance(r, dict):
        return (reply or "")[:300] if isinstance(reply, str) else None
    keep = {k: r[k] for k in ("thought", "feeling", "impulse", "intend", "plan", "say", "acts", "to", "end", "settled") if k in r}
    return json.dumps(keep)[:600]


# ---- batches ---------------------------------------------------------------------------

def ledger():
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else {"cap": TOTAL_CAP, "batches": {}}


def run(a):
    guard()
    if not re.fullmatch(r"[a-z0-9]+", a.batch):
        sys.exit("--batch must be lowercase letters and digits")
    trials = [load_trial(t) for t in a.trials]
    vs = variants()
    names = a.variants.split(",")
    for v in names:
        if v not in vs:
            sys.exit(f"unknown variant {v}; see living/trials/variants.json")
    plan = [(t, v, r) for t in trials for v in names for r in range(1, a.replicates + 1)]
    led = ledger()
    spent = sum(b.get("tokens", 0) for b in led["batches"].values())
    need = sum(t.get("budget", {}).get("tokens", 220000) for t, _, _ in plan)
    print(f"batch {a.batch}: {len(plan)} instances; worst case {need:,} tokens; spent so far {spent:,} of {TOTAL_CAP:,}{' (fake: not counted)' if a.fake else ''}")
    if not a.fake and spent + need > TOTAL_CAP and not a.allow_partial:
        sys.exit("the batch's worst case exceeds the remaining total; lower the caps, run fewer, or pass --allow-partial (the total cap still stops it)")
    if a.batch in led["batches"] and not a.fake:
        sys.exit(f"batch {a.batch} already ran; choose a new name")
    shared = {"token": admin_token(), "neo4j_pw": neo4j_password(), "variants": vs, "spent": 0, "ledger_before": spent, "wasm": {}, "seed_rel": {}}
    for t in trials:
        name, rel, _ = world_seed(t["world"])
        if not (OUT / "wasm" / f"{name}.wasm").exists():
            sys.exit(f"module for {t['name']} ({name}) is not built: run `trials.py build {t['name']}`")
        shared["wasm"][t["name"]], shared["seed_rel"][t["name"]] = name, rel
    if not (TARGET / "release/living-mind").exists():
        sys.exit(f"no mind binary at {TARGET / 'release/living-mind'}: run `trials.py build`")
    fake = None
    bdir = OUT / a.batch
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "batch.json").write_text(json.dumps({"trials": a.trials, "variants": names, "replicates": a.replicates, "fake": a.fake,
                                                 "commit": sh("git", "-C", ROOT, "rev-parse", "--short", "HEAD").stdout.strip(),
                                                 "dirty": bool(sh("git", "-C", ROOT, "status", "--porcelain", "living").stdout.strip()),
                                                 "started": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1))
    if a.fake:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        shared["fake_port"] = s.getsockname()[1]
        s.close()
        fake = subprocess.Popen([sys.executable, str(FAKE), "--port", str(shared["fake_port"]), "--log", str(bdir / "fake-requests.jsonl")],
                                stdout=open(bdir / "fake.log", "a"), stderr=subprocess.STDOUT, start_new_session=True)
        time.sleep(1)
    instances = [Instance(a.batch, t, v, r, a, shared) for t, v, r in plan]
    sem = threading.Semaphore(a.parallel)

    def go(inst):
        with sem:
            inst.run()

    threads = [threading.Thread(target=go, args=(i,), daemon=True) for i in instances]
    for th in threads:
        th.start()
        time.sleep(2)
    old = signal.signal(signal.SIGINT, lambda *_: shared.__setitem__("abort", True))
    try:
        while any(th.is_alive() for th in threads):
            time.sleep(15)
            line = " ".join(f"{i.name}:{i.status}{'@' + str(round((i.t() or 0) / 60, 1)) + 'm' if i.status == 'running' else ''}" for i in instances)
            print(f"[{time.strftime('%H:%M:%S')}] spent {shared['spent']:,} | {line}", flush=True)
    finally:
        signal.signal(signal.SIGINT, old)
        if fake:
            os.killpg(fake.pid, signal.SIGTERM)
    if not a.fake:
        led = ledger()
        led["batches"][a.batch] = {"tokens": shared["spent"], "instances": len(plan), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        LEDGER.write_text(json.dumps(led, indent=1))
    report(argparse.Namespace(batch=a.batch))


def fmt(v):
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    if isinstance(v, bool):
        return "yes" if v else "no"
    if v is None:
        return "–"
    if isinstance(v, dict):
        return ", ".join(f"{k} {fmt(x)}" for k, x in v.items()) or "–"
    if isinstance(v, list):
        return "; ".join(map(str, v)) or "–"
    return str(v)


def spread(vals):
    nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(nums) < 2:
        return ""
    return f"mean {statistics.mean(nums):.2f}, range {min(nums):g}–{max(nums):g}"


ROWS = ["subject", "stopped_by", "minutes_run", "survived", "died_min", "hp_min", "hunger_start", "hunger_max", "hunger_end",
        "first_eat_min", "food_gained", "skills", "min_dist", "fled_m", "lines_said", "said_to", "talk_turns", "graph_revisions",
        "refusals", "learned", "built", "relations_end", "judgments_end", "memories_remembered", "calls", "tokens"]


def report(a):
    bdir = OUT / a.batch
    sums = [json.loads(p.read_text()) for p in sorted(bdir.glob("*/summary.json"))]
    groups = defaultdict(list)
    for s in sums:
        groups[(s["trial"], s["variant"])].append(s)
    out = [f"# Trial batch {a.batch}\n"]
    meta = json.loads((bdir / "batch.json").read_text()) if (bdir / "batch.json").exists() else {}
    out.append(f"Commit {meta.get('commit')}{' + uncommitted living/ changes' if meta.get('dirty') else ''}; {'fake model' if meta.get('fake') else 'real models'}; started {meta.get('started')}.\n")
    tok = defaultdict(lambda: Counter())
    for s in sums:
        for m, v in s.get("by_model", {}).items():
            tok[m]["calls"] += v["calls"]
            tok[m]["tokens"] += v["tokens"]
            tok[m]["prompt"] += v["prompt"]
            tok[m]["completion"] += v["completion"]
            tok[m]["cached"] += v["cached"]
    out.append("| Model | Calls | Tokens | Prompt | Completion | Cached |\n| --- | ---: | ---: | ---: | ---: | ---: |")
    for m, v in tok.items():
        out.append(f"| {m} | {v['calls']} | {v['tokens']:,} | {v['prompt']:,} | {v['completion']:,} | {v['cached']:,} |")
    out.append("")
    for (trial, variant), ss in sorted(groups.items()):
        ss.sort(key=lambda s: s["replicate"])
        out.append(f"## {trial} / {variant}\n")
        out.append("| Probe | " + " | ".join(f"r{s['replicate']}" for s in ss) + " | Spread |")
        out.append("| --- |" + " --- |" * len(ss) + " --- |")
        for k in ROWS:
            vals = [s.get(k) for s in ss]
            out.append(f"| {k} | " + " | ".join(fmt(v).replace("|", "/") for v in vals) + f" | {spread(vals)} |")
        out.append("")
    (bdir / "report.md").write_text("\n".join(out))
    print("\n".join(out))
    print(f"\nwritten {bdir / 'report.md'}")


def clean(a):
    guard()
    bdir = OUT / a.batch
    dbs = [d for d in databases() if d.startswith(f"{PREFIX}{a.batch}-")]
    for db in dbs:
        print(f"delete {db}: {'ok (SQL 404)' if delete_db(db) else 'STILL ANSWERS'}")
    runs = [json.loads(p.read_text())["db"] for p in bdir.glob("*/summary.json")]
    if runs and docker_state(NEO4J) == "running":
        q = "MATCH (n) WHERE n.run IN $runs DETACH DELETE n"
        r = sh("docker", "exec", NEO4J, "cypher-shell", "-u", "neo4j", "-p", neo4j_password(), "-P", f"runs => {json.dumps(runs)}", q, check=False)
        print(f"neo4j minds of {len(runs)} runs removed" if r.returncode == 0 else f"neo4j cleanup failed: {r.stderr.strip()[:300]}")
    for p in bdir.glob("*/mind.log"):
        if p.stat().st_size > 1 << 30:
            p.unlink()
            print(f"removed {p} (> 1 GB)")


def show_ledger(_a):
    led = ledger()
    total = sum(b.get("tokens", 0) for b in led["batches"].values())
    for k, b in led["batches"].items():
        print(f"{k}: {b['tokens']:,} tokens, {b['instances']} instances, {b['at']}")
    print(f"total {total:,} of {TOTAL_CAP:,}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up").set_defaults(f=up)
    sub.add_parser("down").set_defaults(f=down)
    p = sub.add_parser("build")
    p.add_argument("trials", nargs="*")
    p.set_defaults(f=build)
    p = sub.add_parser("run")
    p.add_argument("--batch", required=True)
    p.add_argument("trials", nargs="+")
    p.add_argument("--variants", default="default")
    p.add_argument("--replicates", type=int, default=3)
    p.add_argument("--minutes", type=float)
    p.add_argument("--fake", action="store_true", help="answer every model call from the local fake server (no provider keys)")
    p.add_argument("--parallel", type=int, default=18)
    p.add_argument("--keep-db", action="store_true")
    p.add_argument("--allow-partial", action="store_true")
    p.set_defaults(f=run)
    p = sub.add_parser("report")
    p.add_argument("--batch", required=True)
    p.set_defaults(f=report)
    p = sub.add_parser("clean")
    p.add_argument("--batch", required=True)
    p.set_defaults(f=clean)
    sub.add_parser("ledger").set_defaults(f=show_ledger)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
