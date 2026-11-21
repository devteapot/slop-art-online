#!/usr/bin/env python3
"""Run the scheduled trial maintenance window on Spark."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import uuid

import trial_archive
import trial_reclaim as reclaim
import world_guard

CHECK_TIMER = "slop-timer-check.timer"
CLEAN_TIMER = "slop-disk-clean.timer"
CLEAN_SERVICE = "slop-disk-clean.service"
TIMERS = (CHECK_TIMER, CLEAN_TIMER)


def systemctl(*args, check=True):
    return subprocess.run(["systemctl", "--user", *args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)


def log(message):
    with (reclaim.QUEUE / "disk-alarm.log").open("a") as stream:
        print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} trial reclaim: {message}", file=stream)
    subprocess.run(["logger", "-t", "slop-trial-reclaim", "--", message], check=True, timeout=10)


def trigger(now, hourly_log):
    if now.hour == 4:
        return "daily quiet window"
    try:
        with hourly_log.open() as stream:
            last = None
            for line in stream:
                if match := re.fullmatch(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) trial volume (\d+(?:\.\d+)?) GB\s*", line):
                    last = match.groups()
    except FileNotFoundError:
        return None
    if last:
        observed = datetime.fromisoformat(last[0]).astimezone()
        if 0 <= (now - observed).total_seconds() <= 90 * 60 and float(last[1]) > 140:
            return f"hourly volume log reported {last[1]} GB"
    return None


@contextmanager
def timer_window(hold):
    owned = None
    try:
        with hold.open("x") as stream:
            stream.write("scheduled trial reclaim\n")
            owned = os.fstat(stream.fileno())
    except FileExistsError:
        pass
    try:
        for timer in TIMERS:
            systemctl("stop", timer)
        for timer in (*TIMERS, CLEAN_SERVICE):
            if systemctl("is-active", timer, check=False).stdout.strip() != "inactive":
                raise RuntimeError(f"{timer} did not become inactive")
        yield
    finally:
        cleaner_failed = False
        try:
            cleaner_failed = systemctl("start", CLEAN_SERVICE, check=False).returncode != 0
        except (OSError, subprocess.SubprocessError):
            cleaner_failed = True
        systemctl("restart", CLEAN_TIMER, CHECK_TIMER)
        listing = systemctl("list-timers", "--all", "--no-legend", "--no-pager", *TIMERS).stdout
        for timer in TIMERS:
            if not any(timer in row.split() and row.split()[0] != "-" for row in listing.splitlines() if row.split()):
                raise RuntimeError(f"timer has no NEXT activation: {timer}")
        if owned is not None:
            try:
                current = hold.stat(follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                    hold.unlink()
            except FileNotFoundError:
                pass
        if cleaner_failed:
            raise RuntimeError("disk-clean service failed during timer restoration")


def smoke(reader, wasm, directory):
    name = f"verify-gate-reclaim-{uuid.uuid4().hex[:12]}"
    cli = ("docker", "exec", reclaim.SERVER, "spacetime")
    raw = reclaim.command(*cli, "login", "show", "--token", text=True, timeout=30)
    match = re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", raw)
    if not match:
        raise RuntimeError("could not read the smoke database administrator token")
    token = match[0]
    if world_guard.lookup(reclaim.URL, name, token) is not None:
        raise RuntimeError("smoke database name already exists")
    reclaim.command(*cli, "publish", "-s", "local", "-b", wasm, name, "-y", timeout=180)
    identity = world_guard.lookup(reclaim.URL, name, token)
    if not identity:
        raise RuntimeError("smoke publication did not resolve")
    endpoint = f"{reclaim.URL}/v1/database/{identity}"
    try:
        status, row = world_guard.world(endpoint, token)
        if status != 200 or not row:
            raise RuntimeError(f"smoke SQL failed (HTTP {status})")
    finally:
        world_guard.request(endpoint + "/call/set_paused", token, b"[true]", json_body=True)
        status, paused = world_guard.world(endpoint, token)
        if status != 200 or not paused or paused[1] is not True:
            raise RuntimeError("smoke pause could not be confirmed")
        control, _ = reclaim.collect_metadata(reader, running=True, include_snapshots=False)
        owners = {key for key, db in control["databases"].items() if db["identity"] == identity}
        replicas = [key for key, owner in control["replicas"].items() if str(owner) in owners]
        if len(replicas) != 1:
            raise RuntimeError("smoke replica could not be uniquely identified")
        archive = trial_archive.archive(reclaim.SERVER, replicas[0], name, identity, directory)
        if not reclaim.verify_existing(replicas[0], [(archive, None)], running=True):
            raise RuntimeError("smoke archive verification failed")
        trial_archive.finish(directory, reclaim.URL, reclaim.SERVER, name, identity, token,
                             delete=True, archive_commitlog=False, expected_epoch=paused[0])
    return {"database": name, "archive": str(archive), "sql": 200, "paused": True, "deleted": True}


def volume():
    return float(reclaim.command(str(reclaim.ROOT / "trial_volume_size.sh"), text=True, timeout=180))


def load_blockers(max_load):
    load = os.getloadavg()[0]
    return [f"one-minute load {load:.2f} exceeds {max_load:g}"] if load > max_load else []


def run(max_load, wasm):
    now = datetime.now().astimezone()
    reason = trigger(now, reclaim.QUEUE / "trial-volume.log")
    if not reason:
        log("skip: outside daily window and no recent reading above 140 GB")
        return 0
    with reclaim.maintenance_locks() as locks:
        problems = locks + reclaim.blockers() + load_blockers(max_load)
        if problems:
            log("skip: " + "; ".join(problems))
            return 0
        reclaim.preflight()
        reader = reclaim.metadata_reader()
        control, _ = reclaim.collect_metadata(reader, running=True, include_snapshots=False)
        if problems := reclaim.quiet_worlds(control):
            log("skip: " + "; ".join(problems))
            return 0
        output = reclaim.EVIDENCE / f"reclaim-scheduled-{now:%Y%m%dT%H%M%S%z}.json"
        with timer_window(reclaim.QUEUE / "HOLD"):
            if os.getloadavg()[0] > max_load:
                log("skip: load rose during preflight")
                return 0
            reclaim.command("docker", "exec", reclaim.SERVER, "test", "-r", wasm, timeout=30)
            before = volume()
            status = reclaim.main(["--apply", "--output", str(output)], locks_held=True, scheduled=True,
                                  extra_guards=lambda: load_blockers(max_load))
            record = json.loads(output.read_text())
            if record.get("skipped"):
                log(f"skip: {'; '.join(record['blockers'])}; {output}")
                return 0
            if status and not record["removed"]:
                log(f"failed: {'; '.join(record['blockers'])}; {output}")
                return status
            after = volume()
            log(f"{reason}; volume {before:.3f} -> {after:.3f} GB, freed {before-after:.3f} GB; {output}")
            record.update(volume_before_gb=before, volume_after_gb=after, volume_freed_gb=round(before-after, 3))
            reclaim.write_json(record, output)
            if status:
                return status
            current, _ = reclaim.collect_metadata(reader, running=True, include_snapshots=False)
            if control["databases"] != current["databases"] or (problems := reclaim.quiet_worlds(current)):
                raise RuntimeError("kept worlds changed or pause could not be verified")
            record["smoke"] = smoke(reader, wasm, output.with_suffix(""))
            reclaim.write_json(record, output)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-load", type=float, default=2)
    parser.add_argument("--wasm", default="/wasm/trial-island-0265d69b.wasm")
    args = parser.parse_args()
    def interrupt(_signum, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise RuntimeError("terminated during scheduled reclaim")
    signal.signal(signal.SIGTERM, interrupt)
    try:
        return run(args.max_load, args.wasm)
    except Exception as error:
        log(f"failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
