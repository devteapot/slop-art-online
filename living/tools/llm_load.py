#!/usr/bin/env python3
"""LLM load from the mind journal: calls, failures, tokens and latency per minute,
by purpose and by character kind (people vs animals).

Usage: living/tools/llm_load.py [--run realm-1] [--minutes 15]
"""
import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="realm-1")
    ap.add_argument("--minutes", type=float, default=15)
    a = ap.parse_args()
    since = time.time() * 1000 - a.minutes * 60000
    by = defaultdict(lambda: {"calls": 0, "errors": 0, "tokens": 0, "latency": []})
    for f in (ROOT / ".local/living/journal" / a.run).glob("*.jsonl"):
        for line in f.open():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("at_ms", 0) < since:
                continue
            kind = "animal" if r.get("profile") == "ministral" or r.get("species") in ("deer", "wolf") else "person"
            for key in (f"purpose:{r.get('purpose')}", f"model:{r.get('model')}", "all"):
                b = by[key]
                b["calls"] += 1
                b["errors"] += 1 if r.get("error") else 0
                b["tokens"] += r.get("tokens") or 0
                b["latency"].append(r.get("latency_ms") or 0)
    out = {}
    for k, b in sorted(by.items()):
        lat = sorted(b["latency"]) or [0]
        out[k] = {
            "calls_per_min": round(b["calls"] / a.minutes, 1),
            "errors": b["errors"],
            "tokens_per_min": round(b["tokens"] / a.minutes),
            "latency_p50_ms": lat[len(lat) // 2],
            "latency_p95_ms": lat[int(len(lat) * 0.95) - 1 if len(lat) > 1 else 0],
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
