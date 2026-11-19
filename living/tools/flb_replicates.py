#!/usr/bin/env python3
"""Run and watch the authorized fast-lane battle replicates, one world at a time."""
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen

from flb_report import recorded_cost

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local/living"
EVIDENCE = Path.home() / "slop-evidence"
EARLIER = Path.home() / "dev/slop-cm-flb/.local/living/verify"
SERVER = "http://127.0.0.1:3320"
LIMIT = 4.08
RUNS = (("B", "200", "2"), ("C", "200", "2"), ("A", "200", "2"),
        ("A", "100", "1"), ("B", "100", "1"))


class Stop(Exception):
    pass


def interrupted(signum, _frame):
    raise Stop(f"interrupted by signal {signum}")


def disk_check():
    if shutil.disk_usage(ROOT).free < 45 * 1024**3:
        raise Stop("disk fell below 45 GiB free")


def gone(run):
    try:
        with urlopen(f"{SERVER}/v1/database/verify-{run}", timeout=10):
            return False
    except HTTPError as error:
        if error.code == 404:
            return True
        raise


def confirm_cleanup(run):
    if gone(run):
        return
    result = subprocess.run([ROOT / ".agents/skills/verify/scripts/verify.py", "cleanup", "--run", run],
                            check=False)
    if result.returncode or not gone(run):
        raise Stop(f"cleanup failed for verify-{run}")


class JournalUsage:
    """Tail complete journal rows even while a call is writing its response."""

    def __init__(self):
        self.offsets = {}
        self.totals = {"usd": 0.0, "calls": 0, "failures": 0, "unpriced_success": 0}

    def sample(self, journal):
        for file in journal.glob("*.jsonl"):
            try:
                stream = file.open("rb")
            except FileNotFoundError:
                # The driver copies the journal into run evidence before removing it.
                continue
            with stream:
                stream.seek(self.offsets.get(file, 0))
                while line := stream.readline():
                    if not line.endswith(b"\n"):
                        break
                    self.offsets[file] = stream.tell()
                    call = json.loads(line)
                    if call.get("purpose") != "fast":
                        continue
                    self.totals["calls"] += 1
                    failed = bool(call.get("error"))
                    self.totals["failures"] += failed
                    cost = recorded_cost(call)
                    if cost is not None:
                        self.totals["usd"] += cost
                    elif not failed:
                        self.totals["unpriced_success"] += 1
        return self.totals


def guard(current, previous_usd, diag):
    disk_check()
    if previous_usd + current["usd"] > LIMIT:
        raise Stop("estimated fast-call spend exceeded $4.08")
    if current["unpriced_success"]:
        raise Stop("a successful fast call has no recorded or estimable price")
    if current["failures"] * 10 > current["calls"]:
        raise Stop("more than 10% of this run's fast calls failed")
    if diag.exists():
        with diag.open() as stream:
            rows = [json.loads(line) for line in stream if line.endswith("\n")]
        if sum(row["ticks_per_s"] < 2 for row in rows) >= 2:
            raise Stop("two windows below 2 ticks/s")


def archive(path, source, names):
    subprocess.run(["tar", "--zstd", "-cf", path, "-C", source, "--", *names], check=True)
    subprocess.run(["zstd", "-t", path], check=True)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n")
    return digest


def key_fragments(content):
    fragments = set()
    for line in content.splitlines():
        if b"=" not in line or line.lstrip().startswith(b"#"):
            continue
        name, value = line.split(b"=", 1)
        if not re.search(rb"KEY|TOKEN|SECRET|PASSWORD", name, re.IGNORECASE):
            continue
        value = value.strip().strip(b"\"'")
        if len(value) >= 12:
            fragments.update((value[:12], value[-12:]))
    return fragments


def leak_count(paths, fragments):
    """Count files containing a fragment without emitting any matching text."""
    matches = 0
    for path in paths:
        for file in path.rglob("*"):
            if not file.is_file() or file.name.endswith(".zst"):
                continue
            open_file = gzip.open if file.name.endswith(".gz") else open
            with open_file(file, "rb") as stream:
                matches += any(fragment in line for line in stream for fragment in fragments)
    return matches


def run_one(spec, out, previous_usd):
    arm, size, rep = spec
    name = f"minds-flb-{arm.lower()}-{size}-{rep}"
    path = LOCAL / "verify" / name
    log = out / f"{name}.log"
    watch = out / f"{name}.watch.jsonl"
    live = LOCAL / "journal" / f"verify-{name}"
    print(f"start {name}", flush=True)
    with log.open("w") as stream, watch.open("w") as observations:
        child = None
        journal = JournalUsage()
        try:
            child = subprocess.Popen([ROOT / "living/tools/flb-run.sh", *spec, "10"],
                                     stdout=stream, stderr=subprocess.STDOUT)
            while child.poll() is None:
                current = journal.sample(live)
                observations.write(json.dumps({"at": time.time(), **current}) + "\n")
                observations.flush()
                guard(current, previous_usd, path / "diag.jsonl")
                time.sleep(1)
            if child.returncode:
                raise Stop(f"{name} exited with status {child.returncode}")
        finally:
            # Avoid interrupting pause and deletion a second time.
            previous_handlers = {s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGTERM)}
            try:
                if child is not None and child.poll() is None:
                    child.terminate()
                    child.wait()
                confirm_cleanup(name)
            finally:
                for sig, handler in previous_handlers.items():
                    signal.signal(sig, handler)


def main():
    if os.environ.get("FLB_WINDOW_OPEN") != "yes" or os.environ.get("LIVING_STDB_URL") != SERVER or \
            os.environ.get("LIVING_STDB_CONTAINER") != "slop-trials-stdb":
        raise Stop("use flb-all.sh after the coordinator opens the trial window")
    disk_check()
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = LOCAL / f"flb-replicates-{date}"
    out.mkdir()
    dest = EVIDENCE / f"{out.name}.tar.zst"
    key_file = ROOT / ".env"
    source = Path.home() / "dev/slop-trials/.env"
    spend = 0.0
    attempted = []
    completed = []
    summary = {"runs": {}, "estimated_usd": 0.0}
    key_bytes = source.read_bytes()
    fragments = key_fragments(key_bytes)
    created = False
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(key_bytes)
        layouts = {}
        for spec in RUNS:
            name = f"minds-flb-{spec[0].lower()}-{spec[1]}-{spec[2]}"
            path = LOCAL / "verify" / name
            if path.exists() or not gone(name):
                raise Stop(f"run already exists: {name}")
            attempted.append(name)
            try:
                run_one(spec, out, spend)
                head = json.loads((path / "diag-result.json").read_text())
                setup = (head["world_seed"], head["site"], [x["at"] for x in head["layout"]],
                         [x["at"] for x in head["walker_layout"]])
                if setup != layouts.setdefault(spec[1], setup):
                    raise Stop(f"starting layout changed in {name}")
            finally:
                current = JournalUsage().sample(path / "journal")
                summary["runs"][name] = current
                files = [f"{out.name}/{name}{suffix}" for suffix in (".log", ".watch.jsonl")]
                archive(EVIDENCE / f"{out.name}-{name}.tar.zst", LOCAL,
                        [file for file in [f"verify/{name}", *files] if (LOCAL / file).exists()])
            completed.append(path)
            guard(current, spend, path / "diag.jsonl")
            spend += current["usd"]
    except (Stop, OSError, subprocess.SubprocessError, ValueError) as error:
        summary["stop"] = str(error)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            if completed:
                try:
                    earlier = [EARLIER / f"minds-flb-{arm}-200-1" for arm in "abc"]
                    with (out / "report.json").open("w") as report, (out / "report-errors.log").open("w") as errors:
                        result = subprocess.run([sys.executable, ROOT / "living/tools/flb_report.py", *earlier,
                                                 *completed], stdout=report, stderr=errors, check=False)
                    summary["report_exit"] = result.returncode
                except OSError:
                    summary["report_exit"] = 1
            paths = [LOCAL / "verify" / name for name in attempted]
            summary["key_fragment_files"] = leak_count([out, *paths], fragments)
        except (OSError, EOFError):
            summary["key_fragment_files"] = None
        finally:
            if created:
                key_file.unlink()
        summary["estimated_usd"] = sum(row["usd"] for row in summary["runs"].values())
        summary["worlds_deleted"] = deleted = {}
        for name in attempted:
            try:
                deleted[name] = gone(name)
            except OSError:
                deleted[name] = False
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        sha = archive(dest, LOCAL, [out.name, *(f"verify/{name}" for name in attempted
                                                if (LOCAL / "verify" / name).is_dir())])
        print(json.dumps({"archive": str(dest), "sha256": sha, **summary}), flush=True)
    return int("stop" in summary or summary.get("report_exit", 0) != 0
               or not all(summary["worlds_deleted"].values()) or summary["key_fragment_files"] != 0)


if __name__ == "__main__":
    sys.exit(main())
