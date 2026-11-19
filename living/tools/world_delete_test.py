#!/usr/bin/env python3
"""Checks of world_delete.pause_and_delete with fake servers: python3 living/tools/world_delete_test.py"""
import world_delete as wd


def run(pause_code, reads, gone_after=True):
    calls = []
    reads = list(reads)
    out = wd.pause_and_delete(
        pause=lambda: (calls.append("pause"), pause_code)[1],
        read=lambda: (calls.append("read"), reads.pop(0) if reads else (200, "false"))[1],
        delete=lambda: calls.append("delete"),
        gone=lambda: gone_after,
        sleep=lambda s: calls.append(f"sleep {s}"))
    return out, calls


# Paused at the second read: waits 1 s between reads, 2 s before the delete, then deletes.
(ok, why), calls = run(200, [(200, "false"), (200, "true")])
assert ok and why == "deleted (SQL now 404)", why
assert calls == ["pause", "read", "sleep 1", "read", "sleep 2.0", "delete"], calls
# Never paused within 10 reads: not deleted, and says why.
(ok, why), calls = run(200, [(200, "false")] * 10)
assert not ok and "could not be read back as paused" in why and "delete" not in calls, (why, calls)
# A 404 at the pause or at a read counts as deleted, with nothing deleted.
(ok, why), calls = run(404, [])
assert ok and "delete" not in calls
(ok, why), calls = run(200, [(404, "")])
assert ok and "delete" not in calls
# Deleted but still answering: reported.
(ok, why), _ = run(200, [(200, "true")], gone_after=False)
assert not ok and "still answers" in why

# Over HTTP, against a fake server (a local http.server): the same rule end to end.
import http.server
import threading


def fake(pauses):
    """A fake SpacetimeDB: `set_paused` is answered 200; SQL reads `paused` as `pauses` says
    (after the pause call, or never); after a delete every request answers 404."""
    state = {"paused": False, "deleted": False, "calls": []}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            state["calls"].append((self.path, body))
            if state["deleted"]:
                code, out = 404, ""
            elif self.path.endswith("/call/set_paused"):
                state["paused"] = pauses
                code, out = 200, ""
            elif self.path.endswith("/sql"):
                code, out = 200, '[{"rows": [[%s]]}]' % ("true" if state["paused"] else "false")
            else:
                code, out = 404, ""
            self.send_response(code)
            self.end_headers()
            self.wfile.write(out.encode())

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


for pauses in (False, True):
    srv, state = fake(pauses)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    deletes = []

    def delete(state=state):
        deletes.append(1)
        state["deleted"] = True

    ok, why = wd.http_pause_and_delete(url, "verify-x", "tok", delete, tries=3, settle_s=0, sleep=lambda s: None)
    srv.shutdown()
    if pauses:
        assert ok and deletes == [1] and why == "deleted (SQL now 404)", (ok, why, deletes)
        assert state["calls"][0][0].endswith("/call/set_paused") and state["calls"][1] == ("/v1/database/verify-x/sql", "SELECT paused FROM world")
    else:
        assert not ok and not deletes and "could not be read back as paused" in why, (ok, why, deletes)
print("world_delete: 7 checks pass (5 with fake callables, 2 against a fake HTTP server)")
