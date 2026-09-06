"""Offline subprocess contract tests: fake stdio MCP + deterministic local HTTP, no models.

Run with SAO_WORKER_TEST_BINARY=/absolute/path/participant_live_agent python3 this_file.py.
The fake MCP occupies only a temporary working directory; production binaries are untouched.
"""
import ctypes
import fcntl
import http.server
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import threading
import time
import unittest

PROTOCOL = "sao-external-worker-v1"
BINARY = Path(os.environ["SAO_WORKER_TEST_BINARY"]).resolve()
FAKE_MCP = r'''#!/usr/bin/env python3
import json, os, pathlib, sys, time
root = pathlib.Path.cwd()
with (root / "pids").open("a") as log:
    log.write(str(os.getpid()) + "\n")
count = 0
for line in sys.stdin:
    request = json.loads(line)
    with (root / "requests.jsonl").open("a") as log:
        log.write(json.dumps(request) + "\n")
    mode = (root / "mode").read_text()
    if mode == "malformed":
        print("not-json", flush=True)
        continue
    if request["method"] == "server/discover":
        result = {"fixture": True}
    elif request["method"] == "tools/list":
        result = {"tools": [{"name": "observe"}]}
    else:
        assert request["params"]["name"] == "observe"
        assert request["params"]["arguments"] == {"after_cursor": 0, "limit": 256}
        count += 1
        if mode == "admission_delay":
            def event(kind):
                fd = os.open(root / "overlap.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                os.write(fd, (json.dumps({"event": kind, "pid": os.getpid(), "at": time.monotonic_ns()}) + "\n").encode())
                os.close(fd)
            event("start")
            time.sleep(0.2)
            event("end")
        if mode == "rpc_wait":
            (root / "rpc_started").touch()
            time.sleep(60)
        if mode == "first_observe_error" and count == 1:
            result = {"isError": True, "structuredContent": {"error": "initial state unavailable"}}
        else:
            result = {"structuredContent": {"control_epoch": 1, "latest_cursor": count,
                "context": {"skill_definitions": [], "fixture_observation": count}}}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


class WorkerContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sao-worker-offline-")
        self.root = Path(self.temp.name)
        fake = self.root / "target/debug/sao-agent-mcp"
        fake.parent.mkdir(parents=True)
        fake.write_text(FAKE_MCP)
        fake.chmod(0o755)
        (self.root / "mode").write_text("normal")
        self.http_started = threading.Event()
        self.http_release = threading.Event()
        self.http_requests = []
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                fixture.http_requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                fixture.http_started.set()
                if (fixture.root / "mode").read_text() == "http_wait":
                    fixture.http_release.wait(8)
                reply = json.dumps({"message": {"content": json.dumps({"reason": "offline fixture", "operations": []})},
                                    "done": True, "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(reply)))
                    self.end_headers()
                    self.wfile.write(reply)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"backend": {"kind": "ollama", "model": "fixture",
                                           "endpoint": f"http://127.0.0.1:{self.server.server_port}"},
                                           "deadline_ms": 300000, "max_attempts": 1}))
        self.audit = self.root / "audit"
        self.stderr = (self.root / "worker.log").open("wb")
        self.worker_env = os.environ.copy()
        for name in ["SAO_EXTERNAL_RPC_ADMISSION_DIR", "SAO_EXTERNAL_RPC_CONCURRENCY"]:
            self.worker_env.pop(name, None)
        self.process = subprocess.Popen([str(BINARY), "external-worker", str(self.root / "session.json"), str(self.audit)],
                                        cwd=self.root, env=self.worker_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr)

    def tearDown(self):
        if self.process.poll() is None:
            self.send({"op": "shutdown"})
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.http_release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.stderr.close()
        self.process.stdin.close()
        self.process.stdout.close()
        pids = [int(pid) for pid in (self.root / "pids").read_text().splitlines()] if (self.root / "pids").exists() else []
        for pid in pids:
            self.assertFalse(Path(f"/proc/{pid}").exists(), f"MCP child {pid} not reaped")
        self.temp.cleanup()

    def send(self, message):
        self.process.stdin.write((json.dumps({"protocol": PROTOCOL, **message}) + "\n").encode())
        self.process.stdin.flush()

    def job(self, job_id, role="behavior"):
        self.send({"op": "job", "id": job_id, "config_path": str(self.config),
                   "responsibility": role, "output": f"{job_id:02d}-{role}"})

    def response(self):
        self.assertTrue(select.select([self.process.stdout], [], [], 6)[0], "terminal acknowledgement missing")
        line = self.process.stdout.readline()
        self.assertTrue(line, (self.root / "worker.log").read_text())
        return json.loads(line)

    def wait_file(self, path):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if path.exists():
                return
            time.sleep(0.01)
        self.fail(f"missing fixture marker {path.name}")

    def admission_restart(self, count):
        self.send({"op": "shutdown"})
        self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        directory = self.root / "admission"
        directory.mkdir()
        for index in range(count):
            (directory / f"slot-{index:02d}.lock").touch()
        self.worker_env.update(SAO_EXTERNAL_RPC_ADMISSION_DIR=str(directory),
                               SAO_EXTERNAL_RPC_CONCURRENCY=str(count))
        self.process = self.admission_worker(self.audit)
        return directory

    def admission_worker(self, audit):
        return subprocess.Popen([str(BINARY), "external-worker", str(self.root / "session.json"), str(audit)],
                                cwd=self.root, env=self.worker_env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=self.stderr)

    def submit_to(self, worker):
        worker.stdin.write((json.dumps({"protocol": PROTOCOL, "op": "job", "id": 1,
                            "config_path": str(self.config), "responsibility": "behavior",
                            "output": "01-behavior"}) + "\n").encode())
        worker.stdin.flush()

    def stop_extra(self, worker):
        if worker.poll() is None:
            worker.stdin.write((json.dumps({"protocol": PROTOCOL, "op": "shutdown"}) + "\n").encode())
            worker.stdin.flush()
            worker.wait(timeout=5)
        worker.stdin.close()
        worker.stdout.close()

    def test_admission_caps_four_native_workers_at_two_and_releases(self):
        self.admission_restart(2)
        (self.root / "mode").write_text("admission_delay")
        extras = [self.admission_worker(self.root / f"audit-extra-{i}") for i in range(3)]
        try:
            for worker in [self.process, *extras]:
                self.submit_to(worker)
            for worker in [self.process, *extras]:
                self.assertTrue(select.select([worker.stdout], [], [], 6)[0])
                self.assertEqual(json.loads(worker.stdout.readline())["phase"], "completed")
            events = sorted((json.loads(line) for line in (self.root / "overlap.jsonl").read_text().splitlines()),
                            key=lambda item: item["at"])
            active = peak = 0
            for event in events:
                active += 1 if event["event"] == "start" else -1
                peak = max(peak, active)
                self.assertLessEqual(active, 2)
            self.assertEqual(peak, 2)
            self.assertEqual(active, 0)
            self.assertEqual(len(events), 8)
            for out in [self.audit, *[self.root / f"audit-extra-{i}" for i in range(3)]]:
                audit = json.loads((out / "01-behavior/worker-job.json").read_text())
                requests = audit["mcp"]["requests"]
                self.assertEqual([r["admission_outcome"] for r in requests], ["not_required", "not_required", "acquired"])
                self.assertIn(requests[-1]["admission_slot"], [0, 1])
                self.assertFalse(audit["delivery_may_be_unknown"])
        finally:
            for worker in extras:
                self.stop_extra(worker)

    def test_cancel_while_waiting_for_admission_never_dispatches(self):
        directory = self.admission_restart(1)
        with (directory / "slot-00.lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.job(1)
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                path = self.audit / "01-behavior/worker-job.json"
                try:
                    if json.loads(path.read_text())["setup_phase"] == "observe":
                        break
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                time.sleep(0.01)
            else:
                self.fail("worker did not reach observe admission")
            time.sleep(0.05)
            self.send({"op": "cancel", "id": 1})
            self.assertEqual(self.response()["phase"], "interrupted")
            audit = json.loads(path.read_text())
            event = audit["mcp"]["requests"][-1]
            self.assertEqual(event["admission_outcome"], "cancelled")
            self.assertIsNone(event["id"])
            self.assertIsNone(event["flushed_unix_ms"])
            self.assertFalse(event["delivery_unknown"])
            self.assertFalse(audit["delivery_may_be_unknown"])
            requests = [json.loads(line) for line in (self.root / "requests.jsonl").read_text().splitlines()]
            self.assertEqual([r["method"] for r in requests], ["server/discover", "tools/list"])
            self.assertEqual(len(self.http_requests), 0)

    @unittest.skipUnless(Path("/proc/self").exists(), "Linux child-reaper contract")
    def test_native_worker_death_releases_slot_before_child_cleanup(self):
        libc = ctypes.CDLL(None, use_errno=True)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)  # Adopt this test's orphan MCP for explicit reap.
        self.admission_restart(1)
        (self.root / "mode").write_text("rpc_wait")
        self.job(1)
        self.wait_file(self.root / "rpc_started")
        orphan = int((self.root / "pids").read_text().strip())
        self.process.kill()
        self.process.wait(timeout=5)
        (self.root / "mode").write_text("normal")
        second = self.admission_worker(self.root / "audit-after-death")
        try:
            self.submit_to(second)
            self.assertTrue(select.select([second.stdout], [], [], 6)[0], "dead worker retained admission slot")
            self.assertEqual(json.loads(second.stdout.readline())["phase"], "completed")
            self.assertTrue(Path(f"/proc/{orphan}").exists(), "original MCP must still exist during slot-release check")
        finally:
            self.stop_extra(second)
            os.kill(orphan, signal.SIGKILL)
            os.waitpid(orphan, 0)
            self.assertEqual(libc.prctl(36, 0, 0, 0, 0), 0)

    def test_two_jobs_use_one_child_and_fresh_context(self):
        self.assertFalse((self.root / "pids").exists())
        for job_id, role in [(1, "behavior"), (2, "communication")]:
            self.job(job_id, role)
            response = self.response()
            self.assertEqual(response["phase"], "completed", response)
            self.assertTrue(response["worker_reusable"])
        self.assertEqual(len((self.root / "pids").read_text().splitlines()), 1)
        requests = [json.loads(line) for line in (self.root / "requests.jsonl").read_text().splitlines()]
        self.assertEqual([r["id"] for r in requests], list(range(1, 7)))
        self.assertEqual(len(self.http_requests), 2)
        instance = None
        for job_id, role in [(1, "behavior"), (2, "communication")]:
            out = self.audit / f"{job_id:02d}-{role}"
            audit = json.loads((out / "worker-job.json").read_text())
            self.assertEqual(audit["mcp_reused"], job_id == 2)
            self.assertEqual(audit["mcp"]["pid"], int((self.root / "pids").read_text().strip()))
            if instance is None:
                instance = audit["mcp"]["instance"]
            self.assertEqual(audit["mcp"]["instance"], instance)
            for request in audit["mcp"]["requests"]:
                self.assertGreaterEqual(request["flushed_unix_ms"], request["started_unix_ms"])
                self.assertEqual(request["outcome"], "returned")
                self.assertEqual(request["admission_outcome"], "disabled")
                self.assertFalse(request["delivery_unknown"])
                self.assertLess(request["elapsed_ms"], request["deadline_ms"])
            self.assertEqual(audit["rpc_id_before"], (job_id - 1) * 3)
            self.assertEqual([r["deadline_ms"] for r in audit["mcp"]["requests"]], [15000] * 3)
            record = json.loads((out / "external.json").read_text())
            self.assertEqual(record["participant_context"]["context"]["fixture_observation"], job_id)
            self.assertEqual(record["request"], self.http_requests[job_id - 1])

    def test_application_setup_failure_retains_child_for_next_observe(self):
        (self.root / "mode").write_text("first_observe_error")
        self.job(1)
        ack = self.response()
        self.assertEqual(ack["phase"], "failed")
        self.assertTrue(ack["worker_reusable"])
        self.assertFalse((self.audit / "01-behavior/external.json").exists())
        self.assertEqual(len(self.http_requests), 0)
        self.job(2, "learning")
        self.assertEqual(self.response()["phase"], "completed")
        self.assertEqual(len((self.root / "pids").read_text().splitlines()), 1)
        self.assertEqual(len(self.http_requests), 1)
        context = json.loads((self.audit / "02-learning/external.json").read_text())["participant_context"]
        self.assertEqual(context["context"]["fixture_observation"], 2)

    def test_malformed_frame_stops_transport_without_respawn(self):
        (self.root / "mode").write_text("malformed")
        for job_id in [1, 2]:
            self.job(job_id)
            ack = self.response()
            self.assertEqual(ack["phase"], "failed")
            self.assertFalse(ack["worker_reusable"])
        self.assertEqual(len((self.root / "pids").read_text().splitlines()), 1)
        self.assertEqual(len(self.http_requests), 0)

    def test_cancel_during_rpc_reaps_child_and_marks_unknown_delivery(self):
        (self.root / "mode").write_text("rpc_wait")
        self.job(1)
        self.wait_file(self.root / "rpc_started")
        self.send({"op": "cancel", "id": 1, "reason": "test cancellation"})
        ack = self.response()
        self.assertEqual(ack["phase"], "interrupted")
        self.assertFalse(ack["worker_reusable"])
        audit = json.loads((self.audit / "01-behavior/worker-job.json").read_text())
        self.assertTrue(audit["delivery_may_be_unknown"])
        self.assertFalse((self.audit / "01-behavior/external.json").exists())

    def test_sigterm_during_provider_retains_journal_and_reaps_child(self):
        (self.root / "mode").write_text("http_wait")
        self.job(1)
        self.assertTrue(self.http_started.wait(6))
        self.process.send_signal(signal.SIGTERM)
        ack = self.response()
        self.assertEqual(ack["phase"], "interrupted")
        self.assertFalse(ack["worker_reusable"])
        self.process.wait(timeout=5)
        external = json.loads((self.audit / "01-behavior/external.json").read_text())
        self.assertEqual(external["phase"], "interrupted")
        self.assertIn("cancelled", external["reply"]["error"])
        self.assertEqual(len(self.http_requests), 1)

    def test_python_supervisor_to_native_worker_compatibility(self):
        # Reuse this exact fixture with the pilot's actual supervisor class.
        self.send({"op": "shutdown"})
        self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        helper_path = Path(__file__).resolve().parents[4] / "scripts/external_worker.py"
        spec = importlib.util.spec_from_file_location("sao_external_worker_under_test", helper_path)
        helper_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper_module)
        helper = helper_module.ExternalWorker(
            [str(BINARY), "external-worker", str(self.root / "session.json"), str(self.audit)],
            cwd=self.root, env=self.worker_env, log_path=self.root / "supervisor-worker.log")
        (self.root / "mode").write_text("first_observe_error")
        try:
            first = helper.run(1, "behavior", self.config, "01-behavior",
                               deadline=time.monotonic() + 6, cancelled=lambda: False, alive=lambda: True)
            self.assertEqual(first["phase"], "failed", first)
            self.assertTrue(first["worker_reusable"])
            second = helper.run(2, "communication", self.config, "02-communication",
                                deadline=time.monotonic() + 6, cancelled=lambda: False, alive=lambda: True)
            self.assertEqual(second["phase"], "completed", second)
            self.assertTrue(second["worker_reusable"])
            self.assertEqual(first["worker_pid"], second["worker_pid"])
            self.assertEqual(len((self.root / "pids").read_text().splitlines()), 1)
            self.assertEqual(len(self.http_requests), 1)
        finally:
            helper.stop()
            if helper.process is not None:
                self.process = helper.process
        self.assertIsNone(helper.cleanup_error)
        self.assertFalse(helper.reader.is_alive())
        self.assertEqual(self.process.returncode, 0)

    def test_busy_job_is_not_queued(self):
        (self.root / "mode").write_text("rpc_wait")
        self.job(1)
        self.wait_file(self.root / "rpc_started")
        self.job(2)
        self.assertEqual(self.response()["phase"], "interrupted")
        self.assertNotEqual(self.process.wait(timeout=5), 0)
        self.assertFalse((self.audit / "02-behavior").exists())
        self.assertEqual(len(self.http_requests), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
