#!/usr/bin/env python3
"""Own the driver group independently of the calling wrapper's lifetime."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


def group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def signal_group(pgid, signum):
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        pass


def reap(driver):
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if not pid:
            return
        if pid == driver.pid:
            driver.returncode = os.waitstatus_to_exitcode(status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--deadline', type=float, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.deadline <= 0 or not args.command:
        parser.error('positive deadline and driver command required')
    # Reap orphaned grandchildren too, so a killed driver cannot leave a zombie group.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError('Linux child-subreaper support required')
    end = time.monotonic() + args.deadline
    with (args.directory / 'duel-driver.log').open('w') as stream:
        driver = subprocess.Popen(args.command, stdout=stream, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        pgid = driver.pid
        record = {'guardian_pid': os.getpid(), 'driver_pid': driver.pid, 'pgid': pgid,
                  'deadline_s': args.deadline}
        (args.directory / 'duel-process.json').write_text(json.dumps(record, indent=2))
        try:
            while driver.poll() is None:
                if time.monotonic() >= end:
                    record['reason'] = 'watchdog deadline'
                    break
                if select.select([sys.stdin], [], [], 0.1)[0] and not os.read(0, 1):
                    record['reason'] = 'wrapper exited'
                    break
            else:
                record['reason'] = 'driver exited'
            record['driver_exit_before_cleanup'] = driver.poll()
        finally:
            # Check the group even when its leader has exited.
            if group_exists(pgid):
                signal_group(pgid, signal.SIGTERM)
            until = time.monotonic() + 2
            while group_exists(pgid) and time.monotonic() < until:
                driver.poll()
                reap(driver)
                time.sleep(0.05)
            if group_exists(pgid):
                signal_group(pgid, signal.SIGKILL)
                record['escalated'] = True
            driver.wait(timeout=5)
            until = time.monotonic() + 5
            while group_exists(pgid) and time.monotonic() < until:
                reap(driver)
                time.sleep(0.05)
            record['group_gone'] = not group_exists(pgid)
            record['driver_exit'] = driver.returncode
            (args.directory / 'duel-cleanup.json').write_text(json.dumps(record, indent=2))
    return 0 if record['group_gone'] and record['reason'] == 'driver exited' and driver.returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
