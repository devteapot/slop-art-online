#!/usr/bin/env python3
"""gate_server.py's probe on a fake `docker` (docs/TOOLING.md, "The gate's server").

    python3 living/tools/gate_server_selftest.py

A fake `docker` on PATH answers `inspect` and `exec` as each case needs; a local HTTP server
stands in for /v1/ping. Cases:
- a healthy server: check exits 0;
- running, but every exec fails with "transport endpoint is not connected" (the overlay helper
  died): check exits 14 and names it;
- not running: 14;
- exec works but /v1/ping does not answer: 14;
- stop refuses a trial or reference server's name.
The live cases (start, stop clearing a deleted database's replica and keeping them while one is
listed, merge.py and gate_merge.sh refusing at once) were run on a scratch server for
queue-fail-fast and are in its commit and docs/TOOLING.md.
"""

import http.server
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAKE = r"""#!/usr/bin/env bash
case "$1" in
  inspect) echo "${FAKE_RUNNING:-true}"; exit 0 ;;
  exec) if [ "${FAKE_EXEC:-ok}" = ok ]; then exit 0; fi
        echo "Error: crun: chdir to /home/spacetime: Transport endpoint is not connected: OCI runtime attempted to invoke a command that was not found" >&2; exit 126 ;;
  *) exit 0 ;;
esac
"""


class Ping(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/v1/ping" else 404)
        self.end_headers()

    def log_message(self, *a):
        pass


def main():
    fails = 0

    def case(name, ok, detail=""):
        nonlocal fails
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" ({detail})" if detail else ""))
        fails += 0 if ok else 1

    srv = http.server.HTTPServer(("127.0.0.1", 0), Ping)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    live = f"http://127.0.0.1:{srv.server_address[1]}"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "docker").write_text(FAKE)
        (Path(d) / "docker").chmod(0o755)

        def check(url=live, **env):
            e = dict(os.environ, PATH=f"{d}:{os.environ['PATH']}", **env)
            r = subprocess.run([sys.executable, str(HERE / "gate_server.py"), "check", "--container", "gate-test", "--url", url],
                               env=e, capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr

        rc, out = check()
        case("a healthy server answers", rc == 0, out.strip())
        rc, out = check(FAKE_EXEC="fail")
        case("running, every exec failing: 14, named", rc == 14 and "Transport endpoint is not connected" in out, out.strip()[:120])
        rc, out = check(FAKE_RUNNING="false")
        case("not running: 14", rc == 14 and "not running" in out)
        rc, out = check(url="http://127.0.0.1:9")
        case("exec works, /v1/ping does not: 14", rc == 14 and "/v1/ping failed" in out)
        for name in ("slop-trials-stdb", "sao-living_spacetimedb_1"):
            r = subprocess.run([sys.executable, str(HERE / "gate_server.py"), "stop", "--container", name],
                               env=dict(os.environ, PATH=f"{d}:{os.environ['PATH']}"), capture_output=True, text=True)
            case(f"stop refuses {name}", r.returncode != 0 and "refusing" in r.stderr)
    srv.shutdown()
    print(f"gate_server_selftest: {'all passed' if not fails else f'{fails} failed'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
