#!/usr/bin/env python3
"""Watch a trial batch's spend and stop it at a ceiling (docs/PACK_MIND.md §8: stop at $8).

  living/tools/pack_spend.py --batch pkp1 --pid RUNNER_PID --stop-usd 8 [--every 30]

Every `--every` seconds it sums the dollars of every model call journaled by every instance of
the batch (the journals' prompt, cached and completion tokens at `trials.PRICES`, as the batch
report prices them), prints the total, and sends the runner SIGINT (its own abort: instances stop
as "aborted" and are collected) once the total reaches `--stop-usd`. It ends when the runner
does. Read-only otherwise.
"""
import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "living/tools"))
import trials  # noqa: E402


def spent(bdir):
    total, calls, unpriced = 0.0, 0, 0
    # The live journals (`.local/living/journal/<db>`, as the runner reads them), else the
    # copies a finished instance keeps (`<instance>/journal`).
    live = list((trials.ROOT / ".local/living/journal").glob(f"verify-trial-{bdir.name}-*/*.jsonl"))
    for f in live or bdir.glob("*/journal/*.jsonl"):
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            calls += 1
            if r.get("cost_usd") is not None:
                total += float(r["cost_usd"])
                continue
            c = trials.cost(r.get("model") or "", r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0, r.get("cached_tokens") or 0)
            if c is None:
                unpriced += 1
            else:
                total += c
    return total, calls, unpriced


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--batch", required=True)
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--stop-usd", type=float, required=True)
    p.add_argument("--every", type=float, default=30)
    a = p.parse_args()
    bdir = trials.OUT / a.batch
    stopped = False
    while True:
        alive = os.path.exists(f"/proc/{a.pid}")
        usd, calls, unpriced = spent(bdir)
        print(f"[{time.strftime('%H:%M:%S')}] {a.batch}: ${usd:.3f} over {calls} calls ({unpriced} unpriced)", flush=True)
        if usd >= a.stop_usd and not stopped and alive:
            print(f"stop: ${usd:.3f} reached the ${a.stop_usd} ceiling; SIGINT to {a.pid}", flush=True)
            os.kill(a.pid, signal.SIGINT)
            stopped = True
        if not alive:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
