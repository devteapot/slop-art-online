#!/usr/bin/env python3
"""Exercise the detached lease guard without a SpacetimeDB server.

    python3 living/tools/verify_lease_selftest.py

Cases: an idle verification lease pauses its world; the disk floor (docs/TRIAL_DISK.md) pauses a
driver-bound world at once, writes world-guard-disk.json, keeps guarding and pauses a world unpaused
while the disk is still low; with the floor at 0 nothing is read or paused.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import world_guard

IDENTITY = "c200" + "0" * 60
DATABASE = "verify-lease-selftest"
WINDOW = 2


class Authority(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply({"database_identity": {"__identity__": IDENTITY}})

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path.endswith("/call/set_paused"):
            self.server.paused.set()
            self.reply([])
        else:
            assert body == b"SELECT epoch_ms, paused FROM world"
            self.reply([{"rows": [[123, self.server.paused.is_set()]]}])


class LeaseTest(unittest.TestCase):
    def test_launcher_exits_while_run_renews_lease(self):
        with tempfile.TemporaryDirectory() as tmp, ThreadingHTTPServer(("127.0.0.1", 0), Authority) as authority:
            directory = Path(tmp)
            authority.paused = threading.Event()
            server = threading.Thread(target=authority.serve_forever, daemon=True)
            server.start()
            url = f"http://127.0.0.1:{authority.server_port}"
            try:
                subprocess.run([sys.executable, __file__, "--launch", tmp, url],
                               check=True, timeout=10, env=dict(os.environ, SLOP_GUARD_FREE_FLOOR_GB="0"))
                lease = world_guard.read_lease(world_guard.lease(directory))
                self.assertIsNone(lease["driver"])
                # The launcher has exited. Renew for multiple inactivity windows.
                until = time.monotonic() + WINDOW * 2
                while time.monotonic() < until:
                    world_guard.refresh(directory, url, DATABASE, IDENTITY)
                    self.assertFalse(authority.paused.wait(0.2), "world paused during active renewal")
                world_guard.refresh(directory, url, DATABASE, IDENTITY)
                self.assertFalse(authority.paused.wait(WINDOW / 2))
                self.assertTrue(authority.paused.wait(WINDOW + 3), "idle world never paused")
            finally:
                world_guard.stop(directory)
                authority.shutdown()
                server.join()


    def guarded(self, floor):
        """A driver-bound guard (this process) on a fake world, with the given disk floor."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        authority = ThreadingHTTPServer(("127.0.0.1", 0), Authority)
        authority.paused = threading.Event()
        threading.Thread(target=authority.serve_forever, daemon=True).start()
        self.addCleanup(authority.server_close)
        self.addCleanup(authority.shutdown)
        directory = Path(tmp.name)
        self.addCleanup(world_guard.stop, directory)
        old = os.environ.get("SLOP_GUARD_FREE_FLOOR_GB")
        os.environ["SLOP_GUARD_FREE_FLOOR_GB"] = str(floor)
        try:
            world_guard.arm(directory, f"http://127.0.0.1:{authority.server_port}", DATABASE, "fixture",
                            os.getpid(), expected=IDENTITY)
        finally:
            os.environ.pop("SLOP_GUARD_FREE_FLOOR_GB") if old is None else os.environ.update(SLOP_GUARD_FREE_FLOOR_GB=old)
        return directory, authority

    def test_disk_floor_pauses_and_keeps_guarding(self):
        # A floor no disk reaches: the first reading is under it.
        directory, authority = self.guarded(1e9)
        self.assertTrue(authority.paused.wait(5), "world not paused under the disk floor")
        marker = directory / "world-guard-disk.json"
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        state = json.loads(marker.read_text())
        self.assertEqual((state["floor_gb"], state["db"]), (1e9, DATABASE))
        # Unpaused by someone while the disk is still low: paused again on the next reading.
        authority.paused.clear()
        self.assertTrue(authority.paused.wait(world_guard.DISK_EVERY_S + 4), "an unpaused world was not paused again")
        deadline = time.monotonic() + 3  # the guard logs just after its pause call
        while "PAUSED AGAIN" not in (log := (directory / "world-guard.log").read_text()) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertIn("PAUSED AND VERIFIED by SQL (disk floor)", log)
        self.assertIn("PAUSED AGAIN", log)

    def test_floor_zero_reads_nothing(self):
        directory, authority = self.guarded(0)
        self.assertFalse(authority.paused.wait(3), "paused with the floor off")
        self.assertNotIn("disk floor", (directory / "world-guard.log").read_text())


if __name__ == "__main__":
    if sys.argv[1:2] == ["--launch"]:
        world_guard.arm(Path(sys.argv[2]), sys.argv[3], DATABASE, "fixture",
                        expected=IDENTITY, idle_seconds=WINDOW)
    else:
        unittest.main()
