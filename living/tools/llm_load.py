#!/usr/bin/env python3
"""LLM load from the mind journal: calls, failures, tokens and latency per minute,
by purpose and by character kind (people vs animals).

Usage: living/tools/llm_load.py [--run realm-1] [--minutes 15] [--span]
With --span, rates are per minute of the journal's own span (first to last call in the
window), which suits short experiments. Keys: `all`, `purpose:<p>`, `model:<m>` and
`purpose:<p>/model:<m>` (e.g. conversation turns per model: `purpose:talk/model:...`).
"""
import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("LIVING_ROOT") or Path(__file__).resolve().parents[2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="realm-1")
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--span", action="store_true", help="rate over the calls' own time span")
    a = ap.parse_args()
    since = time.time() * 1000 - a.minutes * 60000
    by = defaultdict(lambda: {"calls": 0, "errors": 0, "tokens": 0, "latency": []})
    first, last = None, None
    for f in (ROOT / ".local/living/journal" / a.run).glob("*.jsonl"):
        for line in f.open():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("at_ms", 0) < since:
                continue
            at = r.get("at_ms", 0)
            first = at if first is None else min(first, at)
            last = at if last is None else max(last, at)
            for key in (f"purpose:{r.get('purpose')}", f"model:{r.get('model')}", f"purpose:{r.get('purpose')}/model:{r.get('model')}", "all"):
                b = by[key]
                b["calls"] += 1
                b["errors"] += 1 if r.get("error") else 0
                b["tokens"] += r.get("tokens") or 0
                b["latency"].append(r.get("latency_ms") or 0)
    minutes = a.minutes
    if a.span and first is not None:
        minutes = max((last - first) / 60000, 1 / 60)
    out = {"minutes": round(minutes, 2)}
    for k, b in sorted(by.items()):
        lat = sorted(b["latency"]) or [0]
        out[k] = {
            "calls": b["calls"],
            "calls_per_min": round(b["calls"] / minutes, 1),
            "errors": b["errors"],
            "tokens_per_min": round(b["tokens"] / minutes),
            "latency_p50_ms": lat[len(lat) // 2],
            "latency_p95_ms": lat[int(len(lat) * 0.95) - 1 if len(lat) > 1 else 0],
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
