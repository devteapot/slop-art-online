"""Pause, archive and optionally delete one run-owned SpacetimeDB database."""
import hashlib
import json
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import world_guard

REPLICAS = "/home/spacetime/.local/share/spacetime/data/replicas"


def replica_for(endpoint, token, container):
    status, data = world_guard.request(endpoint + "/logs?num_lines=20", token)
    if status != 200:
        raise RuntimeError(f"cannot read database logs to locate its replica (HTTP {status})")
    for line in reversed(data.splitlines()):
        ts = json.loads(line).get("ts")
        if ts is not None:
            break
    else:
        raise RuntimeError("no database log timestamp to locate the replica")
    # Module logs are under the replica's directory and include server-assigned timestamps.
    matches = subprocess.check_output(
        ["docker", "exec", container, "find", REPLICAS, "-path", "*/module_logs/*.log",
         "-exec", "sh", "-c", 'grep -lF "$@" || test "$?" = 1',
         "grep", f'"ts":{int(ts)},', "{}", "+"], text=True, timeout=120)
    replicas = {path.removeprefix(REPLICAS + "/").split("/")[0] for path in matches.splitlines()}
    if len(replicas) != 1 or not re.fullmatch(r"[0-9]+", next(iter(replicas))):
        raise RuntimeError("could not match database logs to exactly one replica")
    return replicas.pop()


def archive(container, replica, db, identity, destination):
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    label = re.sub(r"[^a-zA-Z0-9_-]", "_", db)
    target = destination / f"{label}-{identity[:12]}-{replica}-{stamp}.tar.zst"
    with tempfile.TemporaryDirectory(prefix=".commitlog-", dir=destination) as tmp:
        staged = Path(tmp) / target.name
        with subprocess.Popen(["docker", "exec", container, "tar", "-C", f"{REPLICAS}/{replica}",
                               "-cf", "-", "clog"], stdout=subprocess.PIPE) as tar:
            with tar.stdout:
                subprocess.run(["zstd", "-q", "-o", str(staged)], stdin=tar.stdout, check=True)
            if tar.wait() != 0:
                raise RuntimeError("could not read the replica commitlog")
        subprocess.run(["zstd", "-qt", str(staged)], check=True)
        digest = hashlib.sha256()
        with staged.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        checksum = staged.with_suffix(".zst.sha256")
        checksum.write_text(f"{digest.hexdigest()}  {target.name}\n")
        staged.replace(target)
        checksum.replace(destination / checksum.name)
    return target


def finish(directory, url, container, db, identity, token, *, delete, archive_commitlog=True, destination=None, expected_epoch=None):
    """Leave the database paused on archive failure. Return the archive path on success."""
    with world_guard.world_lock(url, db):
        current = world_guard.lookup(url, db, token)
        if current is None:
            world_guard.stop(directory)
            return None
        if current != identity:
            raise RuntimeError(f"refusing cleanup of {db}: identity differs from run record")
        endpoint = f"{url}/v1/database/{identity}"
        status, state = world_guard.world(endpoint, token)
        if status != 200:
            raise RuntimeError(f"cannot read {db} before cleanup (HTTP {status})")
        if expected_epoch is not None and (not state or state[0] != expected_epoch):
            raise RuntimeError(f"refusing cleanup of {db}: world epoch differs from the run record")
        if state and not state[1]:
            status, _ = world_guard.request(endpoint + "/call/set_paused", token, b"[true]", json_body=True)
            if status != 200:
                raise RuntimeError(f"cannot pause {db} (HTTP {status})")
        for _ in range(10):
            status, state = world_guard.world(endpoint, token)
            if status == 200 and state and state[1] is True:
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"cannot verify {db} is paused")
        # Keep the existing pause/delete settling interval for scheduled reducers.
        time.sleep(2)
        record = None
        if archive_commitlog:
            replica = replica_for(endpoint, token, container)
            record = archive(container, replica, db, identity, destination or Path.home() / "slop-evidence")
            print(f"Archived {db} commitlog to {record}", flush=True)
        if delete:
            subprocess.run(["docker", "exec", container, "spacetime", "delete", "-s", "local",
                            identity, "-y"], check=True, capture_output=True, timeout=120)
            if world_guard.lookup(url, db, token) is not None:
                raise RuntimeError(f"{db} still exists after delete")
        world_guard.stop(directory)
        return record
