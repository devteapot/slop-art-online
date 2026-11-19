#!/usr/bin/env python3
"""Where the database thread's time goes between ticks (tick-rate, 2026-11-13; docs/TICK_RATE.md):
look_cost.py's crowd (216 real players in clusters, walking circles), measured with the server's own
counters as well as the module's spans.

    tick_cost.py --label NAME --wasm FILE --load GATE_LOAD [look_cost.py's options]

It runs look_cost.py's workload (publish fresh as `verify-lookcost-<label>-<stamp>`, join, place,
walk, profile a window, delete), and around the same window it also records:

1. Every Prometheus series of `/v1/metrics` that names this database (`db=` or `database_identity=`),
   before and after the window, and their difference: `reducer_wasm_time_usec` (a reducer's or a
   view's WASM time, by name), `view_call_time_usec` / `view_total_time_usec` / `view_calls` (by view;
   the total includes materializing the view's rows), `view_calls_triggered_by_reducer`,
   `spacetime_reducer_plus_query_duration_sec` (a reducer's whole call: its body, the views it
   triggered, the commit and the subscription evaluation, by reducer), `spacetime_txn_elapsed_time_sec`
   and `spacetime_txn_cpu_time_sec` (by transaction kind and reducer), `spacetime_reducer_wait_time_sec`
   (time queued for the instance, by reducer; ticks are "scheduled reducer"),
   `spacetime_scheduled_function_delay_seconds` (due against started, by function), the row and
   delta-query counters. Histograms keep their buckets.
2. The CPU each thread of the server process used in the window (`/proc/<pid>/task/*/stat`, by
   thread name), and the server process's CPU in all.
3. Each tick's start, end and scheduler delay, from the module's `Timing span "tick"` lines: a line is
   logged when the tick's span ends, so the tick's body ran from (stamp - span) to stamp. Ticks are due
   on a fixed 16,667 µs grid (an interval schedule is anchored to its first due time, and missed
   boundaries are skipped: `next_interval_tick_after` in 2.14.1 `scheduler.rs`). The grid's phase is
   where the largest empty arc of start residues (modulo the interval) ends, so each start's delay
   is (start - phase) mod the interval, assuming no tick started a whole interval late. The
   server's own `spacetime_scheduled_function_delay_seconds` is the reference.

4. With `--mind-probe` (the default; `--no-mind-probe` to leave it out): an owner connection that
   subscribes what the mind service subscribes (`gate-load mind`), so the owner's subscription
   traffic is measured apart from the players': its WebSocket messages, bytes, rows per table
   and how late time-stamped rows reach it. It joins before the window and is counted in the
   server's totals.
5. Every second of the window, the server's queue gauges for this database
   (`spacetime_subscription_send_queue_length`, `spacetime_total_outgoing_queue_length`,
   `spacetime_worker_instance_operation_queue_length`, `spacetime_total_incoming_queue_length`).

Writes `<out>/metrics.json` (before, after and the difference), `<out>/threads.json`,
`<out>/ticks.json`, `<out>/mind.json` and `<out>/gauges.json` beside look_cost.py's `result.json`
and `module.log`. `frames.json` records the served scene rows and authority frame cadence per viewer.
Python standard library.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import look_cost  # noqa: E402

INTERVAL_US = 16_667
LINE = re.compile(r'^([A-Za-z_:][A-Za-z0-9_:]*)(\{[^}]*\})? (\S+)$')


def scrape(ident):
    """Every series naming the database: {"name{labels}": value}."""
    text = urllib.request.urlopen(f"{look_cost.URL}/v1/metrics", timeout=60).read().decode()
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or ident not in line:
            continue
        m = LINE.match(line)
        if m:
            try:
                out[m.group(1) + (m.group(2) or "")] = float(m.group(3))
            except ValueError:
                pass
    return out


def server_pid():
    return int(subprocess.run(["podman", "inspect", look_cost.CONTAINER, "--format", "{{.State.Pid}}"], capture_output=True, text=True, check=True).stdout.strip())


def thread_cpu(pid):
    """{tid: (name, utime+stime in clock ticks)} for the server's threads."""
    out = {}
    for tid in os.listdir(f"/proc/{pid}/task"):
        try:
            stat = open(f"/proc/{pid}/task/{tid}/stat").read()
        except OSError:
            continue
        name = stat[stat.index("(") + 1: stat.rindex(")")]
        f = stat[stat.rindex(")") + 2:].split()
        out[tid] = (name, int(f[11]) + int(f[12]))
    return out


def ticks(log, t0, t1):
    rx = re.compile(r'^(\S+Z)\s.*Timing span "tick": ([\d.]+)(µs|ms|s)\b')
    rows = []
    for line in log.splitlines():
        m = rx.match(line)
        if not m:
            continue
        stamp = m.group(1).rstrip("Z")
        sec, _, frac = stamp.partition(".")
        base = datetime.strptime(sec, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        end_us = int(round(base * 1e6)) + (int((frac + "000000")[:6]) if frac else 0)
        dur_us = float(m.group(2)) * {"µs": 1.0, "ms": 1e3, "s": 1e6}[m.group(3)]
        if t0 * 1e6 <= end_us < t1 * 1e6:
            rows.append((end_us - dur_us, end_us, dur_us))
    if not rows:
        return {}
    # The grid's phase: the start residues cluster just after it, so it is where the largest
    # empty arc of residues ends (robust to residues that straddle the interval's wrap).
    res = sorted(s % INTERVAL_US for s, _, _ in rows)
    arcs = [(res[0] + INTERVAL_US - res[-1], res[0])] + [(b - a, b) for a, b in zip(res, res[1:])]
    phase = max(arcs)[1]
    delays = [((s - phase) % INTERVAL_US) / 1e3 for s, _, _ in rows]
    starts = [s for s, _, _ in rows]
    gaps = [(b - a) / 1e3 for a, b in zip(starts, starts[1:])]
    slots = [round(g / (INTERVAL_US / 1e3)) for g in gaps]
    q = lambda v, f: sorted(v)[min(len(v) - 1, int(len(v) * f))] if v else None
    return {
        "n": len(rows), "seconds": round((t1 - t0), 1), "ticks_per_s": round(len(rows) / (t1 - t0), 2),
        "gap_slots": {str(k): slots.count(k) for k in sorted(set(slots))},
        "delay_ms": {"p50": q(delays, .5), "p90": q(delays, .9), "p99": q(delays, .99), "max": max(delays), "mean": sum(delays) / len(delays)},
        "body_ms": {"p50": q([d / 1e3 for _, _, d in rows], .5), "p99": q([d / 1e3 for _, _, d in rows], .99)},
        # Wall-clock timestamps from the module log, with grid-relative estimates.
        "body_over_16_7_ms_pct": 100 * sum(d > 16_700 for _, _, d in rows) / len(rows),
        "columns": ["start_us", "end_us", "grid_offset_ms", "body_ms", "slots_to_next"],
        "rows": [[round(r[0]), r[1], round(d, 3), round(r[2] / 1e3, 3), s]
                 for d, r, s in zip(delays, rows, slots + [None])],
    }


def frame_cadence(log, t0, t1):
    """Count scene rows scheduled for delivery, including rows that needed no write."""
    pattern = re.compile(r'frame cadence: (\d+) (\d+) (\[.*\])$')
    pair_pattern = re.compile(r"frame pair cadence: (\d+) (\[.*\])$")
    ticks = []
    by_viewer = defaultdict(list)
    all_pairs, relevant_pairs = Counter(), Counter()
    for line in log.splitlines():
        match = pattern.search(line)
        if not match:
            pair_match = pair_pattern.search(line)
            if pair_match and t0 * 1e6 <= int(pair_match[1]) < t1 * 1e6:
                for ms, all_count, relevant_count in json.loads(pair_match[2].replace("(", "[").replace(")", "]")):
                    all_pairs[ms] += all_count
                    relevant_pairs[ms] += relevant_count
            continue
        start_us, budget = map(int, match.groups()[:2])
        if not t0 * 1e6 <= start_us < t1 * 1e6:
            continue
        # Rust's Debug representation of Vec<(u32, usize)>.
        frames = json.loads(match[3].replace("(", "[").replace(")", "]"))
        ticks.append([start_us, budget, sum(n for _, n in frames)])
        for viewer, n in frames:
            by_viewer[viewer].append([start_us, n])

    def percentiles(samples):
        samples = sorted(samples)
        return {f"p{p}": samples[min(len(samples) - 1, len(samples) * p // 100)]
                for p in (10, 50, 90, 95)} if samples else {}

    def pair_percentiles(counts):
        n = sum(counts.values())
        values = sorted(counts.items())
        result = {"samples": n, "counts_ms": dict(values)}
        for p in (50, 90, 95):
            index = n * p // 100
            for ms, count in values:
                if index < count:
                    result[f"p{p}"] = ms
                    break
                index -= count
        return result

    def intervals(frames):
        return [(b[0] - a[0]) / 1000 for a, b in zip(frames, frames[1:])]

    return {
        "columns": ["start_us", "budget", "frame_scene_rows"],
        "ticks": ticks,
        "pair_interval_ms": {"all_in_sight": pair_percentiles(all_pairs),
                             "engaged_or_near": pair_percentiles(relevant_pairs)},
        "rows_per_tick": percentiles(t[2] for t in ticks),
        "ticks_at_budget_min": sum(t[1] == 250 for t in ticks),
        "frame_interval_ms": percentiles(v for frames in by_viewer.values() for v in intervals(frames)),
        "viewers": {viewer: {"rows_per_s": sum(n for _, n in frames) / (t1 - t0),
                             "interval_ms": percentiles(intervals(frames)),
                             "frames": frames}
                    for viewer, frames in by_viewer.items()},
    }


GAUGES = ("spacetime_subscription_send_queue_length", "spacetime_total_outgoing_queue_length", "spacetime_worker_instance_operation_queue_length", "spacetime_total_incoming_queue_length")


def sample_gauges(ident, stop, rows):
    while not stop.wait(1.0):
        try:
            m = scrape(ident)
        except OSError:
            continue
        rows.append([round(time.time(), 2)] + [sum(v for k, v in m.items() if k.split("{")[0] == g) for g in GAUGES])


def main():
    import threading
    a = sys.argv[1:]
    probe = "--no-mind-probe" not in a
    a = [x for x in a if x not in ("--mind-probe", "--no-mind-probe")]
    sys.argv = sys.argv[:1] + a
    out = None
    for i, v in enumerate(a):
        if v == "--out":
            out = Path(a[i + 1])
    assert out, "--out is required"
    out.mkdir(parents=True, exist_ok=True)
    box = {}
    real_call = look_cost.call

    # look_cost turns profiling on and off with `set_profile`; the window is between the two.
    load_bin = a[a.index("--load") + 1]

    def call(db, reducer, args, token):
        if reducer == "set_profile" and args == [True]:
            ident = json.loads(look_cost.http(f"/v1/database/{db}")[1])["database_identity"]["__identity__"].removeprefix("0x")
            if probe:
                mp = look_cost.Proc([load_bin, "mind"], out / "mind.stderr")
                mp.send(json.dumps({"uri": look_cost.URL, "db": db, "token": token}))
                box["mind"] = mp
                box["mind_ready"] = mp.expect("ready", 300)
            real_call(db, reducer, args, token)
            box.update(ident=ident, pid=server_pid())
            box["stop"], box["gauges"] = threading.Event(), []
            threading.Thread(target=sample_gauges, args=(ident, box["stop"], box["gauges"]), daemon=True).start()
            if probe:
                box["mind"].send("go")
            box["m0"], box["c0"], box["p0"], box["t0"] = scrape(ident), thread_cpu(box["pid"]), proc_cpu(box["pid"]), time.time()
            return
        if reducer == "set_profile" and args == [False] and "m0" in box:
            box["m1"], box["c1"], box["p1"], box["t1"] = scrape(box["ident"]), thread_cpu(box["pid"]), proc_cpu(box["pid"]), time.time()
            box["stop"].set()
            if probe:
                box["mind"].send("stop")
                try:
                    box["mind_done"] = box["mind"].expect("done", 120)
                except RuntimeError as e:
                    box["mind_done"] = {"error": str(e)}
        real_call(db, reducer, args, token)

    look_cost.call = call
    try:
        look_cost.main()
    finally:
        if "stop" in box:
            box["stop"].set()
        mind = box.get("mind")
        if mind and mind.p.poll() is None:
            mind.p.terminate()
        if "m1" in box:
            dur = box["t1"] - box["t0"]
            diff = {k: box["m1"].get(k, 0.0) - box["m0"].get(k, 0.0) for k in sorted(set(box["m0"]) | set(box["m1"]))}
            (out / "metrics.json").write_text(json.dumps({"seconds": dur, "before": box["m0"], "after": box["m1"], "diff": {k: v for k, v in diff.items() if v}}, indent=1) + "\n")
            hz = os.sysconf("SC_CLK_TCK")
            by = {}
            for tid, (name, c1) in box["c1"].items():
                c0 = box["c0"].get(tid, (name, 0))[1]
                if c1 - c0:
                    by.setdefault(name, []).append(round((c1 - c0) / hz / dur * 1000, 1))
            (out / "threads.json").write_text(json.dumps({"seconds": dur, "process_cpu_ms_per_s": round((box["p1"] - box["p0"]) / hz / dur * 1000, 1),
                                                          "threads_cpu_ms_per_s": {k: sorted(v, reverse=True) for k, v in sorted(by.items())}}, indent=1) + "\n")
            (out / "gauges.json").write_text(json.dumps({"columns": ["t"] + list(GAUGES), "rows": box.get("gauges", [])}) + "\n")
            if probe:
                (out / "mind.json").write_text(json.dumps({"ready": box.get("mind_ready"), "done": box.get("mind_done")}, indent=1) + "\n")
            log = (out / "module.log").read_text() if (out / "module.log").exists() else ""
            (out / "frames.json").write_text(json.dumps(frame_cadence(log, box["t0"], box["t1"])) + "\n")
            (out / "ticks.json").write_text(json.dumps(ticks(log, box["t0"], box["t1"])) + "\n")


def proc_cpu(pid):
    f = open(f"/proc/{pid}/stat").read()
    f = f[f.rindex(")") + 2:].split()
    return int(f[11]) + int(f[12])


if __name__ == "__main__":
    main()
