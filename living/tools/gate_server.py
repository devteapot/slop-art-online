#!/usr/bin/env python3
"""The scene gate's own SpacetimeDB server: probe it, start it, stop it and clear what it kept
(docs/TOOLING.md, "The gate's server").

    python3 living/tools/gate_server.py check  [--container C] [--url URL]
    python3 living/tools/gate_server.py start  [--container C] [--url URL]
    python3 living/tools/gate_server.py stop   [--container C] [--url URL] [--volume V] [--keep-replicas]

The container and URL default to LIVING_GATE_STDB_CONTAINER and LIVING_GATE_STDB_URL (as the
scene gate reads them); the volume to the one mounted at /home/spacetime.

- check: `docker exec C true` and `GET URL/v1/ping`, each with a time limit. A container can read as
  running while its overlay helper is gone ("transport endpoint is not connected", "unable to
  find user spacetime"): only an exec shows that. Exit 0 reachable, 14 not, with the error.
  merge.py runs the same probe before a gate with scenes, and gate_merge.sh before and while it
  waits for disk, so a dead server fails the gate at once instead of after the check.
- start: `docker start C` in a systemd user scope of its own (the overlay helper dies with the
  caller's scope otherwise), with no inherited descriptor (Python closes them: no gate lock goes
  with it), then waits until check passes (90 s).
- stop: lists the server's databases, stops it with SIGINT and waits until it has exited. Then,
  only if the server held no database, it removes every replica directory: SpacetimeDB 2.14.1
  keeps a deleted database's replica (its commitlog and snapshots) on disk, and a gate deletes
  every world it makes (2026-11-21: 216 such directories, 12.8 GB, held a gate two hours on
  disk). The removal runs in a one-off container of the server's image on its volume, with the
  server stopped. A database still listed (a world kept for inspection), or a list that could not
  be read, keeps every replica, and stop says so. --keep-replicas keeps them in any case.
This is the gate's server only: never point it at a reference or trial server, whose deleted
databases' commitlogs are evidence (docs/TRIAL_DISK.md).
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

UNREACHABLE = 14
DATA = "/home/spacetime/.local/share/spacetime/data"


def run(*cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout} s")


def last(text):
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def probe(container, url, timeout=20):
    """None when the server answers, else what failed."""
    up = run("docker", "inspect", "-f", "{{.State.Running}}", container, timeout=timeout)
    if up.returncode != 0 or up.stdout.strip() != "true":
        return f"the container {container} is not running ({last(up.stderr) or up.stdout.strip() or 'no state'})"
    r = run("docker", "exec", container, "true", timeout=timeout)
    if r.returncode != 0:
        return f"docker exec {container} failed: {last(r.stderr) or last(r.stdout) or f'exit {r.returncode}'}"
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/v1/ping", timeout=timeout) as resp:
            if resp.status != 200:
                return f"{url}/v1/ping answered {resp.status}"
    except Exception as e:  # noqa: BLE001 - any failure to reach it is the answer
        return f"{url}/v1/ping failed: {e}"
    return None


def databases(container):
    """The server's database names, or None when they could not be read."""
    r = run("docker", "exec", container, "spacetime", "list", "-s", "local", timeout=60)
    if r.returncode != 0:
        return None
    if "No databases found" in r.stdout:
        return []
    names = []
    for ln in r.stdout.splitlines():
        cell = ln.split("|")[0].strip()
        if cell and not cell.startswith(("-", "Database", "WARNING", "Associated")):
            names.append(cell)
    return names


def volume_of(container):
    r = run("docker", "inspect", "-f", "{{json .Mounts}}", container)
    for m in json.loads(r.stdout or "[]"):
        if m.get("Destination") == "/home/spacetime" and m.get("Type") == "volume":
            return m.get("Name")
    return None


def image_of(container):
    return run("docker", "inspect", "-f", "{{.Config.Image}}", container).stdout.strip()


def cmd_check(a):
    why = probe(a.container, a.url)
    if why:
        print(f"gate_server: the gate's server is unreachable: {why}", file=sys.stderr)
        return UNREACHABLE
    print(f"gate_server: {a.container} answers ({a.url})")
    return 0


def cmd_start(a):
    up = run("docker", "inspect", "-f", "{{.State.Running}}", a.container).stdout.strip()
    if up != "true":
        r = run("systemd-run", "--user", "--scope", "--quiet", f"--unit=gate-stdb-{int(time.time())}", "docker", "start", a.container)
        if r.returncode != 0:
            print(f"gate_server: could not start {a.container}: {last(r.stderr)}", file=sys.stderr)
            return UNREACHABLE
    t0 = time.time()
    why = probe(a.container, a.url, timeout=5)
    while why and time.time() - t0 < 90:
        time.sleep(2)
        why = probe(a.container, a.url, timeout=5)
    if why:
        print(f"gate_server: {a.container} started but does not answer after 90 s: {why}", file=sys.stderr)
        return UNREACHABLE
    print(f"gate_server: {a.container} up ({time.time() - t0:.0f} s)")
    return 0


def cmd_stop(a):
    names = databases(a.container) if probe(a.container, a.url, timeout=10) is None else None
    volume = a.volume or volume_of(a.container)
    image = image_of(a.container)
    run("docker", "kill", "-s", "INT", a.container)
    w = run("docker", "wait", a.container, timeout=120)
    up = run("docker", "inspect", "-f", "{{.State.Running}}", a.container).stdout.strip()
    if up == "true":
        print(f"gate_server: {a.container} did not stop on SIGINT within 120 s; replicas kept", file=sys.stderr)
        return 1
    print(f"gate_server: {a.container} stopped (exit {w.stdout.strip() or '?'})")
    if a.keep_replicas:
        print("gate_server: replicas kept (--keep-replicas)")
        return 0
    if names is None:
        print("gate_server: its databases could not be listed before the stop; replicas kept", file=sys.stderr)
        return 0
    if names:
        print(f"gate_server: {len(names)} database(s) still on the server ({', '.join(names[:3])}); replicas kept")
        return 0
    if not volume or not image:
        print("gate_server: no volume at /home/spacetime (or no image) found; replicas kept", file=sys.stderr)
        return 0
    script = (f"R=/v{DATA[len('/home/spacetime'):]}/replicas; [ -d \"$R\" ] || exit 0; "
              "n=$(find \"$R\" -mindepth 1 -maxdepth 1 -type d | wc -l); b=$(du -sb \"$R\" | cut -f1); "
              "find \"$R\" -mindepth 1 -maxdepth 1 -type d -exec rm -rf -- {} +; echo \"$n $b\"")
    r = run("docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{volume}:/v", image, "-c", script, timeout=600)
    if r.returncode != 0:
        print(f"gate_server: clearing the replicas failed: {last(r.stderr)}", file=sys.stderr)
        return 1
    n, b = (r.stdout.split() + ["0", "0"])[:2]
    print(f"gate_server: no database left: {n} deleted databases' replica directories removed ({int(b) / 1e9:.2f} GB)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "start", "stop"])
    ap.add_argument("--container", default=os.environ.get("LIVING_GATE_STDB_CONTAINER", "slop-trials-stdb"))
    ap.add_argument("--url", default=os.environ.get("LIVING_GATE_STDB_URL", "http://127.0.0.1:3320"))
    ap.add_argument("--volume")
    ap.add_argument("--keep-replicas", action="store_true")
    a = ap.parse_args()
    if a.cmd != "check" and a.container in ("slop-trials-stdb", "sao-living_spacetimedb_1"):
        sys.exit(f"gate_server: {a.container} is a trial or reference server: refusing to {a.cmd} it")
    sys.exit({"check": cmd_check, "start": cmd_start, "stop": cmd_stop}[a.cmd](a))


if __name__ == "__main__":
    main()
