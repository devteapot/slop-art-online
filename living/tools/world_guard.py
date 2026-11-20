"""Detached, run-owned guard for scratch worlds. Admin credentials travel over stdin."""
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

from verify_credentials import redact

GRACE_SECONDS = 120


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


def request(url, token, body=None, json_body=False):
    headers = {"Authorization": f"Bearer {token}"}
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
    driver = [driver_pid, process_stamp(driver_pid)] if driver_pid is not None else None
    config = dict(path=str(path), result=str(result), generation=generation, url=url, db=db,
                  token=token, driver=driver, grace=grace, idle_seconds=idle_seconds,
                  command=command, expected=expected, expected_epoch=expected_epoch)
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
    with world_lock(url, db):
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

    def report(message):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S %z')} ORPHAN GUARD {config['db']}: {message}", flush=True)

    def dead(process):
        pid, stamp = process
        return stamp is None or process_stamp(pid) != stamp

    def current():
        state = read_lease(path)
        return state if state and state["generation"] == config["generation"] else None

    if idle_seconds is None:
        report(f"armed for driver PID {driver[0]} with {config['grace']} s grace")
    else:
        report(f"armed with {idle_seconds:g} s inactivity lease")
    while (state := current()) is not None:
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
