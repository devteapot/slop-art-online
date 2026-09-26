#!/usr/bin/env python3
"""Run a lab scenario: a small world built from `seeds/<scenario>.json` (its own pace, e.g.
lives compressed to hours) on its own database with its own mind service; the active world
is untouched. Builds the module with that seed, publishes a fresh database, runs minds for
the given time with the watcher reporting, then stops the minds (the database stays for the
viewer: http://127.0.0.1:8330/?db=<db>).

Usage: living/tools/lab.py lab-lifecycle [--db living-lab] [--minutes 60] [--every 600]
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVING = ROOT / "living"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--db", default=None, help="database (default: the scenario name)")
    ap.add_argument("--minutes", type=float, default=240)
    ap.add_argument("--every", type=int, default=600)
    a = ap.parse_args()
    a.db = a.db or a.scenario
    env = dict(os.environ, LIVING_SEED=a.scenario)
    # Each scenario builds in its own target dir, so labs can be (re)built side by side.
    tdir = f"target/lab-{a.scenario}"
    subprocess.run(["cargo", "build", "-p", "living-authority", "--target", "wasm32-unknown-unknown", "--release", "--target-dir", tdir], cwd=LIVING, env=env, check=True)
    src = LIVING / tdir / "wasm32-unknown-unknown/release/living_authority.wasm"
    wasm = f"living_authority_{a.scenario.replace('-', '_')}.wasm"
    shutil.copy(src, LIVING / "target/wasm32-unknown-unknown/release" / wasm)
    stdb = str(LIVING / "tools/stdb")
    subprocess.run([stdb, "publish", "-s", "local", "-b", f"/wasm/{wasm}", a.db, "--delete-data", "-y"], check=True)
    run = f"{a.scenario}-{int(time.time())}"
    mind_env = dict(os.environ, LIVING_DB=a.db, LIVING_RUN=run, LIVING_SEED=a.scenario, RUST_LOG="info")
    log = open(ROOT / f".local/living/{run}.log", "a")
    start_mind = lambda: subprocess.Popen([str(LIVING / "target/release/living-mind")], cwd=ROOT, env=mind_env, stdout=log, stderr=subprocess.STDOUT)
    mind = start_mind()
    # A stopped lab (SIGTERM, SIGHUP) takes its mind and watcher down with it.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))
    watch = subprocess.Popen([sys.executable, str(LIVING / "tools/watch.py"), "--db", a.db, "--every", str(a.every), "--review", "--llm-run", run], cwd=ROOT)
    print(f"lab {a.scenario}: db {a.db}, run {run}; viewer http://127.0.0.1:8330/?db={a.db}; reports in .local/living/watch/", flush=True)
    end = time.time() + a.minutes * 60
    try:
        # Keep the minds connected: restart the mind service whenever it exits.
        while time.time() < end:
            if mind.poll() is not None:
                print(f"[{time.strftime('%H:%M:%S')}] mind service exited ({mind.returncode}); restarting", flush=True)
                time.sleep(3)
                mind = start_mind()
            time.sleep(5)
    finally:
        watch.terminate()
        mind.terminate()
        mind.wait(timeout=30)
    subprocess.run([sys.executable, str(LIVING / "tools/watch.py"), "--db", a.db, "--once", "--review", "--llm-run", run], cwd=ROOT)


if __name__ == "__main__":
    main()
