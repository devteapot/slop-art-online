#!/usr/bin/env python3
"""E2 (branch attention-e2, docs/ATTENTION_E2_COST.md): one table from `battle_viewers.py --detail`
runs of the attention prototype.

    e2_report.py RUN_DIR... [--json OUT] [--ref ZERO_VIEWER_RUN_DIR...]
    e2_report.py --selftest

Each RUN_DIR is a `--out` of battle_viewers.py with one viewer count (`battle-viewers.json`,
`v<n>/metrics.json`, `v<n>/threads.json`, `v<n>/module.log`, optional `v<n>/rss.json` written by
the series driver). Runs are grouped into arms by their directory name less a trailing `-r<k>`.

Per run, over the measured window:
- ticks/s (`battle-viewers.json`), the database thread's CPU ms/s (`threads.json`, the
  `wasm-*` thread), the tick reducer's CPU ms/s (`spacetime_txn_cpu_time_sec_sum{reducer="tick"}`),
  ms of database thread per tick;
- per viewer and second: kB and rows sent to clients (`spacetime_num_bytes_sent_to_clients_total`,
  `spacetime_websocket_sent_num_rows_sum`);
- the scheduled reducers' queue wait (`spacetime_reducer_wait_time_sec`, mean and the p99 bucket);
- `seen_crowd` rows inserted and deleted a second (an update counts once in each);
- WASM memory at the end (`spacetime_worker_wasm_memory_bytes`), the service's VmRSS and VmHWM
  (`rss.json`: the whole server process, one world on it);
- from the module log's per-second `diag` lines inside the window: sweeps a second, attended per
  sweep (`sweep:seen`), in sight per sweep (`sweep:seen` + `attend:dropped`), promotions and
  demotions per viewer-second, crowd cells and crowd row writes per viewer-second.

Per arm: the mean of its runs (and their range). With `--ref` (0-viewer runs of the same build),
the delivery cost per viewer (ms/s) and per attended pair (µs/s) = (DB ms/s − ref) / (viewers ×
attended per sweep), as docs/COMBAT_PHASE.md's per-pair method. Across arms with the same viewer
count and crowd setting, the least-squares slope of DB ms/s against attended pairs is the marginal
cost of one attended individual (µs/s per pair).
"""
import argparse
import datetime
import json
import math
import os
import re
import statistics
import sys
import tempfile
from pathlib import Path


def metric_sum(diff, name, **labels):
    tot = 0.0
    for k, v in diff.items():
        if not k.startswith(name + "{") and k != name:
            continue
        if all(f'{lk}="{lv}"' in k for lk, lv in labels.items()):
            tot += v
    return tot


def bucket_p(diff, name, q, **labels):
    """The q quantile's upper bucket bound from a histogram's bucket differences."""
    rows = []
    for k, v in diff.items():
        if not k.startswith(name + "_bucket{"):
            continue
        if not all(f'{lk}="{lv}"' in k for lk, lv in labels.items()):
            continue
        m = re.search(r'le="([^"]+)"', k)
        if m:
            rows.append((math.inf if m.group(1) == "+Inf" else float(m.group(1)), v))
    rows.sort()
    if not rows or rows[-1][1] <= 0:
        return None
    total = rows[-1][1]
    for le, n in rows:
        if n >= q * total:
            return le
    return rows[-1][0]


def diag_window(log, t0, t1):
    """Mean per second of each diag counter over the lines stamped inside [t0, t1]."""
    sums, n = {}, 0
    for line in open(log, errors="replace"):
        if "diag: {" not in line:
            continue
        stamp = line.split(" ", 1)[0]
        try:
            ts = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if not (t0 <= ts <= t1):
            continue
        try:
            d = json.loads(line[line.index("diag: {") + 6:])
        except ValueError:
            continue
        n += 1
        for k, v in d.items():
            sums[k] = sums.get(k, 0) + v
    return {k: v / n for k, v in sums.items()} if n else {}, n


def visible_churn(log, t0, t1):
    """From the `attend-vis` lines (attend_vis_on): 10 s buckets lying wholly inside [t0, t1].
    Per viewer-minute, flip-backs within 2 s and within 5 s; the share of attended creatures
    affected (affected over attended, per bucket, mean); the worst viewer by flip-backs within
    5 s a minute."""
    per = {}
    for line in open(log, errors="replace"):
        i = line.find("attend-vis {")
        if i < 0:
            continue
        try:
            d = json.loads(line[i + 11:])
        except ValueError:
            continue
        lo, hi = d["bucket"] * 10, d["bucket"] * 10 + 10
        if lo < t0 or hi > t1:
            continue
        per.setdefault(d["viewer"], []).append(d)
    if not per:
        return None
    rates = {}
    shares = []
    for v, bs in per.items():
        mins = len(bs) * 10 / 60
        rates[v] = (sum(b["back2"] for b in bs) / mins, sum(b["back5"] for b in bs) / mins)
        shares += [b["affected"] / b["attended"] for b in bs if b["attended"]]
    worst = max(rates.items(), key=lambda kv: kv[1][1])
    return {"viewers": len(rates), "buckets": sum(len(b) for b in per.values()),
            "back2_per_viewer_min": round(statistics.mean(r[0] for r in rates.values()), 2),
            "back5_per_viewer_min": round(statistics.mean(r[1] for r in rates.values()), 2),
            "share_attended_affected": round(statistics.mean(shares), 4) if shares else None,
            "worst_viewer": {"viewer": worst[0], "back2_per_min": round(worst[1][0], 2), "back5_per_min": round(worst[1][1], 2)}}


def one(run):
    run = Path(run)
    bv = json.loads((run / "battle-viewers.json").read_text())
    row = bv["rows"][0]
    n = row["viewers"]
    v = run / f"v{n}"
    m = json.loads((v / "metrics.json").read_text())
    diff, after, secs = m["diff"], m["after"], m["seconds"]
    th = json.loads((v / "threads.json").read_text())
    db_ms = sum(sum(x) for k, x in th["threads_cpu_ms_per_s"].items() if k.startswith("wasm-"))
    ticks = row["ticks_per_s"]
    w = row.get("window", {})
    dg, lines = diag_window(v / "module.log", w.get("t0", 0), w.get("t1", 9e18)) if (v / "module.log").exists() else ({}, 0)
    sweeps = dg.get("sweep:viewers", 0)
    out = {
        "run": run.name, "viewers": n, "laws": bv.get("laws", []), "seconds": round(secs, 2),
        "ticks_per_s": ticks,
        "db_ms_s": round(db_ms, 2),
        "tick_ms_s": round(metric_sum(diff, "spacetime_txn_cpu_time_sec_sum", reducer="tick", txn_type="Reducer") / secs * 1000, 2),
        "db_ms_per_tick": round(db_ms / ticks, 3) if ticks else None,
        "sent_kB_s_per_viewer": round(metric_sum(diff, "spacetime_num_bytes_sent_to_clients_total") / secs / max(n, 1) / 1000, 2),
        "sent_rows_s_per_viewer": round(metric_sum(diff, "spacetime_websocket_sent_num_rows_sum") / secs / max(n, 1), 1),
        "wait_ms_mean": None, "wait_ms_p99": None,
        "crowd_ins_s": round(metric_sum(diff, "spacetime_num_rows_inserted_total", table_name="seen_crowd") / secs, 1),
        "crowd_del_s": round(metric_sum(diff, "spacetime_num_rows_deleted_total", table_name="seen_crowd") / secs, 1),
        "crowd_rows_end": metric_sum(after, "spacetime_num_table_rows", table_name="seen_crowd"),
        "wasm_mb": round(metric_sum(after, "spacetime_worker_wasm_memory_bytes") / 1e6, 1),
        "diag_seconds": lines,
        "sweeps_s": round(sweeps, 1),
        "attended_per_sweep": round(dg.get("sweep:seen", 0) / sweeps, 2) if sweeps else None,
        "in_sight_per_sweep": round((dg.get("sweep:seen", 0) + dg.get("attend:dropped", 0)) / sweeps, 2) if sweeps else None,
        "promoted_per_viewer_s": round(dg.get("attend:promoted", 0) / max(n, 1), 2),
        "demoted_per_viewer_s": round(dg.get("attend:demoted", 0) / max(n, 1), 2),
        "grace_per_viewer": round(dg.get("attend:grace", 0) / sweeps, 2) if sweeps else None,
        "crowd_cells_per_viewer_s": round(dg.get("crowd:cells", 0) / max(n, 1), 2),
        "crowd_writes_per_viewer_s": round((dg.get("crowd:insert", 0) + dg.get("crowd:update", 0) + dg.get("crowd:delete", 0)) / max(n, 1), 2),
        # The battle itself (a stalled fight measures delivery without combat): blows struck a second
        # (`fold:blow`: hit, blocked, dodged or missed), fighters fallen in the window (the keeper's
        # refills), and the share alive at the window's end (the keeper's census).
        "blows_s": round(dg.get("fold:blow", 0), 1),
        "fallen_window": (row.get("keeper_window") or {}).get("refills"),
        "alive_end_share": round(kw["alive_end"] / kw["target"], 3) if (kw := row.get("keeper_window")) and kw.get("target") else None,
    }
    wc = metric_sum(diff, "spacetime_reducer_wait_time_sec_count", reducer="scheduled reducer")
    if wc:
        out["wait_ms_mean"] = round(metric_sum(diff, "spacetime_reducer_wait_time_sec_sum", reducer="scheduled reducer") / wc * 1000, 3)
        p = bucket_p(diff, "spacetime_reducer_wait_time_sec", 0.99, reducer="scheduled reducer")
        out["wait_ms_p99"] = None if p is None else (p * 1000 if math.isfinite(p) else "inf")
    if (v / "ticks.json").exists():
        tj = json.loads((v / "ticks.json").read_text())
    if (v / "ticks.json").exists() and tj.get("body_ms"):  # L0 (--no-profile) runs log no tick bodies
        out["tick_body_p50_ms"], out["tick_body_p99_ms"] = tj["body_ms"].get("p50"), tj["body_ms"].get("p99")
        out["tick_over_16_7_pct"] = tj.get("body_over_16_7_ms_pct")
        gaps = tj.get("gap_slots", {})
        total = sum(gaps.values())
        out["missed_slot_ticks_pct"] = round(100 * sum(n for k, n in gaps.items() if int(k) > 1) / total, 2) if total else None
        flip = row.get("flip_law")
        if flip:
            cols = tj["columns"]
            si, bi, gi = cols.index("start_us"), cols.index("body_ms"), cols.index("slots_to_next")
            at = flip["at"] * 1e6

            def around(lo, hi):
                ts = [r for r in tj["rows"] if lo <= r[si] < hi]
                return {"ticks": len(ts), "body_max_ms": max((r[bi] for r in ts), default=None),
                        "body_sum_ms": round(sum(r[bi] for r in ts), 2), "missed_slots": sum(r[gi] - 1 for r in ts)}
            out["burst"] = {"law": f"{flip['law']}={flip['value']}", "before_1s": around(at - 1e6, at), "after_1s": around(at, at + 1e6)}
    if (v / "module.log").exists():
        vc = visible_churn(v / "module.log", w.get("t0", 0), w.get("t1", 9e18))
        if vc:
            out["visible_churn"] = vc
    if (v / "rss.json").exists():
        r = json.loads((v / "rss.json").read_text())
        out["rss_mb"], out["hwm_mb"] = round(r.get("VmRSS", 0) / 1e6, 1), round(r.get("VmHWM", 0) / 1e6, 1)
    return out


def arm_of(name):
    return re.sub(r"-r\d+$", "", name)


def summarize(runs, refs):
    ref = statistics.mean(r["db_ms_s"] for r in refs) if refs else None
    arms = {}
    for r in runs:
        arms.setdefault(arm_of(r["run"]), []).append(r)
    table = []
    for name, rs in arms.items():
        row = {"arm": name, "runs": len(rs), "viewers": rs[0]["viewers"], "laws": rs[0]["laws"]}
        for k in ("ticks_per_s", "db_ms_s", "tick_ms_s", "db_ms_per_tick", "sent_kB_s_per_viewer", "sent_rows_s_per_viewer",
                  "wait_ms_mean", "crowd_ins_s", "crowd_del_s", "wasm_mb", "rss_mb", "attended_per_sweep", "in_sight_per_sweep",
                  "promoted_per_viewer_s", "demoted_per_viewer_s", "grace_per_viewer", "crowd_cells_per_viewer_s", "crowd_writes_per_viewer_s"):
            vals = [r[k] for r in rs if isinstance(r.get(k), (int, float))]
            if vals:
                row[k] = round(statistics.mean(vals), 3)
                row[k + "_range"] = [min(vals), max(vals)]
        if ref is not None and row.get("attended_per_sweep"):
            pairs = row["viewers"] * row["attended_per_sweep"]
            row["per_viewer_ms_s"] = round((row["db_ms_s"] - ref) / row["viewers"], 3)
            row["per_attended_pair_us_s"] = round((row["db_ms_s"] - ref) / pairs * 1000, 2)
        table.append(row)
    # The marginal attended pair: slope of DB ms/s against pairs across arms of one viewer count.
    slopes = {}
    by_v = {}
    for row in table:
        if row.get("attended_per_sweep"):
            by_v.setdefault(row["viewers"], []).append((row["viewers"] * row["attended_per_sweep"], row["db_ms_s"]))
    for v, pts in by_v.items():
        if len(pts) >= 2:
            mx, my = statistics.mean(p[0] for p in pts), statistics.mean(p[1] for p in pts)
            sxx = sum((p[0] - mx) ** 2 for p in pts)
            if sxx > 0:
                slopes[v] = round(sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx * 1000, 2)
    return {"ref_db_ms_s": ref, "arms": table, "marginal_us_s_per_attended_pair": slopes}


def selftest():
    """Known answers: two synthetic runs of one arm and one 0-viewer reference."""
    fails = []

    def expect(name, ok, got=""):
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f" ({got})"))
        if not ok:
            fails.append(name)

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)

        def make(name, n, db_ms, ticks, seen, dropped, sent_b, rows, crowd_ins):
            r = d / name
            (r / f"v{n}").mkdir(parents=True)
            t0 = 1_700_000_000.0
            (r / "battle-viewers.json").write_text(json.dumps({"laws": ["attend_n=16"], "rows": [{"viewers": n, "ticks_per_s": ticks, "window": {"t0": t0, "t1": t0 + 10},
                                                                                              "keeper_window": {"target": 200, "alive_end": 190, "refills": 37}}]}))
            secs = 10.0
            diff = {
                'spacetime_txn_cpu_time_sec_sum{db="x",reducer="tick",txn_type="Reducer"}': 3.0,
                'spacetime_txn_cpu_time_sec_sum{db="x",reducer="tick",txn_type="Update"}': 0.5,
                'spacetime_num_bytes_sent_to_clients_total{db="x",txn_type="Update"}': sent_b,
                'spacetime_websocket_sent_num_rows_sum{db="x"}': rows,
                'spacetime_reducer_wait_time_sec_sum{db="x",reducer="scheduled reducer"}': 0.2,
                'spacetime_reducer_wait_time_sec_count{db="x",reducer="scheduled reducer"}': 100.0,
                'spacetime_reducer_wait_time_sec_bucket{db="x",reducer="scheduled reducer",le="0.001"}': 50.0,
                'spacetime_reducer_wait_time_sec_bucket{db="x",reducer="scheduled reducer",le="0.01"}': 98.0,
                'spacetime_reducer_wait_time_sec_bucket{db="x",reducer="scheduled reducer",le="0.1"}': 100.0,
                'spacetime_reducer_wait_time_sec_bucket{db="x",reducer="scheduled reducer",le="+Inf"}': 100.0,
                'spacetime_num_rows_inserted_total{db="x",reducer_or_query="tick",table_id="1",table_name="seen_crowd"}': crowd_ins,
            }
            after = {'spacetime_worker_wasm_memory_bytes{db="x"}': 200e6, 'spacetime_num_table_rows{db="x",table_id="1",table_name="seen_crowd"}': 40.0}
            (r / f"v{n}" / "metrics.json").write_text(json.dumps({"seconds": secs, "diff": diff, "after": after}))
            (r / f"v{n}" / "threads.json").write_text(json.dumps({"threads_cpu_ms_per_s": {"wasm-abc": [db_ms], "tokio-runtime-w": [10.0]}}))
            lines = []
            for i in range(12):  # 10 inside the window, 2 outside
                ts = datetime.datetime.fromtimestamp(t0 - 5 if i == 0 else t0 + 15 if i == 11 else t0 + i - 0.5, datetime.timezone.utc)
                inside = i not in (0, 11)
                dg = {"fold:blow": 12, "sweep:viewers": 80, "sweep:seen": seen * 80, "attend:dropped": dropped * 80, "attend:promoted": 8,
                      "attend:demoted": 8, "crowd:cells": 160, "crowd:insert": 4, "crowd:update": 12, "crowd:delete": 4} if inside else {"sweep:viewers": 999999}
                lines.append(f"{ts.isoformat().replace('+00:00', 'Z')}  INFO: housekeeping x: diag: {json.dumps(dg)}")
            if name == "n16-r1":
                # Viewer 7: three buckets inside the window... the window is 10 s here, so one bucket
                # [t0, t0+10) fits; one bucket outside. Viewer 8 likewise, with fewer flips.
                b0 = int(t0 // 10)
                lines.append(f"2023-11-14T22:13:21Z  INFO: x: attend-vis {json.dumps({'viewer': 7, 'bucket': b0, 'flips': 20, 'back2': 3, 'back5': 6, 'affected': 4, 'attended': 20})}")
                lines.append(f"2023-11-14T22:13:21Z  INFO: x: attend-vis {json.dumps({'viewer': 8, 'bucket': b0, 'flips': 5, 'back2': 1, 'back5': 2, 'affected': 1, 'attended': 10})}")
                lines.append(f"2023-11-14T22:13:21Z  INFO: x: attend-vis {json.dumps({'viewer': 7, 'bucket': b0 + 1, 'flips': 99, 'back2': 99, 'back5': 99, 'affected': 9, 'attended': 9})}")
            (r / f"v{n}" / "module.log").write_text("\n".join(lines) + "\n")
            (r / f"v{n}" / "rss.json").write_text(json.dumps({"VmRSS": 1.5e9, "VmHWM": 2.0e9}))
            if name.startswith("burst"):
                bv = json.loads((r / "battle-viewers.json").read_text())
                bv["rows"][0]["flip_law"] = {"law": "attend_burst_cap", "value": "6", "at": t0 + 5}
                (r / "battle-viewers.json").write_text(json.dumps(bv))
                rows = []
                for k in range(600):  # 60 ticks a second over the window; a 40 ms tick right after the flip, two slots missed
                    st = (t0 + k / 60) * 1e6
                    body = 40.0 if k == 300 else 5.0
                    rows.append([st, st + body * 1000, 0.5, body, 3 if k == 300 else 1])
                (r / f"v{n}" / "ticks.json").write_text(json.dumps({"columns": ["start_us", "end_us", "grid_offset_ms", "body_ms", "slots_to_next"], "rows": rows,
                                                                  "body_ms": {"p50": 5.0, "p99": 5.0}, "body_over_16_7_ms_pct": 0.17, "gap_slots": {"1": 599, "3": 1}}))
            return r

        a1 = make("n16-r1", 16, 400.0, 60.0, 16, 70, 4_000_000, 160_000, 300)
        a2 = make("n16-r2", 16, 420.0, 59.0, 16, 70, 4_000_000, 160_000, 300)
        b1 = make("n32-r1", 16, 480.0, 58.0, 32, 54, 6_000_000, 240_000, 300)
        z = make("zero-r1", 0, 230.0, 60.0, 0, 0, 0, 0, 0)
        bu = one(make("burst-r1", 16, 400.0, 60.0, 16, 70, 4_000_000, 160_000, 300))
        expect("burst: the second after the flip against the second before",
               bu["burst"]["after_1s"] == {"ticks": 60, "body_max_ms": 40.0, "body_sum_ms": 335.0, "missed_slots": 2}
               and bu["burst"]["before_1s"]["body_max_ms"] == 5.0 and bu["burst"]["before_1s"]["missed_slots"] == 0, bu.get("burst"))
        expect("tick body and missed slots", bu["tick_body_p99_ms"] == 5.0 and bu["missed_slot_ticks_pct"] == 0.17, bu)
        r1 = one(a1)
        expect("DB ms/s from the wasm thread", r1["db_ms_s"] == 400.0, r1["db_ms_s"])
        expect("tick ms/s from the tick reducer's CPU", r1["tick_ms_s"] == 300.0, r1["tick_ms_s"])
        expect("ms per tick", r1["db_ms_per_tick"] == round(400 / 60, 3), r1["db_ms_per_tick"])
        expect("kB sent per viewer-second", r1["sent_kB_s_per_viewer"] == 25.0, r1["sent_kB_s_per_viewer"])
        expect("rows sent per viewer-second", r1["sent_rows_s_per_viewer"] == 1000.0, r1["sent_rows_s_per_viewer"])
        expect("queue wait mean and p99 bucket", r1["wait_ms_mean"] == 2.0 and r1["wait_ms_p99"] == 100.0, (r1["wait_ms_mean"], r1["wait_ms_p99"]))
        expect("crowd inserts a second", r1["crowd_ins_s"] == 30.0, r1["crowd_ins_s"])
        expect("only diag lines inside the window", r1["diag_seconds"] == 10 and r1["sweeps_s"] == 80.0, (r1["diag_seconds"], r1["sweeps_s"]))
        expect("attended and in sight per sweep", r1["attended_per_sweep"] == 16.0 and r1["in_sight_per_sweep"] == 86.0, (r1["attended_per_sweep"], r1["in_sight_per_sweep"]))
        expect("churn and crowd writes per viewer-second", r1["promoted_per_viewer_s"] == 0.5 and r1["crowd_writes_per_viewer_s"] == 1.25 and r1["crowd_cells_per_viewer_s"] == 10.0, r1)
        vc = r1.get("visible_churn") or {}
        expect("visible churn: buckets inside the window only, per viewer-minute, share, worst viewer",
               vc.get("buckets") == 2 and vc.get("back2_per_viewer_min") == 12.0 and vc.get("back5_per_viewer_min") == 24.0
               and vc.get("share_attended_affected") == 0.15 and vc.get("worst_viewer") == {"viewer": 7, "back2_per_min": 18.0, "back5_per_min": 36.0}, vc)
        expect("the battle: blows a second, fallen in the window, alive at its end",
               r1["blows_s"] == 12.0 and r1["fallen_window"] == 37 and r1["alive_end_share"] == 0.95, (r1["blows_s"], r1["fallen_window"], r1["alive_end_share"]))
        expect("WASM memory and RSS", r1["wasm_mb"] == 200.0 and r1["rss_mb"] == 1500.0 and r1["hwm_mb"] == 2000.0, r1)
        s = summarize([r1, one(a2), one(b1)], [one(z)])
        arm = {a["arm"]: a for a in s["arms"]}
        expect("arms group runs by name less -r<k>", set(arm) == {"n16", "n32"} and arm["n16"]["runs"] == 2, list(arm))
        expect("arm mean", arm["n16"]["db_ms_s"] == 410.0 and arm["n16"]["db_ms_s_range"] == [400.0, 420.0], arm["n16"])
        expect("per viewer and per attended pair against the 0-viewer reference",
               arm["n16"]["per_viewer_ms_s"] == round(180 / 16, 3) and arm["n16"]["per_attended_pair_us_s"] == round(180 / 256 * 1000, 2), arm["n16"])
        # slope: (480 - 410) / (512 - 256) pairs -> 0.2734 ms/s per pair = 273.44 us/s
        expect("marginal cost of an attended pair (slope across N)", s["marginal_us_s_per_attended_pair"] == {16: round(70 / 256 * 1000, 2)}, s["marginal_us_s_per_attended_pair"])
    print("e2_report selftest:", "all passed" if not fails else f"{len(fails)} failed")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs", nargs="*")
    ap.add_argument("--ref", nargs="*", default=[])
    ap.add_argument("--json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    s = summarize([one(r) for r in a.runs], [one(r) for r in a.ref])
    if a.json:
        Path(a.json).write_text(json.dumps(s, indent=1) + "\n")
    cols = ["arm", "runs", "viewers", "ticks_per_s", "db_ms_s", "db_ms_per_tick", "per_viewer_ms_s", "per_attended_pair_us_s", "attended_per_sweep",
            "in_sight_per_sweep", "sent_kB_s_per_viewer", "sent_rows_s_per_viewer", "wait_ms_mean", "promoted_per_viewer_s", "crowd_writes_per_viewer_s", "wasm_mb", "rss_mb"]
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for row in s["arms"]:
        print("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
    print(f"ref DB ms/s: {s['ref_db_ms_s']}; marginal µs/s per attended pair by viewers: {s['marginal_us_s_per_attended_pair']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
