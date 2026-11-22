#!/usr/bin/env python3
"""Launch one paid arm of E3 under its spend guard (docs/ATTENTION_E3.md §5, §7).

The guard (`act_trial.py watch`) starts FIRST and watches the arm's journal folder; this launcher
blocks until the guard has written its ready file, and only then starts the runner
(`living-mind heed-replay --ask mind|jev ...`) and hands the guard its PID. A guard that dies or
never gets ready means no runner and no call. Caps (frozen): arm b $4, arm c $5, everything $12
with $3 of it reserved (only with `--reserve-approved`, the general coordinator's word), each arm
stopping $0.25 early.

  heed_e3_launch.py --arm b|c --out DIR --runner-bin PATH [runner args after --] [--dry-run-price MODEL=IN]
                    [--reserve-approved] [--interval 30]

Jev (arm c) is priced from the LOCAL prices file only (LIVING_PRICES, living/configs/prices.local.json
or ~/.config/slop-living/prices.local.json); without a price the launcher refuses (stop rule 3).
The price is passed to the guard and never printed here.

`--dry-run-price MODEL=IN` (free dry runs against the fake server only): prices that model so the
guard's arithmetic and its stop can be checked without spending.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPS = {"b": 4.0, "c": 5.0}
TOTAL = 12.0
RESERVE = 3.0
MARGIN = 0.25
JEV = "jev-1.14.0"


def local_jev_price():
    cands = [os.environ.get("LIVING_PRICES")] if os.environ.get("LIVING_PRICES") else [str(ROOT / "living/configs/prices.local.json"), os.path.expanduser("~/.config/slop-living/prices.local.json")]
    for p in cands:
        try:
            v = json.loads(Path(p).read_text())["models"][JEV]["input_usd_per_m"]
            return float(v) if v is not None else None
        except (OSError, KeyError, ValueError, TypeError):
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["b", "c"], required=True)
    ap.add_argument("--out", required=True, help="the arm's run folder (its journal is <out>/calls.journal)")
    ap.add_argument("--runner-bin", required=True)
    ap.add_argument("--reserve-approved", action="store_true")
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--dry-run-price", action="append", default=[])
    ap.add_argument("runner", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    calls = out / "calls.jsonl"
    journal = out / "calls.journal"
    ready = out / "guard.ready"
    pidf = out / "runner.pid"
    for f in (ready, pidf):
        f.unlink(missing_ok=True)
    prices = list(a.dry_run_price)
    if a.arm == "c" and not a.dry_run_price:
        p = local_jev_price()
        if p is None:
            print("REFUSED: no local price for jev-1.14.0 (stop rule 3: no price, no Jev)", flush=True)
            return 2
        prices.append(f"{JEV}={p},0,0")
    total = TOTAL if a.reserve_approved else TOTAL - RESERVE
    guard_cmd = [sys.executable, "-I", str(ROOT / "living/tools/act_trial.py"), "watch", "--arm", f"e3{a.arm}", "--group", "e3",
                 "--ledger", str(out.parent / "e3-ledger.json"), "--log", str(out / "guard.log"), "--pid-file", str(pidf),
                 "--journal", str(journal / "*.jsonl"), "--ready", str(ready), "--group-cap", str(CAPS[a.arm] if a.arm == "c" else CAPS[a.arm] + 0.0),
                 "--total-cap", str(total), "--margin", str(MARGIN), "--interval", str(a.interval)]
    for p in prices:
        guard_cmd += ["--price", p]
    journal.mkdir(parents=True, exist_ok=True)
    gout = open(out / "guard.out", "a")
    guard = subprocess.Popen(guard_cmd, stdout=gout, stderr=subprocess.STDOUT, cwd=ROOT)
    print(f"guard started (pid {guard.pid}); waiting for its ready file before any call", flush=True)
    t0 = time.time()
    while not ready.exists():
        if guard.poll() is not None:
            print(f"REFUSED: the guard exited ({guard.returncode}) before it was ready; no runner started", flush=True)
            return 2
        if time.time() - t0 > 180:
            guard.terminate()
            print("REFUSED: the guard was not ready in 180 s; no runner started", flush=True)
            return 2
        time.sleep(0.2)
    print(f"guard ready after {time.time() - t0:.1f} s: {ready.read_text().strip()[:160]}", flush=True)
    runner_args = [x for x in a.runner if x != "--"]
    rout = open(out / "runner.out", "a")
    runner = subprocess.Popen([a.runner_bin, "heed-replay", *runner_args, "--out", str(calls)], stdout=rout, stderr=subprocess.STDOUT, cwd=ROOT)
    pidf.write_text(str(runner.pid))
    print(f"runner started (pid {runner.pid}) under the guard", flush=True)
    rc = runner.wait()
    print(f"runner exited {rc}", flush=True)
    # The guard ends the arm when its runner is gone; give it a last poll.
    try:
        guard.wait(timeout=max(60, a.interval * 3))
    except subprocess.TimeoutExpired:
        guard.terminate()
    print(f"guard exited {guard.returncode}; ledger {out.parent / 'e3-ledger.json'}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
