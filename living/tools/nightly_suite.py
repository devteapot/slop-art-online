#!/usr/bin/env python3
"""The nightly full suite on the Spark (docs/TOOLING.md, "The nightly suite").

The merge's scene gate (scene_gate.py) runs only the cases a merge's paths select. This runs,
once a night against current origin/main, every verify-core scene and driver no gate case
reaches: life and wildlife, laws and the clock, the body, infant, goods, perception, battle
scale and the rest. Each entry runs on a fresh world of its seed on a private SpacetimeDB
server of its own. Measurement drivers with no pass mark are left out (EXCLUDED says why).

    nightly_suite.py plan [--repo R]                 the entries tonight's run would make
    nightly_suite.py run [--repo R] [--only a,b] [--until HH:MM] [--lanes 3] [--no-reds]
    nightly_suite.py selftest                        the plan's coverage and the guards, no server

Guards, in order (as the trial reclaim, docs/TOOLING.md):
  1. battle.lock (~/slop-mq/battle.lock), taken exclusively first and held for the whole run,
     holding nothing else while it waits;
  2. each entry's launch and drive under the trial-activity lock, shared
     (flock -s ~/slop-mq/trial-activity.lock), as every verify.py launch on the Spark;
  3. no entry starts while the merge queue is at work (drain.lock or lock held, or drain.sh,
     merge2.sh or scene_gate.py running) or the 1-minute load is over --max-load (8): it waits,
     and what has not started by --until is recorded "not run". SIGINT/SIGTERM: nothing more
     starts, running entries are interrupted (SIGINT to their group), the server stops.
Builds go through ~/slop-mq/build-slot. Its checkout is a detached worktree of the repository
at origin/main (STATE/main, made once), built in STATE/target.

Results: STATE/<date>/record.json and record.md (per entry: seed, run, exit codes, the first
failed checks, evidence path, minutes). A red entry is listed in STATE/<date>/reds.txt for the
owning machine's queue (owners from ~/.config/slop-nightly/owners.json, by entry or area; else
"unassigned") and added to the red-on-main list as `nightly:<entry>` (scene_gate.py reds --add);
a green entry that is listed is dropped from it. Python standard library only.
"""
import argparse
import ast
import contextlib
import datetime
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get("SLOP_NIGHTLY_STATE") or HOME / ".local/state/slop-nightly")
MQ = Path(os.environ.get("SLOP_NIGHTLY_MQ") or HOME / "slop-mq")
OWNERS = HOME / ".config/slop-nightly/owners.json"
IMAGE = "clockworklabs/spacetime:v2.14.1"
PORT = int(os.environ.get("SLOP_NIGHTLY_PORT") or 3690)
CPUS = os.environ.get("SLOP_NIGHTLY_CPUS", "0-4,10-14")
C = ".agents/skills/verify-core/scripts"
V = ".agents/skills/verify/scripts/verify.py"

# Measurement drivers and helpers with no pass mark, or that need what a night cannot provide.
EXCLUDED = {
    "doing_cost": "a measurement, no pass mark",
    "intents_cost": "a measurement, no pass mark",
    "fights": "a measurement (fight length), no pass mark",
    "chase": "a measurement (the chase), no pass mark",
    "doing_deltas.py": "a measurement, no pass mark",
    "arrival": "a rerun helper of `wildlife` from its checkpoint, not a scene of its own",
    "updates.py": "needs chains of prebuilt modules named by hand (features/updates.md)",
    "cover.py": "its --fixture file is not in the skill; the cover proof runs by hand (docs/COVER_SIGHT.md)",
    "speech.py diff": "compares a run against a baseline run of another module",
    "sex-seed": "writes the sex scene's seed (a prep step of `sex`)",
}

# One entry per world: (id, seed, area, commands). Seeds as verify.py takes them; "{C}" is the
# scripts folder, "{run}" the entry's run, "{root}" the checkout. A command list runs in order on
# the entry's world; all must exit 0. `prep` runs before the launch, `driver` entries publish
# their own world (no launch). Areas are for owners.json.
W = "world"
SCENE = lambda name: [["python3", f"{C}/scenes.py", name, "--run", "{run}"]]


def plan_entries():
    e = []
    default = ["needs", "alarms", "sleeper", "food", "teach", "doing", "doing_seen", "doing_renew", "seen_again",
               "crowd_sight", "stranger_filter", "cues", "first_sight", "familiar_dense", "notice_rate", "witness_wake",
               "witness_fold", "cheap_check_ctx", "cheap_alarms", "cheap_warmth", "status_parts", "scene_lazy",
               "chronicle_recent", "notice_inplace", "notice_delta", "seen_remains", "regard_check", "moves",
               "known_ground", "nav_belief", "stamina", "death-names", "intents", "fov", "placement", "answers",
               "admin_vitals", "alert_after_hit", "apart", "howl_reach", "fast_diag", "ground_goto", "relation_fight",
               "heed", "sex_seen_bound", "familiar_regard"]
    for s in default:
        e.append({"id": s, "seed": W, "area": "core", "cmds": SCENE(s), "scene": s})
    e.append({"id": "perceived_threat", "seed": W, "area": "perception",
              "cmds": SCENE("perceived_threat"), "scene": "perceived_threat"})
    for s in ("seen_remains_gaze", "sweep_kept", "sweep_rollback", "sweep_marks"):
        e.append({"id": s, "seed": "cullet", "area": "perception", "cmds": SCENE(s), "scene": s})
    for s in ("low", "dealings"):
        e.append({"id": s, "seed": "island", "area": "core", "cmds": SCENE(s), "scene": s})
    for s in ("drop", "owners"):
        e.append({"id": s, "seed": "plan-test", "area": "perception", "cmds": SCENE(s), "scene": s})
    for s in ("goods", "stock", "making", "workplace"):
        e.append({"id": s, "seed": "{root}/" + C + "/goods", "area": "goods", "cmds": SCENE(s), "scene": s})
    for s in ("laws", "decay"):
        e.append({"id": s, "seed": "cullet-laws", "area": "laws", "cmds": SCENE(s), "scene": s, "minutes": 50})
    e.append({"id": "winter", "seed": "{root}/" + C + "/winter", "area": "laws", "cmds": SCENE("winter"), "scene": "winter", "minutes": 15})
    e.append({"id": "infant", "seed": "{root}/" + C + "/infant", "area": "life", "cmds": SCENE("infant"), "scene": "infant",
              "minutes": 130})
    for s in ("lifecycle", "family_laws", "wildlife", "remains", "flee", "grazing"):
        e.append({"id": s, "seed": "stage1-acts", "area": "life" if s in ("lifecycle", "family_laws") else "wildlife",
                  "cmds": SCENE(s), "scene": s, "minutes": 30 if s == "wildlife" else 10})
    e.append({"id": "sex", "seed": "{root}/.local/living/verify/sex-family", "area": "life", "scene": "sex",
              "prep": [["python3", f"{C}/scenes.py", "sex-seed"]], "cmds": SCENE("sex")})
    for p in ("pack-reflex-on", "pack-reflex-off"):
        e.append({"id": f"pack_reflex-{p.rsplit('-', 1)[1]}", "seed": p, "area": "wildlife", "scene": "pack_reflex",
                  "cmds": SCENE("pack_reflex")})
    for s in ("regress", "ways", "channels", "crowd"):
        e.append({"id": f"speech-{s}", "seed": W, "area": "speech", "driver_name": f"speech.py {s}",
                  "cmds": [["python3", f"{C}/speech.py", s, "--run", "{run}"]]})
    e.append({"id": "town", "seed": "island", "area": "town", "driver_name": "town.py", "minutes": 20,
              "cmds": [["python3", f"{C}/town.py", "--run", "{run}"]]})
    e.append({"id": "lives", "seed": "island", "area": "town", "driver_name": "lives.py", "minutes": 30,
              "cmds": [["python3", f"{C}/lives.py", "--run", "{run}", "--minutes", "24"]]})
    e.append({"id": "rhythm", "seed": "{root}/.local/living/verify/{run}/cullet-rhythm", "area": "town", "driver_name": "rhythm.py",
              "prep": [["python3", f"{C}/rhythm.py", "seed", "--run", "{run}"]], "minutes": 20,
              "cmds": [["python3", f"{C}/rhythm.py", "drive", "--run", "{run}"]]})
    e.append({"id": "closed_gate", "seed": "island", "area": "steering", "driver_name": "closed_gate.py",
              "cmds": [["python3", f"{C}/closed_gate.py", "--run", "{run}"]]})
    e.append({"id": "look_bands", "seed": "{root}/.local/living/verify/{run}/look-bands", "area": "life", "driver_name": "look_bands.py",
              "prep": [["python3", f"{C}/look_bands.py", "seed", "--run", "{run}"]],
              "cmds": [["python3", f"{C}/look_bands.py", "drive", "--run", "{run}"]]})
    # law_override checks drive verify-client's first-result check: a client-* run, and its probe.
    e.append({"id": "law_override", "seed": "island", "area": "laws", "driver_name": "law_override.py", "prefix": "client",
              "prep": [["cargo", "build", "--locked", "--manifest-path", ".agents/skills/verify-client/scripts/probe/Cargo.toml"]],
              "cmds": [["python3", f"{C}/law_override.py", "checks", "--run", "{run}"],
                       ["python3", f"{C}/law_override.py", "time", "--run", "{run}"]]})
    e.append({"id": "law_override-switch", "seed": "island", "area": "laws", "driver_name": "law_override.py switch",
              "cmds": [["python3", f"{C}/law_override.py", "switch", "--run", "{run}"]]})
    # verify_steering publishes its own world from the server's /wasm/living_authority.wasm.
    e.append({"id": "verify_steering", "seed": W, "area": "steering", "driver_name": "verify_steering.py", "driver": True,
              "cmds": [["python3", "living/tools/verify_steering.py", "--db", "verify-{run}"]]})
    return e


def scenes_in(root):
    """Every scene name scenes.py registers (SCENES), read from the source."""
    src = (Path(root) / C / "scenes.py").read_text()
    names = set()
    m = re.search(r"^SCENES = \{(.*?)\}$", src, re.M | re.S)
    if m:
        names |= set(re.findall(r'"([\w-]+)":', m.group(1)))
    names |= set(re.findall(r'SCENES\["([\w-]+)"\]\s*=', src))
    names |= set(re.findall(r'SCENES\[\s*"([\w-]+)"\s*\]', src))
    return names


def gate_cases(root, surface="verify-core"):
    """The given verification surface's cases the merge's scene gate runs (CASES in that checkout's scene_gate.py)."""
    tree = ast.parse((Path(root) / "living/tools/scene_gate.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "CASES" for t in node.targets):
            out = set()
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Dict):
                    fields = {kk.value: vv for kk, vv in zip(v.keys, v.values) if isinstance(kk, ast.Constant)}
                    skill = fields.get("skill")
                    if isinstance(skill, ast.Constant) and skill.value == surface:
                        out.add(k.value)
            return out
    return set()


def plan(root):
    """(tonight's entries, scenes no entry, gate case or exclusion covers)."""
    gate = gate_cases(root)
    scenes = scenes_in(root)
    entries = [x for x in plan_entries() if not (x.get("scene") in gate and x["id"] == x.get("scene"))]
    entries = [x for x in entries if x.get("scene") is None or x["scene"] in scenes]
    covered = {x.get("scene") for x in plan_entries()} | gate | set(EXCLUDED)
    return entries, sorted(scenes - covered)


# ---------------------------------------------------------------- guards

# Set by SIGINT or SIGTERM (systemd stops the service with SIGINT): no entry starts, the running
# ones are interrupted (SIGINT to their process group, so their cleanup runs), the server stops.
STOP = threading.Event()


def lock_held(path, proc):
    """Inspect a queue flock without acquiring or opening the queue's lock file."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return False
    device_inode = (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
    for line in (proc / "locks").read_text().splitlines():
        fields = line.split()
        if fields[1] == "FLOCK":
            major, minor, inode = fields[5].split(":")
            if (int(major, 16), int(minor, 16), int(inode)) == device_inode:
                return True
    return False


def merge_queue_active(mq=MQ, proc=Path("/proc")):
    """Why the merge queue is at work now, or None: its drain (drain.lock) or a merge (lock) is
    held, or drain.sh, merge2.sh or scene_gate.py runs. Branches waiting in queue.txt with nothing
    draining them do not count (the drain that starts later is seen at the next entry): on
    2026-11-23 queue.txt kept a branch merged hours before, which would have held a night."""
    for name in ("drain.lock", "lock"):
        if lock_held(mq / name, proc):
            return f"{name} is held (the merge queue is at work)"
    for p in proc.iterdir():
        if not p.name.isdecimal() or p.name == str(os.getpid()):
            continue
        try:
            argv = (p / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        names = {Path(a.decode(errors="replace")).name for a in argv[:3] if a}
        hit = names & {"drain.sh", "merge2.sh", "scene_gate.py"}
        if hit:
            return f"{sorted(hit)[0]} runs (pid {p.name})"
    return None


def queue_note(mq=MQ):
    """What queue.txt holds, for the record (it does not hold an entry back)."""
    try:
        return [l.split("\t")[0] for l in (mq / "queue.txt").read_text().splitlines() if l.strip()]
    except OSError:
        return []


def wait_turn(until, max_load, say, mq=MQ, sleep=None, now=datetime.datetime.now):
    """Wait until the merge queue is idle and the load is under max_load; False once `until`
    passes or a stop was asked."""
    sleep = sleep or (lambda s: STOP.wait(s))
    said = None
    while True:
        if now() >= until or STOP.is_set():
            return False
        why = merge_queue_active(mq) or (f"1-minute load {os.getloadavg()[0]:.1f} over {max_load:g}"
                                         if os.getloadavg()[0] > max_load else None)
        if not why:
            return True
        if why != said:
            say(f"waiting: {why}")
            said = why
        sleep(60)


@contextlib.contextmanager
def battle_lock(until, say, path=MQ / "battle.lock", sleep=time.sleep, now=datetime.datetime.now):
    """battle.lock exclusively, taken first with nothing else held; yields False when `until`
    came before it was free."""
    f = path.open("a")
    try:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if now() >= until:
                    say("battle.lock still held at the window's end: nothing run")
                    yield False
                    return
                sleep(60)
        yield True
    finally:
        f.close()


# ---------------------------------------------------------------- the run

def sh(cmd, cwd, log, env, timeout):
    """Run `cmd` in a process group of its own; on a stop or the timeout, SIGINT the group (the
    drivers' cleanup runs) and SIGKILL it after 120 s more."""
    with open(log, "a") as out:
        out.write(f"$ {' '.join(map(str, cmd))}\n")
        out.flush()
        p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=out, stderr=subprocess.STDOUT, env=env,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        end = time.monotonic() + timeout
        while p.poll() is None:
            if STOP.is_set() or time.monotonic() > end:
                out.write("stopped (a stop was asked)\n" if STOP.is_set() else f"timed out after {timeout} s\n")
                out.flush()
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGINT)
                try:
                    p.wait(120)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
                return 130 if STOP.is_set() else 124
            time.sleep(1)
        return p.returncode


def fetch_main(repo):
    subprocess.run(["git", "-C", repo, "fetch", "-q", "origin", "main"], check=True)
    return subprocess.check_output(["git", "-C", repo, "rev-parse", "origin/main"], text=True).strip()


def checkout(repo):
    """STATE/main: a detached worktree of the repository at origin/main (made once)."""
    main = STATE / "main"
    sha = fetch_main(repo)
    if not (main / ".git").exists():
        main.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", str(main), sha], check=True)
    else:
        if subprocess.run(["git", "-C", main, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip():
            raise SystemExit(f"nightly: {main} has changes; refusing to move it")
        subprocess.run(["git", "-C", main, "checkout", "-q", "--detach", sha], check=True)
    return main, sha


def server(name, wasm_dir, say):
    subprocess.run(["docker", "volume", "create", name], check=True, capture_output=True)
    subprocess.run(["docker", "run", "-d", "--name", name, "--cpuset-cpus", CPUS, "--ulimit", "nofile=65536:524288",
                    "-p", f"127.0.0.1:{PORT}:3000", "-v", f"{wasm_dir}:/wasm", "-v", f"{name}:/home/spacetime", IMAGE,
                    "start", "--listen-addr", "0.0.0.0:3000"], check=True, capture_output=True)
    for _ in range(90):
        if subprocess.run(["curl", "-sf", f"http://127.0.0.1:{PORT}/v1/ping"], capture_output=True).returncode == 0:
            return
        time.sleep(2)
    raise SystemExit(f"nightly: {name} did not answer on :{PORT}")


def stop_server(name, record_dir, say):
    """SIGINT, a long wait, the log kept beside the record, then the container and its volume."""
    subprocess.run(["docker", "kill", "-s", "INT", name], capture_output=True)
    code = subprocess.run(["timeout", "600", "docker", "wait", name], capture_output=True, text=True).stdout.strip()
    log = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
    (record_dir / "server.log").write_text(log.stdout + log.stderr)
    forced = code != "0"
    if forced:
        subprocess.run(["docker", "kill", name], capture_output=True)
    subprocess.run(["docker", "rm", name], capture_output=True)
    subprocess.run(["docker", "volume", "rm", name], capture_output=True)
    say(f"server {name} stopped ({'FORCED: exit ' + code if forced else 'exit 0'})")
    return {"exit": code, "forced": forced, "panics": len(re.findall(r"panicked|PANIC", log.stdout + log.stderr))}


def first_failures(evidence, entry):
    """The first failed checks from a scene's results, else the last lines of its log."""
    got = []
    res = evidence / f"{entry.get('scene') or entry['id']}-results.json"
    if res.exists():
        try:
            data = json.loads(res.read_text())
            got = [k for k, v in (data.get("checks") or {}).items() if not (v or {}).get("passed")]
            if data.get("error"):
                got.append(f"error: {data['error']}")
        except (ValueError, AttributeError):
            pass
    if not got and (evidence / "nightly.log").exists():
        tail = [l for l in (evidence / "nightly.log").read_text(errors="replace").splitlines() if l.strip()][-3:]
        got = [l[:200] for l in tail]
    return got[:5]


def launch_command(run, seed, target):
    # Raw CLI and HTTP scene drivers do not renew the inactivity lease.
    return [sys.executable, V, "launch", "--run", run, "--seed", seed,
            "--target-dir", str(target), "--driver-pid", str(os.getpid())]


def run_entry(entry, root, stamp, env, until, max_load, say):
    run = f"{entry.get('prefix', 'core')}-nt{stamp}-{re.sub(r'[^a-z0-9]+', '-', entry['id'].lower()).strip('-')}"[:56]
    ev = Path(root) / ".local/living/verify" / run
    ev.mkdir(parents=True, exist_ok=True)
    log = ev / "nightly.log"
    fmt = lambda a: a.replace("{run}", run).replace("{root}", str(root)).replace("{C}", C)
    t0 = time.time()
    result = {"id": entry["id"], "seed": fmt(entry["seed"]), "area": entry["area"], "run": run, "evidence": str(ev)}
    if not wait_turn(until, max_load, say):
        return dict(result, status="not run", why="stopped" if STOP.is_set() else "the window ended first")
    result["waited_min"] = round((time.time() - t0) / 60, 1)
    t0 = time.time()  # minutes count the entry's own run, not its wait for the queue and the load
    lock = ["flock", "-s", str(MQ / "trial-activity.lock")]
    slot = [str(MQ / "build-slot")] if (MQ / "build-slot").exists() else []
    codes = []
    try:
        for cmd in entry.get("prep", []):
            prep = [fmt(c) for c in cmd]
            if cmd[0] == "cargo":
                # drive.py finds the client probe in the verification checkout.
                probe_dir = ev.parent / "target-client"
                prep = lock + slot + prep + ["--target-dir", str(probe_dir)]
            codes.append(sh(prep, root, log, env, 1800))
        if any(codes):
            return dict(result, status="red", why="prep failed", codes=codes, minutes=round((time.time() - t0) / 60, 1),
                        failed=first_failures(ev, entry))
        if not entry.get("driver"):
            target = Path(env["CARGO_TARGET_DIR"])
            if entry["seed"] != W:
                seed_key = entry["id"] if "{" in entry["seed"] else entry["seed"]
                target = target / seed_key
            launch = launch_command(run, fmt(entry["seed"]), target)
            code = sh(lock + slot + launch, root, log, env, 3600)
            if code:
                return dict(result, status="red", why=f"launch exit {code}", minutes=round((time.time() - t0) / 60, 1),
                            failed=first_failures(ev, entry))
            sh(["python3", V, "doctor", "--run", run], root, log, env, 300)
        else:
            denv = dict(env, CORE_VERIFY_RUN=run, LIVING_STDB=str(Path(root) / C / "record_stdb.py"))
            env = denv
        for cmd in entry["cmds"]:
            if STOP.is_set():
                break
            codes.append(sh(lock + [fmt(c) for c in cmd], root, log, env, 4 * 3600))
        if STOP.is_set():
            return dict(result, status="not run", why="stopped", codes=codes, minutes=round((time.time() - t0) / 60, 1))
        ok = not any(codes)
        return dict(result, status="green" if ok else "red", codes=codes, minutes=round((time.time() - t0) / 60, 1),
                    failed=[] if ok else first_failures(ev, entry))
    finally:
        # the cleanup runs even after a stop (outside sh's stop check)
        with open(log, "a") as out:
            subprocess.run(["python3", V, "cleanup", "--run", run], cwd=root, stdout=out, stderr=subprocess.STDOUT,
                           env=env, stdin=subprocess.DEVNULL, timeout=600)


def owner_of(entry_id, area):
    try:
        owners = json.loads(OWNERS.read_text())
    except (OSError, ValueError):
        owners = {}
    return owners.get(entry_id) or owners.get(area) or "unassigned"


def write_record(day_dir, record):
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "record.json").write_text(json.dumps(record, indent=1) + "\n")
    rows = ["| Entry | Seed | Status | Minutes | Failed | Evidence |", "|---|---|---|---|---|---|"]
    for r in record["entries"]:
        rows.append(f"| {r['id']} | {r['seed']} | {r['status']} | {r.get('minutes', '')} | "
                    f"{'; '.join(r.get('failed') or []) or r.get('why', '')} | `{r.get('evidence', '')}` |")
    reds = [r for r in record["entries"] if r["status"] == "red"]
    md = [f"# Nightly suite {record['date']}", "",
          f"origin/main `{record['main'][:10]}`; {len(record['entries'])} entries: "
          f"{sum(r['status'] == 'green' for r in record['entries'])} green, {len(reds)} red, "
          f"{sum(r['status'] == 'not run' for r in record['entries'])} not run; server {record.get('server')}.", "",
          *rows, ""]
    if record.get("unplanned"):
        md += ["Scenes no entry, gate case or exclusion covers (add them): " + ", ".join(record["unplanned"]), ""]
    (day_dir / "record.md").write_text("\n".join(md))
    lines = [f"{r['id']}\towner={owner_of(r['id'], r['area'])}\t{'; '.join(r.get('failed') or [])}\t{r.get('evidence')}" for r in reds]
    (day_dir / "reds.txt").write_text("\n".join(lines) + ("\n" if lines else ""))


def update_reds(record, repo, say):
    """`nightly:<entry>` on the red-on-main list: added when red, dropped when green."""
    gate = [sys.executable, str(Path(repo) / "living/tools/scene_gate.py"), "reds"]
    listed = subprocess.run(gate + ["--json"], capture_output=True, text=True)
    try:
        current = set(json.loads(listed.stdout or "{}"))
    except ValueError:
        current = set()
    for r in record["entries"]:
        key = f"nightly:{r['id']}"
        if r["status"] == "red":
            subprocess.run(gate + ["--add", key, "--skill", "verify-core", "--who", owner_of(r["id"], r["area"]),
                                   "--reason", f"nightly {record['date']}: " + ("; ".join(r.get("failed") or []) or r.get("why", "red"))[:300],
                                   "--main", record["main"], "--evidence", r.get("evidence", "")], capture_output=True)
            say(f"red-on-main: added {key}")
        elif r["status"] == "green" and key in current:
            subprocess.run(gate + ["--drop", key], capture_output=True)
            say(f"red-on-main: dropped {key} (green tonight)")


def cmd_plan(a):
    root = Path(a.repo)
    entries, unplanned = plan(root)
    for x in entries:
        print(f"{x['id']:22} {x['seed']:52} {x['area']:10} ~{x.get('minutes', 5)} min")
    print(f"{len(entries)} entries; excluded: {', '.join(sorted(EXCLUDED))}")
    if unplanned:
        print("UNPLANNED (no entry, gate case or exclusion): " + ", ".join(unplanned))
    return 1 if unplanned else 0


def cmd_run(a):
    stamp = datetime.datetime.now().strftime("%m%d")
    date = datetime.date.today().isoformat()
    day_dir = STATE / date
    day_dir.mkdir(parents=True, exist_ok=True)
    say_log = day_dir / "nightly.log"

    def say(msg):
        line = f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        with say_log.open("a") as f:
            f.write(line + "\n")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: (say("stop asked: no entry starts; running ones are interrupted"), STOP.set()))
    h, m = map(int, a.until.split(":"))
    until = datetime.datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    if until <= datetime.datetime.now():
        until += datetime.timedelta(days=1)
    with battle_lock(until, say) as held:
        if not held:
            write_record(day_dir, {"date": date, "main": "", "entries": [], "note": "battle.lock held until the window's end"})
            return 0
        root, sha = checkout(a.repo)
        entries, unplanned = plan(root)
        if a.only:
            entries = [x for x in entries if x["id"] in a.only.split(",")]
        # longest first, so the long waits overlap the short ones
        entries.sort(key=lambda x: -x.get("minutes", 5))
        name = f"slop-nightly-{date}"
        wasm = STATE / "wasm"
        wasm.mkdir(parents=True, exist_ok=True)
        server(name, wasm, say)
        env = dict(os.environ, LIVING_STDB_CONTAINER=name, LIVING_STDB_URL=f"http://127.0.0.1:{PORT}",
                   CARGO_TARGET_DIR=str(STATE / "target"))
        record = {"date": date, "main": sha, "until": a.until, "unplanned": unplanned, "entries": [], "server": name,
                  "queue_at_start": queue_note()}
        try:
            if unplanned:
                say("UNPLANNED scenes (no entry, gate case or exclusion): " + ", ".join(unplanned))
            # verify_steering publishes /wasm/living_authority.wasm: the default seed's build, made by
            # one default launch whose module copy is kept under that name.
            if any(x.get("driver") for x in entries) and wait_turn(until, a.max_load, say):
                base = f"core-nt{stamp}-base"
                blog = day_dir / "base-launch.log"
                code = sh(["flock", "-s", str(MQ / "trial-activity.lock")] + ([str(MQ / "build-slot")] if (MQ / "build-slot").exists() else [])
                          + launch_command(base, W, env["CARGO_TARGET_DIR"]), root, blog, env, 3600)
                built = wasm / f"living_authority_verify_{base.replace('-', '_')}.wasm"
                if code == 0 and built.exists():
                    shutil.copyfile(built, wasm / "living_authority.wasm")
                sh(["python3", V, "cleanup", "--run", base], root, blog, env, 600)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.lanes)) as ex:
                futs = [ex.submit(run_entry, x, root, stamp, env, until, a.max_load, say) for x in entries]
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    say(f"{r['id']}: {r['status']} {('; '.join(r.get('failed') or []) or r.get('why', ''))[:200]}")
                    record["entries"].append(r)
                    write_record(day_dir, record)
        finally:
            record["server_stop"] = stop_server(name, day_dir, say)
            write_record(day_dir, record)
        if not a.no_reds:
            update_reds(record, root, say)
        say(f"done: {sum(r['status'] == 'red' for r in record['entries'])} red; {day_dir / 'record.md'}")
    return 0


def cmd_selftest(a):
    root = Path(a.repo)
    if not a.origin_main:
        return selftest(root)
    # The installed runner uses its own plan against origin/main's scene and gate registries.
    # Read those files at one commit without moving either the source repo or the nightly checkout.
    sha = fetch_main(a.repo)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for path in (f"{C}/scenes.py", "living/tools/scene_gate.py"):
            dest = root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(subprocess.check_output(["git", "-C", a.repo, "show", f"{sha}:{path}"]))
        return selftest(root)


def selftest(root):
    failures = []

    def expect(name, cond, detail=""):
        print(("ok   " if cond else "FAIL ") + name + (f" ({detail})" if detail and not cond else ""))
        if not cond:
            failures.append(name)
    entries, unplanned = plan(root)
    expect("every scene is an entry, a gate case or excluded with a reason", not unplanned, unplanned)
    ids = [x["id"] for x in entries]
    expect("entry ids are unique", len(ids) == len(set(ids)))
    gate = gate_cases(root)
    step_one = {"say", "heard_first", "audience", "flee_wall", "pursue_last_seen", "act_gaps",
                "act_replace", "truthful_refusals", "committed", "dodge_told", "health_seen", "seize", "outcomes"}
    expect("the gate covers all step-1 core scenes", step_one <= gate, sorted(step_one - gate))
    expect("no nightly scene repeats a gate case", not {x.get("scene") for x in entries} & gate)
    expect("speak and told belong only to the gate's player surface",
           {"speak", "told"} <= gate_cases(root, "verify-player") and not {"speak", "told"} & (gate | set(ids)))
    expect("core dealings stays nightly despite the gate's minds case",
           "dealings" in ids and "dealings" in gate_cases(root, "verify-minds"))
    launch = launch_command("core-nightly-test", W, "/private/target")
    expect("launches watch the nightly process", launch[-2:] == ["--driver-pid", str(os.getpid())])
    expect("measurements are left out", not {"doing_cost", "intents_cost", "fights", "chase"} & set(ids))
    expect("the long waits are in (wildlife, laws, decay, winter, infant)", {"wildlife", "laws", "decay", "winter", "infant"} <= set(ids))
    expect("run names fit verify.py (core-*, client-*; at most 56 characters)",
           all(re.fullmatch(r"[a-z0-9-]+", re.sub(r"[^a-z0-9]+", "-", x["id"].lower())) for x in entries))
    with tempfile.TemporaryDirectory() as t:
        mq = Path(t)
        (mq / "locks").write_text("")
        (mq / "queue.txt").write_text("")
        expect("an empty queue is idle", merge_queue_active(mq, proc=mq) is None)
        (mq / "queue.txt").write_text("some-branch\tMerge it\n")
        expect("a queued branch nobody drains does not hold an entry back (it is noted)",
               merge_queue_active(mq, proc=mq) is None and queue_note(mq) == ["some-branch"])
        held = (mq / "drain.lock").open("a")
        fcntl.flock(held, fcntl.LOCK_EX)
        expect("a held drain.lock is the queue at work",
               "drain.lock is held" in (merge_queue_active(mq) or ""))
        held.close()
        fake = mq / "123"
        fake.mkdir()
        (fake / "cmdline").write_bytes(b"bash\0/home/x/slop-mq/merge2.sh\0")
        expect("a running merge2.sh is active", "merge2.sh" in (merge_queue_active(mq, proc=mq) or ""))
        clock = [datetime.datetime(2026, 1, 1, 1, 0)]
        STOP.set()
        expect("a stop ends the wait", wait_turn(datetime.datetime(2099, 1, 1), 99, lambda m: None, mq=mq, sleep=lambda s: None) is False)
        STOP.clear()
        log = mq / "sh.log"
        t = threading.Timer(1.0, STOP.set)
        t.start()
        t1 = time.monotonic()
        code = sh(["sh", "-c", "trap 'echo cleaned; exit 3' INT; sleep 30 & wait"], mq, log, dict(os.environ), 60)
        STOP.clear()
        expect("a stop interrupts a running command with SIGINT, and its cleanup runs",
               code == 130 and time.monotonic() - t1 < 20 and "cleaned" in log.read_text(), log.read_text()[-200:])
        expect("waiting past --until gives up", wait_turn(datetime.datetime(2026, 1, 1, 1, 0), 99, lambda m: None, mq=mq,
                                                            sleep=lambda s: None, now=lambda: clock[0]) is False)
        (mq / "battle.lock").write_text("")
        holder = (mq / "battle.lock").open("a")
        fcntl.flock(holder, fcntl.LOCK_EX)
        with battle_lock(datetime.datetime(2026, 1, 1, 1, 0), lambda m: None, path=mq / "battle.lock", sleep=lambda s: None,
                         now=lambda: datetime.datetime(2026, 1, 1, 2, 0)) as held:
            expect("battle.lock held by another until the window's end: nothing runs", held is False)
        holder.close()
        with battle_lock(datetime.datetime(2026, 1, 1, 1, 0), lambda m: None, path=mq / "battle.lock") as held:
            expect("battle.lock free: taken", held is True)
        rec = {"date": "2026-01-01", "main": "a" * 40, "entries": [
            {"id": "wildlife", "seed": "stage1-acts", "area": "wildlife", "status": "red", "failed": ["arrival"], "evidence": "/x"},
            {"id": "needs", "seed": "world", "area": "core", "status": "green", "evidence": "/y"}], "server": "s"}
        write_record(mq / "day", rec)
        expect("the record lists a red for its owner's queue",
               (mq / "day" / "reds.txt").read_text().startswith("wildlife\towner=") and "| wildlife |" in (mq / "day" / "record.md").read_text())
    print("nightly_suite selftest: " + ("all passed" if not failures else f"{len(failures)} FAILED"))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_repo = str(Path(__file__).resolve().parents[2])
    p = sub.add_parser("plan")
    p.add_argument("--repo", default=default_repo)
    p.set_defaults(f=cmd_plan)
    r = sub.add_parser("run")
    r.add_argument("--repo", default=default_repo)
    r.add_argument("--only")
    r.add_argument("--until", default="10:00", help="no entry starts after this local time (HH:MM)")
    r.add_argument("--lanes", type=int, default=3, help="entries at once (each its own world)")
    r.add_argument("--max-load", type=float, default=8.0)
    r.add_argument("--no-reds", action="store_true", help="do not write the red-on-main list")
    r.set_defaults(f=cmd_run)
    s = sub.add_parser("selftest")
    s.add_argument("--repo", default=default_repo)
    s.add_argument("--origin-main", action="store_true", help="check coverage against freshly fetched origin/main")
    s.set_defaults(f=cmd_selftest)
    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    raise SystemExit(main())
