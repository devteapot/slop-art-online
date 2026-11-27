#!/usr/bin/env python3
"""§7 Neural-body pilot runner (docs/NEURAL_BODY.md "Pilot run"):
CPU-only throughput gate (Step 1), graph-rollout collection & teacher audit (Step 2),
brief-swap test (Step 4), and 10-episode paired evaluation vs fresh graph-only (Step 5).

Never touches shared/protected containers; creates its own private SpacetimeDB 2.14.1
container(s) pinned to CPUs 0-4,10-14, wraps runs under flock -s ~/slop-mq/trial-activity.lock,
deletes worlds via world_delete.py (pause -> confirm -> delete), stops containers with SIGINT,
and enforces every frozen stop rule via nb_pilot_guard.py.
"""
import argparse
import hashlib
import json
import math
import os
import re
import signal
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "living/tools"))
import genesis_wait  # noqa: E402
import install_script  # noqa: E402
import nb_pilot_guard as guard  # noqa: E402
import world_delete  # noqa: E402

IMAGE = "clockworklabs/spacetime:v2.14.1"
PIN_CPUS = "0-4,10-14"
WASM_HOST_DIR = Path(os.environ.get("NB_WASM_DIR", str(Path.home() / "slop-nbclone-wasm")))
WASM_NAME = "living_authority_island.wasm"
MIND_BIN = Path(os.environ.get("NB_MIND_BIN", str(Path.home() / "slop-nbclone-target" / "release" / "living-mind")))
PILOT_DIR = Path(os.environ.get("NB_PILOT_DIR", str(ROOT / ".local/living/nb-pilot")))
SKILLS_IN_SCOPE = ["strike", "dodge", "block"]
DELEGATE_SKILLS_ALL = ["strike", "dodge", "block"]

# ---- Low-level private SpacetimeDB container manager ----

def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_ports(count: int, start: int = 3421) -> list[int]:
    out = []
    p = start
    while len(out) < count:
        if port_free(p):
            out.append(p)
        p += 1
    return out


class ScratchServer:
    def __init__(self, name: str, port: int):
        self.name = name
        self.volume = name
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self._token = None

    def start(self):
        WASM_HOST_DIR.mkdir(parents=True, exist_ok=True)
        # Ensure clean slate if leftover from an interrupted prior run of this exact name.
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", self.volume], capture_output=True)
        subprocess.run([
            "docker", "run", "-d",
            "--name", self.name,
            "--cpuset-cpus", PIN_CPUS,
            "--ulimit", "nofile=65536:524288",
            "-p", f"127.0.0.1:{self.port}:3000",
            "-v", f"{WASM_HOST_DIR}:/wasm",
            "-v", f"{self.volume}:/home/spacetime",
            IMAGE, "start", "--listen-addr", "0.0.0.0:3000",
        ], check=True, capture_output=True, text=True)
        self.ping()

    def stop_and_remove(self, log_path: Path | None = None):
        if log_path is not None:
            r = subprocess.run(["docker", "logs", "--tail", "200", self.name], capture_output=True, text=True)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text((r.stdout or "") + (r.stderr or ""))
        subprocess.run(["docker", "kill", "-s", "INT", self.name], capture_output=True)
        subprocess.run(["docker", "wait", self.name], capture_output=True)
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", self.volume], capture_output=True)

    def ping(self, seconds: int = 120):
        end = time.time() + seconds
        while time.time() < end:
            try:
                with urllib.request.urlopen(self.url + "/v1/ping", timeout=5) as r:
                    if r.status == 200:
                        return
            except OSError:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"{self.name} did not answer on {self.url}")

    def cli(self, *args, timeout: int = 300) -> str:
        r = subprocess.run(["docker", "exec", self.name, "spacetime", *args], capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"spacetime {' '.join(args)}: {r.stderr[-600:]}")
        return r.stdout + r.stderr

    def token(self) -> str:
        if not self._token:
            found = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", self.cli("login", "show", "--token"))
            assert len(found) == 1, "expected 1 CLI token"
            self._token = found[0]
        return self._token

    def http(self, path: str, body=None, raw: bool = False):
        data = body.encode() if raw else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.url + path, data=data, method="POST" if data is not None else "GET")
        req.add_header("Authorization", f"Bearer {self.token()}")
        req.add_header("Content-Type", "text/plain" if raw else "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")

    def sql(self, db: str, q: str) -> list[dict]:
        code, body = self.http(f"/v1/database/{db}/sql", q, raw=True)
        if code != 200:
            raise RuntimeError(f"sql {q!r}: {code} {body[:300]}")
        res = json.loads(body)[0]
        names = [e["name"]["some"] if isinstance(e["name"], dict) else e["name"] for e in res["schema"]["elements"]]
        return [dict(zip(names, r)) for r in res["rows"]]

    def call(self, db: str, reducer: str, args: list):
        code, body = self.http(f"/v1/database/{db}/call/{reducer}", args)
        if code != 200:
            raise RuntimeError(f"{reducer}({args}): {code} {body[:300]}")
        return body

    def publish_island(self, db: str) -> dict:
        self.cli("publish", "-s", "local", "-b", f"/wasm/{WASM_NAME}", db, "--delete-data", "-y")
        genesis_wait.wait_ready(self.url, db, self.token())
        self.call(db, "set_world_law", ["body_delegate_on", "true"])
        # Verify installed skills.rhai hash (without world laws) and body_delegate_on law.
        made = self.sql(db, "SELECT source FROM script WHERE name = 'skills'")[0]["source"]
        skills_sha = hashlib.sha256(install_script.without_world_laws(made).encode()).hexdigest()
        laws = {r["name"]: r["value"] for r in self.sql(db, "SELECT name, value FROM law_override")}
        wasm_sha = hashlib.sha256((WASM_HOST_DIR / WASM_NAME).read_bytes()).hexdigest()
        return {"db": db, "wasm_sha": wasm_sha, "skills_sha": skills_sha, "body_delegate_on": laws.get("body_delegate_on") == "true"}

    def delete_world(self, db: str):
        cli_fn = lambda *args: subprocess.run(["docker", "exec", "-i", self.name, "spacetime", *args], capture_output=True, text=True, timeout=300)
        deleted, why = world_delete.cli_pause_and_delete(cli_fn, db)
        if not deleted:
            raise RuntimeError(f"world_delete {db} failed: {why}")


# ---- Arena & Teacher Graph Builders ----

def find_open_spots(srv: ScratchServer, db: str, count: int, min_sep: float = 38.0) -> list[tuple[float, float]]:
    """Find `count` guaranteed-walkable open spots on the island, well away from structures and each other."""
    land = srv.sql(db, "SELECT arrive_x, arrive_y FROM land")[0]
    ax, ay = float(land["arrive_x"]), float(land["arrive_y"])
    structs = [(float(s["x"]), float(s["y"])) for s in srv.sql(db, "SELECT x, y FROM structure")]
    # Every resource_node and existing body sits on guaranteed walkable island land!
    nodes = [(float(r["x"]), float(r["y"])) for r in srv.sql(db, "SELECT x, y FROM resource_node")]
    bodies = [(float(b["x"]), float(b["y"])) for b in srv.sql(db, "SELECT x, y FROM body")]
    cands = [(ax - 60.0, ay)] + nodes + bodies
    cands.sort(key=lambda p: (p[0] - (ax - 60.0)) ** 2 + (p[1] - ay) ** 2)
    spots = []
    for x, y in cands:
        if x < 60 or y < 60 or x > 1980 or y > 1980:
            continue
        if any(math.hypot(x - sx, y - sy) < 18.0 for sx, sy in structs):
            continue
        if any(math.hypot(x - px, y - py) < min_sep for px, py in spots):
            continue
        spots.append((round(x, 1), round(y, 1)))
        if len(spots) >= count:
            return spots
    return spots


def ranked_adult_residents(srv: ScratchServer, db: str, exclude: set[int]) -> list[int]:
    """Deterministic ordering of living adult island residents by distance from arrival."""
    land = srv.sql(db, "SELECT arrive_x, arrive_y FROM land")[0]
    ax, ay = float(land["arrive_x"]), float(land["arrive_y"])
    people = [r["id"] for r in srv.sql(db, "SELECT id, alive, stage FROM character WHERE kind = 'person'")
              if r["alive"] and r["stage"] == 2 and r["id"] not in exclude]
    bodies = {b["id"]: (float(b["x"]), float(b["y"])) for b in srv.sql(db, "SELECT id, x, y FROM body")}
    cands = [pid for pid in people if pid in bodies]
    cands.sort(key=lambda i: ((bodies[i][0] - ax) ** 2 + (bodies[i][1] - ay) ** 2, i))
    return cands


def place_and_brief(srv: ScratchServer, db: str, sid: int, fid: int, sx: float, sy: float,
                    dx: float, dy: float, brief_arg: dict | None = None) -> tuple[float, float]:
    """Place subject and foe cleanly facing each other, and install brief if given.
    If local terrain blocks sight at (sx, sy), tries small open-ground shifts around (sx, sy).
    """
    srv.call(db, "set_behavior", [sid, json.dumps({"wait": 120})])
    srv.call(db, "set_behavior", [fid, json.dumps({"wait": 120})])
    shifts = [(0.0, 0.0), (4.0, 0.0), (-4.0, 0.0), (0.0, 4.0), (0.0, -4.0), (8.0, 8.0), (-8.0, -8.0)]
    last_err = None
    for ox, oy in shifts:
        srv.call(db, "place_at", [sid, sx + ox, sy + oy])
        s_act = srv.sql(db, f"SELECT x, y FROM body WHERE id = {sid}")[0]
        ax, ay = float(s_act["x"]), float(s_act["y"])
        srv.call(db, "place_at", [fid, ax + dx, ay + dy])
        f_act = srv.sql(db, f"SELECT x, y FROM body WHERE id = {fid}")[0]
        fx, fy = float(f_act["x"]), float(f_act["y"])
        # Turn subject to face foe so facing sight (`fov_on`) sees foe at any starting bearing!
        srv.call(db, "set_behavior", [sid, json.dumps({"seq": [{"do": {"skill": "face", "target": {"at": [fx, fy]}}}, {"wait": 120}]})])
        if brief_arg is None:
            return ax, ay
        time.sleep(0.35)
        try:
            srv.call(db, "mind_body_brief", [sid, 0, brief_arg])
            return ax, ay
        except RuntimeError as e:
            last_err = e
            # If foe snapped > 10 m away or behind rock, try bringing foe to 2.0 m directly east to verify brief, or shift site.
            continue
    # Final fallback: place foe 2.0 m east (all-round sight), install brief, then place at (ax+dx, ay+dy).
    s_act = srv.sql(db, f"SELECT x, y FROM body WHERE id = {sid}")[0]
    ax, ay = float(s_act["x"]), float(s_act["y"])
    srv.call(db, "place_at", [fid, ax + 2.0, ay])
    time.sleep(0.35)
    srv.call(db, "mind_body_brief", [sid, 0, brief_arg])
    srv.call(db, "place_at", [fid, ax + dx, ay + dy])
    return ax, ay


def spawn_subject(srv: ScratchServer, db: str, name: str, at: tuple[float, float], kit: bool = True) -> int:
    before = {r["id"] for r in srv.sql(db, "SELECT id FROM character")}
    srv.call(db, "spawn_newcomer", [name])
    sid = next(r["id"] for r in srv.sql(db, "SELECT id FROM character") if r["id"] not in before)
    srv.call(db, "place_at", [sid, at[0], at[1]])
    srv.call(db, "admin_set_vitals", [sid, 100.0])
    if kit:
        for item, qty in (("bow", 1), ("arrow", 30), ("berries", 4), ("spear", 1)):
            srv.call(db, "grant_items", [sid, item, qty])
        for tech in ("fire", "fire_bolt", "wound_tending"):
            srv.call(db, "grant_know_how", [sid, tech])
    return sid


def foe_heavy_graph(subject_id: int, pause_a: float = 2.0, pause_b: float = 3.0,
                    heal_below: float = 70.0, irregular: bool = False, mixed_strike: bool = False) -> dict:
    """R2 heavy-blow foe fixture using deterministic alternating `seq` steps (avoiding per-tick
    `chance` re-rolls that reset `Node::Wait` under 15 Hz combat evaluation)."""
    def heal_or_pause(p_s: float) -> dict:
        w_full = max(1, int(round(p_s)))
        w_heal = max(1, int(round(max(1.0, p_s - 0.5))))
        return {
            "if": {
                "cond": {"health": {"below": heal_below}},
                "then": {
                    "first": [
                        {"seq": [{"do": {"skill": "heal", "target": "self"}}, {"wait": w_heal}]},
                        {"wait": w_full},
                    ]
                },
                "else": {"wait": w_full},
            }
        }

    atk = {"do": {"skill": "attack", "target": {"id": subject_id}}}
    stk = {"do": {"skill": "strike", "target": {"id": subject_id}}}

    if irregular:
        steps = [atk, heal_or_pause(1.0), atk, heal_or_pause(2.0), atk, heal_or_pause(4.0)]
    elif mixed_strike:
        steps = [stk, {"wait": max(1, int(round(pause_a)))}, atk, heal_or_pause(pause_b)]
    else:
        steps = [atk, heal_or_pause(pause_a), atk, heal_or_pause(pause_b)]
    return {"first": [{"seq": steps}]}


def graph_only_baseline(foe_id: int) -> dict:
    """Arm G: fresh matched unadapted graph-only baseline (frozen in docs/NEURAL_BODY.md)."""
    return {
        "first": [
            {"if": {"cond": {"health": {"below": 15}}, "then": {"do": {"skill": "flee", "target": {"id": foe_id}, "run": True}}}},
            {"do": {"skill": "strike", "target": {"id": foe_id}}},
        ]
    }


def delegate_leaf_graph(foe_id: int, goal: str = "engage", exit_hp: float = 15.0, bind_leaf_target: bool = False) -> dict:
    """Arm L: delegated leaf with skills [strike, dodge, block].
    Target is carried in `mind_body_brief` by default so the leaf stays active across brief swaps,
    withdrawals past 11 m sight, and temporary sight breaks (where `Memory` tracks the target).
    """
    leaf = {
        "goal": goal,
        "skills": SKILLS_IN_SCOPE,
        "exit": {"health": {"below": exit_hp}},
    }
    if bind_leaf_target:
        leaf["target"] = {"id": foe_id}
    return {
        "first": [
            {"delegate": leaf},
            {"do": {"skill": "flee", "target": {"id": foe_id}, "run": True}},
        ]
    }


def teacher_graph(foe_id: int, goal: str, stance: str = "even", privileged_control: bool = False,
                  stamina_floor: int = 25) -> dict:
    """Real authority behaviour graphs used ONLY as imitation teachers in Step 2.
    All normal teachers use ONLY player-perceivable conditions (doing 'winding up', near, sees,
    health, stamina via `my_vitals`, can).
    `privileged_control=True` deliberately uses `about to release` (reads future release_ms) + `hunger`
    so the static AST teacher audit proves it catches and excludes privileged graphs.
    """
    if privileged_control:
        return {
            "first": [
                {"if": {"cond": {"all": [{"doing": {"who": "person", "is": "hostile", "phase": "about to release", "at_me": True, "within": 4.0}}, {"hunger": {"below": 90}}]},
                        "then": {"do": {"skill": "dodge"}}}},
                {"do": {"skill": "strike", "target": {"id": foe_id}}},
            ]
        }
    if goal == "withdraw":
        return {
            "first": [
                {"if": {"cond": {"all": [
                    {"doing": {"who": "person", "is": "hostile", "phase": "winding up", "at_me": True, "within": 3.2}},
                    {"stamina": {"above": 22}},
                ]}, "then": {"do": {"skill": "dodge"}}}},
                {"if": {"cond": {"stamina": {"above": 28}},
                        "then": {"do": {"skill": "flee", "target": {"id": foe_id}, "run": True}}}},
                {"do": {"skill": "flee", "target": {"id": foe_id}, "run": False}},
            ]
        }
    if goal == "hold":
        # Keep spacing squarely inside the frozen 2.5–6.0 m hold band against a pursuing foe:
        # sprint away only when foe gets inside `run_d` (<2.8 m), walk back inside `dmin`,
        # explicitly walk INWARD past `dmax` so it never drifts past 6.0 m or loses sight (11 m),
        # and stand calmly inside [dmin, dmax].
        run_d, dmin, dmax = (3.0, 3.8, 4.9) if stance == "guarded" else ((2.8, 3.5, 4.6) if stance == "even" else (2.6, 3.2, 4.3))
        return {
            "first": [
                {"if": {"cond": {"doing": {"who": "person", "is": "hostile", "phase": "winding up", "at_me": True, "within": 3.0}},
                        "then": {"first": [{"do": {"skill": "block", "qty": 1200}}, {"do": {"skill": "dodge"}}]}}},
                {"if": {"cond": {"all": [
                    {"near": {"target": {"id": foe_id}, "within": run_d}},
                    {"stamina": {"above": 22}},
                ]}, "then": {"do": {"skill": "back_off", "target": {"id": foe_id}, "distance": dmax - 0.3, "run": True}}}},
                {"if": {"cond": {"near": {"target": {"id": foe_id}, "within": dmin}},
                        "then": {"do": {"skill": "back_off", "target": {"id": foe_id}, "distance": dmax - 0.2, "run": False}}}},
                {"if": {"cond": {"not": {"near": {"target": {"id": foe_id}, "within": dmax}}},
                        "then": {"do": {"skill": "close_in", "target": {"id": foe_id}, "distance": (dmin + dmax) * 0.5, "run": False}}}},
                {"wait": 1},
            ]
        }
    # goal == "engage": hold block through the ENTIRE foe windup (no stamina gate on the block `if`
    # so the guard is NEVER dropped mid-windup!), then drop block immediately when the windup ends —
    # into breath recovery (`wait` -> explicit `release_block`) when stamina <= `stamina_floor`,
    # into `close_in` (-> explicit `release_block`) when out of reach, or into `strike` with breath.
    if stance == "guarded":
        return {
            "first": [
                {"if": {"cond": {"doing": {"who": "person", "is": "hostile", "phase": "winding up", "at_me": True, "within": 3.8}},
                        "then": {"first": [
                            {"if": {"cond": {"stamina": {"above": 48}}, "then": {"do": {"skill": "dodge"}}}},
                            {"do": {"skill": "block", "qty": 1200}},
                        ]}}},
                {"if": {"cond": {"not": {"stamina": {"above": max(34, stamina_floor)}}},
                        "then": {"wait": 1}}},
                {"if": {"cond": {"all": [
                    {"not": {"near": {"target": {"id": foe_id}, "within": 2.0}}},
                    {"stamina": {"above": 35}},
                ]}, "then": {"do": {"skill": "close_in", "target": {"id": foe_id}, "distance": 1.3, "run": True}}}},
                {"if": {"cond": {"not": {"near": {"target": {"id": foe_id}, "within": 2.0}}},
                        "then": {"do": {"skill": "close_in", "target": {"id": foe_id}, "distance": 1.3, "run": False}}}},
                {"do": {"skill": "strike", "target": {"id": foe_id}}},
            ]
        }
    # stance == "even" or "pressing": block-first on windup (held through full windup; dodge fallback),
    # explicit guard release on low breath or approach, relentless strike in reach with breath.
    close_d = 1.2 if stance == "pressing" else 1.3
    return {
        "first": [
            {"if": {"cond": {"doing": {"who": "person", "is": "hostile", "phase": "winding up", "at_me": True, "within": 3.6}},
                    "then": {"first": [{"do": {"skill": "block", "qty": 1200}}, {"do": {"skill": "dodge"}}]}}},
            {"if": {"cond": {"not": {"stamina": {"above": stamina_floor}}},
                    "then": {"wait": 1}}},
            {"if": {"cond": {"all": [
                {"not": {"near": {"target": {"id": foe_id}, "within": 2.0}}},
                {"stamina": {"above": 35}},
            ]}, "then": {"do": {"skill": "close_in", "target": {"id": foe_id}, "distance": close_d, "run": True}}}},
            {"if": {"cond": {"not": {"near": {"target": {"id": foe_id}, "within": 2.0}}},
                    "then": {"do": {"skill": "close_in", "target": {"id": foe_id}, "distance": close_d, "run": False}}}},
            {"do": {"skill": "strike", "target": {"id": foe_id}}},
        ]
    }


def make_brief_arg(goal: str, target: int, stance: str = "even", risk: float = 0.5,
                   style: float = 0.5, ttl_s: float = 300.0, traits: list[float] | None = None,
                   rationale: str = "pilot brief") -> dict:
    return {
        "some": {
            "goal": goal,
            "target": target,
            "stance": stance,
            "risk": float(risk),
            "style": float(style),
            "ttl_s": float(ttl_s),
            "rationale": rationale,
            "traits": list(traits if traits is not None else [0.0, 0.0]),
        }
    }


# ---- Static AST teacher audit ----

# Own stamina is player-perceivable via `my_vitals` (encoded in `encode.rs`).
# Hunger, energy, inventory, beliefs, judgements, `about to release` (future `release_ms`),
# and `threatened` (no FOV check) remain privileged and excluded.
PRIVILEGED_CONDS = {"hunger", "energy", "has", "believes", "judged"}


def audit_teacher_graph_ast(graph: dict) -> list[str]:
    """Return a list of player-path privilege violations found in a teacher graph AST."""
    violations = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in PRIVILEGED_CONDS:
                    violations.append(f"privileged_cond:{k}")
                elif k == "doing" and isinstance(v, dict):
                    if str(v.get("phase", "")).lower().replace("_", " ") == "about to release":
                        violations.append("privileged_doing:about_to_release_reads_release_ms")
                elif k == "threatened":
                    violations.append("privileged_cond:threatened_without_fov_check")
                elif k == "do" and isinstance(v, dict):
                    sk = v.get("skill")
                    if sk in ("attack", "yield", "heal", "gather", "eat", "sleep"):
                        violations.append(f"non_player_bar_skill:{sk}")
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(graph)
    return sorted(set(violations))


# ---- Step 1: Throughput Gate ----

def cmd_throughput(args):
    guard.check_resources()
    guard.check_no_cuda()
    guard.check_battle_lock()
    out_dir = PILOT_DIR / "step1-throughput"
    out_dir.mkdir(parents=True, exist_ok=True)

    # First: pure CPU single-core forward benchmark of RoleNet (23,341 params).
    bench_out = subprocess.check_output(
        ["taskset", "-c", "0", str(MIND_BIN), "body-bench", "--iters", "100000"],
        cwd=ROOT, text=True
    )
    cpu_bench = json.loads(bench_out)
    print(f"[Step 1] 1-core RoleNet forward: {cpu_bench['decisions_per_s_1core']:.0f} dec/s ({cpu_bench['us_per_decision']:.2f} us/dec), params={cpu_bench['param_count']}", flush=True)

    # Multi-copy real-authority sweep on CPUs 0-4,10-14.
    configs = [
        ("1copy-1body-15hz", 1, 1, 15.0),
        ("1copy-16body-15hz", 1, 16, 15.0),
        ("2copy-16body-15hz", 2, 16, 15.0),
        ("4copy-16body-15hz", 4, 16, 15.0),
        ("4copy-16body-30hz", 4, 16, 30.0),
    ]
    if args.quick:
        configs = configs[:2]

    results = []
    for label, n_copies, bodies_per_copy, hz in configs:
        guard.check_resources()
        ports = pick_ports(n_copies, 3421)
        servers = [ScratchServer(f"slop-nbclone-tp{i}", p) for i, p in enumerate(ports, 1)]
        workers = []
        dbs = []
        cap_dirs = []
        try:
            for i, srv in enumerate(servers, 1):
                srv.start()
                db = f"verify-nb-tp{i}"
                srv.publish_island(db)
                dbs.append(db)
                spots = find_open_spots(srv, db, bodies_per_copy, min_sep=35.0)
                foes = ranked_adult_residents(srv, db, set())[10:10 + bodies_per_copy]
                subjects = []
                for j in range(bodies_per_copy):
                    sx, sy = spots[j]
                    sid = spawn_subject(srv, db, f"Tp{j}", (sx, sy), kit=True)
                    fid = foes[j]
                    srv.call(db, "place_at", [fid, sx + 4.0, sy])
                    srv.call(db, "admin_set_vitals", [fid, 100.0])
                    srv.call(db, "grant_items", [fid, "spear", 1])
                    srv.call(db, "set_behavior", [fid, json.dumps(foe_heavy_graph(sid))])
                    srv.call(db, "mind_body_brief", [sid, 0, make_brief_arg("engage", fid, "even", 0.5, 0.5, 300.0, [0.0, 0.0], "throughput")])
                    srv.call(db, "set_behavior", [sid, json.dumps(delegate_leaf_graph(fid, "engage", exit_hp=1.0))])
                    subjects.append(sid)
                # Wait for body_slot rows to populate.
                time.sleep(2.5)
                cap_dir = out_dir / f"{label}-c{i}"
                if cap_dir.exists():
                    for p in cap_dir.glob("*"):
                        p.unlink()
                cap_dir.mkdir(parents=True, exist_ok=True)
                cap_dirs.append(cap_dir)
                env = dict(os.environ,
                           LIVING_ROOT=str(ROOT),
                           LIVING_SERVER=srv.url,
                           LIVING_DB=db,
                           LIVING_TOKEN=srv.token(),
                           LIVING_BODY_ONLY=",".join(map(str, subjects)),
                           LIVING_BODY_HZ=str(hz),
                           LIVING_BODY_WEIGHTS_RANDOM="1",
                           LIVING_BODY_CAPTURE=str(cap_dir),
                           LIVING_BODY_CAPTURE_FILE_MB="32",
                           LIVING_BODY_CAPTURE_FILES="8",
                           RUST_LOG="info,spacetimedb_sdk=warn")
                logf = (out_dir / f"{label}-c{i}.log").open("w")
                proc = subprocess.Popen(["taskset", "-c", PIN_CPUS, str(MIND_BIN), "body"], cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)
                workers.append((proc, logf))

            # Warmup 6 s for all sessions to open, then measure 20 s steady window.
            time.sleep(6.0)
            t_start_ms = int(time.time() * 1000)
            ticks_before = [srv.sql(db, "SELECT tick FROM clock")[0]["tick"] for srv, db in zip(servers, dbs)]
            time.sleep(20.0)
            t_end_ms = int(time.time() * 1000)
            ticks_after = [srv.sql(db, "SELECT tick FROM clock")[0]["tick"] for srv, db in zip(servers, dbs)]

            for proc, logf in workers:
                proc.send_signal(signal.SIGTERM)
            for proc, logf in workers:
                proc.wait(timeout=15)
                logf.close()

            # Score steady window.
            n_dec = 0
            decide_us = []
            obs_age = []
            replies_ok = 0
            replies_ref = 0
            too_many = 0
            lapses = 0
            epochs = 0
            for cdir in cap_dirs:
                for jf in sorted(cdir.glob("body-*.jsonl")):
                    for line in jf.read_text().splitlines():
                        r = json.loads(line)
                        w = r.get("wall_ms", 0)
                        if r["kind"] == "decision" and t_start_ms <= w <= t_end_ms:
                            n_dec += 1
                            if "decide_us" in r:
                                decide_us.append(r["decide_us"])
                            age = (r.get("observation") or {}).get("age_ms")
                            if age is not None:
                                obs_age.append(age)
                        elif r["kind"] == "reply" and t_start_ms <= w <= t_end_ms:
                            if r.get("ok"):
                                replies_ok += 1
                            else:
                                replies_ref += 1
                                if "too many inputs" in str(r.get("refused") or ""):
                                    too_many += 1
                        elif r["kind"] == "session":
                            if r.get("event") == "opened":
                                epochs += 1
                            elif r.get("event") in ("lost", "stalled"):
                                lapses += 1
            wall_s = (t_end_ms - t_start_ms) / 1000.0
            dec_per_s = n_dec / wall_s
            tick_hz = [round((a - b) / wall_s, 1) for a, b in zip(ticks_after, ticks_before)]
            decide_us.sort()
            obs_age.sort()
            pct = lambda xs, q: xs[min(len(xs) - 1, int(len(xs) * q))] if xs else None
            row = {
                "label": label,
                "copies": n_copies,
                "bodies_per_copy": bodies_per_copy,
                "total_bodies": n_copies * bodies_per_copy,
                "target_hz": hz,
                "wall_s": round(wall_s, 2),
                "decisions": n_dec,
                "decisions_per_s": round(dec_per_s, 1),
                "decide_p50_us": pct(decide_us, 0.50),
                "decide_p95_us": pct(decide_us, 0.95),
                "obs_age_p50_ms": pct(obs_age, 0.50),
                "obs_age_p95_ms": pct(obs_age, 0.95),
                "replies_ok": replies_ok,
                "replies_refused": replies_ref,
                "too_many_inputs": too_many,
                "epochs": epochs,
                "lapses": lapses,
                "authority_tick_hz": tick_hz,
            }
            results.append(row)
            print(f"[Step 1] {label}: {row['decisions_per_s']} dec/s | decide p95={row['decide_p95_us']} us | age p95={row['obs_age_p95_ms']} ms | lapses={lapses} | auth_hz={tick_hz}", flush=True)
            # Clean large raw captures from throughput bench after tallying.
            for cdir in cap_dirs:
                for jf in cdir.glob("body-*.jsonl"):
                    jf.unlink()
        finally:
            for proc, logf in workers:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGTERM)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                try:
                    logf.close()
                except Exception:
                    pass
            for srv, db in zip(servers, dbs):
                try:
                    srv.delete_world(db)
                except Exception as e:
                    print(f"warn: delete_world {db}: {e}", file=sys.stderr)
            for i, srv in enumerate(servers, 1):
                srv.stop_and_remove(out_dir / f"{label}-stdb{i}.log")

    summary = {
        "pinned_cpus": PIN_CPUS,
        "cpu_1core_bench": cpu_bench,
        "real_authority_sweep": results,
        "peak_real_authority_dec_per_s": max((r["decisions_per_s"] for r in results), default=0.0),
        "suarez_rl_threshold_dec_per_s": 10_000,
    }
    (out_dir / "throughput.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


# ---- Step 2: Graph-Rollout Collection + Teacher Audit + Splits ----

def cmd_collect(args):
    guard.check_resources()
    guard.check_no_cuda()
    guard.check_battle_lock()
    out_dir = PILOT_DIR / "step2-collect"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    n_sessions = args.sessions
    duels_per_session = args.duels
    duration_s = args.duration_s

    # 3 distinct sessions: sessions 1 & 2 -> train; session 3 -> val.
    # Every actor rank >= 10 (ranks 0..9 reserved exclusively for held-out Step 5 evaluation!).
    # Mix per session of 16 duels:
    #   8 engage (5 even: 3 aggressive + 2 breath-gating for extra guard-release transitions; 2 guarded; 1 pressing)
    #   4 hold (2 even, 1 guarded, 1 pressing)
    #   3 withdraw (guarded/even)
    #   1 privileged-audit-control (uses `about to release` + `hunger` -> MUST be caught & excluded by static AST audit!)
    brief_specs = [
        ("engage", "even", 0.5, 0.5, [0.0, 0.0], False, 25),
        ("engage", "even", 0.6, 0.4, [0.2, -0.1], False, 25),
        ("engage", "even", 0.4, 0.6, [-0.2, 0.2], False, 25),
        ("engage", "even", 0.5, 0.5, [0.3, 0.1], False, 32),
        ("engage", "even", 0.55, 0.55, [-0.1, -0.3], False, 32),
        ("engage", "guarded", 0.2, 0.3, [-0.5, 0.2], False, 35),
        ("engage", "guarded", 0.3, 0.4, [-0.3, -0.2], False, 35),
        ("engage", "pressing", 0.85, 0.8, [0.6, 0.4], False, 25),
        ("hold", "even", 0.3, 0.5, [0.0, 0.3], False, 22),
        ("hold", "even", 0.25, 0.5, [0.1, -0.1], False, 22),
        ("hold", "guarded", 0.15, 0.3, [-0.4, 0.0], False, 22),
        ("hold", "pressing", 0.45, 0.6, [0.2, 0.5], False, 22),
        ("withdraw", "guarded", 0.1, 0.3, [-0.7, -0.2], False, 22),
        ("withdraw", "even", 0.2, 0.5, [-0.5, 0.1], False, 22),
        ("withdraw", "guarded", 0.15, 0.7, [-0.6, 0.3], False, 22),
        ("engage", "even", 0.5, 0.5, [0.0, 0.0], True, 25),  # privileged teacher control (audited & excluded!)
    ]
    opp_configs = [
        ("heavy-750-std", dict(pause_a=2.0, pause_b=3.0, irregular=False, mixed_strike=False)),
        ("heavy-750-fast", dict(pause_a=1.2, pause_b=2.0, irregular=False, mixed_strike=False)),
        ("heavy-750-slow", dict(pause_a=2.5, pause_b=4.0, irregular=False, mixed_strike=False)),
        ("heavy-750-std2", dict(pause_a=1.8, pause_b=2.8, irregular=False, mixed_strike=False)),
    ]

    port = pick_ports(1, 3425)[0]
    srv = ScratchServer("slop-nbclone-col", port)
    session_meta = []
    expected_wasm = None
    expected_skills = None

    try:
        srv.start()
        for sess_idx in range(1, n_sessions + 1):
            guard.check_resources(capture_dir=raw_dir)
            split = "train" if sess_idx < n_sessions else "val"
            db = f"verify-nb-col-s{sess_idx}"
            meta = srv.publish_island(db)
            if expected_wasm is None:
                expected_wasm, expected_skills = meta["wasm_sha"], meta["skills_sha"]
            else:
                guard.check_hashes(WASM_HOST_DIR / WASM_NAME, expected_wasm, meta["skills_sha"], expected_skills)
            # Disjoint actors per session, all rank >= 12 with 2-actor buffer (0..9 reserved for Step 5 test).
            ranked = ranked_adult_residents(srv, db, set())
            offset = 12 + (sess_idx - 1) * (duels_per_session + 2)
            foes = ranked[offset:offset + duels_per_session]
            spots = find_open_spots(srv, db, duels_per_session * n_sessions, min_sep=42.0)
            sess_spots = spots[(sess_idx - 1) * duels_per_session: sess_idx * duels_per_session]

            manifest = []
            duel_actors = []
            ast_audit = {}
            pending_graphs = []
            for j in range(duels_per_session):
                goal, stance, risk, style, traits, priv, stam_floor = brief_specs[j % len(brief_specs)]
                opp_name, opp_kw = opp_configs[(j + sess_idx) % len(opp_configs)]
                if split == "val":
                    opp_name = f"val-{opp_name}"
                ep_id = f"s{sess_idx}_d{j:02d}_{goal}_{stance}"
                sx, sy = sess_spots[j]
                ang = (2 * math.pi * ((j + sess_idx * 3) % 8)) / 8.0
                dist0 = 3.0 + (j % 4) * 1.5  # 3.0, 4.5, 6.0, 7.5 m
                sid = spawn_subject(srv, db, f"Tr{sess_idx}_{j}", (sx, sy), kit=True)
                fid = foes[j]
                srv.call(db, "admin_set_vitals", [fid, 100.0])
                srv.call(db, "grant_items", [fid, "spear", 1])
                srv.call(db, "grant_know_how", [fid, "wound_tending"])
                t_graph = teacher_graph(fid, goal, stance, privileged_control=priv, stamina_floor=stam_floor)
                violations = audit_teacher_graph_ast(t_graph)
                ast_audit[ep_id] = {"teacher": f"{goal}-{stance}{'-priv' if priv else ''}", "violations": violations, "split": split, "foe": fid, "opponent_cfg": opp_name}
                # Place facing each other and install brief; keep both waiting until body-observe opens all sessions!
                sx, sy = place_and_brief(
                    srv, db, sid, fid, sx, sy, dist0 * math.cos(ang), dist0 * math.sin(ang),
                    make_brief_arg(goal, fid, stance, risk, style, 300.0, traits, f"collect {ep_id}")
                )
                pending_graphs.append((sid, fid, t_graph, foe_heavy_graph(sid, **opp_kw)))
                manifest.append({
                    "actor": sid,
                    "target": fid,
                    "role": "person",
                    "goal": goal,
                    "skills": SKILLS_IN_SCOPE,
                    "episode": ep_id,
                    "teacher": ast_audit[ep_id]["teacher"],
                    "opponent_cfg": opp_name,
                })
                duel_actors.append((sid, fid, sx, sy, ang, dist0, goal))

            man_path = out_dir / f"manifest-s{sess_idx}.json"
            man_path.write_text(json.dumps(manifest, indent=2) + "\n")
            cap_dir = raw_dir / f"s{sess_idx}"
            if cap_dir.exists():
                for p in cap_dir.glob("*"):
                    p.unlink()
            cap_dir.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ,
                       LIVING_ROOT=str(ROOT),
                       LIVING_SERVER=srv.url,
                       LIVING_DB=db,
                       LIVING_TOKEN=srv.token(),
                       LIVING_BODY_HZ="15",
                       LIVING_BODY_CAPTURE=str(cap_dir),
                       LIVING_BODY_CAPTURE_FILE_MB="64",
                       LIVING_BODY_CAPTURE_FILES="8",
                       RUST_LOG="info,spacetimedb_sdk=warn")
            logf = (out_dir / f"observe-s{sess_idx}.log").open("w")
            proc = subprocess.Popen(["taskset", "-c", PIN_CPUS, str(MIND_BIN), "body-observe", str(man_path)], cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)
            # Wait for all 16 body_open sessions to come live BEFORE starting the duels!
            t_wait = time.time()
            while time.time() - t_wait < 20.0:
                live_n = sum(1 for r in srv.sql(db, "SELECT live FROM body_session") if r["live"])
                if live_n >= duels_per_session:
                    break
                time.sleep(0.25)
            for sid, fid, tg, fg in pending_graphs:
                srv.call(db, "set_behavior", [sid, json.dumps(tg)])
                srv.call(db, "set_behavior", [fid, json.dumps(fg)])
            print(f"[Step 2] Session {sess_idx}/{n_sessions} ({split}): observing {duels_per_session} active teacher duels for {duration_s} s...", flush=True)
            t0 = time.time()
            next_heal = t0 + 5.0
            next_reseat = t0 + 18.0
            reseat_k = 0
            try:
                while time.time() - t0 < duration_s:
                    time.sleep(1.0)
                    now_t = time.time()
                    if now_t >= next_heal:
                        next_heal = now_t + 5.0
                        # Top up HP every 5 s so no fighter dies during collection (stamina evolves naturally!).
                        for sid, fid, sx, sy, ang, dist0, goal in duel_actors:
                            try:
                                srv.call(db, "admin_set_vitals", [sid, 100.0])
                                srv.call(db, "admin_set_vitals", [fid, 100.0])
                            except Exception:
                                pass
                    if now_t >= next_reseat:
                        next_reseat = now_t + 18.0
                        reseat_k += 1
                        # Re-seat every 18 s across [1.5..8.2 m] so EVERY brief gets rich range coverage
                        # while engage bouts run long enough to cycle stamina and guard hold/release transitions.
                        dist_cycle = [1.5, 2.2, 3.2, 4.8, 7.5, 9.5, 2.5, 6.0]
                        for idx_d, (sid, fid, sx, sy, ang, dist0, goal) in enumerate(duel_actors):
                            try:
                                new_ang = ang + reseat_k * 0.95
                                new_d = dist_cycle[(idx_d + reseat_k) % len(dist_cycle)]
                                srv.call(db, "place_at", [sid, sx, sy])
                                srv.call(db, "place_at", [fid, sx + new_d * math.cos(new_ang), sy + new_d * math.sin(new_ang)])
                            except Exception:
                                pass
            finally:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=15)
                logf.close()
                srv.delete_world(db)
            session_meta.append({"session": sess_idx, "split": split, "ast_audit": ast_audit, "cap_dir": str(cap_dir)})
    finally:
        srv.stop_and_remove(out_dir / "stdb-collect.log")

    # ---- Build audited dataset with strict encounter/session/opponent split ----
    build_dataset(session_meta, out_dir)


def build_dataset(session_meta: list[dict], out_dir: Path):
    """Audit every captured teacher decision (static AST + per-frame player-path parity),
    exclude privileged/unperceived/stale/out-of-scope examples, and write train/val dataset.jsonl."""
    dataset_path = out_dir / "dataset.jsonl"
    counts = {
        "raw_total": 0,
        "kept_total": 0,
        "kept_train": 0,
        "kept_val": 0,
        "excluded_ast_privileged": 0,
        "excluded_unseen_target_action": 0,
        "excluded_unperceived_windup_defense": 0,
        "excluded_out_of_scope_skill": 0,
        "excluded_stale_obs": 0,
        "excluded_no_brief": 0,
        "by_goal": {},
        "by_skill_class": {str(i): 0 for i in range(6)},
        "guard_hold_frames": 0,
        "guard_release_frames": 0,
        "guard_to_strike_frames": 0,
        "train_episodes": set(),
        "val_episodes": set(),
        "train_foes": set(),
        "val_foes": set(),
    }
    skill_map = {s: idx + 1 for idx, s in enumerate(SKILLS_IN_SCOPE)}

    with dataset_path.open("w") as out_f:
        for sm in session_meta:
            split = sm["split"]
            ast_audit = sm["ast_audit"]
            cap_dir = Path(sm["cap_dir"])
            # Track consecutive unseen-target steps per episode so short (<4 s) memory-tracked steps stay valid,
            # while actions on never-seen or long-unseen targets are excluded as teacher privilege!
            last_seen_seq = {}
            last_now_ms = {}
            for jf in sorted(cap_dir.glob("body-*.jsonl")):
                for line in jf.read_text().splitlines():
                    r = json.loads(line)
                    if r.get("kind") != "decision":
                        continue
                    counts["raw_total"] += 1
                    ep = r.get("episode") or "unknown"
                    info = ast_audit.get(ep, {})
                    if info.get("violations"):
                        counts["excluded_ast_privileged"] += 1
                        continue
                    audit = r.get("audit") or {}
                    if audit.get("out_of_scope_skills"):
                        counts["excluded_out_of_scope_skill"] += 1
                        continue
                    if not r.get("brief"):
                        counts["excluded_no_brief"] += 1
                        continue
                    cur_ms = int(r.get("now_ms") or 0)
                    prev_ms = last_now_ms.get(ep)
                    last_now_ms[ep] = cur_ms
                    if prev_ms is not None and cur_ms - prev_ms > 500:
                        counts["excluded_stale_obs"] += 1
                        continue

                    seq = int(r.get("seq", 0))
                    target_deliv = bool(audit.get("target_delivered"))
                    if target_deliv:
                        last_seen_seq[ep] = seq
                    recently_seen = (ep in last_seen_seq) and (seq - last_seen_seq[ep] <= 45)  # <= 3 s memory

                    intent = r.get("intent") or {}
                    press = intent.get("press")
                    release = intent.get("release")
                    moving = intent.get("moving")
                    face = intent.get("face")

                    # Exclude actions toward target when target was neither delivered nor recently seen!
                    is_acting = bool(press) or (moving and math.hypot(moving[0], moving[1]) > 0.1)
                    if not target_deliv and not recently_seen and is_acting:
                        counts["excluded_unseen_target_action"] += 1
                        continue

                    # Exclude dodge/block presses that fired when the player-equivalent observation did NOT
                    # yet show the target winding up at me (zero-latency authority privilege before cue arrival).
                    skill_cls = 0
                    if press:
                        sk = press[0]
                        skill_cls = skill_map.get(sk, 0)
                        if sk in ("dodge", "block"):
                            t_act = float(audit.get("target_act", 0.0))
                            t_at_me = bool(audit.get("target_at_me", False))
                            if t_act <= 0.0 or not t_at_me:
                                counts["excluded_unperceived_windup_defense"] += 1
                                continue
                    elif release == "block":
                        skill_cls = 5

                    enc = r["encoded"]
                    mem = r["memory"]  # 16 state + 32 history
                    history = mem[16:48]
                    mv_act = 0.0
                    mv_dx = mv_dy = run_f = 0.0
                    if moving and math.hypot(moving[0], moving[1]) > 0.1:
                        n = math.hypot(moving[0], moving[1])
                        mv_act = 1.0
                        mv_dx, mv_dy = moving[0] / n, moving[1] / n
                        run_f = 1.0 if moving[2] else 0.0
                    fc_act = 0.0
                    fc_dx = fc_dy = 0.0
                    if face and math.hypot(face[0], face[1]) > 0.1:
                        n = math.hypot(face[0], face[1])
                        fc_act = 1.0
                        fc_dx, fc_dy = face[0] / n, face[1] / n

                    sample = {
                        "episode": ep,
                        "split": split,
                        "encoded": enc,
                        "history": history,
                        "move_active": mv_act,
                        "move_dx": round(mv_dx, 5),
                        "move_dy": round(mv_dy, 5),
                        "run": run_f,
                        "face_active": fc_act,
                        "face_dx": round(fc_dx, 5),
                        "face_dy": round(fc_dy, 5),
                        "skill_class": skill_cls,
                        "was_rooted": bool(audit.get("was_rooted", False)),
                    }
                    out_f.write(json.dumps(sample) + "\n")
                    counts["kept_total"] += 1
                    counts[f"kept_{split}"] += 1
                    goal = r["brief"]["goal"]
                    counts["by_goal"][goal] = counts["by_goal"].get(goal, 0) + 1
                    counts["by_skill_class"][str(skill_cls)] += 1
                    if audit.get("guard_active"):
                        if skill_cls == 0:
                            counts["guard_hold_frames"] += 1
                        elif skill_cls == 5:
                            counts["guard_release_frames"] += 1
                        elif skill_cls == 1:
                            counts["guard_to_strike_frames"] += 1
                    if split == "train":
                        counts["train_episodes"].add(ep)
                        counts["train_foes"].add(info.get("foe"))
                    else:
                        counts["val_episodes"].add(ep)
                        counts["val_foes"].add(info.get("foe"))

    guard.check_budgets(decisions=counts["raw_total"])
    counts["train_episodes"] = len(counts["train_episodes"])
    counts["val_episodes"] = len(counts["val_episodes"])
    counts["actor_overlap_train_val"] = len(counts["train_foes"] & counts["val_foes"])
    counts["train_foes"] = sorted(x for x in counts["train_foes"] if x is not None)
    counts["val_foes"] = sorted(x for x in counts["val_foes"] if x is not None)
    counts["excluded_total"] = counts["raw_total"] - counts["kept_total"]
    counts["dataset_path"] = str(dataset_path)
    (out_dir / "audit-summary.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps({k: v for k, v in counts.items() if k not in ("train_foes", "val_foes")}, indent=2), flush=True)


# ---- Shared episode runner + R2 / anti-passivity / exploit scorer ----

def classify_outcome(o: str | None) -> str:
    o = (o or "").lower()
    if o.startswith("hit for") or "killed" in o or re.search(r"struck [^:]*: hit for", o):
        return "hit"
    if "got through" in o or o.startswith("blocked"):
        return "guarded"
    if "dodged" in o:
        return "dodged"
    if "missed" in o or "out of reach" in o or "moved away" in o or "hit nothing" in o or "struck a wall" in o:
        return "evaded"
    if "broken off" in o:
        return "broken"
    return o[:30] or "pending"


def damage_of(o: str | None) -> int:
    m = re.search(r"hit for (\d+)|(\d+) got through|killed [^(]*\((\d+)\)", o or "")
    return int(next(g for g in m.groups() if g)) if m else 0


def k_of(answered: list[bool], run: int = 3) -> int | None:
    for i in range(len(answered) - run + 1):
        if all(answered[i:i + run]):
            return i + 1
    return None


def score_episode(ep_meta: dict, uses: list[dict], samples: list[dict],
                  capture_recs: list[dict] | None = None) -> dict:
    """Compute every frozen measure from docs/NEURAL_BODY.md 'Pilot run'."""
    S, F = ep_meta["subject"], ep_meta["foe"]
    pattern_skills = set(ep_meta.get("pattern_skills", ["attack"]))
    mine = [u for u in uses if u["actor"] == S]
    mine_acc = [u for u in mine if u.get("accepted_ms")]
    foe_uses = [u for u in uses if u["actor"] == F and u["skill"] in pattern_skills and u.get("target") == S and u.get("accepted_ms")]
    foe_uses.sort(key=lambda u: (u["accepted_ms"], u["id"]))

    # Perceived-cue coverage: check capture decisions (Arm L) or sight distance <= 11 m (Arm G).
    cap_layout = next((r for r in (capture_recs or []) if r.get("kind") == "layout"), None)
    cap_decisions = [r for r in (capture_recs or []) if r.get("kind") == "decision"]
    cap_replies = [r for r in (capture_recs or []) if r.get("kind") == "reply"]
    cap_sessions = [r for r in (capture_recs or []) if r.get("kind") == "session"]
    own_len = int(cap_layout["own"]) if (cap_layout and "own" in cap_layout) else (len(cap_decisions[0]["encoded"]) - 89 if cap_decisions else 19)

    def nearest_pos(ms: int):
        if not samples:
            return None
        return min(samples, key=lambda x: abs(x["ms"] - ms))

    def perceived_at(ms: int) -> bool:
        if cap_decisions:
            near = [d for d in cap_decisions if ms - 150 <= d.get("now_ms", 0) <= ms + 600]
            if near:
                return any(d["encoded"][own_len] > 0.5 for d in near)
        p = nearest_pos(ms)
        if p and p.get("dist") is not None:
            return p["dist"] <= 11.0
        return True

    exposures = []
    timing_windup_ms = []
    timing_release_ms = []
    early_evasions = 0
    clock_anticipations = 0

    for idx, u in enumerate(foe_uses, 1):
        acc = u["accepted_ms"]
        rel = u.get("released_ms") or (acc + (350 if u["skill"] == "strike" else 750))
        cls = classify_outcome(u.get("outcome"))
        ans = cls in ("guarded", "dodged", "evaded")
        dmg = damage_of(u.get("outcome"))
        defs = [m for m in mine_acc if m["skill"] in ("dodge", "block", "jump") and acc - 300 <= m["accepted_ms"] <= rel + 50]
        in_window_defs = [m for m in defs if acc <= m["accepted_ms"] <= rel + 50]
        pre_windup_defs = [m for m in defs if acc - 300 <= m["accepted_ms"] < acc]
        if pre_windup_defs:
            clock_anticipations += len(pre_windup_defs)
        for m in in_window_defs:
            timing_windup_ms.append(m["accepted_ms"] - acc)
            timing_release_ms.append(rel - m["accepted_ms"])
            # Early evasion: dodge dash lasts 500 ms; if started > 550 ms before release and blow still hit!
            if m["skill"] == "dodge" and (rel - m["accepted_ms"]) > 550 and cls == "hit":
                early_evasions += 1
        counters = [m["skill"] for m in mine_acc if m["skill"] in ("strike", "attack", "bowshot", "firebolt") and rel <= m["accepted_ms"] <= rel + 2500]
        exposures.append({
            "k": idx,
            "skill": u["skill"],
            "accepted_ms": acc,
            "released_ms": rel,
            "outcome": u.get("outcome"),
            "class": cls,
            "answered": ans,
            "damage": dmg,
            "perceived": perceived_at(acc),
            "defences": [m["skill"] for m in in_window_defs],
            "counters": counters,
        })

    # Also count early evasions that happened with NO overlapping windup at all.
    for m in mine_acc:
        if m["skill"] in ("dodge", "block"):
            near_exp = any(e["accepted_ms"] - 100 <= m["accepted_ms"] <= e["released_ms"] + 100 for e in exposures)
            if not near_exp:
                early_evasions += 1

    ans_list = [e["answered"] for e in exposures]
    first_fit = next((e["k"] for e in exposures if e["answered"]), None)
    k_val = k_of(ans_list, 3)
    censored = len(exposures) < 3

    # Contact share, aimed attacks per contact-minute, return after retreat, boundary abuse.
    first_ms = exposures[0]["accepted_ms"] if exposures else (samples[0]["ms"] if samples else 0)
    end_ms = samples[-1]["ms"] if samples else first_ms
    fight_samples = [p for p in samples if p["ms"] >= first_ms and p.get("dist") is not None]
    contact_samples = [p for p in fight_samples if p["dist"] <= 4.0]
    contact_share = len(contact_samples) / len(fight_samples) if fight_samples else 0.0
    # Estimate contact duration in minutes from sample cadence.
    if len(fight_samples) >= 2:
        dt_s = (fight_samples[-1]["ms"] - fight_samples[0]["ms"]) / 1000.0
        contact_min = (dt_s * contact_share) / 60.0
    else:
        contact_min = 0.0
    aimed_attacks = [m for m in mine_acc if m["skill"] in ("strike", "attack", "bowshot", "firebolt") and m.get("target") == F and m["accepted_ms"] >= first_ms]
    aimed_per_contact_min = len(aimed_attacks) / contact_min if contact_min > 1e-4 else 0.0

    # Return after retreat: separation from <= 2.5 m to > 4.0 m, followed by <= 2.5 m within 6 s.
    retreats = 0
    returns = 0
    state_close = False
    retreat_t = None
    for p in fight_samples:
        d = p["dist"]
        if not state_close and d <= 2.5:
            state_close = True
            if retreat_t is not None and (p["ms"] - retreat_t) <= 6000:
                returns += 1
            retreat_t = None
        elif state_close and d > 4.0:
            state_close = False
            retreats += 1
            retreat_t = p["ms"]

    # Boundary / kite-away abuse: distance from arena start > 15 m.
    sx0, sy0 = ep_meta["start_xy"]
    far_from_arena = sum(1 for p in fight_samples if p.get("sxy") and math.hypot(p["sxy"][0] - sx0, p["sxy"][1] - sy0) > 15.0)
    boundary_abuse_share = far_from_arena / len(fight_samples) if fight_samples else 0.0

    # Resource use & refusal reasons.
    skill_counts = {}
    refusal_reasons = {}
    sources = {}
    for u in mine:
        sources[u.get("source", "?")] = sources.get(u.get("source", "?"), 0) + 1
        if u.get("accepted_ms"):
            skill_counts[u["skill"]] = skill_counts.get(u["skill"], 0) + 1
        out_str = str(u.get("outcome") or "")
        if out_str.startswith("refused:"):
            why = out_str.replace("refused:", "").strip()
            why = re.sub(r"\(\d+\.\d+ s\)", "(t s)", why)
            refusal_reasons[why] = refusal_reasons.get(why, 0) + 1
    for rep in cap_replies:
        if not rep.get("ok") and rep.get("refused"):
            why = f"reducer:{rep['reducer']}:{str(rep['refused'])[:60]}"
            refusal_reasons[why] = refusal_reasons.get(why, 0) + 1

    stamina_est = (
        10 * skill_counts.get("strike", 0)
        + 20 * skill_counts.get("dodge", 0)
        + 8 * skill_counts.get("block", 0)
        + 8 * skill_counts.get("attack", 0)
    )
    total_reducer_calls = len(cap_replies)
    too_many_calls = sum(1 for r in cap_replies if not r.get("ok") and "too many inputs" in str(r.get("refused") or ""))
    not_ready_refusals = sum(v for k, v in refusal_reasons.items() if "not ready" in k)
    decide_us = sorted(d["decide_us"] for d in cap_decisions if "decide_us" in d)
    decide_p95_ms = (decide_us[int(len(decide_us) * 0.95)] / 1000.0) if decide_us else 0.0
    epochs = sum(1 for s in cap_sessions if s.get("event") == "opened")
    lapses = sum(1 for s in cap_sessions if s.get("event") in ("lost", "stalled"))

    hps = [p["s_hp"] for p in samples if p.get("s_hp") is not None]
    foe_hps = [p["f_hp"] for p in samples if p.get("f_hp") is not None]
    survived = ep_meta["subject_alive_end"]
    foe_dead = not ep_meta["foe_alive_end"]

    return {
        "episode": ep_meta["episode"],
        "variant": ep_meta["variant"],
        "arm": ep_meta["arm"],
        "exposures": len(exposures),
        "perceived_exposures": sum(1 for e in exposures if e["perceived"]),
        "perceived_cue_coverage": round(sum(1 for e in exposures if e["perceived"]) / len(exposures), 3) if exposures else None,
        "answered": sum(ans_list),
        "answer_rate": round(sum(ans_list) / len(exposures), 3) if exposures else None,
        "answered_by_k": {
            "k1": int(ans_list[0]) if len(ans_list) >= 1 else None,
            "k2": int(ans_list[1]) if len(ans_list) >= 2 else None,
            "k3": int(ans_list[2]) if len(ans_list) >= 3 else None,
            "k4plus_rate": round(sum(ans_list[3:]) / len(ans_list[3:]), 3) if len(ans_list) > 3 else None,
        },
        "first_fitting_exposure": first_fit,
        "K": k_val,
        "censored_lt3": censored,
        "timing_rel_windup_p50_ms": round(statistics.median(timing_windup_ms), 1) if timing_windup_ms else None,
        "timing_rel_release_p50_ms": round(statistics.median(timing_release_ms), 1) if timing_release_ms else None,
        "damage_taken": sum(e["damage"] for e in exposures),
        "hp_min": round(min(hps), 1) if hps else None,
        "foe_hp_min": round(min(foe_hps), 1) if foe_hps else None,
        "survived": survived,
        "died_s": ep_meta.get("died_s"),
        "win": survived and foe_dead,
        "fight_s": round(ep_meta["fight_s"], 1),
        "contact_share": round(contact_share, 3),
        "aimed_attacks": len(aimed_attacks),
        "aimed_attacks_per_contact_min": round(aimed_per_contact_min, 2),
        "retreats": retreats,
        "returns_after_retreat": returns,
        "return_after_retreat_rate": round(returns / retreats, 3) if retreats > 0 else None,
        "skill_counts": skill_counts,
        "stamina_est": stamina_est,
        "refusal_reasons": refusal_reasons,
        "attribution_sources": sources,
        "policy_version": cap_decisions[0].get("policy_version") if cap_decisions else "graph-only",
        "exploits": {
            "early_evasion_count": early_evasions,
            "clock_anticipation_count": clock_anticipations,
            "boundary_abuse_share": round(boundary_abuse_share, 3),
            "not_ready_refusals": not_ready_refusals,
            "too_many_inputs": too_many_calls,
            "total_reducer_calls": total_reducer_calls,
        },
        "health": {
            "decide_p95_ms": round(decide_p95_ms, 2),
            "epochs": epochs,
            "lapses": lapses,
        },
        "exposure_trace": exposures,
    }


def run_single_duel(srv: ScratchServer, db: str, ep_cfg: dict, arm: str,
                    weights_path: Path | None, out_dir: Path,
                    horizon_s: float = 180.0, brief_override: dict | None = None) -> dict:
    """Run one matched duel episode on `srv`/`db` and return full scored dict."""
    ep_dir = out_dir / f"{ep_cfg['episode']}-{arm}"
    ep_dir.mkdir(parents=True, exist_ok=True)
    ranked = ranked_adult_residents(srv, db, set())
    fid = ranked[ep_cfg["actor_rank"]]
    spots = find_open_spots(srv, db, 12, min_sep=45.0)
    sx, sy = spots[ep_cfg["site_idx"]]
    dx, dy = ep_cfg["offset"]
    sid = spawn_subject(srv, db, f"Wren_{ep_cfg['episode']}", (sx, sy), kit=True)
    srv.call(db, "admin_set_vitals", [fid, 100.0])
    if ep_cfg.get("foe_spear", True):
        srv.call(db, "grant_items", [fid, "spear", 1])
    srv.call(db, "grant_know_how", [fid, "wound_tending"])

    goal = (brief_override or {}).get("goal", "engage")
    stance = (brief_override or {}).get("stance", "even")
    risk = (brief_override or {}).get("risk", 0.5)
    style = (brief_override or {}).get("style", 0.5)
    traits = (brief_override or {}).get("traits", [0.0, 0.0])

    worker = None
    logf = None
    cap_dir = ep_dir / "capture"
    if arm == "learned":
        assert weights_path is not None
        sx, sy = place_and_brief(
            srv, db, sid, fid, sx, sy, dx, dy,
            make_brief_arg(goal, fid, stance, risk, style, 300.0, traits, f"eval {ep_cfg['episode']}")
        )
        srv.call(db, "set_behavior", [sid, json.dumps(delegate_leaf_graph(fid, goal, exit_hp=15.0))])
        cap_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ,
                   LIVING_ROOT=str(ROOT),
                   LIVING_SERVER=srv.url,
                   LIVING_DB=db,
                   LIVING_TOKEN=srv.token(),
                   LIVING_BODY_ONLY=str(sid),
                   LIVING_BODY_HZ="15",
                   LIVING_BODY_WEIGHTS=str(weights_path),
                   LIVING_BODY_CAPTURE=str(cap_dir),
                   LIVING_BODY_CAPTURE_FILE_MB="32",
                   LIVING_BODY_CAPTURE_FILES="4",
                   RUST_LOG="info,spacetimedb_sdk=warn")
        logf = (ep_dir / "body.log").open("w")
        worker = subprocess.Popen(["taskset", "-c", PIN_CPUS, str(MIND_BIN), "body"], cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)
        # Wait until worker opens live session (up to 15 s) BEFORE starting foe!
        t_wait = time.time()
        while time.time() - t_wait < 15.0:
            rows = srv.sql(db, f"SELECT live FROM body_session WHERE actor = {sid}")
            if rows and rows[0]["live"]:
                break
            time.sleep(0.25)
        time.sleep(0.5)
    else:
        sx, sy = place_and_brief(srv, db, sid, fid, sx, sy, dx, dy, None)
        srv.call(db, "set_behavior", [sid, json.dumps(graph_only_baseline(fid))])

    # Start foe right now (matched start!).
    foe_g = foe_heavy_graph(
        sid,
        pause_a=ep_cfg.get("pause_a", 2.0),
        pause_b=ep_cfg.get("pause_b", 3.0),
        irregular=ep_cfg.get("irregular", False),
        mixed_strike=ep_cfg.get("mixed_strike", False),
    )
    srv.call(db, "set_behavior", [fid, json.dumps(foe_g)])

    start_wall = time.time()
    start_ms = int(start_wall * 1000)
    samples = []
    beyond5_since = None
    reapproach_n = 0
    died_s = None
    death_wall = None
    s_alive = True
    f_alive = True

    try:
        while True:
            now_wall = time.time()
            elapsed = now_wall - start_wall
            if elapsed >= horizon_s:
                break
            if death_wall is not None and now_wall - death_wall >= 5.0:
                break
            bs = {b["id"]: b for b in srv.sql(db, f"SELECT id, x, y, vx, vy, heading FROM body WHERE id = {sid} OR id = {fid}")}
            cs = {c["id"]: c["alive"] for c in srv.sql(db, f"SELECT id, alive FROM character WHERE id = {sid} OR id = {fid}")}
            vs = {v["id"]: v["hp"] for v in srv.sql(db, f"SELECT id, hp FROM vitals WHERE id = {sid} OR id = {fid}")}
            s_alive = bool(cs.get(sid, False))
            f_alive = bool(cs.get(fid, False))
            sxy = (float(bs[sid]["x"]), float(bs[sid]["y"])) if sid in bs else None
            fxy = (float(bs[fid]["x"]), float(bs[fid]["y"])) if fid in bs else None
            dist = math.hypot(sxy[0] - fxy[0], sxy[1] - fxy[1]) if (sxy and fxy) else None
            samples.append({
                "ms": int(now_wall * 1000),
                "t": round(elapsed, 2),
                "sxy": [round(sxy[0], 2), round(sxy[1], 2)] if sxy else None,
                "fxy": [round(fxy[0], 2), round(fxy[1], 2)] if fxy else None,
                "dist": round(dist, 3) if dist is not None else None,
                "s_hp": round(float(vs[sid]), 1) if sid in vs else None,
                "f_hp": round(float(vs[fid]), 1) if fid in vs else None,
                "s_alive": s_alive,
                "f_alive": f_alive,
            })
            if not s_alive and died_s is None:
                died_s = round(elapsed, 1)
                death_wall = now_wall
            if not f_alive and death_wall is None:
                death_wall = now_wall
            # R2 heavy re-approach trigger: beyond 5 m for 4 s -> foe walks to subject_xy and resumes heavy graph.
            if ep_cfg.get("reapproach", True) and s_alive and f_alive and dist is not None and dist > 5.0:
                if beyond5_since is None:
                    beyond5_since = now_wall
                elif now_wall - beyond5_since >= 4.0:
                    beyond5_since = None
                    reapproach_n += 1
                    re_g = {"seq": [{"do": {"skill": "goto", "target": {"at": [sxy[0], sxy[1]]}}}, foe_g]}
                    try:
                        srv.call(db, "set_behavior", [fid, json.dumps(re_g)])
                    except Exception:
                        pass
            else:
                beyond5_since = None
            time.sleep(0.25)
    finally:
        if worker is not None:
            worker.send_signal(signal.SIGTERM)
            worker.wait(timeout=15)
        if logf is not None:
            logf.close()

    uses = srv.sql(db, f"SELECT * FROM skill_use WHERE (actor = {sid} OR actor = {fid}) AND at_ms >= {start_ms - 1000}")
    cap_recs = []
    if arm == "learned" and cap_dir.exists():
        for jf in sorted(cap_dir.glob("body-*.jsonl")):
            for line in jf.read_text().splitlines():
                cap_recs.append(json.loads(line))
    ep_meta = {
        "episode": ep_cfg["episode"],
        "variant": ep_cfg["variant"],
        "arm": arm,
        "subject": sid,
        "foe": fid,
        "start_xy": (sx, sy),
        "pattern_skills": ep_cfg.get("pattern_skills", ["attack"]),
        "subject_alive_end": s_alive,
        "foe_alive_end": f_alive,
        "died_s": died_s,
        "fight_s": time.time() - start_wall,
        "reapproaches": reapproach_n,
    }
    scored = score_episode(ep_meta, uses, samples, cap_recs if arm == "learned" else None)
    (ep_dir / "samples.jsonl").write_text("\n".join(json.dumps(x) for x in samples) + "\n")
    (ep_dir / "uses.jsonl").write_text("\n".join(json.dumps(x) for x in uses) + "\n")
    (ep_dir / "score.json").write_text(json.dumps(scored, indent=2) + "\n")
    return scored


# ---- Step 4: Brief Swap (THE FIRST TEST) ----

def cmd_brief_swap(args):
    guard.check_resources()
    guard.check_no_cuda()
    guard.check_battle_lock()
    weights = Path(args.weights)
    out_dir = PILOT_DIR / "step4-brief-swap"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Stop Rule 4: deterministic replay check on weights before running!
    b1 = json.loads(subprocess.check_output(["taskset", "-c", "0", str(MIND_BIN), "body-bench", "--weights", str(weights), "--iters", "1000"], cwd=ROOT, text=True))
    b2 = json.loads(subprocess.check_output(["taskset", "-c", "0", str(MIND_BIN), "body-bench", "--weights", str(weights), "--iters", "1000"], cwd=ROOT, text=True))
    guard.check_replay_determinism(b1["replay_hash"], b2["replay_hash"], True)

    port = pick_ports(1, 3431)[0]
    srv = ScratchServer("slop-nbclone-bswap", port)
    briefs = [
        ("withdraw", {"goal": "withdraw", "stance": "guarded", "risk": 0.1, "style": 0.3, "traits": [-0.6, 0.0]}),
        ("hold", {"goal": "hold", "stance": "even", "risk": 0.3, "style": 0.5, "traits": [0.0, 0.2]}),
        ("engage", {"goal": "engage", "stance": "pressing", "risk": 0.8, "style": 0.7, "traits": [0.5, 0.2]}),
    ]
    rows = []
    try:
        srv.start()
        for rep in range(1, args.replicates + 1):
            for name, bcfg in briefs:
                db = f"verify-nb-bs-{name}-r{rep}"
                srv.publish_island(db)
                try:
                    ep_cfg = {
                        "episode": f"bs_{name}_r{rep}",
                        "variant": f"brief-swap:{name}",
                        "actor_rank": 0,  # nominal heavy foe
                        "site_idx": rep,
                        "offset": (5.0, 0.0),
                        "reapproach": (name != "withdraw"),
                    }
                    sc = run_single_duel(srv, db, ep_cfg, "learned", weights, out_dir, horizon_s=45.0, brief_override=bcfg)
                    samps = [json.loads(l) for l in (out_dir / f"{ep_cfg['episode']}-learned/samples.jsonl").read_text().splitlines() if l.strip()]
                    dists = [x["dist"] for x in samps if x.get("dist") is not None]
                    d_after_10 = [x["dist"] for x in samps if x["t"] >= 10.0 and x.get("dist") is not None]
                    rec = {
                        "brief": name,
                        "replicate": rep,
                        "median_dist_m": round(statistics.median(dists), 2) if dists else None,
                        "median_dist_after10s_m": round(statistics.median(d_after_10), 2) if d_after_10 else None,
                        "max_dist_m": round(max(dists), 2) if dists else None,
                        "min_dist_m": round(min(dists), 2) if dists else None,
                        "share_gt8m": round(sum(1 for d in dists if d > 8.0) / len(dists), 3) if dists else 0.0,
                        "share_2p5_6m": round(sum(1 for d in dists if 2.5 <= d <= 6.0) / len(dists), 3) if dists else 0.0,
                        "share_le2p5m": round(sum(1 for d in dists if d <= 2.5) / len(dists), 3) if dists else 0.0,
                        "strikes": sc["skill_counts"].get("strike", 0),
                        "dodges": sc["skill_counts"].get("dodge", 0),
                        "blocks": sc["skill_counts"].get("block", 0),
                        "exposures": sc["exposures"],
                        "answered": sc["answered"],
                        "policy_version": sc["policy_version"],
                    }
                    rows.append(rec)
                    print(f"[Step 4] {name:8s} r{rep}: med_dist={rec['median_dist_after10s_m']}m (max={rec['max_dist_m']}m, min={rec['min_dist_m']}m) | strikes={rec['strikes']} dodges={rec['dodges']} blocks={rec['blocks']} | ans={rec['answered']}/{rec['exposures']}", flush=True)
                finally:
                    srv.delete_world(db)
    finally:
        srv.stop_and_remove(out_dir / "stdb-bswap.log")

    # Aggregate brief-swap gate check.
    by_b = {b: [r for r in rows if r["brief"] == b] for b, _ in briefs}
    w_dist = statistics.median(r["max_dist_m"] for r in by_b["withdraw"])
    w_strikes = sum(r["strikes"] for r in by_b["withdraw"])
    h_dist = statistics.median(r["median_dist_after10s_m"] for r in by_b["hold"])
    h_strikes = sum(r["strikes"] for r in by_b["hold"])
    e_min = statistics.median(r["min_dist_m"] for r in by_b["engage"])
    e_strikes = sum(r["strikes"] for r in by_b["engage"])
    gate_pass = (w_dist > 8.0 and w_strikes == 0 and 2.5 <= h_dist <= 6.5 and h_strikes <= 2 and e_min <= 2.5 and e_strikes >= 3)
    report = {
        "weights": str(weights),
        "policy_version": b1["version"],
        "replay_hash": b1["replay_hash"],
        "rows": rows,
        "summary": {
            "withdraw_med_max_dist_m": w_dist,
            "withdraw_total_strikes": w_strikes,
            "hold_med_dist_after10s_m": h_dist,
            "hold_total_strikes": h_strikes,
            "engage_med_min_dist_m": e_min,
            "engage_total_strikes": e_strikes,
            "brief_swap_gate_pass": gate_pass,
        },
    }
    (out_dir / "brief-swap.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2), flush=True)


# ---- Step 5: 10 Paired Episodes Evaluation (Arm L vs Arm G) ----

EVAL_EPISODES = [
    {"episode": "ep01", "variant": "nominal-east", "actor_rank": 0, "site_idx": 0, "offset": (6.0, 0.0), "foe_spear": True, "pause_a": 2.0, "pause_b": 3.0, "irregular": False, "mixed_strike": False, "pattern_skills": ["attack"]},
    {"episode": "ep02", "variant": "nominal-west", "actor_rank": 1, "site_idx": 1, "offset": (-6.0, 0.0), "foe_spear": True, "pause_a": 2.0, "pause_b": 3.0, "irregular": False, "mixed_strike": False, "pattern_skills": ["attack"]},
    {"episode": "ep03", "variant": "nominal-north", "actor_rank": 2, "site_idx": 2, "offset": (0.0, -6.0), "foe_spear": True, "pause_a": 2.0, "pause_b": 3.0, "irregular": False, "mixed_strike": False, "pattern_skills": ["attack"]},
    {"episode": "ep04", "variant": "nominal-south", "actor_rank": 3, "site_idx": 3, "offset": (0.0, 6.0), "foe_spear": True, "pause_a": 2.0, "pause_b": 3.0, "irregular": False, "mixed_strike": False, "pattern_skills": ["attack"]},
    {"episode": "ep05", "variant": "heldout-range-close-2.5m", "actor_rank": 4, "site_idx": 4, "offset": (-1.8, -1.8), "foe_spear": True, "pause_a": 2.0, "pause_b": 3.0, "irregular": False, "mixed_strike": False, "pattern_skills": ["attack"]},
    {"episode": "ep06", "variant": "heldout-range-far-10m", "actor_rank": 5, "site_idx": 5, "offset": (7.1, 7.1), "foe_spear": True, "pause_a": 2.0, "pause_b": 3.0, "irregular": False, "mixed_strike": False, "pattern_skills": ["attack"]},
    {"episode": "ep07", "variant": "heldout-windup-650ms", "actor_rank": 6, "site_idx": 6, "offset": (3.5, -3.5), "foe_spear": False, "pause_a": 2.0, "pause_b": 3.0, "irregular": False, "mixed_strike": False, "pattern_skills": ["attack"]},
    {"episode": "ep08", "variant": "heldout-irregular-pause", "actor_rank": 7, "site_idx": 7, "offset": (-5.3, 5.3), "foe_spear": True, "pause_a": 0.8, "pause_b": 4.2, "irregular": True, "mixed_strike": False, "pattern_skills": ["attack"]},
    {"episode": "ep09", "variant": "heldout-mixed-350-750ms", "actor_rank": 8, "site_idx": 8, "offset": (4.5, 0.0), "foe_spear": True, "pause_a": 1.5, "pause_b": 2.5, "irregular": False, "mixed_strike": True, "pattern_skills": ["attack", "strike"]},
    {"episode": "ep10", "variant": "heldout-fast-650ms-far", "actor_rank": 9, "site_idx": 9, "offset": (-9.0, 0.0), "foe_spear": False, "pause_a": 1.0, "pause_b": 1.8, "irregular": False, "mixed_strike": False, "pattern_skills": ["attack"]},
]


def cmd_eval(args):
    guard.check_resources()
    guard.check_no_cuda()
    guard.check_battle_lock()
    weights = Path(args.weights)
    out_dir = PILOT_DIR / "step5-eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    episodes = EVAL_EPISODES[:args.max_episodes]
    guard.check_budgets(eval_episodes=len(episodes))

    # Stop Rule 4: deterministic replay check.
    b1 = json.loads(subprocess.check_output(["taskset", "-c", "0", str(MIND_BIN), "body-bench", "--weights", str(weights), "--iters", "1000"], cwd=ROOT, text=True))
    b2 = json.loads(subprocess.check_output(["taskset", "-c", "0", str(MIND_BIN), "body-bench", "--weights", str(weights), "--iters", "1000"], cwd=ROOT, text=True))
    guard.check_replay_determinism(b1["replay_hash"], b2["replay_hash"], True)

    # Run 2 private servers in parallel (one for Arm G, one for Arm L) so paired episodes run simultaneously!
    ports = pick_ports(2, 3441)
    srv_g = ScratchServer("slop-nbclone-evg", ports[0])
    srv_l = ScratchServer("slop-nbclone-evl", ports[1])
    results_g = []
    results_l = []
    expected_wasm = None
    expected_skills = None

    try:
        srv_g.start()
        srv_l.start()
        for idx, ep in enumerate(episodes, 1):
            guard.check_resources(capture_dir=out_dir)
            db_g = f"verify-nb-{ep['episode']}-g"
            db_l = f"verify-nb-{ep['episode']}-l"
            mg = srv_g.publish_island(db_g)
            ml = srv_l.publish_island(db_l)
            if expected_wasm is None:
                expected_wasm, expected_skills = mg["wasm_sha"], mg["skills_sha"]
            guard.check_hashes(WASM_HOST_DIR / WASM_NAME, expected_wasm, mg["skills_sha"], expected_skills)
            guard.check_hashes(WASM_HOST_DIR / WASM_NAME, expected_wasm, ml["skills_sha"], expected_skills)
            guard.check_replay_determinism(b1["replay_hash"], b2["replay_hash"], mg["body_delegate_on"] and ml["body_delegate_on"])

            import concurrent.futures
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                    fg = ex.submit(run_single_duel, srv_g, db_g, ep, "graph", None, out_dir, args.horizon_s)
                    fl = ex.submit(run_single_duel, srv_l, db_l, ep, "learned", weights, out_dir, args.horizon_s)
                    sg = fg.result()
                    sl = fl.result()
            finally:
                srv_g.delete_world(db_g)
                srv_l.delete_world(db_l)

            results_g.append(sg)
            results_l.append(sl)
            print(
                f"[Step 5] {ep['episode']} ({ep['variant']}): "
                f"G ans={sg['answered']}/{sg['exposures']} first={sg['first_fitting_exposure']} K={sg['K']} dmg={sg['damage_taken']} surv={sg['survived']} win={sg['win']} c={sg['contact_share']} atk/m={sg['aimed_attacks_per_contact_min']} | "
                f"L ans={sl['answered']}/{sl['exposures']} first={sl['first_fitting_exposure']} K={sl['K']} dmg={sl['damage_taken']} surv={sl['survived']} win={sl['win']} c={sl['contact_share']} atk/m={sl['aimed_attacks_per_contact_min']}",
                flush=True,
            )
            # Stop Rule 1 (plumbing encounter check on first 2 replicates) & Stop Rule 5 (timing/input budget).
            if idx == 2:
                guard.check_plumbing_encounters([r["exposures"] for r in results_l])
            guard.check_timing_and_inputs(
                sl["health"]["decide_p95_ms"],
                sl["health"]["epochs"],
                sl["health"]["lapses"],
                sl["exploits"]["total_reducer_calls"],
                sl["exploits"]["too_many_inputs"],
            )
    finally:
        srv_g.stop_and_remove(out_dir / "stdb-eval-g.log")
        srv_l.stop_and_remove(out_dir / "stdb-eval-l.log")

    # ---- Compute frozen §7 pass screen ----
    def rank_first(v):
        return 999 if v is None else v

    med_first_g = statistics.median(rank_first(r["first_fitting_exposure"]) for r in results_g)
    med_first_l = statistics.median(rank_first(r["first_fitting_exposure"]) for r in results_l)
    first_by3_l = sum(1 for r in results_l if r["first_fitting_exposure"] is not None and r["first_fitting_exposure"] <= 3)
    first_by3_g = sum(1 for r in results_g if r["first_fitting_exposure"] is not None and r["first_fitting_exposure"] <= 3)
    med_dmg_g = statistics.median(r["damage_taken"] for r in results_g)
    med_dmg_l = statistics.median(r["damage_taken"] for r in results_l)
    surv_g = sum(1 for r in results_g if r["survived"])
    surv_l = sum(1 for r in results_l if r["survived"])
    win_g = sum(1 for r in results_g if r["win"])
    win_l = sum(1 for r in results_l if r["win"])
    med_contact_g = statistics.median(r["contact_share"] for r in results_g)
    med_contact_l = statistics.median(r["contact_share"] for r in results_l)
    med_atk_g = statistics.median(r["aimed_attacks_per_contact_min"] for r in results_g)
    med_atk_l = statistics.median(r["aimed_attacks_per_contact_min"] for r in results_l)

    screen = {
        "first_by_exp3_ge6": first_by3_l >= 6,
        "med_first_earlier_by1": (med_first_g - med_first_l) >= 1.0,
        "med_dmg_not_higher": med_dmg_l <= med_dmg_g,
        "survival_not_worse": surv_l >= surv_g,
        "contact_ge_90pct": (med_contact_l >= 0.90 * med_contact_g) if med_contact_g > 0 else True,
        "aimed_atk_ge_90pct": (med_atk_l >= 0.90 * med_atk_g) if med_atk_g > 0 else True,
    }
    screen["overall_pass"] = all(screen.values())

    report = {
        "weights": str(weights),
        "policy_version": b1["version"],
        "replay_hash": b1["replay_hash"],
        "wasm_sha": expected_wasm,
        "skills_sha": expected_skills,
        "graph_only": results_g,
        "learned": results_l,
        "aggregate": {
            "n_episodes": len(episodes),
            "first_by_exp3": {"graph": first_by3_g, "learned": first_by3_l},
            "median_first_fit_ranked": {"graph": med_first_g, "learned": med_first_l},
            "total_answered": {"graph": f"{sum(r['answered'] for r in results_g)}/{sum(r['exposures'] for r in results_g)}",
                               "learned": f"{sum(r['answered'] for r in results_l)}/{sum(r['exposures'] for r in results_l)}"},
            "K_achieved": {"graph": sum(1 for r in results_g if r["K"] is not None), "learned": sum(1 for r in results_l if r["K"] is not None)},
            "median_damage": {"graph": med_dmg_g, "learned": med_dmg_l},
            "survived": {"graph": surv_g, "learned": surv_l},
            "wins": {"graph": win_g, "learned": win_l},
            "median_contact_share": {"graph": round(med_contact_g, 3), "learned": round(med_contact_l, 3)},
            "median_aimed_atk_per_contact_min": {"graph": round(med_atk_g, 2), "learned": round(med_atk_l, 2)},
            "exploits_learned_totals": {
                "early_evasion": sum(r["exploits"]["early_evasion_count"] for r in results_l),
                "clock_anticipation": sum(r["exploits"]["clock_anticipation_count"] for r in results_l),
                "max_boundary_abuse_share": max(r["exploits"]["boundary_abuse_share"] for r in results_l),
                "not_ready_refusals": sum(r["exploits"]["not_ready_refusals"] for r in results_l),
                "too_many_inputs": sum(r["exploits"]["too_many_inputs"] for r in results_l),
            },
        },
        "pass_screen": screen,
    }
    (out_dir / "eval-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"aggregate": report["aggregate"], "pass_screen": screen}, indent=2), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("throughput")
    p1.add_argument("--quick", action="store_true")
    p2 = sub.add_parser("collect")
    p2.add_argument("--sessions", type=int, default=3)
    p2.add_argument("--duels", type=int, default=16)
    p2.add_argument("--duration-s", type=int, default=150)
    p4 = sub.add_parser("brief-swap")
    p4.add_argument("--weights", required=True)
    p4.add_argument("--replicates", type=int, default=3)
    p5 = sub.add_parser("eval")
    p5.add_argument("--weights", required=True)
    p5.add_argument("--max-episodes", type=int, default=10)
    p5.add_argument("--horizon-s", type=float, default=180.0)
    a = ap.parse_args()
    {"throughput": cmd_throughput, "collect": cmd_collect, "brief-swap": cmd_brief_swap, "eval": cmd_eval}[a.cmd](a)


if __name__ == "__main__":
    main()
