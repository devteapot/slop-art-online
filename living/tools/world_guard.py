"""Detached, run-owned guard for scratch worlds. Admin credentials travel over stdin.

Besides pausing orphans, the guard pauses its world when the host's free space falls under a floor
(docs/TRIAL_DISK.md, "The disk floor during a run"): every DISK_EVERY_S seconds it reads free space
(statvfs, no subprocess) on SLOP_GUARD_DISK_PATH (default: the home directory, where rootless
podman keeps its volumes), and under SLOP_GUARD_FREE_FLOOR_GB (default 15; 0 turns it off) it pauses
the world at once, verifies the pause by SQL, writes world-guard-disk.json in the run directory and
keeps guarding: a world unpaused while the disk is still low is paused again. It never unpauses.
"""
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from trial_activity import running_trial
from verify_credentials import redact

GRACE_SECONDS = 120
# A battle of 216 viewers writes up to about 9 MB/s of raw commitlog at 55 ticks/s (docs/BATTLE_DISK.md),
# about 50 MB in 5 s; the 15 GB floor is about 25 minutes of such a battle, and cleanup's archive room.
DISK_EVERY_S = 5
FREE_FLOOR_GB = 15.0


def free_gb(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1e9


def disk_settings():
    """The floor and the path, read where the run starts (arm), so the detached guard keeps them."""
    floor = float(os.environ.get("SLOP_GUARD_FREE_FLOOR_GB", FREE_FLOOR_GB))
    return {"disk_path": os.environ.get("SLOP_GUARD_DISK_PATH", str(Path.home())), "free_floor_gb": floor}


def process_stamp(pid):
    """Identify the process incarnation, treating unreaped children as dead."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] in ("Z", "X") else fields[19]
    except FileNotFoundError:
        if sys.platform.startswith("linux"):
            return None
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat=", "-o", "lstart="],
                            capture_output=True, text=True)
    status, _, started = result.stdout.strip().partition(" ")
    return started.strip() if status and not status.startswith("Z") else None


ARM_WAIT_S = 30  # how long arming waits for a just-published world to answer (scene gate, 2026-11-20)


def request(url, token, body=None, json_body=False):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if json_body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, body, headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
    except OSError:
        return 0, b""


def lookup(url, db, token):
    status, body = request(f"{url}/v1/database/{db}", token)
    if status == 404:
        return None
    if status == 200:
        identity = json.loads(body)["database_identity"]["__identity__"].removeprefix("0x")
        if re.fullmatch(r"[0-9a-f]{64}", identity):
            return identity
    raise RuntimeError(f"could not resolve {db} (HTTP {status})")


def world(endpoint, token):
    status, data = request(endpoint + "/sql", token, b"SELECT epoch_ms, paused FROM world")
    if status != 200:
        return status, None
    rows = json.loads(data)[0]["rows"]
    return status, rows[0] if rows else None


def lease(directory):
    return directory / "world-guard.json"


def read_lease(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def set_mind(directory, pid):
    path = lease(directory)
    state = read_lease(path)
    if state and "activity" not in state:
        write_json(path, dict(state, mind=[pid, process_stamp(pid)]))


def write_json(path, state):
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    temp.write_text(json.dumps(state))
    temp.replace(path)


def stop(directory):
    lease(directory).unlink(missing_ok=True)


@contextmanager
def world_lock(url, db):
    # Serialize local publishers and guards even when they run in different checkouts.
    key = hashlib.sha256(f"{urllib.parse.urlsplit(url).port}/{db.lower()}".encode()).hexdigest()
    directory = Path.home() / ".cache/slop-world-guards"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / key).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def refresh(directory, url, db, identity):
    """Renew a verification lease if it still belongs to this run."""
    path = lease(directory)
    # Serialize renewal with the watcher's final check before it pauses the world.
    with world_lock(url, db):
        state = read_lease(path)
        if state and state.get("url") == url and state["identity"] == identity and "activity" in state:
            write_json(path, dict(state, activity=time.monotonic()))


def arm(directory, url, db, token, driver_pid=None, *, command=None, expected=None,
        expected_epoch=None, grace=GRACE_SECONDS, idle_seconds=None):
    """Publish in the detached worker so it can arm even if the driver dies during publish."""
    if (driver_pid is None) == (idle_seconds is None):
        raise ValueError("provide either a driver PID or an inactivity window")
    path = lease(directory)
    generation = secrets.token_hex(16)
    result = directory / f".world-guard-start-{generation}.json"
    container = None
    if command:
        container = command[2] if command[:2] == ["docker", "exec"] else os.environ.get("LIVING_STDB_CONTAINER")
    driver = [driver_pid, process_stamp(driver_pid)] if driver_pid is not None else None
    config = dict(container=container, path=str(path), result=str(result), generation=generation, url=url, db=db,
                  token=token, driver=driver, grace=grace, idle_seconds=idle_seconds,
                  command=command, expected=expected, expected_epoch=expected_epoch, **disk_settings())
    with (directory / "world-guard.log").open("a") as log:
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve())], stdin=subprocess.PIPE,
                                stdout=log, stderr=log, start_new_session=True)
        with proc.stdin:
            proc.stdin.write(json.dumps(config).encode())
    while not result.exists():
        if proc.poll() is not None and not result.exists():
            raise RuntimeError(f"orphan guard for {db} failed to arm; see world-guard.log")
        time.sleep(0.1)
    try:
        return json.loads(result.read_text())
    finally:
        result.unlink()


def prepare(config):
    url, db, token = (config[key] for key in ("url", "db", "token"))
    with running_trial(config["container"]), world_lock(url, db):
        existing = lookup(url, db, token)
        if existing != config["expected"]:
            raise RuntimeError(f"refusing to guard or publish {db}: database identity differs from run record")
        if existing and config["expected_epoch"] is not None:
            _, prior = world(f"{url}/v1/database/{existing}", token)
            if not prior or prior[0] != config["expected_epoch"]:
                raise RuntimeError(f"refusing to guard or publish {db}: world epoch differs from run record")
        if command := config["command"]:
            published = subprocess.run(command, timeout=300, stdin=subprocess.DEVNULL,
                                       capture_output=True, text=True)
            print(redact(published.stdout, (token,)), end="", flush=True)
            print(redact(published.stderr, (token,)), end="", file=sys.stderr, flush=True)
            if published.returncode:
                raise RuntimeError(f"publish failed for {db} (exit {published.returncode})")
            op = "Updated" if existing else "Created new"
            receipt = re.search(rf"^{op} database with name: [^,]+, identity: ([0-9a-f]{{64}})$",
                                published.stdout, re.MULTILINE)
            if not receipt:
                raise RuntimeError(f"publish did not confirm the expected ownership of {db}")
        identity = lookup(url, db, token)
        if command and receipt[1] != identity:
            raise RuntimeError(f"publish receipt and database name disagree for {db}")
        if not identity or (existing and existing != identity):
            raise RuntimeError(f"could not verify the published identity of {db}")
        endpoint = f"{url}/v1/database/{identity}"
        status, row = world(endpoint, token)
        # A world just published can be slow to answer its first query on a loaded server (no
        # answer within the 5 s timeout reads as HTTP 0): ask again for up to ARM_WAIT_S.
        deadline = time.monotonic() + ARM_WAIT_S
        while status == 0 and time.monotonic() < deadline:
            time.sleep(2)
            status, row = world(endpoint, token)
        if status != 200:
            raise RuntimeError(f"cannot arm orphan guard for {db} (world query HTTP {status})")
        epoch = row[0] if row else None
        path = Path(config["path"])
        owner = {"identity": identity, "epoch": epoch, "driver": config["driver"]}
        previous = read_lease(path) or {}
        mind = previous.get("mind") if all(previous.get(k) == v for k, v in owner.items()) else None
        state = dict(owner, generation=config["generation"], mind=mind)
        if config["idle_seconds"] is not None:
            state.update(url=url, activity=time.monotonic())
        write_json(path, state)
        write_json(Path(config["result"]), {"identity": identity, "epoch": epoch})
        config.update(endpoint=endpoint, epoch=epoch)
    watch(config)


def watch(config):
    path = Path(config["path"])
    endpoint, token = config["endpoint"], config["token"]
    epoch = config["epoch"]
    driver = config["driver"]
    idle_seconds = config["idle_seconds"]
    missing_since = None
    reported = False
    floor = config.get("free_floor_gb", 0) or 0
    disk_path = config.get("disk_path")
    next_disk = 0.0
    disk_low = False  # in a low episode: paused (or pausing), reported once

    def report(message):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S %z')} ORPHAN GUARD {config['db']}: {message}", flush=True)

    def dead(process):
        pid, stamp = process
        return stamp is None or process_stamp(pid) != stamp

    def current():
        state = read_lease(path)
        return state if state and state["generation"] == config["generation"] else None

    def disk_pause(free):
        """Pause at once while free space is under the floor. Returns False when the guard should end."""
        nonlocal disk_low
        with world_lock(config["url"], config["db"]):
            status, row = world(endpoint, token)
            if status == 404:
                report("database gone")
                return False
            if row and epoch is not None and row[0] != epoch:
                report("world incarnation changed; exiting")
                return False
            if not row:
                return True
            if not disk_low:
                report(f"PAUSING: free space {free:.1f} GB under the floor of {floor:g} GB on {disk_path}")
            if not row[1]:
                request(endpoint + "/call/set_paused", token, b"[true]", json_body=True)
                _, confirmed = world(endpoint, token)
                if not (confirmed and confirmed[1]):
                    report("disk pause not verified; retrying")
                    return True
                if disk_low:
                    report(f"the world was unpaused while free space is {free:.1f} GB: PAUSED AGAIN, verified by SQL")
                else:
                    report("PAUSED AND VERIFIED by SQL (disk floor); the guard goes on, and does not unpause")
            elif not disk_low:
                report("already paused; the guard goes on")
            if not disk_low:
                write_json(path.with_name("world-guard-disk.json"),
                           {"paused_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "free_gb": round(free, 3),
                            "floor_gb": floor, "path": disk_path, "db": config["db"]})
            disk_low = True
        return True

    if idle_seconds is None:
        report(f"armed for driver PID {driver[0]} with {config['grace']} s grace")
    else:
        report(f"armed with {idle_seconds:g} s inactivity lease")
    if floor > 0:
        report(f"disk floor {floor:g} GB free on {disk_path}, read every {DISK_EVERY_S} s")
    while (state := current()) is not None:
        if floor > 0 and time.monotonic() >= next_disk:
            next_disk = time.monotonic() + DISK_EVERY_S
            try:
                free = free_gb(disk_path)
            except OSError as error:
                free = None
                report(f"cannot read free space on {disk_path}: {error}")
            if free is not None and free < floor:
                if not disk_pause(free):
                    return
            elif free is not None and disk_low:
                report(f"free space back to {free:.1f} GB (floor {floor:g} GB); the world stays paused")
                disk_low = False
        mind = state["mind"]
        if state["epoch"] is not None:
            epoch = state["epoch"]
        if idle_seconds is None:
            reason = f"driver PID {driver[0]} exited" if dead(driver) else None
        else:
            reason = f"no verification activity for {idle_seconds:g} s" if time.monotonic() - state["activity"] >= idle_seconds else None
        if idle_seconds is None and reason is None and mind and dead(mind):
            reason = f"mind PID {mind[0]} exited"
        if reason is None:
            missing_since, reported = None, False
        elif idle_seconds is None and missing_since is None:
            missing_since = time.monotonic()
            report(f"{reason}; waiting for recovery or cleanup")
        grace_elapsed = reason and (idle_seconds is not None or time.monotonic() - missing_since >= config["grace"])
        if epoch is None or grace_elapsed:
            with world_lock(config["url"], config["db"]):
                if current() != state:
                    continue
                status, row = world(endpoint, token)
                if status == 404:
                    report("database gone")
                    return
                if row and epoch is None:
                    epoch = row[0]
                    if idle_seconds is not None:
                        write_json(path, dict(state, epoch=epoch))
                if row and row[0] != epoch:
                    report("world incarnation changed; exiting")
                    return
                if row and grace_elapsed:
                    if not reported:
                        report(f"PAUSING ORPHAN ({reason})")
                        reported = True
                    if not row[1]:
                        request(endpoint + "/call/set_paused", token, b"[true]", json_body=True)
                    _, confirmed = world(endpoint, token)
                    if confirmed == [epoch, True]:
                        report("PAUSED AND VERIFIED by SQL")
                        return
                    report("pause not verified; retrying")
        time.sleep(1)


if __name__ == "__main__":
    prepare(json.load(sys.stdin))
