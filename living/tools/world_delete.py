"""Delete a scratch world's database without taking its server down.

SpacetimeDB 2.14.1 can panic, and take the whole server down, when a database is deleted while
its world still ticks: the trial service went down that way on 2026-11-12 at 12:52 ("local
durability: actor vanished", while a busy world was deleted). So a world is paused first, read
back as paused, given 2 s for its queue to drain, and only then deleted. A world that cannot be
read back as paused is not deleted, and the caller is told why. A database that answers 404 at any
step is already gone, which counts as deleted.

The verify harness's cleanup (`verify.py cleanup`, which every surface's cleanup and the tools
built on its runs go through) and the trial runner (`trials.py` `delete_db`) apply the same rule in
their own code. This module serves the tools that delete scratch databases outside both:
verify-core's `verify_mechanics.py` and `verify_steering.py`, `gate.py`, `latency.py` and `play.py`.
Each passes its own ways of reaching the server:

    deleted, why = pause_and_delete(
        pause=lambda: <call set_paused(true) as the world's admin; returns the HTTP status, or 0>,
        read=lambda: <(status, body) of SQL "SELECT paused FROM world">,
        delete=lambda: <delete the database, e.g. the CLI's `spacetime delete`>,
        gone=lambda: <True when SQL on the database answers 404>)
"""
import time

TRIES = 10       # read-backs of `paused`, one a second
SETTLE_S = 2.0   # after the world reads back paused, before the delete


def pause_and_delete(pause, read, delete, gone, tries=TRIES, settle_s=SETTLE_S, sleep=time.sleep):
    """Pause, confirm, wait, delete. Returns `(deleted, why)`."""
    code = pause()
    if code == 404:
        return True, "already gone (404)"
    paused = False
    last = ""
    for _ in range(tries):
        c, body = read()
        if c == 404:
            return True, "gone (404)"
        if c == 200 and "true" in body.lower():
            paused = True
            break
        last = f"{c} {body.strip()[:160]}"
        sleep(1)
    if not paused:
        return False, f"not deleted: its world could not be read back as paused within {tries} s (set_paused {code}; last read {last})"
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
