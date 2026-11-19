#!/usr/bin/env python3
"""The fast-lane frame trial (docs/FAST_LANE_FRAME.md): arm B (the fast lane on, the shipped
caps, real fast calls, `--keep-plans`) at 100 fighters, the first frame against the balanced one
(`--law fast_frame=1|2`), two runs each, interleaved v1 v2 v1 v2; everything else fixed (model,
rules, seed `island`, the fixed site and formation, the persona mix). Paid: start it with
flf-all.sh only when the coordinator has authorized the run.

Each run holds `~/slop-mq/battle.lock` (other workers share the host) and records the host's
load. The spend watcher tails the fast calls' journal: a hard stop at $2 across the trial, or more
than 10% failed calls, or two windows under 2 ticks a second. No run starts within the reclaim
window (23:15-02:00 CET), or so late it would reach it. The keys are copied from a trials
checkout's .env without being shown, removed afterwards, and the outputs scanned for fragments.
"""
import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from flb_replicates import JournalUsage, Stop, confirm_cleanup, disk_check, gone, key_fragments, leak_count

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local/living"
SERVER = "http://127.0.0.1:3320"
LIMIT = 2.00
SIZE, MINUTES = "100", 5
RUNS = (("v1", "1"), ("v2", "1"), ("v1", "2"), ("v2", "2"))
LOCK = Path.home() / "slop-mq/battle.lock"
KEYS = Path.home() / "dev/slop-trials/.env"
# A run takes its minutes plus about seven of setup, refill and cleanup.
RUN_BUDGET = datetime.timedelta(minutes=MINUTES + 12)


def interrupted(signum, _frame):
    raise Stop(f"interrupted by signal {signum}")


def window_ok(now=None):
    """Not within 23:15-02:00 CET (a reclaim may take the trial server), and not so late that a
    run would reach 23:15."""
    now = now or datetime.datetime.now(ZoneInfo("Europe/Berlin"))
    t = now.time()
    if t >= datetime.time(23, 15) or t < datetime.time(2, 0):
        return False
    end = now + RUN_BUDGET
    return end.date() == now.date() and end.time() < datetime.time(23, 15)


def name_of(frame, rep):
    return f"minds-flf-{frame}-{SIZE}-{rep}"


def run_one(frame, rep, out, previous_usd):
    name = name_of(frame, rep)
    path = LOCAL / "verify" / name
    live = LOCAL / "journal" / f"verify-{name}"
    log, watch = out / f"{name}.log", out / f"{name}.watch.jsonl"
    # The host's battle lock, held by this process for the run (the child is battle_diag itself,
    # so a stop signals it and its own cleanup runs).
    lock = LOCK.open("a")
    waited = time.time()
    fcntl.flock(lock, fcntl.LOCK_EX)
    record = {"run": name, "frame": frame, "rep": rep, "lock_wait_s": round(time.time() - waited, 1), "load_start": os.getloadavg(),
              "started": datetime.datetime.now(ZoneInfo("Europe/Berlin")).isoformat(timespec="seconds")}
    print(f"start {name}", flush=True)
    with lock, log.open("w") as stream, watch.open("w") as observations:
        child = None
        journal = JournalUsage()
        try:
            child = subprocess.Popen(
                [sys.executable, str(ROOT / "living/tools/battle_diag.py"), "--run", name, "--battle", SIZE,
                 "--walkers", "16", "--minutes", str(MINUTES), "--keep-plans", "--arm", f"B-{SIZE}-{frame}", "--fast-lane",
                 "--fast-real", "--law", f"fast_frame={frame[1:]}"],
                stdout=stream, stderr=subprocess.STDOUT)
            while child.poll() is None:
                current = journal.sample(live)
                observations.write(json.dumps({"at": time.time(), "load": os.getloadavg(), **current}) + "\n")
                observations.flush()
                disk_check()
                if previous_usd + current["usd"] > LIMIT:
                    raise Stop(f"estimated fast-call spend exceeded ${LIMIT:.2f}")
                if current["unpriced_success"]:
                    raise Stop("a successful fast call has no recorded or estimable price")
                if current["calls"] >= 20 and current["failures"] * 10 > current["calls"]:
                    raise Stop("more than 10% of this run's fast calls failed")
                diag = path / "diag.jsonl"
                if diag.exists():
                    rows = [json.loads(line) for line in diag.open() if line.endswith("\n")]
                    if sum(row["ticks_per_s"] < 2 for row in rows) >= 2:
                        raise Stop("two windows below 2 ticks/s")
                time.sleep(1)
            if child.returncode:
                raise Stop(f"{name} exited with status {child.returncode}")
        finally:
            previous = {s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGTERM)}
            try:
                if child is not None and child.poll() is None:
                    # Its own PID only: battle_diag pauses, reads back and deletes its world.
                    child.terminate()
                    child.wait()
                confirm_cleanup(name)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
            record["load_end"] = os.getloadavg()
            record["usd"] = JournalUsage().sample(path / "journal")["usd"] if (path / "journal").exists() else journal.totals["usd"]
    return record


def main():
    if os.environ.get("FLF_AUTHORIZED") != "yes" or os.environ.get("LIVING_STDB_URL") != SERVER or \
            os.environ.get("LIVING_STDB_CONTAINER") != "slop-trials-stdb":
        raise SystemExit("use flf-all.sh --authorized once the coordinator has authorized the paid run")
    disk_check()
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = LOCAL / f"flf-trial-{stamp}"
    out.mkdir(parents=True)
    key_file = ROOT / ".env"
    key_bytes = KEYS.read_bytes()
    fragments = key_fragments(key_bytes)
    summary = {"runs": [], "limit_usd": LIMIT, "minutes": MINUTES, "size": SIZE,
               "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()}
    attempted, completed, spend, created = [], [], 0.0, False
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(key_bytes)
        for frame, rep in RUNS:
            name = name_of(frame, rep)
            if (LOCAL / "verify" / name).exists() or not gone(name):
                raise Stop(f"run already exists: {name}")
            if not window_ok():
                raise Stop("inside or too near the reclaim window (23:15-02:00 CET)")
            attempted.append(name)
            record = run_one(frame, rep, out, spend)
            spend += record["usd"]
            summary["runs"].append(record)
            completed.append(LOCAL / "verify" / name)
            if spend > LIMIT:
                raise Stop(f"estimated fast-call spend exceeded ${LIMIT:.2f}")
    except (Stop, OSError, subprocess.SubprocessError, ValueError) as error:
        summary["stop"] = str(error)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            if completed:
                with (out / "report.json").open("w") as report, (out / "report-errors.log").open("w") as errors:
                    result = subprocess.run([sys.executable, str(ROOT / "living/tools/flf_report.py"), *map(str, completed)],
                                            stdout=report, stderr=errors, check=False)
                summary["report_exit"] = result.returncode
            summary["key_fragment_files"] = leak_count([out, *(LOCAL / "verify" / n for n in attempted if (LOCAL / "verify" / n).exists())], fragments)
        except (OSError, EOFError):
            summary["key_fragment_files"] = None
        finally:
            if created:
                key_file.unlink()
        summary["estimated_usd"] = spend
        summary["worlds_deleted"] = {n: gone(n) for n in attempted}
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps({"out": str(out), **summary}), flush=True)
    return int("stop" in summary or summary.get("report_exit", 0) != 0 or not all(summary["worlds_deleted"].values())
               or summary["key_fragment_files"] != 0)


if __name__ == "__main__":
    sys.exit(main())
