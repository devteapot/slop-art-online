"""Delete a scratch world's database without taking its server down.

SpacetimeDB 2.14.1 can panic, and take the whole server down, when a database is deleted while
its world still ticks: the trial service went down that way on 2026-11-12 at 12:52 ("local
durability: actor vanished", while a busy world was deleted). So a world is paused first, read
back as paused, given 2 s for its queue to drain, and only then deleted. A world that cannot be
read back as paused is not deleted, and the caller is told why. A database that answers 404 at any
step is already gone, which counts as deleted.

This is the one copy of that rule. Its callers: the verify harness's cleanup (`verify.py cleanup`,
through `trial_archive.finish`, which archives between the confirmed pause and the delete, so it uses
`pause_confirmed`), verify-core's `verify_mechanics.py`, `verify_steering.py` and `updates.py`,
`gate.py`, `latency.py`, `play.py`, the trial runner's `trials.py clean` (`delete_db`, through
`http_pause_and_delete`), and the measurement tools `look_cost.py` (and `tick_cost.py` on it) and
`battle_viewers.py`. Each passes its own ways of reaching the server:

    deleted, why = pause_and_delete(
        pause=lambda: <call set_paused(true) as the world's admin; returns the HTTP status, or 0>,
        read=lambda: <(status, body) of SQL "SELECT paused FROM world">,
        delete=lambda: <delete the database, e.g. the CLI's `spacetime delete`>,
        gone=lambda: <True when SQL on the database answers 404>)
"""
import time

TRIES = 10       # read-backs of `paused`, one a second
SETTLE_S = 2.0   # after the world reads back paused, before the delete


def pause_confirmed(pause, read, tries=TRIES, sleep=time.sleep):
    """Pause the world and read it back as paused. Returns `(state, why)`: state "paused", "gone"
    (404 at any step) or "unpaused" (never read back as paused within `tries` s: do not delete)."""
    code = pause()
    if code == 404:
        return "gone", "already gone (404)"
    last = ""
    for _ in range(tries):
        c, body = read()
        if c == 404:
            return "gone", "gone (404)"
        if c == 200 and "true" in body.lower():
            return "paused", "paused"
        last = f"{c} {body.strip()[:160]}"
        sleep(1)
    return "unpaused", f"its world could not be read back as paused within {tries} s (set_paused {code}; last read {last})"


def pause_and_delete(pause, read, delete, gone, tries=TRIES, settle_s=SETTLE_S, sleep=time.sleep):
    """Pause, confirm, wait, delete. Returns `(deleted, why)`."""
    state, why = pause_confirmed(pause, read, tries, sleep)
    if state == "gone":
        return True, why
    if state != "paused":
        return False, f"not deleted: {why}"
    sleep(settle_s)
    delete()
    if gone():
        return True, "deleted (SQL now 404)"
    return False, "still answers SQL after delete"


def cli_pause_and_delete(cli, db):
    """`pause_and_delete` through the SpacetimeDB CLI alone, as the world's admin. `cli(*args)`
    runs the CLI and returns its `subprocess.CompletedProcess` without raising on failure."""

    def status(r):
        if r.returncode == 0:
            return 200
        err = f"{r.stderr or ''} {r.stdout or ''}".lower()
        return 404 if ("404" in err or "not found" in err or "no such database" in err) else 0

    def read():
        r = cli("sql", "-s", "local", db, "SELECT paused FROM world")
        return status(r), r.stdout or ""

    return pause_and_delete(
        pause=lambda: status(cli("call", "-s", "local", db, "set_paused", "true")),
        read=read,
        delete=lambda: cli("delete", "-s", "local", db, "-y"),
        gone=lambda: status(cli("sql", "-s", "local", db, "SELECT 1 FROM world")) == 404)


def http_pause_and_delete(url, db, token, delete, tries=TRIES, settle_s=SETTLE_S, sleep=time.sleep):
    """`pause_and_delete` over the server's HTTP API as the world's admin (`token`): `set_paused`
    by `/call`, the read-back and the 404 check by `/sql`; `delete()` deletes (the CLI)."""
    import json
    import urllib.error
    import urllib.request

    def post(path, body):
        req = urllib.request.Request(f"{url}/v1/database/{db}/{path}", data=body.encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json" if path.startswith("call/") else "text/plain"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except OSError as e:
            return 0, str(e)

    return pause_and_delete(
        pause=lambda: post("call/set_paused", json.dumps([True]))[0],
        read=lambda: post("sql", "SELECT paused FROM world"),
        delete=delete,
        gone=lambda: post("sql", "SELECT 1 FROM world")[0] == 404,
        tries=tries, settle_s=settle_s, sleep=sleep)
