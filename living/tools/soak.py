#!/usr/bin/env python3
"""The playtest soak (docs/SOAK.md): a handful of players and one real game client on the island
for hours, with minds on the fake model server and scripted disruptions, measured for crashes,
correctness after each disruption, growth and latency over time.

    living/tools/soak.py run [--hours 4.25] [--players 7] [--smoke]
    living/tools/soak.py analyze .local/living/soak/<run>
    living/tools/soak.py cleanup        # its own processes (recorded PIDs), containers and volumes

What `run` does (every step is logged in <run>/run.log; times are the Mac's wall clock):
1. Starts its own SpacetimeDB (`soak-stdb`) and Neo4j (`soak-neo4j`) containers with their own
   volumes, publishes the island module fresh as `verify-soak-*` and installs the skills.
2. Starts two byte-counting relays (`gate-load relay`): players, and the game client. A relay
   `cut` closes its connections and refuses new ones for a while (a network outage).
3. Starts the fake model server and the mind service (Neo4j on, player memory on), kept running
   by a supervisor that restarts it 3 s after any exit and records why it exited.
4. Joins the players (`gate-load soak`, real WebSocket connections, own identities) and one
   headless `living-game` that walks between towns, gathers, eats, greets and talks.
5. Runs the timeline: short and long disconnects (long ones past `takeover_s`), hunts and duels,
   a game-client outage, a mind-service restart, a full SpacetimeDB container restart, a module
   republish with the data kept, a network blip for every player; then a privacy check with
   verify-client's probe. Every reconnect's restored state is checked against the authority.
6. Samples every 30 s (server metrics, container memory and CPU, process RSS and CPU) and every
   5 min (row counts, the replica on disk, Neo4j nodes and relationships).
7. At the end: the module log, the mind log, the game client's frames and log, then `analyze`.
Never touches anything but its own containers, volumes and `verify-soak-*` database.
"""
import argparse
import collections
import gzip
import hashlib
import json
import math
import os
import platform
import queue
import random
import re
import secrets
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = Path(os.environ.get("SOAK_MAIN", "/Users/carlid/dev/slop-art-online"))
EVID = Path(os.environ.get("SOAK_EVIDENCE", MAIN / ".local/living/soak"))
BIN = Path(os.environ.get("SOAK_BIN", MAIN / ".local/living/soak/bin"))
STDB = os.environ.get("SOAK_STDB_CONTAINER", "soak-stdb")
STDB_VOL = os.environ.get("SOAK_STDB_VOLUME", "soak-stdb-data")
NEO = os.environ.get("SOAK_NEO4J_CONTAINER", "soak-neo4j")
NEO_VOL = os.environ.get("SOAK_NEO4J_VOLUME", "soak-neo4j-data")
PORT = int(os.environ.get("SOAK_STDB_PORT", "3361"))
PLAYERS_RELAY = int(os.environ.get("SOAK_PLAYERS_RELAY", "3362"))
GAME_RELAY = int(os.environ.get("SOAK_GAME_RELAY", "3363"))
FAKE_PORT = int(os.environ.get("SOAK_FAKE_PORT", "3364"))
NEO_PORT = int(os.environ.get("SOAK_NEO4J_PORT", "7731"))
URL = f"http://127.0.0.1:{PORT}"
IMAGE = "docker.io/clockworklabs/spacetime:v2.14.1"
NEO_IMAGE = "neo4j:2026.10.1"
LOAD, GAME, MIND = BIN / "gate-load", BIN / "living-game", BIN / "living-mind"
WASM = BIN / "wasm/living_authority.wasm"
PROBE = Path(os.environ.get("SOAK_PROBE", BIN / "verify-client-probe"))
FAKE = ROOT / ".agents/skills/verify-llm/scripts/fake_llm.py"
PIDS = EVID / "pids.json"
TAKEOVER_S = 30.0
# verify-client's lists (.agents/skills/verify-client/scripts/drive.py): private to every client,
# and private in the default scoped build.
sys.path.insert(0, str(ROOT / ".agents/skills/verify-client/scripts"))


def client_lists():
    src = (ROOT / ".agents/skills/verify-client/scripts/drive.py").read_text()
    out = {}
    for name in ("PRIVATE", "SCOPED", "VIEWS"):
        m = re.search(rf"^{name} = (\[.*?\])", src, re.S | re.M)
        out[name] = eval(m.group(1), {})  # noqa: S307 - a literal list in our own source
    return out


# ---- helpers -----------------------------------------------------------------------------------

class Run:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log_file = (self.dir / "run.log").open("a")
        self.lock = threading.Lock()
        self.checks = (self.dir / "checks.jsonl").open("a")
        self.disruptions = (self.dir / "disruptions.jsonl").open("a")

    def log(self, msg):
        line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3]}] {msg}"
        with self.lock:
            print(line, flush=True)
            self.log_file.write(line + "\n")
            self.log_file.flush()

    def check(self, name, ok, **detail):
        row = {"t": time.time(), "check": name, "ok": bool(ok), **detail}
        with self.lock:
            self.checks.write(json.dumps(row, default=str) + "\n")
            self.checks.flush()
        if not ok:
            self.log(f"CHECK FAILED {name}: {json.dumps(detail, default=str)[:600]}")
        return ok

    def disruption(self, **row):
        row["t"] = time.time()
        with self.lock:
            self.disruptions.write(json.dumps(row, default=str) + "\n")
            self.disruptions.flush()

    def save(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj, indent=2, default=str) + "\n")


def sh(*args, check=True, timeout=600, **kw):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args))[:200]}: {r.returncode} {r.stderr.strip()[-2000:]}")
    return r.stdout


def stdb(*args, check=True, timeout=600):
    return sh("docker", "exec", "-i", STDB, "spacetime", *args, check=check, timeout=timeout)


def http(path, body=None, token=None, raw=False, timeout=30):
    data = body.encode() if raw else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(URL + path, data=data, method="POST" if data is not None or path == "/v1/identity" else "GET")
    if data is not None and not raw:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # noqa: BLE001 - the server may be down on purpose
        return 0, str(e)


def sql(db, q, token, timeout=60):
    code, body = http(f"/v1/database/{db}/sql", q, token, raw=True, timeout=timeout)
    if code != 200:
        raise RuntimeError(f"sql {q!r}: {code} {body[:300]}")
    res = json.loads(body)[0]
    names = [e["name"]["some"] if isinstance(e["name"], dict) else e["name"] for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def ident_hex(v):
    """An identity as SQL returns it (`{"__identity__": "0x…"}` or a string), as bare hex."""
    if isinstance(v, dict):
        v = v.get("__identity__", "")
    if isinstance(v, list) and v:
        v = v[0]
    return str(v).removeprefix("0x").lower()


def admin_token():
    out = stdb("login", "show", "--token")
    found = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", out)
    if len(found) != 1:
        raise RuntimeError("could not read the container CLI's token")
    return found[0]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summary(xs, digits=1):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "p50": round(pct(xs, 50), digits), "p95": round(pct(xs, 95), digits), "p99": round(pct(xs, 99), digits), "max": round(max(xs), digits), "mean": round(statistics.fmean(xs), digits)}


def proc_stats(pids):
    """RSS (kB) and CPU time (s) of each named process, from ps (macOS and Linux)."""
    live = {k: v for k, v in pids.items() if v}
    if not live:
        return {}
    out = sh("ps", "-o", "pid=,rss=,time=", "-p", ",".join(str(p) for p in live.values()), check=False)
    by = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) < 3:
            continue
        t = f[2]
        days = 0
        if "-" in t:
            d, t = t.split("-", 1)
            days = int(d)
        parts = [float(x) for x in t.split(":")]
        secs = days * 86400 + sum(v * 60 ** (len(parts) - 1 - i) for i, v in enumerate(parts))
        by[int(f[0])] = {"rss_kb": int(f[1]), "cpu_s": secs}
    return {k: by.get(v) for k, v in live.items()}


def remember(pid, name):
    d = json.loads(PIDS.read_text()) if PIDS.exists() else {}
    d[str(pid)] = name
    PIDS.write_text(json.dumps(d))


class Proc:
    """A child process; stdout JSON lines go to a queue, or stdout goes to its log file."""

    def __init__(self, r, name, cmd, env=None, lines=True, stdin=True):
        self.name = name
        self.err = (r.dir / f"{name}.stderr").open("a")
        self.p = subprocess.Popen([str(c) for c in cmd], stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                                  stdout=subprocess.PIPE if lines else self.err, stderr=self.err, text=True, env=env, start_new_session=True)
        remember(self.p.pid, name)
        self.q = queue.Queue()
        self.lines = []
        if lines:
            threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            try:
                v = json.loads(line)
            except ValueError:
                continue
            self.lines.append(v)
            self.q.put(v)

    def send(self, obj):
        self.p.stdin.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")
        self.p.stdin.flush()

    def expect(self, event, timeout, keep=None):
        end = time.time() + timeout
        while time.time() < end:
            try:
                v = self.q.get(timeout=max(0.05, end - time.time()))
            except queue.Empty:
                break
            if v.get("event") == event:
                return v
            if keep is not None:
                keep(v)
        raise RuntimeError(f"{self.name}: no {event} within {timeout}s (exit {self.p.poll()})")

    def pid(self):
        return self.p.pid if self.p.poll() is None else None

    def stop(self, sig=signal.SIGTERM, wait=15):
        if self.p.poll() is None:
            try:
                os.killpg(self.p.pid, sig)
            except ProcessLookupError:
                pass
            try:
                self.p.wait(wait)
            except subprocess.TimeoutExpired:
                os.killpg(self.p.pid, signal.SIGKILL)
                self.p.wait(10)
        return self.p.returncode


# ---- containers --------------------------------------------------------------------------------

def ping(timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        if http("/v1/ping", timeout=5)[0] == 200:
            return True
        time.sleep(1)
    return False


def start_stdb(r):
    names = sh("docker", "ps", "-a", "--format", "{{.Names}}", check=False).split()
    if STDB in names:
        raise RuntimeError(f"{STDB} exists: run `soak.py cleanup` first")
    WASM.parent.mkdir(parents=True, exist_ok=True)
    r.log(f"starting {STDB} (port {PORT}, volume {STDB_VOL}, memory limit 3g)")
    sh("docker", "run", "-d", "--name", STDB, "--memory", "3g", "--stop-signal", "SIGINT", "--stop-timeout", "60",
       "-p", f"127.0.0.1:{PORT}:3000", "-v", f"{STDB_VOL}:/home/spacetime", "-v", f"{WASM.parent}:/wasm:ro", IMAGE, "start", "--listen-addr", "0.0.0.0:3000")
    if not ping():
        raise RuntimeError("the server did not answer /v1/ping")


def start_neo4j(r, password):
    r.log(f"starting {NEO} (bolt 127.0.0.1:{NEO_PORT}, volume {NEO_VOL}, heap 512m, page cache 256m, memory limit 1500m)")
    sh("docker", "run", "-d", "--name", NEO, "--memory", "1500m", "-p", f"127.0.0.1:{NEO_PORT}:7687", "-v", f"{NEO_VOL}:/data",
       "-e", f"NEO4J_AUTH=neo4j/{password}", "-e", "NEO4J_server_memory_heap_max__size=512m", "-e", "NEO4J_server_memory_heap_initial__size=512m",
       "-e", "NEO4J_server_memory_pagecache_size=256m", NEO_IMAGE)
    for _ in range(120):
        if subprocess.run(["docker", "exec", NEO, "cypher-shell", "-u", "neo4j", "-p", password, "RETURN 1"], capture_output=True).returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("Neo4j did not answer")


def neo_counts(password):
    out = sh("docker", "exec", NEO, "cypher-shell", "-u", "neo4j", "-p", password, "--format", "plain",
             "MATCH (n) WITH count(n) AS nodes OPTIONAL MATCH ()-[e]->() RETURN nodes, count(e) AS edges", check=False, timeout=120)
    nums = re.findall(r"^(\d+), (\d+)$", out, re.M)
    labels = sh("docker", "exec", NEO, "cypher-shell", "-u", "neo4j", "-p", password, "--format", "plain",
                "MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c ORDER BY c DESC LIMIT 12", check=False, timeout=120)
    return {"nodes": int(nums[0][0]) if nums else None, "edges": int(nums[0][1]) if nums else None,
            "labels": dict((a.strip('"'), int(b)) for a, b in re.findall(r'^"?([^",]*)"?, (\d+)$', labels, re.M))}


def container_stats():
    out = sh("docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}", STDB, NEO, check=False, timeout=60)
    res = {}
    units = {"B": 1, "KiB": 2**10, "MiB": 2**20, "GiB": 2**30, "kB": 1e3, "MB": 1e6, "GB": 1e9}
    for line in out.splitlines():
        f = line.split("\t")
        if len(f) < 3:
            continue
        m = re.match(r"([\d.]+)(\w+)", f[1].split("/")[0].strip())
        res[f[0]] = {"mem": float(m.group(1)) * units.get(m.group(2), 1) if m else None, "cpu_pct": float(f[2].rstrip("%") or 0)}
    return res


def stdb_cgroup():
    out = sh("docker", "exec", STDB, "sh", "-c", "cat /sys/fs/cgroup/cpu.stat /sys/fs/cgroup/memory.current; grep -E '^(anon|file) ' /sys/fs/cgroup/memory.stat; "
             "ps -o rss= -p 1", check=False, timeout=30)
    usage = re.search(r"usage_usec (\d+)", out)
    lines = out.splitlines()
    mem = next((int(l) for l in lines if l.strip().isdigit() and int(l) > 10**6), None)
    anon = re.search(r"^anon (\d+)", out, re.M)
    file_ = re.search(r"^file (\d+)", out, re.M)
    return {"cpu_usec": int(usage.group(1)) if usage else None, "memory_current": mem, "anon": int(anon.group(1)) if anon else None, "file": int(file_.group(1)) if file_ else None}


def disk_usage():
    out = sh("docker", "exec", STDB, "sh", "-c", "for d in /home/spacetime/.local/share/spacetime/data/replicas/*/clog /home/spacetime/.local/share/spacetime/data/replicas/*/snapshots "
             "/home/spacetime/.local/share/spacetime/data/replicas/*/module_logs /home/spacetime/.local/share/spacetime/data; do du -sk $d; done 2>/dev/null", check=False, timeout=120)
    return [(int(a) * 1024, b) for a, b in re.findall(r"^(\d+)\s+(\S+)$", out, re.M)]


# ---- the mind service, kept running -------------------------------------------------------------

class Mind(threading.Thread):
    """The mind service, restarted 3 s after any exit (as living/tools/run-mind.sh does), each
    exit recorded with its code, its last log lines and whether this run asked for it."""

    def __init__(self, r, env):
        super().__init__(daemon=True)
        self.r, self.env = r, env
        self.name = "mind"
        self.proc = None
        self.exits = []
        self.planned = False
        self.stopping = False
        self.log_path = r.dir / "mind.log"

    def run(self):
        while not self.stopping:
            out = self.log_path.open("a")
            started = time.time()
            self.proc = subprocess.Popen([str(MIND)], env=self.env, stdout=out, stderr=out, start_new_session=True)
            remember(self.proc.pid, "mind")
            code = self.proc.wait()
            out.close()
            tail = self.log_path.read_text(errors="replace").splitlines()[-6:]
            row = {"t": time.time(), "code": code, "ran_s": round(time.time() - started, 1), "planned": self.planned, "stopping": self.stopping, "tail": tail}
            self.exits.append(row)
            self.r.log(f"mind exited {code} after {row['ran_s']} s (planned {self.planned}): {tail[-1][:200] if tail else ''}")
            self.planned = False
            if not self.stopping:
                time.sleep(3)

    def pid(self):
        return self.proc.pid if self.proc and self.proc.poll() is None else None

    def restart(self):
        self.planned = True
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)

    def stop(self, *_):
        self.stopping = True
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)


# ---- sampling ----------------------------------------------------------------------------------

TABLES = ["character", "body", "vitals", "activity", "experience", "chronicle", "skill_use", "combat_seen", "missile", "fighter", "perceived", "projected", "inventory",
          "resource_node", "structure", "mind_state", "brain", "wake", "doing", "presence", "connection", "acquaintance", "reveal", "readiness", "deliberation", "thought",
          "persona", "belief", "relation", "judgment", "place", "know_how", "artifact", "trade_offer", "routine", "routine_stat", "act_queue", "guest", "judged"]


class Sampler(threading.Thread):
    def __init__(self, r, ctx):
        super().__init__(daemon=True)
        self.r, self.ctx = r, ctx
        self.stop = threading.Event()
        self.out = gzip.open(r.dir / "samples.jsonl.gz", "at")

    def run(self):
        k = 0
        while not self.stop.is_set():
            t = time.time()
            s = {"t": t, "load": os.getloadavg()}
            try:
                code, text = http("/v1/metrics", timeout=20)
                ident = self.ctx["ident"]
                s["metrics"] = [l for l in text.splitlines() if (ident in l or l.startswith(("jemalloc_", "spacetime_page_pool", "page_pool"))) and not l.startswith("#")] if code == 200 else None
            except Exception as e:  # noqa: BLE001
                s["metrics_error"] = str(e)
            try:
                s["cgroup"] = stdb_cgroup()
                s["containers"] = container_stats()
            except Exception as e:  # noqa: BLE001
                s["container_error"] = str(e)
            s["procs"] = proc_stats(self.ctx["pids"]())
            if k % 10 == 0:
                counts = {}
                for tb in TABLES:
                    try:
                        counts[tb] = sql(self.ctx["db"], f"SELECT COUNT(*) AS n FROM {tb}", self.ctx["token"], timeout=30)[0]["n"]
                    except Exception as e:  # noqa: BLE001
                        counts[tb] = str(e)[:80]
                s["rows"] = counts
                try:
                    s["stats"] = sql(self.ctx["db"], "SELECT * FROM stats", self.ctx["token"], timeout=30)[0]
                except Exception as e:  # noqa: BLE001
                    s["stats"] = str(e)[:80]
                try:
                    s["disk"] = disk_usage()
                except Exception as e:  # noqa: BLE001
                    s["disk"] = str(e)[:80]
                try:
                    s["neo4j"] = neo_counts(self.ctx["neo_pw"])
                except Exception as e:  # noqa: BLE001
                    s["neo4j"] = str(e)[:80]
            self.out.write(json.dumps(s, default=str) + "\n")
            self.out.flush()
            k += 1
            self.stop.wait(max(0.0, 30 - (time.time() - t)))
        self.out.close()


# ---- correctness checks ------------------------------------------------------------------------

def inv_of(db, token, cid):
    out = collections.Counter()
    for row in sql(db, f"SELECT * FROM inventory WHERE owner = {cid}", token):
        out[row["item"]] += row["qty"]
    return dict(out)


class Checker:
    """Checks each reconnect's restored state, and the world's invariants, against the
    authority's rows (read as the owner)."""

    def __init__(self, r, ctx):
        self.r, self.ctx = r, ctx
        self.lock = threading.Lock()

    def restored(self, ev):
        db, token = self.ctx["db"], self.ctx["token"]
        p, me = ev["p"], ev.get("me")
        ident = self.ctx["idents"][p]
        try:
            mine = [c for c in sql(db, f"SELECT * FROM character WHERE controller = 0x{ident}", token)]
            pres = sql(db, f"SELECT * FROM presence WHERE player = 0x{ident}", token)
        except Exception as e:  # noqa: BLE001
            self.r.check("restore.truth_readable", False, p=p, error=str(e))
            return
        alive = [c for c in mine if c["alive"]]
        detail = {"p": p, "gen": ev.get("gen"), "before": ev.get("before"), "me": me, "down_ms": ev.get("down_ms"), "planned": ev.get("planned"), "connect_ms": ev.get("connect_ms")}
        self.r.check("restore.one_living_character", len(alive) <= 1, **detail, alive=[c["id"] for c in alive])
        if alive:
            c = alive[0]
            self.r.check("restore.character_given_back", me == c["id"], **detail, truth=c["id"])
            self.r.check("restore.control_handed_back", not c["ai"], **detail, ai=c["ai"])
            pr = [x for x in pres if x["id"] == c["id"]]
            self.r.check("restore.presence_present", bool(pr) and pr[0]["present"] and not pr[0]["ai"] and pr[0]["connections"] >= 1, **detail, presence=pr)
            truth = inv_of(db, token, c["id"])
            same = truth == {k: v for k, v in ev.get("inv", {}).items() if v}
            if not same:
                # A second look: an act finishing as the connection came back moves both.
                time.sleep(2)
                truth2 = inv_of(db, token, c["id"])
                client = {k: v for k, v in ev.get("inv", {}).items() if v}
                ok, why = explained(db, token, c["id"], int(ev["ts"] / 1000) - 5000, client, truth)
                self.r.check("restore.inventory_matches", ok, **detail, client=client, truth=truth, truth_2s=truth2, explained_by=why)
            else:
                self.r.check("restore.inventory_matches", True, **detail, items=sum(truth.values()))
            if ev.get("before") not in (None, c["id"]):
                self.r.check("restore.same_character_unless_dead", False, **detail, note="the client had another living character before")
        else:
            dead = [c for c in mine if not c["alive"]]
            self.r.check("restore.no_character_means_dead", me is None, **detail, dead=[(c["id"], c["cause"]) for c in dead[-2:]])
            if ev.get("before") is not None:
                self.r.disruption(kind="died_while_away", p=p, before=ev.get("before"), cause=[c["cause"] for c in dead if c["id"] == ev.get("before")])

    def invariants(self, tag):
        db, token = self.ctx["db"], self.ctx["token"]
        try:
            pres = sql(db, "SELECT * FROM presence", token)
            chars = sql(db, "SELECT * FROM character WHERE kind = 'person'", token)
            conns = sql(db, "SELECT * FROM connection", token)
        except Exception as e:  # noqa: BLE001
            self.r.check("invariants.readable", False, tag=tag, error=str(e))
            return None
        by_player = collections.Counter(ident_hex(p["player"]) for p in pres)
        dup = {k: v for k, v in by_player.items() if v > 1}
        self.r.check("invariants.one_presence_per_person", not dup, tag=tag, duplicates=dup)
        ours = set(self.ctx["idents"])
        alive_by = collections.Counter()
        for c in chars:
            if c["alive"] and ident_hex(c["controller"]) in ours and not c["ai"]:
                alive_by[ident_hex(c["controller"])] += 1
        presence_by = {ident_hex(p["player"]): p for p in pres}
        for i in ours:
            n = alive_by[i] + (1 if i in presence_by and presence_by[i]["ai"] else 0)
            if n > 1:
                self.r.check("invariants.one_living_character_per_person", False, tag=tag, identity=i[:12], n=n)
        dead_present = [p["id"] for p in pres if not next((c for c in chars if c["id"] == p["id"] and c["alive"]), None)]
        self.r.check("invariants.presence_only_for_the_living", not dead_present, tag=tag, rows=dead_present)
        conn_by = collections.Counter(ident_hex(c["identity"]) for c in conns)
        wrong = [p["id"] for p in pres if p["connections"] != conn_by.get(ident_hex(p["player"]), 0) or p["present"] != (conn_by.get(ident_hex(p["player"]), 0) > 0)]
        self.r.check("invariants.presence_counts_connections", not wrong, tag=tag, rows=wrong, presence=[{k: p[k] for k in ("id", "connections", "present", "ai")} for p in pres if p["id"] in wrong])
        return {"presence": len(pres), "connections": len(conns), "people": len(chars), "alive_people": sum(1 for c in chars if c["alive"])}

    def truth(self):
        """Each player's living character, inventory and vitals, and the dead count, as the
        authority has them."""
        db, token = self.ctx["db"], self.ctx["token"]
        out = {}
        for p, ident in enumerate(self.ctx["idents"]):
            mine = sql(db, f"SELECT * FROM character WHERE controller = 0x{ident}", token)
            pres = sql(db, f"SELECT * FROM presence WHERE player = 0x{ident}", token)
            alive = [c["id"] for c in mine if c["alive"]] + [x["id"] for x in pres if x["ai"]]
            cid = alive[0] if alive else None
            out[p] = {"alive": sorted(set(alive)), "dead": sorted(c["id"] for c in mine if not c["alive"]),
                      "inv": inv_of(db, token, cid) if cid else {}}
        return out


def explained(db, token, cid, since_ms, before, after):
    """Whether the authority's own experience rows for `cid` since `since_ms` explain the
    difference between two inventories: food spoils by itself ("Some of your berries spoiled
    (1 lost)"), the only change that happens with nobody acting."""
    lost = {k: before.get(k, 0) - after.get(k, 0) for k in set(before) | set(after)}
    if any(v < 0 for v in lost.values()):
        return False, []
    rows = sql(db, f"SELECT * FROM experience WHERE observer = {cid}", token)
    lines = [x["text"] for x in rows if x["at_ms"] >= since_ms]
    spoiled = collections.Counter()
    for t in lines:
        m = re.search(r"Some of your (\w+) spoiled \((\d+) lost\)", t)
        if m:
            spoiled[m.group(1)] += int(m.group(2))
    return all(spoiled.get(k, 0) >= v for k, v in lost.items() if v > 0), [t for t in lines if "spoil" in t]


def compare_truths(r, tag, before, after, ctx=None, since_ms=None):
    """Across a server restart or republish nothing a player owned or lived may change (food
    that spoils meanwhile excepted, when the authority says so)."""
    for p in before:
        b, a = before[p], after[p]
        r.check(f"{tag}.characters_kept", b["alive"] == a["alive"] and set(b["dead"]) <= set(a["dead"]), p=p, before=b, after=a)
        if b["inv"] == a["inv"]:
            r.check(f"{tag}.inventory_kept", True, p=p)
            continue
        why = (False, [])
        if ctx and since_ms and a["alive"] and b["alive"] == a["alive"]:
            why = explained(ctx["db"], ctx["token"], a["alive"][0], since_ms, b["inv"], a["inv"])
        r.check(f"{tag}.inventory_kept", why[0], p=p, before=b["inv"], after=a["inv"], explained_by=why[1])


# ---- the game client's plan --------------------------------------------------------------------

def game_plan(towns, seconds, rng, start):
    """A long headless script: walk between towns (click-to-move and held keys), gather, eat,
    greet, talk, rest; `rejoin` now and then (harmless when alive, arrives again when dead)."""
    steps = ["ready", "wait:5"]
    t = 0.0
    k = 0
    at = start
    while t < seconds:
        x, y = towns[k % len(towns)]
        k += 1
        # A click on a far town finds no path (docs/SOAK.md): click about 50 m ahead at a time.
        d = math.hypot(x - at[0], y - at[1])
        hops = max(1, math.ceil(d / 50))
        for j in range(1, hops):
            steps += [f"goto:{at[0] + (x - at[0]) * j / hops:.0f},{at[1] + (y - at[1]) * j / hops:.0f}", "wait:40"]
            t += 40
        at = (x, y)
        # Held keys: eight 3 s walks, each a new direction (the input→drawn measurement pairs
        # human_move inputs with the frame that draws them).
        walks = [f"walk:{rng.randrange(0, 360)}:3" + (":run" if j % 3 == 2 else "") for j in range(8)]
        steps += [f"goto:{x:.0f},{y:.0f}", "wait:45", "stop", *walks, "act:gather@nearest:berry_bush", "wait:6", "act:eat:berries@self", "wait:4",
                  "gesture:wave", "wait:3", "say:Hello! Lovely evening.", "wait:4", "panel:inventory", "wait:2", "panel:none", "rejoin", "wait:15"]
        t += 45 + 24 + 6 + 4 + 3 + 4 + 2 + 15 + 3
    return steps + ["quit"]


# ---- the run -----------------------------------------------------------------------------------

def run(a):
    procs = []
    try:
        _run(a, procs)
    finally:
        for p in procs:
            p.stop()


def _run(a, procs):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{'smoke' if a.smoke else 'soak'}-{stamp}"
    r = Run(EVID / name)
    PIDS.unlink(missing_ok=True)
    # verify-client's probe only opens `verify-client-*` databases (its guard against reference worlds).
    db = f"verify-client-soak-{stamp}"
    seconds = a.hours * 3600
    for f in (LOAD, GAME, MIND, WASM, PROBE):
        if not Path(f).exists():
            sys.exit(f"missing {f}: build it first (docs/SOAK.md, 'Reproduce')")
    git = sh("git", "-C", ROOT, "rev-parse", "HEAD").strip()
    dirty = sh("git", "-C", ROOT, "status", "--short", "--untracked-files=no").splitlines()
    neo_pw = secrets.token_hex(12)
    manifest = {
        "run": name, "db": db, "started_utc": stamp, "git": git, "dirty": dirty, "hours": a.hours, "players": a.players,
        "host": {"node": platform.node(), "os": platform.platform(), "cpu": sh("sysctl", "-n", "machdep.cpu.brand_string", check=False).strip(), "threads": os.cpu_count(),
                 "mem_gb": round(int(sh("sysctl", "-n", "hw.memsize", check=False).strip() or 0) / 2**30, 1), "load_at_start": os.getloadavg(),
                 "docker": sh("docker", "info", "--format", "{{.ServerVersion}} {{.NCPU}} CPUs {{.MemTotal}} B", check=False).strip()},
        "server": {"image": IMAGE, "container": STDB, "port": PORT, "volume": STDB_VOL, "memory_limit": "3g"},
        "neo4j": {"image": NEO_IMAGE, "container": NEO, "port": NEO_PORT, "volume": NEO_VOL, "heap": "512m", "pagecache": "256m", "memory_limit": "1500m"},
        "binaries": {p.name: sha256(p) for p in (LOAD, GAME, MIND, WASM)},
        "skills_rhai_sha256": sha256(ROOT / "living/scripts/skills.rhai"), "seed": "island",
        "minds": {"model": "fake (verify-llm fake_llm.py, scenario valid)", "neo4j": "on (own container)", "player_memory": "LIVING_PLAYER_MEMORY=1", "concurrency": 4},
        "network": "loopback through byte-counting relays; no added delay",
    }
    r.save("manifest.json", manifest)
    r.log(f"run {name}: db {db}, {a.players} players + 1 game client, {a.hours} h, git {git[:10]}{' (dirty)' if dirty else ''}")
    start_stdb(r)
    start_neo4j(r, neo_pw)
    stdb("publish", "-s", "local", "-b", "/wasm/living_authority.wasm", db, "--delete-data", "-y")
    stdb("call", "-s", "local", db, "install_script", json.dumps((ROOT / "living/scripts/skills.rhai").read_text()))
    token = admin_token()
    ident = json.loads(http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
    land = sql(db, "SELECT * FROM land", token)[0]
    world = sql(db, "SELECT * FROM world", token)[0]
    towns = [(s["x"], s["y"]) for s in sql(db, "SELECT * FROM settlement", token)]
    laws_takeover = TAKEOVER_S
    r.log(f"published: identity {ident[:12]}…, arrival ({land['arrive_x']:.0f}, {land['arrive_y']:.0f}), {len(towns)} settlements, day {world['day_ms'] / 60000:.0f} min")
    ctx = {"db": db, "token": token, "ident": ident, "neo_pw": neo_pw, "idents": [], "pids": lambda: {}}
    relay_p = Proc(r, "relay-players", [LOAD, "relay", "--listen", f"127.0.0.1:{PLAYERS_RELAY}", "--upstream", f"127.0.0.1:{PORT}", "--out", r.dir / "relay-players.jsonl"])
    relay_g = Proc(r, "relay-game", [LOAD, "relay", "--listen", f"127.0.0.1:{GAME_RELAY}", "--upstream", f"127.0.0.1:{PORT}", "--out", r.dir / "relay-game.jsonl"])
    procs += [relay_p, relay_g]
    fake = Proc(r, "fake-llm", [sys.executable, FAKE, "--port", FAKE_PORT, "--log", r.dir / "fake-requests.jsonl"], lines=False, stdin=False)
    procs.append(fake)
    models = {"default": "local", "profiles": {"local": {"base_url": f"http://127.0.0.1:{FAKE_PORT}/v1", "model": "fake-minds", "key_env": "LIVING_VERIFY_FAKE_KEY", "max_tokens": 256, "requests_per_minute": 6000}}}
    r.save("models.json", models)
    env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=URL, LIVING_DB=db, LIVING_RUN=db, LIVING_SEED="island", LIVING_MODELS=str(r.dir / "models.json"),
               LIVING_NEO4J_URI=f"127.0.0.1:{NEO_PORT}", LIVING_NEO4J_PASSWORD=neo_pw, LIVING_PLAYER_MEMORY="1", LIVING_LLM_PER_MIN="0", LIVING_CONCURRENCY="4",
               LIVING_TOKEN=token, LIVING_VERIFY_FAKE_KEY="dummy-local-only", NO_PROXY="127.0.0.1,localhost", RUST_LOG="info,neo4rs=warn,spacetimedb_sdk=warn")
    time.sleep(1)
    mind = Mind(r, env)
    mind.start()
    procs.append(mind)
    # Identities: the players and the game client.
    ids = []
    for _ in range(a.players + 1):
        v = json.loads(http("/v1/identity", {})[1])
        ids.append({"token": v["token"], "identity": v["identity"].removeprefix("0x").lower()})
    ctx["idents"] = [i["identity"] for i in ids[: a.players]]
    ctx["tokens"] = [i["token"] for i in ids[: a.players]]
    names = ["Ada", "Bram", "Cleo", "Dov", "Esme", "Finn", "Gus", "Hana", "Ivo", "Juno"]
    players = [{"token": ids[i]["token"], "name": f"Soak{names[i % len(names)]}", "confirmed": i % 2 == 0} for i in range(a.players)]
    load = Proc(r, "players", [LOAD, "soak"])
    procs.append(load)
    load.send({"uri": f"http://127.0.0.1:{PLAYERS_RELAY}", "db": db, "events": str(r.dir / "events.jsonl"), "players": players})
    ready = load.expect("ready", 300)
    r.log(f"{a.players} players ready in {ready['after_s']:.1f} s: {ready['players']}")
    # The game client, through its own relay.
    game_dir = r.dir / "game"
    game_dir.mkdir(exist_ok=True)
    token_file = r.dir / "game.token"
    token_file.write_text(ids[a.players]["token"])
    rng = random.Random(7)
    plan = game_plan(towns, seconds + 600, rng, (land["arrive_x"], land["arrive_y"]))
    (game_dir / "plan.txt").write_text("\n".join(plan) + "\n")
    genv = dict(os.environ, LIVING_SERVER=f"http://127.0.0.1:{GAME_RELAY}", LIVING_DB=db, LIVING_GAME_TOKEN=str(token_file), LIVING_GAME_NAME="SoakWatcher",
                LIVING_GAME_LIVE=str(game_dir), LIVING_GAME_LIVE_PLAN=";".join(plan), LIVING_GAME_FRAMES=str(game_dir / "frames.csv"), LIVING_GAME_PERF="hitch=100",
                RUST_LOG="info,wgpu=warn,naga=warn,spacetimedb_sdk=warn")
    game = Proc(r, "game", [GAME], env=genv, lines=False, stdin=False)
    procs.append(game)
    t = time.time()
    gid = None
    while time.time() - t < 300 and game.p.poll() is None:
        rows = sql(db, "SELECT id FROM character WHERE name = 'SoakWatcher' AND alive = true", token)
        if rows:
            gid = rows[0]["id"]
            break
        time.sleep(2)
    r.log(f"game client joined as #{gid}" if gid else "WARNING: the game client did not join")
    ctx["pids"] = lambda: {"players": load.pid(), "game": game.pid(), "mind": mind.pid(), "fake_llm": fake.pid(), "relay_players": relay_p.pid(), "relay_game": relay_g.pid()}
    sampler = Sampler(r, ctx)
    sampler.start()
    checker = Checker(r, ctx)
    # Restored-state events from the players, checked as they come.
    done_box = {}

    def drain():
        while True:
            v = load.q.get()
            if v.get("event") == "restored":
                threading.Thread(target=checker.restored, args=(v,), daemon=True).start()
            elif v.get("event") in ("snap", "done"):
                done_box.setdefault(v["event"], queue.Queue()).put(v)

    threading.Thread(target=drain, daemon=True).start()

    def snap(tag):
        q = done_box.setdefault("snap", queue.Queue())
        load.send({"cmd": "snap", "tag": tag})
        end = time.time() + 20
        while time.time() < end:
            try:
                v = q.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                break
            if v.get("tag") == tag:
                return v
        return None

    marks = {"go": time.time()}
    r.save("marks.json", marks)
    t0 = marks["go"]
    ctx["t0"] = t0
    S = seconds
    scale = S / (4.25 * 3600)
    # ---- the timeline -----------------------------------------------------------------------
    events = []
    n = a.players
    # Disconnects: every player several times; every second one of each player's past takeover_s.
    k = 0
    at = 300 * scale
    while at < S - 600 * scale:
        p = k % n
        long_ = (k // n) % 2 == 1
        secs = rng.uniform(45, 110) if long_ else rng.uniform(4, 20)
        if a.smoke:
            secs = rng.uniform(36, 45) if long_ else rng.uniform(3, 8)
        events.append((at, "drop", {"p": p, "secs": round(secs, 1), "long": long_}))
        k += 1
        at += rng.uniform(240, 420) * scale
    hunts = 0
    at = 200 * scale
    while at < S - 300 * scale:
        events.append((at, "hunt", {}))
        hunts += 1
        at += rng.uniform(300, 480) * scale
    at = 900 * scale
    while at < S - 900 * scale:
        events.append((at, "duel", {}))
        at += rng.uniform(1500, 2100) * scale
    events += [
        (1.0 * 3600 * scale, "game_cut", {"secs": 10}),
        (1.5 * 3600 * scale, "mind_restart", {}),
        (2.0 * 3600 * scale, "stdb_restart", {}),
        (2.5 * 3600 * scale, "game_cut", {"secs": 75 if not a.smoke else 40}),
        (3.0 * 3600 * scale, "republish", {}),
        (3.3 * 3600 * scale, "players_cut", {"secs": 8}),
        (0.4 * 3600 * scale, "privacy", {}),
        (3.6 * 3600 * scale, "privacy", {}),
    ]
    for h in range(1, int(a.hours * 4) + 1):
        events.append((h * 900 * scale, "invariants", {}))
    events.sort(key=lambda e: e[0])
    r.save("timeline.json", [{"at_s": round(e[0], 1), "what": e[1], **e[2]} for e in events])
    r.log(f"timeline: {len(events)} events over {S / 3600:.2f} h")
    for at, what, arg in events:
        wait = t0 + at - time.time()
        if wait > 0:
            time.sleep(wait)
        if game.p.poll() is not None:
            r.log(f"game client exited {game.p.returncode}")
            r.disruption(kind="game_exit", code=game.p.returncode)
            game_restart = Proc(r, "game", [GAME], env=genv, lines=False, stdin=False)
            procs.append(game_restart)
            game = game_restart
        try:
            do_event(r, ctx, checker, load, snap, mind, relay_p, relay_g, what, arg, rng, a, laws_takeover, game)
        except Exception as e:  # noqa: BLE001 - an event that fails is a finding, the run goes on
            r.log(f"event {what} failed: {e}")
            r.disruption(kind="event_failed", what=what, error=str(e))
    wait = t0 + S - time.time()
    if wait > 0:
        time.sleep(wait)
    marks["end_play"] = time.time()
    r.log("time is up: final snapshot and invariants")
    final_snap = snap("final")
    try:
        final_truth = checker.truth()
        r.save("final.json", {"snap": final_snap, "truth": final_truth, "invariants": checker.invariants("final")})
    except Exception as e:  # noqa: BLE001
        r.log(f"final truth: {e}")
    load.send({"cmd": "stop"})
    try:
        done = done_box.setdefault("done", queue.Queue()).get(timeout=60)
        r.save("players-done.json", done)
    except queue.Empty:
        r.log("players: no done line")
    sampler.stop.set()
    sampler.join(60)
    marks["end"] = time.time()
    r.save("marks.json", marks)
    r.save("mind-exits.json", mind.exits)
    mind.stop()
    for p in procs:
        if p.name.startswith("relay"):
            try:
                p.p.stdin.close()
                p.p.wait(15)
            except Exception:  # noqa: BLE001
                p.stop()
    game_code = game.stop(signal.SIGTERM, 20)
    r.log(f"game client stopped ({game_code})")
    r.log("saving the module log")
    with gzip.open(r.dir / "module.log.gz", "wt") as f:
        f.write(stdb("logs", "-s", "local", db, "-n", "2000000", check=False, timeout=1800))
    sh("docker", "logs", STDB, check=False, timeout=600)
    with gzip.open(r.dir / "stdb-container.log.gz", "wt") as f:
        f.write(subprocess.run(["docker", "logs", STDB], capture_output=True, text=True, timeout=600).stderr + "\n---stdout---\n" +
                subprocess.run(["docker", "logs", STDB], capture_output=True, text=True, timeout=600).stdout)
    analyze(r.dir)
    return mind


def do_event(r, ctx, checker, load, snap, mind, relay_p, relay_g, what, arg, rng, a, takeover_s, game):
    db, token = ctx["db"], ctx["token"]
    if what == "drop":
        p, secs = arg["p"], arg["secs"]
        cid = None
        try:
            cid = sql(db, f"SELECT id FROM character WHERE controller = 0x{ctx['idents'][p]} AND alive = true", token)
            cid = cid[0]["id"] if cid else None
        except Exception:  # noqa: BLE001
            pass
        r.log(f"drop: player {p} (#{cid}) away {secs} s{' (past takeover)' if arg['long'] else ''}")
        r.disruption(kind="drop", p=p, secs=secs, long=arg["long"], character=cid)
        load.send({"cmd": "drop", "p": p, "secs": secs})
        if arg["long"] and cid:
            # Look in on the character while its person is away: the minds have it after takeover_s.
            def look():
                time.sleep(min(secs - 3, takeover_s + 6))
                try:
                    pr = sql(db, f"SELECT * FROM presence WHERE id = {cid}", token)
                    ch = sql(db, f"SELECT * FROM character WHERE id = {cid}", token)
                except Exception as e:  # noqa: BLE001
                    r.check("takeover.readable", False, p=p, error=str(e))
                    return
                if ch and not ch[0]["alive"]:
                    r.check("takeover.minds_have_it", True, p=p, character=cid, note="died before the takeover check")
                    return
                ok = bool(pr) and pr[0]["ai"] and not pr[0]["present"] and ch and ch[0]["ai"]
                r.check("takeover.minds_have_it", ok, p=p, character=cid, presence=pr, ai=ch[0]["ai"] if ch else None, after_s=min(secs - 3, takeover_s + 6))
            threading.Thread(target=look, daemon=True).start()
        elif cid:
            def look_short():
                time.sleep(max(1.0, secs - 2))
                try:
                    pr = sql(db, f"SELECT * FROM presence WHERE id = {cid}", token)
                except Exception as e:  # noqa: BLE001
                    r.check("presence.readable", False, p=p, error=str(e))
                    return
                if pr:
                    r.check("presence.away_not_taken", (not pr[0]["present"]) and not pr[0]["ai"], p=p, character=cid, presence=pr)
            threading.Thread(target=look_short, daemon=True).start()
    elif what == "hunt":
        wolves = sql(db, "SELECT b.id, b.x, b.y FROM body b JOIN character c ON b.id = c.id WHERE c.kind = 'wolf' AND c.alive = true", token)
        players = sql(db, "SELECT b.id, b.x, b.y, c.controller FROM body b JOIN character c ON b.id = c.id WHERE c.kind = 'person' AND c.alive = true AND c.ai = false", token)
        ours = {ident_hex(pl["controller"]): pl for pl in players}
        cands = [(p, ours[i]) for p, i in enumerate(ctx["idents"]) if i in ours]
        if not wolves or not cands:
            r.log("hunt: no wolf or no player")
            return
        p, pl = rng.choice(cands)
        w = min(wolves, key=lambda w: (w["x"] - pl["x"]) ** 2 + (w["y"] - pl["y"]) ** 2)
        d = math.hypot(w["x"] - pl["x"], w["y"] - pl["y"])
        r.log(f"hunt: player {p} → wolf #{w['id']} {d:.0f} m away")
        load.send({"cmd": "hunt", "p": p, "x": w["x"], "y": w["y"], "secs": int(min(600, 90 + d / 1.2))})
    elif what == "duel":
        players = sql(db, "SELECT b.id, b.x, b.y, c.controller FROM body b JOIN character c ON b.id = c.id WHERE c.kind = 'person' AND c.alive = true AND c.ai = false", token)
        ours = {ident_hex(pl["controller"]): pl for pl in players}
        cands = [(p, ours[i]) for p, i in enumerate(ctx["idents"]) if i in ours]
        if len(cands) < 2:
            return
        pairs = sorted(((math.hypot(x[1]["x"] - y[1]["x"], x[1]["y"] - y[1]["y"]), x[0], y[0], x[1], y[1]) for i, x in enumerate(cands) for y in cands[i + 1:]))
        d, pa, pb, ba, bb = pairs[0]
        mx, my = (ba["x"] + bb["x"]) / 2, (ba["y"] + bb["y"]) / 2
        r.log(f"duel: players {pa} and {pb} ({d:.0f} m apart) meet at ({mx:.0f}, {my:.0f}) and spar")
        r.disruption(kind="duel", a=pa, b=pb, d=d)
        meet = int(min(400, 40 + d / 1.2))
        load.send({"cmd": "goto", "p": pa, "x": mx, "y": my, "secs": meet})
        load.send({"cmd": "goto", "p": pb, "x": mx + 2, "y": my, "secs": meet})

        def fight():
            time.sleep(meet)
            load.send({"cmd": "duel", "p": pa, "foe": pb, "secs": 240})
            load.send({"cmd": "duel", "p": pb, "foe": pa, "secs": 240})
        threading.Thread(target=fight, daemon=True).start()
    elif what == "game_cut":
        r.log(f"game client: network outage {arg['secs']} s (relay cut)")
        r.disruption(kind="game_cut", secs=arg["secs"])
        relay_g.send(f"cut {arg['secs']}")
        gid = sql(db, "SELECT id FROM character WHERE name = 'SoakWatcher' AND alive = true", token)
        gid = gid[0]["id"] if gid else None
        if gid and arg["secs"] > takeover_s:
            time.sleep(takeover_s + 6)
            pr = sql(db, f"SELECT * FROM presence WHERE id = {gid}", token)
            r.check("takeover.game_client_taken", bool(pr) and pr[0]["ai"], presence=pr)
            time.sleep(max(0, arg["secs"] - takeover_s - 6) + 25)
            pr = sql(db, f"SELECT * FROM presence WHERE id = {gid}", token)
            ch = sql(db, f"SELECT * FROM character WHERE id = {gid}", token)
            r.check("handback.game_client_back", bool(pr) and pr[0]["present"] and not pr[0]["ai"] and ch and not ch[0]["ai"], presence=pr, character=ch)
        elif gid:
            time.sleep(arg["secs"] + 25)
            pr = sql(db, f"SELECT * FROM presence WHERE id = {gid}", token)
            r.check("presence.game_client_back", bool(pr) and pr[0]["present"] and not pr[0]["ai"], presence=pr)
    elif what == "players_cut":
        r.log(f"every player: network outage {arg['secs']} s (relay cut)")
        r.disruption(kind="players_cut", secs=arg["secs"])
        relay_p.send(f"cut {arg['secs']}")
    elif what == "mind_restart":
        r.log("mind service: restart (SIGTERM, then the supervisor starts it again)")
        r.disruption(kind="mind_restart")
        mind.restart()
    elif what in ("stdb_restart", "republish"):
        load.send({"cmd": "hold"})
        time.sleep(6)
        before_snap = snap(f"{what}-before")
        before = checker.truth()
        before_ms = int(time.time() * 1000) - 2000
        checker.invariants(f"{what}-before")
        r.save(f"{what}-before.json", {"snap": before_snap, "truth": before})
        t1 = time.time()
        if what == "stdb_restart":
            r.log("SpacetimeDB: container restart (docker stop: SIGINT, 60 s grace; then docker start)")
            res = subprocess.run(["docker", "stop", "-t", "60", STDB], capture_output=True, text=True, timeout=180)
            stopped = time.time()
            state = sh("docker", "inspect", "-f", "{{.State.ExitCode}} {{.State.OOMKilled}}", STDB, check=False).split()
            r.log(f"stopped in {stopped - t1:.1f} s, exit code {state[0] if state else '?'} ({'graceful' if state and state[0] == '0' else 'FORCED or failed'})")
            sh("docker", "start", STDB)
            up = ping(300)
            t2 = time.time()
            r.disruption(kind="stdb_restart", stop_s=round(stopped - t1, 1), exit_code=state[0] if state else None, oom=state[1] if len(state) > 1 else None, down_s=round(t2 - t1, 1), up=up, stop_output=res.stdout + res.stderr)
        else:
            r.log("module republish, same code, data kept (spacetime publish without --delete-data)")
            out = stdb("publish", "-s", "local", "-b", "/wasm/living_authority.wasm", db, "-y", check=False, timeout=600)
            t2 = time.time()
            r.log(f"republished in {t2 - t1:.1f} s: {out.strip().splitlines()[-1][:200] if out.strip() else ''}")
            r.disruption(kind="republish", s=round(t2 - t1, 1), output=out[-1500:])
        # The world still answers, ticks, and holds what it held.
        time.sleep(5)
        try:
            k1 = sql(db, "SELECT * FROM stats", token)[0]
            time.sleep(3)
            k2 = sql(db, "SELECT * FROM stats", token)[0]
            r.check(f"{what}.ticks_resume", k2.get("ticks", 0) > k1.get("ticks", 0), before=k1.get("ticks"), after=k2.get("ticks"))
        except Exception as e:  # noqa: BLE001
            r.check(f"{what}.ticks_resume", False, error=str(e))
        after = checker.truth()
        compare_truths(r, what, before, after, ctx, before_ms)
        # Clients come back by themselves (retry every 3 s): wait, then compare what they hold.
        time.sleep(25)
        after_snap = snap(f"{what}-after")
        r.save(f"{what}-after.json", {"snap": after_snap, "truth": after})
        now_truth = checker.truth()
        if after_snap:
            for pl in after_snap["players"]:
                b = next((x for x in (before_snap or {}).get("players", []) if x["p"] == pl["p"]), None)
                away = b is not None and not b["connected"]
                r.check(f"{what}.client_reconnected", pl["connected"] or away, p=pl["p"], reconnects=pl["reconnects"], away_before=away)
                if pl["connected"]:
                    # What the client holds now against the authority now (the world went on:
                    # berries spoil, hunger grows), and the same character as before unless it died.
                    tr = now_truth[pl["p"]]
                    alive = tr["alive"][0] if tr["alive"] else None
                    inv = {k: v for k, v in pl["inv"].items() if v}
                    ok = pl["me"] == alive and (alive is None or inv == tr["inv"])
                    if not ok and alive is not None and pl["me"] == alive:
                        # The client's snapshot came a moment before the truth: let the authority
                        # say whether food spoiled in between.
                        ok = explained(db, token, alive, before_ms, inv, tr["inv"])[0]
                    same = b is None or b["me"] in (None, pl["me"]) or b["me"] in tr["dead"]
                    r.check(f"{what}.client_state_back", ok and same, p=pl["p"], before={"me": b and b["me"], "inv": b and b["inv"]}, client={"me": pl["me"], "inv": inv}, truth=tr)
        checker.invariants(f"{what}-after")
        load.send({"cmd": "resume"})
    elif what == "invariants":
        res = checker.invariants(f"t+{int(time.time() - ctx.get('t0', time.time()))}")
        r.log(f"invariants: {res}")
    elif what == "privacy":
        privacy(r, ctx, load)


def privacy(r, ctx, load):
    """verify-client's perception checks on this world, after the disruptions: every private and
    scoped table is refused to an anonymous client and to a player (WebSocket subscription and
    HTTP SQL); a player's own-state views hold only its own rows; its seen_* views hold its own
    character and what the authority says it perceives (`perceived`)."""
    db, token = ctx["db"], ctx["token"]
    lists = client_lists()
    out = {"tables": {}, "players": {}}
    r.log(f"privacy: {len(lists['PRIVATE']) + len(lists['SCOPED'])} tables refused to anonymous and a player; own-state and seen views of every player")

    def run_probe(queries, tok, seconds=0, stream=False):
        """verify-client's probe; `stream` returns the rows received (its `initial` event)."""
        req = {"uri": URL, "db": db, "token": tok, "queries": queries, "seconds": seconds, "drop_file": None, "until_actor": None, "stream": stream}
        res = subprocess.run([str(PROBE)], input=json.dumps(req), text=True, capture_output=True, timeout=90)
        try:
            lines = [json.loads(l) for l in res.stdout.strip().splitlines() if l.strip()]
        except ValueError:
            return {"status": "error", "error": res.stdout[-300:] + res.stderr[-300:]}
        if not lines:
            return {"status": "error", "error": res.stderr[-300:]}
        out = dict(lines[-1])
        initial = next((l for l in lines if l.get("event") == "initial"), None)
        if initial is not None:
            out["tables"] = initial.get("tables", {})
            out.setdefault("status", "applied")
        return out

    v = json.loads(http("/v1/identity", {})[1])
    stranger = v["token"]
    for table in lists["PRIVATE"] + lists["SCOPED"]:
        anon = run_probe([f"SELECT * FROM {table}"], None)
        other = run_probe([f"SELECT * FROM {table}"], stranger)
        player = run_probe([f"SELECT * FROM {table}"], ctx["tokens"][0])
        code_a, _ = http(f"/v1/database/{db}/sql", f"SELECT * FROM {table}", None, raw=True)
        code_p, _ = http(f"/v1/database/{db}/sql", f"SELECT * FROM {table}", ctx["tokens"][0], raw=True)
        ok = all(x.get("status") == "rejected" for x in (anon, other, player)) and code_a != 200 and code_p != 200
        out["tables"][table] = {"anon": anon.get("status"), "stranger": other.get("status"), "player": player.get("status"), "sql_anon": code_a, "sql_player": code_p}
        r.check("privacy.private_table_refused", ok, table=table, **out["tables"][table])
    # Each player, through its own identity (a second connection, as a second tab would be): its
    # own-state views hold only its own rows; seen_* hold its character and what the authority
    # says it perceives (`perceived`, swept every 200 ms, so a body may be entering or leaving).
    views = ["seen_bodies", "seen_characters", "my_characters", "my_inventory", "my_vitals", "my_experience", "my_know_how"]
    # Only players connected now: a probe connection of an away player's identity is that
    # person coming back (it would hand control back and restart the takeover clock).
    connected = set()
    for attempt in range(12):
        load.send({"cmd": "snap", "tag": f"privacy-{attempt}"})
        time.sleep(3)
        for v in list(load.lines)[::-1]:
            if v.get("event") == "snap" and v.get("tag") == f"privacy-{attempt}":
                connected = {pl["p"] for pl in v["players"] if pl["connected"]}
                break
        if len(connected) >= max(1, len(ctx["tokens"]) - 2):
            break
        time.sleep(5)
    r.log(f"privacy: views of players {sorted(connected)} (connected now)")
    for p, tok in enumerate(ctx["tokens"]):
        if p not in connected:
            continue
        ident = ctx["idents"][p]
        got = run_probe([f"SELECT * FROM {v}" for v in views], tok, seconds=1, stream=True)
        try:
            perceived = {row["body"] for row in sql(db, f"SELECT * FROM perceived WHERE viewer = 0x{ident}", token)}
            mine = sql(db, f"SELECT * FROM character WHERE controller = 0x{ident}", token)
        except Exception as e:  # noqa: BLE001
            r.check("privacy.truth_readable", False, p=p, error=str(e))
            continue
        tables = got.get("tables") or {}
        own_ids = {c["id"] for c in mine}
        alive_own = {c["id"] for c in mine if c["alive"] and not c["ai"]}
        seen = {row.get("id") for row in tables.get("seen_bodies", [])}
        extra = seen - perceived - alive_own
        missing = (perceived | alive_own) - seen
        r.check("privacy.seen_bodies_only_perceived", got.get("status") == "applied" and not extra and alive_own <= seen, p=p, seen=len(seen), perceived=len(perceived), extra=sorted(extra)[:20], missing=sorted(missing)[:20])
        chars = {row.get("id") for row in tables.get("seen_characters", [])}
        r.check("privacy.seen_characters_only_perceived", not (chars - perceived - alive_own), p=p, extra=sorted(chars - perceived - alive_own)[:20])
        foreign_inv = [row for row in tables.get("my_inventory", []) if row.get("owner") not in own_ids]
        foreign_chars = [row.get("id") for row in tables.get("my_characters", []) if row.get("id") not in own_ids]
        foreign_vit = [row.get("id") for row in tables.get("my_vitals", []) if row.get("id") not in own_ids]
        foreign_exp = [row.get("id") for row in tables.get("my_experience", []) if row.get("observer") not in own_ids]
        r.check("privacy.own_state_only", not (foreign_inv or foreign_chars or foreign_vit or foreign_exp), p=p,
                foreign={"inventory": foreign_inv[:5], "characters": foreign_chars[:5], "vitals": foreign_vit[:5], "experience": foreign_exp[:5]},
                held={k: len(v) for k, v in tables.items()} if isinstance(tables, dict) else None)
        out["players"][p] = {"status": got.get("status"), "held": {k: len(v) for k, v in tables.items()} if isinstance(tables, dict) else None, "perceived": len(perceived)}
    r.save("privacy.json", out)


# ---- analysis ----------------------------------------------------------------------------------

def hist_mean(lines, name, label_filter=None):
    """Sum and count of a Prometheus histogram over the matching label sets."""
    s = c = 0.0
    for l in lines:
        if not l.startswith(name):
            continue
        if label_filter and label_filter not in l:
            continue
        if l.startswith(name + "_sum"):
            s += float(l.rsplit(" ", 1)[1])
        elif l.startswith(name + "_count"):
            c += float(l.rsplit(" ", 1)[1])
    return s, c


def metric(lines, name, label_filter=None):
    total = None
    for l in lines:
        if l.startswith(name + "{") or l.startswith(name + " "):
            if label_filter and label_filter not in l:
                continue
            total = (total or 0.0) + float(l.rsplit(" ", 1)[1])
    return total


def opn(path):
    """A run file, or its gzipped copy (evidence is compressed after the run)."""
    path = Path(path)
    if path.exists():
        return path.open(errors="replace")
    return gzip.open(str(path) + ".gz", "rt", errors="replace")


def exists(path):
    return Path(path).exists() or Path(str(path) + ".gz").exists()


def analyze(d):
    d = Path(d)
    rep = {}
    marks = json.loads((d / "marks.json").read_text())
    t0 = marks["go"]
    t_end = marks.get("end_play", marks.get("end", time.time()))
    hours = max(1, math.ceil((t_end - t0) / 3600 - 0.05))
    bins = [(t0 + 3600 * h, min(t_end, t0 + 3600 * (h + 1))) for h in range(hours)]
    disruptions = [json.loads(l) for l in (d / "disruptions.jsonl").read_text().splitlines()] if (d / "disruptions.jsonl").exists() else []
    checks = [json.loads(l) for l in (d / "checks.jsonl").read_text().splitlines()] if (d / "checks.jsonl").exists() else []
    # ---- checks
    by = collections.defaultdict(lambda: [0, 0])
    for c in checks:
        by[c["check"]][0 if c["ok"] else 1] += 1
    rep["checks"] = {k: {"pass": v[0], "fail": v[1]} for k, v in sorted(by.items())}
    rep["check_failures"] = [c for c in checks if not c["ok"]][:200]
    rep["disruptions"] = disruptions
    # ---- inputs and outcomes
    ins, res = {}, {}
    kinds = collections.Counter()
    deaths, alive, outcomes, discs, restored, connect_fail = [], [], collections.Counter(), [], [], collections.Counter()
    errs = collections.Counter()
    with opn(d / "events.jsonl") as f:
        for line in f:
            try:
                v = json.loads(line)
            except ValueError:
                continue
            k = v.get("k") or v.get("event")
            kinds[k] += 1
            if k == "in":
                ins[(v["p"], v["n"])] = v
            elif k == "res":
                res[(v["p"], v["n"])] = v
            elif k == "death":
                deaths.append(v)
            elif k == "alive":
                alive.append(v)
            elif k == "act_outcome":
                txt = v["text"]
                if v["ok"]:
                    m = re.match(r"You did what you had decided: (\w+)", txt)
                    outcomes["done " + (m.group(1) if m else "?")] += 1
                else:
                    m = re.match(r"What you had decided did not work out: (\w+)[^:]*: (.*)", txt)
                    outcomes["failed " + (f"{m.group(1)}: {re.sub(r'[0-9]+', 'N', m.group(2))[:70]}" if m else txt[:80])] += 1
            elif k == "disconnected":
                discs.append(v)
            elif k == "restored":
                restored.append(v)
            elif k in ("connect_failed", "connect_error"):
                connect_fail[re.sub(r"[0-9a-f]{16,}", "…", str(v.get("e")))[:120]] += 1
    rep["event_kinds"] = dict(kinds)
    rep["act_outcomes"] = dict(outcomes.most_common(60))
    rep["deaths"] = {"n": len(deaths), "causes": dict(collections.Counter(re.sub(r"#\d+", "#N", str(x.get("cause")))[:60] for x in deaths).most_common(20)), "arrivals": len(alive)}
    rep["disconnects"] = {"n": len(discs), "why": dict(collections.Counter(str(x.get("e"))[:100] for x in discs).most_common(10)), "reconnects": len(restored),
                          "connect_failures": dict(connect_fail.most_common(10)),
                          "connect_ms": summary([x["connect_ms"] for x in restored if x.get("connect_ms") is not None]),
                          "down_ms_unplanned": summary([x["down_ms"] for x in restored if x.get("down_ms") is not None and not x.get("planned")])}
    statuses = collections.Counter()
    for key, v in res.items():
        st = v.get("st", "")
        if st != "ok":
            i = ins.get(key, {})
            errs[f"{i.get('r')} {i.get('act', '')}: {re.sub(r'[0-9]+', 'N', st)[:110]}"] += 1
        statuses["ok" if st == "ok" else "err"] += 1
    rep["reducer_replies"] = {"inputs": len(ins), "replies": len(res), "unanswered": len(set(ins) - set(res)), **statuses, "errors": dict(errs.most_common(40))}
    # The server's clock against the Mac's: off ∈ [max(srv − reply), min(srv − send)] per minute.
    # Docker Desktop's VM clock wanders by about a millisecond, so the bounds can cross; the
    # midpoint is used either way and the half-width is reported.
    pairs = [(ins[k], res[k]) for k in res if k in ins and res[k].get("srv")]
    offs = collections.defaultdict(lambda: [-1e18, 1e18])
    for i, rr in pairs:
        w = int((i["ts"] - t0 * 1e6) // 60e6)
        o = offs[w]
        o[0] = max(o[0], rr["srv"] - rr["ts"])
        o[1] = min(o[1], rr["srv"] - i["ts"])
    rep["clock_offset_us"] = {"half_width": summary([(o[1] - o[0]) / 2 for o in offs.values()]), "midpoint": summary([(o[0] + o[1]) / 2 for o in offs.values()])}
    lat = []
    for h, (a_, b_) in enumerate(bins):
        row = {"hour": h + 1}
        for kind, conf in (("move", True), ("move", False), ("act", None), ("say", None), ("skill", None)):
            xs, srv = [], []
            for i, rr in pairs:
                if i["r"] != kind or not (a_ * 1e6 <= i["ts"] < b_ * 1e6) or (conf is not None and i.get("c") != conf):
                    continue
                xs.append((rr["ts"] - i["ts"]) / 1000)
                w = int((i["ts"] - t0 * 1e6) // 60e6)
                o = offs.get(w)
                if o:
                    srv.append((rr["ts"] - (rr["srv"] - (o[0] + o[1]) / 2)) / 1000)
            label = kind + ("" if conf is None else ("_confirmed" if conf else "_unconfirmed"))
            row[label] = summary(xs)
            row[label + "_receipt_to_reply"] = summary(srv)
        lat.append(row)
    rep["latency_by_hour"] = lat
    # ---- samples: growth
    samples = []
    with gzip.open(d / "samples.jsonl.gz", "rt") as f:
        for line in f:
            try:
                samples.append(json.loads(line))
            except ValueError:
                pass
    rep["samples"] = len(samples)
    series = collections.defaultdict(list)
    for s in samples:
        t = (s["t"] - t0) / 3600
        m = s.get("metrics") or []
        if m:
            for nm, key, lf in (("wal_bytes", "spacetime_message_log_size_bytes", None), ("wasm_memory", "spacetime_worker_wasm_memory_bytes", None),
                                ("jemalloc_resident", "jemalloc_resident_bytes", None), ("jemalloc_allocated", "jemalloc_allocated_bytes", None),
                                ("instance_queue", "spacetime_worker_instance_operation_queue_length", None)):
                v = metric(m, key, lf)
                if v is not None:
                    series[nm].append((t, v))
        cg = s.get("cgroup") or {}
        if cg.get("memory_current"):
            series["stdb_cgroup_mem"].append((t, cg["memory_current"]))
        if cg.get("anon"):
            series["stdb_cgroup_anon"].append((t, cg["anon"]))
        if cg.get("cpu_usec"):
            series["stdb_cpu_usec"].append((t, cg["cpu_usec"]))
        for cn, cv in (s.get("containers") or {}).items():
            if cv.get("mem"):
                series[f"{cn}_mem"].append((t, cv["mem"]))
        for pn, pv in (s.get("procs") or {}).items():
            if pv:
                series[f"{pn}_rss"].append((t, pv["rss_kb"] * 1024))
                series[f"{pn}_cpu_s"].append((t, pv["cpu_s"]))
        if isinstance(s.get("rows"), dict):
            for tb, n in s["rows"].items():
                if isinstance(n, int):
                    series[f"rows.{tb}"].append((t, n))
        if isinstance(s.get("disk"), list):
            for size, path in s["disk"]:
                key = "disk." + ("clog" if path.endswith("/clog") else "snapshots" if path.endswith("snapshots") else "module_logs" if path.endswith("module_logs") else "data_total")
                series[key].append((t, size))
        if isinstance(s.get("neo4j"), dict) and s["neo4j"].get("nodes") is not None:
            series["neo4j.nodes"].append((t, s["neo4j"]["nodes"]))
            series["neo4j.edges"].append((t, s["neo4j"]["edges"]))
    growth = {}
    for nm, pts in sorted(series.items()):
        if len(pts) < 2:
            continue
        first, last = pts[0], pts[-1]
        span = last[0] - first[0]
        # The rate over the second half: what is still growing late.
        half = [p for p in pts if p[0] >= first[0] + span / 2]
        late = (half[-1][1] - half[0][1]) / (half[-1][0] - half[0][0]) if len(half) > 1 and half[-1][0] > half[0][0] else None
        early_pts = [p for p in pts if p[0] <= first[0] + span / 2]
        early = (early_pts[-1][1] - early_pts[0][1]) / (early_pts[-1][0] - early_pts[0][0]) if len(early_pts) > 1 and early_pts[-1][0] > early_pts[0][0] else None
        by_hour = []
        for h in range(hours + 1):
            near = min(pts, key=lambda p: abs(p[0] - h))
            if abs(near[0] - h) < 0.1:
                by_hour.append(near[1])
        growth[nm] = {"first": first[1], "last": last[1], "max": max(p[1] for p in pts), "per_hour": (last[1] - first[1]) / span if span > 0 else None,
                      "per_hour_first_half": early, "per_hour_second_half": late, "at_hour": by_hour}
    rep["growth"] = growth
    # Server-side latency from the histograms, per hour: queue wait and the transaction.
    srv = []
    for (a_, b_) in bins:
        pick = [s for s in samples if s.get("metrics") and a_ <= s["t"] <= b_]
        if len(pick) < 2:
            srv.append(None)
            continue
        row = {}
        for red in ("human_move", "human_act", "human_say", "use_skill", "tick", "join", "housekeeping", "mind_act", "mind_say", "mind_install"):
            out = {}
            for nm, key in (("wait", "spacetime_reducer_wait_time_sec"), ("tx", "spacetime_reducer_plus_query_duration_sec")):
                # Sum the deltas between consecutive samples; a counter that went back was reset
                # by the server's restart, and counts from zero.
                ds = dc = 0.0
                prev = hist_mean(pick[0]["metrics"], key, f'reducer="{red}"')
                for smp in pick[1:]:
                    cur = hist_mean(smp["metrics"], key, f'reducer="{red}"')
                    if cur[1] >= prev[1] and cur[0] >= prev[0]:
                        ds, dc = ds + cur[0] - prev[0], dc + cur[1] - prev[1]
                    else:
                        ds, dc = ds + cur[0], dc + cur[1]
                    prev = cur
                if dc > 0:
                    out[nm + "_mean_ms"] = round(ds / dc * 1000, 3)
                    out["n"] = int(dc)
            row[red] = out
        srv.append(row)
    rep["server_latency_by_hour"] = srv
    # ---- the game client
    g = d / "game"
    frames = []
    if (g / "frames.csv").exists():
        with (g / "frames.csv").open() as f:
            for line in f:
                p = line.strip().split(",")
                if len(p) >= 3 and p[0].isdigit():
                    frames.append((int(p[0]) / 1e6, int(p[1]) / 1000, int(p[2]) / 1000))
    fr = []
    for h, (a_, b_) in enumerate(bins):
        xs = [x for x in frames if a_ <= x[0] < b_]
        iv = [x[1] for x in xs]
        wk = [x[2] for x in xs]
        fr.append({"hour": h + 1, "frames": len(xs), "fps": round(len(xs) / max(1, b_ - a_), 1), "interval": summary(iv, 2), "work": summary(wk, 2),
                   "over_25ms": sum(1 for x in iv if x > 25), "over_50ms": sum(1 for x in iv if x > 50), "over_250ms": sum(1 for x in iv if x > 250), "over_1s": sum(1 for x in iv if x > 1000),
                   "worst": sorted(((round(x[1]), datetime.fromtimestamp(x[0], timezone.utc).strftime("%H:%M:%S")) for x in xs), reverse=True)[:5]})
    rep["frames_by_hour"] = fr
    glog = d / "game.stderr"
    clock, gwarn = [], collections.Counter()
    if exists(glog):
        rx = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z).*clock: input→drawn mine \[n (\d+) p50 (\d+) p95 (\d+) max (\d+)\]")
        for line in opn(glog):
            m = rx.search(line)
            if m:
                ts = datetime.strptime(m.group(1)[:26], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp()
                clock.append((ts, int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))))
            if " WARN " in line or " ERROR " in line or "panicked" in line:
                gwarn[re.sub(r"\d+(\.\d+)?", "N", re.sub(r"^.*?(WARN|ERROR)", r"\1", line.strip()))[:140]] += 1
    rep["game_input_to_drawn_by_hour"] = []
    for h, (a_, b_) in enumerate(bins):
        xs = [c for c in clock if a_ <= c[0] < b_]
        rep["game_input_to_drawn_by_hour"].append({"hour": h + 1, "windows": len(xs), "inputs": sum(c[1] for c in xs), "p50_of_windows": summary([c[2] for c in xs]),
                                                   "p95_of_windows": summary([c[3] for c in xs]), "max": max((c[4] for c in xs), default=None)})
    rep["game_warnings"] = dict(gwarn.most_common(30))
    # ---- module, mind, container logs
    mod = collections.Counter()
    panics = []
    if (d / "module.log.gz").exists():
        with gzip.open(d / "module.log.gz", "rt", errors="replace") as f:
            for line in f:
                low = line.lower()
                if "panic" in low or " error" in low or "rolled back" in low or " warn" in low:
                    key = re.sub(r"\d+(\.\d+)?", "N", re.sub(r"^\S+\s+", "", line.strip()))[:160]
                    mod[key] += 1
                    if "panic" in low and len(panics) < 40:
                        panics.append(line.strip()[:400])
    rep["module_log"] = {"categories": dict(mod.most_common(40)), "panics": panics}
    ml = collections.Counter()
    if exists(d / "mind.log"):
        for line in opn(d / "mind.log"):
            if " WARN " in line or " ERROR " in line or "panicked" in line:
                ml[re.sub(r"#?\d+(\.\d+)?", "N", re.sub(r"^.*?(WARN|ERROR|panicked)", r"\1", line.strip()))[:150]] += 1
    rep["mind_log"] = dict(ml.most_common(40))
    if (d / "mind-exits.json").exists():
        rep["mind_exits"] = json.loads((d / "mind-exits.json").read_text())
    if exists(d / "fake-requests.jsonl"):
        purposes = collections.Counter()
        for line in opn(d / "fake-requests.jsonl"):
            try:
                purposes[json.loads(line).get("purpose", "?")] += 1
            except ValueError:
                pass
        rep["model_requests"] = dict(purposes)
    (d / "report.json").write_text(json.dumps(rep, indent=1, default=str) + "\n")
    print(json.dumps({k: rep[k] for k in ("checks", "deaths", "disconnects", "reducer_replies")}, indent=1, default=str)[:6000])
    return rep


# ---- markdown for docs/SOAK.md -----------------------------------------------------------------

GROWTH_ROWS = [
    ("wal_bytes", "Commit log (`spacetime_message_log_size_bytes`)", "MB"), ("disk.clog", "Replica `clog` on disk", "MB"), ("disk.snapshots", "Replica snapshots on disk", "MB"),
    ("disk.module_logs", "Module log on disk", "MB"), ("disk.data_total", "Server data directory", "MB"), ("wasm_memory", "Module WASM memory", "MB"),
    ("jemalloc_resident", "Server allocator resident (jemalloc)", "MB"), ("jemalloc_allocated", "Server allocator allocated", "MB"),
    ("stdb_cgroup_mem", "SpacetimeDB container memory (cgroup)", "MB"), ("stdb_cgroup_anon", "  of which anonymous", "MB"),
    ("soak-neo4j_mem", "Neo4j container memory", "MB"), ("neo4j.nodes", "Neo4j nodes", ""), ("neo4j.edges", "Neo4j relationships", ""),
    ("mind_rss", "Mind service RSS", "MB"), ("players_rss", "Driven players process RSS", "MB"), ("game_rss", "Game client RSS", "MB"),
    ("fake_llm_rss", "Fake model server RSS", "MB"),
]


def fmt(v, unit):
    if v is None:
        return "–"
    if unit == "MB":
        return f"{v / 1e6:,.1f}"
    return f"{v:,.0f}"


def tables(d):
    rep = json.loads((Path(d) / "report.json").read_text())
    g = rep["growth"]
    print("| Quantity | Unit | Start | End | Max | Per hour, whole run | Per hour, first half | Per hour, second half |")
    print("|---|---|---:|---:|---:|---:|---:|---:|")
    for key, label, unit in GROWTH_ROWS:
        x = g.get(key)
        if not x:
            continue
        print(f"| {label} | {unit or 'count'} | {fmt(x['first'], unit)} | {fmt(x['last'], unit)} | {fmt(x['max'], unit)} | {fmt(x['per_hour'], unit)} | {fmt(x['per_hour_first_half'], unit)} | {fmt(x['per_hour_second_half'], unit)} |")
    print()
    print("| Table | Start | End | Max | Per hour, first half | Per hour, second half |")
    print("|---|---:|---:|---:|---:|---:|")
    for key in sorted(k for k in g if k.startswith("rows.")):
        x = g[key]
        print(f"| `{key[5:]}` | {x['first']:,.0f} | {x['last']:,.0f} | {x['max']:,.0f} | {fmt(x['per_hour_first_half'], '')} | {fmt(x['per_hour_second_half'], '')} |")
    print()
    print("| Hour | Move, confirmed reads: send → reply p50/p95/p99 (n) | Move, unconfirmed | Act | Say | Skill | Move receipt → reply p50/p95/p99 |")
    print("|---|---|---|---|---|---|---|")
    q = lambda s: f"{s['p50']} / {s['p95']} / {s['p99']} ({s['n']})" if s.get("n") else "–"
    for row in rep["latency_by_hour"]:
        print(f"| {row['hour']} | {q(row['move_confirmed'])} | {q(row['move_unconfirmed'])} | {q(row['act'])} | {q(row['say'])} | {q(row['skill'])} | {q(row['move_unconfirmed_receipt_to_reply'])} |")
    print()
    print("| Hour | human_move wait / tx (ms) | human_act wait / tx | use_skill wait / tx | tick wait / tx | ticks |")
    print("|---|---|---|---|---|---|")
    for h, row in enumerate(rep["server_latency_by_hour"]):
        if not row:
            continue
        c = lambda red: f"{row[red].get('wait_mean_ms', '–')} / {row[red].get('tx_mean_ms', '–')}" if row.get(red) else "–"
        print(f"| {h + 1} | {c('human_move')} | {c('human_act')} | {c('use_skill')} | {c('tick')} | {row.get('tick', {}).get('n', '–')} |")
    print()
    print("| Hour | FPS | Interval p50/p95/p99/max (ms) | Frame work p50/p95/p99/max (ms) | > 50 ms | > 250 ms | > 1 s | Input → drawn, p50 of 10 s windows (median / max) | p95 of windows (median / max) |")
    print("|---|---:|---|---|---:|---:|---:|---|---|")
    for f, c in zip(rep["frames_by_hour"], rep["game_input_to_drawn_by_hour"]):
        i, w = f["interval"], f["work"]
        print(f"| {f['hour']} | {f['fps']} | {i.get('p50')} / {i.get('p95')} / {i.get('p99')} / {i.get('max')} | {w.get('p50')} / {w.get('p95')} / {w.get('p99')} / {w.get('max')} | {f['over_50ms']} | {f['over_250ms']} | {f['over_1s']} | "
              f"{c['p50_of_windows'].get('p50', '–')} / {c['p50_of_windows'].get('max', '–')} | {c['p95_of_windows'].get('p50', '–')} / {c['p95_of_windows'].get('max', '–')} |")


# ---- cleanup -----------------------------------------------------------------------------------

def cleanup(a):
    removed = []
    if PIDS.exists():
        for pid, name in json.loads(PIDS.read_text()).items():
            try:
                cmd = sh("ps", "-o", "command=", "-p", pid, check=False).strip()
                if cmd and (str(BIN) in cmd or "fake_llm.py" in cmd):
                    os.killpg(int(pid), signal.SIGTERM)
                    removed.append(f"process {pid} {name}")
            except (ProcessLookupError, PermissionError):
                pass
        PIDS.unlink()
    for c in (STDB, NEO):
        if c in sh("docker", "ps", "-a", "--format", "{{.Names}}", check=False).split():
            sh("docker", "stop", "-t", "60", c, check=False, timeout=180)
            code = sh("docker", "inspect", "-f", "{{.State.ExitCode}}", c, check=False).strip()
            sh("docker", "rm", c, check=False)
            removed.append(f"container {c} (exit {code})")
    for v in (STDB_VOL, NEO_VOL):
        if v in sh("docker", "volume", "ls", "--format", "{{.Name}}", check=False).split():
            sh("docker", "volume", "rm", v, check=False)
            removed.append(f"volume {v}")
    print("\n".join(removed) or "nothing to remove")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--hours", type=float, default=4.25)
    r.add_argument("--players", type=int, default=7)
    r.add_argument("--smoke", action="store_true", help="a short run of the whole timeline, compressed")
    an = sub.add_parser("analyze")
    an.add_argument("dir")
    tb = sub.add_parser("tables")
    tb.add_argument("dir")
    sub.add_parser("cleanup")
    a = ap.parse_args()
    if a.cmd == "run":
        # Launched in the background, SIGINT arrives ignored; stop cleanly on either signal.
        def interrupted(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGINT, interrupted)
        signal.signal(signal.SIGTERM, interrupted)
        if a.smoke and a.hours == 4.25:
            a.hours = 0.25
        run(a)
    elif a.cmd == "analyze":
        analyze(a.dir)
    elif a.cmd == "tables":
        tables(a.dir)
    else:
        cleanup(a)


if __name__ == "__main__":
    main()
