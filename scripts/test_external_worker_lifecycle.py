"""Isolated Linux process-lifecycle regressions; no authority or model calls."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import external_worker


def process_identity(pid):
    """Read identity without reaping the worker's process-group leader."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return None
    return {"pid": pid, "state": fields[0], "group": int(fields[2]), "start": fields[19]}


def wait_until(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("fixture did not reach its expected state")
        time.sleep(.01)


def wait_for_exit_without_reaping(pid):
    wait_until(lambda: os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None)


def save_owned_process(folder, name, pid):
    identity = process_identity(pid)
    assert identity is not None
    (folder / name).write_text(json.dumps(identity))


def force_fixture_cleanup(folder):
    """Timeout fallback signals only groups with a surviving recorded identity."""
    groups = set()
    for name in ("worker-identity.json", "child-identity.json"):
        path = folder / name
        if path.exists():
            recorded = json.loads(path.read_text())
            current = process_identity(recorded["pid"])
            if current and current["start"] == recorded["start"] and current["group"] == recorded["group"]:
                groups.add(recorded["group"])
    for group in groups:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass


RECORDER = r"""
import json, pathlib, sys
folder = pathlib.Path(sys.argv[1])
for line in sys.stdin:
    value = json.loads(line)
    with (folder / 'received.jsonl').open('a') as stream:
        stream.write(json.dumps(value) + '\n')
    if value['op'] == 'shutdown':
        break
"""

ORPHAN_LEADER = r"""
import pathlib, subprocess, sys, time
folder = pathlib.Path(sys.argv[1])
child = subprocess.Popen([sys.executable, '-c', '''
import os, pathlib, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(60)
''', str(folder / 'child.pid')])
while not (folder / 'child.pid').exists():
    time.sleep(.01)
"""


def run_scenario(name, folder):
    command = [sys.executable, "-c", ORPHAN_LEADER if name == "exited_leader" else
               "pass" if name == "closed_pipe" else RECORDER, str(folder)]
    worker = external_worker.ExternalWorker(command, cwd=folder, env=os.environ.copy(),
                                             log_path=folder / "worker.log")
    if name == "exited_leader":
        worker._start()
        save_owned_process(folder, "worker-identity.json", worker.process.pid)
        wait_for_exit_without_reaping(worker.process.pid)
        child_pid = int((folder / "child.pid").read_text())
        save_owned_process(folder, "child-identity.json", child_pid)
        started = time.monotonic()
        worker.stop(grace=.05)
        elapsed = time.monotonic() - started
        wait_until(lambda: (process_identity(child_pid) or {}).get("state") in (None, "Z"))
        return {"elapsed": elapsed, "cleanup_error": worker.cleanup_error,
                "returncode": worker.process.returncode, "reader_alive": worker.reader.is_alive(),
                "child_alive": (process_identity(child_pid) or {}).get("state") not in (None, "Z")}

    cancelled = [False]
    alive = [True]
    clock_reads = []
    clock = SimpleNamespace(monotonic=lambda: clock_reads.pop(0) if clock_reads else time.monotonic(),
                            sleep=time.sleep)
    deadline = clock.monotonic() + 30

    def on_start(process):
        save_owned_process(folder, "worker-identity.json", process.pid)
        if name == "cancel_during_start":
            cancelled[0] = True
        elif name == "actor_dies_during_start":
            alive[0] = False
        elif name == "deadline_during_start":
            # Equality must already forbid dispatch; cleanup uses real time.
            clock_reads.append(deadline)
        elif name == "closed_pipe":
            wait_for_exit_without_reaping(process.pid)
        else:
            raise AssertionError(f"unknown scenario: {name}")

    with patch.object(external_worker, "time", clock):
        result = worker.run(1, "behavior", folder / "unused-config.json", str(folder / "unused-output"),
                            deadline=deadline, cancelled=lambda: cancelled[0], alive=lambda: alive[0],
                            on_start=on_start)
    # Repeated cleanup must remain harmless after a broken pipe or cancellation.
    worker.stop(grace=.05)
    received = folder / "received.jsonl"
    operations = [json.loads(line)["op"] for line in received.read_text().splitlines()] if received.exists() else []
    return {"result": result, "operations": operations, "cleanup_error": worker.cleanup_error,
            "returncode": worker.process.returncode, "reader_alive": worker.reader.is_alive(),
            "log_closed": worker.log is None}


@unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os, "WNOWAIT"),
                     "worker group ownership uses Linux waitid(WNOWAIT)")
class ExternalWorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        # Deliberately avoid /tmp: inherited pipes and timeout diagnostics need
        # small, durable files even on hosts with a full tmpfs quota.
        temp_root = Path(os.environ.get("SAO_TEST_TMPDIR", Path.home() / ".cache" / "sao-m7-8-tmp"))
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="worker-lifecycle-", dir=temp_root)
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def scenario(self, name):
        folder = self.folder / name
        folder.mkdir()
        runner = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--scenario", name, str(folder)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  start_new_session=True)
        timed_out = False
        try:
            try:
                stdout, stderr = runner.communicate(timeout=6)
            except subprocess.TimeoutExpired:
                timed_out = True
                force_fixture_cleanup(folder)
                try:
                    stdout, stderr = runner.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(runner.pid, signal.SIGKILL)
                    stdout, stderr = runner.communicate(timeout=2)
            self.assertFalse(timed_out, f"{name} exceeded bounded cleanup; stderr={stderr!r}")
            self.assertEqual(runner.returncode, 0, stderr)
            return json.loads(stdout)
        finally:
            force_fixture_cleanup(folder)
            if runner.poll() is None:
                os.killpg(runner.pid, signal.SIGKILL)
                runner.communicate(timeout=2)

    def test_startup_cancellation_actor_death_and_deadline_never_dispatch_job(self):
        for name in ("cancel_during_start", "actor_dies_during_start", "deadline_during_start"):
            with self.subTest(boundary=name):
                result = self.scenario(name)
                self.assertEqual(result["result"]["phase"], "interrupted")
                self.assertFalse(result["result"]["worker_reusable"])
                self.assertEqual(result["operations"], ["shutdown"])
                self.assertIsNone(result["cleanup_error"])
                self.assertFalse(result["reader_alive"])
                self.assertTrue(result["log_closed"])

    def test_exited_unreaped_leader_does_not_leave_child_or_block_reader_close(self):
        result = self.scenario("exited_leader")
        self.assertLess(result["elapsed"], 2)
        self.assertEqual(result["returncode"], 0)
        self.assertIsNone(result["cleanup_error"])
        self.assertFalse(result["child_alive"])
        self.assertFalse(result["reader_alive"])

    def test_worker_exit_before_dispatch_returns_failure_and_closes_broken_pipe(self):
        result = self.scenario("closed_pipe")
        self.assertEqual(result["result"]["phase"], "failed")
        self.assertFalse(result["result"]["worker_reusable"])
        self.assertIn("persistent worker unavailable", result["result"]["error"])
        self.assertIsNone(result["cleanup_error"])
        self.assertFalse(result["reader_alive"])
        self.assertTrue(result["log_closed"])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--scenario":
        print(json.dumps(run_scenario(sys.argv[2], Path(sys.argv[3]))))
    else:
        unittest.main()
