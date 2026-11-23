"""The SpacetimeDB container CLI's first login, taken once (.agents/skills/verify/SKILL.md, Launch).

`spacetime login --server-issued-login local` asks the server for a new identity
(`POST /v1/identity`) and overwrites the CLI's `cli.toml` every time it runs. Launches that found
a fresh container's CLI not logged in and each logged it in (2026-11-21, four parallel verify
launches on a new `wf-stdb`) each kept the token of their own login, while every publish ran as
whichever identity was written last: one world was published under another launch's identity,
and its `install_script`, sent with its own token, was refused (`530 admin only`).

`ensure(container, cli)` makes the check and the login one step: a process that finds the CLI not
logged in takes an exclusive lock for that container (a file under ~/.cache/slop-cli-login/, so
every checkout on the machine shares it), checks again, and only then logs in. Everyone after
finds it logged in and reads the same identity. `cli(*args)` runs `spacetime ARGS` in the
container and returns a CompletedProcess (stdout and stderr as text). Selftest:
`python3 living/tools/cli_login_selftest.py`.
"""

import fcntl
import os
import re
from pathlib import Path


def lock_path(container):
    base = Path(os.environ.get("SLOP_CLI_LOGIN_LOCK_DIR") or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "slop-cli-login")
    base.mkdir(parents=True, exist_ok=True)
    return base / (re.sub(r"[^A-Za-z0-9_.-]", "_", container) + ".lock")


def logged_in(cli):
    r = cli("login", "show")
    return "not logged in" not in (r.stdout + r.stderr).lower()


def ensure(container, cli, setup=()):
    """Log the container's CLI in once. True when this call logged it in, False when it already was.
    `setup` holds CLI argument tuples run before the login, under the lock (e.g. server set-default)."""
    if logged_in(cli):
        return False
    with open(lock_path(container), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if logged_in(cli):
            return False
        for args in setup:
            cli(*args)
        r = cli("login", "--server-issued-login", "local")
        if r.returncode != 0:
            raise RuntimeError(f"spacetime login --server-issued-login local failed in {container}: {(r.stderr or r.stdout).strip()[-1000:]}")
        return True
