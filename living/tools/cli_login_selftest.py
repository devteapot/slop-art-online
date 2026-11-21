#!/usr/bin/env python3
"""cli_login.ensure: parallel first logins end with one identity (cli_login.py).

    python3 living/tools/cli_login_selftest.py [--parallel 8]
    python3 living/tools/cli_login_selftest.py --server CONTAINER --url http://127.0.0.1:PORT [--parallel 4]

Fake tier (always, no server): a fake CLI keeps its login in a file; `login show` says "not logged
in" until a login, and each `login --server-issued-login` takes 0.3 s and writes a new identity,
as the real one does. --parallel processes call ensure() at once: exactly one login, and every
process reads the same identity. The same processes with the old check-then-login (no lock) are
run as a control, and how many logins they made is printed (a note: the race, not a check).

Server tier (--server): a fresh scratch SpacetimeDB container whose CLI has never logged in (it is
refused otherwise: nothing would be tested). --parallel processes call verify.py's
admin_token(initialize=True), as parallel launches do, with LIVING_STDB_CONTAINER and
LIVING_STDB_URL set to it. Every process must get the same token, and it must be the CLI's own
afterwards (the identity every publish then runs as). Tokens are compared by hash, never printed.
Prints one line per check and exits 1 on any failure.
"""

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VERIFY = ROOT / ".agents/skills/verify/scripts"

FAKE_CLI = textwrap.dedent('''
    import os, secrets, sys, time
    from pathlib import Path
    state = Path(os.environ["FAKE_CLI_STATE"])
    def cli(*args):
        class R: pass
        r = R(); r.returncode = 0; r.stderr = ""
        if args[:2] == ("login", "show"):
            r.stdout = f"logged in as {state.read_text()}" if state.exists() and state.read_text() else "You are not logged in."
        elif args[:2] == ("login", "--server-issued-login"):
            state.write_text("")                       # the real CLI saves its config first
            time.sleep(0.3)                            # POST /v1/identity
            state.write_text(secrets.token_hex(8))     # a new identity, every time
            with open(str(state) + ".logins", "a") as f:
                f.write("1\\n")
            r.stdout = ""
        else:
            r.stdout = ""
        return r
''')

WORKER = textwrap.dedent('''
    import os, sys, time
    sys.path.insert(0, sys.argv[1])
    exec(open(sys.argv[2]).read())
    import cli_login
    go = float(sys.argv[4])
    while time.time() < go:
        time.sleep(0.001)
    if sys.argv[3] == "locked":
        cli_login.ensure("fake-container", cli)
    elif not cli_login.logged_in(cli):              # the old pattern: check, then log in
        cli("login", "--server-issued-login", "local")
    print(state.read_text())
''')

SERVER_WORKER = textwrap.dedent('''
    import hashlib, sys, time
    sys.path.insert(0, sys.argv[1])
    import verify
    go = float(sys.argv[2])
    while time.time() < go:
        time.sleep(0.001)
    print(hashlib.sha256(verify.admin_token(initialize=True).encode()).hexdigest()[:16])
''')


def parallel(cmds, env):
    procs = [subprocess.Popen(c, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for c in cmds]
    outs = []
    for p in procs:
        o, e = p.communicate(timeout=300)
        outs.append((p.returncode, o.strip(), e.strip()))
    return outs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--parallel", type=int, default=0)
    ap.add_argument("--server")
    ap.add_argument("--url")
    a = ap.parse_args()
    fails = 0

    def case(name, ok, detail=""):
        nonlocal fails
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" ({detail})" if detail else ""))
        fails += 0 if ok else 1

    import time
    n = a.parallel or (4 if a.server else 8)
    if not a.server:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "fake_cli.py").write_text(FAKE_CLI)
            (d / "worker.py").write_text(WORKER)
            for mode in ("locked", "unlocked"):
                state = d / f"cli-{mode}.toml"
                env = dict(os.environ, FAKE_CLI_STATE=str(state), SLOP_CLI_LOGIN_LOCK_DIR=str(d / "locks"))
                go = time.time() + 1.0
                outs = parallel([[sys.executable, str(d / "worker.py"), str(HERE), str(d / "fake_cli.py"), mode, str(go)] for _ in range(n)], env)
                logins = len(Path(str(state) + ".logins").read_text().split()) if Path(str(state) + ".logins").exists() else 0
                ids = {o for _, o, _ in outs}
                errs = [e for rc, _, e in outs if rc]
                if mode == "locked":
                    case(f"{n} parallel first logins through ensure(): one login", logins == 1 and not errs, f"{logins} logins{', errors: ' + errs[0][-200:] if errs else ''}")
                    case("and every process reads the same identity, the CLI's own", len(ids) == 1 and ids == {state.read_text()}, f"{len(ids)} distinct")
                else:
                    print(f"note the old check-then-login, {n} at once: {logins} logins, {len(ids)} distinct identities read (the race ensure() removes)")
    else:
        if not a.url:
            ap.error("--server needs --url")
        env = dict(os.environ, LIVING_STDB_CONTAINER=a.server, LIVING_STDB_URL=a.url)
        show = subprocess.run(["docker", "exec", a.server, "spacetime", "login", "show"], capture_output=True, text=True)
        if "not logged in" not in (show.stdout + show.stderr).lower():
            sys.exit(f"cli_login_selftest: {a.server}'s CLI is already logged in; the server tier needs a fresh container")
        with tempfile.TemporaryDirectory() as d:
            w = Path(d) / "server_worker.py"
            w.write_text(SERVER_WORKER)
            go = time.time() + 2.0
            outs = parallel([[sys.executable, str(w), str(VERIFY), str(go)] for _ in range(n)], env)
        errs = [e for rc, _, e in outs if rc]
        hashes = {o for rc, o, _ in outs if not rc}
        final = subprocess.run(["docker", "exec", a.server, "spacetime", "login", "show", "--token"], capture_output=True, text=True).stdout
        token = next((ln.rsplit(" is ", 1)[1].strip() for ln in final.splitlines() if "auth token" in ln and " is " in ln), "")
        own = hashlib.sha256(token.encode()).hexdigest()[:16]
        case(f"{n} parallel admin_token(initialize=True) on fresh {a.server}: no error", not errs, errs[0][-300:] if errs else "")
        case("every launch holds the same token", len(hashes) == 1, f"{len(hashes)} distinct")
        case("and it is the CLI's own (the identity publishes run as)", hashes == {own})
    print(f"cli_login_selftest: {'all passed' if not fails else f'{fails} failed'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
