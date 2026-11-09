#!/usr/bin/env python3
"""The immediate gate (docs/PERFORMANCE_CONTRACT.md): 216 active characters for 30 minutes with a
crowded battle, measured against every requirement the contract lists. One command runs it and
writes raw evidence and a JSON report; docs/GATE_216.md describes the workload and the results.

    living/tools/gate.py run [--smoke] [--battle 100 --walkers 116 --warmup 300 --seconds 1800 ...]
    living/tools/gate.py analyze .local/living/gate/<run>
    living/tools/gate.py cleanup            # stop and remove the container, its volume, leftovers

What `run` does, in order (every step is logged in <run>/run.log):
1. Records the host, versions and hashes (manifest.json), then publishes the island module fresh
   as a `verify-gate-*` scratch database on its own SpacetimeDB container and installs the skills.
2. Starts two byte-counting relays (`gate-load relay`): one for the shaped clients, one for the
   local observer.
3. Shapes the player traffic: the players and the game client run in their own network
   namespaces made by `pasta` (unprivileged), each with `tc netem delay 40ms` on its loopback,
   where pasta's forwarded port is, so every packet each way waits 40 ms: 80 ms round trip,
   no jitter or loss. Calibrated before the run (calibration.json).
4. Starts the fake model server and the mind service against it (model latency stays out).
5. Joins the players over their own WebSocket connections (`join`), places the battle group
   round the battle site and the walkers at lot doors round the settlements (admin `place_at`),
   connects the tick watcher, the lab observer's subscriptions, and one headless game client.
6. `go`: profiling on (the module's tick spans), warm-up, then the measured window: ordinary
   movement first, then the battle group fights until the end.
7. Every 10 s: server metrics, container CPU and memory, process CPU, load average; every 60 s
   table counts and the replica's size on disk. At the end: the module log, the players' and
   watchers' event files, the game client's frames, then `analyze`.
Never run against anything but its own container and a `verify-gate-*` database.
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import platform
import re
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
CONTAINER = os.environ.get("GATE_STDB_CONTAINER", "gate-stdb")
VOLUME = os.environ.get("GATE_STDB_VOLUME", "gate-stdb-data")
PORT = int(os.environ.get("GATE_STDB_PORT", "3397"))
URL = f"http://127.0.0.1:{PORT}"
SHAPED_PORT = int(os.environ.get("GATE_RELAY_PORT", "3398"))
LOCAL_PORT = int(os.environ.get("GATE_LOCAL_RELAY_PORT", "3396"))
FAKE_PORT = int(os.environ.get("GATE_FAKE_PORT", "3395"))
TARGET = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "living/target"))
WASM_DIR = TARGET / "wasm32-unknown-unknown/release"
LOAD = Path(os.environ.get("GATE_LOAD", TARGET / "release/gate-load"))
GAME = Path(os.environ.get("GATE_GAME", TARGET / "release/living-game"))
MIND = Path(os.environ.get("GATE_MIND", TARGET / "release/living-mind"))
TC = os.environ.get("GATE_TC", str(ROOT / ".local/living/gate/bin/tc"))
FAKE = ROOT / ".agents/skills/verify-llm/scripts/fake_llm.py"
IMAGE = "docker.io/clockworklabs/spacetime:v2.14.1"
ONE_WAY_MS = 40
P_US = 16_667


# ---- small helpers ----------------------------------------------------------------------------

class Run:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log_file = (self.dir / "run.log").open("a")
        self.procs = []

    def log(self, msg):
        line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:-3]}] {msg}"
        print(line, flush=True)
        self.log_file.write(line + "\n")
        self.log_file.flush()

    def save(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj, indent=2) + "\n")


def sh(*args, check=True, timeout=600, **kw):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args))[:200]}: {r.returncode} {r.stderr.strip()[-2000:]}")
    return r.stdout


def stdb(*args, check=True, timeout=600):
    return sh("docker", "exec", "-i", CONTAINER, "spacetime", *args, check=check, timeout=timeout)


def http(path, body=None, token=None, raw=False, timeout=60):
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


def call(db, reducer, args, token):
    code, body = http(f"/v1/database/{db}/call/{reducer}", args, token)
    if code != 200:
        raise RuntimeError(f"{reducer}{args}: {code} {body[:300]}")


def sql(db, q, token):
    code, body = http(f"/v1/database/{db}/sql", q, token, raw=True)
    if code != 200:
        raise RuntimeError(f"sql {q!r}: {code} {body[:300]}")
    res = json.loads(body)[0]
    names = [e["name"]["some"] if isinstance(e["name"], dict) else e["name"] for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


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


def summary(xs, scale=1.0, digits=2):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "p50": round(pct(xs, 50) * scale, digits), "p95": round(pct(xs, 95) * scale, digits), "p99": round(pct(xs, 99) * scale, digits), "max": round(max(xs) * scale, digits), "mean": round(statistics.fmean(xs) * scale, digits)}


def proc_cpu_s(pid):
    """utime + stime of a process and its reaped children, in seconds."""
    try:
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        tck = os.sysconf("SC_CLK_TCK")
        return (int(f[11]) + int(f[12]) + int(f[13]) + int(f[14])) / tck
    except (OSError, IndexError):
        return None


def tree_pids(pid):
    out = [pid]
    try:
        for c in Path(f"/proc/{pid}/task/{pid}/children").read_text().split():
            out.extend(tree_pids(int(c)))
    except OSError:
        pass
    return out


def tree_cpu_s(pid):
    return sum(v for v in (proc_cpu_s(p) for p in tree_pids(pid)) if v is not None)


def metrics_text():
    return urllib.request.urlopen(f"{URL}/v1/metrics", timeout=30).read().decode()


def cgroup():
    out = sh("docker", "exec", CONTAINER, "sh", "-c", "cat /sys/fs/cgroup/cpu.stat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.stat")
    usage = int(re.search(r"usage_usec (\d+)", out).group(1))
    lines = out.splitlines()
    mem = int(next(l for l in lines if l.strip().isdigit()))
    anon = re.search(r"^anon (\d+)", out, re.M)
    return {"cpu_usec": usage, "memory_current": mem, "anon": int(anon.group(1)) if anon else None}


# ---- container ---------------------------------------------------------------------------------

def container_up(r):
    running = sh("docker", "ps", "--format", "{{.Names}}", check=False).split()
    if CONTAINER not in running:
        if CONTAINER in sh("docker", "ps", "-a", "--format", "{{.Names}}", check=False).split():
            sh("docker", "rm", "-f", CONTAINER)
        r.log(f"starting container {CONTAINER} (16 CPUs, port {PORT}, volume {VOLUME})")
        sh("docker", "run", "-d", "--name", CONTAINER, "--cpus", "16", "--security-opt", "label=disable", "--stop-signal", "SIGINT",
           "-p", f"127.0.0.1:{PORT}:3000", "-v", f"{VOLUME}:/home/spacetime", "-v", f"{WASM_DIR}:/wasm:ro", IMAGE, "start", "--listen-addr", "0.0.0.0:3000")
    for _ in range(60):
        if http("/v1/ping", timeout=5)[0] == 200:
            return
        time.sleep(1)
    raise RuntimeError("the server did not answer /v1/ping")


def ensure_tc(r):
    if Path(TC).exists():
        return
    r.log("fetching tc (iproute-tc) for the unprivileged network namespaces")
    d = ROOT / ".local/living/gate/rpm"
    d.mkdir(parents=True, exist_ok=True)
    sh("dnf", "download", "--destdir", str(d), "iproute-tc")
    rpm = next(d.glob("iproute-tc-*.rpm"))
    sh("sh", "-c", f"cd {d} && rpm2cpio {rpm.name} | cpio -idm")
    Path(TC).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(next(d.rglob("bin/tc")), TC)


def shaped(cmd, port=None):
    """`cmd` in a fresh user and network namespace (pasta) whose loopback delays every packet by
    40 ms; connections to 127.0.0.1:SHAPED_PORT inside reach the host's relay."""
    inner = f"{TC} qdisc add dev lo root netem delay {ONE_WAY_MS}ms limit 100000 && exec {cmd}"
    return ["pasta", "--config-net", "-q", "-T", str(port or SHAPED_PORT), "--", "sh", "-c", inner]


def calibrate(r):
    """Request round trips through the shaped path (namespace, pasta, the server's /v1/ping; the
    relay is left out so its connection numbers stay the players'), and TCP connects inside."""
    script = r.dir / "calibrate.sh"
    script.write_text(f"for i in $(seq 1 30); do curl -s -o /dev/null -w '%{{time_connect}} %{{time_starttransfer}}\\n' http://127.0.0.1:{PORT}/v1/ping; done\n")
    out = sh(*shaped(f"sh {script}", PORT))
    pairs = [tuple(map(float, l.split())) for l in out.splitlines() if l.strip()]
    connect = [p[0] * 1000 for p in pairs]
    request = [(p[1] - p[0]) * 1000 for p in pairs]
    res = {"method": "curl through pasta's forwarded port in a namespace with netem 40 ms on lo; time_connect is the namespace hop's TCP handshake, time_starttransfer - time_connect a request round trip to the server's /v1/ping (without the relay)",
           "connect_ms": summary(connect), "request_rtt_ms": summary(request)}
    r.save("calibration.json", res)
    r.log(f"calibration: connect {res['connect_ms']}, request {res['request_rtt_ms']}")
    return res


# ---- placements --------------------------------------------------------------------------------

def walker_spots(db, token, n):
    lots = sql(db, "SELECT * FROM lot", token)
    by = {}
    for l in sorted(lots, key=lambda l: l["id"]):
        by.setdefault(l["settlement"], []).append(l)
    order = sorted(by)
    out, k = [], 0
    while len(out) < n:
        s = by[order[k % len(order)]]
        lot = s[(k // len(order)) * 7 % len(s)]
        out.append((lot["door_x"], lot["door_y"]))
        k += 1
    return out


def battle_spots(center, n, radius):
    out = []
    for i in range(n):
        a, rr = i * 2.399963, radius * math.sqrt((i + 0.5) / max(n, 1))
        out.append((center[0] + rr * math.cos(a), center[1] + rr * math.sin(a)))
    return out


# ---- the run -----------------------------------------------------------------------------------

class Sampler(threading.Thread):
    """Every 10 s: metrics (this database's lines and the node's allocator), container cgroup,
    process CPU, load average; every 60 s: table counts and the replica's disk use."""

    TABLES = ["character", "body", "vitals", "activity", "experience", "chronicle", "skill_use", "combat_seen", "missile", "fighter", "perceived", "projected",
              "inventory", "resource_node", "structure", "mind_state", "brain", "wake", "doing", "presence", "acquaintance", "reveal", "readiness", "deliberation", "thought"]

    def __init__(self, r, db, ident, token, pids):
        super().__init__(daemon=True)
        self.r, self.db, self.db_ident, self.token, self.pids = r, db, ident, token, pids
        self.stop = threading.Event()
        self.out = gzip.open(r.dir / "samples.jsonl.gz", "wt")

    def run(self):
        k = 0
        while not self.stop.is_set():
            t = time.time()
            s = {"t": t, "load": os.getloadavg()}
            try:
                text = metrics_text()
                s["metrics"] = [l for l in text.splitlines() if (self.db_ident in l or l.startswith(("jemalloc_", "page_pool", "spacetime_page_pool"))) and not l.startswith("#")]
            except Exception as e:  # noqa: BLE001 - a missed sample is recorded, not fatal
                s["metrics_error"] = str(e)
            try:
                s["cgroup"] = cgroup()
            except Exception as e:  # noqa: BLE001
                s["cgroup_error"] = str(e)
            s["cpu_s"] = {name: tree_cpu_s(pid) for name, pid in self.pids().items()}
            if k % 6 == 0:
                counts = {}
                for tb in self.TABLES:
                    try:
                        counts[tb] = sql(self.db, f"SELECT COUNT(*) AS n FROM {tb}", self.token)[0]["n"]
                    except Exception as e:  # noqa: BLE001
                        counts[tb] = str(e)[:80]
                s["rows"] = counts
                try:
                    s["stats"] = sql(self.db, "SELECT * FROM stats", self.token)[0]
                except Exception as e:  # noqa: BLE001
                    s["stats"] = str(e)[:80]
                s["disk"] = sh("docker", "exec", CONTAINER, "sh", "-c", "du -sb /home/spacetime/.local/share/spacetime/data/replicas/*/clog /home/spacetime/.local/share/spacetime/data/replicas/*/snapshots /home/spacetime/.local/share/spacetime/data/replicas/*/module_logs 2>/dev/null", check=False)
            self.out.write(json.dumps(s) + "\n")
            self.out.flush()
            k += 1
            self.stop.wait(max(0.0, 10 - (time.time() - t)))
        self.out.close()


class Proc:
    """A child process speaking JSON lines on stdout."""

    def __init__(self, r, name, cmd, env=None, stdin=True, lines=True):
        """`lines`: the child speaks JSON lines on stdout; otherwise stdout goes to its log file."""
        self.name = name
        self.err = (r.dir / f"{name}.stderr").open("w")
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL, stdout=subprocess.PIPE if lines else self.err, stderr=self.err, text=True, env=env, start_new_session=True)
        r.procs.append(self)
        remember(self.p.pid, name)
        self.lines = []

    def send(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def expect(self, event, timeout):
        box = {}

        def read():
            for line in self.p.stdout:
                try:
                    v = json.loads(line)
                except ValueError:
                    continue
                self.lines.append(v)
                if v.get("event") == event:
                    box["v"] = v
                    return

        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(timeout)
        if "v" not in box:
            raise RuntimeError(f"{self.name}: no {event} within {timeout}s (exit {self.p.poll()}); see {self.err.name}")
        return box["v"]

    def pid(self):
        return self.p.pid

    def kill(self):
        if self.p.poll() is None:
            try:
                os.killpg(self.p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(self.p.pid, signal.SIGKILL)


def run(a):
    procs = []
    try:
        _run(a, procs)
    finally:
        for p in procs:
            p.kill()


def _run(a, procs):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{'smoke' if a.smoke else 'gate'}-{stamp}"
    r = Run(ROOT / ".local/living/gate" / name)
    r.procs = procs
    PIDS.unlink(missing_ok=True)
    db = a.db or f"verify-gate-{stamp}"
    if not db.startswith("verify-gate"):
        sys.exit("the gate runs only on verify-gate-* scratch databases")
    r.log(f"run {name}: db {db}, {a.battle} battle + {a.walkers} walkers, warm-up {a.warmup} s, window {a.seconds} s (calm {a.calm} s then battle)")
    for f in (LOAD, GAME, MIND, WASM_DIR / "living_authority.wasm"):
        if not Path(f).exists():
            sys.exit(f"missing {f}: build it first (docs/GATE_216.md, 'Reproduce')")
    ensure_tc(r)
    container_up(r)
    git = sh("git", "-C", str(ROOT), "rev-parse", "HEAD").strip()
    dirty = sh("git", "-C", str(ROOT), "status", "--short", "--untracked-files=no").splitlines()
    cpu_model = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines() if l.startswith("model name")), "?")
    gpu = sh("sh", "-c", "vulkaninfo --summary 2>/dev/null | grep -m1 deviceName", check=False).strip()
    manifest = {
        "run": name, "db": db, "started_utc": stamp, "git": git, "dirty": dirty,
        "host": {"node": platform.node(), "kernel": platform.release(), "cpu": cpu_model, "threads": os.cpu_count(), "mem_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1), "gpu": gpu, "load_at_start": os.getloadavg()},
        "server": {"image": IMAGE, "container": CONTAINER, "cpus": 16, "port": PORT, "volume": VOLUME, "cli": stdb("--version").strip().splitlines()[-1]},
        "binaries": {str(p.name): sha256(p) for p in (LOAD, GAME, MIND, WASM_DIR / "living_authority.wasm")},
        "skills_rhai_sha256": sha256(ROOT / "living/scripts/skills.rhai"),
        "seed": "island", "network": {"one_way_ms": ONE_WAY_MS, "rtt_ms": 2 * ONE_WAY_MS, "jitter": 0, "loss": 0, "how": "pasta user+net namespace per client process, tc netem on the namespace's lo"},
        "workload": {"battle_players": a.battle, "walkers": a.walkers, "active_total": a.battle + a.walkers, "warmup_s": a.warmup, "window_s": a.seconds, "calm_s": a.calm,
                     "fight_period_ms": a.fight_ms, "walk_period_ms": a.walk_ms, "rejoin_s": 3, "battle_radius_m": a.radius, "game_client": not a.no_game, "observer": True, "minds": "fake model server"},
    }
    r.save("manifest.json", manifest)
    stdb("publish", "-s", "local", "-b", "/wasm/living_authority.wasm", db, "--delete-data", "-y")
    stdb("call", "-s", "local", db, "install_script", json.dumps((ROOT / "living/scripts/skills.rhai").read_text()))
    token = admin_token()
    ident = json.loads(http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
    land = sql(db, "SELECT * FROM land", token)[0]
    world = sql(db, "SELECT * FROM world", token)[0]
    center = (land["arrive_x"], land["arrive_y"] - 30.0)
    # The declared timing of each combat skill (windup, recovery, cooldown): reported apart from latency.
    r.save("skill_cards.json", {c["skill"]: c for c in sql(db, "SELECT * FROM skill_card", token)})
    r.log(f"published: identity {ident[:12]}…, arrival ({land['arrive_x']}, {land['arrive_y']}), battle site {center}, day {world['day_ms'] / 60000:.0f} min")
    relay_shaped = Proc(r, "relay-shaped", [str(LOAD), "relay", "--listen", f"127.0.0.1:{SHAPED_PORT}", "--upstream", f"127.0.0.1:{PORT}", "--out", str(r.dir / "relay-shaped.jsonl")])
    relay_local = Proc(r, "relay-local", [str(LOAD), "relay", "--listen", f"127.0.0.1:{LOCAL_PORT}", "--upstream", f"127.0.0.1:{PORT}", "--out", str(r.dir / "relay-local.jsonl")])
    time.sleep(0.5)
    calibrate(r)
    # Minds against the fake model server.
    fake = mind = None
    if not a.no_minds:
        fake_log = r.dir / "fake-requests.jsonl"
        fake = Proc(r, "fake-llm", [sys.executable, str(FAKE), "--port", str(FAKE_PORT), "--log", str(fake_log)], stdin=False, lines=False)
        models = {"default": "local", "profiles": {"local": {"base_url": f"http://127.0.0.1:{FAKE_PORT}/v1", "model": "fake-minds", "key_env": "LIVING_VERIFY_FAKE_KEY", "max_tokens": 256, "requests_per_minute": 6000}}}
        r.save("models.json", models)
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=URL, LIVING_DB=db, LIVING_RUN=db, LIVING_SEED="island", LIVING_MODELS=str(r.dir / "models.json"), LIVING_NEO4J="off",
                   LIVING_NEO4J_PASSWORD="", LIVING_LLM_PER_MIN="0", LIVING_CONCURRENCY="4", LIVING_TOKEN=token, LIVING_VERIFY_FAKE_KEY="dummy-local-only", NO_PROXY="127.0.0.1,localhost",
                   RUST_LOG="info,neo4rs=warn,spacetimedb_sdk=warn")
        mind = Proc(r, "mind", [str(MIND)], env=env, stdin=False, lines=False)
    # Player identities.
    n = a.battle + a.walkers
    tokens = [json.loads(http("/v1/identity", {})[1])["token"] for _ in range(n + 1)]
    players = [{"token": tokens[i], "name": f"GateB{i}" if i < a.battle else f"GateW{i - a.battle}", "role": "battle" if i < a.battle else "walk"} for i in range(n)]
    watch = Proc(r, "watch", [str(LOAD), "watch"])
    watch.send(json.dumps({"uri": URL, "db": db, "token": token, "out": str(r.dir / "ticks.csv")}))
    watch.expect("ready", 60)
    load = Proc(r, "players", shaped(f"{LOAD} players"))
    behaviour = {"fight_period_ms": a.fight_ms, "walk_period_ms": a.walk_ms, "rejoin_s": 3, "grace_s": 5}
    load.send(json.dumps({"uri": f"http://127.0.0.1:{SHAPED_PORT}", "db": db, "events": str(r.dir / "events.jsonl"), "battle": list(center), "behaviour": behaviour, "players": players}))
    joined = load.expect("joined", 600)
    r.log(f"{len(joined['players'])} players joined in {joined['after_s']:.1f} s")
    ids = {p["p"]: p["id"] for p in joined["players"]}
    for i, (x, y) in enumerate(battle_spots(center, a.battle, a.radius)):
        call(db, "place_at", [ids[i], x, y], token)
    for j, (x, y) in enumerate(walker_spots(db, token, a.walkers)):
        call(db, "place_at", [ids[a.battle + j], x, y], token)
    load.send("placed")
    ready = load.expect("ready", 600)
    r.log(f"players ready in {ready['after_s']:.1f} s; bodies held (first 5): {ready['held'][:5]}")
    observer = Proc(r, "observer", [str(LOAD), "observe"])
    observer.send(json.dumps({"uri": f"http://127.0.0.1:{LOCAL_PORT}", "db": db, "token": token, "inspect": ids[0]}))
    observer.expect("ready", 300)
    game = None
    game_dir = r.dir / "game"
    if not a.no_game:
        game_dir.mkdir(exist_ok=True)
        token_file = ROOT / ".local/living/gate/game.token"
        token_file.write_text(tokens[n])
        total = a.warmup + a.seconds + 120
        steps = ["ready", "sync:placed"] + [f"walk:{90 if k % 2 else 270}:3" if k % 4 < 2 else "wait:3" for k in range(int(total / 3))] + ["quit"]
        env = dict(os.environ, LIVING_SERVER=f"http://127.0.0.1:{SHAPED_PORT}", LIVING_DB=db, LIVING_GAME_TOKEN=str(token_file), LIVING_GAME_NAME="GateWatcher",
                   LIVING_GAME_LIVE=str(game_dir), LIVING_GAME_LIVE_PLAN=";".join(steps), LIVING_GAME_FPS_CAP=str(a.fps_cap), LIVING_GAME_FRAMES=str(game_dir / "frames.csv"),
                   LIVING_GAME_PERF="hitch=50", RUST_LOG="info,wgpu=warn,naga=warn,spacetimedb_sdk=warn")
        game = Proc(r, "game", shaped(str(GAME)), env=env, stdin=False, lines=False)
        t = time.time()
        gid = None
        while time.time() - t < 300 and game.p.poll() is None:
            rows = sql(db, "SELECT id FROM character WHERE name = 'GateWatcher' AND alive = true", token)
            if rows:
                gid = rows[0]["id"]
                break
            time.sleep(2)
        if gid is None:
            r.log("WARNING: the game client did not join; frame pacing will be missing")
        else:
            time.sleep(5)
            call(db, "place_at", [gid, center[0], center[1] + 14.0], token)
            (game_dir / "placed.go").write_text("0")
            r.log(f"game client joined as #{gid}, placed 14 m south of the battle")
    pids = lambda: {k: v for k, v in {"players": load.pid(), "watch": watch.pid(), "observer": observer.pid(), "relays": relay_shaped.pid(),
                                      "relay_local": relay_local.pid(), "mind": mind.pid() if mind else None, "fake_llm": fake.pid() if fake else None,
                                      "game": game.pid() if game else None}.items() if v}
    sampler = Sampler(r, db, ident, token, pids)
    sampler.start()
    stdb("call", "-s", "local", db, "set_profile", "true")
    marks = {"go": time.time()}
    load.send("go")
    r.log("go: warm-up")
    time.sleep(a.warmup)
    marks["window_start"] = time.time()
    r.log("measured window: calm")
    time.sleep(a.calm)
    marks["battle_start"] = time.time()
    load.send("battle")
    r.log("battle")
    time.sleep(a.seconds - a.calm)
    marks["window_end"] = time.time()
    r.log("window over")
    load.send("stop")
    done = load.expect("done", 300)
    r.save("players-done.json", done)
    stdb("call", "-s", "local", db, "set_profile", "false")
    observer.send("stop")
    try:
        r.save("observer-done.json", observer.expect("done", 60))
    except RuntimeError as e:
        r.log(f"observer: {e}")
    watch.send("stop")
    sampler.stop.set()
    sampler.join(30)
    marks["end"] = time.time()
    r.save("marks.json", marks)
    for p in (relay_shaped, relay_local):
        try:
            p.p.stdin.close()
            p.p.wait(15)
        except Exception:  # noqa: BLE001
            p.kill()
    for p in r.procs:
        p.kill()
    r.log("saving the module log")
    with gzip.open(r.dir / "module.log.gz", "wt") as f:
        f.write(stdb("logs", "-s", "local", db, "-n", str(int((marks["end"] - marks["go"]) * 60 * 20 + 100_000)), timeout=1800))
    if a.delete:
        stdb("delete", "-s", "local", db, "-y", check=False)
        r.log(f"deleted {db}")
    analyze(r.dir)


# ---- analysis ----------------------------------------------------------------------------------

def windows_of(marks):
    w0, w1, b = marks["window_start"], marks["window_end"], marks["battle_start"]
    late = max(b, w1 - 600)
    return {"window": (w0, w1), "calm": (w0, b), "battle": (b, w1), "late": (late, w1)}


def parse_module_log(path, t0, t1):
    spans = {}
    starts = []
    rx = re.compile(r'^(\S+Z)\s.*Timing span "([^"]+)": ([\d.]+)(µs|ms|s)\b')
    with gzip.open(path, "rt") as f:
        for line in f:
            m = rx.match(line)
            if not m:
                continue
            stamp = m.group(1).rstrip("Z")
            stamp = stamp[:26]
            fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in stamp else "%Y-%m-%dT%H:%M:%S"
            at = datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc).timestamp()
            if not (t0 - 2 <= at <= t1 + 2):
                continue
            d = float(m.group(3)) * {"µs": 1e-3, "ms": 1.0, "s": 1e3}[m.group(4)]
            spans.setdefault(m.group(2), []).append((at, d))
            if m.group(2) == "tick":
                starts.append((at - d / 1000, d))
    return spans, sorted(starts)


def tick_analysis(starts, ticks_csv, win, delay_mean_ms=None):
    """Step intervals, lateness against the 16.667 ms grid, and each step's delivery."""
    out = {}
    for name, (a, b) in win.items():
        st = [(s, d) for s, d in starts if a <= s < b]
        if len(st) < 3:
            out[name] = {"n": len(st)}
            continue
        us = [round(s * 1e6) for s, _ in st]
        iv = [(us[i] - us[i - 1]) / 1000 for i in range(1, len(us))]
        # The grid's phase: the schedule is anchored (fixed rate), and a step never starts before
        # its intended time, so the phase is where the steps' start times modulo P cluster lowest.
        # The phase: the circular mean of start times modulo P (they cluster within a millisecond
        # or two of the intended time); lateness is each start's offset from it, shifted so its
        # mean equals the server's exact mean scheduling delay for the window
        # (spacetime_scheduled_function_delay_seconds: start - intended), since the log only
        # gives the start, not the intended time.
        ang = [2 * math.pi * (u % P_US) / P_US for u in us]
        c = math.atan2(sum(map(math.sin, ang)), sum(map(math.cos, ang))) % (2 * math.pi) * P_US / (2 * math.pi)
        off = [(((u - c) + P_US / 2) % P_US - P_US / 2) / 1000 for u in us]
        shift = (delay_mean_ms.get(name) - statistics.fmean(off)) if delay_mean_ms and delay_mean_ms.get(name) is not None else -min(off)
        late = [o + shift for o in off]
        skipped = sum(max(0, round(x / (P_US / 1000)) - 1) for x in iv)
        dur = [d for _, d in st]
        span_s = (us[-1] - us[0]) / 1e6
        out[name] = {"steps": len(st), "steps_per_s": round((len(st) - 1) / span_s, 3), "expected_steps": round(span_s * 1e6 / P_US) + 1, "skipped_grid_steps": skipped,
                     "interval_ms": summary(iv), "intervals_over_25ms": sum(x > 25.0 for x in iv), "intervals_over_33ms": sum(x > 33.4 for x in iv),
                     "lateness_vs_grid_ms": summary(late), "lateness_anchor": "server mean delay" if delay_mean_ms and delay_mean_ms.get(name) is not None else "earliest start", "lateness_over_1ms": sum(x > 1 for x in late), "lateness_over_4ms": sum(x > 4 for x in late),
                     "tick_code_ms": summary(dur, digits=3), "tick_code_over_16_7ms": sum(d > 16.667 for d in dur)}
    # Delivery of each tick's clock row to a local owner client, with and without confirmed reads.
    deliveries = {"c": {}, "u": {}}
    if ticks_csv.exists():
        for line in ticks_csv.read_text().splitlines():
            f = line.split(",")
            if len(f) == 4:
                deliveries[f[0]][int(f[2])] = int(f[3])
    for name, (a, b) in win.items():
        st = [(s, d) for s, d in starts if a <= s < b]
        res = {}
        for flag, label in (("u", "unconfirmed"), ("c", "confirmed")):
            dl = deliveries[flag]
            lat = []
            for s, _ in st:
                ms = int(s * 1000)
                for k in (ms, ms - 1, ms + 1):
                    if k in dl:
                        lat.append((dl[k] - s * 1e6) / 1000)
                        break
            res[label] = summary(lat)
            res[label + "_over_16_7ms"] = sum(x > 16.667 for x in lat)
        out[name]["step_start_to_delivered_ms"] = res
    return out


def hist_quantiles(buckets, total):
    """Bucket-bounded quantiles: the upper bound of the bucket holding each quantile."""
    out = {}
    for q in (50, 95, 99):
        need = total * q / 100
        bound = next((le for le, c in buckets if c >= need), float("inf"))
        out[f"p{q}_le"] = bound
    return out


def metric_deltas(samples, a, b, ident):
    """Histogram and counter deltas between the samples nearest the window's ends."""
    s0 = min(samples, key=lambda s: abs(s["t"] - a))
    s1 = min(samples, key=lambda s: abs(s["t"] - b))
    def parse(s):
        d = {}
        for l in s.get("metrics", []):
            m = re.match(r'^(\w+)\{([^}]*)\} (\S+)$', l)
            if m:
                d[(m.group(1), m.group(2))] = float(m.group(3))
            else:
                m = re.match(r'^(\w+) (\S+)$', l)
                if m:
                    d[(m.group(1), "")] = float(m.group(2))
        return d
    m0, m1 = parse(s0), parse(s1)
    dt = s1["t"] - s0["t"]
    lab = lambda labels, k: (re.search(rf'{k}="([^"]*)"', labels) or [None, None])[1]
    out = {"seconds": round(dt, 1)}
    for hist in ("spacetime_reducer_wait_time_sec", "spacetime_txn_elapsed_time_sec", "spacetime_reducer_plus_query_duration_sec", "spacetime_scheduled_function_delay_seconds"):
        per = {}
        for (name, labels), v in m1.items():
            if name != hist + "_bucket":
                continue
            red = lab(labels, "reducer") or lab(labels, "reducer_symbol") or lab(labels, "function") or "?"
            le = lab(labels, "le")
            per.setdefault(red, {})[float("inf") if le == "+Inf" else float(le)] = v - m0.get((name, labels), 0)
        res = {}
        for red, bk in per.items():
            items = sorted(bk.items())
            total = items[-1][1] if items else 0
            if total <= 0:
                continue
            sums = [v - m0.get((n, l), 0) for (n, l), v in m1.items() if n == hist + "_sum" and (lab(l, "reducer") or lab(l, "function")) == red]
            res[red] = {"count": int(total), "mean_ms": round(sum(sums) / total * 1000, 3) if sums else None, **{k: (v * 1000 if v != float("inf") else "inf") for k, v in hist_quantiles(items, total).items()}}
        out[hist] = res
    counters = {}
    for (name, labels), v in m1.items():
        if name in ("reducer_wasm_time_usec", "view_calls_triggered_by_reducer", "spacetime_num_bytes_sent_to_clients_total"):
            key = lab(labels, "reducer") or lab(labels, "txn_type") or "?"
            rate = round((v - m0.get((name, labels), 0)) / dt, 2)
            if rate:
                counters.setdefault(name, {})[key] = rate
    out["per_second"] = counters
    gauges = {}
    for (name, labels), v in m1.items():
        if name in ("spacetime_worker_wasm_memory_bytes", "spacetime_message_log_size_bytes", "spacetime_module_log_file_size_bytes", "jemalloc_resident_bytes", "jemalloc_allocated_bytes",
                    "jemalloc_active_bytes", "spacetime_worker_instance_operation_queue_length", "spacetime_subscription_send_queue_length"):
            gauges[name] = {"start": m0.get((name, labels)), "end": v}
    out["gauges"] = gauges
    return out


def inputs_analysis(events_path, win, cards):
    ins, res, uses_by_call, use_states, deaths, alive = {}, {}, {}, {}, [], []
    go = None
    with open(events_path) as f:
        for line in f:
            e = json.loads(line)
            k = e["k"]
            if k == "in":
                ins[(e["p"], e["n"])] = e
            elif k == "res":
                res[(e["p"], e["n"])] = e
                if e.get("use") is not None:
                    uses_by_call[(e["p"], e["use"])] = (e["p"], e["n"])
            elif k == "use":
                use_states.setdefault((e["p"], e["use"]), []).append(e)
            elif k == "death":
                deaths.append(e)
            elif k == "alive":
                alive.append(e)
            elif k == "go":
                go = e["ts"]
    out = {}
    stop_us = win["window"][1] * 1e6
    for wname, (a, b) in win.items():
        a_us, b_us = a * 1e6, b * 1e6
        rows = {"move": [], "skill_ack": [], "skill_outcome": [], "join": []}
        server = {"move": [], "skill_ack": [], "skill_outcome": []}
        by_skill, missing, unanswered, errors, refused, broke = {}, 0, 0, {}, {}, {}
        for key, i in ins.items():
            if not (a_us <= i["ts"] < b_us):
                continue
            r_ = res.get(key)
            if r_ is None:
                if i["ts"] < stop_us - 5e6:
                    unanswered += 1
                continue
            rtt = (r_["ts"] - i["ts"]) / 1000
            srv = (r_["ts"] - ONE_WAY_MS * 1000 - r_["srv"]) / 1000
            if r_["st"] != "ok":
                errors[r_["st"][:60]] = errors.get(r_["st"][:60], 0) + 1
            if i["r"] == "move":
                rows["move"].append(rtt)
                server["move"].append(srv)
            elif i["r"] == "join":
                rows["join"].append(rtt)
            elif i["r"] == "skill":
                rows["skill_ack"].append(rtt)
                server["skill_ack"].append(srv)
                uid = r_.get("use")
                skill = i["skill"]
                bs = by_skill.setdefault(skill, {"inputs": 0, "accepted": 0, "refused": 0, "broken_off": 0, "actor_died": 0, "missing": 0, "outcome_ms": [], "server_outcome_ms": [], "release_late_ms": []})
                bs["inputs"] += 1
                if uid is None:
                    continue
                states = use_states.get((i["p"], uid), [])
                acc = next((s for s in states if s["acc"]), None)
                if acc is None:
                    bs["refused"] += 1
                    o = next((s for s in states if s["out"]), None)
                    why = (o or r_)["out"] if (o or r_).get("out") else "?"
                    refused[str(why)[:50]] = refused.get(str(why)[:50], 0) + 1
                    continue
                bs["accepted"] += 1
                card = cards.get(skill, {})
                windup = card.get("windup_ms", 0)
                if card.get("aim") in ("dash", "facing") or windup == 0:
                    # A dash or a raised guard: what the press does (the dash under way, the guard
                    # up) is the accepted move itself; its later outcome ends a declared duration.
                    done, minus = acc, 0
                else:
                    # A timed move: its outcome is the release (the blow or heal applied, the
                    # missile away), after the declared windup, which is taken off.
                    done, minus = next((s for s in states if s["rel"]), None), windup
                    if done is None:
                        broken = next((s for s in states if s["out"]), None)
                        died = any(dd["p"] == i["p"] and i["ts"] <= dd["ts"] <= i["ts"] + (windup + 2000) * 1000 for dd in deaths)
                        if broken is not None:
                            bs["broken_off"] += 1
                            broke[str(broken["out"])[:40]] = broke.get(str(broken["out"])[:40], 0) + 1
                        elif died:
                            bs["actor_died"] += 1
                        elif i["ts"] < stop_us - 5e6:
                            bs["missing"] += 1
                            missing += 1
                        continue
                if minus and done["rel"] and acc["acc"]:
                    # On the authority's own clock: how long after its declared windup the move
                    # was released (the tick's granularity and any lateness).
                    bs["release_late_ms"].append(done["rel"] - acc["acc"] - windup)
                lat = (done["ts"] - i["ts"]) / 1000 - minus
                slat = (done["ts"] - ONE_WAY_MS * 1000 - r_["srv"]) / 1000 - minus
                bs["outcome_ms"].append(lat)
                bs["server_outcome_ms"].append(slat)
                rows["skill_outcome"].append(lat)
                server["skill_outcome"].append(slat)
        out[wname] = {
            "client_input_to_result_ms": {k: summary(v) for k, v in rows.items()},
            "server_receipt_to_result_ms": {k: summary(v) for k, v in server.items()},
            "inputs": sum(1 for i in ins.values() if a_us <= i["ts"] < b_us),
            "inputs_per_s": round(sum(1 for i in ins.values() if a_us <= i["ts"] < b_us) / max(b - a, 1), 1),
            "unanswered": unanswered, "accepted_without_outcome": missing, "errors": errors, "refusals": dict(sorted(refused.items(), key=lambda x: -x[1])[:12]), "broken_off": broke,
            "by_skill": {s: {**{k: v for k, v in d.items() if not isinstance(v, list)}, "client_outcome_ms": summary(d["outcome_ms"]), "server_outcome_ms": summary(d["server_outcome_ms"]), "authority_release_after_windup_ms": summary(d["release_late_ms"])} for s, d in sorted(by_skill.items())},
            "deaths": sum(1 for d in deaths if a_us <= d["ts"] < b_us), "rejoins": sum(1 for x in alive if a_us <= x["ts"] < b_us and go and x["ts"] > go),
        }
    return out


def bytes_analysis(path, win, n_players, battle):
    snaps = [json.loads(l) for l in open(path)] if Path(path).exists() else []
    out = {}
    for wname, (a, b) in win.items():
        if not snaps:
            break
        s0 = min(snaps, key=lambda s: abs(s["t"] / 1e6 - a))
        s1 = min(snaps, key=lambda s: abs(s["t"] / 1e6 - b))
        dt = (s1["t"] - s0["t"]) / 1e6
        if dt <= 0:
            continue
        d0 = {c[0]: c[2] for c in s0["c"]}
        per = [(c[0], (c[2] - d0.get(c[0], 0)) / dt) for c in s1["c"]]
        bat = [v for i, v in per if i < battle]
        wal = [v for i, v in per if battle <= i < n_players]
        rest = [v for i, v in per if i >= n_players]
        out[wname] = {"seconds": round(dt, 1), "battle_B_per_s": summary(bat, digits=0), "walker_B_per_s": summary(wal, digits=0), "other_connections_B_per_s": [round(v) for v in rest]}
    return out


def frames_analysis(path, win):
    if not Path(path).exists():
        return None
    rows = []
    for line in open(path):
        f = line.strip().split(",")
        if len(f) == 3 and f[0].isdigit():
            rows.append((int(f[0]) / 1e6, int(f[1]) / 1000, int(f[2]) / 1000))
    out = {}
    for wname, (a, b) in win.items():
        iv = [r[1] for r in rows if a <= r[0] < b]
        wk = [r[2] for r in rows if a <= r[0] < b]
        if not iv:
            out[wname] = {"frames": 0}
            continue
        out[wname] = {"frames": len(iv), "fps": round(len(iv) / (b - a), 2), "interval_ms": summary(iv), "work_ms": summary(wk),
                      "within_16_7ms": round(sum(x <= 16.7 for x in iv) / len(iv) * 100, 2), "within_17_5ms": round(sum(x <= 17.5 for x in iv) / len(iv) * 100, 2),
                      "missed_over_25ms": sum(x > 25 for x in iv), "stutters_over_50ms": sum(x > 50 for x in iv), "worst_ms": round(max(iv), 1)}
    return out


def samples_analysis(path, win):
    samples = [json.loads(l) for l in gzip.open(path, "rt")]
    out = {}
    for wname, (a, b) in win.items():
        ss = [s for s in samples if a - 5 <= s["t"] <= b + 5 and "cgroup" in s]
        if len(ss) < 2:
            continue
        s0, s1 = ss[0], ss[-1]
        dt = s1["t"] - s0["t"]
        cpu = (s1["cgroup"]["cpu_usec"] - s0["cgroup"]["cpu_usec"]) / 1e6 / dt
        per10 = [(ss[i]["cgroup"]["cpu_usec"] - ss[i - 1]["cgroup"]["cpu_usec"]) / 1e6 / (ss[i]["t"] - ss[i - 1]["t"]) for i in range(1, len(ss))]
        procs = {}
        for k in s1.get("cpu_s", {}):
            if s0.get("cpu_s", {}).get(k) is not None and s1["cpu_s"][k] is not None:
                procs[k] = round((s1["cpu_s"][k] - s0["cpu_s"][k]) / dt, 3)
        out[wname] = {"server_cpu_cores": round(cpu, 3), "server_cpu_cores_10s": summary(per10, digits=3), "process_cpu_cores": procs,
                      "container_memory_mb": {"start": round(s0["cgroup"]["memory_current"] / 2**20), "end": round(s1["cgroup"]["memory_current"] / 2**20), "max": round(max(s["cgroup"]["memory_current"] for s in ss) / 2**20)},
                      "load_avg_1m": summary([s["load"][0] for s in ss])}
    rows = [s for s in samples if "rows" in s]
    if rows:
        out["rows"] = {"first": {"t": rows[0]["t"], **rows[0]["rows"]}, "last": {"t": rows[-1]["t"], **rows[-1]["rows"]}}
        out["rows_series"] = [{"t": round(s["t"]), **{k: v for k, v in s["rows"].items() if isinstance(v, int)}} for s in rows]
        out["stats_series"] = [{"t": round(s["t"]), **s["stats"]} for s in rows if isinstance(s.get("stats"), dict)]
        out["disk_series"] = [{"t": round(s["t"]), "du": s.get("disk", "")} for s in rows]
    return out, samples


def analyze(directory):
    d = Path(directory)
    marks = json.loads((d / "marks.json").read_text())
    manifest = json.loads((d / "manifest.json").read_text())
    win = windows_of(marks)
    w = manifest["workload"]
    cards = {}
    rep = {"run": manifest["run"], "windows_utc": {k: [datetime.fromtimestamp(v[0], timezone.utc).strftime("%H:%M:%S"), datetime.fromtimestamp(v[1], timezone.utc).strftime("%H:%M:%S")] for k, v in win.items()}}
    db_ident = None
    sres, samples = samples_analysis(d / "samples.jsonl.gz", win)
    for s in samples:
        for l in s.get("metrics", []):
            m = re.search(r'(?:db|database_identity)="([0-9a-f]{64})"', l)
            if m:
                db_ident = m.group(1)
                break
        if db_ident:
            break
    spans, starts = parse_module_log(d / "module.log.gz", win["window"][0] - 1, win["window"][1] + 1)
    rep["server_metrics"] = {name: metric_deltas(samples, a, b, db_ident) for name, (a, b) in win.items()}
    delay = {name: m.get("spacetime_scheduled_function_delay_seconds", {}).get("tick", {}).get("mean_ms") for name, m in rep["server_metrics"].items()}
    rep["ticks"] = tick_analysis(starts, d / "ticks.csv", win, delay)
    rep["spans_ms_per_s"] = {}
    for name, (a, b) in win.items():
        rep["spans_ms_per_s"][name] = {k: round(sum(dd for t, dd in v if a <= t < b) / (b - a), 2) for k, v in sorted(spans.items())}
    hk = [(t, dd) for t, dd in spans.get("housekeeping", []) if win["window"][0] <= t < win["window"][1]]
    rep["housekeeping"] = {"runs": len(hk), "duration_ms": summary([dd for _, dd in hk], digits=3), "interval_ms": summary([(hk[i][0] - hk[i - 1][0]) * 1000 for i in range(1, len(hk))])}
    sk = d / "skill_cards.json"
    if sk.exists():
        cards = json.loads(sk.read_text())
    rep["inputs"] = inputs_analysis(d / "events.jsonl", win, cards)
    rep["bytes"] = bytes_analysis(d / "relay-shaped.jsonl", win, w["battle_players"] + w["walkers"], w["battle_players"])
    rep["observer_bytes"] = bytes_analysis(d / "relay-local.jsonl", win, 0, 0)
    rep["frames"] = frames_analysis(d / "game/frames.csv", win)
    rep["resources"] = sres
    rep["verdicts"] = verdicts(rep)
    (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
    print(json.dumps(rep["verdicts"], indent=2))
    return rep


def verdicts(rep):
    """Each requirement: pass, fail or not measured, with the numbers that decide it."""
    v = []
    t = rep["ticks"].get("window", {})
    ok60 = t.get("skipped_grid_steps", 1) == 0 and t.get("interval_ms", {}).get("p99", 99) <= 16.667 * 1.5 and t.get("lateness_vs_grid_ms", {}).get("p99", 99) < 16.667
    v.append({"requirement": "60 Hz authoritative simulation (16.667 ms steps, battle included)", "verdict": "pass" if ok60 else "fail",
              "evidence": {k: t.get(k) for k in ("steps_per_s", "skipped_grid_steps", "interval_ms", "lateness_vs_grid_ms", "intervals_over_25ms")}})
    for name, key, p95, p99 in (("Server receipt to committed outcome", "server_receipt_to_result_ms", 50, 100), ("Client input to authoritative outcome received at 80 ms RTT", "client_input_to_result_ms", 150, 250)):
        i = rep["inputs"].get("window", {}).get(key, {})
        worst = {k: s for k, s in i.items() if s.get("n")}
        fails = {k: s for k, s in worst.items() if k != "join" and (s["p95"] > p95 or s["p99"] > p99)}
        v.append({"requirement": f"{name} ≤{p95} ms p95, ≤{p99} ms p99", "verdict": ("fail" if fails else "pass") if worst else "not measured", "evidence": worst, "failing": sorted(fails)})
    f = (rep.get("frames") or {}).get("window")
    if f and f.get("frames"):
        v.append({"requirement": "Client 60 FPS, 99% of frames within ~16.7 ms", "verdict": "pass" if f["within_16_7ms"] >= 99 else "fail", "evidence": f})
    else:
        v.append({"requirement": "Client 60 FPS, 99% of frames within ~16.7 ms", "verdict": "not measured"})
    hk = rep.get("housekeeping", {})
    v.append({"requirement": "Slow systems at their deadlines (1 Hz housekeeping)", "verdict": "pass" if hk.get("interval_ms", {}).get("max", 1e9) < 1500 else "fail", "evidence": hk})
    return v


# ---- cleanup -----------------------------------------------------------------------------------

PIDS = ROOT / ".local/living/gate/pids.json"


MINE = ("gate-load", "fake_llm.py", "pasta", str(MIND), str(GAME))


def ours(pid):
    """Whether `pid` is still a process the gate started (a recorded PID can be reused)."""
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return False
    return any(m in cmd for m in MINE)


def remember(pid, name):
    """Every process the gate starts is recorded, so cleanup stops exactly those and nothing else
    on a shared host (never a pattern match: other agents run the same binaries)."""
    known = json.loads(PIDS.read_text()) if PIDS.exists() else {}
    known[str(pid)] = name
    PIDS.parent.mkdir(parents=True, exist_ok=True)
    PIDS.write_text(json.dumps(known))


def cleanup(a):
    known = json.loads(PIDS.read_text()) if PIDS.exists() else {}
    stopped = []
    known = {pid: name for pid, name in known.items() if ours(pid)}
    for pid, name in known.items():
        try:
            os.killpg(int(pid), signal.SIGTERM)
            stopped.append(name)
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(2)
    for pid in known:
        if not ours(pid):
            continue
        try:
            os.killpg(int(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    PIDS.unlink(missing_ok=True)
    if a.container:
        subprocess.run(["docker", "stop", "-t", "30", CONTAINER], check=False)
        subprocess.run(["docker", "rm", "-f", CONTAINER], check=False)
        subprocess.run(["docker", "volume", "rm", VOLUME], check=False)
    alive = [pid for pid in known if Path(f"/proc/{pid}").exists() and "zombie" not in Path(f"/proc/{pid}/status").read_text().lower()]
    print(json.dumps({"stopped": stopped, "still_alive": alive, "container_present": CONTAINER in sh("docker", "ps", "-a", "--format", "{{.Names}}").split(),
                      "volume_present": VOLUME in sh("docker", "volume", "ls", "--format", "{{.Name}}").split()}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--db")
    r.add_argument("--battle", type=int, default=100)
    r.add_argument("--walkers", type=int, default=116)
    r.add_argument("--warmup", type=int, default=300)
    r.add_argument("--seconds", type=int, default=1800)
    r.add_argument("--calm", type=int, default=300, help="seconds of the window before the battle starts")
    r.add_argument("--fight-ms", type=int, default=250)
    r.add_argument("--walk-ms", type=int, default=1500)
    r.add_argument("--radius", type=float, default=9.0)
    r.add_argument("--fps-cap", type=int, default=0, help="the game client's loop rate; 0 (default) is uncapped, so frame intervals are the frames' real cost")
    r.add_argument("--no-game", action="store_true")
    r.add_argument("--no-minds", action="store_true")
    r.add_argument("--keep", dest="delete", action="store_false", help="keep the database afterwards")
    r.add_argument("--smoke", action="store_true", help="a short run: 6 battle, 4 walkers, 20 s warm-up, 90 s window")
    an = sub.add_parser("analyze")
    an.add_argument("dir")
    c = sub.add_parser("cleanup")
    c.add_argument("--container", action="store_true", help="also stop and remove the container and its volume")
    a = ap.parse_args()
    if a.cmd == "run":
        if a.smoke:
            a.battle, a.walkers, a.warmup, a.seconds, a.calm = min(a.battle, 6), min(a.walkers, 4), 20, 90, 30
        run(a)
    elif a.cmd == "analyze":
        analyze(a.dir)
    else:
        cleanup(a)


if __name__ == "__main__":
    main()
