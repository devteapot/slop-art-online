#!/usr/bin/env python3
"""Wait until a freshly published world is made (staged genesis, docs/STAGED_GENESIS.md §4).

Since staged genesis, `init` keeps the script, the seed's check and its rules, and the world itself
is made by scheduled steps after the publish returns. Until the public `genesis` row says `done`,
the player and mind reducers refuse with `world_preparing`, and an admin call or SQL read lands on
a half-made world. So every tool that publishes a world and then calls it waits here first: the
one shared copy of the rule, as `world_delete.py` is for deletes.

    import genesis_wait
    row = genesis_wait.wait_ready(url, db, token)          # over HTTP as the owner
    row = genesis_wait.wait_ready_cli(cli, db)             # through the CLI (`cli(*args)` -> stdout)
    row = genesis_wait.wait_until(read, db)                # any reader of the `genesis` row

A world with no `genesis` row (made inline before staged genesis, or a floor module not yet given
its seed) counts as ready. A chain that stopped (a failed step: its label says "stopped: …") or a
timeout raises `GenesisNotReady` with the last label.

    python3 living/tools/genesis_wait.py URL DB [--token T | --token-file F] [--timeout S]
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

TIMEOUT_S = 600.0
POLL_S = 0.25


class GenesisNotReady(RuntimeError):
    pass


def genesis_row(url, db, token):
    """The `genesis` row (a dict), None when the world has none, or raises on an HTTP error."""
    req = urllib.request.Request(f"{url}/v1/database/{db}/sql", data=b"SELECT * FROM genesis", method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode())[0]
    except urllib.error.HTTPError as e:
        raise GenesisNotReady(f"{db}: SQL on genesis failed (HTTP {e.code}): {e.read().decode(errors='replace')[:200]}") from e
    names = [c["name"]["some"] if isinstance(c.get("name"), dict) else c.get("name") for c in res["schema"]["elements"]]
    rows = [dict(zip(names, r)) for r in res["rows"]]
    return rows[0] if rows else None


def wait_until(read, db, timeout_s=TIMEOUT_S, poll_s=POLL_S, log=None):
    """The rule itself: `read()` returns the `genesis` row (a dict with `done`, `step`, `steps`,
    `label`) or None; block until it is done (or absent) and return it."""
    end = time.monotonic() + timeout_s
    last = None
    while True:
        row = read()
        if row is None or row.get("done"):
            return row
        label = str(row.get("label", ""))
        if label != last and log:
            log(f"{db}: genesis step {row.get('step')} of {row.get('steps')}: {label}")
        last = label
        if label.startswith("stopped"):
            raise GenesisNotReady(f"{db}: genesis stopped at step {row.get('step')}: {label}")
        if time.monotonic() > end:
            raise GenesisNotReady(f"{db}: genesis not done after {timeout_s:.0f} s (step {row.get('step')} of {row.get('steps')}: {label})")
        time.sleep(poll_s)


def wait_ready(url, db, token, timeout_s=TIMEOUT_S, poll_s=POLL_S, log=None):
    """Block until the world `db` is made, reading it over HTTP as `token` (the owner)."""
    return wait_until(lambda: genesis_row(url, db, token), db, timeout_s, poll_s, log)


def wait_ready_cli(cli, db, timeout_s=TIMEOUT_S, poll_s=POLL_S, log=None):
    """The same through the SpacetimeDB CLI as the world's owner: `cli(*args)` runs `spacetime
    *args` and returns its stdout (a tool that has no token of its own)."""
    def read():
        out = cli("sql", "-s", "local", db, "SELECT done, step, steps, label FROM genesis")
        for line in out.splitlines():
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 4 and cells[0] in ("true", "false"):
                return {"done": cells[0] == "true", "step": cells[1], "steps": cells[2], "label": cells[3].strip('"')}
        return None
    return wait_until(read, db, timeout_s, poll_s, log)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("db")
    ap.add_argument("--token")
    ap.add_argument("--token-file")
    ap.add_argument("--timeout", type=float, default=TIMEOUT_S)
    a = ap.parse_args()
    token = a.token or (open(a.token_file).read().strip() if a.token_file else None)
    if not token:
        ap.error("--token or --token-file")
    t0 = time.monotonic()
    try:
        row = wait_ready(a.url, a.db, token, a.timeout, log=lambda m: print(m, file=sys.stderr, flush=True))
    except GenesisNotReady as e:
        sys.exit(str(e))
    print(json.dumps({"db": a.db, "ready_s": round(time.monotonic() - t0, 2), "genesis": row}))


if __name__ == "__main__":
    main()
