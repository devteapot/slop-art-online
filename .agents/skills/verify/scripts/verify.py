#!/usr/bin/env python3
"""Drive the living core the way a player and an observer do, on a scratch database.

Every command works on one verification run, `.local/living/verify/<run>/`, which holds
`state.json` (database, player token, what this run started) and the evidence. Cleanup
removes what the run started and keeps the evidence.

  verify.py launch  --run R [--seed NAME] [--keep-data] [--target-dir DIR]
                                            build the module, start SpacetimeDB if needed,
                                            publish the scratch database verify-R
  verify.py doctor  --run R                 read-only: is this instance worth driving?
  verify.py player  --run R join NAME       a fresh non-admin identity joins (once per run)
  verify.py player  --run R move DX DY [--run-gait]
  verify.py player  --run R act NODE_JSON
  verify.py player  --run R say TEXT [--to ID]
  verify.py sql     --run R QUERY [--as-player | --as-admin] [--save NAME]
  verify.py call    --run R REDUCER ARGS_JSON [--as-player | --as-admin] [--expect-refusal TEXT]
  verify.py observer --run R start|shot NAME|stop
  verify.py cleanup --run R [--keep-db]

Paths and ports: SpacetimeDB http://127.0.0.1:3300, the local container's port (LIVING_STDB_URL may
only name that port, so publishing and HTTP calls always reach the same server); observer
http://127.0.0.1:8330 (VERIFY_OBSERVER_PORT); Chromium from Playwright's cache (VERIFY_CHROME).
"""
import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LIVING = ROOT / "living"
STDB = str(LIVING / "tools/stdb")
URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")
# Publishing goes through the container's CLI, so HTTP must reach that same container.
LOCAL_URLS = {"http://127.0.0.1:3300", "http://localhost:3300"}
OBS_PORT = int(os.environ.get("VERIFY_OBSERVER_PORT", "8330"))
OBSERVER = ROOT / ".local/living/verify/observer.json"
COMPOSE = ["docker", "compose", "--env-file", str(ROOT / ".local/living/neo4j.env"), "-f", str(LIVING / "deploy/compose.yml"), "-p", "sao-living"]
CONTAINER = "sao-living_spacetimedb_1"
# Worlds kept for reference. The helper only ever publishes or deletes `verify-*`.
PREFIX = "verify-"


def wasm_mount():
    """Host directory the container serves as /wasm. From a git worktree it is not this checkout's build dir."""
    r = subprocess.run(["docker", "inspect", CONTAINER, "--format", '{{range .Mounts}}{{if eq .Destination "/wasm"}}{{.Source}}{{end}}{{end}}'], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.stdout.strip() else LIVING / "target/wasm32-unknown-unknown/release"


def run_dir(run):
    d = ROOT / ".local/living/verify" / run
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(run):
    p = run_dir(run) / "state.json"
    return json.loads(p.read_text()) if p.exists() else {"run": run, "db": PREFIX + run, "pids": {}}


def save(st):
    (run_dir(st["run"]) / "state.json").write_text(json.dumps(st, indent=2))


def log(st, line, out=sys.stdout):
    with open(run_dir(st["run"]) / "actions.log", "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {line}\n")
    print(line, file=out, flush=True)


def http(path, body=None, token=None, raw=False):
    data = body.encode() if raw else (json.dumps(body).encode() if body is not None else b"")
    req = urllib.request.Request(URL + path, data=data, method="POST" if body is not None or path == "/v1/identity" else "GET")
    if not raw:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)


def stdb(*args, check=True, timeout=180):
    r = subprocess.run([STDB, *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        sys.exit(f"spacetime {' '.join(args[:3])} failed: {r.stderr.strip()[-4000:]}")
    return r


def container_up():
    r = subprocess.run(["docker", "ps", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Status}}"], capture_output=True, text=True)
    return r.stdout.strip().startswith("Up")


def wait_ping(seconds):
    end = time.time() + seconds
    while time.time() < end:
        if http("/v1/ping")[0] == 200:
            return True
        time.sleep(2)
    return False


def launch(a):
    st = load(a.run)
    if not st["db"].startswith(PREFIX):
        sys.exit(f"refusing to publish {st['db']}: verification databases start with {PREFIX}")
    st["seed"] = a.seed
    if not container_up():
        # `compose up --wait` can hang under podman-compose even after the container is
        # healthy, so start detached and poll the ping endpoint instead.
        subprocess.run([*COMPOSE, "up", "-d", "--no-deps", "spacetimedb"], capture_output=True, timeout=300, check=False)
        st["started_container"] = True
        save(st)
        log(st, "started SpacetimeDB container")
    if not wait_ping(180):
        save(st)
        sys.exit("SpacetimeDB did not answer /v1/ping within 180 s (see `docker logs sao-living_spacetimedb_1`)")
    env = dict(os.environ, LIVING_SEED=a.seed)
    # A non-default seed builds in its own target dir, as living/tools/lab.py does, so the
    # active world's module is never rebuilt with a lab seed. --target-dir overrides it.
    target = getattr(a, "target_dir", None) or (f"target/verify-{a.seed}" if a.seed != "world" else None)
    tdir = ["--target-dir", str(Path(target).resolve()) if getattr(a, "target_dir", None) else target] if target else []
    subprocess.run(["cargo", "build", "-p", "living-authority", "--target", "wasm32-unknown-unknown", "--release", *tdir], cwd=LIVING, env=env, check=True)
    wasm = "living_authority.wasm"
    base = (Path(tdir[1]) if Path(tdir[1]).is_absolute() else LIVING / tdir[1]) if tdir else LIVING / "target"
    built = base / "wasm32-unknown-unknown/release/living_authority.wasm"
    mount = wasm_mount()
    if tdir or built.parent.resolve() != mount.resolve():
        wasm = f"living_authority_verify_{a.run.replace('-', '_')}.wasm"
        (mount / wasm).write_bytes(built.read_bytes())
    st["wasm"] = wasm
    # Record the database before publishing: a publish or script install that fails halfway
    # still leaves a database for cleanup to delete.
    st["published"] = True
    save(st)
    # --keep-data updates the module in place (as `just living-publish` does for the active
    # world), so a mind's reconnect and recovery across a module update can be proven.
    keep = getattr(a, "keep_data", False)
    fresh = [] if keep else ["--delete-data"]
    stdb("publish", "-s", "local", "-b", f"/wasm/{wasm}", st["db"], *fresh, "-y")
    stdb("call", "-s", "local", st["db"], "install_script", json.dumps((LIVING / "scripts/skills.rhai").read_text()))
    st["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    st["dirty"] = bool(subprocess.run(["git", "status", "--porcelain", "living"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    save(st)
    log(st, f"published {st['db']} from {wasm} ({'updated in place, data kept' if keep else 'fresh'}; seed {a.seed}, commit {st['commit']}{' + uncommitted living/ changes' if st['dirty'] else ''})")


def doctor(a):
    st = load(a.run)
    checks = {}
    checks["container up"] = container_up()
    code, _ = http("/v1/ping")
    checks["SpacetimeDB answers /v1/ping"] = code == 200
    r = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{.Config.Image}}"], capture_output=True, text=True)
    checks[f"server image is v2.10.1 ({r.stdout.strip() or 'none'})"] = r.stdout.strip().endswith(":v2.10.1")
    q = lambda text: json.loads(http(f"/v1/database/{st['db']}/sql", text, raw=True)[1])[0]["rows"]
    code, _ = http(f"/v1/database/{st['db']}/sql", "SELECT paused FROM world", raw=True)
    checks[f"database {st['db']} exists"] = code == 200
    if code == 200:
        paused = q("SELECT paused FROM world")[0][0]
        # Housekeeping writes the single `stats` row a few seconds after publishing and then
        # rewrites it periodically, so wait for it and sample it over a window.
        ticks = lambda: next(iter(q("SELECT ticks FROM stats")), [None])[0]
        end = time.time() + 30
        while ticks() is None and time.time() < end:
            time.sleep(1)
        t0 = ticks()
        time.sleep(4)
        t1 = ticks()
        checks[f"world is ticking (paused={paused}, ticks {t0} -> {t1} in 4 s)"] = not paused and None not in (t0, t1) and t1 > t0
    wasm = wasm_mount() / st.get("wasm", "living_authority.wasm")
    src = max((p.stat().st_mtime for d in ("authority/src", "rules/src") for p in (LIVING / d).rglob("*.rs")), default=0)
    checks["published module is newer than authority and rules sources"] = wasm.exists() and wasm.stat().st_mtime >= src
    if st.get("observer"):
        checks[f"observer answers on :{OBS_PORT}"] = observer_answers()
    for k, v in checks.items():
        print(("ok   " if v else "FAIL ") + k)
    sys.exit(0 if all(checks.values()) else 1)


def player(a):
    st = load(a.run)
    if a.action == "join":
        if "token" not in st:
            code, body = http("/v1/identity", {})
            if code != 200:
                sys.exit(f"identity: {code} {body}")
            j = json.loads(body)
            st["token"], st["identity"] = j["token"], j["identity"]
            save(st)
        args = [a.args[0]]
    elif a.action == "move":
        args = [float(a.args[0]), float(a.args[1]), a.run_gait]
    elif a.action == "act":
        args = [a.args[0]]
    else:
        args = [a.args[0], a.to]
    if "token" not in st:
        sys.exit("no player yet: run `player join NAME` first")
    reducer = "join" if a.action == "join" else f"human_{a.action}"
    code, body = http(f"/v1/database/{st['db']}/call/{reducer}", args, st["token"])
    log(st, f"player {reducer}{json.dumps(args)} -> {code} {body.strip()}")
    sys.exit(0 if code == 200 else 1)


def admin_token():
    """The world admin's token (the in-container CLI identity). Kept in memory only."""
    out = stdb("login", "show", "--token").stdout
    for line in out.splitlines():
        if "auth token" in line and " is " in line:
            return line.rsplit(" is ", 1)[1].strip()
    sys.exit("could not read the admin token from `spacetime login show --token`")


def sql(a):
    st = load(a.run)
    token = admin_token() if getattr(a, "as_admin", False) else st.get("token") if getattr(a, "as_player", False) else None
    code, body = http(f"/v1/database/{st['db']}/sql", a.query, token, raw=True)
    if code != 200:
        sys.exit(f"sql: {code} {body}")
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    rows = [dict(zip(names, r)) for r in res["rows"]]
    out = json.dumps(rows, indent=1)
    if getattr(a, "save", None):
        (run_dir(a.run) / f"{a.save}.json").write_text(out)
        log(st, f"sql saved {a.save}.json: {a.query}", sys.stderr)
    print(out)


def call(a):
    """Call one reducer over HTTP as the player, the admin or (default) an anonymous identity."""
    st = load(a.run)
    token = admin_token() if a.as_admin else st.get("token") if a.as_player else None
    if a.as_player and not token:
        sys.exit("no player yet: run `player join NAME` first")
    args = json.loads(a.args)
    if not isinstance(args, list):
        sys.exit("ARGS_JSON must be a JSON array of the reducer's arguments")
    who = "admin" if a.as_admin else "player" if a.as_player else "anonymous"
    code, body = http(f"/v1/database/{st['db']}/call/{a.reducer}", args, token)
    log(st, f"call {a.reducer}{json.dumps(args)} as {who} -> {code} {body.strip()}")
    if a.expect_refusal is not None:
        ok = code != 200 and a.expect_refusal in body
        log(st, f"expected refusal containing {a.expect_refusal!r}: {'yes' if ok else 'NO'}")
        sys.exit(0 if ok else 1)
    sys.exit(0 if code == 200 else 1)


def proc_start(pid):
    """Process start time from /proc, to tell a process from a later one reusing its pid."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def observer_answers():
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{OBS_PORT}/", timeout=5).status == 200
    except OSError:
        return False


def chrome():
    if os.environ.get("VERIFY_CHROME"):
        return os.environ["VERIFY_CHROME"]
    found = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))
    return found[-1] if found else "chromium"


def observer(a):
    st = load(a.run)
    d = run_dir(a.run)
    # One observer serves every run. observer.json records the trunk process (pid and start
    # time) and the runs using it; the last run to leave stops it.
    reg = json.loads(OBSERVER.read_text()) if OBSERVER.exists() else None
    ours = bool(reg) and proc_start(reg["pid"]) == reg["start"]
    if a.action == "start":
        if ours and observer_answers():
            reg["consumers"] = sorted(set(reg["consumers"]) | {a.run})
            OBSERVER.write_text(json.dumps(reg))
            st["observer"] = True
            save(st)
            log(st, f"observer already served on :{OBS_PORT} by verification (pid {reg['pid']}); joined as a user")
            return
        if observer_answers():
            log(st, f"observer already served on :{OBS_PORT} by something outside verification; using it, never stopping it")
            return
        out = open(d / "trunk.log", "a")
        p = subprocess.Popen(["trunk", "serve", "--cargo-profile", "wasm-dev", "--address", "127.0.0.1", "--port", str(OBS_PORT)], cwd=LIVING / "viewer", stdout=out, stderr=subprocess.STDOUT, env={k: v for k, v in os.environ.items() if k != "NO_COLOR"}, start_new_session=True)
        OBSERVER.write_text(json.dumps({"pid": p.pid, "start": proc_start(p.pid), "consumers": [a.run]}))
        st["observer"] = True
        save(st)
        end = time.time() + 600
        while time.time() < end:
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{OBS_PORT}/", timeout=2).status == 200:
                    log(st, f"observer serving http://127.0.0.1:{OBS_PORT}/?db={st['db']} (pid {p.pid})")
                    return
            except OSError:
                time.sleep(3)
        sys.exit("observer did not come up within 10 minutes; see trunk.log")
    if a.action == "shot":
        png = d / f"{a.name}.png"
        url = f"http://127.0.0.1:{OBS_PORT}/?db={st['db']}"
        # Software WebGL keeps the canvas renderable without a GPU; virtual time lets the
        # wasm load and the subscription fill before the capture.
        subprocess.run([chrome(), "--headless=new", "--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", f"--window-size={a.size}", f"--virtual-time-budget={a.wait_ms}", f"--screenshot={png}", url], capture_output=True, timeout=180)
        if not png.exists():
            sys.exit("screenshot failed")
        log(st, f"observer screenshot {png.relative_to(ROOT)} of {url}")
        return
    if not st.pop("observer", False):
        save(st)
        return
    save(st)
    if not ours:
        OBSERVER.unlink(missing_ok=True)
        log(st, "observer process is gone or was replaced; nothing to stop")
        return
    reg["consumers"] = [r for r in reg["consumers"] if r != a.run]
    if reg["consumers"]:
        OBSERVER.write_text(json.dumps(reg))
        log(st, f"left the observer running for {', '.join(reg['consumers'])}")
        return
    try:
        os.killpg(reg["pid"], signal.SIGTERM)
    except ProcessLookupError:
        pass
    OBSERVER.unlink(missing_ok=True)
    log(st, f"observer stopped (pid {reg['pid']}, last user)")


def cleanup(a):
    st = load(a.run)
    if st.get("observer"):
        observer(argparse.Namespace(run=a.run, action="stop"))
        st = load(a.run)
    if st.get("published") and not getattr(a, "keep_db", False) and st["db"].startswith(PREFIX):
        stdb("delete", "-s", "local", st["db"], "-y", check=False)
        # Trust the server, not the CLI's exit status: a deleted database answers SQL with 404.
        code, body = http(f"/v1/database/{st['db']}/sql", "SELECT 1 FROM world", raw=True)
        if code == 404:
            st["published"] = False
            log(st, f"deleted {st['db']} (SQL now 404)")
        else:
            save(st)
            sys.exit(f"{st['db']} still answers SQL after delete (HTTP {code}); rerun cleanup or delete it with living/tools/stdb")
    if st.get("wasm", "").startswith("living_authority_verify_"):
        (wasm_mount() / st["wasm"]).unlink(missing_ok=True)
        log(st, f"removed module copy {st['wasm']}")
    if st.get("started_container"):
        # Other runs may share the server. Leave it up while any other verify-* database lives.
        others = [l.split("|")[0].strip() for l in stdb("list", check=False).stdout.splitlines() if l.strip().startswith(PREFIX)]
        others = [d for d in others if d != st["db"]]
        if others:
            log(st, f"left SpacetimeDB running: other verification databases are live ({', '.join(others)})")
            st.pop("started_container")
    if st.pop("started_container", False):
        # The server (PID 1) handles SIGINT, not SIGTERM; compose sets stop_signal: SIGINT, and
        # sending it directly also covers containers created before that setting.
        subprocess.run(["docker", "kill", "--signal", "SIGINT", CONTAINER], capture_output=True, text=True, timeout=30)
        subprocess.run(["docker", "stop", "-t", "60", CONTAINER], capture_output=True, text=True, timeout=180)
        # podman falls back to SIGKILL after the timeout; report a forced stop as forced.
        code = subprocess.run(["docker", "inspect", CONTAINER, "--format", "{{.State.ExitCode}}"], capture_output=True, text=True).stdout.strip()
        log(st, f"stopped SpacetimeDB container (this run started it; exit code {code}{', forced by SIGKILL' if code == '137' else ''})")
    st.pop("token", None)
    save(st)
    print(f"evidence kept in {run_dir(a.run).relative_to(ROOT)}/")


def main():
    if URL not in LOCAL_URLS:
        sys.exit(f"LIVING_STDB_URL={URL} is not the local container (http://127.0.0.1:3300); publishing and HTTP calls would reach different servers")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("launch"); p.add_argument("--run", required=True); p.add_argument("--seed", default="world")
    p.add_argument("--keep-data", action="store_true", help="update the run's existing database in place instead of publishing it fresh")
    p.add_argument("--target-dir", help="cargo target directory for the module build, e.g. under .local/living/verify/<run>/")
    p.set_defaults(f=launch)
    p = sub.add_parser("doctor"); p.add_argument("--run", required=True); p.set_defaults(f=doctor)
    p = sub.add_parser("player"); p.add_argument("--run", required=True); p.add_argument("action", choices=["join", "move", "act", "say"]); p.add_argument("args", nargs="+")
    p.add_argument("--run-gait", action="store_true"); p.add_argument("--to", type=int, default=0); p.set_defaults(f=player)
    p = sub.add_parser("sql"); p.add_argument("--run", required=True); p.add_argument("query"); p.add_argument("--as-player", action="store_true"); p.add_argument("--as-admin", action="store_true"); p.add_argument("--save"); p.set_defaults(f=sql)
    p = sub.add_parser("call"); p.add_argument("--run", required=True); p.add_argument("reducer"); p.add_argument("args", help="JSON array, e.g. '[true]'")
    g = p.add_mutually_exclusive_group(); g.add_argument("--as-player", action="store_true"); g.add_argument("--as-admin", action="store_true")
    p.add_argument("--expect-refusal", metavar="TEXT", help="succeed only if the call is refused with TEXT in the error"); p.set_defaults(f=call)
    p = sub.add_parser("observer"); p.add_argument("--run", required=True); p.add_argument("action", choices=["start", "shot", "stop"]); p.add_argument("name", nargs="?", default="observer")
    p.add_argument("--size", default="1400,900"); p.add_argument("--wait-ms", type=int, default=25000); p.set_defaults(f=observer)
    p = sub.add_parser("cleanup"); p.add_argument("--run", required=True); p.add_argument("--keep-db", action="store_true"); p.set_defaults(f=cleanup)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
