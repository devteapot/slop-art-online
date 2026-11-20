#!/usr/bin/env python3
"""The mind's dispatch profile for one battle run (docs/INPUT_LATENCY.md, "Mind dispatch profile").

  python3 -I living/tools/dispatch_profile.py RUN_DIR [--window-s 300] [--json OUT]

RUN_DIR is a battle_diag run directory (`.local/living/verify/<run>`) from a mind started with
`LIVING_INPUT_LATENCY=1`. Reads, inside the measured window (`measure-start-ms.txt` onward):

- `journal/outcomes/input_latency_deliberation.jsonl`: each deliberation's stages, joined to the
  fake provider's receipt (`fake-requests.jsonl`, the `X-Living-Battle-Timing` header) for its
  lane by the deliberation's start;
- `journal/outcomes/input_latency_fast.jsonl`: each fast ask's stages;
- `mind.log`: the 5 s `input_latency_prof` summaries (event queue, locks, SDK cache probe,
  runtime) and `grant stall` lines.

Percentiles are nearest-rank over the joined samples. Series summaries are per 5 s window; the
report gives each series' total time, the median and largest of its window p95s, and its max.
"""
import argparse
import json
import re
import sys
from pathlib import Path


def q(v, p):
    if not v:
        return None
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]


def dist(v):
    return {"n": len(v), "p50": q(v, .5), "p90": q(v, .9), "p95": q(v, .95), "p99": q(v, .99), "max": max(v) if v else None}


def rows(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


DELIB = [("callback", "dispatch"), ("dispatch", "spawned"), ("spawned", "slept"), ("slept", "found"), ("found", "gated"),
         ("gated", "start"), ("start", "lane"), ("lane", "character"), ("character", "recall"), ("recall", "experiences"),
         ("experiences", "context"), ("context", "prompt"), ("prompt", "enqueue"), ("enqueue", "grant"), ("grant", "reply")]
FAST = [("callback_ms", "dispatch_ms"), ("dispatch_ms", "picked_ms"), ("picked_ms", "model_start_ms"),
        ("model_start_ms", "queue_enter_ms"), ("queue_enter_ms", "grant_ms"), ("grant_ms", "model_reply_ms"),
        ("model_reply_ms", "patch_send_ms")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--window-s", type=float, default=300)
    ap.add_argument("--json")
    a = ap.parse_args()
    d = Path(a.run_dir)
    start = int((d / "measure-start-ms.txt").read_text())
    end = start + int(a.window_s * 1000)
    inside = lambda ms: ms is not None and start <= ms < end
    out = {"run": d.name, "window_ms": [start, end]}

    # Lanes by deliberation start, from the fake provider's think receipts.
    lane_at = {}
    for r in rows(d / "fake-requests.jsonl"):
        t = r.get("timing") or {}
        if r.get("purpose") == "think" and t.get("deliberation_started_ms"):
            lane_at.setdefault(t["deliberation_started_ms"], t.get("lane"))

    def lane_of(ms):
        for k in (ms, ms - 1, ms + 1, ms - 2, ms + 2):
            if k in lane_at:
                return lane_at[k]
        return "unjoined"

    by_lane = {}
    for x in rows(d / "journal/outcomes/input_latency_deliberation.jsonl"):
        m = dict(x.get("marks") or {})
        if not inside(m.get("start")):
            continue
        m["callback"], m["dispatch"] = x.get("callback_ms"), x.get("dispatch_ms")
        m["requested"], m["updated"] = x.get("requested_ms"), x.get("updated_ms")
        lane = lane_of(m["start"]) if "enqueue" in m else "no_call"
        b = by_lane.setdefault(lane, {})
        for s, e in DELIB + [("start", "enqueue"), ("start", "grant"), ("callback", "start"), ("callback", "enqueue"),
                             ("updated", "start"), ("requested", "enqueue")]:
            if m.get(s) is not None and m.get(e) is not None:
                b.setdefault(f"{s}->{e}", []).append(m[e] - m[s])
    out["deliberation"] = {lane: {k: dist(v) for k, v in b.items()} for lane, b in sorted(by_lane.items())}

    fast = {}
    for x in rows(d / "journal/outcomes/input_latency_fast.jsonl"):
        if not inside(x.get("callback_ms")):
            continue
        for s, e in FAST + [("callback_ms", "queue_enter_ms"), ("callback_ms", "model_reply_ms"), ("issued_ms", "callback_ms")]:
            if x.get(s) is not None and x.get(e) is not None:
                fast.setdefault(f"{s[:-3]}->{e[:-3]}", []).append(x[e] - x[s])
    out["fast"] = {k: dist(v) for k, v in fast.items()}

    series = {}
    log = (d / "mind.log").read_text(errors="replace") if (d / "mind.log").exists() else ""
    for m in re.finditer(r"input_latency_prof (\d+) (\{.*\})", log):
        at = int(m.group(1))
        if not inside(at):
            continue
        for k, v in json.loads(m.group(2)).items():
            s = series.setdefault(k, {"n": 0, "sum": 0, "p95s": [], "p50s": [], "max": 0})
            n, total, p50, p90, p95, p99, mx = v
            s["n"] += n
            s["sum"] += total
            s["p95s"].append(p95)
            s["p50s"].append(p50)
            s["max"] = max(s["max"], mx)
    out["series"] = {k: {"n": s["n"], "sum": s["sum"], "p50_median": q(s["p50s"], .5), "p95_median": q(s["p95s"], .5),
                         "p95_max": max(s["p95s"]), "max": s["max"]} for k, s in sorted(series.items())}
    stalls = [(int(m.group(1)), int(m.group(2))) for m in re.finditer(r"grant stall: (\d+) ms with up to (\d+) ready", log)]
    out["grant_stalls"] = {"n": len(stalls), "max_ms": max((s[0] for s in stalls), default=0), "total_ms": sum(s[0] for s in stalls)}
    text = json.dumps(out, indent=1)
    if a.json:
        Path(a.json).write_text(text)
    print(text)


if __name__ == "__main__":
    sys.exit(main())
