#!/usr/bin/env python3
"""CLI recorder for the existing mechanics and steering drivers' LIVING_STDB hook."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def main():
    run = os.environ.get("CORE_VERIFY_RUN", "")
    if not re.fullmatch(r"core-[a-z0-9-]+", run):
        sys.exit("CORE_VERIFY_RUN must be a core-* run name")
    args = sys.argv[1:]
    db = "verify-" + run
    if not args or args[0] not in {"publish", "call", "sql", "subscribe", "delete"} or db not in args:
        sys.exit(f"recorder accepts only verification driver commands for {db}")
    out = ROOT / ".local/living/verify" / run
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    if args[0] == "publish":
        if state_path.exists():
            sys.exit("use a fresh run name; the recorder will not overwrite existing harness state")
        state_path.write_text(json.dumps({"run": run, "db": db, "published": True, "pids": {}}) + "\n")
    r = subprocess.run([str(ROOT / "living/tools/stdb"), *args], capture_output=True, text=True)
    with (out / "stdb-actions.jsonl").open("a") as f:
        f.write(json.dumps({"at_ms": time.time_ns() // 1_000_000, "args": args,
                            "exit": r.returncode, "stdout": r.stdout, "stderr": r.stderr}) + "\n")
    if args[0] == "sql" and r.returncode == 0 and "FROM routine" in args[-1]:
        match = re.search(r"WHERE actor = (\d+)", args[-1])
        if match:
            readback(out, db, "routine", match[1])
    if args[0] == "call" and r.returncode == 0 and args[4] == "set_behavior":
        readback(out, db, "brain", args[5])
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if args[0] == "delete" and r.returncode == 0 and state_path.exists():
        state = json.loads(state_path.read_text())
        state["driver_deleted"] = True
        state_path.write_text(json.dumps(state, indent=2) + "\n")
    return r.returncode


def readback(out, db, table, actor):
    key = "id" if table == "brain" else "actor"
    args = ["sql", "--format", "json", "-s", "local", db, f"SELECT * FROM {table} WHERE {key} = {int(actor)}"]
    r = subprocess.run([str(ROOT / "living/tools/stdb"), *args], capture_output=True, text=True)
    with (out / "stdb-actions.jsonl").open("a") as f:
        f.write(json.dumps({"at_ms": time.time_ns() // 1_000_000, "args": args,
                            "exit": r.returncode, "stdout": r.stdout, "stderr": r.stderr}) + "\n")
    if r.returncode:
        sys.exit(f"installed {table} readback failed: {r.stderr[-500:]}")
    (out / f"installed-{table}-{actor}-{time.time_ns()}.json").write_text(r.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
