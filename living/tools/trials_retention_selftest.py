#!/usr/bin/env python3
"""Exercise PID loss and archive-before-delete against a dedicated retention scratch server."""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import trial_archive
import world_guard


def wait(predicate, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if value := predicate():
            return value
        time.sleep(0.2)
    raise AssertionError("timed out waiting for retention check")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--grace", type=int, default=world_guard.GRACE_SECONDS)
    parser.add_argument("--driver", action="store_true")
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    container = "slop-retention-stdb"
    mapping = subprocess.check_output(["docker", "port", container, "3000/tcp"], text=True)
    assert mapping.strip() == f"127.0.0.1:{args.port}", mapping
    url = f"http://127.0.0.1:{args.port}"
    suffix = directory.name.rsplit(".", 1)[-1].lower()
    assert re.fullmatch(r"[a-z0-9]+", suffix)
    db = f"verify-trial-retention-selftest-{suffix}"
    cli = ["docker", "exec", container, "spacetime"]
    login = subprocess.check_output([*cli, "login", "show", "--token"], text=True)
    token = re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", login)[0]
    ready = directory / "ready.json"
    publish = [*cli, "publish", "-s", "local", "-b", "/tmp/retention.wasm"]
    if args.driver:
        published = world_guard.arm(directory, url, db, token, os.getpid(),
                                   command=[*publish, db, "-y"], grace=args.grace)
        ready.write_text(json.dumps(published))
        signal.pause()
        return
    assert world_guard.lookup(url, db, token) is None
    assert not ready.exists()
    other = f"{db}-other"
    subprocess.run([*publish, other, "-y"], check=True, capture_output=True)
    other_id = world_guard.lookup(url, other, token)
    other_endpoint = f"{url}/v1/database/{other_id}"
    with subprocess.Popen([sys.executable, __file__, str(directory), "--port", str(args.port),
                           "--grace", str(args.grace), "--driver"]) as driver:
        try:
            def driver_ready():
                if driver.poll() is not None:
                    raise RuntimeError("fake driver exited before arming")
                return ready.exists()

            wait(driver_ready, 180)
            published = json.loads(ready.read_text())
            identity = published["identity"]
            endpoint = f"{url}/v1/database/{identity}"
            assert world_guard.world(endpoint, token)[1][1] is False
            started = time.monotonic()
            os.kill(driver.pid, signal.SIGKILL)
            driver.wait(timeout=5)
            guard_log = directory / "world-guard.log"
            wait(lambda: "PAUSED AND VERIFIED" in guard_log.read_text(), args.grace + 15)
            assert world_guard.world(endpoint, token)[1][1] is True
            print(f"PASS driver PID {driver.pid} killed and world paused in {time.monotonic() - started:.1f} s", flush=True)
            assert world_guard.world(other_endpoint, token)[1][1] is False
            print("PASS unrelated database stayed unpaused", flush=True)
            bad = directory / "blocked-destination"
            bad.touch()
            try:
                trial_archive.finish(directory, url, container, db, identity, token, delete=True, destination=bad)
            except FileExistsError:
                assert world_guard.lookup(url, db, token) == identity
                assert world_guard.world(endpoint, token)[1][1] is True
                print("PASS archive failure preserved the paused database", flush=True)
            else:
                raise AssertionError("archive unexpectedly succeeded with a blocked destination")
            archive = trial_archive.finish(directory, url, container, db, identity, token,
                                           delete=True, destination=directory, expected_epoch=published["epoch"])
            subprocess.run(["sha256sum", "-c", archive.with_suffix(".zst.sha256").name],
                           cwd=directory, check=True)
            subprocess.run(["zstd", "-t", str(archive)], check=True)
            listing = subprocess.check_output(["tar", "--zstd", "-tf", str(archive)], text=True)
            assert ".stdb.log" in listing, listing
            assert world_guard.lookup(url, db, token) is None
            print("PASS verified the commitlog archive and database deletion", flush=True)
        finally:
            if driver.poll() is None:
                os.kill(driver.pid, signal.SIGKILL)
                driver.wait(timeout=5)
    mind_dir = directory / "mind-loss"
    mind_dir.mkdir()
    world_guard.arm(mind_dir, url, other, token, os.getpid(), expected=other_id, grace=3)
    with subprocess.Popen([sys.executable, "-c", "import signal; signal.pause()"]) as mind:
        try:
            world_guard.set_mind(mind_dir, mind.pid)
        finally:
            os.kill(mind.pid, signal.SIGKILL)
            mind.wait(timeout=5)
    mind_log = mind_dir / "world-guard.log"
    wait(lambda: "PAUSED AND VERIFIED" in mind_log.read_text(), 15)
    assert f"mind PID {mind.pid} exited" in mind_log.read_text()
    assert world_guard.world(other_endpoint, token)[1][1] is True
    print("PASS mind PID loss paused its world while the driver stayed alive", flush=True)
    trial_archive.finish(mind_dir, url, container, other, other_id, token, delete=True, destination=directory)


if __name__ == "__main__":
    main()
