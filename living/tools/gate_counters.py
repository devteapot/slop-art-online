#!/usr/bin/env python3
"""Per-second rates of the server's Prometheus counters over a gate run's window
(docs/GATE_216.md): `gate_counters.py <run dir> [window] [--match regex]`.

Takes the first and last sample inside the window from `samples.jsonl.gz` and prints the
counters' differences per second, summed over all label sets except the ones named in
`--by` (default: `reducer` and `view`), for the run's database and server-wide series.
"""
import argparse
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{([^}]*)\})? (\S+)$')


def parse(lines, by):
    out = defaultdict(float)
    for l in lines:
        m = LINE.match(l)
        if not m:
            continue
        name, labels, value = m.group(1), m.group(3) or "", m.group(4)
        lab = dict(re.findall(r'(\w+)="([^"]*)"', labels))
        key = name + "".join(f"[{lab[b]}]" for b in by if b in lab)
        try:
            out[key] += float(value)
        except ValueError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("window", nargs="?", default="battle")
    ap.add_argument("--match", default="")
    ap.add_argument("--by", default="reducer,view_name,view,txn_type")
    a = ap.parse_args()
    d = Path(a.run)
    m = json.loads((d / "marks.json").read_text())
    t0, t1 = {"window": (m["window_start"], m["window_end"]), "calm": (m["window_start"], m["battle_start"]), "battle": (m["battle_start"], m["window_end"])}[a.window]
    by = a.by.split(",")
    samples = [json.loads(l) for l in gzip.open(d / "samples.jsonl.gz", "rt")]
    samples = [s for s in samples if "metrics" in s]
    inside = [s for s in samples if t0 <= s["t"] <= t1]
    first, last = inside[0], inside[-1]
    secs = last["t"] - first["t"]
    a0, a1 = parse(first["metrics"], by), parse(last["metrics"], by)
    rx = re.compile(a.match)
    for k in sorted(a1):
        if not rx.search(k):
            continue
        dv = a1[k] - a0.get(k, 0.0)
        if dv:
            print(f"{k}\t{dv / secs:.2f}/s")


if __name__ == "__main__":
    main()
