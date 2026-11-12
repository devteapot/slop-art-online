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
  trials.py clean --batch B             delete the batch's databases (its own records; each paused first) and Neo4j minds (evidence kept)
  trials.py dbs --batch B [--json]      the batch's databases from its runner's records: name, identity, replica
  trials.py reclaim [--json FILE]       classify the trial volume's replica directories (live, paid, no-model, fake, verify); removes nothing
  trials.py ledger                      real tokens spent per batch against the total cap

Defaults are the Spark setup: container slop-trials-stdb on 127.0.0.1:3320 and Neo4j
slop-trials-neo4j on 127.0.0.1:7699 (TRIALS_STDB_CONTAINER, TRIALS_STDB_PORT,
TRIALS_NEO4J_CONTAINER, TRIALS_NEO4J_PORT). Databases are always `verify-trial-<batch>-...`;
the runner never publishes or deletes anything else. Evidence: .local/living/trials/<batch>/.
"""
import argparse
import bisect
import concurrent.futures
import datetime
import hashlib
import json
import math
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ooc  # noqa: E402
from journal_io import restore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TRIALS = ROOT / "living/trials"
OUT = ROOT / ".local/living/trials"
CONTAINER = os.environ.get("TRIALS_STDB_CONTAINER", "slop-trials-stdb")
PORT = int(os.environ.get("TRIALS_STDB_PORT", "3320"))
# Where `up` publishes the port: loopback by default; 0.0.0.0 lets LAN observers watch.
BIND = os.environ.get("TRIALS_STDB_BIND", "127.0.0.1")
URL = f"http://127.0.0.1:{PORT}"
NEO4J = os.environ.get("TRIALS_NEO4J_CONTAINER", "slop-trials-neo4j")
NEO4J_PORT = int(os.environ.get("TRIALS_NEO4J_PORT", "7699"))
TARGET = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "living/target")
IMAGE_STDB = "clockworklabs/spacetime:v2.14.1"
IMAGE_NEO4J = "neo4j:2026.10.1"
# Services that hold other people's worlds. The runner never addresses them.
PROTECTED = {"sao-living_spacetimedb_1", "sao-living-neo4j-1"}
PREFIX = "verify-trial-"
# No total cap unless one is asked for: trials measure tokens; the runaway watchdog stops loops.
TOTAL_CAP = int(os.environ["TRIALS_TOTAL_TOKENS"]) if os.environ.get("TRIALS_TOTAL_TOKENS") else None
FAKE = ROOT / ".agents/skills/verify-llm/scripts/fake_llm.py"
FOOD = {"berries", "meat", "fish", "cooked_meat", "cooked_fish", "smoked_meat", "smoked_fish", "bread"}
SAMPLE_S = 2.0
# How a player-framed system prompt opens (LIVING_FRAME=player; prompts.rs PLAYER_FRAME).
PLAYER_FRAME_HEAD = "You are an AI playing the person described under # Who you are"
# Estimated USD per million tokens: (input, output, cached input), for the report only, not an
# invoice. Mistral's model pages, read 2026-11-09 (docs.mistral.ai/models/...): DeepSeek V4.1
# Flash 0.30 / 1.20 / 0.007; GLM 5.3 Flash 0.15 / 0.50 / 0.03; Ministral 3 3B, 8B and 14B
# 0.10, 0.15 and 0.20 per million (one unlabeled price, taken as both input and output; no
# cached price). Reasoning tokens are counted in completion tokens and priced as output (the
# pages do not say). Mistral Small (batches b1-b3 only): third-party lists, 0.20 / 0.60.
PRICES = {"deepseek-v4-1-flash-1017": (0.30, 1.20, 0.007), "zai-glm-5-3-flash": (0.15, 0.50, 0.03),
          "ministral-3b-latest": (0.10, 0.10, 0.10), "ministral-8b-latest": (0.15, 0.15, 0.15),
          "ministral-14b-latest": (0.20, 0.20, 0.20), "mistral-small-latest": (0.20, 0.60, 0.20)}


def cost(model, prompt, completion, cached):
    pr = PRICES.get(model)
    if not pr:
        return None
    return ((prompt - cached) * pr[0] + cached * pr[2] + completion * pr[1]) / 1e6
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
    # A name is a file in living/trials/, or a path to a trial file elsewhere (an iteration's).
    path = Path(name) if name.endswith(".json") else TRIALS / f"{name}.json"
    t = json.loads(path.read_text())
    if "extends" in t:
        base = load_trial(t.pop("extends"))
        # Lists (the timeline) are replaced as a whole; objects are merged.
        t = deep_merge(base, t)
    t["name"] = Path(name).stem if name.endswith(".json") else name
    return t


def variants():
    """living/trials/variants.json, plus any in the file TRIALS_VARIANTS names (an iteration's
    variants, kept out of the tracked list)."""
    v = json.loads((TRIALS / "variants.json").read_text())
    extra = os.environ.get("TRIALS_VARIANTS")
    if extra:
        v.update(json.loads(Path(extra).read_text()))
    return v


def worlds_of(t):
    """The worlds a trial runs on: one, or one per entry of `world_seeds` (replicate k runs on
    the k-th, cycling), each the trial's world with its `seed` overridden."""
    seeds = t.get("world_seeds")
    if not seeds:
        return {t["name"]: t["world"]}
    return {f"{t['name']}#{n}": deep_merge(t["world"], {"overrides": {**t["world"].get("overrides", {}), "seed": n}}) for n in seeds}


def world_key(t, rep):
    seeds = t.get("world_seeds")
    return f"{t['name']}#{seeds[(rep - 1) % len(seeds)]}" if seeds else t["name"]


def journal_file(name):
    """A character's journal file name, as the mind writes it (llm.rs: every character that is
    not a letter or digit becomes `_`, so "Sefa Reed" is Sefa_Reed.jsonl)."""
    return "".join(c if c.isalnum() else "_" for c in name) + ".jsonl"


# A seed's laws (`laws`/`laws_file`) composed over the shipped script as the authority composes
# them at creation (`living_rules::floors::compose`): one Python copy, in install_script.py.
from install_script import OVERLAY_MARK, compose_laws, same_script, seed_laws, without_world_laws  # noqa: E402

DEFAULT_DAY_MS = 12 * 60 * 1000  # living_rules::DEFAULT_DAY_MS: a seed without `day_minutes`


def laws_problems(seed, overlay, built, creation, sent, readback, day_ms):
    """Why an instance must not start with the script its world runs; [] when it may.

    `seed` is the parsed world seed and `overlay` its laws ("" without). `built` is the runner's
    composition of the script the world was created with (its laws over the tree's skills.rhai;
    None for a module built elsewhere, a variant's `wasm_tag`, whose overlay is then looked for
    at the row's end). `creation` is the `script` row before any install, `sent` the source
    installed (None for a variant that keeps the world's own laws), `readback` the row after,
    and `day_ms` the world's day."""
    bad = []
    if sent is not None and not same_script(readback, sent):
        bad.append("the `script` row read back after install_script is not the source the runner sent")
    if sent is None and built is not None and not same_script(readback, built):
        bad.append("the world keeps its own laws (no install), but its `script` row is not the seed's laws composed over skills.rhai")
    if overlay:
        if built is not None and not same_script(creation, built):
            bad.append("the world's creation-time composition of the seed's laws differs from the runner's")
        if built is None and not without_world_laws(creation or "").rstrip("\n").endswith(OVERLAY_MARK + overlay.rstrip("\n")):
            bad.append("the world's creation-time script does not end with the seed's laws")
        want = round(float(seed["day_minutes"]) * 60000) if seed.get("day_minutes") is not None else DEFAULT_DAY_MS
        if day_ms != want:
            bad.append(f"world.day_ms is {day_ms}, not the seed's day_minutes ({want})")
    return bad


def mind_concurrency(trial):
    """How many model calls the trial's mind service runs at once (`LIVING_CONCURRENCY`):
    `minds.concurrency`, else 64 where many think (`minds.only` "all" or `minds.max`) and 4 for a
    single thinker. Before 2026-11-11 every trial ran at 4: in the hamlet's greeting batches the
    queue, not the model, set the pace (talk turns waited a median 2-7 s, p90 15-25 s, against
    0.8 s of model time; deliberations 6-13 s). One-mind trials keep 4, so their batches stay
    comparable."""
    m = trial.get("minds", {})
    if m.get("concurrency"):
        return int(m["concurrency"])
    return 64 if m.get("only") == "all" or m.get("max") else 4


def residents_from(seed, spec):
    """A seed with some residents' authored entries (sheet, rhythm, places, kit: the whole
    resident) taken from another commit's version of the same seed (`world.residents_from`:
    `ref`, a git revision, and `names`). For arms that must differ only in some lives: the
    strangers trial's C and S run the Quill, Morrow and Sato entries from before the lives were
    written (dc2ecfc8^), L and LS main's (docs/STRANGERS.md). Every name must exist in both; the
    resolved commit goes in the seed's `trial_residents_from` (read by trials, not the authority)."""
    ref, names = spec["ref"], list(spec["names"])
    sha = sh("git", "-C", ROOT, "rev-parse", "--short", ref).stdout.strip()
    old = json.loads(sh("git", "-C", ROOT, "show", f"{sha}:living/seeds/{spec.get('seed', seed['run'])}.json").stdout)

    def residents(x, acc):
        if isinstance(x, dict):
            if "sheet" in x and "name" in x:
                acc[x["name"]] = x
            for v in x.values():
                residents(v, acc)
        elif isinstance(x, list):
            for v in x:
                residents(v, acc)
        return acc
    then, now = residents(old, {}), residents(seed, {})
    missing = [n for n in names if n not in then or n not in now]
    if missing:
        raise RuntimeError(f"residents_from {ref}: {missing} not in both seeds")
    for n in names:
        now[n].clear()
        now[n].update(json.loads(json.dumps(then[n])))
    seed["trial_residents_from"] = {"ref": ref, "commit": sha, "names": names}
    return seed


def patch_skills(text, trial, variant):
    """A skills file with the trial's `skills_patch`, then the variant's, applied: each entry is
    name -> [old, new], a law value changed in place. An old text that does not occur exactly
    once is an error: a rules file that moved on must not silently run unpatched."""
    names = []
    for owner, patches in (("trial", trial.get("skills_patch") or {}), ("variant", variant.get("skills_patch") or {})):
        for name, (old, new) in patches.items():
            n = text.count(old)
            if n != 1:
                raise RuntimeError(f"{owner} skills_patch {name}: {old[:80]!r} occurs {n} times in the skills file")
            text = text.replace(old, new)
            names.append(name)
    return text, names


def world_seed(world):
    """A trial world is a seed plus overrides, written as a derived seed the module and the
    mind both read (LIVING_SEED is resolved under living/seeds/, so a relative path works)."""
    base = json.loads((ROOT / "living/seeds" / f"{world['seed']}.json").read_text())
    merged = deep_merge(base, {"rules": world.get("rules", {}), **world.get("overrides", {})})
    if world.get("residents_from"):
        merged = residents_from(merged, world["residents_from"])
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
           "-p", f"{BIND}:{PORT}:3000", "-v", f"{CONTAINER}:/home/spacetime",
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
    try:
        live = [d for d in databases() if d.startswith(PREFIX)]
    except RuntimeError as e:
        live = []
        print(f"note: {e}")
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
    """The trial databases `spacetime list` shows (the container CLI's identity owns them). A
    backstop only: deleting a database removes it from the list but not from disk, and a run's
    own records (`state.json`, `batch_databases`) are what clean, reclaim and samplers use."""
    r = sh("docker", "exec", CONTAINER, "spacetime", "list", check=False)
    if r.returncode != 0 or "Error" in (r.stderr or "") or "Error" in r.stdout:
        # One database whose name is 64 characters or more makes the server's `/names` answer
        # 500 and the whole listing fail (2026-11-12, fs1e): an empty list is not "none".
        raise RuntimeError(f"spacetime list failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return [l.split("|")[0].strip() for l in r.stdout.splitlines() if l.strip().startswith(PREFIX)]


# SpacetimeDB 2.14.1 accepts a longer database name at publish, but its `/names` route then
# fails ("Domain name parts must be shorter than 64 characters"), and with it `spacetime list`.
MAX_DB_NAME = 63


REPLICAS = "/home/spacetime/.local/share/spacetime/data/replicas"


def database_identity(db):
    """A database's identity by its name (`GET /v1/database/<name>`), or None when it is gone."""
    code, body = http(f"/v1/database/{db}")
    if code != 200:
        return None
    try:
        return json.loads(body)["database_identity"]["__identity__"].removeprefix("0x")
    except (ValueError, KeyError, TypeError):
        return None


def replica_of(db, token, newer_than=None):
    """The replica directory holding a database, found by its module log: the last line's
    microsecond timestamp appears in that replica's log file only (SpacetimeDB 2.14.1 gives no
    API for it). `newer_than` (a `find -newermt` time) limits the search to recent replicas."""
    code, body = http(f"/v1/database/{db}/logs?num_lines=20", token=token)
    ts = None
    for line in reversed(body.strip().splitlines() if code == 200 else []):
        try:
            ts = json.loads(line)["ts"]
            break
        except (ValueError, KeyError):
            continue
    if ts is None:
        return None
    where = f"$(find . -mindepth 1 -maxdepth 1 -type d -newermt '{newer_than}')" if newer_than else "*"
    hit = sh("docker", "exec", CONTAINER, "sh", "-c", f"cd {REPLICAS} && grep -l '\"ts\":{ts},' $(for r in {where}; do echo $r/module_logs/*.log; done) 2>/dev/null", check=False).stdout.split()
    owners = {h.lstrip("./").split("/")[0] for h in hit}
    return next(iter(owners)) if len(owners) == 1 else None


def batch_databases(batch):
    """The databases a batch's runner published, from its own records: {name: {"identity",
    "replica", "instance"}} (state.json, or summary.json's `db` for batches older than these
    records)."""
    out = {}
    for d in sorted((OUT / batch).glob("*/")):
        rec = {}
        for f in ("summary.json", "state.json"):
            try:
                rec.update(json.loads((d / f).read_text()))
            except (OSError, ValueError):
                pass
        db = rec.get("db") or (f"{PREFIX}{batch}-{d.name}" if (d / "state.json").exists() else None)
        if db:
            out[db] = {"identity": rec.get("database_identity"), "replica": rec.get("replica"), "instance": d.name}
    return out


def build(a):
    guard()
    env = dict(os.environ, CARGO_TARGET_DIR=str(TARGET))
    sh("cargo", "build", "--manifest-path", ROOT / "living/Cargo.toml", "-p", "living-mind", "--release", env=env, timeout=3600)
    seeds = {}
    for t in a.trials:
        for w in worlds_of(load_trial(t)).values():
            name, rel, _ = world_seed(w)
            seeds[name] = rel
    for name, rel in seeds.items():
        build_module(name, rel)
    print("built:", TARGET / "release/living-mind", *[OUT / "wasm" / f"{n}.wasm" for n in seeds])


def wasm_mount():
    """The host directory the trial container serves as /wasm (read-only inside it). It is this
    checkout's `OUT/wasm` when this checkout started the container; from another checkout (a git
    worktree) it is the starting checkout's, and modules go there under this checkout's name."""
    r = sh("docker", "inspect", CONTAINER, "--format", '{{range .Mounts}}{{if eq .Destination "/wasm"}}{{.Source}}{{end}}{{end}}', check=False)
    src = r.stdout.strip() if r.returncode == 0 else ""
    return Path(src) if src else OUT / "wasm"


def served_name(name):
    """A module's name under the container's /wasm: as built, or, when the mount is another
    checkout's, with this checkout's tag, so a worktree never overwrites or reuses a module
    another checkout's batches run (`trial-<seed>-<hash>-wt<tag>`)."""
    if wasm_mount().resolve() == (OUT / "wasm").resolve():
        return name
    return f"{name}-wt{hashlib.sha256(str(ROOT).encode()).hexdigest()[:6]}"


def build_module(name, rel):
    # One target dir for every trial world: a seed change rebuilds only the authority crate.
    env = dict(os.environ, CARGO_TARGET_DIR=str(TARGET / "trials-wasm"), LIVING_SEED=rel)
    sh("cargo", "build", "--manifest-path", ROOT / "living/Cargo.toml", "-p", "living-authority",
       "--target", "wasm32-unknown-unknown", "--release", env=env, timeout=3600)
    out = OUT / "wasm" / f"{name}.wasm"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TARGET / "trials-wasm/wasm32-unknown-unknown/release/living_authority.wasm", out)
    os.chmod(out, 0o644)
    served = served_name(name)
    if served != name:
        shutil.copyfile(out, wasm_mount() / f"{served}.wasm")
        os.chmod(wasm_mount() / f"{served}.wasm", 0o644)
        print(f"module {name} served to the container as /wasm/{served}.wasm")


# ---- one trial instance ----------------------------------------------------------------

class Stop(Exception):
    pass


class Player:
    """A scripted human session through the player reducers (`join`, `human_move`, `human_act`,
    `human_say`) with the player's own non-admin identity, as a person at a keyboard would
    play: no admin scene-setting. Every call opens and closes an HTTP connection, which is
    presence; calls stay under `takeover_s` (30 s) apart until the session ends, after which
    the character stands for `takeover_s` and the minds take it over. Each call is recorded
    in `human.jsonl`; the identity's token stays in memory."""

    def __init__(self, inst, name):
        self.inst, self.name = inst, name
        code, body = http("/v1/identity", {})
        if code != 200:
            raise RuntimeError(f"identity: {code} {body[:200]}")
        j = json.loads(body)
        self.token, self.identity = j["token"], j["identity"]

    def call(self, reducer, *args):
        code, body = http(f"/v1/database/{self.inst.db}/call/{reducer}", list(args), self.token)
        self.inst.emit("human", {"t": self.inst.t(), "call": reducer, "args": list(args), "status": code, "error": body.strip()[:200] if code != 200 else ""})
        return code == 200

    def join(self):
        if not self.call("join", self.name):
            raise RuntimeError("player join refused")
        time.sleep(1)
        rows = [c for c in self.inst.rows(f"SELECT * FROM character WHERE name = '{self.name}'") if c["alive"]]
        return max(c["id"] for c in rows)

    @property
    def pid(self):
        """The player's character: the trial's subject, or the newcomer once it joined (`newcomer`)."""
        return getattr(self, "id", None) or self.inst.subject

    def me(self):
        b = self.inst.bodies([self.pid])
        return b.get(self.pid)

    def walk_toward(self, target, seconds):
        """Steer toward a point in 3 s pulses (a held direction key)."""
        end = time.time() + seconds
        while time.time() < end:
            here = self.me()
            if not here:
                return
            dx, dy = target[0] - here[0], target[1] - here[1]
            n = (dx * dx + dy * dy) ** 0.5
            if n < 4:
                break
            self.call("human_move", dx / n, dy / n, False)
            time.sleep(3)
        self.call("human_move", 0.0, 0.0, False)

    def is_mind(self, c):
        """Whether a resident is thought for by the trial's mind service: past infancy, and in its
        `LIVING_ONLY` set when it has one (`thinkers` under `minds.max`, the subject alone for a
        one-mind trial, every person under `minds.only: "all"` without `max`). Infants and
        residents beyond `minds.max` live by their graphs and can never answer."""
        if c.get("stage", 2) == 0:
            return False
        only = self.inst.trial.get("minds", {}).get("only")
        thinkers = getattr(self.inst, "thinkers", None)
        if only == "all":
            return thinkers is None or c["id"] in thinkers
        return c["id"] in self.inst.roles.get("subject", [])

    def residents_near(self, within, minds=False):
        here = self.me()
        people = [c for c in self.inst.rows("SELECT * FROM character WHERE kind = 'person' AND alive = true") if c["id"] not in (self.inst.subject, self.pid) and (not minds or self.is_mind(c))]
        pos = self.inst.bodies([c["id"] for c in people])
        near = sorted(((dist(here, pos[c["id"]]), c) for c in people if c["id"] in pos and here), key=lambda x: x[0])
        return [(d, c) for d, c in near if d <= within]

    def act(self, node):
        return self.call("human_act", json.dumps(node))

    def body(self):
        rows = self.inst.rows(f"SELECT * FROM body WHERE id = {self.pid}")
        return rows[0] if rows else None

    def hold(self, seconds):
        """Stand still for a while, still present: a call at least every 10 s (an idle player
        whose client keeps its connection). From exp-greet. While an answer is due (`answer`
        in the arrival script), it listens every 2 s."""
        end = time.time() + seconds
        while time.time() < end:
            self.call("human_move", 0.0, 0.0, False)
            step_end = min(end, time.time() + 10.0)
            while time.time() < step_end:
                if getattr(self, "answer_due", None):
                    self.listen()
                    time.sleep(min(2.0, max(0.0, step_end - time.time())))
                else:
                    time.sleep(max(0.0, step_end - time.time()))

    def listen(self):
        """The arrival script's one answer: the first line a resident thought for by the minds
        (`is_mind`) addresses to the player (its own `speech` experience with the player as
        `object`) gets `answer_due`, said back to that resident; then the player is silent again. The answer is a `human_answer` event
        with the line it answers."""
        inst = self.inst
        rows = sorted(inst.rows(f"SELECT * FROM experience WHERE observer = {self.pid} AND id > {getattr(self, 'heard_cursor', 0)}"), key=lambda r: r["id"])
        for r in rows:
            self.heard_cursor = max(getattr(self, "heard_cursor", 0), r["id"])
            if r["kind"] == "speech" and r["object"] == self.pid and r["subject"] != self.pid and \
                    any(self.is_mind(c) for c in inst.rows(f"SELECT * FROM character WHERE id = {r['subject']}")):
                text = self.answer_due
                self.answer_due = None
                ok = self.call("human_say", text, r["subject"])
                inst.emit("events", {"t": inst.t(), "human_answer": {"to": r["subject"], "text": text, "ok": ok, "at_ms": inst.now_ms(),
                                                                     "heard": {"id": r["id"], "at_ms": r["at_ms"], "text": r["text"][:300]}}})
                return

    def group(self, avoid=(), minds=False):
        """The densest group of residents: the resident with the most others within 6 m (at
        least two, else the most within 10 m). The greeting trial (`minds` false) counts every
        resident and avoids a group led by one in `avoid` when another will do; the arrival
        trial (`minds`) counts only residents a mind thinks for (a group of graph-run residents
        could never answer) and shares as few members with `avoid` as can be.
        Returns (centre, member ids)."""
        people = [c for c in self.inst.rows("SELECT * FROM character WHERE kind = 'person' AND alive = true") if c["id"] not in (self.inst.subject, self.pid) and (not minds or self.is_mind(c))]
        pos = self.inst.bodies([c["id"] for c in people])
        ids = [c["id"] for c in people if c["id"] in pos]
        best = None
        for r in (6.0, 10.0):
            for i in ids:
                members = [j for j in ids if dist(pos[i], pos[j]) <= r]
                key = (len(members) >= 3, -sum(1 for j in members if j in avoid) if minds else i not in avoid, len(members))
                if best is None or key > best[0]:
                    best = (key, members)
            if best and best[0][0]:
                break
        if not best:
            return None, []
        members = best[1]
        cx = sum(pos[j][0] for j in members) / len(members)
        cy = sum(pos[j][1] for j in members) / len(members)
        return (cx, cy), members

    def approach(self, members=None, seconds=150, within=5.0, minds=False):
        """Walk up to a group as a player would: a `goto` act (a walk along a route, as the
        client's click-to-walk does) to the centre of the densest group (`group`, with `minds`
        and the arrival trial's `avoid`), re-chosen and re-aimed every 15 s while people move,
        until two residents are within `within` m (or, after 90 s, the nearest is within 3 m);
        then a short step toward the group's centre, so that the player faces into it. While an
        answer is due (the arrival trial's `answer`) it listens. Returns the group's members
        when it stopped."""
        start, end, last = time.time(), time.time() + seconds, 0.0
        members = members or []
        while time.time() < end:
            if len(self.residents_near(within, minds=minds)) >= 2:
                break
            if time.time() - start > 90 and self.residents_near(3, minds=minds):
                break
            if time.time() - last >= 15:
                centre, members = self.group(avoid=getattr(self, "avoid", ()), minds=minds)
                if centre:
                    # A point, not a person: `goto` aims only at someone in sight.
                    self.act({"do": "goto", "target": {"at": [round(centre[0], 1), round(centre[1], 1)]}})
                last = time.time()
            if getattr(self, "answer_due", None):
                self.listen()
            time.sleep(2.0)
        here = self.me()
        pos = self.inst.bodies([c["id"] for _, c in self.residents_near(8, minds=minds)])
        if here and pos:
            cx = sum(p[0] for p in pos.values()) / len(pos)
            cy = sum(p[1] for p in pos.values()) / len(pos)
            dx, dy = cx - here[0], cy - here[1]
            n = (dx * dx + dy * dy) ** 0.5 or 1.0
            self.call("human_move", dx / n, dy / n, False)
            time.sleep(0.4)
        self.call("human_move", 0.0, 0.0, False)
        return members

    def arrive_session(self, spec):
        """The arrival trial (docs/TRIALS.md, "Arrivals"): a newcomer who says and does nothing.
        After `settle_s` at the arrival point, walk (`goto`) to the densest group of residents
        until two are within `within_m`, stand there silent for `stand_s`; then walk to the
        group that shares fewest members with the first and stand silent `stand_s` more; then
        stay where it is to the end of the run. It never speaks, gestures or acts toward anyone,
        and its name is never said, so it stays a stranger. With `answer`, it says that one line
        back to the first resident who addresses it (`listen`), then is silent again. Each stand is a `human_stand` event
        (from/to ms, who was within 12 m at its start) for arrive_report.py."""
        inst, end = self.inst, time.time() + spec.get("minutes", 14) * 60
        stands = spec.get("stands", 2)
        # `answer`: the one line said back to the first resident who addresses the player.
        self.answer_due = spec.get("answer")
        try:
            self.hold(spec.get("settle_s", 20))
            self.avoid = ()
            for k in range(stands):
                inst.emit("events", {"t": inst.t(), "human_walk": {"stand": k, "from_ms": inst.now_ms()}})
                members = self.approach(seconds=spec.get("walk_s", 150), within=spec.get("within_m", 5.0), minds=True)
                near = [(round(d, 1), c["id"], c["name"]) for d, c in self.residents_near(12)]
                start = inst.now_ms()
                inst.emit("events", {"t": inst.t(), "human_stand": {"stand": k, "from_ms": start, "s": spec.get("stand_s", 300), "group": members, "near": near, "at": [round(x, 1) for x in (self.me() or (0, 0))]}})
                self.hold(min(spec.get("stand_s", 300), max(0, end - time.time() - 5)))
                inst.emit("events", {"t": inst.t(), "human_stand_end": {"stand": k, "to_ms": inst.now_ms()}})
                self.avoid = tuple(members) + tuple(i for _, i, _ in near)
            self.hold(max(0, end - time.time()))
        except Exception as e:  # recorded, never raised into the run
            inst.emit("events", {"t": inst.t(), "human_error": repr(e)[:300]})
        inst.emit("events", {"t": inst.t(), "human_left": True, "takeover_due_s": 30})

    def line(self, kind, text, to, cycle):
        """Say a line, recording who stood within earshot (12 m) and how far (`human_line`)."""
        near = [(round(d, 1), c["id"], c["name"]) for d, c in self.residents_near(12)]
        b = self.body()
        ok = self.call("human_say", text, to)
        self.inst.emit("events", {"t": self.inst.t(), "human_line": {"kind": kind, "text": text, "to": to, "cycle": cycle, "ok": ok, "at_ms": self.inst.now_ms(),
                                  "near": near, "heading": b and b.get("heading")}})

    def greet_session(self, spec):
        """The greeting trial (docs/TRIALS.md, "The greeting trial"): for `minutes`, in cycles,
        walk into a group of residents, (1) say a greeting to no one in particular, (2) 50 s
        later say a line addressed (`to`) to the nearest resident within earshot, as the game
        client does when no one is under the cursor, (3) then stand among them for
        `listen_s` saying nothing, while they talk among themselves; then the next group. The
        lines name nobody and the player never says its own name, so it stays a stranger to
        those it has not met."""
        inst, end = self.inst, time.time() + spec.get("minutes", 25) * 60
        greetings = spec.get("greetings", ["Hello there!", "Good day to you all.", "Hello, everyone. I've only just come down the road."])
        addressed = spec.get("addressed", ["Is there somewhere a traveller could get a bite to eat around here?", "You look like you know this place well.",
                                           "What do people here do for work?", "That looks like hard work."])
        wait_s, listen_s = spec.get("wait_s", 50), spec.get("listen_s", 150)
        led = []
        try:
            cycle = 0
            while time.time() < end - 60:
                centre, members = self.group(avoid=led[-1:])
                if not members:
                    self.hold(10)
                    continue
                led.append(members[0])
                inst.emit("events", {"t": inst.t(), "human_group": {"cycle": cycle, "members": members, "centre": [round(x, 1) for x in centre]}})
                self.approach(members)
                self.line("unaddressed", greetings[cycle % len(greetings)], 0, cycle)
                self.hold(wait_s)
                # As the game client addresses a line with nothing under the cursor (talk-1): to
                # the nearest person within earshot (`earshot_m`; Cullet's speech carries 12 m).
                near = self.residents_near(spec.get("earshot_m", 12))
                if near:
                    self.line("addressed", addressed[cycle % len(addressed)], near[0][1]["id"], cycle)
                self.hold(wait_s)
                inst.emit("events", {"t": inst.t(), "human_listen": {"cycle": cycle, "from_ms": inst.now_ms(), "s": listen_s}})
                self.hold(min(listen_s, max(0, end - time.time() - 5)))
                inst.emit("events", {"t": inst.t(), "human_listen_end": {"cycle": cycle, "to_ms": inst.now_ms()}})
                cycle += 1
            # Stay present to the end of the run: no takeover inside it.
            self.hold(max(0, end - time.time()))
        except Exception as e:  # recorded, never raised into the run
            inst.emit("events", {"t": inst.t(), "human_error": repr(e)[:300]})
        inst.emit("events", {"t": inst.t(), "human_left": True, "takeover_due_s": 30})

    def join_newcomer(self, spec):
        """A newcomer who joins later (`newcomer`: `name`, and `at_hour`, the world hour it joins
        at, or `after_s`): the world and its minds live first, so the residents have seen each
        other and may have written routines; the newcomer is the one first seen later
        (docs/STRANGERS.md). The join is a `newcomer_join` event, and the newcomer a cast role."""
        inst = self.inst
        while not inst.stopped_by:
            hour = hour_of(inst.now_ms(), inst.rows("SELECT * FROM world")[0])
            if ("at_hour" in spec and hour >= spec["at_hour"]) or ("at_hour" not in spec and inst.t() >= spec.get("after_s", 0)):
                break
            time.sleep(2)
        self.id = self.join()
        inst.roles.setdefault("newcomer", []).append(self.id)
        here = self.me()
        land = getattr(inst, "land", None) or {}
        inst.emit("events", {"t": inst.t(), "newcomer_join": {"id": self.id, "name": self.name, "at_ms": inst.now_ms(), "hour": round(hour_of(inst.now_ms(), inst.rows("SELECT * FROM world")[0]), 2),
                                                              "at": [round(x, 1) for x in here] if here else None,
                                                              "arrival_point": [land.get("arrive_x"), land.get("arrive_y")] if land else None}})
        inst.note_role("newcomer", self.id)
        inst.log(f"newcomer {self.name}#{self.id} joined at {here}")
        return self.id

    def approach_group(self, seconds=150, within=5.0, avoid=()):
        """Walk to the densest group of residents thought for by the minds (`group`, re-chosen
        and re-aimed every 15 s, a `goto` to a point as the client's click-to-walk does) until two
        of them are within `within` m (or, after 90 s, one within 3 m); then a short step toward
        them, so that the player faces into the group (from exp-arrive). Returns its members."""
        start, end, last = time.time(), time.time() + seconds, 0.0
        members = []
        while time.time() < end:
            if len(self.residents_near(within, minds=True)) >= 2:
                break
            if time.time() - start > 90 and self.residents_near(3, minds=True):
                break
            if time.time() - last >= 15:
                centre, members = self.group(avoid=avoid, minds=True)
                if centre:
                    self.act({"do": "goto", "target": {"at": [round(centre[0], 1), round(centre[1], 1)]}})
                last = time.time()
            time.sleep(2.0)
        here = self.me()
        pos = self.inst.bodies([c["id"] for _, c in self.residents_near(8)])
        if here and pos:
            cx = sum(p[0] for p in pos.values()) / len(pos)
            cy = sum(p[1] for p in pos.values()) / len(pos)
            dx, dy = cx - here[0], cy - here[1]
            n = (dx * dx + dy * dy) ** 0.5 or 1.0
            self.call("human_move", dx / n, dy / n, False)
            time.sleep(0.4)
        self.call("human_move", 0.0, 0.0, False)
        return members

    def walk_route(self, points, name, per_point_s=45):
        """Walk through `points` (world metres) in turn, a `goto` to each as the client's
        click-to-walk sends it, on to the next once within 3 m or after `per_point_s`; silent. A
        `human_route` event marks the start and the end, with where the player was."""
        inst = self.inst
        inst.emit("events", {"t": inst.t(), "human_route": {"name": name, "from_ms": inst.now_ms(), "points": points, "at": [round(x, 1) for x in (self.me() or (0, 0))]}})
        for p in points:
            self.act({"do": "goto", "target": {"at": [round(p[0], 1), round(p[1], 1)]}})
            end = time.time() + per_point_s
            while time.time() < end:
                here = self.me()
                if here and dist(here, p) <= 3.0:
                    break
                time.sleep(2.0)
        self.call("human_move", 0.0, 0.0, False)
        inst.emit("events", {"t": inst.t(), "human_route_end": {"name": name, "to_ms": inst.now_ms(), "at": [round(x, 1) for x in (self.me() or (0, 0))]}})

    def stands_session(self, spec):
        """The strangers trial (docs/STRANGERS.md section 6; `script: arrive` with `stands` a list): a newcomer
        who says and does nothing. It joins (`newcomer`) at the arrival point, then stands
        silent at each of `stands` in turn: `{"at": "arrival", "s": 300}` where it is (the arrival
        point, as at a gate), `{"at": "group", "s": 300}` after walking to the densest group of
        residents (`approach_group`); an entry `{"walk": [[x, y], ...], "name": ...}` walks through
        the town instead (`walk_route`, stage 2b: along the Strand past the Fish Steps). Then it stays where it is to the end of the run. It never
        speaks, gestures or names itself, so it stays a stranger. Each stand is a `human_stand`
        event (from/to ms, who was within 12 m at its start) for arrive_report.py; `human_walk`
        marks the arrival (its join) and each walk."""
        inst, end = self.inst, time.time() + spec.get("minutes", 20) * 60
        try:
            if inst.trial.get("newcomer"):
                self.join_newcomer(inst.trial["newcomer"])
            avoid = ()
            for k, st in enumerate(spec.get("stands") or []):
                if st.get("walk"):
                    # A walk through the town, as a player clicks along a street: no stand.
                    self.walk_route(st["walk"], st.get("name", "a walk"), per_point_s=st.get("per_point_s", 45))
                    continue
                inst.emit("events", {"t": inst.t(), "human_walk": {"stand": k, "from_ms": inst.now_ms(), "to": st.get("at")}})
                members = self.approach_group(seconds=spec.get("walk_s", 150), within=spec.get("within_m", 5.0), avoid=avoid) if st.get("at") == "group" else []
                near = [(round(d, 1), c["id"], c["name"]) for d, c in self.residents_near(12)]
                inst.emit("events", {"t": inst.t(), "human_stand": {"stand": k, "at_kind": st.get("at"), "from_ms": inst.now_ms(), "s": st.get("s", 300), "group": members, "near": near,
                                                                    "at": [round(x, 1) for x in (self.me() or (0, 0))]}})
                self.hold(min(st.get("s", 300), max(0, end - time.time() - 5)))
                inst.emit("events", {"t": inst.t(), "human_stand_end": {"stand": k, "to_ms": inst.now_ms()}})
                avoid = tuple(members) + tuple(i for _, i, _ in near)
            self.hold(max(0, end - time.time()))
        except Exception as e:  # recorded, never raised into the run
            inst.emit("events", {"t": inst.t(), "human_error": repr(e)[:300]})
        inst.emit("events", {"t": inst.t(), "human_left": True, "takeover_due_s": 30})

    def session(self, spec):
        """About `minutes` of play: walk to the town, forage, meet people and tell them a plan,
        make a camp by the gate, then leave (stop calling). `script: greet` plays the greeting
        trial instead (`greet_session`), `script: arrive` the arrival trial (`arrive_session`, or
        `stands_session` when `stands` lists the stands)."""
        if spec.get("script") == "greet":
            return self.greet_session(spec)
        if spec.get("script") == "arrive":
            return self.stands_session(spec) if isinstance(spec.get("stands"), list) else self.arrive_session(spec)
        inst, end = self.inst, time.time() + spec.get("minutes", 20) * 60
        try:
            centre = inst.anchor({"town": spec.get("town", "Brackenford")})
            self.call("human_say", "Hello? I'm " + self.name + ", just off the road.", 0)
            self.walk_toward(centre, 150)
            met = []
            while time.time() < end:
                phase = (time.time() - (end - spec.get("minutes", 20) * 60)) / 60
                if phase < 9:
                    self.act({"do": {"skill": "gather", "target": {"nearest": "berry_bush"}}})
                    time.sleep(12)
                    self.act({"do": {"skill": "eat", "item": "berries"}})
                    time.sleep(6)
                elif phase < 14:
                    near = [(d, c) for d, c in self.residents_near(20) if c["id"] not in met]
                    if near:
                        d, c = near[0]
                        self.walk_toward(inst.bodies([c["id"]]).get(c["id"], centre), 20)
                        self.call("human_say", f"Good day, {c['name']}. I'm {self.name}. I mean to make my camp by the gate and gather berries to trade.", c["id"])
                        self.act({"do": "wave", "target": {"id": c["id"]}})
                        met.append(c["id"])
                        inst.emit("events", {"t": inst.t(), "human_met": c["id"], "name": c["name"]})
                    time.sleep(10)
                elif phase < 18:
                    self.act({"do": {"skill": "gather", "target": {"nearest": "tree"}}})
                    time.sleep(14)
                else:
                    if not getattr(self, "built", False):
                        self.built = self.act({"do": {"skill": "build", "item": "campfire"}})
                        time.sleep(8)
                        self.call("human_say", "This fire is my camp now. I'll be back by it at dusk.", 0)
                    time.sleep(10)
        except Exception as e:  # recorded, never raised into the run
            inst.emit("events", {"t": inst.t(), "human_error": repr(e)[:300]})
        inst.emit("events", {"t": inst.t(), "human_left": True, "takeover_due_s": 30})


def proc_start(pid):
    """A process's start time from /proc, to tell it from a later process reusing its pid."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


class Mind:
    """A living-mind process: started by this runner (`popen`) or adopted after a runner restart."""

    def __init__(self, pid, popen=None):
        self.pid, self.popen = pid, popen

    def alive(self):
        if self.popen:
            return self.popen.poll() is None
        try:
            os.kill(self.pid, 0)
        except OSError:
            return False
        return proc_start(self.pid) is not None and "zombie" not in Path(f"/proc/{self.pid}/status").read_text().lower()

    def exit_code(self):
        return self.popen.poll() if self.popen else None

    def stop(self):
        try:
            os.killpg(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        for _ in range(50):
            if not self.alive():
                return
            time.sleep(0.2)
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def out_of_capacity(error):
    """A provider's 429 that says it has no capacity for the model (Mistral: "Not enough
    capacity available", `backend_out_of_capacity`, code 3505). The mind sends listed memory
    work to the overflow and retries a failed consolidation later (llm.rs `capacity_overflow`,
    mind.rs `retry_after`)."""
    return bool(error) and "429" in error and ("Not enough capacity" in error or "out_of_capacity" in error)


def failure_kind(error):
    """What a journaled call's error says about who failed: None (it succeeded), a provider
    kind (`capacity_429`, `rate_429`, `http_5xx`, `connection`: the provider out of capacity,
    limiting the rate, failing or unreachable; the mind falls back, retries or holds its calls)
    or `mind` (anything else: a request the provider refused, a missing key, a reply that was
    not JSON; the same act failing again and again is a runaway)."""
    if not error:
        return None
    if out_of_capacity(error):
        return "capacity_429"
    if error.startswith("HTTP 429"):
        return "rate_429"
    if re.match(r"HTTP 5\d\d", error):
        return "http_5xx"
    # llm.rs `chat_once`: the request could not be sent or answered (connect, timeout), or
    # its body was cut off or was not the provider's JSON envelope.
    if error.startswith(("request", "body", "response json")):
        return "connection"
    return "mind"


CONSOLIDATION_COLUMNS = ("attempted", "primary", "fallback", "retried", "lost", "trimmed", "capacity_429")


def consolidation_table(jdir):
    """What each character's consolidations came to, from the mind's outcome lines
    (`<journal>/outcomes/consolidations.jsonl`, one per consolidation that called a model,
    failed or found experiences lost): attempted; integrated on the primary model or on the
    fallback (its overflow); failed and retried later; failed with no later attempt (lost: its
    experiences were never integrated before the run stopped); experiences of failed ones that
    left the inbox before they were integrated (trimmed: the authority keeps a character's last
    400); failures that were a capacity 429. None when the mind wrote no outcomes (before
    2026-11-11)."""
    path = Path(jdir) / "outcomes" / "consolidations.jsonl"
    if not path.exists():
        return None
    lines = []
    for line in path.read_text().splitlines():
        try:
            lines.append(json.loads(line))
        except ValueError:
            pass
    by = {}
    for name in dict.fromkeys(r.get("actor") for r in lines):
        mine = sorted((r for r in lines if r.get("actor") == name), key=lambda r: r.get("at_ms") or 0)
        tried = [r for r in mine if r.get("model_call") or r.get("outcome") == "failed"]
        row = dict.fromkeys(CONSOLIDATION_COLUMNS, 0)
        row["attempted"] = len(tried)
        for i, r in enumerate(tried):
            if r.get("outcome") == "integrated":
                row["fallback" if r.get("route") == "fallback" else "primary"] += 1
            else:
                row["retried" if i + 1 < len(tried) else "lost"] += 1
                row["capacity_429"] += 1 if out_of_capacity(r.get("failure")) else 0
        row["trimmed"] = sum(r.get("trimmed") or 0 for r in mine)
        by[name] = row
    total = {k: sum(r[k] for r in by.values()) for k in CONSOLIDATION_COLUMNS}
    return {"total": total, "by_character": by}


# A provider is down for every route when no call has succeeded for this long while calls are
# still failing on it (the last within OUTAGE_LIVE_S): only then does an outage stop a run.
OUTAGE_STOP_S = 600
OUTAGE_LIVE_S = 180
# Provider failures with no success on any route for this long are recorded as an outage; a
# shorter gap (a capacity 429 the fallback answers a second later) is counted, not recorded.
OUTAGE_RECORD_S = 30


class Instance:
    def __init__(self, batch, trial, variant, rep, opts, shared):
        self.trial, self.variant, self.rep, self.opts, self.shared = trial, variant, rep, opts, shared
        self.name = f"{trial['name']}-{variant}-r{rep}"
        self.db = f"{PREFIX}{batch}-{self.name}"
        self.dir = OUT / batch / self.name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.journal = ROOT / ".local/living/journal" / self.db
        self.roles, self.saved_graphs, self.mind, self.t0 = {}, {}, None, None
        self.cursor = {"thought": 0, "experience": 0, "chronicle": 0, "talk": 0, "audience": 0, "all_experience": 0, "gesture": 0, "all_thought": 0}
        self.jpos = {}
        self.tokens = Counter()
        self.calls = Counter()
        self.latency = defaultdict(list)
        self.pending = []
        self.fired = Counter()
        self.held = {}  # a `near … beyond … for_s` trigger: since when its condition has held
        self.status = "starting"
        self.stopped_by = None
        self.last_rows = {}
        self.brain_rev = None
        self.kinds = {}
        self.recent = []
        self.starts = []
        self.done_at = set()
        self.died = None
        self.snapshots = 0
        self.runaway_seen = []
        self.provider_fails = []
        self.last_ok = None
        self.outage_since = None
        self.outages = []
        self.published = False

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
        wasm = self.shared["wasm"][world_key(self.trial, self.rep)]
        # A variant may run a module built from another branch (an iteration's engine change):
        # the same world seed, built there and copied in as <module>-<wasm_tag>.wasm.
        tag = self.shared["variants"][self.variant].get("wasm_tag")
        if tag:
            wasm = f"{wasm}-{tag}"
        wasm = served_name(wasm)
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 5))
        sh("docker", "exec", CONTAINER, "spacetime", "publish", "-s", "local", "-b", f"/wasm/{wasm}.wasm", self.db, "--delete-data", "-y", timeout=300)
        self.published = True
        # Which database and which replica directory this run wrote: deleting a database leaves
        # its replica on disk (SpacetimeDB 2.14.1, docs/STORE.md), so the record is what tells a
        # run's commitlog apart from scratch later. The container's clock is UTC.
        self.database_identity = database_identity(self.db)
        try:
            self.replica = replica_of(self.db, self.shared["token"], newer_than=started)
        except Exception as e:  # noqa: BLE001 - a missing record never stops a run
            self.replica = None
            self.log(f"replica not recorded: {e}")
        self.log(f"database {self.db}: identity {self.database_identity}, replica {self.replica}")
        self.save()
        variant = self.shared["variants"][self.variant]
        # A variant may name another skills file (a rules change under test); the default is the tree's.
        skills = ROOT / variant.get("skills", "living/scripts/skills.rhai")
        # The trial's and then the variant's `skills_patch` change law values in that file
        # (name -> [old text, new text]; each old text must occur exactly once).
        # A seed's own laws (`laws`/`laws_file`, docs/CULLET_RULES.md) are composed over it first, as
        # the authority did at creation: installing the bare file would drop them.
        seed = world_seed(worlds_of(self.trial)[world_key(self.trial, self.rep)])[2]
        overlay = seed_laws(seed)
        base = compose_laws(skills.read_text(), overlay) if overlay else skills.read_text()
        # What the world was created with: its laws over the tree's skills.rhai, which the module
        # compiled in. A module built on another branch (`wasm_tag`) compiled that branch's.
        tree = (ROOT / "living/scripts/skills.rhai").read_text()
        built = None if tag else (compose_laws(tree, overlay) if overlay else tree)
        script_row = lambda: next(iter(self.rows("SELECT * FROM script WHERE name = 'skills'")), {}).get("source")
        creation = script_row()
        if variant.get("keep_laws"):
            # The world keeps the script it was created with (its seed's laws), uninstalled.
            if variant.get("skills") or variant.get("skills_patch") or self.trial.get("skills_patch"):
                raise RuntimeError("a keep_laws variant installs nothing, so it takes no `skills` or `skills_patch`")
            source, patched, readback = None, [], creation
        else:
            source, patched = patch_skills(base, self.trial, variant)
            if overlay:
                patched = ["seed laws"] + patched
            code, body = http(f"/v1/database/{self.db}/call/install_script", [source], self.shared["token"])
            if code != 200:
                raise RuntimeError(f"install_script {code}: {body[:300]}")
            readback = script_row()
        day_ms = (next(iter(self.rows("SELECT day_ms FROM world")), {}) or {}).get("day_ms")
        problems = laws_problems(seed, overlay, built, creation, source, readback, day_ms)
        # The instance does not start (no mind, no timeline) on a world whose laws are not its seed's.
        for why in problems:
            self.log(f"laws guard: {why}")
            self.emit("events", {"t": self.t(), "error": f"laws guard: {why}"})
        if problems:
            raise RuntimeError("laws guard: " + "; ".join(problems))
        ran = source if source is not None else readback
        (self.dir / "skills.sha256").write_text(hashlib.sha256(ran.encode()).hexdigest() + "\n")
        # A variant's world laws (`world_laws`, name -> value), set as an admin sets them on a live
        # world (`set_world_law`), after the laws guard; read back from `world_law`.
        wl = variant.get("world_laws") or {}
        for name, value in wl.items():
            code, body = http(f"/v1/database/{self.db}/call/set_world_law", [name, json.dumps(value)], self.shared["token"])
            if code != 200:
                raise RuntimeError(f"set_world_law {name} {value}: {code} {body[:300]}")
        if wl:
            got = {r["name"]: json.loads(r["value"]) for r in self.rows("SELECT * FROM world_law")}
            if any(got.get(k) != v for k, v in wl.items()):
                raise RuntimeError(f"world laws not in force: wanted {wl}, world_law has {got}")
            (self.dir / "world_laws.json").write_text(json.dumps(got, indent=1))
            self.log(f"world laws set (set_world_law): {wl}; world_law now {got}")
        self.log(f"laws guard passed: the `script` row read back is the {'source sent' if source is not None else 'creation-time script, kept'}"
                 f"{'; the seed laws are composed as the world composed them' + (' (overlay found; module from ' + tag + ')' if built is None else '') + f'; day_ms {day_ms}' if overlay else ''}")
        how = "kept the world's own laws (keep_laws, no install)" if source is None else f"skills installed from {skills.relative_to(ROOT)}"
        self.log(f"published {self.db} from {wasm}.wasm; {how}"
                 f"{' patched ' + ','.join(patched) if patched else ''} (sha256 {hashlib.sha256(ran.encode()).hexdigest()[:12]})")
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
            kinds = spec.get("kinds") or [spec.get("kind", "person")]
            if c["id"] in taken or c["kind"] not in kinds:
                continue
            if spec.get("mindable", True) and not (c["ai"] and c["controller"] == admin):
                continue
            if "stage" in spec and c["stage"] != spec["stage"]:
                continue
            if "name" in spec and c["name"] != spec["name"]:
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
        elif spec.get("youngest"):
            # Seeded characters share a birth time, so the youngest has the fewest days at birth.
            out.sort(key=lambda c: (c["birth_age_days"], c["id"]))
        n = len(out) if spec.get("count") == "all" else spec.get("count", 1)
        if len(out) < n:
            raise RuntimeError(f"pick {spec}: only {len(out)} match")
        return [c["id"] for c in out[:n]]

    def cast(self):
        self.census_cache = self.census()
        taken = set()
        if "subject" not in self.roles:
            # A subject may be several characters (a wolf pack): the mind thinks for all of
            # them (LIVING_ONLY); samples and probes follow the first.
            self.roles["subject"] = self.pick(self.trial["subject"]["pick"], taken)
        taken |= set(self.roles["subject"])
        for role, spec in self.trial.get("cast", {}).items():
            self.roles[role] = self.pick(spec["pick"], taken)
            taken |= set(self.roles[role])
        self.subject = self.roles["subject"][0]
        chars = {c["id"]: c for c in self.census_cache[0]}
        if self.subject not in chars:
            chars[self.subject] = self.rows(f"SELECT * FROM character WHERE id = {self.subject}")[0]
        genome = self.rows(f"SELECT * FROM genome WHERE id = {self.subject}")
        self.cast_info = {r: [{"id": i, "name": chars[i]["name"], "kind": chars[i]["kind"], "background": self.census_cache[1].get(i, {})} for i in ids] for r, ids in self.roles.items()}
        (self.dir / "cast.json").write_text(json.dumps({"roles": self.cast_info, "subject_genome": genome}, indent=1))
        self.log("cast: " + ", ".join(f"{r}={[chars[i]['name'] + '#' + str(i) for i in ids]}" for r, ids in self.roles.items()))

    def note_role(self, role, cid):
        """Add a character who came later (a newcomer who joined) to cast.json's roles."""
        path = self.dir / "cast.json"
        cast = json.loads(path.read_text()) if path.exists() else {"roles": {}}
        row = next(iter(self.rows(f"SELECT * FROM character WHERE id = {cid}")), {})
        cast["roles"].setdefault(role, []).append({"id": cid, "name": row.get("name"), "kind": row.get("kind")})
        path.write_text(json.dumps(cast, indent=1))
        self.save()

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
            pos = self.bodies(self.roles[a["who"]])
            if not pos:
                raise RuntimeError(f"role {a['who']} has no living member")
            p = next(iter(pos.values()))
        elif "structure" in a:
            near = self.anchor(a["near"])
            st = self.rows(f"SELECT * FROM structure WHERE kind = '{a['structure']}'")
            if "owner" in a:
                owner = self.ids(a["owner"])[0] if isinstance(a["owner"], str) else a["owner"]
                st = [x for x in st if x["owner"] == owner]
            s = min(st, key=lambda s: dist((s["x"], s["y"]), near))
            p = (s["x"], s["y"])
        elif "home_of" in a:
            c = self.rows(f"SELECT * FROM character WHERE id = {self.roles[a['home_of']][0]}")[0]
            p = (c["home_x"], c["home_y"])
        elif "farthest_town" in a:
            # The centre of the settlement farthest from another anchor: always walkable ground
            # (a map corner can be sea), used to clear an arena of animals (docs/PACK_MIND.md).
            ref = self.anchor(a["farthest_town"])
            groups = self.census_cache[-1]
            p = max((self.anchor({"town": g}) for g in groups), key=lambda c: dist(c, ref))
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
        if "spread" in a:
            # Each member at its own offset from the point (a formation: docs/PACK_MIND.md, the
            # arena's starts), in order; past the list's end, the last offsets again.
            sx, sy = a["spread"][min(member, len(a["spread"]) - 1)]
            p = (p[0] + dx + sx, p[1] + dy + sy)
        else:
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
            pa, pb = self.bodies(self.ids(m.group(1))), self.bodies(self.ids(m.group(2)))
            (ax, ay), (bx, by) = next(iter(pa.values())), next(iter(pb.values()))
            n = max(1e-6, ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5)
            d = float(m.group(3))
            return [round(ax + (bx - ax) / n * d, 1), round(ay + (by - ay) / n * d, 1)]
        m = re.fullmatch(r"\$(\w+)_xy(?:\+(-?[\d.]+),(-?[\d.]+))?", v) if isinstance(v, str) else None
        if m:
            # "$subject_xy+9,0": where that role stands now, plus an offset in tiles.
            pos = self.bodies(self.ids(m.group(1)))
            x, y = next(iter(pos.values()))
            dx, dy = float(m.group(2) or 0), float(m.group(3) or 0)
            return [round(x + dx, 1), round(y + dy, 1)]
        if isinstance(v, str) and v.startswith("$"):
            ids = self.ids(v)
            return {"id": ids[0]} if ids else v
        if isinstance(v, dict):
            if list(v) == ["id"] and isinstance(v["id"], str) and v["id"].startswith("$"):
                return {"id": self.ids(v["id"])[0]}  # a graph target written {"id": "$role"}
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
        if who and kind in ("place", "graph", "say", "act", "items", "know", "structure"):
            # Members who died (or were removed) since the cast was picked are skipped, and said so.
            have = set(self.bodies(who))
            gone = [x for x in who if x not in have]
            if gone:
                self.emit("events", {"t": self.t(), "skipped": gone, "do": kind, "why": "no living body"})
                who = [x for x in who if x in have]
                if not who:
                    return
        for i, actor in enumerate(who or [None]):
            if kind == "place":
                x, y = self.anchor(s["to"], i)
                self.call("place_at", actor, x, y)
            elif kind == "graph":
                if actor not in self.saved_graphs:
                    b = self.rows(f"SELECT * FROM brain WHERE id = {actor}")
                    if b:
                        self.saved_graphs[actor] = json.loads(b[0]["graph"])
                # `graphs`: one graph per member, in order (cycling), for fixtures whose members
                # differ (docs/PACK_MIND.md §5.6, the calibration "sides").
                g = s["graphs"][i % len(s["graphs"])] if "graphs" in s else s["graph"]
                self.call("set_behavior", actor, json.dumps(self.graph_of(g, actor)))
            elif kind == "items":
                for item, qty in s["items"].items():
                    self.call("grant_items", actor, item, qty)
            elif kind == "know":
                for t in s["techniques"]:
                    self.call("grant_know_how", actor, t)
            elif kind == "say":
                to = self.ids(s.get("to"))[0] if s.get("to") else 0
                self.call("mind_say", actor, s["text"], to, s.get("way", ""), 0, {"kind": "trial", "summary": f"scripted line (trial fixture): {s['text'][:200]}",
                          "detail": "", "latency_ms": 0, "tokens": 0, "model": "", "reference": f"trial:{self.trial['name']}"})
            elif kind == "act":
                acts = s["acts"] if "acts" in s else [s["act"]]
                self.call("mind_act", actor, [json.dumps(self.subst(x)) for x in acts], "trial")
            elif kind == "structure":
                self.call("place_structure", actor, s["kind"])
            elif kind == "background":
                # Compact, as the seed writes it: the authority reads a pack's `"bold":true` from
                # the text itself (act.rs), so `"bold": true` would never take effect.
                self.call("set_background", actor, json.dumps(s["background"], separators=(",", ":")))
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
                    time.sleep(s.get("after", 0))
                    self.step(s)
                    time.sleep(0.3)

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
                n = w["near"]
                a = self.ids(n.get("who", "subject"))
                if "to" in n:
                    spot = self.anchor(n["to"])
                    ds = [dist(positions[x], spot) for x in a if x in positions]
                else:
                    b = self.ids(n["of"])
                    ds = [dist(positions[x], positions[y]) for x in a for y in b if x in positions and y in positions]
                # `within`: fires when any is that close; `beyond`: when all are farther than that
                # (both placed), and with `for_s` only once it has held that long (then the clock
                # starts again).
                hit = bool(ds) and (all(d > n["beyond"] for d in ds) if "beyond" in n else any(d <= n["within"] for d in ds))
                if hit and n.get("for_s"):
                    since = self.held.setdefault(k, self.t())
                    hit = self.t() - since >= n["for_s"]
                    if hit:
                        self.held.pop(k, None)
                elif not hit:
                    self.held.pop(k, None)
                if hit:
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
        # A variant names a whole models file (`models_file`) or patches the repository's.
        base = ROOT / v.get("models_file", "living/configs/models.json")
        m = json.loads(base.read_text())
        # People think with the variant's default profile: no groups, assignments, rotation
        # or stage profiles. `species` routing (animals' think/remember/compile) is kept.
        m = deep_merge({**m, "assign": {}, "rotate": [], "groups": {}, "stages": {}}, v.get("models", {}))
        if self.opts.fake:
            # Same routing, every profile answered by the local fake server under the name
            # `fake-<model>`, so the journal shows which profile each call was routed to.
            port = self.shared["fake_port"]
            m["profiles"] = {name: {"base_url": f"http://127.0.0.1:{port}/v1", "model": f"fake-{p['model']}", "key_env": "LIVING_VERIFY_FAKE_KEY",
                                    "max_tokens": 512, "requests_per_minute": 6000, **{k: p[k] for k in ("overflow", "capacity_overflow") if p.get(k)}}
                             for name, p in m["profiles"].items()}
        return m

    def start_mind(self, planned=False):
        v = self.shared["variants"][self.variant]
        if v.get("mind") is False:
            # Instinct-only control: no mind service; the subject lives on its graph.
            self.mind = None
            self.log(f"no mind (variant {self.variant}): the subject lives on its instinct graph")
            self.save()
            return
        path = self.dir / "models.json"
        path.write_text(json.dumps(self.models(), indent=1))
        budget = self.trial.get("budget", {})
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=URL, LIVING_DB=self.db, LIVING_RUN=self.db,
                   LIVING_SEED=self.shared["seed_rel"][world_key(self.trial, self.rep)], LIVING_MODELS=str(path),
                   LIVING_ONLY=",".join(map(str, self.roles["subject"])),
                   LIVING_TOKEN=self.shared["token"],
                   LIVING_NEO4J_URI=f"127.0.0.1:{NEO4J_PORT}", LIVING_NEO4J_PASSWORD=self.shared["neo4j_pw"],
                   # Off (0) unless a trial asks for a rate: trials measure, they do not cap.
                   LIVING_LLM_PER_MIN=str(budget.get("calls_per_min", 0)), LIVING_CONCURRENCY=str(mind_concurrency(self.trial)),
                   LIVING_VERIFY_FAKE_KEY="dummy-local-only", NO_PROXY="127.0.0.1,localhost",
                   RUST_LOG="info,neo4rs=warn,spacetimedb_sdk=warn")
        # `minds.only: "all"`: the service thinks for every person and animal (no LIVING_ONLY);
        # with `minds.max` for at most that many at a time (`thinkers`, kept by `slots`).
        # `minds.roles`: the service thinks for every member of these roles (an arena where both
        # sides have minds: docs/PACK_MIND.md), not the subject alone.
        if self.trial.get("minds", {}).get("roles"):
            env["LIVING_ONLY"] = ",".join(str(i) for r in self.trial["minds"]["roles"] for i in self.roles.get(r, []))
        if self.trial.get("minds", {}).get("only") == "all":
            env.pop("LIVING_ONLY")
            if self.trial["minds"].get("max"):
                self.thinkers, self.capped = self.slots()
                if self.capped:
                    env["LIVING_ONLY"] = ",".join(map(str, self.thinkers))
        if self.opts.fake:
            # A fake run must never reach a provider: no provider keys in its environment.
            for k in ("MISTRAL_API_KEY", "CARLID_NPC_API_KEY", "TYPESAFE_API_KEY"):
                env[k] = ""
        env.update({k: str(x) for k, x in v.get("env", {}).items()})
        if self.opts.fake and env.get("LIVING_RETHINK") == "jev":
            # The gate's Jev judge goes to the fake server's `/v1/systemone` too (fake_llm.py), never to TypeSafe.
            env["LIVING_RETHINK_URL"] = f"http://127.0.0.1:{self.shared['fake_port']}/v1/systemone"
            env["TYPESAFE_API_KEY"] = "fake-only"
        self.concurrency = int(env["LIVING_CONCURRENCY"])
        (self.dir / "mind-env.json").write_text(json.dumps({k: env[k] for k in sorted(env) if k.startswith("LIVING_") and k not in ("LIVING_TOKEN", "LIVING_NEO4J_PASSWORD")}, indent=1))
        log = open(self.dir / "mind.log", "a")
        # A variant may run a mind built from another branch (an iteration's mind change): `mind_bin`,
        # a path under the repository or absolute; the default is this tree's build.
        binary = Path(os.path.expanduser(v["mind_bin"])) if v.get("mind_bin") else TARGET / "release/living-mind"
        binary = binary if binary.is_absolute() else ROOT / binary
        p = subprocess.Popen([str(binary)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        log.close()
        self.mind = Mind(p.pid, p)
        # A planned restart (new thinkers) is not a crash: the runaway watchdog counts the others.
        if not planned:
            self.starts.append(time.time())
        self.log(f"mind pid {p.pid} LIVING_ONLY={env.get('LIVING_ONLY', 'all')} variant {self.variant} (start {len(self.starts)}) from {binary}")
        self.save()

    def slots(self):
        """Who thinks under `minds.max` N, and whether the cap binds. While everyone the mind would
        think for (alive, past infancy) fits under N, all of them think and the mind runs without
        LIVING_ONLY, so it takes up a newborn turned child itself, with no restart. Once they are
        more than N: those already thinking who are alive, then the earliest-born of the rest, up
        to N. A death frees a slot; a newborn takes one when it becomes a child and one is free."""
        n = self.trial["minds"]["max"]
        cs = {c["id"]: c for c in self.rows("SELECT * FROM character WHERE alive = true")}
        admin = self.world["admin"]
        able = [c for c in cs.values() if c["ai"] and c["controller"] == admin and c["stage"] != 0]
        if len(able) <= n:
            return sorted(c["id"] for c in able), False
        keep = [i for i in (getattr(self, "thinkers", None) or []) if i in cs]
        for c in sorted(able, key=lambda c: (c["born_ms"], c["id"])):
            if len(keep) >= n:
                break
            if c["id"] not in keep:
                keep.append(c["id"])
        return keep, True

    def reslot(self):
        """Restart the mind when the thinkers under `minds.max` change (at most every 2 minutes):
        the mind reads LIVING_ONLY when it starts. While the cap does not bind (no LIVING_ONLY) the
        mind already thinks for everyone able, so only the census's list is brought up to date;
        it is restarted when the cap starts or stops binding, or a capped set gains someone."""
        if not self.trial.get("minds", {}).get("max") or not self.mind or time.time() - getattr(self, "reslot_at", 0) < 120:
            return
        self.reslot_at = time.time()
        want, capped = self.slots()
        # A state saved before this flag ran capped whenever it had a `minds.max`.
        was = True if getattr(self, "capped", None) is None else self.capped
        gone, new = sorted(set(self.thinkers or []) - set(want)), sorted(set(want) - set(self.thinkers or []))
        if capped != was or (capped and new):
            self.emit("events", {"t": self.t(), "reslot": want, "left": gone, "joined": new, "capped": capped})
            self.stop_mind()
            self.start_mind(planned=True)
        elif gone or new:
            # Deaths (the mind leaves the dead alone), or children the uncapped mind took up itself.
            if new:
                self.emit("events", {"t": self.t(), "joined": new, "capped": False})
            self.thinkers = want

    def take_census(self, row):
        """Every character of a small world (`census_s`): stage, life and death, parents, where
        it is, what it does and its hunger, and who the mind thinks for. For worlds of a few dozen."""
        chars = self.rows("SELECT * FROM character")
        pos = {b["id"]: self.pos(b) for b in self.rows("SELECT * FROM body")}
        act = {a["id"]: a for a in self.rows("SELECT * FROM activity")}
        vit = {v["id"]: v for v in self.rows("SELECT * FROM vitals")}
        now = self.now_ms()
        people = []
        for c in chars:
            v, a = vit.get(c["id"]), act.get(c["id"])
            hunger = round(min(100.0, max(0.0, v["hunger"] + v["hunger_rate"] * (now - v["at_ms"]) / 60000)), 1) if v else None
            people.append({"id": c["id"], "name": c["name"], "kind": c["kind"], "stage": c["stage"], "alive": c["alive"], "cause": c["cause"],
                           "born_ms": c["born_ms"], "died_ms": c["died_ms"], "age0": round(c["birth_age_days"], 3), "parents": [c["parent_a"], c["parent_b"]],
                           "pos": [round(x, 1) for x in pos[c["id"]]] if c["alive"] and c["id"] in pos else None, "hunger": hunger if c["alive"] else None,
                           "activity": [a["skill"], a["target"]] if a and c["alive"] else None})
        self.emit("census", {"t": self.t(), "hour": row.get("hour"), "now_ms": now, "thinkers": getattr(self, "thinkers", None), "people": people})

    def record_world(self):
        """Small-world evidence (`record`; whole-table reads, meant for worlds of a few dozen
        bodies): `talk`, every conversation turn (thought rows of kind `talk`) to `talk.jsonl`
        (from exp-greet); `experiences`, every character's experience rows as they arrive, before
        minds integrate and delete them, to `experiences_all.jsonl`; `gestures`, every use of a
        gesture or turn (`wave`, `nod`, `face`, `appraise`; `skill_use`) to `gestures.jsonl`;
        `positions`, every person's position, heading and activity (its skill, and whom it is aimed
        at) each sample to `positions.jsonl`; `uses`, every skill use by the subject and the cast
        (`skill_use`: the attempt, acceptance, release and outcome), written again each time its
        outcome changes (a missile "in flight", then what it struck), to `uses.jsonl`; `thoughts`, every character's thought rows (with
        `detail.reasons`, what each deliberation carried) to `thoughts_all.jsonl`; `audience`,
        who heard each line and how they stood (the `audience` table, where the world keeps it)
        to `audience.jsonl` (greet_report.py)."""
        rec = self.trial.get("record", {})
        for k in ("talk", "audience", "all_experience", "gesture"):
            self.cursor.setdefault(k, 0)
        if rec.get("talk") or rec.get("thoughts"):
            for r in sorted(self.rows(f"SELECT * FROM thought WHERE id > {self.cursor['talk']}"), key=lambda r: r["id"]):
                self.cursor["talk"] = max(self.cursor["talk"], r["id"])
                if rec.get("talk") and r.get("kind") == "talk":
                    self.emit("talk", {"t": self.t(), **r})
                if rec.get("thoughts"):
                    self.emit("thoughts_all", {"t": self.t(), **r})
        if rec.get("experiences"):
            for r in sorted(self.rows(f"SELECT * FROM experience WHERE id > {self.cursor['all_experience']}"), key=lambda r: r["id"]):
                self.cursor["all_experience"] = max(self.cursor["all_experience"], r["id"])
                self.emit("experiences_all", {"t": self.t(), **r})
        if rec.get("gestures"):
            for r in sorted(self.rows(f"SELECT * FROM skill_use WHERE id > {self.cursor['gesture']}"), key=lambda r: r["id"]):
                self.cursor["gesture"] = max(self.cursor["gesture"], r["id"])
                if r.get("skill") in ("wave", "nod", "face", "appraise"):
                    self.emit("gestures", {"t": self.t(), **r})
        if rec.get("uses"):
            # `skill_use` keeps each character's last 24 uses; read them per role each sample and
            # write a row again when its outcome has changed, so the last copy per id is final.
            seen = self.cursor.setdefault("uses_seen", {})
            actors = sorted({i for ids in self.roles.values() for i in ids})
            for actor in actors:
                for r in self.rows(f"SELECT * FROM skill_use WHERE actor = {actor}"):
                    key = str(r["id"])
                    state = (r.get("accepted_ms"), r.get("released_ms"), r.get("outcome"), r.get("outcome_ms"))
                    if seen.get(key) != list(state):
                        seen[key] = list(state)
                        self.emit("uses", {"t": self.t(), **r})
        if rec.get("positions"):
            people = {c["id"] for c in self.rows("SELECT * FROM character WHERE kind = 'person' AND alive = true")}
            now = self.now_ms()
            pos = {str(b["id"]): [round(v, 2) for v in self.pos(b)] + [round(b.get("heading") or 0.0, 3)] for b in self.rows("SELECT * FROM body") if b["id"] in people}
            # What each is doing, and at whom when it is aimed at a creature (target class 3).
            act = {str(a["id"]): [a["skill"], a["target"][1] if isinstance(a.get("target"), list) and a["target"] and a["target"][0] == 3 else 0]
                   for a in self.rows("SELECT * FROM activity") if a["id"] in people}
            self.emit("positions", {"t": self.t(), "ms": now, "pos": pos, "act": act})
        if rec.get("audience"):
            for r in sorted(self.rows(f"SELECT * FROM audience WHERE id > {self.cursor['audience']}"), key=lambda r: r["id"]):
                self.cursor["audience"] = max(self.cursor["audience"], r["id"])
                self.emit("audience", {"t": self.t(), **r})

    def watch_bodies(self, spec):
        """`record.bodies` ({"hz": 5}): every member of every role, `hz` times a second, to
        `bodies.jsonl` (docs/PACK_MIND.md, the arena): position projected to the sample time
        along its row's motion (to `next_ms`), facing (heading and held look, with their turns,
        as `common::facing_at`), `running`, alive, the fighter row (band, move code, start,
        release, end, target) and the activity (skill, creature target). Read-only, on its own
        thread, until the instance stops. Also ends the run (`stopped_by` "side down") when a
        role listed in `trial.end.side_down` has had no living member for `end.after_s` (30)."""
        hz = float(spec.get("hz", 5)) if isinstance(spec, dict) else 5.0
        end = self.trial.get("end", {})
        down_roles, after_s = end.get("side_down", []), float(end.get("after_s", 30))
        down_since = {}
        ids = sorted({i for ids in self.roles.values() for i in ids})
        if not ids:
            return
        where = " OR ".join(f"id = {i}" for i in ids)
        (self.dir / "arena.json").write_text(json.dumps({"trial": self.trial["name"], "variant": self.variant, "replicate": self.rep,
                                                         "arena": self.trial.get("arena", {}), "roles": self.roles, "end": end}, indent=1))
        pool = concurrent.futures.ThreadPoolExecutor(6)
        while not getattr(self, "_bodies_stop", False):
            tick = time.time()
            try:
                # The five reads at once (2.14.1's SQL endpoint takes one statement a request), so
                # a sample costs about one round trip.
                chars, bodies, fighters, acts, vitals, clock = pool.map(self.rows, [f"SELECT {cols} FROM {t} WHERE {where}" for t, cols in (
                    ("character", "id, alive, cause"), ("body", "*"), ("fighter", "*"), ("activity", "*"), ("vitals", "*"))] + ["SELECT * FROM clock"])
                now = self.now_ms()
                alive = {c["id"]: c["alive"] for c in chars}
                out = {}
                for b in bodies:
                    dt = max(0.0, (min(now, b["next_ms"]) - b["t_ms"]) / 1000)
                    head = b.get("heading") or 0.0
                    head += (b.get("turn") or 0.0) * min(dt, b.get("turn_s") or 0.0)
                    face = head + (b.get("face_off") or 0.0) + (b.get("face_turn") or 0.0) * min(dt, b.get("face_turn_s") or 0.0)
                    out[str(b["id"])] = [round(b["x"] + b["vx"] * dt, 2), round(b["y"] + b["vy"] * dt, 2), round(math.atan2(math.sin(face), math.cos(face)), 3), bool(b.get("running"))]
                fighter = {str(f["id"]): [f["band"], f["act"], f["act_ms"], f["release_ms"], f["until_ms"], f["target"]] for f in fighters}
                act = {str(a["id"]): [a["skill"], a["target"][1] if isinstance(a.get("target"), list) and a["target"] and a["target"][0] == 3 else 0]
                       for a in acts}
                hp = {str(v["id"]): [round(v["hp"] + v.get("hp_rate", 0.0) * max(0.0, (now - v["at_ms"]) / 60000), 2), v["max_hp"], round(v["hunger"], 1)]
                      for v in vitals}
                # The world's last tick against the wall clock (ms; includes the read's latency) and
                # the longest gap between ticks it has seen: how far a loaded host slowed it.
                lag = [now - clock[0]["last_ms"], clock[0].get("max_gap_ms")] if clock else None
                self.emit("bodies", {"t": self.t(), "ms": now, "b": out, "hp": hp, "lag": lag, "dead": {str(c["id"]): c.get("cause", "") for c in chars if not c["alive"]}, "f": fighter, "act": act})
                for r in down_roles:
                    if not any(alive.get(i) for i in self.roles.get(r, [])):
                        down_since.setdefault(r, time.time())
                        if time.time() - down_since[r] >= after_s:
                            self.side_down = r
                    else:
                        down_since.pop(r, None)
            except Exception as e:  # a failed read is a gap in the samples, not a failed run
                self.emit("events", {"t": self.t(), "bodies_error": str(e)[:200]})
            time.sleep(max(0.0, 1.0 / hz - (time.time() - tick)))

    def stop_mind(self):
        if self.mind and self.mind.alive():
            self.mind.stop()
            self.log(f"mind stopped (pid {self.mind.pid})")

    # -- state kept for `resume`
    STATE = ("database_identity", "replica", "status", "subject", "roles", "t0", "cursor", "jpos", "brain_rev", "done_at", "saved_graphs", "nsample",
             "died", "published", "snapshots", "stopped_by", "starts", "runaway_seen", "thinkers", "capped", "census_at", "outages")

    def save(self):
        st = {k: getattr(self, k, None) for k in self.STATE}
        st["fired"] = {json.dumps(k): v for k, v in self.fired.items()}
        st["done_at"] = sorted(self.done_at)
        st["mind_pid"] = self.mind.pid if self.mind else None
        st["mind_start"] = proc_start(self.mind.pid) if self.mind else None
        st["saved_graphs"] = {str(k): v for k, v in self.saved_graphs.items()}
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(st))
        tmp.replace(self.dir / "state.json")

    def restore(self):
        st = json.loads((self.dir / "state.json").read_text())
        for k in self.STATE:
            if k in st and st[k] is not None:
                setattr(self, k, st[k])
        self.saved_graphs = {int(k): v for k, v in (st.get("saved_graphs") or {}).items()}
        if not self.subject:
            raise RuntimeError("no subject in state.json: the run had not started; run it again instead")
        self.fired = Counter({tuple(json.loads(k)) if k.startswith("[") else json.loads(k): v for k, v in st.get("fired", {}).items()})
        self.held = {}
        self.done_at = set(self.done_at or [])
        pid = st.get("mind_pid")
        if pid and proc_start(pid) == st.get("mind_start") and proc_start(pid) is not None:
            self.mind = Mind(pid)
            self.log(f"resumed: adopted running mind pid {pid}")
        self.world = self.rows("SELECT * FROM world")[0]
        try:
            self.land = next(iter(self.rows("SELECT * FROM land")), None)
        except RuntimeError:
            self.land = None
        # The journal is re-read from its start so that token totals cover the whole run.
        self.jpos = {}
        self.tokens, self.calls = Counter(), Counter()

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
                    self.note_call(r)
                    self.tokens[key] += tok
                    self.calls[key] += 1
                    if r.get("latency_ms"):
                        self.latency[r.get("purpose")].append(r["latency_ms"])
                    if not self.opts.fake:
                        with _lock:
                            self.shared["spent"] += tok

    def note_call(self, r):
        """One journaled call for the runaway and outage guards, at the call's own time (a
        resumed runner re-reads the whole journal)."""
        at = (r.get("at_ms") or 0) / 1000
        kind = failure_kind(r.get("error"))
        self.recent.append((at, r.get("purpose"), (r.get("error") or "")[:100], kind))
        if kind is None:
            self.last_ok = at if self.last_ok is None else max(self.last_ok, at)
        elif kind != "mind":
            self.provider_fails.append((at, kind))

    # -- sampling
    def sample(self):
        S = self.subject
        others = [i for r, ids in self.roles.items() if r != "subject" for i in ids]
        everyone = list(dict.fromkeys(self.roles["subject"] + others))
        ors = " OR ".join(f"id = {i}" for i in everyone)
        q = [f"SELECT * FROM vitals WHERE id = {S}", f"SELECT * FROM activity WHERE id = {S}",
             f"SELECT * FROM inventory WHERE owner = {S}", f"SELECT * FROM brain WHERE id = {S}",
             f"SELECT * FROM character WHERE {ors}", "SELECT * FROM world", f"SELECT * FROM body WHERE {ors}",
             f"SELECT * FROM thought WHERE actor = {S} AND id > {self.cursor['thought']}",
             f"SELECT * FROM experience WHERE observer = {S} AND id > {self.cursor['experience']}",
             f"SELECT * FROM chronicle WHERE id > {self.cursor['chronicle']}",
             f"SELECT * FROM know_how WHERE actor = {S}", f"SELECT * FROM relation WHERE actor = {S}",
             f"SELECT * FROM judgment WHERE actor = {S}", f"SELECT * FROM persona WHERE id = {S}",
             f"SELECT * FROM structure WHERE owner = {S}", f"SELECT * FROM place WHERE actor = {S}",
             f"SELECT * FROM routine WHERE actor = {S}"]
        # 2.14.1 answers one statement per request ("Multiple SQL statements are not supported").
        # The mind's projections change slowly, so they are read every fifth sample.
        self.nsample = getattr(self, "nsample", 0) + 1
        slow = self.nsample % 5 == 1
        res = [self.rows(x) if i < 10 or slow else None for i, x in enumerate(q)]
        (vit, act, inv, brain, chars, world, bodies, thoughts, exps, chron, know, rel, jud, persona, structs, places, routines) = res
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
        if len(self.roles["subject"]) > 1:
            # A subject of several (a pack) lives while any member does: the run stops when the
            # last one dies, not the first (w3 stopped at the lead's death; fixed after).
            row["lead_alive"] = row["alive"]
            row["alive"] = any(alive.get(i) for i in self.roles["subject"])
            # Where each member is and whether it lives.
            row["members"] = {str(i): {"pos": [round(x, 1) for x in positions[i]] if i in positions else None, "alive": alive.get(i)}
                              for i in self.roles["subject"]}
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
        # `record.speech`: every line said in the world (small worlds; greet_report.py, arrive_report.py).
        speech_all = self.trial.get("record", {}).get("speech")
        for r in new_chron:
            self.cursor["chronicle"] = max(self.cursor["chronicle"], r["id"])
            if r["a"] in mine or r["b"] in mine:
                self.emit("chronicle", {"t": self.t(), **r})
            if speech_all and r.get("kind") == "speech":
                self.emit("speech", {"t": self.t(), **r})
        self.record_world()
        for name, rows in (("know_how", know), ("relation", rel), ("judgment", jud), ("persona", persona), ("structure", structs), ("place", places), ("routine", routines)):
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
                        ("stats", "SELECT * FROM stats"),
                        # Every attention cue in the world (at most 8 per character; docs/ATTENTION.md).
                        ("cue", "SELECT * FROM cue")):
            try:
                snap[name] = self.rows(q)
            except RuntimeError as e:
                snap[name] = {"error": str(e)}
        (self.dir / "final.json").write_text(json.dumps(snap, indent=1))
        if self.journal.exists():
            shutil.copytree(self.journal, self.dir / "journal", dirs_exist_ok=True)

    # -- runaways: loops that cost calls without changing anything
    def rate_limit(self):
        limit = self.trial.get("budget", {}).get("runaway_calls_per_min")
        if limit is not None:
            return limit
        return float("inf") if self.trial.get("minds", {}).get("only") == "all" else 60

    def runaway(self):
        """A retry storm or one failure repeated: recorded, and the run stopped, so that its
        cause is fixed rather than hidden behind a cap."""
        now = time.time()
        self.recent = [r for r in self.recent if now - r[0] <= 300]
        # A provider outage is not a loop: its failures (capacity or rate 429s, 5xx, no
        # connection) count toward no failure limit (ar1: 7 of 28 instances stopped over
        # consolidation's capacity 429s while the mind retried them, most within a minute).
        # They still count as calls, so a mind that storms a failing provider trips the call
        # rate; the outage itself stops a run only when no route answers (`outage`).
        errors = [r for r in self.recent if r[3] == "mind"]
        same = Counter((r[1], r[2]) for r in errors).most_common(1)
        last_min = sum(1 for r in self.recent if now - r[0] <= 60)
        why = None
        # Where a whole island thinks (`minds.only: "all"`, thousands of calls in 5 minutes), a
        # provider's 429s at about 1% are noise the mind retries: failures count as a runaway
        # only as a share of the calls (half, the same one 40%: the island's first minutes are a
        # burst of identity and memory calls the provider answers with 429s), never below the
        # one-mind counts.
        many = self.trial.get("minds", {}).get("only") == "all"
        fail_limit = max(30, 0.5 * len(self.recent)) if many else 30
        same_limit = max(15, 0.4 * len(self.recent)) if many else 15
        if len(errors) >= fail_limit:
            why = f"{len(errors)} failed model calls in 5 minutes"
        elif same and same[0][1] >= same_limit:
            why = f"the same failure {same[0][1]} times in 5 minutes ({same[0][0][0]}: {same[0][0][1]})"
        # A call rate is a loop signal only when one mind thinks: with `minds.only: "all"` a whole
        # island thinks (lives-2: hundreds of calls a minute is its normal), so only a trial's
        # `budget.runaway_calls_per_min` limits it; failures and restarts above still apply.
        elif last_min > self.rate_limit():
            why = f"{last_min} model calls in one minute"
        why = why or self.outage(now)
        recent_starts = [t for t in self.starts if now - t <= 1800]
        if len(recent_starts) > 5:
            why = f"the mind was restarted {len(recent_starts)} times in 30 minutes"
        if why:
            self.emit("events", {"t": self.t(), "runaway": why})
            self.runaway_seen.append([self.t(), why])
        return why

    def outage(self, now):
        """Provider failures since the last call that succeeded on any route: recorded as an
        outage (an `outage` event when it starts, one in `outages` and the events when a call
        succeeds again), and the run's stop only when nothing has answered for OUTAGE_STOP_S
        while calls still fail (the last within OUTAGE_LIVE_S)."""
        if self.last_ok is not None:
            self.provider_fails = [f for f in self.provider_fails if f[0] > self.last_ok]
        rel = lambda at: None if self.t0 is None else round(at - self.t0, 1)
        if self.outage_since is not None and self.last_ok is not None and self.last_ok > self.outage_since:
            ended = {"since_t": rel(self.outage_since), "until_t": rel(self.last_ok), "seconds": round(self.last_ok - self.outage_since, 1),
                     "failed": self.outage_failed, "kinds": dict(self.outage_kinds)}
            if not any(o.get("since_t") == ended["since_t"] for o in self.outages):
                self.outages.append(ended)
                self.emit("events", {"t": self.t(), "outage_ended": ended})
            self.outage_since = None
        if not self.provider_fails:
            return None
        since = min(f[0] for f in self.provider_fails)
        if now - since < OUTAGE_RECORD_S:
            return None
        if self.outage_since is None:
            self.emit("events", {"t": self.t(), "outage": {"since_t": rel(since), "kind": self.provider_fails[0][1]}})
        self.outage_since = since
        self.outage_failed = len(self.provider_fails)
        self.outage_kinds = Counter(k for _, k in self.provider_fails)
        last = max(f[0] for f in self.provider_fails)
        if now - since >= OUTAGE_STOP_S and now - last <= OUTAGE_LIVE_S:
            kinds = ", ".join(f"{k} {n}" for k, n in self.outage_kinds.most_common())
            return f"provider outage: no route answered for {(now - since) / 60:.0f} minutes ({self.outage_failed} failed calls: {kinds})"
        return None

    # -- hourly snapshots (life runs)
    def snapshot(self, row):
        S = self.subject
        snap = {"t": self.t(), "hour_of_run": self.snapshots, "sample": row}
        for name, q in (("know_how", f"SELECT * FROM know_how WHERE actor = {S}"), ("practice", f"SELECT * FROM practice WHERE actor = {S}"),
                        ("relation", f"SELECT * FROM relation WHERE actor = {S}"), ("judgment", f"SELECT * FROM judgment WHERE actor = {S}"),
                        ("place", f"SELECT * FROM place WHERE actor = {S}"), ("persona", f"SELECT * FROM persona WHERE id = {S}"),
                        ("brain", f"SELECT * FROM brain WHERE id = {S}"), ("routine", f"SELECT * FROM routine WHERE actor = {S}"),
                        ("inventory", f"SELECT * FROM inventory WHERE owner = {S}"), ("vitals", f"SELECT * FROM vitals WHERE id = {S}"),
                        ("structure", f"SELECT * FROM structure WHERE owner = {S}"), ("settlement", "SELECT * FROM settlement")):
            try:
                snap[name] = self.rows(q)
            except RuntimeError as e:
                snap[name] = {"error": str(e)}
        if row.get("pos") and isinstance(snap.get("settlement"), list) and snap["settlement"]:
            near = min(snap["settlement"], key=lambda t: dist((t["x"], t["y"]), row["pos"]))
            d = dist((near["x"], near["y"]), row["pos"])
            names = self.settlement_names()
            snap["region"] = {"nearest_settlement": names.get(near["id"], f"settlement {near['id']}"), "kind": near["kind"],
                              "distance_m": round(d), "inside": d <= near["radius_m"]}
        snap["memories"] = self.memories()
        d = self.dir / "snapshots"
        d.mkdir(exist_ok=True)
        (d / f"h{self.snapshots:02d}.json").write_text(json.dumps(snap, indent=1))
        self.snapshots += 1

    def settlement_names(self):
        if not hasattr(self, "_snames"):
            names = {}
            for b in self.rows("SELECT * FROM background"):
                try:
                    bg = json.loads(b["text"])
                except ValueError:
                    continue
                if isinstance(bg.get("settlement"), int) and bg.get("town"):
                    names.setdefault(bg["settlement"], bg["town"])
            self._snames = names
        return self._snames

    def memories(self):
        """The subject's kept memories, from the mind's own graph (read-only)."""
        if self.opts.fake or docker_state(NEO4J) != "running":
            return None
        q = ("MATCH (m:Concept {run: $run, actor: $actor}) WHERE m:Memory AND NOT m:Forgotten "
             "RETURN m.t AS t, m.gist AS gist, m.salience AS salience ORDER BY m.t DESC LIMIT 60")
        r = sh("docker", "exec", NEO4J, "cypher-shell", "-u", "neo4j", "-p", self.shared["neo4j_pw"], "--format", "plain",
               "-P", f"run => {json.dumps(self.db)}", "-P", f"actor => {self.subject}", q, check=False, timeout=60)
        return r.stdout.splitlines()[1:] if r.returncode == 0 else {"error": r.stderr.strip()[:300]}

    # -- the whole run
    def setup(self):
        self.status = "publishing"
        self.publish()
        subj = self.trial["subject"]
        if subj.get("join"):
            # `after_s`: the world lives that long before the player joins (the residents have
            # seen each other first, and the player is the one stranger among them).
            time.sleep(subj["join"].get("after_s", 0))
            self.player = Player(self, subj["join"]["name"])
            self.roles["subject"] = [self.player.join()]
        elif subj.get("spawn"):
            name = subj["spawn"]["name"]
            self.call("spawn_newcomer", name)
            self.roles["subject"] = [max(c["id"] for c in self.rows(f"SELECT * FROM character WHERE name = '{name}'"))]
        self.cast()
        if self.trial.get("newcomer"):
            # A newcomer joins later, in the human session (`Player.join_newcomer`).
            self.player = Player(self, self.trial["newcomer"]["name"])
            self.roles.setdefault("newcomer", [])
        self.status = "preparing"
        # A repurposed resident starts empty-handed and without its old routines. A spawned
        # newcomer, a joined player (whose rows only the player may act on) and an animal do not.
        kinds = subj.get("pick", {}).get("kinds") or [subj.get("pick", {}).get("kind", "person")]
        repurposed = not subj.get("spawn") and not subj.get("join") and kinds == ["person"]
        if subj.get("clear_items", repurposed):
            self.clear_items(self.subject)
        if subj.get("clear_routines", repurposed):
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
        if self.trial.get("record", {}).get("bodies"):
            threading.Thread(target=self.watch_bodies, args=(self.trial["record"]["bodies"],), daemon=True).start()
        self.start_mind()
        if self.trial.get("human"):
            self.human = threading.Thread(target=self.player.session, args=(self.trial["human"],), daemon=True)
            self.human.start()

    def loop(self):
        self.status = "running"
        life = self.trial.get("kind") == "life"
        minutes = self.opts.minutes or self.trial.get("minutes", 15)
        cap = self.trial.get("budget", {}).get("tokens")
        timeline = [(e.get("at"), e) for e in self.trial.get("timeline", []) if isinstance(e.get("at"), (int, float))]
        snap_s = self.trial.get("life", {}).get("snapshot_min", 60) * 60
        last_save = 0
        while True:
            tick = time.time()
            self.read_journal()
            row, new_chron, positions, hour = self.sample()
            for k, (at, e) in enumerate(timeline):
                if k not in self.done_at and self.t() >= at * 60:
                    self.done_at.add(k)
                    self.schedule(e, at * 60)
            self.triggers(new_chron, positions, hour)
            due = [p for p in self.pending if p[0] <= self.t()]
            self.pending = [p for p in self.pending if p[0] > self.t()]
            for _, s in sorted(due, key=lambda p: p[0]):
                self.step(s)
            if life and self.t() >= self.snapshots * snap_s:
                self.snapshot(row)
            census_s = self.trial.get("census_s")
            if census_s and self.t() >= (getattr(self, "census_at", None) or 0):
                self.take_census(row)
                self.census_at = self.t() + census_s
            self.reslot()
            if row["alive"] is False and self.died is None:
                self.died = self.t()
            mind_down = self.mind is not None and not self.mind.alive()
            if mind_down and life and (row["alive"] is not False or not self.trial.get("life", {}).get("stop_on_death", True)):
                # A life run keeps its world: the mind is restarted (as run-mind.sh does).
                self.emit("events", {"t": self.t(), "mind_exit": self.mind.exit_code() if self.mind else None})
                self.start_mind()
                mind_down = False
            why = self.runaway()
            if self.t() >= minutes * 60:
                self.stopped_by = "duration"
            elif cap and sum(self.tokens.values()) >= cap:
                self.stopped_by = "trial token cap"
            elif why:
                self.stopped_by = why if why.startswith("provider outage") else f"runaway: {why}"
            elif self.died is not None and self.t() - self.died >= 20 and self.trial.get("life", {}).get("stop_on_death", True):
                self.stopped_by = "subject died"
            elif mind_down:
                self.stopped_by = f"mind exited ({self.mind.exit_code() if self.mind else None})"
            elif self.shared.get("abort"):
                self.stopped_by = "aborted"
            elif getattr(self, "side_down", None):
                self.stopped_by = f"side down: {self.side_down}"
            if self.stopped_by or time.time() - last_save > 30:
                self.save()
                last_save = time.time()
            if self.stopped_by:
                break
            time.sleep(max(0.0, (getattr(self.opts, "sample_s", None) or SAMPLE_S) - (time.time() - tick)))
        self.status = "collecting"
        self._bodies_stop = True
        self.stop_mind()
        self.read_journal()
        if life:
            self.snapshot(row)
        if self.trial.get("census_s"):
            self.take_census(row)
        self.final()
        self.status = "done"

    def run(self, resume=False):
        try:
            if resume:
                self.restore()
                if self.trial.get("record", {}).get("bodies"):
                    threading.Thread(target=self.watch_bodies, args=(self.trial["record"]["bodies"],), daemon=True).start()
                if (not self.mind or not self.mind.alive()) and self.shared["variants"][self.variant].get("mind") is not False:
                    self.start_mind()
                self.loop()
            else:
                self.setup()
                self.loop()
        except Exception as e:
            self.stopped_by = self.stopped_by or f"error: {e}"
            self.status = "failed"
            self.log(f"FAILED: {e!r}")
            self.stop_mind()
        finally:
            if self.outage_since is not None and not any(o.get("since_t") == round(self.outage_since - (self.t0 or 0), 1) for o in self.outages):
                self.outages.append({"since_t": round(self.outage_since - (self.t0 or 0), 1), "until_t": None, "failed": self.outage_failed,
                                     "kinds": dict(self.outage_kinds)})
            self.save()
            summary = summarize(self.dir, self.trial, extra={"db": self.db, "database_identity": getattr(self, "database_identity", None), "replica": getattr(self, "replica", None), "variant": self.variant, "replicate": self.rep,
                                "stopped_by": self.stopped_by, "fake": bool(self.opts.fake), "minutes_planned": self.opts.minutes or self.trial.get("minutes", 15),
                                "runaways": self.runaway_seen, "mind_starts": len(self.starts), "outages": self.outages,
                                "day_ms": (getattr(self, "world", None) or {}).get("day_ms"),
                                "concurrency": getattr(self, "concurrency", None) or mind_concurrency(self.trial), "world_laws": self.shared["variants"][self.variant].get("world_laws") or {}})
            (self.dir / "summary.json").write_text(json.dumps(summary, indent=1))
            keep = self.opts.keep_db or self.trial.get("keep_db")
            if self.published and not keep and self.status != "failed-keep":
                delete_db(self.db)
            elif self.published and self.trial.get("kind") == "life":
                # Kept, but stopped: a paused world does not tick or grow.
                self.call("set_paused", True)


def delete_db(db):
    """Delete a trial database, its world paused first: SpacetimeDB 2.14.1 can panic, and take
    the whole trial server down, when a database is deleted while its world still ticks (the
    trial service went down that way on 2026-11-12 at 12:52). A world that cannot be paused and
    read back as paused is not deleted."""
    if not db.startswith(PREFIX):
        raise RuntimeError(f"refusing to delete {db}")
    tok = admin_token()
    code, body = http(f"/v1/database/{db}/call/set_paused", [True], tok)
    if code == 404:
        return True
    paused = False
    for _ in range(10):
        c, b = http(f"/v1/database/{db}/sql", "SELECT paused FROM world", tok, raw=True)
        if c == 404:
            return True
        if c == 200 and "true" in b.lower():
            paused = True
            break
        time.sleep(1)
    if not paused:
        print(f"not deleting {db}: its world could not be paused ({code} {body.strip()[:160]})", file=sys.stderr)
        return False
    time.sleep(2)
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


SPOKEN_ID = re.compile(r"#\d+")


def spoken_ids(speech):
    """Lines said aloud whose words hold a `#<digits>` id (`record.speech`): an id is for acts and
    memory ("a stranger #77" is a memory handle), never for speech, so this should be 0. Per
    speaker id; the words are the quoted part of the chronicle line ("A to B: “...”")."""
    by = Counter()
    for r in speech:
        m = re.search(r"“(.*)”", r.get("text") or "", re.S)
        if SPOKEN_ID.search(m[1] if m else (r.get("text") or "").split(": ", 1)[-1]):
            by[str(r.get("a"))] += 1
    return {"lines": sum(by.values()), "by_speaker": dict(by), "of": len(speech)} if speech else None


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
    # The mind's live journal while it exists (a copy taken at a stop can be stale after a
    # reopen), else the instance's copy.
    live = ROOT / ".local/living/journal" / f"{PREFIX}{d.parent.name}-{d.name}"
    jdir = live if live.exists() else d / "journal"
    s["consolidations"] = consolidation_table(jdir)
    for f in sorted(jdir.glob("*.jsonl")) if jdir.exists() else []:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            try:
                r = restore(json.loads(line), f.parent)
                r["_ref"] = f"{d.name}/journal/{f.name}:{n}"
                j.append(r)
            except ValueError:
                pass
    j.sort(key=lambda r: r.get("at_ms", 0))
    # Failed calls by who failed (`failure_kind`): the provider's kinds, and `mind`.
    s["call_failures"] = dict(Counter(k for k in (failure_kind(r.get("error")) for r in j) if k))
    by_purpose = defaultdict(lambda: {"calls": 0, "tokens": 0, "errors": 0, "latency_ms": []})
    by_model = defaultdict(lambda: {"calls": 0, "tokens": 0, "prompt": 0, "completion": 0, "cached": 0})
    remembered = 0
    for r in j:
        p = by_purpose[r.get("purpose")]
        p["calls"] += 1
        p["tokens"] += r.get("tokens") or 0
        p["errors"] += 1 if r.get("error") else 0
        p["capacity_429"] = p.get("capacity_429", 0) + (1 if out_of_capacity(r.get("error")) else 0)
        if r.get("latency_ms"):
            p["latency_ms"].append(r["latency_ms"])
        # The rethink gate's decisions (`rethink-gate`) are journaled beside the calls but are not
        # model calls; its judge's calls are (`rethink`), priced by the mind (`cost_usd`, from the
        # local prices file for Jev).
        if r.get("purpose") != "rethink-gate":
            m = by_model[r.get("model")]
            m["calls"] += 1
            m["tokens"] += r.get("tokens") or 0
            m["prompt"] += r.get("prompt_tokens") or 0
            m["completion"] += r.get("completion_tokens") or 0
            m["cached"] += r.get("cached_tokens") or 0
            if r.get("cost_usd") is not None:
                m["cost_usd"] = m.get("cost_usd", 0.0) + float(r["cost_usd"])
                m["cost_known"] = m.get("cost_known", 0) + 1
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
    s["by_purpose_model"] = purpose_model(j, thoughts)
    social(s, d, S, chron, exps, samples, j, extra)
    members = [x for x in samples if x.get("members")]
    if members:
        pack = len(members[0]["members"])
        hours = (members[-1]["t"] - members[0]["t"]) / 3600 or None
        gaps = []
        for x in members[::5]:
            pts = [m["pos"] for m in x["members"].values() if m.get("alive") and m.get("pos")]
            if len(pts) > 1:
                gaps.append(statistics.mean(dist(a, b) for i, a in enumerate(pts) for b in pts[i + 1:]))
        ids = {int(k) for k in members[0]["members"]}
        kills = [c for c in chron if c.get("kind") == "death" and c.get("b") in ids]
        s["pack"] = {"members": pack, "alive_end": sum(1 for m in members[-1]["members"].values() if m.get("alive")),
                     "kills": len(kills), "killed": dict(Counter(re.sub(r" died.*", "", c["text"]) for c in kills).most_common(6)),
                     "mean_pairwise_m": round(statistics.mean(gaps), 1) if gaps else None, "max_pairwise_m": round(max(gaps), 1) if gaps else None,
                     "calls_per_wolf_hour": round(s["calls"] / (pack * hours), 1) if hours else None,
                     "tokens_per_wolf_hour": round(s["tokens"] / (pack * hours)) if hours else None}
    s["talk_turns"] = by_purpose["talk"]["calls"] if "talk" in by_purpose else 0
    if extra.get("day_ms") and s["minutes_run"]:
        days = s["minutes_run"] * 60000 / extra["day_ms"]
        s["game_days"] = round(days, 2)
        s["tokens_per_game_day"] = round(s["tokens"] / days) if days else None
        s["calls_per_game_day"] = round(s["calls"] / days, 1) if days else None
        per_day = defaultdict(lambda: Counter())
        for r in j:
            if samples and r.get("at_ms"):
                day = int((r["at_ms"] - j[0]["at_ms"]) // extra["day_ms"]) + 1
                per_day[day]["calls"] += 1
                per_day[day]["tokens"] += r.get("tokens") or 0
        s["by_game_day"] = {k: dict(v) for k, v in sorted(per_day.items())}
    s["memories_remembered"] = remembered
    s["spoken_ids"] = spoken_ids(jsonl(d / "speech.jsonl"))
    frame_probes(s, S, chron, j)
    s["exchanges"] = [{"ref": r["_ref"], "purpose": r.get("purpose"), "model": r.get("model"), "tokens": r.get("tokens"),
                       "reply": excerpt(r.get("reply"))} for r in j if r.get("purpose") in ("deliberate", "think", "talk")][:40]
    return s


def frame_probes(s, S, chron, j):
    """The player-frame experiment's probes. `prompt_frame`: per purpose, how many of the
    subject's recorded requests opened with the player frame, of all its requests ("player
    3/3"; "character" when none did). `out_of_character`: lines the subject spoke or wrote that
    step outside the world (ooc.py), and the same count over its replies' private fields."""
    sub_name = (s.get("subject") or "").split("#")[0]
    mine = [r for r in j if sub_name and r.get("_ref", "").split("/journal/")[-1].startswith(sub_name + ".jsonl")]
    framed, total = Counter(), Counter()
    for r in mine:
        msgs = (r.get("request") or {}).get("messages") or []
        system = next((m.get("content") for m in msgs if isinstance(m, dict) and m.get("role") == "system"), None)
        if not isinstance(system, str):
            continue
        total[r.get("purpose")] += 1
        framed[r.get("purpose")] += system.startswith(PLAYER_FRAME_HEAD)
    s["prompt_frame"] = {p: f"{'player' if framed[p] else 'character'} {framed[p]}/{n}" for p, n in sorted(total.items(), key=lambda x: str(x[0]))}
    spoken = [re.sub(r"^[^“]*“|”$", "", c.get("text", "")) for c in chron if c.get("a") == S and c.get("kind") in ("speech", "write")]
    private = [x for r in mine for x in ooc.private_texts(parse_reply(r.get("reply")))]
    s["out_of_character"] = {"spoken": ooc.scan(spoken), "private": ooc.scan(private)}
    s["ooc_lines"] = s["out_of_character"]["spoken"]["flagged"]
    s["ooc_private"] = s["out_of_character"]["private"]["flagged"]


def social(s, d, S, chron, exps, samples, j, extra):
    """Probes for residents who answer: who answered the subject, what was done for it (food,
    a lesson, lodging), where it slept, and what the residents' minds cost per resident-hour
    (every resident has a mind; with `minds.only: "all"` this service thinks for all of them)."""
    speech_to = [c for c in chron if c.get("kind") == "speech" and c.get("b") == S and c.get("a") != S]
    s["answers_to_subject"] = len(speech_to)
    s["answering_people"] = len({c["a"] for c in speech_to})
    done_to = [e for e in exps if e.get("object") == S and e.get("subject") not in (S, 0) and e.get("kind") not in ("saw", "speech", "discovered", "repeat")]
    s["acts_to_subject"] = dict(Counter(e.get("kind") for e in done_to))
    s["taught"] = sorted({re.sub(r".* taught you ([a-z_ ]+).*", r"\1", e["text"]) for e in exps if " taught you " in e.get("text", "")})
    s["lodging"] = any(p == "lodging" for p in s.get("places_named", []))
    snaps = sorted((d / "snapshots").glob("h*.json")) if (d / "snapshots").exists() else []
    setts = json.loads(snaps[0].read_text()).get("settlement", []) if snaps else []
    sleeps = [x for x in samples if (x.get("activity") or [None])[0] == "sleep" and x.get("pos")]
    inside = [x for x in sleeps if any(dist((t["x"], t["y"]), x["pos"]) <= t["radius_m"] for t in setts)] if setts else []
    s["slept_inside_walls"] = f"{len(inside)}/{len(sleeps)} sleep samples" if sleeps else None
    sub_name = (s.get("subject") or "").split("#")[0]
    res = [r for r in j if not r.get("_ref", "").split("/journal/")[-1].startswith(journal_file(sub_name))]
    thinking = {r.get("_ref", "").split("/journal/")[-1].split(".jsonl")[0] for r in res}
    s["residents_thinking"] = len(thinking)
    if res:
        at = [r.get("at_ms") or 0 for r in res if r.get("at_ms")]
        hours = len(thinking) * (max(at) - min(at)) / 3.6e6 if at else 0
        tok = sum(r.get("tokens") or 0 for r in res)
        s["residents_tokens"] = tok
        s["residents_calls"] = len(res)
        s["tokens_per_resident_hour"] = round(tok / hours) if hours > 0 else None
        s["cost_per_resident_hour"] = round(sum((cost(r.get("model"), r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0, r.get("cached_tokens") or 0) or 0) for r in res) / hours, 4) if hours > 0 else None


def strictness(text):
    """How a reply parses: `strict` JSON, `repaired` (the mind's lenient front end would be
    needed: code fences, trailing commas, stray text), or `invalid`. The journal keeps the
    raw reply; the mind's own repair happens after journaling, so this re-checks it."""
    if not isinstance(text, str):
        return "invalid" if text is None else "strict"
    t = text.strip()
    if not t:
        return "empty"
    try:
        json.loads(t)
        return "strict"
    except ValueError:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return "invalid"
    body = re.sub(r",\s*([}\]])", r"\1", m.group(0))
    try:
        json.loads(body)
        return "repaired"
    except ValueError:
        return "invalid"


def purpose_model(j, thoughts):
    """Per purpose x model: calls, tokens, latency p50/p95, failed calls, replies that needed
    repair or could not be parsed, estimated cost; and for deliberations, retries and pruned
    (normalized) graphs from the thought rows."""
    out = defaultdict(lambda: {"calls": 0, "tokens": 0, "prompt": 0, "completion": 0, "cached": 0, "reasoning": 0, "lat": [], "errors": 0, "empty": 0, "repaired": 0, "invalid": 0, "profiles": Counter()})
    for r in j:
        o = out[f"{r.get('purpose')} / {r.get('model')}"]
        o["calls"] += 1
        o["tokens"] += r.get("tokens") or 0
        o["prompt"] += r.get("prompt_tokens") or 0
        o["completion"] += r.get("completion_tokens") or 0
        o["cached"] += r.get("cached_tokens") or 0
        if r.get("latency_ms"):
            o["lat"].append(r["latency_ms"])
        if r.get("error"):
            o["errors"] += 1
        else:
            k = strictness(r.get("reply"))
            if k != "strict":
                o[k] += 1
        o["profiles"][r.get("profile")] += 1
    res = {}
    for k, o in out.items():
        lat = sorted(o["lat"])
        model = k.split(" / ", 1)[1]
        c = cost(model, o["prompt"], o["completion"], o["cached"])
        res[k] = {"calls": o["calls"], "tokens": o["tokens"], "prompt": o["prompt"], "completion": o["completion"],
                  "latency_p50_ms": lat[len(lat) // 2] if lat else None, "latency_p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
                  "errors": o["errors"], "empty": o["empty"], "repaired": o["repaired"], "invalid": o["invalid"], "profiles": dict(o["profiles"]),
                  "cached": o["cached"], "cost_usd": round(c, 4) if c is not None else None}
    retries = pruned = rejected = 0
    # Reasons each deliberation carried (`detail.reasons`, since 2026-11-11): `reused` counts
    # reasons an earlier deliberation of the same service already carried (same words, same
    # arrival), which should be 0 since the stale-reasons fix.
    carried = reused = max_before = 0
    for t in thoughts:
        if t.get("kind") == "error":
            rejected += 1
        try:
            det = json.loads(t.get("detail") or "{}")
        except ValueError:
            continue
        if isinstance(det, dict):
            retries += max(0, (det.get("attempts") or 1) - 1)
            pruned += 1 if det.get("pruned") else 0
            for r in det.get("reasons") or []:
                carried += 1
                reused += 1 if r.get("carried_before") else 0
                max_before = max(max_before, r.get("carried_before") or 0)
    res["deliberations"] = {"retried_attempts": retries, "pruned_graphs": pruned, "rejected": rejected,
                            "reasons_carried": carried, "reasons_reused": reused, "max_carried_before": max_before}
    return res


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


def shared_for(trials, a, bdir):
    shared = {"token": admin_token(), "neo4j_pw": neo4j_password(), "variants": variants(), "spent": 0, "wasm": {}, "seed_rel": {}}
    for t in trials:
        for key, w in worlds_of(t).items():
            name, rel, _ = world_seed(w)
            if not (wasm_mount() / f"{served_name(name)}.wasm").exists():
                sys.exit(f"module for {key} ({name}) is not built: run `trials.py build {t['name']}`")
            shared["wasm"][key], shared["seed_rel"][key] = name, rel
    if not (TARGET / "release/living-mind").exists():
        sys.exit(f"no mind binary at {TARGET / 'release/living-mind'}: run `trials.py build`")
    if a.fake:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        shared["fake_port"] = s.getsockname()[1]
        s.close()
        # `--fake-script`: the fake server's script (fake-llm.md), e.g. capacity 429s on consolidation, or living/trials/fake/latency.json (model latencies like the real ones).
        script = ["--script", str(Path(a.fake_script).resolve())] if getattr(a, "fake_script", None) else []
        shared["fake"] = subprocess.Popen([sys.executable, str(FAKE), "--port", str(shared["fake_port"]), "--log", str(bdir / "fake-requests.jsonl"), *script],
                                          stdout=open(bdir / "fake.log", "a"), stderr=subprocess.STDOUT, start_new_session=True)
        time.sleep(1)
    return shared


def execute(a, instances, shared, resume=False):
    sem = threading.Semaphore(a.parallel)

    def go(inst):
        with sem:
            inst.run(resume=resume)

    threads = [threading.Thread(target=go, args=(i,), daemon=True) for i in instances]
    for th in threads:
        th.start()
        # Starts are staggered so world creation (seeding, births) does not land at once.
        time.sleep(getattr(a, "stagger", 2) or 2)
    old = signal.signal(signal.SIGINT, lambda *_: shared.__setitem__("abort", True))
    try:
        while any(th.is_alive() for th in threads):
            time.sleep(15)
            line = " ".join(f"{i.name}:{i.status}{'@' + str(round((i.t() or 0) / 60, 1)) + 'm' if i.status == 'running' else ''}" for i in instances)
            print(f"[{time.strftime('%H:%M:%S')}] tokens {shared['spent']:,} | {line}", flush=True)
    finally:
        signal.signal(signal.SIGINT, old)
        if shared.get("fake"):
            os.killpg(shared["fake"].pid, signal.SIGTERM)
    if not a.fake:
        led = ledger()
        sums = [json.loads(p.read_text()) for p in (OUT / a.batch).glob("*/summary.json")]
        led["batches"][a.batch] = {"tokens": sum(x.get("tokens", 0) for x in sums), "instances": len(sums), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        LEDGER.write_text(json.dumps(led, indent=1))
    report(argparse.Namespace(batch=a.batch))


def run(a):
    guard()
    if not re.fullmatch(r"[a-z0-9]+", a.batch):
        sys.exit("--batch must be lowercase letters and digits")
    trials = [load_trial(t) for t in a.trials]
    names = a.variants.split(",")
    for v in names:
        if v not in variants():
            sys.exit(f"unknown variant {v}; see living/trials/variants.json")
    # A trial may name the only variants it runs with (`variants`): others are skipped for it.
    plan = [(t, v, r) for t in trials for v in names if not t.get("variants") or v in t["variants"] for r in range(1, a.replicates + 1)]
    # Instance names follow Instance.__init__ (`<trial>-<variant>-r<rep>`).
    long = [n for n in (f"{PREFIX}{a.batch}-{t['name']}-{v}-r{r}" for t, v, r in plan) if len(n) > MAX_DB_NAME]
    if long:
        sys.exit(f"refusing: database names over {MAX_DB_NAME} characters break the server's listing: {long[0]} ({len(long[0])}); use a shorter batch name")
    led = ledger()
    spent = sum(b.get("tokens", 0) for b in led["batches"].values())
    print(f"batch {a.batch}: {len(plan)} instances; real tokens so far {spent:,}{f' of a cap of {TOTAL_CAP:,}' if TOTAL_CAP else ' (no cap)'}{' (fake: not counted)' if a.fake else ''}")
    if TOTAL_CAP and not a.fake and spent >= TOTAL_CAP:
        sys.exit("TRIALS_TOTAL_TOKENS is already spent")
    bdir = OUT / a.batch
    if (bdir / "batch.json").exists():
        sys.exit(f"batch {a.batch} exists; choose a new name, or `trials.py resume --batch {a.batch}`")
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "batch.json").write_text(json.dumps({"trials": a.trials, "variants": names, "replicates": a.replicates, "fake": a.fake,
                                                 "minutes": a.minutes, "keep_db": a.keep_db, "parallel": a.parallel, "sample_s": a.sample_s,
                                                 "commit": sh("git", "-C", ROOT, "rev-parse", "--short", "HEAD").stdout.strip(),
                                                 "dirty": bool(sh("git", "-C", ROOT, "status", "--porcelain", "living").stdout.strip()),
                                                 "started": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1))
    shared = shared_for(trials, a, bdir)
    execute(a, [Instance(a.batch, t, v, r, a, shared) for t, v, r in plan], shared)


def resume(a):
    """Continue a batch after the runner (or a mind) crashed, without resetting any world:
    instances that had not finished reattach to their databases, adopt a mind that is still
    running or start a new one, and go on from their saved cursors and clock."""
    guard()
    bdir = OUT / a.batch
    meta = json.loads((bdir / "batch.json").read_text())
    a = argparse.Namespace(batch=a.batch, fake=meta["fake"], minutes=meta.get("minutes"), keep_db=meta.get("keep_db"), parallel=meta.get("parallel") or 18, stagger=2, sample_s=meta.get("sample_s"))
    trials = {t: load_trial(t) for t in meta["trials"]}
    todo = []
    for t in trials.values():
        for v in meta["variants"]:
            for r in range(1, meta["replicates"] + 1):
                d = bdir / f"{t['name']}-{v}-r{r}"
                st = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
                if st.get("status") in ("running", "starting", "collecting") and st.get("subject"):
                    todo.append((t, v, r))
                elif st.get("status") not in ("done", "failed"):
                    print(f"{d.name}: status {st.get('status')}; not resumable (it had not started its mind)")
    if not todo:
        sys.exit("nothing to resume")
    print(f"resuming {len(todo)} instances of {a.batch}: " + ", ".join(f"{t['name']}-{v}-r{r}" for t, v, r in todo))
    shared = shared_for([t for t, _, _ in todo], a, bdir)
    execute(a, [Instance(a.batch, t, v, r, a, shared) for t, v, r in todo], shared, resume=True)


FIGHT = {"attack", "strike", "shoot", "bowshot", "firebolt", "block", "dodge", "throw", "threaten", "aim"}


def graph_terms(g):
    """Skills, items and labels a graph names: what a revision is about, for a diff summary."""
    out = set()
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "skill" and isinstance(v, str):
                    out.add(v)
                elif k == "want" and isinstance(v, str):
                    out.add(f"want:{v}")
                elif k == "routine" and isinstance(v, str):
                    out.add(f"routine:{v}")
                elif k == "do" and isinstance(v, str):
                    out.add(v)
                elif k == "label" and isinstance(v, str):
                    out.add(f"[{v}]")
                elif k == "item" and isinstance(v, str):
                    out.add(f"{v}")
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(g)
    return out


def life_report(a):
    bdir = OUT / a.batch
    meta = json.loads((bdir / "batch.json").read_text())
    for d in sorted(p.parent for p in bdir.glob("*/samples.jsonl")):
        samples = jsonl(d / "samples.jsonl")
        if not samples:
            continue
        exps = jsonl(d / "experiences.jsonl")
        chron = jsonl(d / "chronicle.jsonl")
        graphs = jsonl(d / "graphs.jsonl")
        rows = jsonl(d / "mind_rows.jsonl")
        status = json.loads((d / "state.json").read_text()).get("status") if (d / "state.json").exists() else None
        if (d / "summary.json").exists() and status not in ("running", "starting", "collecting"):
            summ = json.loads((d / "summary.json").read_text())
        else:
            # Still running: probes from the evidence so far.
            trial = max((t for t in meta["trials"] if d.name.startswith(t + "-")), key=len)
            summ = summarize(d, load_trial(trial), extra={"stopped_by": "still running", "day_ms": 720000})
        snaps = sorted((d / "snapshots").glob("h*.json")) if (d / "snapshots").exists() else []
        setts = json.loads(snaps[0].read_text()).get("settlement", []) if snaps else []
        names = {}
        for b in (json.loads((d / "cast.json").read_text())["roles"].get("subject", [])):
            names[b["id"]] = b["name"]
        S = next(iter(names), None)
        day_ms = summ.get("day_ms") or 720000
        tm = lambda t: f"day {int(t * 1000 // day_ms) + 1}, {t / 60:.0f} min"
        first = {}

        def once(key, t, what):
            if key not in first:
                first[key] = (t, what)

        prev = None
        for x in samples:
            a_ = (x.get("activity") or [None])[0]
            if a_ == "eat" or (prev and prev.get("hunger") is not None and x.get("hunger") is not None and x["hunger"] < prev["hunger"] - 3):
                once("first meal", x["t"], (x.get("activity") or ["?", "?"])[1])
            if a_ in FIGHT:
                once("first fight", x["t"], (x.get("activity") or ["?", "?"])[1])
            if a_ == "craft":
                once("first craft", x["t"], x["activity"][1])
            if a_ == "build":
                once("first build", x["t"], x["activity"][1])
            if a_ == "sleep":
                once("first sleep", x["t"], x["activity"][1])
            if a_ in ("gather", "take") and x.get("activity"):
                once(f"first {a_}", x["t"], x["activity"][1])
            prev = x
        for c in chron:
            if c.get("kind") == "speech" and c.get("a") == S and c.get("b"):
                once("first conversation", c["t"], c["text"][:120])
        for e in exps:
            if e.get("kind") == "fight":
                once("first fight", e["t"], e["text"][:120])
        for r in rows:
            if r["table"] == "structure":
                for st in r["rows"]:
                    if st["kind"] in ("shelter", "house", "campfire", "storage") and st.get("built_ms", 0) > 0:
                        once(f"first {st['kind']} of my own", r["t"], f"{st['kind']} at ({st['x']:.0f}, {st['y']:.0f})")
        deaths = [(e["t"], e["text"][:140]) for e in exps if e.get("kind") == "death"]
        # Where: the nearest settlement, inside it or out in the wilds.
        visits, last = [], None
        for x in samples[::15]:
            if not x.get("pos") or not setts:
                continue
            n = min(setts, key=lambda t: dist((t["x"], t["y"]), x["pos"]))
            dd = dist((n["x"], n["y"]), x["pos"])
            where = f"{'in' if dd <= n['radius_m'] else 'near' if dd <= 3 * n['radius_m'] else 'wilds beyond'} settlement {n['id']} ({n['kind']})"
            if where != last:
                visits.append((x["t"], where))
                last = where
        learned, seen = [], None
        for r in rows:
            if r["table"] == "know_how":
                now_ = {k["technique"]: k["source"] for k in r["rows"]}
                if seen is not None:
                    for k, src in now_.items():
                        if k not in seen:
                            learned.append((r["t"], k, src))
                seen = now_
        revs, prev_terms = [], set()
        for g in graphs:
            try:
                terms = graph_terms(json.loads(g["graph"]))
            except (ValueError, TypeError):
                terms = set()
            added, removed = sorted(terms - prev_terms), sorted(prev_terms - terms)
            revs.append((g["t"], g.get("source"), g.get("plan", "")[:120], added, removed))
            prev_terms = terms
        rout, prev_r = [], {}
        for r in rows:
            if r["table"] != "routine":
                continue
            now_r = {}
            for x in r["rows"]:
                try:
                    now_r[x["name"]] = (x["revision"], graph_terms(json.loads(x["graph"])))
                except (ValueError, TypeError):
                    now_r[x["name"]] = (x["revision"], set())
            for name, (rev, terms) in now_r.items():
                old = prev_r.get(name)
                if old is None:
                    rout.append((r["t"], name, "new", sorted(terms), []))
                elif old[0] != rev:
                    rout.append((r["t"], name, f"rev {rev}", sorted(terms - old[1]), sorted(old[1] - terms)))
            for name in set(prev_r) - set(now_r):
                rout.append((r["t"], name, "dropped", [], []))
            prev_r = now_r
        # Stalls: at least 10 minutes in which the subject stays within 15 m and keeps its graph.
        stalls, i = [], 0
        rev_t = [g["t"] for g in graphs]
        while i < len(samples):
            j = i
            while j + 1 < len(samples) and samples[j + 1].get("pos") and samples[i].get("pos") and dist(samples[i]["pos"], samples[j + 1]["pos"]) < 15:
                j += 1
            span = samples[j]["t"] - samples[i]["t"]
            if span >= 600 and not any(samples[i]["t"] < t <= samples[j]["t"] for t in rev_t):
                acts = Counter((x.get("activity") or ["idle"])[0] for x in samples[i:j + 1])
                stalls.append((samples[i]["t"], span, dict(acts.most_common(4))))
            i = j + 1
        plans = Counter(g.get("plan", "") for g in graphs if g.get("source") == "mind")
        repeats = sum(1 for e in exps if e.get("kind") == "repeat")
        flips = [e["text"][:120] for e in exps if "back and forth" in e.get("text", "")]
        out = [f"# Life of {names.get(S, S)} ({d.name})", "",
               f"Ran {summ.get('minutes_run')} min ({summ.get('game_days')} game days); stopped by {summ.get('stopped_by')}; survived: {summ.get('survived')}; "
               f"{summ.get('calls')} model calls, {summ.get('tokens'):,} tokens ({summ.get('tokens_per_game_day')} per game day); mind starts: {summ.get('mind_starts')}; runaways: {summ.get('runaways') or 'none'}.", "",
               "## Firsts", ""] + [f"- {k}: {tm(t)}: {w}" for k, (t, w) in sorted(first.items(), key=lambda kv: kv[1][0])] + \
              ["", "## Deaths seen", ""] + ([f"- {tm(t)}: {w}" for t, w in deaths] or ["- none"]) + \
              ["", "## Where", ""] + [f"- {tm(t)}: {w}" for t, w in visits] + \
              ["", "## Learned", ""] + ([f"- {tm(t)}: {k} ({src})" for t, k, src in learned] or ["- nothing"]) + \
              ["", f"## Graph revisions ({len(revs)})", ""] + [f"- {tm(t)} [{src}] {plan} | +{', '.join(ad) or '–'} | -{', '.join(rm) or '–'}" for t, src, plan, ad, rm in revs] + \
              ["", f"## Routine changes ({len(rout)}; sampled every 10 s, so quick successive edits merge)", ""] + ([f"- {tm(t)} {name} [{what}] | +{', '.join(ad) or '–'} | -{', '.join(rm) or '–'}" for t, name, what, ad, rm in rout] or ["- none recorded (runs before routine sampling)"]) + \
              ["", "## Stretches where nothing changed (10+ min, within 15 m, no new graph)", ""] + ([f"- {tm(t)} for {span / 60:.0f} min: {acts}" for t, span, acts in stalls] or ["- none"]) + \
              ["", "## Loops", "", f"- plans installed more than 3 times: {[(p, n) for p, n in plans.most_common(8) if n > 3] or 'none'}",
               f"- lines the subject repeated almost word for word (feedback percepts): {repeats}",
               f"- turning back and forth (feedback percepts): {len(flips)}" + (f", e.g. {flips[0]}" if flips else "")]
        (d / "timeline.md").write_text("\n".join(out) + "\n")
        print(f"written {d / 'timeline.md'}")


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


ROWS = ["subject", "stopped_by", "minutes_run", "game_days", "tokens_per_game_day", "survived", "died_min", "hp_min", "hunger_start", "hunger_max", "hunger_end",
        "first_eat_min", "food_gained", "skills", "min_dist", "fled_m", "lines_said", "said_to", "talk_turns", "graph_revisions",
        "refusals", "learned", "built", "relations_end", "judgments_end", "memories_remembered", "prompt_frame", "ooc_lines", "ooc_private", "calls", "tokens"]


def consolidation_report(sums):
    """report.md's consolidation tables: per instance, then per character (summary.json
    `consolidations`, from the mind's outcome lines; see `consolidation_table`)."""
    have = [s for s in sums if s.get("consolidations")]
    if not have:
        return []
    head = " | ".join(c.replace("_", " ") for c in CONSOLIDATION_COLUMNS)
    rule = " ---: |" * len(CONSOLIDATION_COLUMNS)
    name = lambda s: f"{s.get('trial')}/{s.get('variant')}/r{s.get('replicate')}"
    out = ["## Consolidations\n",
           "Per character: attempted; integrated on the primary model or on the fallback; failed and retried later; failed with no later attempt "
           "(lost: never integrated before the stop); experiences of failed ones that left the inbox unintegrated (trimmed); failures that were capacity 429s.\n",
           f"| Instance | {head} |\n| --- |{rule}"]
    for s in have:
        t = s["consolidations"]["total"]
        out.append(f"| {name(s)} | " + " | ".join(str(t[c]) for c in CONSOLIDATION_COLUMNS) + " |")
    out += ["", f"| Instance | Character | {head} |\n| --- | --- |{rule}"]
    for s in have:
        for who, r in sorted(s["consolidations"]["by_character"].items(), key=lambda kv: str(kv[0])):
            out.append(f"| {name(s)} | {str(who).replace('|', '/')} | " + " | ".join(str(r[c]) for c in CONSOLIDATION_COLUMNS) + " |")
    missing = [name(s) for s in sums if not s.get("consolidations")]
    if missing:
        out.append(f"\nNo consolidation outcomes (a mind before 2026-11-11, or none ran): {', '.join(missing)}.")
    out.append("")
    if any(s.get("outages") for s in sums):
        out.append("## Provider outages\n\n| Instance | From (s) | Until (s) | Failed calls | Kinds |\n| --- | ---: | ---: | ---: | --- |")
        for s in sums:
            for o in s.get("outages") or []:
                kinds = ", ".join(f"{k} {n}" for k, n in (o.get("kinds") or {}).items())
                out.append(f"| {name(s)} | {o.get('since_t')} | {o.get('until_t') if o.get('until_t') is not None else 'still down at the stop'} | {o.get('failed')} | {kinds} |")
        out.append("")
    return out


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
            tok[m]["cost_usd"] += v.get("cost_usd", 0.0)
            tok[m]["cost_known"] += v.get("cost_known", 0)
    out.append("| Model | Calls | Tokens | Prompt | Completion | Cached | Est. cost (USD) |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for m, v in tok.items():
        c = cost(m, v["prompt"], v["completion"], v["cached"])
        if c is None and v["calls"] and v["cost_known"] == v["calls"]:
            c = v["cost_usd"]  # priced by the mind on every call (Jev, from the local prices file)
        out.append(f"| {m} | {v['calls']} | {v['tokens']:,} | {v['prompt']:,} | {v['completion']:,} | {v['cached']:,} | {f'{c:.2f}' if c is not None else 'unknown'} |")
    out.append("")
    pm = defaultdict(lambda: Counter())
    lats = defaultdict(list)
    for s_ in sums:
        for k, v in (s_.get("by_purpose_model") or {}).items():
            if k == "deliberations":
                continue
            for f in ("calls", "tokens", "errors", "empty", "repaired", "invalid"):
                pm[k][f] += v[f]
            if v.get("latency_p50_ms"):
                lats[k].append((v["latency_p50_ms"], v["latency_p95_ms"]))
    if pm:
        out.append("| Purpose / model | Calls | Tokens | p50 ms (median of runs) | p95 ms (max of runs) | Failed | Empty text | Repaired | Invalid |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for k, v in sorted(pm.items()):
            l50 = sorted(x for x, _ in lats[k])
            out.append(f"| {k} | {v['calls']} | {v['tokens']:,} | {l50[len(l50) // 2] if l50 else '–'} | {max((y for _, y in lats[k]), default='–')} | {v['errors']} | {v['empty']} | {v['repaired']} | {v['invalid']} |")
        out.append("")
    out += consolidation_report(sums)
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


def record_roots():
    """Every checkout's trial and verification records on this machine (as docs/STORE.md's
    manifest scans them)."""
    home = Path.home()
    roots = [p for pat in ("dev/*", ".t3/worktrees/*/*", "slop*") for p in home.glob(pat) if (p / ".local/living").is_dir()]
    return sorted({p / ".local/living" for p in roots})


def recorded_replicas():
    """{replica: {"batch", "instance", "db", "paid", "root"}} from every checkout's run records
    (state.json `replica`) and, for runs older than that field, from the publish time in each
    instance's actions.log matched to a replica's `db.lock` time (within 40 s) by the caller."""
    rec, pubs = {}, []
    for root in record_roots():
        for bj in (root / "trials").glob("*/batch.json"):
            try:
                b = json.loads(bj.read_text())
            except (OSError, ValueError):
                continue
            bdir = bj.parent
            for inst in bdir.glob("*/"):
                st = {}
                for f in ("summary.json", "state.json"):
                    try:
                        st.update(json.loads((inst / f).read_text()))
                    except (OSError, ValueError):
                        pass
                paid = any(not str(m).startswith("fake") and m != "jev" and (v or {}).get("tokens") for m, v in (st.get("by_model") or {}).items())
                info = {"batch": bdir.name, "instance": inst.name, "db": st.get("db"), "paid": paid, "fake": bool(b.get("fake")), "root": str(bdir), "module": None}
                if st.get("replica"):
                    rec[str(st["replica"])] = info
                started = b.get("started")
                al = inst / "actions.log"
                if started and al.exists():
                    day = datetime.datetime.fromisoformat(started)
                    for line in al.read_text(errors="replace").splitlines():
                        m = re.match(r"(\d\d):(\d\d):(\d\d) published (\S+) from (\S+?)\.wasm", line) or re.match(r"(\d\d):(\d\d):(\d\d) published (\S+)", line)
                        if m:
                            if m.lastindex >= 5:
                                info = {**info, "module": m[5]}
                            t = day.replace(hour=int(m[1]), minute=int(m[2]), second=int(m[3]))
                            if t < day - datetime.timedelta(hours=1):
                                t += datetime.timedelta(days=1)
                            pubs.append((t.astimezone(datetime.timezone.utc).timestamp(), info))
        # Verification runs (verify.py launch): "HH:MM:SS published <db> from …" in each case's
        # actions.log, dated by the file (a scene runs within a day).
        for al in (root / "verify").glob("*/actions.log"):
            try:
                text = al.read_text(errors="replace")
                day = datetime.datetime.fromtimestamp(al.stat().st_mtime)
            except OSError:
                continue
            for line in text.splitlines():
                m = re.match(r"(\d\d):(\d\d):(\d\d) published (\S+)", line)
                if m:
                    t = day.replace(hour=int(m[1]), minute=int(m[2]), second=int(m[3]), microsecond=0)
                    if t > day + datetime.timedelta(minutes=5):
                        t -= datetime.timedelta(days=1)
                    pubs.append((t.astimezone(datetime.timezone.utc).timestamp(),
                                 {"batch": "verify:" + al.parent.name, "instance": "", "db": m[4], "paid": False, "fake": False, "verify": True, "root": str(al.parent)}))
    return rec, sorted(pubs, key=lambda p: p[0])


def reclaim(a):
    """Classify every replica directory in the trial volume; remove nothing by default.

    SpacetimeDB 2.14.1 does not remove a deleted database's replica directory
    (`standalone/src/lib.rs` `on_delete_replica`: "will not remove them from disk"; docs/STORE.md).
    Each directory is one of: `live` (a database the server still hosts, found by its module log),
    `paid` (a deleted trial run that made real model calls: its commitlog is evidence, archived
    before anything is removed), `no-model` (a deleted real run without model calls), `fake`,
    `verify` (scratch), or `unknown`. `--dry-run` (the default) prints the table and totals and
    writes it as JSON with `--json`. Removal is not implemented here: it is the owner's decision,
    with the server stopped and the paid commitlogs archived first."""
    guard()
    token = admin_token()
    lines = sh("docker", "exec", CONTAINER, "sh", "-c", f"cd {REPLICAS} && for r in *; do echo \"$r $(du -sk $r | cut -f1) $(du -sk $r/clog 2>/dev/null | cut -f1) $(cut -d';' -f2 $r/db.lock 2>/dev/null | cut -d= -f2) $(find $r -type f -printf '%T@\\n' | sort -n | tail -1 | cut -d. -f1)\"; done", timeout=1800).stdout.splitlines()
    now_s = time.time()
    owner = sh("docker", "exec", CONTAINER, "spacetime", "login", "show").stdout.split()[-1]
    code, body = http(f"/v1/identity/{owner}/databases")
    live_ids = json.loads(body).get("identities", []) if code == 200 else []
    live = {}
    for ident in live_ids:
        c, b = http(f"/v1/database/{ident}/names")
        name = (json.loads(b).get("names") or [ident])[0] if c == 200 else ident
        r = replica_of(name, token)
        if r:
            live[r] = name
        else:
            sys.exit(f"refusing: the live database {name} ({ident}) cannot be mapped to its replica directory")
    rec, pubs = recorded_replicas()
    ptimes = [p[0] for p in pubs]
    rows = []
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        r, kb, clog_kb, lock = parts[0], int(parts[1]), int(parts[2] or 0), parts[3]
        last_write = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        if r in live or now_s - last_write < 15 * 60:
            # Hosted, or written in the last 15 minutes (a world that may still be running): kept.
            rows.append({"replica": r, "kb": kb, "clog_kb": clog_kb, "lock": lock, "class": "live",
                         "what": live.get(r, "written in the last 15 minutes"), "last_write": last_write})
            continue
        info = rec.get(r)
        if info is None:
            t = datetime.datetime.fromisoformat(lock.replace("Z", "+00:00")).timestamp()
            k = bisect.bisect_left(ptimes, t)
            near = [pubs[j] for j in (k - 1, k) if 0 <= j < len(pubs) and abs(pubs[j][0] - t) <= 40]
            info = near[0][1] if near else None
        if info and info.get("verify"):
            cls, what = "verify", info["batch"]
        elif info:
            cls = "paid" if info["paid"] else "fake" if info["fake"] else "no-model"
            what = f"{info['batch']}/{info['instance']}"
        else:
            cls, what = "unknown", ""
        rows.append({"replica": r, "kb": kb, "clog_kb": clog_kb, "lock": lock, "class": cls, "what": what,
                     "module": (info or {}).get("module"), "root": (info or {}).get("root")})
    action = {"live": "keep", "paid": "archive commitlog, then remove", "no-model": "archive commitlog, then remove",
              "fake": "remove", "verify": "remove", "unknown": "hold"}
    for x in rows:
        x["action"] = action[x["class"]]
    tot = Counter()
    for x in rows:
        tot[x["class"]] += x["kb"]
    for x in sorted(rows, key=lambda x: (x["class"], x["what"], x["replica"])):
        print(f"{x['class']:9} {x['replica']:>9} {x['kb'] / 1048576:7.2f} GB  clog {x['clog_kb'] / 1048576:6.2f} GB  {x['lock'][:19]}  {x['action']:31} {x['what']}")
    print("totals: " + ", ".join(f"{k} {v / 1048576:.1f} GB ({sum(1 for x in rows if x['class'] == k)})" for k, v in sorted(tot.items())))
    print("nothing removed (dry run)")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1))


def resummarize(a):
    """Recompute every instance's summary from its kept evidence (after a probe changes)."""
    bdir = OUT / a.batch
    keep = ("db", "variant", "replicate", "stopped_by", "fake", "minutes_planned", "runaways", "mind_starts", "day_ms", "outages", "concurrency", "world_laws")
    for p in sorted(bdir.glob("*/summary.json")):
        old = json.loads(p.read_text())
        extra = {k: old.get(k) for k in keep}
        if not extra.get("day_ms"):
            extra["day_ms"] = 720000  # every trial world so far has the 12-minute day
        p.write_text(json.dumps(summarize(p.parent, load_trial(old["trial"]), extra), indent=1))
    report(argparse.Namespace(batch=a.batch))


def clean(a):
    guard()
    bdir = OUT / a.batch
    # The batch's own records first (the runner's names), the server's list as a backstop.
    try:
        listed = {d for d in databases() if d.startswith(f"{PREFIX}{a.batch}-")}
    except RuntimeError as e:
        listed = set()
        print(f"note: {e}; deleting from the batch's records only")
    dbs = sorted(set(batch_databases(a.batch)) | listed)
    for db in dbs:
        # delete_db pauses the world first and treats 404 as already deleted
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


def show_dbs(a):
    """A batch's databases from its own records (for samplers: no `spacetime list`). An identity
    missing from older records is looked up by name while the database exists."""
    dbs = batch_databases(a.batch)
    for name, v in dbs.items():
        if not v["identity"]:
            v["identity"] = database_identity(name)
    if a.json:
        print(json.dumps(dbs))
    else:
        for name, v in dbs.items():
            print(f"{name} | {v['identity'] or '(gone)'} | replica {v['replica'] or '?'}")


def show_ledger(_a):
    led = ledger()
    total = sum(b.get("tokens", 0) for b in led["batches"].values())
    for k, b in led["batches"].items():
        print(f"{k}: {b['tokens']:,} tokens, {b['instances']} instances, {b['at']}")
    print(f"total {total:,}" + (f" of {TOTAL_CAP:,}" if TOTAL_CAP else ""))


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
    p.add_argument("--fake-script", help="with --fake: the fake server's script (fake-llm.md), e.g. capacity 429s, or living/trials/fake/latency.json")
    p.add_argument("--parallel", type=int, default=18)
    p.add_argument("--keep-db", action="store_true")
    p.add_argument("--stagger", type=float, default=2, help="seconds between instance starts")
    p.add_argument("--sample-s", type=float, default=SAMPLE_S, help="seconds between samples of each subject (default 2)")
    p.add_argument("--allow-partial", action="store_true")
    p.set_defaults(f=run)
    p = sub.add_parser("report")
    p.add_argument("--batch", required=True)
    p.set_defaults(f=report)
    p = sub.add_parser("clean")
    p.add_argument("--batch", required=True)
    p.set_defaults(f=clean)
    sub.add_parser("ledger").set_defaults(f=show_ledger)
    p = sub.add_parser("resume")
    p.add_argument("--batch", required=True)
    p.set_defaults(f=resume)
    p = sub.add_parser("reclaim", help="classify the trial volume's replica directories (a dry run; removes nothing)")
    p.add_argument("--dry-run", action="store_true", default=True, help="the only mode: print and classify, remove nothing")
    p.add_argument("--json", help="also write the table as JSON")
    p.set_defaults(f=reclaim)
    p = sub.add_parser("dbs", help="a batch's databases from its runner's records: name, identity, replica")
    p.add_argument("--batch", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(f=show_dbs)
    p = sub.add_parser("resummarize")
    p.add_argument("--batch", required=True)
    p.set_defaults(f=resummarize)
    p = sub.add_parser("life")
    p.add_argument("--batch", required=True)
    p.set_defaults(f=life_report)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
