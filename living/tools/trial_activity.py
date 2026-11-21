"""Shared half of the Spark trial maintenance lock."""
from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def running_trial(container):
    queue = Path.home() / "slop-mq"
    if container != "slop-trials-stdb" or not queue.is_dir():
        yield
        return
    with (queue / "trial-activity.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("trial server maintenance is holding trial-activity.lock") from None
        yield
