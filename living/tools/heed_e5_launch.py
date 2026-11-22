#!/usr/bin/env python3
"""Launch one paid part of E5 under its spend guard (docs/ATTENTION_E5.md §4, stop rules).

The guard (`act_trial.py watch`) starts FIRST, on the part's own journal folder (created empty
before the runner), and this launcher starts the runner only once the guard has written its ready
file, then hands the guard the runner's PID. A guard that exits or is not ready in 180 s means no
runner and no call.

  heed_e5_launch.py --part p1 --run NAME [--ledger F] [--dry-run-price MODEL=IN,OUT,CACHED] -- <battle_diag.py args>
  heed_e5_launch.py --part b|c --out DIR --runner-bin PATH [--ledger F] [--dry-run-price ...] -- <heed-replay args>

Caps (frozen): phase 1 (the recording, every run together) $20, (b) $2, (c) $5, everything $27,
each part stopping $0.50 below its cap, from journal spend: phase 1 and (b) at the committed
prices (`act_trial.py` PRICES), (c) at the LOCAL prices file's price for Jev (LIVING_PRICES,
living/configs/prices.local.json or ~/.config/slop-living/prices.local.json), never printed; without
a price, (c) is refused. (c) also needs `--prompts FILE`, the runner's own `--prompts-only`
output for the same states: the launcher keeps the longest run of states, in the states file's
order, whose estimated input tokens fit the part's remaining budget at that price (`--limit N`), and
prints only how many states fit. Also (any one stops the part): more than 10% of the last 50 calls failing
(at least 20); phase 1 only, more than 1,000 calls a minute over 2 minutes; the host floors.

Phase 1 runs `battle_diag.py --run NAME --guard-ready <ready> <args>`: the guard starts first;
battle_diag (which refuses a run whose journal folder already exists) creates the mind's journal
folder `.local/living/journal/verify-NAME` after its setup and holds the mind, so every call, until
the guard has seen the folder and written its ready file. A guard that exits before it is ready
stops the runner (SIGINT); battle_diag itself gives up after `--guard-wait-s` with no call made.
The ledger (default `.local/heed-e5/e5-ledger.json`) holds every part's final spend, which later
parts read. `--dry-run-price` (free runs against the fake server only) prices a model so the
guard's arithmetic and its stop can be checked without spending.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPS = {"p1": 20.0, "b": 2.0, "c": 5.0}
TOTAL = 27.0
MARGIN = 0.5
FAIL_LAST = 50
MAX_CALLS_MIN = 1000
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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--part", choices=["p1", "b", "c"], required=True)
    ap.add_argument("--run", help="p1: the battle_diag run name")
    ap.add_argument("--out", help="b|c: the part's folder (its journal is <out>/calls.journal)")
    ap.add_argument("--runner-bin", help="b|c: a built living-mind")
    ap.add_argument("--ledger", default=str(ROOT / ".local/heed-e5/e5-ledger.json"))
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--dry-run-price", action="append", default=[])
    ap.add_argument("--prompts", help="c: the --prompts-only output (est_tokens per request), to fit the state list to the budget")
    ap.add_argument("runner", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    runner_args = [x for x in a.runner if x != "--"]
    if a.part == "p1":
        if not a.run:
            ap.error("--part p1 needs --run")
        out = ROOT / ".local/heed-e5" / a.run
        journal = ROOT / ".local/living/journal" / f"verify-{a.run}"
        arm = f"e5p1-{a.run}"
        cmd = [sys.executable, str(ROOT / "living/tools/battle_diag.py"), "--run", a.run, "--guard-ready", str(out / "guard.ready"), *runner_args]
    else:
        if not (a.out and a.runner_bin):
            ap.error("--part b|c needs --out and --runner-bin")
        out = Path(a.out)
        journal = out / "calls.journal"
        arm = f"e5{a.part}"
        cmd = [a.runner_bin, "heed-replay", *runner_args, "--out", str(out / "calls.jsonl")]
    out.mkdir(parents=True, exist_ok=True)
    ready, pidf = out / "guard.ready", out / "runner.pid"
    for f in (ready, pidf):
        f.unlink(missing_ok=True)
    prices = list(a.dry_run_price)
    if a.part == "c" and not a.dry_run_price:
        p = local_jev_price()
        if p is None:
            print("REFUSED: no local price for jev-1.14.0 (no price, no Jev)", flush=True)
            return 2
        prices.append(f"{JEV}={p},0,0")
    if a.part == "c":
        if not a.prompts:
            ap.error("--part c needs --prompts (the runner's --prompts-only output) to fit the state list to the budget")
        price = next(float(x.split("=", 1)[1].split(",")[0]) for x in prices if x.startswith(JEV + "="))
        try:
            led = json.loads(Path(a.ledger).read_text())["arms"]
        except (OSError, ValueError, KeyError):
            led = []
        prior = [x for x in led if x["arm"] != f"e5{a.part}"]
        budget = min(CAPS["c"] - sum(x["usd"] for x in prior if x["group"] == "e5c"), TOTAL - sum(x["usd"] for x in prior)) - MARGIN
        per_state, order = {}, []
        for line in open(a.prompts):
            r = json.loads(line)
            if r["state"] not in per_state:
                order.append(r["state"])
            per_state[r["state"]] = per_state.get(r["state"], 0) + r["est_tokens"]
        n, spent = 0, 0.0
        for st in order:
            cost = per_state[st] * price / 1e6
            if spent + cost > budget:
                break
            spent, n = spent + cost, n + 1
        if n == 0:
            print("REFUSED: not one state fits the remaining (c) budget", flush=True)
            return 2
        print(f"(c): {n} of {len(order)} states fit the remaining budget at the local price ({'all' if n == len(order) else 'shortened'})", flush=True)
        runner_args = [x for x in runner_args]
        if "--limit" in runner_args:
            ap.error("--part c sets --limit itself")
        runner_args += ["--limit", str(n)]
        cmd = [a.runner_bin, "heed-replay", *runner_args, "--out", str(out / "calls.jsonl")]
    guard_cmd = [sys.executable, "-I", str(ROOT / "living/tools/act_trial.py"), "watch", "--arm", arm, "--group", f"e5{a.part}",
                 "--ledger", a.ledger, "--log", str(out / "guard.log"), "--pid-file", str(pidf), "--journal", str(journal / "*.jsonl"),
                 "--ready", str(ready), "--group-cap", str(CAPS[a.part]), "--total-cap", str(TOTAL), "--margin", str(MARGIN),
                 "--interval", str(a.interval), "--fail-last", str(FAIL_LAST)]
    if a.part == "p1":
        # Setup (publish, spawn, warm-up) comes before the mind's first call.
        guard_cmd += ["--max-calls-min", str(MAX_CALLS_MIN), "--first-journal-s", "900", "--ready-wait-s", "1800"]
    for p in prices:
        guard_cmd += ["--price", p]
    gout = open(out / "guard.out", "a")
    if a.part == "p1":
        guard = subprocess.Popen(guard_cmd, stdout=gout, stderr=subprocess.STDOUT, cwd=ROOT)
        time.sleep(2)
        if guard.poll() is not None:
            print(f"REFUSED: the guard exited ({guard.returncode}) at start; no runner started", flush=True)
            return 2
        rout = open(out / "runner.out", "a")
        runner = subprocess.Popen(cmd, stdout=rout, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=ROOT)
        pidf.write_text(str(runner.pid))
        print(f"guard started (pid {guard.pid}); runner started (pid {runner.pid}), holding its mind until {ready} exists", flush=True)
        while runner.poll() is None and not ready.exists():
            if guard.poll() is not None:
                runner.send_signal(signal.SIGINT)
                print(f"STOPPED: the guard exited ({guard.returncode}) before it was ready; runner interrupted", flush=True)
                break
            time.sleep(0.5)
        if ready.exists():
            print("guard ready: the mind may start", flush=True)
        rc = runner.wait()
        print(f"runner exited {rc}", flush=True)
        try:
            guard.wait(timeout=max(60, a.interval * 3))
        except subprocess.TimeoutExpired:
            guard.terminate()
        print(f"guard exited {guard.returncode}; ledger {a.ledger}", flush=True)
        return rc
    journal.mkdir(parents=True, exist_ok=True)
    guard = subprocess.Popen(guard_cmd, stdout=gout, stderr=subprocess.STDOUT, cwd=ROOT)
    print(f"guard started (pid {guard.pid}) on {journal}; waiting for its ready file before any call", flush=True)
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
    print(f"guard ready after {time.time() - t0:.1f} s", flush=True)
    rout = open(out / "runner.out", "a")
    runner = subprocess.Popen(cmd, stdout=rout, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=ROOT)
    pidf.write_text(str(runner.pid))
    print(f"runner started (pid {runner.pid}) under the guard: {' '.join(cmd[:4])} ...", flush=True)
    rc = runner.wait()
    print(f"runner exited {rc}", flush=True)
    try:
        guard.wait(timeout=max(60, a.interval * 3))
    except subprocess.TimeoutExpired:
        guard.terminate()
    print(f"guard exited {guard.returncode}; ledger {a.ledger}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
