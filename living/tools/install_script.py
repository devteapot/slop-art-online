#!/usr/bin/env python3
"""Install a rules script on a database as the world admin, over HTTP.

    python3 living/tools/install_script.py DB [SCRIPT]

SCRIPT defaults to living/scripts/skills.rhai; `-` reads it from stdin. The source goes in the
request body: the shipped script passed 128 KiB on 2026-11-11, past Linux's limit on one
command-line argument (MAX_ARG_STRLEN), so `spacetime call ... install_script "<source>"` no
longer runs. The admin token is the in-container CLI identity's (living/tools/stdb), read into
memory only; LIVING_STDB_URL names the server (default the shared one, http://127.0.0.1:3300),
and LIVING_STDB_CONTAINER its container, as for living/tools/stdb. Standard library only.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
URL = os.environ.get("LIVING_STDB_URL", "http://127.0.0.1:3300").rstrip("/")


def admin_token():
    out = subprocess.run([str(ROOT / "living/tools/stdb"), "login", "show", "--token"], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if "auth token" in line and " is " in line:
            return line.rsplit(" is ", 1)[1].strip()
    sys.exit("could not read the admin token from `spacetime login show --token`")


def install(db, source, token=None, timeout=180):
    """POST the source to `install_script`; returns (status, body)."""
    req = urllib.request.Request(f"{URL}/v1/database/{db}/call/install_script", data=json.dumps([source]).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token or admin_token()}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    db = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) == 3 else str(ROOT / "living/scripts/skills.rhai")
    source = sys.stdin.read() if path == "-" else Path(path).read_text()
    code, body = install(db, source)
    if code != 200:
        sys.exit(f"install_script on {db}: {code} {body.strip()[-2000:]}")
    print(f"installed {len(source)} bytes of rules on {db}")


if __name__ == "__main__":
    main()
