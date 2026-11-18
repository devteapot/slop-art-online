#!/usr/bin/env python3
"""tick_report.py <run-dir>...: a tick_cost.py run's numbers, per second of the measured window
(tick-rate, 2026-11-13; docs/TICK_RATE.md).

Per run: ticks a second and the gaps between them in 60 Hz slots; the scheduler's delay (due against
started, from the tick grid and from the server's histogram); the tick's body (span) and its whole
call (`spacetime_reducer_plus_query_duration_sec`: the body, the views it triggered, the commit and
the subscription evaluation); per reducer, calls and ms a second (WASM, whole call, queue wait); per
view, calls and ms a second (the function, and with materializing); the database thread's CPU and the
server's; bytes sent; the host's load. `--json` prints the rows as JSON instead of tables.
"""

import json
import re
import statistics
import sys
from pathlib import Path


def labels(key):
    return dict(re.findall(r'(\w+)="([^"]*)"', key))


def series(diff, name):
    for k, v in diff.items():
        if k.split("{", 1)[0] == name:
            yield labels(k), v


def one(d):
    d = Path(d)
    m = json.loads((d / "metrics.json").read_text())
    t = json.loads((d / "ticks.json").read_text())
    th = json.loads((d / "threads.json").read_text())
    res = json.loads((d / "result.json").read_text())
    s, diff = m["seconds"], m["diff"]
    r = {"run": d.name, "seconds": round(s, 1), "in_sight": res.get("held_at_ready", {}).get("seen_characters_mean")}
    r["ticks_per_s"] = t.get("ticks_per_s")
    r["gap_slots"] = t.get("gap_slots")
    r["delay_ms_grid"] = {k: round(v, 2) for k, v in t.get("delay_ms", {}).items()}
    r["tick_body_ms"] = {k: round(v, 2) for k, v in t.get("body_ms", {}).items()}
    # Per reducer: committed transactions, WASM time, whole call, wait.
    red = {}
    for lb, v in series(diff, "spacetime_num_txns_total"):
        if lb.get("txn_type") == "Reducer":
            red.setdefault(lb["reducer"], {})["calls_per_s"] = red.get(lb["reducer"], {}).get("calls_per_s", 0) + v / s
    for lb, v in series(diff, "spacetime_reducer_plus_query_duration_sec_sum"):
        red.setdefault(lb["reducer"], {})["call_ms_per_s"] = v * 1e3 / s
    for lb, v in series(diff, "reducer_wasm_time_usec"):
        red.setdefault(lb["reducer"], {})["wasm_ms_per_s"] = v / 1e3 / s
    for lb, v in series(diff, "spacetime_txn_cpu_time_sec_sum"):
        key = "txn_cpu_ms_per_s" if lb.get("txn_type") == "Reducer" else "update_cpu_ms_per_s"
        red.setdefault(lb["reducer"], {})[key] = red.get(lb["reducer"], {}).get(key, 0) + v * 1e3 / s
    for lb, v in series(diff, "view_calls_triggered_by_reducer"):
        red.setdefault(lb["reducer"], {})["views_per_s"] = v / s
    waits = {}
    for lb, v in series(diff, "spacetime_reducer_wait_time_sec_sum"):
        waits.setdefault(lb["reducer"], {})["sum"] = v
    for lb, v in series(diff, "spacetime_reducer_wait_time_sec_count"):
        waits.setdefault(lb["reducer"], {})["n"] = v
    r["wait_ms_mean"] = {k: round(w["sum"] / w["n"] * 1e3, 3) for k, w in waits.items() if w.get("n")}
    r["wait_ms_per_s"] = {k: round(w["sum"] * 1e3 / s, 1) for k, w in waits.items() if w.get("n")}
    views = {}
    for name, key in (("view_calls", "calls_per_s"), ("view_call_time_usec", "fn_ms_per_s"), ("view_total_time_usec", "total_ms_per_s")):
        for lb, v in series(diff, name):
            views.setdefault(lb["view"], {})[key] = v / s / (1e3 if "usec" in name else 1)
    r["views"] = {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in sorted(views.items(), key=lambda kv: -kv[1].get("total_ms_per_s", 0)) if v.get("calls_per_s")}
    r["reducers"] = {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in sorted(red.items(), key=lambda kv: -kv[1].get("call_ms_per_s", 0)) if v.get("calls_per_s") or v.get("wasm_ms_per_s")}
    dl = dict(series(diff, "spacetime_scheduled_function_delay_seconds_sum").__iter__()) if False else None
    sd = {lb["function"]: v for lb, v in series(diff, "spacetime_scheduled_function_delay_seconds_sum")}
    sc = {lb["function"]: v for lb, v in series(diff, "spacetime_scheduled_function_delay_seconds_count")}
    r["sched_delay_ms_mean"] = {k: round(sd[k] / sc[k] * 1e3, 3) for k in sd if sc.get(k)}
    r["sched_delay_buckets_tick"] = {lb["le"]: v for lb, v in series(diff, "spacetime_scheduled_function_delay_seconds_bucket") if lb.get("function") == "tick"}
    r["tick_call_buckets"] = {lb["le"]: v for lb, v in series(diff, "spacetime_reducer_plus_query_duration_sec_bucket") if lb.get("reducer") == "tick"}
    wasm_thread = [v for k, vs in th["threads_cpu_ms_per_s"].items() if k.startswith("wasm-") for v in vs]
    r["db_thread_cpu_ms_per_s"] = round(sum(wasm_thread), 1)
    r["process_cpu_ms_per_s"] = th["process_cpu_ms_per_s"]
    r["other_threads_cpu_ms_per_s"] = {k: round(sum(vs), 1) for k, vs in th["threads_cpu_ms_per_s"].items() if not k.startswith("wasm-")}
    r["calls_ms_per_s_all"] = round(sum(v.get("call_ms_per_s", 0) for v in red.values()), 1)
    r["bytes_sent_per_s"] = res.get("bytes_sent_per_s")
    sp = res.get("spans_ms_per_s", {})
    r["spans_ms_per_s"] = sp
    # Subscription traffic: the server's totals for this database (every connection), the mind
    # probe's own (the owner's subscription), and the players' share (the rest, per player).
    tot = lambda name: sum(v for _, v in series(diff, name))
    sub = {"messages_per_s": tot("spacetime_websocket_sent_msg_size_bytes_count") / s, "payload_bytes_per_s": tot("spacetime_websocket_sent_msg_size_bytes_sum") / s,
           "rows_per_s": tot("spacetime_websocket_sent_num_rows_sum") / s, "bytes_sent_per_s": tot("spacetime_num_bytes_sent_to_clients_total") / s,
           "serialize_ms_per_s": tot("spacetime_websocket_serialize_secs_sum") * 1e3 / s,
           "pong_rtt_ms_mean": (tot("spacetime_websocket_pong_rtt_secs_sum") / tot("spacetime_websocket_pong_rtt_secs_count") * 1e3) if tot("spacetime_websocket_pong_rtt_secs_count") else None}
    mind = None
    if (d / "mind.json").exists():
        md = (json.loads((d / "mind.json").read_text()) or {}).get("done") or {}
        if md.get("seconds"):
            ms = md["seconds"]
            rows = {k: sum(v) / ms for k, v in md.get("events", {}).items()}
            mind = {"messages_per_s": md["messages"] / ms, "wire_bytes_per_s": md["bytes"] / ms, "rows_per_s": sum(rows.values()),
                    "rows_per_s_by_table": {k: round(v, 1) for k, v in sorted(rows.items(), key=lambda kv: -kv[1])}, "lag_ms": md.get("lag_ms")}
    players = res.get("players", 216)
    if mind:
        sub["players_messages_per_s_each"] = (sub["messages_per_s"] - mind["messages_per_s"]) / players
        sub["players_rows_per_s_each"] = (sub["rows_per_s"] - mind["rows_per_s"]) / players
        sub["players_bytes_per_s_each"] = (sub["bytes_sent_per_s"] - mind["wire_bytes_per_s"]) / players
    r["subscriptions"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in sub.items()}
    r["mind_probe"] = mind
    if (d / "gauges.json").exists():
        g = json.loads((d / "gauges.json").read_text())
        cols = g["columns"]
        r["gauges_max"] = {c: max((row[i] for row in g["rows"]), default=None) for i, c in enumerate(cols) if i}
    loads = [float(l.split()[1]) for l in (d / "load.log").read_text().splitlines() if l.strip()]
    r["load_min_med_max"] = [min(loads), statistics.median(loads), max(loads)] if loads else None
    return r


def table(rows):
    print("| run | ticks/s | gaps (slots: n) | sched delay p50/p99 ms (grid) | tick body p50/p99 ms | tick call ms/s | all calls ms/s | db thread CPU ms/s | process CPU ms/s | in sight | load min/med/max |")
    print("|" + "---|" * 11)
    for r in rows:
        tick = r["reducers"].get("tick", {})
        print(f"| {r['run']} | {r['ticks_per_s']} | {r['gap_slots']} | {r['delay_ms_grid'].get('p50')} / {r['delay_ms_grid'].get('p99')} | {r['tick_body_ms'].get('p50')} / {r['tick_body_ms'].get('p99')} | {tick.get('call_ms_per_s')} | {r['calls_ms_per_s_all']} | {r['db_thread_cpu_ms_per_s']} | {r['process_cpu_ms_per_s']} | {r['in_sight']} | {r['load_min_med_max']} |")
    for r in rows:
        print(f"\n### {r['run']}\n\n| reducer | calls/s | WASM ms/s | whole call ms/s | views triggered/s | wait mean ms |\n|---|---|---|---|---|---|")
        for k, v in r["reducers"].items():
            print(f"| {k} | {v.get('calls_per_s', 0):.1f} | {v.get('wasm_ms_per_s', 0):.1f} | {v.get('call_ms_per_s', 0):.1f} | {v.get('views_per_s', 0):.0f} | {r['wait_ms_mean'].get(k, r['wait_ms_mean'].get('scheduled reducer') if k in ('tick', 'housekeeping') else '')} |")
        su, mp = r["subscriptions"], r["mind_probe"]
        print(f"\nSubscriptions (all connections): {su.get('messages_per_s')} messages/s, {su.get('rows_per_s')} rows/s, {su.get('bytes_sent_per_s')} B/s; per player {su.get('players_messages_per_s_each')} messages/s, {su.get('players_rows_per_s_each')} rows/s, {su.get('players_bytes_per_s_each')} B/s; serialize {su.get('serialize_ms_per_s')} ms/s; pong RTT mean {su.get('pong_rtt_ms_mean')} ms; queue gauges max {r.get('gauges_max')}")
        if mp:
            print(f"Mind probe (owner): {mp['messages_per_s']:.1f} messages/s, {mp['rows_per_s']:.1f} rows/s, {mp['wire_bytes_per_s']:.0f} B/s; rows/s by table {mp['rows_per_s_by_table']}; lag {mp['lag_ms']}")
        print("\n| view | calls/s | function ms/s | with materializing ms/s | µs per call |\n|---|---|---|---|---|")
        for k, v in r["views"].items():
            print(f"| {k} | {v.get('calls_per_s', 0):.0f} | {v.get('fn_ms_per_s', 0):.1f} | {v.get('total_ms_per_s', 0):.1f} | {1e3 * v.get('total_ms_per_s', 0) / max(v.get('calls_per_s', 1), 1e-9):.0f} |")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--json"]
    rows = [one(a) for a in args]
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=1))
    else:
        table(rows)
