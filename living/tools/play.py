#!/usr/bin/env python3
"""Play a scene with one command, and leave nothing paid running after the game client exits.

    python3 living/tools/play.py SCENE                  # create or resume the scene's world, its memory
                                                        # store, its minds and the game client
    python3 living/tools/play.py SCENE --fresh          # delete the current world first (says what, asks)
    python3 living/tools/play.py SCENE --no-minds       # the world and the client only (no model calls)
    python3 living/tools/play.py SCENE --now            # do not wait for heavy jobs already running
    python3 living/tools/play.py SCENE --no-client --minds-without-client [--minutes N]
                                                        # minds with nobody playing (paid; prints $/hour)
    python3 living/tools/play.py SCENE --status         # what is running, and the run's cost so far
    python3 living/tools/play.py SCENE --stop           # close a session left behind (by recorded PIDs)
    python3 living/tools/play.py --cost JOURNAL_DIR [--since-ms MS] [--until-ms MS]
                                                        # price a journal with living/tools/trials.py

`just living-play SCENE [options]` runs the same. SCENE is a directory holding `play.json` (or the
path of such a file); docs/LIVING_CORE.md "Play with one command" documents the format.

While the game is open the launcher holds the laptop's build lock (.local/build-slots/session,
taken when the client starts), so build-slot starts no new heavy job; before that, it waits
(without the lock) for jobs already running. Tests set PLAY_BUILD_SLOTS (or PLAY_SESSION_LOCK)
to a scratch path: only the owner's sessions may hold the real lock.

When the client exits, whether the player quit or it crashed, the launcher:
  1. pauses the world (the offline takeover does not fire while it is paused);
  2. stops the mind service by its recorded PID, after checking that PID is still that process;
  3. stops the memory store (Neo4j) by its exact container name (its volume is kept);
  4. prints what the session cost, from the run's journal, at living/tools/trials.py's prices;
  5. runs tool 1's report (living/tools/play_report.py) when that file exists.
A detached warden does the same if the launcher itself dies (killed, or its terminal closed).

Starting again resumes the same world and the same minds (the same LIVING_RUN). Secrets (the
admin token, the Neo4j password, provider keys) are passed in child environments only, never
printed or written to logs.
"""
import argparse
import contextlib
import datetime
import fcntl
import gzip
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPORT = TOOLS / "play_report.py"
# The laptop's heavy-job slots (.local/bin/build-slot). While a game is open the launcher holds
# <slots>/session/{pid,since}; build-slot starts no new heavy job while that pid lives.
BUILD_SLOTS = Path(os.environ.get("PLAY_BUILD_SLOTS", "/Users/carlid/dev/slop-art-online/.local/build-slots"))
# The lock itself. Tests point PLAY_SESSION_LOCK at a scratch path; only the owner's sessions hold
# the real one, which stops every heavy job on the laptop.
SESSION_LOCK = Path(os.environ.get("PLAY_SESSION_LOCK", str(BUILD_SLOTS / "session")))
JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
# Never ours to start or stop: the shared lab store holds the paused reference worlds' minds.
SHARED_NEO4J = {"sao-living-neo4j-1"}
SHARED_NEO4J_PORTS = {7689}
CLIENT_LOG_READY = "connected as "     # the client's log line once its connection is open
MIND_LOG_READY = "world subscribed"


class Stop(Exception):
    """A signal asked the launcher to end the session."""


class Refuse(Exception):
    """A precondition failed before anything was started."""


class _Guard:
    """Signals that arrive inside a critical section (a child started but not yet recorded, a
    teardown) are held and acted on when it ends, so nothing paid is ever left unrecorded."""
    depth = 0
    pending = None


GUARD = _Guard()
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@contextlib.contextmanager
def critical():
    GUARD.depth += 1
    try:
        yield
    finally:
        GUARD.depth -= 1
        if GUARD.depth == 0 and GUARD.pending:
            name, GUARD.pending = GUARD.pending, None
            raise Stop(name)


def hold_signals_for_good():
    """From here on (the teardown) signals are noted and ignored; they cannot interrupt it."""
    GUARD.depth += 1


def run_cmd(cmd, timeout, **kw):
    """subprocess.run with a timeout: a wedged Docker or tool never blocks the teardown."""
    try:
        return subprocess.run(cmd, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, stdout="" if kw.get("text") else b"",
                                           stderr=f"timed out after {timeout} s" if kw.get("text") else b"")


def say(*parts):
    # The terminal may be gone (SIGHUP); never let a print stop the teardown.
    try:
        print(*parts, flush=True)
    except (OSError, ValueError):
        pass


def now_ms():
    return int(time.time() * 1000)


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path, data, mode=None):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- the scene


class Scene:
    """A scene's play.json, with its paths resolved (relative paths are relative to its directory)."""

    def __init__(self, path):
        p = Path(path).expanduser().resolve()
        f = p / "play.json" if p.is_dir() else p
        if not f.is_file():
            raise Refuse(f"no scene config at {f}")
        self.file = f
        self.dir = f.parent
        try:
            c = json.loads(f.read_text())
        except ValueError as e:
            raise Refuse(f"{f}: not JSON ({e})")
        self.raw = c
        self.name = c.get("name") or self.dir.name
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.name):
            raise Refuse(f"scene name {self.name!r}: use letters, digits, - and _")
        self.about = c.get("about", "")
        self.state = self.path(c.get("state", "."))
        self.server = c.get("server", "http://127.0.0.1:3300").rstrip("/")
        self.container = c.get("stdb_container", "sao-living_spacetimedb_1")
        self.db_pattern = c.get("db", "")
        self.run_pattern = c.get("run", "")
        if not self.db_pattern.startswith("verify-") or "{stamp}" not in self.db_pattern:
            raise Refuse(f"{f}: \"db\" must start with verify- and contain {{stamp}} (got {self.db_pattern!r})")
        if "{stamp}" not in self.run_pattern:
            raise Refuse(f"{f}: \"run\" must contain {{stamp}} (got {self.run_pattern!r})")
        w = c.get("world") or {}
        self.wasm = self.path(w.get("wasm")) if w.get("wasm") else None
        self.floor_seed = self.path(w["create_floor"]) if w.get("create_floor") else None
        self.seed = self.path(c["seed"]) if c.get("seed") else None
        self.laws_check = c.get("laws_check")
        cl = c.get("client") or {}
        self.client_bin = self.path(cl.get("bin")) if cl.get("bin") else None
        self.client_cwd = self.path(cl.get("cwd", "{state}"))
        self.character = cl.get("name", "Wanderer")
        self.token_pattern = cl.get("token", "{state}/tokens/{db}.token")
        self.client_env = dict(cl.get("env") or {})
        m = c.get("minds")
        self.minds = None
        if m:
            self.minds = {
                "bin": self.path(m["bin"]),
                "root": self.path(m["root"]),
                "dotenv": self.path(m["dotenv"]) if m.get("dotenv") else None,
                "env": dict(m.get("env") or {}),
                "cost_per_hour": m.get("cost_per_hour", ""),
            }
        n = c.get("neo4j")
        self.neo4j = None
        if n:
            self.neo4j = {
                "container": n["container"],
                "port": int(n["port"]),
                "image": n.get("image", "neo4j:2026.10.1"),
                "volume": n.get("volume", f"{n['container']}-data"),
                "password_file": self.path(n.get("password_file", "{state}/neo4j.env")),
                "heap": n.get("heap", "1G"),
                "pagecache": n.get("pagecache", "512M"),
            }
            if self.neo4j["container"] in SHARED_NEO4J or self.neo4j["port"] in SHARED_NEO4J_PORTS:
                raise Refuse(f"{f}: Neo4j {self.neo4j['container']}:{self.neo4j['port']} is the shared lab store; give the scene its own")
        if self.neo4j and not self.minds:
            raise Refuse(f"{f}: a memory store without minds has nothing to serve; drop \"neo4j\" or add \"minds\"")

    def path(self, value):
        if value is None:
            return None
        v = str(value).replace("{scene}", str(self.dir))
        if "{state}" in v:
            v = v.replace("{state}", str(getattr(self, "state", self.dir)))
        p = Path(v).expanduser()
        return (p if p.is_absolute() else self.dir / p).resolve()

    def fill(self, text, **kw):
        out = str(text).replace("{scene}", str(self.dir)).replace("{state}", str(self.state))
        out = out.replace("{server}", self.server)
        for k, v in kw.items():
            out = out.replace("{" + k + "}", str(v))
        return out

    # State kept in the scene's state directory.
    @property
    def current_file(self):
        return self.state / "current.json"

    @property
    def session_file(self):
        return self.state / "session.json"

    def run_dir(self, run):
        return self.state / "runs" / run

    def journal_dir(self, run):
        return self.minds["root"] / ".local/living/journal" / run if self.minds else None

    @staticmethod
    def _matches(pattern, name):
        rx = re.escape(pattern).replace(re.escape("{stamp}"), r"\d{8}-\d{6}")
        return bool(re.fullmatch(rx, name or ""))

    def db_ok(self, db):
        return db.startswith("verify-") and self._matches(self.db_pattern, db)

    def run_ok(self, run):
        return self._matches(self.run_pattern, run)


# ---------------------------------------------------------------- processes


def proc_identity(pid):
    """(start time, command path) of a live pid, or None. Used to check a recorded PID is still ours."""
    if not pid:
        return None
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError):
        return None
    except PermissionError:
        pass
    # A fixed locale and zone: lstart's text depends on both, and the identity is compared later
    # from other shells (--stop) or after the laptop's time zone changed.
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "TZ": "UTC"}
    r1 = run_cmd(["ps", "-o", "lstart=", "-p", str(pid)], 10, capture_output=True, text=True, env=env)
    r2 = run_cmd(["ps", "-o", "comm=", "-p", str(pid)], 10, capture_output=True, text=True, env=env)
    start, comm = r1.stdout.strip(), r2.stdout.strip()
    if r1.returncode or not start:
        return None
    return start, comm


def is_same(pid, ident, binary=None):
    """True when `pid` is still the process recorded as `ident` (its start time and command), and,
    when `binary` is given, that command is that binary."""
    if not pid or not ident:
        return False
    now = proc_identity(pid)
    if not now or list(now) != list(ident):
        return False
    return binary is None or Path(now[1]).name == Path(binary).name


def alive(pid):
    return proc_identity(pid) is not None


def stop_pid(pid, ident, binary, popen=None, label="process"):
    """Stop one process by PID, only if it is still the process we started. Returns what happened."""
    if not pid:
        return f"{label}: none recorded"
    if popen is not None and popen.poll() is not None:
        return f"{label} pid {pid}: already exited ({popen.returncode})"
    # Our own unreaped child cannot have had its PID reused: holding its Popen is proof enough.
    ours = (lambda: popen.poll() is None) if popen is not None else (lambda: is_same(pid, ident, binary))
    if popen is None and not alive(pid):
        return f"{label} pid {pid}: already gone"
    if not ours():
        return f"{label} pid {pid}: no longer the {Path(binary).name} we started; not signalled"
    sent = []
    for sig, wait in ((signal.SIGINT, 15), (signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        if not ours():
            break
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            break
        sent.append(sig.name)
        end = time.time() + wait
        while time.time() < end:
            if popen is not None:
                if popen.poll() is not None:
                    break
            elif not alive(pid):
                break
            time.sleep(0.2)
        gone = popen.poll() is not None if popen is not None else not alive(pid)
        if gone:
            return f"{label} pid {pid}: stopped ({' then '.join(sent)})"
    if ours():
        return f"{label} pid {pid}: STILL RUNNING after {' then '.join(sent)}"
    if popen is None and alive(pid):
        return f"{label} pid {pid}: a process with this PID runs but no longer matches what we started; check it"
    return f"{label} pid {pid}: stopped ({' then '.join(sent) or 'it exited'})"


# ---------------------------------------------------------------- SpacetimeDB


class World:
    def __init__(self, scene):
        self.s = scene
        self._token = None

    def cli(self, *args, check=True, stdout=None, input_text=None, timeout=60):
        cmd = ["docker", "exec", "-i", self.s.container, "spacetime", *args]
        r = run_cmd(cmd, timeout, capture_output=stdout is None, stdout=stdout,
                    stderr=subprocess.STDOUT if stdout else None, text=True, input=input_text)
        if check and r.returncode:
            out = (r.stdout or "") if stdout is None else ""
            raise Refuse(f"spacetime {args[0]} failed (exit {r.returncode}) {out.strip()[-400:]}")
        return r

    def token(self):
        """The world admin's token (the in-container CLI identity), kept in memory only."""
        if not self._token:
            r = self.cli("login", "show", "--token", check=False)
            m = JWT.findall((r.stdout or "") + (r.stderr or ""))
            if not m:
                raise Refuse("could not read the admin token from the SpacetimeDB container's CLI")
            self._token = m[-1]
        return self._token

    def http(self, method, path, body=None, timeout=30):
        req = urllib.request.Request(self.s.server + path, data=body, method=method)
        req.add_header("Authorization", "Bearer " + self.token())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def sql(self, db, query):
        code, body = self.http("POST", f"/v1/database/{db}/sql", query.encode())
        if code != 200:
            return code, None
        data = json.loads(body)
        return code, (data[0]["rows"] if data else [])

    def exists(self, db):
        """True if the database answers, False only on 404; any other answer is an error, not 'gone'."""
        code, _ = self.sql(db, "SELECT paused FROM world")
        if code == 200:
            return True
        if code == 404:
            return False
        raise Refuse(f"SpacetimeDB answered HTTP {code} for {db}; cannot tell whether it exists")

    def paused(self, db):
        code, rows = self.sql(db, "SELECT paused FROM world")
        return bool(rows and rows[0][0]) if code == 200 else None

    def ticks(self, db):
        code, rows = self.sql(db, "SELECT ticks FROM stats")
        return rows[0][0] if code == 200 and rows else None

    def set_paused(self, db, value):
        self.cli("call", "-s", "local", db, "set_paused", "true" if value else "false", timeout=30)
        if self.paused(db) != value:
            raise Refuse(f"set_paused {value} on {db} did not take (paused reads {self.paused(db)})")

    def ping(self):
        try:
            with urllib.request.urlopen(self.s.server + "/v1/ping", timeout=5) as r:
                return r.status == 200
        except OSError:
            return False

    def wasm_mount(self):
        r = run_cmd(["docker", "inspect", self.s.container, "--format",
                     '{{range .Mounts}}{{if eq .Destination "/wasm"}}{{.Source}}{{end}}{{end}}'],
                    30, capture_output=True, text=True)
        m = re.sub(r"^/host_mnt", "", r.stdout.strip())
        if not m or not Path(m).is_dir():
            raise Refuse(f"the server's /wasm mount ({m!r}) is not a directory")
        return Path(m)

    def publish(self, db, log_path):
        if self.exists(db):
            raise Refuse(f"database {db} already exists; not publishing over it")
        name = f"living_authority_{self.s.name}.wasm"
        target = self.wasm_mount() / name
        target.write_bytes(self.s.wasm.read_bytes())
        try:
            with open(log_path, "w") as log:
                r = self.cli("publish", "-s", "local", "-b", f"/wasm/{name}", db, "--delete-data", "-y",
                             check=False, stdout=log, timeout=900)
        finally:
            target.unlink(missing_ok=True)     # the module is stored in the database once published
        if r.returncode:
            raise Refuse(f"publish of {db} failed; see {log_path}")
        if self.s.floor_seed:
            seed = json.loads(self.s.floor_seed.read_text())
            if seed.get("laws_file") and not str(seed.get("laws") or "").strip():
                base = self.s.minds["root"] / "living/seeds" if self.s.minds else TOOLS.parent / "seeds"
                seed["laws"] = (base / seed["laws_file"]).read_text()   # the build's seeds when known
            code, body = self.http("POST", f"/v1/database/{db}/call/create_floor",
                                   json.dumps([json.dumps(seed)]).encode(), timeout=600)
            if code != 200:
                raise Refuse(f"create_floor on {db} failed (HTTP {code}): {body[:300]!r}")
            end = time.time() + 1800
            while time.time() < end:
                code, rows = self.sql(db, "SELECT done, label FROM genesis")
                if code == 200 and rows and rows[0][0]:
                    break
                time.sleep(3)
            else:
                raise Refuse(f"{db}: genesis not done after 30 minutes")

    def delete(self, db):
        if not self.s.db_ok(db):
            raise Refuse(f"refusing to delete {db}: not this scene's database pattern {self.s.db_pattern}")
        self.cli("delete", "-s", "local", db, "-y", check=False, timeout=120)
        code, _ = self.http("POST", f"/v1/database/{db}/sql", b"SELECT 1 FROM world")
        if code != 404:
            raise Refuse(f"{db} still answers SQL (HTTP {code}) after delete")


# ---------------------------------------------------------------- Neo4j


def docker_state(name):
    r = run_cmd(["docker", "inspect", "-f", "{{.State.Running}}", name], 30, capture_output=True, text=True)
    if r.returncode:
        return None
    return r.stdout.strip() == "true"


def port_free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def neo4j_password(n):
    f = n["password_file"]
    if not f.exists():
        vol = run_cmd(["docker", "volume", "inspect", n["volume"]], 30, capture_output=True, text=True)
        if vol.returncode == 0:
            raise Refuse(f"{f} is missing but volume {n['volume']} exists: its store keeps the old password. "
                         "Restore the file; a new password would lock the minds out")
        f.parent.mkdir(parents=True, exist_ok=True)
        old = os.umask(0o077)
        try:
            f.write_text(f"LIVING_NEO4J_PASSWORD={secrets.token_urlsafe(24)}\n")
        finally:
            os.umask(old)
    for line in f.read_text().splitlines():
        if line.startswith("LIVING_NEO4J_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise Refuse(f"{f} has no LIVING_NEO4J_PASSWORD line")


def neo4j_up(n, log, scene_name):
    name, port = n["container"], n["port"]
    pw = neo4j_password(n)
    since = str(int(time.time()) - 1)
    state = docker_state(name)
    if state is None:
        if not port_free(port):
            raise Refuse(f"port {port} is taken; Neo4j {name} cannot use it")
        env = dict(os.environ, NEO4J_AUTH=f"neo4j/{pw}")
        r = run_cmd(["docker", "run", "-d", "--name", name, "--label", f"sao.play.scene={scene_name}",
                            "-p", f"127.0.0.1:{port}:7687", "-e", "NEO4J_AUTH",
                            "-e", f"NEO4J_server_memory_heap_max__size={n['heap']}",
                            "-e", f"NEO4J_server_memory_pagecache_size={n['pagecache']}",
                            "-v", f"{n['volume']}:/data", n["image"]], 120, capture_output=True, text=True, env=env)
        if r.returncode:
            raise Refuse(f"docker run {name} failed: {r.stderr.strip()[-300:]}")
        log(f"created Neo4j container {name} (volume {n['volume']}, bolt 127.0.0.1:{port})")
    else:
        lab = run_cmd(["docker", "inspect", "-f", '{{index .Config.Labels "sao.play.scene"}}', name], 30,
                      capture_output=True, text=True).stdout.strip()
        if lab != scene_name:
            raise Refuse(f"container {name} exists but was not made by play.py for scene {scene_name} "
                         f"(label sao.play.scene={lab or 'none'}); not using it. Name the scene's own container")
        r = run_cmd(["docker", "inspect", "-f", "{{json .HostConfig.PortBindings}}", name], 30,
                    capture_output=True, text=True)
        try:
            binds = (json.loads(r.stdout) or {}).get("7687/tcp") or []
        except ValueError:
            binds = []
        if not any(str(b.get("HostPort")) == str(port) for b in binds):
            raise Refuse(f"container {name} does not publish bolt on 127.0.0.1:{port} ({r.stdout.strip()!r})")
        if not state:
            if not port_free(port):
                raise Refuse(f"port {port} is taken; Neo4j {name} cannot start on it")
            r = run_cmd(["docker", "start", name], 120, capture_output=True, text=True)
            if r.returncode:
                raise Refuse(f"docker start {name} failed: {r.stderr.strip()[-300:]}")
    end = time.time() + 180
    while time.time() < end:
        r = run_cmd(["docker", "logs", "--since", since, name], 30, capture_output=True, text=True)
        if "Started." in (r.stdout + r.stderr) and port_open(port):
            return pw
        if docker_state(name) is False:
            raise Refuse(f"Neo4j {name} exited while starting (docker logs {name})")
        time.sleep(2)
    raise Refuse(f"Neo4j {name} did not start within 3 minutes (docker logs {name})")


def neo4j_down(name):
    state = docker_state(name)
    if state is None:
        return f"Neo4j {name}: no such container"
    if state:
        run_cmd(["docker", "stop", "-t", "30", name], 90, capture_output=True, text=True)
    state = docker_state(name)
    return f"Neo4j {name}: stopped (volume kept)" if state is False else f"Neo4j {name}: STILL RUNNING"


# ---------------------------------------------------------------- cost


def journal_cost(jdir, since_ms=None, until_ms=None):
    """Price a journal directory's records with living/tools/trials.py's prices (as llm_load.py and
    the play-test proof's spend.py read it). since/until (epoch ms) select one session's calls."""
    sys.path.insert(0, str(TOOLS))
    import trials  # constants only at import
    jdir = Path(jdir)
    if jdir.is_dir() and not list(jdir.glob("*.jsonl*")) or (jdir / "journal").is_dir() and not _has_records(jdir):
        if (jdir / "journal").is_dir():
            jdir = jdir / "journal"              # an evidence folder holding a journal copy
    tot = {"journal": str(jdir), "calls": 0, "errors": 0, "usd": 0.0, "unpriced": 0, "batch": 0, "prompt": 0, "completion": 0,
           "cached": 0, "first_ms": None, "last_ms": None, "unpriced_models": {}, "by_model": {}, "by_purpose": {}}
    files = sorted(jdir.glob("*.jsonl")) + sorted(jdir.glob("*.jsonl.gz")) if jdir.is_dir() else []
    for f in files:
        opener = gzip.open if f.suffix == ".gz" else open
        with opener(f, "rt") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(r, dict) or "model" not in r or "purpose" not in r:
                    continue                     # not a model exchange (a transcript or other log)
                at = r.get("at_ms") or 0
                if since_ms is not None and at < since_ms or until_ms is not None and at > until_ms:
                    continue
                p, c, k = r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0, r.get("cached_tokens") or 0
                model = r.get("model")
                usd = trials.cost(model, p, c, k)
                tot["calls"] += 1
                tot["errors"] += 1 if r.get("error") else 0
                tot["batch"] += 1 if r.get("mode") == "batch" else 0
                if usd is None:
                    usd = 0.0
                    if p or c:
                        tot["unpriced"] += 1
                        tot["unpriced_models"][str(model)] = tot["unpriced_models"].get(str(model), 0) + 1
                tot["usd"] += usd
                tot["prompt"] += p
                tot["completion"] += c
                tot["cached"] += k
                tot["first_ms"] = at if tot["first_ms"] is None else min(tot["first_ms"], at)
                tot["last_ms"] = at if tot["last_ms"] is None else max(tot["last_ms"], at)
                for key, val in (("by_model", str(model)), ("by_purpose", str(r.get("purpose")))):
                    b = tot[key].setdefault(val, {"calls": 0, "usd": 0.0})
                    b["calls"] += 1
                    b["usd"] += usd
    tot["pending_batches"] = len(list((jdir / "batches").glob("*.json"))) if (jdir / "batches").is_dir() else 0
    return tot


def _has_records(jdir):
    for f in Path(jdir).glob("*.jsonl"):
        with open(f) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and "model" in r and "purpose" in r:
                    return True
    return False


def cost_line(t, label):
    s = f"{label} ${t['usd']:.2f} (${t['usd']:.4f}; {t['calls']} calls, {t['errors']} errors"
    if t["unpriced"]:
        models = ", ".join(f"{m} {n}" for m, n in sorted(t["unpriced_models"].items()))
        s += f"; {t['unpriced']} on models with no price in trials.py: {models}"
    if t["batch"]:
        s += f"; {t['batch']} batch answers at list price"
    s += ")"
    if t.get("pending_batches"):
        s += f"; {t['pending_batches']} batch job(s) still pending: they are collected and journaled at the next start"
    return s


# ---------------------------------------------------------------- the build lock


def held_slots():
    """Heavy jobs running now: build-slot's slot-N directories whose pid lives."""
    out = []
    for d in sorted(BUILD_SLOTS.glob("slot-*")):
        try:
            pid = int((d / "pid").read_text().split()[0])
        except (OSError, ValueError, IndexError):
            continue
        if alive(pid):
            label = (d / "label").read_text().strip() if (d / "label").is_file() else "?"
            since = (d / "since").read_text().strip() if (d / "since").is_file() else "?"
            out.append(f"{d.name}: {label} (pid {pid}, since {since})")
    return out


def lock_builds(pid, lock=None):
    """Hold the build lock for a play session (pid = the launcher). Returns what happened."""
    lock = Path(lock or SESSION_LOCK)
    if not lock.parent.is_dir():
        return f"no build-slot directory at {lock.parent}; nothing to hold"
    for _ in range(2):
        try:
            lock.mkdir()
        except FileExistsError:
            try:
                other = int((lock / "pid").read_text().split()[0])
            except (OSError, ValueError, IndexError):
                other = None
            if other and other != pid and alive(other):
                return f"build lock already held by pid {other} (another session); builds stay held"
            for f in lock.glob("*"):          # stale: its launcher is dead
                f.unlink()
            lock.rmdir()
            continue
        (lock / "pid").write_text(f"{pid}\n")
        (lock / "since").write_text(time.strftime("%H:%M:%S") + "\n")
        return f"build lock held ({lock}, pid {pid}): no new heavy job starts until the game closes"
    return "could not take the build lock"


def repoint_builds(old, new, lock=None):
    """The warden takes over the lock when the launcher dies while the game still runs."""
    f = Path(lock or SESSION_LOCK) / "pid"
    try:
        if int(f.read_text().split()[0]) == old:
            f.write_text(f"{new}\n")
            return True
    except (OSError, ValueError, IndexError):
        pass
    return False


def unlock_builds(pids, lock=None):
    """Remove the build lock if one of `pids` (the launcher, the warden) holds it."""
    lock = Path(lock or SESSION_LOCK)
    try:
        holder = int((lock / "pid").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return "build lock: not held"
    if holder not in [p for p in pids if p]:
        return f"build lock: held by pid {holder}, not this session; left alone"
    for f in lock.glob("*"):
        f.unlink()
    lock.rmdir()
    return "build lock released: heavy jobs may start again"


def wait_for_builds(log, now):
    """Before the game opens: let heavy jobs already running finish (the lock stops new ones)."""
    jobs = held_slots()
    if not jobs:
        return
    if now:
        log(f"--now: starting while {len(jobs)} heavy job(s) run; the frame rate may suffer: " + "; ".join(jobs))
        return
    log(f"waiting for {len(jobs)} heavy job(s) to finish before the game opens (--now to start anyway; "
        "the frame rate may suffer):")
    for j in jobs:
        log("  " + j)
    start = shown = time.time()
    last = jobs
    while jobs:
        time.sleep(5)
        jobs = held_slots()
        if jobs and (jobs != last or time.time() - shown >= 60):
            log(f"  still waiting ({(time.time() - start) / 60:.0f} min): {len(jobs)} running: " + "; ".join(jobs))
            shown, last = time.time(), jobs
    log("heavy jobs finished; starting")


# ---------------------------------------------------------------- the session


def scrub_env(extra):
    """The launcher's environment without LIVING_*/TRIALS_* settings from the shell, plus `extra`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LIVING_", "TRIALS_"))}
    env.update({k: str(v) for k, v in extra.items()})
    return env


class Session:
    def __init__(self, scene, args):
        self.s = scene
        self.a = args
        self.w = World(scene)
        self.info = {}
        self.client = None
        self.mind = None
        self.dir = None
        self.capture = None
        self.locked = False
        self.fresh_ok = False
        self.pending = []          # log lines from before the session directory exists

    # -- state
    def save(self):
        write_json(self.s.session_file, self.info)
        if self.dir:
            write_json(self.dir / "session.json", self.info)

    def log(self, msg):
        say(msg)
        self.pending.append(f"{utc()} {msg}\n")
        if self.dir:
            with open(self.dir / "launcher.log", "a") as f:
                f.writelines(self.pending)
            self.pending = []

    # -- preflight
    def preflight(self, want_minds, want_client):
        s = self.s
        missing = []
        if want_client and not (s.client_bin and s.client_bin.is_file()):
            missing.append(f"client {s.client_bin}")
        if s.wasm and not s.wasm.is_file():
            missing.append(f"authority wasm {s.wasm}")
        if not s.wasm:
            missing.append("world.wasm in play.json")
        if s.floor_seed and not s.floor_seed.is_file():
            missing.append(f"floor seed {s.floor_seed}")
        if want_minds:
            m = s.minds
            if not m["bin"].is_file():
                missing.append(f"mind service {m['bin']}")
            if not (m["root"] / "living/Cargo.toml").is_file():
                missing.append(f"mind root checkout {m['root']} (its living/Cargo.toml)")
            if not (s.seed and s.seed.is_file()):
                missing.append(f"seed {s.seed}")
            if s.neo4j:
                r = run_cmd(["docker", "image", "inspect", s.neo4j["image"]], 30, capture_output=True)
                if r.returncode:
                    missing.append(f"Neo4j image {s.neo4j['image']} (not pulled)")
                if docker_state(s.neo4j["container"]) is not None:
                    lab = run_cmd(["docker", "inspect", "-f", '{{index .Config.Labels "sao.play.scene"}}',
                                   s.neo4j["container"]], 30, capture_output=True, text=True).stdout.strip()
                    if lab != s.name:
                        raise Refuse(f"container {s.neo4j['container']} exists but was not made by play.py for scene "
                                     f"{s.name} (label sao.play.scene={lab or 'none'}); not using or stopping it. "
                                     "Give the scene its own container name")
        if missing:
            raise Refuse("missing: " + "; ".join(missing))
        if docker_state(s.container) is not True:
            raise Refuse(f"SpacetimeDB container {s.container} is not running (just living-up)")
        if not self.w.ping():
            raise Refuse(f"SpacetimeDB does not answer {s.server}/v1/ping")

    # -- the world
    def choose_world(self):
        s, w = self.s, self.w
        cur = read_json(s.current_file)
        if cur and not (s.db_ok(cur.get("db", "")) and s.run_ok(cur.get("run", ""))):
            raise Refuse(f"{s.current_file} names {cur.get('db')!r} / {cur.get('run')!r}, which are not this scene's "
                         f"patterns {s.db_pattern} / {s.run_pattern}")
        if self.a.fresh and cur:
            db, run = cur["db"], cur["run"]
            if w.exists(db):
                self.confirm_fresh(cur)          # already asked before any wait; a no-op then
                w.delete(db)
                self.log(f"deleted {db} (SQL now answers 404)")
            else:
                self.log(f"world {db} no longer exists; making a new one")
            s.run_dir(run).mkdir(parents=True, exist_ok=True)
            os.replace(s.current_file, s.run_dir(run) / "current.deleted.json")
            cur = None
        if cur and cur.get("status") == "creating":
            if not self.a.fresh:
                raise Refuse(f"world {cur['db']} was never finished (its creation was interrupted); "
                             "start with --fresh to delete it and make a new one")
        if cur:
            if not w.exists(cur["db"]):
                raise Refuse(f"world {cur['db']} (from {s.current_file}) no longer exists; "
                             "start with --fresh for a new one")
            self.log(f"resuming world {cur['db']} (run {cur['run']}, created {cur.get('created_utc')})")
            return cur["db"], cur["run"], False
        st = stamp()
        db, run = s.db_pattern.replace("{stamp}", st), s.run_pattern.replace("{stamp}", st)
        rd = s.run_dir(run)
        rd.mkdir(parents=True, exist_ok=True)
        self.log(f"creating world {db} (run {run}){': ' + s.about if s.about else ''}")
        # Recorded before publishing, so an interrupted creation is never an untracked world.
        write_json(s.current_file, {"db": db, "run": run, "status": "creating", "scene": s.name})
        try:
            w.publish(db, rd / "publish.log")
        except BaseException as e:
            hold_signals_for_good()
            try:
                if w.exists(db):
                    w.delete(db)
                    self.log(f"the creation failed ({e or type(e).__name__}); deleted the half-made {db}")
            except Exception as e2:  # noqa: BLE001
                self.log(f"the creation failed and {db} could not be deleted ({e2}); --fresh deletes it")
                raise
            os.replace(s.current_file, rd / "current.failed.json")
            raise
        write_json(s.current_file, {"db": db, "run": run, "created_utc": utc(), "scene": s.name})
        return db, run, True

    def confirm_fresh(self, cur):
        """Say what --fresh deletes and ask (or require --yes), once, before anything waits or starts."""
        if self.fresh_ok:
            return
        s = self.s
        db, run = cur["db"], cur["run"]
        if cur.get("status") == "creating":
            self.log(f"world {db} was never finished; --fresh deletes it")
        jd = s.journal_dir(run)
        self.log(f"--fresh deletes world {db} (run {run}): the database and everything in it")
        self.log("  (its people, places, chronicle and your character there).")
        self.log("  Kept: the run's logs in " + str(s.run_dir(run)))
        if jd:
            self.log(f"  the model journal {jd}")
        if s.neo4j:
            self.log(f"  and the minds' memories of run {run} in Neo4j {s.neo4j['container']} "
                     "(keyed by run; the new world's minds start empty).")
        if not self.a.yes:
            if not sys.stdin.isatty():
                raise Refuse("--fresh needs --yes when not run from a terminal")
            if input(f"delete {db}? [y/N] ").strip().lower() not in ("y", "yes"):
                raise Refuse("not deleted; nothing changed")
        self.fresh_ok = True

    def check_laws(self, db):
        if not self.s.laws_check:
            return
        cmd = [self.s.fill(x, db=db, seed=self.s.seed or "", outdir=self.dir) for x in self.s.laws_check]
        with open(self.dir / "laws_check.log", "w") as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=self.s.dir, env=scrub_env({}))
        if r.returncode:
            raise Refuse(f"the laws read-back failed ({self.dir / 'laws_check.log'}); the world was left paused. "
                         "Start with --fresh for a new world")
        self.log(f"laws read back: passed ({self.dir / 'laws_check.log'})")

    # -- children
    def start_neo4j(self):
        n = self.s.neo4j
        self.log(f"starting memory store {n['container']} (bolt 127.0.0.1:{n['port']}) ...")
        with critical():
            # Recorded (and so stopped at the end) only once it is known to be this scene's.
            pw = neo4j_up(n, self.log, self.s.name)
            self.info["neo4j"] = n["container"]
            self.save()
        return pw

    def start_mind(self, db, run, pw):
        m, s = self.s.minds, self.s
        if m["dotenv"] and not (m["root"] / ".env").exists():
            os.symlink(m["dotenv"], m["root"] / ".env")       # provider keys; never read here
        seeds = m["root"] / "living/seeds"
        seed = os.path.relpath(s.seed, seeds)
        seed = seed[:-5] if seed.endswith(".json") else seed
        env = {"LIVING_ROOT": m["root"], "LIVING_SERVER": s.server, "LIVING_DB": db, "LIVING_RUN": run,
               "LIVING_SEED": seed, "LIVING_TOKEN": self.w.token(),
               "RUST_LOG": "info,neo4rs=warn,spacetimedb_sdk=warn"}
        if pw:
            env.update({"LIVING_NEO4J_URI": f"127.0.0.1:{s.neo4j['port']}", "LIVING_NEO4J_PASSWORD": pw})
        else:
            env.update({"LIVING_NEO4J": "off", "LIVING_NEO4J_PASSWORD": ""})
        env.update({k: s.fill(v, db=db, run=run, session=self.dir) for k, v in m["env"].items()})
        with critical(), open(self.dir / "mind.log", "ab") as log:
            self.mind = subprocess.Popen([str(m["bin"])], cwd=m["root"], env=scrub_env(env), stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            self.info.update({"mind_pid": self.mind.pid, "mind_bin": str(m["bin"]), "journal": str(s.journal_dir(run))})
            self.save()
            self.info["mind_ident"] = proc_identity(self.mind.pid)
            self.save()
        self.log(f"mind service pid {self.mind.pid} (run {run}) ...")
        end = time.time() + 120
        while time.time() < end:
            if self.mind.poll() is not None:
                raise Refuse(f"the mind service exited at once ({self.mind.returncode}); see {self.dir / 'mind.log'}")
            if MIND_LOG_READY in (self.dir / "mind.log").read_text(errors="replace"):
                return
            time.sleep(0.5)
        raise Refuse(f"the mind service did not subscribe within 2 minutes; see {self.dir / 'mind.log'}")

    def start_client(self, db):
        s = self.s
        token = Path(s.fill(s.token_pattern, db=db))
        token.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {"LIVING_SERVER": s.server, "LIVING_DB": db, "LIVING_GAME_NAME": self.a.name or s.character,
               "LIVING_GAME_TOKEN": token, "NO_COLOR": "1"}
        env.update({k: s.fill(v, db=db, session=self.dir) for k, v in s.client_env.items()})
        for kv in self.a.client_env or []:
            k, _, v = kv.partition("=")
            env[k] = s.fill(v, db=db, session=self.dir)
        if self.capture:
            # The client records its own frames (the session's video), state and presses.
            env["LIVING_GAME_RECORD"] = self.capture / "client"
            if self.a.no_video:
                env["LIVING_GAME_RECORD_FPS"] = "0"   # stills every few seconds instead of video
        with critical():
            self.info["build_lock"] = lock_builds(os.getpid(), self.info["build_lock_path"])
            self.locked = True
            self.save()
        self.log(self.info["build_lock"])
        late = held_slots()
        if late:
            self.log(f"note: {len(late)} heavy job(s) started before the lock was taken: " + "; ".join(late))
        with critical(), open(self.dir / "client.log", "ab") as log:
            self.client = subprocess.Popen([str(s.client_bin)], cwd=s.client_cwd, env=scrub_env(env),
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            self.info.update({"client_pid": self.client.pid, "client_bin": str(s.client_bin)})
            self.save()
            self.info["client_ident"] = proc_identity(self.client.pid)
            self.save()
            if self.capture:
                self.record_start(db)
        self.log(f"game client pid {self.client.pid}, joining {db} as {env['LIVING_GAME_NAME']} "
                 f"(log {self.dir / 'client.log'})")

    # -- the run
    def run(self):
        s, a = self.s, self.a
        want_minds = bool(s.minds) and not a.no_minds
        want_client = not a.no_client
        if want_minds and not want_client and not a.minds_without_client:
            raise Refuse("refusing to run paid minds with no client: they would cost money with nobody playing. "
                         "Add --minds-without-client to do it anyway, or --no-minds")
        if a.minds_without_client and not want_minds:
            raise Refuse("--minds-without-client given, but this run has no minds")
        if a.minutes is not None and want_client:
            raise Refuse("--minutes limits a run without a client; with a client the session ends when it exits")
        if a.minutes is not None and a.minutes <= 0:
            raise Refuse("--minutes must be more than 0")
        s.state.mkdir(parents=True, exist_ok=True)
        self.launch_lock()
        prior = read_json(s.session_file)
        if prior and prior.get("status") != "closed":
            if is_same(prior.get("launcher_pid"), prior.get("launcher_ident")):
                raise Refuse(f"a session of this scene is running (launcher pid {prior['launcher_pid']}); "
                             f"quit its client, or run with --stop")
            if is_same(prior.get("client_pid"), prior.get("client_ident"), prior.get("client_bin")):
                raise Refuse(f"a game of this scene is still open (client pid {prior['client_pid']}; its warden closes "
                             "the session when it exits). Quit it, or run with --stop")
            self.log("the previous session did not close; closing it first")
            with critical():
                closed = teardown(s, prior, why="left over from a previous launch", ended_ms=last_evidence_ms(prior))
            if closed is None:
                end = time.time() + 180          # its warden is closing it: wait for that
                while time.time() < end and (read_json(Path(prior["session_dir"]) / "session.json") or {}).get("status") != "closed":
                    time.sleep(1)
        self.preflight(want_minds, want_client)
        cur = read_json(s.current_file)
        if a.fresh and cur and s.db_ok(cur.get("db", "")) and self.w.exists(cur["db"]):
            self.confirm_fresh(cur)              # refuse or confirm now, not after a wait for builds
        if want_client:
            # Let heavy jobs already running finish before anything paid starts. The lock is not held
            # while waiting (nor while the world is made): it is taken when the client starts.
            wait_for_builds(self.log, self.a.now)

        db, run, created = self.choose_world()
        st = stamp()
        self.dir = s.run_dir(run) / "sessions" / st
        n = 1
        while self.dir.exists():
            n += 1
            self.dir = s.run_dir(run) / "sessions" / f"{st}-{n}"
        self.dir.mkdir(parents=True)
        report = Path(a.report_tool).resolve() if a.report_tool else REPORT
        if want_client and report.is_file() and not a.no_record:
            self.capture = self.dir / "capture"
            self.capture.mkdir(exist_ok=True)
        self.info = {"scene": str(s.file), "db": db, "run": run, "session_dir": str(self.dir), "status": "starting",
                     "started_ms": now_ms(), "started_utc": utc(), "created_world": created,
                     "launcher_pid": os.getpid(), "launcher_ident": proc_identity(os.getpid()),
                     "minds": want_minds, "client": want_client, "report_tool": str(report),
                     "build_lock_path": str(SESSION_LOCK)}
        self.save()
        self.start_warden()
        # The world stays paused until the client's connection is open, so no takeover fires for the
        # player's character before they are back, and the minds start on a still world.
        self.w.set_paused(db, True)
        self.check_laws(db)
        if want_minds:
            pw = self.start_neo4j() if s.neo4j else None
            self.start_mind(db, run, pw)
        if want_client:
            self.start_client(db)
        else:
            self.w.set_paused(db, False)
            self.log(f"world {db} unpaused (no client)")
        self.info["status"] = "running"
        self.save()
        if want_minds and not want_client:
            self.log(minds_rate(s, run, self.dir))
            limit = f" for {a.minutes} minutes" if a.minutes is not None else ""
            self.log(f"minds running without a client{limit}; Ctrl-C (or play.py {s.dir} --stop) ends it")
        self.wait(db, run, want_client)

    def wait(self, db, run, want_client):
        unpaused = not want_client
        warned_mind = False
        last_cost = time.time()
        end = time.time() + self.a.minutes * 60 if self.a.minutes is not None else None
        started, warned_at = time.time(), None
        while True:
            if want_client and self.client.poll() is not None:
                self.info["client_exit"] = self.client.returncode
                return
            if end and time.time() >= end:
                self.log(f"{self.a.minutes} minutes are up")
                return
            if not unpaused and CLIENT_LOG_READY in (self.dir / "client.log").read_text(errors="replace"):
                self.w.set_paused(db, False)
                unpaused = True
                self.info["unpaused_ms"] = now_ms()
                self.save()
                self.log(f"client connected; world {db} unpaused. Play; closing the game window ends the session")
            elif not unpaused and time.time() - started > 120 and (warned_at is None or time.time() - warned_at > 120):
                warned_at = time.time()
                self.log(f"WARNING: the client has not connected after {(time.time() - started) / 60:.0f} min; the world "
                         f"stays paused (minds idle). See {self.dir / 'client.log'}; closing the game ends the session")
            if self.mind is not None and self.mind.poll() is not None and not warned_mind:
                warned_mind = True
                self.log(f"WARNING: the mind service exited ({self.mind.returncode}); the world goes on without "
                         f"minds (no model calls). See {self.dir / 'mind.log'}")
            if self.mind is not None and not want_client and time.time() - last_cost > 300:
                last_cost = time.time()
                t = journal_cost(self.s.journal_dir(run), since_ms=self.info["started_ms"])
                self.log(cost_line(t, "so far this session"))
            time.sleep(0.5)

    def record_start(self, db):
        """Tool 1's session recorder (living/tools/play_report.py record-start): one detached process
        keeping the authority's rows. The video comes from the client itself (LIVING_GAME_RECORD)."""
        cmd = [sys.executable, self.info["report_tool"], "record-start", "--db", db, "--capture", str(self.capture)]
        self.info.update({"capture": str(self.capture), "recorder": "starting"})   # teardown stops it whatever happens
        self.save()
        with open(self.dir / "recorder.log", "a") as f:
            r = run_cmd(cmd, 60, stdout=f, stderr=subprocess.STDOUT, env=scrub_env({}))
        self.info["recorder"] = "started" if r.returncode == 0 else f"record-start failed ({r.returncode})"
        self.save()
        self.log(f"session recorder: {self.info['recorder']} (capture {self.capture}; log {self.dir / 'recorder.log'})")

    def start_warden(self):
        with critical(), open(self.dir / "warden.log", "ab") as log:
            p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(self.s.file), "--warden", str(self.dir)],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                 env=scrub_env({}))
            self.info["warden_pid"] = p.pid
            self.save()
        time.sleep(0.5)
        if p.poll() is not None:
            raise Refuse(f"the warden exited at once ({p.returncode}); see {self.dir / 'warden.log'}. Nothing paid started")
        self.info["warden_ident"] = proc_identity(p.pid)
        self.save()

    def launch_lock(self):
        """One launcher per scene: an exclusive lock held for the launcher's whole life."""
        f = self.s.state / "launch.lock"
        self.lock_fd = os.open(f, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            other = read_json(f) or {}
            raise Refuse(f"another launcher of this scene is running (pid {other.get('pid')}); "
                         f"wait for it, or end it with play.py {self.s.dir} --stop")
        os.ftruncate(self.lock_fd, 0)
        os.write(self.lock_fd, json.dumps({"pid": os.getpid(), "ident": proc_identity(os.getpid())}).encode())


def minds_rate(scene, run, session_dir):
    """The cost per hour of minds: measured on this run's earlier sessions, and the scene's estimate."""
    usd = minutes = 0.0
    for f in sorted((scene.run_dir(run) / "sessions").glob("*/cost.json")):
        c = read_json(f) or {}
        if c.get("minds_minutes"):
            usd += c["session"]["usd"]
            minutes += c["minds_minutes"]
    parts = []
    if minutes >= 5:
        parts.append(f"measured on this world's earlier sessions ${usd / minutes * 60:.2f} per hour "
                     f"(${usd:.2f} over {minutes:.0f} min)")
    if scene.minds.get("cost_per_hour"):
        parts.append(f"scene estimate: {scene.minds['cost_per_hour']}")
    return "cost while minds run: " + ("; ".join(parts) if parts else "no estimate in play.json and nothing measured yet")


# ---------------------------------------------------------------- teardown (launcher, warden or --stop)


def take_lock(session_dir):
    lock = Path(session_dir) / "teardown.lock"
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = read_json(lock) or {}
            pid = holder.get("pid")
            if pid and pid != os.getpid() and is_same(pid, holder.get("ident")):
                return False                     # another live process is tearing this session down
            lock.unlink(missing_ok=True)
            continue
        os.write(fd, json.dumps({"pid": os.getpid(), "ident": proc_identity(os.getpid())}).encode())
        os.close(fd)
        return True
    return False


def last_evidence_ms(info):
    """When a session left over (launcher and warden both gone) really ended: its newest log."""
    sdir = Path(info.get("session_dir", ""))
    times = [f.stat().st_mtime for f in sdir.glob("*") if f.is_file()] if sdir.is_dir() else []
    return int(max(times) * 1000) if times else None


def teardown(scene, info, why, client=None, mind=None, report=True, ended_ms=None):
    """Pause the world, stop the mind (by PID) and the memory store (by name), stop the client and
    tool 1's recorder, release the build lock, price the session, run the report. Every external call
    is bounded, so a wedged Docker cannot keep the minds running. Idempotent; safe to run from the
    launcher, the warden or --stop. Returns None when another live process is already doing it."""
    sdir = Path(info["session_dir"])
    sdir.mkdir(parents=True, exist_ok=True)
    if not take_lock(sdir):
        say("another process is closing this session")
        return None
    w = World(scene)
    db, run = info["db"], info["run"]
    done = {"why": why, "by_pid": os.getpid(), "at_utc": utc()}
    info["status"] = "closing"
    write_json(sdir / "session.json", info)
    ended_ms = ended_ms or now_ms()

    def note(msg):
        say(msg)
        try:
            with open(sdir / "launcher.log", "a") as f:
                f.write(f"{utc()} [teardown pid {os.getpid()}] {msg.strip()}\n")
        except OSError:
            pass

    def step(msg):
        note("  " + msg)

    note(f"session ending ({why}):")
    # 1. Pause the world: no takeover of the player's character, no ticks, until the next start.
    #    Safe while a client is still connected. Bounded: a failure here never delays step 2.
    try:
        if w.exists(db):
            w.set_paused(db, True)
            t1 = w.ticks(db)
            time.sleep(2)
            t2 = w.ticks(db)
            done["world"] = {"db": db, "paused": w.paused(db), "ticks": [t1, t2], "frozen": t1 == t2}
            step(f"world {db}: paused (ticks {t1} → {t2} over 2 s{', frozen' if t1 == t2 else ', STILL ADVANCING'})")
        else:
            done["world"] = {"db": db, "exists": False}
            step(f"world {db}: no longer exists")
    except Exception as e:  # noqa: BLE001 - keep going: stopping the minds matters more
        done["world"] = {"db": db, "error": str(e)}
        step(f"world {db}: COULD NOT PAUSE ({e})")
    # 2. The mind service, by its recorded PID only (or the child we still hold, if it was not recorded).
    if info.get("mind_pid") or mind is not None:
        pid = info.get("mind_pid") or mind.pid
        done["mind"] = stop_pid(pid, info.get("mind_ident"), info.get("mind_bin", "living-mind"),
                                popen=mind, label="mind service")
        step(done["mind"])
    # 3. The memory store, by its exact container name (recorded only once known to be the scene's).
    if info.get("neo4j"):
        done["neo4j"] = neo4j_down(info["neo4j"])
        step(done["neo4j"])
    # 4. The client, if it is still up (the launcher was told to stop), and tool 1's recorder.
    if info.get("client_pid") or client is not None:
        if client is not None and client.poll() is not None:
            done["client"] = f"client exited ({client.returncode})"
        else:
            pid = info.get("client_pid") or client.pid
            done["client"] = stop_pid(pid, info.get("client_ident"), info.get("client_bin", "living-game"),
                                      popen=client, label="game client")
        step(done["client"])
    if info.get("capture"):
        done["recorder"] = stop_recorder(info, sdir)
        step(f"session recorder: {done['recorder']}")
    if info.get("build_lock"):
        done["build_lock"] = unlock_builds([info.get("launcher_pid"), info.get("warden_pid"), os.getpid()],
                                           info.get("build_lock_path"))
        step(done["build_lock"])
    # 5. Cost, from the run's journal.
    if info.get("journal"):
        jd = Path(info["journal"])
        start_ms = info.get("started_ms")
        try:
            sess = journal_cost(jd, since_ms=start_ms, until_ms=ended_ms + 60_000)
            total = journal_cost(jd)
            minutes = (ended_ms - start_ms) / 60000 if start_ms else 0
            write_json(sdir / "cost.json", {"journal": str(jd), "session": sess, "run_total": total,
                                            "minds_minutes": round(minutes, 2), "prices": str(TOOLS / "trials.py")})
            step(cost_line(sess, f"cost: this session ({minutes:.1f} min of minds)"))
            step(cost_line(total, f"cost: run {run} so far"))
            done["cost_usd"] = round(sess["usd"], 4)
        except Exception as e:  # noqa: BLE001 - the cost line must never keep a session open
            step(f"cost: could not read the journal {jd} ({e!r}); price it later with play.py --cost")
    elif info.get("minds") is False:
        step("cost: $0.00 (no minds this session)")
    info["status"] = "closed"
    info["ended_ms"] = ended_ms
    info["teardown"] = done
    write_json(sdir / "session.json", info)
    write_json(sdir / "teardown.json", done)
    cur = read_json(scene.session_file)
    if cur and cur.get("session_dir") == info["session_dir"]:
        write_json(scene.session_file, info)
    logs = [n for n in ("client.log", "mind.log", "launcher.log") if (sdir / n).is_file()]
    note(f"  logs: {sdir} ({', '.join(logs)})")
    # 6. Tool 1's report.
    if report:
        run_report(scene, info, sdir)
    return done


def stop_recorder(info, sdir):
    """Tool 1's record-stop, then a check that the recorder PID it wrote is really gone."""
    tool = info.get("report_tool") or str(REPORT)
    pidf = Path(info["capture"]) / "recorder.pid"
    rec = pidf.read_text().split()[0] if pidf.is_file() else None
    result = "no recorder running"
    if Path(tool).is_file():
        r = run_cmd([sys.executable, tool, "record-stop", "--capture", info["capture"]], 60,
                    capture_output=True, text=True, env=scrub_env({}))
        with open(sdir / "recorder.log", "a") as f:
            f.write((r.stdout or "") + (r.stderr or ""))
        result = "stopped" if r.returncode == 0 else f"record-stop failed ({r.returncode})"
    if rec and rec.isdigit():
        time.sleep(1)
        cmd = run_cmd(["ps", "-o", "command=", "-p", rec], 10, capture_output=True, text=True).stdout
        if "_record" in cmd and f"--capture {info['capture']}" in cmd:
            # Still this session's recorder (it polls the world every second): stop it by its PID.
            result = stop_pid(int(rec), proc_identity(int(rec)), Path(cmd.split()[0]).name,
                              label="session recorder (record-stop left it)")
    return result


def run_report(scene, info, sdir):
    report = Path(info.get("report_tool") or REPORT)
    if not report.is_file():
        say(f"  report: skipped; {report} is not on this checkout yet (tool 1, branch report-1)")
        return
    cmd = [sys.executable, str(report), "--db", info["db"], "--run", info["run"],
           "--journal", info.get("journal") or str(sdir / "no-journal"), "--logs", str(sdir), "--out", str(sdir / "report")]
    if info.get("capture"):
        cmd += ["--capture", info["capture"]]
    with open(sdir / "report.log", "w") as f:
        r = run_cmd(cmd, 600, stdout=f, stderr=subprocess.STDOUT, env=scrub_env({}))
    if r.returncode == 0 and (sdir / "report/index.html").is_file():
        say(f"  report: {sdir / 'report/index.html'}")
    else:
        say(f"  report: play_report.py failed ({r.returncode}); see {sdir / 'report.log'}")


def warden(scene, session_dir):
    """Detached: if the launcher dies before closing its session, close it. A running game is left
    alone (and its world unpaused once it connects); the session closes when the game exits."""
    note_signals()
    sdir = Path(session_dir)
    say(f"{utc()} warden pid {os.getpid()} for {sdir}")
    waiting = False
    while True:
        info = read_json(sdir / "session.json")
        if not info or info.get("status") == "closed":
            say(f"{utc()} session closed; warden exits")
            return
        if not is_same(info.get("launcher_pid"), info.get("launcher_ident")):
            if is_same(info.get("client_pid"), info.get("client_ident"), info.get("client_bin")):
                if not waiting:
                    say(f"{utc()} launcher pid {info.get('launcher_pid')} is gone; waiting for client pid {info['client_pid']}")
                    if repoint_builds(info.get("launcher_pid"), os.getpid(), info.get("build_lock_path")):
                        say(f"{utc()} build lock now held by the warden (pid {os.getpid()})")
                    waiting = True
                if not info.get("unpaused_ms") and CLIENT_LOG_READY in _read(sdir / "client.log"):
                    try:
                        World(scene).set_paused(info["db"], False)
                        info["unpaused_ms"] = now_ms()
                        write_json(sdir / "session.json", info)
                        say(f"{utc()} client connected; unpaused {info['db']} (for the dead launcher)")
                    except Exception as e:  # noqa: BLE001
                        say(f"{utc()} could not unpause {info['db']}: {e}")
                time.sleep(1)
                continue
            say(f"{utc()} launcher pid {info.get('launcher_pid')} is gone; closing the session")
            if teardown(scene, info, why="the launcher died" + (" (then the client exited)" if waiting else ""),
                        report=True) is not None:
                return
            # Another process holds the teardown lock: keep watching, and retry if it dies.
        time.sleep(1)


def _read(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def note_signals():
    """For --stop and the warden: signals are noted and do not interrupt a teardown."""
    for sig in SIGNALS:
        signal.signal(sig, lambda signum, _f: say(f"{utc()} {signal.Signals(signum).name} noted; finishing first"))


def launch_lock_holder(scene):
    """The launcher holding the scene's launch lock (it may still be creating the world), or None."""
    f = scene.state / "launch.lock"
    if not f.exists():
        return None
    fd = os.open(f, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    except BlockingIOError:
        return read_json(f) or {}
    finally:
        os.close(fd)


def stop_session(scene):
    note_signals()
    holder = launch_lock_holder(scene)
    if holder and is_same(holder.get("pid"), holder.get("ident")):
        pid = holder["pid"]
        say(f"asking launcher pid {pid} to end its session")
        os.kill(pid, signal.SIGTERM)
        end = time.time() + 180
        while time.time() < end and is_same(pid, holder.get("ident")):
            time.sleep(0.5)
        if is_same(pid, holder.get("ident")):
            say(f"launcher pid {pid} is still closing after 3 minutes; closing its session from here")
    info = read_json(scene.session_file)
    if not info or info.get("status") == "closed":
        if not holder:
            say("no open session")
        cur = read_json(scene.current_file)
        if cur and World(scene).exists(cur["db"]) and World(scene).paused(cur["db"]) is False:
            World(scene).set_paused(cur["db"], True)
            say(f"paused {cur['db']}")
        return 0
    if teardown(scene, info, why="play.py --stop") is None:
        say("another process is closing that session; check again with --status")
    return 0


def status(scene):
    w = World(scene)
    cur = read_json(scene.current_file)
    if not cur:
        say(f"{scene.name}: no world yet (the next start creates one)")
        return 0
    db, run = cur["db"], cur["run"]
    ex = w.exists(db)
    p = w.paused(db) if ex else None
    state = "GONE" if not ex else "paused" if p else f"RUNNING, ticks {w.ticks(db)}" if p is False else "unknown (SQL failed)"
    say(f"{scene.name}: world {db} (run {run}, created {cur.get('created_utc')}): {state}")
    info = read_json(scene.session_file)
    if info and info.get("status") != "closed":
        say(f"  session {info['session_dir']}: {info.get('status')}, launcher pid {info.get('launcher_pid')} "
            f"{'alive' if is_same(info.get('launcher_pid'), info.get('launcher_ident')) else 'GONE'}")
    if info and info.get("mind_pid"):
        on = is_same(info["mind_pid"], info.get("mind_ident"), info.get("mind_bin", "living-mind"))
        say(f"  mind service pid {info['mind_pid']}: {'RUNNING' if on else 'not running'}")
    if scene.neo4j:
        st = docker_state(scene.neo4j["container"])
        say(f"  Neo4j {scene.neo4j['container']}: {'RUNNING' if st else 'stopped' if st is False else 'not created'}")
    if scene.minds:
        say("  " + cost_line(journal_cost(scene.journal_dir(run)), f"cost: run {run} so far"))
    return 0


# ---------------------------------------------------------------- main


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("scene", nargs="?", help="scene directory (holding play.json) or play.json path")
    ap.add_argument("--fresh", action="store_true", help="delete the current world and make a new one (asks first)")
    ap.add_argument("--yes", action="store_true", help="with --fresh: do not ask")
    ap.add_argument("--name", help="character name for a first join (default: the scene's)")
    ap.add_argument("--no-minds", action="store_true", help="no mind service and no memory store (no model calls)")
    ap.add_argument("--no-client", action="store_true", help="no game client (minds need --minds-without-client)")
    ap.add_argument("--minds-without-client", action="store_true", help="allow paid minds with no client")
    ap.add_argument("--minutes", type=float, help="end a run without a client after this many minutes")
    ap.add_argument("--client-env", action="append", metavar="K=V", help="extra client environment (e.g. a scripted plan)")
    ap.add_argument("--now", action="store_true", help="open the game without waiting for heavy jobs already running")
    ap.add_argument("--no-record", action="store_true", help="do not run tool 1's session recorder")
    ap.add_argument("--no-video", action="store_true", help="record stills every few seconds instead of the session's video")
    ap.add_argument("--report-tool", metavar="PATH", help=argparse.SUPPRESS)  # tool 1 from elsewhere (tests)
    ap.add_argument("--status", action="store_true", help="show the scene's world, session and cost")
    ap.add_argument("--stop", action="store_true", help="close an open session (by its recorded PIDs)")
    ap.add_argument("--cost", metavar="JOURNAL_DIR", help="price a journal directory and exit")
    ap.add_argument("--since-ms", type=int)
    ap.add_argument("--until-ms", type=int)
    ap.add_argument("--json", action="store_true", help="with --cost: print the totals as JSON")
    ap.add_argument("--warden", metavar="SESSION_DIR", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if a.cost:
        t = journal_cost(a.cost, a.since_ms, a.until_ms)
        if not t["calls"] and not Path(a.cost).is_dir():
            say(f"no journal at {a.cost}")
            return 1
        say(json.dumps(t, indent=2) if a.json else cost_line(t, f"cost of {t['journal']}:"))
        return 0
    if not a.scene:
        ap.error("a scene is required (or --cost JOURNAL_DIR)")
    try:
        scene = Scene(a.scene)
        if a.warden:
            warden(scene, a.warden)
            return 0
        if a.status:
            return status(scene)
        if a.stop:
            return stop_session(scene)
    except Refuse as e:
        say(f"play.py: {e}")
        return 2

    sess = Session(scene, a)

    def on_signal(signum, _frame):
        # Ctrl-C reaches the client too (same terminal); it quits and the loop sees it. With no client,
        # or for SIGTERM/SIGHUP, end the session here, but never inside a critical section (a child
        # started and not yet recorded, a teardown): there it is acted on when the section ends.
        if signum == signal.SIGINT and sess.client is not None and sess.client.poll() is None:
            return
        name = signal.Signals(signum).name
        if GUARD.depth:
            GUARD.pending = GUARD.pending or name
            return
        raise Stop(name)

    for sig in SIGNALS:
        signal.signal(sig, on_signal)
    why = "the client exited"
    code = 0
    try:
        sess.run()
        if sess.client is not None:
            why = f"the client exited ({sess.client.returncode})"
        elif a.minutes is not None:
            why = f"{a.minutes} minutes are up"
    except Stop as e:
        why = f"{e} received"
    except Refuse as e:
        say(f"play.py: {e}")
        why = "the start failed"
        code = 2
    except Exception as e:  # noqa: BLE001 - anything else still tears down
        say(f"play.py: unexpected error: {e!r}")
        why = "an error in the launcher"
        code = 1
    finally:
        hold_signals_for_good()
        if sess.locked and not sess.info.get("session_dir"):
            say(unlock_builds([os.getpid()], sess.info.get("build_lock_path")))
        if sess.info.get("session_dir"):
            teardown(scene, sess.info, why, client=sess.client, mind=sess.mind, report=code == 0 or bool(sess.client))
            say(f"next time: just living-play {scene.dir} (resumes {sess.info['db']}); --fresh for a new world")
    return code


if __name__ == "__main__":
    sys.exit(main())
