#!/usr/bin/env python3
"""Exercise the detached lease guard without a SpacetimeDB server."""
import json
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
                               check=True, timeout=10)
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


if __name__ == "__main__":
    if sys.argv[1:2] == ["--launch"]:
        world_guard.arm(Path(sys.argv[2]), sys.argv[3], DATABASE, "fixture",
                        expected=IDENTITY, idle_seconds=WINDOW)
    else:
        unittest.main()
