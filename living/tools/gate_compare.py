#!/usr/bin/env python3
"""Side-by-side numbers of gate runs (docs/GATE_216.md): one column per run, one table per window.

    living/tools/gate_compare.py .local/living/gate/<run> [<run> ...] [--windows calm,battle]

Reads each run's `report.json` (written by `gate.py analyze`) and prints a Markdown table of the
numbers the contract's lines are judged on, plus the costs behind them: steps, the tick's code
and transaction, view calls and the views' WASM time, latency by input kind, the database queue,
bytes per connection, CPU and the host's load.
"""
import argparse
import json
from pathlib import Path


def get(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict) or p not in d:
            return default
        d = d[p]
    return d


def q(d, keys=("p50", "p95", "p99")):
    if not d:
        return "—"
    return " / ".join(f"{d[k]:.1f}" if isinstance(d.get(k), (int, float)) else "—" for k in keys)


def views(sm, n=5):
    w = get(sm, "per_second", "reducer_wasm_time_usec", default={}) or {}
    v = {k: x / 1000 for k, x in w.items() if k.startswith(("seen_", "my_"))}
    top = sorted(v.items(), key=lambda kv: -kv[1])[:n]
    return f"{sum(v.values()):.0f}: " + ", ".join(f"{k} {x:.1f}" for k, x in top)


def rows(r, w):
    t = get(r, "ticks", w, default={})
    sm = get(r, "server_metrics", w, default={})
    i = get(r, "inputs", w, default={})
    b = get(r, "bytes", w, default={})
    res = get(r, "resources", w, default={})
    cs = get(i, "server_receipt_to_result_ms", default={})
    cc = get(i, "client_input_to_result_ms", default={})
    calls = get(sm, "per_second", "view_calls_triggered_by_reducer", default={}) or {}
    qlen = get(sm, "gauges", "spacetime_worker_instance_operation_queue_length", default={}) or {}
    wait = get(sm, "spacetime_reducer_wait_time_sec", "human_move", default={}) or {}
    tx = get(sm, "spacetime_reducer_plus_query_duration_sec", "tick", default={}) or {}
    spans = get(r, "spans_ms_per_s", w, default={}) or {}
    return [
        ("Steps/s; grid steps skipped", f"{t.get('steps_per_s', 0):.1f}; {t.get('skipped_grid_steps', '—')} of {t.get('expected_steps', '—')}"),
        ("Step interval p50 / p95 / p99 (ms)", q(t.get("interval_ms"))),
        ("Tick code p50 / p95 / p99 (ms)", q(t.get("tick_code_ms"))),
        ("Tick transaction mean (ms)", f"{tx.get('mean_ms', 0):.2f}"),
        ("Tick spans ms/s: frames, perception", f"{spans.get('tick.frames', 0):.1f}, {spans.get('tick.perception', 0):.1f}"),
        ("View calls/s (tick, human_move, use_skill)", f"{sum(calls.values()):.0f} ({calls.get('tick', 0):.0f}, {calls.get('human_move', 0):.0f}, {calls.get('use_skill', 0):.0f})"),
        ("Views' WASM ms/s: total: top", views(sm)),
        ("Move, server receipt → committed p50 / p95 / p99", q(cs.get("move"))),
        ("Move, client input → received p50 / p95 / p99", q(cc.get("move"))),
        ("Skill outcome, server p50 / p95 / p99", q(cs.get("skill_outcome"))),
        ("Skill outcome, client p50 / p95 / p99", q(cc.get("skill_outcome"))),
        ("Step → delivered p95, unconfirmed / confirmed", f"{get(t, 'step_start_to_delivered_ms', 'unconfirmed', 'p95', default=0):.1f} / {get(t, 'step_start_to_delivered_ms', 'confirmed', 'p95', default=0):.1f}"),
        ("Queue wait, human_move mean (ms)", f"{wait.get('mean_ms', 0):.1f}"),
        ("Operation queue (end)", f"{qlen.get('end', '—')}"),
        ("Unanswered; accepted without outcome", f"{i.get('unanswered', '—')}; {i.get('accepted_without_outcome', '—')}"),
        ("Bytes/s battle player / walker p50", f"{get(b, 'battle_B_per_s', 'p50', default=0):.0f} / {get(b, 'walker_B_per_s', 'p50', default=0):.0f}"),
        ("Server CPU (cores)", f"{res.get('server_cpu_cores', 0):.2f}"),
        ("Host load (1 min) p50", f"{get(res, 'load_avg_1m', 'p50', default=0):.1f}"),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--windows", default="calm,battle")
    a = ap.parse_args()
    reports = [(Path(p).name, json.loads((Path(p) / "report.json").read_text())) for p in a.runs]
    for w in a.windows.split(","):
        print(f"\n### {w}\n")
        print("| | " + " | ".join(n for n, _ in reports) + " |")
        print("|---|" + "---|" * len(reports))
        cols = [rows(r, w) for _, r in reports]
        for k in range(len(cols[0])):
            print(f"| {cols[0][k][0]} | " + " | ".join(c[k][1] for c in cols) + " |")


if __name__ == "__main__":
    main()
