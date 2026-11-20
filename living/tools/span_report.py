#!/usr/bin/env python3
"""span_report.py <run-dir>... [--json]: every module Timing span and diagnostic count of a
`battle_viewers.py --detail` (or tick_cost.py) window, per second (combat-phase, 2026-11-20;
docs/COMBAT_PHASE.md).

Reads `<run-dir>/module.log` (take it with `--full-log`: the CLI's tail drops lines under detail
spans) and the window from `result.json`. Per span: calls a second, ms a second, mean, p50 and p99
µs a call. Spans nest (a `brain.graph` holds its `brain.leaf`s), so a parent's ms include its
children's; the tick phases (`tick.*`) partition the tick. Per `diag:` key (`common::diag`, summed
from the once-a-second lines): its rate. Per `scene seen:` line: scenes built and the creatures in
them. Python standard library.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# A span under a microsecond is printed in ns (2.14.1 prints the `Duration` with `{:?}`).
SPAN = re.compile(r'^(\S+Z)\s.*Timing span "([^"]+)": ([\d.]+)(ns|µs|ms|s)\b')
DIAG = re.compile(r'^(\S+Z)\s.*diag: (\{.*\})\s*$')
SCENE = re.compile(r'^(\S+Z)\s.*scene seen: builds=(\d+) seen=(\d+) max=(\d+)')
UNIT = {"ns": 1e-3, "µs": 1.0, "ms": 1e3, "s": 1e6}


def stamp(s):
    s = s.rstrip("Z")
    sec, _, frac = s.partition(".")
    return datetime.strptime(sec, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() + (int((frac + "000000")[:6]) / 1e6 if frac else 0.0)


def q(v, f):
    return v[min(len(v) - 1, int(len(v) * f))] if v else None


def one(d):
    d = Path(d)
    res = json.loads((d / "result.json").read_text())
    t0, t1 = res["window"]["t0"], res["window"]["t1"]
    secs = t1 - t0
    spans, diag, scenes = {}, {}, [0, 0, 0]
    with open(d / "module.log", encoding="utf-8", errors="replace") as f:
        for line in f:
            if "Timing span" in line:
                m = SPAN.match(line)
                if m and t0 <= stamp(m.group(1)) < t1:
                    spans.setdefault(m.group(2), []).append(float(m.group(3)) * UNIT[m.group(4)])
            elif "diag: " in line:
                m = DIAG.match(line)
                if m and t0 <= stamp(m.group(1)) < t1:
                    for k, v in json.loads(m.group(2)).items():
                        diag[k] = diag.get(k, 0) + v
            elif "scene seen:" in line:
                m = SCENE.match(line)
                if m and t0 <= stamp(m.group(1)) < t1:
                    scenes[0] += int(m.group(2))
                    scenes[1] += int(m.group(3))
                    scenes[2] = max(scenes[2], int(m.group(4)))
    rows = {}
    for k, v in spans.items():
        v.sort()
        rows[k] = {"calls_per_s": len(v) / secs, "ms_per_s": sum(v) / 1e3 / secs, "mean_us": sum(v) / len(v), "p50_us": q(v, .5), "p99_us": q(v, .99), "max_us": v[-1]}
    return {
        "run": str(d), "seconds": secs, "viewers": res.get("viewers"), "fighters": res.get("fighters"), "ticks_per_s": res.get("ticks_per_s"),
        "spans": dict(sorted(rows.items(), key=lambda kv: -kv[1]["ms_per_s"])),
        "diag_per_s": {k: v / secs for k, v in sorted(diag.items())},
        "scenes": {"builds_per_s": scenes[0] / secs, "mean_seen": scenes[1] / scenes[0] if scenes[0] else None, "max_seen": scenes[2]},
    }


def table(r):
    print(f"\n## {r['run']}\n\n{r['viewers']} viewers, {r['fighters']} fighters, {r['ticks_per_s']} ticks/s over {r['seconds']:.1f} s; "
          f"scenes {r['scenes']['builds_per_s']:.0f}/s, mean {r['scenes']['mean_seen']} creatures (max {r['scenes']['max_seen']})\n")
    print("| span | calls/s | ms/s | mean µs | p50 µs | p99 µs |\n|---|---:|---:|---:|---:|---:|")
    for k, v in r["spans"].items():
        print(f"| {k} | {v['calls_per_s']:.1f} | {v['ms_per_s']:.2f} | {v['mean_us']:.1f} | {v['p50_us']:.1f} | {v['p99_us']:.1f} |")
    print("\n| diag | per s |\n|---|---:|")
    for k, v in r["diag_per_s"].items():
        print(f"| {k} | {v:.1f} |")


if __name__ == "__main__":
    out = [one(a) for a in sys.argv[1:] if a != "--json"]
    if "--json" in sys.argv:
        print(json.dumps(out, indent=1))
    else:
        for r in out:
            table(r)
